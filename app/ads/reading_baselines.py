"""app/ads/reading_baselines.py — 品牌基線（票 10-split-reading-py）。

從 `app/ads/reading.py`（凍結 1039 行、不得再長）拆出來的小檔——這幾個函式原樣搬過來，
只有 reading.py 這一個呼叫端，不是新開的容器（集裝箱憲章：拆檔不是拆模組）。

`dual_baseline()` 本身**沒有**跟著搬過來：它要用到 `orders_repo`（`app/main.py` 開機時
才注入到 `app.ads.reading` 這個模組物件上，見該檔「app.ads → app.orders 依賴注入」那段），
搬過來會讓這裡的 `orders_repo` 永遠是 `None`——注入目標認的是 `reading` 這個模組，不會
自動跟著函式搬家。`dual_baseline()` 留在 reading.py，靠 import 呼叫這裡的函式。
"""

from datetime import timedelta
from statistics import median

# 基線旺淡季標注（票 #39，決策 0025 第 4 點）：拿「去年同期」跟「全年平均」比值判斷，
# 不是拍腦袋猜哪個月熱賣——比值落在中間段一律算「一般」，避免雜訊被誤標成季節效應。
SEASON_RATIO_PEAK = 1.2
SEASON_RATIO_LOW = 0.8
SEASON_LABELS = {"peak": "旺季", "low": "淡季", "typical": "一般"}


def _median_derived_metrics(conn, brand_id: str, *, extra_where: str = "",
                            extra_params: list | None = None) -> dict:
    """derived_metric 依 metric 取中位數的共用聚合點——brand_baseline／
    _same_period_last_year_baseline（進而 dual_baseline／校準區間 basis，見
    app/ads/simulation.py _basis）都經這裡出，一次排除 `phase='simulation'` 的檔期
    （票 #71：模擬檔期的假成效不能污染任何真基線判讀）。模擬頁自己的顯示走
    `performance_snapshot`／`ads_performance.totals()`，不經這裡，不受影響。
    品牌層（`campaign_cycle_id IS NULL`，見 save_brand_level_derived_metrics）沒有對應檔期，
    一律保留。
    """
    sql = ("SELECT dm.metric, dm.value FROM derived_metric dm"
           " LEFT JOIN campaign_cycle cc ON cc.id = dm.campaign_cycle_id"
           " WHERE dm.brand_id = %s AND (cc.id IS NULL OR cc.phase != 'simulation')")
    params = [brand_id]
    if extra_where:
        sql += " " + extra_where
        params.extend(extra_params or [])
    rows = conn.execute(sql, params).fetchall()
    grouped: dict = {}
    for row in rows:
        grouped.setdefault(row["metric"], []).append(row["value"])
    return {metric: round(median(values), 4) for metric, values in grouped.items() if values}


def brand_baseline(conn, brand_id: str, exclude_cycle_id: str | None = None) -> dict:
    """這個品牌自己的基準：**過去**檔期各指標的中位數。沒有歷史就回空 dict。

    決策 0022 第 21 點：有歷史就用歷史，沒有才退回產業基準——而且要標明用的是哪一種，
    不能讓使用者以為通例值是他自己的數字。

    `exclude_cycle_id` 一定要傳當期：拿這期的數字當「過去的水準」再回頭評價這期，
    是循環論證——永遠會得到「跟過去差不多」，而且第一期的預告會謊稱有歷史可依據。
    """
    extra_where, extra_params = "", []
    if exclude_cycle_id:
        extra_where = "AND (dm.campaign_cycle_id IS NULL OR dm.campaign_cycle_id != %s)"
        extra_params = [exclude_cycle_id]
    return _median_derived_metrics(conn, brand_id, extra_where=extra_where,
                                   extra_params=extra_params)


# 基線比較優先看的指標順序：ROAS 最能反映廣告效率，其餘依序退而求其次
# （不是每個品牌／每期都收得到完整 KPI，見 compute_kpis 分母為 0 回 None 的規則）。
_SEASON_METRIC_PRIORITY = ("roas", "ctr", "cpa", "cpc")


def _same_period_last_year_baseline(conn, brand_id: str, cycle: dict,
                                    exclude_cycle_id: str | None = None) -> dict:
    """「去年同期」基線：這個品牌去年同一段日子（±15 天）跑過的檔期，KPI 中位數。
    找不到對應檔期就回空 dict（不硬湊）。"""
    start = cycle["start_date"]
    try:
        target = start.replace(year=start.year - 1)
    except ValueError:
        target = start - timedelta(days=365)  # 2/29 沒有對應日期時退而求其次
    window_start = (target - timedelta(days=15)).isoformat()
    window_end = (target + timedelta(days=15)).isoformat()

    sql = ("SELECT id FROM campaign_cycle WHERE brand_id = %s AND start_date >= %s"
          " AND start_date <= %s")
    params = [brand_id, window_start, window_end]
    if exclude_cycle_id:
        sql += " AND id != %s"
        params.append(exclude_cycle_id)
    cycle_ids = [row["id"] for row in conn.execute(sql, params).fetchall()]
    if not cycle_ids:
        return {}

    placeholders = ",".join("%s" for _ in cycle_ids)
    return _median_derived_metrics(
        conn, brand_id, extra_where=f"AND dm.campaign_cycle_id IN ({placeholders})",
        extra_params=cycle_ids)


def _season_label(same_period: dict, annual: dict) -> dict:
    """比較「去年同期」與「全年平均」，標注旺淡季——旺季自然增長不該被誤判成廣告有效
    （決策 0025 第 4 點）。任一邊缺資料就誠實說看不出來，不硬猜。"""
    metric = next((m for m in _SEASON_METRIC_PRIORITY if same_period.get(m) and annual.get(m)),
                  None)
    if metric is None:
        return {"level": None, "label": "資料不足，看不出旺淡季", "ratio": None, "metric": None}
    ratio = round(same_period[metric] / annual[metric], 2)
    if ratio >= SEASON_RATIO_PEAK:
        level = "peak"
    elif ratio <= SEASON_RATIO_LOW:
        level = "low"
    else:
        level = "typical"
    return {"level": level, "label": SEASON_LABELS[level], "ratio": ratio, "metric": metric}
