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
`platform_objectives.json` 這份資料檔讀出來，不寫死成 Python 常數或畫面 label（票 08）。

票 01（`.scratch/approval-slice/issues/01-approval-is-the-money-brake.md`，ADR 0040）：
「核准」＝花錢煞車，POST .../tree/approve 與 .../tree/approve/revoke 兩支端點，資料落在
`app.core.approval`（外殼自己的字，不是排程模組的資料）。核准金額由這裡算（`_sum_daily_amounts`），
絕不採信呼叫端傳的數字；`content_hash` 由這裡算（`_tree_content_hash`），刻意排除
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

import hashlib
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Request
from pydantic import BaseModel

import app.shared.web as web
from app.background import enqueue as background_enqueue
from app.brand_intelligence import repository as bi_repo
from app.core import approval as approval_mod
from app.core import rule_cards
from app.core import settings as coresettings
from app.core.db import APP_DIR, jsonb
from app.llm import gateway
from app.meta import repository as meta_repo
from app.schedule import creative as creative_mod
from app.schedule import period as period_mod
from app.schedule import plan as plan_mod
from app.schedule import repository as schedule_repo
from app.schedule import tree as tree_mod

router = APIRouter(prefix="/api/schedule")

# task_type：providers.py TASK_TYPE_LABELS／TASK_DEFAULTS 的 "schedule_plan"（票 07 settled 段：
# 重新命名死掉的 campaign_plan，不是新增第二個型別）。
TASK_TYPE = "schedule_plan"
# 票 09：選定一個方案之後展開成三層活動樹，第二個 task_type，同一支 llm_task 表。
TREE_TASK_TYPE = "schedule_tree"
# 票 01（`.scratch/creative-slice/issues/01-ad-creative-per-ad-node.md`）：把展開好的活動樹
# 每個最深層節點各配一份內容，第三個 task_type，同一支 llm_task 表（frozen decision 1）。
CREATIVE_TASK_TYPE = "schedule_creative"
# 對照 app/methodology/README.md 既有的「檔期計畫生成」列，不新增列——展開活動樹用的到的
# 平台知識（帳戶結構、AB 測試分流）跟出方案是同一批，沒有真的用到才新增專屬列（維護規則
# 「只按消費拉動萃取」）。
METHODOLOGY_TASK_LABELS = ["檔期計畫生成"]
# 票 T1 站③收尾：曾經跟上面共用一張清單餵給三支 job，副作用是計畫／活動樹的方法論區塊
# 平白多讀到創意矩陣、Meta 版位格式規格這兩份不相干的檔案（21,432 → 38,074 字，＋78%）。
# 改成 schedule_creative 專屬一張清單，計畫／活動樹維持只吃「檔期計畫生成」。
CREATIVE_METHODOLOGY_TASK_LABELS = ["廣告內容生成"]
DEPARTMENT_FILE = APP_DIR / "departments" / "ads" / "schedule.md"
TREE_DEPARTMENT_FILE = APP_DIR / "departments" / "ads" / "campaign_tree.md"
# 票 01 frozen decision 2：這是創意部門的第一個任務檔，`app/departments/` 底下新增一個
# 資料夾，程式一行不改（ADR 0028）——這裡只是讀檔路徑，不是新的 Python 套件。
CREATIVE_DEPARTMENT_FILE = APP_DIR / "departments" / "creative" / "ad_creative.md"
# 平台／行銷目標資料檔（票 08 §3）：改這個檔案不必重新部署程式；每次讀都重新讀檔
# （不快取到模組層），比照 DEPARTMENT_FILE 既有的讀法。
PLATFORM_DATA_FILE = APP_DIR / "schedule" / "platform_objectives.json"

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


class CreateCoordinateRequest(BaseModel):
    # 票 T1b：新增一個座標——租戶界線先於欄位驗證（同上），真正的驗證在
    # `create_coordinate()` 這支路由函式裡。
    dimension: str = ""
    label: str = ""
    category: str = ""


class DisableCoordinateRequest(BaseModel):
    disabled: bool = True


def _load_platform_data() -> dict:
    return json.loads(PLATFORM_DATA_FILE.read_text(encoding="utf-8"))


def _latest_task_row(conn, brand_id: str, task_type: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM llm_task WHERE brand_id = %s AND task_type = %s "
        "ORDER BY started_at DESC LIMIT 1",
        (brand_id, task_type),
    ).fetchone()
    return dict(row) if row is not None else None


def _display_task_row(conn, brand_id: str, task_type: str) -> tuple:
    """回傳 (要顯示的那一列, 有沒有更新的一次正在跑)。

    2026-08-29：原本畫面一律拿 `started_at` 最新的那一列，於是「還在跑的這一次」會蓋掉
    「上一次已經成功的樹」——12,815 字算好的結果就在隔壁列，使用者卻只看得到一句
    「展開失敗，請重新展開一次」，按下去又開一個 running，再蓋掉一次。已經算出來的東西
    不該被下一次嘗試抹掉：正在跑的時候繼續顯示上一次成功的結果，另外標明有一次在跑。
    """
    newest = _latest_task_row(conn, brand_id, task_type)
    if newest is None or newest["status"] != "running":
        return newest, False
    row = conn.execute(
        "SELECT * FROM llm_task WHERE brand_id = %s AND task_type = %s AND status = 'succeeded' "
        "ORDER BY started_at DESC LIMIT 1",
        (brand_id, task_type),
    ).fetchone()
    return (dict(row) if row is not None else newest), True


def _plan_count_bounds(conn, brand_id: str) -> tuple[int, int]:
    plan_count_min = rule_cards.get_value(conn, brand_id, "schedule_plan_count", "plan_count_min")
    plan_count_max = rule_cards.get_value(conn, brand_id, "schedule_plan_count", "plan_count_max")
    return int(plan_count_min), int(plan_count_max)  # get_value 回 float，這裡才是個數，轉 int


def _current_month_window(conn, org_id: str) -> tuple:
    """[月初, 下月初) 半開區間——跟 app/meta/routes.py brand_spend 同一個窗口（票 11
    settled 段第 9 點：綁定節點的花費／ROAS 用這一期，不是另開一套時間規則）。

    「今天」用組織自己的時區算（票 04-1b），跟 brand_spend 同一個來源。"""
    today = coresettings.today_for_org(conn, org_id=org_id)
    month_start = today.replace(day=1)
    month_end = (month_start + timedelta(days=32)).replace(day=1)
    return month_start, month_end


def _fill_node_spend(conn, org_id: str, brand_id: str, tree: dict) -> None:
    """票 11：把已綁定的第一層節點對上 ticket 05 的當月花費／ROAS——一棵樹裡沒有任何
    節點綁定，就完全不查（省一次查詢），比對用 campaign_id，不重讀名稱。

    `level="campaign"`（票 S1）：這棵樹綁定的是第一層節點，meta_entity_spend 三層共用
    一張表，不篩層級會把 adset／ad 層的花費一起加進來，變成三倍。"""
    bound_ids = {n["bound_external_id"] for n in tree["nodes"] if n["bound_external_id"]}
    if not bound_ids:
        return
    account_ids = meta_repo.bound_account_ids_for_brand(conn, org_id, brand_id)
    month_start, month_end = _current_month_window(conn, org_id)
    summary = meta_repo.spend_summary(
        conn, org_id, account_ids, month_start, month_end, level="campaign",
    )
    by_campaign_id = {e["entity_id"]: e for e in summary["entities"]}
    for node in tree["nodes"]:
        campaign = by_campaign_id.get(node["bound_external_id"])
        if campaign is not None:
            node["spend"] = campaign["spend"]
            node["roas"] = campaign["roas"]


# ---------------------------------------------------------------------------
# 票 01（ADR 0040）：核准——花錢煞車。scope_type 固定 "schedule_tree"，scope_ref 存的是
# 被核准的那棵樹自己的 `llm_task` id——事後查「我那天到底簽了哪一棵」靠的就是這一欄。
# 查詢不靠它（`approval.latest()` 只用品牌＋類型找最新一筆），因為樹每重新展開一次就是
# 全新一列；拿當下的 id 去查會永遠查不到上一次的核准，畫面就會顯示「從沒核准過」而不是
# 「核准過、但內容已經變了」。「簽的是哪一份」與「還是不是同一份」是兩件事：前者是
# scope_ref，後者是 content_hash。
# ---------------------------------------------------------------------------
APPROVAL_SCOPE_TYPE = "schedule_tree"

NO_TREE_TO_APPROVE_MESSAGE = "還沒有成功展開的活動樹可以核准，請先展開活動樹。"


def _tree_signature(tree: dict) -> dict:
    """把 `tree_from_task_row()` 的回傳形狀，剝到「使用者當時看到、簽核的那份結構」——
    `content_hash` 只對這份剝過的資料算雜湊。排除清單（ticket 明文，理由寫在這裡）：
    `bound_external_id`／`spend`／`roas`（配對一顆活動、或花費進來，都是樹核准之後才
    發生的事，不該讓已經簽過的核准悄悄失效）；`task_id`／`created_at`／`narrative`／
    `failure`／`running`／`bind_failure` 是殼層欄位，不是代理生成的樹本身內容。"""
    def _node(n: dict) -> dict:
        return {
            "name": n["name"], "fields": n["fields"], "share": n["share"],
            "daily_amount": n["daily_amount"], "warnings": n["warnings"],
            "children": [_node(c) for c in n["children"]],
        }
    return {
        "levels": tree["levels"], "budget_level": tree["budget_level"],
        "nodes": [_node(n) for n in tree["nodes"]],
    }


def _tree_content_hash(tree: dict) -> str:
    body = json.dumps(_tree_signature(tree), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _sum_daily_amounts(nodes: list) -> float:
    """核准金額＝整棵樹扛預算節點的 `daily_amount` 加總，外殼算，絕不採信呼叫端傳的
    數字（花錢的數字是外殼唯一能信任的來源）。"""
    total = 0
    for node in nodes:
        if node["daily_amount"] is not None:
            total += node["daily_amount"]
        total += _sum_daily_amounts(node["children"])
    return total


def _approval_overspend(conn, org_id: str, brand_id: str, tree: dict, approval_row: dict) -> dict:
    """兩個數字要蓋同一段日子（ticket 明講的第一版錯誤）：從「核准當天」跟「這個月月初」
    兩者較晚的那個開始，算到今天（含）——不是整個月，避免核准前的花費被誤算進超支。
    沒有任何節點綁定時 `spend_to_date` 是 None（沒在追蹤），不是 0（0 跟「不知道」是
    兩件事，印 0 會被讀成「還沒花錢」）。不設門檻：兩個數字都給，讓使用者自己判斷。"""
    approved_at = approval_row["approved_at"]
    approval_date = approved_at.date() if isinstance(approved_at, datetime) else approved_at
    today = coresettings.today_for_org(conn, org_id=org_id)  # 組織時區的今天（票 04-1b）
    month_start = today.replace(day=1)
    window_start = max(month_start, approval_date)
    days_elapsed = (today - window_start).days + 1
    approved_amount = float(approval_row["approved_amount"])

    bound_ids = {n["bound_external_id"] for n in tree["nodes"] if n["bound_external_id"]}
    spend_to_date = None
    if bound_ids:
        account_ids = meta_repo.bound_account_ids_for_brand(conn, org_id, brand_id)
        window_end = today + timedelta(days=1)  # 半開區間含今天
        # level="campaign"（票 S1）：這是核准金額的比對對象，核准只認第一層節點的
        # daily_amount（見 _sum_daily_amounts），不篩層級會把 adset／ad 層也算進實際花費，
        # 超支判斷會抓到假警報（ADR 0040 的錢煞車，錯的方向是更嚴格不是更寬鬆，但仍是錯的）。
        summary = meta_repo.spend_summary(
            conn, org_id, account_ids, window_start, window_end, level="campaign",
        )
        spend_to_date = summary["total"]["spend"]

    return {
        "expected_to_date": approved_amount * days_elapsed,
        "spend_to_date": spend_to_date,
        "days_elapsed": days_elapsed,
    }


def _fill_approval(conn, org_id: str, brand_id: str, tree: dict) -> None:
    approval_row = approval_mod.latest(
        conn, org_id=org_id, brand_id=brand_id,
        scope_type=APPROVAL_SCOPE_TYPE,
    )
    if approval_row is None:
        tree["approval"] = None
        return
    overspend = _approval_overspend(conn, org_id, brand_id, tree, approval_row)
    tree["approval"] = {
        "id": approval_row["id"],
        "approved_amount": float(approval_row["approved_amount"]),
        "approved_by": approval_row["approved_by"],
        "approved_at": approval_row["approved_at"],
        "matches_current_tree": approval_row["content_hash"] == _tree_content_hash(tree),
        **overspend,
    }


def _leaf_ad_node_names(nodes: list) -> list[str]:
    """活動樹最深層（沒有 `children` 的）節點名稱，照文件順序（深度優先、前序）——票 01：
    內容跟這一層的節點一一對應，不是每一層都配一份。"""
    names = []
    for node in nodes:
        if node["children"]:
            names.extend(_leaf_ad_node_names(node["children"]))
        else:
            names.append(node["name"])
    return names


def _creative_ad_node_names(conn, creative_row: dict) -> list[str]:
    """從這一列內容任務凍結的 `source_tree_task_id` 找回當時的那棵樹，重算最深層節點名稱
    ——frozen decision 5：核對用的永遠是產出當下的那棵樹，使用者之後重新展開樹不會悄悄
    改寫已經產出的內容，所以這裡不能讀「最新一次的樹」，只能讀凍結住的那一列。"""
    scope = creative_row.get("context_scope_json") or {}
    source_tree_task_id = scope.get("source_tree_task_id")
    if not source_tree_task_id:
        return []
    tree_row = gateway.get_task(conn, source_tree_task_id)
    if tree_row is None:
        return []
    tree = tree_mod.tree_from_task_row(tree_row)
    return _leaf_ad_node_names(tree["nodes"])


def _brand_response(conn, brand_id: str, org_id: str) -> dict:
    current_daily_budget = rule_cards.get_value(conn, brand_id, "schedule_budget", "daily_budget")
    plan_count_min, plan_count_max = _plan_count_bounds(conn, brand_id)
    data = _load_platform_data()
    row, plan_running = _display_task_row(conn, brand_id, TASK_TYPE)
    plan = plan_mod.plan_from_task_row(row) if row is not None else None
    if plan is not None and plan_running:
        plan["running"] = True
    tree_row, tree_running = _display_task_row(conn, brand_id, TREE_TASK_TYPE)
    tree = tree_mod.tree_from_task_row(tree_row) if tree_row is not None else None
    if tree is not None and tree_running:
        tree["running"] = True
    if tree is not None:
        _fill_node_spend(conn, org_id, brand_id, tree)
        _fill_approval(conn, org_id, brand_id, tree)
    creative_row, creative_running = _display_task_row(conn, brand_id, CREATIVE_TASK_TYPE)
    creative = None
    if creative_row is not None:
        ad_node_names = _creative_ad_node_names(conn, creative_row)
        creative = creative_mod.creative_from_task_row(creative_row, ad_node_names)
        if creative_running:
            creative["running"] = True
        # 票 T1b：內容一旦成功就落地成 creative_slot／creative_candidate／
        # creative_candidate_item——跟 35 個座標種子同一套「讀的時候順手確保落地」寫法，
        # 冪等（見 schedule_repo.persist_creative_result 檔頭），這裡不判斷「是不是第一次
        # 讀」，每次成功讀都呼叫一次，函式自己用 llm_task_id 擋掉重複寫入。
        if creative["failure"] is None and not creative["running"]:
            schedule_repo.persist_creative_result(
                conn, org_id, brand_id, creative["task_id"],
                creative["source_tree_task_id"], creative["ads"],
            )
    return {
        "daily_budget": current_daily_budget,
        "plan_count_min": plan_count_min,
        "plan_count_max": plan_count_max,
        "platforms": data["platforms"],
        "objectives": data["objectives"],
        "plan": plan,
        "tree": tree,
        "creative": creative,
        "period": period_mod.brand_period_response(conn, org_id, brand_id),
    }


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
    plan_count_min, plan_count_max = _plan_count_bounds(conn, brand_id)
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
    plan_row = _latest_task_row(conn, brand_id, TASK_TYPE)
    if plan_row is None or plan_row["status"] != "succeeded":
        raise web.ApiError(400, "no_plan", NO_PLAN_TO_EXPAND_MESSAGE)

    plan_scope = plan_row.get("context_scope_json") or {}
    daily_budget = plan_scope.get("daily_budget", 0)
    plans, failure = plan_mod.build_plans(plan_row.get("rendered_output") or "", daily_budget)
    if failure is not None or not (0 <= body.plan_index < len(plans)):
        raise web.ApiError(400, "plan_index_out_of_range", PLAN_INDEX_OUT_OF_RANGE_MESSAGE)

    gateway.check_spend_cap(conn, org_id=org_id)
    if _display_task_row(conn, brand_id, TREE_TASK_TYPE)[1]:
        raise _already_running_error()
    period = schedule_repo.get_latest_period(conn, org_id, brand_id)
    if not background_enqueue(
        f"background.{TREE_TASK_TYPE}", org_id=org_id, lock=f"{TREE_TASK_TYPE}:{brand_id}",
        brand_id=brand_id, plan_index=body.plan_index, plan_task_id=plan_row["id"],
        campaign_period_id=period["id"] if period else None,
    ):
        raise _already_running_error()
    return _brand_response(conn, brand_id, org_id)


def _run_creative(conn, brand_id: str, org_id: str) -> dict:
    """票 01：把已展開的活動樹每個最深層節點各配一份內容。票 05-1：這裡只做驗證——重讀
    最新一次成功的 `schedule_tree` 那列，確認它至少有一個最深層節點；找不到成功的樹、或
    樹沒有任何最深層節點，都在 enqueue 之前回人話 400（比照 `_run_tree` 的
    「先驗證、後花錢」次序）。真正產內容、把來源樹的 id 凍結進 `context_scope_json`
    （frozen decision 5）在 `app/schedule/jobs.py` 的 `schedule_creative()`——`tree_row["id"]`
    同樣在這裡釘進 job 參數，理由見 `_run_tree()` 的 fix round 1 註解。"""
    tree_row = _latest_task_row(conn, brand_id, TREE_TASK_TYPE)
    if tree_row is None or tree_row["status"] != "succeeded":
        raise web.ApiError(400, "no_tree", NO_TREE_TO_GENERATE_CREATIVE_MESSAGE)
    tree = tree_mod.tree_from_task_row(tree_row)
    ad_node_names = _leaf_ad_node_names(tree["nodes"]) if tree["failure"] is None else []
    if not ad_node_names:
        raise web.ApiError(400, "no_tree", NO_TREE_TO_GENERATE_CREATIVE_MESSAGE)

    gateway.check_spend_cap(conn, org_id=org_id)
    if _display_task_row(conn, brand_id, CREATIVE_TASK_TYPE)[1]:
        raise _already_running_error()
    current_period = schedule_repo.get_latest_period(conn, org_id, brand_id)
    if not background_enqueue(
        f"background.{CREATIVE_TASK_TYPE}", org_id=org_id,
        lock=f"{CREATIVE_TASK_TYPE}:{brand_id}", brand_id=brand_id, tree_task_id=tree_row["id"],
        campaign_period_id=current_period["id"] if current_period else None,
    ):
        raise _already_running_error()
    return _brand_response(conn, brand_id, org_id)


def _run_plan(conn, brand_id: str, org_id: str, body: "PlanRequest") -> dict:
    """票 07／08：出 N 個方案。票 05-1：這裡只做驗證（產品／平台／目標／方案數存在且
    合法、日預算已設定、月費上限沒破）＋enqueue；真正打代理、寫 prompt 在
    `app/schedule/jobs.py` 的 `schedule_plan()`（worker 執行，見該檔檔頭「為什麼分兩邊」）。
    """
    _validate_products(conn, brand_id, body.product_ids)
    data = _load_platform_data()
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
    period_id = schedule_repo.upsert_draft_period(
        conn, org_id, brand_id,
        name=f"{start_date.isoformat()} ~ {end_date.isoformat()}",
        start_date=start_date, end_date=end_date, daily_budget=daily_budget,
        currency=period_mod.CURRENCY,
    )

    gateway.check_spend_cap(conn, org_id=org_id)
    if _display_task_row(conn, brand_id, TASK_TYPE)[1]:
        raise _already_running_error()
    if not background_enqueue(
        f"background.{TASK_TYPE}", org_id=org_id, lock=f"{TASK_TYPE}:{brand_id}",
        brand_id=brand_id, product_ids=body.product_ids, platform=body.platform,
        objective=body.objective, promotion_note=body.promotion_note,
        plan_count=body.plan_count, campaign_period_id=period_id,
    ):
        raise _already_running_error()
    return _brand_response(conn, brand_id, org_id)


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

    plan_row = _latest_task_row(conn, brand_id, TASK_TYPE)
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
    current_period = schedule_repo.get_latest_period(conn, actor.org_id, brand_id)
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


NO_TREE_TO_BIND_MESSAGE = "還沒有成功產生的活動樹可以綁定，請先展開活動樹。"
BIND_FAILURE_MESSAGE = "配對失敗，請檢查名稱是否完全相符"


def _run_bind(conn, brand_id: str, org_id: str) -> dict:
    """票 11：把手動在平台上發布的活動用名稱精準比對回這棵樹的第一層節點——SQL '=' 比對，
    區分大小寫、不 trim（settled 段第 2 點）。名稱只用一次：已經有 bound_external_id 的
    節點跳過不重比對，之後一律靠存下來的 id 找資料（settled 段第 3 點，改名不斷線）。
    零筆或兩筆以上都是失敗，不猜——整批回同一句訊息，不逐節點分開講（settled 段第 4 點）。
    還沒有成功展開過的活動樹，先擋在比對之前（比照 `_run_tree` 的「先驗證、後動作」次序）。
    """
    tree_row = _latest_task_row(conn, brand_id, TREE_TASK_TYPE)
    if tree_row is None or tree_row["status"] != "succeeded":
        raise web.ApiError(400, "no_tree", NO_TREE_TO_BIND_MESSAGE)

    scope = tree_row.get("context_scope_json") or {}
    bound_external_ids = dict(scope.get("bound_external_ids") or {})
    tree = tree_mod.tree_from_task_row(tree_row)

    account_ids = meta_repo.bound_account_ids_for_brand(conn, org_id, brand_id)
    any_failure = False
    newly_bound = False
    for node in tree["nodes"]:
        if node["bound_external_id"] is not None:
            continue
        matches = meta_repo.campaign_ids_by_exact_name(conn, org_id, account_ids, node["name"])
        if len(matches) == 1:
            bound_external_ids[node["name"]] = matches[0]
            newly_bound = True
        else:
            any_failure = True

    if newly_bound:
        conn.execute(
            "UPDATE llm_task SET context_scope_json = %s WHERE id = %s",
            (jsonb({**scope, "bound_external_ids": bound_external_ids}), tree_row["id"]),
        )
        conn.commit()

    response = _brand_response(conn, brand_id, org_id)
    # settled 段第 7 點：這個欄位只在這支路由的回應裡非空，且從不落地——重讀
    # tree_from_task_row() 之後才蓋上，GET／plan／tree／reject 走的都是同一個
    # tree_from_task_row()，一律留 null。
    response["tree"]["bind_failure"] = BIND_FAILURE_MESSAGE if any_failure else None
    return response


def _run_approve(conn, brand_id: str, org_id: str, actor: str) -> dict:
    """票 01：核准目前展開的活動樹——金額、雜湊都在這裡算，`approval` 表本身完全不知道
    「樹」長什麼樣子（集裝箱憲章）。先驗證有沒有一棵可以核准的樹，再落地（比照
    `_run_tree`／`_run_bind` 的「先驗證、後動作」次序）。舊列從不覆寫，一次核准就是
    一列新的（ticket 明文）。"""
    tree_row = _latest_task_row(conn, brand_id, TREE_TASK_TYPE)
    if tree_row is None or tree_row["status"] != "succeeded":
        raise web.ApiError(400, "no_tree", NO_TREE_TO_APPROVE_MESSAGE)
    tree = tree_mod.tree_from_task_row(tree_row)
    if tree["failure"] is not None:
        raise web.ApiError(400, "no_tree", NO_TREE_TO_APPROVE_MESSAGE)

    approval_mod.approve(
        conn, org_id=org_id, brand_id=brand_id, scope_type=APPROVAL_SCOPE_TYPE,
        scope_ref=tree["task_id"], content_hash=_tree_content_hash(tree),
        amount=_sum_daily_amounts(tree["nodes"]), actor=actor,
    )
    # ADR 0053 決策 1：核准這一press＝「這期真的要投」，草稿在這裡變 running。找不到草稿
    # （例如已經核准過一次）就什麼都不做——approval.py 自己已經 commit 過，這裡是同一個
    # 請求裡緊接著的下一個落地動作，不是另開一支路由。
    schedule_repo.approve_draft_period(conn, org_id, brand_id)
    return _brand_response(conn, brand_id, org_id)


def _run_approve_revoke(conn, brand_id: str, org_id: str, actor: str) -> dict:
    """撤回目前有效的核准；沒有可撤回的核准就是沒事發生（比照畫面只在有核准時才會顯示
    「撤回」按鈕，這裡不必為了「按到一個畫面上不該出現的按鈕」另開一條錯誤訊息）。"""
    approval_row = approval_mod.latest(
        conn, org_id=org_id, brand_id=brand_id,
        scope_type=APPROVAL_SCOPE_TYPE,
    )
    if approval_row is not None:
        approval_mod.revoke(conn, approval_id=approval_row["id"], org_id=org_id, actor=actor)
    return _brand_response(conn, brand_id, org_id)


def _run_settle(conn, brand_id: str, org_id: str, period_id: str, actor: str) -> dict:
    """票 T2b（ADR 0053 §3／§4）：結算——算法／落地都在 `period.settle()`（租戶界線在
    `schedule_repo.get_period()` 的 WHERE 裡，不是靠 `require_brand` 就夠——`brand_id`
    對了不代表 `period_id` 也是這個組織的，ticket 矛盾檢查段第三點），這裡只管把失敗代碼
    翻成 HTTP 錯誤。"""
    error = period_mod.settle(conn, org_id=org_id, brand_id=brand_id, period_id=period_id,
                               actor=actor)
    if error == "not_found":
        raise web.NotFoundKind("檔期")
    if error == "not_started":
        raise web.ApiError(400, "not_started", period_mod.NOT_STARTED_MESSAGE)
    return _brand_response(conn, brand_id, org_id)


@router.get("/brands/{brand_id}")
def get_schedule(request: Request, brand_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    return _brand_response(web.conn, brand_id, actor.org_id)


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
