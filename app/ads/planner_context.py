"""app/ads/planner_context.py — F48 Contract P: the one planner context every ads planner reads
(the brief, the strategy and the delivery plan). The program gathers and caps what a planner may
use for one sell-way -- the product and its facts, the 「不能講」 list, the coordinate menu and the
offers it keeps with their sentences, the customer groups, the product's learnings, last period's
learning goals and the capacity line -- and `section_text` prints each prompt block. No model
call, no write. Private to app/ads.

The menu (`prompt_rows`／`menu`) is the one filter the delivery plan's prompt and the hand edits
(`plan.create_ad`／`update_ad`) share. Headers that already existed elsewhere keep their exact
wording (`customer_groups.HEADER`, `coordinate_learning.HEADER`, 【這期可用的優惠】 with its
「- offer=〈key〉｜〈sentence〉」 lines), so `providers.ScriptedProvider`'s parsers keep working.
"""

import json
import math
from copy import deepcopy

from app import workbench
from app.ads import (
    ads_learnings as learning_service,
)
from app.ads import (
    budget,
    calendar_tw,
    coordinate_learning,
    customer_groups,
    learning_rank,
    learning_view,
    targets,
    triage,
    triage_capacity,
)
from app.ads import repository as ads_repo
from app.ads import sell_way as sell_way_mod
from app.brand_intelligence import repository as bi_repo
from app.core import rule_cards, vocab
from app.core import settings as coresettings

PRODUCT_HEADER = "【這個賣法】"
FORBIDDEN_HEADER = "【不能講】"
OFFERS_HEADER = "【這期可用的優惠】"
LEARNINGS_HEADER = "【過去的學習】"
PREVIOUS_HEADER = "【上一期想學的】"
CAPACITY_HEADER = "【這期撐得起幾則】"

KIND_LABELS = {"base": "單品", "composed": "組合"}

# Prompt caps (ARCHITECTURE.md §1: every list that reaches a prompt is capped), not rule cards.
_MAX_SELL_WAYS = 8  # sell-ways printed per knowledge product
_MAX_LEARNINGS = 10
_LEARNING_SCAN = 200  # rows read to pick the newest verdict per sell-way
_CREATIVE_CAPS = {"results": 12, "controls": 6, "learnings": 10, "calendar": 12, "facts": 12}
# Event learnings (pause confirmation, A/B, month settle) carry this scope prefix: each is its own
# finding; every other `ads` row is a period verdict sentence (`learning.write_learning`).
_EVENT_SCOPE_PREFIX = "ads;"


# -- product ------------------------------------------------------------------------------------


def sell_way_display_name(full_name: str) -> str:
    """A sell-way is named 「〈商品〉 · 〈賣法〉」: print the part after 「 · 」 (else all)."""
    return full_name.split(" · ", 1)[-1]


def _knowledge(conn, brand_id: str, knowledge_id: str, fact_cap: int) -> dict:
    """One knowledge product: `{id, name, facts: ["label：value"], omitted}` -- confirmed facts
    newest first, capped at `fact_cap`."""
    product = bi_repo.get_product(conn, brand_id, knowledge_id)
    facts = sorted(
        bi_repo.list_product_facts(conn, brand_id, knowledge_id, status="confirmed"),
        key=lambda f: f.get("confirmed_at") or f["created_at"], reverse=True,
    )
    return {
        "id": knowledge_id, "name": product["name"] if product else knowledge_id,
        "facts": [f"{f['label']}：{f['value']}" for f in facts[:fact_cap]],
        "omitted": max(len(facts) - fact_cap, 0),
    }


def _knowledge_line(entry: dict) -> str:
    text = "；".join(entry["facts"]) if entry["facts"] else "尚無確認過的事實"
    if entry["omitted"]:
        text += f"（另有 {entry['omitted']} 筆較舊的事實沒有列出）"
    return f"- {entry['name']}｜事實：{text}"


def _sell_way(conn, brand_id: str, product_id: str, today, shapes: dict) -> dict:
    """One sell-way: name, kind and today's price. A price whose window has passed is marked
    stale, never used as the current price (same rule as the brief's product list)."""
    product = bi_repo.get_product(conn, brand_id, product_id)
    name = product["name"] if product else product_id
    kind = shapes.get(product_id, "base")
    economics = bi_repo.get_product_economics(conn, brand_id, product_id)
    entry = {
        "id": product_id, "name": name, "display": sell_way_display_name(name),
        "kind": kind, "kind_label": KIND_LABELS[kind], "price": None, "stale": False,
        "priced": economics is not None,
    }
    if economics is not None:
        effective_to = economics.get("effective_to")
        entry["price"] = economics.get("selling_price")
        entry["stale"] = effective_to is not None and effective_to < today
        entry["basis"] = {
            "product_id": product_id, "price": entry["price"],
            "effective_from": economics.get("effective_from"), "stale": entry["stale"],
            "assumptions": list(economics.get("assumptions_json") or []),
            "sell_way_name": entry["display"],
        }
    return entry


def _product_blocks(conn, org_id: str, brand_id: str, product_ids: list[str]) -> list[dict]:
    """One block per set of knowledge products (`bi_repo.knowledge_product_ids`: a bundle has
    several, each with its own fact line under one cap); each block lists its sell-ways' prices,
    at most `_MAX_SELL_WAYS`. Knowledge hangs on the product, money on the sell-way (§8 item 1)."""
    today = coresettings.today_for_org(conn, org_id=org_id)
    fact_cap = int(rule_cards.get_value(conn, brand_id, "rule_prompt_cap", "max_active_rules"))
    shapes = {way["id"]: way["shape"] for way in bi_repo.list_sell_ways(conn, brand_id)}
    grouped: dict[tuple[str, ...], list[str]] = {}
    for product_id in product_ids:
        if bi_repo.get_product(conn, brand_id, product_id) is None:
            continue  # a stored id with no product behind it is never invented into a prompt
        knowledge_ids = tuple(bi_repo.knowledge_product_ids(conn, brand_id, product_id))
        grouped.setdefault(knowledge_ids, []).append(product_id)
    return [
        {
            "knowledge": [_knowledge(conn, brand_id, k, fact_cap) for k in knowledge_ids],
            "sell_ways": [_sell_way(conn, brand_id, pid, today, shapes)
                          for pid in ids[:_MAX_SELL_WAYS]],
            "overflow": max(len(ids) - _MAX_SELL_WAYS, 0),
        }
        for knowledge_ids, ids in grouped.items()
    ]


def _sell_way_piece(way: dict) -> str:
    if not way["priced"]:
        return f"{way['display']} 沒有價格資料｜{way['kind_label']}"
    piece = f"{way['display']} NT${way['price']}"
    if way["stale"]:
        piece += "（價格可能過期，僅供參考）"
    return f"{piece}｜{way['kind_label']}"


def _product_text(blocks: list[dict], has_ids: bool) -> str:
    if not has_ids:
        return PRODUCT_HEADER + "（這個 Campaign 沒有指定商品）"
    if not blocks:
        return PRODUCT_HEADER + "（沒有可用的價格資料）"
    lines = []
    for block in blocks:
        ways = "／".join(_sell_way_piece(way) for way in block["sell_ways"])
        if block["overflow"]:
            ways += f"（另有 {block['overflow']} 種賣法沒有列出）"
        facts = "\n".join(_knowledge_line(k) for k in block["knowledge"])
        lines.append(f"{facts}\n  賣法：{ways}")
    return PRODUCT_HEADER + "\n" + "\n".join(lines)


def prices_basis(blocks: list[dict]) -> list[dict]:
    """One row per priced sell-way the product block printed (查看策略依據 = what the model saw)."""
    return [way["basis"] for block in blocks for way in block["sell_ways"] if "basis" in way]


def products_section(conn, org_id: str, brand_id: str,
                     product_ids: list[str]) -> tuple[str, list[dict]]:
    """(【這個賣法】 text, prices basis) for these sell-ways -- the block the strategy and the brief
    print (moved here from `strategy._products_section`, one implementation)."""
    blocks = _product_blocks(conn, org_id, brand_id, product_ids)
    return _product_text(blocks, bool(product_ids)), prices_basis(blocks)


def _product(blocks: list[dict], product_id: str | None) -> dict | None:
    """Contract P's `product`: the picked sell-way with its kind, knowledge facts and price."""
    for block in blocks:
        for way in block["sell_ways"]:
            if way["id"] == product_id:
                return {
                    "id": way["id"], "name": way["name"], "kind": way["kind"],
                    "kind_label": way["kind_label"], "price": way["price"], "stale": way["stale"],
                    "knowledge": [{"id": k["id"], "name": k["name"], "facts": k["facts"]}
                                  for k in block["knowledge"]],
                }
    return None


# -- the menu (F38／F42; one filter for the planner and the hand edits, F48-I06) ------------------

# Why a vocabulary row is off this period's menu -- the hand-edit refusal names it.
NO_EVIDENCE = "沒有登記證據"
OFFER_NOT_HONOURED = "優惠不適用"
NO_END_DATE = "沒有結束日"
PHOTOS_ONLY = "只有照片"


def _exclusion(row: dict, allowed_proof: set, has_end_date: bool, allowed_offer: set,
               media_capability: str | None) -> str | None:
    dimension, key = row["dimension"], row["key"]
    if dimension == "proof" and key not in allowed_proof:
        return NO_EVIDENCE
    if dimension == "offer" and key not in allowed_offer:
        return OFFER_NOT_HONOURED
    if dimension == "offer" and key == "limited_time" and not has_end_date:
        return NO_END_DATE
    if dimension == "format" and key == "video" and media_capability == "photo":
        return PHOTOS_ONLY
    return None


def prompt_rows(rows: list, available_proof: set[str], has_end_date: bool,
                available_offer: set[str], media_capability: str | None) -> list:
    """F38 decision 1/3: the model's menu only offers the proof kinds the brand has confirmed
    evidence for (plus `none`), and `offer/limited_time` only when the campaign has an end date
    (the workbench quotes that date as the copy's one deadline). F42 (drill-8 red #1 #2): an
    `offer` row is offered only when it is `none` or the brand can honour it
    (`bi_repo.available_offer_keys`; `limited_time` must pass both rules), and `format/video` is
    dropped for a photo-only brand (`brand.media_capability == "photo"`; NULL = never asked, no
    format filter). Every other row passes through. `coordinate_vocabulary` itself stays
    unfiltered -- label lookups use it."""
    allowed_proof, allowed_offer = available_proof | {"none"}, available_offer | {"none"}
    return [row for row in rows if _exclusion(
        row, allowed_proof, has_end_date, allowed_offer, media_capability) is None]


def menu(conn, org_id: str, brand_id: str, product_id: str | None, has_end_date: bool) -> dict:
    """`{rows, excluded}` for one sell-way: `rows` = `prompt_rows` over the brand vocabulary (the
    delivery plan's menu, served as the campaign's `menu`); `excluded` = `{(dimension, key):
    reason}` for every vocabulary row the menu leaves out (`create_ad`／`update_ad` refuse those
    keys and say why)."""
    brand = bi_repo.get_brand(conn, brand_id) or {}
    vocabulary = ads_repo.coordinate_vocabulary(conn, org_id, brand_id)
    allowed_proof = bi_repo.available_proof_keys(conn, brand_id) | {"none"}
    allowed_offer = bi_repo.available_offer_keys(conn, brand_id, product_id) | {"none"}
    rows, excluded = [], {}
    for row in vocabulary:
        reason = _exclusion(row, allowed_proof, has_end_date, allowed_offer,
                            brand.get("media_capability"))
        if reason is None:
            rows.append(row)
        else:
            excluded[(row["dimension"], row["key"])] = reason
    return {"rows": rows, "excluded": excluded}


def menu_offer_keys(rows: list) -> set[str]:
    """The filtered menu's offer keys other than `none` -- what the planner may truly promise."""
    return {row["key"] for row in rows if row["dimension"] == "offer" and row["key"] != "none"}


# -- offers -------------------------------------------------------------------------------------


def _offers(conn, brand_id: str, product_id: str | None, rows: list) -> list:
    """`[{key, label, sentence}]`: each registered offer sentence (`bi_repo.offer_sources`) whose
    key the filtered menu `rows` keeps (the brand vocabulary, the offers this sell-way can honour,
    `limited_time` only with an end date), each sentence once."""
    labels = {row["key"]: row["label"] for row in rows
              if row["dimension"] == "offer" and row["key"] != "none"}
    out: list[dict] = []
    for source in bi_repo.offer_sources(conn, brand_id, product_id):
        key, sentence = source["offer_key"], source["sentence"]
        if key in labels and not any(o["key"] == key and o["sentence"] == sentence for o in out):
            out.append({"key": key, "label": labels[key] or vocab.offer_label(key),
                        "sentence": sentence})
    return out


# -- learnings ----------------------------------------------------------------------------------


def newest_per_product(rows: list[dict]) -> list[dict]:
    """F41-I02: one current campaign verdict per `product_id` -- `rows` come newest first, so the
    first verdict of each sell-way wins; an older period's contradicting verdict never reaches the
    model. Event learnings (`ads;` scope) pass through untouched; the order stays newest first."""
    seen: set = set()
    kept = []
    for row in rows:
        scope = workbench.base_learning_scope(row.get("applicability_scope"))
        if not scope.startswith(_EVENT_SCOPE_PREFIX):
            if row.get("product_id") in seen:
                continue
            seen.add(row.get("product_id"))
        kept.append(row)
    return kept


def ads_learnings(conn, brand_id: str, product_id: str | None = None, *, rows=None,
                 evidence_context=None) -> list[dict]:
    """The `ads`-track learnings a planner reads, newest first, at most `_MAX_LEARNINGS`. With a
    sell-way: that sell-way's rows plus brand-level ones (an imported campaign has no sell-way);
    another product's never apply. Without a selected product: brand-level rows only."""
    if rows is None:
        rows = bi_repo.list_learnings(conn, brand_id, limit=_LEARNING_SCAN, source_track="ads",
                                      include_expired=True)
    rows = [row for row in rows if row.get("product_id") in (product_id, None)]
    kept = newest_per_product(rows)[:_MAX_LEARNINGS]
    if kept:
        projected = evidence_context or learning_service.evidence_context(
            conn, kept[0]["org_id"], brand_id, product_id, rows=rows, cap=_LEARNING_SCAN,
        )
        by_id = {item["id"]: item for item in projected["items"]}
        kept = [{**row, "evidence": by_id[row["id"]]} for row in kept]
    return kept


def learnings_text(rows: list[dict]) -> str:
    if not rows:
        return LEARNINGS_HEADER + "（這個品牌還沒有任何學習記錄）"
    lines = [
        f"- {row['learning_text']}（{row['evidence']['support_label']}；"
        + ("本期可用" if row["evidence"]["use_state"] == "usable"
           else "歷史／待核對，不能作本期市場支持") + "）"
        for row in rows
    ]
    return LEARNINGS_HEADER + "\n" + "\n".join(lines)


def learnings_basis(rows: list[dict]) -> list[dict]:
    return [
        {"id": row["id"], "text": row["learning_text"], "level": row["confidence"],
         "needs_revalidation": row["needs_revalidation"], "evidence": row["evidence"]}
        for row in rows
    ]


# -- previous period ----------------------------------------------------------------------------


def _previous(conn, org_id: str, brand_id: str, product_id: str | None) -> dict | None:
    """The newest closed internal campaign of this sell-way: `{campaign_id, name, learning_goals,
    closed_count, best}` -- `best` = its cheapest sold ad `{ad_name, cost_per_sale, sales}` from
    the ranked view, `None` when nothing sold. `None` when this sell-way never closed one."""
    rows = [
        dict(row) for row in conn.execute(
            "SELECT id, name, context_json, budget_basis_json FROM ads_campaign"
            " WHERE org_id = %s AND brand_id = %s AND status = 'closed' AND origin = 'internal'"
            " ORDER BY closed_at DESC NULLS LAST, id",
            (org_id, brand_id),
        ).fetchall()
        if sell_way_mod.of_campaign(dict(row)) == product_id
    ]
    if not rows:
        return None
    newest = rows[0]
    goals = ((newest.get("budget_basis_json") or {}).get("strategy") or {}).get("learning_goals")
    view = learning_view.learnings_view(conn, org_id, brand_id, campaign_id=newest["id"], limit=1)
    sold = [row for c in view["campaigns"] for row in c["rows"] if row["cost_per_sale"] is not None]
    best = min(sold, key=lambda row: row["cost_per_sale"]) if sold else None
    return {
        "campaign_id": newest["id"], "name": newest["name"],
        "learning_goals": [g for g in goals or [] if isinstance(g, str)],
        "closed_count": len(rows),
        "best": None if best is None else {
            "ad_name": best["ad_name"], "cost_per_sale": best["cost_per_sale"],
            "sales": best["sales"],
        },
    }


def _previous_text(previous: dict | None) -> str:
    if previous is None:
        return PREVIOUS_HEADER + "（這個賣法還沒有結案過的上一期）"
    if not previous["learning_goals"]:
        return PREVIOUS_HEADER + f"（上一期「{previous['name']}」沒有寫想學的）"
    lines = [f"- {goal}" for goal in previous["learning_goals"]]
    return PREVIOUS_HEADER + f"（上一期「{previous['name']}」）\n" + "\n".join(lines)


# -- capacity (Contract C) ----------------------------------------------------------------------


def capacity_of(daily, cap, roles: int = 0) -> dict | None:
    """Contract C: `{daily, cap, can_support, ceiling}` -- `ceiling = max(can_support + 1, roles)`
    (one explore slot; every adopted role needs an ad). `None` when either number is unknown."""
    if any(value is None or isinstance(value, bool) or not math.isfinite(value) or value <= 0
           for value in (daily, cap)):
        return None
    can_support = triage_capacity.can_support(daily, cap)
    if can_support is None:
        return None
    return {"daily": daily, "cap": cap, "can_support": can_support,
            "ceiling": max(can_support + 1, roles)}


def capacity_line(capacity: dict | None) -> str:
    if capacity is None:
        return "還算不出這期撐得起幾則（沒有上限或還沒有預算）"
    return (
        f"這期每天 {learning_rank.whole(capacity['daily'])}，撐得起 {capacity['can_support']} 則"
        f"（另加 1 則探索）；最多 {capacity['ceiling']} 則"
        f"（上限每筆 {learning_rank.whole(capacity['cap'])}）"
    )


def _days(campaign: dict) -> int:
    start, end = campaign.get("start_date"), campaign.get("end_date")
    if start is None or end is None:
        return 0
    return max((end - start).days + 1, 0)


# -- the context --------------------------------------------------------------------------------


def calendar_window(campaign: dict, group: dict | None = None) -> tuple:
    """Effective delivery dates: each missing group side falls back independently."""
    group = group or {}
    return (
        group.get("start_date") or campaign.get("start_date"),
        group.get("end_date") or campaign.get("end_date"),
    )


def _calendar_source(campaign: dict, groups: list[dict] | None) -> tuple[list, list]:
    """Full known windows and their event union; an unknown side supplies no invented range."""
    windows = []
    events = {}
    # Retain the full known campaign comparison range, adding child windows when it is unbound.
    for group in [None, *(groups or [])]:
        start, end = calendar_window(campaign, group)
        windows.append({"group_id": (group or {}).get("id"), "start": start, "end": end})
        if start is None or end is None:
            continue
        for row in calendar_tw.events_between(start, end):
            events[(row["start"], row["end"], row["name"])] = row
    windows.sort(key=lambda row: str(row["group_id"] or ""))
    return windows, sorted(events.values(), key=lambda row: (row["start"], row["end"], row["name"]))


def planner_context(conn, org_id: str, brand_id: str, product_id: str | None, *,
                    campaign: dict | None = None,
                    calendar_groups: list[dict] | None = None) -> dict:
    """Contract P for one sell-way (`product_id`; `None` = brand level). With `campaign`, its
    product list, customer-group pick, end date, cap and adopted budget are used; without one,
    the sell-way alone (the brief, before a campaign exists)."""
    scope = campaign if campaign is not None else {
        "context_json": {"product_ids": [product_id] if product_id else []},
    }
    product_ids = list((scope.get("context_json") or {}).get("product_ids") or [])
    blocks = _product_blocks(conn, org_id, brand_id, product_ids)
    product = _product(blocks, product_id)
    known = product_id if product is not None else None
    customers_text, listed = customer_groups.prompt_groups(conn, org_id, brand_id, scope)
    current = learning_service.current_conditions(conn, org_id, brand_id, known, campaign=campaign)
    source = (scope.get("context_json") or {}).get("next_period_source")
    continuation = None
    if source:
        from app.ads import next_period

        continuation = next_period.planner_source(conn, org_id, brand_id, source, scope)
    raw_learnings = (bi_repo.list_learnings(
        conn, brand_id, limit=_LEARNING_SCAN, source_track="ads", include_expired=True,
    ) if continuation is None else [])
    if continuation is not None:
        raw_learnings = continuation["records"]
        view = continuation["view"]
        items = [row["evidence"] for row in raw_learnings]
        view["evidence_context"] = {
            "schema_version": 1, "revision": continuation["revision"], "scope_product_id": known,
            "items": items, "omitted": 0,
            "eligible_count": sum(bool(i["allowed_uses"]) for i in items),
        }
    else:
        view = coordinate_learning.prompt_view(conn, org_id, brand_id, sell_way_id=known,
                                              current=current, additional_rows=raw_learnings,
                                              context_cap=None)
    view = learning_view.scoped_view(view, known)
    ranked_text, ranked_ids = coordinate_learning.ranked_section(
        conn, org_id, brand_id, scope, view=view, listed=listed,
    )
    full_evidence = view["evidence_context"]
    rows = ads_learnings(conn, brand_id, known, rows=raw_learnings, evidence_context=full_evidence)
    evidence = {**full_evidence, "items": full_evidence["items"][:30],
                "omitted": max(len(full_evidence["items"]) - 30, 0)}
    view["evidence_context"] = evidence
    cap = capacity = None
    if campaign is not None:
        cap = targets.resolve(conn, org_id, brand_id, campaign)["value"]
        daily = budget.daily_of(campaign.get("budget_planned"), _days(campaign))
        capacity = capacity_of(daily, cap)
    basis = prices_basis(blocks)
    # The delivery plan's menu (and the offers it keeps) for the caller's sell-way.
    the_menu = menu(conn, org_id, brand_id, product_id,
                    campaign is None or campaign.get("end_date") is not None)
    carried = (continuation["carried_candidates"] if continuation is not None
               else coordinate_learning.keep_ads(conn, org_id, brand_id, product_id,
                                                 destination=campaign) if campaign else [])
    for item in carried:
        creative = item["creative"]
        reasons = list((item.get("eligibility") or {}).get("reasons") or [])
        if creative is not None:
            checked = workbench.validate_claims(conn, org_id, brand_id, product_id,
                creative["copy_fields"], offer_key=item["ad"].get("offer_key") or "none")
            reasons = [*checked["unsupported_promises"], *checked["forbidden_terms"],
                       *checked["missing_offer"]]
            if any(not str(creative["copy_fields"].get(k) or "").strip()
                   for k in ("headline", "body", "description")):
                reasons.append("原文案欄位不完整")
        else:
            reasons.append("原圖或原文案無法沿用")
        item["eligibility"] = {"state": "blocked" if reasons else "ready", "reasons": reasons}
    calendar_windows, calendar = _calendar_source(campaign or {}, calendar_groups)
    return {
        "product": product,
        "product_ids": product_ids,
        "product_blocks": blocks,
        "prices": basis,
        "forbidden": workbench.forbidden_terms(conn, org_id, brand_id, known),
        "menu": the_menu["rows"],
        "offers": _offers(conn, brand_id, product_id, the_menu["rows"]),
        "customer_groups": listed,
        "customers_text": customers_text,
        "learnings": {"ads": rows, "ranked": view, "evidence_context": evidence},
        "learning_current": current,
        "ranked_text": ranked_text,
        "ranked_ids": ranked_ids,
        "previous": ({"campaign_id": continuation["source_campaigns"][0]["campaign_id"],
                      "name": "、".join(c["name"] for c in continuation["source_campaigns"]),
                      "learning_goals": [], "closed_count": len(continuation["source_campaigns"]),
                      "best": None} if continuation is not None
                     else _previous(conn, org_id, brand_id, known)),
        "continuation": None if continuation is None else {
            k: continuation[k] for k in ("month", "window", "revision", "source_campaigns",
                                         "eligible_learning_refs", "excluded")},
        "cap": cap,
        "capacity": capacity,
        "budget_advice": campaign.get("budget_advice") if campaign else None,
        "carried_candidates": carried,
        "calendar_windows": calendar_windows,
        "calendar_evidence": [{**row, "id": f"{row['start']}:{row['end']}:{row['name']}"}
                              for row in calendar],
        "knowledge_item_ids": (
            [row["product_id"] for row in basis] + [group["id"] for group in listed]
            + [row["id"] for row in rows] + ranked_ids
        ),
    }


def creative_basis(ctx: dict) -> dict:
    """Full comparison inputs, detached from the prepared context and scoped to its sell-way.

    Storage/fingerprints use this full value. Only creative_projection reaches a prompt;
    a changed result beyond the prompt cap must still invalidate a suggestion batch.
    """
    product_id = (ctx.get("product") or {}).get("id")
    results = []
    for campaign in ctx["learnings"]["ranked"].get("campaigns") or []:
        if campaign.get("sell_way_id") != product_id:
            continue
        period = {
            k: campaign.get(k)
            for k in (
                "campaign_id",
                "sell_way_id",
                "currency",
                "start_date",
                "end_date",
                "cap",
            )
        }
        results.extend({**period, **row} for row in campaign.get("rows") or [])
    controls = [
        {
            "ad_id": item["ad"]["id"],
            "role": item.get("role"),
            "customer_group_id": item["ad"].get("customer_group_id"),
            "coordinates": {d: item["ad"].get(f"{d}_key") for d in learning_rank.DIMENSIONS},
            "scene": item["ad"].get("scene"),
            "creative": item.get("creative"),
            "result": item.get("row"),
            "eligibility": item.get("eligibility"),
        }
        for item in ctx.get("carried_candidates") or []
    ]
    return deepcopy(
        {
            "results": results,
            "controls": controls,
            "learnings": learnings_basis(ctx["learnings"]["ads"]),
            "evidence_context": ctx["learnings"].get("evidence_context"),
            "learning_current": ctx.get("learning_current"),
            "learning_min_result_events": triage.MIN_RESULT_EVENTS,
            "calendar": ctx.get("calendar_evidence") or [],
            "calendar_windows": ctx.get("calendar_windows") or [],
            "offers": ctx.get("offers") or [],
            "facts": (ctx.get("product") or {}).get("knowledge") or [],
            "customer_groups": ctx.get("customer_groups") or [],
            "previous_goals": (ctx.get("previous") or {}).get("learning_goals") or [],
        }
    )


def creative_projection(basis: dict, offer_key: str | None) -> dict:
    """Bounded ranked comparisons; preserve original copy/version and sample caveats verbatim."""
    key = offer_key or "none"
    offers = [o for o in basis["offers"] if o["key"] == key] if key != "none" else []
    return deepcopy(
        {
            **{name: basis[name][:cap] for name, cap in _CREATIVE_CAPS.items()},
            "previous_goals": basis["previous_goals"][:6],
            "evidence_context": basis.get("evidence_context"),
            "learning_current": basis.get("learning_current"),
            "learning_min_result_events": basis.get("learning_min_result_events"),
            "selected_offer": {
                "key": key,
                "sentence": offers[0]["sentence"] if offers else None,
                "sentences": [o["sentence"] for o in offers],
                "state": "none" if key == "none" else "registered" if offers else "unavailable",
            },
            "omitted": {
                **{name: max(len(basis[name]) - cap, 0) for name, cap in _CREATIVE_CAPS.items()},
                "previous_goals": max(len(basis["previous_goals"]) - 6, 0),
            },
        }
    )


def quoted_names(ctx: dict) -> list[str]:
    """Every name the context hands the model -- sell-way and knowledge product names, offer
    labels and sentences, customer groups' 「who」, the previous campaign and its best ad, the
    ranking's campaign and ad names -- longest first, so a reply quoting one (「咖啡因 150mg」)
    can be stripped before its prose is checked for a number (F48 Contract S)."""
    names: list = []
    for block in ctx["product_blocks"]:
        names += [k["name"] for k in block["knowledge"]]
        names += [n for way in block["sell_ways"] for n in (way["name"], way["display"])]
    names += [n for offer in ctx["offers"] for n in (offer["label"], offer["sentence"])]
    names += [group.get("who") for group in ctx["customer_groups"]]
    previous = ctx["previous"]
    if previous is not None:
        names += [previous["name"], (previous["best"] or {}).get("ad_name")]
    ranked = ctx["learnings"]["ranked"]
    names += [group.get("who") for group in ranked["groups"]]
    for campaign in ranked["campaigns"]:
        names.append(campaign["campaign_name"])
        names += [row["ad_name"] for row in campaign["rows"]]
        names += [(row["customer_group"] or {}).get("who") for row in campaign["rows"]]
    unique = {str(n).strip() for n in names if n and str(n).strip()}
    return sorted(unique, key=lambda n: (-len(n), n))


def section_text(ctx: dict, which: str) -> str:
    """One prompt block of `ctx`: product／forbidden／offers／customers／learnings／ranked／
    previous／capacity."""
    if which == "product":
        return _product_text(ctx["product_blocks"], bool(ctx["product_ids"]))
    if which == "forbidden":
        if not ctx["forbidden"]:
            return FORBIDDEN_HEADER + "（這個賣法沒有登記不能講的字）"
        return FORBIDDEN_HEADER + "\n" + "\n".join(f"- {term}" for term in ctx["forbidden"])
    if which == "offers":
        if not ctx["offers"]:
            return OFFERS_HEADER + "（這期沒有可用的優惠）"
        return OFFERS_HEADER + "\n" + "\n".join(
            f"- offer={offer['key']}｜{offer['sentence']}" for offer in ctx["offers"]
        )
    if which == "customers":
        return ctx["customers_text"]
    if which == "learnings":
        return learnings_text(ctx["learnings"]["ads"])
    if which == "ranked":
        return ctx["ranked_text"]
    if which == "previous" and ctx.get("continuation"):
        source = ctx["continuation"]
        return "【明確選中的上一期來源】\n" + json.dumps(source, ensure_ascii=False, default=str)
    if which == "previous":
        return _previous_text(ctx["previous"])
    if which == "capacity":
        return CAPACITY_HEADER + "\n" + capacity_line(ctx["capacity"])
    raise ValueError(f"section_unknown: {which}")
