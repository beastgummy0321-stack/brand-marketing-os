"""app/schedule/scoring.py -- settling a period scores every bound node (ticket smart-loop 01,
ADR 0066).

Private to app/schedule/ (container contract section 1): only app/schedule/routes.py calls
score_period(), after period.settle() succeeds. Never imported by period.py or state.py --
the in-package import direction stays state -> period, performance -> state
(docs/contracts/schedule.md); scoring sits outside that chain on purpose so a resettle's scoring
can never become part of what settle() itself depends on.

What gets a row (ADR 0066 rule 2): every node of the period's OWN tree (named by its
period_node_membership rows' source_tree_task_id, not whichever tree is bound "now") that has a
channel_entity_map binding at depth 2 (ad set, carries the approved share) or depth 3 (ad,
carries the seven coordinate keys). Depth 1 (one campaign) is never scored. Rows of different
depths are never summed -- the same money sits on both levels, same reason
period.node_level_spend() is pinned to one level.

Which money (ADR 0066 rule 3): the bound platform object's spend on the period's own
[start_date, end_date], read through meta_repo.daily_entity_spend() at that node's level and
aggregated with performance._bucket() -- the same arithmetic as the coordinate chart. This is a
per-node READING, not the money of record: campaign_period.settled_spend keeps ADR 0053 section 4's
ownership split (shorter period wins, ties split evenly); this table does not apply that split,
so the same spend can legitimately show up in full on more than one overlapping period's node
rows while settled_spend itself is only ever split once.
"""

from datetime import timedelta

from app.llm import gateway
from app.meta import repository as meta_repo
from app.schedule import diagnosis as diagnosis_mod
from app.schedule import performance as performance_mod
from app.schedule import repository as schedule_repo
from app.schedule import tree as tree_mod

_CHANNEL_KEY = "meta"  # the only channel this module binds today (binding.py's own constant
                       # is not imported -- not on this file's allowed-imports list).
_SCORED_DEPTHS = {2: "adset", 3: "ad"}
_COORDINATE_FIELDS = ("audience_key", "pain_key", "angle_key", "hook_key", "proof_key",
                      "offer_key", "format_key")


def verdict(roas_conservative: float | None, roas_optimistic: float | None,
            breakeven: float | None) -> str:
    """ADR 0066 rule 4. Order matters: a missing break-even or a spend-less node is `unclear`
    before either ROAS comparison runs."""
    if breakeven is None or roas_conservative is None:
        return "unclear"
    if roas_conservative >= breakeven:
        return "win"
    if roas_optimistic is not None and roas_optimistic < breakeven:
        return "lose"
    return "unclear"


def _flatten(nodes: list, depth: int = 1):
    """Depth-first walk of tree_mod.tree_from_task_row()'s nested `nodes` -- depth is the
    node_key's dot count + 1, same definition as channel_entity_map.depth (GENERATED column)."""
    for node in nodes:
        yield node["node_key"], depth, node
        yield from _flatten(node["children"], depth + 1)


def score_period(conn, org_id: str, brand_id: str, period_id: str, settled_at) -> int:
    """Writes/replaces this period's period_node_result rows; returns the row count."""
    period = schedule_repo.get_period(conn, org_id, brand_id, period_id)
    if period is None:
        return 0
    memberships = schedule_repo.period_node_memberships_for_period(conn, org_id, brand_id,
                                                                     period_id)
    if not memberships:
        return 0
    newest = max(memberships, key=lambda m: m["created_at"])
    source_tree_task_id = newest["source_tree_task_id"]
    channel_id = newest["channel_id"]

    task_row = gateway.get_task(conn, source_tree_task_id)
    tree = tree_mod.tree_from_task_row(task_row) if task_row is not None else {"nodes": []}
    bindings = schedule_repo.bindings_for_tree(conn, org_id, brand_id, _CHANNEL_KEY,
                                                source_tree_task_id)
    account_ids = meta_repo.bound_account_ids_for_brand(conn, org_id, brand_id)
    breakeven, breakeven_source = diagnosis_mod.breakeven_roas(conn, org_id, brand_id)
    coordinate_lookup = schedule_repo.creative_candidates_for_brand(conn, org_id, brand_id)

    scored: dict[int, list] = {2: [], 3: []}
    for node_key, depth, node in _flatten(tree.get("nodes", [])):
        binding = bindings.get(node_key)
        if depth in _SCORED_DEPTHS and binding is not None:
            scored[depth].append((node_key, node, binding))

    end_exclusive = period["end_date"] + timedelta(days=1)
    rows = []
    for depth, level in _SCORED_DEPTHS.items():
        entity_ids = {binding["external_id"] for _, _, binding in scored[depth]}
        spend_rows = meta_repo.daily_entity_spend(
            conn, org_id, account_ids, period["start_date"], end_exclusive, level=level,
        ) if entity_ids else []
        by_entity: dict[str, list] = {}
        for r in spend_rows:
            if r["entity_id"] in entity_ids:
                by_entity.setdefault(r["entity_id"], []).append(r)

        for node_key, node, binding in scored[depth]:
            bucket = performance_mod._bucket(by_entity.get(binding["external_id"], []))
            coordinates_json = None
            if depth == 3:
                candidate = coordinate_lookup.get((node_key, source_tree_task_id))
                if candidate is not None:
                    coordinates_json = {k: candidate[k] for k in _COORDINATE_FIELDS}
            rows.append({
                "source_tree_task_id": source_tree_task_id, "channel_id": channel_id,
                "node_key": node_key, "depth": depth,
                "node_name": binding["node_name_at_bind"], "external_id": binding["external_id"],
                "approved_share": node["share"], "approved_daily_amount": node["daily_amount"],
                "actual_spend": bucket["spend"], "revenue_tracked": bucket["revenue"],
                "roas_conservative": bucket["roas_conservative"], "roas_optimistic": bucket["roas"],
                "roas_coverage": bucket["roas_coverage"], "breakeven_roas": breakeven,
                "breakeven_source": breakeven_source,
                "verdict": verdict(bucket["roas_conservative"], bucket["roas"], breakeven),
                "coordinates_json": coordinates_json, "settled_at": settled_at,
            })

    return schedule_repo.replace_period_node_results(conn, org_id, brand_id, period_id, rows)
