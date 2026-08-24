# -*- coding: utf-8 -*-
"""app/ads/reading_hypotheses.py — 假設結案週邊讀寫（票 10-split-reading-py）。

從 `app/ads/reading.py`（凍結 1039 行、不得再長）拆出來的小檔——這幾個函式原樣搬過來，
只有 reading.py 這一個呼叫端，不是新開的容器（集裝箱憲章：拆檔不是拆模組）。

`resolve_hypotheses()` 與 `_ledger_confidence()` 本身**沒有**跟著搬過來：後者要用到
`MIN_CONVERSIONS_FOR_DIRECTIONAL_CALL`——D3 決定「門檻常數留在 reading.py，跟 judge()
放一起」，搬 `_ledger_confidence` 出來會逼著這個門檻常數也跟著搬，或是逼這裡回頭
import reading.py（集裝箱憲章：拆出來的檔不准 import 回 reading.py）。兩條路都不
乾淨，所以兩個函式留在 reading.py，靠 import 呼叫這裡的 `comparison_cells()`。
"""

from typing import Optional

from app.ads import performance as ads_performance
from app.ads import repository as ads_repo
from app.ads import settlement as ads_settlement
from app.brand_intelligence import repository as bi
from app.core import interrupts as core_interrupts

# 假設結案（票 #53，決策 0030 第三節第 8 點）：判讀頁列出這期的策略假設，三選一結案。
PENDING_HYPOTHESIS_STATUSES = ("proposed", "testing")

# R4-late-data-downstream 契約第 4 點（B0-34）：已簽核假設不能因為補件重判自動翻案，
# 但要告訴使用者依據換了。
STALE_HYPOTHESIS_NOTE = "結論依據已變，建議重看"

# R2-learning-honesty：一條「A比B好」的假設要算「做過對照」，這期至少要有兩個切角
# （experiment_cell）真的投放過、有成效資料回得來——只投 1 個切角就沒有 B 邊可比，
# 不管整體判讀方向多明確都不算數（契約第 3 點）。
MIN_COMPARISON_CELLS = 2

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


def comparison_cells(conn, brand_id: str, cycle_id: str,
                     product_id: Optional[str]) -> list:
    """這期真的投放過、有成效資料回得來的切角（experiment_cell），供假設結案畫面並排
    出示 A／B 兩邊的實際數字（切角名／樣本數／CPA／ROAS／花費——契約第 2 點），也用它的
    筆數判斷這條假設這期是不是「真的做過對照」（契約第 3 點：少於
    `MIN_COMPARISON_CELLS` 就不算，不管整體判讀方向多明確）。

    只算走完 performance_snapshot → external_ad_mapping → publishing_package →
    experiment_cell 這條鏈、真的對回成效資料的切角（比照 `reading_assets.asset_totals()`
    的既有 JOIN 寫法，改成依 `experiment_cell_id` 分組）——矩陣頁上還沒生成主題、
    沒真的投放過的「＋生成主題」空格不算數，不然又會把沒發生過的對照算成已驗證
    （鐵則 16）。product_id 給 None 時比照 `_conversions_for_hypothesis` 舊有的整期
    後備行為，不篩產品，算整個檔期的切角。
    """
    sql = ("SELECT pkg.experiment_cell_id cell_id, cell.creative_angle,"
          " COALESCE(SUM(ps.spend),0) spend, COALESCE(SUM(ps.conversions),0) conversions,"
          " COALESCE(SUM(ps.revenue),0) revenue"
          " FROM performance_snapshot ps"
          " JOIN external_ad_mapping xam ON xam.id = ps.external_ad_mapping_id"
          " JOIN publishing_package pkg ON pkg.id = xam.publishing_package_id"
          " JOIN experiment_cell cell ON cell.id = pkg.experiment_cell_id"
          " WHERE ps.brand_id = ? AND ps.campaign_cycle_id = ? AND ps.quarantined = 0")
    params = [brand_id, cycle_id]
    if product_id:
        sql += " AND ps.product_id = ?"
        params.append(product_id)
    sql += " GROUP BY pkg.experiment_cell_id ORDER BY cell.creative_angle"
    rows = conn.execute(sql, params).fetchall()
    result = []
    for row in rows:
        data = dict(row)
        data["kpis"] = ads_performance.compute_kpis(data)
        result.append(data)
    return result


def has_real_comparison(conn, brand_id: str, cycle_id: str, product_id: Optional[str]) -> bool:
    return len(comparison_cells(conn, brand_id, cycle_id, product_id)) >= MIN_COMPARISON_CELLS


def stale_note(conn, brand_id: str, cycle_id: str, hypothesis: dict) -> Optional[str]:
    """已結案（非 pending）的假設，簽核之後這期是不是又真的重判過、數字真的變了——回傳
    提示文字或 None（B0-34）。在讀取時算，不寫回 `strategy_hypothesis`：已簽核的
    verdict／`learning_ledger` 不因為這個提示自動改動，這裡連寫都不寫（比照
    `guard_supported_verdict` 只擋「入帳」那一步的精神，這裡連擋都不用擋，純粹是唯讀的
    旁註）。拿 `updated_at`（簽核當下寫入的唯一時間戳）找簽核當下是第幾版判讀快照，
    跟現在的版次比對數字內容——每次 `settlement.freeze()` 都會多一版，不比對內容的話
    「重跑但沒改變」也會被錯誤標成「依據已變」。
    """
    if hypothesis["status"] in PENDING_HYPOTHESIS_STATUSES:
        return None
    current = ads_settlement.load_snapshot(conn, brand_id, cycle_id)
    if current is None:
        return None
    asof_row = conn.execute(
        "SELECT MAX(version) v FROM settlement_version WHERE brand_id = ? AND"
        " campaign_cycle_id = ? AND created_at <= ?",
        (brand_id, cycle_id, hypothesis["updated_at"]),
    ).fetchone()
    asof_version = asof_row["v"] if asof_row else None
    if asof_version is None or asof_version >= current["settlement_version"]:
        return None
    diffs = ads_settlement.diff_versions(conn, brand_id, cycle_id, asof_version,
                                         current["settlement_version"])
    return STALE_HYPOTHESIS_NOTE if diffs else None


def guard_supported_verdict(conn, brand_id: str, cycle_id: str,
                            product_id: Optional[str], verdict: str) -> tuple:
    """回傳 `(實際要入帳的 verdict, sample_size)`（R2-learning-honesty 契約第 3／4 點）。

    無對照資料的「成立」在這裡被程式端擋下、降級成「看不出來」——這是
    `resolve_hypotheses()` 寫入 `learning_ledger` 前的唯一路口，不信任呼叫端（前端本來
    就不會預選這個選項，但 API 才是真正的信任邊界，擋一次才算數）。sample_size 只算
    這次真的拿來對照的那幾個切角自己的轉換數加總，不是這個產品／這期的全部轉換數
    ——後者會把沒參與這次對照的流量也算進「樣本」，用統計語氣包裝一個沒對照過的數字。
    """
    cells = comparison_cells(conn, brand_id, cycle_id, product_id)
    if verdict == "supported" and len(cells) < MIN_COMPARISON_CELLS:
        verdict = "inconclusive"
    return verdict, int(sum(c["conversions"] for c in cells))


def build_hypothesis_items(conn, brand_id: str, cycle_id: str, pending_hypotheses: list,
                           product_status: dict, product_reasons: dict, cycle_status: str,
                           cycle_reasons: list, status_labels: dict, preselect_fn) -> list:
    """判讀頁假設結案清單（票 #53）：每條待結案假設配一組預選裁決＋這期真的對照過的切角
    （契約第 2 點的並排證據）。`status_labels`／`preselect_fn` 由呼叫端（reading.py）注入
    ——`STATUS_LABELS`／`_preselect_hypothesis_status` 定義在別的檔案，這裡不 import 回去
    （集裝箱憲章：拆出來的檔不准 import 回 reading.py）。

    R2-learning-honesty 契約第 1／3 點：沒真的做過對照（這期切不到 ≥2 個有成效資料的
    切角）就不准預選「成立」或「不成立」——不管整體判讀方向多明確，程式也算不出這條
    「A比B好」的假設今天有沒有對照組可以驗證，預選只能是空（None）。
    """
    items = []
    for h in pending_hypotheses:
        cells = comparison_cells(conn, brand_id, cycle_id, h["product_id"])
        if len(cells) >= MIN_COMPARISON_CELLS:
            status = product_status.get(h["product_id"], cycle_status)
            reasons = product_reasons.get(h["product_id"], cycle_reasons)
            preselect = preselect_fn(status)
            fallback_reason = f"這期判讀結論是「{status_labels[status]}」，依據：" + "；".join(reasons)
        else:
            preselect = None
            fallback_reason = (f"這期只投了 {len(cells)} 個切角，沒有對照組，看不出這條假設"
                               "成不成立" if cells else
                               "這期沒有對得回切角的成效資料，看不出這條假設成不成立")
        items.append({
            "id": h["id"], "statement": h["statement"], "hypothesis_type": h["hypothesis_type"],
            "preselect": preselect, "fallback_reason": fallback_reason,
            "comparison_cells": cells,
        })
    return items


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
