"""app/ads/repository.py — private DB access for the `ads_*` tables (F03-I01,
ARCHITECTURE.md §0/§2/§3/§4/§6). Private to app/ads (container contract §1): only
`routes.py`/`__init__.py` import this; nothing outside the package does.

Read shape: `list_campaigns` and `campaign_detail` are the **one** place `budget_total` is
derived (`sum(group.daily_budget) x days`) — `ads_campaign.budget_planned` is the adopted
scenario amount and is never recomputed here or anywhere else (F03 decision 4/§0 "One source
of truth for money after 採用").

Write shape (this issue): only `create_campaign` — groups/ads/actions/outcomes are written by
later issues (publish, bind, outcome ingest). This issue is the shared read contract.
"""

from app.core import cleanup
from app.core.db import Conn, ConnProxy, jsonb, new_id

_AnyConn = Conn | ConnProxy

_SUCCESS_METRICS = frozenset({"cpa", "roas", "purchases"})


def _budget_total(start_date, end_date, groups: list[dict]) -> float | None:
    """`sum(group.daily_budget) x days`, one definition (§0). `days` is inclusive of both
    ends (a one-day campaign still spends one day's budget); `None` when either bound is
    missing — there is nothing to derive a total from yet."""
    if start_date is None or end_date is None:
        return None
    days = (end_date - start_date).days + 1
    if days <= 0:
        return None
    daily_sum = sum(float(g["daily_budget"]) for g in groups)
    return round(daily_sum * days, 2)


def create_campaign(conn: _AnyConn, org_id: str, brand_id: str, campaign: dict, *,
                     created_by: str | None = None) -> dict:
    """寫一列 `ads_campaign`。`name`／`goal_text`／`objective`／`success_metric` 都是必填——
    `ValueError("field_unknown")` 帶欄位名在缺欄／空字串時；`success_metric` 不在
    CPA／ROAS／購買數之外一律 `ValueError("success_metric_unknown")`；`success_target` 可以是
    `None`（模型說不出有根據的數字），但若有值就必須是數字，非數字一律
    `ValueError("success_target_unknown")`。
    """
    for field in ("name", "goal_text", "objective"):
        value = campaign.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field}_unknown")
    success_metric = campaign.get("success_metric")
    if success_metric not in _SUCCESS_METRICS:
        raise ValueError("success_metric_unknown")
    success_target = campaign.get("success_target")
    if success_target is not None and (
        isinstance(success_target, bool) or not isinstance(success_target, (int, float))
    ):
        raise ValueError("success_target_unknown")

    campaign_id = new_id("adc")
    conn.execute(
        "INSERT INTO ads_campaign (id, org_id, brand_id, name, goal_text, objective,"
        " success_metric, success_target, success_basis, start_date, end_date, status,"
        " budget_planned, budget_scenario, budget_basis_json, context_json, constraints_json,"
        " created_by)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            campaign_id, org_id, brand_id, campaign["name"], campaign["goal_text"],
            campaign["objective"], success_metric, success_target,
            campaign.get("success_basis"), campaign.get("start_date"), campaign.get("end_date"),
            campaign.get("status", "draft"), campaign.get("budget_planned"),
            campaign.get("budget_scenario"), jsonb(campaign.get("budget_basis_json") or {}),
            jsonb(campaign.get("context_json") or {}),
            jsonb(campaign.get("constraints_json") or {}),
            created_by,
        ),
    )
    row = get_campaign(conn, org_id, brand_id, campaign_id)
    assert row is not None  # 剛剛才插入的那一列，一定讀得到
    return row


def get_campaign(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM ads_campaign WHERE org_id = %s AND brand_id = %s AND id = %s",
        (org_id, brand_id, campaign_id),
    ).fetchone()
    return dict(row) if row is not None else None


def _groups_for_campaign(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str) -> list:
    rows = conn.execute(
        "SELECT * FROM ads_delivery_group WHERE org_id = %s AND brand_id = %s"
        " AND campaign_id = %s ORDER BY created_at",
        (org_id, brand_id, campaign_id),
    ).fetchall()
    return [dict(r) for r in rows]


def list_campaigns(conn: _AnyConn, org_id: str, brand_id: str) -> list:
    """`GET /campaigns` 列表：每筆帶 `budget_total`（推導）跟一句成效摘要。"""
    rows = conn.execute(
        "SELECT * FROM ads_campaign WHERE org_id = %s AND brand_id = %s ORDER BY created_at DESC",
        (org_id, brand_id),
    ).fetchall()
    entries = []
    for row in rows:
        row = dict(row)
        groups = _groups_for_campaign(conn, org_id, brand_id, row["id"])
        outcome = _outcome_totals(conn, org_id, brand_id, row["id"])
        entries.append({
            "id": row["id"], "name": row["name"], "status": row["status"],
            "start_date": row["start_date"], "end_date": row["end_date"],
            "objective": row["objective"],
            "budget_planned": row["budget_planned"],
            "budget_total": _budget_total(row["start_date"], row["end_date"], groups),
            "outcome": outcome,
        })
    return entries


def _outcome_totals(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str) -> dict:
    """Campaign-level totals sum `entity_kind = 'group'` rows only. `ads_outcome_daily` also
    carries `entity_kind = 'ad'` rows (for the per-ad 花費占比), and those are never summed
    into a campaign total — summing both levels double-counts (§0 "money totals belong to the
    group level")."""
    row = conn.execute(
        "SELECT COALESCE(SUM(spend), 0) AS spend, COALESCE(SUM(purchases), 0) AS purchases,"
        " COALESCE(SUM(revenue), 0) AS revenue"
        " FROM ads_outcome_daily WHERE org_id = %s AND brand_id = %s AND campaign_id = %s"
        " AND entity_kind = 'group'",
        (org_id, brand_id, campaign_id),
    ).fetchone()
    return dict(row) if row is not None else {"spend": 0, "purchases": 0, "revenue": 0}


def campaign_detail(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str) -> dict | None:
    """`GET /campaigns/{c}`：整個五分頁工作區要讀的一份 dict——campaign 本身 + 投放組 +
    廣告（掛在各自的投放組下）+ 每個節點最新一筆 action + 成效小計。`budget_total` 是這裡
    推導的第二個地方跟 `list_campaigns` 共用同一個 `_budget_total()`，不重算第二套邏輯。
    """
    campaign = get_campaign(conn, org_id, brand_id, campaign_id)
    if campaign is None:
        return None

    groups = _groups_for_campaign(conn, org_id, brand_id, campaign_id)
    ad_rows = conn.execute(
        "SELECT * FROM ads_ad WHERE org_id = %s AND brand_id = %s AND campaign_id = %s"
        " ORDER BY created_at",
        (org_id, brand_id, campaign_id),
    ).fetchall()
    ads_by_group: dict[str, list] = {}
    for row in ad_rows:
        row = dict(row)
        ads_by_group.setdefault(row["group_id"], []).append(row)
    for group in groups:
        group["ads"] = ads_by_group.get(group["id"], [])

    latest_actions = conn.execute(
        "SELECT * FROM ads_action WHERE org_id = %s AND brand_id = %s AND campaign_id = %s"
        " ORDER BY created_at DESC LIMIT 20",
        (org_id, brand_id, campaign_id),
    ).fetchall()

    detail = dict(campaign)
    detail["groups"] = groups
    detail["budget_total"] = _budget_total(campaign["start_date"], campaign["end_date"], groups)
    detail["actions"] = [dict(a) for a in latest_actions]
    detail["outcome"] = _outcome_totals(conn, org_id, brand_id, campaign_id)
    return detail


# -- app.core.cleanup 登記（品牌刪除連鎖清資料，ARCHITECTURE.md §4） -------------------------

_CHILD_TABLES = (
    ("ads_outcome_daily", "投放中心成效"),
    ("ads_action", "投放中心操作紀錄"),
    ("ads_ad", "投放中心廣告"),
    ("ads_delivery_group", "投放中心投放組"),
    ("ads_campaign", "投放中心 Campaign"),
)


def _count_brand(conn: _AnyConn, brand_id: str) -> list:
    counts = []
    for table, label in _CHILD_TABLES:
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE brand_id = %s", (brand_id,)
        ).fetchone()
        counts.append((label, row["n"] if row is not None else 0))
    return counts


def _delete_brand(conn: _AnyConn, brand_id: str) -> dict:
    counts = dict(_count_brand(conn, brand_id))
    for table, _label in _CHILD_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE brand_id = %s", (brand_id,))
    return counts


cleanup.register(
    "投放中心",
    count_brand=_count_brand,
    delete_brand=_delete_brand,
    brand_tables=frozenset({t for t, _ in _CHILD_TABLES}),
    count_product=None,
    delete_product=None,
    product_tables=frozenset(),
)
