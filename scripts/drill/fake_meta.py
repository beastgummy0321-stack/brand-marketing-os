"""scripts/drill/fake_meta.py — a stand-in for the Meta Graph API, for usability drills only.

WHY THIS EXISTS. The ad loop's steps 6-8 need a human to hand-build campaigns inside Meta Ads
Manager and then wait for real money to be spent. A persona drill cannot do either. This module
replaces the single network edge `app.meta.graph.fetch_page` (the same seam the unit tests
replace by name) with a reader over a JSON state file, so that binding (step 7) and the spend
pull (step 8) run their real code paths against invented platform data.

NOT A PRODUCT PATH. Nothing under `app/` imports this file, and nothing here writes to the
database directly — spend reaches `meta_entity_spend` only by way of the real
`app.meta.daily_pull.backfill`. Delete this directory and the product is unchanged.

State file (`.scratch/drill/meta_state.json`, override with DRILL_META_STATE):

    {"accounts": [{account_id, name, currency, timezone_name}],
     "campaigns": [{id, account_id, name, effective_status}],
     "adsets":    [{id, campaign_id, name, effective_status}],
     "ads":       [{id, adset_id, campaign_id, name, effective_status}],
     "insights":  [{level, date_start, campaign_id, adset_id, ad_id, <level>_name,
                    spend, impressions, clicks, purchase_roas}]}

CLI:
    python -m scripts.drill.fake_meta reset
    python -m scripts.drill.fake_meta mirror <brand_id>          # tree -> platform entities
    python -m scripts.drill.fake_meta spend <brand_id> --round N # invent insights
    python -m scripts.drill.fake_meta pull <org_id> --since YYYY-MM-DD
    python -m scripts.drill.fake_meta show
"""

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
# the fake network edge
# ---------------------------------------------------------------------------

def fake_fetch_page(url: str, *, params: dict | None, headers: dict) -> dict:
    """Drop-in for `app.meta.graph.fetch_page`. Returns one page, never a `paging.next` —
    the drill's data is small enough that paging adds nothing but a way to be wrong."""
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
        return {"data": [{"id": c["id"], "name": c["name"],
                          "effective_status": c["effective_status"]}
                         for c in state["campaigns"] if c["account_id"] == account_id]}

    if edge == "adsets":
        return {"data": [{"id": s["id"], "name": s["name"],
                          "effective_status": s["effective_status"]}
                         for s in state["adsets"] if s["campaign_id"] == node]}

    if edge == "ads":
        return {"data": [{"id": a["id"], "name": a["name"],
                          "effective_status": a["effective_status"]}
                         for a in state["ads"] if a["adset_id"] == node]}

    if edge == "insights":
        # Filter by account as well as level and date. Without this, a drill's invented rows
        # would answer a pull for somebody else's real ad account — the one way this stand-in
        # could put fiction into data a person believes.
        account_id = node.removeprefix("act_")
        own = {c["id"] for c in state["campaigns"] if c["account_id"] == account_id}
        level = (params or {}).get("level")
        window = json.loads((params or {}).get("time_range") or "{}")
        since = window.get("since", "0000-01-01")
        until = window.get("until", "9999-12-31")
        return {"data": [row for row in state["insights"]
                         if row["level"] == level and row["campaign_id"] in own
                         and since <= row["date_start"] <= until]}

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
    """(org_id, top-level tree nodes) for the brand's current tree task."""
    import app.main  # noqa: F401 — .env load + assembly, same reason as daily_pull's __main__
    from app.core.db import connection
    from app.schedule import state as schedule_state
    from app.schedule import tree as tree_mod

    with connection() as conn:
        row = conn.execute("SELECT org_id FROM brand WHERE id = %s", (brand_id,)).fetchone()
        if row is None:
            raise SystemExit(f"找不到品牌 {brand_id}")
        org_id = row["org_id"]
        task_row, _running = schedule_state._display_task_row(
            conn, brand_id, schedule_state.TREE_TASK_TYPE)
        if task_row is None:
            raise SystemExit(f"品牌 {brand_id} 還沒有展開活動樹，沒有東西可以鏡射")
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
    account_id = _bound_account_id(brand_id) or state["accounts"][0]["account_id"]
    seq = [0]

    existing = len([e for e in state["campaigns"] + state["adsets"] + state["ads"]
                    if e.get("brand_id") == brand_id]) if append else 0

    def new_id(kind: str) -> str:
        seq[0] += 1
        return f"{kind}{brand_id[-6:]}{existing + seq[0]:04d}"

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
