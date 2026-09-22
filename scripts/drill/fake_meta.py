"""scripts/drill/fake_meta.py — a stand-in for the Meta Graph API, for usability drills only.

WHY THIS EXISTS. The ad loop's steps 6-8 need a human to hand-build campaigns inside Meta Ads
Manager and then wait for real money to be spent. A persona drill cannot do either. This module
replaces the single network edge `app.meta.graph.fetch_page` (the same seam the unit tests
replace by name) with a reader over a JSON state file, so that binding (step 7) and the spend
pull (step 8) run their real code paths against invented platform data.

DRILL 5: the imported-campaign path. `app/ads/external_sync.py` -> `app/ads/adapters/meta_read.py`
-> `app.meta.graph.external_page`/`fetch_ad_creatives`/single-node reads is a second, separate
consumer of `app.meta.graph.fetch_page` — the old-campaign functions above (`list_campaigns`,
`list_ad_sets`, `list_ads`, `list_entity_insights`) never touch it. `fake_fetch_page` now answers
both: the old shapes (unchanged, still fed by `mirror`/`spend`/`pull`), and the new ones an
imported campaign's sync, its readbacks (`change_control_verify.py`/`handoff_check.py` via
`reader.verify_native`), and `fetch_ad_creatives`/`fetch_budgets` use. IDs for the imported path
are digits-only (`graph.external_page` rejects anything else) and live in their own numeric
prefix range (92xx…) so they never collide with the old path's `brand_id`-derived ids.

NOT A PRODUCT PATH. Nothing under `app/` imports this file, and nothing here writes to the
database directly — spend reaches the database only by way of the real product's own sync code
(`app.meta.daily_pull.backfill` for the old path, `app.ads.external_sync.run_sync` for the
imported path). Delete this directory and the product is unchanged.

State file (`.scratch/drill/meta_state.json`, override with DRILL_META_STATE):

    {"accounts": [{account_id, name, currency, timezone_name, token}],
     "campaigns": [{id, account_id, name, effective_status,
                    # imported-path campaigns also carry:
                    objective, start_time, stop_time}],
     "adsets":    [{id, campaign_id, name, effective_status,
                    # imported-path adsets also carry:
                    account_id, start_time, end_time, daily_budget}],
     "ads":       [{id, adset_id, campaign_id, name, effective_status,
                    # imported-path ads also carry:
                    account_id, creative, _daily_spend_recent, _daily_purchases_recent,
                    _daily_spend_old, _daily_purchases_old}],
     "insights":  [{level, date_start, campaign_id, adset_id, ad_id, <level>_name,
                    spend, impressions, clicks, purchase_roas,
                    # imported-path rows also carry:
                    date_stop, account_id, account_currency, actions, action_values}],
     "_seq": {<id prefix>: <last number used>}, "_today": "<last imported-path insight day>"}

CLI:
    python -m scripts.drill.fake_meta reset
    python -m scripts.drill.fake_meta mirror <brand_id>          # tree -> platform entities
    python -m scripts.drill.fake_meta spend <brand_id> --round N # invent insights
    python -m scripts.drill.fake_meta pull <org_id> --since YYYY-MM-DD
    python -m scripts.drill.fake_meta show

    # imported-campaign path (operator plays "Meta"; nothing here needs a brand or the DB):
    python -m scripts.drill.fake_meta seed-imported --token T --account 900... --currency TWD
    python -m scripts.drill.fake_meta pause|activate <ad_id>
    python -m scripts.drill.fake_meta set-budget <adset_id> <amount>
    python -m scripts.drill.fake_meta edit-copy <ad_id> --title T --body B
    python -m scripts.drill.fake_meta add-ad <adset_id> --name N --title T --body B --image-url U
    python -m scripts.drill.fake_meta advance-days <n> [--spend-scale X]
    python -m scripts.drill.fake_meta selfcheck-imported
"""

import hashlib
import json
import os
from datetime import date, timedelta
from pathlib import Path

STATE_PATH = Path(os.environ.get(
    "DRILL_META_STATE",
    Path(__file__).resolve().parents[2] / ".scratch" / "drill" / "meta_state.json",
))

# One invented ad account PER PERSONA, matched by the token they paste. Sharing one account
# across personas silently merged their spend: a pull for one org came back holding another
# persona's campaigns, because `/act_<id>/insights` cannot tell two tenants apart when both
# bound the same account. Real tenants can share an ad account, but a drill must not force it.
# `account_id` is digits only, like the real thing: `act_` is a prefix the client adds.
DRILL_ACCOUNTS = [
    {"account_id": "900000000000001", "name": "MOVE Daily 廣告帳戶", "currency": "TWD",
     "timezone_name": "Asia/Taipei", "token": "EAAG-drill-token-vivian"},
    {"account_id": "900000000000002", "name": "常春健康廣告帳戶", "currency": "TWD",
     "timezone_name": "Asia/Taipei", "token": "EAAG-drill-token-aming"},
    {"account_id": "900000000000003", "name": "日常萃廣告帳戶", "currency": "TWD",
     "timezone_name": "Asia/Taipei", "token": "EAAG-drill-token-jay"},
]


def load() -> dict:
    if not STATE_PATH.exists():
        return {"accounts": [], "campaigns": [], "adsets": [], "ads": [], "insights": []}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# imported-campaign path: ids, state helpers, fixture shape
# ---------------------------------------------------------------------------

# Digits-only, disjoint from the old path's `{kind}{brand_id[-6:]}{seq}` ids (which embed
# brand_id characters and are not guaranteed numeric) — `app.meta.graph.external_page` rejects
# any account/native id that fails `str(x).isdigit()`.
_ID_PREFIX = {"campaign": "9201", "adset": "9202", "ad": "9203"}
SALES_OBJECTIVE = "OUTCOME_SALES"  # app/ads/adapters/meta_read.py::_SALES_OBJECTIVES


def _next_id(state: dict, kind: str) -> str:
    seq = state.setdefault("_seq", {})
    seq[kind] = seq.get(kind, 0) + 1
    return f"{_ID_PREFIX[kind]}{seq[kind]:06d}"


def _upsert_account(state: dict, token: str, account_id: str, currency: str) -> None:
    for account in state["accounts"]:
        if account["account_id"] == account_id:
            account.update(token=token, currency=currency)
            return
    state["accounts"].append({
        "account_id": account_id, "name": f"演練匯入帳戶 {account_id}", "currency": currency,
        "timezone_name": "Asia/Taipei", "token": token,
    })


def _fmt_amount(value) -> str:
    return f"{value:.2f}"


def _actions_for(purchases: float) -> list:
    return [{"action_type": "omni_purchase", "value": f"{purchases:.4f}"}]


def _action_values_for(spend: float) -> list:
    # Revenue is never read by triage (`app/ads/triage.py` only reads spend/result_count) —
    # an arbitrary multiple is enough to keep the field shape realistic.
    return [{"action_type": "omni_purchase", "value": f"{spend * 3:.2f}"}]


def _ad_insight_row(ad, campaign_id, account_id, currency, day, spend, purchases) -> dict:
    return {
        "level": "ad", "date_start": day.isoformat(), "date_stop": day.isoformat(),
        "campaign_id": campaign_id, "adset_id": ad["adset_id"], "ad_id": ad["id"],
        "ad_name": ad["name"], "account_id": account_id, "account_currency": currency,
        "spend": _fmt_amount(spend), "impressions": round(spend * 30), "clicks": round(spend / 5),
        "actions": _actions_for(purchases), "action_values": _action_values_for(spend),
    }


def _rollup_insight_row(level, day, campaign_id, account_id, currency, spend, impressions,
                        clicks, purchases, *, adset_id=None, name=None) -> dict:
    row = {
        "level": level, "date_start": day.isoformat(), "date_stop": day.isoformat(),
        "campaign_id": campaign_id, "account_id": account_id, "account_currency": currency,
        "spend": _fmt_amount(spend), "impressions": impressions, "clicks": clicks,
        "actions": _actions_for(purchases), "action_values": _action_values_for(spend),
    }
    if level == "adset":
        row["adset_id"] = adset_id
        row["adset_name"] = name
    elif level == "campaign":
        row["campaign_name"] = name
    return row


def _write_day(state, campaign, account_id, currency, ads, day, rate_of) -> None:
    """One day of insights for every ACTIVE ad in `ads`, plus the adset- and campaign-level
    rollups the same day would need (`external_page`'s observations phase reads all three
    levels through the campaign's own `insights` edge — see `fake_fetch_page`). `rate_of(ad)` ->
    (spend, purchases) for this ad on this day; callers vary it by day offset (`seed-imported`'s
    recent/older split) or hold it constant (`advance-days`)."""
    campaign_spend = campaign_purchases = 0.0
    campaign_impressions = campaign_clicks = 0
    per_adset: dict = {}
    adsets_by_id = {s["id"]: s for s in state["adsets"] if s["campaign_id"] == campaign["id"]}
    for ad in ads:
        if ad["effective_status"] != "ACTIVE":
            continue
        spend, purchases = rate_of(ad)
        row = _ad_insight_row(ad, campaign["id"], account_id, currency, day, spend, purchases)
        state["insights"].append(row)
        campaign_spend += spend
        campaign_purchases += purchases
        campaign_impressions += row["impressions"]
        campaign_clicks += row["clicks"]
        acc = per_adset.setdefault(ad["adset_id"], [0.0, 0.0, 0, 0])
        acc[0] += spend
        acc[1] += purchases
        acc[2] += row["impressions"]
        acc[3] += row["clicks"]
    for adset_id, (spend, purchases, impressions, clicks) in per_adset.items():
        adset = adsets_by_id.get(adset_id)
        name = adset["name"] if adset else adset_id
        state["insights"].append(_rollup_insight_row(
            "adset", day, campaign["id"], account_id, currency, spend, impressions, clicks,
            purchases, adset_id=adset_id, name=name,
        ))
    if per_adset:
        state["insights"].append(_rollup_insight_row(
            "campaign", day, campaign["id"], account_id, currency, campaign_spend,
            campaign_impressions, campaign_clicks, campaign_purchases, name=campaign["name"],
        ))


# ---------------------------------------------------------------------------
# the fake network edge
# ---------------------------------------------------------------------------

_LIST_EDGES = {"adaccounts", "campaigns", "adsets", "ads", "insights"}


def _find_by_id(state: dict, entity_id: str) -> dict | None:
    """Any campaign/adset/ad by its native id — used for single-node reads
    (`GET {id}`, no edge word), the shape `external_page`'s `campaign`/`adset`/`ad` sections,
    `fetch_budgets` and `fetch_ad_creatives` all use. IDs are digits-only and drawn from
    disjoint prefix ranges (see `_next_id`), so one merged index is unambiguous."""
    for bucket in ("campaigns", "adsets", "ads"):
        for item in state[bucket]:
            if item["id"] == entity_id:
                return dict(item)
    return None


def fake_fetch_page(url: str, *, params: dict | None, headers: dict) -> dict:
    """Drop-in for `app.meta.graph.fetch_page`. Pages list answers like Graph does: `limit` rows
    per page (the client refuses a page over 100 — drill 5 hit that with 560 ad-level insight
    rows), `paging.next` + `cursors.after` while rows remain; `after` is an opaque offset."""
    body = _answer(url, params=params, headers=headers)
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        return body
    limit = int((params or {}).get("limit") or 100)
    start = int(str((params or {}).get("after") or "o0").removeprefix("o"))
    page: dict = {"data": data[start:start + limit]}
    if start + limit < len(data):
        page["paging"] = {"next": url, "cursors": {"after": f"o{start + limit}"}}
    return page


def _answer(url: str, *, params: dict | None, headers: dict) -> dict:
    """One unpaged answer for `url`.

    Serves two generations of URL shape, disambiguated by node/edge, never by which CLI command
    wrote the data: the old internal-campaign functions (`list_campaigns`/`list_ad_sets`/
    `list_ads`/`list_entity_insights`, node is `me`/`act_<id>`/an adset id) and the imported-
    campaign path (`external_page`, node is `act_<id>` for `campaigns`/monthly `insights`, or a
    campaign's own native id for `adsets`/`ads`/creatives-as-`ads`/campaign-scoped `insights`, or
    absent — a bare single-node `GET {id}` — for `campaign`/`adset`/`ad`/`fetch_budgets`/
    `fetch_ad_creatives`)."""
    state = load()
    tail = url.rstrip("/").split("/")
    node, edge = tail[-2], tail[-1]

    if node == "me" and edge == "adaccounts":
        # A token sees its own account only. `_to_account` ignores the extra `token` key.
        bearer = (headers or {}).get("Authorization", "").removeprefix("Bearer ").strip()
        mine = [a for a in state["accounts"] if a.get("token") == bearer]
        return {"data": mine or [a for a in state["accounts"] if not a.get("token")]}

    if edge == "campaigns":
        account_id = node.removeprefix("act_")
        # Full stored dict, not a 3-field projection: the old path's `_to_campaign` only reads
        # id/name/effective_status and ignores the rest; the imported path's `_entity` needs
        # account_id/objective/budget/start_time/stop_time too. One shape serves both.
        return {"data": [dict(c) for c in state["campaigns"] if c["account_id"] == account_id]}

    if edge == "adsets":
        return {"data": [dict(s) for s in state["adsets"] if s["campaign_id"] == node]}

    if edge == "ads":
        # Two different node semantics share this one edge word: the old path's
        # `list_ads(token, adset_id)` (`GET {adset_id}/ads`) and the imported path's structure/
        # creatives phases, which always query the CAMPAIGN's own `ads` edge (`GET
        # {campaign_id}/ads`, `read_structure`/`read_creatives` in meta_read.py fix `native_id`
        # to the campaign root for every phase). Id namespaces never overlap (`_next_id`), so
        # trying the adset filter first and falling back to the campaign filter is unambiguous.
        by_adset = [dict(a) for a in state["ads"] if a["adset_id"] == node]
        if by_adset:
            return {"data": by_adset}
        return {"data": [dict(a) for a in state["ads"] if a.get("campaign_id") == node]}

    if edge == "insights":
        level = (params or {}).get("level")
        window = json.loads((params or {}).get("time_range") or "{}")
        since = window.get("since", "0000-01-01")
        until = window.get("until", "9999-12-31")
        if node.startswith("act_"):
            # Account-scoped: the old path's `list_entity_insights` (any level, whole account)
            # and the imported path's account-wide monthly rollup (level=campaign) share this
            # shape. Filter by account as well as level and date — without this, a drill's
            # invented rows would answer a pull for somebody else's real ad account, the one way
            # this stand-in could put fiction into data a person believes.
            account_id = node.removeprefix("act_")
            own = {c["id"] for c in state["campaigns"] if c["account_id"] == account_id}
            rows = [row for row in state["insights"]
                    if row["level"] == level and row["campaign_id"] in own
                    and since <= row["date_start"] <= until]
        else:
            # Campaign-scoped: the imported path's per-campaign observations phase
            # (`{campaign_native_id}/insights?level=campaign|adset|ad`) — every level reads
            # through this one campaign node, never the child adset/ad node directly.
            rows = [row for row in state["insights"]
                    if row["level"] == level and row["campaign_id"] == node
                    and since <= row["date_start"] <= until]
        return {"data": rows}

    if edge not in _LIST_EDGES:
        # Bare `GET {id}` — no edge word, `edge` IS the id (see docstring). Used by
        # `external_page`'s `campaign`/`adset`/`ad` sections, `fetch_budgets` and
        # `fetch_ad_creatives`. Real Meta answers a deleted/unreadable id with `{"error": …}`,
        # not a 404 — `graph.py` already treats that as a per-id "no answer" for
        # `fetch_ad_creatives`/`fetch_budgets`, and as a hard `GraphError` for `external_page`.
        entity = _find_by_id(state, edge)
        if entity is None:
            return {"error": {"message": f"演練替身找不到節點 {edge}", "type": "DrillError",
                              "code": 100}}
        return entity

    return {"error": {"message": f"演練替身沒有實作這個端點：{url}", "type": "DrillError",
                      "code": 0}}


def install() -> None:
    """Point the running process's Graph client at this file. Call before app code runs."""
    from app.meta import graph
    graph.fetch_page = fake_fetch_page


# ---------------------------------------------------------------------------
# CLI: what the drill operator (playing "the human in Ads Manager") does
# ---------------------------------------------------------------------------

def _tree_nodes(brand_id: str) -> tuple[str, list]:
    """(org_id, top-level tree nodes) for the brand's campaigns that are waiting to be built
    on the platform. Drill 4 (2026-09-13): 投放中心 (F03/F04) keeps the tree as rows —
    `ads_campaign` → `ads_delivery_group` → `ads_ad` — so the mirror reads those; the campaign
    node is the Campaign itself (the manual path binds all three levels by exact name). Every
    `ready`/`live` campaign of the brand that is not yet bound becomes a platform campaign.
    Falls back to the retired schedule tree only when the brand has no ads campaign at all."""
    import app.main  # noqa: F401 — .env load + assembly, same reason as daily_pull's __main__
    from app.core.db import connection

    with connection() as conn:
        row = conn.execute("SELECT org_id FROM brand WHERE id = %s", (brand_id,)).fetchone()
        if row is None:
            raise SystemExit(f"找不到品牌 {brand_id}")
        org_id = row["org_id"]
        campaigns = conn.execute(
            "SELECT id, name FROM ads_campaign WHERE org_id = %s AND brand_id = %s"
            " AND status IN ('ready', 'live') AND local_state = 'unbound'"
            " ORDER BY created_at", (org_id, brand_id)).fetchall()
        if campaigns:
            nodes = []
            for campaign in campaigns:
                groups = conn.execute(
                    "SELECT id, name FROM ads_delivery_group WHERE campaign_id = %s"
                    " ORDER BY created_at", (campaign["id"],)).fetchall()
                children = []
                for group in groups:
                    ads = conn.execute(
                        "SELECT name FROM ads_ad WHERE group_id = %s ORDER BY created_at",
                        (group["id"],)).fetchall()
                    children.append({"name": group["name"],
                                     "children": [{"name": a["name"], "children": []}
                                                  for a in ads]})
                nodes.append({"name": campaign["name"], "children": children})
            return org_id, nodes
        from app.schedule import state as schedule_state
        from app.schedule import tree as tree_mod
        task_row, _running = schedule_state._display_task_row(
            conn, brand_id, schedule_state.TREE_TASK_TYPE)
        if task_row is None:
            raise SystemExit(
                f"品牌 {brand_id} 沒有待鏡射的 Campaign（要先「手動發布」），也沒有舊的活動樹")
        return org_id, tree_mod.tree_from_task_row(task_row)["nodes"]


def _bound_account_id(brand_id: str) -> str | None:
    """The account this brand actually bound in the product, so the mirror builds the
    campaigns where that brand's pull will look for them."""
    import app.main  # noqa: F401
    from app.core.db import connection
    with connection() as conn:
        row = conn.execute(
            "SELECT a.account_id FROM meta_ad_account a"
            " JOIN brand_meta_ad_account b ON b.ad_account_id = a.id"
            " WHERE b.brand_id = %s LIMIT 1", (brand_id,)).fetchone()
    return row["account_id"] if row else None


def cmd_reset() -> None:
    save({"accounts": list(DRILL_ACCOUNTS), "campaigns": [], "adsets": [], "ads": [],
          "insights": []})
    for account in DRILL_ACCOUNTS:
        print(f"演練帳戶 {account['account_id']}（{account['name']}）← {account['token']}")


def cmd_mirror(brand_id: str, append: bool = False) -> None:
    """Play the human who hand-builds the tree inside Ads Manager: every node becomes a
    platform entity with the same name, built PAUSED — the order the manual path prescribes
    (build closed, confirm the match, then turn on)."""
    _org_id, nodes = _tree_nodes(brand_id)
    state = load()
    if not state["accounts"]:
        state["accounts"] = list(DRILL_ACCOUNTS)
    account_id = _bound_account_id(brand_id)
    if account_id is None:
        # Drill 4 (J-3): falling back to accounts[0] put one persona's campaigns under another
        # persona's account. A brand with no bound account has nowhere to build; refuse.
        raise SystemExit(f"品牌 {brand_id} 還沒有指定廣告帳戶，先在產品裡把帳號勾給品牌再鏡射")
    seq = [0]

    existing = len([e for e in state["campaigns"] + state["adsets"] + state["ads"]
                    if e.get("brand_id") == brand_id]) if append else 0

    # Digits only, like a real Meta id: `graph.external_page` refuses anything else, so a mirrored
    # node built with the brand's own (alphanumeric) id suffix could be listed but never read back
    # (drill 5: the launch handoff's readback answered "no such object").
    brand_digits = int(hashlib.sha1(brand_id.encode()).hexdigest()[:8], 16) % 1_000_000

    def new_id(kind: str) -> str:
        seq[0] += 1
        return f"{kind}{brand_digits:06d}{existing + seq[0]:04d}"

    campaigns, adsets, ads = [], [], []
    for node in nodes:
        cid = new_id("120")
        campaigns.append({"id": cid, "account_id": account_id, "brand_id": brand_id,
                          "name": node["name"], "effective_status": "PAUSED"})
        for child in node["children"]:
            sid = new_id("230")
            adsets.append({"id": sid, "campaign_id": cid, "brand_id": brand_id,
                           "name": child["name"], "effective_status": "PAUSED"})
            for grandchild in child["children"]:
                ads.append({"id": new_id("340"), "adset_id": sid, "campaign_id": cid,
                            "brand_id": brand_id, "name": grandchild["name"],
                            "effective_status": "PAUSED"})

    # Replace only this brand's entities. Every persona shares one invented account, so a
    # wholesale overwrite would delete the previous persona's platform out from under them.
    # `--append` keeps what is already there: a second wave is built alongside the first,
    # the way a person adds a campaign rather than deleting last month's.
    def others(bucket: str) -> list:
        return [e for e in state[bucket]
                if append or e.get("brand_id") != brand_id]

    keep_ids = {c["id"] for c in others("campaigns")}
    state["insights"] = [r for r in state["insights"] if r["campaign_id"] in keep_ids]
    state["campaigns"] = others("campaigns") + campaigns
    state["adsets"] = others("adsets") + adsets
    state["ads"] = others("ads") + ads
    save(state)
    print(f"鏡射完成：活動 {len(campaigns)}、組合 {len(adsets)}、廣告 {len(ads)}")
    for ad in ads:
        print(f"  廣告 {ad['id']}  {ad['name']}")


def cmd_spend(brand_id: str, round_no: int, days: int, daily_total: float = 1000.0,
              new_only: bool = False, today: date | None = None) -> None:
    """Invent `days` days of insights ending today. Half the ads win, half lose, and which
    half swaps between rounds — a designed contrast, so that the diagnosis has something real
    to find and the second round's numbers are not the first round's numbers again.

    The ROAS values are invented. They say nothing about whether the product's judgement is
    correct; they only let the pipeline carry a signal end to end.
    """
    state = load()
    ads = sorted((a for a in state["ads"] if a.get("brand_id") == brand_id),
                 key=lambda a: a["id"])
    if new_only:
        # Never rewrite days that already happened. A second wave gets its own numbers; the
        # first wave's history stays exactly as it was observed.
        already = {r.get("ad_id") for r in state["insights"] if r["level"] == "ad"}
        ads = [a for a in ads if a["id"] not in already]
    if not ads:
        raise SystemExit(f"演練替身裡沒有 {brand_id} 的廣告，先跑 mirror")
    today = today or date.today()
    # Alternate rather than split the list in half: a half-split follows the ad-set boundary,
    # so every winner would share one ad set and the contrast would say nothing about the
    # creative coordinates. Alternating puts winners and losers inside each ad set.
    winners = {a["id"] for i, a in enumerate(ads) if i % 2 == 0}
    if round_no >= 2:
        winners = {a["id"] for a in ads} - winners

    rows = []
    for offset in range(days):
        day = (today - timedelta(days=offset)).isoformat()
        per_campaign: dict = {}
        per_adset: dict = {}
        for index, ad in enumerate(ads):
            won = ad["id"] in winners
            # Stay near the brand's own daily budget. Invented spend an order of magnitude
            # above what the user approved reads as a money bug, and a persona would stop
            # the run over it — the fixture would have manufactured its own finding.
            share = daily_total / len(ads)
            spend = round(share * (0.8 + 0.4 * index / max(1, len(ads) - 1)) + 3 * offset)
            roas = (3.4 if round_no == 1 else 3.9) if won else (0.7 if round_no == 1 else 0.6)
            impressions = spend * 24
            clicks = spend // 3
            rows.append({
                "level": "ad", "date_start": day,
                "campaign_id": ad["campaign_id"], "adset_id": ad["adset_id"],
                "ad_id": ad["id"], "ad_name": ad["name"],
                "spend": f"{spend}.00", "impressions": impressions, "clicks": clicks,
                "purchase_roas": [{"action_type": "omni_purchase", "value": f"{roas}"}],
            })
            acc = per_adset.setdefault(ad["adset_id"], [ad["campaign_id"], 0, 0, 0, 0.0])
            acc[1] += spend
            acc[2] += impressions
            acc[3] += clicks
            acc[4] += spend * roas
            acc2 = per_campaign.setdefault(ad["campaign_id"], [0, 0, 0, 0.0])
            acc2[0] += spend
            acc2[1] += impressions
            acc2[2] += clicks
            acc2[3] += spend * roas

        # The platform reports every level; so does the puller. Roll the ad rows up rather
        # than inventing a second, inconsistent set of numbers.
        name_of = {s["id"]: s["name"] for s in state["adsets"]}
        for adset_id, (campaign_id, spend, impressions, clicks, revenue) in per_adset.items():
            rows.append({
                "level": "adset", "date_start": day, "campaign_id": campaign_id,
                "adset_id": adset_id, "adset_name": name_of.get(adset_id, adset_id),
                "spend": f"{spend}.00", "impressions": impressions, "clicks": clicks,
                "purchase_roas": [{"action_type": "omni_purchase",
                                   "value": f"{revenue / spend:.4f}"}],
            })
        cname_of = {c["id"]: c["name"] for c in state["campaigns"]}
        for campaign_id, (spend, impressions, clicks, revenue) in per_campaign.items():
            rows.append({
                "level": "campaign", "date_start": day, "campaign_id": campaign_id,
                "campaign_name": cname_of.get(campaign_id, campaign_id),
                "spend": f"{spend}.00", "impressions": impressions, "clicks": clicks,
                "purchase_roas": [{"action_type": "omni_purchase",
                                   "value": f"{revenue / spend:.4f}"}],
            })

    own = {a["id"] for a in ads}
    state["insights"] = [r for r in state["insights"]
                         if r.get("ad_id") not in own
                         and not (r["level"] != "ad"
                                  and r["campaign_id"] in {a["campaign_id"] for a in ads})] + rows
    # Money is being spent, so this brand's entities are no longer paused.
    for bucket in ("campaigns", "adsets", "ads"):
        for entity in state[bucket]:
            if entity.get("brand_id") == brand_id:
                entity["effective_status"] = "ACTIVE"
    save(state)
    print(f"第 {round_no} 輪花費已寫入替身：{len(rows)} 列，{days} 天，"
          f"贏家 {len(winners)} 則 / 共 {len(ads)} 則")
    for ad in ads:
        print(f"  {'贏' if ad['id'] in winners else '賠'}  {ad['name']}")


def cmd_pull(org_id: str, since: str, until: str | None) -> None:
    """Run the product's own backfill with the stand-in installed — this is the only way
    invented numbers reach `meta_entity_spend`."""
    install()
    import app.main  # noqa: F401
    from app.core import settings as coresettings
    from app.core.db import connection
    from app.meta import daily_pull

    with connection() as conn:
        end = date.fromisoformat(until) if until else coresettings.today_for_org(
            conn, org_id=org_id)
    written = daily_pull.backfill(org_id, date.fromisoformat(since), end)
    print(f"組織 {org_id}：{since} ~ {end} 拉取完成，寫入 {written} 列。")


def cmd_selfcheck() -> None:
    """The one thing that must never break: a pull for somebody else's ad account must come
    back empty, not with this drill's invented rows."""
    global load
    original = load
    load = lambda: {  # noqa: E731 — a stub, not a design
        "accounts": list(DRILL_ACCOUNTS),
        "campaigns": [{"id": "c1", "account_id": "900000000000001", "name": "甲",
                       "effective_status": "ACTIVE"}],
        "adsets": [], "ads": [],
        "insights": [{"level": "ad", "date_start": "2026-09-03", "campaign_id": "c1",
                      "ad_id": "a1", "spend": "100.00"}],
    }
    try:
        params = {"level": "ad", "time_range": '{"since":"2026-09-01","until":"2026-09-30"}'}
        mine = fake_fetch_page("https://x/act_900000000000001/insights",
                               params=params, headers={})
        theirs = fake_fetch_page("https://x/act_368741390835357/insights",
                                  params=params, headers={})
        assert len(mine["data"]) == 1, mine
        assert theirs["data"] == [], theirs
        old = fake_fetch_page("https://x/act_900000000000001/insights", headers={},
                              params={"level": "ad",
                                      "time_range": '{"since":"2026-08-01","until":"2026-08-31"}'})
        assert old["data"] == [], old
    finally:
        load = original
    print("selfcheck ok")


def cmd_show() -> None:
    state = load()
    print(json.dumps({k: len(v) for k, v in state.items()}, ensure_ascii=False))


# ---------------------------------------------------------------------------
# CLI: the imported-campaign path (operator plays "Meta"; no brand, no DB)
# ---------------------------------------------------------------------------

# F18 discovery numeric defaults (`app/ads/triage.py`): STOP_LOSS_SPEND_MULTIPLE=3,
# MIN_RESULT_EVENTS=10, FLAT_BAND=0.20, first window=7 days. `seed-imported` shapes fixture spend/
# purchases against an ASSUMED campaign target of 450 TWD/purchase — the drill's operator (or the
# persona) still has to type that target into the product; this file never writes it.
_ASSUMED_TARGET = 450.0


def cmd_seed_imported(token: str, account: str, currency: str, scenario: str,
                      today: date | None = None) -> None:
    if scenario != "loop5":
        raise SystemExit(f"演練替身只實作了 loop5 情境，收到：{scenario}")
    if not account.isdigit():
        raise SystemExit("帳號 id 必須是純數字（比照 Meta 的 account_id，不含 act_ 前綴）。")
    state = load()
    _upsert_account(state, token, account, currency)
    today = today or date.today()
    cutoff = today - timedelta(days=1)  # "ending yesterday"

    campaign_id = _next_id(state, "campaign")
    campaign = {
        "id": campaign_id, "account_id": account, "name": "loop5 演練活動",
        "objective": SALES_OBJECTIVE, "effective_status": "ACTIVE",
        "start_time": (cutoff - timedelta(days=90)).isoformat() + "T00:00:00+0800",
    }
    state["campaigns"].append(campaign)

    adset_a = {
        "id": _next_id(state, "adset"), "campaign_id": campaign_id, "account_id": account,
        "name": "loop5 廣告組合 A", "effective_status": "ACTIVE",
        "start_time": campaign["start_time"], "daily_budget": "1000",
    }
    adset_b = {
        "id": _next_id(state, "adset"), "campaign_id": campaign_id, "account_id": account,
        "name": "loop5 廣告組合 B", "effective_status": "ACTIVE",
        "start_time": campaign["start_time"], "daily_budget": "600",
    }
    state["adsets"].extend([adset_a, adset_b])

    def make_ad(adset, name, status, recent, old):
        ad_id = _next_id(state, "ad")
        ad = {
            "id": ad_id, "adset_id": adset["id"], "campaign_id": campaign_id,
            "account_id": account, "name": name, "effective_status": status,
            "creative": {
                "id": ad_id + "1", "title": f"{name}｜標題",
                "body": f"{name}｜文案", "image_url": "https://example.invalid/loop5.jpg",
                "thumbnail_url": "https://example.invalid/loop5-thumb.jpg",
            },
            "_daily_spend_recent": recent[0], "_daily_purchases_recent": recent[1],
            "_daily_spend_old": old[0], "_daily_purchases_old": old[1],
        }
        state["ads"].append(ad)
        return ad

    # Numbers below are worked out against `_ASSUMED_TARGET` and `app/ads/triage.py`'s own
    # constants — see the module docstring's CLI section and the drill task for the derivation.
    stop_loss_ad = make_ad(adset_a, "loop5 停損廣告", "ACTIVE", (250.0, 0.0), (250.0, 0.0))
    worse_ad = make_ad(adset_a, "loop5 變差廣告", "ACTIVE",
                       (4000 / 7, 10 / 7), (3000 / 7, 10 / 7))
    insufficient_ads = [
        make_ad(adset_a, "loop5 資料不足廣告 1", "ACTIVE", (40.0, 0.0), (40.0, 0.0)),
        make_ad(adset_a, "loop5 資料不足廣告 2", "ACTIVE", (40.0, 0.0), (40.0, 0.0)),
    ]
    scale_ads = [
        make_ad(adset_b, f"loop5 可加預算廣告 {i}", "ACTIVE", (100.0, 2.0), (100.0, 2.0))
        for i in range(1, 5)
    ]
    paused_ads = [
        make_ad(adset_a, "loop5 已暫停廣告 1", "PAUSED", (0.0, 0.0), (0.0, 0.0)),
        make_ad(adset_b, "loop5 已暫停廣告 2", "PAUSED", (0.0, 0.0), (0.0, 0.0)),
    ]

    all_ads = [stop_loss_ad, worse_ad, *insufficient_ads, *scale_ads, *paused_ads]
    for offset in range(56):
        day = cutoff - timedelta(days=offset)

        def rate_of(ad, offset=offset):
            key = "_daily_spend_recent" if offset < 7 else "_daily_spend_old"
            pkey = "_daily_purchases_recent" if offset < 7 else "_daily_purchases_old"
            return ad[key], ad[pkey]

        _write_day(state, campaign, account, currency, all_ads, day, rate_of)
    state["_today"] = cutoff.isoformat()
    save(state)

    print(f"loop5 已灌入：活動 {campaign_id}，組合 {adset_a['id']}（日預算1000）/"
          f" {adset_b['id']}（日預算600），56 天成效至 {cutoff}")
    print(f"  停損 stop_loss    -> {stop_loss_ad['id']}  {stop_loss_ad['name']}")
    print(f"  變差 worse        -> {worse_ad['id']}  {worse_ad['name']}")
    for ad in insufficient_ads:
        print(f"  資料不足 insufficient -> {ad['id']}  {ad['name']}")
    for ad in scale_ads:
        print(f"  可加預算 scale_budget（組合 {adset_b['id']}）-> {ad['id']}  {ad['name']}")
    for ad in paused_ads:
        print(f"  已暫停（不參與判讀）-> {ad['id']}  {ad['name']}")
    print(f"  過多廣告 cleanup  -> 整個活動 {campaign_id}（8 則投遞中，日預算合計 1600，"
          f"假設目標 {_ASSUMED_TARGET:.0f} 只撐得住 1 則）")
    print("  上述判讀假設使用者已在產品內把這個活動的目標設成每次購買 450 TWD。")


def _find_ad(state, ad_id):
    for ad in state["ads"]:
        if ad["id"] == ad_id:
            return ad
    raise SystemExit(f"演練替身裡沒有廣告 {ad_id}")


def _find_adset(state, adset_id):
    for adset in state["adsets"]:
        if adset["id"] == adset_id:
            return adset
    raise SystemExit(f"演練替身裡沒有廣告組合 {adset_id}")


def cmd_pause(ad_id: str) -> None:
    state = load()
    ad = _find_ad(state, ad_id)
    ad["effective_status"] = "PAUSED"
    save(state)
    print(f"已暫停 {ad_id}  {ad['name']}")


def cmd_activate(ad_id: str) -> None:
    state = load()
    ad = _find_ad(state, ad_id)
    ad["effective_status"] = "ACTIVE"
    save(state)
    print(f"已開啟 {ad_id}  {ad['name']}")


def cmd_set_budget(adset_id: str, amount: float) -> None:
    state = load()
    adset = _find_adset(state, adset_id)
    adset["daily_budget"] = str(int(amount)) if amount == int(amount) else str(amount)
    save(state)
    print(f"{adset_id}  {adset['name']} 日預算改成 {adset['daily_budget']}")


def cmd_edit_copy(ad_id: str, title: str | None, body: str | None,
                  titles: str | None, bodies: str | None) -> None:
    state = load()
    ad = _find_ad(state, ad_id)
    creative = ad.setdefault("creative", {})
    if title is not None:
        creative["title"] = title
    if body is not None:
        creative["body"] = body
    if titles is not None or bodies is not None:
        # Dynamic/catalog shape (`app/ads/adapters/meta_read.py::copy_variants`) — Meta's own
        # `asset_feed_spec.titles[]/bodies[].text` variant arrays, the only text a dynamic
        # creative exposes for editing.
        creative["asset_feed_spec"] = {
            "titles": [{"text": t} for t in json.loads(titles)] if titles else [],
            "bodies": [{"text": b} for b in json.loads(bodies)] if bodies else [],
        }
    save(state)
    print(f"{ad_id}  {ad['name']} 素材已更新")


def cmd_add_ad(adset_id: str, name: str, title: str, body: str, image_url: str) -> None:
    state = load()
    adset = _find_adset(state, adset_id)
    ad = {
        "id": _next_id(state, "ad"), "adset_id": adset_id, "campaign_id": adset["campaign_id"],
        "account_id": adset["account_id"], "name": name, "effective_status": "ACTIVE",
        "creative": {"title": title, "body": body, "image_url": image_url},
        # A brand-new ad has no track record yet: known-zero purchases so it reads as genuinely
        # unproven (資料不足), never as an unknown/undefined result (see triage.py's
        # `_stop_loss_hit`/`_sample_gate` — a KNOWN zero is required, never an absent action).
        "_daily_spend_recent": 80.0, "_daily_purchases_recent": 0.0,
        "_daily_spend_old": 80.0, "_daily_purchases_old": 0.0,
    }
    state["ads"].append(ad)
    save(state)
    print(f"新廣告 {ad['id']}  {name}（掛在 {adset_id}）")


def cmd_advance_days(n: int, spend_scale: float) -> None:
    state = load()
    if not state.get("_today"):
        raise SystemExit("還沒有任何成效歷史可以往前推——先跑 seed-imported。")
    last_day = date.fromisoformat(state["_today"])
    imported_ads = [ad for ad in state["ads"] if "_daily_spend_recent" in ad]
    if not imported_ads:
        raise SystemExit("演練替身裡沒有匯入路徑的廣告——先跑 seed-imported。")
    by_campaign: dict = {}
    for ad in imported_ads:
        by_campaign.setdefault(ad["campaign_id"], []).append(ad)
    for offset in range(1, n + 1):
        day = last_day + timedelta(days=offset)

        def rate_of(ad, spend_scale=spend_scale):
            return (ad["_daily_spend_recent"] * spend_scale,
                    ad["_daily_purchases_recent"] * spend_scale)

        for campaign_id, ads in by_campaign.items():
            campaign = next(c for c in state["campaigns"] if c["id"] == campaign_id)
            account_id = campaign["account_id"]
            account = next(a for a in state["accounts"] if a["account_id"] == account_id)
            _write_day(state, campaign, account_id, account["currency"], ads, day, rate_of)
    state["_today"] = (last_day + timedelta(days=n)).isoformat()
    save(state)
    active = sum(1 for ad in imported_ads if ad["effective_status"] == "ACTIVE")
    paused = len(imported_ads) - active
    print(f"往前推進 {n} 天，至 {state['_today']}：{active} 則投遞中的廣告灌了新成效，"
          f"{paused} 則已暫停（沒有新的列）。")


def cmd_selfcheck_imported() -> None:
    """Prove the adapter, not the network: install the stand-in, seed one campaign, and run every
    real read the imported-campaign path and its readbacks use
    (`app.meta.graph.external_page`/`fetch_ad_creatives`/single-node reads) through
    `app/ads/adapters/meta_read.py`'s own pure functions (`_entity`/`observation`/
    `creative_summary`) — no conn, no DB, no HTTP. `app.main` is imported first only so this
    behaves the same under the repo's `.env` as every other drill command (same reason
    `cmd_pull` does it), even though nothing called below actually needs a database."""
    import app.main  # noqa: F401 — .env load, same reason as cmd_pull's __main__
    from app.ads.adapters import meta_read
    from app.meta import graph
    from app.meta import repository as meta_repository

    install()
    state = load()
    if not any(c.get("objective") for c in state["campaigns"]):
        cmd_seed_imported("EAAG-drill-token-selfcheck", "900099999999999", "TWD", "loop5")
        state = load()
    campaign = next(c for c in state["campaigns"] if c.get("objective"))
    account_row = next(a for a in state["accounts"] if a["account_id"] == campaign["account_id"])
    account = {"account_id": account_row["account_id"], "currency": account_row["currency"],
              "timezone_name": account_row["timezone_name"]}
    token = account_row["token"]
    checked = 0

    campaigns_page = graph.external_page(token, account["account_id"], "campaigns")
    assert campaigns_page["data"], "campaigns 頁是空的"
    for item in campaigns_page["data"]:
        meta_read._entity(item, "campaign", account)
        checked += 1

    campaign_page = graph.external_page(token, account["account_id"], "campaign",
                                        native_id=campaign["id"])
    assert len(campaign_page["data"]) == 1
    meta_read._entity(campaign_page["data"][0], "campaign", account)
    checked += 1

    adsets_page = graph.external_page(token, account["account_id"], "adsets",
                                      native_id=campaign["id"])
    assert adsets_page["data"], "adsets 頁是空的"
    for item in adsets_page["data"]:
        meta_read._entity(item, "adset", account)
        checked += 1
        node = graph.external_page(token, account["account_id"], "adset", native_id=item["id"])
        meta_read._entity(node["data"][0], "adset", account)
        checked += 1

    ads_page = graph.external_page(token, account["account_id"], "ads", native_id=campaign["id"])
    assert ads_page["data"], "ads 頁是空的"
    ad_ids = [item["id"] for item in ads_page["data"]]
    for item in ads_page["data"]:
        meta_read._entity(item, "ad", account)
        checked += 1

    creatives_page = graph.external_page(token, account["account_id"], "creatives",
                                         native_id=campaign["id"])
    assert creatives_page["data"], "creatives 頁是空的"
    for item in creatives_page["data"]:
        meta_read.creative_summary(item.get("creative"))
        checked += 1

    node = graph.external_page(token, account["account_id"], "ad", native_id=ad_ids[0])
    meta_read._entity(node["data"][0], "ad", account)
    checked += 1

    creatives = graph.fetch_ad_creatives(token, ad_ids)
    assert all(creatives[i] is not None for i in ad_ids), creatives
    checked += len(creatives)
    missing = graph.fetch_ad_creatives(token, ["900000000000099"])
    assert missing["900000000000099"] is None, "刪除／讀不到的廣告該回 None，不是丟例外"

    budgets = graph.fetch_budgets(token, [item["id"] for item in adsets_page["data"]])
    assert all(b["daily_budget"] for b in budgets.values()), budgets
    checked += len(budgets)

    end = date.fromisoformat(state["_today"])
    start = end - timedelta(days=6)
    for level in ("campaign", "adset", "ad"):
        obs_page = graph.external_page(token, account["account_id"], "insights",
                                       native_id=campaign["id"], level=level,
                                       start=start, end=end)
        assert obs_page["data"], f"{level} 層 insights 是空的"
        for item in obs_page["data"]:
            meta_read.observation(item, level, account, SALES_OBJECTIVE)
            checked += 1

    monthly_start = end.replace(day=1)
    monthly_page = graph.external_page(token, account["account_id"], "monthly",
                                       start=monthly_start, end=end)
    for item in monthly_page["data"]:
        purchase = meta_repository.external_purchase_values(
            item.get("actions"), item.get("action_values")
        )
        assert purchase["purchases"] is not None
        meta_read.observation(item, "campaign", account)
        checked += 1

    print(f"selfcheck-imported ok（{checked} 筆讀回都轉成了 entity／observation，沒有例外）")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(prog="python -m scripts.drill.fake_meta")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("reset")
    p_mirror = sub.add_parser("mirror")
    p_mirror.add_argument("brand_id")
    p_mirror.add_argument("--append", action="store_true",
                          help="保留這個品牌已經在替身上的活動，只加新的（第二波用）")
    p_spend = sub.add_parser("spend")
    p_spend.add_argument("brand_id")
    p_spend.add_argument("--round", type=int, default=1)
    p_spend.add_argument("--days", type=int, default=5)
    p_spend.add_argument("--new-only", action="store_true",
                         help="只給還沒有任何花費紀錄的廣告灌數字（第二波用，不改寫第一波的歷史）")
    p_spend.add_argument("--daily-total", type=float, default=1000.0,
                         help="這個品牌一天總共花多少（貼近使用者自己設的日預算）")
    p_pull = sub.add_parser("pull")
    p_pull.add_argument("org_id")
    p_pull.add_argument("--since", required=True)
    p_pull.add_argument("--until")
    sub.add_parser("show")
    sub.add_parser("selfcheck")

    p_seed = sub.add_parser("seed-imported")
    p_seed.add_argument("--token", required=True)
    p_seed.add_argument("--account", required=True, help="純數字帳號 id，不含 act_ 前綴")
    p_seed.add_argument("--currency", default="TWD")
    p_seed.add_argument("--scenario", default="loop5")
    p_pause = sub.add_parser("pause")
    p_pause.add_argument("ad_id")
    p_activate = sub.add_parser("activate")
    p_activate.add_argument("ad_id")
    p_budget = sub.add_parser("set-budget")
    p_budget.add_argument("adset_id")
    p_budget.add_argument("amount", type=float)
    p_copy = sub.add_parser("edit-copy")
    p_copy.add_argument("ad_id")
    p_copy.add_argument("--title")
    p_copy.add_argument("--body")
    p_copy.add_argument("--titles", help="JSON 陣列（動態素材多版本標題）")
    p_copy.add_argument("--bodies", help="JSON 陣列（動態素材多版本文案）")
    p_add_ad = sub.add_parser("add-ad")
    p_add_ad.add_argument("adset_id")
    p_add_ad.add_argument("--name", required=True)
    p_add_ad.add_argument("--title", required=True)
    p_add_ad.add_argument("--body", required=True)
    p_add_ad.add_argument("--image-url", required=True)
    p_advance = sub.add_parser("advance-days")
    p_advance.add_argument("n", type=int)
    p_advance.add_argument("--spend-scale", type=float, default=1.0)
    sub.add_parser("selfcheck-imported")

    args = parser.parse_args()

    if args.cmd == "reset":
        cmd_reset()
    elif args.cmd == "mirror":
        cmd_mirror(args.brand_id, args.append)
    elif args.cmd == "spend":
        cmd_spend(args.brand_id, args.round, args.days, args.daily_total, args.new_only)
    elif args.cmd == "pull":
        cmd_pull(args.org_id, args.since, args.until)
    elif args.cmd == "show":
        cmd_show()
    elif args.cmd == "selfcheck":
        cmd_selfcheck()
    elif args.cmd == "seed-imported":
        cmd_seed_imported(args.token, args.account, args.currency, args.scenario)
    elif args.cmd == "pause":
        cmd_pause(args.ad_id)
    elif args.cmd == "activate":
        cmd_activate(args.ad_id)
    elif args.cmd == "set-budget":
        cmd_set_budget(args.adset_id, args.amount)
    elif args.cmd == "edit-copy":
        cmd_edit_copy(args.ad_id, args.title, args.body, args.titles, args.bodies)
    elif args.cmd == "add-ad":
        cmd_add_ad(args.adset_id, args.name, args.title, args.body, args.image_url)
    elif args.cmd == "advance-days":
        cmd_advance_days(args.n, args.spend_scale)
    elif args.cmd == "selfcheck-imported":
        cmd_selfcheck_imported()
