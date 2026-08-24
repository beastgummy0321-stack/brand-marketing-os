# -*- coding: utf-8 -*-
"""app/ads/reading_assets.py — 素材層成效（修憲落地 G2，決策 0035 第二節第 4 點）。

從 `app/ads/reading.py`（凍結 1039 行、不得再長）拆出來的小檔——`_asset_totals()` 原樣
搬過來改成公開的 `asset_totals()`，只有 reading.py 這一個呼叫端，不是新開的容器
（集裝箱憲章：拆檔不是拆模組）。這裡另外放這次新增的白話「哪支廣告拖累最兇」判讀，
同樣的理由：加進 reading.py 會讓它破凍結上限。
"""

from typing import Optional

from app.ads import performance as ads_performance


def asset_totals(conn, brand_id: str, cycle_id: str) -> list:
    """依素材（廣告名稱對回的交接包）分開的成效加總（修憲落地 G2，決策 0035 第二節第 4 點）。

    只有 CSV 匯入時廣告名稱對得回已授權素材的資料列才會出現在這裡（見
    app/ads/performance.py match_asset_mapping）；對不上的資料只算進檔期層，
    這裡不猜、不硬湊一列（鐵則 16）。純顯示用途，不影響 judge() 的門檻判定。

    ponytail：只用既有的 publishing_package_id／external_ad_mapping_id 兩個欄位做 JOIN，
    不新增 schema。Meta API 同步（app/ads/sync.py）目前用 meta_campaign_id 而非 meta_ad_id
    找 mapping，同一活動底下多支廣告時可能對到同一筆 mapping——這是既有的、與本票無關的
    另一個缺口，這裡的清單因此只保證 CSV 這條匯入路徑的歸屬是準的。
    """
    rows = conn.execute(
        "SELECT pkg.id pkg_id, pkg.ad_name asset_name,"
        " COALESCE(SUM(ps.impressions),0) impressions, COALESCE(SUM(ps.clicks),0) clicks,"
        " COALESCE(SUM(ps.spend),0) spend, COALESCE(SUM(ps.conversions),0) conversions,"
        " COALESCE(SUM(ps.revenue),0) revenue"
        " FROM performance_snapshot ps"
        " JOIN external_ad_mapping xam ON xam.id = ps.external_ad_mapping_id"
        " JOIN publishing_package pkg ON pkg.id = xam.publishing_package_id"
        " WHERE ps.brand_id = ? AND ps.campaign_cycle_id = ? AND ps.quarantined = 0"
        " GROUP BY pkg.id ORDER BY revenue DESC", (brand_id, cycle_id),
    ).fetchall()
    result = []
    for row in rows:
        data = dict(row)
        data["kpis"] = ads_performance.compute_kpis(data)
        result.append(data)
    return result


def worst_asset_reason(asset_breakdown: list, breakeven=None) -> Optional[str]:
    """素材層成效裡投報率最差的那支，用一句白話點名（D4 觸點 2，票
    03-performance-reaches-the-user；拖累用詞的損益兩平前提見票
    09-worst-ad-wording-must-respect-breakeven）。算不出投報率（沒花費或沒收到營收資料）
    的素材不列入比較；一支能比的都沒有就老實回 None，不硬猜是哪一支拖累（鐵則 16）。

    `breakeven` 是損益兩平投報率，由呼叫端（reading.py）算好傳進來，這裡不重算一次
    （票 09 D1：兩個地方各算一次，數字會兜不起來）。依它分三種說法（票 09 D2）：
    最差那支真的低於損益兩平才說拖累；沒有 breakeven 可比就只講「相對最低」的事實，
    不做賺賠的斷言；全部都不低於損益兩平，代表最弱的那支其實也賺錢，只是相對弱。
    """
    candidates = [row for row in asset_breakdown if (row.get("kpis") or {}).get("roas") is not None]
    if not candidates:
        return None
    worst = min(candidates, key=lambda row: row["kpis"]["roas"])
    roas = worst["kpis"]["roas"]
    cpa = worst["kpis"].get("cpa")
    if breakeven is not None and roas >= breakeven:
        sentence = (f"這期{len(candidates)}支都有賺，相對最弱的是「{worst['asset_name']}」，"
                    f"投報率 {roas:.2f} 倍")
    elif breakeven is None:
        sentence = f"這期投報率相對最低的是「{worst['asset_name']}」這支廣告，投報率 {roas:.2f} 倍"
    else:
        sentence = f"這期拖累最兇的是「{worst['asset_name']}」這支廣告，投報率只有 {roas:.2f} 倍"
    if cpa is not None:
        sentence += f"，平均花 {cpa:,.0f} 元才換到一筆成交"
    return sentence


def max_frequency_by_asset(conn, brand_id: str, cycle_id: str) -> Optional[dict]:
    """本期頻率最高的那支廣告：`{"target", "frequency"}`，一筆頻率都沒有就回 None。

    JOIN 與 `asset_totals()` 同一條（只走「廣告名稱對得回交接包」的資料列）。健康燈的
    疲勞盞用整期最大頻率（app/ads/performance.py max_frequency），那個數字答得出「有多糟」
    卻答不出「是哪一支」——這裡逐支取 MAX 才點得到名。

    target 優先用切角名稱、對不到切角才退回廣告名稱：歷史切角來的換素材卡也用切角當目標，
    同一個目標才比得出來、才不會同時出兩張（`weekly_proposals.select_cards()`）。

    ponytail：對不回交接包的資料列（例如純手動匯入的檔期層數字）不在這個清單裡，
    燈紅但這裡回 None 是可能的——那種情況不硬猜是哪一支（鐵則 16）。
    """
    row = conn.execute(
        "SELECT COALESCE(cell.creative_angle, pkg.ad_name) target,"
        " MAX(ps.frequency) frequency"
        " FROM performance_snapshot ps"
        " JOIN external_ad_mapping xam ON xam.id = ps.external_ad_mapping_id"
        " JOIN publishing_package pkg ON pkg.id = xam.publishing_package_id"
        " LEFT JOIN experiment_cell cell ON cell.id = pkg.experiment_cell_id"
        " WHERE ps.brand_id = ? AND ps.campaign_cycle_id = ? AND ps.quarantined = 0"
        " AND ps.frequency IS NOT NULL"
        " GROUP BY pkg.id ORDER BY frequency DESC LIMIT 1", (brand_id, cycle_id),
    ).fetchone()
    return {"target": row["target"], "frequency": row["frequency"]} if row else None
