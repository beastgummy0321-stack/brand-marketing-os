# -*- coding: utf-8 -*-
"""app/ads/reading.py — 成效判讀（票 12）。

決策 0016 硬性原則 4 的分工在這裡最吃緊：
**狀態由門檻規則判定（純程式），LLM 只負責把結論翻成人話**。模型不決定要不要加碼，
也不決定該不該停——它只是把程式算好的判斷講得讓人聽得懂。

## 賺不賺錢的門檻不是拍腦袋的

打平所需的投報率＝售價 ÷ 單位毛利。毛利率 40% 的產品，廣告投報率要到 2.5 倍才回本；
毛利率 70% 的產品，1.43 倍就開始賺。所以同一個 ROAS 數字對不同產品意義完全不同，
用固定門檻（例如「ROAS 3 以上算好」）會把高毛利的好檔期誤判成差。

沒有單位經濟資料時，程式**不會假裝算得出賺不賺錢**——狀態退回「還看不出賺不賺」，
只就點擊表現給觀察，並明說少了什麼資料（鐵則 16、決策 0013）。

## 資料不足就直說

Meta 有學習期，前幾天的數字本來就不準；樣本太少時任何結論都是擲硬幣。
所以先過「資料夠不夠」這一關，不夠就回 insufficient_data，不硬給方向。
"""

import json
from datetime import date, timedelta
from statistics import median
from typing import Optional

from app.ads import budget as budget_calc
from app.ads import inflation as ads_inflation
from app.ads import performance as ads_performance
from app.ads import reconcile as ads_reconcile
from app.ads import repository as ads_repo
from app.ads import settlement as ads_settlement
from app.brand_intelligence import repository as bi
from app.core import interrupts as core_interrupts
from app.core import prototype_phase
from app.core import rule_cards
from app.core.db import new_id, now_iso
from app.llm import gateway, providers

# 第 7 刀（A1 三層地界新規則：app/ads 不得 import app.orders，見
# test_architecture_boundaries.py）：orders_channel／orders_repo 不在這裡 import，
# 改由組裝根 app/main.py 啟動時注入真正的 app.orders.channel／repository 模組。
orders_channel = None
orders_repo = None

PROVIDER = providers.AnthropicProvider()  # 測試整包換掉

# --- 門檻常數（要調就改這裡）-------------------------------------------------

MIN_IMPRESSIONS = 1000      # 低於此曝光量，點擊率的分母太小，算出來的百分比沒有意義
MIN_SPEND_RATIO = 0.25      # 花不到計畫的四分之一，等於還在學習期
MIN_CONVERSIONS_FOR_ROAS = 3  # 轉換少於這個數，ROAS 只是運氣——這個門檻管「要不要算」

# 修憲落地 G4（決策 0035 第三節第 7 點）：3–10 筆轉換的 ROAS 信賴區間跨越打平線兩側，
# 而 status 是全系統總開關（驅動下期預算、假設預選），算出來的方向再明確也不准信。
# 這個門檻管「算出來的加碼／停損方向能不能信」——跟上面 MIN_CONVERSIONS_FOR_ROAS 是兩條
# 不同的線。唯一該在小樣本成立的強訊號是既有的「花掉一半預算零轉換」（在這個門檻之前就
# 判定 pause_candidate），那條不受這裡影響。
MIN_CONVERSIONS_FOR_DIRECTIONAL_CALL = 10

SCALE_MARGIN = 1.3          # 投報率超過打平線這個倍數 → 可以考慮加碼
PAUSE_MARGIN = 0.7          # 低於打平線這個倍數 → 該考慮停損
ZERO_CONVERSION_SPEND_RATIO = 0.5  # 花掉一半預算還是零轉換 → 該考慮停

# 產業基準的退路值。只在「這個品牌完全沒有歷史資料」時使用，且介面必須標明來源。
INDUSTRY_FALLBACK = {"ctr": 0.01, "roas": 2.0}

STATUS_LABELS = {
    "insufficient_data": "資料還不夠",
    "learning": "還在學習期",
    "maintain": "維持現狀",
    "scale_candidate": "可以考慮加碼",
    "pause_candidate": "該考慮停下來",
    "unclear_economics": "還看不出賺不賺",
}

# 統計等級標注（票 8）：跟上面 STATUS_LABELS 是兩條不同的線——STATUS_LABELS 是「錢的門檻」判斷
# 出來的結論，這裡是「這個結論夠不夠格叫統計等級」的誠實標注。方向性判讀不代表結論是錯的，
# 只是樣本還沒到能講「這是嚴謹統計結果」的程度，小預算常常收不到那麼多樣本。
STATISTICAL_LEVEL_NOTES = {
    "statistical": "這期收到的樣本數已經到達 A/B 測試方法論的統計等級門檻，這個結論有統計依據撐著。",
    "directional": "這期的樣本數還沒到統計等級的門檻，這只能算方向性判讀——大概是這樣，"
                   "但還不到能說「已經證實」的程度。小預算常常收不到這麼多樣本，先看方向就好，"
                   "不用等到跟大品牌一樣的樣本數才敢動作。",
}

# 基線旺淡季標注（票 #39，決策 0025 第 4 點）：拿「去年同期」跟「全年平均」比值判斷，
# 不是拍腦袋猜哪個月熱賣——比值落在中間段一律算「一般」，避免雜訊被誤標成季節效應。
SEASON_RATIO_PEAK = 1.2
SEASON_RATIO_LOW = 0.8
SEASON_LABELS = {"peak": "旺季", "low": "淡季", "typical": "一般"}

# 翻盤分級規則（票 #38，決策 0025 判讀節奏第 5 點：「翻盤警示分級——微調不吵、判定翻盤才
# 進佇列」）：規則寫死在程式，不用 LLM 判斷、不用可調參數。判讀結論只分三群——正向可以
# 加碼、負向該停損、中間還看不準——補件後只有「正向→負向」或「負向→正向」跨群才算真正
# 翻盤；停在同一群內的變化（含還是看不準）都算微調，不驚動使用者。
_POSITIVE_STATUSES = {"scale_candidate", "maintain"}
_NEGATIVE_STATUSES = {"pause_candidate"}

# 假設結案（票 #53，決策 0030 第三節第 8 點）：判讀頁列出這期的策略假設，三選一結案。
# AI 的預選值由程式依判讀結論算（決策 0016 硬性原則 4：結論由程式定，LLM 只翻人話）。
#
# 修憲落地 G4（決策 0035 第三節第 6 點）：預選**不再**沿用上面 `_verdict_group()` 那套
# 正負向分群——那組分群是給翻盤警示（票 #38）與回購雙線衝突（票 #39）用的，`maintain`
# （只是打平）在那裡算正面訊號是對的（見 test_ads_reading.py 的 VerdictShiftTest），
# 但拿來預選假設「成立」就是橡皮圖章：使用者十之八九照 AI 預選送出（0030 否決程式自動判
# 的理由「假設是自由文字、沒有可量測判準」對人類更成立），maintain 這種「沒虧沒賺」的
# 結論不該被貼上「已驗證」標籤。改用專屬判準：只有 `scale_candidate`／`pause_candidate`
# 這兩個真正算得出方向的結論才預選成立／不成立，其餘（含 maintain、learning、
# insufficient_data、unclear_economics）一律預選「看不出來」，沒有明確規則訊號就不硬給答案
# ——使用者仍可手動改選任何一個，系統不擋（決策 0013）。
HYPOTHESIS_STATUS_LABELS = {"supported": "成立", "rejected": "不成立", "inconclusive": "看不出來"}
_HYPOTHESIS_DIRECTIONAL_PRESELECT = {"scale_candidate": "supported", "pause_candidate": "rejected"}
PENDING_HYPOTHESIS_STATUSES = ("proposed", "testing")
HYPOTHESIS_TYPE_LABELS = {"audience": "受眾假設", "message": "訊息假設"}

# ledger 自己的可信度分級（修憲落地 G4，決策 0035 第三節第 8 點）：樣本數＋是否被獨立
# 重測過，不借用 `ads_inflation.data_grade()`（成色標籤）——那個標籤講的是「資料來源有沒有
# 對過帳」，跟「這條學習可不可信」是兩回事。「重測過」＝這個品牌／這個範圍下，同一句學習
# 文字之前已經進過帳——不是同一次判讀的巧合，是不同期別各自算出同一個結論。
LEDGER_CONFIDENCE_LABELS = {
    "preliminary": "初步（樣本還沒到可以下判斷的門檻，這是第一次看到這個結論）",
    "moderate": "穩定（樣本數已達門檻，這是第一次看到這個結論）",
    "reinforced": "已加強（不同期別各自驗證過同一個結論）",
}


def _verdict_group(status: Optional[str]) -> str:
    """翻盤警示（`classify_verdict_shift`）與回購雙線衝突（`_repurchase_line`）專用的
    正負向分群——`maintain` 算正面在這兩個用途下是對的。**假設結案預選不用這個**，
    見下面 `_preselect_hypothesis_status` 與其專屬的 `_HYPOTHESIS_DIRECTIONAL_PRESELECT`
    （修憲落地 G4）。"""
    if status in _POSITIVE_STATUSES:
        return "positive"
    if status in _NEGATIVE_STATUSES:
        return "negative"
    return "uncertain"


def _preselect_hypothesis_status(status: Optional[str]) -> str:
    return _HYPOTHESIS_DIRECTIONAL_PRESELECT.get(status, "inconclusive")


def classify_verdict_shift(before_status: Optional[str], after_status: Optional[str]) -> str:
    """'unchanged'（結論沒變）／'adjustment'（微調，不吵）／'reversal'（翻盤，要進佇列）。"""
    if before_status == after_status:
        return "unchanged"
    if {_verdict_group(before_status), _verdict_group(after_status)} == {"positive", "negative"}:
        return "reversal"
    return "adjustment"


def _unsettled_note(ratio: Optional[float]) -> str:
    """期末暫定判讀標注「未結案訂單佔 X%」（決策 0025 判讀節奏第 5 點）：貨到付款＋超商取貨
    型態下，這些訂單期末後才會定案，暫定結論可能因此翻盤。"""
    if ratio is None:
        return "沒有比對得到訂單資料，看不出未結案訂單的比例。"
    return f"這期還有 {ratio:.0%} 的訂單尚未結案（出貨或取貨還沒完成），這是暫定結論。"


def breakeven_roas(economics: Optional[dict]) -> Optional[float]:
    """打平所需的投報率＝售價 ÷ 單位毛利。算不出來回 None（不猜）。"""
    if not economics:
        return None
    margin = budget_calc.gross_margin(economics)
    price = economics.get("selling_price")
    if not margin or not price:
        return None
    return round(float(price) / margin, 2)


def repurchase_breakeven_roas(first_order_breakeven: Optional[float],
                              multiplier: Optional[float]) -> Optional[float]:
    """含 90 天回購的實質打平線（票 #39，決策 0025 第 7 點）：回購讓客戶在 90 天內帶來
    `multiplier` 倍首單的淨營收，所以首單廣告投報率不用到打平線就已經回本——
    實質打平線＝首單打平線 ÷ 回購倍數。任一邊算不出來就回 None，不猜。"""
    if not first_order_breakeven or not multiplier:
        return None
    return round(first_order_breakeven / multiplier, 2)


def _median_derived_metrics(conn, brand_id: str, *, extra_where: str = "",
                            extra_params: Optional[list] = None) -> dict:
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
           " WHERE dm.brand_id = ? AND (cc.id IS NULL OR cc.phase != 'simulation')")
    params = [brand_id]
    if extra_where:
        sql += " " + extra_where
        params.extend(extra_params or [])
    rows = conn.execute(sql, params).fetchall()
    grouped: dict = {}
    for row in rows:
        grouped.setdefault(row["metric"], []).append(row["value"])
    return {metric: round(median(values), 4) for metric, values in grouped.items() if values}


def brand_baseline(conn, brand_id: str, exclude_cycle_id: Optional[str] = None) -> dict:
    """這個品牌自己的基準：**過去**檔期各指標的中位數。沒有歷史就回空 dict。

    決策 0022 第 21 點：有歷史就用歷史，沒有才退回產業基準——而且要標明用的是哪一種，
    不能讓使用者以為通例值是他自己的數字。

    `exclude_cycle_id` 一定要傳當期：拿這期的數字當「過去的水準」再回頭評價這期，
    是循環論證——永遠會得到「跟過去差不多」，而且第一期的預告會謊稱有歷史可依據。
    """
    extra_where, extra_params = "", []
    if exclude_cycle_id:
        extra_where = "AND (dm.campaign_cycle_id IS NULL OR dm.campaign_cycle_id != ?)"
        extra_params = [exclude_cycle_id]
    return _median_derived_metrics(conn, brand_id, extra_where=extra_where,
                                   extra_params=extra_params)


# 基線比較優先看的指標順序：ROAS 最能反映廣告效率，其餘依序退而求其次
# （不是每個品牌／每期都收得到完整 KPI，見 compute_kpis 分母為 0 回 None 的規則）。
_SEASON_METRIC_PRIORITY = ("roas", "ctr", "cpa", "cpc")


def _same_period_last_year_baseline(conn, brand_id: str, cycle: dict,
                                    exclude_cycle_id: Optional[str] = None) -> dict:
    """「去年同期」基線：這個品牌去年同一段日子（±15 天）跑過的檔期，KPI 中位數。
    找不到對應檔期就回空 dict（不硬湊）。"""
    start = date.fromisoformat(cycle["start_date"])
    try:
        target = start.replace(year=start.year - 1)
    except ValueError:
        target = start - timedelta(days=365)  # 2/29 沒有對應日期時退而求其次
    window_start = (target - timedelta(days=15)).isoformat()
    window_end = (target + timedelta(days=15)).isoformat()

    sql = ("SELECT id FROM campaign_cycle WHERE brand_id = ? AND start_date >= ?"
          " AND start_date <= ?")
    params = [brand_id, window_start, window_end]
    if exclude_cycle_id:
        sql += " AND id != ?"
        params.append(exclude_cycle_id)
    cycle_ids = [row["id"] for row in conn.execute(sql, params).fetchall()]
    if not cycle_ids:
        return {}

    placeholders = ",".join("?" for _ in cycle_ids)
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


def dual_baseline(conn, brand_id: str, cycle: dict,
                  exclude_cycle_id: Optional[str] = None) -> dict:
    """基線兩條並列（票 #39，決策 0025 第 4 點）：「去年同期」與「全年平均」，並標注旺淡季；
    這個品牌記錄過折扣／退款口徑變更時，跨口徑比較標「不同尺」——數字不完全對等。

    ponytail：不同尺判斷用「這個品牌是否曾記過任何口徑變更」這個粗粒度條件，不細分變更
    究竟落在哪一段比較區間內；口徑變更通常不頻繁，粗粒度已經夠用，之後如需要精準區間比對
    再細分（見 app/orders/repository.list_policy_changes 的 until 參數）。
    """
    annual = brand_baseline(conn, brand_id, exclude_cycle_id=exclude_cycle_id)
    same_period = _same_period_last_year_baseline(conn, brand_id, cycle, exclude_cycle_id)
    season = _season_label(same_period, annual)

    policy_changes = orders_repo.list_policy_changes(conn, brand_id, until=cycle["end_date"])
    cross_ruler_note = None
    if policy_changes and (annual or same_period):
        kinds = sorted({orders_repo.POLICY_TYPE_LABELS.get(c["policy_type"], c["policy_type"])
                       for c in policy_changes})
        cross_ruler_note = (f"這個品牌的{'、'.join(kinds)}口徑曾經變更過，"
                            "跟基線比較時標「不同尺」，數字不完全對等。")

    return {"annual_average": annual, "same_period_last_year": same_period, "season": season,
           "policy_changes": policy_changes, "cross_ruler_note": cross_ruler_note}


def judge(totals: dict, *, plan_budget: float, breakeven: Optional[float], brand_id: str,
          baseline: Optional[dict] = None, conn=None) -> dict:
    """純函數：一組數字 → 判讀狀態與理由。不碰資料庫（conn／brand_id 只用來讀這個品牌的規則卡門檻，conn 可傳 None）、
    不呼叫 LLM。

    決策 0023 第 19、20 點：「錢的門檻」（status，打平／加碼／停損）跟「統計的門檻」
    （statistical_level，樣本夠不夠格叫統計等級）是兩條分開的線——status 的算法完全不受
    這裡新增的統計標注影響，改動只在額外附上 statistical_level／statistical_note。
    """
    baseline = baseline or {}
    kpis = totals.get("kpis") or ads_performance.compute_kpis(totals)
    spend = totals.get("spend") or 0
    impressions = totals.get("impressions") or 0
    conversions = totals.get("conversions") or 0
    clicks = totals.get("clicks") or 0
    cvr = (conversions / clicks) if clicks else None
    tier = rule_cards.sample_size_tier(conn, brand_id, clicks, cvr)
    reasons = []

    def verdict(status: str) -> dict:
        return {
            "status": status, "reasons": reasons, "kpis": kpis,
            "statistical_level": tier["level"],
            "statistical_level_label": rule_cards.STATISTICAL_LEVEL_LABELS[tier["level"]],
            "statistical_note": STATISTICAL_LEVEL_NOTES[tier["level"]],
        }

    # 1. 資料夠不夠——不夠就不下結論
    if plan_budget and spend < plan_budget * MIN_SPEND_RATIO:
        reasons.append(f"只花了計畫的 {spend / plan_budget:.0%}，還在起步階段")
        return verdict("insufficient_data")
    if impressions < MIN_IMPRESSIONS:
        reasons.append(f"曝光只有 {impressions:,.0f} 次，樣本太少算不出可靠的比例")
        return verdict("insufficient_data")

    # 2. 花掉一半預算還是零轉換——不必等 ROAS，這已經是訊號
    if conversions == 0 and plan_budget and spend >= plan_budget * ZERO_CONVERSION_SPEND_RATIO:
        reasons.append(f"花了 {spend:,.0f} 還是一筆都沒成交")
        return verdict("pause_candidate")

    # 3. 算不算得出賺不賺——沒有單位經濟就不假裝
    if breakeven is None:
        reasons.append("這期的產品沒有成本售價資料，算不出要幾倍投報才回本")
        if kpis.get("ctr") is not None:
            reference = baseline.get("ctr") or INDUSTRY_FALLBACK["ctr"]
            reasons.append(f"點擊率 {kpis['ctr']:.2%}，"
                           + ("比過去水準好" if kpis["ctr"] >= reference else "低於過去水準"))
        return verdict("unclear_economics")

    roas = kpis.get("roas")
    if conversions < MIN_CONVERSIONS_FOR_ROAS:
        reasons.append(f"只有 {conversions:.0f} 筆成交，這個投報率還不夠穩定")
        return verdict("learning")

    reasons.append(f"這些產品要投報 {breakeven:.2f} 倍才回本，這期是 {roas:.2f} 倍")
    if roas >= breakeven * SCALE_MARGIN:
        status = "scale_candidate"
    elif roas < breakeven * PAUSE_MARGIN:
        status = "pause_candidate"
    elif roas >= breakeven:
        status = "maintain"
    else:
        status = "learning"
        reasons.append("在打平線附近，再跑一陣子看看")

    # 修憲落地 G4（決策 0035 第三節第 7 點）：3–10 筆轉換的信賴區間跨越打平線兩側，
    # 不准輸出加碼或停損，即使算出來的方向很明確——誠實降回「還在學習期」。maintain 不受
    # 影響：它本來就是這個樣本區間唯一該有信心講出來的錢的結論之一。
    if status in ("scale_candidate", "pause_candidate") and conversions < MIN_CONVERSIONS_FOR_DIRECTIONAL_CALL:
        reasons.append(f"只有 {conversions:.0f} 筆成交，樣本還不夠大到能斷言加碼或停損，先看學習期")
        status = "learning"

    return verdict(status)


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


def _asset_totals(conn, brand_id: str, cycle_id: str) -> list:
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


def _repurchase_line(conn, brand_id: str, cycle_totals: dict, first_order_breakeven: Optional[float],
                     *, plan_budget: float, baseline: dict, first_status: str) -> dict:
    """回購實質打平線（票 #39）：算出來但不取代首單線——首單線（cycle_verdict 本身）永遠是
    正式判讀，這條只是旁列參考，不能拿未來的回購替今天的爛廣告辯護（決策 0025 第 7 點）。"""
    repurchase = orders_repo.repurchase_multiplier(conn, brand_id)
    breakeven = repurchase_breakeven_roas(first_order_breakeven, repurchase["multiplier"])
    verdict = None
    if breakeven is not None:
        verdict = judge(cycle_totals, plan_budget=plan_budget, breakeven=breakeven, brand_id=brand_id,
                        baseline=baseline, conn=conn)
    conflict = (verdict is not None
               and {_verdict_group(first_status), _verdict_group(verdict["status"])}
                   == {"positive", "negative"})
    return {
        "available": verdict is not None,
        "sample_size": repurchase["sample_size"],
        "insufficient_sample": repurchase["insufficient_sample"],
        "multiplier": repurchase["multiplier"],
        "breakeven": breakeven,
        "status": verdict["status"] if verdict else None,
        "status_label": STATUS_LABELS.get(verdict["status"]) if verdict else None,
        "reasons": verdict["reasons"] if verdict else [],
        "conflict": conflict,
    }


def _repurchase_dissent_check(conn, brand_id: str, cycle_id: str, settlement_version_id: str,
                              line: dict, first_status: str) -> None:
    """兩條打平線結論相反時，寫一筆 AI 具名異議並進打斷佇列複核（決策 0025 第 7 點）；
    沒衝突（或樣本不足沒有實質線）就清掉舊的 pending 異議——比照結論不再翻盤就不用再吵。

    異議文字直接引用兩條線已經算好的理由（judge() 產出的白話句子），不經 LLM：這是規則觸發
    的事實陳述，不是需要 AI 判斷語氣的主觀建議（決策 0016 硬性原則 4）。
    """
    dissents = []
    if line["conflict"]:
        suggestion = (f"首單線判定「{STATUS_LABELS.get(first_status, first_status)}」，"
                      f"回購實質線判定「{line['status_label']}」，兩線結論相反，建議人工複核。")
        reason = (f"回購倍數 {line['multiplier']:.2f} 倍（樣本 {line['sample_size']} 位滿"
                  f" {orders_repo.REPURCHASE_OBSERVATION_DAYS} 天顧客），"
                  f"回購實質打平線 {line['breakeven']:.2f} 倍；" + "；".join(line["reasons"]))
        dissents.append({"target_type": "repurchase_breakeven", "suggestion": suggestion,
                         "reason": reason})

    ads_repo.replace_pending_dissents(conn, brand_id, cycle_id, dissents, None,
                                      target_types=("repurchase_breakeven",))
    if line["conflict"]:
        core_interrupts.enqueue(
            conn, category="repurchase_conflict",
            dedupe_key=f"repurchase_conflict:{settlement_version_id}",
            message="回購校正結論跟首單線相反，去複核。", brand_id=brand_id,
            campaign_cycle_id=cycle_id,
            action_url=f"/brands/{brand_id}/ads/{cycle_id}/performance",
        )


def run(conn, brand_id: str, cycle_id: str, actor: str,
       trigger_reason: Optional[str] = None) -> tuple:
    """跑一次判讀並入庫。成功回 (True, None)；沒有資料回 (False, 人話說明)。

    trigger_reason 轉交給 app/ads/settlement.py freeze()（'final_settlement'／'late_data'
    等），省略時沿用它自己的預設（第一次判'initial'、之後'manual_rerun'）。
    """
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    if cycle is None:
        raise ValueError("找不到廣告檔期")

    cycle_totals = ads_performance.totals(conn, brand_id, cycle_id)
    if not cycle_totals["rows"]:
        return False, "這期還沒有成效資料，先把數字補上來再判讀。"

    baseline = brand_baseline(conn, brand_id, exclude_cycle_id=cycle_id)
    allocations = ads_repo.list_cycle_products(conn, brand_id, cycle_id)
    per_product = _product_totals(conn, brand_id, cycle_id)
    confidence = ads_reconcile.load(conn, brand_id, cycle_id)
    unsettled_ratio = orders_repo.unsettled_order_ratio(
        conn, brand_id, cycle["start_date"], cycle["end_date"])
    # 併進快照的攤平明細（不影響 judge()——它只認自己會用到的那幾個鍵）：未結案佔比
    # 隨版次留痕，晚到訂單資料把佔比拉低時，逐版差異直接看得到（票 #38）。
    cycle_totals["unsettled_ratio"] = unsettled_ratio

    # 先凍結快照、再算判定（決策 0025 審查補遺 C）：把這次判讀看到的原始畫面定格下來，
    # 之後才餵給 judge() 算結論——同一期重跑必產生新版次，成本／係數回改不會偷改到這一筆。
    freeze_result = ads_settlement.freeze(conn, brand_id, cycle, actor=actor,
                                          cycle_totals=cycle_totals, per_product=per_product,
                                          trigger_reason=trigger_reason)

    ts = now_iso()
    # 先子後父：recommendation（下期草案）指向 performance_reading，順序倒過來會被外鍵擋下。
    # 重新判讀本來就該重出下期草案，所以一起清掉。
    conn.execute(
        "DELETE FROM recommendation WHERE brand_id = ? AND campaign_cycle_id = ?",
        (brand_id, cycle_id),
    )
    # learning_ledger 解除關聯（不刪列，比照 repository.delete_cycle() 既有先例）：假設結案
    # 入帳時可能記下了這一版 performance_reading 的 id，重判必須先斷開，否則 PRAGMA
    # foreign_keys=ON 會擋下面這個 DELETE（append-only 的學習列本身不受影響，只是來源指標
    # 指到新的一版）。learning_ledger 現屬品牌永久層（修憲落地 A3），走 bi 的公開函式。
    reading_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM performance_reading WHERE campaign_cycle_id = ?", (cycle_id,)
    ).fetchall()]
    bi.unlink_learning_ledger_reading(conn, reading_ids)
    conn.execute(
        "DELETE FROM performance_reading WHERE brand_id = ? AND campaign_cycle_id = ?",
        (brand_id, cycle_id),
    )

    readings = []
    # 產品層：每個產品各判各的（決策 0022 第 8 點）。沒有產品層資料就跳過，不硬掰。
    for allocation in allocations:
        totals = per_product.get(allocation["product_id"])
        if not totals:
            continue
        economics = bi.get_product_economics(conn, brand_id, allocation["product_id"])
        verdict = judge(totals, plan_budget=allocation["allocated_budget"] or 0, brand_id=brand_id,
                        breakeven=breakeven_roas(economics), baseline=baseline, conn=conn)
        verdict["product_id"] = allocation["product_id"]
        verdict["product_name"] = allocation["product_name"]
        readings.append(verdict)

    # 檔期層：一句總結。產品層判不出來時，這是唯一的結論。
    cycle_breakeven = None
    breakevens = [breakeven_roas(bi.get_product_economics(conn, brand_id, a["product_id"]))
                  for a in allocations]
    known = [b for b in breakevens if b]
    if known:
        cycle_breakeven = round(sum(known) / len(known), 2)
    cycle_verdict = judge(cycle_totals, plan_budget=cycle["budget"] or 0, brand_id=brand_id,
                          breakeven=cycle_breakeven, baseline=baseline, conn=conn)
    cycle_verdict["product_id"] = None
    cycle_verdict["product_name"] = None
    if allocations and not per_product:
        cycle_verdict["reasons"].append(
            "這期的成效數字沒有分到各個產品，所以只能給整體判讀，看不出是哪個產品拉的")
    # 期末暫定判讀：只有檔期層有「未結案佔比」這件事（決策 0025 判讀節奏第 5 點）；
    # is_tentative＝這一版還不是最終結算（final_settlement 才是最終版）。
    cycle_verdict["unsettled_ratio"] = unsettled_ratio
    cycle_verdict["unsettled_note"] = _unsettled_note(unsettled_ratio)
    cycle_verdict["is_tentative"] = trigger_reason != "final_settlement"

    # 回購雙打平線（票 #39，決策 0025 第 7 點）：檔期層才算——首單打平線是這期唯一的正式
    # 判讀（cycle_verdict 本身，保守），這裡另外並列一條含 90 天回購的實質判讀給旁觀參考。
    cycle_verdict["repurchase_line"] = _repurchase_line(
        conn, brand_id, cycle_totals, cycle_breakeven, plan_budget=cycle["budget"] or 0,
        baseline=baseline, first_status=cycle_verdict["status"])
    _repurchase_dissent_check(conn, brand_id, cycle_id, freeze_result["settlement_version_id"],
                              cycle_verdict["repurchase_line"], cycle_verdict["status"])

    # 基線兩條並列＋旺淡季標注（票 #39，決策 0025 第 4 點）：純顯示用途，不影響上面的判定。
    cycle_verdict["baseline_comparison"] = dual_baseline(conn, brand_id, cycle,
                                                         exclude_cycle_id=cycle_id)

    # 通路對照卡（票 #40，決策 0025 第二節 B）：外溢／互噬／缺資料燈號，純顯示用途，
    # 不影響上面的判定——不算歸因比例，只是規則判定的粗標籤＋人話說明。連兩期灰燈才算
    # 「灰燈債務」，只降級顯示可信度、不進打斷佇列、不擋路。
    channel_signal = orders_channel.signal(conn, brand_id, cycle)
    channel_signal["gray_light_debt"] = orders_channel.gray_light_debt(
        conn, brand_id, cycle, ads_repo.list_cycles)
    cycle_verdict["channel_comparison"] = channel_signal

    # 成色標籤＋GA4 漏率反偵測（票 #41，決策 0025 懶人優先第 6 點／小補丁組第 5 點）：
    # 純顯示用途，不影響上面的判定；資料不足也照樣給結論，只是標成「Meta 視角判讀」。
    cycle_verdict["data_grade"] = ads_inflation.data_grade(conn, brand_id)
    cycle_verdict["ga4_leak"] = ads_inflation.ga4_leak_estimate(conn, brand_id, cycle)

    # 素材層成效歸因（修憲落地 G2，決策 0035 第二節第 4 點）：純顯示用途，不影響上面的判定。
    cycle_verdict["asset_breakdown"] = _asset_totals(conn, brand_id, cycle_id)

    # 假設結案（票 #53）：還沒結案的策略假設，AI 依這期各產品／整體的判讀結論預選一個答案。
    # 沒有待結案假設就不必呼叫 LLM（懶人優先，決策 0025 第五節）。
    product_status = {r["product_id"]: r["status"] for r in readings}
    product_reasons = {r["product_id"]: r["reasons"] for r in readings}
    pending_hypotheses = [h for h in ads_repo.list_cycle_hypotheses(conn, brand_id, cycle_id)
                          if h["status"] in PENDING_HYPOTHESIS_STATUSES]
    hyp_items = []
    for h in pending_hypotheses:
        status = product_status.get(h["product_id"], cycle_verdict["status"])
        reasons = product_reasons.get(h["product_id"], cycle_verdict["reasons"])
        preselect = _preselect_hypothesis_status(status)
        fallback_reason = f"這期判讀結論是「{STATUS_LABELS[status]}」，依據：" + "；".join(reasons)
        hyp_items.append({
            "id": h["id"], "statement": h["statement"],
            "type_label": HYPOTHESIS_TYPE_LABELS.get(h["hypothesis_type"], h["hypothesis_type"]),
            "preselect": preselect, "fallback_reason": fallback_reason,
        })
    llm_reasons = _explain_hypotheses(conn, brand_id, cycle, hyp_items)
    cycle_verdict["hypothesis_reviews"] = [
        {"id": it["id"], "statement": it["statement"], "type_label": it["type_label"],
         "preselect": it["preselect"], "ai_reason": llm_reasons.get(it["id"]) or it["fallback_reason"]}
        for it in hyp_items
    ]

    readings.append(cycle_verdict)

    explanation = _explain(conn, brand_id, cycle, readings, confidence, baseline)

    for verdict in readings:
        conn.execute(
            "INSERT INTO performance_reading (id, brand_id, campaign_cycle_id, product_id,"
            " status, rule_result_json, confidence_level, llm_explanation, llm_task_id,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id("prd"), brand_id, cycle_id, verdict["product_id"], verdict["status"],
             json.dumps({"reasons": verdict["reasons"], "kpis": verdict["kpis"],
                        "statistical_level": verdict["statistical_level"],
                        "statistical_level_label": verdict["statistical_level_label"],
                        "statistical_note": verdict["statistical_note"],
                        "unsettled_ratio": verdict.get("unsettled_ratio"),
                        "unsettled_note": verdict.get("unsettled_note"),
                        "is_tentative": verdict.get("is_tentative"),
                        "repurchase_line": verdict.get("repurchase_line"),
                        "baseline_comparison": verdict.get("baseline_comparison"),
                        "channel_comparison": verdict.get("channel_comparison"),
                        "data_grade": verdict.get("data_grade"),
                        "ga4_leak": verdict.get("ga4_leak"),
                        "asset_breakdown": verdict.get("asset_breakdown"),
                        "hypothesis_reviews": verdict.get("hypothesis_reviews")},
                        ensure_ascii=False),
             confidence["label"],
             explanation["text"] if verdict["product_id"] is None else None,
             explanation["task_id"], ts),
        )

    ads_repo.update_cycle_status(conn, brand_id, cycle_id, status="EVALUATING", actor=actor)

    # 期中檢查點是事件不是死線（決策 0025 審查補遺第 4 點）：期末判讀一跑，還沒被處理的
    # day3／day7 提醒併入這裡的結論，不用使用者事後補做。這裡才 import 避開
    # onboarding → checkpoint 沒問題，但集中在呼叫點才 import 比照 nextcycle 的既定寫法。
    from app.ads import onboarding as ads_onboarding
    ads_onboarding.resolve_stale_checkpoint_reminders(conn, brand_id, cycle_id, actor=actor)
    conn.commit()

    # 判讀完成的同時就把下期準備好（決策 0022 第 15 點）：預算建議、規則卡、回音室檢查。
    # 這裡才 import 是為了避開 nextcycle → reading 的循環相依。
    from app.ads import nextcycle
    nextcycle.build(conn, brand_id, cycle_id, actor)
    return True, None


def finalize(conn, brand_id: str, cycle_id: str, actor: str) -> tuple:
    """期末＋14 天最終結算（決策 0025 判讀節奏第 5 點）：重跑一次判讀
    （trigger_reason='final_settlement'，未結案佔比理論上該已經收斂），完成後把檔期標成
    CLOSED——這是全系統唯一會把狀態轉成 CLOSED 的地方。"""
    ok, err = run(conn, brand_id, cycle_id, actor, trigger_reason="final_settlement")
    if not ok:
        return ok, err
    ads_repo.update_cycle_status(conn, brand_id, cycle_id, status="CLOSED", actor=actor)
    _flag_unresolved_hypotheses(conn, brand_id, cycle_id)
    # 原型階段結束判定（修憲落地 A6，決策 0037 第一節）：結算完成且這期實際花費 > 0
    # 才算數；已經翻過旗標的話 check_and_flag 內部直接短路，不重複提醒。
    cycle_totals = ads_performance.totals(conn, brand_id, cycle_id)
    prototype_phase.check_and_flag(
        conn, actual_spend=cycle_totals.get("spend") or 0, actor=actor, cycle_id=cycle_id)
    return True, None


# ---------------------------------------------------------------------------
# 補件驅動回溯重判（票 #38，決策 0025 懶人優先第 3 點）：晚到檔案丟進拖檔口時，
# app/orders/dispatch.py 對每個受影響期別呼叫這裡。只有「這期已經判讀過、且不在投放中」
# 才算「晚到」——還在 LIVE 或根本沒判讀過都是正常匯入，不是補件，原樣略過。
# ---------------------------------------------------------------------------

_DIFF_SYSTEM = (
    "你是資深廣告投手，正在跟老闆解釋為什麼補進晚到的資料後，這期的判讀結果變了。"
    "只回傳 JSON，不要任何 JSON 以外的文字。全部用繁體中文，白話、不用行銷術語。"
)


def _explain_diff(conn, brand_id: str, cycle: dict, diffs: list, before_status: Optional[str],
                  after_status: Optional[str]) -> Optional[str]:
    """把 settlement.diff_versions() 算好的逐鍵差異交給 LLM 翻成人話（決策 0016 硬性原則 4：
    數字走程式，AI 只翻人話）。失敗就沒有這段話，重判本身不受影響。"""
    lines = [f"- {scope}.{key}：{before} → {after}" for scope, key, before, after in diffs[:30]]
    conclusion_line = (
        f"判讀結論從「{STATUS_LABELS.get(before_status, before_status)}」變成"
        f"「{STATUS_LABELS.get(after_status, after_status)}」。"
        if before_status != after_status else "判讀結論本身沒有變。"
    )
    user_text = "\n\n".join([
        f"檔期：{cycle['start_date']} 到 {cycle['end_date']}",
        conclusion_line,
        "補件後數字上的變化：\n" + "\n".join(lines),
        "請用 2 到 3 句白話解釋這次補件造成了什麼變化、為什麼結論這樣調整或維持。"
        "不要編造原本沒有的數字。",
        '輸出格式：只回傳 {"text": "..."}',
    ])
    task = gateway.run_task(
        conn, PROVIDER, brand_id=brand_id, task_type="settlement_diff_explanation",
        prompt_template_id="settlement_diff_explanation", prompt_template_version="v1",
        system=_DIFF_SYSTEM, messages=[{"role": "user", "content": user_text}],
        context=gateway.TaskContext(
            context_scope={"brand_id": brand_id, "campaign_cycle_id": cycle["id"]},
            knowledge_item_ids=[], brand_version=0),
        options=gateway.TaskOptions(max_tokens=800),
    )
    if task["status"] != "succeeded":
        return None
    data = gateway.parse_json_reply(task["rendered_output"])
    text = data.get("text") if isinstance(data, dict) else None
    return text if isinstance(text, str) and text.strip() else None


REVERSAL_MESSAGE = "補件後判讀翻盤，這期結論整個變了，去看新結論。"


def rerun_for_late_data(conn, brand_id: str, cycle_id: str, *, actor: str) -> Optional[dict]:
    """晚到的檔案（Meta CSV／訂單匯出）丟進拖檔口後，對受影響期別呼叫這個函式：
    若這期已經判讀過（有版次）且不在投放中，自動重判＋算差異摘要＋分級翻盤警示；
    否則（還在 LIVE、或根本還沒判讀過）代表這不是「補件」，原樣略過回 None。
    """
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    if cycle is None or cycle["status"] == "LIVE":
        return None
    before_snapshot = ads_settlement.load_snapshot(conn, brand_id, cycle_id)
    if before_snapshot is None:
        return None  # 這期還沒判讀過，這是第一次判讀，不是補件
    before_loaded = load(conn, brand_id, cycle_id)
    before_status = before_loaded["cycle"]["status"] if before_loaded["cycle"] else None

    ok, _err = run(conn, brand_id, cycle_id, actor, trigger_reason="late_data")
    if not ok:
        return None

    after_snapshot = ads_settlement.load_snapshot(conn, brand_id, cycle_id)
    diffs = ads_settlement.diff_versions(
        conn, brand_id, cycle_id, before_snapshot["settlement_version"],
        after_snapshot["settlement_version"])
    if not diffs:
        return None  # 補件沒有真的改變任何數字，不必吵（決策 0025：翻盤警示分級，微調不吵）

    after_status = load(conn, brand_id, cycle_id)["cycle"]["status"]
    shift = classify_verdict_shift(before_status, after_status)
    explanation = _explain_diff(conn, brand_id, cycle, diffs, before_status, after_status)
    if explanation:
        ads_settlement.record_diff_summary(
            conn, brand_id, cycle_id, after_snapshot["settlement_version_id"], explanation)

    if shift == "reversal":
        core_interrupts.enqueue(
            conn, category="reading_reversal",
            dedupe_key=f"reading_reversal:{after_snapshot['settlement_version_id']}",
            message=REVERSAL_MESSAGE, brand_id=brand_id, campaign_cycle_id=cycle_id,
            action_url=f"/brands/{brand_id}/ads/{cycle_id}/performance",
        )
        conn.commit()

    return {
        "version": after_snapshot["settlement_version"], "diffs": diffs,
        "explanation": explanation, "shift": shift,
        "before_status": before_status, "after_status": after_status,
    }


_SYSTEM = (
    "你是資深廣告投手，正在把系統算出來的判讀結果講給一位不懂行銷的老闆聽。"
    "只回傳 JSON，不要任何 JSON 以外的文字。全部用繁體中文，白話、不用行銷術語。"
)


def _explain(conn, brand_id: str, cycle: dict, readings: list, confidence: dict,
             baseline: dict) -> dict:
    """把程式判好的結論交給 LLM 翻成人話。失敗就沒有這段話，判讀本身不受影響。"""
    lines = []
    for verdict in readings:
        who = verdict["product_name"] or "整體"
        lines.append(f"- {who}：{STATUS_LABELS[verdict['status']]}"
                     f"（依據：{'；'.join(verdict['reasons'])}）")

    user_text = "\n\n".join([
        f"檔期：{cycle['start_date']} 到 {cycle['end_date']}，"
        f"計畫預算 {cycle['budget']:,.0f}",
        "系統算出來的判讀結果（這些結論已經定了，你不要改也不要重算）：\n" + "\n".join(lines),
        f"本期資料可信度：{confidence['label']}——{confidence['note']}",
        ("這個品牌過去的水準：" + "、".join(f"{k} {v}" for k, v in baseline.items())
         if baseline else "這個品牌還沒有過去的數字可以比較。"),
        "請寫一段 3 到 5 句的白話說明：這期發生了什麼、為什麼是這個結論、接下來該注意什麼。"
        "不要加上系統沒算出來的結論，不要編造數字。資料不足時就直說看不出來。",
        '輸出格式：只回傳 {"text": "..."}',
    ])

    task = gateway.run_task(
        conn, PROVIDER, brand_id=brand_id, task_type="performance_reading",
        prompt_template_id="performance_reading", prompt_template_version="v1",
        system=_SYSTEM, messages=[{"role": "user", "content": user_text}],
        context=gateway.TaskContext(
            context_scope={"brand_id": brand_id, "campaign_cycle_id": cycle["id"]},
            knowledge_item_ids=[], brand_version=0),
        options=gateway.TaskOptions(max_tokens=2000),
    )
    if task["status"] != "succeeded":
        return {"text": None, "task_id": None}
    data = gateway.parse_json_reply(task["rendered_output"])
    text = data.get("text") if isinstance(data, dict) else None
    return {"text": text if isinstance(text, str) and text.strip() else None,
            "task_id": task["id"]}


_HYPOTHESIS_SYSTEM = (
    "你是資深廣告投手，正在跟老闆解釋這期的數據支不支持他當初提的策略假設。"
    "系統已經算好每條假設該打哪個結論，你不能改也不能重算，只負責把結論翻成一句白話理由。"
    "只回傳 JSON，不要任何 JSON 以外的文字。全部用繁體中文，不用行銷術語。"
)


def _explain_hypotheses(conn, brand_id: str, cycle: dict, items: list) -> dict:
    """把程式已經判好的假設結案結果交給 LLM 各寫一句理由。失敗（或沒有待結案假設）就整批
    用呼叫端準備好的 fallback_reason（純程式產生，不必等 LLM——決策 0016 硬性原則 4）。"""
    if not items:
        return {}
    lines = [f"- id={it['id']}：假設「{it['statement']}」，系統已判定"
            f"「{HYPOTHESIS_STATUS_LABELS[it['preselect']]}」，依據：{it['fallback_reason']}"
            for it in items]
    user_text = "\n\n".join([
        f"檔期：{cycle['start_date']} 到 {cycle['end_date']}",
        "以下每條假設，系統已經算好結論（不要改、不要重算）：\n" + "\n".join(lines),
        "請針對每條假設寫一句不超過 60 字的白話說明，解釋這期的數據為什麼支持這個結論。"
        "不要編造原本沒有的數字。",
        '輸出格式：只回傳 {"reasons": {"id": "一句話", ...}}，key 要跟上面給的 id 一致。',
    ])
    task = gateway.run_task(
        conn, PROVIDER, brand_id=brand_id, task_type="hypothesis_review",
        prompt_template_id="hypothesis_review", prompt_template_version="v1",
        system=_HYPOTHESIS_SYSTEM, messages=[{"role": "user", "content": user_text}],
        context=gateway.TaskContext(
            context_scope={"brand_id": brand_id, "campaign_cycle_id": cycle["id"]},
            knowledge_item_ids=[], brand_version=0),
        options=gateway.TaskOptions(max_tokens=1200),
    )
    if task["status"] != "succeeded":
        return {}
    data = gateway.parse_json_reply(task["rendered_output"])
    reasons = data.get("reasons") if isinstance(data, dict) else None
    if not isinstance(reasons, dict):
        return {}
    return {k: v for k, v in reasons.items() if isinstance(v, str) and v.strip()}


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


def resolve_hypotheses(conn, brand_id: str, cycle_id: str, verdicts: dict, *, actor: str) -> int:
    """判讀頁假設結案（票 #53）：verdicts＝{hypothesis_id: 'supported'/'rejected'/'inconclusive'}。
    只處理目前仍待結案（proposed／testing）的假設，其餘忽略（防重複送出、防偽造 id）。
    判為「成立」才入帳 `learning_ledger`（決策 0030 第一節第 1 點：ledger 只收經判讀驗證且
    經人確認的正面學習，不成立／看不出來只更新假設狀態，不入帳）。回傳這次實際更新的筆數。
    """
    if ads_repo.get_cycle(conn, brand_id, cycle_id) is None:
        raise ValueError("找不到廣告檔期")
    pending = {h["id"]: h for h in ads_repo.list_cycle_hypotheses(conn, brand_id, cycle_id)
              if h["status"] in PENDING_HYPOTHESIS_STATUSES}
    loaded = load(conn, brand_id, cycle_id)
    reading_id_by_product = {p["product_id"]: p["id"] for p in loaded["products"]}
    cycle_reading_id = loaded["cycle"]["id"] if loaded["cycle"] else None

    updated = 0
    for hyp_id, verdict in verdicts.items():
        hyp = pending.get(hyp_id)
        if hyp is None or verdict not in HYPOTHESIS_STATUS_LABELS:
            continue
        bi.update_hypothesis_status(conn, brand_id, hyp_id, status=verdict, actor=actor)
        updated += 1
        if verdict != "supported":
            continue
        # 修憲落地 G4（決策 0035 第三節第 6 點）：假設結案入帳原本是確認偏誤幫浦——AI 預選
        # 加一路下一步等於橡皮圖章。統計缺陷修好後重新開回來：預選一律改看不出來、只有
        # 程式算得出方向才預選成立、maintain 移出正面訊號、3–10 筆轉換不准喊加碼停損
        # （見 judge()），入帳的產物因此不再是橡皮圖章。
        sample_size = _conversions_for_hypothesis(conn, brand_id, cycle_id, hyp["product_id"])
        ads_repo.create_learning_ledger_entry(
            conn, brand_id, learning_text=hyp["statement"],
            applicability_scope="product" if hyp["product_id"] else "brand",
            created_by=actor, actor=actor, product_id=hyp["product_id"],
            source_cycle_id=cycle_id,
            source_reading_id=reading_id_by_product.get(hyp["product_id"], cycle_reading_id),
            source_hypothesis_id=hyp_id, sample_size=str(sample_size),
            confidence=_ledger_confidence(conn, brand_id, hyp["product_id"], hyp["statement"],
                                          sample_size),
        )
    conn.commit()
    return updated


def _ledger_confidence(conn, brand_id: str, product_id: Optional[str], learning_text: str,
                       sample_size: int) -> str:
    """ledger 自己的可信度（修憲落地 G4，決策 0035 第三節第 8 點）：樣本數＋是否被獨立
    重測過，回傳 `LEDGER_CONFIDENCE_LABELS` 的鍵，不是 `ads_inflation.data_grade()` 的
    成色標籤。"重測過"＝這個品牌、這個範圍（品牌整體或同一產品）下，同一句學習文字之前
    已經進過帳——不同期別各自算出同一個結論，不是同一次判讀的巧合。
    """
    retested = bi.learning_ledger_entry_exists(
        conn, brand_id, product_id=product_id, learning_text=learning_text)
    if retested:
        return "reinforced"
    if sample_size and sample_size >= MIN_CONVERSIONS_FOR_DIRECTIONAL_CALL:
        return "moderate"
    return "preliminary"


# ---------------------------------------------------------------------------
# needs_revalidation 到期重測（修憲落地 G4，決策 0035 第三節第 10 點）
# ---------------------------------------------------------------------------

# 學習條目掛滿幾期都沒被重新驗證，就該提醒複查——只提醒、不擋路、不自動下架（決策 0013）。
LEDGER_REVALIDATION_WINDOW_CYCLES = 3


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
        action_url=f"/brands/{brand_id}/ads/{cycle_id}/performance",
    )
    conn.commit()


def load(conn, brand_id: str, cycle_id: str) -> dict:
    """讀回判讀結果：{cycle: 檔期層, products: [產品層...]}。"""
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM performance_reading WHERE brand_id = ? AND campaign_cycle_id = ?"
        " ORDER BY product_id IS NULL, created_at", (brand_id, cycle_id),
    )]
    products, cycle_row = [], None
    for row in rows:
        row["result"] = json.loads(row["rule_result_json"] or "{}")
        row["status_label"] = STATUS_LABELS.get(row["status"], row["status"])
        if row["product_id"] is None:
            cycle_row = row
        else:
            product = bi.get_product(conn, brand_id, row["product_id"])
            row["product_name"] = product["name"] if product else "（產品已刪除）"
            products.append(row)
    if cycle_row is not None:
        cycle_row["hypothesis_reviews"] = _pending_hypothesis_reviews(
            conn, brand_id, cycle_id, cycle_row)
    return {"cycle": cycle_row, "products": products}


def prediction_settlement(conn, brand_id: str, cycle: Optional[dict]) -> Optional[dict]:
    """兌現預言卡的資料組裝（決策 0039 第 13–16 條，票 F5）。cycle 傳哪一期就對哪一期的
    區間快照兌現——判讀頁出口傳「正在看的這期」自己，第二期檔期內頁出口傳「上一期」
    （見 app/ads/routes.py 兩個呼叫端；上一期由 onboarding.previous_cycle() 取得，本函式
    接受 None 直接短路，呼叫端不必自己先判斷有沒有上一期）。快照讀取一律走
    forecast_snapshot()（票 F1單點 helper），沒存過快照的期不出卡，不補算（鐵則 16）；
    一筆成效資料都還沒有時同樣不出卡——「兌現」需要真的有結果可以對，不能拿零筆資料充數。
    """
    from app.ads import onboarding as ads_onboarding

    if cycle is None:
        return None
    forecast = ads_onboarding.forecast_snapshot(cycle)
    if not forecast:
        return None
    totals = ads_performance.totals(conn, brand_id, cycle["id"])
    if not totals["rows"]:
        return None
    return {
        "forecast": forecast,
        "clicks": totals["clicks"],
        "conversions": totals["conversions"],
        "spend": totals["spend"],
        "budget": cycle["budget"],
        "gap": ads_onboarding.forecast_gap(forecast, totals),
    }
