"""app/schedule/routes.py — /api/schedule/*. Private: only app/schedule/__init__.py imports
this (container contract §1); it is only ever loaded via `register()`.

票 07：檔期規劃最薄路徑——選產品、確認，拿回一張方案卡。票 08：表單加平台／目標／促銷
重點／方案數，代理出 N 個方案前先用網路搜尋工具查這期有沒有真正相關的節慶或時事。
ADR 0028／0029／0032／0033：部門是 repo 裡的一個資料夾
（`app/departments/ads/schedule.md`），外殼原樣把它貼進 prompt，從不解析；品牌上下文經
既有的 `context_compiler.compile()` 組出來；`gateway.run_task()` 是全站唯一的 LLM 入口，
這裡不重寫第二個。money 由 `plan.py` 的純函數算，代理只給比例。票 10-feedback-entries
（ADR 0037）：拒絕一批方案＝把每條意見寫成 `rule` 表的一列（呼叫既有的
`bi_repo.create_rule()`，不自己下 SQL），再用最新一次成功的 `schedule_plan` 凍結參數重跑，
沒有第二條把回饋文字塞進 prompt 的路徑。票 01（`.scratch/creative-slice/issues/`）：
`app/departments/creative/ad_creative.md` 是創意部門的第一個任務檔（ADR 0028 加的第二個
部門資料夾），把展開好的活動樹每個最深層節點各配一份內容，`task_type = "schedule_creative"`
——外殼一樣不解析這份任務檔，也不認得任何一個具體欄位名稱（見 `app/schedule/creative.py`）。

平台／行銷目標不是外殼的業務詞（CONTEXT.md：外殼只認得檔期／核准／預算上限），一律從
`channel_catalogue.json` 這份資料檔讀出來，不寫死成 Python 常數或畫面 label（票 08；
票 T4／ADR 0056：這份資料檔改名，並多負責通路能力旗標）。

票 01（`.scratch/approval-slice/issues/01-approval-is-the-money-brake.md`，ADR 0040）：
「核准」＝花錢煞車，POST .../tree/approve 與 .../tree/approve/revoke 兩支端點，資料落在
`app.core.approval`（外殼自己的字，不是排程模組的資料）。**算錢的部分 2026-09-03 已經搬去
`app/schedule/tree_approval.py`**（集裝箱憲章 §7：算錢或算核准金額的函式不住在 routes 檔），
本檔只剩兩支端點呼叫它：核准金額 `tree_approval._sum_daily_amounts()` 絕不採信呼叫端傳的
數字；`content_hash` 是 `tree_approval._tree_content_hash()`，刻意排除
`bound_external_id`／`spend`／`roas` 三個綁定之後才補上的欄位——見該函式的說明。

`conn` 在下面的私有函式一律不標型別：`web.conn` 是 `ConnProxy`、
`context_compiler.compile()`／`gateway.run_task()`／`repo.get_product()` 三個既有函式簽章
都吃 `Conn`（非 `ConnProxy`），比照 `app/intake/persona_generation.py`／
`app/brand_web/product_ai_calls.py` 既有寫法——`conn` 參數留白讓 pyright 用型別
不定（Unknown）通過，呼叫端只在路由這一層傳入真正的 `web.conn`。

票 05-1：三個生成端點（POST .../plans、.../tree、.../creative）不再在這支 request 裡打代理
（本檔頭原本那句「兩到六分鐘」的阻塞 POST，process 被殺掉就留一列 `llm_task` 永遠卡在
`running`，畫面永遠出不了那個狀態）。這裡現在只做四件事：驗證（跟改之前逐字一樣的次序、
代碼、訊息）＋`gateway.check_spend_cap()`；查 `_display_task_row()` 有沒有一次還在跑，是就
409；`background.enqueue()`，`False`（同一個 lock 已經排隊）也是同一個 409；回
`_brand_response()`——跟 GET 回的形狀一模一樣，`plan`／`tree`／`creative` 在剛排進去、worker
還沒撿走的那一刻可能還是 null（如果是第一次跑）或上一次成功的結果（如果是重跑）。真正打
代理、寫 `llm_task` 的程式碼搬進 `app/schedule/jobs.py`（procrastinate task body，
`register_tasks()` 掛給 `app.background`），因為 `app/schedule` 自己永遠不 import
`procrastinate`（本模組既有的界線）；enqueue／worker 過場的通用機制在 `app/background`，
不在這裡重寫第二份。
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel

import app.shared.web as web
from app.background import enqueue as background_enqueue
from app.brand_intelligence import repository as bi_repo
from app.core import approval as approval_mod
from app.core import rule_cards, vocab
from app.llm import gateway
from app.schedule import binding as binding_mod
from app.schedule import creative as creative_mod
from app.schedule import diagnosis as diagnosis_mod
from app.schedule import history as history_mod
from app.schedule import performance as performance_mod
from app.schedule import period as period_mod
from app.schedule import period_repository as period_repo
from app.schedule import plan as plan_mod
from app.schedule import repository as schedule_repo
from app.schedule import scoring as scoring_mod
from app.schedule import state, tree_approval

router = APIRouter(prefix="/api/schedule")


# 票 05-1：這一份端點驗證通過就 enqueue，第二次按下去在這一份 llm_task 列還在跑的時候
# 一律回這個訊息——三支端點共用同一個 code／message，不必各自造一句。
ALREADY_RUNNING_MESSAGE = "上一次還在跑，請等它跑完再按。"


def _already_running_error() -> web.ApiError:
    return web.ApiError(409, "already_running", ALREADY_RUNNING_MESSAGE)


class PlanRequest(BaseModel):
    # 全部欄位都給預設值，不是必填：租戶界線（require_brand）要先於「填了什麼」被檢查，見
    # test_identity_auth.py／test_identity_tenant_routes.py 的全站 sweep（送空 body 也要
    # 先走到 401／404，不能被 pydantic 必填欄位擋在驗證身分之前）——真的沒填/填錯仍在
    # `_run_plan()` 裡逐一驗證、回人話的 400，不會假裝成功。
    product_ids: list[str] = []
    platform: str = ""
    objective: str = ""
    promotion_note: str = ""
    plan_count: int = 3  # 畫面預設值；程式真正允許的範圍讀規則卡 schedule_plan_count（票 08）
    start_date: str = ""  # 票 T2b：檔期日期，真正的驗證在 `period.validate_dates()`
    end_date: str = ""


class TreeRequest(BaseModel):
    plan_index: int = 0  # 沒有型別上界，超出方案數的驗證在 `_run_tree()` 裡回人話 400


class RejectEntry(BaseModel):
    # 票 10-feedback-entries（ADR 0037）：一條回饋＝rule 表的一列。這裡全部給預設值，同樣
    # 理由（租戶界線先於欄位驗證），真正的驗證在 `_validate_reject_entries()`。
    severity: str = ""
    rule_type: str | None = None
    content: str = ""


class RejectRequest(BaseModel):
    entries: list[RejectEntry] = []


class AdoptRequest(BaseModel):
    # 票 02（T6c）：「採用」一條成效判讀建議——租戶界線先於欄位驗證（同上），真正的驗證
    # 在 `_run_diagnosis_adopt()`。-1 不是任何合法索引，直接落進「找不到這條建議」那支錯誤。
    suggestion_index: int = -1


class CreateCoordinateRequest(BaseModel):
    # 票 T1b：新增一個座標——租戶界線先於欄位驗證（同上），真正的驗證在
    # `create_coordinate()` 這支路由函式裡。
    dimension: str = ""
    label: str = ""
    category: str = ""


class DisableCoordinateRequest(BaseModel):
    disabled: bool = True


class TagImportedAdRequest(BaseModel):
    # 票 past-ads/03（ADR 0067）：owner 標一則老廣告的七維座標——租戶界線先於欄位驗證
    # （同上），真正的驗證在 `history.tag_imported_ad()`。七個鍵沒填到的當 None，不是必填。
    coordinates: dict[str, str | None] = {}
    owner_note: str | None = None


NO_TREE_TO_APPROVE_MESSAGE = "還沒有成功展開的活動樹可以核准，請先展開活動樹。"


def _validate_products(conn, brand_id: str, product_ids: list) -> list:
    """驗證之外還回傳選定產品的名稱（順序照使用者送來的），給 `_plan_params_text` 列進
    prompt。名稱非得從這裡帶出去不可：`context_compiler.compile()` 只吐「已確認的事實／
    規則／宣稱／典型客人」，產品自己的名字不在裡面——一個還沒建過事實的產品，勾了等於
    沒勾（2026-08-29 實測：晨光咖啡 0 筆 confirmed fact，品牌上下文長度為 0）。"""
    if not product_ids:
        raise web.ApiError(400, "no_products", "請至少選擇一項產品。")
    names = []
    for product_id in product_ids:
        product = bi_repo.get_product(conn, brand_id, product_id)
        if product is None:
            raise web.ApiError(400, "product_not_found", f"找不到產品：{product_id}")
        names.append(product["name"])
    return names


def _validate_platform_and_objective(data: dict, platform: str, objective: str) -> None:
    """平台必須是資料檔裡標記 enabled 的那個（票 08：Meta 選得到，Google／TikTok 只列出、
    停用）；目標必須是資料檔裡屬於這個平台的那個。兩個清單都來自資料檔，不寫死在這裡。"""
    enabled_platforms = {p["id"] for p in data["platforms"] if p.get("enabled")}
    if platform not in enabled_platforms:
        raise web.ApiError(400, "platform_not_enabled", "請選擇一個已開放的平台。")
    valid_objectives = {o["value"] for o in data["objectives"] if o["platform"] == platform}
    if objective not in valid_objectives:
        raise web.ApiError(400, "objective_invalid", "請選擇一個有效的行銷目標。")


def _validate_plan_count(conn, brand_id: str, plan_count: int) -> None:
    plan_count_min, plan_count_max = state._plan_count_bounds(conn, brand_id)
    if not (plan_count_min <= plan_count <= plan_count_max):
        raise web.ApiError(
            400, "plan_count_out_of_range",
            f"方案數量需介於 {plan_count_min} 到 {plan_count_max} 之間。",
        )


NO_PLAN_TO_EXPAND_MESSAGE = "還沒有成功產生的方案可以展開，請先完成排程。"
PLAN_INDEX_OUT_OF_RANGE_MESSAGE = "找不到這個方案編號，請重新選擇。"
NO_TREE_TO_GENERATE_CREATIVE_MESSAGE = "還沒有成功展開的活動樹可以產出內容，請先展開活動樹。"


def _run_tree(conn, brand_id: str, org_id: str, body: "TreeRequest") -> dict:
    """票 09：選定一個既有方案，展開成三層活動樹。票 05-1：這裡只做驗證——重讀最新一次
    `schedule_plan` 那列 `llm_task`（凍結的預算／平台），確認 `body.plan_index` 落在這批
    方案的範圍內；找不到成功的方案、或方案編號超出範圍，都在 enqueue 之前回人話 400
    （比照 `_run_plan` 的「先驗證、後花錢」次序）。真正展開活動樹在
    `app/schedule/jobs.py` 的 `schedule_tree()`（worker 執行，見該檔檔頭）——`plan_row["id"]`
    在這裡（enqueue 當下）就釘進 job 參數，job 執行時不重讀「這個品牌最新一次」（fix
    round 1：frozen decision 3 的「一次一個」是按 task type 算的，這中間可能已經有另一種
    工作的新列插進來）。"""
    plan_row = state._latest_task_row(conn, brand_id, state.TASK_TYPE)
    if plan_row is None or plan_row["status"] != "succeeded":
        raise web.ApiError(400, "no_plan", NO_PLAN_TO_EXPAND_MESSAGE)

    plan_scope = plan_row.get("context_scope_json") or {}
    daily_budget = plan_scope.get("daily_budget", 0)
    plans, failure = plan_mod.build_plans(plan_row.get("rendered_output") or "", daily_budget)
    if failure is not None or not (0 <= body.plan_index < len(plans)):
        raise web.ApiError(400, "plan_index_out_of_range", PLAN_INDEX_OUT_OF_RANGE_MESSAGE)

    gateway.check_spend_cap(conn, org_id=org_id)
    if state._display_task_row(conn, brand_id, state.TREE_TASK_TYPE)[1]:
        raise _already_running_error()
    period = period_repo.get_latest_period(conn, org_id, brand_id)
    if not background_enqueue(
        f"background.{state.TREE_TASK_TYPE}", org_id=org_id,
        lock=f"{state.TREE_TASK_TYPE}:{brand_id}",
        brand_id=brand_id, plan_index=body.plan_index, plan_task_id=plan_row["id"],
        campaign_period_id=period["id"] if period else None,
    ):
        raise _already_running_error()
    return state._brand_response(conn, brand_id, org_id)


def _run_creative(conn, brand_id: str, org_id: str) -> dict:
    """票 01：把已展開的活動樹每個最深層節點各配一份內容。票 05-1：這裡只做驗證——重讀
    最新一次成功的 `schedule_tree` 那列，確認它至少有一個最深層節點；找不到成功的樹、或
    樹沒有任何最深層節點，都在 enqueue 之前回人話 400（比照 `_run_tree` 的
    「先驗證、後花錢」次序）。真正產內容、把來源樹的 id 凍結進 `context_scope_json`
    （frozen decision 5）在 `app/schedule/jobs.py` 的 `schedule_creative()`——`tree_row["id"]`
    同樣在這裡釘進 job 參數，理由見 `_run_tree()` 的 fix round 1 註解。"""
    tree_row = state._latest_task_row(conn, brand_id, state.TREE_TASK_TYPE)
    if tree_row is None or tree_row["status"] != "succeeded":
        raise web.ApiError(400, "no_tree", NO_TREE_TO_GENERATE_CREATIVE_MESSAGE)
    tree = binding_mod.tree_with_bindings(conn, tree_row, org_id, brand_id)
    ad_nodes = state._leaf_ad_nodes(tree["nodes"]) if tree["failure"] is None else []
    if not ad_nodes:
        raise web.ApiError(400, "no_tree", NO_TREE_TO_GENERATE_CREATIVE_MESSAGE)

    gateway.check_spend_cap(conn, org_id=org_id)
    if state._display_task_row(conn, brand_id, state.CREATIVE_TASK_TYPE)[1]:
        raise _already_running_error()
    current_period = period_repo.get_latest_period(conn, org_id, brand_id)
    if not background_enqueue(
        f"background.{state.CREATIVE_TASK_TYPE}", org_id=org_id,
        lock=f"{state.CREATIVE_TASK_TYPE}:{brand_id}", brand_id=brand_id,
        tree_task_id=tree_row["id"],
        campaign_period_id=current_period["id"] if current_period else None,
    ):
        raise _already_running_error()
    return state._brand_response(conn, brand_id, org_id)


def _run_plan(conn, brand_id: str, org_id: str, body: "PlanRequest") -> dict:
    """票 07／08：出 N 個方案。票 05-1：這裡只做驗證（產品／平台／目標／方案數存在且
    合法、日預算已設定、月費上限沒破）＋enqueue；真正打代理、寫 prompt 在
    `app/schedule/jobs.py` 的 `schedule_plan()`（worker 執行，見該檔檔頭「為什麼分兩邊」）。
    """
    _validate_products(conn, brand_id, body.product_ids)
    data = state._load_platform_data()
    _validate_platform_and_objective(data, body.platform, body.objective)
    _validate_plan_count(conn, brand_id, body.plan_count)
    start_date, end_date, dates_code, dates_message = period_mod.validate_dates(
        body.start_date, body.end_date
    )
    if dates_code is not None:
        raise web.ApiError(400, dates_code, dates_message)

    daily_budget = rule_cards.get_value(conn, brand_id, "schedule_budget", "daily_budget")
    if not daily_budget:
        raise web.ApiError(400, "budget_not_set", plan_mod.BUDGET_NOT_SET_MESSAGE)

    # ADR 0053 決策 1：這期誕生在這裡（出方案成功的當下），不是等到核准——同一個品牌
    # 最多一個草稿，第二次以後改的是同一列的日期／預算（票 T2b「on success, before the
    # enqueue」）。
    period_id = period_repo.upsert_draft_period(
        conn, org_id, brand_id,
        name=f"{start_date.isoformat()} ~ {end_date.isoformat()}",
        start_date=start_date, end_date=end_date, daily_budget=daily_budget,
        currency=period_mod.CURRENCY,
    )

    gateway.check_spend_cap(conn, org_id=org_id)
    if state._display_task_row(conn, brand_id, state.TASK_TYPE)[1]:
        raise _already_running_error()
    if not background_enqueue(
        f"background.{state.TASK_TYPE}", org_id=org_id, lock=f"{state.TASK_TYPE}:{brand_id}",
        brand_id=brand_id, product_ids=body.product_ids, platform=body.platform,
        objective=body.objective, promotion_note=body.promotion_note,
        plan_count=body.plan_count, campaign_period_id=period_id,
    ):
        raise _already_running_error()
    return state._brand_response(conn, brand_id, org_id)


# 票 10-feedback-entries（ADR 0037）：soft 回饋允許的類別——vocab.py RULE_TYPES 新增的
# 五個（四個偏好分類＋other）；hard 回饋一律強制 forbidden_word，不接受這份清單裡任何值
# （dropdown 只問後果、不問內容，見 ADR 0037「兩個值，永遠不會有第三個」）。
SOFT_REJECT_RULE_TYPES = frozenset({"angle", "audience", "product_pick", "budget_split", "other"})

REJECT_NO_ENTRIES_MESSAGE = "拒絕一批之前，請至少填一條意見。"
REJECT_CONTENT_INVALID_MESSAGE = "每一條意見請填 1～100 字。"
REJECT_SEVERITY_INVALID_MESSAGE = "請選擇「紅線」或「偏好」。"
REJECT_CATEGORY_INVALID_MESSAGE = "請為這條偏好選一個類別。"
NO_PLAN_TO_RERUN_MESSAGE = "還沒有成功產生的方案可以重新排程，請先完成排程。"


def _validate_reject_entries(entries: list["RejectEntry"]) -> list[dict]:
    """票 10 settled 段第 3 點：空清單先擋（「拒絕一批要先寫至少一條」不只在表單擋，這裡
    也擋）；每條意見驗證後轉成 `bi_repo.create_rule()` 要的形狀。任何一條不合法，整批不建立
    ——不挑合法的先建立、不合法的丟掉（比照 `plan.py` 的「整批失敗」慣例）。"""
    if not entries:
        raise web.ApiError(400, "no_entries", REJECT_NO_ENTRIES_MESSAGE)
    validated = []
    for entry in entries:
        content = entry.content.strip()
        if not content or len(content) > 100:
            raise web.ApiError(400, "content_invalid", REJECT_CONTENT_INVALID_MESSAGE)
        if entry.severity == "hard":
            rule_type = "forbidden_word"  # 強制，不採信呼叫端傳的任何值（settled 段第 3 點）
        elif entry.severity == "soft":
            if entry.rule_type not in SOFT_REJECT_RULE_TYPES:
                raise web.ApiError(400, "rule_type_invalid", REJECT_CATEGORY_INVALID_MESSAGE)
            rule_type = entry.rule_type
        else:
            raise web.ApiError(400, "severity_invalid", REJECT_SEVERITY_INVALID_MESSAGE)
        validated.append({"severity": entry.severity, "rule_type": rule_type, "content": content})
    return validated


def _run_reject(conn, brand_id: str, actor, body: "RejectRequest") -> dict:
    """票 10 settled 段第 3 點：驗證、把每條意見建成品牌層規則（`product_id=None`），
    再用最新一次成功的 `schedule_plan` 任務凍結的參數重新排程——規則在重新排程組 prompt
    之前已經 `active`，`context_compiler.compile()` 既有的注入邏輯就會吃到，不另開第二條
    把回饋文字直接塞進 prompt 的路徑。"""
    validated = _validate_reject_entries(body.entries)

    plan_row = state._latest_task_row(conn, brand_id, state.TASK_TYPE)
    if plan_row is None or plan_row["status"] != "succeeded":
        raise web.ApiError(400, "no_plan", NO_PLAN_TO_RERUN_MESSAGE)
    scope = plan_row.get("context_scope_json") or {}

    for entry in validated:
        bi_repo.create_rule(
            conn, brand_id, actor=str(actor.user_id), rule_type=entry["rule_type"],
            content=entry["content"], severity=entry["severity"],
        )

    # 票 T2b：檔期日期不是 `schedule_plan` 凍結參數的一部分（那是檔期自己的欄位）——
    # 重新排程沿用同一個檔期，從品牌目前的檔期讀日期，不必使用者重填。
    current_period = period_repo.get_latest_period(conn, actor.org_id, brand_id)
    rerun_body = PlanRequest(
        product_ids=scope.get("product_ids", []),
        platform=scope.get("platform", ""),
        objective=scope.get("objective", ""),
        promotion_note=scope.get("promotion_note", ""),
        plan_count=scope.get("plan_count", 3),
        start_date=current_period["start_date"].isoformat() if current_period else "",
        end_date=current_period["end_date"].isoformat() if current_period else "",
    )
    return _run_plan(conn, brand_id, actor.org_id, rerun_body)


def _run_bind(conn, brand_id: str, org_id: str) -> dict:
    """綁定的本體住在 `binding.py`（票 T3c 站①：那是做事，不是收請求）。這裡只留路由該做
    的三件事：先驗證有沒有一棵可以綁的樹（比照 `_run_tree` 的「先驗證、後動作」次序）、
    交給 `binding.bind_tree()`、把整批共用的失敗訊息貼回回應。"""
    tree_row = state._latest_task_row(conn, brand_id, state.TREE_TASK_TYPE)
    if tree_row is None or tree_row["status"] != "succeeded":
        raise web.ApiError(400, "no_tree", binding_mod.NO_TREE_TO_BIND_MESSAGE)

    failures = binding_mod.bind_tree(conn, tree_row, org_id, brand_id)
    response = state._brand_response(conn, brand_id, org_id)
    # settled 段第 7 點：這個欄位只在這支路由的回應裡非空、從不落地，其餘讀取路徑一律 null。
    response["tree"]["bind_failure"] = (
        binding_mod.bind_failure_message(failures) if failures else None
    )
    # 票 05：只有這支路由填值，其餘讀取路徑一律 null，跟 bind_failure 同一條規則
    # （tree.py 的殼層欄位註解）。
    response["tree"]["budget_note"] = binding_mod.budget_placement_note(
        conn, org_id, brand_id, tree_row
    )
    return response


def _run_approve(conn, brand_id: str, org_id: str, actor: str) -> dict:
    """票 01：核准目前展開的活動樹——金額、雜湊都在這裡算，`approval` 表本身完全不知道
    「樹」長什麼樣子（集裝箱憲章）。先驗證有沒有一棵可以核准的樹，再落地（比照
    `_run_tree`／`_run_bind` 的「先驗證、後動作」次序）。舊列從不覆寫，一次核准就是
    一列新的（ticket 明文）。"""
    tree_row = state._latest_task_row(conn, brand_id, state.TREE_TASK_TYPE)
    if tree_row is None or tree_row["status"] != "succeeded":
        raise web.ApiError(400, "no_tree", NO_TREE_TO_APPROVE_MESSAGE)
    tree = binding_mod.tree_with_bindings(conn, tree_row, org_id, brand_id)
    if tree["failure"] is not None:
        raise web.ApiError(400, "no_tree", NO_TREE_TO_APPROVE_MESSAGE)

    # ADR 0059：上限＝簽核當下的總額，一次算好傳兩次——兩次呼叫 _sum_daily_amounts 會是
    # 兩次可能飄移的機會（ticket 明文）。
    daily_amount = tree_approval._sum_daily_amounts(tree["nodes"])
    approval_mod.approve(
        conn, org_id=org_id, brand_id=brand_id, scope_type=tree_approval.APPROVAL_SCOPE_TYPE,
        scope_ref=tree["task_id"], content_hash=tree_approval._tree_content_hash(tree),
        amount=daily_amount, max_daily_amount=daily_amount, actor=actor,
    )
    # ADR 0053 決策 1：核准這一press＝「這期真的要投」，草稿在這裡變 running。找不到草稿
    # （例如已經核准過一次）就什麼都不做——approval.py 自己已經 commit 過，這裡是同一個
    # 請求裡緊接著的下一個落地動作，不是另開一支路由。
    period_repo.approve_draft_period(conn, org_id, brand_id)
    return state._brand_response(conn, brand_id, org_id)


def _run_approve_revoke(conn, brand_id: str, org_id: str, actor: str) -> dict:
    """撤回目前有效的核准；沒有可撤回的核准就是沒事發生（比照畫面只在有核准時才會顯示
    「撤回」按鈕，這裡不必為了「按到一個畫面上不該出現的按鈕」另開一條錯誤訊息）。"""
    approval_row = approval_mod.latest(
        conn, org_id=org_id, brand_id=brand_id,
        scope_type=tree_approval.APPROVAL_SCOPE_TYPE,
    )
    if approval_row is not None:
        approval_mod.revoke(conn, approval_id=approval_row["id"], org_id=org_id, actor=actor)
    return state._brand_response(conn, brand_id, org_id)


def _run_settle(conn, brand_id: str, org_id: str, period_id: str, actor: str) -> dict:
    """票 T2b（ADR 0053 §3／§4）：結算——算法／落地都在 `period.settle()`（租戶界線在
    `period_repo.get_period()` 的 WHERE 裡，不是靠 `require_brand` 就夠——`brand_id`
    對了不代表 `period_id` 也是這個組織的，ticket 矛盾檢查段第三點），這裡只管把失敗代碼
    翻成 HTTP 錯誤。ADR 0066: on success, also score every bound node for this same press
    (scoring.py, never imported by period.py/state.py -- see docs/contracts/schedule.md)."""
    error = period_mod.settle(conn, org_id=org_id, brand_id=brand_id, period_id=period_id,
                               actor=actor)
    if error == "not_found":
        raise web.NotFoundKind("檔期")
    if error == "not_started":
        raise web.ApiError(400, "not_started", period_mod.NOT_STARTED_MESSAGE)
    settled_period = period_repo.get_period(conn, org_id, brand_id, period_id)
    assert settled_period is not None  # settle() just returned None (success) for this row
    scoring_mod.score_period(conn, org_id, brand_id, period_id,
                              settled_at=settled_period["settled_at"])
    return state._brand_response(conn, brand_id, org_id)


@router.get("/brands/{brand_id}")
def get_schedule(request: Request, brand_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    return state._brand_response(web.conn, brand_id, actor.org_id)


@router.post("/brands/{brand_id}/plans")
def create_plan(request: Request, brand_id: str, body: PlanRequest):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    return _run_plan(web.conn, brand_id, actor.org_id, body)


@router.post("/brands/{brand_id}/tree")
def create_tree(request: Request, brand_id: str, body: TreeRequest):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    return _run_tree(web.conn, brand_id, actor.org_id, body)


@router.post("/brands/{brand_id}/tree/bind")
def bind_tree(request: Request, brand_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    return _run_bind(web.conn, brand_id, actor.org_id)


@router.post("/brands/{brand_id}/tree/approve")
def approve_tree(request: Request, brand_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    return _run_approve(web.conn, brand_id, actor.org_id, str(actor.user_id))


@router.post("/brands/{brand_id}/tree/approve/revoke")
def revoke_tree_approval(request: Request, brand_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    return _run_approve_revoke(web.conn, brand_id, actor.org_id, str(actor.user_id))


@router.post("/brands/{brand_id}/reject")
def create_reject(request: Request, brand_id: str, body: RejectRequest):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    return _run_reject(web.conn, brand_id, actor, body)


@router.post("/brands/{brand_id}/creative")
def create_creative(request: Request, brand_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    return _run_creative(web.conn, brand_id, actor.org_id)


@router.post("/brands/{brand_id}/periods/{period_id}/settle")
def settle_period(request: Request, brand_id: str, period_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    return _run_settle(web.conn, brand_id, actor.org_id, period_id, str(actor.user_id))


@router.get("/brands/{brand_id}/creative-performance")
def get_creative_performance(request: Request, brand_id: str):
    """票 T5（ADR 0057）：本月每個座標維度的花費／成效——沒有查詢參數，窗口固定是組織
    自己時區的這個日曆月（`performance_mod.brand_creative_performance` 檔頭有完整說明）。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    return performance_mod.brand_creative_performance(web.conn, actor.org_id, brand_id)


def _run_diagnosis(conn, brand_id: str, org_id: str) -> dict:
    """票 01（T6c）：跑一次成效判讀。比照既有 `_run_creative` 的形狀——這裡只做「還有沒有
    在跑」的檢查＋`gateway.check_spend_cap()`＋enqueue，真正壓縮資料、打三次代理、收斂在
    `app/schedule/jobs.py` 的 `schedule_diagnosis()`（worker 執行）。沒有「有沒有東西可以
    診斷」這道前置驗證：花費為零、七維全部沒有座標可對，都是誠實的判讀結果之一，不是擋在
    按鈕前的錯誤——回應的 `no_tagged_spend` 分辨得出「沒有座標可談」與「有座標但這輪沒建議」，
    畫面照那一欄說不同的話（`diagnosis.brand_diagnosis_response`）。"""
    gateway.check_spend_cap(conn, org_id=org_id)
    if state._display_task_row(conn, brand_id, state.DIAGNOSIS_TASK_TYPE)[1]:
        raise _already_running_error()
    if not background_enqueue(
        f"background.{state.DIAGNOSIS_TASK_TYPE}", org_id=org_id,
        lock=f"{state.DIAGNOSIS_TASK_TYPE}:{brand_id}", brand_id=brand_id,
    ):
        raise _already_running_error()
    return diagnosis_mod.brand_diagnosis_response(conn, org_id, brand_id)


@router.post("/brands/{brand_id}/diagnosis")
def create_diagnosis(request: Request, brand_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    return _run_diagnosis(web.conn, brand_id, actor.org_id)


@router.get("/brands/{brand_id}/diagnosis")
def get_diagnosis(request: Request, brand_id: str):
    """最新一輪：狀態、窗口日期、打平線與來源、前 5 條建議、三個 lens 各自的原文
    （`diagnosis.brand_diagnosis_response` 檔頭有完整說明）。從沒跑過就是 `status: null`。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    return diagnosis_mod.brand_diagnosis_response(web.conn, actor.org_id, brand_id)


SUGGESTION_NOT_FOUND_MESSAGE = "找不到這條建議，請重新整理後再試一次。"


def _run_diagnosis_adopt(conn, brand_id: str, actor, body: "AdoptRequest") -> dict:
    """票 02（T6c）：「採用」一條成效判讀建議 → 品牌規則卡（決定 8／9）。**不走** `_run_reject`
    那條路——那支會用凍結參數重新排程，採用一條判讀不等於現在就要重出方案（票 02 矛盾檢查段
    第二組裁決）。`source_reference_id` 固定傳 `None`：那一欄的 FK 指向 `source_reference`，
    `llm_task.id` 會違反約束（plan review 實跑 SQL 證明），來源改寫進 `diagnosis.adopt_content()`
    組出的文字。同一輪同一條重複採用只回既有那列（先查再寫，比照既有 accept 類端點的冪等寫法）
    ——查詢鍵是 `rule_type` ＋ 這段內文本身，內文由同一條建議、同一個 `round_date` 決定性算出，
    同一條建議不會算出兩種不同的內文。"""
    round_date, suggestions = diagnosis_mod.latest_round(conn, brand_id)
    if round_date is None or not (0 <= body.suggestion_index < len(suggestions)):
        raise web.ApiError(400, "suggestion_not_found", SUGGESTION_NOT_FOUND_MESSAGE)
    suggestion = suggestions[body.suggestion_index]
    # issue adopted-advice-can-invert（2026-09-06 演練）：採用一條判讀寫出來的是「這一期要
    # 去做的實驗」，不是「不准做的事」，所以固定寫 EXPERIMENT_RULE_TYPE，不再按維度借用
    # 角度／受眾的抽屜（原本鉤子的結論會被存成 angle，下一次 prompt 當角度限制讀）。
    rule_type = vocab.EXPERIMENT_RULE_TYPE
    content = diagnosis_mod.adopt_content(suggestion, round_date)

    existing = next(
        (r for r in bi_repo.list_rules_for_brand(conn, brand_id)
         if r["product_id"] is None and r["rule_type"] == rule_type and r["content"] == content),
        None,
    )
    row = existing or bi_repo.create_rule(
        conn, brand_id, actor=str(actor.user_id), rule_type=rule_type,
        content=content, severity="soft", source_reference_id=None,
    )
    return {"id": row["id"], "content": row["content"]}


@router.post("/brands/{brand_id}/diagnosis/adopt")
def adopt_diagnosis_suggestion(request: Request, brand_id: str, body: AdoptRequest):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    return _run_diagnosis_adopt(web.conn, brand_id, actor, body)


# ---------------------------------------------------------------------------
# 票 T1b：品牌智庫「創意座標」分頁（frontend/src/components/library/ 自己吃資料，站①
# decision 3——這裡只是資料源，不是那個分頁本身）。維度限定 creative.COORDINATE_KEYS
# 這七個，不另開一份清單（DB CHECK／Python 端只該有一份事實）。
# ---------------------------------------------------------------------------
COORDINATE_NOT_FOUND_MESSAGE = "找不到這個座標。"
COORDINATE_DIMENSION_INVALID_MESSAGE = "請選擇一個有效的維度。"
COORDINATE_LABEL_REQUIRED_MESSAGE = "請填寫座標名稱。"


@router.get("/brands/{brand_id}/coordinates")
def list_brand_coordinates(request: Request, brand_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    return {"coordinates": schedule_repo.list_coordinates(web.conn, actor.org_id, brand_id)}


@router.post("/brands/{brand_id}/coordinates")
def create_brand_coordinate(request: Request, brand_id: str, body: CreateCoordinateRequest):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    dimension = body.dimension.strip()
    label = body.label.strip()
    if dimension not in creative_mod.COORDINATE_KEYS:
        raise web.ApiError(400, "dimension_invalid", COORDINATE_DIMENSION_INVALID_MESSAGE)
    if not label:
        raise web.ApiError(400, "label_required", COORDINATE_LABEL_REQUIRED_MESSAGE)
    return schedule_repo.create_coordinate(
        web.conn, actor.org_id, brand_id, dimension, label, body.category.strip() or None,
    )


@router.post("/brands/{brand_id}/coordinates/{coordinate_id}/disable")
def disable_brand_coordinate(
    request: Request, brand_id: str, coordinate_id: str, body: DisableCoordinateRequest,
):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    row = schedule_repo.set_coordinate_disabled(
        web.conn, actor.org_id, brand_id, coordinate_id, body.disabled,
    )
    if row is None:
        raise web.ApiError(404, "coordinate_not_found", COORDINATE_NOT_FOUND_MESSAGE)
    return row


# ---------------------------------------------------------------------------
# 票 past-ads/03（ADR 0067）：投放史頁面——讀老廣告的成效排名＋素材快取，owner 自己標
# 座標。沒有任何一步呼叫 gateway（`grep -n gateway app/schedule/history.py` 印不出東西）。
# ---------------------------------------------------------------------------
COORDINATE_UNKNOWN_MESSAGE = "這個座標不存在，或跟這個維度對不上。"
IMPORTED_AD_UNKNOWN_MESSAGE = "找不到這則廣告，請先重新整理投放史頁面。"


@router.get("/brands/{brand_id}/history")
def get_history(request: Request, brand_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    return history_mod.history_cards(web.conn, actor.org_id, brand_id)


@router.put("/brands/{brand_id}/history/{external_id}")
def tag_history_ad(request: Request, brand_id: str, external_id: str, body: TagImportedAdRequest):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    try:
        return history_mod.tag_imported_ad(
            web.conn, actor.org_id, brand_id, external_id,
            keys=body.coordinates, owner_note=body.owner_note, actor=str(actor.user_id),
        )
    except ValueError as exc:
        message = str(exc)
        if message.startswith("coordinate_unknown:"):
            raise web.ApiError(400, "coordinate_unknown", COORDINATE_UNKNOWN_MESSAGE) from None
        if message == "imported_ad_unknown":
            raise web.ApiError(404, "imported_ad_unknown", IMPORTED_AD_UNKNOWN_MESSAGE) from None
        raise
