"""app/schedule/state.py — 排程畫面的組裝：讀 llm_task 的列、拼出品牌那一頁要的形狀。

從 routes.py 搬出來（2026-09-03 邊界盤點），一行邏輯都沒改。留在 routes.py 的判準：
一個符號只有在「離開 HTTP 端點就沒有存在理由」時才配留在那裡。這裡的每一支就算改用
CLI 驅動也照樣需要，所以它們是工作，不是端點。

`_brand_response()` 把核准那一塊交給 `tree_approval._fill_approval()`——本檔不算任何錢。
本檔曾經 import `routes` 只為了那一行，跟 `routes` import 本檔形成雙向環，同一天的第二張票
（`tree_approval.py`）把它關掉了：**本檔不得再 import `app.schedule.routes`**。
"""

import json
from datetime import timedelta

from app.brand_intelligence import personas
from app.brand_intelligence import repository as bi_repo
from app.core import rule_cards
from app.core import settings as coresettings
from app.core.db import APP_DIR
from app.llm import gateway
from app.meta import repository as meta_repo
from app.schedule import binding as binding_mod
from app.schedule import creative as creative_mod
from app.schedule import period as period_mod
from app.schedule import plan as plan_mod
from app.schedule import repository as schedule_repo
from app.schedule import tree_approval

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
# 票 01（T6c）：成效判讀，第四個 task_type——決定 7，用既有的 `performance_reading`
# （`app/llm/providers.py` 已註冊、原本零呼叫者）。方法論走既有對照表「成效判讀／下期草案」
# 那一列（`ab-testing.md`＋`ads-core.md`＋`ads-commerce.md`），這張票是接線不是寫方法論
# ——不新增部門任務檔，prompt 組法見 `app/schedule/diagnosis.py`。
DIAGNOSIS_TASK_TYPE = "performance_reading"
DIAGNOSIS_METHODOLOGY_TASK_LABELS = ["成效判讀／下期草案"]
# 票 T1 站③收尾：曾經跟上面共用一張清單餵給三支 job，副作用是計畫／活動樹的方法論區塊
# 平白多讀到創意矩陣、Meta 版位格式規格這兩份不相干的檔案（21,432 → 38,074 字，＋78%）。
# 改成 schedule_creative 專屬一張清單，計畫／活動樹維持只吃「檔期計畫生成」。
CREATIVE_METHODOLOGY_TASK_LABELS = ["廣告內容生成"]
DEPARTMENT_FILE = APP_DIR / "departments" / "ads" / "schedule.md"
TREE_DEPARTMENT_FILE = APP_DIR / "departments" / "ads" / "campaign_tree.md"
# 票 01 frozen decision 2：這是創意部門的第一個任務檔，`app/departments/` 底下新增一個
# 資料夾，程式一行不改（ADR 0028）——這裡只是讀檔路徑，不是新的 Python 套件。
CREATIVE_DEPARTMENT_FILE = APP_DIR / "departments" / "creative" / "ad_creative.md"
# 通路目錄資料檔（票 08 §3；票 T4／ADR 0056 改名並加上通路能力旗標）：改這個檔案不必
# 重新部署程式；每次讀都重新讀檔（不快取到模組層），比照 DEPARTMENT_FILE 既有的讀法。
PLATFORM_DATA_FILE = APP_DIR / "schedule" / "channel_catalogue.json"


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


def _leaf_ad_nodes(nodes: list) -> list[dict]:
    """活動樹最深層（沒有 `children` 的）節點，照文件順序（深度優先、前序）——票 01：
    內容跟這一層的節點一一對應，不是每一層都配一份。每個元素 `{"node_key", "name"}`
    （票 T3d，ADR 0055 §1：身分是 `node_key`，`name` 只給代理比對用）。"""
    result = []
    for node in nodes:
        if node["children"]:
            result.extend(_leaf_ad_nodes(node["children"]))
        else:
            result.append({"node_key": node["node_key"], "name": node["name"]})
    return result


def _creative_ad_nodes(conn, creative_row: dict, org_id: str, brand_id: str) -> list[dict]:
    """從這一列內容任務凍結的 `source_tree_task_id` 找回當時的那棵樹，重算最深層節點——
    frozen decision 5：只能讀凍結住的那一列，不能讀「最新一次的樹」。"""
    source_tree_task_id = (creative_row.get("context_scope_json") or {}).get("source_tree_task_id")
    if not source_tree_task_id:
        return []
    tree_row = gateway.get_task(conn, source_tree_task_id)
    if tree_row is None:
        return []
    tree = binding_mod.tree_with_bindings(conn, tree_row, org_id, brand_id)
    return _leaf_ad_nodes(tree["nodes"])


def _knowledge_gaps(conn, brand_id: str) -> list[str]:
    """票 plan-quality/03：哪些品牌檔案分類是空的——讀跟 `context_compiler.compile()`
    同一批查詢（品牌事實只算 confirmed、宣稱不分產品），通知才不會跟 plan prompt 的內容
    互相矛盾。順序固定：品牌事實、典型客人、宣稱；產品事實不在這裡，那是逐產品的事，表單
    已經處理過品牌沒有產品的情況。"""
    gaps = []
    if not bi_repo.list_brand_facts(conn, brand_id, status="confirmed"):
        gaps.append("品牌事實")
    if not personas.list_personas(conn, brand_id):
        gaps.append("典型客人")
    if not bi_repo.list_claims_for_brand(conn, brand_id):
        gaps.append("宣稱")
    return gaps


def _brand_response(conn, brand_id: str, org_id: str) -> dict:
    current_daily_budget = rule_cards.get_value(conn, brand_id, "schedule_budget", "daily_budget")
    plan_count_min, plan_count_max = _plan_count_bounds(conn, brand_id)
    data = _load_platform_data()
    row, plan_running = _display_task_row(conn, brand_id, TASK_TYPE)
    plan = plan_mod.plan_from_task_row(row) if row is not None else None
    if plan is not None and plan_running:
        plan["running"] = True
    tree_row, tree_running = _display_task_row(conn, brand_id, TREE_TASK_TYPE)
    tree = (binding_mod.tree_with_bindings(conn, tree_row, org_id, brand_id)
            if tree_row is not None else None)
    if tree is not None and tree_running:
        tree["running"] = True
    if tree is not None:
        _fill_node_spend(conn, org_id, brand_id, tree)
        tree_approval._fill_approval(conn, org_id, brand_id, tree)
    creative_row, creative_running = _display_task_row(conn, brand_id, CREATIVE_TASK_TYPE)
    creative = None
    if creative_row is not None:
        ad_nodes = _creative_ad_nodes(conn, creative_row, org_id, brand_id)
        creative = creative_mod.creative_from_task_row(creative_row, ad_nodes)
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
        "knowledge_gaps": _knowledge_gaps(conn, brand_id),
        "platforms": data["platforms"],
        "objectives": data["objectives"],
        "plan": plan,
        "tree": tree,
        "creative": creative,
        "period": period_mod.brand_period_response(conn, org_id, brand_id),
        "next_period_suggestion": period_mod.next_period_suggestion(conn, org_id, brand_id),
    }
