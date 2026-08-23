# -*- coding: utf-8 -*-
"""app/ads/health_lights.py — 檔期健康燈號（票 B4R-warroom-redesign，GRILL-B4R-performance.md
「檔期健康燈號」小節，S8R.20／S3P.12 共用同一份邏輯，不重複兩套判定）。

四盞燈全部組裝既有函式算出來的數字，只新增「怎麼分三色」的比較門檻（不發明新資料源）：
燒錢速度 `pacing.classify()`、CPA/ROAS `performance.totals()`＋`target_cpa`／`reading.breakeven_roas()`、
疲勞 `performance.max_frequency()`＋`rule_cards.classify_ad_frequency()`。

門檻倍率（CPA×1.3、ROAS×0.8、燒錢速度門檻×0.6）是 grill 新提的合理值，掛進 rule_cards
的 `health_lights` 卡（人話頁面可看可改可重設），預設值＝這裡原本寫死的數字。

對外進入點：`compute()`。誰依賴它：作戰室成效區＋駕駛艙釘選視圖⑤兩個薄呼叫端。
"""

from datetime import date
from typing import Optional

from app.ads import pacing as ads_pacing
from app.ads import performance as ads_performance
from app.ads import reading as ads_reading
from app.ads import repository as ads_repo
from app.ads import target_cpa as ads_target_cpa
from app.brand_intelligence import repository as bi
from app.core import orchestrator as core_orchestrator
from app.core import rule_cards


def _light(status: str, value, label: str, note: str) -> dict:
    return {"status": status, "value": value, "label": label, "note": note}


def _cycle_breakeven(conn, brand_id: str, cycle_id: str) -> Optional[float]:
    """比照 `reading.run()` 既有算法：這期各產品打平投報率的平均值（reading.py:543-548）。"""
    allocations = ads_repo.list_cycle_products(conn, brand_id, cycle_id)
    breakevens = [ads_reading.breakeven_roas(bi.get_product_economics(conn, brand_id, a["product_id"]))
                  for a in allocations]
    known = [b for b in breakevens if b]
    return round(sum(known) / len(known), 2) if known else None


def _spend_rate_light(conn, brand_id: str, cycle: dict) -> dict:
    threshold = rule_cards.get_value(conn, brand_id, "pacing", "deviation_threshold_ratio")
    spend = ads_performance.totals(conn, brand_id, cycle["id"])["spend"]
    result = ads_pacing.classify(budget=cycle["budget"], spend=spend, start_date=cycle["start_date"],
                                 end_date=cycle["end_date"], today=date.today().isoformat(),
                                 threshold_pct=threshold)
    deviation = result["deviation"]
    if result["status"] == "insufficient_sample":
        return _light("insufficient", None, "燒錢速度", "這期才剛開始，還看不出燒錢速度。")
    spend_yellow_ratio = rule_cards.get_value(conn, brand_id, "health_lights", "spend_yellow_ratio")
    if result["status"] == "normal" and abs(deviation) <= threshold * spend_yellow_ratio:
        return _light("green", deviation, "燒錢速度", "花費進度跟時間進度差不多，一切正常。")
    if result["status"] == "normal":
        return _light("yellow", deviation, "燒錢速度", "花費進度跟時間進度有點落差，先留意。")
    note = "本期預算恐提前燒完。" if result["status"] == "overspend" else "本期預算恐怕花不完。"
    return _light("red", deviation, "燒錢速度", note)


def _cpa_light(conn, brand_id: str, cycle: dict) -> dict:
    kpis = ads_performance.compute_kpis(ads_performance.totals(conn, brand_id, cycle["id"]))
    actual_cpa = kpis.get("cpa")
    product_ids = [a["product_id"] for a in ads_repo.list_cycle_products(conn, brand_id, cycle["id"])]
    target = ads_target_cpa.resolve_target_cpa(conn, brand_id, cycle["objective"], product_ids)
    target_cpa = target["value"] if target else None
    if actual_cpa is None or not target_cpa:
        return _light("insufficient", actual_cpa, "CPA", "算不出目標 CPA 或實際 CPA，先看其他指標。")
    if actual_cpa <= target_cpa:
        return _light("green", actual_cpa, "CPA", f"實際 CPA {actual_cpa:,.0f}，在目標 {target_cpa:,.0f} 之內。")
    cpa_yellow_multiplier = rule_cards.get_value(conn, brand_id, "health_lights", "cpa_yellow_multiplier")
    if actual_cpa <= target_cpa * cpa_yellow_multiplier:
        return _light("yellow", actual_cpa, "CPA", f"實際 CPA {actual_cpa:,.0f}，略高於目標 {target_cpa:,.0f}。")
    return _light("red", actual_cpa, "CPA", f"實際 CPA {actual_cpa:,.0f}，明顯高於目標 {target_cpa:,.0f}。")


def _roas_light(conn, brand_id: str, cycle: dict) -> dict:
    kpis = ads_performance.compute_kpis(ads_performance.totals(conn, brand_id, cycle["id"]))
    actual_roas = kpis.get("roas")
    breakeven = _cycle_breakeven(conn, brand_id, cycle["id"])
    if actual_roas is None or not breakeven:
        return _light("insufficient", actual_roas, "ROAS", "算不出打平投報率或實際 ROAS，先看其他指標。")
    if actual_roas >= breakeven:
        return _light("green", actual_roas, "ROAS", f"實際 ROAS {actual_roas:.2f}，達到打平線 {breakeven:.2f}。")
    roas_yellow_multiplier = rule_cards.get_value(conn, brand_id, "health_lights", "roas_yellow_multiplier")
    if actual_roas >= breakeven * roas_yellow_multiplier:
        return _light("yellow", actual_roas, "ROAS", f"實際 ROAS {actual_roas:.2f}，接近打平線 {breakeven:.2f}。")
    return _light("red", actual_roas, "ROAS", f"實際 ROAS {actual_roas:.2f}，低於打平線 {breakeven:.2f}。")


_FATIGUE_STATUS_LIGHT = {"safe": "green", "warning": "yellow", "danger": "red"}


def _fatigue_light(conn, brand_id: str, cycle: dict) -> dict:
    frequency = ads_performance.max_frequency(conn, brand_id, cycle["id"])
    if frequency is None:
        return _light("insufficient", None, "疲勞", "還沒有成效資料，算不出頻率。")
    status = rule_cards.classify_ad_frequency(conn, brand_id, "cold", frequency)
    return _light(_FATIGUE_STATUS_LIGHT[status], frequency, "疲勞", rule_cards.FATIGUE_STATUS_LABELS[status])


def compute(conn, brand_id: str, cycle_id: str) -> dict:
    """四盞燈：`{spend_rate, cpa, roas, fatigue}`，每盞 `{status, value, label, note}`。"""
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    if cycle is None:
        raise ValueError("找不到廣告檔期")
    return {
        "spend_rate": _spend_rate_light(conn, brand_id, cycle),
        "cpa": _cpa_light(conn, brand_id, cycle),
        "roas": _roas_light(conn, brand_id, cycle),
        "fatigue": _fatigue_light(conn, brand_id, cycle),
    }


# ---------------------------------------------------------------------------
# 調度台『監測』模組門面（票 O1-02，ADR 0024）
# ---------------------------------------------------------------------------

def _current_cycle(conn, brand_id: str) -> Optional[dict]:
    """比照 app/ads/diagnosis.py:29 _current_cycle()：取最新一個投放中或等判讀的檔期。"""
    for cycle in ads_repo.list_cycles(conn, brand_id):
        if cycle["status"] in ("LIVE", "EVALUATING"):
            return cycle
    return None


def status(conn, brand_id: str) -> dict:
    """調度台 facts：`monitor.cycle_id`、`monitor.spend_rate_light`（燒錢速度燈號 status，
    見 compute()）、`monitor.red_lights`（四盞裡幾盞是紅燈）。"""
    cycle = _current_cycle(conn, brand_id)
    if cycle is None:
        return {"monitor.cycle_id": None, "monitor.spend_rate_light": None,
                "monitor.red_lights": 0}
    lights = compute(conn, brand_id, cycle["id"])
    return {
        "monitor.cycle_id": cycle["id"],
        "monitor.spend_rate_light": lights["spend_rate"]["status"],
        "monitor.red_lights": sum(1 for light in lights.values() if light["status"] == "red"),
    }


def handle(conn, action: dict) -> dict:
    """調度台唯一支援的 op：check_pacing（叫既有 pacing.check_cycle() 判定一次，不重寫
    第二套步調判定）。不認得的 op 一律丟 ValueError（ADR 0024 決議 6）。"""
    if action["op"] != "check_pacing":
        raise ValueError(f"監測模組不認得這個 op：{action['op']}")
    interrupt_id = ads_pacing.check_cycle(conn, action["brand_id"], action["params"]["cycle_id"])
    return {"interrupt_id": interrupt_id}


core_orchestrator.register_module("monitor", status=status, handle=handle)
