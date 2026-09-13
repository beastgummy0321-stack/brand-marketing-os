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

import statistics
from datetime import date, timedelta
from typing import cast

from app.ads import channels, judgment
from app.brand_intelligence import repository as bi_repo
from app.core import cleanup
from app.core import settings as coresettings
from app.core.db import Conn, ConnProxy, jsonb, new_id

_AnyConn = Conn | ConnProxy

_SUCCESS_METRICS = frozenset({"cpa", "roas", "purchases"})


def _budget_total(start_date, end_date, groups: list[dict]) -> float | None:
    """`sum(group.daily_budget) x days`, one definition (§0). `days` is inclusive of both
    ends (a one-day campaign still spends one day's budget); `None` when either bound is
    missing — there is nothing to derive a total from yet. Same rule when there are no ad
    groups (or their daily budgets sum to <= 0): nothing to derive a total from, so `None`,
    not `0.0` — a Campaign that hasn't adopted a strategy yet has no budget, it doesn't have
    a zero budget (F04 decision 12, same honesty rule applied to the total-budget field)."""
    if start_date is None or end_date is None:
        return None
    days = (end_date - start_date).days + 1
    if days <= 0:
        return None
    daily_sum = sum(float(g["daily_budget"]) for g in groups)
    if daily_sum <= 0:
        return None
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


_PATCHABLE_COLUMNS = (
    "name", "objective", "success_metric", "success_target", "success_basis",
    "start_date", "end_date",
)


# F04-I11：使用者改過的那一格，`context_json.field_sources` 要跟著翻成「你說的」
# （ARCHITECTURE.md §6.1 第 11 條）——`updates` 這個鍵有出現，就代表使用者親手做了決定，
# 就算他把值清空也一樣。`platform`／`budget` 藏在 `constraints_json` 裡，要跟舊值比過才算數。
def _touched_field_sources(updates: dict, old_constraints: dict) -> set[str]:
    touched: set[str] = set()
    if "product_ids" in updates:
        touched.add("product")
    if "objective" in updates:
        touched.add("objective")
    if "start_date" in updates or "end_date" in updates:
        touched.add("dates")
    if "constraints_json" in updates:
        new_constraints = updates["constraints_json"] or {}
        for constraints_key, source_key in (("platform", "platform"), ("budget", "budget")):
            if new_constraints.get(constraints_key) != old_constraints.get(constraints_key):
                touched.add(source_key)
    return touched


def update_campaign(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str,
                     updates: dict) -> dict:
    """F03-I03: plain editing of a `status='draft'` campaign's own fields — not an `ads_action`
    (nothing is bound to a platform yet, §0). `updates` only ever contains keys the caller
    (`routes.py`) explicitly received; unknown keys are ignored so callers can pass a raw
    `dict(exclude_unset=True)` straight through. Same field rules as `create_campaign` for any
    key that's present. `constraints_json` replaces whole; `product_ids` merges into the
    existing `context_json` (the one nested field this issue lets the user correct — §0
    "PATCH ... for context_json.product_ids" — the rest of `context_json` is untouched).

    F04-I11: any key in `updates` that maps to a `context_json.field_sources` slot flips that
    slot to `"user"` — the user editing the confirmation screen is itself "you said it", even
    when they clear the value (`_touched_field_sources`)."""
    campaign = get_campaign(conn, org_id, brand_id, campaign_id)
    if campaign is None:
        raise ValueError("campaign_unknown")

    for field in ("name", "objective"):
        if field in updates:
            value = updates[field]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field}_unknown")
    if "success_metric" in updates and updates["success_metric"] not in _SUCCESS_METRICS:
        raise ValueError("success_metric_unknown")
    if "success_target" in updates:
        success_target = updates["success_target"]
        if success_target is not None and (
            isinstance(success_target, bool) or not isinstance(success_target, (int, float))
        ):
            raise ValueError("success_target_unknown")

    # F03-I19: dates validated on the *merged* row — a patch may move only one of the two, so
    # checking the payload alone would miss `end < start` when only `end_date` is sent (§0 "The
    # draft PATCH cannot create a state the create path refuses").
    def _merged_date(key):
        if key in updates:
            value = updates[key]
            return date.fromisoformat(value) if isinstance(value, str) else value
        return campaign.get(key)

    merged_start = _merged_date("start_date")
    merged_end = _merged_date("end_date")
    if merged_start is not None and merged_end is not None and merged_end < merged_start:
        raise ValueError("end_before_start")

    # A bound campaign's identity is not a field edit (§0): the name is exactly what exact-name
    # matching resolves against, and a change to a bound node has to leave an `ads_action`
    # instead (§6.5) — this endpoint never writes one.
    if campaign.get("local_state") != "unbound" and (
        "name" in updates or "start_date" in updates or "end_date" in updates
    ):
        raise ValueError("campaign_bound")

    set_clauses = []
    params: list = []
    for column in _PATCHABLE_COLUMNS:
        if column in updates:
            set_clauses.append(f"{column} = %s")
            params.append(updates[column])
    if "constraints_json" in updates:
        set_clauses.append("constraints_json = %s")
        params.append(jsonb(updates["constraints_json"] or {}))
    context_json = dict(campaign.get("context_json") or {})
    context_json_changed = False
    if "product_ids" in updates:
        product_ids = updates["product_ids"] or []
        # `bi_repo.list_products` is typed `Conn`-only; `ads` routes are handed the `ConnProxy`
        # the rest of this module already treats as interchangeable (`_AnyConn`).
        brand_product_ids = {p["id"] for p in bi_repo.list_products(cast(Conn, conn), brand_id)}
        for product_id in product_ids:
            if product_id not in brand_product_ids:
                raise ValueError("product_unknown")
        context_json["product_ids"] = product_ids
        context_json_changed = True

    old_constraints = campaign.get("constraints_json") or {}
    touched_sources = _touched_field_sources(updates, old_constraints)
    if touched_sources:
        field_sources = dict(context_json.get("field_sources") or {})
        for source_key in touched_sources:
            field_sources[source_key] = "user"
        context_json["field_sources"] = field_sources
        context_json_changed = True

    if context_json_changed:
        set_clauses.append("context_json = %s")
        params.append(jsonb(context_json))

    if set_clauses:
        params.extend([org_id, brand_id, campaign_id])
        conn.execute(
            f"UPDATE ads_campaign SET {', '.join(set_clauses)}"
            " WHERE org_id = %s AND brand_id = %s AND id = %s",
            tuple(params),
        )
    row = get_campaign(conn, org_id, brand_id, campaign_id)
    assert row is not None
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
    """`GET /campaigns` 列表：每筆帶 `budget_total`（推導）、`budget_progress`、一句成效摘要
    跟 F04-I08 的 `judgment`。沒有分頁——`routes.py` 的首頁路由靠這一點在原地數計數（見那邊
    的註解）。"""
    today = coresettings.today_for_org(conn, org_id=org_id)
    rows = conn.execute(
        "SELECT * FROM ads_campaign WHERE org_id = %s AND brand_id = %s ORDER BY created_at DESC",
        (org_id, brand_id),
    ).fetchall()
    entries = []
    for row in rows:
        row = dict(row)
        groups = _groups_for_campaign(conn, org_id, brand_id, row["id"])
        outcome = _outcome_totals(conn, org_id, brand_id, row["id"])
        budget_total = _budget_total(row["start_date"], row["end_date"], groups)
        spend = float(outcome["spend"]) if outcome["row_count"] else None
        pct = (
            round(spend / float(budget_total) * 100)
            if spend is not None and budget_total else None
        )
        entries.append({
            "id": row["id"], "name": row["name"], "status": row["status"],
            "start_date": row["start_date"], "end_date": row["end_date"],
            "objective": row["objective"],
            "created_at": row["created_at"], "created_by": row["created_by"],
            "budget_planned": row["budget_planned"],
            "budget_total": budget_total,
            "budget_progress": {"spent": spend, "total": budget_total, "pct": pct},
            "spend": spend,
            "outcome": outcome,
            "judgment": judgment.campaign_judgment({**row, "budget_total": budget_total,
                                                     "spend": spend}, today=today),
        })
    return entries


def _outcome_totals(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str) -> dict:
    """Campaign-level totals sum `entity_kind = 'group'` rows only. `ads_outcome_daily` also
    carries `entity_kind = 'ad'` rows (for the per-ad 花費占比), and those are never summed
    into a campaign total — summing both levels double-counts (§0 "money totals belong to the
    group level")."""
    row = conn.execute(
        "SELECT COALESCE(SUM(spend), 0) AS spend, COALESCE(SUM(purchases), 0) AS purchases,"
        " COALESCE(SUM(revenue), 0) AS revenue, COUNT(*) AS row_count"
        " FROM ads_outcome_daily WHERE org_id = %s AND brand_id = %s AND campaign_id = %s"
        " AND entity_kind = 'group'",
        (org_id, brand_id, campaign_id),
    ).fetchone()
    return dict(row) if row is not None else {
        "spend": 0, "purchases": 0, "revenue": 0, "row_count": 0,
    }


def _target_name(conn: _AnyConn, org_id: str, brand_id: str, action: dict,
                  *, campaign_name: str) -> str | None:
    """`ads_action.target_kind` 是 campaign／group／ad——只有 group／ad 需要另外查名字
    （campaign 自己就是 `campaign_name`）。N+1（每個 action 一次查詢）在 `limit=20` 之下可以
    接受，換一支 join 查詢不會讓程式碼變簡單。
    ponytail: N+1 lookup, batch-join if the actions list grows past ~20."""
    if action["target_kind"] == "campaign":
        return campaign_name
    table = "ads_delivery_group" if action["target_kind"] == "group" else "ads_ad"
    row = conn.execute(
        f"SELECT name FROM {table} WHERE org_id = %s AND brand_id = %s AND id = %s",
        (org_id, brand_id, action["target_id"]),
    ).fetchone()
    return row["name"] if row is not None else None


def recent_actions(conn: _AnyConn, org_id: str, brand_id: str, *, limit: int = 20) -> list:
    """F04-I08：這個品牌**跨 Campaign** 的最近操作——首頁「最近做了什麼」時間軸。每一列帶
    `campaign_id`／`campaign_name`（JOIN `ads_campaign`）跟 `judgment.action_line()` 組好的
    三個字串。"""
    today = coresettings.today_for_org(conn, org_id=org_id)
    rows = conn.execute(
        "SELECT a.*, c.name AS campaign_name FROM ads_action a"
        " JOIN ads_campaign c ON c.id = a.campaign_id"
        " WHERE a.org_id = %s AND a.brand_id = %s ORDER BY a.created_at DESC LIMIT %s",
        (org_id, brand_id, limit),
    ).fetchall()
    entries = []
    for row in rows:
        row = dict(row)
        target_name = _target_name(conn, org_id, brand_id, row, campaign_name=row["campaign_name"])
        line = judgment.action_line(
            row, campaign_name=row["campaign_name"], target_name=target_name, today=today,
        )
        entries.append({
            "campaign_id": row["campaign_id"], "campaign_name": row["campaign_name"], **line,
        })
    return entries


def campaign_detail(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str) -> dict | None:
    """`GET /campaigns/{c}`：整個五分頁工作區要讀的一份 dict——campaign 本身 + 投放組 +
    廣告（掛在各自的投放組下）+ 每個節點最新一筆 action + 成效小計 + F04-I08 的
    `judgment`／`action_lines`。`budget_total` 是這裡推導的第二個地方跟 `list_campaigns`
    共用同一個 `_budget_total()`，不重算第二套邏輯。
    """
    campaign = get_campaign(conn, org_id, brand_id, campaign_id)
    if campaign is None:
        return None

    today = coresettings.today_for_org(conn, org_id=org_id)
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
    outcome = _outcome_totals(conn, org_id, brand_id, campaign_id)
    budget_total = _budget_total(campaign["start_date"], campaign["end_date"], groups)

    detail = dict(campaign)
    detail["groups"] = groups
    detail["budget_total"] = budget_total
    detail["actions"] = [dict(a) for a in latest_actions]
    detail["outcome"] = outcome
    detail_spend = float(outcome["spend"]) if outcome["row_count"] else None
    detail["judgment"] = judgment.campaign_judgment(
        {**campaign, "budget_total": budget_total, "spend": detail_spend}, today=today,
    )
    detail["action_lines"] = [
        {
            "campaign_id": a["campaign_id"], "campaign_name": campaign["name"],
            **judgment.action_line(
                a, campaign_name=campaign["name"],
                target_name=_target_name(conn, org_id, brand_id, a, campaign_name=campaign["name"]),
                today=today,
            ),
        }
        for a in detail["actions"]
    ]
    return detail


def budget_history(conn: _AnyConn, org_id: str, brand_id: str) -> dict | None:
    """F03-I05／F05-I11: `app.ads.budget.scenarios()` 要吃的 `history` dict，`None` 代表這個
    品牌完全沒有花費可以參考——冷啟動，不是給一個缺 `cpa` 的半吊子 dict（§0「Never pass a
    partial dict」）。`cpa` = 近 30 天每日 CPA 的中位數（只算 `entity_kind='group'` 的列，跟
    `_outcome_totals` 同一條「money totals belong to the group level」規則），
    `last_daily_budget` = 最近一個 `status='closed'` Campaign 的投放組日預算合計。用
    `coresettings.today_for_org` 而非機器的 `date.today()`（`app/core/settings.py:293`）。

    F05-I11：這個品牌自己的迴圈（`ads_outcome_daily`）沒有已結案的花費時，退回讀它綁的廣告
    帳戶近 30 天真實花費（`app.ads.channels.account_spend_history`，平台名字只住在
    `channels.py`）——「投放過但還沒在新迴圈裡結案」不等於「沒投放過」（演練四 V-13）。帳戶
    也沒有花費才是誠實冷啟動。"""
    today = coresettings.today_for_org(conn, org_id=org_id)
    since = today - timedelta(days=30)
    daily_rows = conn.execute(
        "SELECT day, SUM(spend) AS spend, SUM(purchases) AS purchases FROM ads_outcome_daily"
        " WHERE org_id = %s AND brand_id = %s AND entity_kind = 'group' AND day >= %s"
        " GROUP BY day",
        (org_id, brand_id, since),
    ).fetchall()
    daily_cpas = [
        float(row["spend"]) / float(row["purchases"])
        for row in daily_rows if row["purchases"]
    ]
    if not daily_cpas:
        return _account_history(conn, org_id, brand_id)

    closed = conn.execute(
        "SELECT id FROM ads_campaign WHERE org_id = %s AND brand_id = %s AND status = 'closed'"
        " ORDER BY closed_at DESC NULLS LAST, created_at DESC LIMIT 1",
        (org_id, brand_id),
    ).fetchone()
    if closed is None:
        return _account_history(conn, org_id, brand_id)
    total_row = conn.execute(
        "SELECT COALESCE(SUM(daily_budget), 0) AS total FROM ads_delivery_group"
        " WHERE org_id = %s AND campaign_id = %s",
        (org_id, closed["id"]),
    ).fetchone()
    sample_ads_row = conn.execute(
        "SELECT COUNT(DISTINCT a.id) AS n FROM ads_ad a WHERE a.org_id = %s"
        " AND a.brand_id = %s AND a.local_state = 'bound' AND a.campaign_id IN ("
        "   SELECT DISTINCT campaign_id FROM ads_outcome_daily"
        "   WHERE org_id = %s AND brand_id = %s AND entity_kind = 'group' AND day >= %s"
        "   AND purchases > 0)",
        (org_id, brand_id, org_id, brand_id, since),
    ).fetchone()
    assert total_row is not None and sample_ads_row is not None  # 都是聚合查詢，永遠有一列
    return {
        "cpa": statistics.median(daily_cpas),
        "last_daily_budget": float(total_row["total"]),
        "sample_days": len(daily_cpas),
        "sample_ads": sample_ads_row["n"],
        "source": "ads_loop",
        "source_text": "上一期日預算",
    }


def _account_history(conn: _AnyConn, org_id: str, brand_id: str) -> dict | None:
    """F05-I11: 迴圈自己沒有已結案花費時的退路——讀這個品牌綁的廣告帳戶近 30 天真實花費。
    `conversion_goal` 只在這裡讀一次（`app.brand_intelligence.repository.get_brand` 既有
    facade），CPA 該用哪個轉換事件由它決定。"""
    brand = bi_repo.get_brand(conn, brand_id)
    conversion_goal = brand["conversion_goal"] if brand else None
    hist = channels.account_spend_history(conn, org_id, brand_id, conversion_goal)
    if hist is None or hist["daily_spend"] <= 0:
        return None
    return {
        "last_daily_budget": round(hist["daily_spend"]),
        "cpa": hist["cpa"],
        "sample_days": 30,
        "sample_ads": None,
        "source": channels.ACCOUNT_SOURCE,
        "source_text": f"{hist['channel_label']} 近 30 天平均日花費",
    }


def save_strategy(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str, *,
                   budget_basis_json: dict) -> dict:
    """F03-I05: 策略＋預算情境＋依據整包寫進 `ads_campaign.budget_basis_json`——沒有新表
    （§0「strategy JSON stored in the campaign row」）。"""
    conn.execute(
        "UPDATE ads_campaign SET budget_basis_json = %s"
        " WHERE org_id = %s AND brand_id = %s AND id = %s",
        (jsonb(budget_basis_json), org_id, brand_id, campaign_id),
    )
    row = get_campaign(conn, org_id, brand_id, campaign_id)
    assert row is not None
    return row


def select_scenario(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str, *,
                     scenario_key: str, budget_planned: float, budget_basis_json: dict) -> dict:
    """F03-I05: 使用者採用的情境（或手改的總額）——寫 `budget_planned`／`budget_scenario`；
    這之後 group 日預算才是錢的真相（§0「One source of truth for money after 採用」），這裡
    寫的是「採用當下記錄」，永不被重算覆寫。"""
    conn.execute(
        "UPDATE ads_campaign SET budget_planned = %s, budget_scenario = %s,"
        " budget_basis_json = %s WHERE org_id = %s AND brand_id = %s AND id = %s",
        (budget_planned, scenario_key, jsonb(budget_basis_json), org_id, brand_id, campaign_id),
    )
    row = get_campaign(conn, org_id, brand_id, campaign_id)
    assert row is not None
    return row


# -- F03-I06: 採用策略寫投放組／廣告，以及後續編輯 ------------------------------------------


def set_campaign_status(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str,
                         status: str) -> None:
    conn.execute(
        "UPDATE ads_campaign SET status = %s WHERE org_id = %s AND brand_id = %s AND id = %s",
        (status, org_id, brand_id, campaign_id),
    )


def coordinate_vocabulary(conn: _AnyConn, org_id: str, brand_id: str) -> list:
    """F03-I06 §0 blocked-if：跟 `app/workbench/repository.py::list_coordinate_vocabulary`
    同一份查法，複製而非 import（container contract 規則 5；不 import `app.schedule`／
    `app.workbench`，也不寫這張表）。只回七維座標，不回 `feedback` 拒絕標記——這裡只是
    prompt 要用的詞彙表，不是工作檯的挑選清單。"""
    rows = conn.execute(
        "SELECT dimension, key, label FROM brand_coordinate"
        " WHERE org_id = %s AND brand_id = %s AND disabled_at IS NULL"
        " ORDER BY dimension, label",
        (org_id, brand_id),
    ).fetchall()
    return [dict(row) for row in rows]


def create_group(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str, *,
                  channel_key: str, name: str, role: str, daily_budget: float,
                  start_date=None, end_date=None) -> dict:
    group_id = new_id("adg")
    conn.execute(
        "INSERT INTO ads_delivery_group (id, org_id, brand_id, campaign_id, channel_key, name,"
        " role, daily_budget, start_date, end_date)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (group_id, org_id, brand_id, campaign_id, channel_key, name, role, daily_budget,
         start_date, end_date),
    )
    row = get_group(conn, org_id, brand_id, group_id)
    assert row is not None
    return row


def get_group(conn: _AnyConn, org_id: str, brand_id: str, group_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM ads_delivery_group WHERE org_id = %s AND brand_id = %s AND id = %s",
        (org_id, brand_id, group_id),
    ).fetchone()
    return dict(row) if row is not None else None


_GROUP_PATCHABLE = ("name", "role", "daily_budget", "start_date", "end_date")


def update_group_fields(conn: _AnyConn, org_id: str, brand_id: str, group_id: str,
                         updates: dict) -> dict:
    """單純欄位寫入——業務規則（金額核准煞車、`ads_action` 留痕）在 `app/ads/plan.py`，
    這裡只管落地，跟 `update_campaign` 同一個分層。"""
    set_clauses = []
    params: list = []
    for column in _GROUP_PATCHABLE:
        if column in updates:
            set_clauses.append(f"{column} = %s")
            params.append(updates[column])
    if set_clauses:
        params.extend([org_id, brand_id, group_id])
        conn.execute(
            f"UPDATE ads_delivery_group SET {', '.join(set_clauses)}"
            " WHERE org_id = %s AND brand_id = %s AND id = %s",
            tuple(params),
        )
    row = get_group(conn, org_id, brand_id, group_id)
    assert row is not None
    return row


def delete_group(conn: _AnyConn, org_id: str, brand_id: str, group_id: str) -> None:
    conn.execute(
        "DELETE FROM ads_delivery_group WHERE org_id = %s AND brand_id = %s AND id = %s",
        (org_id, brand_id, group_id),
    )


def group_budget_total(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str) -> float:
    """這個 Campaign 目前所有投放組日預算合計——核准煞車比對的就是這個數字（§0）。"""
    row = conn.execute(
        "SELECT COALESCE(SUM(daily_budget), 0) AS total FROM ads_delivery_group"
        " WHERE org_id = %s AND brand_id = %s AND campaign_id = %s",
        (org_id, brand_id, campaign_id),
    ).fetchone()
    return float(row["total"]) if row is not None else 0.0


_AD_COORDINATE_COLUMNS = {
    "audience": "audience_key", "pain": "pain_key", "angle": "angle_key",
    "hook": "hook_key", "proof": "proof_key", "offer": "offer_key", "format": "format_key",
}


def create_ad(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str, group_id: str, *,
              name: str, coordinates: dict, coordinates_snapshot: dict) -> dict:
    ad_id = new_id("ada")
    conn.execute(
        "INSERT INTO ads_ad (id, org_id, brand_id, campaign_id, group_id, name, audience_key,"
        " pain_key, angle_key, hook_key, proof_key, offer_key, format_key,"
        " coordinates_snapshot_json)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (ad_id, org_id, brand_id, campaign_id, group_id, name,
         coordinates.get("audience"), coordinates.get("pain"), coordinates.get("angle"),
         coordinates.get("hook"), coordinates.get("proof"), coordinates.get("offer"),
         coordinates.get("format"), jsonb(coordinates_snapshot)),
    )
    row = get_ad(conn, org_id, brand_id, ad_id)
    assert row is not None
    return row


def get_ad(conn: _AnyConn, org_id: str, brand_id: str, ad_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM ads_ad WHERE org_id = %s AND brand_id = %s AND id = %s",
        (org_id, brand_id, ad_id),
    ).fetchone()
    return dict(row) if row is not None else None


def update_ad_fields(conn: _AnyConn, org_id: str, brand_id: str, ad_id: str,
                      updates: dict) -> dict:
    """`updates` 是 `{"name": ..., "coordinates": {"audience": ..., ...}}`——`coordinates`
    只送使用者真的改過的維度，其餘維度保持原樣（跟 `update_campaign` 的 `exclude_unset`
    同一條慣例）。"""
    set_clauses = []
    params: list = []
    if "name" in updates:
        set_clauses.append("name = %s")
        params.append(updates["name"])
    if "coordinates" in updates:
        for dim, column in _AD_COORDINATE_COLUMNS.items():
            if dim in updates["coordinates"]:
                set_clauses.append(f"{column} = %s")
                params.append(updates["coordinates"][dim])
    if set_clauses:
        params.extend([org_id, brand_id, ad_id])
        conn.execute(
            f"UPDATE ads_ad SET {', '.join(set_clauses)}"
            " WHERE org_id = %s AND brand_id = %s AND id = %s",
            tuple(params),
        )
    row = get_ad(conn, org_id, brand_id, ad_id)
    assert row is not None
    return row


def delete_ad(conn: _AnyConn, org_id: str, brand_id: str, ad_id: str) -> None:
    conn.execute(
        "DELETE FROM ads_ad WHERE org_id = %s AND brand_id = %s AND id = %s",
        (org_id, brand_id, ad_id),
    )


def list_ads_for_campaign(conn: _AnyConn, org_id: str, brand_id: str,
                           campaign_id: str) -> list:
    """F03-I08：這個 Campaign 底下所有廣告的平面清單（不掛在投放組下），供
    `app/ads/assets.py` 派工／讀就緒狀態用——跟 `campaign_detail()` 的 `ad_rows` 同一個
    查法，複製一份而非要求呼叫端拆解巢狀結構。"""
    rows = conn.execute(
        "SELECT * FROM ads_ad WHERE org_id = %s AND brand_id = %s AND campaign_id = %s"
        " ORDER BY created_at",
        (org_id, brand_id, campaign_id),
    ).fetchall()
    return [dict(r) for r in rows]


def set_ad_asset_ready(conn: _AnyConn, org_id: str, brand_id: str, ad_id: str, *,
                        actor: str | None, ready: bool) -> dict:
    """F03-I08：使用者手動勾／取消勾「素材已就位」——不是 `ads_action`（沒有東西碰到平台，
    §0「It is not an ads_action」），單純這一列自己的事實。"""
    if ready:
        conn.execute(
            "UPDATE ads_ad SET asset_ready_source = 'manual', asset_ready_by = %s,"
            " asset_ready_at = now() WHERE org_id = %s AND brand_id = %s AND id = %s",
            (actor, org_id, brand_id, ad_id),
        )
    else:
        conn.execute(
            "UPDATE ads_ad SET asset_ready_source = NULL, asset_ready_by = NULL,"
            " asset_ready_at = NULL WHERE org_id = %s AND brand_id = %s AND id = %s",
            (org_id, brand_id, ad_id),
        )
    row = get_ad(conn, org_id, brand_id, ad_id)
    assert row is not None
    return row


def record_action(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str, *,
                   target_kind: str, target_id: str, kind: str, before: dict, after: dict,
                   approved_by: str, sync_state: str = "pending_manual",
                   platform_ref: str | None = None) -> dict:
    """每一次碰到已綁定節點的改動留一列 `ads_action`（§0「every platform-bound change is an
    ads_action row」）。`approved_at` 跟這一列同時寫——這裡的「核准」是使用者在畫面上按下
    這次編輯的那一刻，不是另一支獨立的核准端點。`platform_ref`（F03-I09）：`bind` 寫的每一
    列帶上比對到的平台 id，其餘 kind 維持 `None`。"""
    action_id = new_id("adx")
    conn.execute(
        "INSERT INTO ads_action (id, org_id, brand_id, campaign_id, target_kind, target_id,"
        " kind, before_json, after_json, approved_by, approved_at, sync_state, platform_ref)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), %s, %s)",
        (action_id, org_id, brand_id, campaign_id, target_kind, target_id, kind,
         jsonb(before), jsonb(after), approved_by, sync_state, platform_ref),
    )
    row = conn.execute("SELECT * FROM ads_action WHERE id = %s", (action_id,)).fetchone()
    assert row is not None
    return dict(row)


# -- F03-I09: 手動發布／配對 -- 綁定欄位落地、campaign 狀態 ready -> live --------------------


def bind_campaign(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str, *,
                   external_id: str, external_name: str, external_status: str | None) -> None:
    conn.execute(
        "UPDATE ads_campaign SET external_id = %s, external_name = %s, external_status = %s,"
        " local_state = 'bound', bound_at = now()"
        " WHERE org_id = %s AND brand_id = %s AND id = %s",
        (external_id, external_name, external_status, org_id, brand_id, campaign_id),
    )


def bind_group(conn: _AnyConn, org_id: str, brand_id: str, group_id: str, *,
               external_id: str, external_name: str, external_status: str | None) -> None:
    conn.execute(
        "UPDATE ads_delivery_group SET external_id = %s, external_name = %s,"
        " external_status = %s, local_state = 'bound', bound_at = now()"
        " WHERE org_id = %s AND brand_id = %s AND id = %s",
        (external_id, external_name, external_status, org_id, brand_id, group_id),
    )


def bind_ad(conn: _AnyConn, org_id: str, brand_id: str, ad_id: str, *,
            external_id: str, external_name: str, external_status: str | None) -> None:
    conn.execute(
        "UPDATE ads_ad SET external_id = %s, external_name = %s, external_status = %s,"
        " local_state = 'bound', bound_at = now()"
        " WHERE org_id = %s AND brand_id = %s AND id = %s",
        (external_id, external_name, external_status, org_id, brand_id, ad_id),
    )


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
