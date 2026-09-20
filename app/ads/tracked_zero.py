"""F18-I01: conditional tracked zero. An absent platform action becomes a knowable
"spend with zero results", never a guess.

Platform-neutral (ARCHITECTURE.md §6.14/§6.15): no adapter import, no platform literal, no
`attribution_key` parsing. Never invents a result definition -- a zero is only derived once this
campaign has demonstrated exactly one (result_kind, result_action, result_attribution) triple with
a real non-zero count of its own, over its own trailing `OBSERVATION_WINDOW_DAYS`. The write is
`result_count=0` plus that demonstrated action/attribution and
`availability.result_count="derived_zero"` -- distinguishable everywhere from a platform-reported
`"available"` zero and from a genuinely `"unknown"` absence (F18 feature Decisions).
"""

from datetime import timedelta

from app.ads.external_repository import MONTHLY_BUDGET_ATTRIBUTION_KEY
from app.core import settings
from app.core.db import jsonb

OBSERVATION_WINDOW_DAYS = 28


def apply(conn, org_id, brand_id, campaign_id, start, end) -> dict:
    """Derive `result_count=0` on rows of `campaign_id` within the just-completed sync's covered
    `[start, end]`. Writes nothing (and reports why) unless this campaign's own trailing
    `OBSERVATION_WINDOW_DAYS` ending at `end` demonstrates exactly one result definition.
    """
    demo_start = end - timedelta(days=OBSERVATION_WINDOW_DAYS - 1)
    demonstrated = conn.execute(
        "SELECT DISTINCT result_kind,result_action,result_attribution FROM ads_external_daily "
        "WHERE org_id=%s AND brand_id=%s AND campaign_id=%s AND day BETWEEN %s AND %s "
        "AND result_kind IS NOT NULL AND result_count IS NOT NULL AND result_count>0 "
        "AND availability->>'result_count'='available'",
        (org_id, brand_id, campaign_id, demo_start, end),
    ).fetchall()
    if len(demonstrated) == 0:
        return {"derived": 0, "reason": "no_demonstrated_definition"}
    if len(demonstrated) > 1:
        return {"derived": 0, "reason": "mixed_result_definition"}
    definition = demonstrated[0]
    cutoff = settings.today_for_org(conn, org_id=org_id) - timedelta(days=1)
    rows = conn.execute(
        "UPDATE ads_external_daily SET result_count=0,result_action=%s,result_attribution=%s,"
        "availability=availability || %s::jsonb "
        "WHERE org_id=%s AND brand_id=%s AND campaign_id=%s AND day BETWEEN %s AND %s "
        "AND day<=%s AND result_kind=%s AND result_count IS NULL "
        "AND availability->>'result_count' IS NOT NULL "
        "AND availability->>'spend'='available' AND (spend>0 OR impressions>0) "
        "AND attribution_key<>%s RETURNING id",
        (
            definition["result_action"],
            definition["result_attribution"],
            jsonb({"result_count": "derived_zero"}),
            org_id,
            brand_id,
            campaign_id,
            start,
            end,
            cutoff,
            definition["result_kind"],
            MONTHLY_BUDGET_ATTRIBUTION_KEY,
        ),
    ).fetchall()
    return {"derived": len(rows), "reason": None}
