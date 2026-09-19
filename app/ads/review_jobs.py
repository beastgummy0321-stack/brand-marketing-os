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
                    context_scope={"brand_id": brand_id, "review_id": review_id},
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
            settle(conn, org_id, review_id, task)
            conn.execute(
                "UPDATE ads_review_round SET llm_task_id=%s WHERE id=%s", (task["id"], review_id)
            )
            conn.commit()
            if task["status"] != "succeeded":
                status = "failed" if task.get("cost") is not None else "unknown"
                conn.execute(
                    "UPDATE ads_review_round SET status=%s,error=%s,updated_at=now() WHERE id=%s",
                    (status, "模型未完成；保留已知證據，不自動重送。", review_id),
                )
                conn.commit()
                return
            output = task.get("rendered_output") or ""
            if len(output) > policy.OUTPUT_CHARS:
                raise ValueError("模型回傳超出接受上限，未採用。")
            result = review_policy.validate(
                conn, org_id, brand_id, evidence, gateway.parse_json_reply(output)
            )
            conn.execute(
                "UPDATE ads_review_round SET status='ready',result_json=%s,error=NULL,"
                "updated_at=now() WHERE id=%s",
                (db.jsonb(result), review_id),
            )
            conn.commit()
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
