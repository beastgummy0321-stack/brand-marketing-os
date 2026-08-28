"""app/dashboard/campaign_calendar.py — 檔期日曆第一層（票 06-campaign-calendar，規格 0001）。

純函數：資料進、結論出，不碰資料庫、不呼叫 LLM（沿用判讀狀態機模式，同
app/dashboard/health.py／guide_cards.py）。零 API 成本——AI 聯網（ADR 0005）
屬階段 3，不在本票範圍。

檔期資料為系統內建資料檔（同目錄 campaign_calendar_data.json），節日＋電商大檔，
含等級：大／中／小（可人工增修，直接編輯該 JSON 檔即可，欄位為
{id, name, date(YYYY-MM-DD), tier(large/medium/small), applicable_industries}）。

業種相關性比對（ADR 0014 第一節）：applicable_industries 是業種清單（值域見
app/brand_intelligence/repository.py INDUSTRIES）或字串 "all"（對所有業種都相關，
例如雙11／618 這類全民購物節）。品牌業種不在清單內、且事件沒標 "all"，就不算相關、
不觸發提醒——見 industry_relevant()。

提前期分級（blueprint 第五節）：大檔 90 天、中檔 45 天、小檔 30 天開始提醒備戰；
素材一律提前 14 天完稿提醒，與等級無關。備戰倒數分遠期備戰→中期備戰→近期備戰
三段，本檔把提前期窗口等分三段推導（規格未進一步訂細節，取等分為最簡單的合理
切法）。「預熱／高潮／衝刺」留給檔期開跑後的排期曲線三階段用，兩者不同義。
"""

import json
import re
from datetime import date
from pathlib import Path

LEAD_DAYS = {"large": 90, "medium": 45, "small": 30}
TIER_LABELS = {"large": "大檔", "medium": "中檔", "small": "小檔"}
CREATIVE_LEAD_DAYS = 14
STAGE_LABELS = ("遠期備戰", "中期備戰", "近期備戰")
INDUSTRY_ALL = "all"

_DATA_PATH = Path(__file__).parent / "campaign_calendar_data.json"
_YEAR_SUFFIX_RE = re.compile(r"_\d{4}$")


def load_events(path: str | None = None) -> list:
    """讀檔期資料檔（預設同目錄 campaign_calendar_data.json，可人工增修）。"""
    with open(path or _DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def holiday_id(event_id: str) -> str:
    """節日跨年份的穩定識別碼（票 03-cycle-skip-record）：本檔事件 id 逐年帶年份尾碼
    （同一節日逐年 id 不同，如 cny_2026／cny_2027），去掉尾碼年份才能拿來做「去年是否
    跳過」這種跨年比對——app/core/campaign_skip.py 的跳過紀錄按這個穩定碼存，
    不是按逐年 id。沒有年份尾碼的 id（測試用合成 id）原樣傳回。"""
    return _YEAR_SUFFIX_RE.sub("", event_id)


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


def campaign_stage(today: date, event_date: date, tier: str) -> str | None:
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


def prep_reminder(today: date, event: dict) -> dict | None:
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


def industry_relevant(event: dict, brand_industry: str | None) -> bool:
    """業種相關性比對（ADR 0014 第一節）：event 標 "all"，或 brand_industry 落在
    event["applicable_industries"] 清單內，才算相關。event 沒有 applicable_industries
    欄位（舊資料／測試手刻的 dict，如 demo() 與 test_campaign_calendar.py 的 _event()）
    一律視為 "all"，維持相容。"""
    industries = event.get("applicable_industries", INDUSTRY_ALL)
    if industries == INDUSTRY_ALL:
        return True
    return brand_industry in industries


def creative_reminder(today: date, event: dict) -> dict | None:
    """單一檔期的素材完稿提醒：一律提前 14 天，與等級無關。"""
    event_date = date.fromisoformat(event["date"])
    if not in_creative_window(today, event_date):
        return None
    return {
        "id": event["id"], "name": event["name"],
        "days_until": _days_until(today, event_date),
        "kind": "creative",
    }


def _not_dismissed(event: dict, dismissed_categories) -> bool:
    """票 02-permanent-dismiss-category（ADR 0014 第二節）：品牌永久關閉某節日類別後，
    即使業種比對判相關也不再提醒。dismissed_categories 為 holiday_id() 字串集合，
    None／空集合＝沒有任何類別被關閉，全部放行。"""
    if not dismissed_categories:
        return True
    return holiday_id(event["id"]) not in dismissed_categories


def next_calendar_reminder(events: list, today: date, brand_industry: str | None = None,
                            dismissed_categories: set | None = None) -> dict | None:
    """全部檔期一起掃：同一檔期若備戰期與素材期限同時成立，素材期限更急迫、優先回傳；
    多檔期同時觸發時取天數最接近（days_until 最小）的一筆——最急迫的先講。與品牌業種
    不相關的檔期（ADR 0014 第一節）、品牌永久關閉的節日類別（ADR 0014 第二節）先濾掉，
    沒有任何檔期觸發回 None（呼叫端＝guide_cards 規則，不觸發就不出卡）。"""
    reminders = []
    for event in events:
        if not industry_relevant(event, brand_industry):
            continue
        if not _not_dismissed(event, dismissed_categories):
            continue
        card = creative_reminder(today, event) or prep_reminder(today, event)
        if card:
            reminders.append(card)
    if not reminders:
        return None
    return min(reminders, key=lambda c: c["days_until"])


def current_campaign_stage(events: list, today: date, brand_industry: str | None = None,
                            dismissed_categories: set | None = None) -> dict | None:
    """駕駛艙用：目前正處於三階段之一的檔期（同一時間可能有多檔重疊，取天數最接近的
    一檔優先顯示，同 next_calendar_reminder 的排序邏輯）。與品牌業種不相關的檔期
    （ADR 0014 第一節）、品牌永久關閉的節日類別（ADR 0014 第二節）先濾掉，沒有任何
    檔期在窗口內回 None。"""
    candidates = []
    for event in events:
        if not industry_relevant(event, brand_industry):
            continue
        if not _not_dismissed(event, dismissed_categories):
            continue
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
    assert all("applicable_industries" in e for e in events)
    # ADR 0014 第一節：業種相關性比對。
    all_event = {**event, "applicable_industries": "all"}
    niche_event = {**event, "applicable_industries": ["beauty_personal_care"]}
    assert industry_relevant(all_event, None) is True  # 標 all，不管業種都相關
    assert industry_relevant(niche_event, "beauty_personal_care") is True  # 業種對到
    assert industry_relevant(niche_event, "food_beverage") is False  # 業種對不到
    assert next_calendar_reminder([niche_event], date(2026, 8, 13), "food_beverage") is None
    assert next_calendar_reminder([niche_event], date(2026, 8, 13),
                                  "beauty_personal_care") is not None
    # 票 03-cycle-skip-record：holiday_id() 去掉逐年 id 的年份尾碼，拿到跨年穩定識別碼。
    assert holiday_id("cny_2026") == "cny"
    assert holiday_id("cny_2027") == "cny"
    assert holiday_id("double11_2026") == "double11"
    assert holiday_id("evt_1") == "evt_1"  # 沒有年份尾碼原樣傳回
    # 票 02-permanent-dismiss-category（ADR 0014 第二節）：永久關閉的類別即使業種對到
    # 也不再提醒；重新開啟（不在集合內）恢復提醒。event["id"] == "evt_1" -> holiday_id
    # 也是 "evt_1"（沒有年份尾碼），用它當「已關閉」那個類別鍵。
    matching_event = {**event, "applicable_industries": "all"}
    assert next_calendar_reminder([matching_event], date(2026, 8, 13),
                                  dismissed_categories={"evt_1"}) is None
    assert next_calendar_reminder([matching_event], date(2026, 8, 13),
                                  dismissed_categories=set()) is not None
    assert current_campaign_stage([matching_event], date(2026, 8, 13),
                                  dismissed_categories={"evt_1"}) is None
    assert current_campaign_stage([matching_event], date(2026, 8, 13),
                                  dismissed_categories={"valentine"}) is not None
    print("dashboard.campaign_calendar 自檢通過")


if __name__ == "__main__":
    demo()
