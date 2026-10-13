"""Small shared eligibility/projection seam; aggregation stays in review_evidence."""

from app.ads import result_kinds

INCOMPATIBLE = frozenset({"mixed_currency", "mixed_result_definition", "mixed_attribution",
                          "result_kind_mismatch", "cap_currency_mismatch"})
UNCONFIGURED = frozenset({"target_unresolved", "result_kind_unknown"})


def for_target(view: dict | None, target: dict) -> dict | None:
    """Keep observed counts, but refuse to compare a different or unverified result unit."""
    if view is None:
        return None
    expected, actual = target.get("result_kind"), view.get("result_kind")
    reason = view.get("reason")
    if expected is not None and actual is not None and expected != actual:
        reason = "result_kind_mismatch"
    elif reason is None and expected is None:
        reason = "result_kind_unknown"
    elif reason is None and (actual is None or view.get("result_action") is None
                             or view.get("result_attribution") is None):
        reason = "result_definition_unverified"
    return {**view, "reason": reason,
            "source_reason": view.get("source_reason", view.get("reason"))}


def project(view: dict | None, spend, target: dict, scope: dict, *, comparison=None,
            evidence_refs=(), reason=None) -> dict:
    """Result truth, cap eligibility and sample context remain explicit and independent."""
    checked = for_target(view, target)
    reasons = list(dict.fromkeys(filter(None, [
        reason, checked.get("reason") if checked else "result_unknown_days",
        (comparison or {}).get("reason"),
        "target_unresolved" if target.get("value") is None else None,
    ])))
    count = (view or {}).get("result_count")
    raw_reason = (view or {}).get("source_reason", (view or {}).get("reason"))
    known_count = count
    if raw_reason or reason or view is None:
        count = None
    definition_known = bool(view and view.get("result_kind") and view.get("result_action")
                            and view.get("result_attribution"))
    data_state = (
        "incompatible" if raw_reason in INCOMPATIBLE else "incomplete"
        if raw_reason or reason or count is None or spend is None or not definition_known else
        "known_zero" if count == 0 else "known_positive"
    )
    if any(r in INCOMPATIBLE for r in reasons):
        state = "incompatible"
    elif any(r in UNCONFIGURED for r in reasons):
        state = "unconfigured"
    elif reasons or count is None or spend is None:
        state = "incomplete"
    else:
        state = "known_zero" if count == 0 else "known_positive"
    cost = (view or {}).get("cost_per_result") if data_state == "known_positive" else None
    kind = (view or {}).get("result_kind")
    refs = list(evidence_refs)
    return {
        "scope": scope, "result_kind": kind, "result_label": result_kinds.label(kind),
        "result_action": (view or {}).get("result_action"),
        "result_attribution": (view or {}).get("result_attribution"),
        "currency": (view or {}).get("currency"), "spend": spend, "count": count,
        "known_count": known_count,
        "cost_per_result": cost, "state": state, "data_state": data_state, "reasons": reasons,
        "comparison_state": "ready" if not reasons else "unconfigured"
        if any(r in UNCONFIGURED for r in reasons) else "incompatible"
        if any(r in INCOMPATIBLE for r in reasons) else "unknown",
        "target": {k: target.get(k) for k in ("value", "basis", "result_kind", "revision")},
        "comparison": comparison,
        "sample": {"count": count, "result_kind": kind, "days": scope.get("days"),
                   "days_present": (view or {}).get("days_present", 0),
                   "days_known": (view or {}).get("days_known", 0),
                   "derived_zero_days": (view or {}).get("derived_zero_days", 0)},
        "evidence_refs": refs[:32], "evidence_ref_count": len(refs),
        "evidence_refs_omitted": max(len(refs) - 32, 0),
    }
