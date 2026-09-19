"""Durable, bounded local monitoring. All platform operations are existing read interfaces."""

from datetime import UTC, date, datetime, timedelta

from app import background
from app.ads import change_control_data as changes
from app.ads import external_sync, month_budget
from app.core import db, interrupts, settings

TASK = "background.ads_runtime_campaign"
INTERVAL_SECONDS = 900
SYNC_SECONDS = 21600


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
    conn.execute(
        "UPDATE ads_campaign SET context_json=jsonb_set(context_json,'{runtime}',"
        "COALESCE(context_json->'runtime','{}'::jsonb) || %s::jsonb) "
        "WHERE org_id=%s AND brand_id=%s AND id=%s",
        (db.jsonb(patch), org, brand, campaign),
    )
    conn.commit()


def _sources(conn, org, brand, campaign):
    rows = conn.execute(
        "SELECT DISTINCT e.platform,e.source_account,j.status,j.last_attempt_at,j.last_success_at,"
        "j.tasks,j.error FROM ads_external_entity e LEFT JOIN ads_external_sync_job j "
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
        failed = bool(row["error"]) or any(t.get("status") == "failed" for t in tasks)
        result.append({
            **{k: row[k] for k in (
                "platform", "source_account", "last_attempt_at", "last_success_at"
            )},
            "status": row["status"] or "unknown",
            "coverage": {"start": latest["start"], "end": latest["end"]} if latest else None,
            "error": "部分來源未能讀取；請檢視連線與同步缺漏。" if failed else None,
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
        except Exception:
            conn.rollback()
            # Even a disconnected account needs a persisted backoff. A failure before
            # request_sync's insert must not cause a new source attempt every minute.
            conn.execute(
                "INSERT INTO ads_external_sync_job(id,org_id,brand_id,platform,source_account,"
                "status,error,last_attempt_at) VALUES(%s,%s,%s,%s,%s,'partial',%s,%s) "
                "ON CONFLICT(org_id,brand_id,platform,source_account) DO UPDATE SET "
                "last_attempt_at=EXCLUDED.last_attempt_at,updated_at=now(),error=EXCLUDED.error",
                (db.new_id("aes"), org, brand, source["platform"], source["source_account"],
                 "來源連線或排程未完成；已保留原進度，稍後重試。", now),
            )
            conn.commit()
    return count


def _readback(conn, org, brand, campaign):
    from app.ads import change_control_verify, handoff_check

    # IDs must already be known; discovery never guesses the object a human changed.
    failed = 0
    items = conn.execute(
        "SELECT h.* FROM ads_handoff_item h JOIN ads_change_set c ON c.id=h.change_set_id "
        "AND c.org_id=h.org_id AND c.brand_id=h.brand_id WHERE h.org_id=%s AND h.brand_id=%s "
        "AND h.campaign_id=%s AND c.status='approved' AND h.entity_id IS NOT NULL "
        "AND h.status<>'stale' ORDER BY "
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
        "AND a.verification_state<>'stale' AND NOT EXISTS "
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


def _health(conn, org, brand, campaign, now):
    value = changes.campaign(conn, org, brand, campaign)
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
    if value.get("end_date") and value["end_date"] <= today:
        add("plan_date_passed", "原計畫日期已到。活動與平台投放仍保留，請確認期限與下一步。")
    expired = conn.execute(
        "SELECT COUNT(*) AS n FROM ads_external_entity WHERE org_id=%s AND brand_id=%s "
        "AND campaign_id=%s AND end_date<=%s AND native_status='ACTIVE'",
        (org, brand, campaign, today),
    ).fetchone()["n"]
    if expired:
        add("source_date_passed", "仍標示投放中的平台物件已超過讀回的排程期限，請核對狀態。")
    sources = _sources(conn, org, brand, campaign)
    if any(s["error"] or s["status"] == "unknown" for s in sources):
        add("source_incomplete", "來源資料未完整讀回；保留舊紀錄，請檢視連線與缺漏。", "unknown")
    for alert in health:
        interrupts.enqueue(
            conn, org_id=org, brand_id=brand, category="ads_runtime_attention",
            dedupe_key=f"ads-runtime:{campaign}:{today}:{alert['code']}",
            message="廣告追蹤有待確認項目，請檢視",
            action_url=f"/brands/{brand}/ads/campaigns/{campaign}?tab=performance",
        )
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
            failures = []
            for function in (_sync_sources, _readback):
                try:
                    args = (now,) if function is _sync_sources else ()
                    function(conn, org_id, brand_id, campaign_id, *args)
                except Exception:
                    conn.rollback()
                    failures.append("部分同步或核對未完成；下次重試仍保留原有物件與紀錄。")
            try:
                health, budget = _health(conn, org_id, brand_id, campaign_id, now)
            except Exception:
                conn.rollback()
                health, budget = [], None
                failures.append("本次健康與月額資料未完整取得；餘額仍待確認，稍後重試。")
            for message in failures:
                health.append({"code": "partial", "severity": "unknown", "message": message,
                               "observed_at": now.isoformat()})
            _save(conn, org_id, brand_id, campaign_id, {
                "last_checked_at": now, "health": health, "budget": budget,
            })
        finally:
            conn.rollback()
            conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (lock,))
            conn.commit()


def dispatch(timestamp, *, limit=100):
    from app.ads import review_jobs, review_monitor

    now = datetime.fromtimestamp(timestamp, UTC)
    limit = min(max(int(limit), 1), 100)
    with db.connection() as conn:
        recovered = review_jobs.recover(conn, timestamp, limit=limit)
        monitors = review_monitor.dispatch_due(conn, timestamp, limit=limit)
        rows = conn.execute(
            "SELECT c.id,c.org_id,c.brand_id,c.context_json FROM ads_campaign c WHERE "
            "EXISTS(SELECT 1 FROM ads_external_entity e WHERE e.campaign_id=c.id) "
            "OR EXISTS(SELECT 1 FROM ads_review_monitor m WHERE m.campaign_id=c.id) "
            "ORDER BY COALESCE(c.context_json->'runtime'->>'last_checked_at',''),c.id LIMIT %s",
            (limit + 1,),
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
            "sync_enqueued": enqueued, "health_checked": 0,
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
