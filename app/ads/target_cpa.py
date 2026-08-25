# -*- coding: utf-8 -*-
"""app/ads/target_cpa.py — 目標 CPA 三層鏈＋投放量護欄＋三檔預算卡（票 21）。

設計依據見 .scratch/creative-studio/issues/21-target-cpa-guardrail.md（已查證，勿另立機制）：
只服務轉換型目標（sales／leads）。非轉換型（awareness／traffic／engagement）走
`non_conversion_range()`，完全不碰三層鏈——那些目標沒有 CPA 這個概念，硬套只會生出
垃圾數字（鐵則 16：拿不到就不要放）。

目標 CPA 三層鏈依序嘗試，第一個算得出來就用：
1. 歷史實際 CPA：同品牌同目標最近一期已結束（CLOSED）檔期，花費 ÷ 淨歸因訂單數。
2. 打平 CPA（僅 sales）：這期只對應單一產品時，用該產品單位毛利當打平 CPA。
3. 引導推算：兩題表單存進 brand_performance_baseline（metric='target_cpa'），這裡只負責讀
   最近一筆；寫入是 `save_guided_target_cpa()`，兩邊分開是因為「解析」跟「使用者填表送出」
   是不同時間點發生的動作，硬塞一支函式會把唯讀查詢跟資料庫寫入攪在一起。
"""

from datetime import date
from typing import Optional

from app.ads import budget as budget_calc
from app.ads import codes as ads_codes
from app.ads import performance as ads_performance
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi

CONVERSION_OBJECTIVES = ("sales", "leads")

# Meta 廣告的實務基準：一個廣告組合每週要有約 50 次轉換才有機會穩定跑出學習期。
# 不是精算，是業界常見的下限經驗值（票 21 已查證，這裡不另立機制）。
WEEKLY_CONVERSIONS_PER_GROUP = 50.0
CREATIVES_PER_GROUP_MIN = 3
CREATIVES_PER_GROUP_MAX = 5

# 非轉換型目標抓不到 CPA，退而求其次用「上期同目標實際花費」抓一個區間，
# ±30% 是粗估緩衝，不是精算門檻。
NON_CONVERSION_RANGE_RATIO = 0.3

LEARNING_PHASE_NOTE = "新檔期會重跑 Meta 學習期，初期 CPA 偏高屬正常。"


# ---------------------------------------------------------------------------
# 三層鏈：解析
# ---------------------------------------------------------------------------

def _historical_tier(conn, brand_id: str, objective: str) -> Optional[dict]:
    """第 1 層：同目標最近一期已結束檔期的實際 CPA。查無廣告碼或淨歸因數為 0 就跳下一期。"""
    cycles = [c for c in ads_repo.list_cycles(conn, brand_id)
              if c["objective"] == objective and c["status"] == "CLOSED"]
    for cycle in cycles:  # list_cycles 已依 start_date DESC 排序，最近一期排最前
        codes = ads_codes.list_codes(conn, brand_id, cycle["id"])
        if not any(c["source_type"] == "ad" for c in codes):
            continue
        net_count = ads_codes.attribution_summary(conn, brand_id, cycle["id"])["net"]["count"]
        if not net_count:
            continue
        spend = ads_performance.totals(conn, brand_id, cycle["id"])["spend"]
        return {
            "tier": "history", "value": round(spend / net_count, 2),
            "basis_label": f"依 {cycle['start_date']} 那期實際成效：花費 ÷ 淨歸因訂單數",
        }
    return None


def _breakeven_tier(conn, brand_id: str, product_ids: list) -> Optional[dict]:
    """第 2 層（僅 sales）：這期只對應單一產品時，用該產品單位毛利當打平 CPA。"""
    if len(product_ids) != 1:
        return None
    margin = budget_calc.gross_margin(bi.get_product_economics(conn, brand_id, product_ids[0]))
    if margin is None:
        return None
    return {"tier": "breakeven", "value": round(margin, 2),
            "basis_label": "打平 CPA：這期唯一產品的單位毛利（賣一件不賺不賠的上限）"}


def _guided_tier(conn, brand_id: str) -> Optional[dict]:
    """第 3 層：讀最近一筆已存的引導推算值（brand-level，product_id 為 None）。"""
    baselines = bi.list_brand_performance_baselines(conn, brand_id)
    row = next((b for b in baselines if b["metric"] == "target_cpa" and b["product_id"] is None),
              None)
    if row is None:
        return None
    return {"tier": "guided", "value": row["value"], "basis_label": row["basis_note"] or "引導推算"}


def resolve_target_cpa(conn, brand_id: str, objective: str,
                        product_ids: Optional[list] = None) -> Optional[dict]:
    """目標 CPA 三層鏈，依序嘗試，回傳 {tier, value, basis_label} 或 None（三層都不可用）。"""
    tier = _historical_tier(conn, brand_id, objective)
    if tier:
        return tier
    if objective == "sales":
        tier = _breakeven_tier(conn, brand_id, product_ids or [])
        if tier:
            return tier
    return _guided_tier(conn, brand_id)


def save_guided_target_cpa(conn, brand_id: str, *, events_per_sale: float, margin_per_sale: float,
                           actor: str) -> dict:
    """引導推算表單送出：目標 CPA ＝ 每單毛利 ÷ 平均幾個轉換事件成交一單，存進
    brand_performance_baseline（不新增資料表，只用既有欄位）。"""
    if not events_per_sale or events_per_sale <= 0:
        raise ValueError("平均幾個轉換事件成交一單，請填大於 0 的數字")
    if not margin_per_sale or margin_per_sale <= 0:
        raise ValueError("成交一單大約賺多少，請填大於 0 的數字")
    value = round(margin_per_sale / events_per_sale, 2)
    basis_note = (f"引導推算：成交一單毛利 {margin_per_sale:g} ÷ 平均 {events_per_sale:g} "
                 f"個轉換事件成交一單 ＝ {value:g}")
    return bi.create_brand_performance_baseline(
        conn, brand_id, actor=actor, metric="target_cpa", value=value,
        as_of_date=date.today().isoformat(), created_by=actor, basis_note=basis_note)


# ---------------------------------------------------------------------------
# 護欄公式與三檔預算卡：純數學，不碰資料庫
# ---------------------------------------------------------------------------

def volume_guardrail(weekly_budget: float, target_cpa: float) -> dict:
    """投放量護欄：每週預算能養出幾組轉換、能撐幾組受眾／幾則素材，純顯示提醒不擋提交。"""
    if weekly_budget <= 0:
        raise ValueError("每週預算必須大於 0")
    if target_cpa <= 0:
        raise ValueError("目標 CPA 必須大於 0")
    weekly_conversions = weekly_budget / target_cpa
    groups = int(weekly_conversions // WEEKLY_CONVERSIONS_PER_GROUP)
    return {
        "weekly_conversions": round(weekly_conversions, 1),
        "groups_sustainable": groups,
        "creatives_per_group_min": CREATIVES_PER_GROUP_MIN,
        "creatives_per_group_max": CREATIVES_PER_GROUP_MAX,
        "cycle_creative_cap": groups * CREATIVES_PER_GROUP_MAX,
    }


def budget_tiers(target_cpa: float, previous_weekly_spend: Optional[float] = None) -> dict:
    """保守／建議／積極三檔週預算。積極檔上限＝上期實際週預算 × 2，沒有上期資料不設上限。"""
    if target_cpa <= 0:
        raise ValueError("目標 CPA 必須大於 0")
    cap = round(previous_weekly_spend * 2, 2) if previous_weekly_spend else None
    aggressive_raw = round(target_cpa * 100, 2)
    aggressive = min(aggressive_raw, cap) if cap is not None else aggressive_raw
    return {
        "conservative": {
            "label": "保守", "weekly_budget": round(target_cpa * 50, 2), "multiplier": 50,
            "formula": f"50 × 目標 CPA（{target_cpa:g}）／週",
        },
        "recommended": {
            "label": "建議", "weekly_budget": round(target_cpa * 75, 2), "multiplier": 75,
            "formula": f"75 × 目標 CPA（{target_cpa:g}）／週", "default": True,
        },
        "aggressive": {
            "label": "積極", "weekly_budget": aggressive, "multiplier": 100,
            "formula": f"100 × 目標 CPA（{target_cpa:g}）／週",
            "capped": cap is not None and aggressive_raw > cap, "cap": cap,
        },
    }


# ---------------------------------------------------------------------------
# 非轉換型目標：±30% 區間
# ---------------------------------------------------------------------------

def previous_actual_weekly_spend(conn, brand_id: str) -> Optional[float]:
    """上期（同品牌任意目標，取最近一期）實際週預算，供積極檔上限使用。沒有上期或上期
    還沒回填成效資料就回 None（不設上限）。"""
    cycles = ads_repo.list_cycles(conn, brand_id)
    if not cycles:
        return None
    previous = cycles[0]
    duration_days = ads_repo.derived_plan(previous).get("duration_days")
    if not duration_days:
        return None
    spend = ads_performance.totals(conn, brand_id, previous["id"])["spend"]
    if not spend:
        return None
    return round(spend / duration_days * 7, 2)


def non_conversion_range(conn, brand_id: str, objective: str) -> Optional[dict]:
    """非轉換型目標（awareness／traffic／engagement）：上期同目標實際花費 ±30%。
    沒有上期資料回 None（畫面顯示「此目標無公式依據」）。"""
    cycles = [c for c in ads_repo.list_cycles(conn, brand_id) if c["objective"] == objective]
    if not cycles:
        return None
    latest = cycles[0]
    spend = ads_performance.totals(conn, brand_id, latest["id"])["spend"]
    if not spend:
        return None
    return {
        "low": round(spend * (1 - NON_CONVERSION_RANGE_RATIO), 2),
        "high": round(spend * (1 + NON_CONVERSION_RANGE_RATIO), 2),
        "basis_label": f"依 {latest['start_date']} 那期同目標實際花費 ±30%",
    }


# ---------------------------------------------------------------------------
# 頁面組裝：依目標類型分流，非轉換型完全不碰三層鏈（不做白工計算）
# ---------------------------------------------------------------------------

def guardrail_view(conn, brand_id: str, *, objective: str, product_ids: list,
                    weekly_budget: float) -> dict:
    if objective not in CONVERSION_OBJECTIVES:
        return {"kind": "non_conversion",
                "range": non_conversion_range(conn, brand_id, objective)}

    target = resolve_target_cpa(conn, brand_id, objective, product_ids)
    if target is None:
        return {"kind": "conversion", "target_cpa": None}

    volume = volume_guardrail(weekly_budget, target["value"]) if weekly_budget > 0 else None
    tiers = budget_tiers(target["value"], previous_actual_weekly_spend(conn, brand_id))
    return {"kind": "conversion", "target_cpa": target, "volume": volume, "tiers": tiers,
            "learning_note": LEARNING_PHASE_NOTE}


# ---------------------------------------------------------------------------
# 最大虧損卡 AI 建議（票 B4R-warroom-redesign，S8R.4／S8R.5；公式來源見
# .scratch/b4-redesign/blocks.md 第 3.3 節，已查證勿另立機制）。
# ---------------------------------------------------------------------------

def _nearest_slider_step(amount: float) -> float:
    """把估算金額四捨五入到最接近的離散滑桿檔位（routes_common.SLIDER_STEPS）。
    延遲 import routes_common 避免循環匯入（該檔已 import 本模組）。"""
    from app.ads.routes_common import SLIDER_STEPS
    return min(SLIDER_STEPS, key=lambda step: abs(step - amount))


def suggest_pain_value(conn, brand_id: str, objective: str, product_ids: list) -> dict:
    """最大虧損卡的 AI 建議值＋依據（`PainSuggestion` 形狀：`amount`／`is_ai_suggested`／
    `basis_label`）。三層分流，見 blocks.md 3.3 節；三層都算不出來就回退系統預設檔位，
    `is_ai_suggested=False`（S8R.5）。"""
    default_amount = _nearest_slider_step(5000)  # DEFAULT_STEP_INDEX 對應的預設檔位

    if objective in CONVERSION_OBJECTIVES:
        target = resolve_target_cpa(conn, brand_id, objective, product_ids)
        if target:
            weekly = target["value"] * WEEKLY_CONVERSIONS_PER_GROUP
            amount = weekly * 2  # DEFAULT_DURATION_DAYS(14) / 7 週
            cap_base = previous_actual_weekly_spend(conn, brand_id)
            if cap_base:
                amount = min(amount, cap_base * 2 * 2)
            return {
                "amount": _nearest_slider_step(amount),
                "is_ai_suggested": True,
                "basis_label": f"{target['basis_label']}，估算兩週建議花費",
            }
    else:
        rng = non_conversion_range(conn, brand_id, objective)
        if rng:
            midpoint = (rng["low"] + rng["high"]) / 2
            return {
                "amount": _nearest_slider_step(midpoint),
                "is_ai_suggested": True,
                "basis_label": rng["basis_label"],
            }

    return {
        "amount": default_amount, "is_ai_suggested": False,
        "basis_label": "這個品牌還沒有數據可以參考，先用系統的保守預設值，之後幾期會抓到你自己的數字。",
    }


def demo() -> None:
    """python -m app.ads.target_cpa —— 純函數自檢（無需資料庫）。"""
    tiers = budget_tiers(200)
    assert tiers["conservative"]["weekly_budget"] == 10000
    assert tiers["recommended"]["weekly_budget"] == 15000
    assert tiers["aggressive"]["weekly_budget"] == 20000
    assert tiers["aggressive"]["capped"] is False

    capped = budget_tiers(200, previous_weekly_spend=6000)
    assert capped["aggressive"]["weekly_budget"] == 12000  # 6000*2 < 200*100
    assert capped["aggressive"]["capped"] is True

    guard = volume_guardrail(weekly_budget=5000, target_cpa=100)
    assert guard["weekly_conversions"] == 50.0
    assert guard["groups_sustainable"] == 1
    assert guard["cycle_creative_cap"] == 5

    # suggest_pain_value()：品牌完全沒有歷史資料時三層鏈都算不出來，退回系統預設檔位。
    # 對本機 Supabase stack 跑（02-3b 票 9）；create_brand() 本身會 commit，brand_id 走
    # new_id() 天生不重複，不必靠 rollback 復原。
    from app.brand_intelligence import repository as bi_repo
    from app.core import db as core_db

    with core_db.connection() as conn:
        brand = bi_repo.create_brand(conn, name="虛構示範品牌", client_name=None, actor="demo")
        suggestion = suggest_pain_value(conn, brand["id"], "sales", [])
        assert suggestion["is_ai_suggested"] is False
        assert suggestion["amount"] == _nearest_slider_step(5000)
    print("target_cpa 自檢通過")


if __name__ == "__main__":
    demo()
