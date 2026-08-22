# -*- coding: utf-8 -*-
"""app/ads/reading_hypotheses.py — 假設結案週邊讀寫（票 10-split-reading-py）。

從 `app/ads/reading.py`（凍結 1039 行、不得再長）拆出來的小檔——這幾個函式原樣搬過來，
只有 reading.py 這一個呼叫端，不是新開的容器（集裝箱憲章：拆檔不是拆模組）。

`resolve_hypotheses()` 與 `_ledger_confidence()` 本身**沒有**跟著搬過來：後者要用到
`MIN_CONVERSIONS_FOR_DIRECTIONAL_CALL`——D3 決定「門檻常數留在 reading.py，跟 judge()
放一起」，搬 `_ledger_confidence` 出來會逼著這個門檻常數也跟著搬，或是逼這裡回頭
import reading.py（集裝箱憲章：拆出來的檔不准 import 回 reading.py）。兩條路都不
乾淨，所以兩個函式留在 reading.py，靠 import 呼叫這裡的 `_conversions_for_hypothesis`。
"""

from typing import Optional

from app.ads import performance as ads_performance
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi
from app.core import interrupts as core_interrupts

# 假設結案（票 #53，決策 0030 第三節第 8 點）：判讀頁列出這期的策略假設，三選一結案。
PENDING_HYPOTHESIS_STATUSES = ("proposed", "testing")

# 學習條目掛滿幾期都沒被重新驗證，就該提醒複查——只提醒、不擋路、不自動下架（決策 0013）。
LEDGER_REVALIDATION_WINDOW_CYCLES = 3


def _product_totals(conn, brand_id: str, cycle_id: str) -> dict:
    """各產品的成效加總。成效資料沒帶產品時回空 dict——不假裝分得出來。"""
    rows = conn.execute(
        "SELECT product_id, COALESCE(SUM(impressions),0) impressions,"
        " COALESCE(SUM(clicks),0) clicks, COALESCE(SUM(spend),0) spend,"
        " COALESCE(SUM(conversions),0) conversions, COALESCE(SUM(revenue),0) revenue,"
        " COUNT(*) rows FROM performance_snapshot"
        " WHERE brand_id = ? AND campaign_cycle_id = ? AND quarantined = 0"
        " AND product_id IS NOT NULL GROUP BY product_id",
        (brand_id, cycle_id),
    ).fetchall()
    result = {}
    for row in rows:
        data = dict(row)
        data["kpis"] = ads_performance.compute_kpis(data)
        result[data["product_id"]] = data
    return result


def _pending_hypothesis_reviews(conn, brand_id: str, cycle_id: str, cycle_row: dict) -> list:
    """判讀頁顯示用：只留目前仍待結案的假設——使用者確認後 status 更新，下次讀取就自動
    從清單消失，不必重跑一次判讀（票 #53）。"""
    stored = (cycle_row.get("result") or {}).get("hypothesis_reviews") or []
    if not stored:
        return []
    current_status = {h["id"]: h["status"]
                      for h in ads_repo.list_cycle_hypotheses(conn, brand_id, cycle_id)}
    return [r for r in stored if current_status.get(r["id"]) in PENDING_HYPOTHESIS_STATUSES]


def _conversions_for_hypothesis(conn, brand_id: str, cycle_id: str,
                                product_id: Optional[str]) -> int:
    """樣本數＝判讀當下該產品（或整期）的轉換數，程式帶入不猜（決策 0030 第 11 點）。"""
    if product_id:
        totals = _product_totals(conn, brand_id, cycle_id).get(product_id)
        return int(totals["conversions"]) if totals else 0
    return int(ads_performance.totals(conn, brand_id, cycle_id).get("conversions") or 0)


def mark_stale_learnings_for_revalidation(conn, brand_id: str) -> int:
    """「第 N 期再驗一次」：這個品牌又開過幾期（依 `campaign_cycle.created_at` 排序），
    超過 `LEDGER_REVALIDATION_WINDOW_CYCLES` 期還沒被下架，就把 `needs_revalidation` 標成 1。
    掛在 `app/ads/nextcycle.py` 的 `build()`，每次判讀完成都會順手檢查一次。回傳這次新標記
    的筆數。找不到來源期別（`source_cycle_id` 為空，例如前朝教訓訪談自述）的條目跳過，
    不硬猜「第幾期」。
    """
    cycle_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM campaign_cycle WHERE brand_id = ? ORDER BY created_at", (brand_id,)
    ).fetchall()]
    if len(cycle_ids) < LEDGER_REVALIDATION_WINDOW_CYCLES:
        return 0
    index = {cid: i for i, cid in enumerate(cycle_ids)}
    latest_index = len(cycle_ids) - 1

    updated = 0
    for entry in ads_repo.list_learning_ledger(conn, brand_id):
        if entry["needs_revalidation"] or not entry["source_cycle_id"]:
            continue
        origin = index.get(entry["source_cycle_id"])
        if origin is None:
            continue
        if latest_index - origin >= LEDGER_REVALIDATION_WINDOW_CYCLES:
            bi.mark_learning_ledger_needs_revalidation(conn, brand_id, entry["id"])
            updated += 1
    if updated:
        conn.commit()
    return updated


def _flag_unresolved_hypotheses(conn, brand_id: str, cycle_id: str) -> None:
    """期末結算（finalize，全系統唯一把檔期轉 CLOSED 之處）時，這期還留著沒結案的假設
    丟一張卡進打斷佇列補網（決策 0030 第三節第 9 點：判讀頁是主入口，這裡只是補漏）。"""
    pending = [h for h in ads_repo.list_cycle_hypotheses(conn, brand_id, cycle_id)
              if h["status"] in PENDING_HYPOTHESIS_STATUSES]
    if not pending:
        return
    core_interrupts.enqueue(
        conn, category="hypothesis_unresolved",
        dedupe_key=f"hypothesis_unresolved:{cycle_id}",
        message="這期還有策略假設沒結案，去看看", brand_id=brand_id, campaign_cycle_id=cycle_id,
        action_url=f"/app/brands/{brand_id}/campaigns/{cycle_id}",
    )
    conn.commit()
