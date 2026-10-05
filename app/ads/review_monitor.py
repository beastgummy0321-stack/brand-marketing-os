"""Per-ad opt-in review scheduling. Waiting windows are durable, not rolling polling prompts."""

from datetime import UTC, datetime, timedelta

from app.ads import asset_binding_repository as bindings
from app.ads import change_control_data as changes
from app.ads import coverage, external_sync, review_evidence, review_monitor_source, review_rounds
from app.ads.adapters.external import SourceReadError
from app.core import db

# F50 Contract I (decision 11): the observation window and the review cadence, in days -- served
# to the screens as `GET …/rules` `limits` and quoted by the refusals below.
DAYS_RANGE = (1, 31)
DEFAULT_CADENCE_DAYS = 7
_DAY_DIGITS = "零一二三四五六七八九"


def _days_text(n: int) -> str:
    """A day count in Chinese numerals (1-99), as the refusal sentence has always read it."""
    tens, ones = divmod(n, 10)
    if tens == 0:
        return _DAY_DIGITS[ones]
    return (_DAY_DIGITS[tens] if tens > 1 else "") + "十" + (_DAY_DIGITS[ones] if ones else "")


def _now(timestamp=None):
    return db.now_utc() if timestamp is None else datetime.fromtimestamp(timestamp, UTC)


def _row(conn, org, brand, campaign, entity):
    return conn.execute(
        "SELECT m.*,e.name AS entity_name FROM ads_review_monitor m "
        "JOIN ads_external_entity e ON e.id=m.entity_id "
        "WHERE m.org_id=%s AND m.brand_id=%s AND m.campaign_id=%s AND m.entity_id=%s",
        (org, brand, campaign, entity),
    ).fetchone()


def _view(conn, row):
    if row is None:
        return None
    state, reason = row["state"], row["reason"]
    if not row["enabled"]:
        state = "paused"
    elif row["review_id"]:
        review = conn.execute(
            "SELECT status,error FROM ads_review_round WHERE org_id=%s AND brand_id=%s "
            "AND campaign_id=%s AND id=%s",
            (row["org_id"], row["brand_id"], row["campaign_id"], row["review_id"]),
        ).fetchone()
        if review and review["status"] in {"queued", "running", "ready"}:
            state = review["status"]
        elif review and review["status"] in {"failed", "unknown"}:
            state, reason = "needs_attention", review["error"]
    return {
        **{
            k: row[k]
            for k in (
                "id",
                "entity_id",
                "entity_name",
                "revision",
                "enabled",
                "window_days",
                "cadence_days",
                "next_check_at",
                "review_id",
                "last_checked_at",
                "reason",
                "observe_after",
                "source_handoff_id",
            )
        },
        "state": state,
        "reason": reason,
        "window": (
            {
                "start": row["window_start"],
                "end": row["window_end"],
                "previous_id": row["previous_id"],
            }
            if row["window_start"]
            else None
        ),
    }


def get(conn, org, brand, campaign, entity):
    bindings.entity(conn, org, brand, campaign, entity)
    return _view(conn, _row(conn, org, brand, campaign, entity))


def workspace(conn, org, brand, campaign):
    changes.campaign(conn, org, brand, campaign)
    rows = conn.execute(
        "SELECT m.*,e.name AS entity_name FROM ads_review_monitor m "
        "JOIN ads_external_entity e ON e.id=m.entity_id "
        "WHERE m.org_id=%s AND m.brand_id=%s AND m.campaign_id=%s "
        "ORDER BY m.created_at,m.id LIMIT 501",
        (org, brand, campaign),
    ).fetchall()
    return {"monitors": [_view(conn, row) for row in rows[:500]], "truncated": len(rows) > 500}


def put(conn, org, brand, campaign, entity, payload):
    target = bindings.entity(conn, org, brand, campaign, entity)
    if target["native_kind"] != "ad":
        raise ValueError("持續檢討只能設定單則平台廣告。")
    if changes.campaign(conn, org, brand, campaign)["status"] == "closed":
        raise ValueError("已結案活動不能啟用持續檢討。")
    low, high = DAYS_RANGE
    if any(not low <= payload[k] <= high for k in ("window_days", "cadence_days")):
        raise ValueError(f"觀察窗與重看間隔請選{_days_text(low)}至{_days_text(high)}日。")
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("ads-monitor-config:" + entity,)
    )
    row = _row(conn, org, brand, campaign, entity)
    if (row["revision"] if row else 0) != payload["expected_revision"]:
        raise ValueError("持續檢討設定已更新，請重新載入再修改。")
    if row and payload.get("reset_window") and row["review_id"]:
        active = conn.execute(
            "SELECT status FROM ads_review_round WHERE id=%s", (row["review_id"],)
        ).fetchone()
        if active and active["status"] in {"queued", "running", "ready"}:
            raise ValueError("本回仍在處理或等候人工決定，請先處理本回再重設觀察窗。")
    if not row:
        conn.execute(
            "INSERT INTO ads_review_monitor(id,org_id,brand_id,campaign_id,entity_id,enabled,"
            "window_days,cadence_days,state,next_check_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                db.new_id("arm"),
                org,
                brand,
                campaign,
                entity,
                payload["enabled"],
                payload["window_days"],
                payload["cadence_days"],
                "scheduled" if payload["enabled"] else "paused",
                _now(),
            ),
        )
    else:
        conn.execute(
            "UPDATE ads_review_monitor SET enabled=%s,window_days=%s,cadence_days=%s,"
            "revision=revision+1,state=%s,next_check_at=%s,reason=NULL,updated_at=now() "
            "WHERE id=%s",
            (
                payload["enabled"],
                payload["window_days"],
                payload["cadence_days"],
                "scheduled" if payload["enabled"] else "paused",
                _now(),
                row["id"],
            ),
        )
        if payload.get("reset_window"):
            conn.execute(
                "UPDATE ads_review_monitor SET window_start=NULL,window_end=NULL,review_id=NULL,"
                "last_input_hash=NULL WHERE id=%s",
                (row["id"],),
            )
    conn.commit()
    return get(conn, org, brand, campaign, entity)


def track_manual(conn, review, *, commit=True):
    """Only an explicit review POST opts an ad in; preserve existing pause/preferences."""
    conn.execute(
        "INSERT INTO ads_review_monitor(id,org_id,brand_id,campaign_id,entity_id,window_start,"
        "window_end,previous_id,review_id,state,next_check_at) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT(org_id,brand_id,campaign_id,entity_id) DO UPDATE SET "
        "window_start=EXCLUDED.window_start,window_end=EXCLUDED.window_end,"
        "previous_id=EXCLUDED.previous_id,review_id=EXCLUDED.review_id,state=EXCLUDED.state,"
        "next_check_at=EXCLUDED.next_check_at,last_input_hash=NULL,updated_at=now()",
        (
            db.new_id("arm"),
            review["org_id"],
            review["brand_id"],
            review["campaign_id"],
            review["entity_id"],
            review["window_start"],
            review["window_end"],
            review["previous_id"],
            review["id"],
            _state(review),
            _now(),
        ),
    )
    if review.get("decision"):
        on_decision(conn, review, commit=False)
    if commit:
        conn.commit()
    return get(
        conn, review["org_id"], review["brand_id"], review["campaign_id"], review["entity_id"]
    )


def _state(review):
    return (
        review["status"]
        if review["status"] in {"queued", "running", "ready", "waiting"}
        else "needs_attention"
        if review["status"] in {"failed", "unknown"}
        else "scheduled"
    )


def on_decision(conn, review, *, commit=True):
    row = _row(
        conn, review["org_id"], review["brand_id"], review["campaign_id"], review["entity_id"]
    )
    if not row or row["review_id"] != review["id"]:
        return
    next_at = review["revisit_at"] or _now() + timedelta(days=row["cadence_days"])
    advance = bool(review["result_json"]) and review["decision"] in {"completed", "deferred"}
    conn.execute(
        "UPDATE ads_review_monitor SET state=%s,next_check_at=%s,reason=%s,"
        "window_start=%s,window_end=%s,previous_id=%s,review_id=%s,updated_at=now() WHERE id=%s",
        (
            "scheduled" if row["enabled"] else "paused",
            next_at,
            review["reason"],
            None if advance else row["window_start"],
            None if advance else row["window_end"],
            review["id"] if advance else row["previous_id"],
            None if advance else row["review_id"],
            row["id"],
        ),
    )
    if commit:
        conn.commit()


def _source_account(conn, row):
    """The bound account of the monitored ad, `None` when it cannot be read."""
    entity = bindings.entity(
        conn, row["org_id"], row["brand_id"], row["campaign_id"], row["entity_id"]
    )
    try:
        _, account = external_sync.account_reader(
            conn, row["org_id"], row["brand_id"], entity["platform"], entity["source_account"]
        )
    except SourceReadError:
        return None
    return account


def _checkpoint(conn, row, now, state, reason=None, *, days=False):
    conn.execute(
        "UPDATE ads_review_monitor SET state=%s,reason=%s,last_checked_at=%s,next_check_at=%s,"
        "updated_at=now() WHERE id=%s",
        (
            state,
            reason,
            now,
            now + timedelta(days=1) if days else now + timedelta(hours=6),
            row["id"],
        ),
    )
    conn.commit()


def _discover(conn, now, limit):
    rows = conn.execute(
        "SELECT h.* FROM ads_handoff_item h JOIN ads_change_set c ON c.id=h.change_set_id "
        "WHERE h.entity_id IS NOT NULL AND h.planned_kind='ad' AND c.status='approved' "
        "AND c.plan_json->>'review_id' IS NOT NULL AND NOT EXISTS "
        "(SELECT 1 FROM ads_review_monitor m WHERE m.entity_id=h.entity_id) "
        "ORDER BY h.review_monitor_checked_at NULLS FIRST,h.created_at,h.id LIMIT %s",
        (limit,),
    ).fetchall()
    count = 0
    for row in rows:
        conn.execute(
            "UPDATE ads_handoff_item SET review_monitor_checked_at=%s WHERE id=%s", (now, row["id"])
        )
        source = review_monitor_source.source_review(
            conn, row["org_id"], row["brand_id"], row["campaign_id"], row["entity_id"]
        )
        if not source:
            continue
        original = _row(
            conn, row["org_id"], row["brand_id"], row["campaign_id"], source["source_entity_id"]
        )
        if not original:
            continue
        observed = source["readback"]["first_observed_at"] or now
        result = conn.execute(
            "INSERT INTO ads_review_monitor(id,org_id,brand_id,campaign_id,entity_id,enabled,"
            "window_days,cadence_days,state,next_check_at,observe_after,source_handoff_id,reason) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT(org_id,brand_id,campaign_id,entity_id) DO NOTHING",
            (
                db.new_id("arm"),
                row["org_id"],
                row["brand_id"],
                row["campaign_id"],
                row["entity_id"],
                original["enabled"],
                original["window_days"],
                original["cadence_days"],
                "waiting" if original["enabled"] else "paused",
                now,
                observed,
                row["id"],
                "承接原廣告的檢討設定；等待新廣告有完整觀察窗，素材對應仍可能未知。",
            ),
        )
        count += result.rowcount
    conn.commit()
    return count


def _dispatch_one(conn, row, now):
    if (
        changes.campaign(conn, row["org_id"], row["brand_id"], row["campaign_id"])["status"]
        == "closed"
    ):
        _checkpoint(conn, row, now, "needs_attention", "活動已結案，請人工確認。", days=True)
        return 0
    if row["review_id"]:
        old = review_rounds.get(
            conn, row["org_id"], row["brand_id"], row["campaign_id"], row["review_id"]
        )
        if old["status"] in {"queued", "running", "ready", "failed", "unknown"}:
            _checkpoint(conn, row, now, _state(old), old.get("error"))
            return 0
    account = _source_account(conn, row)
    zone = coverage.account_zone(account)
    # F50 Contract K: the one "complete day" (the ad account's yesterday, fail closed).
    last = coverage.account_last_complete_day(conn, row["org_id"], account)
    if not row["window_start"]:
        if zone is None and row["observe_after"]:
            _checkpoint(conn, row, now, "waiting", "來源帳戶時區未知；請先核對來源，暫不呼叫模型。")
            return 0
        end = last
        start = end - timedelta(days=row["window_days"] - 1)
        if row["observe_after"] and not row["previous_id"]:
            start = row["observe_after"].astimezone(zone).date() + timedelta(days=1)
            end = start + timedelta(days=row["window_days"] - 1)
        if row["previous_id"]:
            prior = review_rounds.get(
                conn, row["org_id"], row["brand_id"], row["campaign_id"], row["previous_id"]
            )
            if end <= prior["window_end"]:
                _checkpoint(conn, row, now, "waiting", "等待前回之後完整的新觀察日期。")
                return 0
        conn.execute(
            "UPDATE ads_review_monitor SET window_start=%s,window_end=%s WHERE id=%s",
            (start, end, row["id"]),
        )
        conn.commit()
        row = {**row, "window_start": start, "window_end": end}
    if row["window_end"] > last:
        _checkpoint(conn, row, now, "waiting", "等待新廣告完整觀察窗結束，暫不呼叫模型。")
        return 0
    evidence = review_evidence.snapshot(
        conn,
        row["org_id"],
        row["brand_id"],
        row["campaign_id"],
        row["entity_id"],
        row["window_start"],
        row["window_end"],
        row["previous_id"],
        automatic=True,
    )
    digest = review_rounds.evidence_digest(evidence)
    if digest == row["last_input_hash"]:
        _checkpoint(conn, row, now, "waiting", "固定觀察窗的證據尚未改變；不重複呼叫模型。")
        return 0
    review = review_rounds.submit(
        conn,
        row["org_id"],
        row["brand_id"],
        row["campaign_id"],
        row["entity_id"],
        row["window_start"],
        row["window_end"],
        row["previous_id"],
        "monitor",
        evidence,
    )
    conn.execute(
        "UPDATE ads_review_monitor SET review_id=%s,last_input_hash=%s WHERE id=%s",
        (review["id"], digest, row["id"]),
    )
    _checkpoint(conn, row, now, _state(review), "；".join(evidence["waiting_reasons"]) or None)
    return int(review["status"] == "queued")


def dispatch_due(conn, timestamp, *, limit=100):
    now, limit = _now(timestamp), min(max(limit, 1), 100)
    discovered = _discover(conn, now, limit)
    rows = conn.execute(
        "SELECT * FROM ads_review_monitor WHERE enabled AND next_check_at<=%s "
        "AND state<>'needs_attention' ORDER BY next_check_at,id LIMIT %s",
        (now, limit + 1),
    ).fetchall()
    result = dict(
        monitors_checked=0,
        reviews_enqueued=0,
        monitors_discovered=discovered,
        has_more=len(rows) > limit,
    )
    for value in rows[:limit]:
        row = dict(value)
        key = "ads-monitor-config:" + row["entity_id"]
        locked = conn.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS ok", (key,)
        ).fetchone()["ok"]
        if not locked:
            continue
        try:
            fresh = _row(conn, row["org_id"], row["brand_id"], row["campaign_id"], row["entity_id"])
            if not fresh["enabled"] or fresh["next_check_at"] > now:
                continue
            result["monitors_checked"] += 1
            result["reviews_enqueued"] += _dispatch_one(conn, dict(fresh), now)
        except (ValueError, SourceReadError) as exc:
            conn.rollback()
            _checkpoint(conn, row, now, "needs_attention", str(exc), days=True)
        finally:
            conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (key,))
            conn.commit()
    return result


def required_windows(conn, org, brand, campaign):
    """Source collection includes paused monitors and the complete comparison period."""
    rows = conn.execute(
        "SELECT m.*,e.platform,e.source_account FROM ads_review_monitor m "
        "JOIN ads_external_entity e ON e.id=m.entity_id WHERE m.org_id=%s "
        "AND m.brand_id=%s AND m.campaign_id=%s ORDER BY m.id LIMIT 501",
        (org, brand, campaign),
    ).fetchall()
    if len(rows) > 500:
        raise ValueError("活動監測數量超過單次來源補回上限，請縮小活動範圍。")
    last = coverage.last_complete_day(conn, org, brand, campaign)
    result = []
    for row in rows:
        end = min(row["window_end"] or last, last)
        start = row["window_start"] or end - timedelta(days=row["window_days"] - 1)
        days = (
            (row["window_end"] - row["window_start"]).days + 1
            if row["window_start"]
            else row["window_days"]
        )
        start -= timedelta(days=days)
        if start <= end:
            result.append(
                {
                    "entity_id": row["entity_id"],
                    "platform": row["platform"],
                    "source_account": row["source_account"],
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "reason": "本期與等長前期；暫停判讀仍補來源",
                }
            )
    return result
