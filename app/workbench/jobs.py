"""app/workbench/jobs.py — the one generation task's actual LLM work, private to this package
(container contract §1; only `app/workbench/__init__.py` exports anything from here).

One brief = one procrastinate job per part = one LLM call, JSON-only reply (ADR 0068 §6).
Body, in order: mark brief `running` -> build the prompt (`prompts.py`) -> `gateway.run_task()`
-> `validate.parse_json_only` -> `validate.check_<part>()` -> failing items are re-asked once,
together, in one follow-up call (`fix.md`) whose prompt names only the failing paths, never the
whole brief again -> write `workbench_output` -> brief `done`. A failed `llm_task`, a
non-JSON-only reply, or any other exception all become a `RuntimeError` that the outer wrapper
turns into `brief.status='failed'` + `last_error`, then re-raises — the exception is not
swallowed (ticket workbench/02 §2).

Freely reads `routes`-shaped pieces? No — this package has no `routes.py` yet (ticket 03).
`register_tasks()` follows the exact pattern of `app/schedule/jobs.py::register_tasks()` /
`app/meta/daily_pull.py::register_task()`: `app.background.app()`'s DSN-keyed rebuild means a
task registered once at import time silently stops being live after a DSN change, so every
caller that gets a fresh `background.app()` (each test module) must call this again.
"""

import re

from app.background import app as background_app
from app.brand_intelligence import repository as bi_repo
from app.core.db import APP_DIR, connection
from app.llm import context_compiler, gateway, methodology, providers
from app.workbench import prompts, repository, validate

DEPARTMENTS_DIR = APP_DIR / "departments" / "workbench"

# 唯一的供應商實例，比照 app/schedule/jobs.py：測試用
# `mock.patch.object(jobs, "PROVIDER", FakeProvider(...))` 換掉。
PROVIDER = providers.AnthropicProvider()

# 任務型別 -> 方法論對照表列名（app/methodology/README.md，ADR 0068 §9）。`free`
# 沒有自己的方法論列、也沒有 app/departments/workbench/free.md——跟 video_script 一樣，
# 這個 part 在這張票是休眠的（沒有路由、沒有測試案例呼叫它），留給之後補上任務檔的票。
_METHODOLOGY_LABELS = {
    "copy": "素材工作檯文案",
    "image_prompt": "素材工作檯圖片提示詞",
    "video_script": "素材工作檯影片腳本",
}

_PATH_RE = re.compile(r"^([a-z_]+)(?:\[(\d+)\]|\.([a-z_]+))?$")


def _apply_replacements(data: dict, replacements) -> None:
    """把修正輪回覆的 `replacements` 套進原始資料——只認得到的 path 才套，套不出來的
    （model 亂寫的 path）安靜跳過，不炸掉整個修正輪。`fixed` 整段鎖死：ADR 0068 §7，固定段
    一份 brief 只產一次、逐則比對用，修正輪不准動它，不管回覆點名哪個 path。"""
    for item in replacements or []:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        match = _PATH_RE.match(path) if isinstance(path, str) else None
        if not match:
            continue
        key, index, subkey = match.groups()
        if key == "fixed":
            continue
        value = item.get("value")
        if index is not None:
            items = data.get(key)
            i = int(index) - 1
            if isinstance(items, list) and 0 <= i < len(items):
                items[i] = value
        elif subkey is not None:
            obj = data.get(key)
            if isinstance(obj, dict):
                obj[subkey] = value
        else:
            data[key] = value


def _validate(part: str, data, *, vocabulary: dict, count) -> tuple:
    """回傳 `(結果清單, 渲染清單或 None)`——只有 `image_prompt` 有渲染清單要存進
    `body_json.rendered`。"""
    if part == "copy":
        return validate.check_copy(data, vocabulary), None
    if part == "image_prompt":
        return validate.check_image_prompts(data, count)
    if part == "video_script":
        return validate.check_video_script(data, count), None
    return [], None  # 'free'：自由生成沒有格式驗證器（ADR 0068 §9 沒有這個 part 的方法論
                      # 或格式規則），只驗過 JSON-only 就算數


def _fix_call(conn, brand_id: str, context, task_type: str, failing: list) -> dict:
    """ADR 0068 §6：失敗項目一次問完、只問失敗的那幾項——prompt 只點名 `failing` 裡的
    path，不重貼原本的部門任務檔／工單／方法論（那些內容模型已經看過一次，批次不重生）。"""
    fix_text = (DEPARTMENTS_DIR / "fix.md").read_text(encoding="utf-8")
    listing = "\n".join(f"- path: {item['path']}\n  問題：{item['message']}" for item in failing)
    prompt = "\n\n".join([fix_text, "## 這些欄位沒有通過驗證，只重新回答這些", listing])
    return gateway.run_task(
        conn, PROVIDER, brand_id=brand_id, task_type=task_type,
        prompt_template_id=f"{task_type}_fix", prompt_template_version="v1",
        system=None, messages=[{"role": "user", "content": prompt}], context=context,
        options=gateway.TaskOptions(max_tokens=16000, timeout_s=480.0),
    )


def _run(conn, org_id: str, brand_id: str, brief_id: str, part: str, count) -> None:
    brief = repository.get_brief(conn, org_id, brand_id, brief_id)
    if brief is None:
        raise RuntimeError(f"找不到工單：{brief_id}")

    product_id = brief.get("product_id")
    product = bi_repo.get_product(conn, brand_id, product_id) if product_id else None
    style = repository.get_style(brief["style_key"])
    request = brief.get("request_json") or {}

    if request.get("use_brand_knowledge") and product_id:
        brand_context, knowledge_item_ids, brand_version, _product_version = (
            context_compiler.compile(conn, brand_id, product_id)
        )
    else:
        brand_context, knowledge_item_ids = "", []
        brand_row = bi_repo.get_brand(conn, brand_id)
        assert brand_row is not None  # brief 已經查得到，它的 brand_id 不可能是空品牌
        brand_version = brand_row["knowledge_version"]

    task_type = f"workbench_{part}"
    department_text = (DEPARTMENTS_DIR / f"{part}.md").read_text(encoding="utf-8")
    methodology_label = _METHODOLOGY_LABELS.get(part)
    methodology_text = methodology.compile(
        conn, [methodology_label] if methodology_label else [], brand_id=brand_id
    ).text
    brief_section = prompts.brief_text(brief, (product or {}).get("name"), style)

    vocabulary: dict = {}
    if part == "copy":
        coordinate_rows = repository.list_coordinate_vocabulary(conn, org_id, brand_id)
        vocabulary = validate.vocabulary_by_dimension(coordinate_rows)
        coordinate_text = prompts.coordinate_vocabulary_text(coordinate_rows)
        prompt = prompts.copy_prompt(
            department_text, methodology_text, brief_section, brand_context, coordinate_text
        )
    elif part == "image_prompt":
        headlines_output = repository.adopted_output(conn, org_id, brand_id, brief_id, "copy")
        headlines = (headlines_output or {}).get("body_json", {}).get("headlines") or []
        prompt = prompts.image_prompt_prompt(
            department_text, methodology_text, brief_section, brand_context, headlines, count
        )
    else:
        # video_script／free：跟 copy 同一種組法，少座標詞彙表（這兩個 part 不用回答七維
        # 座標）。
        prompt = prompts.copy_prompt(
            department_text, methodology_text, brief_section, brand_context, ""
        )

    context = gateway.TaskContext(
        context_scope={"brand_id": brand_id, "brief_id": brief_id, "part": part},
        knowledge_item_ids=knowledge_item_ids, brand_version=brand_version, product_version=None,
    )
    task_row = gateway.run_task(
        conn, PROVIDER, brand_id=brand_id, task_type=task_type,
        prompt_template_id=task_type, prompt_template_version="v1",
        system=None, messages=[{"role": "user", "content": prompt}], context=context,
        options=gateway.TaskOptions(max_tokens=16000, timeout_s=480.0),
    )
    if task_row["status"] != "succeeded":
        raise RuntimeError(task_row.get("error") or "生成失敗。")

    data = validate.parse_json_only(task_row.get("rendered_output") or "")
    if data is None:
        raise RuntimeError("代理沒有回傳純 JSON，請重新產出一次。")

    results, rendered = _validate(part, data, vocabulary=vocabulary, count=count)
    failing = [r for r in results if not r["ok"]]
    if failing:
        fix_row = _fix_call(conn, brand_id, context, task_type, failing)
        if fix_row["status"] == "succeeded":
            fix_data = validate.parse_json_only(fix_row.get("rendered_output") or "")
            if fix_data is not None:
                _apply_replacements(data, fix_data.get("replacements"))
        # 批次不重生（ADR 0068 §6）：不管修正輪成不成功都只重跑一次驗證，還不合格就老實
        # 印 ❌，不再問第二次。
        results, rendered = _validate(part, data, vocabulary=vocabulary, count=count)

    round_no = repository.next_round(conn, org_id, brand_id, brief_id, part)
    body = dict(data)
    body["validation"] = [
        ("✅ " if r["ok"] else "❌ ") + f"{r['path']}：{r['message']}" for r in results
    ]
    if rendered is not None:
        body["rendered"] = rendered
    repository.write_output(
        conn, org_id=org_id, brand_id=brand_id, brief_id=brief_id, part=part,
        generation_round=round_no, body_json=body,
        coordinates_json=data.get("coordinates") if part == "copy" else None,
        llm_task_id=task_row["id"],
    )
    repository.mark_brief_status(conn, org_id, brand_id, brief_id, "done")


def workbench_generate(org_id: str, brand_id: str, brief_id: str, part: str, *,
                        count: int | None = None) -> None:
    """procrastinate task body（`background.workbench_generate`）。每個 job 開自己的
    連線——worker job 不繼承 request 的連線（同 `app/schedule/jobs.py` 三支 task 的慣例）。"""
    with connection() as conn:
        repository.mark_brief_status(conn, org_id, brand_id, brief_id, "running")
        try:
            _run(conn, org_id, brand_id, brief_id, part, count)
        except Exception as exc:
            repository.mark_brief_failed(conn, org_id, brand_id, brief_id, str(exc))
            raise


def register_tasks() -> None:
    """掛一個生成 task，冪等——同一個原因、同一個模式，見 `app/schedule/jobs.py
    register_tasks()` 檔頭：`app.background.app()` 的 DSN 換了會整顆重建，只註冊一次在
    import 期會在任何 DSN 換過之後悄悄失效。"""
    a = background_app()
    name = "background.workbench_generate"
    if name not in a.tasks:
        a.task(name=name)(workbench_generate)
