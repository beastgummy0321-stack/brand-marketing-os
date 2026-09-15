"""app/workbench/identity.py — F07-I05 (ARCHITECTURE.md §5.9, Decision 20): derives and caches
a brand's visual identity and its ranked starting guess of fitting looks, using only that
brand's own facts. Private to app/workbench (container contract §1): `jobs.py` calls
`ensure_identity()`.

No user tuning, style picking or instruction lives here (the user's own bar, F07's outcome
text) — the model answers once per (brand, knowledge_version) from a fixed department prompt
plus the brand's compiled context; the program then checks the reply before ever caching it
(Decision 20 step 4): the schema is not a guarantee.
"""

from pathlib import Path

from app.brand_intelligence import repository as bi_repo
from app.llm import context_compiler, gateway
from app.workbench import looks
from app.workbench import repository as workbench_repo

_DEPARTMENT_PATH = (
    Path(__file__).resolve().parents[1] / "departments" / "workbench" / "visual_identity.md"
)

DERIVE_FAILED_MESSAGE = "品牌視覺推導失敗，請再生成一次。"

_MIN_FIT_LOOKS = 3
_MAX_FIT_LOOKS = 5
_MAX_EXCLUDED_LOOKS = 3

_TOOL_SCHEMA = {
    "name": "visual_identity",
    "description": "提交這個品牌的視覺識別、適合的風格排序，以及有事實依據才能列的排除風格。",
    "input_schema": {
        "type": "object",
        "properties": {
            "identity": {"type": "string"},
            "fit_looks": {
                "type": "array",
                "items": {"type": "string", "enum": list(looks.LOOKS)},
                "minItems": _MIN_FIT_LOOKS, "maxItems": _MAX_FIT_LOOKS,
            },
            "excluded_looks": {
                "type": "array",
                "maxItems": _MAX_EXCLUDED_LOOKS,
                "items": {
                    "type": "object",
                    "properties": {
                        "look": {"type": "string", "enum": list(looks.LOOKS)},
                        "fact": {"type": "string"},
                    },
                    "required": ["look", "fact"],
                    "additionalProperties": False,
                },
            },
            "reason": {"type": "string"},
        },
        "required": ["identity", "fit_looks", "excluded_looks", "reason"],
        "additionalProperties": False,
    },
}


def brand_spec_text(conn, brand_id: str) -> str | None:
    # `conn` 這裡不標 _AnyConn（同 repository.py::submit_brief 檔頭的既有寫法）：
    # `bi_repo.list_brand_facts()`／`context_compiler.compile()`／`gateway.run_task()` 簽章
    # 吃 `Conn`（非 `ConnProxy`），留白讓 pyright 用型別不定（Unknown）通過，呼叫端只在真正
    # 呼叫這裡的地方傳入 `web.conn`（`ConnProxy`）或一條真的 `Conn`。
    """確認過的 `visual_base` 品牌事實，依 `list_brand_facts` 的順序合併成一段文字；
    沒有就回 `None`（Decision 20：`brand_spec` 只在有值時才進 fit_looks）。"""
    facts = bi_repo.list_brand_facts(conn, brand_id, status="confirmed")
    values = [f["value"] for f in facts if f["fact_type"] == "visual_base" and f["value"]]
    return "\n".join(values) if values else None


def _build_prompt(context_text: str) -> str:
    department_text = _DEPARTMENT_PATH.read_text(encoding="utf-8")
    style_lines = [
        f"- {key}：{looks.look_label(key)}——{looks.look_texture(key, None)}"
        for key in looks.LOOKS
    ]
    return (
        f"{department_text}\n\n## 風格清單\n" + "\n".join(style_lines)
        + f"\n\n## 品牌事實與規則\n{context_text}"
    )


def _checked_reply(data: dict | None, context_text: str) -> tuple[str, list, list] | None:
    """Decision 20 step 4：schema 不是保證。回傳 `None` 代表這輪推導失敗，什麼都不存。"""
    if not isinstance(data, dict):
        return None
    identity = data.get("identity")
    if not isinstance(identity, str) or not identity.strip():
        return None

    fit_raw = data.get("fit_looks")
    fit_looks: list[str] = []
    if isinstance(fit_raw, list):
        for key in fit_raw:
            if key in looks.LOOKS and key not in fit_looks:
                fit_looks.append(key)

    excluded_raw = data.get("excluded_looks")
    excluded: list[dict] = []
    if isinstance(excluded_raw, list):
        for entry in excluded_raw:
            if not isinstance(entry, dict):
                continue
            look_key = entry.get("look")
            fact = entry.get("fact")
            if look_key not in looks.LOOKS:
                continue
            if not isinstance(fact, str) or not fact.strip():
                continue
            if fact not in context_text:
                continue
            excluded.append({"look": look_key, "fact": fact})

    excluded_keys = {e["look"] for e in excluded}
    fit_looks = [k for k in fit_looks if k not in excluded_keys]

    if len(fit_looks) < _MIN_FIT_LOOKS:
        return None
    return identity.strip(), fit_looks, excluded


def ensure_identity(conn, org_id: str, brand_id: str, provider) -> dict:
    """Decision 20：一個 (brand_id, knowledge_version) 只推導一次，之後直接讀快取。
    `RuntimeError(DERIVE_FAILED_MESSAGE)` 且不存任何一列：模型沒成功、回覆解不出來、
    `identity` 是空字串，或有效 `fit_looks` 少於 3 個。"""
    brand = bi_repo.get_brand(conn, brand_id)
    if brand is None:
        raise ValueError(f"找不到品牌：{brand_id}")
    version = brand["knowledge_version"]

    existing = workbench_repo.get_visual_identity(conn, org_id, brand_id, version)
    if existing is not None:
        return existing

    context_text, knowledge_item_ids, _brand_version, _product_version = (
        context_compiler.compile(conn, brand_id, None)
    )
    prompt = _build_prompt(context_text)

    task = gateway.run_task(
        conn, provider, brand_id=brand_id, task_type="workbench_derive_identity",
        prompt_template_id="workbench_derive_identity", prompt_template_version="v1",
        system=None, messages=[{"role": "user", "content": prompt}],
        context=gateway.TaskContext(
            context_scope={"brand_id": brand_id, "part": "visual_identity"},
            knowledge_item_ids=knowledge_item_ids,
            brand_version=version, product_version=None,
        ),
        options=gateway.TaskOptions(
            max_tokens=2000, timeout_s=180.0, tools=[_TOOL_SCHEMA],
        ),
    )

    if task["status"] != "succeeded":
        raise RuntimeError(DERIVE_FAILED_MESSAGE)

    data = task["structured_output_json"]
    if data is None:
        from app.workbench import validate as workbench_validate

        data = workbench_validate.parse_json_only(task["rendered_output"])

    checked = _checked_reply(data, context_text)
    if checked is None:
        raise RuntimeError(DERIVE_FAILED_MESSAGE)
    identity_text, fit_looks, excluded_looks = checked

    spec = brand_spec_text(conn, brand_id)
    fit_final = ([looks.BRAND_SPEC] if spec else []) + fit_looks

    workbench_repo.insert_visual_identity(
        conn, org_id=org_id, brand_id=brand_id, knowledge_version=version,
        identity_text=identity_text, fit_looks=fit_final, excluded_looks=excluded_looks,
        brand_spec_text=spec, llm_task_id=task["id"],
    )
    result = workbench_repo.get_visual_identity(conn, org_id, brand_id, version)
    assert result is not None
    return result
