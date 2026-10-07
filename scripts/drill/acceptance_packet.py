"""Freeze a bounded independent-acceptance packet; never run or grade a drill.

CLI: python -m scripts.drill.acceptance_packet INPUT --source-root SOURCES
     --fresh-root RUN_ROOT --output NEW_DIRECTORY

Input schema acceptance-packet-v1 names comparison_side/product_side, head/run_id,
sources [{id,path,bytes,sha256}], context reference IDs (facts/persona/calendar/
fit_rubric/aggregate_rubric), periods [{side,period,plan,fit,copy,reasoning,
prior_creatives,requested_budget,requested_ad_count}], and variants [{side,period,
date_mode:actual|aligned,audience_mode:ad|group,plan,rows,priors}]. Three periods
and all four variants are required per side. Missing references remain gaps.
Prepare first without fit/results/scores to freeze single-plan fit inputs; later
prepare a different fresh directory with independently supplied records. These
files do not establish that a third party respected its role or the required
freeze-before-judge sequence. Preserve those independent receipts separately.
Controls are append-only route/state/action events; previous_controls may name a
previous verified ledger reference. Evidence layers name {ref,status,head,run_id}.
Subjective score files, if supplied, use dimensions plus optional exact total/mean.

Raw originals live only in private/raw. Public fit files contain one masked plan,
facts/rubric and all same-side prior creatives, without fit scores or simulator
outputs. Public aggregate packaging is separate. Masking changes display names
only; raw simulator seeds, fit keys, copy and score bytes remain immutable.
The private mapping is not a simulator input. Directory separation is not an OS
access-control guarantee; operators must distribute only the intended public file.
"""

import argparse
import copy
import hashlib
import json
import re
import secrets
from datetime import date, timedelta
from decimal import Decimal, localcontext
from pathlib import Path


class PacketError(ValueError):
    """Invalid provenance or contradictory packet input, with a stable reason code."""


C_PARTIAL_LINES = (
    355,
    356,
    357,
    358,
    370,
    371,
    372,
    380,
    381,
    382,
    383,
    384,
    389,
    390,
    391,
    407,
    408,
    417,
    418,
    419,
    420,
    422,
    445,
)
REQUIRED_CONTROLS = (
    "A216",
    "A247",
    "A248",
    "A349",
    "A420",
    "A421",
    "A561",
    "A017",
    "A233",
    "A234",
    "A453",
    "A454",
    "B-empty-fill",
    "B-explicit-zero-protection",
    "B-suggestion-continue",
    "B-suggestion-discard",
    "B-copy-fixed5",
    "B-script1",
    "B-script2",
    "B-plain-select",
    "B-plain-deselect",
    "B-warning-back",
    "B-warning-confirm",
    "B-clipboard-bytes",
    "B-reference-upload",
    "B-raster-output",
    "B-image-job-identity",
    "C-date-helpers",
    "C-upload-download",
    "C-monthly-csv",
    "C-candidate-alternatives",
    "C-source-alternatives",
    "C-placement-alternatives",
    "C-change-history",
    "C-exits",
    "C-cleanup-eligible",
    "C-settlement-eligible",
    "C-legacy-redirect",
    "C-platform-guess",
    "C-blank-batches",
) + tuple(f"C-partial-{line}" for line in C_PARTIAL_LINES)
REQUIRED_LAYERS = (
    "head_environment",
    "targeted_red_green",
    "independent_money_tenant_review",
    "full_integration",
    "api_db_reconciliation",
    "reference_built_ui",
    "normalized_controls",
    "fault_screenshots",
    "three_period_persona",
    "raw_fit",
    "independent_verdict",
    "simulation_aggregates",
    "unresolved_excluded",
    "owned_cleanup",
    "human_approval",
)
LIMITATIONS = [
    "Raw bytes, side/period/ad-name seeds and original fit keys remain unchanged in private/raw.",
    "Exact copy, reasons, dates, budgets and source content may reveal identity; "
    "masking is partial.",
    "Absent legacy fields remain absent/null; simulator defaults are not invented here.",
    "Actual/aligned dates and ad/group audiences do not equalize spend, budgets "
    "or creative counts.",
    "Historical PASS is not a current PASS. Packet generation never certifies product quality.",
]


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _json(data):
    return json.loads(data, parse_float=Decimal)


def _dump(value):
    return json.dumps(value, ensure_ascii=False, indent=2, default=str).encode("utf-8")


def _number(value):
    try:
        number = Decimal(str(value))
    except Exception as exc:
        raise PacketError("invalid_number") from exc
    if not number.is_finite():
        raise PacketError("nonfinite")
    if (
        isinstance(value, bool)
        or len(number.as_tuple().digits) > 100
        or abs(number.adjusted()) > 100
    ):
        raise PacketError("invalid_number")
    return number


def simulation_totals(rows):
    """Sum raw records before division; compare the unchanged CPA band exactly."""
    with localcontext() as context:
        context.prec = 220
        spend = purchases = revenue = Decimal(0)
        for row in rows:
            values = [_number(row[key]) for key in ("spend", "purchases", "revenue")]
            if min(values) < 0 or values[1] != values[1].to_integral_value():
                raise PacketError("invalid_simulation_row")
            spend += values[0]
            purchases += values[1]
            revenue += values[2]
        return {
            "spend": str(spend),
            "purchases": str(purchases),
            "revenue": str(revenue),
            "cpa": str(spend / purchases) if purchases else None,
            "threshold_met": spend <= Decimal(559) * purchases if purchases else False,
            "ratio_basis": "raw sum(spend)/sum(purchases); not rounded display CPA",
        }


def fit_summary(records):
    with localcontext() as context:
        context.prec = 220
        values = [_number(row["fit"]) for row in records if row.get("fit") is not None]
        if any(not Decimal("0.6") <= value <= Decimal("1.4") for value in values):
            raise PacketError("fit_range")
        complete = len(values) == len(records) and bool(values)
        total = sum(values, Decimal(0))
        return {
            "mean": str(total / len(values)) if complete else None,
            "count": len(values),
            "missing": len(records) - len(values),
            "threshold_met": total >= Decimal("1.15") * len(values) if complete else None,
        }


def validate_scores(raw):
    """Validate independently supplied arithmetic, never choose subjective grades."""
    with localcontext() as context:
        context.prec = 220
        dimensions = raw.get("dimensions", {})
        if any(str(key) not in {str(i) for i in range(1, 10)} for key in dimensions):
            raise PacketError("score_dimensions")
        values = [_number(value) for value in dimensions.values()]
        if any(not 0 <= value <= 10 for value in values):
            raise PacketError("score_range")
        total = sum(values, Decimal(0))
        if raw.get("total") is not None and _number(raw["total"]) != total:
            raise PacketError("score_arithmetic")
        if raw.get("mean") is not None and (
            not values or _number(raw["mean"]) * len(values) != total
        ):
            raise PacketError("score_arithmetic")
        return {
            "dimensions": dimensions,
            "total": str(total),
            "mean": str(total / len(values)) if values else None,
            "missing_dimensions": [str(i) for i in range(1, 10) if str(i) not in dimensions],
        }


def control_coverage(events, *, run_id, head, previous=None, inventory_complete=False):
    """Append attempts to semantic keys, retaining historical and excluded observations."""
    rows, event_ids = {}, {}
    prior_events = [event for row in (previous or {}).get("rows", []) for event in row["events"]]
    for event in [*prior_events, *events]:
        key = tuple(event.get(field) for field in ("route", "state", "action"))
        if not all(isinstance(value, str) and value.strip() for value in key):
            raise PacketError("semantic_key_missing")
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise PacketError("event_id_missing")
        if event_id in event_ids:
            if event_ids[event_id] != event:
                raise PacketError("event_id_conflict")
            continue
        event_ids[event_id] = copy.deepcopy(event)
        verdict = event.get("verdict")
        if verdict not in {
            "pass",
            "fail",
            "unknown",
            "untested",
            "partial",
            "inapplicable",
            "unsupported",
        }:
            raise PacketError("control_verdict")
        if verdict in {"inapplicable", "unsupported"} and not event.get("exclusion_reason"):
            raise PacketError("exclusion_reason")
        identity = "control-" + _sha(_dump(key))[:20]
        if identity not in rows:
            rows[identity] = {
                "id": identity,
                "route": key[0],
                "state": key[1],
                "action": key[2],
                "prerequisite": event.get("prerequisite"),
                "expected": event.get("expected"),
                "events": [],
                "obligations": [],
                "verdict": "unknown",
            }
        row = rows[identity]
        if any(row[field] != event.get(field) for field in ("prerequisite", "expected")):
            raise PacketError("semantic_key_conflict")
        row["events"].append(copy.deepcopy(event))
        row["obligations"] = list(
            dict.fromkeys([*row["obligations"], *event.get("obligations", [])])
        )
        # Built-in IDs are distinct required branches, not human label aliases.
        if len(set(row["obligations"]) & set(REQUIRED_CONTROLS)) > 1:
            raise PacketError("obligation_mapping")
        fresh = (
            event.get("scope") == "fresh"
            and event.get("run_id") == run_id
            and event.get("head") == head
        )
        if fresh:
            if verdict == "pass" and (
                not event.get("evidence") or not row["prerequisite"] or not row["expected"]
            ):
                raise PacketError("control_evidence")
            row["verdict"] = verdict
            row["exclusion_reason"] = event.get("exclusion_reason")
    mapped = {key for row in rows.values() for key in row["obligations"]}
    resolved = {
        key
        for key in mapped
        if all(
            row["verdict"] in {"pass", "inapplicable", "unsupported"}
            for row in rows.values()
            if key in row["obligations"]
        )
    }
    gaps = [key for key in REQUIRED_CONTROLS if key not in resolved]
    placeholders = [
        {
            "id": "required-" + key,
            "route": None,
            "state": "required_gap",
            "action": key,
            "events": [],
            "verdict": "unknown",
            "obligations": [key],
            "prerequisite": None,
            "expected": None,
        }
        for key in REQUIRED_CONTROLS
        if key not in mapped
    ]
    all_rows = [*rows.values(), *placeholders]
    exclusions = [row for row in all_rows if row["verdict"] in {"inapplicable", "unsupported"}]
    applicable = [row for row in all_rows if row not in exclusions]
    passed = sum(row["verdict"] == "pass" for row in applicable)
    complete = (
        bool(inventory_complete)
        and not gaps
        and all(row["prerequisite"] and row["expected"] for row in applicable)
    )
    return {
        "rows": all_rows,
        "exclusions": exclusions,
        "denominator": len(applicable),
        "passed": passed,
        "required_gaps": gaps,
        "complete": complete,
        "pass_rate": str(Decimal(passed) / len(applicable)) if applicable else None,
        "acceptance_95": complete and bool(applicable) and passed * 100 >= len(applicable) * 95,
    }


def _sources(spec, source_root):
    result = {}
    folded_ids = set()
    for row in spec.get("sources", []):
        identity = row["id"]
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", identity) or identity.casefold() in folded_ids:
            raise PacketError("source_id")
        folded_ids.add(identity.casefold())
        path = (source_root / row["path"]).resolve()
        if not path.is_relative_to(source_root) or not path.is_file():
            raise PacketError("source_boundary")
        data = path.read_bytes()
        if len(data) != row["bytes"] or _sha(data) != row["sha256"].lower():
            raise PacketError("source_integrity")
        result[identity] = (row, data)
    return result


def prepare_packet(input_file, *, source_root, fresh_root, output):
    source_root, fresh_root, output = map(
        lambda path: Path(path).resolve(), (source_root, fresh_root, output)
    )
    forbidden = {"drill12", "drill-12"}
    if (
        output == fresh_root
        or not output.is_relative_to(fresh_root)
        or forbidden & {part.lower() for part in output.parts}
    ):
        raise PacketError("output_boundary")
    if output.exists():
        raise PacketError("output_exists")
    if not Path(input_file).resolve().is_relative_to(source_root):
        raise PacketError("source_boundary")
    input_bytes = Path(input_file).read_bytes()
    spec = _json(input_bytes)
    if (
        spec.get("schema") != "acceptance-packet-v1"
        or not spec.get("head")
        or not spec.get("run_id")
    ):
        raise PacketError("input_context")
    sides = [spec["comparison_side"], spec["product_side"]]
    if len(set(sides)) != 2 or not all(isinstance(side, str) and side for side in sides):
        raise PacketError("side_identity")
    sources = _sources(spec, source_root)
    missing = []

    def raw(identity, layer):
        if identity is None:
            missing.append({"layer": layer, "reason": "not_supplied"})
            return None
        if identity not in sources:
            raise PacketError("source_reference")
        return sources[identity][1]

    def parsed(identity, layer):
        data = raw(identity, layer)
        return _json(data) if data is not None else None

    def material(identity, layer):
        data = raw(identity, layer)
        if data is None:
            return None
        try:
            return _json(data)
        except json.JSONDecodeError:
            return data.decode("utf-8-sig")

    context = {
        key: material(spec.get("context", {}).get(key), key)
        for key in ("facts", "persona", "calendar", "fit_rubric", "aggregate_rubric")
    }
    previous = (
        parsed(spec.get("previous_controls"), "previous_controls")
        if spec.get("previous_controls")
        else None
    )
    previous_events = [event for row in (previous or {}).get("rows", []) for event in row["events"]]
    for event in [*previous_events, *spec.get("controls", [])]:
        for identity in event.get("evidence", []):
            raw(identity, "control_evidence")
    controls = control_coverage(
        spec.get("controls", []),
        run_id=spec["run_id"],
        head=spec["head"],
        previous=previous,
        inventory_complete=spec.get("inventory_complete", False),
    )
    missing.extend({"layer": "control", "reason": key} for key in controls["required_gaps"])
    aliases = sides[:]
    secrets.SystemRandom().shuffle(aliases)
    side_alias = {side: f"Candidate-{i + 1}" for i, side in enumerate(aliases)}
    mapping = {"sides": {alias: side for side, alias in side_alias.items()}, "ads": []}
    periods, variants, fit_packets, public_plans, product_fits = {}, {}, {}, [], []

    def masked(plan):
        result = copy.deepcopy(plan)
        result["side"] = side_alias[plan["side"]]
        for gi, group in enumerate(result.get("groups", []), 1):
            group["name"] = f"Group-{gi}"
            for ai, ad in enumerate(group.get("ads", []), 1):
                original = ad["name"]
                ad["name"] = f"Ad-{gi}-{ai}"
                entry = {
                    "candidate": result["side"],
                    "period": plan["period"],
                    "display_ad": ad["name"],
                    "original_side": plan["side"],
                    "original_ad_name": original,
                    "original_fit_key": original,
                }
                if entry not in mapping["ads"]:
                    mapping["ads"].append(entry)
        return result

    for entry in sorted(spec.get("periods", []), key=lambda row: (row["side"], row["period"])):
        key = (entry["side"], entry["period"])
        if key in periods or key[0] not in sides or key[1] not in (1, 2, 3):
            raise PacketError("period_identity")
        plan = parsed(entry.get("plan"), "plan")
        if plan is None:
            continue
        if (plan["side"], plan["period"]) != key:
            raise PacketError("plan_identity")
        names = [ad["name"] for group in plan["groups"] for ad in group.get("ads", [])]
        if len(set(names)) != len(names):
            raise PacketError("fit_keys_ambiguous")
        fit = parsed(entry.get("fit"), "raw_fit")
        if fit is not None and set(fit.get("ads", {})) != set(names):
            raise PacketError("fit_keys")
        fit_values = [fit["ads"][name] for name in names] if fit else []
        fit_stats = fit_summary(fit_values)
        if key[0] == spec["product_side"]:
            product_fits.extend(fit_values)
        reasoning = material(entry.get("reasoning"), "reasoning")
        adopted_copy = material(entry.get("copy"), "adopted_copy")
        prior_ids = entry.get("prior_creatives", [])
        if len(prior_ids) != key[1] - 1:
            raise PacketError("creative_prior_chain")
        prior_plans = [parsed(identity, "prior_creative") for identity in prior_ids]
        if any(
            prior is None or (prior.get("side"), prior.get("period")) != (key[0], p)
            for p, prior in enumerate(prior_plans, 1)
        ):
            raise PacketError("creative_prior_chain")
        if any(
            (key[0], p) in periods and periods[(key[0], p)]["plan_id"] != identity
            for p, identity in enumerate(prior_ids, 1)
        ):
            raise PacketError("creative_prior_chain")
        public_plan = masked(plan)
        fit_packets[f"{side_alias[key[0]]}-period-{key[1]}"] = {
            "candidate": side_alias[key[0]],
            "period": key[1],
            "plan": public_plan,
            "facts": context["facts"],
            "persona": context["persona"],
            "calendar": context["calendar"],
            "rubric": context["fit_rubric"],
            "prior_creatives": [masked(prior) for prior in prior_plans],
            "limitations": LIMITATIONS,
        }
        public_plans.append(
            {
                "candidate": side_alias[key[0]],
                "period": key[1],
                "plan": public_plan,
                "reasoning": reasoning,
                "adopted_copy": adopted_copy,
                "fit": fit_stats,
                "fit_records": {
                    ad["name"]: value
                    for ad, value in zip(
                        [ad for group in public_plan["groups"] for ad in group.get("ads", [])],
                        fit_values,
                        strict=bool(fit),
                    )
                },
                "requested_budget": entry.get("requested_budget"),
                "used_budget": entry.get("used_budget"),
                "requested_ad_count": entry.get("requested_ad_count"),
                "used_ad_count": entry.get("used_ad_count"),
                "plan_ad_count": len(names),
            }
        )
        periods[key] = {
            "side": key[0],
            "period": key[1],
            "plan_id": entry["plan"],
            "plan": plan,
            "requested_budget": entry.get("requested_budget"),
            "used_budget": entry.get("used_budget"),
            "requested_ad_count": entry.get("requested_ad_count"),
            "used_ad_count": entry.get("used_ad_count"),
            "plan_ad_count": len(names),
        }
    for side in sides:
        for period in (1, 2, 3):
            if (side, period) not in periods:
                missing.append({"layer": "period", "side": side, "period": period})
    seen_variants = set()
    for entry in sorted(
        spec.get("variants", []),
        key=lambda row: (row["side"], row["period"], row["date_mode"], row["audience_mode"]),
    ):
        key = (entry["side"], entry["period"], entry["date_mode"], entry["audience_mode"])
        if (
            key in seen_variants
            or key[0] not in sides
            or key[1] not in (1, 2, 3)
            or key[2] not in {"actual", "aligned"}
            or key[3] not in {"ad", "group"}
        ):
            raise PacketError("variant_identity")
        seen_variants.add(key)
        if key[:2] not in periods:
            missing.append(
                {
                    "layer": "variant",
                    "reason": "missing_period_plan",
                    "side": key[0],
                    "period": key[1],
                }
            )
            continue
        plan = parsed(entry.get("plan"), "variant_plan")
        rows = parsed(entry.get("rows"), "variant_rows")
        if plan is None or rows is None:
            continue
        original = periods[key[:2]]["plan"]
        if {k: v for k, v in plan.items() if k not in {"start_date", "end_date"}} != {
            k: v for k, v in original.items() if k not in {"start_date", "end_date"}
        }:
            raise PacketError("variant_seed_identity")
        if key[2] == "actual" and plan != original:
            raise PacketError("actual_plan_changed")
        names = {ad["name"] for group in plan["groups"] for ad in group.get("ads", [])}
        try:
            start = date.fromisoformat(plan["start_date"])
            end = date.fromisoformat(plan["end_date"])
            if start.isoformat() != plan["start_date"] or end.isoformat() != plan["end_date"]:
                raise ValueError("noncanonical date")
        except (ValueError, TypeError) as exc:
            raise PacketError("variant_window") from exc
        if end < start:
            raise PacketError("variant_window")
        if not isinstance(rows, list) or any(
            (row.get("side"), row.get("period")) != key[:2]
            or row.get("ad_name") not in names
            or not plan["start_date"] <= row.get("date", "") <= plan["end_date"]
            for row in rows
        ):
            raise PacketError("row_identity")
        try:
            if any(date.fromisoformat(row["date"]).isoformat() != row["date"] for row in rows):
                raise ValueError("noncanonical date")
        except (ValueError, TypeError) as exc:
            raise PacketError("row_identity") from exc
        identities = [(row["ad_name"], row["date"]) for row in rows]
        if len(set(identities)) != len(identities) or len(identities) != len(names) * (
            (end - start).days + 1
        ):
            raise PacketError("row_coverage")
        expected_identities = {
            (name, (start + timedelta(days=day)).isoformat())
            for name in names
            for day in range((end - start).days + 1)
        }
        if set(identities) != expected_identities:
            raise PacketError("row_coverage")
        expected = [
            variants[(key[0], p, key[2], key[3])]["rows"]
            for p in range(1, key[1])
            if (key[0], p, key[2], key[3]) in variants
        ]
        if len(expected) != key[1] - 1:
            missing.append(
                {
                    "layer": "variant_prior",
                    "reason": "missing_earlier_variant",
                    "side": key[0],
                    "period": key[1],
                    "date_mode": key[2],
                    "audience_mode": key[3],
                }
            )
            continue
        if entry.get("priors") != expected:
            raise PacketError("prior_chain")
        variants[key] = {
            **entry,
            "totals": simulation_totals(rows),
            "raw_rows": rows,
            "window_days": (end - start).days + 1,
        }
    for side in sides:
        for period in (1, 2, 3):
            for dates in ("actual", "aligned"):
                for audience in ("ad", "group"):
                    if (side, period, dates, audience) not in variants:
                        missing.append(
                            {
                                "layer": "variant",
                                "side": side,
                                "period": period,
                                "date_mode": dates,
                                "audience_mode": audience,
                            }
                        )
    metrics = {}
    for dates in ("actual", "aligned"):
        for audience in ("ad", "group"):
            selected = [
                value
                for key, value in variants.items()
                if key[0] == spec["product_side"] and key[2:] == (dates, audience)
            ]
            totals = simulation_totals([row for variant in selected for row in variant["raw_rows"]])
            if len(selected) != 3:
                totals.update(cpa=None, threshold_met=None)
            metrics[f"{dates}.{audience}"] = totals
    scores = {
        side_alias[side]: validate_scores(parsed(identity, "independent_scores"))
        for side, identity in spec.get("scores", {}).items()
        if side in side_alias
    }
    for layer in REQUIRED_LAYERS:
        entry = spec.get("layers", {}).get(layer, {})
        raw(entry.get("ref"), layer)
        if (
            entry.get("status") != "complete"
            or entry.get("head") != spec["head"]
            or entry.get("run_id") != spec["run_id"]
        ):
            missing.append({"layer": layer, "reason": "missing_or_not_current_complete"})
    output.mkdir(parents=True, exist_ok=False)
    raw_root = output / "private" / "raw"
    raw_root.mkdir(parents=True)
    (output / "private" / "input.json").write_bytes(input_bytes)
    frozen = []
    for identity, (reference, data) in sources.items():
        path = raw_root / (identity + ".bin")
        path.write_bytes(data)
        frozen.append({**reference, "original_path": reference["path"], "frozen_path": str(path)})
    (output / "private" / "mapping.json").write_bytes(_dump(mapping))
    public_root = output / "public"
    (public_root / "fit").mkdir(parents=True)
    for identity, value in fit_packets.items():
        (public_root / "fit" / (identity + ".json")).write_bytes(_dump(value))
    aggregate = {
        "plans": public_plans,
        "rubric": context["aggregate_rubric"],
        "scores": scores,
        "variants": [
            {
                "candidate": side_alias[key[0]],
                "period": key[1],
                "date_mode": key[2],
                "audience_mode": key[3],
                "totals": value["totals"],
                "prior_periods": len(value["priors"]),
                "window_days": value["window_days"],
            }
            for key, value in variants.items()
        ],
        "limitations": LIMITATIONS,
        "disclosures": spec.get("disclosures", []),
    }
    (public_root / "aggregate.json").write_bytes(_dump(aggregate))
    (output / "controls.json").write_bytes(_dump(controls))
    copy_fit = fit_summary(product_fits)
    expected_fit_count = sum(
        row["plan_ad_count"] for row in periods.values() if row["side"] == spec["product_side"]
    )
    if (
        len(product_fits) != expected_fit_count
        or sum(key[0] == spec["product_side"] for key in periods) != 3
    ):
        copy_fit.update(
            mean=None, threshold_met=None, missing=expected_fit_count - len(product_fits)
        )
    output_files = [
        {
            "path": path.relative_to(output).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha(path.read_bytes()),
        }
        for path in sorted(output.rglob("*"))
        if path.is_file()
    ]
    result = {
        "schema": "acceptance-packet-result-v1",
        "head": spec["head"],
        "run_id": spec["run_id"],
        "output": str(output),
        "quality_verdict": "not_certified",
        "raw_sources": frozen,
        "periods": list(periods.values()),
        "variants": [
            {k: v for k, v in value.items() if k != "raw_rows"} for value in variants.values()
        ],
        "metrics": metrics,
        "copy_fit": copy_fit,
        "controls": controls,
        "frozen_files": output_files,
        "missing": missing,
        "private_mapping": str(output / "private" / "mapping.json"),
        "limitations": LIMITATIONS,
        "evidence_layers": spec.get("layers", {}),
    }
    (output / "manifest.json").write_bytes(_dump(result))
    (output / "missing-evidence.json").write_bytes(_dump(missing))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--fresh-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = prepare_packet(
        args.input, source_root=args.source_root, fresh_root=args.fresh_root, output=args.output
    )
    print(
        json.dumps(
            {
                "output": result["output"],
                "quality_verdict": result["quality_verdict"],
                "missing": len(result["missing"]),
            }
        )
    )


if __name__ == "__main__":
    main()
