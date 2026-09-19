"""Resumable account reads. One invocation commits one bounded page, never a platform write."""

import calendar
from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app import background
from app.ads import channels
from app.ads import external_repository as repo
from app.ads.adapters.external import SourceReadError
from app.ads.external_models import ExternalObservation
from app.core import settings
from app.core.db import connection, jsonb, new_id, now_utc, set_tenant_scope

TASK = "background.ads_external_sync"
SECTIONS = ("structure", "creatives", "observations")


def account_reader(conn, org_id, brand_id, platform, source_account):
    reader = channels.external_reader(platform)
    if reader is None:
        raise SourceReadError("此通路尚未支援既有活動讀取。", "unsupported")
    accounts = reader.accounts(conn, org_id, brand_id)
    account = next((a for a in accounts if a["account_id"] == source_account), None)
    if account is None:
        raise SourceReadError("來源帳號已解除或不屬於此品牌。", "disconnected")
    return reader, account


def _enqueue(job):
    lock = f"external-sync:{job['id']}:{job['revision']}"
    if not background.is_active(lock):
        background.enqueue(
            TASK, org_id=job["org_id"], lock=lock, brand_id=job["brand_id"], job_id=job["id"]
        )


def request_sync(conn, org_id, brand_id, platform, source_account, *, start=None, end=None):
    account_reader(conn, org_id, brand_id, platform, source_account)
    today = settings.today_for_org(conn, org_id=org_id)
    month_request_start = start or end or today
    end = end or today
    start = start or end - timedelta(days=29)
    if start > end or (end - start).days > 30 or end > today:
        raise ValueError("每次同步請選擇最多31日且不含未來的範圍。")
    conn.execute(
        "INSERT INTO ads_external_sync_job(id,org_id,brand_id,platform,source_account) "
        "VALUES (%s,%s,%s,%s,%s) ON CONFLICT(org_id,brand_id,platform,source_account) DO NOTHING",
        (new_id("aes"), org_id, brand_id, platform, source_account),
    )
    row = conn.execute(
        "SELECT * FROM ads_external_sync_job WHERE org_id=%s AND brand_id=%s AND platform=%s "
        "AND source_account=%s FOR UPDATE",
        (org_id, brand_id, platform, source_account),
    ).fetchone()
    assert row is not None
    tasks = dict(row["tasks"])
    roots = conn.execute(
        "SELECT e.campaign_id,e.native_id FROM ads_external_entity e JOIN "
        "ads_campaign c ON c.id=e.campaign_id "
        "WHERE e.org_id=%s AND e.brand_id=%s AND e.platform=%s AND e.source_account=%s "
        "AND e.parent_native_id IS NULL",
        (org_id, brand_id, platform, source_account),
    ).fetchall()
    requested = {"list": {"section": "list"}}
    # Explicit backfills cover each touched month; daily/default reads cover this month.
    month = month_request_start.replace(day=1)
    while month <= end:
        month_end = month.replace(day=calendar.monthrange(month.year, month.month)[1])
        requested["monthly:" + month.strftime("%Y-%m")] = {
            "section": "monthly",
            "start": month.isoformat(),
            "end": min(today, month_end).isoformat(),
        }
        month = month_end + timedelta(days=1)
    for root in roots:
        for section in SECTIONS:
            key = root["campaign_id"] + ":" + section
            if section == "observations":
                key += ":" + start.isoformat() + ":" + end.isoformat()
            requested[key] = {
                "section": section,
                **dict(root),
                "start": str(start),
                "end": str(end),
            }
    tasks = {
        key: task
        for key, task in tasks.items()
        if task["status"] != "succeeded" or key in requested or key.startswith("monthly:")
    }
    active = row["status"] in {"pending", "running"}
    for key, task in requested.items():
        old = tasks.get(key)
        same_range = (
            old and old.get("start") == task.get("start") and old.get("end") == task.get("end")
        )
        if active and old and (task["section"] != "monthly" or same_range):
            continue
        resume = (
            old
            and old["status"] == "failed"
            and (task["section"] != "monthly" or same_range and not old.get("restart_required"))
        )
        resumed = old if resume and old is not None else {}
        tasks[key] = {
            **resumed,
            **task,
            "generation": resumed.get("generation") if resume else new_id("round"),
            "started_at": resumed.get("started_at") if resume else now_utc(),
            "cursor": resumed.get("cursor") if resume else None,
            "status": "pending",
            "errors": [],
            "error_code": None,
            "attempts": 0,
        }
    conn.execute(
        "UPDATE ads_external_sync_job SET "
        "tasks=%s,status='pending',error=NULL,updated_at=now() WHERE id=%s",
        (jsonb(tasks), row["id"]),
    )
    conn.commit()
    job = repo.get_job(conn, org_id, brand_id, row["id"])
    _enqueue(job)
    return job


def _update_task(conn, job, key, task):
    conn.execute(
        "UPDATE ads_external_sync_job SET tasks=tasks || jsonb_build_object(%s::text,%s::jsonb), "
        "revision=revision+1,last_attempt_at=now(),updated_at=now() WHERE "
        "org_id=%s AND brand_id=%s AND id=%s",
        (key, jsonb(task), job["org_id"], job["brand_id"], job["id"]),
    )
    current = repo.get_job(conn, job["org_id"], job["brand_id"], job["id"])
    values = list(current["tasks"].values())
    status = (
        "pending"
        if any(t["status"] == "pending" for t in values)
        else ("partial" if any(t["status"] == "failed" for t in values) else "succeeded")
    )
    conn.execute(
        "UPDATE ads_external_sync_job SET status=%s,last_success_at=CASE WHEN %s='succeeded' "
        "THEN now() ELSE last_success_at END WHERE id=%s",
        (status, status, job["id"]),
    )
    conn.commit()
    return repo.get_job(conn, job["org_id"], job["brand_id"], job["id"])


def _monthly_roots(conn, job, kind, native_id):
    return conn.execute(
        "SELECT e.id,e.campaign_id,e.brand_id FROM ads_external_entity e "
        "JOIN ads_campaign c ON c.id=e.campaign_id AND c.org_id=e.org_id AND c.brand_id=e.brand_id "
        "WHERE e.org_id=%s AND e.platform=%s AND e.source_account=%s "
        "AND e.native_kind=%s AND e.native_id=%s AND e.parent_native_id IS NULL",
        (job["org_id"], job["platform"], job["source_account"], kind, native_id),
    ).fetchall()


def _save_monthly(conn, job, task, page, account):
    proof = page.coverage or {}
    try:
        ZoneInfo(account.get("timezone_name") or "")
    except (ValueError, ZoneInfoNotFoundError):
        raise SourceReadError("帳戶時區未知，不能確認月份涵蓋。", "invalid_monthly_scope") from None
    if (
        proof.get("scope") != "account_campaign_day"
        or proof.get("start") != task["start"]
        or proof.get("end") != task["end"]
        or proof.get("account_id") != job["source_account"]
        or not account.get("currency")
        or proof.get("currency") != account["currency"]
        or proof.get("timezone_name") != account["timezone_name"]
        or (
            task.get("coverage")
            and any(
                task["coverage"].get(k) != proof.get(k)
                for k in ("scope", "start", "end", "account_id", "currency", "timezone_name")
            )
        )
    ):
        raise SourceReadError("來源沒有可核對的帳戶整月涵蓋證據。", "invalid_monthly_scope")
    if page.errors or len(page.items) > 100:
        raise SourceReadError("月份來源分頁有缺漏，請完整重讀。", "invalid_source_page")
    seen = {tuple(pair) for pair in task.get("seen_native_ids", [])}
    assigned = {
        (kind, native): entity for kind, native, entity in task.get("assigned_native_ids", [])
    }
    row_keys = {tuple(key) for key in task.get("row_keys", [])}
    unassigned = set((task.get("coverage") or {}).get("unassigned_native_ids", []))
    page_count = task.get("page_count", 0) + 1
    if page_count > 1000:
        raise SourceReadError("月份分頁超出本次讀取上限，涵蓋仍不完整。", "page_limit")
    # Validate every row before saving; the page transaction rolls back on any bad row.
    for item in page.items:
        if (
            item.get("currency") != account["currency"]
            or item.get("spend") is None
            or isinstance(item.get("spend"), bool)
            or not item.get("native_id")
            or not item.get("native_kind")
            or item.get("metric_scope") != item["native_kind"]
            or not task["start"] <= str(item.get("day")) <= task["end"]
        ):
            raise SourceReadError("月份來源列無法核對，請完整重讀。", "invalid_source_page")
        from app.ads.month_budget import money

        money(item["spend"])
        ExternalObservation.model_validate(
            {k: v for k, v in item.items() if k not in {"native_kind", "native_id"}}
            | {"entity_id": "unassigned"}
        )
        key = (item["native_kind"], item["native_id"])
        row_key = (*key, str(item["day"]))
        if row_key in row_keys:
            raise SourceReadError("月份來源重複同日活動，請完整重讀。", "invalid_source_page")
        row_keys.add(row_key)
        seen.add(key)
        roots = _monthly_roots(conn, job, *key)
        if len(roots) != 1 or roots[0]["brand_id"] != job["brand_id"]:
            unassigned.add(key[1])
            continue
        root = roots[0]
        if key in assigned and assigned[key] != root["id"]:
            unassigned.add(key[1])
        assigned[key] = root["id"]
        repo.upsert_observation(
            conn,
            job["org_id"],
            job["brand_id"],
            root["campaign_id"],
            {k: v for k, v in item.items() if k not in {"native_kind", "native_id"}}
            | {"entity_id": root["id"], "attribution_key": "account_monthly_spend"},
        )
    # Recheck all observed identities: another brand may have claimed a root between pages.
    for kind, native_id in sorted(seen):
        roots = _monthly_roots(conn, job, kind, native_id)
        if (
            len(roots) != 1
            or roots[0]["brand_id"] != job["brand_id"]
            or assigned.get((kind, native_id)) != roots[0]["id"]
        ):
            unassigned.add(native_id)
    task["seen_native_ids"] = sorted(seen)
    task["assigned_native_ids"] = [
        [kind, native, entity] for (kind, native), entity in sorted(assigned.items())
    ]
    task["row_keys"] = sorted(row_keys)
    task["page_count"] = page_count
    task["coverage"] = {**proof, "unassigned_native_ids": sorted(set(unassigned))}


def _save_page(conn, job, task, page):
    org, brand = job["org_id"], job["brand_id"]
    if len(page.items) > 100:
        raise ValueError("來源分頁超過100個節點。")
    errors = list(page.errors)
    for item in page.items:
        if task["section"] == "list":
            repo.cache_listing(conn, org, brand, job["platform"], job["source_account"], item)
        elif task["section"] == "observations":
            entity = conn.execute(
                "SELECT id FROM ads_external_entity WHERE org_id=%s AND "
                "brand_id=%s AND campaign_id=%s "
                "AND platform=%s AND source_account=%s AND native_kind=%s AND native_id=%s",
                (
                    org,
                    brand,
                    task["campaign_id"],
                    job["platform"],
                    job["source_account"],
                    item["native_kind"],
                    item["native_id"],
                ),
            ).fetchone()
            if entity is None:
                errors.append("部分成效缺少已讀回的來源節點。")
                continue
            repo.upsert_observation(
                conn,
                org,
                brand,
                task["campaign_id"],
                {k: v for k, v in item.items() if k not in {"native_kind", "native_id"}}
                | {"entity_id": entity["id"]},
            )
        else:
            if (
                item["platform"] != job["platform"]
                or item["source_account"] != job["source_account"]
            ):
                raise ValueError("來源頁的帳號範圍不符。")
            if (
                task["section"] == "creatives"
                and not conn.execute(
                    "SELECT 1 FROM ads_external_entity WHERE org_id=%s AND "
                    "brand_id=%s AND campaign_id=%s "
                    "AND platform=%s AND source_account=%s AND native_kind=%s AND native_id=%s",
                    (
                        org,
                        brand,
                        task["campaign_id"],
                        job["platform"],
                        job["source_account"],
                        item["native_kind"],
                        item["native_id"],
                    ),
                ).fetchone()
            ):
                errors.append("部分素材缺少已讀回的來源節點。")
                continue
            if "creative" in item:
                from app.ads import asset_binding_repository

                asset_binding_repository.lock_native(conn, {"org_id": org, **item})
            saved = repo.upsert_entity(conn, org, brand, task["campaign_id"], item)
            if "creative" in item:
                from app.ads import asset_binding_repository

                asset_binding_repository.stale_for_entity(
                    conn, org, brand, task["campaign_id"], saved["id"], item["creative"]
                )
    return errors


def run_sync(org_id, brand_id, job_id):
    with connection() as conn:
        set_tenant_scope(conn, org_id)
        job = repo.get_job(conn, org_id, brand_id, job_id)
        lock = f"external-account:{org_id}:{job['platform']}:{job['source_account']}"
        lock_row = conn.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS ok", (lock,)
        ).fetchone()
        acquired = bool(lock_row and lock_row["ok"])
        conn.commit()
        if not acquired:
            return  # The minute dispatcher retries durable pending jobs, across brands too.
        try:
            job = repo.get_job(conn, org_id, brand_id, job_id)
            pending = [
                (key, value) for key, value in job["tasks"].items() if value["status"] == "pending"
            ]
            if not pending:
                return
            priority = {"list": 0, "structure": 1, "creatives": 2, "observations": 3, "monthly": 4}
            key, task = min(pending, key=lambda pair: (priority[pair[1]["section"]], pair[0]))
            conn.execute(
                "UPDATE ads_external_sync_job SET "
                "status='running',last_attempt_at=now() WHERE id=%s",
                (job_id,),
            )
            conn.commit()
            try:
                reader, account = account_reader(
                    conn, org_id, brand_id, job["platform"], job["source_account"]
                )
                conn.commit()
                if task["section"] == "monthly" and not hasattr(reader, "read_monthly"):
                    raise SourceReadError("此來源尚未支援帳戶整月花費核對。", "unsupported")
                method = (
                    reader.list_existing
                    if task["section"] == "list"
                    else getattr(reader, "read_" + task["section"])
                )
                page = method(
                    conn,
                    org_id,
                    brand_id,
                    account,
                    cursor=task.get("cursor"),
                    native_id=task.get("native_id"),
                    start=task.get("start"),
                    end=task.get("end"),
                )
                if page.cursor is not None and page.cursor == task.get("cursor"):
                    raise ValueError("來源未前進至下一頁。")
                # A binding can be revoked while HTTP is in flight; do not save that response.
                _, current_account = account_reader(
                    conn, org_id, brand_id, job["platform"], job["source_account"]
                )
                latest_row = conn.execute(
                    "SELECT tasks FROM ads_external_sync_job WHERE id=%s FOR UPDATE", (job_id,)
                ).fetchone()
                if latest_row is None:
                    conn.rollback()
                    return
                latest = latest_row["tasks"].get(key, {})
                if latest.get("generation") != task.get("generation"):
                    conn.rollback()
                    _enqueue(repo.get_job(conn, org_id, brand_id, job_id))
                    return
                if task["section"] == "monthly":
                    _save_monthly(conn, job, task, page, current_account)
                    errors = []
                else:
                    errors = (task.get("errors", []) + _save_page(conn, job, task, page))[-20:]
                updated = {
                    **task,
                    "cursor": page.cursor,
                    "errors": errors,
                    "error_code": "partial_source_page" if errors else None,
                    "status": "pending" if page.cursor else "failed" if errors else "succeeded",
                }
                if not page.cursor and not errors:
                    updated["completed_at"] = now_utc()
                if task["section"] not in {"list", "monthly"}:
                    state = {
                        "status": "partial" if errors else "syncing" if page.cursor else "success",
                        "last_attempt_at": now_utc(),
                        "error": "；".join(errors) if errors else None,
                    }
                    if not page.cursor and not errors:
                        state["last_success_at"] = now_utc()
                        if task["section"] == "observations":
                            state["coverage"] = {"start": task["start"], "end": task["end"]}
                    repo.record_sync(
                        conn,
                        org_id,
                        brand_id,
                        task["campaign_id"],
                        section=task["section"],
                        state=state,
                    )
                # FK/acyclic constraints are deferred: check before marking the page successful.
                conn.execute("SET CONSTRAINTS ALL IMMEDIATE")
                if errors and task.get("campaign_id"):
                    from app.ads import asset_binding_repository

                    asset_binding_repository.sync_failed(
                        conn, org_id, brand_id, task["campaign_id"]
                    )
                current = _update_task(conn, job, key, updated)
            except Exception as exc:
                conn.rollback()
                latest_row = conn.execute(
                    "SELECT tasks FROM ads_external_sync_job WHERE id=%s FOR UPDATE", (job_id,)
                ).fetchone()
                if latest_row is None:
                    conn.rollback()
                    return
                latest = latest_row["tasks"].get(key, {})
                if latest.get("generation") != task.get("generation"):
                    conn.rollback()
                    _enqueue(repo.get_job(conn, org_id, brand_id, job_id))
                    return
                # No raw provider/validation exception is persisted (it can include source URLs).
                reason = "來源讀取失敗或連線已解除；已保留前次資料，可重試。"
                if isinstance(exc, SourceReadError):
                    reason = str(exc)
                code = exc.code if isinstance(exc, SourceReadError) else "invalid_source_page"
                attempts = task.get("attempts", 0) + 1
                retry = task["section"] == "monthly" and code == "source_error" and attempts < 3
                updated = {
                    **task,
                    "status": "pending" if retry else "failed",
                    "errors": [reason],
                    "error_code": code,
                    "attempts": attempts,
                }
                if task["section"] == "monthly":
                    updated["restart_required"] = code not in {
                        "source_error",
                        "permission_denied",
                        "disconnected",
                    }
                if task["section"] not in {"list", "monthly"}:
                    repo.record_sync(
                        conn,
                        org_id,
                        brand_id,
                        task["campaign_id"],
                        section=task["section"],
                        state={
                            "status": "error",
                            "error": reason,
                            "error_code": code,
                            "last_attempt_at": now_utc(),
                        },
                    )
                if task.get("campaign_id"):
                    from app.ads import asset_binding_repository

                    asset_binding_repository.sync_failed(
                        conn, org_id, brand_id, task["campaign_id"]
                    )
                current = _update_task(conn, job, key, updated)
            if current["status"] == "pending":
                _enqueue(current)
        finally:
            conn.rollback()
            conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (lock,))
            conn.commit()


def dispatch_pending(timestamp):
    with connection() as conn:
        orgs = conn.execute(
            "SELECT DISTINCT org_id FROM ads_external_sync_job "
            "WHERE status IN ('pending','running')"
        ).fetchall()
    for org in orgs:
        with connection() as conn:
            set_tenant_scope(conn, org["org_id"])
            rows = conn.execute(
                "SELECT * FROM ads_external_sync_job WHERE org_id=%s "
                "AND status IN ('pending','running')",
                (org["org_id"],),
            ).fetchall()
        for row in rows:
            _enqueue(dict(row))


def dispatch_daily(timestamp):
    with connection() as conn:
        scopes = {
            (r["org_id"], r["brand_id"], r["platform"], r["source_account"])
            for r in conn.execute(
                "SELECT DISTINCT org_id,brand_id,platform,source_account FROM ads_external_entity "
                "WHERE parent_native_id IS NULL"
            ).fetchall()
        }
        for channel in channels.CHANNELS:
            reader = channels.external_reader(channel["key"])
            if reader and hasattr(reader, "sync_scopes"):
                scopes.update(
                    (r["org_id"], r["brand_id"], channel["key"], r["source_account"])
                    for r in reader.sync_scopes(conn)
                )
    for org, brand, platform, account in sorted(scopes):
        with connection() as conn:
            set_tenant_scope(conn, org)
            try:
                request_sync(conn, org, brand, platform, account)
            except ValueError:
                conn.rollback()
