"""Durable review requests and human dispositions, scoped to a single native ad."""

import math
from copy import deepcopy
from datetime import datetime

from app.ads import asset_binding_repository as bindings
from app.ads import asset_suggestion_policy as policy
from app.ads import change_control_data as changes
from app.ads import review_evidence
from app.core import db, interrupts, settings
from app.llm import providers

TASK_TYPE = "ads_ad_review"
PROVIDER = providers.AnthropicProvider()
PROMPT = db.APP_DIR / "departments" / "ads" / "review_round.md"


def evidence_digest(evidence):
    """Ignore only import refresh metadata; retain all decision-bearing dates and evidence."""
    content = deepcopy(evidence)
    for period in ("current", "previous"):
        summary = content.get("commerce", {}).get(period, {}).get("order_summary", {})
        summary.pop("latest_import_at", None)
    return changes.digest(content)


def model_input(evidence):
    """What the model reads: `retry_of` only separates a re-run's digest, it is not evidence."""
    return policy.encode({k: v for k, v in evidence.items() if k != "retry_of"})


def get(conn, org, brand, campaign, review_id):
    changes.campaign(conn, org, brand, campaign)
    row = conn.execute(
        "SELECT * FROM ads_review_round WHERE org_id=%s AND brand_id=%s "
        "AND campaign_id=%s AND id=%s",
        (org, brand, campaign, review_id),
    ).fetchone()
    if row is None:
        raise ValueError("找不到此品牌活動的檢討。")
    result = dict(row)
    # Contract B: `copy_editable` is computed at READ time, never stored in the immutable
    # `evidence_json` snapshot -- a later re-sync of the ad's creative must change the answer
    # without touching the evidence hash or anything already approved.
    try:
        target = bindings.entity(conn, org, brand, campaign, result["entity_id"])
        editable = changes.copy_editable(target.get("creative") or {})
    except ValueError:
        editable = {"ok": False, "mode": None, "reason": None}
    result["evidence_json"] = {
        **result["evidence_json"],
        "conditions": {
            **result["evidence_json"].get("conditions", {}),
            "copy_editable": editable,
        },
    }
    result["usage_notice"] = (
        policy.CODEX_NOTICE
        if result["evidence_json"].get("provider") == "codex_cli"
        else ("單回一次呼叫、最多 US$0.50 保守預留；未與所有其他功能共享並行預留鎖。")
    )
    result["retry_notice"] = (
        "相同證據重用本回；失敗或狀態不明不自動重送。可補資料、延後或標無法判讀。"
    )
    return result


def workspace(conn, org, brand, campaign):
    changes.campaign(conn, org, brand, campaign)
    targets = conn.execute(
        "SELECT * FROM ads_external_entity WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND native_kind='ad' ORDER BY name,id LIMIT 501",
        (org, brand, campaign),
    ).fetchall()
    rows = conn.execute(
        "SELECT id FROM ads_review_round WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "ORDER BY created_at DESC,id DESC LIMIT 101",
        (org, brand, campaign),
    ).fetchall()
    return {
        "reviews": [get(conn, org, brand, campaign, r["id"]) for r in rows[:100]],
        "targets": [dict(r) for r in targets[:500]],
        "targets_truncated": len(targets) > 500,
        "reviews_truncated": len(rows) > 100,
    }


def _reserve(conn, org, amount):
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("ads-review-budget:" + org,)
    )
    since = db.now_utc().strftime("%Y-%m-01T00:00:00")
    extra = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN reservation_state='held' THEN reserved_amount ELSE 0 END),0)"
        "+COALESCE(SUM(CASE WHEN created_at>=%s THEN failed_cost ELSE 0 END),0) AS n "
        "FROM ads_review_round WHERE org_id=%s",
        (since, org),
    ).fetchone()["n"]
    limit = settings.get_ai_monthly_cost_limit(conn, org_id=org)
    spent = settings.org_ai_spent_this_month(conn, org_id=org, since=since)
    if amount and (not math.isfinite(limit) or spent + float(extra) + amount > limit):
        raise ValueError("組織剩餘 AI 額度不足，本回未送出。")


def request(
    conn,
    org,
    brand,
    campaign,
    entity_id,
    start,
    end,
    previous_id=None,
    actor="human",
    *,
    automatic=False,
    manual_monitor=False,
):
    evidence = review_evidence.snapshot(
        conn, org, brand, campaign, entity_id, start, end, previous_id, automatic=automatic
    )
    return submit(
        conn,
        org,
        brand,
        campaign,
        entity_id,
        start,
        end,
        previous_id,
        actor,
        evidence,
        manual_monitor=manual_monitor,
    )


def request_manual(
    conn, org, brand, campaign, entity_id, start, end, previous_id=None, actor="human"
):
    """The explicit HTTP command opts in and commits its monitor linkage before queue dispatch."""
    return request(
        conn, org, brand, campaign, entity_id, start, end, previous_id, actor, manual_monitor=True
    )


def submit(
    conn,
    org,
    brand,
    campaign,
    entity_id,
    start,
    end,
    previous_id,
    actor,
    evidence,
    *,
    manual_monitor=False,
):
    """Persist an already compiled ads-owned snapshot; no repeated compilation in monitor ticks."""
    system = PROMPT.read_text(encoding="utf-8")
    provider = providers.select_provider(PROVIDER, task_type=TASK_TYPE)
    model = providers.resolve_model(task_type=TASK_TYPE, conn=conn, brand_id=brand)
    evidence.update(provider=provider.name, model=model, template_hash=changes.digest(system))
    digest = evidence_digest(evidence)
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
        (f"ads-review:{org}:{brand}:{campaign}:{entity_id}",),
    )
    old = conn.execute(
        "SELECT id FROM ads_review_round WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND evidence_hash=%s",
        (org, brand, campaign, digest),
    ).fetchone()
    if old:
        result = get(conn, org, brand, campaign, old["id"])
        # A decided round is history: pointing the monitor back at it (a stale-screen
        # re-request or retry) would reopen its window and replay `on_decision`.
        if manual_monitor and result["decision"] is None:
            from app.ads import review_monitor

            review_monitor.track_manual(conn, result, commit=False)
        conn.commit()
        return result
    waiting = bool(evidence["waiting_reasons"])
    if not waiting and len(system) + len(model_input(evidence)) + 32 > policy.INPUT_CHARS:
        raise ValueError("完整證據超過 12,000 字元，未截斷或送出；請縮短期間或整理品牌背景。")
    amount = 0 if waiting else policy.ceiling(provider.name, model)
    if not waiting:
        _reserve(conn, org, amount)
    review_id = db.new_id("arv")
    conn.execute(
        "INSERT INTO ads_review_round(id,org_id,brand_id,campaign_id,entity_id,previous_id,"
        "window_start,window_end,evidence_json,evidence_hash,status,reserved_amount,"
        "reservation_state,created_by) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            review_id,
            org,
            brand,
            campaign,
            entity_id,
            previous_id,
            start,
            end,
            db.jsonb(evidence),
            digest,
            "waiting" if waiting else "queued",
            amount,
            "settled" if waiting else "held",
            actor,
        ),
    )
    if manual_monitor:
        from app.ads import review_monitor

        review_monitor.track_manual(conn, get(conn, org, brand, campaign, review_id), commit=False)
    conn.commit()
    if not waiting:
        from app.ads import review_jobs

        review_jobs.enqueue(org, brand, campaign, review_id)
    return get(conn, org, brand, campaign, review_id)


def retry(conn, org, brand, campaign, review_id, actor="human"):
    """Re-run an undecided failed or AI-rejected round on its own saved evidence (Contract A).

    `retry_of` gives the re-run its own digest (the old one is UNIQUE per campaign), so a repeat
    call dedupes to the same retry round; the round reserves AI cost like any other."""
    # Same guard as `review_evidence.snapshot`: a closed campaign only shows its history.
    if changes.campaign(conn, org, brand, campaign)["status"] == "closed":
        raise ValueError("已結案活動只能查看歷史檢討。")
    old = get(conn, org, brand, campaign, review_id)
    # A superseded round passes so a stale screen's repeat dedupes to its retry round.
    superseded = _superseded(conn, org, brand, campaign, review_id)
    if not superseded and (old["decision"] is not None or not (
        old["status"] == "failed" or (old["result_json"] or {}).get("rejected")
    )):
        raise ValueError("只有尚未決定、失敗或 AI 說明被擋下的檢討可以再請 AI 看一次。")
    # Read the stored snapshot, not `get`'s view: `copy_editable` is a read-time field.
    evidence = conn.execute(
        "SELECT evidence_json FROM ads_review_round WHERE org_id=%s AND id=%s", (org, review_id)
    ).fetchone()["evidence_json"]
    result = submit(
        conn,
        org,
        brand,
        campaign,
        old["entity_id"],
        old["window_start"],
        old["window_end"],
        old["previous_id"],
        actor,
        {**deepcopy(evidence), "retry_of": review_id},
        manual_monitor=True,
    )
    # The retry round replaces this one: close it with an existing decision value (no new
    # state) so it stops counting as open, and end its ready notice.
    conn.execute(
        "UPDATE ads_review_round SET status='unjudgeable',decision='unjudgeable',reason=%s,"
        "updated_at=now() WHERE org_id=%s AND brand_id=%s AND campaign_id=%s AND id=%s "
        "AND decision IS NULL",
        ("已重新請 AI 看一次，改看新一回。", org, brand, campaign, review_id),
    )
    _resolve_ready_notice(conn, org, brand, review_id)
    conn.commit()
    return result


def _superseded(conn, org, brand, campaign, review_id):
    return conn.execute(
        "SELECT 1 FROM ads_review_round WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND evidence_json->>'retry_of'=%s LIMIT 1",
        (org, brand, campaign, review_id),
    ).fetchone() is not None


def _resolve_ready_notice(conn, org, brand, review_id):
    """End the 「廣告檢討已備妥」 notice `runtime` raised for this round (commits)."""
    for row in interrupts.list_open(
        conn, org_id=org, brand_id=brand, category="ads_review_ready", archive_stale=False
    ):
        if row["dedupe_key"] == "ads-review:" + review_id:
            interrupts.resolve(conn, row["id"], actor="system", org_id=org)


def decide(conn, org, brand, campaign, review_id, decision, reason, revisit_at=None):
    if decision not in {"completed", "deferred", "unjudgeable"}:
        raise ValueError("請選擇完成本回、延後或無法判讀。")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
        raise ValueError("請留下本回處理原因，最多兩千字。")
    revisit = None
    if revisit_at:
        try:
            revisit = datetime.fromisoformat(revisit_at)
            if revisit.tzinfo is None or revisit <= db.now_utc():
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError("請選未來的重看時間，並包含時區。") from None
    if decision == "deferred" and revisit is None:
        raise ValueError("延後檢討請留下重看時間。")
    get(conn, org, brand, campaign, review_id)
    if _superseded(conn, org, brand, campaign, review_id):
        raise ValueError("本回已重新請 AI 看一次，請改在新一回決定。")
    allowed = (
        ["ready"]
        if decision == "completed"
        else ["ready", "waiting", "failed", "unknown", "deferred", "unjudgeable"]
    )
    row = conn.execute(
        "UPDATE ads_review_round SET status=%s,decision=%s,reason=%s,revisit_at=%s,"
        "updated_at=now() WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND id=%s AND status=ANY(%s) RETURNING id",
        (decision, decision, reason.strip(), revisit, org, brand, campaign, review_id, allowed),
    ).fetchone()
    if row is None:
        raise ValueError("本回仍在處理或已完成，請重新載入；不會結束活動。")
    result = get(conn, org, brand, campaign, review_id)
    from app.ads import review_monitor

    review_monitor.on_decision(conn, result, commit=False)
    _resolve_ready_notice(conn, org, brand, review_id)
    conn.commit()
    # F49 Contract Q: a deferred／unjudgeable round (or a completed one whose copy set is done)
    # leaves the inbox now, not at the next refresh.
    from app.ads import triage

    triage.resolve_done(conn, org, brand, kind="worse", identity_id=result["entity_id"])
    return result


def proposal_reference(conn, org, brand, campaign, review_id, recommendation_id, items):
    if not review_id and not recommendation_id:
        return {}
    if not review_id or not recommendation_id:
        raise ValueError("檢討與建議識別必須成對提供。")
    review = get(conn, org, brand, campaign, review_id)
    if review["status"] not in {"ready", "completed"}:
        raise ValueError("本回尚未有可採用的檢討結果。")
    recommendation = next(
        (
            r
            for r in review["result_json"].get("recommendations", [])
            if r["id"] == recommendation_id
        ),
        None,
    )
    if recommendation is None or recommendation["recommendation"] != "adjust":
        raise ValueError("此建議不提供修改原廣告文案，請重新檢視。")
    if any(i["target_id"] != review["entity_id"] or i["kind"] != "copy" for i in items):
        raise ValueError("此檢討草稿只適用原廣告的文案調整。")
    entity = bindings.entity(conn, org, brand, campaign, review["entity_id"])
    c = changes.campaign(conn, org, brand, campaign)
    current = review_evidence.premise(entity, c)
    if changes.digest(current) != changes.digest(review["evidence_json"]["premise"]):
        raise ValueError("檢討後廣告設定、素材或目標已改變，請依現況重新檢討。")
    age = (settings.today_for_org(conn, org_id=org) - review["window_end"]).days
    if age > 30:
        raise ValueError("此檢討觀察期距今超過三十日，請先重看近期資料。")
    return {
        "review_id": review_id,
        "recommendation_id": recommendation_id,
        "review_evidence_hash": review["evidence_hash"],
    }
