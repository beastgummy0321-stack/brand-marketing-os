"""Contract C (F27): three short angle candidates per (ad, copy), cached in `llm_task` itself --
no dedicated table. `get()` is a pure read plus an idempotent first enqueue; the cache key is the
task's own `context_scope_json` (`entity_id` + a hash of this ad's own copy), looked up through
the existing `gateway.find_tasks_for_scope` the same way `review_jobs.recover` does. A later copy
edit changes the hash, so it naturally falls back to a fresh `pending` -> a fresh background call,
never a stale cached answer silently reused (correction 9: one call per ad per copy hash)."""

from app import background
from app.ads import asset_binding_repository as bindings
from app.ads import asset_suggestion_policy as policy
from app.ads import change_control_data as changes
from app.brand_intelligence import repository as bi_repo
from app.core import db
from app.llm import gateway, providers

TASK_TYPE = "ads_angles"
TASK = "background.ads_angles"
PROVIDER = providers.AnthropicProvider()
PROMPT = db.APP_DIR / "departments" / "ads" / "angles.md"
MAX_TOKENS = 256
TIMEOUT_SECONDS = 60


def _copy_hash(entity):
    return changes.digest(changes.copy_fields(entity))


def _scope(brand_id, entity_id, copy_hash):
    return {"brand_id": brand_id, "entity_id": entity_id, "copy_hash": copy_hash}


def _validate(reply):
    if not isinstance(reply, dict) or set(reply) != {"angles"}:
        raise ValueError("模型回覆格式錯誤，未採用。")
    angles = reply["angles"]
    if not isinstance(angles, list) or len(angles) != 3:
        raise ValueError("模型未回傳三個候選主打，未採用。")
    cleaned = []
    for value in angles:
        if not isinstance(value, str):
            raise ValueError("候選主打格式錯誤，未採用。")
        text = value.strip()
        if not text or len(text) > 12:
            raise ValueError("候選主打需為一至十二字，未採用。")
        cleaned.append(text)
    if len(set(cleaned)) != len(cleaned):
        raise ValueError("候選主打重複，未採用。")
    return cleaned


def get(conn, org, brand, campaign, entity_id):
    changes.campaign(conn, org, brand, campaign)
    entity = bindings.entity(conn, org, brand, campaign, entity_id)
    copy_hash = _copy_hash(entity)
    scope = _scope(brand, entity_id, copy_hash)
    tasks = gateway.find_tasks_for_scope(
        conn, org_id=org, brand_id=brand, task_type=TASK_TYPE, context_scope=scope
    )
    task = tasks[0] if tasks else None
    if task is None:
        enqueue(org, brand, campaign, entity_id, copy_hash)
        return {"status": "pending", "candidates": [], "error": None}
    if task["status"] == "running":
        return {"status": "pending", "candidates": [], "error": None}
    if task["status"] != "succeeded":
        return {"status": "failed", "candidates": [], "error": task.get("error")}
    output = task.get("rendered_output") or ""
    if len(output) > policy.OUTPUT_CHARS:
        return {"status": "failed", "candidates": [], "error": "模型回傳超出接受上限，未採用。"}
    try:
        candidates = _validate(gateway.parse_json_reply(output))
    except ValueError as exc:
        return {"status": "failed", "candidates": [], "error": str(exc)}
    return {"status": "ready", "candidates": candidates, "error": None}


def enqueue(org, brand, campaign, entity_id, copy_hash):
    lock = f"ads-angles:{entity_id}:{copy_hash}"
    if not background.is_active(lock):
        background.enqueue(
            TASK,
            org_id=org,
            lock=lock,
            brand_id=brand,
            campaign_id=campaign,
            entity_id=entity_id,
            copy_hash=copy_hash,
        )


def register_tasks():
    app = background.app()
    if TASK not in app.tasks:
        app.task(name=TASK)(run)


def run(org_id, brand_id, campaign_id, entity_id, copy_hash):
    with db.connection() as conn:
        db.set_tenant_scope(conn, org_id)
        try:
            entity = bindings.entity(conn, org_id, brand_id, campaign_id, entity_id)
        except ValueError:
            return
        if _copy_hash(entity) != copy_hash:
            # The ad's copy changed since this job was queued -- a stale request. A fresh GET
            # under the new copy hash enqueues its own job; this one is simply skipped, not paid.
            return
        brand_row = bi_repo.get_brand(conn, brand_id)
        system = PROMPT.read_text(encoding="utf-8")
        provider = providers.select_provider(PROVIDER, task_type=TASK_TYPE)
        model = providers.resolve_model(task_type=TASK_TYPE, conn=conn, brand_id=brand_id)
        content = policy.encode(
            {"copy": changes.copy_fields(entity), "brand_name": (brand_row or {}).get("name") or ""}
        )
        gateway.run_task(
            conn,
            provider,
            brand_id=brand_id,
            task_type=TASK_TYPE,
            prompt_template_id="ads/angles",
            prompt_template_version=changes.digest(system),
            system=system,
            messages=[{"role": "user", "content": content}],
            context=gateway.TaskContext(
                context_scope=_scope(brand_id, entity_id, copy_hash),
                knowledge_item_ids=[],
                brand_version=(brand_row or {}).get("knowledge_version") or 1,
            ),
            options=gateway.TaskOptions(
                model=model,
                thinking="low",
                max_tokens=MAX_TOKENS,
                timeout_s=TIMEOUT_SECONDS,
                max_retries=0,
            ),
        )
