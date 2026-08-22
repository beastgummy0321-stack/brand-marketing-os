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


def worst_asset_reason(asset_breakdown: list) -> Optional[str]:
    """素材層成效裡投報率最差的那支，用一句白話點名（D4 觸點 2，票
    03-performance-reaches-the-user）。算不出投報率（沒花費或沒收到營收資料）的素材
    不列入比較；一支能比的都沒有就老實回 None，不硬猜是哪一支拖累（鐵則 16）。
    """
    candidates = [row for row in asset_breakdown if (row.get("kpis") or {}).get("roas") is not None]
    if not candidates:
        return None
    worst = min(candidates, key=lambda row: row["kpis"]["roas"])
    roas = worst["kpis"]["roas"]
    cpa = worst["kpis"].get("cpa")
    sentence = f"這期拖累最兇的是「{worst['asset_name']}」這支廣告，投報率只有 {roas:.2f} 倍"
    if cpa is not None:
        sentence += f"，平均花 {cpa:,.0f} 元才換到一筆成交"
    return sentence
