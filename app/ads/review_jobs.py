"""One durable gateway call per evidence snapshot; never blind retry paid work."""

from app import background
from app.ads import asset_suggestion_policy as policy
from app.ads import change_control_data as changes
from app.ads import review_policy, review_rounds
from app.core import db
from app.llm import gateway, providers

TASK = "background.ads_review_round"


def enqueue(org, brand, campaign, review_id):
    if not background.is_active("ads-review:" + review_id):
        background.enqueue(
            TASK,
            org_id=org,
            lock="ads-review:" + review_id,
            brand_id=brand,
            campaign_id=campaign,
            review_id=review_id,
        )


def register_tasks():
    app = background.app()
    if TASK not in app.tasks:
        app.task(name=TASK)(run)


def settle(conn, org, review_id, task):
    if task.get("cost") is None:
        return
    conn.execute(
        "UPDATE ads_review_round SET reservation_state='settled',failed_cost=%s "
        "WHERE org_id=%s AND id=%s",
        (float(task["cost"]) if task["status"] != "succeeded" else 0, org, review_id),
    )


def apply_saved_task(conn, review, task):
    """Validate and adopt a durable output against its original evidence, without a provider."""
    evidence = review["evidence_json"]
    scope = task.get("context_scope_json") or {}
    if (
        task.get("org_id") != review["org_id"]
        or task.get("brand_id") != review["brand_id"]
        or task.get("task_type") != review_rounds.TASK_TYPE
        or scope.get("review_id") != review["id"]
        or scope.get("campaign_id") != review["campaign_id"]
        or scope.get("evidence_hash") != review["evidence_hash"]
        or task.get("prompt_template_id") != "ads/review_round"
        or task.get("prompt_template_version") != evidence["template_hash"]
        or task.get("provider") != evidence["provider"]
        or task.get("model") != evidence["model"]
    ):
        raise ValueError("已保存的模型結果與本回證據不符；不自動重送。")
    if task["status"] == "running":
        return None
    result, error = {}, "模型未完成；保留已知證據，不自動重送。"
    status = "failed" if task.get("cost") is not None else "unknown"
    if (
        status == "unknown"
        and task["status"] != "succeeded"
        and review["status"] == "unknown"
        and review["llm_task_id"] == task["id"]
    ):
        return None
    if task["status"] == "succeeded":
        try:
            output = task.get("rendered_output") or ""
            if len(output) > policy.OUTPUT_CHARS:
                raise ValueError("模型回傳超出接受上限，未採用。")
            result = review_policy.validate(
                conn,
                review["org_id"],
                review["brand_id"],
                evidence,
                gateway.parse_json_reply(output),
            )
            status, error = "ready", None
        except ValueError as exc:
            status, error = "failed", str(exc)
    changed = conn.execute(
        "UPDATE ads_review_round SET status=%s,result_json=%s,llm_task_id=%s,error=%s,"
        "updated_at=now() WHERE id=%s AND decision IS NULL "
        "AND status IN ('queued','running','unknown') RETURNING id",
        (status, db.jsonb(result), task["id"], error, review["id"]),
    ).fetchone()
    if changed:
        settle(conn, review["org_id"], review["id"], task)
    conn.commit()
    return status if changed else None


def recover(conn, timestamp, *, limit=100, bootstrap=False):
    """Recover saved output / an unsent queue gap. Only bootstrap can declare a dead runner."""
    limit = min(max(limit, 1), 100)
    result = dict(
        reviews_recovered=0, reviews_unknown=0, reviews_failed=0, reviews_enqueued=0, has_more=False
    )
    rows = conn.execute(
        "SELECT * FROM ads_review_round WHERE status IN ('queued','running','unknown') "
        "AND decision IS NULL ORDER BY recovery_checked_at NULLS FIRST,created_at,id LIMIT %s",
        (limit + 1,),
    ).fetchall()
    result["has_more"] = len(rows) > limit
    for row in rows[:limit]:
        review = dict(row)
        conn.execute(
            "UPDATE ads_review_round SET recovery_checked_at=to_timestamp(%s) WHERE id=%s",
            (timestamp, review["id"]),
        )
        conn.commit()
        tasks = gateway.find_tasks_for_scope(
            conn,
            org_id=review["org_id"],
            brand_id=review["brand_id"],
            task_type=review_rounds.TASK_TYPE,
            context_scope={"review_id": review["id"]},
        )
        if len(tasks) == 1:
            try:
                status = apply_saved_task(conn, review, tasks[0])
                if status:
                    key = {
                        "ready": "reviews_recovered",
                        "failed": "reviews_failed",
                        "unknown": "reviews_unknown",
                    }[status]
                    result[key] += 1
                    continue
                if not bootstrap or tasks[0]["status"] != "running":
                    continue
            except ValueError:
                pass
        elif not tasks and review["status"] == "queued" and not review["llm_task_id"]:
            if not background.is_active("ads-review:" + review["id"]):
                enqueue(review["org_id"], review["brand_id"], review["campaign_id"], review["id"])
                result["reviews_enqueued"] += 1
            continue
        elif not tasks and not bootstrap:
            continue
        if review["status"] != "unknown":
            conn.execute(
                "UPDATE ads_review_round SET status='unknown',updated_at=now(),error=%s "
                "WHERE id=%s AND status IN ('queued','running') AND decision IS NULL",
                ("執行結果或費用無法確認；保留預留額度，不自動重送。", review["id"]),
            )
            conn.commit()
            result["reviews_unknown"] += 1
    return result


def run(org_id, brand_id, campaign_id, review_id):
    with db.connection() as conn:
        db.set_tenant_scope(conn, org_id)
        review = review_rounds.get(conn, org_id, brand_id, campaign_id, review_id)
        changed = conn.execute(
            "UPDATE ads_review_round SET status='running',updated_at=now() "
            "WHERE org_id=%s AND brand_id=%s AND campaign_id=%s AND id=%s AND status='queued'",
            (org_id, brand_id, campaign_id, review_id),
        ).rowcount
        conn.commit()
        if not changed:
            return
        evidence, sent = review["evidence_json"], False
        try:
            provider = providers.select_provider(
                review_rounds.PROVIDER, task_type=review_rounds.TASK_TYPE
            )
            model = providers.resolve_model(
                task_type=review_rounds.TASK_TYPE, conn=conn, brand_id=brand_id
            )
            system = review_rounds.PROMPT.read_text(encoding="utf-8")
            if (
                provider.name != evidence["provider"]
                or model != evidence["model"]
                or changes.digest(system) != evidence["template_hash"]
            ):
                raise ValueError("模型或規則已改變，本回未送出；請重新建立檢討。")
            if len(system) + len(policy.encode(evidence)) + 32 > policy.INPUT_CHARS:
                raise ValueError("完整證據超出上限，本回未送出。")
            policy.ceiling(provider.name, model)
            sent = True
            task = gateway.run_task(
                conn,
                review_rounds.PROVIDER,
                brand_id=brand_id,
                task_type=review_rounds.TASK_TYPE,
                prompt_template_id="ads/review_round",
                prompt_template_version=evidence["template_hash"],
                system=system,
                messages=[{"role": "user", "content": policy.encode(evidence)}],
                context=gateway.TaskContext(
                    context_scope={
                        "brand_id": brand_id,
                        "review_id": review_id,
                        "campaign_id": campaign_id,
                        "evidence_hash": review["evidence_hash"],
                    },
                    knowledge_item_ids=evidence["knowledge_ids"],
                    brand_version=evidence["brand_version"],
                ),
                options=gateway.TaskOptions(
                    model=model,
                    thinking="low",
                    max_tokens=policy.OUTPUT_TOKENS,
                    timeout_s=policy.TIMEOUT_SECONDS,
                    max_retries=0,
                ),
            )
            apply_saved_task(conn, review, task)
        except Exception as exc:
            conn.rollback()
            if not sent:
                settle(conn, org_id, review_id, {"cost": 0, "status": "failed"})
            reason = (
                str(exc) if isinstance(exc, ValueError) else "檢討執行中斷，結果未知，不自動重送。"
            )
            status = "failed" if isinstance(exc, ValueError) or not sent else "unknown"
            conn.execute(
                "UPDATE ads_review_round SET status=%s,error=%s,updated_at=now() WHERE id=%s",
                (status, reason, review_id),
            )
            conn.commit()
