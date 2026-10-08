"""app/workbench/looks.py — F07-I04 (ARCHITECTURE.md §5.9): the look catalogue, the
program-only slot plan (`allocate`), the recommendation rule and the learnings read used to
build it. No model call lives here — the model only ever fills the slots this module already
decided (Decision 21). Catalogue copied verbatim from
`.harness/scratch/probes/image-prompt-v4/run_v4.py::LOOKS` (Decision 19), same order — that
order is the catalogue order used as the final tiebreak in `allocate()`.
"""

import hashlib
import json
import random
from copy import deepcopy

from app.brand_intelligence import repository as bi_repo
from app.core import settings
from app.workbench import coordinate_vocabulary
from app.workbench.learning_evidence import base_learning_scope, qualify_learning_evidence

# F53 retains the source owner's ten-event rule. Brief payloads cannot change that policy.
_MARKET_EVENTS = 10

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


def _version(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), default=str).encode()).hexdigest()


def current_conditions(conn, org, brand, product_id, *, supplied=None):
    """Recheck own brand facts; unavailable ads-owned inputs stay unknown, never inferred."""
    product = bi_repo.get_product(conn, brand, product_id) if product_id else None
    selected = product_id if product else None
    # Enqueue-time ads inputs are historical context. This owner has no legal fresh target,
    # measurement or material read; a matching product or timestamp cannot certify them today.
    current = {}
    today = settings.today_for_org(conn, org_id=org).isoformat()
    economics = bi_repo.get_product_economics(conn, brand, selected) if selected else None
    price = None
    active = economics and (not economics.get("effective_from") or
                           str(economics["effective_from"]) <= today) and (
        not economics.get("effective_to") or str(economics["effective_to"]) >= today)
    if economics and economics.get("status") == "confirmed" and active:
        price = _version({k: economics.get(k) for k in (
            "selling_price", "list_price", "currency", "effective_from", "effective_to",
            "unit_variable_cost", "shipping_cost",
        )})
    sources = bi_repo.offer_sources(conn, brand, selected)
    policies = bi_repo.list_brand_policies(conn, brand)
    offers = []
    for key in sorted({s["offer_key"] for s in sources}):
        terms = sorted(s["sentence"] for s in sources if s["offer_key"] == key)
        supporting = [p for p in policies if p["status"] == "confirmed" and p["offer_key"] == key
                      and p["sentence"] in terms]
        ends = [(p.get("params") or {}).get("valid_until") or
                (p.get("params") or {}).get("end_date") for p in supporting]
        offers.append({"key": key, "version": _version({
            "terms": terms, "params": sorted((p.get("params") or {} for p in supporting),
                                              key=lambda p: json.dumps(p, sort_keys=True)),
        }), "valid_until": min((str(e) for e in ends if e), default=None)})
    return {**current, "org_id": org, "brand_id": brand, "product_id": selected,
            "org_day": today, "mode": "real", "result_kind": None,
            "currency": None, "attribution": None,
            "audience_keys": [r["key"] for r in coordinate_vocabulary.list_coordinate_vocabulary(
                conn, org, brand) if r["dimension"] == "audience"],
            "customer_group_ids": [g["id"] for g in bi_repo.list_customer_groups(
                conn, brand, selected)] if selected else [],
            "conditions": {"price_version": price, "offers": offers,
                           "target_version": None, "materials": []}}


def _context(projected, current):
    return {"schema_version": 1, "revision": projected["revision"],
            "scope_product_id": current.get("product_id"), "scope_label": None,
            "eligible_count": projected["eligible_count"], "items": projected["items"][:30],
            "omitted": max(len(projected["items"]) - 30, 0)}


def qualified_creative(conn, org, brand, product_id, creative):
    """Refresh proposed evidence only; accepted assignments and original controls stay exact."""
    creative = deepcopy(creative)
    comparison = creative.get("comparison") or {}
    current = current_conditions(conn, org, brand, product_id,
                                 supplied=comparison.get("learning_current"))
    rows = bi_repo.list_learnings(conn, brand, limit=500, include_expired=True)
    references = [{"id": row["id"], "text": row.get("text"), "evidence": row.get("evidence")}
                  for row in comparison.get("learnings") or []]
    references += [{"id": row.get("learning_id"), "text": row.get("ad_name"),
                    "evidence": row.get("evidence")}
                   for row in [*(comparison.get("results") or []),
                       *((c.get("result") or {}) for c in comparison.get("controls") or [])]]
    retained = {row["id"] for row in rows}
    for row in references:
        if row["id"] and row["id"] not in retained:
            rows.append({"id": row["id"], "org_id": org, "brand_id": brand,
                         "product_id": ((row.get("evidence") or {}).get("scope") or {}).get(
                             "product_id"), "learning_text": row.get("text") or "",
                         "applicability_scope": "", "needs_revalidation": True})
            retained.add(row["id"])
    full = qualify_learning_evidence(rows, current, min_result_events=_MARKET_EVENTS,
                                     max_age_days=180)
    by_id = {item["id"]: item for item in full["items"]}
    raw = {row["id"]: row for row in rows}
    for row in comparison.get("learnings") or []:
        if row["id"] in by_id:
            row.update(evidence=by_id[row["id"]], text=raw[row["id"]]["learning_text"])
    for row in [*(comparison.get("results") or []),
                *((c.get("result") or {}) for c in comparison.get("controls") or [])]:
        if row.get("learning_id") in by_id:
            row["evidence"] = by_id[row["learning_id"]]
    comparison["evidence_context"] = {"schema_version": 1, "revision": full["revision"],
        "scope_product_id": current["product_id"], "scope_label": None,
        "eligible_count": full["eligible_count"], "items": full["items"][:30],
        "omitted": max(len(full["items"]) - 30, 0)}
    creative["comparison"] = comparison
    return creative


def visual_learnings(conn, brand_id: str, audience_key: str | None, *, today,
                     product_id=None, current=None, min_result_events=None) -> dict:
    """Decision 23: learnings read for the slot plan and the prompt shell. No audience or an
    unknown audience -> nothing (there is nothing to match against)."""
    if audience_key is None:
        return {"winners": [], "lines": [], "omitted": 0, "ids": []}

    rows = bi_repo.list_learnings(conn, brand_id, source_track="visual", limit=200,
                                  include_expired=True)
    current = current or {"brand_id": brand_id, "product_id": product_id, "conditions": {},
                          "org_day": str(today.date() if hasattr(today, "date") else today)}
    full = qualify_learning_evidence(rows, current, min_result_events=_MARKET_EVENTS,
                                     max_age_days=180)
    context = _context(full, current)
    by_id = {item["id"]: item for item in full["items"]}
    matched = []
    seen = set()
    for row in rows:
        evidence = by_id[row["id"]]
        if evidence["use_state"] != "usable" or not set(evidence["allowed_uses"]) & {
            "test", "retain_control", "market_support",
        } or evidence["same_direction_count"] < 2:
            continue
        parsed = _parse_visual_scope(base_learning_scope(row.get("applicability_scope")))
        if parsed is None:
            continue
        audience, dimension, value = parsed
        if audience != audience_key or value == "看不出":
            continue
        identity = (evidence["scope"]["claim_key"], dimension, value)
        if identity in seen:
            continue
        seen.add(identity)
        matched.append(({**row, "evidence": evidence}, dimension, value))

    lines = [f"{row['learning_text']}（{row['evidence']['support_label']}）"
             for row, _dim, _value in matched[:5]]
    omitted = max(0, len(matched) - 5)
    winners: list[str] = []
    winner_ids: list[str] = []
    for row, dimension, value in matched:
        if dimension == "look" and value not in winners and "market_support" in row[
            "evidence"]["allowed_uses"] and row["evidence"]["same_direction_count"] >= 2:
            winners.append(value)
            winner_ids.append(row["id"])
    line_ids = [row["id"] for row, _dim, _value in matched[:5]]
    ids = list(dict.fromkeys([*line_ids, *winner_ids]))
    return {"winners": winners, "lines": lines, "omitted": omitted, "ids": ids,
            "evidence_context": context}
