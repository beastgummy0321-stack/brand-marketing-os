"""Bounded single-ad evidence. Arithmetic belongs here, judgment belongs to the model."""

from collections import defaultdict
from datetime import date, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app import orders
from app.ads import asset_binding_repository as bindings
from app.ads import asset_suggestion_policy as policy
from app.ads import change_control_data as changes
from app.ads import external_sync, review_monitor_source
from app.ads.adapters.external import SourceReadError
from app.ads.external_repository import is_monthly_budget_row
from app.brand_intelligence import repository as brands
from app.core import db, settings
from app.llm import context_compiler

METRICS = ("spend", "impressions", "clicks", "purchases", "revenue")
LIMITATIONS = [
    "平台歸因收入不是商務實收；品牌訂單淨額不可分配至單則廣告。",
    "商務來源訂單淨額未經會計核實；未付款、未知幣別及不完整覆蓋不可當實收或計算跨來源 ROAS。",
    "歷史投放條件未完整確認：目前素材快照不能證明整期素材與投放條件相同。",
    "前後比較不是素材因果；平台設定相符不代表已改善。",
    "商務記錄日期時區尚未確認，商務與平台日期口徑不保證一致。",
]


def _predates_result_columns(row):
    """F16-I06: a row written before the F16-I03 result columns existed was never touched by
    `external_repository.upsert_observation`'s availability bookkeeping, so it carries no
    `result_count` entry in `availability` at all (on top of all four result fields being NULL).
    A row a result mapping actually ran against but that simply had nothing to report that day
    (e.g. a known objective, no purchase yet) always has that `availability` entry recorded as
    `"unknown"` -- never absent. This is the only thing `needs_resync` may key off; never a date
    constant, never a guess."""
    return (
        row.get("result_kind") is None
        and row.get("result_count") is None
        and row.get("result_action") is None
        and row.get("result_attribution") is None
        and "result_count" not in (row.get("availability") or {})
    )


def _result_view(key, group):
    """This entity's own result, over ALL rows of one (metric_scope, currency) regardless of
    `attribution_key` (F16-I03 repair): the per-`attribution_key` series above groups by the
    purchase-derived `attribution_key`, so one ad can flap between keys the day an incidental
    purchase lands, tearing one ad's result into two series. This view never groups by
    `attribution_key`, so it cannot be torn that way. `group` never contains monthly-budget rows
    (`aggregate()` excludes them before grouping, F16-I06) -- their NULL `result_count` must never
    force this view unknown.

    Fail-closed, same family as the `len(known) == len(group)` rule above: rows must agree on
    `result_kind`/`result_action`/`result_attribution` (no "pick first" — Meta's `page_engagement`
    already contains `post_engagement`; summing counts from two different action types under one
    label is never a real quantity), and every row must have a known `result_count` and `spend`
    or the whole window is unknown. Never a partial sum divided by partial or full spend.

    `reason` (F16-I06) is one of three distinct, truthful signals for an unknown window:
    `mixed_result_definition` (rows disagree on what they're even measuring, fail closed rather
    than pick one); `needs_resync` (every row missing a result count predates the F16-I03 result
    columns -- a re-sync, not a wait, resolves it); `result_unknown_days` (a result mapping ran
    but genuinely has nothing to report, or spend itself is unknown -- no re-sync fixes that).

    `availability.result_count == "derived_zero"` (F18-I01, `app/ads/tracked_zero.py`) counts as
    known here on the same footing as a platform-reported `"available"` row -- it is a rule-marked
    absence of the campaign's own demonstrated result, not a guess. `derived_zero_days` reports how
    many of the days counted as known were filled this way, so a reader can tell "zero, proven
    absent" apart from "zero, actually reported" without a second query.
    """
    def _known(field):
        return {r[field] for r in group if r.get(field) is not None}

    metric_scope, currency = key
    kinds, actions, attributions = _known("result_kind"), _known("result_action"), _known(
        "result_attribution"
    )
    result_known = [
        r
        for r in group
        if r.get("result_count") is not None
        and r["availability"].get("result_count") in {"available", "derived_zero"}
    ]
    derived_zero = [
        r for r in result_known if r["availability"].get("result_count") == "derived_zero"
    ]
    spend_known = [
        r for r in group if r["spend"] is not None and r["availability"].get("spend") == "available"
    ]
    reason = None
    if len(kinds) > 1 or len(actions) > 1 or len(attributions) > 1:
        reason = "mixed_result_definition"
    elif len(spend_known) != len(group):
        reason = "result_unknown_days"
    elif len(result_known) != len(group):
        missing = [r for r in group if r not in result_known]
        reason = (
            "needs_resync"
            if all(_predates_result_columns(r) for r in missing)
            else "result_unknown_days"
        )
    result_count = cost_per_result = None
    if reason is None:
        result_count = sum(float(r["result_count"]) for r in result_known)
        spend_total = sum(float(r["spend"]) for r in spend_known)
        cost_per_result = spend_total / result_count if result_count else None
    return {
        "metric_scope": metric_scope,
        "currency": currency,
        "result_kind": next(iter(kinds)) if len(kinds) == 1 else None,
        "result_action": next(iter(actions)) if len(actions) == 1 else None,
        "result_attribution": next(iter(attributions)) if len(attributions) == 1 else None,
        "result_count": result_count,
        "cost_per_result": cost_per_result,
        "days_present": len({r["day"] for r in group}),
        "days_known": len({r["day"] for r in result_known}),
        "derived_zero_days": len({r["day"] for r in derived_zero}),
        "reason": reason,
    }


def aggregate(rows, start, end):
    # F16-I06: account-month budget source rows share entity/day/`metric_scope`/currency with
    # ordinary observation rows but are a different grain entirely (§0 "one shared definition") --
    # excluded here, at the one point both the per-`attribution_key` series and the result view
    # below are built from, not per reader.
    rows = [r for r in rows if not is_monthly_budget_row(r["attribution_key"])]
    groups = defaultdict(list)
    for row in rows:
        groups[
            tuple(row[k] for k in ("metric_scope", "attribution_key", "currency", "source"))
        ].append(row)
    series = []
    for key, group in sorted(groups.items(), key=lambda pair: str(pair[0])):
        metrics, counts = {}, {}
        for metric in METRICS:
            known = [
                float(r[metric])
                for r in group
                if r[metric] is not None and r["availability"].get(metric) == "available"
            ]
            counts[metric] = len(known)
            metrics[metric] = sum(known) if len(known) == len(group) else None
        for name, numerator, denominator, multiplier in (
            ("ctr", "clicks", "impressions", 100),
            ("cpc", "spend", "clicks", 1),
            ("cpa", "spend", "purchases", 1),
            ("roas", "revenue", "spend", 1),
        ):
            a, b = metrics[numerator], metrics[denominator]
            metrics[name] = (
                a / b * multiplier if a is not None and b and (key[2] or name == "ctr") else None
            )
        series.append(
            dict(zip(("metric_scope", "attribution_key", "currency", "source"), key, strict=True))
            | {
                "row_count": len(group),
                "days_present": len({r["day"] for r in group}),
                "metrics": metrics,
                "known_counts": counts,
            }
        )
    # The campaign's own result (F16-I03 repair): one view per (metric_scope, currency), over
    # every row of that scope regardless of `attribution_key`. Previous-vs-current comparison of
    # "this campaign's own result" reads this, never the per-`attribution_key` series above.
    result_groups = defaultdict(list)
    for row in rows:
        result_groups[(row["metric_scope"], row["currency"])].append(row)
    result_views = [
        _result_view(key, group)
        for key, group in sorted(result_groups.items(), key=lambda pair: str(pair[0]))
    ]
    expected, present = (end - start).days + 1, len({r["day"] for r in rows})
    return {
        "row_count": len(rows),
        "days_present": present,
        "days_expected": expected,
        "missing_days": expected - present,
        "series": series,
        "result_views": result_views,
    }


def premise(entity, campaign):
    result = {
        "entity": {
            k: entity.get(k)
            for k in (
                "id",
                "platform",
                "source_account",
                "native_id",
                "native_status",
                "budget_type",
                "budget_amount",
                "currency",
                "start_date",
                "end_date",
            )
        },
        "creative_hash": bindings.creative_hash(entity.get("creative") or {}),
        "goal": changes.context(campaign),
    }
    # Match jsonb's numeric encoding before hashing both live and persisted premises.
    # Otherwise Decimal('2') hashes as the string '2', but reads back as numeric 2.0.
    value = result["entity"].get("budget_amount")
    if value is not None:
        result["entity"]["budget_amount"] = float(value)
    for key in ("start_date", "end_date"):
        value = result["entity"].get(key)
        if isinstance(value, date):
            result["entity"][key] = value.isoformat()
    return result


def snapshot(
    conn, org, brand, campaign_id, entity_id, start, end, previous_id=None, *, automatic=False
):
    campaign = changes.campaign(conn, org, brand, campaign_id)
    if campaign["status"] == "closed":
        raise ValueError("已結案活動只能查看歷史檢討。")
    if not isinstance(start, date) or not isinstance(end, date):
        raise ValueError("請提供觀察期間。")
    today = settings.today_for_org(conn, org_id=org)
    if start > end or (end - start).days >= 31 or end >= today:
        raise ValueError("每回最多檢討 31 個已完整過去的日期；今天尚未完整，不能納入。")
    entity = bindings.entity(conn, org, brand, campaign_id, entity_id)
    if entity["native_kind"] != "ad":
        raise ValueError("每回檢討請選一則平台廣告。")
    timezone = None
    try:
        _, account = external_sync.account_reader(
            conn, org, brand, entity["platform"], entity["source_account"]
        )
        timezone = str(ZoneInfo(account.get("timezone_name") or ""))
    except (SourceReadError, ValueError, ZoneInfoNotFoundError):
        pass
    if timezone and end >= db.now_utc().astimezone(ZoneInfo(timezone)).date():
        raise ValueError("觀察結束日於來源帳戶時區尚未完整結束，請改選更早的日期。")
    prior_end = start - timedelta(days=1)
    prior_start = start - timedelta(days=(end - start).days + 1)
    rows = conn.execute(
        "SELECT * FROM ads_external_daily WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND entity_id=%s AND day BETWEEN %s AND %s ORDER BY day,id LIMIT 2001",
        (org, brand, campaign_id, entity_id, prior_start, end),
    ).fetchall()
    if len(rows) > 2000:
        raise ValueError("此廣告來源分組過多；請縮短觀察期間，原始資料保留。")
    current = aggregate([r for r in rows if r["day"] >= start], start, end)
    previous = aggregate([r for r in rows if r["day"] < start], prior_start, prior_end)
    bound = conn.execute(
        "SELECT creative_hash,valid_from,valid_to FROM ads_asset_binding WHERE org_id=%s "
        "AND brand_id=%s AND campaign_id=%s AND entity_id=%s ORDER BY valid_from LIMIT 101",
        (org, brand, campaign_id, entity_id),
    ).fetchall()
    if len(bound) > 100:
        raise ValueError("素材對應歷史超出單回檢討上限，請先整理來源。")
    mixed = len({r["creative_hash"] for r in bound if r["creative_hash"]}) > 1
    prior = None
    if previous_id:
        from app.ads import review_rounds

        value = review_rounds.get(conn, org, brand, campaign_id, previous_id)
        if value["entity_id"] != entity_id or value["window_end"] >= end:
            raise ValueError("前回必須是同一則廣告且觀察結束日早於本回。")
        if value["status"] not in {"ready", "completed", "deferred", "unjudgeable", "waiting"}:
            raise ValueError("前回尚未完成判讀，請先確認其狀態。")
        actions = conn.execute(
            "SELECT a.id,a.kind,a.verification_state,a.reported_at,a.first_observed_at,"
            "a.verified_at,a.before_json,a.after_json,a.evidence_json "
            "FROM ads_action a JOIN ads_change_set c ON c.id=a.change_set_id "
            "AND c.org_id=a.org_id AND c.brand_id=a.brand_id AND c.campaign_id=a.campaign_id "
            "WHERE a.org_id=%s AND a.brand_id=%s AND a.campaign_id=%s "
            "AND c.plan_json->>'review_id'=%s "
            "ORDER BY a.created_at LIMIT 31",
            (org, brand, campaign_id, previous_id),
        ).fetchall()
        if len(actions) > 30:
            raise ValueError("前回操作超出單回證據上限，不能省略反證後繼續判讀。")
        prior = {
            "id": value["id"],
            "evidence_hash": value["evidence_hash"],
            "window_start": value["window_start"],
            "window_end": value["window_end"],
            "result_json": value["result_json"],
            "decision": value["decision"],
            "reason": value["reason"],
            "actions": [review_monitor_source.action_summary(dict(a)) for a in actions],
        }
        prior["evidence"] = {key: value["evidence_json"][key] for key in ("current", "conditions")}
    text, knowledge, version, _ = context_compiler.compile(conn, brand, include_personas=False)
    sources, forbidden = policy.source_rows(conn, brand, knowledge)
    product_ids = (campaign.get("context_json") or {}).get("product_ids") or []
    if len(product_ids) > 3:
        raise ValueError("活動商品超過單回判讀上限，請先縮小此次檢討的商品背景。")
    products = []
    for product_id in product_ids:
        product = brands.get_product(conn, brand, product_id)
        if product is None:
            raise ValueError("活動商品背景已不存在，請先核對目標。")
        product_text, product_knowledge, _, _ = context_compiler.compile(
            conn, brand, product_id, include_personas=False
        )
        products.append({"id": product_id, "name": product["name"], "context": product_text})
        knowledge = list(dict.fromkeys([*knowledge, *product_knowledge]))
    ancestors = []
    node = entity
    while node.get("parent_native_id"):
        if len(ancestors) >= 10:
            raise ValueError("平台父層過深，無法完整保留本次投放條件。")
        node = conn.execute(
            "SELECT * FROM ads_external_entity WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
            "AND platform=%s AND source_account=%s AND native_kind=%s AND native_id=%s",
            (
                org,
                brand,
                campaign_id,
                entity["platform"],
                entity["source_account"],
                node["parent_native_kind"],
                node["parent_native_id"],
            ),
        ).fetchone()
        if node is None:
            raise ValueError("平台父層條件缺漏，請先完成同步。")
        ancestors.append(
            {
                k: node[k]
                for k in (
                    "id",
                    "native_kind",
                    "native_status",
                    "budget_type",
                    "budget_amount",
                    "currency",
                    "start_date",
                    "end_date",
                )
            }
        )
    # Lazy: both modules import this one. The target is the one the ads centre shows and sets
    # (`targets.resolve`), and an imported campaign's objective is its platform objective --
    # drill 5: reading only the wizard's goal_text/objective made every imported campaign
    # "missing a goal" right after the user set one on the target page.
    from app.ads import repository as ads_repo
    from app.ads import targets

    target = targets.resolve(conn, org, brand, campaign)
    objective = campaign.get("objective") or (
        ads_repo.campaign_objective_family(conn, org, brand, campaign)
        if campaign.get("origin") == "imported" else None
    )
    waiting = []
    if not (campaign.get("goal_text") or target["value"] is not None) or not objective:
        waiting.append("請先補活動目標與目的，再重新建立檢討。")
    if not any(
        (s["metrics"]["impressions"] or 0) > 0
        or (s["metrics"]["clicks"] or 0) > 0
        or (s["metrics"]["spend"] or 0) > 0
        for s in current["series"]
    ):
        waiting.append("本期沒有足夠的已知平台活動樣本；請同步完整期間或延後重看。")
    limitations = list(LIMITATIONS)
    source_review = review_monitor_source.source_review(conn, org, brand, campaign_id, entity_id)
    first_test = False
    if automatic and source_review and not previous_id and timezone:
        monitor = conn.execute(
            "SELECT observe_after FROM ads_review_monitor WHERE org_id=%s AND brand_id=%s "
            "AND campaign_id=%s AND entity_id=%s",
            (org, brand, campaign_id, entity_id),
        ).fetchone()
        anchor = monitor["observe_after"] if monitor else None
        if anchor and prior_end <= anchor.astimezone(ZoneInfo(timezone)).date():
            first_test = True
            previous["comparison_available"] = False
            previous["comparison_basis"] = "before_first_identity_observation"
            limitations.append(
                "新測試前期早於首次身分觀測，沒有可比較的完整前期；缺漏不補零，來源廣告僅供背景。"
            )
    if timezone is None:
        limitations.append("來源平台帳戶時區未知，不以組織時區代替。")
    if mixed:
        limitations.append("投放條件有變動：曾讀到不同素材版本，本期不可歸因到單一素材。")
    if current["missing_days"] or previous["missing_days"]:
        limitations.append("本期或前期缺日期；指標只代表已讀到的日期，缺漏不能當零。")
    if automatic and timezone is None:
        waiting.append("自動檢討等待來源帳戶時區確認，再確認完整日期。")
    if automatic and (current["missing_days"] or (previous["missing_days"] and not first_test)):
        waiting.append("自動檢討等待本期與等長前期的完整日期；固定觀察窗不隨重看移動。")
    return {
        "target": {
            k: entity.get(k) for k in ("id", "name", "platform", "source_account", "native_id")
        },
        "window": {
            "start": start,
            "end": end,
            "previous_start": prior_start,
            "previous_end": prior_end,
            "timezone": timezone,
            "org_timezone": str(settings.org_timezone(conn, org_id=org)),
        },
        "current": current,
        "previous": previous,
        "commerce": {
            "current": orders.review_evidence(conn, org, brand, start=start, end=end),
            "previous": orders.review_evidence(conn, org, brand, start=prior_start, end=prior_end),
        },
        "conditions": {
            "history": "mixed" if mixed else "unknown",
            "binding_count": len(bound),
            "parent_snapshots": ancestors,
            "creative_snapshot": {
                "kind": (entity.get("creative") or {}).get("kind"),
                "copy_fields": changes.copy_fields(entity),
            },
        },
        "previous_review": prior,
        "source_review": source_review,
        "limitations": limitations,
        "waiting_reasons": waiting,
        "context": text,
        "sources": sources,
        "forbidden": forbidden,
        "products": products,
        "constraints": campaign.get("constraints_json") or {},
        "brand_version": version,
        "knowledge_ids": knowledge,
        "campaign": {
            "goal_text": campaign.get("goal_text"),
            "objective": objective,
            "target": target,
        },
        "premise": premise(entity, campaign),
    }
