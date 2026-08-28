"""app/ads/account_structure.py — 帳戶結構＋預算配置底案（票 5，決策 0023 第 14、15 點）。

純函數：吃這期的日預算，依 `app.core.rule_cards`「帳戶結構與預算配置門檻」規則卡（card_key
`budget_structure`）算出底案——CBO／ABO、開幾組、每組怎麼分預算。不呼叫 LLM、不寫資料庫；
AI 只能對這裡算出來的底案「具名異議」（見 app/ads/plan.py），不能自己改數字
（決策 0016 硬性原則 4：數字走程式，AI 只翻人話／給意見）。
"""

from dataclasses import dataclass

from app.core import rule_cards

CARD_KEY = "budget_structure"

TIER_LABELS = {
    "small": "小預算",
    "medium": "中預算",
    "large": "大預算",
}


@dataclass(frozen=True)
class GroupPlan:
    """底案裡的一個廣告組／活動。"""

    role: str          # test/validation/scaling/testing
    label: str          # 人話角色名
    ratio: float        # 佔日預算比例
    daily_budget: float
    below_floor: bool   # 這組日預算低於每組下限，可能跑不出可判讀數據


@dataclass(frozen=True)
class StructureRecommendation:
    tier: str                # small/medium/large
    tier_label: str
    structure_label: str     # 人話：帳戶結構長怎樣
    groups: list              # GroupPlan 清單
    note: str                 # 人話理由


def _group(role: str, label: str, ratio: float, daily_budget: float, floor: float) -> GroupPlan:
    daily_budget = round(daily_budget, 2)
    return GroupPlan(role=role, label=label, ratio=round(ratio, 4),
                      daily_budget=daily_budget, below_floor=daily_budget < floor)


def recommend(conn, brand_id: str, daily_budget: float) -> StructureRecommendation:
    """算這期的帳戶結構與預算配置底案。daily_budget 已經是程式算好的數字（見 app/ads/budget.py），
    這裡只負責依規則卡門檻（這個品牌的覆寫值，沒覆寫就用系統預設）分級距、分組別，不重算日預算本身。"""
    if daily_budget is None or daily_budget <= 0:
        raise ValueError("日預算必須大於 0")

    floor = rule_cards.get_value(conn, brand_id, CARD_KEY, "min_daily_per_group")
    medium_floor = rule_cards.get_value(conn, brand_id, CARD_KEY, "medium_tier_floor")
    large_floor = rule_cards.get_value(conn, brand_id, CARD_KEY, "large_tier_floor")
    validation_ratio = rule_cards.get_value(conn, brand_id, CARD_KEY, "medium_validation_ratio")
    scaling_ratio = rule_cards.get_value(conn, brand_id, CARD_KEY, "large_scaling_ratio")

    if daily_budget < medium_floor:
        tier = "small"
        structure_label = "單一廣告組（不分 CBO／ABO，錢不夠拆）"
        groups = [_group("test", "全額投入測試", 1.0, daily_budget, floor)]
        note = (
            f"日預算約 {daily_budget:,.0f} 元，低於中預算門檻（{medium_floor:,.0f} 元）："
            "硬拆成兩組的話，每組都會低於 Meta 每組日預算下限，兩組都跑不出可判讀的數據。"
            "這期全額投入單一測試組，目標講清楚：先找出能打的受眾與素材角度，"
            "不同時追求「驗證」與「放大」兩件事。"
        )
    elif daily_budget < large_floor:
        tier = "medium"
        structure_label = "CBO，兩組（驗證＋測試）"
        test_ratio = 1 - validation_ratio
        groups = [
            _group("validation", "已驗證方向", validation_ratio,
                   daily_budget * validation_ratio, floor),
            _group("test", "新受眾／新素材測試", test_ratio, daily_budget * test_ratio, floor),
        ]
        note = (
            f"日預算約 {daily_budget:,.0f} 元，用一個 CBO 活動、兩個廣告組："
            f"約 {validation_ratio:.0%} 留給比較有把握的方向，"
            f"約 {test_ratio:.0%} 留給新受眾或新素材測試，兩邊都要顧到。"
        )
    else:
        tier = "large"
        structure_label = "雙 CBO：放大＋測試"
        testing_ratio = 1 - scaling_ratio
        groups = [
            _group("scaling", "放大活動（只放已驗證贏家）", scaling_ratio,
                   daily_budget * scaling_ratio, floor),
            _group("testing", "測試活動（新概念與迭代版本）", testing_ratio,
                   daily_budget * testing_ratio, floor),
        ]
        note = (
            f"日預算約 {daily_budget:,.0f} 元，開兩個獨立的 CBO 活動：放大活動抓約 "
            f"{scaling_ratio:.0%} 預算，只放已經驗證過的贏家素材；測試活動抓約 "
            f"{testing_ratio:.0%}，放新概念與迭代版本，用獨立保護預算，避免贏家把新測試餓死。"
            "如果這是第一次投放、還沒有歷期驗證過的贏家，兩個活動這期都先當測試用，"
            "等下一期真的有贏家後再照這個比例分配。"
        )

    return StructureRecommendation(tier=tier, tier_label=TIER_LABELS[tier],
                                    structure_label=structure_label, groups=groups, note=note)


def demo() -> None:
    """python -m app.ads.account_structure — 最小自檢，順便當用法示範（無需資料庫，規則卡走預設值）。"""
    small = recommend(None, "demo_brand", 500)
    assert small.tier == "small" and len(small.groups) == 1, small
    assert small.groups[0].daily_budget == 500

    medium = recommend(None, "demo_brand", 1000)
    assert medium.tier == "medium" and len(medium.groups) == 2, medium
    assert medium.groups[0].daily_budget == 700.0  # 70%
    assert medium.groups[1].daily_budget == 300.0  # 30%，剛好貼著下限，不算低於

    large = recommend(None, "demo_brand", 2000)
    assert large.tier == "large" and len(large.groups) == 2, large
    assert large.groups[0].daily_budget == 1600.0  # 80%
    assert large.groups[1].daily_budget == 400.0   # 20%

    dipping = recommend(None, "demo_brand", 650)  # 中預算但 30% 那組會掉到下限以下
    assert dipping.groups[1].below_floor, dipping
    print("account_structure 自檢通過：", small, medium, large, sep="\n")


if __name__ == "__main__":
    demo()
