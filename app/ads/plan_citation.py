# -*- coding: utf-8 -*-
"""app/ads/plan_citation.py — 票 F2 契約 (b)：贏家有沒有被真的沿用。

從 `app/ads/plan.py`（凍結 800 行、不得再長，見 `docs/tech-debt.md`）拆出來的小檔——
這兩個函式只有 `plan.py::generate_options()` 這一個呼叫端，不是新開的容器（比照
`app/ads/reading_hypotheses.py` 檔頭說明：拆檔不是拆模組）。

形狀驗完（`plan.py::_normalize_option()` 只驗形狀，不驗內容）之後，內容再跟
`carry_forward.prior_winners()`／`carry_forward.rejected_directions()` 這兩份具名事實
比對一次：具名贏家沒有被任何切角引用、或已避開的方向原封不動又冒出來，都算違規，
沒通過是可見的失敗（不存進 `campaign_plan_option`），不是形狀合法就悄悄放行。
"""


def citation_violations(options: list, prior_winners: list, avoid_directions: list) -> list:
    """只在真的有具名事實可比對時才查（沒有贏家／避開方向就無從比對，不擋路）。"""
    if not prior_winners and not avoid_directions:
        return []

    angle_texts = [f"{angle['title']} {angle['message']}"
                   for option in options for angle in option["angles"]]

    violations = []
    if prior_winners and not any(
        w["angle"] in text for w in prior_winners for text in angle_texts
    ):
        violations.append({"kind": "winner_not_cited", "winner_angle": prior_winners[0]["angle"]})

    for avoided in avoid_directions:
        if any(avoided["statement"] in text for text in angle_texts):
            violations.append({"kind": "avoid_direction_reused", "statement": avoided["statement"]})

    return violations


def citation_error_message(violations: list) -> str:
    parts = []
    not_cited = [v["winner_angle"] for v in violations if v["kind"] == "winner_not_cited"]
    reused = [v["statement"] for v in violations if v["kind"] == "avoid_direction_reused"]
    if not_cited:
        parts.append(f"方案沒有沿用上期打出成績的切角（{not_cited[0]}）")
    if reused:
        parts.append(f"又出現已避開的方向（{'、'.join(reused)}）")
    return "，".join(parts) + "，麻煩重新產生一次。"
