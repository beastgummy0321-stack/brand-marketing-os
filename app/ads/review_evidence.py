"""Bounded single-ad evidence. Arithmetic belongs here, judgment belongs to the model."""

from collections import defaultdict
from datetime import date, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app import orders
from app.ads import asset_binding_repository as bindings
from app.ads import asset_suggestion_policy as policy
from app.ads import change_control_data as changes
from app.ads import external_sync
from app.ads.adapters.external import SourceReadError
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


def aggregate(rows, start, end):
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
    expected, present = (end - start).days + 1, len({r["day"] for r in rows})
    return {
        "row_count": len(rows),
        "days_present": present,
        "days_expected": expected,
        "missing_days": expected - present,
        "series": series,
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
    for scope, key in (("entity", "budget_amount"), ("goal", "success_target")):
        value = result[scope].get(key)
        if value is not None:
            result[scope][key] = float(value)
    for key in ("start_date", "end_date"):
        value = result["entity"].get(key)
        if isinstance(value, date):
            result["entity"][key] = value.isoformat()
    return result


def snapshot(conn, org, brand, campaign_id, entity_id, start, end, previous_id=None):
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
            "actions": [dict(a) for a in actions],
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
    waiting = []
    if not campaign.get("goal_text") or not campaign.get("objective"):
        waiting.append("請先補活動目標與目的，再重新建立檢討。")
    if not any(
        (s["metrics"]["impressions"] or 0) > 0
        or (s["metrics"]["clicks"] or 0) > 0
        or (s["metrics"]["spend"] or 0) > 0
        for s in current["series"]
    ):
        waiting.append("本期沒有足夠的已知平台活動樣本；請同步完整期間或延後重看。")
    limitations = list(LIMITATIONS)
    if timezone is None:
        limitations.append("來源平台帳戶時區未知，不以組織時區代替。")
    if mixed:
        limitations.append("投放條件有變動：曾讀到不同素材版本，本期不可歸因到單一素材。")
    if current["missing_days"] or previous["missing_days"]:
        limitations.append("本期或前期缺日期；指標只代表已讀到的日期，缺漏不能當零。")
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
            k: campaign.get(k)
            for k in ("goal_text", "objective", "success_metric", "success_target", "success_basis")
        },
        "premise": premise(entity, campaign),
    }
