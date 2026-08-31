"""app/schedule/onboarding.py — 票 S2「開帳讀歷史」：讀一個廣告帳戶過去在 Meta 上投過什麼、
什麼奏效過，逐活動（campaign）各跑一個分析師，交人手動勾選要不要把結論存進品牌的學習帳本。

Private to app/schedule/（集裝箱憲章第一節）：只有 app/schedule/onboarding_routes.py（HTTP
層）與 app/schedule/jobs.py（掛 procrastinate task）import 這裡的東西。

**刻意不 import app/schedule/routes.py**（S2-DESIGN.md D1）：jobs.py 已經 import 了
routes.py，這個模組留乾淨，環的機率永遠是零，不必事後靠測試證明。跟 routes.py 重複的兩個
常數（`ALREADY_RUNNING_MESSAGE`／`_already_running_error()`）因此各自留一份——兩行字串沒有
共用一個新模組的價值。

跟 app/schedule/routes.py 的三個既有生成端點（schedule_plan／schedule_tree／
schedule_creative）不同的地方：那三個是「validate → enqueue → 全部工作丟給 worker」，這裡
的「列出這個帳號有哪些活動、算好整個讀取的既定事實（D6）」是在 HTTP 請求裡同步做完的
（S2-DESIGN.md D3 第 1-4 步）——這兩步都是快速的 DB／單次 Graph 呼叫，真正花錢、花時間的
逐活動分析（列 adset／ad、抓素材、打代理）留在 `onboarding_read()`（procrastinate task
body，一個活動一份工），所以本檔同時擁有「dispatch 用的驗證＋列活動＋enqueue」與「真正執行
的 task body」，不像三個既有生成器分別落在 routes.py／jobs.py 兩邊。

ADR 0042（修正版，見 docs/adr/0042-work-the-user-waits-for-runs-on-the-queue.md「Amended
2026-08-30」）：這裡的鎖字面值是 `onboarding_read:{account_external_id}:{campaign_id}`——
工作項是「這個活動」，不是「這個品牌」，所以同一次讀取底下的所有活動真的會平行跑，不會
互相 409。

Fan-in（S2-DESIGN.md D3）：一支 SQL 查這個讀取（read）底下所有 `llm_task` 列
（`context_scope_json->>'onboarding_read_id'`），Python 裡拿 `count(status='succeeded')`
跟 `len(expected_jobs)` 比——沒有第二張表、沒有佇列原生的 join table。

絕不對 learning_ledger 這張表自己下 SQL（票 S2 §4）：入帳一律經
`app.brand_intelligence.repository.create_learning_ledger_entry`，這是
CrossLayerRawSqlScanTest（app/tests/test_architecture_boundaries.py）逐字掃描原始碼文字
（含註解）抓到的鐵則，本檔任何地方都不會出現「FROM／INTO／UPDATE／JOIN」後面緊接那張表
名稱的字樣。
"""

from datetime import date, timedelta

import app.shared.web as web
from app.background import enqueue as background_enqueue
from app.brand_intelligence import repository as bi_repo
from app.core.db import APP_DIR, connection, new_id
from app.llm import context_compiler, gateway, methodology, providers
from app.meta import graph
from app.meta import repository as meta_repo
from app.schedule import onboarding_slice
from app.schedule.plan import _extract_last_json_block

TASK_TYPE = "onboarding_read"
DEPARTMENT_FILE = APP_DIR / "departments" / "ads" / "onboarding_read.md"
# 對照既有 app/methodology/README.md 的列名（票 S2 D8）：這一列本來就存在、本來零呼叫者，
# 不是為了這張票新開一列（維護規則「只按消費拉動萃取」，同 routes.py METHODOLOGY_TASK_LABELS
# 的說明）。
METHODOLOGY_TASK_LABELS = ["成效判讀／下期草案"]

# 唯一的供應商實例：這支 task body 是本模組真的打代理的地方，比照 app/schedule/jobs.py
# 既有的 PROVIDER 寫法——測試用 `mock.patch.object(onboarding, "PROVIDER", FakeProvider(...))`
# 換掉。
PROVIDER = providers.AnthropicProvider()

NO_META_ACCOUNT_MESSAGE = "這個品牌還沒有綁定 Meta 廣告帳戶，請先到「Meta 廣告帳戶」頁綁定。"
NO_SPEND_DATA_MESSAGE = (
    "這個帳戶還沒有拉過任何成效資料，先跑 "
    "`uv run python -m app.meta.daily_pull --since YYYY-MM-DD`"
)
# 三支端點共用同一個 code／message，比照 routes.py 既有的 ALREADY_RUNNING_MESSAGE——
# 不從那邊 import（本檔頭已說明為什麼不 import routes.py），兩行字串各留一份。
ALREADY_RUNNING_MESSAGE = "上一次還在跑，請等它跑完再按。"
NO_READING_MESSAGE = "找不到這筆判讀。"
NO_REPLY_MESSAGE = "讀取失敗，請重新讀一次這個活動。"
NO_CONCLUSIONS_MESSAGE = "代理沒有回傳看得懂的結論，請重新讀一次這個活動。"
INDEX_OUT_OF_RANGE_MESSAGE = "找不到這個結論編號，請重新整理頁面。"
SCOPE_NOT_ACCEPTABLE_MESSAGE = "這條結論的適用範圍不是品牌，也不是這個品牌的產品，不能勾選採用。"

# D6 的兩句話，字面值固定：「窗口讀＝實際存在的範圍」與「這是 Meta 現在還回得來的，不是
# 全部」都不是可以調的文案，是這份任務誠實與否的界線。
COVERAGE_NOTE = "這幾天完全沒有資料——可能那天沒有投遞，也可能從來沒有拉過，我們分不出來。"
CAMPAIGNS_NOTE = (
    "以下是 Meta 現在還回得來的活動，不是你投過的全部——已經刪除的活動 Meta 不讓我們列出來"
    "（2026-08-31 對真帳號實測，見 app/meta/graph.py 的 _HISTORICAL_STATUSES），封存的則讀得到。"
)


def _already_running_error() -> web.ApiError:
    return web.ApiError(409, "already_running", ALREADY_RUNNING_MESSAGE)


# ---------------------------------------------------------------------------
# 綁定帳號、既定事實（D6）——GET 與 dispatch（POST 建立讀取）共用
# ---------------------------------------------------------------------------

def _bound_accounts(conn, org_id: str, brand_id: str) -> list[dict]:
    """這個品牌綁定的 Meta 帳號，回傳 API 要的三個欄位——`account_id` 是打 Graph API 要用的
    那個純數字外部 id，`id` 是我們自己的 `mad_...`（enqueue 時要釘住是哪一列帳號）。"""
    accounts = []
    for account_id in meta_repo.bound_account_ids_for_brand(conn, org_id, brand_id):
        account = meta_repo.get_account(conn, org_id, account_id)
        if account is not None:
            accounts.append(
                {"id": account["id"], "account_id": account["account_id"], "name": account["name"]}
            )
    return accounts


def _compute_frozen_facts(conn, org_id: str, account_ids: list) -> dict | None:
    """D6：整個讀取只算一次，逐活動的 job 拿到的是完全一樣的一份（context_scope_json
    裡的 `frozen_facts`）。窗口＝這批帳號實際拉回來的 min／max spend_date，沒有任何預設
    回看天數——S1 已經定案這件事沒辦法放進品牌層規則卡（一個帳號可能服務好幾個品牌）。

    一列資料都沒有（`spend_date_bounds` 回 `(None, None)`）時回傳 None，呼叫端據此判斷
    「這個帳戶還沒拉過資料」，不是「這段窗口剛好是空的」——兩者是不同的錯誤訊息。"""
    since, until = meta_repo.spend_date_bounds(conn, org_id, account_ids)
    if since is None or until is None:
        return None
    windows = meta_repo.attribution_windows_in_range(conn, org_id, account_ids, since, until)
    have_data = set(meta_repo.spend_dates_with_data(conn, org_id, account_ids, since, until))
    total_days = (until - since).days + 1
    days_without_data = [
        day.isoformat()
        for day in (since + timedelta(days=i) for i in range(total_days))
        if day not in have_data
    ]
    return {
        "since": since.isoformat(),
        "until": until.isoformat(),
        "attribution_windows": windows,
        "days_without_data": days_without_data,
    }


def _frozen_facts_text(frozen_facts: dict) -> str:
    """D6／D8 segment [3]：把 `_compute_frozen_facts` 的結果轉成給模型讀的一段文字——
    純轉換，不重新計算任何東西。"""
    windows = frozen_facts["attribution_windows"]
    days_without_data = frozen_facts["days_without_data"]
    lines = [
        "## 這次讀取的既定事實",
        f"讀到的時間窗：{frozen_facts['since']} 到 {frozen_facts['until']}"
        "（這是實際拉回來的範圍，不是設定過的回看天數）。",
        "用的歸因窗：" + ("、".join(windows) if windows else "（這段窗口沒有任何一天有資料）"),
    ]
    if len(windows) > 1:
        lines.append(
            "這段範圍裡送出過不只一種歸因窗——用不同窗量出來的 ROAS 不能直接放在一起比。"
        )
    if days_without_data:
        lines.append("完全沒有資料的日子：" + "、".join(days_without_data))
        lines.append(COVERAGE_NOTE)
    lines.append(CAMPAIGNS_NOTE)
    # 被篩掉的活動也要讓模型知道——它在判斷「這個帳號整體偏好什麼」時，該知道自己看到的
    # 是一個子集合，不是全部（票 S2 §1／§5：沒讀到的東西要講出來，不是當作不存在）。
    skipped = frozen_facts.get("campaigns_without_numbers") or []
    if skipped:
        names = "、".join(f"{s['name']}（{s['campaign_id']}）" for s in skipped)
        lines.append(
            f"另外有 {len(skipped)} 個活動 Meta 還列得出來，但我們手上這段期間一列數字都沒有，"
            f"所以沒有派人讀：{names}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 建立一次讀取（HTTP 請求裡同步做完；只有真正打代理的部分留給 worker）
# ---------------------------------------------------------------------------

def _newest_read_id(conn, brand_id: str) -> str | None:
    row = conn.execute(
        "SELECT context_scope_json->>'onboarding_read_id' AS read_id FROM llm_task"
        " WHERE brand_id = %s AND task_type = %s ORDER BY started_at DESC LIMIT 1",
        (brand_id, TASK_TYPE),
    ).fetchone()
    return row["read_id"] if row is not None else None


def _read_rows(conn, brand_id: str, read_id: str) -> list[dict]:
    """D3 的 fan-in：一支 SQL 撈出這個讀取（read）底下全部的分析師列，依 started_at 排序——
    「要顯示哪一次讀取」＝這個品牌最新的 read_id（`_newest_read_id`），不是逐列
    started_at 最新——ADR 0042 修正版的重點正是「用工作項自己找列，不是用『最新』找列」，
    這裡的工作項是整個讀取，讀取底下每一列再各自用它自己的活動 id 找（見 `_job_response`）。

    ponytail：一個 job 如果在 `gateway.run_task()` 真的寫進第一列之前就死掉
    （例如 Graph API 認證掛了、`connection()` 借不到連線），這裡永遠少一列，
    `count(succeeded)` 永遠追不上 `len(expected_jobs)`——使用者看到的會是「還沒完成」，
    直到他自己對著那一個活動重新按一次。procrastinate 沒有對應的佇列原生機制能填這個洞
    （SPEC §8），這個代價是設計裡明講接受的。"""
    return list(conn.execute(
        "SELECT id, status, error, started_at, rendered_output, context_scope_json"
        " FROM llm_task WHERE brand_id = %s AND task_type = %s"
        "   AND context_scope_json->>'onboarding_read_id' = %s"
        " ORDER BY started_at",
        (brand_id, TASK_TYPE, read_id),
    ))


def _latest_read_rows(conn, brand_id: str) -> list[dict]:
    read_id = _newest_read_id(conn, brand_id)
    return [] if read_id is None else _read_rows(conn, brand_id, read_id)


def _latest_read_running(conn, brand_id: str) -> bool:
    """這個品牌最新一次讀取裡，有沒有任何一個活動的分析師還在跑——按第二次「開始讀」的
    409 判斷依據。不是『全部完成才准開新的一次』（那樣一個活動失敗就永遠卡住整個品牌），
    只擋『真的還在跑』這個窗口，跟 `app/schedule/routes.py` 既有 `_display_task_row` 的
    running 檢查同一種精神。"""
    return any(row["status"] == "running" for row in _latest_read_rows(conn, brand_id))


def start_onboarding_read(conn, brand_id: str, org_id: str) -> dict:
    """POST .../onboarding-read：驗證（D13 的三個 400／一個 502）＋列出這個品牌所有綁定
    帳號目前在 Meta 上的活動（含 ARCHIVED；DELETED 要不到，實測見 `graph._HISTORICAL_STATUSES`）
    ＋算好整個讀取共用的既定事實＋逐活動
    enqueue 一個分析師 job。次序照 `app/schedule/routes.py` 既有的「先驗證、後花錢」慣例：
    `gateway.check_spend_cap()` 與「上一次還在跑」檢查都排在列活動、enqueue 之前。"""
    accounts = _bound_accounts(conn, org_id, brand_id)
    if not accounts:
        raise web.ApiError(400, "no_meta_account", NO_META_ACCOUNT_MESSAGE)
    account_ids = [a["id"] for a in accounts]

    frozen_facts = _compute_frozen_facts(conn, org_id, account_ids)
    if frozen_facts is None:
        raise web.ApiError(400, "no_spend_data", NO_SPEND_DATA_MESSAGE)

    token = meta_repo.get_token(conn, org_id)
    if token is None:
        raise web.ApiError(400, "no_meta_account", NO_META_ACCOUNT_MESSAGE)

    gateway.check_spend_cap(conn, org_id=org_id)
    if _latest_read_running(conn, brand_id):
        raise _already_running_error()

    # 只派給「這段期間手上真的有數字」的活動。2026-08-31 實機驗收量到：這個真帳號 Meta
    # 列得出 58 個活動，其中只有 24 個有成效列——另外 34 個派過去只會拿到一份空 CSV，
    # 白花 34 次代理呼叫，還生出 34 條無中生有的結論等人一條一條拒絕。被篩掉的**報出來**
    # （`campaigns_without_numbers` 進既定事實，畫面與提示詞都看得到），不是靜靜消失：
    # 票 S2 §1 的「Missing entities are reported, never inferred」講的就是這件事。
    since = date.fromisoformat(frozen_facts["since"])
    until = date.fromisoformat(frozen_facts["until"])
    with_rows = meta_repo.campaign_ids_with_rows(conn, org_id, account_ids, since, until)

    jobs_to_enqueue = []
    skipped = []
    for account in accounts:
        try:
            campaigns = graph.list_entities(token, account["account_id"], "campaign")
        except graph.GraphError as exc:
            raise web.ApiError(502, "meta_unreachable", f"連不上 Meta：{exc.message}") from exc
        for campaign in campaigns:
            if campaign["id"] in with_rows:
                jobs_to_enqueue.append((account, campaign))
            else:
                skipped.append({"campaign_id": campaign["id"], "name": campaign.get("name", "")})
    if not jobs_to_enqueue:
        # 帳號有花費紀錄，但 Meta 現在列得出來的活動沒有一個對得上那些數字——沒有第三個錯誤
        # 代碼（D13 只點名三個 400／一個 502），沿用 no_spend_data：對使用者來說一樣是
        # 「現在讀不出東西」。
        raise web.ApiError(400, "no_spend_data", NO_SPEND_DATA_MESSAGE)
    frozen_facts = {**frozen_facts, "campaigns_without_numbers": skipped}

    read_id = new_id("onb")
    expected_jobs = [
        f"{account['account_id']}:{campaign['id']}" for account, campaign in jobs_to_enqueue
    ]
    for account, campaign in jobs_to_enqueue:
        if not background_enqueue(
            f"background.{TASK_TYPE}", org_id=org_id,
            lock=f"{TASK_TYPE}:{account['account_id']}:{campaign['id']}",
            brand_id=brand_id, read_id=read_id, ad_account_id=account["id"],
            account_external_id=account["account_id"], campaign_id=campaign["id"],
            campaign_name=campaign.get("name", ""),
            campaign_effective_status=campaign.get("effective_status", ""),
            expected_jobs=expected_jobs, frozen_facts=frozen_facts,
        ):
            # 正常流程走不到這裡（上面已經檢查過『最新一次讀取』沒有在跑的列）；真的撞到
            # 代表這個活動自己的鎖被別處佔用（例如重新讀取單一活動的機制在別的地方同時按
            # 下），這一次讀取因此半途而廢——跟上面 `_read_rows` 的 ponytail 同一類已接受
            # 的殘餘風險，不為了這個邊界情境做整批 enqueue 的復原。
            raise _already_running_error()
    return brand_response(conn, brand_id, org_id)


# ---------------------------------------------------------------------------
# 讀出目前狀態（GET，以及 POST 之後回同一個形狀）
# ---------------------------------------------------------------------------

def brand_response(conn, brand_id: str, org_id: str) -> dict:
    rows = _latest_read_rows(conn, brand_id)
    return {
        "bound_accounts": _bound_accounts(conn, org_id, brand_id),
        "read": _read_response(conn, brand_id, rows) if rows else None,
    }


def _read_response(conn, brand_id: str, rows: list[dict]) -> dict:
    scope = rows[0].get("context_scope_json") or {}
    expected_jobs = scope.get("expected_jobs") or []
    frozen_facts = scope.get("frozen_facts") or {}
    succeeded = sum(1 for row in rows if row["status"] == "succeeded")
    since, until = frozen_facts.get("since"), frozen_facts.get("until")
    return {
        "read_id": scope.get("onboarding_read_id"),
        "started_at": rows[0]["started_at"],
        "window": {"since": since, "until": until} if since and until else None,
        "attribution_windows": frozen_facts.get("attribution_windows") or [],
        "days_without_data": frozen_facts.get("days_without_data") or [],
        "coverage_note": COVERAGE_NOTE,
        "campaigns_note": CAMPAIGNS_NOTE,
        # 這段期間一列數字都沒有、因此沒有派人讀的活動——要出現在畫面上，不是靜靜少掉
        # （票 S2 §1／§5）。空清單就是「每一個列得出來的活動都讀了」。
        "campaigns_without_numbers": frozen_facts.get("campaigns_without_numbers") or [],
        "expected": len(expected_jobs),
        "succeeded": succeeded,
        "finished": succeeded == len(expected_jobs),
        "jobs": [_job_response(conn, brand_id, row) for row in rows],
    }


def _parse_conclusions(rendered_output: str) -> tuple[list[dict], str | None]:
    """回覆最後一個 fenced json block → (conclusions, failure)（D9）。重用
    `app.schedule.plan._extract_last_json_block`——`tree.py`／`creative.py` 已經是這樣
    引用，不重寫第二個解析器；不用 `gateway.parse_json_reply()`，那支解的是『第一個』
    JSON 值，不是『最後一個』fenced block，形狀不合。

    任何一條結論格式不對，整批失敗——沿用 `plan.py`／`tree.py`／`creative.py` 既有的
    『整批失敗』慣例，不挑好的留、壞的丟。"""
    data = _extract_last_json_block(rendered_output)
    if data is None:
        return [], NO_CONCLUSIONS_MESSAGE
    raw = data.get("conclusions")
    if not isinstance(raw, list) or not raw:
        return [], NO_CONCLUSIONS_MESSAGE

    conclusions = []
    for item in raw:
        if not isinstance(item, dict):
            return [], NO_CONCLUSIONS_MESSAGE
        text, scope_value = item.get("text"), item.get("scope")
        text_ok = isinstance(text, str) and text
        scope_ok = isinstance(scope_value, str) and scope_value
        if not text_ok or not scope_ok:
            return [], NO_CONCLUSIONS_MESSAGE
        conclusions.append({
            "text": text, "scope": scope_value,
            "confidence": str(item.get("confidence") or ""),
            "evidence": str(item.get("evidence") or ""),
            "sample_note": str(item.get("sample_note") or ""),
        })
    return conclusions, None


def _conclusions_response(conn, brand_id: str, task_id: str, conclusions: list[dict]) -> list[dict]:
    """D9：`scope` 不是 `"brand"` 也不是這個品牌真的存在的產品，就標 `acceptable: false`
    並附上原因——絕不猜成 `"brand"`（那正是這一層不准做的判斷）。`accepted` 讀
    `list_learning_ledger_by_source_reading`：同一個 `task_id`＋逐字相同的 `learning_text`
    才算已經接受過（ADR 0044，精準比對，不正規化）。"""
    if not conclusions:
        return []
    product_names = {p["id"]: p["name"] for p in bi_repo.list_products(conn, brand_id)}
    accepted_texts = {
        row["learning_text"]
        for row in bi_repo.list_learning_ledger_by_source_reading(
            conn, brand_id, source_reading_id=task_id
        )
    }
    out = []
    for index, item in enumerate(conclusions):
        scope_value = item["scope"]
        acceptable = scope_value == "brand" or scope_value in product_names
        scope_label = (
            "整個品牌" if scope_value == "brand" else product_names.get(scope_value, scope_value)
        )
        entry = {
            "index": index, "text": item["text"], "scope": scope_value,
            "scope_label": scope_label,
            "confidence": item["confidence"], "evidence": item["evidence"],
            "sample_note": item["sample_note"],
            "acceptable": acceptable, "accepted": item["text"] in accepted_texts,
        }
        if not acceptable:
            entry["scope_note"] = SCOPE_NOT_ACCEPTABLE_MESSAGE
        out.append(entry)
    return out


def _job_response(conn, brand_id: str, row: dict) -> dict:
    scope = row.get("context_scope_json") or {}
    running = row["status"] == "running"
    conclusions_raw: list[dict] = []
    failure = None
    if row["status"] == "succeeded":
        conclusions_raw, failure = _parse_conclusions(row.get("rendered_output") or "")
    elif not running:
        failure = row.get("error") or NO_REPLY_MESSAGE

    return {
        "task_id": row["id"],
        "campaign_id": scope.get("campaign_id"),
        "campaign_name": scope.get("campaign_name"),
        "status": row["status"],
        "failure": failure,
        "running": running,
        # 存進 context_scope_json 的 unreadable_ad_ids 本身就帶 name（見 job body），
        # 這裡直接原樣穿出去，不必為了補一個名字回頭再打一次 Graph API。
        "unreadable_ads": scope.get("unreadable_ad_ids") or [],
        "conclusions": _conclusions_response(conn, brand_id, row["id"], conclusions_raw),
    }


# ---------------------------------------------------------------------------
# 接受結論（D10）——一律經 create_learning_ledger_entry，這個模組自己永遠不會對那張表
# 下 SQL。
# ---------------------------------------------------------------------------

def accept_conclusions(
    conn, brand_id: str, org_id: str, actor_user_id: str, task_id: str, indexes: list,
) -> dict:
    """POST .../accept：`indexes` 全部先驗證過（每一個都在範圍內、每一個的 scope 都可以
    採用）才開始寫，任何一個不合法整批擋下——比照 `app/schedule/routes.py`
    `_validate_reject_entries()` 的『整批驗證、要嘛全部合法要嘛什麼都不建立』慣例，不挑
    合法的先建立。

    冪等靠 `(source_reading_id, learning_text)` 逐字相同（ADR 0044）：同一條結論被勾兩次
    （使用者重整頁面又勾一次已經接受過的），第二次直接跳過，不重複入帳，也不報錯。

    ponytail: 這個冪等是「先查再寫」，不是資料庫層的保證——`learning_ledger` 上沒有
    `(brand_id, source_reading_id, learning_text)` 的唯一索引，而
    `create_learning_ledger_entry` 每寫一列就自己 commit 一次。真的有兩個請求同時進來
    （連點兩下、或客戶端逾時後重送），兩邊都會讀到同一份還沒被寫進去的
    `accepted_texts`，然後各寫一列——同一條觀察在帳本裡變成兩列。這不只是多一列：
    ADR 0044 明講「同一條結論出現不只一次，代表它被觀察到不只一次」，所以重複的列會對
    下一期的企劃說謊。
    現在擋在兩個地方：畫面按下去當下就把按鈕 disable（`OnboardingReadPage.handleAccept`
    在 await 之前先 setState），而且這套系統今天是單人本機用。**真的踩到的那天**，修法是
    開一支 migration 加那條唯一索引、讓 `create_learning_ledger_entry` 把違反唯一鍵當成
    「已經有了」吞掉——這張票不能做，ADR 0044「What this does not authorise」第一條就是
    「No migration, no new column, no sweep」。沒有量到痛過之前不先蓋。"""
    row = gateway.get_task(conn, task_id)
    if row is None or row["brand_id"] != brand_id or row["task_type"] != TASK_TYPE:
        raise web.ApiError(404, "not_found", NO_READING_MESSAGE)

    conclusions, failure = _parse_conclusions(row.get("rendered_output") or "")
    if failure is not None:
        raise web.ApiError(400, "no_conclusions", failure)

    product_ids = {p["id"] for p in bi_repo.list_products(conn, brand_id)}
    for index in indexes:
        if not (0 <= index < len(conclusions)):
            raise web.ApiError(400, "index_out_of_range", INDEX_OUT_OF_RANGE_MESSAGE)
        scope_value = conclusions[index]["scope"]
        if scope_value != "brand" and scope_value not in product_ids:
            raise web.ApiError(400, "scope_not_acceptable", SCOPE_NOT_ACCEPTABLE_MESSAGE)

    accepted_texts = {
        row2["learning_text"]
        for row2 in bi_repo.list_learning_ledger_by_source_reading(
            conn, brand_id, source_reading_id=task_id
        )
    }
    for index in indexes:
        conclusion = conclusions[index]
        if conclusion["text"] in accepted_texts:
            continue
        applicability_scope = "brand" if conclusion["scope"] == "brand" else "product"
        product_id = None if conclusion["scope"] == "brand" else conclusion["scope"]
        sample_size = conclusion["sample_note"]
        if conclusion["evidence"]:
            # D10：sample_size 借來同時裝樣本大小跟依據——這張表沒有 evidence 欄位，
            # 這張票也不能加，兩句話都在回答『這個樣本有多可信』。
            sample_size = f"{sample_size}（依據：{conclusion['evidence']}）"
        bi_repo.create_learning_ledger_entry(
            conn, brand_id, learning_text=conclusion["text"],
            applicability_scope=applicability_scope, product_id=product_id, platform="meta",
            confidence=conclusion["confidence"], sample_size=sample_size,
            source_reading_id=task_id, source_track=bi_repo.SOURCE_TRACK_IMPORTED,
            created_by=actor_user_id, actor=actor_user_id,
        )
        accepted_texts.add(conclusion["text"])

    return brand_response(conn, brand_id, org_id)


# ---------------------------------------------------------------------------
# procrastinate task body：一個活動一份工
# ---------------------------------------------------------------------------

def onboarding_read(
    org_id: str, brand_id: str, read_id: str, ad_account_id: str, account_external_id: str,
    campaign_id: str, campaign_name: str, campaign_effective_status: str,
    expected_jobs: list, frozen_facts: dict,
) -> None:
    """procrastinate task body（`background.onboarding_read`）——`start_onboarding_read()`
    對這個讀取裡的每個活動各 enqueue 一次。`org_id` 必須是第一個參數、不能有預設值
    （ADR 0038 gate，`app/tests/test_background.py::TaskSignatureOrgIdGateTest`）。

    每個分析師都自己重新列一次帳號整體的 adset／ad 再用 Python 篩出這個活動的（D4
    ponytail：一個活動 2 次 Graph 呼叫，量級小到可以接受；帳號真的大到這裡開始痛，才改成
    dispatch 時列一次、逐一切片傳下來）。"""
    with connection() as conn:
        token = meta_repo.get_token(conn, org_id)
        if token is None:
            raise ValueError(f"組織 {org_id} 的 Meta 權杖不見了，沒辦法讀這個活動")

        adsets = [
            entity for entity in graph.list_entities(token, account_external_id, "adset")
            if entity.get("campaign_id") == campaign_id
        ]
        ads = [
            entity for entity in graph.list_entities(token, account_external_id, "ad")
            if entity.get("campaign_id") == campaign_id
        ]
        ad_ids = [ad["id"] for ad in ads]
        creatives_by_ad = graph.list_ad_creatives(token, ad_ids) if ad_ids else {}

        campaign = {
            "id": campaign_id, "name": campaign_name,
            "effective_status": campaign_effective_status,
        }
        structure_text, unreadable_ads = onboarding_slice.structure_text(
            campaign, adsets, ads, creatives_by_ad
        )

        since = date.fromisoformat(frozen_facts["since"])
        until = date.fromisoformat(frozen_facts["until"])
        account_ids = [ad_account_id]
        brand = bi_repo.get_brand(conn, brand_id)
        conversion_goal = brand["conversion_goal"] if brand is not None else None
        adset_ids = [adset["id"] for adset in adsets]

        totals = onboarding_slice.entity_totals(
            conn, org_id, account_ids, since, until, conversion_goal, campaign_id, adset_ids, ad_ids
        )
        action_totals = meta_repo.entity_action_totals(
            conn, org_id, account_ids, since, until, campaign_id=campaign_id
        )
        totals_text = onboarding_slice.totals_text(totals, action_totals)

        rows = meta_repo.entity_rows(
            conn, org_id, account_ids, since, until, campaign_id=campaign_id
        )
        csv_text = onboarding_slice.daily_csv(rows)

        department_text = DEPARTMENT_FILE.read_text(encoding="utf-8")
        methodology_result = methodology.compile(conn, METHODOLOGY_TASK_LABELS, brand_id=brand_id)
        compiled = context_compiler.compile(conn, brand_id)
        brand_context, knowledge_item_ids, brand_version, _product_version = compiled
        frozen_facts_text = _frozen_facts_text(frozen_facts)
        segment4 = "\n\n".join([
            structure_text, totals_text,
            # 表頭說明必須跟著 CSV 一起走：`action_*` 欄位是攤平來的
            # （見 `onboarding_slice.daily_csv`），
            # 空白格代表「Meta 那天沒有回報這個事件」，不是「那天是 0 次」——這兩件事分不
            # 清楚，整份判讀就會把沒追蹤到的日子當成失敗的日子。
            "## 逐日成效（CSV）\n"
            "`action_*`／`action_value_*` 欄位是 Meta 回報的事件攤平成的欄位；"
            "**空白格是「那天沒有回報這個事件」，不是 0。**\n"
            "```csv\n" + csv_text + "```",
        ])
        # D8：段落順序固定 [1] 部門任務檔＋方法論 [2] 品牌上下文 [3] 既定事實 [4] 這個活動
        # 自己的切片，不得調換。
        prompt = "\n\n".join(
            section for section in
            (department_text, methodology_result.text, brand_context, frozen_facts_text, segment4)
            if section
        )

        context = gateway.TaskContext(
            context_scope={
                "brand_id": brand_id, "onboarding_read_id": read_id,
                "ad_account_id": ad_account_id, "account_external_id": account_external_id,
                "campaign_id": campaign_id, "campaign_name": campaign_name,
                "campaign_effective_status": campaign_effective_status,
                "expected_jobs": expected_jobs, "frozen_facts": frozen_facts,
                "unreadable_ad_ids": unreadable_ads,
            },
            knowledge_item_ids=knowledge_item_ids,
            brand_version=brand_version, product_version=None,
        )
        gateway.run_task(
            conn, PROVIDER, brand_id=brand_id, task_type=TASK_TYPE,
            prompt_template_id=TASK_TYPE, prompt_template_version="v1",
            system=None, messages=[{"role": "user", "content": prompt}], context=context,
            # 思考等級走 TASK_DEFAULTS["onboarding_read"]（app/llm/providers.py），這裡只補
            # timeout_s——跟另外兩個長任務（schedule_tree／schedule_creative）同一個 480 秒。
            options=gateway.TaskOptions(timeout_s=480.0),
        )
