"""app/workbench/looks.py — F07-I04 (ARCHITECTURE.md §5.9): the look catalogue, the
program-only slot plan (`allocate`), the recommendation rule and the learnings read used to
build it. No model call lives here — the model only ever fills the slots this module already
decided (Decision 21). Catalogue copied verbatim from
`.harness/scratch/probes/image-prompt-v4/run_v4.py::LOOKS` (Decision 19), same order — that
order is the catalogue order used as the final tiebreak in `allocate()`.
"""

import random

from app.brand_intelligence import repository as bi_repo

LOOKS: dict[str, tuple[str, str]] = {
    "phone_raw": (
        "手機原生抓拍",
        "iPhone 手持原生抓拍、未修圖、輕微晃動與失焦、不均勻光線、"
        "真實雜亂的環境，不擺拍的日常照片感。",
    ),
    "flash_snapshot": (
        "直閃快照", "小相機或手機直閃、硬陰影與暗角、略過曝的膚色、夜晚與聚會的隨性感。",
    ),
    "documentary": (
        "紀實自然光", "旁觀視角的紀實攝影、自然光、真實環境與互動、不干預的構圖、溫和色彩。",
    ),
    "soft_lifestyle": (
        "柔光生活", "窗邊或清晨柔光、低飽和暖色、布料與木頭等觸感材質、淺景深、溫柔親密。",
    ),
    "clean_bright": (
        "明亮乾淨", "高明度均勻柔光、白與淺色系、整齊有秩序、清楚可信，專業而不冰冷。",
    ),
    "studio_hero": (
        "棚拍主視覺",
        "攝影棚控光、純色或漸層背景、材質與細節清楚、主角是唯一焦點，廣告大片的精準。",
    ),
    "dark_luxury": (
        "暗調精品", "單一側光、深色背景、大量負空間、材質微距、克制的反光，沉靜高級。",
    ),
    "cinematic": (
        "電影感", "有方向性的主光與陰影、電影調色、故事瞬間與情緒張力、寬銀幕般的構圖感。",
    ),
    "bold_graphic": (
        "平面大字", "平面設計海報、純色塊、超大字體與幾何元素、高對比，照片元素極少。",
    ),
    "ui_render": (
        "介面畫面", "乾淨的數位介面與裝置畫面、精準格線、真實可讀的資訊層級、冷靜的科技色。",
    ),
    "illustration": (
        "插畫", "手繪或向量插畫、明確筆觸與色塊、角色化表現，有溫度與幽默。",
    ),
    "editorial_portrait": (
        "人物專訪", "雜誌人物攝影、窗光或柔和主光、淺景深、真實膚質，眼神與姿態有故事。",
    ),
}

BRAND_SPEC = "brand_spec"
BRAND_SPEC_LABEL = "品牌規範"

_CATALOGUE_KEYS = list(LOOKS)


def look_label(key: str) -> str:
    if key == BRAND_SPEC:
        return BRAND_SPEC_LABEL
    entry = LOOKS.get(key)
    return entry[0] if entry is not None else key


def look_texture(key: str, brand_spec_text: str | None) -> str:
    if key == BRAND_SPEC:
        return brand_spec_text or ""
    entry = LOOKS.get(key)
    return entry[1] if entry is not None else ""


def _catalogue_index(key: str) -> int:
    if key == BRAND_SPEC:
        return -1
    return _CATALOGUE_KEYS.index(key)


def allocate(n: int, *, fit_looks: list, excluded: list, winners: list, history: dict,
             rng: random.Random) -> dict:
    """Program-only slot plan (Decision 21). `fit_looks` may start with `brand_spec`;
    `excluded` never excludes `brand_spec` (a brand-provided look is never dropped by the
    system's own guess). `exploit_n = n * 7 // 10` slots cycle the learned winners that are
    still available, else the fit ranking; the rest explore the least-tried non-excluded
    looks (ties: fit rank, then catalogue order, `brand_spec` first)."""
    excluded_set = set(excluded) - {BRAND_SPEC}
    available = set(_CATALOGUE_KEYS) - excluded_set
    if BRAND_SPEC in fit_looks and BRAND_SPEC not in excluded_set:
        available.add(BRAND_SPEC)

    exploit_n = n * 7 // 10
    exploit_pool = [k for k in winners if k in available]
    if not exploit_pool:
        exploit_pool = [k for k in fit_looks if k in available]

    plan: list[tuple[str, str]] = []
    if exploit_pool:
        for i in range(exploit_n):
            plan.append((exploit_pool[i % len(exploit_pool)], "exploit"))

    used = set(exploit_pool)
    candidates = [k for k in available if k not in used]
    rank = {k: i for i, k in enumerate(fit_looks)}
    candidates.sort(key=lambda k: (
        history.get(k, {}).get("adopted", 0),
        history.get(k, {}).get("offered", 0),
        rank.get(k, 99),
        _catalogue_index(k),
    ))

    remaining = n - len(plan)
    explore_first = None
    if candidates:
        explore_first = candidates[0] if remaining > 0 else None
        for i in range(remaining):
            plan.append((candidates[i % len(candidates)], "explore"))
    elif exploit_pool:
        for i in range(remaining):
            plan.append((exploit_pool[i % len(exploit_pool)], "explore"))

    exploit_looks = list(dict.fromkeys(look for look, slot in plan if slot == "exploit"))
    explore_looks = list(dict.fromkeys(look for look, slot in plan if slot == "explore"))

    if n != 2:
        rng.shuffle(plan)

    return {
        "plan": plan, "explore_first": explore_first,
        "exploit_looks": exploit_looks, "explore_looks": explore_looks,
    }


def recommend(plan: list, explore_first: str | None, *, rounds: int,
              explore_recommended: int) -> int:
    """Decision 22: recommend explore roughly 3 in 10 rounds — 1-based slot index."""
    if explore_first is not None and 10 * (explore_recommended + 1) <= 3 * (rounds + 1):
        for i, (look, slot) in enumerate(plan):
            if slot == "explore" and look == explore_first:
                return i + 1
    for i, (_look, slot) in enumerate(plan):
        if slot == "exploit":
            return i + 1
    return 1


def plan_text(exploit_looks: list, explore_looks: list) -> str:
    parts = []
    if exploit_looks:
        parts.append("主力：" + "、".join(look_label(k) for k in exploit_looks))
    if explore_looks:
        parts.append("探索：" + "、".join(look_label(k) for k in explore_looks))
    return "；".join(parts)


def _parse_visual_scope(scope: str) -> tuple[str, str, str] | None:
    """`visual；audience=<key>；<dimension>=<value>` — anything else is malformed and
    skipped, never raised (source data outside this module's control)."""
    parts = (scope or "").split("；")
    if len(parts) != 3 or parts[0] != "visual":
        return None
    if not parts[1].startswith("audience="):
        return None
    if "=" not in parts[2]:
        return None
    audience = parts[1][len("audience="):]
    dimension, _sep, value = parts[2].partition("=")
    if not dimension:
        return None
    return audience, dimension, value


def _within_180_days(learned_at, today) -> bool:
    if learned_at is None or today is None:
        return False
    d1 = learned_at.date() if hasattr(learned_at, "date") else learned_at
    d2 = today.date() if hasattr(today, "date") else today
    return (d2 - d1).days <= 180


def visual_learnings(conn, brand_id: str, audience_key: str | None, *, today) -> dict:
    """Decision 23: learnings read for the slot plan and the prompt shell. No audience or an
    unknown audience -> nothing (there is nothing to match against)."""
    if audience_key is None:
        return {"winners": [], "lines": [], "omitted": 0, "ids": []}

    rows = bi_repo.list_learnings(conn, brand_id, source_track="visual", limit=200)
    matched = []
    for row in rows:
        if row.get("confidence") not in ("likely", "validated"):
            continue
        if not _within_180_days(row.get("learned_at"), today):
            continue
        parsed = _parse_visual_scope(row.get("applicability_scope") or "")
        if parsed is None:
            continue
        audience, dimension, value = parsed
        if audience != audience_key or value == "看不出":
            continue
        matched.append((row, dimension, value))

    lines = [row["learning_text"] for row, _dim, _value in matched[:5]]
    omitted = max(0, len(matched) - 5)
    winners: list[str] = []
    winner_ids: list[str] = []
    for row, dimension, value in matched:
        if dimension == "look" and value not in winners:
            winners.append(value)
            winner_ids.append(row["id"])
    line_ids = [row["id"] for row, _dim, _value in matched[:5]]
    ids = list(dict.fromkeys([*line_ids, *winner_ids]))
    return {"winners": winners, "lines": lines, "omitted": omitted, "ids": ids}
