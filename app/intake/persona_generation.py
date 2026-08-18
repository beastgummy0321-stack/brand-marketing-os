# -*- coding: utf-8 -*-
"""真相卡確認後的人物誌生成；資料存取留在 brand_intelligence.personas。"""

import json
from datetime import datetime, timezone

from app.brand_intelligence import background_job, personas
from app.brand_intelligence import repository as repo
from app.core.db import new_id
from app.llm import context_compiler, gateway, providers


PROVIDER = providers.AnthropicProvider()
JOBS = background_job.JobRegistry()
_USUAL_RANGE = "30 到 60 秒"
_PARSE_FAIL = "AI 有回覆，但人物誌格式不完整，可以再試一次。"

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
    try:
        data = json.loads(task["structured_output_json"] or "null")
    except json.JSONDecodeError:
        data = None
    normalized = _normalize(data)
    if normalized is None:
        return False, _PARSE_FAIL
    return True, personas.replace_personas(conn, brand_id, normalized)


def generation_state(brand_id: str) -> dict:
    return JOBS.get(brand_id, {
        "status": "idle", "stage": "", "started_at": None,
        "usual_range_text": "", "error": None,
    })


def _notify(conn, brand_id: str, message: str) -> None:
    background_job.notify(
        conn, brand_id, category="personas_ready", dedupe_key=new_id("psnjob"),
        message=message, action_url=f"/brands/{brand_id}/hub?tab=customer-voice",
    )


def _run_job(conn, brand_id: str, brand_name: str) -> None:
    try:
        ok, result = generate(conn, brand_id)
    except Exception as exc:  # noqa: BLE001 - 背景執行緒最後一道誠實狀態防線
        ok, result = False, f"背景執行發生未預期錯誤：{exc}"
    started_at = generation_state(brand_id).get("started_at")
    if ok:
        _notify(conn, brand_id, f"「{brand_name}」人物誌好了")
        JOBS.set(brand_id, {
            "status": "done", "stage": "完成", "started_at": started_at,
            "usual_range_text": _USUAL_RANGE, "error": None,
        })
    else:
        _notify(conn, brand_id, f"「{brand_name}」人物誌失敗，可重試")
        JOBS.set(brand_id, {
            "status": "failed", "stage": "整理人物誌", "started_at": started_at,
            "usual_range_text": _USUAL_RANGE, "error": str(result),
        })


def start_generation(conn, brand_id: str) -> None:
    brand = repo.get_brand(conn, brand_id)
    if brand is None:
        raise ValueError(f"找不到品牌：{brand_id}")
    JOBS.start(
        brand_id,
        {
            "status": "running", "stage": "整理人物誌",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "usual_range_text": _USUAL_RANGE, "error": None, "brand_id": brand_id,
        },
        _run_job, (conn, brand_id, brand["name"]), idempotent=True,
    )
