"""app/ads/learning_view.py — F46 Contract L: what the closed campaigns taught, one read for every
place that shows or uses it (品牌智庫 「投放學到的」, the closeout dialog, the month review, the
strategy basis, and the planners' 【上幾期的排名】 through `coordinate_learning.ranked_section`).

A ranked row's numbers come from the stored `v=2` scope rows (`learning_rank.parse_scope`) the
closeout wrote, never recomputed from outcome rows. A campaign's own `spend`／`sales`／
`cost_per_sale`／`currency` are its closed-window totals over every ad, ranked or not
(`outcome.window_totals`, F51 planning #16 -- 上一期花費 no longer skips unranked ads; the
same ad-scope rows and rules the ranked rows were cut by). A customer
group's totals are sums of its stored rows; it carries one `cap` only when every campaign it
was listed in shares cap and currency, else `cap` null with `caps_differ` (never a cross-campaign
每筆 against one campaign's cap). Rows without `v=2` are not read. Ledger access only through
`app.brand_intelligence.repository`'s public reads;
customer group names through `customer_groups.groups_by_id` (a group that no longer resolves
reads 「已刪除的顧客群」).

Private to app/ads.
"""

from typing import cast

from app.ads import ads_learnings, customer_groups, learning_rank, outcome
from app.ads import repository as ads_repo
from app.ads import sell_way as sell_way_mod
from app.brand_intelligence import repository as bi_repo
from app.core import settings as coresettings
from app.core.db import Conn, ConnProxy

_AnyConn = Conn | ConnProxy

SOURCE_TRACK = "coordinate"
# Same ceiling as the other learning-ledger idempotency scans in app/ads.
SCAN_LIMIT = 500
DELETED_GROUP = "已刪除的顧客群"
EMPTY_MISSING_DATA = "資料缺天，這期沒有記學習"
EMPTY_NO_SPEND = "這期沒有花到錢的廣告"
# closeout.py's incomplete-recovery sentence (verdict_json.missing); copied, not imported --
# closeout imports this module's caller.
_INCOMPLETE_SIMULATION = "模擬回收尚有缺日或缺廣告，不把缺資料視為零。"


def vocabulary(conn: _AnyConn, org_id: str, brand_id: str) -> dict:
    """`{(dimension, key): label}` from the brand vocabulary; a missing label reads as the key."""
    return {
        (row["dimension"], row["key"]): row["label"]
        for row in ads_repo.coordinate_vocabulary(conn, org_id, brand_id)
    }


def _split_cycle(source_cycle_id: str | None) -> tuple[str, str] | None:
    campaign_id, sep, ad_id = (source_cycle_id or "").rpartition(":")
    if not sep or not campaign_id or not ad_id:
        return None
    return campaign_id, ad_id


def _stored_rows(conn: _AnyConn, brand_id: str) -> dict:
    """`campaign_id -> [parsed v=2 row + learning_id, ad_id]`, one ledger read."""
    by_campaign: dict = {}
    for row in bi_repo.list_learnings(
        cast(Conn, conn), brand_id, source_track=SOURCE_TRACK, limit=SCAN_LIMIT,
    ):
        parsed = learning_rank.parse_scope(row.get("applicability_scope"))
        cycle = _split_cycle(row.get("source_cycle_id"))
        if parsed is None or cycle is None:
            continue
        by_campaign.setdefault(cycle[0], {})[cycle[1]] = {
            **parsed, "learning_id": row["id"], "ad_id": cycle[1], "ledger_row": dict(row),
        }
    return {cid: list(ads.values()) for cid, ads in by_campaign.items()}


def _closed_campaigns(conn: _AnyConn, org_id: str, brand_id: str, campaign_id, sell_way_id,
                      limit: int) -> list[dict]:
    sql = (
        "SELECT id, name, context_json, start_date, end_date, closed_at, verdict_json"
        " FROM ads_campaign WHERE org_id = %s AND brand_id = %s AND status = 'closed'"
        " AND origin = 'internal'"
    )
    params: list = [org_id, brand_id]
    if campaign_id is not None:
        sql += " AND id = %s"
        params.append(campaign_id)
    sql += " ORDER BY closed_at DESC NULLS LAST, id"
    rows = [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]
    if sell_way_id is not None:
        rows = [row for row in rows if sell_way_mod.of_campaign(row) == sell_way_id]
    return rows[:limit]


def _empty_reason(campaign: dict) -> str:
    verdict_json = campaign.get("verdict_json") or {}
    if "missing_days" in verdict_json or verdict_json.get("missing") == _INCOMPLETE_SIMULATION:
        return EMPTY_MISSING_DATA
    return EMPTY_NO_SPEND


def _coordinates(keys: dict, labels: dict) -> list[dict]:
    return [
        {"dimension": d, "dimension_label": learning_rank.DIMENSION_LABELS[d], "key": keys[d],
         "label": labels.get((d, keys[d]), keys[d])}
        for d in learning_rank.DIMENSIONS if keys[d] != learning_rank.MISSING
    ]


def _campaign(conn, org_id, brand_id, campaign: dict, stored: list[dict], labels: dict, tz,
              group_cache: dict) -> dict:
    stored = sorted(stored, key=lambda row: row["rank"])
    ad_names = {}
    if stored:
        ad_names = {
            row["id"]: row["name"]
            for row in conn.execute(
                "SELECT id, name FROM ads_ad WHERE org_id = %s AND brand_id = %s"
                " AND id = ANY(%s)",
                (org_id, brand_id, [row["ad_id"] for row in stored]),
            ).fetchall()
        }
    products = tuple((campaign.get("context_json") or {}).get("product_ids") or [])
    if products not in group_cache:
        group_cache[products] = customer_groups.groups_by_id(conn, brand_id, campaign)
    groups = group_cache[products]

    rows = []
    for row in stored:
        group_id = row["customer_group_id"]
        group = None
        if group_id is not None:
            found = groups.get(group_id)
            group = {"id": group_id, "who": found["who"] if found else DELETED_GROUP}
        rows.append({
            "rank": row["rank"], "of": row["of"], "ad_id": row["ad_id"],
            "ad_name": ad_names.get(row["ad_id"]) or row["ad_id"], "customer_group": group,
            "coordinates": _coordinates(row["keys"], labels), "spend": row["spend"],
            "sales": row["sales"], "cost_per_sale": row["cost_per_sale"],
            "verdict": row["verdict"], "verdict_label": row["verdict_label"],
            "flags": list(row["flags"]), "learning_id": row["learning_id"],
        })

    cap = stored[0]["cap"] if stored else None
    totals = outcome.window_totals(conn, org_id, brand_id, campaign)
    spend, sales = totals["spend"], totals["results"]
    closed_at = campaign.get("closed_at")
    return {
        "campaign_id": campaign["id"], "campaign_name": campaign["name"],
        "sell_way_id": sell_way_mod.of_campaign(campaign),
        "start_date": campaign["start_date"].isoformat() if campaign.get("start_date") else None,
        "end_date": campaign["end_date"].isoformat() if campaign.get("end_date") else None,
        "closed_on": closed_at.astimezone(tz).date().isoformat() if closed_at else None,
        "cap": cap, "currency": totals["currency"],
        "spend": spend, "sales": sales,
        "cost_per_sale": spend / sales if spend is not None and sales else None,
        "counts": {
            "keep": sum(1 for row in stored if learning_rank.is_keep(row["verdict"])),
            "replace": sum(1 for row in stored if not learning_rank.is_keep(row["verdict"])),
        },
        "rule_text": learning_rank.rule_text(stored, cap),
        "empty_reason": None if stored else _empty_reason(campaign),
        "rows": rows,
    }


def _groups(campaigns: list[dict]) -> list[dict]:
    """Per customer group over the listed rows. `cap` only when every campaign the group was
    listed in shares one cap and one currency; else `cap` null and `caps_differ` true."""
    by_id: dict = {}
    terms: dict = {}
    for campaign in campaigns:  # newest first
        for row in campaign["rows"]:
            group = row["customer_group"]
            if group is None:
                continue
            entry = by_id.setdefault(group["id"], {
                "customer_group_id": group["id"], "who": group["who"], "ads": 0,
                "spend": 0, "sales": 0,
            })
            entry["ads"] += 1
            entry["spend"] += row["spend"] or 0
            entry["sales"] += row["sales"]
            terms.setdefault(group["id"], set()).add((campaign["cap"], campaign["currency"]))
    out = []
    for group_id, entry in by_id.items():
        shared = terms[group_id]
        entry["caps_differ"] = len(shared) > 1
        entry["cap"] = next(iter(shared))[0] if len(shared) == 1 else None
        entry["cost_per_sale"] = entry["spend"] / entry["sales"] if entry["sales"] else None
        out.append(entry)
    out.sort(key=lambda e: (e["cost_per_sale"] is None, e["cost_per_sale"] or 0, e["who"]))
    return out


def learnings_view(conn: _AnyConn, org_id: str, brand_id: str, *, campaign_id: str | None = None,
                   sell_way_id: str | None = None, limit: int = 12) -> dict:
    """Contract L: `{campaigns, groups, next}` over the brand's closed internal campaigns, newest
    closed first (≤ `limit`), optionally one campaign or one sell-way. Each row also carries its
    `learning_id` and each coordinate its `key` (the planners' prompt and gate read them)."""
    campaigns_rows = _closed_campaigns(conn, org_id, brand_id, campaign_id, sell_way_id, limit)
    stored = _stored_rows(conn, brand_id) if campaigns_rows else {}
    labels = vocabulary(conn, org_id, brand_id) if stored else {}
    tz = coresettings.org_timezone(conn, org_id=org_id)
    group_cache: dict = {}
    campaigns = [
        _campaign(conn, org_id, brand_id, campaign, stored.get(campaign["id"], []), labels, tz,
                  group_cache)
        for campaign in campaigns_rows
    ]
    next_sell_way = sell_way_id
    if next_sell_way is None and campaigns:
        next_sell_way = campaigns[0]["sell_way_id"]
    # The all-track cap can omit older coordinate rows still represented by the ranked view.
    # Qualify every represented row from its retained ledger record, without dropping ranks.
    evidence_rows = {row["id"]: row for row in bi_repo.list_learnings(
        cast(Conn, conn), brand_id, limit=SCAN_LIMIT,
    )}
    for campaign in campaigns:
        for row in stored.get(campaign["campaign_id"], []):
            evidence_rows[row["learning_id"]] = row["ledger_row"]
    all_context = ads_learnings.evidence_context(
        conn, org_id, brand_id, next_sell_way,
        rows=list(evidence_rows.values()), cap=len(evidence_rows),
    )
    context = {**all_context, "items": all_context["items"][:30],
               "omitted": max(len(all_context["items"]) - 30, 0)}
    by_id = {item["id"]: item for item in all_context["items"]}
    for campaign in campaigns:
        for row in campaign["rows"]:
            row["evidence"] = by_id[row["learning_id"]]
    return {
        "campaigns": campaigns,
        "groups": _groups(campaigns),
        "evidence_context": context,
        "next": None if next_sell_way is None else {
            "sell_way_id": next_sell_way,
            "new_campaign_href": f"/brands/{brand_id}/ads/new?sell_way={next_sell_way}",
        },
    }


def learning_ids(view: dict) -> list[str]:
    """The ledger rows a view was built from, in display order."""
    return [row["learning_id"] for campaign in view["campaigns"] for row in campaign["rows"]]
