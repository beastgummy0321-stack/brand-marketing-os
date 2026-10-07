"""app/ads/ads_learnings.py — F48 Contract W: `write` is the one door every `learning_ledger` row
from `app/ads` goes through (`bi_repo.record_learning` is called nowhere else in this module tree,
`test_ads_one_ruler.py` enforces it), always with the sell-way it belongs to.

Contract D (F27): the ads-track learning a confirmed `pause` item
carrying an `angle` (Contract C) writes to the brand's learning ledger
(`app.brand_intelligence.repository`, public functions only -- this module never touches
`learning_ledger` directly).

Pre-dispatch correction 8 (2026-09-22, authoritative): the write happens AFTER
`change_control_verify.check` has already committed the item as `confirmed` (`record_learning`
commits its own transaction); idempotency is keyed by an existing learning whose
`source_cycle_id` equals the change ITEM id (`ads_action.id`), never the change SET id -- the
automatic runtime re-check (`app/ads/runtime.py`) calls `check` again on items that are already
`confirmed`, and that second pass must not write a second row.

Promotion (Contract D): confidence is decided by counting earlier `source_track="ads"` learnings
of the brand with the exact same `learning_text` -- 0 earlier -> observed, 1 -> likely, >=2 ->
validated. `list_learnings` has no text filter, so this scans and filters in Python, the same
precedent as `app/ads/visual_learning.py`'s own promotion scan.
"""

import hashlib
import json
from typing import cast

from app import workbench
from app.ads import repository as ads_repo
from app.ads import sell_way
from app.brand_intelligence import repository as bi_repo
from app.core import settings as coresettings
from app.core.db import Conn, ConnProxy

_AnyConn = Conn | ConnProxy

# Generous ceiling for the idempotency/promotion scans below -- same precedent as
# `visual_learning.py`'s `limit=500`; this module's own list endpoint stays at the contract's
# `<=50` (see `list_for_brand`).
_SCAN_LIMIT = 500


def semantic_version(value) -> str:
    """Hash relevant facts, excluding presentation names, labels and read timestamps."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), default=str).encode()).hexdigest()


def _one(values):
    values = set(values)
    return next(iter(values)) if len(values) == 1 and None not in values else None


def condition_snapshot(conn, org, brand, campaign, product_id) -> dict:
    """The conditions known now; only launch freezes can establish historical conditions."""
    from app.ads import targets

    economics = bi_repo.get_product_economics(conn, brand, product_id) if product_id else None
    price = None
    if economics and economics.get("status") == "confirmed":
        price = semantic_version({k: economics.get(k) for k in (
            "selling_price", "list_price", "currency", "effective_from", "effective_to",
            "unit_variable_cost", "shipping_cost",
        )})
    sources = bi_repo.offer_sources(conn, brand, product_id)
    policies = bi_repo.list_brand_policies(conn, brand)
    offers = []
    for key in sorted({s["offer_key"] for s in sources}):
        terms = sorted(s["sentence"] for s in sources if s["offer_key"] == key)
        supporting = [p for p in policies if p["status"] == "confirmed" and p["offer_key"] == key
                      and p["sentence"] in terms]
        ends = [(p.get("params") or {}).get("valid_until")
                or (p.get("params") or {}).get("end_date") for p in supporting]
        offers.append({"key": key, "version": semantic_version({
            "terms": terms, "params": sorted((p.get("params") or {} for p in supporting),
                                              key=lambda p: json.dumps(p, sort_keys=True)),
        }), "valid_until": min((str(e) for e in ends if e), default=None)})
    target = targets.resolve(conn, org, brand, campaign, product_id=product_id)
    target_version = semantic_version({k: target.get(k) for k in ("value", "basis", "result_kind")})
    if target.get("value") is None or target.get("result_kind") is None:
        target_version = None
    return {"price_version": price, "offers": offers, "target_version": target_version}


def material_version(ad, outputs) -> str | None:
    """Actual frozen creative content and placement revision, never selection/read times."""
    parts = {part: {"body_json": row.get("body_json"), "rendered_text": row.get("rendered_text")}
             for part, row in (outputs or {}).items() if isinstance(row, dict)}
    material = ad.get("material_evidence")
    return semantic_version({"parts": parts, "material": material}) if parts or material else None


def bound_material(conn, org, brand, ad) -> dict | None:
    """Content identity survives a carried placement; an unresolved binding stays unknown."""
    from app.ads import asset_binding_repository as binding
    from app.ads import user_assets_repository as assets

    if not ad.get("material_placement_id"):
        return None
    try:
        placement = assets.placement(
            conn, org, brand, ad["campaign_id"], ad["material_placement_id"],
            ad.get("material_placement_revision"),
        )
        asset = assets.get_asset(conn, org, brand, placement["asset_id"])
    except ValueError:
        return None
    return {"sha256": asset["sha256"], "copy": binding.effective_copy(placement)}


def _measurement(observations) -> tuple:
    kind = _one(row.get("result_kind") for row in observations)
    currency = _one(row.get("currency") for row in observations)
    definitions = [(row.get("attribution_key"), row.get("result_action"),
                    row.get("result_attribution")) for row in observations]
    definition = _one(definitions)
    if definition is None or any(v is None for v in definition):
        return None, currency, None
    attribution = json.dumps(dict(zip(("key", "action", "result_attribution"), definition,
                                      strict=True)), sort_keys=True, separators=(",", ":"))
    return kind, currency, attribution


def current_conditions(conn, org, brand, product_id, *, campaign=None) -> dict:
    """Explicit current scope for every ads qualifier; unknown measurement stays unknown."""
    from app.ads import live_creative, outcome, targets

    product = bi_repo.get_product(conn, brand, product_id) if product_id else None
    selected = product_id if product else None
    candidates = []
    if selected:
        candidates = [dict(row) for row in conn.execute(
            "SELECT * FROM ads_campaign WHERE org_id=%s AND brand_id=%s"
            " ORDER BY created_at DESC,id DESC", (org, brand),
        ).fetchall() if sell_way.of_campaign(dict(row)) == selected]
        if campaign is None:
            campaign = candidates[0] if candidates else None
    campaign = campaign or {}
    snapshot = condition_snapshot(conn, org, brand, campaign, selected)
    observations = (outcome.rows(conn, org, brand, campaign["id"], "ad")
                    if campaign.get("id") else [])
    # A new plan has no new outcome yet. Retained actual definitions, matching its explicitly
    # requested kind, can establish the current measurement; origin never supplies a definition.
    if not observations:
        for previous in candidates:
            if targets.effective_result_kind(previous) != targets.effective_result_kind(campaign):
                continue
            retained = outcome.rows(conn, org, brand, previous["id"], "ad")
            if retained:
                observations = retained
                break
    kind, currency, attribution = _measurement(observations)
    if any(r.get("source") != "graph" or not r.get("observation_id") for r in observations):
        kind = attribution = None
    intended = targets.effective_result_kind(campaign) if campaign.get("id") else None
    if kind != intended:
        kind = None
    materials = []
    for source in candidates or ([campaign] if campaign.get("id") else []):
        launched = live_creative.launched_outputs(conn, org, brand, source["id"])
        ads = conn.execute("SELECT * FROM ads_ad"
                           " WHERE org_id=%s AND brand_id=%s AND campaign_id=%s",
                           (org, brand, source["id"])).fetchall()
        materials.extend({"ad_id": ad["id"], "version": material_version(
                         {**ad, "material_evidence": bound_material(conn, org, brand, ad)},
                         (launched.get(ad["id"]) or {}).get("outputs"))} for ad in ads)
    groups = bi_repo.list_customer_groups(conn, brand, selected) if selected else []
    return {"org_id": org, "brand_id": brand, "product_id": selected,
            "org_day": coresettings.today_for_org(conn, org_id=org).isoformat(),
            "audience_keys": [r["key"] for r in ads_repo.coordinate_vocabulary(conn, org, brand)
                              if r["dimension"] == "audience"],
            "customer_group_ids": [g["id"] for g in groups], "result_kind": kind,
            "currency": currency, "attribution": attribution, "mode": "real",
            "conditions": {**snapshot, "materials": materials}}


def source_evidence(conn, org, brand, campaign, *, kind, window, ad=None, observations=None,
                    claim_key=None, direction="inconclusive", action_id=None, entity_id=None,
                    trial_id=None, members=None) -> dict:
    """Extract retained observations and immutable launch conditions without certifying origin."""
    from app.ads import outcome, targets

    product_id = sell_way.of_ad(ad, campaign) if ad else sell_way.of_campaign(campaign)
    if observations is None:
        observations = outcome.rows(conn, org, brand, campaign["id"], "ad")
        if ad:
            observations = [r for r in observations if r["entity_id"] == ad["id"]]
        if window.get("start") and window.get("end"):
            observations = [r for r in observations
                            if str(window["start"]) <= str(r["day"]) <= str(window["end"])]
        else:
            observations = []
    sources = {r.get("source") for r in observations}
    provenance = "unknown"
    if "simulated" in sources:
        provenance = "simulation"
    elif sources == {"graph"} and all(r.get("observation_id") for r in observations):
        provenance = "platform_observation"
    elif sources == {"user_report"}:
        provenance = "user_report"
    measurement, currency, attribution = _measurement(observations)
    if measurement != targets.effective_result_kind(campaign):
        measurement = None
    snapshots = members if members is not None else [ad] if ad else [
        a for g in campaign.get("groups", []) for a in g.get("ads", [])
    ]
    freezes = [a.get("live_creative_json") or {} for a in snapshots]
    conditions = [f.get("evidence_conditions") or {} for f in freezes]
    offer_key = _one(a.get("offer_key") for a in snapshots)
    frozen = {key: _one(c.get(key) for c in conditions)
              for key in ("price_version", "target_version")}
    offer_versions = []
    for c in conditions:
        offer = next((o for o in c.get("offers", []) if o["key"] == offer_key), {})
        offer_versions.append(offer)
    price_conditions = {**frozen, "offer_key": offer_key,
                        "offer_version": _one(o.get("version") for o in offer_versions),
                        "valid_until": _one(o.get("valid_until") for o in offer_versions),
                        "material_version": (conditions[0].get("material_version")
                                             or material_version(ad, freezes[0].get("outputs")))
                        if ad and freezes else None}
    audience = _one(a.get("audience_key") for a in snapshots)
    group = _one(a.get("customer_group_id") for a in snapshots)
    known_events = [r.get("result_count") for r in observations]
    events = sum(float(v) for v in known_events) if known_events and all(
        v is not None for v in known_events) else None
    facts = [{key: r.get(key) for key in ("observation_id", "entity_id", "day", "source", "spend",
             "result_kind", "result_count", "currency", "attribution_key", "result_action",
             "result_attribution")} for r in observations]
    facts.sort(key=lambda r: json.dumps(r, sort_keys=True, default=str))
    limits = []
    if not conditions or any(not c.get("price_version") or not c.get("target_version")
                             for c in conditions) or not audience or not claim_key:
        limits.append("conditions_unknown")
    if measurement is None or attribution is None:
        limits.append("measurement_definition_unknown")
    if not facts:
        limits.append("unknown_source")
    return {"schema_version": 1, "source_kind": kind,
            "source_ref": {"campaign_id": campaign.get("id"), "ad_id": ad.get("id") if ad else None,
                           "action_id": action_id, "entity_id": entity_id,
                           "trial_id": trial_id or campaign.get("id")},
            "source_version": semantic_version({"observations": facts,
                                                "conditions": price_conditions}) if facts else None,
            "provenance": provenance,
            "period": {key: str(window[key]) if window.get(key) else None
                       for key in ("start", "end")},
            "scope": {"product_id": product_id, "audience_key": audience,
                      "customer_group_id": group,
                      "claim_key": claim_key, "claim_family": "performance",
                      "objective_family": ads_repo.campaign_objective_family(
                          conn, org, brand, campaign),
                      "result_kind": measurement, "currency": currency, "attribution": attribution},
            "conditions": price_conditions, "sample": {"result_events": events, "sufficient": None},
            "direction": direction, "limits": limits}


def evidence_context(conn: _AnyConn, org: str, brand: str, product_id: str | None,
                     *, rows: list[dict] | None = None, cap: int = 30,
                     current: dict | None = None) -> dict:
    """Conservative read projection; missing retained source conditions stay explicit unknowns."""
    from app.ads.triage import MIN_RESULT_EVENTS

    product = bi_repo.get_product(cast(Conn, conn), brand, product_id) if product_id else None
    selected = product_id if product else None
    if current is None:
        current = current_conditions(conn, org, brand, selected)
    if rows is None:
        rows = bi_repo.list_learnings(cast(Conn, conn), brand, limit=_SCAN_LIMIT)
    projected = workbench.qualify_learning_evidence(
        rows, current, min_result_events=MIN_RESULT_EVENTS, max_age_days=180,
    )
    return {"schema_version": 1, "revision": projected["revision"],
            "scope_product_id": selected, "scope_label": product["name"] if product else None,
            "eligible_count": projected["eligible_count"], "items": projected["items"][:cap],
            "omitted": max(len(projected["items"]) - cap, 0)}


def write(conn: _AnyConn, org_id: str, brand_id: str, *, product_id: str | None, text: str,
          scope: str, confidence: str, sample_size: str, source_cycle_id: str | None,
          source_track: str, needs_revalidation: bool = False, platform: str | None = None,
          actor: str = "system", evidence: dict | None = None) -> dict:
    """F48 Contract W: write one learning-ledger row and return it. `product_id` is required: the
    sell-way the learning belongs to (`sell_way.of_campaign`／`of_ad`／`of_campaign_id`); pass
    `None` explicitly only for a campaign that has no sell-way (an imported campaign) -- that row
    is read as brand level. `org_id` names the caller's tenant; the ledger derives the org from
    the brand itself."""
    evidence = evidence or {"scope": {"product_id": product_id}, "limits": ["unknown_source"]}
    scope = workbench.encode_learning_scope(scope, evidence)
    campaign_id = (evidence.get("source_ref") or {}).get("campaign_id")
    campaign = ads_repo.get_campaign(cast(Conn, conn), org_id, brand_id, campaign_id) \
        if campaign_id else None
    current = current_conditions(conn, org_id, brand_id, product_id, campaign=campaign)
    candidate = {"id": "pending", "org_id": org_id, "brand_id": brand_id,
                 "product_id": product_id, "learning_text": text, "applicability_scope": scope,
                 "needs_revalidation": needs_revalidation}
    rows = bi_repo.list_learnings(cast(Conn, conn), brand_id, limit=_SCAN_LIMIT)
    projected = evidence_context(conn, org_id, brand_id, product_id,
                                 rows=[*rows, candidate], cap=_SCAN_LIMIT + 1, current=current)
    item = next(i for i in projected["items"] if i["id"] == "pending")
    count = item["same_direction_count"] if item["use_state"] == "usable" else 0
    confidence = _confidence_for_count(max(count - 1, 0))
    return bi_repo.record_learning(
        cast(Conn, conn), brand_id, actor=actor, learning_text=text,
        applicability_scope=scope, confidence=confidence, sample_size=sample_size,
        source_cycle_id=source_cycle_id, product_id=product_id, platform=platform,
        needs_revalidation=needs_revalidation, source_track=source_track,
    )


def _text(angle: str) -> str:
    return f"已暫停「{angle}」，操作已核對；成效原因未知"


def stored_evidence(row: dict) -> dict:
    """Read structured retained metadata; legacy text is never promoted into provenance."""
    try:
        value = json.loads((row.get("applicability_scope") or "").split("\n@evidence-v1:", 1)[1])
    except (ValueError, IndexError, TypeError):
        return {}
    return value if isinstance(value, dict) and type(value.get("schema_version")) is int \
        and value["schema_version"] == 1 else {}


def message_claim(ad: dict) -> str | None:
    """Message coordinates describe a claim; a name or free-form label cannot establish it."""
    if not ad.get("angle_key"):
        return None
    return "message:" + semantic_version({k: ad.get(k) for k in (
        "angle_key", "pain_key", "hook_key", "proof_key",
    )})


def _confidence_for_count(count: int) -> str:
    if count >= 2:
        return "validated"
    if count >= 1:
        return "likely"
    return "observed"


def _ads_rows(conn: _AnyConn, brand: str) -> list[dict]:
    return bi_repo.list_learnings(cast(Conn, conn), brand, source_track="ads", limit=_SCAN_LIMIT)


def view_for_item(conn: _AnyConn, brand: str, item_id: str,
                  *, product_id: str | None = None) -> dict:
    """Contract D: the set item view's `learning` field. Read-time lookup (never stored on the
    item itself) so a later promotion of another item's identical text never has to reach back
    and rewrite this one."""
    rows = _ads_rows(conn, brand)
    mine = next((row for row in rows if row["source_cycle_id"] == item_id), None)
    if mine is None:
        return {"recorded": False, "confidence": None, "count": 0, "evidence": None}
    count = sum(
        1 for row in rows
        if row["learning_text"] == mine["learning_text"] and row["learned_at"] <= mine["learned_at"]
    )
    context = evidence_context(conn, mine["org_id"], brand, product_id, rows=rows, cap=_SCAN_LIMIT)
    evidence = next(item for item in context["items"] if item["id"] == mine["id"])
    return {"recorded": True, "confidence": mine["confidence"], "count": count,
            "evidence": evidence}


def record_for_item(conn: _AnyConn, org: str, brand: str, campaign: str, set_id: str,
                     item: dict) -> dict | None:
    """Contract D + correction 8: call only once `check` has already committed `item` as
    `confirmed`. `item` is the item view returned by `change_control.item`/`change_control_data
    .get` (carries `kind`, `angle`, and `id` -- the change ITEM id, never the change SET id).
    A no-op (returns `None`) for anything but a `pause` item that carries an `angle`, or when a
    learning for this exact item was already recorded (idempotent against the automatic runtime
    re-check in `app/ads/runtime.py`, which calls `check` again on items already `confirmed`)."""
    angle = item.get("angle")
    if item.get("kind") != "pause" or not angle:
        return None
    item_id = item["id"]
    rows = _ads_rows(conn, brand)
    if any(row["source_cycle_id"] == item_id for row in rows):
        return None
    text = _text(angle)
    receipt = item.get("evidence_json") or {}
    confirmed = receipt.get("setting_matches") is True
    metadata = {"source_kind": "pause", "source_ref": {
        "campaign_id": campaign, "action_id": item_id, "entity_id": item.get("target_id"),
        "trial_id": item_id,
    }, "source_version": semantic_version({"target": item.get("target_id"),
                                           "after": item.get("after"), "setting_matches": True})
       if confirmed else None, "provenance": "operation_readback" if confirmed else "unknown",
       "scope": {"product_id": sell_way.of_campaign_id(conn, org, brand, campaign),
                 "claim_family": "operation", "claim_key": "pause"},
       "direction": "inconclusive", "limits": ["operation_only"]}
    return write(
        conn, org, brand, product_id=sell_way.of_campaign_id(conn, org, brand, campaign),
        text=text, scope=f"ads;campaign={campaign}", confidence="observed", evidence=metadata,
        sample_size="1", source_cycle_id=item_id, source_track="ads",
    )


def ab_text(ab: dict) -> str:
    """F29-I04 Contract F: the learning an A/B set's confirmed pause writes -- no numbers, so the
    same conclusion reached twice promotes confidence (Contract D)."""
    return (
        f"「{ab['dimension_label']}」用「{ab['winner']['value_label']}」"
        f"比「{ab['loser']['value_label']}」划算"
    )


def record_for_ab_item(conn: _AnyConn, org: str, brand: str, campaign: str, change_set: dict,
                       item: dict) -> dict | None:
    """F29-I04 Contract F, same rules as `record_for_item`: call only once `check` has already
    committed `item` as `confirmed`; idempotent per change ITEM id (the runtime re-check calls
    `check` again). A no-op for anything but the `pause` item of a `source: "ab"` set."""
    plan = change_set.get("plan_json") or {}
    ab = plan.get("ab")
    if plan.get("source") != "ab" or not ab or item.get("kind") != "pause":
        return None
    item_id = item["id"]
    rows = _ads_rows(conn, brand)
    if any(row["source_cycle_id"] == item_id for row in rows):
        return None
    text = ab_text(ab)
    metadata = ab.get("evidence") or {"source_kind": "ab", "limits": ["unknown_source"]}
    metadata = {**metadata, "source_ref": {**(metadata.get("source_ref") or {}),
                                          "campaign_id": campaign, "action_id": item_id}}
    return write(
        conn, org, brand, product_id=sell_way.of_campaign_id(conn, org, brand, campaign),
        text=text, scope=f"ads;campaign={campaign}", confidence="observed", evidence=metadata,
        sample_size="1", source_cycle_id=item_id, source_track="ads",
    )


# F29-I03 Contract E: a period-settle learning's `source_cycle_id` is `settle:<month>:<entity_id>`
# (`app/ads/settle.py`), naming the ad entity instead of a change item.
_SETTLE_PREFIX = "settle:"


def _campaign_of_source(conn: _AnyConn, org: str, brand: str, source_cycle_id: str | None):
    """The campaign a learning came from: a settle learning through its ad entity, every other one
    through the change item (`ads_action`) its `source_cycle_id` names. `None` when unknown."""
    if not source_cycle_id:
        return None
    if source_cycle_id.startswith(_SETTLE_PREFIX):
        entity_id = source_cycle_id.rsplit(":", 1)[-1]
        row = conn.execute(
            "SELECT campaign_id FROM ads_external_entity WHERE org_id=%s AND brand_id=%s AND id=%s",
            (org, brand, entity_id),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT campaign_id FROM ads_action WHERE org_id=%s AND brand_id=%s AND id=%s",
            (org, brand, source_cycle_id),
        ).fetchone()
    return row["campaign_id"] if row else None


def list_for_brand(conn: _AnyConn, brand: str, *, product_id: str | None = None) -> list[dict]:
    """Contract D: `GET .../learnings` -- ads-track rows only, newest first, <=50 (the ledger's
    own default). Each row's `campaign_id`/`campaign_name` is looked up through this module's own
    `ads_action` table (keyed by `source_cycle_id` = the change item id) -- `learning_ledger`
    itself carries no campaign column, and this module never adds one to the legacy table.
    `campaign_objective` (F27-I27) reuses `repository.campaign_objective_family` -- `null` only
    when the campaign itself is unknown/deleted, never a frontend-side guess off the raw
    objective string."""
    rows = _ads_rows(conn, brand)
    evidence = {item["id"]: item for item in evidence_context(
        conn, rows[0]["org_id"], brand, product_id, rows=rows, cap=_SCAN_LIMIT,
    )["items"]} if rows else {}
    result = []
    for row in rows[:50]:
        campaign_id = _campaign_of_source(conn, row["org_id"], brand, row["source_cycle_id"])
        campaign_name = None
        campaign_objective = None
        if campaign_id:
            campaign = ads_repo.get_campaign(cast(Conn, conn), row["org_id"], brand, campaign_id)
            if campaign is not None:
                campaign_name = campaign["name"]
                # F27-I27: the same `campaign_objective_family` rule the month summary and
                # `CampaignChip` elsewhere already use -- never a second, frontend-side guess
                # off the raw `objective` string.
                campaign_objective = ads_repo.campaign_objective_family(
                    cast(Conn, conn), row["org_id"], brand, campaign,
                )
        count = sum(
            1 for other in rows
            if other["learning_text"] == row["learning_text"]
            and other["learned_at"] <= row["learned_at"]
        )
        result.append({
            "id": row["id"],
            "text": row["learning_text"],
            "confidence": row["confidence"],
            "count": count,
            "campaign_id": campaign_id,
            "campaign_name": campaign_name,
            "campaign_objective": campaign_objective,
            "learned_at": row["learned_at"],
            "evidence": evidence[row["id"]],
        })
    return result
