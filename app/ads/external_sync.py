"""Resumable account reads. One invocation commits one bounded page, never a platform write."""

from datetime import timedelta

from app import background
from app.ads import channels
from app.ads import external_repository as repo
from app.ads.adapters.external import SourceReadError
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
        "AND e.parent_native_id IS NULL AND c.origin='imported'",
        (org_id, brand_id, platform, source_account),
    ).fetchall()
    requested = {"list": {"section": "list"}}
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
        if task["status"] != "succeeded" or key in requested
    }
    active = row["status"] in {"pending", "running"}
    for key, task in requested.items():
        old = tasks.get(key)
        if active and old:
            continue
        # Failed pages retain the exact cursor; completed rounds restart at the first page.
        tasks[key] = {
            **task,
            "cursor": old.get("cursor") if old and old["status"] == "failed" else None,
            "status": "pending",
            "errors": [],
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
            repo.upsert_entity(conn, org, brand, task["campaign_id"], item)
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
            priority = {"list": 0, "structure": 1, "creatives": 2, "observations": 3}
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
                account_reader(conn, org_id, brand_id, job["platform"], job["source_account"])
                errors = _save_page(conn, job, task, page)
                errors = (task.get("errors", []) + errors)[-20:]
                updated = {
                    **task,
                    "cursor": page.cursor,
                    "errors": errors,
                    "status": "pending" if page.cursor else "failed" if errors else "succeeded",
                }
                if task["section"] != "list":
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
                current = _update_task(conn, job, key, updated)
            except Exception as exc:
                conn.rollback()
                # No raw provider/validation exception is persisted (it can include source URLs).
                reason = "來源讀取失敗或連線已解除；已保留前次資料，可重試。"
                if isinstance(exc, SourceReadError):
                    reason = str(exc)
                code = exc.code if isinstance(exc, SourceReadError) else "invalid_source_page"
                updated = {**task, "status": "failed", "errors": [reason], "error_code": code}
                if task["section"] != "list":
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
        rows = conn.execute(
            "SELECT DISTINCT org_id,brand_id,platform,source_account FROM ads_external_entity "
            "WHERE parent_native_id IS NULL"
        ).fetchall()
    for row in rows:
        with connection() as conn:
            set_tenant_scope(conn, row["org_id"])
            try:
                request_sync(conn, **dict(row))
            except ValueError:
                conn.rollback()
