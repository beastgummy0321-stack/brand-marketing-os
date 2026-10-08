"""Read-only completed-month sources and request-scoped internal draft continuation."""

import hashlib
from typing import NoReturn
from uuid import UUID

from app import storage, workbench
from app.ads import (
    actual_format,
    ads_learnings,
    asset_binding_repository,
    coverage,
    customer_groups,
    learning_rank,
    learning_view,
    media_probe,
    outcome,
    period_grades,
    repository,
    sell_way,
    settle,
    targets,
    triage,
)
from app.ads import user_assets_repository as assets
from app.brand_intelligence import repository as brands
from app.core import settings as coresettings

MAX_CAMPAIGNS = 24
MAX_ADS = 48
MAX_OBSERVATIONS = 3000
MAX_LEARNINGS = 200


class ContinuationError(ValueError):
    def __init__(self, code, message, status=409):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _refuse(code, message, status=409) -> NoReturn:
    raise ContinuationError(code, message, status)


def _window(conn, org, month):
    try:
        month = settle._require_month(month)
    except settle.SettleError:
        _refuse("continuation_invalid", "來源月份請使用 YYYY-MM。", 422)
    start, end = settle._window(month)
    if coresettings.today_for_org(conn, org_id=org) <= end:
        _refuse("continuation_not_ended", "來源月份尚未結束。")
    return start, end


def _bounded(rows, limit):
    if len(rows) > limit:
        _refuse("continuation_scope_too_large", "來源資料過多，請縮小下一期的來源範圍。")
    return [dict(row) for row in rows]


def _index(conn, org, brand, start, end):
    return [
        dict(r)
        for r in conn.execute(
            "SELECT c.* FROM ads_campaign c WHERE c.org_id=%s AND c.brand_id=%s AND EXISTS("
            "SELECT 1 FROM ads_external_daily d WHERE d.org_id=c.org_id AND d.brand_id=c.brand_id"
            " AND d.campaign_id=c.id AND d.metric_scope='ad' AND d.day BETWEEN %s AND %s)"
            " ORDER BY c.id LIMIT %s",
            (org, brand, start, end, MAX_CAMPAIGNS + 1),
        ).fetchall()
    ]


def _revision(conn, org, brand, start, end):
    # Hash row content inside PostgreSQL: every late correction matters, including rows omitted
    # from the bounded prompt. No timestamp/count proxy and no cross-module table access.
    hashes = {}
    for table, clause in (
        ("ads_external_daily", "AND day BETWEEN %s AND %s"),
        ("ads_campaign", ""),
        ("ads_external_entity", ""),
        ("ads_asset_placement", ""),
        ("ads_asset_binding", ""),
        ("ads_user_asset", ""),
        ("ads_ad", ""),
    ):
        # New continuation drafts are not source evidence: exclude rows without delivery in
        # this month, so creating the first draft does not invalidate its own source receipt.
        if table not in {"ads_external_daily", "ads_user_asset"}:
            campaign_key = "id" if table == "ads_campaign" else "campaign_id"
            clause += (
                f" AND {campaign_key} IN (SELECT campaign_id FROM ads_external_daily"
                " WHERE org_id=%s AND brand_id=%s AND metric_scope='ad' AND day BETWEEN %s AND %s)"
            )
            args = (org, brand, org, brand, start, end)
        else:
            args = (org, brand, start, end) if clause else (org, brand)
        hashes[table] = conn.execute(
            f"SELECT md5(coalesce(string_agg(md5(to_jsonb(t)::text),'' ORDER BY id),'')) AS digest"
            f" FROM {table} t WHERE org_id=%s AND brand_id=%s {clause}",
            args,
        ).fetchone()["digest"]
    campaigns = _index(conn, org, brand, start, end)[:MAX_CAMPAIGNS]
    hashes["conditions"] = [
        ads_learnings.condition_snapshot(conn, org, brand, c, sell_way.of_campaign(c))
        for c in campaigns
    ]
    hashes["brand"] = brands.get_brand(conn, brand)
    hashes["products"] = [
        {"product": p, "economics": brands.get_product_economics(conn, brand, p["id"])}
        for p in brands.all_product_rows(conn, brand)
    ]
    hashes["learnings"] = brands.list_learnings(
        conn, brand, limit=MAX_LEARNINGS, include_expired=True
    )
    return ads_learnings.semantic_version(hashes)


def _grades(conn, org, brand, campaigns, entities, observations, start, end):
    graded, missing = [], {}
    for campaign in campaigns:
        target = targets.resolve(conn, org, brand, campaign)
        unit = outcome.cap_unit(conn, brand, target, campaign=campaign)
        first, last = coverage.clip(campaign, start, end)
        days = max((last - first).days + 1, 0)
        read = coverage.load(conn, org, brand, campaign, first, last)
        gaps = read.missing(first, last, cap=None) if days else []
        if gaps:
            missing[campaign["id"]] = gaps
        for entity in entities:
            if entity["campaign_id"] != campaign["id"] or entity["native_kind"] != "ad":
                continue
            rows = [r for r in observations if r["entity_id"] == entity["id"]]
            if not period_grades._spent(rows):
                continue
            view, spend = triage._ad_window(rows, first, last)
            currency = period_grades._currency(rows)
            grade, label, reason = period_grades._grade(view, spend, target, days)
            comparison = outcome.compare_cap_unit(unit, currency)
            if comparison["reason"] and grade in triage.GRADED:
                grade, label, reason = "insufficient", triage.NO_DATA_LABEL, comparison["reason"]
            graded.append(
                {
                    "campaign_id": campaign["id"],
                    "campaign_name": campaign["name"],
                    "origin": campaign["origin"],
                    "entity_id": entity["id"],
                    "name": entity["name"],
                    "thumbnail_url": triage._thumbnail_url(entity),
                    "spend": spend,
                    "results": view["result_count"] if view else None,
                    "cost_per_result": view["cost_per_result"] if view else None,
                    "currency": currency,
                    "cap": target["value"],
                    "grade": grade,
                    "grade_label": label,
                    "reason_code": reason,
                    "sample": triage._sample_view(spend, view, target["value"], days),
                }
            )
    return graded, missing


def _load(conn, org, brand, month, ids):
    start, end = _window(conn, org, month)
    observations = _bounded(
        conn.execute(
            "SELECT *,id AS observation_id FROM ads_external_daily WHERE org_id=%s AND brand_id=%s"
            " AND campaign_id=ANY(%s) AND metric_scope='ad' AND day BETWEEN %s AND %s"
            " ORDER BY id LIMIT %s",
            (org, brand, ids, start, end, MAX_OBSERVATIONS + 1),
        ).fetchall(),
        MAX_OBSERVATIONS,
    )
    found = sorted({row["campaign_id"] for row in observations})
    campaigns = _bounded(
        conn.execute(
            "SELECT * FROM ads_campaign WHERE org_id=%s AND brand_id=%s AND id=ANY(%s) ORDER BY id",
            (org, brand, found),
        ).fetchall(),
        MAX_CAMPAIGNS,
    )
    entities = _bounded(
        conn.execute(
            "SELECT * FROM ads_external_entity WHERE org_id=%s AND brand_id=%s AND"
            " campaign_id=ANY(%s)"
            " ORDER BY id LIMIT %s",
            (org, brand, found, MAX_ADS * 3 + 1),
        ).fetchall(),
        MAX_ADS * 3,
    )
    _bounded([e for e in entities if e["native_kind"] == "ad"], MAX_ADS)
    graded, missing = _grades(conn, org, brand, campaigns, entities, observations, start, end)
    placements = _bounded(
        conn.execute(
            "SELECT * FROM ads_asset_placement WHERE org_id=%s AND brand_id=%s"
            " AND campaign_id=ANY(%s) AND is_current ORDER BY id LIMIT %s",
            (org, brand, found, MAX_ADS + 1),
        ).fetchall(),
        MAX_ADS,
    )
    bindings = _bounded(
        conn.execute(
            "SELECT * FROM ads_asset_binding WHERE org_id=%s AND brand_id=%s AND"
            " campaign_id=ANY(%s)"
            " ORDER BY id LIMIT %s",
            (org, brand, found, MAX_ADS * 3 + 1),
        ).fetchall(),
        MAX_ADS * 3,
    )
    originals = [
        assets.get_asset(conn, org, brand, aid)
        for aid in sorted({p["asset_id"] for p in placements})
    ]
    learnings = brands.list_learnings(conn, brand, limit=MAX_LEARNINGS, include_expired=True)
    learnings = [
        row
        for row in learnings
        if row.get("org_id") == org
        and (ads_learnings.stored_evidence(row).get("source_ref") or {}).get("campaign_id") in found
    ]
    ads = _bounded(
        conn.execute(
            "SELECT * FROM ads_ad WHERE org_id=%s AND brand_id=%s AND campaign_id=ANY(%s)"
            " ORDER BY id LIMIT %s",
            (org, brand, found, MAX_ADS + 1),
        ).fetchall(),
        MAX_ADS,
    )
    return {
        "campaigns": campaigns,
        "entities": entities,
        "observations": observations,
        "grades": graded,
        "missing": missing,
        "placements": placements,
        "bindings": bindings,
        "originals": originals,
        "learnings": learnings,
        "ads": ads,
        "month": month,
        "window": {"start": str(start), "end": str(end)},
    }


def _excluded(owner, ref, reason):
    return {"owner": owner, "ref": ref, "reason_code": reason}


def _source_currency(snapshot, campaign_id):
    currencies = {
        r["currency"] for r in snapshot["observations"] if r["campaign_id"] == campaign_id
    }
    return next(iter(currencies)) if len(currencies) == 1 else None


def prepare(conn, org, brand, month):
    start, end = _window(conn, org, month)
    campaigns = _index(conn, org, brand, start, end)
    sources, eligible, excluded = [], [], []
    if len(campaigns) > MAX_CAMPAIGNS:
        excluded.append(_excluded("campaign", "remaining", "source_list_truncated"))
    remaining = MAX_ADS
    for campaign in campaigns[:MAX_CAMPAIGNS]:
        currency = conn.execute(
            "SELECT CASE WHEN count(DISTINCT currency)=1 AND count(currency)=count(*)"
            " THEN min(currency) END AS currency FROM ads_external_daily WHERE org_id=%s"
            " AND brand_id=%s AND campaign_id=%s AND metric_scope='ad' AND day BETWEEN %s AND %s",
            (org, brand, campaign["id"], start, end),
        ).fetchone()["currency"]
        product = sell_way.of_campaign(campaign)
        sources.append(
            {
                "campaign_id": campaign["id"],
                "origin": campaign["origin"],
                "name": campaign["name"],
                "mapping_required": product is None,
                "result_kind": targets.effective_result_kind(campaign),
                "currency": currency,
            }
        )
        try:
            snapshot = _load(conn, org, brand, month, [campaign["id"]])
            if len(snapshot["grades"]) > remaining:
                excluded.append(
                    _excluded("campaign", campaign["id"], "qualification_list_truncated")
                )
                continue
            remaining -= len(snapshot["grades"])
            scope = _qualified(
                conn, org, brand, snapshot, [campaign["id"]], product, False, destination=campaign
            )
        except ContinuationError as exc:
            if exc.code != "continuation_scope_too_large":
                raise
            excluded.append(_excluded("campaign", campaign["id"], "source_scope_too_large"))
            continue
        eligible.extend(scope["eligible_learning_refs"])
        excluded.extend(scope["excluded"])
    return {
        "month": month,
        "window": {"start": str(start), "end": str(end)},
        "revision": _revision(conn, org, brand, start, end),
        "source_campaigns": sources,
        "eligible_learning_refs": eligible,
        "excluded": excluded,
    }


def _original(conn, org, brand, snapshot, campaign, entity, ad):
    """Current confirmed placement + original bytes, scoped to the real native or internal ad."""
    placement = None
    if campaign["origin"] == "imported":
        bound = [
            b
            for b in snapshot["bindings"]
            if b["entity_id"] == entity["id"]
            and b["existence_status"] == "platform_confirmed"
            and b.get("creative_hash") == asset_binding_repository.creative_hash(entity["creative"])
        ]
        candidates = [
            p
            for p in snapshot["placements"]
            if any(
                b["placement_id"] == p["id"] and b["placement_revision"] == p["revision"]
                for b in bound
            )
        ]
        if len(candidates) == 1:
            placement = candidates[0]
    elif ad and ad.get("material_placement_id"):
        placement = next(
            (
                p
                for p in snapshot["placements"]
                if p["id"] == ad["material_placement_id"]
                and p["revision"] == ad.get("material_placement_revision")
            ),
            None,
        )
    if not placement or not placement["confirmed_at"] or not placement["is_current"]:
        return None, "material_permission_unknown"
    asset = next(a for a in snapshot["originals"] if a["id"] == placement["asset_id"])
    if (
        asset["status"] != "ready"
        or not asset.get("storage_key")
        or not asset.get("byte_size")
        or asset["byte_size"] > media_probe.MAX_BYTES
    ):
        return None, "material_unavailable"
    reason = original_bytes(asset, org)
    if reason:
        return None, reason
    expected = {"image": actual_format.SINGLE_IMAGE, "video": actual_format.VIDEO}.get(
        entity["creative"].get("kind")
    )
    if expected is None or actual_format.of_asset(asset) != expected:
        return None, "material_format_incompatible"
    copy = asset_binding_repository.effective_copy(placement)
    if any(not str(copy.get(k) or "").strip() for k in ("headline", "body", "description")):
        return None, "copy_unknown"
    return {
        "asset_id": asset["id"],
        "copy_fields": copy,
        "placement_id": placement["id"],
        "placement_revision": placement["revision"],
        "sha256": asset["sha256"],
    }, None


def original_bytes(asset, org):
    """Verify the original through the storage facade; metadata alone is not usable media."""
    if (
        asset.get("status") != "ready"
        or not asset.get("storage_key")
        or not asset.get("byte_size")
        or asset["byte_size"] > media_probe.MAX_BYTES
        or not asset.get("sha256")
        or not asset.get("mime_type")
    ):
        return "material_unavailable"
    try:
        content, mime = storage.get(org_id=org, key=asset["storage_key"])
        if (
            not content
            or len(content) > media_probe.MAX_BYTES
            or len(content) != asset["byte_size"]
            or hashlib.sha256(content).hexdigest() != asset["sha256"]
            or media_probe.sniff(content) != asset["mime_type"]
            or mime.split(";", 1)[0] != asset["mime_type"]
        ):
            return "material_bytes_changed"
    except (storage.StorageError, ValueError):
        return "material_unavailable"
    return None


def _retained(snapshot, campaign, entity):
    rows = []
    for record in snapshot["learnings"]:
        evidence = ads_learnings.stored_evidence(record)
        ref = evidence.get("source_ref") or {}
        parsed = learning_rank.parse_scope(record["applicability_scope"])
        if (
            parsed
            and ref.get("campaign_id") == campaign["id"]
            and ref.get("entity_id") == entity["id"]
        ):
            rows.append((record, evidence, parsed))
    return max(rows, key=lambda r: str(r[1].get("period", {}).get("end") or ""), default=None)


def _qualified(conn, org, brand, snapshot, ids, product, confirmed, *, destination):
    """One canonical grade/evidence projection, with explicit product association only here."""
    excluded, refs, candidates, views, records = [], [], [], [], []
    labels = learning_view.vocabulary(conn, org, brand)
    groups_by_id = customer_groups.groups_by_id(conn, brand, destination)
    for campaign in snapshot["campaigns"]:
        if campaign["id"] not in ids:
            continue
        known = sell_way.of_campaign(campaign)
        mapping = (
            known == product and product is not None or known is None and confirmed and product
        )
        conditions = ads_learnings.current_conditions(conn, org, brand, product, campaign=campaign)
        source_observations = [
            r for r in snapshot["observations"] if r["campaign_id"] == campaign["id"]
        ]
        kind, currency, attribution = ads_learnings._measurement(source_observations)
        if any(r["source"] != "graph" or not r["observation_id"] for r in source_observations):
            kind = attribution = None
        conditions.update(result_kind=kind, currency=currency, attribution=attribution)
        conditions["conditions"].update(
            ads_learnings.condition_snapshot(conn, org, brand, destination, product)
        )
        target = targets.resolve(conn, org, brand, destination, product_id=product)
        source_family = repository.campaign_objective_family(conn, org, brand, campaign)
        destination_family = repository.campaign_objective_family(conn, org, brand, destination)
        source_rows = [r for r in snapshot["grades"] if r["campaign_id"] == campaign["id"]]
        ranked = learning_rank.rank(source_rows)
        rows = []
        for row in ranked:
            entity = next(e for e in snapshot["entities"] if e["id"] == row["entity_id"])
            native = {
                k: entity[k]
                for k in ("id", "platform", "source_account", "native_kind", "native_id")
            }
            ad = next(
                (
                    a
                    for a in snapshot["ads"]
                    if a["campaign_id"] == campaign["id"]
                    and a.get("external_id") == entity["native_id"]
                ),
                None,
            )
            retained = _retained(snapshot, campaign, entity)
            creative, material_reason = _original(conn, org, brand, snapshot, campaign, entity, ad)
            if ad is None and retained:
                # This object describes the native source; it is not an internal ads_ad row.
                _, _, parsed = retained
                ad = {
                    "id": entity["id"],
                    "campaign_id": campaign["id"],
                    "name": entity["name"] or entity["native_id"],
                    "native_ref": native,
                    "customer_group_id": parsed["customer_group_id"],
                    "scene": None,
                    "coordinates_snapshot_json": {
                        "customer_group": groups_by_id.get(parsed["customer_group_id"])
                    },
                    **{f"{d}_key": k for d, k in parsed["keys"].items()},
                }
            reasons = []
            if source_family == "other":
                reasons.append("objective_unknown")
            elif source_family != destination_family:
                reasons.append("objective_family_mismatch")
            if not mapping:
                reasons.append("mapping_required" if known is None else "other_product")
            if campaign["id"] in snapshot["missing"]:
                reasons.append("coverage_unknown")
            if row["grade"] != "on_target":
                reasons.append(
                    "above_target"
                    if row["grade"] in {"watch", "over", "wasted"}
                    else row.get("reason_code") or "target_unknown"
                )
            if (
                outcome.compare_cap_unit(
                    outcome.cap_unit(conn, brand, target, campaign=destination), row["currency"]
                )["reason"]
                is not None
            ):
                reasons.append("target_unit_unknown")
            if targets.effective_result_kind(destination) != targets.effective_result_kind(
                campaign
            ):
                reasons.append("result_kind_mismatch")
            observations = [r for r in snapshot["observations"] if r["entity_id"] == entity["id"]]
            view, spend = triage._ad_window(
                observations,
                settle._window(snapshot["month"])[0],
                settle._window(snapshot["month"])[1],
            )
            current_grade = triage.grade_window(
                view,
                spend,
                target["value"],
                (settle._window(snapshot["month"])[1] - settle._window(snapshot["month"])[0]).days
                + 1,
            )[0]
            if current_grade != "on_target":
                reasons.append("current_target_not_met")
            evidence = ads_learnings.source_evidence(
                conn,
                org,
                brand,
                campaign,
                kind="coordinate",
                window=snapshot["window"],
                ad=ad,
                observations=observations,
                entity_id=entity["id"],
                claim_key=ads_learnings.message_claim(ad or {}),
                direction="support" if row["grade"] == "on_target" else "contrary",
            )
            if retained:
                _, old, _ = retained
                if any(
                    old["scope"].get(k) != evidence["scope"].get(k)
                    for k in ("result_kind", "currency", "attribution", "objective_family")
                ):
                    reasons.append("measurement_changed")
                evidence = {
                    **evidence,
                    "conditions": old["conditions"],
                    "scope": {
                        **old["scope"],
                        **{
                            k: evidence["scope"][k]
                            for k in ("result_kind", "currency", "attribution", "objective_family")
                        },
                    },
                    "limits": [r for r in evidence["limits"] if r != "conditions_unknown"],
                    "source_version": ads_learnings.semantic_version(
                        {"observations": observations, "conditions": old["conditions"]}
                    ),
                    "direction": "support" if current_grade == "on_target" else "contrary",
                    "sample": {"result_events": row["results"], "sufficient": None},
                }
                if creative and ad:
                    version = ads_learnings.material_version(
                        {
                            "material_evidence": {
                                "sha256": creative["sha256"],
                                "copy": creative["copy_fields"],
                            }
                        },
                        {},
                    )
                    conditions["conditions"]["materials"].append(
                        {"ad_id": ad["id"], "version": version}
                    )
            if mapping and known is None:
                evidence["scope"]["product_id"] = product
            record = {
                "id": entity["id"],
                "org_id": org,
                "brand_id": brand,
                "product_id": product,
                "learning_text": "Completed-period observation, correlation only",
                "confidence": "observed",
                "needs_revalidation": bool(retained and retained[0].get("needs_revalidation")),
                "expired": bool(retained and retained[0].get("expired")),
                "applicability_scope": workbench.encode_learning_scope("next-period", evidence),
            }
            qualified = ads_learnings.evidence_context(
                conn, org, brand, product, rows=[record], current=conditions
            )["items"][0]
            if "retain_control" not in qualified["allowed_uses"]:
                reasons.extend(qualified["reason_codes"])
            if material_reason:
                reasons.append(material_reason)
            if ad is None:
                reasons.append("coordinates_unknown")
            if reasons:
                qualified = {
                    **qualified,
                    "allowed_uses": [],
                    "use_state": "history",
                    "reason_codes": sorted(set([*qualified["reason_codes"], *reasons])),
                    "support_label": "來源條件未符合；僅作歷史對照",
                }
            keys = {
                d: (ad or {}).get(f"{d}_key") or learning_rank.MISSING
                for d in learning_rank.DIMENSIONS
            }
            learning_row = {
                **row,
                "ad_id": entity["id"] if campaign["origin"] == "imported" else (ad or {}).get("id"),
                "ad_name": entity["name"] or entity["native_id"],
                "customer_group": groups_by_id.get((ad or {}).get("customer_group_id") or ""),
                "coordinates": [
                    {"dimension": d, "key": k, "label": labels.get((d, k), k)}
                    for d, k in keys.items()
                ],
                "learning_id": record["id"],
                "evidence": qualified,
            }
            rows.append(learning_row)
            records.append({**record, "evidence": qualified})
            excluded.extend(_excluded("result", entity["id"], r) for r in sorted(set(reasons)))
            if reasons:
                continue
            assert ad is not None and creative is not None
            refs.append({"owner": "result", "ref": entity["id"], "campaign_id": campaign["id"]})
            group = (
                repository.get_group(conn, org, brand, ad["group_id"])
                if ad.get("group_id")
                else None
            )
            projected_ad = {**ad, "id": learning_row["ad_id"], "native_ref": native}
            candidates.append(
                {
                    "ad": projected_ad,
                    "row": learning_row,
                    "role": (group or {}).get("role"),
                    "creative": creative,
                }
            )
        views.append(
            {
                "campaign_id": campaign["id"],
                "campaign_name": campaign["name"],
                "sell_way_id": product,
                "currency": _source_currency(snapshot, campaign["id"]),
                "cap": target["value"],
                "start_date": snapshot["window"]["start"],
                "end_date": snapshot["window"]["end"],
                "rule_text": learning_rank.rule_text(ranked, target["value"]),
                "empty_reason": "No comparable selected observations",
                "rows": rows,
                "counts": {
                    "keep": sum("retain_control" in r["evidence"]["allowed_uses"] for r in rows),
                    "replace": sum(not learning_rank.is_keep(r["verdict"]) for r in rows),
                },
            }
        )
    return {
        "eligible_learning_refs": refs,
        "excluded": excluded,
        "carried_candidates": candidates,
        "records": records,
        "view": {"campaigns": views, "groups": [], "next": None},
    }


def _input(value):
    if not isinstance(value, dict) or not {
        "month", "campaign_ids", "revision", "request_id"
    } <= set(value) or set(value) - {
        "month",
        "campaign_ids",
        "revision",
        "request_id",
        "product_mapping_confirmed",
    }:
        _refuse("continuation_invalid", "下一期來源欄位無效。", 422)
    ids = value.get("campaign_ids")
    if (
        not isinstance(ids, list)
        or not 1 <= len(ids) <= MAX_CAMPAIGNS
        or any(not isinstance(i, str) or not 1 <= len(i) <= 200 for i in ids)
        or len(set(ids)) != len(ids)
        or not isinstance(value.get("revision"), str)
        or not value["revision"]
        or type(value.get("product_mapping_confirmed", False)) is not bool
    ):
        _refuse("continuation_invalid", "請選擇來源活動並重新讀取來源。", 422)
    try:
        request_id = str(UUID(value["request_id"]))
    except (ValueError, TypeError, KeyError, AttributeError):
        _refuse("continuation_invalid", "下一期請求識別碼無效。", 422)
    return {
        **value,
        "request_id": request_id,
        "campaign_ids": sorted(ids),
        "product_mapping_confirmed": value.get("product_mapping_confirmed", False),
    }


def create(conn, org, brand, *, goal_text, start_date, end_date, constraints, actor, picks):
    """Replay precedes fresh validation; one transaction owns lock, model rows and draft."""

    continuation = _input(picks.get("continuation"))
    digest = ads_learnings.semantic_version(
        {
            "goal_text": goal_text,
            "start_date": start_date,
            "end_date": end_date,
            "constraints": constraints,
            "picks": {**picks, "continuation": continuation},
        }
    )
    with conn.atomic():
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (f"next-period:{org}:{brand}:{continuation['request_id']}",),
        )
        rows = conn.execute(
            "SELECT id,context_json FROM ads_campaign WHERE org_id=%s AND brand_id=%s"
            " AND context_json->'next_period_source'->>'request_id'=%s",
            (org, brand, continuation["request_id"]),
        ).fetchall()
        if rows:
            saved = rows[0]["context_json"]["next_period_source"]
            if saved["payload_digest"] != digest:
                _refuse("continuation_request_conflict", "此請求識別碼已用於不同內容。")
            existing = repository.campaign_detail(conn, org, brand, rows[0]["id"])
            assert existing is not None
            return existing
        from app.ads import busy

        with busy.claim(conn, brand, "brief"), conn.atomic():
            return _create_new(
                conn,
                org,
                brand,
                continuation,
                digest,
                goal_text,
                start_date,
                end_date,
                constraints,
                actor,
                picks,
            )


def _create_new(
    conn,
    org,
    brand,
    continuation,
    digest,
    goal_text,
    start_date,
    end_date,
    constraints,
    actor,
    picks,
):
    from app.ads import brief

    checked = brief._check_picks(conn, brand, picks)
    if checked is None:
        _refuse("continuation_invalid", "下一期必須明確選擇商品、目標與預算。", 422)
    snapshot = _load(conn, org, brand, continuation["month"], continuation["campaign_ids"])
    snapshot["revision"] = _revision(conn, org, brand, *_window(conn, org, continuation["month"]))
    ids = continuation["campaign_ids"]
    if not set(ids) <= {c["id"] for c in snapshot["campaigns"]}:
        _refuse("continuation_source_missing", "來源活動不在這個品牌的已完成月份中。")
    if snapshot["revision"] != continuation["revision"]:
        _refuse("continuation_source_changed", "來源資料已變更，請重新讀取後確認。")
    product = checked["product_ids"][0]
    source = {
        **continuation,
        "window": snapshot["window"],
        "product_id": product,
        "payload_digest": digest,
        "source_campaigns": [
            {"campaign_id": c["id"], "origin": c["origin"], "name": c["name"]}
            for c in snapshot["campaigns"]
            if c["id"] in ids
        ],
        "native_entities": [
            {
                k: e[k]
                for k in (
                    "id",
                    "campaign_id",
                    "platform",
                    "source_account",
                    "native_kind",
                    "native_id",
                )
            }
            for e in snapshot["entities"]
            if e["campaign_id"] in ids
        ],
    }
    extras = brief._check_extras(picks)
    destination = {
        "objective": checked["objective"],
        "target_cost": extras["cap"],
        "target_basis": "own" if extras["cap"] is not None else None,
        "context_json": {
            "product_ids": [product],
            "field_sources": {"cap": "user" if extras["cap"] else "system"},
        },
    }
    qualified = _qualified(
        conn,
        org,
        brand,
        snapshot,
        ids,
        product,
        continuation["product_mapping_confirmed"],
        destination=destination,
    )
    source.update({k: qualified[k] for k in ("eligible_learning_refs", "excluded")})
    result = brief.create_draft(
        conn,
        org,
        brand,
        goal_text=goal_text,
        start_date=start_date,
        end_date=end_date,
        constraints=constraints,
        actor=actor,
        picks={k: v for k, v in picks.items() if k != "continuation"},
        next_period_source=source,
    )
    # Recheck sources after external model IO, before this transaction can be committed.
    if (
        _revision(conn, org, brand, *_window(conn, org, continuation["month"]))
        != snapshot["revision"]
    ):
        _refuse("continuation_source_changed", "來源資料已變更，請重新讀取後確認。")
    return result


def planner_source(conn, org, brand, source, campaign):
    """Fresh qualification: stored provenance is never a permission to reuse missing bytes."""
    snapshot = _load(conn, org, brand, source["month"], source["campaign_ids"])
    snapshot["revision"] = _revision(conn, org, brand, *_window(conn, org, source["month"]))
    ids = source["campaign_ids"]
    current_product = sell_way.of_campaign(campaign)
    qualified = _qualified(
        conn,
        org,
        brand,
        snapshot,
        ids,
        current_product,
        bool(current_product and current_product == source.get("product_id")
             and source["product_mapping_confirmed"]),
        destination=campaign,
    )
    if not set(ids) <= {c["id"] for c in snapshot["campaigns"]}:
        qualified["excluded"].append(_excluded("campaign", "selected", "source_missing"))
    return {
        **qualified,
        "revision": snapshot["revision"],
        "month": source["month"],
        "window": snapshot["window"],
        "source_campaigns": source["source_campaigns"],
    }
