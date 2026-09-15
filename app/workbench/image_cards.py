"""app/workbench/image_cards.py — F07-I08 (ARCHITECTURE.md §5.7 (② count), §5.11, §5.13;
Decisions 26-27): pure, read-time rendering of the §5.8 row shape
(`{title, headline, prompt, text, fingerprint, cards, round, ...}`, written by `jobs.py` and
F07-I07) into the 圖片 tab's text — no DB, no model call. Private to app/workbench
(container contract §1; `workbench.may_depend_on == []`).
"""

import re

from app.workbench import visual

_QUOTE_RE = re.compile(r"「([^」]*)」")

# ARCHITECTURE.md §5.7 decision on ② 變體: nine fixed small changes, first N used per the
# plan's `variant_count`.
_VARIANT_CHANGES = [
    "背景色調", "取景遠近", "文字位置", "強調色", "姿勢或表情", "光線時段", "景深",
    "背景色調＋強調色", "取景遠近＋文字位置",
]


def _quotes(prompt: str) -> list[str]:
    seen: list[str] = []
    for match in _QUOTE_RE.findall(prompt or ""):
        if match not in seen:
            seen.append(match)
    return seen


def variant_text(body: dict, count: int) -> str:
    """F07 Decision 27: exactly the program-written ② 變體 text — no model call."""
    prompt = body.get("prompt") or ""
    text = body.get("text") or ""
    ratio_sentence = visual.RATIO["single"][1]
    quotes_line = "".join(f"「{q}」" for q in _quotes(prompt))
    prefix = prompt + "\n\n"
    tail = text[len(prefix):] if text.startswith(prefix) else text
    lines = [
        f"以附上的這張圖為基底，另外生成 {count} 張變體，一張一張出，主體不變、其他部分些許改變。",
        f"保持不變：畫面主體與人物、參考照的外型、{ratio_sentence}、文字的層級，"
        f"以及圖上每一段字逐字不改：{quotes_line}。",
        "每張只改一到兩個地方：",
        *[f"{i} {_VARIANT_CHANGES[i - 1]}" for i in range(1, count + 1)],
        tail,
    ]
    return "\n".join(lines)


def prompt_cards(body, *, version_index: int, selected: bool, variant_count: int) -> list:
    """`[]` for a pre-F07 row (no string `text`); else the version's own card, plus a ②
    變體 card when it is selected, the round is 單圖-shaped, and `variant_count > 0`."""
    if not isinstance(body, dict) or not isinstance(body.get("text"), str):
        return []
    title = body.get("title") or ""
    cards = [{"label": f"{version_index:02d}｜{title}", "text": body["text"]}]
    round_ = body.get("round")
    format_key = round_.get("format") if isinstance(round_, dict) else None
    if selected and visual.shape_for(format_key) == "single" and variant_count > 0:
        cards.append({"label": "② 變體", "text": variant_text(body, variant_count)})
    return cards


def fingerprint_text(body) -> str | None:
    """`None` for a pre-F07 row; else look·layout·device·persuasion labels, persuasion
    omitted when its key is `none` (Decision 26)."""
    if not isinstance(body, dict):
        return None
    fingerprint = body.get("fingerprint")
    if not isinstance(fingerprint, dict):
        return None
    parts = []
    for key in ("look", "layout", "device"):
        entry = fingerprint.get(key)
        label = entry.get("label") if isinstance(entry, dict) else None
        if label:
            parts.append(label)
    persuasion = fingerprint.get("persuasion")
    if isinstance(persuasion, dict) and persuasion.get("key") != "none":
        label = persuasion.get("label")
        if label:
            parts.append(label)
    return " · ".join(parts)


def badges(body, version_index: int) -> list:
    """`[]` for a pre-F07 row; else `[slot_label]` plus 「建議選這張」 when this is the
    round's recommended slot (Decision 26)."""
    if not isinstance(body, dict):
        return []
    fingerprint = body.get("fingerprint")
    round_ = body.get("round")
    if not isinstance(fingerprint, dict) or not isinstance(round_, dict):
        return []
    slot = fingerprint.get("slot")
    slot_label = slot.get("label") if isinstance(slot, dict) else None
    result = [slot_label] if slot_label else []
    if round_.get("recommended_index") == version_index:
        result.append("建議選這張")
    return result


def copy_all_text(bodies: list) -> str | None:
    """`None` when no body carries `text` (all pre-F07 rows). `bodies` is the latest round's
    rows in `version_index` order (Decision 26)."""
    if not any(isinstance(b, dict) and isinstance(b.get("text"), str) for b in bodies):
        return None
    first_round = next(
        (b.get("round") for b in bodies
         if isinstance(b, dict) and isinstance(b.get("round"), dict)),
        None,
    )
    format_key = first_round.get("format") if isinstance(first_round, dict) else None
    shape = visual.shape_for(format_key)
    parts: list[str] = []
    n = 0
    if shape == "carousel":
        lead = "請一次生成 10 張圖：兩組輪播各 5 張，每張只照下面對應的那一段，一段一張，不要合併。"
        for body in bodies:
            cards = body.get("cards") if isinstance(body, dict) else None
            for card in cards or []:
                text = card.get("text") if isinstance(card, dict) else None
                if not isinstance(text, str):
                    continue
                n += 1
                parts.append(f"第 {n} 張\n{text}")
    else:
        lead = "請一次生成 10 張圖，每張只照下面對應的那一段，一段一張，不要合併。"
        for body in bodies:
            text = body.get("text") if isinstance(body, dict) else None
            if not isinstance(text, str):
                continue
            n += 1
            parts.append(f"第 {n} 張\n{text}")
    return "\n\n".join([lead, *parts])
