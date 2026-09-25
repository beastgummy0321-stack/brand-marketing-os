"""真相卡確認後的人物誌生成；資料存取留在 brand_intelligence.personas。

票 09：搬離行程內狀態表＋背景執行緒，改走 `app.background` 佇列（範本同 routes_report_api.py）。
"""

from app.background import JOB_FAILED_MESSAGE
from app.background import enqueue as background_enqueue
from app.background import is_active as background_is_active
from app.background import job_outcome as background_job_outcome
from app.brand_intelligence import background_job, personas
from app.brand_intelligence import repository as repo
from app.core.db import connection as core_db_connection
from app.core.db import new_id
from app.llm import context_compiler, gateway, providers
from app.shared import web

PROVIDER = providers.AnthropicProvider()
_USUAL_RANGE = "30 到 60 秒"
_PARSE_FAIL = "AI 有回覆，但人物誌格式不完整，可以再試一次。"
_TASK_TYPE = "intake_persona"

_SYSTEM = (
    "你是品牌研究員。依已確認的品牌資料與顧客原話，整理最值得優先接觸的典型客人。"
    "不能把猜測寫成已知事實；沒有材料支撐時，要用保守白話描述。請用指定工具回傳。"
)

_PERSONA_TOOL = {
    "name": "submit_personas",
    "description": "提交 2 到 4 張人物誌。",
    "input_schema": {
        "type": "object",
        "properties": {
            "personas": {
                "type": "array", "minItems": 2, "maxItems": 4,
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "這類人的白話名稱"},
                        "when_needed": {"type": "string", "description": "他在什麼時候需要"},
                        "care_about": {"type": "string", "description": "他最在意什麼"},
                        "hesitation": {"type": "string", "description": "他下單前會猶豫什麼"},
                        "where_to_find": {"type": "string", "description": "可以去哪裡找到他"},
                    },
                    "required": list(personas.PERSONA_FIELDS),
                    "additionalProperties": False,
                },
            },
        },
        "required": ["personas"],
        "additionalProperties": False,
    },
}


def _generation_material(conn, brand_id: str) -> tuple:
    context_text, item_ids, brand_version, _product_version = context_compiler.compile(
        conn, brand_id, include_personas=False,
    )
    product_sections = []
    for product in repo.list_products(conn, brand_id):
        if product["status"] != "active":
            continue
        product_text, product_ids, _brand_version, _version = context_compiler.compile(
            conn, brand_id, product["id"], include_personas=False,
        )
        if product_text.strip():
            product_sections.append(f"【產品：{product['name']}】\n{product_text.strip()}")
        item_ids.extend(product_ids)
    item_ids = list(dict.fromkeys(item_ids))
    voices = repo.list_customer_voices(conn, brand_id, status="active")
    voice_lines = [str(row.get("raw_text") or "").strip() for row in voices]
    voice_lines = [line for line in voice_lines if line]
    sections = [context_text.strip()] if context_text.strip() else []
    sections.extend(product_sections)
    if voice_lines:
        sections.append("【顧客原話】\n" + "\n".join(f"- {line}" for line in voice_lines[:20]))
    sections.append(
        "請產生 2 到 4 張人物誌。每張都要填：人物稱呼、什麼時候需要、在意什麼、"
        "會猶豫什麼、去哪裡找得到。不要捏造精確年齡、收入或人數。"
    )
    return "\n\n".join(sections), item_ids, brand_version


def _normalize(data) -> list | None:
    rows = data.get("personas") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not 2 <= len(rows) <= 4:
        return None
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            return None
        clean = {field: str(row.get(field) or "").strip() for field in personas.PERSONA_FIELDS}
        if any(not clean[field] for field in personas.PERSONA_FIELDS):
            return None
        normalized.append(clean)
    return normalized


def generate(conn, brand_id: str) -> tuple:
    """同步生成核心：成功才整批取代舊資料；失敗保留上一批。"""
    prompt, item_ids, brand_version = _generation_material(conn, brand_id)
    task = gateway.run_task(
        conn, PROVIDER, brand_id=brand_id, task_type="intake_persona",
        prompt_template_id="intake_persona", prompt_template_version="v1",
        system=_SYSTEM, messages=[{"role": "user", "content": prompt}],
        context=gateway.TaskContext(
            context_scope={"brand_id": brand_id}, knowledge_item_ids=item_ids,
            brand_version=brand_version,
        ),
        options=gateway.TaskOptions(max_tokens=2400, tools=[_PERSONA_TOOL]),
    )
    if task["status"] != "succeeded":
        return False, task["error"] or "人物誌沒有產生，可以再試一次。"
    data = task["structured_output_json"]
    normalized = _normalize(data)
    if normalized is None:
        return False, _PARSE_FAIL
    brand = repo.get_brand(conn, brand_id)
    if brand is None:
        raise ValueError(f"找不到品牌：{brand_id}")
    return True, personas.replace_personas(conn, brand_id, normalized, org_id=brand["org_id"])


def _latest_task_row(brand_id: str) -> dict | None:
    row = web.conn.execute(
        "SELECT * FROM llm_task WHERE brand_id = %s AND task_type = %s "
        "ORDER BY started_at DESC LIMIT 1",
        (brand_id, _TASK_TYPE),
    ).fetchone()
    return dict(row) if row is not None else None


def _state(status: str, started_at, error: str | None = None) -> dict:
    stage = {"running": "整理人物誌", "done": "完成", "failed": "整理人物誌"}.get(status, "")
    return {"status": status, "stage": stage, "started_at": started_at,
            "usual_range_text": _USUAL_RANGE if status != "idle" else "", "error": error}


def generation_state(brand_id: str) -> dict:
    """Contract J 先看佇列：最新的 job 還在排／在跑＝running（即使有舊的 llm_task 列）；
    最新的 job 失敗＝failed。其餘讀 llm_task 取代 JOBS dict；succeeded 列重驗。"""
    lock = f"intake_persona:{brand_id}"
    row = _latest_task_row(brand_id)
    outcome = background_job_outcome(lock)
    if outcome == "active":
        running_row = row is not None and row["status"] == "running" and row["started_at"]
        return _state("running", row["started_at"].isoformat() if running_row else None)
    if outcome == "failed":
        started_at = row["started_at"].isoformat() if row is not None and row["started_at"] else None
        own_error = row is not None and row["status"] not in ("running", "succeeded") and row["error"]
        return _state("failed", started_at, row["error"] if own_error else JOB_FAILED_MESSAGE)
    if row is None:
        return _state("running", None) if background_is_active(lock) else _state("idle", None)
    started_at = row["started_at"].isoformat() if row["started_at"] else None
    if row["status"] == "running":
        return _state("running", started_at)
    if row["status"] == "succeeded":
        if _normalize(row["structured_output_json"]) is not None:
            if background_is_active(lock):
                return _state("running", started_at)
            return _state("done", started_at)
        return _state("failed", started_at, _PARSE_FAIL)
    return _state("failed", started_at, row["error"])


def _notify(conn, brand_id: str, message: str) -> None:
    background_job.notify(
        conn, brand_id, category="personas_ready", dedupe_key=new_id("psnjob"),
        message=message, action_url=f"/app/brands/{brand_id}/library?tab=customer-voice",
    )


def background_intake_persona(org_id: str, brand_id: str) -> None:
    with core_db_connection() as conn:
        brand = repo.get_brand(conn, brand_id)
        brand_name = brand["name"] if brand else brand_id
        error = None
        try:
            ok, _result = generate(conn, brand_id)
        except Exception as exc:  # noqa: BLE001 — 先寄失敗通知，再往上丟讓 job 記成失敗
            conn.rollback()  # 失敗的交易先收掉，通知才寫得進去
            ok, error = False, exc
        if ok:
            _notify(conn, brand_id, f"「{brand_name}」人物誌好了")
        else:
            _notify(conn, brand_id, f"「{brand_name}」人物誌失敗，可重試")
        if error is not None:
            raise error  # Contract J：job 結局要是 failed，狀態端點才不會讀成完成


def start_generation(org_id: str, brand_id: str) -> None:
    brand = repo.get_brand(web.conn, brand_id)
    if brand is None:
        raise ValueError(f"找不到品牌：{brand_id}")
    lock = f"intake_persona:{brand_id}"
    if background_is_active(lock):
        return  # 已經在跑，第二次按下去是 no-op（原本行程內狀態表的 idempotent=True 同一個行為）
    background_enqueue("background.intake_persona", org_id=org_id, lock=lock, brand_id=brand_id)
