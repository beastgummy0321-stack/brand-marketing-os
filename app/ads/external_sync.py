"""Resumable account reads. One invocation commits one bounded page, never a platform write."""

import calendar
from datetime import date, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app import background
from app.ads import channels, coverage, lifecycle, tracked_zero
from app.ads import external_repository as repo
from app.ads.adapters.external import SourceReadError
from app.ads.external_models import ExternalObservation
from app.ads.external_repository import MONTHLY_BUDGET_ATTRIBUTION_KEY
from app.core import settings
from app.core.db import connection, jsonb, new_id, now_utc, set_tenant_scope

TASK = "background.ads_external_sync"
SECTIONS = ("structure", "creatives", "observations")
# F49 Contract O: the key of the account task `record_request_failure` stores when a read could
# not even be requested (unbound account, unsupported platform). It is never pending, so no worker
# picks it, and the next `request_sync` drops it (it is not a requested key).
REQUEST_TASK = "request"

# -- F49 Contract O: one sync outcome --------------------------------------------------------------
# A read's outcome is computed here from its tasks and nowhere else: every screen reads `outcome`
# (through the routes and `useSyncOutcome`), never a job's `status`／`error` or a task's
# `errors`／`error_code`.
SYNC_STATES = ("running", "failed", "partial", "empty", "found")
SYNC_TEXT = {
    "running": "正在讀取平台資料",
    "failed": "這次沒讀到平台資料",
    "partial": "有部分平台資料沒讀到",
    "empty": "沒有讀到資料",
    "found": "已讀到平台資料",
}
# The first failed task's code by this priority names the reason; codes not listed follow.
CODE_PRIORITY = (
    "disconnected", "permission_denied", "unsupported", "source_error", "page_limit",
    "invalid_source_page", "invalid_monthly_scope", "partial_source_page", "derive_failed",
)
# One sentence per `SourceReadError` code the adapters and this module raise, plus `no_rows`
# (read cleanly, the platform returned nothing) and `not_read` (no read on record yet).
SYNC_REASONS = {
    "disconnected": "廣告帳戶已解除連結或不屬於這個品牌，請到設定重新連接",
    "permission_denied": "平台授權已失效或權限不足，請重新授權",
    "unsupported": "這個平台還不支援這項讀取",
    "source_error": "平台暫時沒有回應，稍後會再試",
    "page_limit": "資料量超過一次可讀的上限，這次沒有讀完",
    "invalid_source_page": "平台回傳的資料無法核對，這次沒有存下",
    "invalid_monthly_scope": "帳戶整月花費的範圍、幣別或時區無法核對",
    "partial_source_page": "部分成效或素材對不到已讀到的廣告，這幾筆沒有存下",
    "derive_failed": "已讀到的成效沒問題，但推算「0 筆」的規則出錯，可重新讀取",
    "parent_mismatch": "平台物件或它的上層結構無法核對",
    "no_rows": "平台在這段期間沒有回傳任何資料",
    "not_read": "這個帳戶還沒讀取過",
}
_FINISHED = {"succeeded", "failed"}


def _code_rank(code):
    return CODE_PRIORITY.index(code) if code in CODE_PRIORITY else len(CODE_PRIORITY)


def _result(state, code):
    reason = SYNC_REASONS.get(code) if code else None
    return {
        "state": state,
        "code": code,
        "text": f"{SYNC_TEXT[state]}：{reason}" if reason else SYNC_TEXT[state],
    }


def outcome(tasks, *, campaign_id=None):
    """F49 Contract O: `{state, code, text}` of a job's `tasks` (key -> task), pure.

    Scope = the account tasks (no `campaign_id`) plus `campaign_id`'s tasks (every campaign task
    when `None`). State, first match: `running` (a scoped task is pending), `failed` (every
    finished scoped task failed), `partial` (some failed), `empty` (none failed and the scoped
    `observations` tasks -- or the `list` task when no campaign task is in scope -- saved 0
    rows; no task at all is `not_read`), else `found`. A task finished before rows were counted
    (no `rows`) is never read as empty."""
    scoped = {
        key: task for key, task in (tasks or {}).items()
        if not task.get("campaign_id") or campaign_id is None
        or task.get("campaign_id") == campaign_id
    }
    if not scoped:
        return _result("empty", "not_read")
    if any(task.get("status") == "pending" for task in scoped.values()):
        return _result("running", None)
    finished = [task for task in scoped.values() if task.get("status") in _FINISHED]
    failed = [task for task in finished if task.get("status") == "failed"]
    if failed:
        code = min(
            (task.get("error_code") or "source_error" for task in failed), key=_code_rank,
        )
        return _result("failed" if len(failed) == len(finished) else "partial", code)
    if any(task.get("campaign_id") for task in scoped.values()):
        counted = [t for t in scoped.values() if t.get("section") == "observations"]
    else:
        counted = [scoped["list"]] if "list" in scoped else []
    if counted and all(isinstance(t.get("rows"), int) for t in counted) \
            and sum(t["rows"] for t in counted) == 0:
        return _result("empty", "no_rows")
    return _result("found", None)


def clean_task_success(task):
    """Whether one task finished cleanly; consumers never interpret raw task errors."""
    return task.get("status") == "succeeded" and not task.get("errors")


def monthly_failure(tasks):
    """An account's unresolved month failure, including a retry not yet read to completion.

    The job still reports running while pages are pending; its source retains the previous
    failure reason until that month succeeds, rather than healing on a different month's read.
    """
    failed = {
        key: {**task, "status": "failed"}
        for key, task in tasks.items()
        if key.startswith("monthly:") and (
            task.get("status") == "failed"
            or task.get("status") == "pending" and task.get("error_code")
        )
    }
    return outcome(failed) if failed else None


def failed_outcome(exc):
    """The outcome of a read that could not even start (`account_reader` raised)."""
    return _result("failed", getattr(exc, "code", None) or "source_error")


_STATE_RANK = {"found": 0, "empty": 1, "partial": 2, "failed": 3, "running": 4}
_JOB_STATUS = {
    "running": "pending", "failed": "failed", "partial": "partial",
    "empty": "succeeded", "found": "succeeded",
}


def _store_outcome(conn, job_id, tasks):
    """Write the job-wide outcome: `status ∈ {pending, succeeded, partial, failed}` and `error` =
    the outcome text when partial／failed, else NULL. The only writer of a job's status／error
    after a task finished."""
    result = outcome(tasks)
    status = _JOB_STATUS[result["state"]]
    conn.execute(
        "UPDATE ads_external_sync_job SET status=%s,error=%s,last_success_at=CASE WHEN "
        "%s='succeeded' THEN now() ELSE last_success_at END WHERE id=%s",
        (status, result["text"] if status in {"partial", "failed"} else None, status, job_id),
    )
    return status


def record_request_failure(conn, org_id, brand_id, platform, source_account, code):
    """F49 Contract O: a read that could not be requested (the runtime's backoff row). Stores a
    failed `request` account task so `outcome` names `code`, and stamps the attempt so the
    runtime's due rule backs off. Earlier tasks (and their coverage proof) are kept."""
    conn.execute(
        "INSERT INTO ads_external_sync_job(id,org_id,brand_id,platform,source_account) "
        "VALUES (%s,%s,%s,%s,%s) ON CONFLICT(org_id,brand_id,platform,source_account) DO NOTHING",
        (new_id("aes"), org_id, brand_id, platform, source_account),
    )
    row = conn.execute(
        "SELECT id,tasks FROM ads_external_sync_job WHERE org_id=%s AND brand_id=%s "
        "AND platform=%s AND source_account=%s FOR UPDATE",
        (org_id, brand_id, platform, source_account),
    ).fetchone()
    assert row is not None
    code = code or "source_error"
    tasks = {
        **dict(row["tasks"] or {}),
        REQUEST_TASK: {
            "section": REQUEST_TASK, "status": "failed", "error_code": code,
            "errors": [SYNC_REASONS.get(code, SYNC_REASONS["source_error"])], "rows": 0,
            "attempted_at": now_utc(),
        },
    }
    conn.execute(
        "UPDATE ads_external_sync_job SET tasks=%s,last_attempt_at=now(),updated_at=now() "
        "WHERE id=%s",
        (jsonb(tasks), row["id"]),
    )
    _store_outcome(conn, row["id"], tasks)
    conn.commit()


def bound_accounts(conn, org_id, brand_id):
    """`(platform, account_id)` of every account bound to the brand, across the channels."""
    return [
        (channel["key"], account["account_id"])
        for channel in channels.CHANNELS
        if (reader := channels.external_reader(channel["key"]))
        for account in reader.accounts(conn, org_id, brand_id)
    ]


def _campaign_accounts(conn, org_id, brand_id, campaign_id):
    """The accounts covering a campaign: its roots' accounts; no root -> every bound account
    (a campaign not on a platform yet is looked for in the account listing)."""
    roots = conn.execute(
        "SELECT DISTINCT platform,source_account FROM ads_external_entity WHERE org_id=%s "
        "AND brand_id=%s AND campaign_id=%s AND parent_native_id IS NULL "
        "ORDER BY platform,source_account",
        (org_id, brand_id, campaign_id),
    ).fetchall()
    if roots:
        return [(r["platform"], r["source_account"]) for r in roots], True
    return bound_accounts(conn, org_id, brand_id), False


def account_job(conn, org_id, brand_id, platform, source_account):
    row = conn.execute(
        "SELECT * FROM ads_external_sync_job WHERE org_id=%s AND brand_id=%s AND platform=%s "
        "AND source_account=%s",
        (org_id, brand_id, platform, source_account),
    ).fetchone()
    return dict(row) if row else None


def request_campaign_sync(conn, org_id, brand_id, campaign_id, *, start=None, end=None):
    """Every job a campaign's 重新讀取 requests: each root account with the asked window; a
    campaign without a root refreshes every bound account (drill 5). Raises `ValueError` when
    there is nothing to read."""
    accounts, rooted = _campaign_accounts(conn, org_id, brand_id, campaign_id)
    if not accounts:
        raise ValueError("此工作區沒有可同步的原生來源。")
    window = {"start": start, "end": end} if rooted else {}
    # F49 Contract N: the campaign the user asked to re-read is read, monitored or not.
    return [
        request_sync(conn, org_id, brand_id, platform, account, campaign_ids=(campaign_id,),
                     retry_failed_monthly=True, **window)
        for platform, account in accounts
    ]


def campaign_outcome(conn, org_id, brand_id, campaign_id):
    """`{state, code, text, job_ids, last_success_at}` -- the worst outcome over the jobs
    covering the campaign (running wins while any runs, then failed > partial > empty > found).
    `last_success_at` is the oldest of their clean reads (null while any never read cleanly):
    everything shown was read at least then."""
    accounts, _ = _campaign_accounts(conn, org_id, brand_id, campaign_id)
    results, jobs = [], []
    for platform, account in accounts:
        job = account_job(conn, org_id, brand_id, platform, account)
        if job is not None:
            jobs.append(job)
        results.append(outcome(job["tasks"] if job else {}, campaign_id=campaign_id))
    worst = max(results, key=lambda r: _STATE_RANK[r["state"]]) if results else outcome({})
    successes = [job["last_success_at"] for job in jobs]
    return {
        **worst,
        "job_ids": [job["id"] for job in jobs],
        "last_success_at": min(successes)
        if successes and len(jobs) == len(accounts) and None not in successes else None,
    }
# Advisory locks are database-wide, but the rows this lock serialises live in the connection's
# schema. The key carries `current_schema()` so a read in one schema never skips because a
# different schema (another test module/run on the same server) holds the same account.
ACCOUNT_LOCK_KEY = "hashtextextended(current_schema() || ':' || %s, 0)"


def account_lock_name(org_id, platform, source_account):
    return f"external-account:{org_id}:{platform}:{source_account}"


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


def _proven_end(conn, org_id, task, account) -> date | None:
    """F50 Contract K: the last day a clean read of `[task.start, task.end]` proves --
    `min(task.end, the account's last complete day now)` (`coverage.account_last_complete_day`);
    `None` when no day of the range is over yet."""
    if not task.get("start") or not task.get("end"):
        return None
    start, end = date.fromisoformat(task["start"]), date.fromisoformat(task["end"])
    end = min(end, coverage.account_last_complete_day(conn, org_id, account))
    return end if start <= end else None


def proven(task) -> dict | None:
    """The range a month task proved (`{start, end}`, already clipped when recorded): a
    succeeded task's own `covered`; a task recorded before F50 its requested range as stored."""
    if task.get("status") != "succeeded":
        return None
    if "covered" in task:
        return task["covered"]
    if task.get("start") and task.get("end"):
        return {"start": task["start"], "end": task["end"]}
    return None


def _last_covered(old):
    """F30-I14: the last range a month task finished reading, carried across the reset below so
    the days it proved stay provable while the next read runs or after it fails. A succeeded task
    is its own proof (`proven`); otherwise the proof it already carried survives."""
    if not old:
        return None
    if old.get("status") == "succeeded":
        covered = proven(old)
        if covered:
            return {**covered, "completed_at": old.get("completed_at")}
    return old.get("last_covered")


def monthly_supported(reader):
    """A reader that cannot prove an account's whole month gets no `monthly:` task (it would
    only ever fail and hold the job `partial`); a reader without the method is assumed able."""
    return bool(getattr(reader, "monthly_supported", lambda: True)())


def request_sync(conn, org_id, brand_id, platform, source_account, *, start=None, end=None,
                 campaign_ids=(), retry_failed_monthly=False):
    """Request the account's read. Account tasks (`list`, `monthly:*`) always; per-campaign
    sections (`SECTIONS`) only for the roots of campaigns `lifecycle.monitored` today, plus the
    `campaign_ids` passed explicitly (a campaign the user asked to re-read or just imported,
    monitored or not) -- F49 Contract N: a closed campaign, or one ended past the grace days, is
    not re-read in the background. Explicit user retry also requests this account's retained
    failed months, at their original ranges; scheduled reads keep only their requested window."""
    reader, _ = account_reader(conn, org_id, brand_id, platform, source_account)
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
    if roots:
        wanted = lifecycle.monitored_ids(conn, org_id, brand_id) | set(campaign_ids)
        roots = [root for root in roots if root["campaign_id"] in wanted]
    requested = {"list": {"section": "list"}}
    # Explicit backfills cover each touched month; daily/default reads cover this month.
    supports_monthly = monthly_supported(reader)
    month = month_request_start.replace(day=1)
    while supports_monthly and month <= end:
        month_end = month.replace(day=calendar.monthrange(month.year, month.month)[1])
        requested["monthly:" + month.strftime("%Y-%m")] = {
            "section": "monthly",
            "start": month.isoformat(),
            "end": min(today, month_end).isoformat(),
        }
        month = month_end + timedelta(days=1)
    if retry_failed_monthly and supports_monthly:
        for key, task in tasks.items():
            if key.startswith("monthly:") and task["status"] == "failed" and key not in requested:
                requested[key] = {field: task[field] for field in ("section", "start", "end")}
    # A clock moving backwards cannot let a shorter clean read erase an unresolved scope.
    # Validate the entire request before replacing any task or enqueueing any new month.
    for key, task in requested.items():
        old = tasks.get(key)
        if old and monthly_failure({key: old}) and (
            task["start"] > old["start"] or task["end"] < old["end"]
        ):
            raise ValueError("本次日期範圍尚未涵蓋先前失敗資料，請確認日期後重試。")
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
    # Observation keys carry their range, and the default range moves daily: a finished task
    # (succeeded or failed) this call did not request is dropped, or an old failed range would
    # hold the job `partial` forever. Pending ones stay for callers that request several ranges.
    tasks = {
        key: task
        for key, task in tasks.items()
        if task["status"] == "pending" or key in requested or key.startswith("monthly:")
    }
    active = row["status"] in {"pending", "running"}
    for key, task in requested.items():
        old = tasks.get(key)
        same_range = (
            old and old.get("start") == task.get("start") and old.get("end") == task.get("end")
        )
        failed_month = old and task["section"] == "monthly" and old["status"] == "failed"
        if active and old and (task["section"] != "monthly" or same_range) \
                and not (retry_failed_monthly and failed_month):
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
            "errors": old.get("errors", []) if old and failed_month else [],
            "error_code": old.get("error_code") if old and failed_month else None,
            "attempts": 0,
            # Contract O: saved rows of this generation (a resumed read keeps counting).
            "rows": resumed.get("rows") if resume else 0,
        }
        covered = _last_covered(old) if task["section"] == "monthly" else None
        if covered:
            tasks[key]["last_covered"] = covered
    conn.execute(
        "UPDATE ads_external_sync_job SET "
        "tasks=%s,status='pending',error=NULL,updated_at=now() WHERE id=%s",
        (jsonb(tasks), row["id"]),
    )
    conn.commit()
    job = repo.get_job(conn, org_id, brand_id, row["id"])
    _enqueue(job)
    return job


def _count_rows(task, saved):
    """Add a page's saved rows; a task from before rows were counted stays uncounted (never
    read as empty)."""
    if isinstance(task.get("rows"), int):
        task["rows"] += saved


def _update_task(conn, job, key, task):
    conn.execute(
        "UPDATE ads_external_sync_job SET tasks=tasks || jsonb_build_object(%s::text,%s::jsonb), "
        "revision=revision+1,last_attempt_at=now(),updated_at=now() WHERE "
        "org_id=%s AND brand_id=%s AND id=%s",
        (key, jsonb(task), job["org_id"], job["brand_id"], job["id"]),
    )
    current = repo.get_job(conn, job["org_id"], job["brand_id"], job["id"])
    _store_outcome(conn, job["id"], current["tasks"])
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
    saved = 0
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
            | {"entity_id": root["id"], "attribution_key": MONTHLY_BUDGET_ATTRIBUTION_KEY},
        )
        saved += 1
    _count_rows(task, saved)
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


def _fill_result_kind_if_null(conn, reader, org, brand, campaign_id, item):
    """F16-I04: `ads_campaign.result_kind` from the campaign-level entity (this platform's root
    of the campaign's own tree -- no `parent_native_id`, whatever `native_kind` label that
    platform gives it; not hard-coded to Meta's `"campaign"`), only when it is currently NULL --
    a user's later PUT choice (`repository.save_campaign_target`) must never be overwritten by a
    re-sync. `reader.result_kind()` is the one seam shared code reads this through (§0 "shared
    code must not read a Meta objective string"); a reader without that capability (no
    result-kind mapping defined, e.g. the generic/manual adapters) leaves `result_kind`
    untouched, same as an unmapped objective."""
    if not hasattr(reader, "result_kind"):
        return
    result_kind = reader.result_kind(item)
    if result_kind is None:
        return
    conn.execute(
        "UPDATE ads_campaign SET result_kind=%s WHERE org_id=%s AND brand_id=%s AND id=%s"
        " AND result_kind IS NULL",
        (result_kind, org, brand, campaign_id),
    )


def _save_page(conn, job, task, page, reader=None):
    org, brand = job["org_id"], job["brand_id"]
    if len(page.items) > 100:
        raise ValueError("來源分頁超過100個節點。")
    errors = list(page.errors)
    saved = 0  # Contract O: rows this page saved, added to the task's `rows` below.
    for item in page.items:
        if task["section"] == "list":
            repo.cache_listing(conn, org, brand, job["platform"], job["source_account"], item)
            saved += 1
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
            result_keys = {"result_kind", "result_count", "result_action", "result_attribution"}
            fields = {
                k: v for k, v in item.items() if k not in {"native_kind", "native_id", *result_keys}
            }
            repo.upsert_observation(
                conn,
                org,
                brand,
                task["campaign_id"],
                fields | {"entity_id": entity["id"]},
                result_kind=item.get("result_kind"),
                result_count=item.get("result_count"),
                result_action=item.get("result_action"),
                result_attribution=item.get("result_attribution"),
                # F16-I06: this is the one point every platform reader's regular (non-monthly)
                # observation write routes through -- heal superseded same-identity rows here,
                # not per reader.
                heal_superseded_attribution=True,
            )
            saved += 1
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
            entity = repo.upsert_entity(conn, org, brand, task["campaign_id"], item)
            saved += 1
            if "creative" in item:
                from app.ads import asset_binding_repository

                asset_binding_repository.stale_for_entity(
                    conn, org, brand, task["campaign_id"], entity["id"], item["creative"]
                )
            if task["section"] == "structure" and not item.get("parent_native_id"):
                _fill_result_kind_if_null(conn, reader, org, brand, task["campaign_id"], item)
    _count_rows(task, saved)
    return errors


def job_result(conn, org_id, brand_id, job_id):
    """F50 Contract J: what one `background.ads_external_sync` invocation reports, from the job's
    Contract O outcome after it ran -- failed／partial -> `Failed(code, text)`, empty ->
    `Empty("no_rows")`, found -> done (None). A job still reading (a task pending: the next page
    is queued as its own job) is done for this invocation; a job no longer on record is done."""
    try:
        job = repo.get_job(conn, org_id, brand_id, job_id)
    except ValueError:
        return None
    result = outcome(job["tasks"])
    if result["state"] in {"failed", "partial"}:
        return background.Failed(result["code"] or "source_error", result["text"])
    if result["state"] == "empty":
        return background.Empty("no_rows", result["text"])
    return None


def run_sync(org_id, brand_id, job_id):
    """One page of one account read (module docstring); returns the job's Contract J result
    (`job_result`) once this page is recorded."""
    ran = _run_page(org_id, brand_id, job_id)
    if not ran:
        return None
    with connection() as conn:
        set_tenant_scope(conn, org_id)
        return job_result(conn, org_id, brand_id, job_id)


def _run_page(org_id, brand_id, job_id) -> bool:
    """Read and record one page. False when nothing was read by this invocation (the account
    lock is held elsewhere, nothing is pending, or a newer request superseded the page)."""
    with connection() as conn:
        set_tenant_scope(conn, org_id)
        job = repo.get_job(conn, org_id, brand_id, job_id)
        lock = account_lock_name(org_id, job["platform"], job["source_account"])
        lock_row = conn.execute(
            f"SELECT pg_try_advisory_lock({ACCOUNT_LOCK_KEY}) AS ok", (lock,)
        ).fetchone()
        acquired = bool(lock_row and lock_row["ok"])
        conn.commit()
        if not acquired:
            return False  # The minute dispatcher retries durable pending jobs, across brands too.
        try:
            job = repo.get_job(conn, org_id, brand_id, job_id)
            pending = [
                (key, value) for key, value in job["tasks"].items() if value["status"] == "pending"
            ]
            if not pending:
                return False
            priority = {"list": 0, "structure": 1, "creatives": 2, "observations": 3, "monthly": 4}
            key, task = min(pending, key=lambda pair: (priority[pair[1]["section"]], pair[0]))
            conn.execute(
                "UPDATE ads_external_sync_job SET "
                "status='running',last_attempt_at=now() WHERE id=%s",
                (job_id,),
            )
            conn.commit()
            rows_before = task.get("rows")  # a rolled-back page saved nothing
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
                    return False
                latest = latest_row["tasks"].get(key, {})
                if latest.get("generation") != task.get("generation"):
                    conn.rollback()
                    _enqueue(repo.get_job(conn, org_id, brand_id, job_id))
                    return False
                if task["section"] == "monthly":
                    _save_monthly(conn, job, task, page, current_account)
                    errors = []
                else:
                    errors = (
                        task.get("errors", []) + _save_page(conn, job, task, page, reader)
                    )[-20:]
                pending_month = task["section"] == "monthly" and bool(page.cursor)
                updated = {
                    **task,
                    "cursor": page.cursor,
                    "errors": task.get("errors", []) if pending_month else errors,
                    "error_code": task.get("error_code") if pending_month
                    else "partial_source_page" if errors else None,
                    "status": "pending" if page.cursor else "failed" if errors else "succeeded",
                }
                finished = not page.cursor and not errors
                # F50 Contract K: a clean read proves its days only up to the account's last
                # complete day when it finished -- recorded clipped, so no reader clips again.
                proven_end = (
                    _proven_end(conn, org_id, task, current_account) if finished else None
                )
                if finished:
                    updated["completed_at"] = now_utc()
                    if task["section"] == "monthly":
                        updated["covered"] = (
                            {"start": task["start"], "end": proven_end.isoformat()}
                            if proven_end is not None else None
                        )
                if task["section"] not in {"list", "monthly"}:
                    state = {
                        "status": "partial" if errors else "syncing" if page.cursor else "success",
                        "last_attempt_at": now_utc(),
                        "error": "；".join(errors) if errors else None,
                    }
                    if finished:
                        state["last_success_at"] = now_utc()
                        if task["section"] == "observations" and proven_end is not None:
                            state["coverage"] = {
                                "start": task["start"], "end": proven_end.isoformat(),
                            }
                        if task["section"] == "observations":
                            # F18-I01: derive conditional tracked zeros in this same transaction,
                            # only once this section's read for the covered window is complete
                            # and clean (no cursor, no errors) -- same place coverage is recorded.
                            # The cutoff for "day is complete" is the one ads answer
                            # (`coverage.account_last_complete_day`, F50 Contract K) for the
                            # account just read; an unknown zone fails closed to the fallback.
                            try:
                                tracked_zero.apply(
                                    conn,
                                    org_id,
                                    brand_id,
                                    task["campaign_id"],
                                    date.fromisoformat(task["start"]),
                                    date.fromisoformat(task["end"]),
                                    coverage.account_last_complete_day(
                                        conn, org_id, current_account),
                                )
                            except SourceReadError:
                                raise
                            except Exception as exc:
                                # Never a source read failure -- the platform read already
                                # succeeded; this is our own derivation rule breaking.
                                raise SourceReadError(
                                    "推定 0 規則執行失敗，"
                                    "已讀到的成效本身不受影響，可重新同步。",
                                    "derive_failed",
                                ) from exc
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
                    return False
                latest = latest_row["tasks"].get(key, {})
                if latest.get("generation") != task.get("generation"):
                    conn.rollback()
                    _enqueue(repo.get_job(conn, org_id, brand_id, job_id))
                    return False
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
                    "rows": rows_before,
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
            return True
        finally:
            conn.rollback()
            conn.execute(f"SELECT pg_advisory_unlock({ACCOUNT_LOCK_KEY})", (lock,))
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
    # F50 Contract J: an account that cannot be requested is recorded on its own job (Contract O
    # `record_request_failure`: the reason shows and the runtime backs off), never dropped
    # silently; any other failure raises and fails this dispatcher job.
    for org, brand, platform, account in sorted(scopes):
        with connection() as conn:
            set_tenant_scope(conn, org)
            try:
                request_sync(conn, org, brand, platform, account)
            except ValueError as exc:
                conn.rollback()
                record_request_failure(conn, org, brand, platform, account,
                                       getattr(exc, "code", None))
