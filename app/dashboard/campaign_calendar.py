# -*- coding: utf-8 -*-
"""app/dashboard/campaign_calendar.py — 檔期日曆第一層（票 06-campaign-calendar，規格 0001）。

純函數：資料進、結論出，不碰資料庫、不呼叫 LLM（沿用判讀狀態機模式，同
app/dashboard/health.py／guide_cards.py）。零 API 成本——AI 聯網（ADR 0005）
屬階段 3，不在本票範圍。

檔期資料為系統內建資料檔（同目錄 campaign_calendar_data.json），節日＋電商大檔，
含等級：大／中／小（可人工增修，直接編輯該 JSON 檔即可，欄位為
{id, name, date(YYYY-MM-DD), tier(large/medium/small)}）。

提前期分級（blueprint 第五節）：大檔 90 天、中檔 45 天、小檔 30 天開始提醒備戰；
素材一律提前 14 天完稿提醒，與等級無關。備戰倒數分遠期備戰→中期備戰→近期備戰
三段，本檔把提前期窗口等分三段推導（規格未進一步訂細節，取等分為最簡單的合理
切法）。「預熱／高潮／衝刺」留給檔期開跑後的排期曲線三階段用，兩者不同義。
"""

import json
from datetime import date
from pathlib import Path
from typing import Optional

LEAD_DAYS = {"large": 90, "medium": 45, "small": 30}
TIER_LABELS = {"large": "大檔", "medium": "中檔", "small": "小檔"}
CREATIVE_LEAD_DAYS = 14
STAGE_LABELS = ("遠期備戰", "中期備戰", "近期備戰")

_DATA_PATH = Path(__file__).parent / "campaign_calendar_data.json"


def load_events(path: Optional[str] = None) -> list:
    """讀檔期資料檔（預設同目錄 campaign_calendar_data.json，可人工增修）。"""
    with open(path or _DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def _days_until(today: date, event_date: date) -> int:
    return (event_date - today).days


def weeks_until(today: date, event_date: date) -> int:
    """距離檔期還有幾週（無條件進位——「還有 4 週」寧可多提醒一天，不少提醒）。"""
    days = max(_days_until(today, event_date), 0)
    return -(-days // 7)


def in_prep_window(today: date, event_date: date, tier: str) -> bool:
    days = _days_until(today, event_date)
    return 0 <= days <= LEAD_DAYS[tier]


def in_creative_window(today: date, event_date: date) -> bool:
    days = _days_until(today, event_date)
    return 0 <= days <= CREATIVE_LEAD_DAYS


def campaign_stage(today: date, event_date: date, tier: str) -> Optional[str]:
    """檔期目前落在三階段的哪一段；不在提前期窗口內（含已過期）回 None。

    提前期窗口等分三段：離窗口開啟越近＝遠期備戰，越接近檔期當天＝近期備戰。
    """
    lead = LEAD_DAYS[tier]
    days = _days_until(today, event_date)
    if not (0 <= days <= lead):
        return None
    elapsed = lead - days
    third = lead / 3
    if elapsed < third:
        return STAGE_LABELS[0]
    if elapsed < 2 * third:
        return STAGE_LABELS[1]
    return STAGE_LABELS[2]


def prep_reminder(today: date, event: dict) -> Optional[dict]:
    """單一檔期的備戰提前期提醒：在提前期窗口內回傳提醒資料，否則 None。"""
    event_date = date.fromisoformat(event["date"])
    tier = event["tier"]
    if not in_prep_window(today, event_date, tier):
        return None
    return {
        "id": event["id"], "name": event["name"], "tier": tier,
        "tier_label": TIER_LABELS[tier],
        "days_until": _days_until(today, event_date),
        "weeks_until": weeks_until(today, event_date),
        "kind": "prep",
    }


def creative_reminder(today: date, event: dict) -> Optional[dict]:
    """單一檔期的素材完稿提醒：一律提前 14 天，與等級無關。"""
    event_date = date.fromisoformat(event["date"])
    if not in_creative_window(today, event_date):
        return None
    return {
        "id": event["id"], "name": event["name"],
        "days_until": _days_until(today, event_date),
        "kind": "creative",
    }


def next_calendar_reminder(events: list, today: date) -> Optional[dict]:
    """全部檔期一起掃：同一檔期若備戰期與素材期限同時成立，素材期限更急迫、優先回傳；
    多檔期同時觸發時取天數最接近（days_until 最小）的一筆——最急迫的先講。沒有任何
    檔期觸發回 None（呼叫端＝guide_cards 規則，不觸發就不出卡）。"""
    reminders = []
    for event in events:
        card = creative_reminder(today, event) or prep_reminder(today, event)
        if card:
            reminders.append(card)
    if not reminders:
        return None
    return min(reminders, key=lambda c: c["days_until"])


def current_campaign_stage(events: list, today: date) -> Optional[dict]:
    """駕駛艙用：目前正處於三階段之一的檔期（同一時間可能有多檔重疊，取天數最接近的
    一檔優先顯示，同 next_calendar_reminder 的排序邏輯）。沒有任何檔期在窗口內回 None。"""
    candidates = []
    for event in events:
        event_date = date.fromisoformat(event["date"])
        stage = campaign_stage(today, event_date, event["tier"])
        if stage:
            candidates.append({
                "id": event["id"], "name": event["name"], "tier": event["tier"],
                "tier_label": TIER_LABELS[event["tier"]],
                "stage": stage, "days_until": _days_until(today, event_date),
            })
    if not candidates:
        return None
    return min(candidates, key=lambda c: c["days_until"])


def demo() -> None:
    """python -m app.dashboard.campaign_calendar —— 純函數的最小自檢（無需資料庫）。"""
    event = {"id": "evt_1", "name": "雙11購物節", "date": "2026-11-11", "tier": "large"}
    assert prep_reminder(date(2026, 8, 13), event) is not None  # 90 天前，剛好開窗
    assert prep_reminder(date(2026, 8, 12), event) is None  # 91 天前，還沒到
    assert creative_reminder(date(2026, 10, 28), event) is not None  # 14 天前
    assert creative_reminder(date(2026, 10, 27), event) is None  # 15 天前
    assert campaign_stage(date(2026, 8, 13), date(2026, 11, 11), "large") == "遠期備戰"
    assert campaign_stage(date(2026, 11, 5), date(2026, 11, 11), "large") == "近期備戰"
    assert campaign_stage(date(2026, 11, 12), date(2026, 11, 11), "large") is None
    events = load_events()
    assert len(events) > 0
    print("dashboard.campaign_calendar 自檢通過")


if __name__ == "__main__":
    demo()
