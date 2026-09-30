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

import math
import statistics
from datetime import date, timedelta
from typing import cast

from app.ads import (
    ad_status,
    budget,
    channels,
    external_models,
    external_repository,
    judgment,
    manual_settings,
    objectives,
    result_kinds,
    triage_scale,
)
from app.brand_intelligence import repository as bi_repo
from app.core import cleanup
from app.core import settings as coresettings
from app.core.db import Conn, ConnProxy, jsonb, new_id

_AnyConn = Conn | ConnProxy

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
    """寫一列 `ads_campaign`。`name`／`goal_text`／`objective` 都是必填——
    `ValueError("field_unknown")` 帶欄位名在缺欄／空字串時。`target_cost`（F28-I01：這個活動
    唯一的上限，每筆成果成本）可以是 `None`（沒有說出上限）；有值就必須是正的有限數字，
    存成 `target_basis='own'`，否則一律 `ValueError("target_value_unknown")`。
    """
    for field in ("name", "goal_text", "objective"):
        value = campaign.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field}_unknown")
    cap = campaign.get("target_cost")
    if cap is not None and not _valid_cap(cap):
        raise ValueError("target_value_unknown")

    campaign_id = new_id("adc")
    conn.execute(
        "INSERT INTO ads_campaign (id, org_id, brand_id, name, goal_text, objective,"
        " target_cost, target_basis, start_date, end_date, status,"
        " budget_planned, budget_scenario, budget_basis_json, context_json, constraints_json,"
        " created_by)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            campaign_id, org_id, brand_id, campaign["name"], campaign["goal_text"],
            campaign["objective"], cap, "own" if cap is not None else None,
            campaign.get("start_date"), campaign.get("end_date"),
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


def _valid_cap(value) -> bool:
    """A cap is a positive, finite number -- never a bool, a string, zero or NaN."""
    return (
        not isinstance(value, bool) and isinstance(value, (int, float))
        and math.isfinite(value) and value > 0
    )


_PATCHABLE_COLUMNS = ("name", "objective", "start_date", "end_date")


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
    if "audience_hint" in updates:
        touched.add("audience")
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
    key that's present. `constraints_json` replaces whole; `product_ids` (and, F30-I04,
    `audience_hint`) merges into the
    existing `context_json` (the one nested field this issue lets the user correct — §0
    "PATCH ... for context_json.product_ids" — the rest of `context_json` is untouched).

    F04-I11: any key in `updates` that maps to a `context_json.field_sources` slot flips that
    slot to `"user"` — the user editing the confirmation screen is itself "you said it", even
    when they clear the value (`_touched_field_sources`)."""
    campaign = get_campaign(conn, org_id, brand_id, campaign_id)
    if campaign is None:
        raise ValueError("campaign_unknown")

    if campaign.get("origin") == "imported":
        allowed = {"goal_text", "objective"}
        if set(updates) - allowed:
            raise ValueError(external_models.IMPORTED_REASON)
        for key in ("goal_text", "objective"):
            value = updates.get(key)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{key}_unknown")
        if updates:
            conn.execute(
                "UPDATE ads_campaign SET updated_at=now(),"
                + ",".join(key + "=%s" for key in updates)
                + " WHERE org_id=%s AND brand_id=%s AND id=%s",
                (*updates.values(), org_id, brand_id, campaign_id),
            )
        updated = get_campaign(conn, org_id, brand_id, campaign_id)
        assert updated is not None
        return updated

    if "name" in updates:
        value = updates["name"]
        if not isinstance(value, str) or not value.strip():
            raise ValueError("name_unknown")
    if "objective" in updates:
        # F30-I04: a draft's objective obeys the same catalog the create path does (a reserved
        # seat -> `objective_unavailable`, anything else not accepted -> `objective_unknown`).
        objectives.check(updates["objective"])

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
    if "audience_hint" in updates:
        # F30-I04: the wizard's 受眾方向 correction; blank clears it (never an empty string).
        hint = updates["audience_hint"]
        if hint is not None and not isinstance(hint, str):
            raise ValueError("audience_hint_unknown")
        context_json["audience_hint"] = (hint.strip() or None) if hint is not None else None
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


def _without_retired_goal(row) -> dict:
    """F28-I01: the pre-cap goal columns (`success_*`) are kept in the table but retired -- one
    cap per campaign lives in `target_cost`/`target_basis` (docs/architecture/ads.md §6.32).
    Dropped here, at the one campaign read, so no caller can read or return them again."""
    return {key: value for key, value in dict(row).items() if not key.startswith("success_")}


def get_campaign(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM ads_campaign WHERE org_id = %s AND brand_id = %s AND id = %s",
        (org_id, brand_id, campaign_id),
    ).fetchone()
    if row is None:
        return None
    campaign = _without_retired_goal(row)
    if campaign["origin"] == "imported":
        return campaign
    brand = bi_repo.get_brand(cast(Conn, conn), brand_id)
    labels = judgment.conversion_labels((brand or {}).get("conversion_goal"))
    cap = None
    stored = (campaign.get("budget_basis_json") or {}).get("scenarios") or {}
    if stored.get("mode") == "cold_start":
        # F28-I01: a cold start is the one cap x purchases per day -- resolved only when the
        # stored projection needs it, so a plain row read stays one query otherwise.
        from app.ads import targets

        cap = targets.resolve(conn, org_id, brand_id, campaign)["value"]
    return budget.reconcile_campaign(campaign, labels["conversion"], cap=cap)


def require_internal_campaign(conn, org_id, brand_id, campaign_id) -> dict:
    campaign = get_campaign(conn, org_id, brand_id, campaign_id)
    if campaign is None:
        raise ValueError("campaign_unknown")
    if campaign.get("origin") == "imported":
        raise ValueError(external_models.IMPORTED_REASON)
    return campaign


_TARGET_BASES = frozenset({"own", "break_even"})


def _campaign_target_view(campaign: dict, resolved: dict) -> dict:
    """The cap view (`targets.resolve`) plus this sub-resource's own configuration: which
    products the campaign names, and the full result-kind vocabulary the cap block's fold
    offers (F19-I06: `result_label` is never a raw code)."""
    return {
        "campaign_id": campaign["id"],
        "product_ids": (campaign.get("context_json") or {}).get("product_ids") or [],
        **resolved,
        "result_kinds": result_kinds.options(),
    }


def get_campaign_target(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str) -> dict:
    """F16-I04: `GET .../target`. `targets.resolve()` is pure and read-only; this is the one
    place that combines it with the stored configuration (`result_kind`/product choice/own
    override/`target_revision`) into the shape the route returns."""
    from app.ads import targets

    campaign = get_campaign(conn, org_id, brand_id, campaign_id)
    if campaign is None:
        raise ValueError("campaign_unknown")
    resolved = targets.resolve(conn, org_id, brand_id, campaign)
    return _campaign_target_view(campaign, resolved)


def save_campaign_target(
    conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str, *,
    result_kind: str | None = None, basis: str | None = None, value: float | None = None,
    product_id: str | None = None, price: float | None = None,
    variable_cost: float | None = None, expected_revision: int | None, actor: str,
) -> dict:
    """F16-I04: `PUT .../target`, optimistic revision exactly like `month_budget.save`
    (`app/ads/month_budget.py:410`) but scoped to `target_revision` -- this sub-resource's own
    counter, so unrelated campaign edits (strategy/plan/bind/...) never collide with it.

    Writes only this sub-resource's own columns (`target_cost`/`target_basis`/`result_kind`/
    `target_revision`) -- the one cap store (F28-I01, docs/architecture/ads.md §6.32).

    `price`/`variable_cost` are never written to `product_economics` here: they only ever reach
    `app.brand_intelligence.repository.save_product_economics`, that layer's own public write
    path (container contract §1) -- merged with the product's current economics so a partial
    edit (just the variable cost, say) never has to guess the other required fields."""
    row = conn.execute(
        "SELECT * FROM ads_campaign WHERE org_id=%s AND brand_id=%s AND id=%s FOR UPDATE",
        (org_id, brand_id, campaign_id),
    ).fetchone()
    if row is None:
        raise ValueError("campaign_unknown")
    campaign = dict(row)
    if (
        type(expected_revision) is not int
        or expected_revision != (campaign.get("target_revision") or 0)
    ):
        raise ValueError("target_conflict")
    if result_kind is not None and result_kind not in result_kinds.LABELS:
        raise ValueError("result_kind_unknown")
    if basis is not None and basis not in _TARGET_BASES:
        raise ValueError("target_basis_unknown")
    if basis == "own" and value is None:
        raise ValueError("target_value_unknown")
    if value is not None and not _valid_cap(value):
        raise ValueError("target_value_unknown")

    context_json = dict(campaign.get("context_json") or {})
    if product_id is not None:
        brand_product_ids = {p["id"] for p in bi_repo.list_products(cast(Conn, conn), brand_id)}
        if product_id not in brand_product_ids:
            raise ValueError("product_unknown")
        context_json["product_ids"] = [product_id]
        conn.execute(
            "UPDATE ads_campaign SET context_json=%s WHERE org_id=%s AND brand_id=%s AND id=%s",
            (jsonb(context_json), org_id, brand_id, campaign_id),
        )

    if price is not None or variable_cost is not None:
        product_ids = [product_id] if product_id else context_json.get("product_ids") or []
        if not product_ids:
            raise ValueError("product_unknown")
        # F43-I01: merge onto the stored row (`raw=True`), never the effective one -- writing the
        # effective values back would freeze a derived list price / bundle cost into a number.
        existing = bi_repo.get_product_economics(
            cast(Conn, conn), brand_id, product_ids[0], raw=True
        ) or {}
        selling_price = price if price is not None else existing.get("selling_price")
        currency = existing.get("currency")
        if selling_price is None or currency is None:
            raise ValueError("product_economics_unknown")
        bi_repo.save_product_economics(
            cast(Conn, conn), brand_id, product_ids[0], actor=actor,
            selling_price=float(selling_price), currency=currency, confirmed_by=actor,
            fixed_cost=existing.get("fixed_cost"),
            unit_variable_cost=(
                float(variable_cost) if variable_cost is not None
                else existing.get("unit_variable_cost")
            ),
            shipping_cost=existing.get("shipping_cost"),
            effective_from=existing.get("effective_from"),
            effective_to=existing.get("effective_to"),
            close_rate=existing.get("close_rate"),
            assumptions=existing.get("assumptions_json"),
        )

    set_clauses = ["target_revision = target_revision + 1", "updated_at = now()"]
    params: list = []
    if result_kind is not None:
        set_clauses.append("result_kind = %s")
        params.append(result_kind)
    if basis == "own":
        set_clauses += ["target_basis = %s", "target_cost = %s"]
        params += ["own", value]
    elif basis is not None:
        # `break_even` only clears the user's own cap so resolve() falls back to break-even --
        # never a stored number (break-even is always recomputed using product economics); the
        # label only records "the user asked for break-even" versus "nothing chosen yet".
        set_clauses += ["target_basis = %s", "target_cost = NULL"]
        params += [basis]
    params += [org_id, brand_id, campaign_id]
    conn.execute(
        f"UPDATE ads_campaign SET {', '.join(set_clauses)} "
        "WHERE org_id=%s AND brand_id=%s AND id=%s",
        tuple(params),
    )
    conn.commit()
    return get_campaign_target(conn, org_id, brand_id, campaign_id)


def _empty_external_outcome() -> dict:
    return {"spend": None, "purchases": None, "revenue": None, "row_count": 0}


def _groups_for_campaign(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str) -> list:
    rows = conn.execute(
        # `id` breaks the tie: a plan's groups/ads are all inserted in one transaction and share
        # `created_at`, so ordering by it alone returns them in arbitrary order -- which changed
        # the launch snapshot between two reads and sent a half-finished handoff stale (drill 5).
        "SELECT * FROM ads_delivery_group WHERE org_id = %s AND brand_id = %s"
        " AND campaign_id = %s ORDER BY created_at, id",
        (org_id, brand_id, campaign_id),
    ).fetchall()
    return [dict(r) for r in rows]


# F24-I01: canonical order for "the first failing section" in `campaign_sync_state` below --
# matches `record_sync`'s own validation order (`external_repository.py:170`, a Python `set`
# literal with no order of its own). `jsonb` key order from Postgres isn't a contract either, so
# this tuple is the one place that order is actually pinned.
_SYNC_SECTION_ORDER = ("structure", "creatives", "observations")
# The two section-level statuses `record_sync` (written by `external_sync.py:446,552`) ever
# writes for a sync attempt that didn't cleanly finish -- there is no literal `"failed"` at the
# section level (that word is reserved for the aggregate `data.sync.state` derived from them).
_SYNC_FAILED_STATUSES = frozenset({"error", "partial"})


def _bound_account_ids(conn: _AnyConn, org_id: str, brand_id: str, platform: str) -> set:
    """This platform's own bound source accounts -- a DB read only (`MetaReader.accounts` ->
    `source.external_bound_accounts`), never a platform API call. Same check
    `external_repository.external_view`'s own `connections` list makes, kept here (not moved
    into `external_repository.py`) because this issue's touch scope doesn't cover that file."""
    reader = channels.external_reader(platform)
    if reader is None:
        return set()
    return {account["account_id"] for account in reader.accounts(conn, org_id, brand_id)}


def _campaign_platforms(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str) -> set:
    """This campaign's own distinct platforms (F27-I09 Contract I) -- used only to decide which
    adapter's `is_auth_error()` a failing section's stored error code goes through
    (`campaign_sync_state` below). Same table `_campaign_disconnected` already reads its own
    (platform, source_account) pairs from, a separate query rather than sharing that one because
    this one runs even when there's no failing section (cheap, no bound-accounts lookup)."""
    rows = conn.execute(
        "SELECT DISTINCT platform FROM ads_external_entity "
        "WHERE org_id=%s AND brand_id=%s AND campaign_id=%s",
        (org_id, brand_id, campaign_id),
    ).fetchall()
    return {row["platform"] for row in rows}


def _campaign_disconnected(
    conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str, accounts_cache: dict,
) -> bool:
    """Whether any of this campaign's own (platform, source_account) pairs sits outside the
    platform reader's bound accounts (F24-I01, feature Decisions) -- same DB-only check
    `external_view`'s own `connections` list makes, just for one campaign. `accounts_cache` (a
    plain `dict`, mutated in place) lets `list_campaigns` below share one `_bound_account_ids`
    read per platform across every campaign in the list, never once per campaign."""
    pairs = conn.execute(
        "SELECT DISTINCT platform, source_account FROM ads_external_entity "
        "WHERE org_id=%s AND brand_id=%s AND campaign_id=%s",
        (org_id, brand_id, campaign_id),
    ).fetchall()
    for row in pairs:
        platform, account = row["platform"], row["source_account"]
        if platform not in accounts_cache:
            accounts_cache[platform] = _bound_account_ids(conn, org_id, brand_id, platform)
        if account not in accounts_cache[platform]:
            return True
    return False


def campaign_sync_state(
    conn: _AnyConn, org_id: str, brand_id: str, campaign: dict,
    *, accounts_cache: dict | None = None,
) -> dict:
    """The `data.sync` object (F24-I01, feature Decisions; `"auth_expired"` added F27-I09 Contract
    I) for one campaign -- read-only, no migration. `campaign` needs `id` and `context_json`.
    State, in priority order: `"never"` (no `external_sync` section recorded at all) /
    `"disconnected"` (`_campaign_disconnected` above) / `"auth_expired"` (the first failing
    section's own STORED `error_code` -- never a raw provider number, correction 2 -- reads as an
    auth error to any of this campaign's own platforms' adapters, `adapters.is_auth_error`) /
    `"failed"` (any other section `status` in `_SYNC_FAILED_STATUSES`) / `"syncing"` (any section
    `status == "syncing"`) / `"ok"`. `error` is the first failing section's own `error`
    (`_SYNC_SECTION_ORDER`, may be `None`); `last_success_at` is the newest section value across
    all three sections -- a failed section keeps its OLD `last_success_at`/`coverage`
    (`external_repository.record_sync`), so this can read as stale, never "recent", once `state`
    is `"failed"`/`"auth_expired"`. `accounts_cache` -- see `_campaign_disconnected`."""
    cache = {} if accounts_cache is None else accounts_cache
    sections = (campaign.get("context_json") or {}).get("external_sync") or {}
    if not sections:
        return {"state": "never", "error": None, "last_success_at": None}
    ordered = [(name, sections[name]) for name in _SYNC_SECTION_ORDER if name in sections]
    failing = [section for _, section in ordered if section.get("status") in _SYNC_FAILED_STATUSES]
    error = failing[0].get("error") if failing else None
    error_code = failing[0].get("error_code") if failing else None
    last_success_at = max(
        (section["last_success_at"] for _, section in ordered if section.get("last_success_at")),
        default=None,
    )
    if _campaign_disconnected(conn, org_id, brand_id, campaign["id"], cache):
        state = "disconnected"
    elif failing:
        from app.ads import adapters

        platforms = _campaign_platforms(conn, org_id, brand_id, campaign["id"])
        if error_code is not None and any(
            adapters.is_auth_error(platform, error_code) for platform in platforms
        ):
            state = "auth_expired"
        else:
            state = "failed"
    elif any(section.get("status") == "syncing" for _, section in ordered):
        state = "syncing"
    else:
        state = "ok"
    return {"state": state, "error": error, "last_success_at": last_success_at}


# F29 Contract D: one plain sentence per `data_status` state -- the screen shows it as is.
DATA_STATUS_LABELS = {
    "ready": "資料已讀齊。",
    "partial": "有幾天的資料還沒讀到，數字可能偏少。",
    "no_rows": "已讀過平台資料，這段期間沒有花費紀錄。",
    "syncing": "正在讀取平台的最新資料。",
    "never": "還沒讀過平台資料。",
    "disconnected": "廣告帳號已中斷連線，讀不到新資料。",
    "auth_expired": "平台授權已過期，重新連線後才能讀資料。",
    "failed": "上次讀取平台資料失敗。",
}


def campaign_data_status(
    conn: _AnyConn, org_id: str, brand_id: str, campaign: dict, *,
    has_rows: bool, missing_days: list, sync: dict | None = None,
    accounts_cache: dict | None = None,
) -> dict:
    """F29 Contract D `data_status`: the one "has data / why not" state of a campaign, for the
    window the caller judged -- triage `data.status` (its 28-day window) and the home row
    `data_status` (this month up to yesterday) both call this, never a second derivation.

    The caller passes what it already read for that window: `has_rows` (any ad-scope daily row
    in it) and `missing_days` (its days outside the recorded sync coverage). `sync` is this
    campaign's `campaign_sync_state` when the caller already has it (read here otherwise).
    Priority: a sync state that is not `ok` wins (`never`/`disconnected`/`auth_expired`/
    `failed`/`syncing` -- a broken read beats a gap); then `partial` (a day of the window was
    never read, so an empty or low number could be that gap); then `no_rows` (every day read,
    nothing spent); else `ready`. Read-only."""
    if sync is None:
        sync = campaign_sync_state(conn, org_id, brand_id, campaign, accounts_cache=accounts_cache)
    state = sync["state"]
    if state == "ok":
        state = "partial" if missing_days else "no_rows" if not has_rows else "ready"
    return {
        "state": state, "label": DATA_STATUS_LABELS[state], "missing_days": list(missing_days),
        "last_success_at": sync["last_success_at"],
    }


# F27-I09 Done #7: `campaign_objective` for a system-built campaign -- the Chinese objective
# labels `app/ads/brief.py::_OBJECTIVES` drafts one with, mapped here (ads-owned, never through
# any adapter). 名單 (leads) and 知名度 (awareness) have no sales/engagement/traffic analogue
# among the three named families, so -- like any unset/unrecognised label -- they read "other".
_INTERNAL_OBJECTIVE_FAMILY = {"購買": "sales", "加購物車": "sales", "流量": "traffic"}


def objective_family(objective: str | None) -> str:
    if objective is None:
        return "other"
    return _INTERNAL_OBJECTIVE_FAMILY.get(objective, "other")


def campaign_objective_family(conn: _AnyConn, org_id: str, brand_id: str, campaign: dict) -> str:
    """`campaign_objective` (F27-I09 Done #7, for `CampaignChip`) of one campaign -- an imported
    campaign routes through the Meta adapter's own raw-objective mapping, read off its own root
    entity (`native_kind='campaign', parent_native_id IS NULL`, the same "this campaign's own
    platform object" lookup shape `external_routes.py::campaign_sync` and
    `triage.py::_account_cutoff` already use); a system-built campaign routes through this
    module's own `objective_family()` over its stored Chinese objective label. No root entity yet
    (an imported campaign mid-first-sync) -> `"other"`, never a guess."""
    if campaign.get("origin") == "imported":
        root = conn.execute(
            "SELECT platform, objective FROM ads_external_entity WHERE org_id=%s AND brand_id=%s "
            "AND campaign_id=%s AND parent_native_id IS NULL",
            (org_id, brand_id, campaign["id"]),
        ).fetchone()
        if root is None:
            return "other"
        from app.ads import adapters

        return adapters.objective_family(root["platform"], root["objective"])
    return objective_family(campaign.get("objective"))


def _campaign_capacity(
    conn: _AnyConn, org_id: str, brand_id: str, campaign: dict, owner_by_entity: dict,
) -> dict:
    """F27-I06 Contract F: `data.capacity` for one campaign card -- `items` here are just the
    campaign's own ACTIVE ad ids (`triage_capacity.capacity_view` only ever reads `entity_id` off
    each), never a full `triage.classify()` call (this list endpoint stays cheap, no per-ad
    program judgement here). `targets`/`triage_capacity` imported locally, not at module top --
    both eventually reach `review_evidence` -> `change_control_data` -> back to this module
    (`repository.py`), a hard cycle at import time; a function-scoped import is this codebase's
    own standard way to break that (same precedent `get_campaign_target` above already sets for
    `targets`, `app/core/settings.py:108`)."""
    from app.ads import targets, triage_capacity

    rows = conn.execute(
        "SELECT id,native_status FROM ads_external_entity WHERE org_id=%s AND brand_id=%s "
        "AND campaign_id=%s AND native_kind='ad'",
        (org_id, brand_id, campaign["id"]),
    ).fetchall()
    items = [
        {"entity_id": row["id"]} for row in rows if not ad_status.is_closed(row["native_status"])
    ]
    target = targets.resolve(conn, org_id, brand_id, campaign)
    return triage_capacity.capacity_view(items, target["value"], owner_by_entity)


def list_campaigns(conn: _AnyConn, org_id: str, brand_id: str) -> list:
    """`GET /campaigns` 列表：每筆帶 `budget_total`（推導）、`budget_progress`、一句成效摘要
    跟 F04-I08 的 `judgment`，F24-I01 起再加 `data.sync`，F27-I06 起再加 `data.capacity`。
    沒有分頁——`routes.py` 的首頁路由靠這一點在原地數計數（見那邊的註解）。"""
    today = coresettings.today_for_org(conn, org_id=org_id)
    rows = conn.execute(
        "SELECT * FROM ads_campaign WHERE org_id = %s AND brand_id = %s ORDER BY created_at DESC",
        (org_id, brand_id),
    ).fetchall()
    accounts_cache: dict = {}
    # One brand-wide owner lookup shared by every campaign card below (F27-I06, same
    # query-sharing shape `accounts_cache` already uses for sync state).
    owner_by_entity = triage_scale.owner_lookup(conn, org_id, brand_id)
    entries = []
    for row in rows:
        row = dict(row)
        groups = _groups_for_campaign(conn, org_id, brand_id, row["id"])
        outcome = (_empty_external_outcome() if row["origin"] == "imported" else
                   _outcome_totals(conn, org_id, brand_id, row["id"]))
        budget_total = _budget_total(row["start_date"], row["end_date"], groups)
        spend = float(outcome["spend"]) if outcome["row_count"] else None
        pct = (
            round(spend / float(budget_total) * 100)
            if spend is not None and budget_total else None
        )
        entries.append({
            "id": row["id"], "name": row["name"], "status": row["status"],
            "origin": row["origin"], "capabilities": external_models.capabilities(row["origin"]),
            "start_date": row["start_date"], "end_date": row["end_date"],
            "objective": row["objective"],
            "campaign_objective": campaign_objective_family(conn, org_id, brand_id, row),
            "created_at": row["created_at"], "created_by": row["created_by"],
            "budget_planned": row["budget_planned"],
            "budget_total": budget_total,
            "budget_progress": {"spent": spend, "total": budget_total, "pct": pct},
            "spend": spend,
            "outcome": outcome,
            "judgment": judgment.campaign_judgment({**row, "budget_total": budget_total,
                                                     "spend": spend}, today=today),
            "data": {
                "sync": campaign_sync_state(
                    conn, org_id, brand_id, row, accounts_cache=accounts_cache,
                ),
                "capacity": _campaign_capacity(conn, org_id, brand_id, row, owner_by_entity),
            },
        })
    return entries


# F37 Contract P: the one mapping from platform rows to this module's local nodes. A performance
# row of an internal campaign is an `ads_external_daily` row (monthly account-budget rows
# excluded) of the platform entity whose `native_id` a local node carries as its `external_id`
# -- the same binding `ab_pairs._entities` reads. `{scope}` is `adset`/`ad`, `{table}` the local
# node table; both come from `_PERF_KIND`, never from a caller. A local node with no bound
# platform id, or a platform row with no local node, has no row here.
_PERF_JOIN = (
    " FROM ads_external_daily d"
    " JOIN ads_external_entity e ON e.org_id = d.org_id AND e.brand_id = d.brand_id"
    " AND e.campaign_id = d.campaign_id AND e.id = d.entity_id"
    " JOIN {table} n ON n.org_id = d.org_id AND n.brand_id = d.brand_id"
    " AND n.campaign_id = d.campaign_id AND n.external_id = e.native_id"
    " WHERE d.metric_scope = '{scope}' AND d.attribution_key <> %s"
)
_PERF_KIND = {
    "group": {"table": "ads_delivery_group", "scope": "adset"},
    "ad": {"table": "ads_ad", "scope": "ad"},
}


def _perf_join(kind: str) -> str:
    if kind not in _PERF_KIND:
        raise ValueError("performance_kind_unknown")
    return _PERF_JOIN.format(**_PERF_KIND[kind])


def performance_rows(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str,
                     kind: str) -> list[dict]:
    """F37 Contract P: this campaign's daily platform rows at the group (`adset`) or ad grain,
    keyed by the LOCAL node id (`entity_id`), ordered by `day, entity_id`. Unknown metrics stay
    `NULL` -- nothing here coerces them."""
    rows = conn.execute(
        "SELECT n.id AS entity_id, d.day, d.spend, d.impressions, d.clicks, d.purchases,"
        " d.revenue, d.currency, d.source, d.observed_at"
        + _perf_join(kind)
        + " AND d.org_id = %s AND d.brand_id = %s AND d.campaign_id = %s"
        " ORDER BY d.day, n.id",
        (external_repository.MONTHLY_BUDGET_ATTRIBUTION_KEY, org_id, brand_id, campaign_id),
    ).fetchall()
    return [dict(r) for r in rows]


def _outcome_totals(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str) -> dict:
    """Campaign-level totals sum the group-grain rows of `performance_rows` only (Contract P).
    Ad-grain rows exist too (for the per-ad 花費占比) and are never summed into a campaign
    total -- summing both levels double-counts (§0 "money totals belong to the group level").
    `purchases`／`revenue` may be `NULL` (untracked): `SUM()` already ignores `NULL` rows on its
    own, so no `COALESCE` here -- when every row is untracked the sum comes back `NULL`/`None`,
    never a fabricated 0. `spend` stays `COALESCE`d to 0 for the no-row case, and `row_count` is
    how callers already tell "no data at all" apart from "zero spend"."""
    row = conn.execute(
        "SELECT COALESCE(SUM(d.spend), 0) AS spend, SUM(d.purchases) AS purchases,"
        " SUM(d.revenue) AS revenue, COUNT(*) AS row_count"
        + _perf_join("group")
        + " AND d.org_id = %s AND d.brand_id = %s AND d.campaign_id = %s",
        (external_repository.MONTHLY_BUDGET_ATTRIBUTION_KEY, org_id, brand_id, campaign_id),
    ).fetchone()
    return dict(row) if row is not None else {
        "spend": 0, "purchases": None, "revenue": None, "row_count": 0,
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
        " ORDER BY created_at, id",
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
    outcome = (_empty_external_outcome() if campaign["origin"] == "imported" else
               _outcome_totals(conn, org_id, brand_id, campaign_id))
    budget_total = _budget_total(campaign["start_date"], campaign["end_date"], groups)

    detail = dict(campaign)
    from app.ads import targets

    detail["cap"] = targets.resolve(conn, org_id, brand_id, campaign)
    detail["capabilities"] = external_models.capabilities(campaign["origin"])
    detail["external_view"] = (
        external_repository.external_view(conn, org_id, brand_id, campaign_id)
        if campaign["origin"] == "imported" else None
    )
    detail["groups"] = groups
    detail["manual_handoff"] = manual_settings.handoff(detail)
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

    F05-I11：這個品牌自己的迴圈（F37：`performance_rows` 同一條 group
    粒度的平台列）沒有已結案的花費時，退回讀它綁的廣告帳戶近 30 天真實花費
    （`app.ads.channels.account_spend_history`，平台名字只住在 `channels.py`）——
    「投放過但還沒在新迴圈裡結案」不等於「沒投放過」（演練四 V-13）。帳戶也沒有花費才是
    誠實冷啟動。"""
    today = coresettings.today_for_org(conn, org_id=org_id)
    since = today - timedelta(days=30)
    daily_rows = conn.execute(
        "SELECT d.day, SUM(d.spend) AS spend, SUM(d.purchases) AS purchases"
        + _perf_join("group")
        + " AND d.org_id = %s AND d.brand_id = %s AND d.day >= %s GROUP BY d.day",
        (external_repository.MONTHLY_BUDGET_ATTRIBUTION_KEY, org_id, brand_id, since),
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
        "   SELECT DISTINCT d.campaign_id"
        + _perf_join("group")
        + "   AND d.org_id = %s AND d.brand_id = %s AND d.day >= %s AND d.purchases > 0)",
        (org_id, brand_id, external_repository.MONTHLY_BUDGET_ATTRIBUTION_KEY,
         org_id, brand_id, since),
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
    facade），CPA 該用哪個轉換事件由它決定。F36-I05（裁決 B）：`sample_days` 與
    `source_text` 都印 `channels.account_spend_history` 算出的「有花費天數」，不再寫死 30。"""
    brand = bi_repo.get_brand(conn, brand_id)
    conversion_goal = brand["conversion_goal"] if brand else None
    hist = channels.account_spend_history(conn, org_id, brand_id, conversion_goal)
    if hist is None or hist["daily_spend"] <= 0:
        return None
    return {
        "last_daily_budget": round(hist["daily_spend"]),
        "cpa": hist["cpa"],
        "sample_days": hist["days"],
        "sample_ads": None,
        "source": channels.ACCOUNT_SOURCE,
        "source_text": (
            f"{hist['channel_label']} 廣告帳戶全部活動，"
            f"近 30 天有投放的 {hist['days']} 天平均日花費"
        ),
    }


def starting_point_reads(conn: _AnyConn, org_id: str, brand_id: str) -> dict:
    """F33-I01: the ads-owned counts behind the strategy prompt's 【這個品牌的起點】 and the
    available-roles rule (`app.ads.strategy._available_roles`). `external_rows_ever` tells
    「還沒讀過平台資料」 apart from a real 0 over the last 90 days; a NULL sum means the metric was
    never tracked, never a counted zero. Ad-scope rows only, monthly budget rows excluded (the
    same grain `home_overview` reads). `loop_purchases` sums the group-level purchases of closed
    campaigns -- the same rows `budget_history` reads. Orders live in another module and are
    not read here."""
    today = coresettings.today_for_org(conn, org_id=org_id)
    since = today - timedelta(days=90)
    external = conn.execute(
        "SELECT COUNT(*) AS rows_ever,"
        " COUNT(*) FILTER (WHERE day >= %s) AS rows_90d,"
        " SUM(clicks) FILTER (WHERE day >= %s) AS clicks,"
        " SUM(purchases) FILTER (WHERE day >= %s) AS purchases"
        " FROM ads_external_daily WHERE org_id = %s AND brand_id = %s"
        " AND metric_scope = 'ad' AND attribution_key <> %s",
        (since, since, since, org_id, brand_id,
         external_repository.MONTHLY_BUDGET_ATTRIBUTION_KEY),
    ).fetchone()
    loop = conn.execute(
        "SELECT SUM(d.purchases) AS purchases"
        + _perf_join("group")
        + " AND d.org_id = %s AND d.brand_id = %s AND d.campaign_id IN ("
        " SELECT c.id FROM ads_campaign c WHERE c.org_id = %s AND c.brand_id = %s"
        " AND c.status = 'closed')",
        (external_repository.MONTHLY_BUDGET_ATTRIBUTION_KEY, org_id, brand_id, org_id, brand_id),
    ).fetchone()
    assert external is not None and loop is not None  # 都是聚合查詢，永遠有一列
    # F39-I05: how many campaigns this brand closed through the system, and the latest one's
    # judged numbers -- one query: the window count rides on the latest closed row.
    last_closed = conn.execute(
        "SELECT COUNT(*) OVER () AS closed_campaigns, name, verdict, verdict_json"
        " FROM ads_campaign WHERE org_id = %s AND brand_id = %s AND status = 'closed'"
        " ORDER BY closed_at DESC NULLS LAST, created_at DESC LIMIT 1",
        (org_id, brand_id),
    ).fetchone()
    if last_closed is None:
        closed_campaigns, last_closed_read = 0, None
    else:
        verdict_json = last_closed["verdict_json"]
        if not isinstance(verdict_json, dict):
            verdict_json = {}
        closed_campaigns = int(last_closed["closed_campaigns"])
        last_closed_read = {
            "name": last_closed["name"], "verdict": last_closed["verdict"],
            "actual": verdict_json.get("actual"), "target": verdict_json.get("target"),
        }
    return {
        "closed_campaigns": closed_campaigns,
        "last_closed": last_closed_read,
        "external_rows_ever": external["rows_ever"] > 0,
        "external_rows_90d": external["rows_90d"] > 0,
        "external_clicks_90d": (
            int(external["clicks"]) if external["clicks"] is not None else None
        ),
        "external_purchases_90d": (
            float(external["purchases"]) if external["purchases"] is not None else None
        ),
        "loop_purchases": float(loop["purchases"]) if loop["purchases"] is not None else None,
    }


def save_strategy(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str, *,
                   budget_basis_json: dict) -> dict:
    """F03-I05: 策略＋預算情境＋依據整包寫進 `ads_campaign.budget_basis_json`——沒有新表
    （§0「strategy JSON stored in the campaign row」）。"""
    require_internal_campaign(conn, org_id, brand_id, campaign_id)
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
    require_internal_campaign(conn, org_id, brand_id, campaign_id)
    conn.execute(
        "UPDATE ads_campaign SET budget_planned = %s, budget_scenario = %s,"
        " budget_basis_json = %s WHERE org_id = %s AND brand_id = %s AND id = %s",
        (budget_planned, scenario_key, jsonb(budget_basis_json), org_id, brand_id, campaign_id),
    )
    row = get_campaign(conn, org_id, brand_id, campaign_id)
    assert row is not None
    return row


def set_budget_cap(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str, *,
                   budget_cap: int | None) -> dict:
    """F28-I03: write only `constraints_json.budget` (set or removed) and flip
    `context_json.field_sources.budget` to the user's -- in any status, no status or binding
    check, and no other column (`budget_planned`／`budget_scenario`／`budget_basis_json` stay as
    saved). The caller validated the value. Both documents are edited in place in SQL, so a
    concurrent edit of another key in them is never overwritten."""
    require_internal_campaign(conn, org_id, brand_id, campaign_id)
    conn.execute(
        "UPDATE ads_campaign SET"
        " constraints_json = (COALESCE(constraints_json, '{}'::jsonb) - 'budget') || %s,"
        " context_json = jsonb_set(COALESCE(context_json, '{}'::jsonb), '{field_sources}',"
        "   COALESCE(context_json->'field_sources', '{}'::jsonb) || '{\"budget\": \"user\"}')"
        " WHERE org_id = %s AND brand_id = %s AND id = %s",
        (jsonb({} if budget_cap is None else {"budget": budget_cap}),
         org_id, brand_id, campaign_id),
    )
    row = get_campaign(conn, org_id, brand_id, campaign_id)
    assert row is not None
    return row


# -- F03-I06: 採用策略寫投放組／廣告，以及後續編輯 ------------------------------------------


def set_campaign_status(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str,
                         status: str) -> None:
    require_internal_campaign(conn, org_id, brand_id, campaign_id)
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
    require_internal_campaign(conn, org_id, brand_id, campaign_id)
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
    node = get_group(conn, org_id, brand_id, group_id)
    if node is not None:
        require_internal_campaign(conn, org_id, brand_id, node["campaign_id"])
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
    node = get_group(conn, org_id, brand_id, group_id)
    if node is not None:
        require_internal_campaign(conn, org_id, brand_id, node["campaign_id"])
        # The only group-removal path: an adopted plan with zero groups is a dead end (adopt
        # refuses a second run, the structure editor has nowhere to add from) -- ads §6.34.
        # ponytail: count-then-delete without a campaign lock; two concurrent deletes of the
        # last two groups could both pass. Lock the campaign row if that ever shows up.
        if len(_groups_for_campaign(conn, org_id, brand_id, node["campaign_id"])) <= 1:
            raise ValueError("last_group")
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
              name: str, coordinates: dict, coordinates_snapshot: dict,
              scene: str | None = None) -> dict:
    """`scene` (F39-I03): the one sentence the delivery-plan model chose for this ad's copy to
    happen in; `None` for hand-made ads. `campaign_detail` selects `*`, so it flows out as-is."""
    require_internal_campaign(conn, org_id, brand_id, campaign_id)
    ad_id = new_id("ada")
    conn.execute(
        "INSERT INTO ads_ad (id, org_id, brand_id, campaign_id, group_id, name, audience_key,"
        " pain_key, angle_key, hook_key, proof_key, offer_key, format_key,"
        " coordinates_snapshot_json, scene)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (ad_id, org_id, brand_id, campaign_id, group_id, name,
         coordinates.get("audience"), coordinates.get("pain"), coordinates.get("angle"),
         coordinates.get("hook"), coordinates.get("proof"), coordinates.get("offer"),
         coordinates.get("format"), jsonb(coordinates_snapshot), scene),
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
    node = get_ad(conn, org_id, brand_id, ad_id)
    if node is not None:
        require_internal_campaign(conn, org_id, brand_id, node["campaign_id"])
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
    node = get_ad(conn, org_id, brand_id, ad_id)
    if node is not None:
        require_internal_campaign(conn, org_id, brand_id, node["campaign_id"])
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
        " ORDER BY created_at, id",
        (org_id, brand_id, campaign_id),
    ).fetchall()
    return [dict(r) for r in rows]


def set_ad_asset_ready(conn: _AnyConn, org_id: str, brand_id: str, ad_id: str, *,
                        actor: str | None, ready: bool) -> dict:
    """F03-I08：使用者手動勾／取消勾「素材已就位」——不是 `ads_action`（沒有東西碰到平台，
    §0「It is not an ads_action」），單純這一列自己的事實。"""
    node = get_ad(conn, org_id, brand_id, ad_id)
    if node is not None:
        require_internal_campaign(conn, org_id, brand_id, node["campaign_id"])
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
    """F32-I01: binding the campaign node by launch readback is the moment a hand-launched
    campaign becomes `live` (2026-09-26 ruling: live = bound to a platform object, not
    "platform reports ACTIVE"). Only `ready` moves; a re-bind on `live`, or any other status,
    is left alone, so the simulated adapter and re-reads stay untouched."""
    require_internal_campaign(conn, org_id, brand_id, campaign_id)
    conn.execute(
        "UPDATE ads_campaign SET external_id = %s, external_name = %s, external_status = %s,"
        " local_state = 'bound', bound_at = now(),"
        " status = CASE WHEN status = 'ready' THEN 'live' ELSE status END"
        " WHERE org_id = %s AND brand_id = %s AND id = %s",
        (external_id, external_name, external_status, org_id, brand_id, campaign_id),
    )


def bind_group(conn: _AnyConn, org_id: str, brand_id: str, group_id: str, *,
               external_id: str, external_name: str, external_status: str | None) -> None:
    node = get_group(conn, org_id, brand_id, group_id)
    if node is not None:
        require_internal_campaign(conn, org_id, brand_id, node["campaign_id"])
    conn.execute(
        "UPDATE ads_delivery_group SET external_id = %s, external_name = %s,"
        " external_status = %s, local_state = 'bound', bound_at = now()"
        " WHERE org_id = %s AND brand_id = %s AND id = %s",
        (external_id, external_name, external_status, org_id, brand_id, group_id),
    )


def bind_ad(conn: _AnyConn, org_id: str, brand_id: str, ad_id: str, *,
            external_id: str, external_name: str, external_status: str | None) -> None:
    node = get_ad(conn, org_id, brand_id, ad_id)
    if node is not None:
        require_internal_campaign(conn, org_id, brand_id, node["campaign_id"])
    conn.execute(
        "UPDATE ads_ad SET external_id = %s, external_name = %s, external_status = %s,"
        " local_state = 'bound', bound_at = now()"
        " WHERE org_id = %s AND brand_id = %s AND id = %s",
        (external_id, external_name, external_status, org_id, brand_id, ad_id),
    )


# -- app.core.cleanup 登記（品牌刪除連鎖清資料，ARCHITECTURE.md §4） -------------------------

_CHILD_TABLES = (
    ("ads_review_monitor", "持續廣告檢討條件"),
    ("ads_handoff_item", "人工交接逐項核對"),
    ("ads_material_operation", "素材任務保存紀錄"),
    ("ads_material_revision", "素材需求版本"),
    ("ads_material_task", "活動素材需求"),
    ("ads_asset_observation_claim", "素材版本成效歸屬"),
    ("ads_asset_binding", "素材版本平台證據"),
    ("ads_asset_placement", "自帶素材安排"),
    ("ads_asset_suggestion_reservation", "素材建議費用預留"),
    ("ads_asset_suggestion_batch", "素材建議批次"),
    ("ads_asset_upload", "素材上傳紀錄"),
    ("ads_asset_upload_batch", "素材上傳批次"),
    ("ads_user_asset", "品牌自帶原檔"),
    ("ads_external_listing", "既有活動清單"),
    ("ads_external_sync_job", "既有活動同步"),
    ("ads_external_daily", "既有活動來源成效"),
    ("ads_external_entity", "既有活動來源結構"),
    ("ads_action", "投放中心操作紀錄"),
    ("ads_change_set", "廣告變更核准清單"),
    ("ads_review_round", "單則廣告檢討紀錄"),
    ("ads_month_budget", "品牌月預算"),
    ("ads_runtime_event", "投放中心背景執行紀錄"),
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
    # The original plan survives assignment edits; release the scoped reference
    # before deleting its material placement during brand cleanup.
    conn.execute(
        "UPDATE ads_ad SET material_placement_id=NULL,material_placement_revision=NULL "
        "WHERE brand_id=%s", (brand_id,),
    )
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
