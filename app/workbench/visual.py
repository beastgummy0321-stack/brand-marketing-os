"""app/workbench/visual.py — F07-I06: the image-prompt tables, pure code, no DB, no model call.
ARCHITECTURE.md §5.7 ("Image prompts: one round..."): the image-task table, the visual-fingerprint
vocabularies (device／layout／subject_role／persuasion／slot), the allowed-persuasion derivation,
the jargon-leak term list and the 品牌事實 negative-phrase warning. Private to app/workbench
(container contract §1; `workbench.may_depend_on == []`).

Ratio table copied from `app/methodology/meta-format-specs.md` (單圖 4:5，1080×1350 · 輪播
1:1，1080×1080) — that file is prompt-zero-parts, not read at runtime.
"""

import re

IMAGE_PROMPT_COUNT = 10

RATIO = {
    "single": ("4:5", "4:5 直式單圖廣告，1080×1350"),
    "carousel": ("1:1", "1:1 輪播卡片，1080×1080"),
}


def shape_for(format_key: str | None) -> str:
    """`carousel` reads as 輪播；everything else (`single_image`／`flexible`／`video`／a
    brand-made key／`None`) reads as 單圖 — ARCHITECTURE.md §5.7's shape rule."""
    return "carousel" if format_key == "carousel" else "single"


DEVICES = {
    "contrast": "對照",
    "metaphor": "誇張比喻",
    "borrowed_format": "借用格式",
    "frozen_moment": "定格瞬間",
    "demonstration": "直接示範",
    "testimony": "人物證言",
    "data_visual": "數據具象",
}

LAYOUTS = {
    "candid_scene": "情境畫面",
    "portrait_focus": "人物特寫",
    "subject_focus": "主角特寫",
    "split_compare": "分割對照",
    "flat_lay": "俯拍陳列",
    "magazine_cover": "雜誌封面",
    "newspaper_editorial": "報紙編輯",
    "zine_collage": "拼貼",
    "infographic": "資訊圖表",
    "social_screenshot": "社群截圖",
    "screen_mockup": "畫面示意",
    "type_poster": "大字海報",
}

SUBJECT_ROLES = {
    "absent": "不出現",
    "incidental": "順手帶到",
    "clear": "清楚出現",
    "hero": "主角",
}

PERSUASIONS = {
    "none": "無",
    "offer_headline": "優惠大字",
    "price_breakdown": "價格拆解",
    "countdown": "倒數",
    "testimonial": "顧客證言",
    "credential": "資格背書",
    "data_proof": "數據證明",
    "before_after": "前後對比",
}

SLOTS = {"exploit": "主力", "explore": "探索"}

CLOSE_WORDS = {
    "purchase": "下單",
    "booking": "預約",
    "lead": "留下資料或報名",
    "awareness": "進一步了解",
}


def _close_word(conversion_goal: str | None) -> str:
    return CLOSE_WORDS.get(conversion_goal or "", "下單")


# audience key -> {key, label (may hold "{close}"), how, subject_roles}
TASKS = {
    "cold_unaware": {
        "key": "stop_relate", "label": "讓人停下來、有共鳴",
        "how": "情境反差、比喻、生活觀察，不推銷",
        "subject_roles": ["absent", "incidental"],
    },
    "cold_problem_aware": {
        "key": "believe_solution", "label": "讓人相信有解法",
        "how": "使用情境、前後對照、把效果或服務現場畫出來（不畫效果數字）",
        "subject_roles": ["clear", "hero"],
    },
    "warm_engaged": {
        "key": "convert", "label": "讓猶豫的人{close}",
        "how": "主角主視覺、誘因與截止、打消疑慮",
        "subject_roles": ["clear", "hero"],
    },
    "customer_repeat": {
        "key": "come_again", "label": "讓用過的人再{close}一次",
        "how": "補齊、時間感、成套",
        "subject_roles": ["clear", "hero"],
    },
    "lapsed": {
        "key": "win_back", "label": "讓很久沒回來的人想起來",
        "how": "給回來的理由、有什麼不一樣了",
        "subject_roles": ["clear"],
    },
}

OFFER_PERSUASION = {
    "discount": ["offer_headline", "price_breakdown"],
    "limited_time": ["offer_headline", "countdown"],
    "bundle": ["offer_headline"],
    "trial_sample": ["offer_headline"],
    "guarantee": ["offer_headline"],
    "free_shipping": ["offer_headline"],
    "none": [],
}

PROOF_PERSUASION = {
    "customer_review": ["testimonial", "before_after"],
    "founder_voice": ["testimonial"],
    "expert_endorsement": ["credential"],
    "lab_report": ["credential"],
    "media_coverage": ["credential"],
    "sales_numbers": ["data_proof"],
    "none": [],
}


def task_row(audience_key: str | None, conversion_goal: str | None) -> dict | None:
    """`TASKS[audience_key]` with `{close}` filled in from `conversion_goal`
    (`CLOSE_WORDS`；`None`／unknown → 下單). `None` when the audience has no row."""
    row = TASKS.get(audience_key or "")
    if row is None:
        return None
    return {
        "key": row["key"],
        "label": row["label"].format(close=_close_word(conversion_goal)),
        "how": row["how"],
        "subject_roles": list(row["subject_roles"]),
    }


def allowed_persuasion(task_key: str, offer_key: str | None, proof_key: str | None) -> list:
    """`["none"]` for `stop_relate`; otherwise `none` plus the offer- and proof-derived union,
    in `PERSUASIONS` order. Unknown offer／proof keys contribute nothing."""
    if task_key == "stop_relate":
        return ["none"]
    allowed = {
        "none",
        *OFFER_PERSUASION.get(offer_key or "", []),
        *PROOF_PERSUASION.get(proof_key or "", []),
    }
    return [key for key in PERSUASIONS if key in allowed]


def all_task_rows(
    conversion_goal: str | None, offer_key: str | None, proof_key: str | None,
) -> dict:
    """`{task_key: {"label", "how", "subject_role", "persuasion"}}` for every row in `TASKS`, in
    `TASKS` order — sent whole when a set has no audience or an audience value the table does not
    know (ARCHITECTURE.md §5.7 decision 11). `offer_key`／`proof_key` are the set's own coordinates
    and do not depend on the audience: an unknown audience never widens persuasion, it is derived
    exactly like a known audience via `allowed_persuasion`."""
    return {
        row["key"]: {
            "label": row["label"].format(close=_close_word(conversion_goal)),
            "how": row["how"],
            "subject_role": list(row["subject_roles"]),
            "persuasion": allowed_persuasion(row["key"], offer_key, proof_key),
        }
        for row in TASKS.values()
    }


# ARCHITECTURE.md §5.7／§5.8: negative phrases the model may write, and the label-leak guard.
NEGATIVE_PATTERN = re.compile(r"(?<!要)不要|請勿|避免|禁止|不得|不出現|不放|勿")


def leak_terms(
    *,
    audience_label: str | None = None,
    angle_label: str | None = None,
    hook_label: str | None = None,
    proof_none_label: str | None = None,
    task_label: str | None = None,
) -> list[str]:
    """Classification jargon only, each label whole (never split on 「・」): the full audience
    label, the angle and hook names, the proof label when proof is `none`（無證明）, and the task
    label. Pain and offer labels are everyday words and are never parameters here. Empty/`None`
    entries are skipped; the result is deduplicated, order preserved."""
    terms = []
    for term in (audience_label, angle_label, hook_label, proof_none_label, task_label):
        if term and term not in terms:
            terms.append(term)
    return terms


def spec_warnings(brand_id, spec_text: str | None) -> list:
    """More than 2 `NEGATIVE_PATTERN` matches in a confirmed `visual_base` spec → one warning
    pointing at 品牌智庫 → 品牌事實 (ARCHITECTURE.md §5.9); `None`／≤2 → `[]`."""
    if not spec_text:
        return []
    if len(NEGATIVE_PATTERN.findall(spec_text)) <= 2:
        return []
    n = len(NEGATIVE_PATTERN.findall(spec_text))
    text = (
        f"視覺基礎裡有 {n} 句「不要／避免」這類限制；"
        "限制太多會鎖死整張圖的設計，建議只留最重要的一兩句。"
    )
    return [{"text": text, "href": f"/brands/{brand_id}/library?tab=facts"}]
