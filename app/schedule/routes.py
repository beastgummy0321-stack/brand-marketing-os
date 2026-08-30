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
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request
from pydantic import BaseModel

import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core import approval as approval_mod
from app.core import rule_cards
from app.core.db import APP_DIR, jsonb
from app.llm import context_compiler, gateway, methodology, providers
from app.meta import repository as meta_repo
from app.schedule import creative as creative_mod
from app.schedule import plan as plan_mod
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
DEPARTMENT_FILE = APP_DIR / "departments" / "ads" / "schedule.md"
TREE_DEPARTMENT_FILE = APP_DIR / "departments" / "ads" / "campaign_tree.md"
# 票 01 frozen decision 2：這是創意部門的第一個任務檔，`app/departments/` 底下新增一個
# 資料夾，程式一行不改（ADR 0028）——這裡只是讀檔路徑，不是新的 Python 套件。
CREATIVE_DEPARTMENT_FILE = APP_DIR / "departments" / "creative" / "ad_creative.md"
# 平台／行銷目標資料檔（票 08 §3）：改這個檔案不必重新部署程式；每次讀都重新讀檔
# （不快取到模組層），比照 DEPARTMENT_FILE 既有的讀法。
PLATFORM_DATA_FILE = APP_DIR / "schedule" / "platform_objectives.json"

# 唯一的供應商實例，比照 app/brand_web/routes_library.py 既有寫法：測試用
# `mock.patch.object(routes, "PROVIDER", FakeProvider(...))` 換掉，不動這裡的呼叫端程式碼。
PROVIDER = providers.AnthropicProvider()


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


def _current_month_window() -> tuple:
    """[月初, 下月初) 半開區間——跟 app/meta/routes.py brand_spend 同一個窗口（票 11
    settled 段第 9 點：綁定節點的花費／ROAS 用這一期，不是另開一套時間規則）。"""
    today = datetime.now(UTC).date()
    month_start = today.replace(day=1)
    month_end = (month_start + timedelta(days=32)).replace(day=1)
    return month_start, month_end


def _fill_node_spend(conn, org_id: str, brand_id: str, tree: dict) -> None:
    """票 11：把已綁定的第一層節點對上 ticket 05 的當月花費／ROAS——一棵樹裡沒有任何
    節點綁定，就完全不查（省一次查詢），比對用 campaign_id，不重讀名稱。"""
    bound_ids = {n["bound_external_id"] for n in tree["nodes"] if n["bound_external_id"]}
    if not bound_ids:
        return
    account_ids = meta_repo.bound_account_ids_for_brand(conn, org_id, brand_id)
    month_start, month_end = _current_month_window()
    summary = meta_repo.spend_summary(conn, org_id, account_ids, month_start, month_end)
    by_campaign_id = {c["campaign_id"]: c for c in summary["campaigns"]}
    for node in tree["nodes"]:
        campaign = by_campaign_id.get(node["bound_external_id"])
        if campaign is not None:
            node["spend"] = campaign["spend"]
            node["roas"] = campaign["roas"]


# ---------------------------------------------------------------------------
# 票 01（ADR 0040）：核准——花錢煞車。scope_type 固定 "schedule_tree"，scope_ref 見
# app.core.approval 表 migration 的欄位註解：用 brand_id，不是這棵樹自己的 llm_task id
# ——原因寫在那裡（re-expand 每次都開一列新的 llm_task，pin 住舊 id 會讓「核准之後又
# 重新展開」這件事永遠查不到舊核准，content_hash 要抓的「悄悄過期」就永遠不會發生）。
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
    today = datetime.now(UTC).date()
    month_start = today.replace(day=1)
    window_start = max(month_start, approval_date)
    days_elapsed = (today - window_start).days + 1
    approved_amount = float(approval_row["approved_amount"])

    bound_ids = {n["bound_external_id"] for n in tree["nodes"] if n["bound_external_id"]}
    spend_to_date = None
    if bound_ids:
        account_ids = meta_repo.bound_account_ids_for_brand(conn, org_id, brand_id)
        window_end = today + timedelta(days=1)  # 半開區間含今天
        summary = meta_repo.spend_summary(conn, org_id, account_ids, window_start, window_end)
        spend_to_date = summary["total"]["spend"]

    return {
        "expected_to_date": approved_amount * days_elapsed,
        "spend_to_date": spend_to_date,
        "days_elapsed": days_elapsed,
    }


def _fill_approval(conn, org_id: str, brand_id: str, tree: dict) -> None:
    approval_row = approval_mod.latest(
        conn, org_id=org_id, brand_id=brand_id,
        scope_type=APPROVAL_SCOPE_TYPE, scope_ref=brand_id,
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
    return {
        "daily_budget": current_daily_budget,
        "plan_count_min": plan_count_min,
        "plan_count_max": plan_count_max,
        "platforms": data["platforms"],
        "objectives": data["objectives"],
        "plan": plan,
        "tree": tree,
        "creative": creative,
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


def _compile_brand_context(conn, brand_id: str, product_ids: list) -> tuple:
    """對每個選定產品各跑一次 `context_compiler.compile()`，用空行接起來；`knowledge_item_ids`
    取聯集、保留原順序去重（票 07 settled 段「品牌上下文」）。回傳 (prompt 片段,
    knowledge_item_ids, brand_version)。

    ponytail: 品牌層段落（規則／宣稱／品牌事實）會隨產品數重複出現——每個產品各自一次
    compile()，沒有跨產品去重這件事。這是票 07 明文接受的上限（最薄路徑，先求打通），
    真的因為 prompt 太長而困擾時再考慮把品牌層與產品層拆開各編一次。
    """
    texts, knowledge_item_ids, seen = [], [], set()
    brand_version = None
    for product_id in product_ids:
        text, ids, brand_version, _product_version = context_compiler.compile(
            conn, brand_id, product_id
        )
        texts.append(text)
        for kid in ids:
            if kid not in seen:
                seen.add(kid)
                knowledge_item_ids.append(kid)
    return "\n\n".join(texts), knowledge_item_ids, brand_version


def _plan_params_text(platform_label: str, objective_label: str, promotion_note: str,
                       plan_count: int, product_names: list) -> str:
    """這次排程的參數，原樣列給代理看——平台／目標的人話標籤都是呼叫端從資料檔查出來的，
    不是這裡自己編的（票 08：CONTEXT.md 的三詞界線只管外殼自己造詞，轉述資料檔內容不算）。
    產品名稱同理，是 `product` 表裡使用者自己打的字；見 `_validate_products` 為什麼非列不可。"""
    return "\n".join([
        "## 這次排程的參數",
        f"平台：{platform_label}",
        f"這期要投放的產品：{'、'.join(product_names)}",
        f"行銷目標：{objective_label}",
        f"促銷或重點：{promotion_note or '（未填寫）'}",
        f"要幾個方案：{plan_count}",
    ])


NO_PLAN_TO_EXPAND_MESSAGE = "還沒有成功產生的方案可以展開，請先完成排程。"
PLAN_INDEX_OUT_OF_RANGE_MESSAGE = "找不到這個方案編號，請重新選擇。"


def _tree_params_text(platform_label: str, plan_index: int, chosen_plan: dict) -> str:
    """這次要展開的參數：選定的第幾個方案、方案本身的摘要／理由／每個方向的比例與金額，
    原樣列給代理看——跟 `_plan_params_text` 同一個道理，平台標籤是呼叫端從資料檔查出來的，
    方案內容是使用者已經看過、選定的那張卡片，不是這裡自己編的。"""
    lines = [
        "## 這次要展開的參數",
        f"平台：{platform_label}",
        f"選定的方案（第 {plan_index + 1} 個）摘要：{chosen_plan['summary']}",
        f"這個方案的理由：{chosen_plan['reasoning']}",
        "這個方案裡錢怎麼分：",
    ]
    for split in chosen_plan["splits"]:
        lines.append(
            f"- {split['label']}：{split['share'] * 100:.0f}%，"
            f"每日 {split['daily_amount']} 元（{split['why']}）"
        )
    return "\n".join(lines)


def _run_tree(conn, brand_id: str, org_id: str, body: "TreeRequest") -> dict:
    """票 09：選定一個既有方案，展開成三層活動樹——重讀最新一次 `schedule_plan` 那列
    `llm_task`（凍結的預算／平台），選出 `body.plan_index` 那個方案，交給
    `campaign_tree.md` 展開。找不到成功的方案、或方案編號超出範圍，都在打代理之前回
    人話 400（比照 `_run_plan` 的「先驗證、後花錢」次序）。"""
    plan_row = _latest_task_row(conn, brand_id, TASK_TYPE)
    if plan_row is None or plan_row["status"] != "succeeded":
        raise web.ApiError(400, "no_plan", NO_PLAN_TO_EXPAND_MESSAGE)

    plan_scope = plan_row.get("context_scope_json") or {}
    daily_budget = plan_scope.get("daily_budget", 0)
    product_ids = plan_scope.get("product_ids", [])
    platform = plan_scope.get("platform", "")

    plans, failure = plan_mod.build_plans(plan_row.get("rendered_output") or "", daily_budget)
    if failure is not None or not (0 <= body.plan_index < len(plans)):
        raise web.ApiError(400, "plan_index_out_of_range", PLAN_INDEX_OUT_OF_RANGE_MESSAGE)
    chosen_plan = plans[body.plan_index]

    data = _load_platform_data()
    platform_label = next((p["label"] for p in data["platforms"] if p["id"] == platform), platform)

    brand_context, knowledge_item_ids, brand_version = _compile_brand_context(
        conn, brand_id, product_ids
    )
    department_text = TREE_DEPARTMENT_FILE.read_text(encoding="utf-8")
    methodology_result = methodology.compile(conn, METHODOLOGY_TASK_LABELS, brand_id=brand_id)
    params_text = _tree_params_text(platform_label, body.plan_index, chosen_plan)
    prompt = "\n\n".join(
        section for section in
        (department_text, methodology_result.text, params_text, brand_context) if section
    )

    context = gateway.TaskContext(
        # 票 09 settled 段第 6 點：預算凍結自選定方案的來源列，不重讀規則卡——樹要跟使用者
        # 選的那張方案卡一致，不是跟當下的規則卡設定一致。
        context_scope={
            "brand_id": brand_id, "plan_index": body.plan_index, "daily_budget": daily_budget,
            "source_plan_task_id": plan_row["id"],
        },
        knowledge_item_ids=knowledge_item_ids,
        brand_version=brand_version,
        product_version=None,
    )
    gateway.run_task(
        conn, PROVIDER, brand_id=brand_id, task_type=TREE_TASK_TYPE,
        prompt_template_id=TREE_TASK_TYPE, prompt_template_version="v1",
        system=None, messages=[{"role": "user", "content": prompt}], context=context,
        # 展開一棵三層樹比出方案重得多，兩個數字都不是猜的，來源是本系統自己的量測：
        # llm_01M16CM5CS8Q435MVWEJ5BYA9D 的 output_tokens 剛好 16000（TaskOptions 的預設）
        # 而且字串停在 `"value": "最大化轉換次`——撞上限被切斷，不是模型亂回。24000 是那個
        # 已知不夠的數字的 1.5 倍；以同一批量測的 53.9 tok/s（見 TaskOptions.timeout_s 註解）
        # 換算需要 445 秒，所以 timeout 一起抬到 480，仍在 SDK 非串流的 600 秒上限之內。
        # 兩個數字必須一起動：只抬 max_tokens 會把「被截斷」換成「逾時」。
        options=gateway.TaskOptions(max_tokens=24000, timeout_s=480.0),
    )
    return _brand_response(conn, brand_id, org_id)


NO_TREE_TO_GENERATE_CREATIVE_MESSAGE = "還沒有成功展開的活動樹可以產出內容，請先展開活動樹。"


def _creative_params_text(tree: dict) -> str:
    """這次要產內容的活動結構，原樣列給代理看——跟 `_tree_params_text` 同一個道理，這裡
    不解讀 tree 的內容，只把已經算好的 JSON 轉成代理看得懂的字串，好讓代理知道每個最深層
    節點屬於哪個上層、已經有什麼欄位／提醒。"""
    body = {"levels": tree["levels"], "nodes": tree["nodes"]}
    return "\n".join([
        "## 這次要產文案的活動結構",
        json.dumps(body, ensure_ascii=False, indent=2),
    ])


def _run_creative(conn, brand_id: str, org_id: str) -> dict:
    """票 01：把已展開的活動樹每個最深層節點各配一份內容——重讀最新一次成功的
    `schedule_tree` 那列，把它的 id 凍結進這次任務的 `context_scope_json`（frozen decision
    5：之後使用者重新展開樹，不會悄悄改寫已經產出的內容）。找不到成功的樹、或樹沒有任何
    最深層節點，都在打代理之前回人話 400（比照 `_run_tree` 的「先驗證、後花錢」次序）。"""
    tree_row = _latest_task_row(conn, brand_id, TREE_TASK_TYPE)
    if tree_row is None or tree_row["status"] != "succeeded":
        raise web.ApiError(400, "no_tree", NO_TREE_TO_GENERATE_CREATIVE_MESSAGE)
    tree = tree_mod.tree_from_task_row(tree_row)
    ad_node_names = _leaf_ad_node_names(tree["nodes"]) if tree["failure"] is None else []
    if not ad_node_names:
        raise web.ApiError(400, "no_tree", NO_TREE_TO_GENERATE_CREATIVE_MESSAGE)

    plan_scope = tree_row.get("context_scope_json") or {}
    plan_row = gateway.get_task(conn, plan_scope.get("source_plan_task_id") or "")
    plan_row_scope = (plan_row.get("context_scope_json") or {}) if plan_row else {}
    product_ids = plan_row_scope.get("product_ids", [])

    brand_context, knowledge_item_ids, brand_version = _compile_brand_context(
        conn, brand_id, product_ids
    )
    department_text = CREATIVE_DEPARTMENT_FILE.read_text(encoding="utf-8")
    params_text = _creative_params_text(tree)
    prompt = "\n\n".join(
        section for section in (department_text, params_text, brand_context) if section
    )

    context = gateway.TaskContext(
        # frozen decision 5：字面契約只有這三個鍵——凍結來源樹的 id，不是凍結當下算出的
        # 節點名稱清單，讀回來的時候（`_creative_ad_node_names`）永遠重新從這棵凍結的樹算。
        context_scope={
            "brand_id": brand_id, "source_tree_task_id": tree_row["id"],
            "plan_index": tree["plan_index"],
        },
        knowledge_item_ids=knowledge_item_ids,
        brand_version=brand_version,
        product_version=None,
    )
    gateway.run_task(
        conn, PROVIDER, brand_id=brand_id, task_type=CREATIVE_TASK_TYPE,
        prompt_template_id=CREATIVE_TASK_TYPE, prompt_template_version="v1",
        system=None, messages=[{"role": "user", "content": prompt}], context=context,
        # frozen decision 6：跟 `_run_tree` 完全相同的兩個數字，來源見那裡的註解——不是
        # 新猜的，是同一批量測的重用；這裡不重新量測、不重新定義。
        options=gateway.TaskOptions(max_tokens=24000, timeout_s=480.0),
    )
    return _brand_response(conn, brand_id, org_id)


def _run_plan(conn, brand_id: str, org_id: str, body: "PlanRequest") -> dict:
    product_names = _validate_products(conn, brand_id, body.product_ids)
    data = _load_platform_data()
    _validate_platform_and_objective(data, body.platform, body.objective)
    _validate_plan_count(conn, brand_id, body.plan_count)

    daily_budget = rule_cards.get_value(conn, brand_id, "schedule_budget", "daily_budget")
    if not daily_budget:
        raise web.ApiError(400, "budget_not_set", plan_mod.BUDGET_NOT_SET_MESSAGE)

    platform_label = next(p["label"] for p in data["platforms"] if p["id"] == body.platform)
    objective_label = next(
        o["label"] for o in data["objectives"]
        if o["platform"] == body.platform and o["value"] == body.objective
    )

    brand_context, knowledge_item_ids, brand_version = _compile_brand_context(
        conn, brand_id, body.product_ids
    )
    department_text = DEPARTMENT_FILE.read_text(encoding="utf-8")
    methodology_result = methodology.compile(conn, METHODOLOGY_TASK_LABELS, brand_id=brand_id)
    params_text = _plan_params_text(
        platform_label, objective_label, body.promotion_note, body.plan_count, product_names
    )
    prompt = "\n\n".join(
        section for section in
        (department_text, methodology_result.text, params_text, brand_context) if section
    )

    context = gateway.TaskContext(
        # 這次跑的參數凍結在跑的當下（票 07 settled 段「No migration」延伸到票 08 的新
        # 欄位）：之後改規則卡或資料檔不會悄悄改寫這張已經出過的方案。
        context_scope={
            "brand_id": brand_id, "product_ids": body.product_ids, "daily_budget": daily_budget,
            "platform": body.platform, "objective": body.objective,
            "promotion_note": body.promotion_note, "plan_count": body.plan_count,
            # plan_count 票 10-feedback-entries 補：拒絕方案重排要能原樣重跑同一組參數，
            # 缺了這欄會找不到「上次要幾個方案」。
        },
        knowledge_item_ids=knowledge_item_ids,
        brand_version=brand_version,
        product_version=None,  # 一次任務跨 N 個產品，這個欄位只吃單一值，見票 07 settled 段
    )
    gateway.run_task(
        conn, PROVIDER, brand_id=brand_id, task_type=TASK_TYPE,
        prompt_template_id=TASK_TYPE, prompt_template_version="v1",
        system=None, messages=[{"role": "user", "content": prompt}], context=context,
        # 開網路搜尋（ADR 0005）：代理排方案前先查這期有沒有真正相關的節慶或時事（票 08）。
        # 查詢不是排程的先決條件——查不到、查失敗，run_task 本身不受影響，一樣正常出方案
        # （見 app/llm/providers.py AnthropicProvider.complete() 對搜尋結果區塊的處理）。
        options=gateway.TaskOptions(tools=[providers.WEB_SEARCH_TOOL]),
    )
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

    rerun_body = PlanRequest(
        product_ids=scope.get("product_ids", []),
        platform=scope.get("platform", ""),
        objective=scope.get("objective", ""),
        promotion_note=scope.get("promotion_note", ""),
        plan_count=scope.get("plan_count", 3),
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
        scope_ref=brand_id, content_hash=_tree_content_hash(tree),
        amount=_sum_daily_amounts(tree["nodes"]), actor=actor,
    )
    return _brand_response(conn, brand_id, org_id)


def _run_approve_revoke(conn, brand_id: str, org_id: str, actor: str) -> dict:
    """撤回目前有效的核准；沒有可撤回的核准就是沒事發生（比照畫面只在有核准時才會顯示
    「撤回」按鈕，這裡不必為了「按到一個畫面上不該出現的按鈕」另開一條錯誤訊息）。"""
    approval_row = approval_mod.latest(
        conn, org_id=org_id, brand_id=brand_id,
        scope_type=APPROVAL_SCOPE_TYPE, scope_ref=brand_id,
    )
    if approval_row is not None:
        approval_mod.revoke(conn, approval_id=approval_row["id"], org_id=org_id, actor=actor)
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
