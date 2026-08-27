# -*- coding: utf-8 -*-
"""app/ads/reading_assets.py — 素材層成效（修憲落地 G2，決策 0035 第二節第 4 點）。

從 `app/ads/reading.py`（凍結 1039 行、不得再長）拆出來的小檔——`_asset_totals()` 原樣
搬過來改成公開的 `asset_totals()`，只有 reading.py 這一個呼叫端，不是新開的容器
（集裝箱憲章：拆檔不是拆模組）。這裡另外放這次新增的白話「哪支廣告拖累最兇」判讀，
同樣的理由：加進 reading.py 會讓它破凍結上限。
"""

from typing import Optional

from app.ads import performance as ads_performance


def asset_totals(conn, brand_id: str, cycle_id: str, breakeven: Optional[float] = None) -> list:
    """依素材（廣告名稱對回的交接包）分開的成效加總（修憲落地 G2，決策 0035 第二節第 4 點）。

    只有 CSV 匯入時廣告名稱對得回已授權素材的資料列才會出現在這裡（見
    app/ads/performance.py match_asset_mapping）；對不上的資料只算進檔期層，
    這裡不猜、不硬湊一列（鐵則 16）。純顯示用途，不影響 judge() 的門檻判定。

    ponytail：只用既有的 publishing_package_id／external_ad_mapping_id 兩個欄位做 JOIN，
    不新增 schema。

    每列附一個 `attributable`（ADR 0025 決定 9）：這一支的數字是不是真的只屬於這一支。
    Meta API 同步（app/ads/sync.py:249,270）已經優先用 meta_ad_id 找 mapping，對得上時
    逐支是準的；對不上而退回 meta_campaign_id 時，同一活動底下的多支廣告會全部擠進同一筆
    mapping、同一個交接包，那種列的逐支數字是假的。CSV 匯入靠廣告名稱完全相等對回唯一的
    交接包（performance.py match_asset_mapping），不經過這個缺口，一律算準。
    純顯示的呼叫端可以不理這個旗標；要據此叫使用者停掉某一支的（週提案卡）必須先看它。

    `breakeven`（可選）：這期損益兩平投報率。給了就順便算好每列的 `dragging_down_cycle`
    （B0-33／票 R4-late-data-downstream 修復）：只有投報率最低、且真的低於這條線的那（幾）
    支才算「拖累檔期」——跟 `worst_asset_reason()` 同一套「先比出最低、再比損益兩平」判準
    （票 09），不是逐支之間互相比大小就算數。原本這個判斷是前端自己重新發明一次
    （`Math.min` 找最低就標紅，完全沒比損益兩平），三支比例相近的廣告在補件後全部由虧轉盈
    （0.86→1.58 倍），卻因為還是「並列最低」而全部繼續掛紅標，此其根因；改在這裡算好、
    直接跟著 `asset_breakdown` 存進 `rule_result_json`，前端只管畫布林值，不再自己判定。
    不給 `breakeven`、或算不出投報率時一律 False（鐵則 16：看不出來就不誣賴）。

    `product_id`（票 F13）：`publishing_package.product_id` 原樣帶出，讓
    `weekly_proposals.select_cards()` 能把產品層停掉卡點名到底下真的屬於這個產品的廣告——
    這欄常是 NULL（交接包掛在切角上，切角的 product_id 常沒填），NULL 的廣告不算進任何
    產品（鐵則 16：不編造歸屬）。附加欄位，不影響既有呼叫端。
    """
    rows = conn.execute(
        "SELECT pkg.id pkg_id, pkg.ad_name asset_name, pkg.product_id product_id,"
        " COALESCE(SUM(ps.impressions),0) impressions, COALESCE(SUM(ps.clicks),0) clicks,"
        " COALESCE(SUM(ps.spend),0) spend, COALESCE(SUM(ps.conversions),0) conversions,"
        " COALESCE(SUM(ps.revenue),0) revenue,"
        " MIN(CASE WHEN ps.source != 'meta_api'"
        "          OR (xam.meta_ad_id IS NOT NULL AND xam.meta_ad_id = ps.meta_ad_id)"
        "          THEN 1 ELSE 0 END) attributable"
        " FROM performance_snapshot ps"
        " JOIN external_ad_mapping xam ON xam.id = ps.external_ad_mapping_id"
        " JOIN publishing_package pkg ON pkg.id = xam.publishing_package_id"
        " WHERE ps.brand_id = %s AND ps.campaign_cycle_id = %s AND ps.quarantined = false"
        " GROUP BY pkg.id ORDER BY revenue DESC", (brand_id, cycle_id),
    ).fetchall()
    result = []
    for row in rows:
        data = dict(row)
        # BUG 修復（route=C 02-3c，同 app/ads/reading_hypotheses.py comparison_cells()
        # 那個發現，範圍更大）：spend/revenue 是 COALESCE(SUM(numeric),0) 讀回來的
        # Decimal；impressions/clicks 底層是 bigint 欄位，但 Postgres 的 SUM(bigint)
        # 聚合結果型別是 numeric（防溢位的既有規則），COALESCE(SUM(...),0) 讀回來
        # 一樣是 Decimal，不是 int——conversions 是 double precision（float）。四種
        # 型別攪在一起，compute_kpis() 內只要有任兩種不同型別相除就會 TypeError；
        # 就近轉型一次收口。
        data["impressions"] = int(data["impressions"])
        data["clicks"] = int(data["clicks"])
        data["spend"] = float(data["spend"])
        data["revenue"] = float(data["revenue"])
        data["kpis"] = ads_performance.compute_kpis(data)
        result.append(data)
    roas_values = [r["kpis"]["roas"] for r in result if r["kpis"]["roas"] is not None]
    worst_roas = min(roas_values) if roas_values else None
    underwater = worst_roas is not None and breakeven is not None and worst_roas < breakeven
    for data in result:
        data["dragging_down_cycle"] = bool(underwater and data["kpis"]["roas"] == worst_roas)
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
    另外回一個 `pkg_id`：跟廣告層「停掉」卡比對是不是同一支廣告時，兩張卡的 target 命名空間
    不同（這裡可能是切角名，那邊一定是廣告名），只有 pkg_id 認得出來（ADR 0025 決定 8）。

    ponytail：對不回交接包的資料列（例如純手動匯入的檔期層數字）不在這個清單裡，
    燈紅但這裡回 None 是可能的——那種情況不硬猜是哪一支（鐵則 16）。
    """
    row = conn.execute(
        "SELECT pkg.id pkg_id, COALESCE(cell.creative_angle, pkg.ad_name) target,"
        " MAX(ps.frequency) frequency"
        " FROM performance_snapshot ps"
        " JOIN external_ad_mapping xam ON xam.id = ps.external_ad_mapping_id"
        " JOIN publishing_package pkg ON pkg.id = xam.publishing_package_id"
        " LEFT JOIN experiment_cell cell ON cell.id = pkg.experiment_cell_id"
        " WHERE ps.brand_id = %s AND ps.campaign_cycle_id = %s AND ps.quarantined = false"
        " AND ps.frequency IS NOT NULL"
        # BUG 修復（route=C 02-3c，app/ads/reading_assets.py:118）：SELECT 帶了
        # cell.creative_angle（LEFT JOIN 來的別張表欄位），只 GROUP BY pkg.id 在
        # SQLite 能過（挑任一列），Postgres 要求非聚合欄位都要進 GROUP BY——
        # cell.creative_angle 加進去不改變分組結果（同一個 pkg.id 只對到一個
        # experiment_cell），只是滿足語法要求。
        " GROUP BY pkg.id, cell.creative_angle ORDER BY frequency DESC LIMIT 1", (brand_id, cycle_id),
    ).fetchone()
    return ({"pkg_id": row["pkg_id"], "target": row["target"], "frequency": row["frequency"]}
            if row else None)
