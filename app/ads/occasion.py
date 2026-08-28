"""app/ads/occasion.py — 檔期情境自動標籤（票 01-occasion-auto-tagging，ADR 0011 第四節）。

純函數：資料進、結論出，不碰資料庫、不呼叫 LLM（同 app/dashboard/campaign_calendar.py
的風格）。判斷檔期時間窗口 [start, end] 是否落在既有節日日曆某個節日的投放窗口內，
落在就回節日名稱，否則回 None（畫面顯示「常態檔期」）。

**刻意不 import app.dashboard.campaign_calendar**：app/dashboard/repository.py 已經
import app.ads（跨分支彙總讀檔期狀態，見 test_architecture_boundaries.py 的
LAYER_ORDER：app.dashboard 排在 app.ads 之後，只准依賴排在自己前面的層）。反過來讓
app.ads import app.dashboard 會形成雙向依賴，違反 code-rules.md「新增一條會形成環的
依賴 → 停下回報，不得自行改依賴方向」。改直接讀同一份 campaign_calendar_data.json——
這是 ADR 0011 第四節指名重用的「資料」本體，不是重用 dashboard 那層的程式碼或狀態。

投放窗口＝節日當天往前推 LEAD_DAYS 天（數字沿用 app/dashboard/campaign_calendar.py
同名常數——大檔 90／中檔 45／小檔 30，同一份節日資料，用同一套提前期分級當「這個節日
這次算不算搭上」的窗口寬度，避免另外發明一套數字）。因為上述層級理由改為獨立宣告，
不是 import 過來的同一個物件。
"""

import json
from datetime import date, timedelta
from pathlib import Path

LEAD_DAYS = {"large": 90, "medium": 45, "small": 30}

_CALENDAR_DATA_PATH = (
    Path(__file__).resolve().parent.parent / "dashboard" / "campaign_calendar_data.json"
)


def load_events(path: str | None = None) -> list:
    """讀節日日曆資料（預設 app/dashboard/campaign_calendar_data.json，兩層共用同一份）。"""
    with open(path or _CALENDAR_DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def _overlaps(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    return a_start <= b_end and b_start <= a_end


def match_occasion(events: list, start: date, end: date) -> str | None:
    """檔期 [start, end] 落在哪個節日的投放窗口內；沒對到任何節日回 None（常態檔期）。

    多個節日窗口同時重疊時，取節日當天離檔期起始日最近的一筆——跟
    campaign_calendar.py `next_calendar_reminder`／`current_campaign_stage` 同一套
    「最接近者優先」慣例。
    """
    candidates = []
    for event in events:
        event_date = date.fromisoformat(event["date"])
        window_start = event_date - timedelta(days=LEAD_DAYS[event["tier"]])
        if _overlaps(start, end, window_start, event_date):
            candidates.append((abs((event_date - start).days), event["name"]))
    if not candidates:
        return None
    return min(candidates, key=lambda c: c[0])[1]


def for_cycle(start: date, end: date) -> str | None:
    """create_cycle() 的呼叫入口：讀既有節日日曆資料檔，回傳這期該標的節日名稱或 None。"""
    return match_occasion(load_events(), start, end)


def demo() -> None:
    """python -m app.ads.occasion —— 純函數最小自檢（無需資料庫）。"""
    events = [{"id": "mothers_day_2026", "name": "母親節", "date": "2026-05-10", "tier": "large"}]
    # 落在窗口內：檔期涵蓋節日當天
    assert match_occasion(events, date(2026, 5, 1), date(2026, 5, 14)) == "母親節"
    # 檔期在窗口開啟前就結束：沒對到
    assert match_occasion(events, date(2026, 1, 1), date(2026, 1, 14)) is None
    # 檔期在節日之後才開始：沒對到（投放窗口不含節日後）
    assert match_occasion(events, date(2026, 5, 11), date(2026, 5, 20)) is None
    real_events = load_events()
    assert len(real_events) > 0
    print("ads.occasion 自檢通過")


if __name__ == "__main__":
    demo()
