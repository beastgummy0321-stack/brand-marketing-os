"""app/ads/outcome.py — the performance tab of an internal campaign (§0 the "outcome" link).
Private to app/ads (container contract §1).

F37 (one performance pipeline): an internal campaign's numbers are the platform sync's own
rows -- `ads_external_daily` read through `repository.performance_rows` (Contract P), the same
rows and the same recorded coverage the home, workspace, triage and review read. The manual
ingest path (`meta_entity_spend` → `POST …/ingest` → a second daily table) is gone; a simulated
campaign writes the same rows through `adapters/simulated.py` like a platform, so nothing here
branches on real/simulated. `rows()` is the one read every other ads reader of daily
performance calls (`experiments`, `ab_pairs`, `visual_learning`, `simulation_recovery`).

`purchases`/`revenue` are nullable: `NULL` means untracked, `0` a real, counted zero. Every
reader below (`_bucket`, `repository._outcome_totals`, `experiments.py`) sums only the
non-`NULL` rows and reports `None`/`NULL` when nothing in the set is tracked -- unknown is never
coerced into zero. `spend`/`impressions`/`clicks` of a platform row may also be unknown; `_bucket`
sums the known ones (a row with no known spend adds nothing, it is not invented).

Coverage (Contract P/Q, F49 Contract V): `coverage` names the campaign-window days nobody read
(`coverage.gap`: no row and no clean read range) over
`start_date … min(end_date, last complete day)`
-- today is never a complete day -- and says `never_synced` instead of a wall of dates when
nothing was read.
"""

import json
from datetime import date, timedelta

from app.core import settings as coresettings
from app.core.db import Conn, ConnProxy

_AnyConn = Conn | ConnProxy


SAMPLE_UNTRACKED = "未追蹤"


def sample_bucket(purchases: int | None, days: int) -> str:
    """低（< `triage.MIN_RESULT_EVENTS` purchases 或 < `triage.WINDOW_STEPS[0]` 天）／中（到 49）／
    高（>= 50）；`purchases is None`（沒追蹤到購買數）＝「未追蹤」，never 低 or 0. F48 Contract R:
    a shown label only -- no verdict reads it -- and its thresholds are the ruler's own
    (the same "too new" line as triage's `sample`), never a copy."""
    from app.ads import triage  # 延遲 import 避免循環

    if purchases is None:
        return SAMPLE_UNTRACKED
    if purchases < triage.MIN_RESULT_EVENTS or days < triage.WINDOW_STEPS[0]:
        return "低"
    if purchases < 50:
        return "中"
    return "高"


def rows(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str, kind: str) -> list:
    """F37 Contract P: this campaign's daily platform rows at `kind` in {"group", "ad"}, keyed by
    the LOCAL node id -- `repository.performance_rows`, the one mapping."""
    from app.ads import repository as ads_repo  # 延遲 import 避免循環

    return ads_repo.performance_rows(conn, org_id, brand_id, campaign_id, kind)


def _fetch_rows(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str,
                 entity_kind: str) -> list:
    return rows(conn, org_id, brand_id, campaign_id, entity_kind)


def period_window(conn: _AnyConn, org_id: str, brand_id: str, campaign: dict) -> dict:
    """The internal campaign's inclusive window through its last completed account day.

    Raw history and explicitly requested comparison/month windows remain independent.
    Missing campaign dates are unknown; a future window contains no completed days.
    """
    from app.ads import coverage

    basis: dict = {}
    cutoff = coverage.last_complete_day(conn, org_id, brand_id, campaign["id"], basis=basis)
    start, planned_end = campaign.get("start_date"), campaign.get("end_date")
    state, selected_start, selected_end, days = "missing_dates", None, None, 0
    if start is not None and planned_end is not None and start <= planned_end:
        end = min(planned_end, cutoff)
        state = "future"
        if start <= end:
            state = "ready"
            selected_start, selected_end = start.isoformat(), end.isoformat()
            days = (end - start).days + 1
    return {
        "start": selected_start,
        "end": selected_end,
        "days": days,
        "campaign_start": start.isoformat() if start else None,
        "campaign_end": planned_end.isoformat() if planned_end else None,
        "last_complete_day": cutoff.isoformat(),
        "basis": "campaign_window",
        "incomplete_day_policy": "excluded",
        "state": state,
        **basis,
    }


def select_period(rows: list, window: dict) -> list:
    """Select rows without altering the unbounded history reader."""
    if window["start"] is None or window["end"] is None:
        return []
    start, end = date.fromisoformat(window["start"]), date.fromisoformat(window["end"])
    return [row for row in rows if start <= row["day"] <= end]


def period_projection(
    conn: _AnyConn, org_id: str, brand_id: str, campaign: dict, group_rows: list, ad_rows: list
) -> dict:
    """Project supplied raw rows using one account cutoff, without campaign-detail recursion."""
    window = period_window(conn, org_id, brand_id, campaign)
    selected_groups, selected_ads = (
        select_period(group_rows, window),
        select_period(ad_rows, window),
    )
    totals = period_bucket(selected_groups)
    return {
        "scope": {
            **window,
            "currency": totals["currency"],
            "attribution_key": totals["attribution_key"],
            "reason": totals["reason"],
            "caption": _scope_caption(window),
            "reason_text": _reason_text(totals["reason"]),
        },
        "group_rows": selected_groups,
        "ad_rows": selected_ads,
        "totals": totals,
    }


def _scope_caption(window: dict) -> str:
    if window["state"] == "missing_dates":
        return "活動期間未設定，無法彙整本期。"
    if window["state"] == "future":
        return "還沒有完整的本期資料日。"
    label = "本期" if window["basis"] == "campaign_window" else "查詢期間"
    day_basis = (
        "帳戶時區未知，採保守完整日"
        if window["day_basis"] == "conservative_org_fallback"
        else "只計完整帳戶日"
    )
    return f"{label} {window['start']} ～ {window['end']}；{day_basis}，今日尚未完整的資料不計入。"


def _reason_text(reason: str | None) -> str | None:
    if reason is None:
        return None
    return {
        "no_data": "本期尚無成效資料，缺資料不算零。",
        "mixed_attribution": "本期有不同歸因，不能合計或比較。",
        "attribution_unknown": "本期歸因尚未核實，不能合計或比較。",
        "mixed_currency": "本期有不同幣別，金額與花費占比不能合計。",
        "currency_unknown": "本期幣別尚未核實，金額與花費占比未知。",
        "spend_unknown": "本期有未知花費，合計花費與花費占比未知。",
    }.get(reason)


def period_bucket(rows: list) -> dict:
    """Keep the existing two ROAS/known-result sums within one currency and attribution.

    No inferred exchange rate or attribution priority. Unknown spend is not fabricated zero;
    missing result/revenue tracking retains the existing named optimistic/conservative bases.
    """
    bucket = _bucket(rows)
    for key in ("impressions", "clicks"):
        if not any(row[key] is not None for row in rows):
            bucket[key] = None
    currencies = {row["currency"] for row in rows}
    attributions = {row.get("attribution_key") for row in rows}
    currency = next(iter(currencies)) if len(currencies) == 1 else None
    attribution = next(iter(attributions)) if len(attributions) == 1 else None
    reason = (
        "no_data"
        if not rows
        else "mixed_attribution"
        if len(attributions) > 1
        else "attribution_unknown"
        if attribution is None
        else "mixed_currency"
        if len(currencies) > 1
        else "currency_unknown"
        if currency is None
        else "spend_unknown"
        if any(row["spend"] is None for row in rows)
        else None
    )
    if reason in {"mixed_attribution", "attribution_unknown"}:
        bucket = dict.fromkeys(bucket)
    elif reason is not None:
        for key in ("spend", "revenue", "cpa", "roas_tracked_spend", "roas_all_spend"):
            bucket[key] = None
        if not rows:
            bucket["impressions"] = bucket["clicks"] = None
    return {**bucket, "currency": currency, "attribution_key": attribution, "reason": reason}


def native_period_view(conn: _AnyConn, org_id: str, brand_id: str, campaign: dict) -> dict:
    """Imported performance keeps its existing requested range, excluding incomplete days.

    The external history reader itself is unchanged. A missing campaign date is not invented:
    the range names the existing request default, distinct from the internal campaign period.
    """
    from app.ads import coverage, external_repository

    requested_end = coresettings.today_for_org(conn, org_id=org_id)
    requested_start = requested_end - timedelta(days=29)
    basis: dict = {}
    cutoff = coverage.last_complete_day(conn, org_id, brand_id, campaign["id"], basis=basis)
    end = min(requested_end, cutoff)
    view = external_repository.external_view(
        conn, org_id, brand_id, campaign["id"], start=requested_start, end=end
    )
    # Both cursors are independent. A scoped performance response is complete, never a first page.
    for kind, rows_key in (("entity", "entities"), ("observation", "observations")):
        cursor_key = f"next_{kind}_cursor"
        cursor = view[cursor_key]
        seen = set()
        while cursor:
            if cursor in seen:
                raise ValueError("平台資料分頁重複，請重新載入。")
            seen.add(cursor)
            page = external_repository.external_view(
                conn, org_id, brand_id, campaign["id"], start=requested_start, end=end,
                **{f"{kind}_after": cursor},
            )
            view[rows_key].extend(page[rows_key])
            if kind == "entity":
                view["connections"].extend(page["connections"])
            cursor = page[cursor_key]
        view[cursor_key] = None
    view["connections"] = list({
        (row["platform"], row["source_account"]): row for row in view["connections"]
    }.values())
    view["scope"] = {
        "basis": "requested_range",
        "start": requested_start.isoformat(),
        "end": end.isoformat(),
        "requested_start": requested_start.isoformat(),
        "requested_end": requested_end.isoformat(),
        "last_complete_day": cutoff.isoformat(),
        "incomplete_day_policy": "excluded",
        "state": "ready",
        "days": (end - requested_start).days + 1,
        **basis,
    }
    view["scope"]["caption"] = _scope_caption(view["scope"])
    from app.ads import targets

    target = targets.resolve(conn, org_id, brand_id, campaign)
    gap = coverage.gap(conn, org_id, brand_id, campaign["id"], requested_start, end)
    view["result_views"] = native_result_views(
        view["observations"], target, view["scope"], gap,
        cap_unit(conn, brand_id, target, campaign=campaign),
    )
    return view


def native_result_views(observations: list, target: dict, scope: dict, gap: dict,
                        unit: dict) -> list[dict]:
    """Project each native scope/currency/attribution independently through the same reducer."""
    from app.ads import review_evidence

    groups: dict[tuple, list] = {}
    for row in observations:
        if review_evidence.is_monthly_budget_row(row["attribution_key"]):
            continue
        key = (row["metric_scope"], row["currency"], row["attribution_key"])
        groups.setdefault(key, []).append({**row, "observation_id": row.get("id")})
    reason = "needs_resync" if gap["never_synced"] or gap["missing_days"] else None
    return [
        {**result_projection(rows, target, {**scope, "metric_scope": key[0]},
                             comparison=compare_cap_unit(unit, key[1]), reason=reason),
         "scope_key": json.dumps(key, ensure_ascii=False, separators=(",", ":"))}
        for key, rows in sorted(groups.items(), key=lambda entry: str(entry[0]))
    ]


def cap_unit(conn: _AnyConn, brand_id: str, cap: dict, *, campaign: dict) -> dict:
    """Resolve only units supported by the cap's recorded source.

    The manual NT$ input records source=user. Other historical own sources lack a frozen
    unit; a current product/account cannot establish the unit of their stored value.
    """
    from app.brand_intelligence import repository as bi_repo

    cap_currency = None
    source = ((campaign.get("context_json") or {}).get("field_sources") or {}).get("cap")
    unit_basis = None
    if cap["basis"] == "own" and source == "user":
        cap_currency, unit_basis = "TWD", "manual_ntd_input"
    if cap["basis"] == "break_even" and cap.get("product_id"):
        economics = bi_repo.get_product_economics(conn, brand_id, cap["product_id"])
        cap_currency = (
            economics.get("currency") if economics and economics["status"] == "confirmed" else None
        )
        unit_basis = "confirmed_product_economics" if cap_currency else None
    return {"basis": cap["basis"], "currency": cap_currency,
            "source": source, "unit_basis": unit_basis}


def break_even_unit(conn: _AnyConn, brand_id: str, target: dict, *, campaign: dict) -> dict:
    """The current computed break-even's independent confirmed economics unit.

    A computable pending row does not establish a comparable money unit. This does not
    reinterpret the stored own cap or change the existing scalar target resolver.
    """
    cap = {**target, "basis": "break_even"}
    if target.get("break_even") is None:
        cap["product_id"] = None
    return {**cap_unit(conn, brand_id, cap, campaign=campaign), "source": "product_economics"}


def price_unit(conn: _AnyConn, brand_id: str, target: dict, *, campaign: dict) -> dict:
    """A known price may have a confirmed unit even while its cost/break-even is missing."""
    cap = {**target, "basis": "break_even"}
    if target.get("price") is None:
        cap["product_id"] = None
    return {**cap_unit(conn, brand_id, cap, campaign=campaign), "source": "product_economics"}


def compare_cap_unit(unit: dict, currency: str | None) -> dict:
    """Compare a recorded cap unit with one observed window; never convert money."""
    reason = None
    if unit["basis"] in {"own", "break_even"}:
        reason = (
            "cap_currency_unknown"
            if unit["currency"] is None or currency is None
            else "cap_currency_mismatch"
            if unit["currency"] != currency
            else None
        )
    return {
        **unit,
        "reason": reason,
        "message": "上限與本期成效的幣別不同或尚未核實，不能比較。" if reason else None,
    }


def cap_comparison(conn: _AnyConn, brand_id: str, cap: dict, currency: str | None,
                   *, campaign: dict) -> dict:
    return compare_cap_unit(cap_unit(conn, brand_id, cap, campaign=campaign), currency)


def roas_pair(rows: list) -> dict:
    """F51 Contract F: the two ROAS bases of `rows` (`app/core/figures.py::BASES`), keyed by their
    basis codes -- `_bucket`'s own (one computation), for a reader that needs only these two
    (the workspace totals)."""
    bucket = _bucket(rows)
    return {key: bucket[key] for key in ("roas_all_spend", "roas_tracked_spend")}


def _bucket(rows: list) -> dict:
    """跟 `app/schedule/performance.py::_bucket()` 同一套算法（再實作一份，不 import —
    container contract §5）。F51 Contract F：ROAS 以口徑命名（key 就是口徑代碼）——
    `roas_tracked_spend`（樂觀）只算「有追蹤到營收」那一份花費當分母，`roas_all_spend`（保守）
    用**全部**花費當分母——兩個都是真的，只印一個是在說謊的另一半。
    購買數／營收是否追蹤直接看欄位是不是 `NULL`（平台列的 `purchases`／`revenue` 是 nullable，
    未追蹤就是 `NULL`，不用猜來源是哪個平台）；有追蹤到的列一起加總，完全沒有追蹤到的列讓整包
    回 `None`，未追蹤永遠不是 0。花費／曝光／點擊只加總已知的值。"""
    spend = round(sum(float(r["spend"]) for r in rows if r["spend"] is not None), 2)
    impressions = sum(float(r["impressions"]) for r in rows if r["impressions"] is not None)
    clicks = sum(float(r["clicks"]) for r in rows if r["clicks"] is not None)

    tracked_purchase_rows = [r for r in rows if r["purchases"] is not None]
    purchases = (
        sum(float(r["purchases"]) for r in tracked_purchase_rows) if tracked_purchase_rows
        else None
    )

    revenue_tracked_rows = [r for r in rows if r["revenue"] is not None]
    revenue = None
    roas_tracked_spend = None
    roas_all_spend = None
    if revenue_tracked_rows:
        revenue = round(sum(float(r["revenue"]) for r in revenue_tracked_rows), 2)
        spend_tracked = sum(
            float(r["spend"]) for r in revenue_tracked_rows if r["spend"] is not None
        )
        roas_tracked_spend = (revenue / spend_tracked) if spend_tracked else None
        roas_all_spend = (revenue / spend) if spend else None

    complete_purchases = bool(rows) and all(r["purchases"] is not None for r in rows)
    complete_spend = bool(rows) and all(r["spend"] is not None for r in rows)
    cpa = spend / purchases if purchases and complete_purchases and complete_spend else None
    ctr = (clicks / impressions) if impressions else None

    return {
        "spend": spend, "impressions": impressions, "clicks": clicks,
        "purchases": purchases, "revenue": revenue, "cpa": cpa, "ctr": ctr,
        "roas_tracked_spend": roas_tracked_spend, "roas_all_spend": roas_all_spend,
    }


def window_totals(conn: _AnyConn, org_id: str, brand_id: str, campaign: dict) -> dict:
    """F51 (planning #16): a closed campaign's own totals over its window `start_date … end_date`
    across EVERY ad on the platform, ranked or not -- the ad-scope rows and the rules each ranked
    ad's own numbers were cut by (`review_evidence.aggregate`, `triage._ad_spend`／`_ad_view`), so
    a campaign total never skips an unranked ad and never mixes units with its rows.
    `{spend, results, currency}`: spend `None` on an unknown day or across two currencies (never a
    sum across currencies), results `None` unless every row agrees on one known result; no window
    or no row at all is all `None` -- never 0."""
    from app.ads import review_evidence, triage  # 延遲 import 避免循環

    start, end = campaign.get("start_date"), campaign.get("end_date")
    if start is None or end is None or end < start:
        return {"spend": None, "results": None, "currency": None}
    rows = [
        dict(r) for r in conn.execute(
            "SELECT * FROM ads_external_daily WHERE org_id = %s AND brand_id = %s"
            " AND campaign_id = %s AND metric_scope = 'ad' AND day BETWEEN %s AND %s",
            (org_id, brand_id, campaign["id"], start, end),
        ).fetchall()
    ]
    aggregated = review_evidence.aggregate(rows, start, end)
    if not aggregated["series"]:
        return {"spend": None, "results": None, "currency": None}
    spend = triage._ad_spend(aggregated)  # noqa: SLF001 -- the one ad-spend rule
    view = triage._ad_view(aggregated)  # noqa: SLF001 -- the one ad result view
    currencies = {s["currency"] for s in aggregated["series"] if s["metric_scope"] == "ad"}
    return {
        "spend": spend,
        "results": triage._sales(view),  # noqa: SLF001 -- known whole count, else None
        "currency": next(iter(currencies)) if len(currencies) == 1 else None,
    }


def _daily_series(rows: list) -> list:
    by_day: dict[date, list] = {}
    for row in rows:
        by_day.setdefault(row["day"], []).append(row)
    return [{"day": day, **period_bucket(day_rows)} for day, day_rows in sorted(by_day.items())]


def _coverage(conn: _AnyConn, org_id: str, brand_id: str, campaign: dict, window: dict) -> dict:
    """Contract P's `coverage`: the campaign window `start_date … min(end_date, last complete
    day)` (F50 Contract K: `coverage.last_complete_day`, the campaign's ad-account day) checked
    day by day by `coverage.gap` (F49 Contract V, the rule triage/closeout/review share).
    No window (no start date, or it starts today or later) ⇒ `expected` 0 and nothing missing;
    `never_synced` still says whether anything was ever read."""
    from app.ads import coverage  # 延遲 import 避免循環

    if window["start"] is None or window["end"] is None:
        cutoff = date.fromisoformat(window["last_complete_day"])
        gap = coverage.gap(conn, org_id, brand_id, campaign, cutoff, cutoff)
        never_synced = gap["never_synced"]
        return {"start": None, "end": None, "expected": 0, "missing": 0, "missing_days": [],
                "never_synced": never_synced}
    start, end = date.fromisoformat(window["start"]), date.fromisoformat(window["end"])
    gap = coverage.gap(conn, org_id, brand_id, campaign, start, end)
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "expected": (end - start).days + 1,
        "missing": len(gap["missing_days"]),
        "missing_days": gap["missing_days"],
        "never_synced": gap["never_synced"],
    }


def _period_view(totals: dict, group_rows: list, result_kind: str | None) -> dict | None:
    """Observed goal results use the same availability-aware reducer as ad reviews.

    Legacy purchase totals and the target kind cannot supply or rename the observation unit.
    """
    del totals, result_kind  # A target cannot relabel the observed purchase field.
    from app.ads import review_evidence

    if not group_rows:
        return None
    rows = [{**row, "metric_scope": row.get("metric_scope", "adset")} for row in group_rows]
    aggregated = review_evidence.aggregate(rows, min(r["day"] for r in rows),
                                          max(r["day"] for r in rows))
    views = aggregated["result_views"]
    if len(views) != 1:
        return {"reason": "mixed_currency", "result_count": None, "result_kind": None,
                "cost_per_result": None, "currency": None}
    return views[0]


def result_projection(group_rows: list, cap: dict, scope: dict, *, comparison=None,
                      reason=None) -> dict:
    """The actual goal result from the original availability-aware observation aggregate."""
    from app.ads import performance_evidence

    view = _period_view({}, group_rows, None)
    currencies = {row["currency"] for row in group_rows}
    spend = None
    if group_rows and len(currencies) == 1 and None not in currencies and all(
        row["spend"] is not None and (row.get("availability") or {}).get("spend") == "available"
        for row in group_rows
    ):
        spend = sum(float(row["spend"]) for row in group_rows)
    return performance_evidence.project(
        view, spend, cap, scope, comparison=comparison, reason=reason,
        evidence_refs=[row["observation_id"] for row in group_rows if row.get("observation_id")],
    )


def _period_grade(totals: dict, group_rows: list, cap: dict, days: int) -> dict:
    """F40-I01: `totals.grade` = the one cap ruler (`triage.grade_window`, ads.md §6.33) over the
    whole period -- `{grade, label}`, `grade` in on_target|watch|over|wasted|insufficient|
    no_target. No cap, or a cap with no result kind anywhere (the precondition `triage` and
    `period_grades._grade` share), is `no_target`."""
    del totals
    return _result_grade(result_projection(group_rows, cap, {"days": days}), cap, days)


def _result_grade(result: dict, cap: dict, days: int) -> dict:
    """Grade the goal projection; incidental purchase-series gaps cannot replace its spend."""
    from app.ads import triage

    if cap["value"] is not None and cap["result_kind"] is None:
        return {"grade": "no_target", "label": triage.GRADE_LABELS["no_target"]}
    view = {"result_count": result["count"], "cost_per_result": result["cost_per_result"],
            "reason": result["reasons"][0] if result["reasons"] else None}
    grade, label, _reason = triage.grade_window(
        view, result["spend"], cap["value"], days,
    )
    return {"grade": grade, "label": label}


def summary(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str) -> dict:
    """成效分頁的整包 payload：campaign 層總計（只算投放組粒度的列，§0「Money totals
    belong to the group level」）、每日序列、每投放組／每廣告一列（含花費占比）、資料覆蓋率
    跟最後更新時間。F40-I01: `totals.grade` is the period's one-ruler grade the 成效分頁's
    「這期狀態列」 prints beside 整期合計 (`_period_grade`, the backend's answer -- never a
    frontend copy of the ruler)."""
    from app.ads import repository as ads_repo
    from app.ads import targets

    detail = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)
    if detail is None:
        raise ValueError("campaign_unknown")
    projected = period_projection(conn, org_id, brand_id, detail,
                                  rows(conn, org_id, brand_id, campaign_id, "group"),
                                  rows(conn, org_id, brand_id, campaign_id, "ad"))
    group_rows, ad_rows = projected["group_rows"], projected["ad_rows"]
    totals = projected["totals"]
    daily = _daily_series(group_rows)
    cap = targets.resolve(conn, org_id, brand_id, detail)
    comparison = cap_comparison(conn, brand_id, cap, totals["currency"], campaign=detail)

    group_total_spend = totals["spend"]
    by_group: dict[str, list] = {}
    for row in group_rows:
        by_group.setdefault(row["entity_id"], []).append(row)
    groups_table = []
    for group in detail["groups"]:
        node_rows = by_group.get(group["id"], [])
        bucket = period_bucket(node_rows)
        bucket["group_id"] = group["id"]
        bucket["name"] = group["name"]
        bucket["spend_share"] = (bucket["spend"] / group_total_spend) \
            if group_total_spend and bucket["spend"] is not None else None
        groups_table.append(bucket)

    ad_total_spend = period_bucket(ad_rows)["spend"]
    by_ad: dict[str, list] = {}
    for row in ad_rows:
        by_ad.setdefault(row["entity_id"], []).append(row)
    ads_table = []
    for group in detail["groups"]:
        for ad in group["ads"]:
            node_rows = by_ad.get(ad["id"], [])
            bucket = period_bucket(node_rows)
            bucket["ad_id"] = ad["id"]
            bucket["name"] = ad["name"]
            bucket["spend_share"] = (bucket["spend"] / ad_total_spend) \
                if ad_total_spend and bucket["spend"] is not None else None
            ads_table.append(bucket)

    all_rows = group_rows + ad_rows
    last_data_at = max((r["observed_at"] for r in all_rows), default=None)
    coverage = _coverage(conn, org_id, brand_id, detail, projected["scope"])
    goal_view = result_projection(group_rows, cap, projected["scope"], comparison=comparison,
                                 reason="needs_resync" if coverage["never_synced"]
                                 or coverage["missing_days"] else None)
    totals["grade"] = _result_grade(goal_view, cap, projected["scope"]["days"])

    return {
        "totals": totals,
        "daily": daily,
        "groups": groups_table,
        "ads": ads_table,
        "coverage": coverage,
        "last_data_at": last_data_at,
        "scope": projected["scope"],
        "cap_comparison": comparison,
        "result_view": goal_view,
    }
