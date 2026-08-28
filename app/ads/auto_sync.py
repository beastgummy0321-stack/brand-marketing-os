"""app/ads/auto_sync.py — 每日自動同步觸發器（票 07-auto-sync，規格 0001）。

沿用既有唯讀同步邏輯：Meta 帳號同步（app/ads/sync.py `sync_account`，全站一組連線、
一次涵蓋所有已認領品牌，比照手動同步鈕 `/brands/{b}/ads/sync` 的既有呼叫方式）＋
GA4 每品牌同步（app/ads/ga4_sync.py `sync_brand`，比照手動同步鈕 `/brands/{b}/ads/ga4/sync`）。
唯一差別是觸發者從「使用者按鈕」換成「排程呼叫這支函式」；不設定連線就跳過、不報錯。

失敗不拋例外、也不讓一個品牌的失敗擋住其他品牌：各自的同步結果各自處理，
失敗才送進打斷佇列（`auto_sync_failed` 類別，見 app/core/interrupts.py CATEGORIES）。
"""

from datetime import UTC, date, datetime, timedelta

from app.ads import diagnosis as ads_diagnosis  # noqa: F401 — 匯入觸發調度台模組登記（票 O1-01）

# 少了這行就只靠別處的 import 鏈碰巧先跑到，鏈一改規則會安靜地不再觸發（審查備註）
from app.ads import (
    ga4_sync,
    health_lights,  # noqa: F401 — 同上：monitor 模組登記在這支（票 O1-02）
    meta_mcp,  # noqa: F401 — 同上：publish 模組登記在這支（票 O1-02）
    onboarding,
    pacing_curve,
    proposal,  # noqa: F401 — 同上：proposal 模組登記在這支（票 O1-02）
    reading,
    theme_batch,  # noqa: F401 — 同上：規則 2（創意.補主題）登記在這支，
    tracking,
    weekly_proposals,
    weekly_reports,
)
from app.ads import repository as ads_repo
from app.ads import sync as ads_sync
from app.brand_intelligence import repository as bi_repo
from app.core import interrupts as core_interrupts
from app.core import orchestrator as core_orchestrator
from app.intake import (
    dispatch as intake_dispatch,  # noqa: F401 — 同上：intake 模組登記在這支（票 O1-02）
)

ACTOR = "auto_sync"
WEEKLY_ACTOR = "weekly_engine"


def _all_org_ids(conn) -> list:
    """票 03-1：背景排程沒有登入者、沒有 X-Org-Id 表頭可讀——這裡是唯一還「跨組織」
    的地方，逐一取出所有組織 id，下面每個迴圈各自對一個組織跑一輪（不得寫死 org_dev）。
    `organisation` 不屬於任何一層的保護表清單（test_architecture_boundaries.py
    CrossLayerRawSqlScanTest），任何模組可以直接查。"""
    return [r["id"] for r in conn.execute("SELECT id FROM organisation").fetchall()]

# 打斷佇列卡片內文上限 30 全形字（app/core/interrupts.py MAX_MESSAGE_LEN）——固定短句，
# 不把原始錯誤訊息塞進去（原始錯誤訊息通常較長且長度不可控，沿用其他模組固定短句的作法）。
_META_FAILURE_MESSAGE = "Meta 自動同步失敗，去設定頁看看。"
_GA4_FAILURE_MESSAGE = "GA4 自動同步失敗，去看看。"
_IMMEDIATE_SYNC_DEBOUNCE = timedelta(seconds=30)
_immediate_sync_cache = {}


def check_schedule_reminder(conn, brand_id: str, cycle_id: str, today: str):
    """排程與畫面共用同一條到期提醒路徑。"""
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    if not cycle:
        return None
    plan = ads_repo.derived_plan(cycle)
    reminder = pacing_curve.due_schedule_change(cycle, plan.get("daily_budgets") or [], today)
    if reminder:
        brand = bi_repo.get_brand(conn, brand_id)
        assert brand is not None, f"找不到品牌：{brand_id}"
        core_interrupts.enqueue(
            conn, org_id=brand["org_id"],
            category="pacing_schedule_due", dedupe_key=f"schedule:{cycle_id}:{today}",
            brand_id=brand_id, message=reminder["copy_text"][:30],
            action_url=f"/app/brands/{brand_id}/campaigns/{cycle_id}",
        )
    return reminder


def run_due_readings(conn, brand_id: str, today: str) -> None:
    """用既有到期提醒觸發第 7 天判讀與期末結算。"""
    for reminder in onboarding.due_reminders(conn, brand_id, today=today):
        if reminder["kind"] == "day7_report":
            ok, _ = reading.run(conn, brand_id, reminder["campaign_cycle_id"], ACTOR)
            if ok:
                weekly_proposals.generate(conn, brand_id, reminder["campaign_cycle_id"])
        elif reminder["kind"] == "final_settlement":
            ok, _ = reading.finalize(
                conn, brand_id, reminder["campaign_cycle_id"], ACTOR,
            )
            if ok:
                weekly_proposals.generate(conn, brand_id, reminder["campaign_cycle_id"])
                org_id = bi_repo._org_id_for_brand(conn, brand_id)
                core_interrupts.resolve(conn, reminder["id"], actor=ACTOR, org_id=org_id)


def run_weekly_engine(conn, *, today: str) -> dict:
    """每個組織底下每個營運中品牌取最新進行中檔期，重跑判讀並產出最多三張週提案。"""
    outcome = {}
    for org_id in _all_org_ids(conn):
        for brand in bi_repo.list_brands(conn, org_id, status="active"):
            brand_id = brand["id"]
            cycle = weekly_proposals.current_cycle(conn, brand_id)
            if cycle is None:
                outcome[brand_id] = {"status": "skipped", "reason": "沒有進行中的檔期"}
                continue
            try:
                ok, err = reading.run(conn, brand_id, cycle["id"], WEEKLY_ACTOR)
                cards = weekly_proposals.generate(conn, brand_id, cycle["id"]) if ok else []
                if ok:
                    weekly_reports.enqueue_if_ready(conn, brand_id, cycle["id"], today=today)
                outcome[brand_id] = {
                    "status": "done" if ok else "failed",
                    "error": err,
                    "proposal_count": len([
                        card for card in cards if card["status"] == "GENERATED"
                    ]),
                    "checked_on": today,
                }
            except Exception as exc:  # noqa: BLE001 — 一個品牌失敗不能擋住其他品牌
                conn.rollback()
                outcome[brand_id] = {
                    "status": "failed",
                    "error": str(exc),
                    "proposal_count": 0,
                    "checked_on": today,
                }
    return outcome


def run_cycle_checks(conn, brand_id: str, today: str, *, url_probe=None) -> None:
    for cycle in ads_repo.list_cycles(conn, brand_id):
        if cycle["status"] in ("LIVE", "EVALUATING"):
            check_schedule_reminder(conn, brand_id, cycle["id"], today)
    run_due_readings(conn, brand_id, today)
    tracking.run_post_sync_checks(conn, brand_id, today=today, url_probe=url_probe)


def sync_brand_now(conn, brand_id: str, actor: str, *, meta_client=None, ga4_client=None,
                   now: datetime | None = None, url_probe=None) -> str:
    """同步單一品牌；30 秒內重按直接沿用同一次完成時間。"""
    now = now or datetime.now(UTC)
    cached = _immediate_sync_cache.get(brand_id)
    if cached and now - cached[0] < _IMMEDIATE_SYNC_DEBOUNCE:
        return cached[1]
    # 02-3c：本機時區才是全站「今天」的基準（同 app/main.py _auto_sync_if_due()），
    # 不能直接拿 now（UTC）的曆日，本機時區早於 UTC 時會晚一天才追到到期提醒。
    today = now.astimezone().date().isoformat()
    brand = bi_repo.get_brand(conn, brand_id)
    if brand is None:
        raise ValueError(f"找不到品牌：{brand_id}")
    org_id = brand["org_id"]
    if ads_sync.is_configured(conn, org_id=org_id):
        meta_result = ads_sync.sync_account(
            conn, actor, org_id=org_id, client=meta_client, today=today, brand_id_filter=brand_id)
        if meta_result.error:
            raise ValueError(meta_result.error)
    if ga4_sync.is_configured(conn, org_id=org_id):
        ga4_result = ga4_sync.sync_brand(conn, brand_id, actor, client=ga4_client, today=today)
        if ga4_result.error:
            raise ValueError(ga4_result.error)
    run_cycle_checks(conn, brand_id, today, url_probe=url_probe)
    completed_at = now.isoformat()
    _immediate_sync_cache[brand_id] = (now, completed_at)
    conn.commit()
    return completed_at


def run(conn, *, today: str | None = None, meta_client=None, ga4_client=None,
        url_probe=None) -> dict:
    """跑一輪每日自動同步。回傳 {"meta": SyncResult|None, "ga4": {brand_id: GA4SyncResult}}
    給呼叫端（測試、未來的執行紀錄）檢查跑了什麼。"""
    today = today or date.today().isoformat()
    outcome = {"meta": None, "ga4": {}}

    # 票 04-0：app/core/settings.py 的 Meta 帳號設定（TOKEN_SETTING／ACCOUNT_SETTING）
    # 已經改成每組織一份、讀值一定要帶 org_id（見 app/ads/sync.py is_configured）——一個
    # ad_account 列本身有 org_id（schema 上一個帳號只屬於一個組織，見 handoff.py
    # _ensure_ad_account），所以「這次要用哪個組織」優先看這個帳號過去同步時記下的
    # org_id；還沒同步過（ad_account 表是空的）才退回「隨便選第一個組織」——這條退回
    # 路徑只在全站僅有一個組織時才誠實正確（報告見票 03-1 交接，票 04-0 沿用同一段話）。
    existing_account = conn.execute(
        "SELECT org_id FROM ad_account WHERE platform = 'meta' ORDER BY created_at LIMIT 1"
    ).fetchone()
    sync_org_id = existing_account["org_id"] if existing_account else next(iter(_all_org_ids(conn)), None)
    if sync_org_id and ads_sync.is_configured(conn, org_id=sync_org_id):
        meta_result = ads_sync.sync_account(conn, ACTOR, org_id=sync_org_id, client=meta_client, today=today)
        outcome["meta"] = meta_result
        if meta_result.error:
            core_interrupts.enqueue(
                conn, org_id=sync_org_id, category="auto_sync_failed",
                dedupe_key=f"auto_sync_failed:meta:{today}",
                message=_META_FAILURE_MESSAGE, action_url="/app/settings",
            )

    for org_id in _all_org_ids(conn):
        if ga4_sync.is_configured(conn, org_id=org_id):
            for brand in bi_repo.list_brands(conn, org_id, status="active"):
                ga4_result = ga4_sync.sync_brand(conn, brand["id"], ACTOR, client=ga4_client, today=today)
                outcome["ga4"][brand["id"]] = ga4_result
                if ga4_result.error:
                    core_interrupts.enqueue(
                        conn, org_id=brand["org_id"], category="auto_sync_failed", brand_id=brand["id"],
                        dedupe_key=f"auto_sync_failed:ga4:{brand['id']}:{today}",
                        message=_GA4_FAILURE_MESSAGE,
                        action_url=f"/app/brands/{brand['id']}/tracking",
                    )

        for brand in bi_repo.list_brands(conn, org_id, status="active"):
            run_cycle_checks(conn, brand["id"], today, url_probe=url_probe)
            cycle = weekly_proposals.current_cycle(conn, brand["id"])
            if cycle is not None:
                weekly_reports.enqueue_if_ready(conn, brand["id"], cycle["id"], today=today)
            try:
                core_orchestrator.run(conn, brand["id"], actor=ACTOR, org_id=brand["org_id"])
            except Exception:  # noqa: BLE001 — 一個品牌的調度台失敗不擋住其他品牌（票 O1-01）
                conn.rollback()

    conn.commit()
    return outcome


# ---------------------------------------------------------------------------
# 調度台『同步』模組門面（票 O1-02，ADR 0024）
# ---------------------------------------------------------------------------

def status(conn, brand_id: str) -> dict:
    """調度台 facts：`sync.meta_configured`／`sync.ga4_configured`（Meta／GA4 連線設定
    好了沒，全組織一組設定，不分品牌）。

    調度台契約：全新／不存在的品牌也要照樣回傳全部 key、不得丟例外（見
    test_core_orchestrator.py NewModuleStatusShapeTest）——用 get_brand() 而不是會噴
    ValueError 的 _org_id_for_brand()，查無此品牌就當作「什麼都沒設定」。
    """
    brand = bi_repo.get_brand(conn, brand_id)
    if brand is None:
        return {"sync.meta_configured": False, "sync.ga4_configured": False}
    org_id = brand["org_id"]
    return {
        "sync.meta_configured": ads_sync.is_configured(conn, org_id=org_id),
        "sync.ga4_configured": ga4_sync.is_configured(conn, org_id=org_id),
    }


def handle(conn, action: dict) -> dict:
    """同步模組沒有任何 op：同步要打 Meta／GA4 外部 API，handle() 不得阻塞
    （ADR 0024 決議 4）。收到任何 op 一律丟 ValueError（ADR 0024 決議 6）。"""
    raise ValueError(f"同步模組不認得這個 op：{action['op']}")


core_orchestrator.register_module("sync", status=status, handle=handle)
