"""app/ads/outcome.py — F03-I11: money spent finds its campaign without any day-splitting rule
(§0 the "outcome" link). Private to app/ads (container contract §1): only `routes.py` imports
this.

`ingest_meta()` reads `app/meta/repository.py::daily_entity_spend` (the module's only public
read for this) once per level (`adset` for groups, `ad` for ads) and upserts `ads_outcome_daily`
rows keyed by `(entity_kind, entity_id, day)` — the unique index the table already carries.
Spend that matches no bound entity of THIS campaign is simply not written: it is not invented
into a campaign it never belonged to. 重疊分帳 does not exist here — a bound entity belongs to
exactly one campaign; if the data says otherwise (two campaigns bound to the same platform
entity) that is a binding bug and ingest refuses, naming both campaigns, rather than silently
picking one.

`purchases`: `daily_entity_spend` does not return a usable purchase count (spend/impressions/
clicks/roas/currency only — see the module docstring's ADR 0057 note on `actions` staying raw
JSON one layer up). Per this ticket's own "Blocked if": purchases stay untracked for
Meta-sourced rows in F03 rather than inventing them from ROAS and an assumed order value.
`revenue` is `spend * roas` when the pulled row's `roas` is tracked, else untracked too.

Ceiling (ponytail): `ads_outcome_daily.purchases`/`revenue` are `NOT NULL DEFAULT 0` (frozen
schema, F03-I01) — there is no per-row "tracked" flag. Meta rows therefore physically store 0
for both when untracked; `summary()` below treats **every** Meta-sourced row's purchases as
untracked outright (the "Blocked if" instruction — Meta purchases are never real in F03) and
treats a row's revenue as untracked when it is exactly 0 (a real $0 revenue day on a real spend
is indistinguishable from "untracked" without a schema change; add a `revenue_tracked` column if
that precision is ever needed). Simulated rows never hit this ambiguity — `generate_outcomes()`
always writes real, non-zero revenue/purchases for the group-level row it creates.
"""

from datetime import date, timedelta

from app.core import settings as coresettings
from app.core.db import Conn, ConnProxy, new_id
from app.meta import repository as meta_repo

_AnyConn = Conn | ConnProxy


def sample_bucket(purchases: int, days: int) -> str:
    """低（< 10 purchases 或 < 3 天）／中（10–49）／高（>= 50）——分級死規則（F03 決策 3），
    never a percentage. 之後給建議（F04）跟學習分級（F03-I12）共用同一個定義。"""
    if purchases < 10 or days < 3:
        return "低"
    if purchases < 50:
        return "中"
    return "高"


def _upsert_outcome(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str, *,
                     entity_kind: str, entity_id: str, day: date, spend: float,
                     impressions: int, clicks: int, purchases: int, revenue: float,
                     currency: str, source: str) -> None:
    conn.execute(
        "INSERT INTO ads_outcome_daily (id, org_id, brand_id, campaign_id, entity_kind,"
        " entity_id, day, spend, impressions, clicks, purchases, revenue, currency, source)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
        " ON CONFLICT (entity_kind, entity_id, day) DO UPDATE SET"
        " spend = excluded.spend, impressions = excluded.impressions, clicks = excluded.clicks,"
        " purchases = excluded.purchases, revenue = excluded.revenue,"
        " currency = excluded.currency, source = excluded.source",
        (new_id("ado"), org_id, brand_id, campaign_id, entity_kind, entity_id, day, spend,
         impressions, clicks, purchases, revenue, currency, source),
    )


def _conflicting_campaigns(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str,
                            table: str, external_ids: list) -> None:
    """一個平台實體只能屬於一個 Campaign（§0「重疊分帳 does not exist here」）——這裡不是分帳
    規則，是綁定資料的一致性檢查：同一個 `external_id` 出現在兩個不同 Campaign 底下的列，
    代表綁定壞了，直接拒絕並講清楚是哪兩個 Campaign，不是各分一半。`table` 只會是這個模組
    自己的兩個常數之一（`ads_delivery_group`／`ads_ad`），不是外部輸入。"""
    if not external_ids:
        return
    rows = conn.execute(
        f"SELECT DISTINCT external_id, campaign_id FROM {table}"  # noqa: S608 — table 是模組常數
        " WHERE org_id = %s AND brand_id = %s AND external_id = ANY(%s)",
        (org_id, brand_id, list(external_ids)),
    ).fetchall()
    by_external: dict[str, set] = {}
    for row in rows:
        by_external.setdefault(row["external_id"], set()).add(row["campaign_id"])
    for external_id, campaign_ids in by_external.items():
        if len(campaign_ids) <= 1:
            continue
        names = conn.execute(
            "SELECT name FROM ads_campaign WHERE org_id = %s AND id = ANY(%s)"
            " ORDER BY created_at",
            (org_id, list(campaign_ids)),
        ).fetchall()
        name_list = "、".join(f"「{n['name']}」" for n in names)
        raise ValueError(
            f"平台上的同一個實體（{external_id}）同時被 {name_list} 認領，這是綁定資料本身的"
            "問題，不是分帳規則——請先修正綁定，成效才拉得出來。"
        )


def ingest_meta(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str, *,
                 start: date, end: date) -> None:
    """把 [start, end) 這段期間內、這個 Campaign 已綁定節點的 Meta 花費灌進
    `ads_outcome_daily`（`source='meta'`）——只讀 `app/meta/repository.py` 的公開函式，不碰
    `meta_*` 表（§0「Outcome ingest」）。沒有比對到綁定節點的列不進這個 Campaign（不是不存
    在，是不屬於它）。"""
    from app.ads import repository as ads_repo  # 延遲 import 避免循環（routes.py 已是入口）

    detail = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)
    if detail is None:
        raise ValueError("campaign_unknown")

    groups = [g for g in detail["groups"] if g["local_state"] == "bound" and g["external_id"]]
    ads = [
        a for g in detail["groups"] for a in g["ads"]
        if a["local_state"] == "bound" and a["external_id"]
    ]
    _conflicting_campaigns(
        conn, org_id, brand_id, campaign_id, "ads_delivery_group",
        [g["external_id"] for g in groups],
    )
    _conflicting_campaigns(
        conn, org_id, brand_id, campaign_id, "ads_ad", [a["external_id"] for a in ads],
    )

    account_ids = meta_repo.bound_account_ids_for_brand(conn, org_id, brand_id)
    if not account_ids:
        return  # 這個品牌還沒接 Meta 帳戶——沒有東西可拉，不是錯誤

    def _pull(level: str, entities: list, entity_kind: str) -> None:
        by_external = {e["external_id"]: e for e in entities}
        if not by_external:
            return
        for row in meta_repo.daily_entity_spend(
            conn, org_id, account_ids, start, end, level=level,
        ):
            entity = by_external.get(row["entity_id"])
            if entity is None:
                continue  # 這一列的錢不屬於這個 Campaign——不猜、不分、不寫
            revenue = round(row["spend"] * row["roas"], 2) if row["roas"] is not None else 0
            _upsert_outcome(
                conn, org_id, brand_id, campaign_id, entity_kind=entity_kind,
                entity_id=entity["id"], day=row["spend_date"], spend=row["spend"],
                impressions=row["impressions"], clicks=row["clicks"], purchases=0,
                revenue=revenue, currency=row["currency"], source="meta",
            )

    _pull("adset", groups, "group")
    _pull("ad", ads, "ad")


def _fetch_rows(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str,
                 entity_kind: str) -> list:
    rows = conn.execute(
        "SELECT * FROM ads_outcome_daily WHERE org_id = %s AND brand_id = %s"
        " AND campaign_id = %s AND entity_kind = %s ORDER BY day",
        (org_id, brand_id, campaign_id, entity_kind),
    ).fetchall()
    return [dict(r) for r in rows]


def _bucket(rows: list) -> dict:
    """跟 `app/schedule/performance.py::_bucket()` 同一套算法（再實作一份，不 import —
    container contract §5）：`roas`/optimistic 只算「有追蹤到營收」那一份花費當分母，
    `roas_conservative` 用**全部**花費當分母——兩個都是真的，只印一個是在說謊的另一半。
    購買數對 Meta 來源的列一律當未追蹤（`purchases` 恆為 0，§0「Blocked if」），有追蹤到的
    只剩模擬通路的列。"""
    spend = round(sum(float(r["spend"]) for r in rows), 2)
    impressions = sum(int(r["impressions"]) for r in rows)
    clicks = sum(int(r["clicks"]) for r in rows)

    tracked_purchase_rows = [r for r in rows if r["source"] != "meta"]
    purchases = (
        sum(int(r["purchases"]) for r in tracked_purchase_rows) if tracked_purchase_rows
        else None
    )

    revenue_tracked_rows = [r for r in rows if r["source"] != "meta" or float(r["revenue"]) != 0]
    revenue = None
    roas = None
    roas_conservative = None
    if revenue_tracked_rows:
        revenue = round(sum(float(r["revenue"]) for r in revenue_tracked_rows), 2)
        spend_tracked = sum(float(r["spend"]) for r in revenue_tracked_rows)
        roas = (revenue / spend_tracked) if spend_tracked else None
        roas_conservative = (revenue / spend) if spend else None

    cpa = (spend / purchases) if purchases else None
    ctr = (clicks / impressions) if impressions else None

    return {
        "spend": spend, "impressions": impressions, "clicks": clicks,
        "purchases": purchases, "revenue": revenue, "cpa": cpa, "ctr": ctr,
        "roas": roas, "roas_conservative": roas_conservative,
    }


def _daily_series(rows: list) -> list:
    by_day: dict[date, list] = {}
    for row in rows:
        by_day.setdefault(row["day"], []).append(row)
    return [{"day": day, **_bucket(day_rows)} for day, day_rows in sorted(by_day.items())]


def _coverage(conn: _AnyConn, org_id: str, detail: dict, ad_rows: list) -> dict:
    """有多少「廣告 x 天」沒有任何一列——只算已綁定、真的在投的廣告，期間是
    `start_date` 到 `min(end_date, today)`（跟 `simulated.generate_outcomes` 同一個窗）。"""
    bound_ads = [
        a for g in detail["groups"] for a in g["ads"]
        if a["local_state"] == "bound" and a["external_id"]
    ]
    start_date = detail["start_date"]
    if start_date is None or not bound_ads:
        return {"expected": 0, "missing": 0}
    end_date = detail["end_date"]
    today = coresettings.today_for_org(conn, org_id=org_id)
    window_end = min(end_date, today) if end_date is not None else today
    if window_end < start_date:
        return {"expected": 0, "missing": 0}
    days = (window_end - start_date).days + 1
    expected = days * len(bound_ads)
    present = {(r["entity_id"], r["day"]) for r in ad_rows}
    actual = sum(
        1 for ad in bound_ads
        for offset in range(days)
        if (ad["id"], start_date + timedelta(days=offset)) in present
    )
    return {"expected": expected, "missing": max(0, expected - actual)}


def summary(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str) -> dict:
    """成效分頁的整包 payload：campaign 層總計（只算 `entity_kind='group'`，§0「Money totals
    belong to the group level」）、每日序列、每投放組／每廣告一列（含花費占比）、資料覆蓋率
    跟最後更新時間。"""
    from app.ads import repository as ads_repo

    detail = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)
    if detail is None:
        raise ValueError("campaign_unknown")

    group_rows = _fetch_rows(conn, org_id, brand_id, campaign_id, "group")
    ad_rows = _fetch_rows(conn, org_id, brand_id, campaign_id, "ad")

    totals = _bucket(group_rows)
    daily = _daily_series(group_rows)

    group_total_spend = sum(float(r["spend"]) for r in group_rows) or 0.0
    by_group: dict[str, list] = {}
    for row in group_rows:
        by_group.setdefault(row["entity_id"], []).append(row)
    groups_table = []
    for group in detail["groups"]:
        rows = by_group.get(group["id"], [])
        bucket = _bucket(rows)
        bucket["group_id"] = group["id"]
        bucket["name"] = group["name"]
        bucket["spend_share"] = (bucket["spend"] / group_total_spend) if group_total_spend else None
        groups_table.append(bucket)

    ad_total_spend = sum(float(r["spend"]) for r in ad_rows) or 0.0
    by_ad: dict[str, list] = {}
    for row in ad_rows:
        by_ad.setdefault(row["entity_id"], []).append(row)
    ads_table = []
    for group in detail["groups"]:
        for ad in group["ads"]:
            rows = by_ad.get(ad["id"], [])
            bucket = _bucket(rows)
            bucket["ad_id"] = ad["id"]
            bucket["name"] = ad["name"]
            bucket["spend_share"] = (bucket["spend"] / ad_total_spend) if ad_total_spend else None
            ads_table.append(bucket)

    all_rows = group_rows + ad_rows
    last_data_at = max((r["created_at"] for r in all_rows), default=None)

    return {
        "totals": totals,
        "daily": daily,
        "groups": groups_table,
        "ads": ads_table,
        "coverage": _coverage(conn, org_id, detail, ad_rows),
        "last_data_at": last_data_at,
    }
