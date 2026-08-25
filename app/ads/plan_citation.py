# -*- coding: utf-8 -*-
"""app/ads/plan_citation.py — 票 F2 契約 (b)：贏家有沒有被真的沿用；票 F12 收緊兩點：
只看客戶真的會讀到的「推薦方案」（不是隨便哪個選項提過就算），而且點名還不夠，要原樣
寫出它的 ROAS 數字。

從 `app/ads/plan.py`（凍結 800 行、不得再長，見 `docs/tech-debt.md`）拆出來的小檔——
這兩個函式只有 `plan.py::generate_options()` 這一個呼叫端，不是新開的容器（比照
`app/ads/reading_hypotheses.py` 檔頭說明：拆檔不是拆模組）。

形狀驗完（`plan.py::_normalize_option()` 只驗形狀，不驗內容）之後，內容再跟
`carry_forward.prior_winners()`／`carry_forward.rejected_directions()` 這兩份具名事實
比對一次：具名贏家沒有被推薦方案引用（連名字帶 ROAS 數字）、或已避開的方向原封不動
又冒出來，都算違規，沒通過是可見的失敗（不存進 `campaign_plan_option`），不是形狀
合法就悄悄放行。
"""

import re

_NUMBER_TOKEN = re.compile(r"\d+(?:\.\d+)?")


def _roas_forms(roas: float) -> set:
    """驗證用的可接受寫法：`f"{roas:.2f}"`（"4.30"）跟去尾零、去尾點的簡寫
    （"4.3"；`4.00` → "4"）。"""
    formatted = f"{roas:.2f}"
    stripped = formatted.rstrip("0").rstrip(".")
    return {formatted, stripped}


def _cites_roas(text: str, roas: float) -> bool:
    """數字要原封不動出現，不是子字串矇混——`4.31` 不能因為前三碼長得像 `4.3` 就算數，
    所以先掃出文字裡每一段完整數字，再逐一比對合法寫法，不是直接 `in` 整段文字。"""
    forms = _roas_forms(roas)
    return any(token in forms for token in _NUMBER_TOKEN.findall(text))


def citation_violations(options: list, prior_winners: list, avoid_directions: list) -> list:
    """只在真的有具名事實可比對時才查（沒有贏家／避開方向就無從比對，不擋路）。贏家只驗
    「推薦方案」——客戶讀到的是它，備案方案提到不算數（票 F12：舊碼的 `any()` 連備案都算
    數，正是原始缺陷）。避開方向沿用舊行為，掃全部選項。"""
    if not prior_winners and not avoid_directions:
        return []

    violations = []
    if prior_winners:
        recommended = (next((o for o in options if o["is_recommended"]), options[0])
                      if options else None)
        rec_angles = recommended["angles"] if recommended else []
        # 票 F15：贏家只要在推薦方案的任何地方交代過（summary／difference／任一切角）就算
        # 點名——只掃切角文字曾經誤判「只寫在 summary、difference 裡」為沒交代。一份全文，
        # 點名跟數字兩個檢查都用它。
        rec_full_text = (
            (recommended.get("summary", "") + recommended.get("difference", "") if recommended else "")
            + "".join(f"{a['title']}{a['message']}" for a in rec_angles)
        )
        for w in prior_winners:
            angle_missing = w["angle"] not in rec_full_text
            number_missing = not _cites_roas(rec_full_text, w["roas"])
            if angle_missing or number_missing:
                violations.append({
                    "kind": "winner_not_cited", "winner_angle": w["angle"],
                    "winner_roas": w["roas"], "angle_missing": angle_missing,
                })

    angle_texts = [f"{angle['title']} {angle['message']}"
                   for option in options for angle in option["angles"]]
    for avoided in avoid_directions:
        if any(avoided["statement"] in text for text in angle_texts):
            violations.append({"kind": "avoid_direction_reused", "statement": avoided["statement"]})

    return violations


def citation_error_message(violations: list) -> str:
    parts = []
    for v in violations:
        if v["kind"] != "winner_not_cited":
            continue
        roas_text = f"{v['winner_roas']:.2f}"
        if v["angle_missing"]:
            parts.append(f"方案沒有交代上期贏家「{v['winner_angle']}」（ROAS {roas_text}）")
        else:
            parts.append(f"方案提到上期贏家「{v['winner_angle']}」但沒寫出它的成績（ROAS {roas_text}）")
    reused = [v["statement"] for v in violations if v["kind"] == "avoid_direction_reused"]
    if reused:
        parts.append(f"又出現已避開的方向（{'、'.join(reused)}）")
    return "，".join(parts) + "，麻煩重新產生一次。"
