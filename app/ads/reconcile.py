# -*- coding: utf-8 -*-
"""app/ads/reconcile.py — 把對帳護欄接上真實資料（票 11）。

判斷邏輯全部在 app/ads/guardrails.py（票 3 的純函數），這一層只做三件事：
組出 plan 與 actuals、呼叫純函數、把結果存成 Finding 並算出本期判讀可信度。

## 只比總花費，不比每日預算

Meta API 回傳的預算金額帶「幣別最小單位」的換算（多數幣別要除以 100），而各幣別的
換算基數不一致。比錯一個零就會每期都跳紅字——ADHD 設計輸入點名的「狼來了」風險
就是這樣來的。所以自動比對只拿**成效裡的實際花費**（那個數字沒有換算問題）跟計畫比；
每日預算與排程是否被改過，交給使用者自答那三題（人看得懂自己的 Meta 畫面，程式看不懂）。

寧可少比一項，也不要製造假警報讓人從此無視所有黃標。
"""

from typing import Optional

from app.ads import guardrails
from app.ads import performance as ads_performance
from app.ads import repository as ads_repo

RECONCILE_TYPES = ("reconciliation", "external_change")

CONFIDENCE_LABELS = [
    (0.9, "可信", "這期的數字跟計畫對得上，判讀可以照著看。"),
    (0.6, "可信度打折", "有些地方跟計畫不太一樣，判讀當參考就好。"),
    (0.0, "僅供參考", "這期的實際狀況跟計畫差很多，結論不建議直接拿來做決定。"),
]


def build_plan(cycle: dict) -> dict:
    derived = ads_repo.derived_plan(cycle)
    return {
        "total_budget": cycle.get("budget"),
        "daily_budget": derived.get("daily_budget"),
        "start_date": cycle.get("start_date"),
        "end_date": cycle.get("end_date"),
    }


def build_actuals(conn, brand_id: str, cycle_id: str) -> dict:
    """實際值只取「已入庫、未被隔離」的成效加總——隔離區的壞資料不參與對帳。"""
    summary = ads_performance.totals(conn, brand_id, cycle_id)
    return {"spend": summary["spend"] if summary["rows"] else None}


def run(conn, brand_id: str, cycle_id: str, *, self_answers: Optional[dict] = None) -> dict:
    """跑一次對帳，回傳 {findings, confidence, label, note}。結果同時存進 finding 表。"""
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    if cycle is None:
        raise ValueError("找不到廣告檔期")

    findings = guardrails.reconcile(build_plan(cycle), build_actuals(conn, brand_id, cycle_id))
    if self_answers:
        findings += guardrails.self_answer_findings(self_answers)

    # 兩類 Finding 一起整批換掉：重跑對帳就是重算，不留上一次的殘留結論
    for finding_type in RECONCILE_TYPES:
        ads_repo.replace_findings(
            conn, brand_id, cycle_id, finding_type,
            [f for f in findings if f.finding_type == finding_type])

    confidence = guardrails.confidence_from_findings(findings)
    label, note = describe_confidence(confidence)
    return {"findings": findings, "confidence": confidence, "label": label, "note": note}


def describe_confidence(confidence: float) -> tuple:
    for threshold, label, note in CONFIDENCE_LABELS:
        if confidence >= threshold:
            return label, note
    return CONFIDENCE_LABELS[-1][1], CONFIDENCE_LABELS[-1][2]


def load(conn, brand_id: str, cycle_id: str) -> dict:
    """讀回已存的對帳結果（頁面每次進來不必重算）。"""
    rows = [r for r in ads_repo.list_findings(conn, brand_id, cycle_id)
            if r["finding_type"] in RECONCILE_TYPES]
    penalty = sum(r["confidence_penalty"] or 0 for r in rows)
    confidence = round(max(0.0, min(1.0, 1.0 - penalty)), 2)
    label, note = describe_confidence(confidence)
    return {"rows": rows, "confidence": confidence, "label": label, "note": note}
