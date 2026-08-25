# -*- coding: utf-8 -*-
"""app/ads/pacing.py — 檔期預算步調警示（票 08-pacing-alert，規格 0001）。

classify() 是純函數：比較「預算消耗進度 vs 檔期時間進度」，偏差超過規則卡門檻就判定
燒太快（預算會提前燒完）或花不完（明顯花不完）。檔期開跑不到 MIN_SAMPLE_DAYS 天不判定
（比照 app/ads/onboarding.py day3 期中檢查點「太早看沒意義」），避免第一天花費波動就誤報。

check_cycle() 是唯一的資料庫進出口：讀檔期與本期成效加總（app.ads.repository／
app.ads.performance 既有公開查詢函式）、讀規則卡門檻（app.core.rule_cards），
判定後送打斷佇列（app.core.interrupts）。去重鍵含檔期 id 與判定狀態——同一檔期同一狀況
不重複轟炸，但狀態翻轉（例如燒太快轉花不完）會被視為新狀況、再送一次。

只對 phase='normal' 且未 CLOSED 的檔期判定：紙上模擬（決策 0022 第 14 點）不是真錢，
已結案的檔期判不判都沒有意義。

呼叫時機：CSV／手動輸入成效資料落地後（app/ads/routes_performance.py）。有 07-auto-sync
的每日自動同步會更即時，但不硬性依賴——手動同步的數據一樣能判定（票 08 說明）。
"""

from datetime import date
from typing import Optional

from app.ads import performance as ads_performance
from app.ads import repository as ads_repo
from app.core import interrupts as core_interrupts
from app.core import rule_cards

MIN_SAMPLE_DAYS = 3  # 檔期開跑不到 3 天，樣本太少，不判定（比照 day3 期中檢查點）

_MESSAGES = {
    "overspend": "本期預算恐提前燒完，去看看",
    "underspend": "本期預算恐怕花不完，去看看",
}
_CATEGORY_BY_STATUS = {"overspend": "pacing_overspend", "underspend": "pacing_underspend"}


def classify(*, budget: Optional[float], spend: float, start_date, end_date,
            today: str, threshold_pct: float) -> dict:
    """比較預算消耗進度與檔期時間進度，回傳 {"status", "time_progress", "budget_progress",
    "deviation"}。status 四選一：

    - 'overspend'：花費進度領先時間進度超過門檻，預算可能提前燒完
    - 'underspend'：花費進度落後時間進度超過門檻，預算可能花不完
    - 'normal'：偏差在門檻內
    - 'insufficient_sample'：檔期剛開始（不到 MIN_SAMPLE_DAYS 天）或沒有可比的預算，
      不判定（鐵則 16：算不出來就誠實說算不出來，不硬猜）
    """
    if not budget or budget <= 0:
        return {"status": "insufficient_sample", "time_progress": None,
                "budget_progress": None, "deviation": None}

    start = start_date if isinstance(start_date, date) else date.fromisoformat(start_date)
    end = end_date if isinstance(end_date, date) else date.fromisoformat(end_date)
    total_days = max((end - start).days + 1, 1)
    elapsed_days = (date.fromisoformat(today) - start).days + 1
    elapsed_days = max(0, min(elapsed_days, total_days))

    time_progress = elapsed_days / total_days
    budget_progress = spend / budget

    if elapsed_days < MIN_SAMPLE_DAYS:
        return {"status": "insufficient_sample", "time_progress": round(time_progress, 4),
                "budget_progress": round(budget_progress, 4), "deviation": None}

    # 用四捨五入到小數第 6 位再比較門檻：0.65-0.5 這種看似整齊的比例，浮點運算實際上
    # 會落在 0.15000000000000002，剛好卡在門檻上時會被誤判成「超過」（鐵則驗證紀律：
    # 邊界案例要精準，不能被浮點雜訊帶偏）。
    deviation = round(budget_progress - time_progress, 6)
    if deviation > threshold_pct:
        status = "overspend"
    elif deviation < -threshold_pct:
        status = "underspend"
    else:
        status = "normal"

    return {"status": status, "time_progress": round(time_progress, 4),
            "budget_progress": round(budget_progress, 4), "deviation": round(deviation, 4)}


def check_cycle(conn, brand_id: str, cycle_id: str, today: Optional[str] = None) -> Optional[str]:
    """判定一期檔期的 pacing 狀態；overspend／underspend 就送打斷佇列。

    回傳這次是否真的新排了一筆（interrupt id），沒觸發、被去重鍵擋下、或這期不適用判定
    （查無此期／已結案／紙上模擬）都回 None。"""
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    if not cycle or cycle["status"] == "CLOSED" or cycle.get("phase") == "simulation":
        return None

    today = today or date.today().isoformat()
    spend = ads_performance.totals(conn, brand_id, cycle_id)["spend"]
    threshold = rule_cards.get_value(conn, brand_id, "pacing", "deviation_threshold_ratio")
    result = classify(budget=cycle["budget"], spend=spend, start_date=cycle["start_date"],
                      end_date=cycle["end_date"], today=today, threshold_pct=threshold)

    if result["status"] not in _CATEGORY_BY_STATUS:
        return None

    interrupt_id = core_interrupts.enqueue(
        conn, category=_CATEGORY_BY_STATUS[result["status"]], brand_id=brand_id,
        campaign_cycle_id=cycle_id, dedupe_key=f"pacing:{cycle_id}:{result['status']}",
        message=_MESSAGES[result["status"]],
        action_url=f"/app/brands/{brand_id}/campaigns/{cycle_id}",
    )
    if interrupt_id:
        conn.commit()
    return interrupt_id


def demo() -> None:
    """python -m app.ads.pacing —— 純函數的最小自檢（無需資料庫）。"""
    normal = classify(budget=10000, spend=5200, start_date="2026-01-01", end_date="2026-04-10",
                      today="2026-02-19", threshold_pct=0.15)
    assert normal["status"] == "normal"
    over = classify(budget=10000, spend=8000, start_date="2026-01-01", end_date="2026-04-10",
                    today="2026-02-19", threshold_pct=0.15)
    assert over["status"] == "overspend"
    under = classify(budget=10000, spend=2000, start_date="2026-01-01", end_date="2026-04-10",
                     today="2026-02-19", threshold_pct=0.15)
    assert under["status"] == "underspend"
    early = classify(budget=10000, spend=5000, start_date="2026-01-01", end_date="2026-04-10",
                     today="2026-01-02", threshold_pct=0.15)
    assert early["status"] == "insufficient_sample"
    for msg in _MESSAGES.values():
        assert len(msg) <= 30
    print("ads.pacing 自檢通過")


if __name__ == "__main__":
    demo()
