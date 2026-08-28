"""app/ads/budget.py — 開期預算的兩個純函數（票 3）。

決策 0016 硬性原則 4：數字走程式、LLM 只解釋。本檔不呼叫 LLM、不碰資料庫、不讀時間，
輸入什麼就算什麼——後續的開期流程（票 4）、交接包（票 8）、下期草案（票 13）全部從這裡取數字。

1. `plan_from_pain()`：「這筆錢賠光我也不心痛」滑桿 → 日預算、檔期長度、停損線、暫停門檻。
2. `split_budget()`：一期多產品時，總預算依各產品單位經濟分配。

人話文案不在這裡：本檔只回數字與旗標，介面自己套模板（文案改動不該動到算式的測試）。
"""

from dataclasses import dataclass

# --- 規則表（寫死常數，不讓 LLM 猜；要調就改這裡，改動會被測試接住）-----------------

# 台灣 Meta 廣告的實務下限：日預算低於這個數字，一天拿不到足夠曝光，
# 跑完整期也累積不出可判讀的樣本。低於此值不擋人，只回 daily_below_floor 旗標讓介面誠實說。
MIN_DAILY_BUDGET = 300.0

# 預設檔期長度。兩週是常見檔期，也讓 Meta 的學習期（約 3–7 天）之後還剩一半時間產生可判讀數據。
# 使用者可在開期表單自訂 7–30 天（票 3）；建議值仍以 14 天為準，只在金額撐不起日預算下限時縮短。
DEFAULT_DURATION_DAYS = 14
MIN_DURATION_DAYS = 7   # 再短，學習期就吃掉整個檔期，判讀沒有意義
MAX_DURATION_DAYS = 30  # 再長，新手等太久才拿到第一次回饋；錢多是每天多花，不是拉長天數

# 單日花費超過日預算這個倍數 → 提醒。Meta 官方允許單日超出日預算約 25%（週總額才守恆），
# 因此門檻設在 1.5 倍才不會天天跳警告（ADHD 設計輸入點名的「狼來了」風險）。
DAILY_STOP_LOSS_MULTIPLIER = 1.5

# 累積花掉總預算這個比例仍然零轉換 → 進入「該考慮暫停」的判斷。
PAUSE_THRESHOLD_RATIO = 0.5


@dataclass(frozen=True)
class CyclePlan:
    """滑桿反推出來的一期投放參數。金額單位同輸入（預設 TWD），不做幣別換算。"""

    total_budget: float
    duration_days: int
    daily_budget: float
    daily_stop_loss: float
    pause_threshold_spend: float
    daily_below_floor: bool  # 日預算低於實務下限，介面需誠實說「這金額可能跑不出可判讀的數據」


def plan_from_pain(pain_value: float) -> CyclePlan:
    """滑桿金額 → 一期的投放參數。

    pain_value 是「整期賠光也不心痛」的**總金額**，不是日預算——新手知道自己能賠多少，
    但不知道日預算該設多少，這個換算就是替他做掉的那一步（鐵則 20）。

    檔期長度的取法：先以 14 天為準；若這樣算出的日預算低於實務下限，就縮短檔期把日預算
    墊上去（最短 7 天）。錢再多也不拉長超過 21 天——多的錢每天多花，而不是讓人等更久。
    """
    if pain_value <= 0:
        raise ValueError("滑桿金額必須大於 0")

    days = DEFAULT_DURATION_DAYS
    if pain_value / days < MIN_DAILY_BUDGET:
        # 縮到剛好讓日預算達到下限；再短就守住 7 天，寧可日預算不足也不讓檔期短到無法判讀
        days = max(MIN_DURATION_DAYS, int(pain_value // MIN_DAILY_BUDGET))
    days = min(days, MAX_DURATION_DAYS)

    daily, below_floor = daily_budget_for(pain_value, days)
    return CyclePlan(
        total_budget=round(pain_value, 2),
        duration_days=days,
        daily_budget=daily,
        daily_stop_loss=round(daily * DAILY_STOP_LOSS_MULTIPLIER, 2),
        pause_threshold_spend=round(pain_value * PAUSE_THRESHOLD_RATIO, 2),
        daily_below_floor=below_floor,
    )


def daily_budget_for(total_budget: float, duration_days: int) -> tuple[float, bool]:
    """總預算 ÷ 使用者自訂天數 → 日預算，附是否低於實務下限。

    跟 `plan_from_pain` 的差別：那支是「金額 → 系統建議天數」的自動換算（會為了墊高日預算
    縮短天數）；這支是「金額＋使用者自己選的天數 → 日預算」的單純除法，供開期表單的檔期長度
    欄位使用——天數已經是人選的，程式不再自作主張改動它，只誠實回報這樣選日預算會是多少。
    """
    if duration_days <= 0:
        raise ValueError("檔期長度必須大於 0")
    daily = round(total_budget / duration_days, 2)
    return daily, daily < MIN_DAILY_BUDGET


# 檔期長度的即時短評（太短／適中／偏長）。門檻是規則卡精神的雛形：寫成表、可視可改，
# 不是散落在程式各處的魔術數字（決策 0016 硬性原則 4：判斷用規則，不用猜）。
DURATION_TIERS = (
    (9, "short", "偏短：Meta 的學習期大約要 3–7 天，天數太少，學習期後幾乎沒剩多少時間能判讀。"),
    (21, "moderate", "長度適中：學習期過後還留得下一段時間看數據，是常見的檔期長度。"),
    (MAX_DURATION_DAYS, "long", "偏長：要等比較久才有第一次完整回饋，但預算夠的話能多測幾個切角。"),
)


def duration_commentary(duration_days: int) -> dict:
    """天數變動時的即時短評。回傳 {"tier": "short/moderate/long", "note": 白話理由}。"""
    for upper, tier, note in DURATION_TIERS:
        if duration_days <= upper:
            return {"tier": tier, "note": note}
    return {"tier": DURATION_TIERS[-1][1], "note": DURATION_TIERS[-1][2]}


# --- 預算分配 ---------------------------------------------------------------

@dataclass(frozen=True)
class Allocation:
    """一個產品分到的預算。欄位對應 campaign_cycle_product 的同名欄位。"""

    product_id: str
    allocated_budget: float
    allocation_ratio: float
    allocation_basis: str      # economics（有自己的毛利）/estimated（用他人平均代入）/even（全都沒有）
    economics_missing: bool    # 介面依此標「精準度打折」＋一鍵去補（決策 0022 第 9 點）


def gross_margin(economics: dict | None) -> float | None:
    """從 product_economics 算單位毛利：售價 −（單位變動成本 ＋ 運費）。

    回 None 代表「算不出來」——缺 economics、缺售價、或毛利 ≤ 0。毛利 ≤ 0 併入「算不出來」是
    刻意的：這種產品拿毛利當權重會分到 0 元或負數，等於系統偷偷替使用者做了「不投這個產品」
    的決定。改為當作沒資料處理（用平均代入並標記），決策權留給人（決策 0013）。
    """
    if not economics:
        return None
    price = economics.get("selling_price")
    if price is None:
        return None
    cost = (economics.get("unit_variable_cost") or 0) + (economics.get("shipping_cost") or 0)
    margin = float(price) - float(cost)
    return margin if margin > 0 else None


def split_budget(total_budget: float, products: list[dict]) -> list[Allocation]:
    """把總預算分配到各產品。

    products：`[{"product_id": str, "economics": dict | None}, ...]`，順序即輸出順序。

    分配依據是**單位毛利**：每筆轉換賺得多的產品，能承受較高的單次取得成本，值得分到較多預算。
    缺毛利資料的產品不擋路——用有資料者的平均毛利代入，只標記 economics_missing；
    全部都沒資料才退回平均分。

    四捨五入的餘數由最後一個產品吸收，保證各項加總嚴格等於 total_budget（錢不能算丟）。
    """
    if not products:
        return []
    if total_budget <= 0:
        raise ValueError("總預算必須大於 0")

    margins = [gross_margin(p.get("economics")) for p in products]
    known = [m for m in margins if m is not None]

    if not known:
        basis_all, weights = "even", [1.0] * len(products)
    else:
        average = sum(known) / len(known)
        basis_all, weights = None, [m if m is not None else average for m in margins]

    total_weight = sum(weights)
    results: list[Allocation] = []
    running = 0.0
    for index, (product, weight, margin) in enumerate(zip(products, weights, margins)):
        is_last = index == len(products) - 1
        ratio = weight / total_weight
        if is_last:
            amount = round(total_budget - running, 2)  # 餘數落在最後一筆，避免加總對不上
        else:
            amount = round(total_budget * ratio, 2)
            running += amount
        results.append(
            Allocation(
                product_id=product["product_id"],
                allocated_budget=amount,
                allocation_ratio=round(ratio, 6),
                allocation_basis=basis_all or ("economics" if margin is not None else "estimated"),
                economics_missing=margin is None,
            )
        )
    return results


def demo() -> None:
    """python -m app.ads.budget — 最小自檢，順便當用法示範。"""
    plan = plan_from_pain(6000)
    assert plan.duration_days == 14 and plan.daily_budget == 428.57, plan
    assert not plan.daily_below_floor

    small = plan_from_pain(1000)
    assert small.duration_days == 7 and small.daily_below_floor, small

    daily, below = daily_budget_for(6000, 30)
    assert daily == 200.0 and below, (daily, below)
    assert duration_commentary(7)["tier"] == "short"
    assert duration_commentary(14)["tier"] == "moderate"
    assert duration_commentary(30)["tier"] == "long"

    parts = split_budget(10000, [
        {"product_id": "prd_A", "economics": {"selling_price": 1000, "unit_variable_cost": 400}},
        {"product_id": "prd_B", "economics": {"selling_price": 500, "unit_variable_cost": 200}},
        {"product_id": "prd_C", "economics": None},
    ])
    assert sum(p.allocated_budget for p in parts) == 10000, parts
    assert [p.allocation_basis for p in parts] == ["economics", "economics", "estimated"]
    print("budget 自檢通過：", plan, parts, sep="\n")


if __name__ == "__main__":
    demo()
