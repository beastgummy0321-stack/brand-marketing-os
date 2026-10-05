"""Durable, bounded local monitoring. All platform operations are existing read interfaces."""

import logging
from datetime import UTC, date, datetime, timedelta

from app import background
from app.ads import change_control_data as changes
from app.ads import channels, external_sync, lifecycle, month_budget
from app.ads.adapters.external import SourceReadError
from app.core import db, interrupts, settings

TASK = "background.ads_runtime_campaign"
INTERVAL_SECONDS = 900
SYNC_SECONDS = 21600
ALERT_CATEGORY = "ads_runtime_attention"
#: F50 Contract J: the code a tick that swallowed a failure (after writing its health row) ends
#: its job with, so the bell counts it.
RUNTIME_ERROR = "runtime_error"

logger = logging.getLogger(__name__)


def _time(value):
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _due(value, now, seconds):
    last = _time(value)
    return last is None or last.tzinfo is None or now - last >= timedelta(seconds=seconds)


def _save(conn, org, brand, campaign, patch):
    _patch_runtime(conn, org, brand, campaign, patch)
    conn.commit()


def _sources(conn, org, brand, campaign):
    rows = conn.execute(
        "SELECT DISTINCT e.platform,e.source_account,j.status,j.last_attempt_at,j.last_success_at,"
        "j.tasks FROM ads_external_entity e LEFT JOIN ads_external_sync_job j "
        "ON j.org_id=e.org_id AND j.brand_id=e.brand_id AND j.platform=e.platform "
        "AND j.source_account=e.source_account WHERE e.org_id=%s AND e.brand_id=%s "
        "AND e.campaign_id=%s AND e.parent_native_id IS NULL ORDER BY e.platform,e.source_account",
        (org, brand, campaign),
    ).fetchall()
    result = []
    for row in rows:
        tasks = list((row["tasks"] or {}).values())
        periods = [
            t for t in tasks if t.get("campaign_id") == campaign
            and t.get("section") == "observations" and t.get("status") == "succeeded"
        ]
        latest = max(periods, key=lambda t: t["end"]) if periods else None
        # F49 Contract O: the read's one outcome, scoped to this campaign (and its account).
        read = external_sync.outcome(row["tasks"] or {}, campaign_id=campaign)
        result.append({
            **{k: row[k] for k in (
                "platform", "source_account", "last_attempt_at", "last_success_at"
            )},
            "status": row["status"] or "unknown",
            "coverage": {"start": latest["start"], "end": latest["end"]} if latest else None,
            "error": read["text"] if read["state"] in {"failed", "partial"} else None,
        })
    return result


def view(conn, org, brand, campaign):
    from app.ads import review_monitor

    value = changes.campaign(conn, org, brand, campaign)
    saved = (value.get("context_json") or {}).get("runtime") or {}
    return {
        "monitors": review_monitor.workspace(conn, org, brand, campaign)["monitors"],
        "sources": _sources(conn, org, brand, campaign),
        "health": saved.get("health", []),
        "last_checked_at": saved.get("last_checked_at"),
        "last_bootstrap_at": saved.get("last_bootstrap_at"),
        "budget": saved.get("budget"),
        "notice": "關閉網頁不會停止背景工作；本機關機或服務停機會中斷監測，平台仍可能花費。",
    }


def _chunks(start, end):
    while start <= end:
        stop = min(start + timedelta(days=30), end)
        yield start, stop
        start = stop + timedelta(days=1)


def _sync_sources(conn, org, brand, campaign, now):
    from app.ads import review_monitor

    today = settings.today_for_org(conn, org_id=org)
    count = 0
    for source in _sources(conn, org, brand, campaign):
        job = conn.execute(
            "SELECT * FROM ads_external_sync_job WHERE org_id=%s AND brand_id=%s "
            "AND platform=%s AND source_account=%s",
            (org, brand, source["platform"], source["source_account"]),
        ).fetchone()
        if job and (job["status"] in {"pending", "running"}
                    or not _due(job["updated_at"], now, SYNC_SECONDS)):
            continue  # Preserve the existing page cursor/generation; permission errors back off.
        campaigns = conn.execute(
            "SELECT DISTINCT campaign_id FROM ads_external_entity WHERE org_id=%s AND brand_id=%s "
            "AND platform=%s AND source_account=%s AND parent_native_id IS NULL",
            (org, brand, source["platform"], source["source_account"]),
        ).fetchall()
        windows = [
            window for item in campaigns
            for window in review_monitor.required_windows(conn, org, brand, item["campaign_id"])
        ]
        requested = {(today - timedelta(days=29), today)}
        for window in windows:
            if (window["platform"], window["source_account"]) != (
                source["platform"], source["source_account"]
            ):
                continue
            start, end = window["start"], window["end"]
            start = start if isinstance(start, date) else date.fromisoformat(start)
            end = end if isinstance(end, date) else date.fromisoformat(end)
            requested.update(_chunks(start, min(end, today)))
        # Each review window is <=62 days including its comparison. Retain all requested
        # ranges; do not arbitrarily cut off a historical window or reset in-flight pages.
        try:
            for start, end in sorted(requested):
                external_sync.request_sync(
                    conn, org, brand, source["platform"], source["source_account"],
                    start=start, end=end,
                )
                count += 1
        except Exception as exc:
            conn.rollback()
            # Even a disconnected account needs a persisted backoff. A failure before
            # request_sync's insert must not cause a new source attempt every minute.
            external_sync.record_request_failure(
                conn, org, brand, source["platform"], source["source_account"],
                exc.code if isinstance(exc, SourceReadError) else None,
            )
    return count


def _readback(conn, org, brand, campaign):
    from app.ads import change_control_verify, handoff_check

    # IDs must already be known; discovery never guesses the object a human changed. F49 Contract
    # N: a `confirmed` item or action is final for the tick (the user's 重新核對 still reads it).
    failed = 0
    items = conn.execute(
        "SELECT h.* FROM ads_handoff_item h JOIN ads_change_set c ON c.id=h.change_set_id "
        "AND c.org_id=h.org_id AND c.brand_id=h.brand_id WHERE h.org_id=%s AND h.brand_id=%s "
        "AND h.campaign_id=%s AND c.status='approved' AND h.entity_id IS NOT NULL "
        "AND h.status NOT IN ('confirmed','stale') ORDER BY "
        "COALESCE(h.evidence_json->>'runtime_checked_at',h.created_at::text),h.id LIMIT 3",
        (org, brand, campaign),
    ).fetchall()
    for item in items:
        entity = conn.execute(
            "SELECT platform,source_account,native_kind,native_id FROM ads_external_entity "
            "WHERE org_id=%s AND brand_id=%s AND campaign_id=%s AND id=%s",
            (org, brand, campaign, item["entity_id"]),
        ).fetchone()
        if entity:
            try:
                handoff_check.check(conn, org, brand, campaign, item["id"], dict(entity), "system")
            except Exception:
                conn.rollback()
                failed += 1
                conn.execute(
                    "UPDATE ads_handoff_item SET status='unknown',evidence_json=evidence_json "
                    "|| %s::jsonb WHERE org_id=%s AND brand_id=%s AND campaign_id=%s AND id=%s "
                    "AND status<>'stale'",
                    (db.jsonb({"attempted_at": db.now_utc(), "setting_matches": None,
                               "message": "本次讀回未完成；保留過去觀測，請檢視連線與計畫。"}),
                     org, brand, campaign, item["id"]),
                )
                conn.execute(
                    "UPDATE ads_action SET verification_state='unknown' WHERE org_id=%s "
                    "AND brand_id=%s AND campaign_id=%s AND id=%s AND verification_state<>'stale'",
                    (org, brand, campaign, item["action_id"]),
                )
            conn.execute(
                "UPDATE ads_handoff_item SET evidence_json=evidence_json || %s::jsonb "
                "WHERE org_id=%s AND brand_id=%s AND campaign_id=%s AND id=%s",
                (db.jsonb({"runtime_checked_at": db.now_utc()}), org, brand, campaign, item["id"]),
            )
            conn.commit()
    actions = conn.execute(
        "SELECT a.id,a.change_set_id FROM ads_action a JOIN ads_change_set c "
        "ON c.id=a.change_set_id AND c.org_id=a.org_id AND c.brand_id=a.brand_id "
        "WHERE a.org_id=%s AND a.brand_id=%s AND a.campaign_id=%s AND c.status='approved' "
        "AND a.verification_state NOT IN ('confirmed','stale') AND NOT EXISTS "
        "(SELECT 1 FROM ads_handoff_item h WHERE h.action_id=a.id) "
        "ORDER BY COALESCE(a.evidence_json->>'runtime_checked_at',a.created_at::text),a.id LIMIT 3",
        (org, brand, campaign),
    ).fetchall()
    for action in actions:
        try:
            change_control_verify.check(
                conn, org, brand, campaign, action["change_set_id"], action["id"], "system"
            )
        except Exception:
            conn.rollback()
            failed += 1
            conn.execute(
                "UPDATE ads_action SET verification_state='unknown' WHERE org_id=%s "
                "AND brand_id=%s AND campaign_id=%s AND id=%s AND verification_state<>'stale'",
                (org, brand, campaign, action["id"]),
            )
        conn.execute(
            "UPDATE ads_action SET evidence_json=evidence_json || %s::jsonb "
            "WHERE org_id=%s AND brand_id=%s AND campaign_id=%s AND id=%s",
            (db.jsonb({"runtime_checked_at": db.now_utc()}), org, brand, campaign, action["id"]),
        )
        conn.commit()
    if failed:
        raise ValueError("部分平台項目未讀回，保留歷史與未知狀態。")
    return len(items) + len(actions)


def _alert_key(campaign, code, since):
    """One row per episode of an alert: `since` is the day this run of the condition was first
    seen. While it persists the key stays the same (one open row, and a row the user resolved is
    not raised again); once it clears and later returns, the new episode raises a new row (the
    interrupt dedupe index spans every status, so a reused key could never come back)."""
    return f"{_alert_prefix(campaign)}{code}:{since}"


def _alert_prefix(campaign):
    return f"ads-runtime:{campaign}:"


def _episodes(saved, codes, today):
    """`{code: since}` for the codes raised now: a code already running keeps its day, a new one
    starts today; a code no longer raised is dropped (its episode ended)."""
    since = saved if isinstance(saved, dict) else {}
    return {code: since.get(code) or today.isoformat() for code in codes}


def _patch_runtime(conn, org, brand, campaign, patch):
    conn.execute(
        "UPDATE ads_campaign SET context_json=jsonb_set(context_json,'{runtime}',"
        "COALESCE(context_json->'runtime','{}'::jsonb) || %s::jsonb) "
        "WHERE org_id=%s AND brand_id=%s AND id=%s",
        (db.jsonb(patch), org, brand, campaign),
    )


def resolve_alerts(conn, org, brand, campaign, *, keep=()):
    """Resolve (`interrupts.resolve`, actor `system`) every open `ads_runtime_attention` row of
    this campaign whose key is not in `keep` -- the old dated keys (`ads-runtime:{c}:{day}:{code}`)
    included, by prefix. Called by the tick after raising (`keep` = what it raised), and with
    `keep=()` by a run that finds the campaign no longer monitored, the dispatcher's daily sweep
    and `closeout.close` -- which also end every episode, so a campaign monitored again starts
    fresh. Commits (each resolve does, the public API's rule)."""
    prefix, keep = _alert_prefix(campaign), set(keep)
    if not keep:
        _patch_runtime(conn, org, brand, campaign, {"alert_since": {}})
    for row in interrupts.list_open(conn, org_id=org, brand_id=brand, category=ALERT_CATEGORY,
                                    archive_stale=False):
        if row["dedupe_key"].startswith(prefix) and row["dedupe_key"] not in keep:
            interrupts.resolve(conn, row["id"], actor="system", org_id=org)
    conn.commit()


def _health(conn, org, brand, campaign, now):
    value = changes.campaign(conn, org, brand, campaign)  # an unknown campaign raises
    today = settings.today_for_org(conn, org_id=org)
    budget = month_budget.view(conn, org, brand, today.strftime("%Y-%m"))
    health = []

    def add(code, message, severity="warning"):
        health.append({"code": code, "message": message, "severity": severity,
                       "observed_at": now.isoformat()})

    if budget["available"] is None or budget["uncertainties"]:
        add("budget_unknown", "本月餘額仍不確定；先補齊來源，暫不核准新增花費。", "unknown")
    elif budget["available"] < 0:
        add("budget_exceeded", "依目前整月花費與持續投放預估，已超出月總額。請檢視降低風險操作。")
    # F32-I01, F49 Contract L: the derived transitions (an internal live campaign past its end
    # date -> `ended`, an imported one following its root) are written by the one lifecycle
    # writer. `ended` is not `closed`: dates prompt a review, never a close-out. Contract N: the
    # passed end date is no alert here -- the decision queue's closeout row carries it.
    lifecycle.record(conn, org, brand, campaign)
    entities = conn.execute(
        "SELECT platform,native_status FROM ads_external_entity WHERE org_id=%s AND brand_id=%s "
        "AND campaign_id=%s AND end_date<%s",
        (org, brand, campaign, today),
    ).fetchall()
    # Still running on the platform past the object's own end date (its last delivery day).
    expired = sum(1 for entity in entities if lifecycle.ad_running(dict(entity)) is True)
    if expired:
        add("source_date_passed", "仍標示投放中的平台物件已超過讀回的排程期限，請核對狀態。")
    sources = _sources(conn, org, brand, campaign)
    if any(s["error"] or s["status"] == "unknown" for s in sources):
        add("source_incomplete", "來源資料未完整讀回；保留舊紀錄，請檢視連線與缺漏。", "unknown")
    # F49 Contract N: one row per (campaign, code, episode) -- an alert that persists stays one
    # row; one whose condition cleared is resolved below by the same tick and its episode ends.
    saved = ((value.get("context_json") or {}).get("runtime") or {}).get("alert_since")
    episodes = _episodes(saved, [alert["code"] for alert in health], today)
    _patch_runtime(conn, org, brand, campaign, {"alert_since": episodes})
    raised = [_alert_key(campaign, code, since) for code, since in episodes.items()]
    for key in raised:
        interrupts.enqueue(
            conn, org_id=org, brand_id=brand, category=ALERT_CATEGORY, dedupe_key=key,
            message="廣告追蹤有待確認項目，請檢視",
            action_url=f"/brands/{brand}/ads/campaigns/{campaign}?tab=performance",
        )
    resolve_alerts(conn, org, brand, campaign, keep=raised)
    ready = conn.execute(
        "SELECT id FROM ads_review_round WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND status='ready' ORDER BY created_at DESC LIMIT 100", (org, brand, campaign),
    ).fetchall()
    for review in ready:
        interrupts.enqueue(
            conn, org_id=org, brand_id=brand, category="ads_review_ready",
            dedupe_key="ads-review:" + review["id"], message="廣告檢討已備妥，請決定下一步",
            action_url=f"/brands/{brand}/ads/campaigns/{campaign}?tab=performance&review={review['id']}",
        )
    conn.commit()
    return health, {k: budget[k] for k in (
        "month", "currency", "amount", "known_spend", "available", "uncertainties", "can_increase"
    )}


def run_campaign(org_id, brand_id, campaign_id):
    """One monitoring tick. A step that fails is rolled back, logged and written into the health
    row as `partial` (the screen keeps showing it); the job then ends `Failed("runtime_error")`
    (F50 Contract J) instead of a quiet success."""
    with db.connection() as conn:
        db.set_tenant_scope(conn, org_id)
        lock = "ads-runtime:" + campaign_id
        got = conn.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS ok", (lock,)
        ).fetchone()
        assert got is not None
        if not got["ok"]:
            conn.commit()
            return
        conn.commit()
        try:
            now = db.now_utc()
            changes.campaign(conn, org_id, brand_id, campaign_id)
            if not lifecycle.is_monitored(conn, org_id, brand_id, campaign_id):
                # F49 Contract N: it left the monitored set between dispatch and run (closed, or
                # past the grace days) -- no read; its alerts no longer apply.
                resolve_alerts(conn, org_id, brand_id, campaign_id)
                conn.commit()
                return
            failures = []
            for step, function in (("sync", _sync_sources), ("readback", _readback)):
                try:
                    args = (now,) if step == "sync" else ()
                    function(conn, org_id, brand_id, campaign_id, *args)
                except Exception:
                    conn.rollback()
                    logger.exception("runtime %s failed for campaign %s", step, campaign_id)
                    failures.append("部分同步或核對未完成；下次重試仍保留原有物件與紀錄。")
            try:
                health, budget = _health(conn, org_id, brand_id, campaign_id, now)
            except Exception:
                conn.rollback()
                logger.exception("runtime health failed for campaign %s", campaign_id)
                health, budget = [], None
                failures.append("本次健康與月額資料未完整取得；餘額仍待確認，稍後重試。")
            for message in failures:
                health.append({"code": "partial", "severity": "unknown", "message": message,
                               "observed_at": now.isoformat()})
            _save(conn, org_id, brand_id, campaign_id, {
                "last_checked_at": now, "health": health, "budget": budget,
            })
            if failures:
                return background.Failed(RUNTIME_ERROR, "；".join(dict.fromkeys(failures)))
            return None
        finally:
            conn.rollback()
            conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (lock,))
            conn.commit()


def _sync_brand_accounts(conn, now):
    """Keep every brand's bound ad accounts read, imported campaigns or not. The month-budget
    guard needs the account's month-to-date spend (`monthly:` task, fresh within 24 h) before it
    approves any new spend; that task was only requested for imported campaigns or when someone
    opened the import list, so a brand that only builds new campaigns could never launch
    (drill 5). Same due rule as `_sync_sources`."""
    count = 0
    # ponytail: scans every brand with a campaign each tick (two small reads per account); order
    # by staleness and cap once brand counts make the minute tick slow.
    brands = conn.execute(
        "SELECT DISTINCT org_id,brand_id FROM ads_campaign ORDER BY org_id,brand_id"
    ).fetchall()
    for brand in brands:
        org, brand_id = brand["org_id"], brand["brand_id"]
        for channel in channels.CHANNELS:
            reader = channels.external_reader(channel["key"])
            if not reader:
                continue
            try:
                accounts = reader.accounts(conn, org, brand_id)
            except Exception:
                # No account id to record a backoff on: the failure is logged, and the other
                # brands and channels still run.
                conn.rollback()
                logger.exception("reading the bound %s accounts of brand %s failed",
                                 channel["key"], brand_id)
                continue
            for account in accounts:
                job = conn.execute(
                    "SELECT status,updated_at FROM ads_external_sync_job WHERE org_id=%s "
                    "AND brand_id=%s AND platform=%s AND source_account=%s",
                    (org, brand_id, channel["key"], account["account_id"]),
                ).fetchone()
                if job and (job["status"] in {"pending", "running"}
                            or not _due(job["updated_at"], now, SYNC_SECONDS)):
                    continue
                try:
                    external_sync.request_sync(conn, org, brand_id, channel["key"],
                                               account["account_id"])
                    count += 1
                except Exception as exc:
                    # F50 Contract J: an unreadable account is recorded on its own job (Contract
                    # O names the reason, so the month budget's 「餘額不確定」 has one, and the
                    # stamped attempt backs the next tick off).
                    conn.rollback()
                    logger.warning("requesting the %s account %s of brand %s failed: %s",
                                   channel["key"], account["account_id"], brand_id, exc)
                    external_sync.record_request_failure(
                        conn, org, brand_id, channel["key"], account["account_id"],
                        exc.code if isinstance(exc, SourceReadError) else None,
                    )
    return count


_last_sweep_day = None


def _sweep_unmonitored_alerts(conn, now, by_brand):
    """Once a day (per worker process): a campaign that left the monitored set without a run
    noticing (past the grace days; closed ones resolve at closeout) is never ticked again, so its
    open runtime alerts are resolved here. `by_brand` = `{(org, brand): monitored ids}`. Returns
    how many campaigns were swept."""
    global _last_sweep_day
    if _last_sweep_day == now.date():
        return 0
    _last_sweep_day = now.date()
    swept = 0
    for (org, brand), monitored in by_brand.items():
        stale = set()
        for row in interrupts.list_open(conn, org_id=org, brand_id=brand,
                                        category=ALERT_CATEGORY, archive_stale=False):
            parts = row["dedupe_key"].split(":")
            if len(parts) > 2 and parts[0] == "ads-runtime" and parts[1] not in monitored:
                stale.add(parts[1])
        for campaign in sorted(stale):
            resolve_alerts(conn, org, brand, campaign)
            swept += 1
    return swept


def dispatch(timestamp, *, limit=100):
    from app.ads import review_jobs, review_monitor

    now = datetime.fromtimestamp(timestamp, UTC)
    limit = min(max(int(limit), 1), 100)
    with db.connection() as conn:
        recovered = review_jobs.recover(conn, timestamp, limit=limit)
        monitors = review_monitor.dispatch_due(conn, timestamp, limit=limit)
        accounts_enqueued = _sync_brand_accounts(conn, now)
        # F49 Contract N: only campaigns the lifecycle still monitors (live, or ended within the
        # grace days). Filtered before the LIMIT: a closed campaign's old `last_checked_at` would
        # otherwise sort first forever and starve the live ones.
        by_brand = {
            (brand["org_id"], brand["brand_id"]): lifecycle.monitored_ids(
                conn, brand["org_id"], brand["brand_id"]
            )
            for brand in lifecycle.brands(conn, lifecycle.NOT_CLOSED)
        }
        monitored = sorted(set().union(*by_brand.values()))
        _sweep_unmonitored_alerts(conn, now, by_brand)
        rows = conn.execute(
            "SELECT c.id,c.org_id,c.brand_id,c.context_json FROM ads_campaign c WHERE "
            "c.id = ANY(%s) AND ("
            "EXISTS(SELECT 1 FROM ads_external_entity e WHERE e.campaign_id=c.id) "
            "OR EXISTS(SELECT 1 FROM ads_review_monitor m WHERE m.campaign_id=c.id)) "
            "ORDER BY COALESCE(c.context_json->'runtime'->>'last_checked_at',''),c.id LIMIT %s",
            (monitored, limit + 1),
        ).fetchall()
    enqueued = 0
    for row in rows[:limit]:
        state = (row["context_json"] or {}).get("runtime") or {}
        if _due(state.get("last_checked_at"), now, INTERVAL_SECONDS):
            lock = "ads-runtime:" + row["id"]
            if not background.is_active(lock):
                enqueued += background.enqueue(
                    TASK, org_id=row["org_id"], lock=lock,
                    brand_id=row["brand_id"], campaign_id=row["id"],
                )
    return {**recovered, "reviews_enqueued": recovered["reviews_enqueued"]
            + monitors["reviews_enqueued"], "monitors_checked": monitors["monitors_checked"],
            "sync_enqueued": enqueued + accounts_enqueued, "health_checked": 0,
            "has_more": len(rows) > limit or recovered["has_more"] or monitors["has_more"]}


def bootstrap(conn, timestamp, *, limit=100):
    from app.ads import review_jobs

    limit = min(max(int(limit), 1), 100)
    # Startup is worker-wide; count tenant-scoped backlogs without exposing review data.
    backlogs = conn.execute(
        "SELECT org_id,COUNT(*) AS n FROM ads_review_round WHERE decision IS NULL "
        "AND status IN ('queued','running','unknown') GROUP BY org_id"
    ).fetchall()
    count = sum(row["n"] for row in backlogs)
    recovered = dict(reviews_recovered=0, reviews_unknown=0, reviews_failed=0,
                     reviews_enqueued=0, has_more=False)
    # Scan the captured backlog once, including unchanged unknown rows ahead of
    # interrupted running rows. A zero business-transition count is not a dead scan.
    for _ in range(min(10, max(1, (count + limit - 1) // limit))):
        batch = review_jobs.recover(conn, timestamp, limit=limit, bootstrap=True)
        for key in ("reviews_recovered", "reviews_unknown", "reviews_failed", "reviews_enqueued"):
            recovered[key] += batch[key]
        recovered["has_more"] = batch["has_more"]
    if count > 10 * limit:
        print("檢討恢復超過本次啟動批次上限；未判定的中斷記錄保留，需再次啟動續接。")
    # Recovery time is an observation, not proof of when the preceding outage began.
    conn.execute(
        "UPDATE ads_campaign SET context_json=jsonb_set(context_json,'{runtime}',"
        "COALESCE(context_json->'runtime','{}'::jsonb) || %s::jsonb) WHERE "
        "EXISTS(SELECT 1 FROM ads_external_entity e WHERE e.campaign_id=ads_campaign.id "
        "AND e.org_id=ads_campaign.org_id AND e.brand_id=ads_campaign.brand_id)",
        (db.jsonb({"last_bootstrap_at": datetime.fromtimestamp(timestamp, UTC)}),),
    )
    conn.commit()
    result = dispatch(timestamp, limit=limit)
    for key in ("reviews_recovered", "reviews_unknown", "reviews_failed", "reviews_enqueued"):
        result[key] += recovered[key]
    result["has_more"] = result["has_more"] or recovered["has_more"]
    return result
