"""app/ads/ad_status.py — F26-I01: the single, shared definition of "closed" for an ad's own
`native_status` (ARCHITECTURE.md §0 "程式整理，LLM 判斷" — this is a lookup table, not a
judgment). Three consumers share this one set rather than each keeping its own, divergent copy
(measured cause, feature Decisions): `triage.classify()` (judges only non-closed ads),
`triage_scale.py` (Rule A/B's own "active" gate), and `month_budget.py` (budget-owner eligibility,
already using this exact five-value set inline before this issue).

Platform-neutral: this file names no platform and imports no adapter -- the five values are Meta's
own `native_status` vocabulary as written by `adapters/meta_read.py`, but nothing here branches on
`platform`.
"""

CLOSED_STATUSES = {"PAUSED", "DELETED", "ARCHIVED", "ADSET_PAUSED", "CAMPAIGN_PAUSED"}


def is_closed(native_status: str | None) -> bool:
    """`None` is NOT closed -- an unknown status is unknown, never treated as closed (feature
    Decisions "I01"). Only an explicit, recognised closed value counts."""
    if native_status is None:
        return False
    return native_status in CLOSED_STATUSES
