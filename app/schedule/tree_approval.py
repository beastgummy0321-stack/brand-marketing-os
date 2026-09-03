"""app/schedule/tree_approval.py — 核准這件事的錢：簽的是哪一份、核准了多少、花超了沒有。

從 routes.py 搬出來（2026-09-03 邊界盤點第二張），一行邏輯都沒改。集裝箱憲章 §7：
算錢或算核准金額的函式，永遠不住在 routes 檔裡。決策本體是 ADR 0040。
"""

import hashlib
import json
from datetime import datetime, timedelta

from app.core import approval as approval_mod
from app.core import settings as coresettings
from app.meta import repository as meta_repo

# ---------------------------------------------------------------------------
# 票 01（ADR 0040）：核准——花錢煞車。scope_type 固定 "schedule_tree"，scope_ref 存的是
# 被核准的那棵樹自己的 `llm_task` id——事後查「我那天到底簽了哪一棵」靠的就是這一欄。
# 查詢不靠它（`approval.latest()` 只用品牌＋類型找最新一筆），因為樹每重新展開一次就是
# 全新一列；拿當下的 id 去查會永遠查不到上一次的核准，畫面就會顯示「從沒核准過」而不是
# 「核准過、但內容已經變了」。「簽的是哪一份」與「還是不是同一份」是兩件事：前者是
# scope_ref，後者是 content_hash。
# ---------------------------------------------------------------------------
APPROVAL_SCOPE_TYPE = "schedule_tree"


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
