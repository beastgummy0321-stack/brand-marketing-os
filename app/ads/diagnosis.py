# -*- coding: utf-8 -*-
"""app/ads/diagnosis.py — 調度台『診斷』模組門面（票 O1-01，ADR 0024）。

`app/ads/reading.py` 已經 797 行頂到 CLAUDE.md 800 行上限（唯讀，不得再加），另開新檔
而不是塞進去（票 03-orchestrator-core.md 明文交代）。`status()`／`handle()` 是本模組
對調度台的唯一公開面，實作直接沿用既有讀取路徑（跟
`app/ads/routes_campaigns_performance_api.py:57-96` 同一套算法，只留調度台 facts 需要
的兩件事，不重寫第二套）：沒有判讀就沒有『這期賺不賺』的結論，瓶頸判讀依附在判讀
結論底下才有意義，所以只在 `reading_ready` 時才算瓶頸。

自己在檔尾呼叫 `orchestrator.register_module()`／`register_rule()` 把自己掛進調度台
（比照 `app/core/cleanup.py` 的登記制）——調度台本身不 import 這個檔案。
"""

from typing import Optional

from app.ads import bottleneck as ads_bottleneck
from app.ads import performance as ads_performance
from app.ads import reading as ads_reading
from app.ads import repository as ads_repo
from app.core import orchestrator as core_orchestrator

# 調度台呼叫 handle() 時模組自己認的執行者身分（DDL 沒有 actor 欄，稽核走各自模組內部
# 既有的 write_audit，這裡只是給 reading.run() 的 actor 參數用）。
_HANDLE_ACTOR = "orchestrator"


def _current_cycle(conn, brand_id: str) -> "Optional[dict]":
    """比照 app/ads/weekly_proposals.py current_cycle()：取最新一個投放中或等判讀的檔期。"""
    for cycle in ads_repo.list_cycles(conn, brand_id):
        if cycle["status"] in ("LIVE", "EVALUATING"):
            return cycle
    return None


def status(conn, brand_id: str) -> dict:
    """調度台 facts：`data.synced`（這期有沒有同步進來的成效資料）、
    `diagnosis.cycle_id`（給 handle() 知道要判讀哪個檔期）、
    `diagnosis.reading_ready`（本期判讀跑過沒）、
    `diagnosis.bottleneck_primary`（bottleneck.diagnose() 的 primary，沒有回 None）。"""
    cycle = _current_cycle(conn, brand_id)
    if cycle is None:
        return {
            "data.synced": False, "diagnosis.cycle_id": None,
            "diagnosis.reading_ready": False, "diagnosis.bottleneck_primary": None,
        }

    totals = ads_performance.totals(conn, brand_id, cycle["id"])
    loaded = ads_reading.load(conn, brand_id, cycle["id"])
    reading_ready = bool(loaded["cycle"])

    bottleneck_primary = None
    if reading_ready:
        baseline = ads_reading.brand_baseline(conn, brand_id, exclude_cycle_id=cycle["id"])
        bottleneck_primary = ads_bottleneck.diagnose(
            totals, baseline=baseline, brand_id=brand_id, conn=conn)["primary"]

    return {
        # ponytail：用「這期有沒有成效資料列」當同步已發生的證據，不另外追蹤一份「上次
        # 同步時間」——需要「同步了但資料是舊的」這種區分時再升級成讀
        # ads_performance.list_snapshots() 的 snapshot_taken_at。
        "data.synced": totals["rows"] > 0,
        "diagnosis.cycle_id": cycle["id"],
        "diagnosis.reading_ready": reading_ready,
        "diagnosis.bottleneck_primary": bottleneck_primary,
    }


def handle(conn, action: dict) -> dict:
    """調度台唯一支援的 op：run_reading。不認得的 op 一律丟 ValueError（ADR 0024 決議 6）。"""
    if action["op"] != "run_reading":
        raise ValueError(f"診斷模組不認得這個 op：{action['op']}")
    ok, err = ads_reading.run(conn, action["brand_id"], action["params"]["cycle_id"],
                              _HANDLE_ACTOR)
    if not ok:
        raise ValueError(err or "判讀執行失敗")
    return {"ok": ok}


def _rule_run_reading_when_synced_unread(facts: dict) -> "Optional[dict]":
    """規則 1（票 03-orchestrator-core.md）：data.synced 成立且本期還沒判讀 →
    診斷.run_reading，risk 無（一律自動做）。"""
    if not facts.get("data.synced"):
        return None
    if facts.get("diagnosis.reading_ready"):
        return None
    cycle_id = facts.get("diagnosis.cycle_id")
    if not cycle_id:
        return None
    return {
        "module": "diagnosis", "op": "run_reading", "brand_id": facts.get("brand_id"),
        "params": {"cycle_id": cycle_id}, "risk": None,
        "dedupe_key": f"run_reading:{cycle_id}",
    }


core_orchestrator.register_module("diagnosis", status=status, handle=handle)
core_orchestrator.register_rule(
    "run_reading_when_synced_unread", _rule_run_reading_when_synced_unread)
