"""Frozen synthetic F53 inputs; no market or subjective acceptance is inferred here."""

import hashlib
import json
from copy import deepcopy
from datetime import date
from pathlib import Path

CASES_SHA256 = "48ada4e752fa4c2e5848b7b986e3af7146c9ede0aa712b7a72460b5d53505339"
ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "docs/drills/drill-12/first-release/cases.json"


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def frozen_cases(path=CASES):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != CASES_SHA256:
        raise ValueError("Frozen semantic input bytes changed; preserve the failed receipt")
    return json.loads(raw)


def current(**changes):
    value = {
        "org_id": "org_f53",
        "brand_id": "brand_A",
        "product_id": "product_A",
        "org_day": "2026-10-08",
        "audience_keys": ["cold"],
        "customer_group_ids": ["A1", "A2"],
        "result_kind": "purchase",
        "currency": "TWD",
        "attribution": "fixed-known-fixture",
        "mode": "real",
        "conditions": {
            "price_version": "price_1",
            "offers": [
                {"key": "shipping", "version": "offer_1", "valid_until": "2026-10-31"},
            ],
            "materials": [{"ad_id": "original", "version": "material_1"}],
            "target_version": "cap_300",
        },
    }
    value.update(changes)
    return value


def observation(identity="august", *, events: int | None = 10, period="P2", direction="support"):
    month = {"P1": "07", "P2": "08", "P3": "09"}[period]
    end = "30" if month == "09" else "31"
    evidence = {
        "schema_version": 1,
        "source_kind": "campaign",
        "source_ref": {
            "campaign_id": identity,
            "ad_id": "original",
            "action_id": None,
            "entity_id": None,
            "trial_id": identity,
        },
        "source_version": "raw_" + identity,
        "provenance": "platform_observation",
        "period": {"start": f"2026-{month}-01", "end": f"2026-{month}-{end}"},
        "scope": {
            "product_id": "product_A",
            "audience_key": "cold",
            "customer_group_id": "A1",
            "claim_key": "buyer_convenience",
            "claim_family": "performance",
            "objective_family": "sales",
            "result_kind": "purchase",
            "currency": "TWD",
            "attribution": "fixed-known-fixture",
        },
        "conditions": {
            "price_version": "price_1",
            "offer_key": "none",
            "offer_version": None,
            "material_version": "material_1",
            "target_version": "cap_300",
            "valid_until": None,
        },
        "sample": {"result_events": events, "sufficient": None},
        "direction": direction,
        "limits": [],
    }
    from app.workbench import encode_learning_scope

    return {
        "id": identity,
        "org_id": "org_f53",
        "brand_id": "brand_A",
        "product_id": "product_A",
        "learning_text": "Synthetic period association",
        "applicability_scope": encode_learning_scope("ads", evidence),
        "needs_revalidation": False,
    }


def changed(source, **changes):
    from app.workbench import encode_learning_scope

    value = deepcopy(source)
    evidence = json.loads(value["applicability_scope"].split("\n@evidence-v1:")[1])
    for key, patch in changes.items():
        evidence[key] = {**evidence[key], **patch} if isinstance(patch, dict) else patch
    value["applicability_scope"] = encode_learning_scope("ads", evidence)
    return value


def qualification_cases():
    """Explicit counterexamples retain raw inputs and evaluated outputs, not pass counts."""
    from app.workbench import qualify_learning_evidence

    reports = []

    def check(name, rows, ctx, predicate, expectation):
        result = qualify_learning_evidence(rows, ctx, min_result_events=10, max_age_days=180)
        if not predicate(result):
            raise AssertionError({"case": name, "expected": expectation, "actual": result})
        reports.append(
            {
                "case": name,
                "raw": rows,
                "current": ctx,
                "expectation": expectation,
                "actual": result,
            }
        )

    july = observation("july", events=2, period="P1")
    aug = observation()
    sep = observation("september", period="P3", direction="contrary")
    check(
        "G1-thin",
        [july],
        current(),
        lambda r: (
            r["items"][0]["independent_count"] == 0
            and "market_support" not in r["items"][0]["allowed_uses"]
        ),
        "thin is not support",
    )
    check(
        "G2-one",
        [july, aug],
        current(),
        lambda r: next(i for i in r["items"] if i["id"] == "august")["independent_count"] == 1,
        "one sufficient trial",
    )
    derivatives = [
        changed({**aug, "id": kind}, source_kind=kind, source_version="revision_" + kind)
        for kind in ("coordinate", "visual", "settle", "ab")
    ]
    check(
        "N03-derivatives",
        [aug, *derivatives],
        current(),
        lambda r: max(i["independent_count"] for i in r["items"]) == 1,
        "derivatives count once",
    )
    replay = changed(
        {**aug, "id": "replay"},
        source_version="new_read",
        period={"start": "2026-08-02", "end": "2026-08-30"},
    )
    overlap = changed(observation("overlap"), period={"start": "2026-08-15", "end": "2026-09-10"})
    check(
        "N03-replay-overlap",
        [aug, replay, overlap],
        current(),
        lambda r: max(i["independent_count"] for i in r["items"]) == 1,
        "replayed or overlapping windows do not count independently",
    )
    check(
        "G3-contrary",
        [aug, sep],
        current(),
        lambda r: (
            next(i for i in r["items"] if i["id"] == "september")["same_direction_count"] == 1
            and next(i for i in r["items"] if i["id"] == "september")["contrary_count"] == 1
        ),
        "contrary resets direction support",
    )
    for field, value in (
        ("product_id", "product_B"),
        ("result_kind", "lead"),
        ("currency", "USD"),
        ("attribution", "other"),
    ):
        other = changed(observation("other"), scope={field: value})
        if field == "product_id":
            other["product_id"] = value
        check(
            "N02-" + field,
            [other],
            current(),
            lambda r: "market_support" not in r["items"][0]["allowed_uses"],
            "incompatible or unknown scope cannot support current product",
        )
    check(
        "N01-unknown-audience",
        [changed(aug, scope={"customer_group_id": None, "audience_key": None})],
        current(),
        lambda r: "market_support" not in r["items"][0]["allowed_uses"],
        "neither retained audience identity is known",
    )
    for field, value in (("org_id", "other_org"), ("brand_id", "brand_B")):
        check(
            "N02-" + field,
            [{**aug, field: value}],
            current(),
            lambda r: "market_support" not in r["items"][0]["allowed_uses"],
            "tenant/brand isolation",
        )
    for events in (None, 0):
        check(
            "N01-sample-" + str(events),
            [observation(events=events)],
            current(),
            lambda r, events=events: (
                r["items"][0]["sample"]["result_events"] == events
                and "market_support" not in r["items"][0]["allowed_uses"]
            ),
            "null and zero stay distinct",
        )
    for provenance in ("simulation", "unknown", "operation_readback"):
        item = changed(aug, provenance=provenance)
        check(
            "C04-" + provenance,
            [item],
            current(),
            lambda r: "market_support" not in r["items"][0]["allowed_uses"],
            "non-market provenance cannot promote",
        )
    old = changed(aug, period={"start": "2025-08-01", "end": "2025-08-31"})
    assert (date.fromisoformat(current()["org_day"]) - date(2025, 8, 31)).days >= 400
    check(
        "R02-400-days",
        [old],
        current(),
        lambda r: r["items"][0]["use_state"] == "revalidation",
        "old needs revalidation",
    )
    for trailer in ("ads", "ads\n@evidence-v1:{broken", 'ads\n@evidence-v1:{"schema_version":999}'):
        check(
            "N05-" + trailer,
            [{**aug, "applicability_scope": trailer}],
            current(),
            lambda r: "market_support" not in r["items"][0]["allowed_uses"],
            "legacy/malformed source remains conservative",
        )
    for field in ("price_version", "material_version", "target_version"):
        check(
            "N06-" + field,
            [changed(aug, conditions={field: "changed"})],
            current(),
            lambda r: "market_support" not in r["items"][0]["allowed_uses"],
            "changed conditions cannot confirm",
        )
    for conditions in (
        {"offer_key": "shipping", "offer_version": "changed"},
        {"offer_key": "shipping", "offer_version": "offer_1", "valid_until": "2026-10-07"},
    ):
        ctx = current()
        if conditions.get("valid_until"):
            ctx["conditions"]["offers"][0]["valid_until"] = conditions["valid_until"]
        check(
            "N06-offer-" + digest(conditions),
            [changed(aug, conditions=conditions)],
            ctx,
            lambda r: "market_support" not in r["items"][0]["allowed_uses"],
            "changed/expired offer cannot confirm",
        )
    check(
        "N07-removed",
        [aug],
        current(customer_group_ids=[]),
        lambda r: "market_support" not in r["items"][0]["allowed_uses"],
        "removed audience does not fallback",
    )
    first = qualify_learning_evidence([aug, sep], current(), min_result_events=10, max_age_days=180)
    reordered = qualify_learning_evidence(
        [sep, aug], current(), min_result_events=10, max_age_days=180
    )
    edited = qualify_learning_evidence(
        [{**aug, "learning_text": "Changed meaning"}, sep],
        current(),
        min_result_events=10,
        max_age_days=180,
    )
    assert first["revision"] == reordered["revision"] != edited["revision"]
    reports.append(
        {
            "case": "D02-N08-revision",
            "raw": [aug, sep],
            "current": current(),
            "original": first,
            "reordered": reordered,
            "edited": edited,
        }
    )
    return reports
