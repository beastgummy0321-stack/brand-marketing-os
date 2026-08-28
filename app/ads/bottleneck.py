"""app/ads/bottleneck.py — 錢卡在哪一關（票 C2-01，ADR 0024 調度台核心觸發來源之一）。

CPA 恆等式拆解：CPA = (CPM / 1000) / (CTR × CVR)，三個因子（cpm／ctr／cvr）的貢獻度
用對數換算（乘法關係要取對數才能加總得 1）。①站裁決五條見
`.scratch/orchestrator/issues/02-bottleneck-tree.md`：尺用這個品牌自己的歷史
（`reading.brand_baseline()`），沒歷史才退回產業基準且只當旁列參考、不參與判定；
七個判定規則走完，`factors` 全部列出並排序，排序＝貢獻度不是人訂的優先序；結果放判讀頁
跟判讀狀態並列；舊檔期的 CPM／CVR 不回填。

純函數，比照 `reading.judge()` 的慣例：不寫資料庫，`conn`／`brand_id` 只用來讀這個品牌的
規則卡門檻（CPA 黃燈倍率、素材疲勞警示門檻），`conn` 可為 None。`pacing_status` 由呼叫端
用既有 `pacing.classify()` 算好傳進來，這裡不自己讀檔期日期；同理，素材疲勞判定要用的
最高頻率由呼叫端存進 `totals["max_frequency"]`（比照 `reading.py` 的
`cycle_totals["unsettled_ratio"]` 寫法，見該檔 319 行）——這支唯一能碰資料庫的地方只有
規則卡，不能自己查 performance_snapshot（這裡的 `diagnose()` 簽章沒有 cycle_id）。

對外進入點：`diagnose()`。誰依賴它：`routes_campaigns_performance_api.py` 的
`performance_get()`。
"""

import math

from app.ads import performance as ads_performance
from app.ads import reading as ads_reading
from app.core import rule_cards

# 三個因子固定的人話標籤（票 C2-01 JSON 契約逐字照用，不隨漲跌換字——「偏低」「變貴」
# 是欄位名字不是即時判斷，判斷結果看 ratio／share）。
_FACTOR_LABELS = {"ctr": "點擊率偏低", "cpm": "曝光成本變貴", "cvr": "成交率"}

_NO_BASELINE_DETAIL = "還沒有你自己的歷史可比"
_REFERENCE_LABEL = "一般電商參考值"

# 素材疲勞判定固定用冷受眾門檻（比照 health_lights._fatigue_light 的既有寫法）：
# diagnose() 簽章沒有受眾類型參數，且冷受眾是最常見、最保守的預設。
_FATIGUE_AUDIENCE_TYPE = "cold"

# 總倍率落在 1 的正負這個範圍內，就當作「整體沒有淨變化」，不歸因貢獻度。
NO_NET_CHANGE_BAND = 0.01


def _ratio(worse_numerator: float | None, worse_denominator: float | None) -> float | None:
    """算一個因子「變差了幾倍」：分子分母任一個是 None、分母是 0、或除出來 <= 0
    （log 需要正數）一律回 None——不硬猜、也不讓後面的 log 炸掉。"""
    if worse_numerator is None or worse_denominator is None or not worse_denominator:
        return None
    value = worse_numerator / worse_denominator
    return round(value, 4) if value > 0 else None


def _factor(key: str, ratio: float | None, detail: str) -> dict:
    return {"key": key, "label": _FACTOR_LABELS[key], "ratio": ratio, "share": None,
           "detail": detail, "sub": None}


def _detail(current: float | None, base: float | None, fmt) -> str:
    if current is None or base is None:
        return _NO_BASELINE_DETAIL
    return fmt(current, base)


def diagnose(totals: dict, *, baseline: dict, brand_id: str,
            pacing_status: str | None = None, conn=None) -> dict:
    """一組本期數字 + 這個品牌自己的歷史基線 → 錢卡在哪一關。回傳形狀見票 C2-01。"""
    baseline = baseline or {}
    impressions = totals.get("impressions") or 0
    kpis = totals.get("kpis") or ads_performance.compute_kpis(totals)

    # 1. 樣本不足——不下任何結論
    if impressions < ads_reading.MIN_IMPRESSIONS:
        return {
            "reliable": False,
            "reason_unreliable": f"曝光只有 {impressions:,.0f} 次，樣本太少算不出可靠的比例",
            "underspend": False, "cpa_ratio": None, "primary": None, "factors": [],
            "reference": None,
        }

    # 2. 流量不足不中止判定，其餘照算（裁決第 3 條：七個判定規則全部走完，全部列出）
    underspend = pacing_status == "underspend"

    ctr, cpm, cvr = kpis.get("ctr"), kpis.get("cpm"), kpis.get("cvr")
    base_ctr, base_cpm, base_cvr = baseline.get("ctr"), baseline.get("cpm"), baseline.get("cvr")
    reference = {"ctr": ads_reading.INDUSTRY_FALLBACK["ctr"], "label": _REFERENCE_LABEL}

    cpm_ratio = _ratio(cpm, base_cpm)
    ctr_ratio = _ratio(base_ctr, ctr)
    cpm_detail = _detail(cpm, base_cpm, lambda c, b: f"這期 NT$ {c:,.0f}，你自己的過去是 NT$ {b:,.0f}")
    ctr_detail = _detail(ctr, base_ctr, lambda c, b: f"這期 {c:.2%}，你自己的過去是 {b:.2%}")

    if cvr is None or kpis.get("cpa") is None:
        # 6. 零轉換（cvr 或 cpa 算不出來）：只拆 CPM 與 CTR 兩個因子，cpa_ratio／share
        # 全部 None，改用各自的 ratio 排序——誠實標示這期沒有成交，算不出每筆成本。
        factors = [_factor("cpm", cpm_ratio, cpm_detail), _factor("ctr", ctr_ratio, ctr_detail)]
        factors.sort(key=lambda f: (f["ratio"] is None, -(f["ratio"] or 0)))
        return {
            "reliable": True, "reason_unreliable": None, "underspend": underspend,
            "cpa_ratio": None, "primary": None, "factors": factors, "reference": reference,
        }

    cvr_ratio = _ratio(base_cvr, cvr)
    cvr_detail = _detail(cvr, base_cvr, lambda c, b: f"這期 {c:.2%}，你自己的過去是 {b:.2%}")

    # 3. CPA 恆等式拆解：cpa_ratio 直接由三個因子的 ratio 相乘得出（不是各自獨立跟
    # baseline["cpa"] 比較）——這樣三個 ratio 相乘必然等於 cpa_ratio，恆等式不會因為
    # 「cpa 的歷史中位數」跟「cpm/ctr/cvr 各自的歷史中位數」不是同一批檔期而對不起來。
    cpa_ratio = None
    if cpm_ratio is not None and ctr_ratio is not None and cvr_ratio is not None:
        cpa_ratio = round(cpm_ratio * ctr_ratio * cvr_ratio, 6)

    def _share(ratio: float | None) -> float | None:
        if ratio is None or cpa_ratio is None:
            return None
        # 總倍率貼近 1 時 ln(cpa_ratio) 趨近 0，貢獻度會炸成天文數字（審查發現 1：
        # 曝光成本貴一倍、點擊率好一倍幾乎完全抵銷，實測印出「貢獻約 138664%」）。
        # 這一帶本來就沒有淨變化可歸因，回 None 讓畫面不印貢獻度，不是回 0（0 會被
        # 讀成「這項沒有影響」，但它其實影響很大，只是被別項抵銷了）。
        if abs(cpa_ratio - 1) < NO_NET_CHANGE_BAND:
            return None
        return round(math.log(ratio) / math.log(cpa_ratio), 6)

    factors = [
        _factor("cpm", cpm_ratio, cpm_detail),
        _factor("ctr", ctr_ratio, ctr_detail),
        _factor("cvr", cvr_ratio, cvr_detail),
    ]
    for f in factors:
        f["share"] = _share(f["ratio"])

    if any(f["share"] is not None for f in factors):
        factors.sort(key=lambda f: (f["share"] is None, -(f["share"] or 0)))
    else:
        # 7. 基線缺（三個因子的歷史中位數不是同時都拿得到）：share 算不出來，改用各自的
        # ratio 排序，跟零轉換那條路走同一套 fallback，不另開一套規則。
        factors.sort(key=lambda f: (f["ratio"] is None, -(f["ratio"] or 0)))

    positive = [f for f in factors if f["share"] is not None and f["share"] > 0]
    primary = max(positive, key=lambda f: f["share"])["key"] if positive else None

    # 4. 門檻：cpa_ratio 沒超過規則卡「CPA 黃燈倍率」就不算有值得報的瓶頸——factors
    # 照樣回（使用者要看全部），但呼叫端知道沒有值得報的瓶頸。
    if cpa_ratio is not None:
        cpa_yellow_multiplier = rule_cards.get_value(conn, brand_id, "health_lights", "cpa_yellow_multiplier")
        if cpa_ratio < cpa_yellow_multiplier:
            primary = None

    # 5. CPM 是 primary 時，再看素材疲勞——頻率讀不到就不猜（不猜 sub，不是不猜 primary）。
    if primary == "cpm":
        frequency = totals.get("max_frequency")
        if frequency is not None:
            status = rule_cards.classify_ad_frequency(conn, brand_id, _FATIGUE_AUDIENCE_TYPE, frequency)
            cpm_factor = next(f for f in factors if f["key"] == "cpm")
            cpm_factor["sub"] = "audience_too_narrow" if status != "safe" else None

    return {
        "reliable": True, "reason_unreliable": None, "underspend": underspend,
        "cpa_ratio": cpa_ratio, "primary": primary, "factors": factors, "reference": reference,
    }
