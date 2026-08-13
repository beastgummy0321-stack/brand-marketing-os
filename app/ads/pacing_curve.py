# -*- coding: utf-8 -*-
"""app/ads/pacing_curve.py — 排期策略推薦與逐日預算換算（票 pacing-curve）。

純函數：不呼叫 AI、不碰資料庫，跟 app/ads/budget.py 同層次。跟 app/ads/pacing.py
（既有「花費步調監控警示」，比對已經花了多少 vs 過了多少天）是不同職責——這支是
開期規劃當下就把整期的每日預算算好，兩邊互不相依、不合併。

三選一：連續（continuous，現況）／間歇（intermittent）／脈動（pulse）。段間強度差
接受觸發 Meta 學習期重置、不為了迴避重置而壓平強度差，取捨見
docs/adr/0010-pacing-curve-accepts-learning-reset.md。
"""

from app.ads import budget as budget_calc

# 天數不到這個門檻，間歇／脈動的段落會被壓得太碎，效果不明顯，只留連續（ADR 0010 第五節）。
SHORT_DURATION_THRESHOLD_DAYS = 14

# 脈動三段：天數比例 20/60/20（預熱/高潮/衝刺），預算比例 15/55/30——衝刺期強度最高
# （截止日效應：檔期本質是限時優惠，越接近截止日買氣越集中）。ADR 0010 第一節。
_PULSE_PHASES = (("warmup", 0.15), ("peak", 0.55), ("sprint", 0.30))

INTERMITTENT_CYCLE_DAYS = 3       # 3 天一循環，2 天正常量＋1 天降量（ADR 0010 第二節）
INTERMITTENT_REDUCED_RATIO = 0.4  # 降量日＝平均日預算的 4 成，下限見 budget.MIN_DAILY_BUDGET

# 畫面標籤：內部代號（continuous/intermittent/pulse）寫進 DB 與程式碼，畫面一律搭配
# 白話主標題（G9 契約「新手友善」第 3 點）。
STRATEGIES = {
    "continuous": {"title": "穩定投放", "tag": "連續", "desc": "每天花一樣多，先求穩定"},
    "intermittent": {"title": "喘息投放", "tag": "間歇", "desc": "投3天、緩1天，避免受眾看膩"},
    "pulse": {"title": "衝刺投放", "tag": "脈動", "desc": "先穩、後衝，越接近檔期尾聲花越多"},
}

# 策略理由：每個策略 2 個常見預設，可自行輸入取代（G9.5／G9.7 契約，文案沿用
# .scratch/grill/G9-pacing-curve-prototype.html 已驗收版本）。
PACING_REASON_PRESETS = {
    "continuous": ["沒有特別理由，先求穩定", "新手第一檔，先看基準表現"],
    "intermittent": ["怕受眾疲乏", "想中途測新素材角度"],
    "pulse": ["檔期本身是限時衝刺", "過去這個品牌衝刺期轉換特別好"],
}


def recommend_pacing_strategy(duration_days: int, has_offer: bool) -> tuple[str, str]:
    """依天數與有沒有綁優惠推薦一種排期策略，附白話理由。

    規則（ADR 0010）：天數 < 14 天只留連續；天數夠長時，有綁限時優惠才推脈動
    （脈動的正當性建立在「越接近截止日買氣越集中」，沒有優惠訊號時不預設）；否則連續。
    """
    if duration_days < SHORT_DURATION_THRESHOLD_DAYS:
        return "continuous", (
            f"這次檔期只有 {duration_days} 天，天數太短，間歇／脈動效果不明顯，先用穩定投放。")
    if has_offer:
        return "pulse", "這次檔期綁了限時優惠，越接近檔期尾聲買氣通常越集中，把預算重心放到後段。"
    return "continuous", "這次檔期沒有綁限時優惠，先用穩定投放，效果最容易判讀。"


def _finalize_days(raw_budgets: list, total_budget: float) -> list:
    """把未四捨五入的逐日預算收斂成兩位小數，餘數分給最後一天——避免逐日各自四捨五入
    累積出加總誤差（決策 0016 硬性原則：算錢不能因為四捨五入把錢弄丟）。"""
    days = [round(b, 2) for b in raw_budgets[:-1]]
    days.append(round(total_budget - sum(days), 2))
    return days


def _pulse_days(duration_days: int, total_budget: float) -> tuple:
    # 預熱／衝刺各自獨立四捨五入（20% 天數），高潮吸收天數捨入後的零頭——跟已驗收原型
    # （.scratch/grill/G9-pacing-curve-prototype.html）的 computeCurve() 算法一致。
    warmup_days = round(duration_days * 0.2)
    sprint_days = round(duration_days * 0.2)
    day_counts = {"warmup": warmup_days, "peak": duration_days - warmup_days - sprint_days,
                 "sprint": sprint_days}

    phases, raw = [], []
    for name, budget_ratio in _PULSE_PHASES:
        count = day_counts[name]
        if count <= 0:
            continue
        per_day = (total_budget * budget_ratio) / count
        phases += [name] * count
        raw += [per_day] * count
    return phases, raw


def _intermittent_days(duration_days: int, total_budget: float) -> tuple:
    avg_daily = total_budget / duration_days
    reduced_budget = max(avg_daily * INTERMITTENT_REDUCED_RATIO, budget_calc.MIN_DAILY_BUDGET)
    reduced_count = duration_days // INTERMITTENT_CYCLE_DAYS
    normal_count = duration_days - reduced_count
    normal_budget = (total_budget - reduced_count * reduced_budget) / normal_count

    phases, raw = [], []
    for i in range(duration_days):
        is_reduced = i % INTERMITTENT_CYCLE_DAYS == INTERMITTENT_CYCLE_DAYS - 1
        phases.append("reduced" if is_reduced else "normal")
        raw.append(reduced_budget if is_reduced else normal_budget)
    return phases, raw


def compute_curve(strategy: str, duration_days: int, total_budget: float) -> list:
    """策略＋天數＋總預算 → 逐日 `[{"phase", "budget", "stop_loss"}, ...]`。

    continuous 每天是同一個值（ADR 0010 第四節：行為不變，只是形狀統一，不套餘數分配，
    跟既有 `budget.daily_budget_for()` 的單純除法一致）；pulse／intermittent 用「餘數分給
    最後一天」讓加總精確等於 total_budget。stop_loss 沿用既有 `budget.DAILY_STOP_LOSS_MULTIPLIER`
    （ADR 0010 第四節，不另外定義新倍數）。
    """
    if duration_days <= 0:
        raise ValueError("檔期長度必須大於 0")
    if total_budget <= 0:
        raise ValueError("總預算必須大於 0")

    if strategy == "continuous":
        daily = round(total_budget / duration_days, 2)
        phases, budgets = ["normal"] * duration_days, [daily] * duration_days
    elif strategy == "pulse":
        phases, raw = _pulse_days(duration_days, total_budget)
        budgets = _finalize_days(raw, total_budget)
    elif strategy == "intermittent":
        phases, raw = _intermittent_days(duration_days, total_budget)
        budgets = _finalize_days(raw, total_budget)
    else:
        raise ValueError(f"不支援的排期策略：{strategy}")

    return [
        {"phase": phase, "budget": b,
         "stop_loss": round(b * budget_calc.DAILY_STOP_LOSS_MULTIPLIER, 2)}
        for phase, b in zip(phases, budgets)
    ]


# ---------------------------------------------------------------------------
# 排期到期提醒（票 B4R-warroom-redesign，S8R.9-11）：比對「今天」與「前一天」在
# `daily_budgets`（`compute_curve()` 既有逐日陣列）裡的金額是否不同，不同就代表今天要去
# Meta 手動調整日預算。`continuous` 策略每天金額都一樣，天生恆回 None，不用特判策略種類。
# ---------------------------------------------------------------------------

def due_schedule_change(cycle: dict, daily_budgets: list, today: str):
    """`cycle` 需要 `start_date`／`end_date`；`daily_budgets` 是這期 `derived_plan_json` 裡
    存的逐日陣列。今天不在檔期範圍內、是第一天（沒有前一天可比）、或前後金額相同都回 None。
    """
    from datetime import date as _date
    if not daily_budgets:
        return None
    start = _date.fromisoformat(cycle["start_date"])
    end = _date.fromisoformat(cycle["end_date"])
    today_date = _date.fromisoformat(today)
    if today_date < start or today_date > end:
        return None
    index = (today_date - start).days
    if index <= 0 or index >= len(daily_budgets):
        return None
    new_amount = daily_budgets[index]["budget"]
    if new_amount == daily_budgets[index - 1]["budget"]:
        return None
    return {
        "date": today,
        "new_daily_budget": new_amount,
        "copy_text": f"今天去 Meta 把日預算改成 NT${new_amount:,.0f}",
    }


def demo() -> None:
    """python -m app.ads.pacing_curve — 最小自檢，順便當用法示範。"""
    assert recommend_pacing_strategy(7, has_offer=True)[0] == "continuous"   # 太短，優惠也不推脈動
    assert recommend_pacing_strategy(21, has_offer=False)[0] == "continuous"  # 沒優惠不預設脈動
    assert recommend_pacing_strategy(21, has_offer=True)[0] == "pulse"
    assert recommend_pacing_strategy(14, has_offer=True)[0] == "pulse"       # 邊界：14 天不算短

    continuous = compute_curve("continuous", 14, 10000)
    assert len(continuous) == 14
    assert all(d["budget"] == continuous[0]["budget"] for d in continuous)  # 每天同一個值

    pulse = compute_curve("pulse", 14, 10000)
    assert len(pulse) == 14
    assert round(sum(d["budget"] for d in pulse), 2) == 10000.0
    assert [d["phase"] for d in pulse][:3] == ["warmup", "warmup", "warmup"]
    assert pulse[-1]["phase"] == "sprint"
    assert pulse[0]["stop_loss"] == round(pulse[0]["budget"] * budget_calc.DAILY_STOP_LOSS_MULTIPLIER, 2)

    intermittent = compute_curve("intermittent", 14, 10000)
    assert len(intermittent) == 14
    assert round(sum(d["budget"] for d in intermittent), 2) == 10000.0
    assert [d["phase"] for d in intermittent[:3]] == ["normal", "normal", "reduced"]

    # 除不盡的組合也要加總精確——這是本票驗收清單明點的守恆要求
    odd = compute_curve("pulse", 17, 12345.67)
    assert round(sum(d["budget"] for d in odd), 2) == 12345.67
    print("pacing_curve 自檢通過")


if __name__ == "__main__":
    demo()
