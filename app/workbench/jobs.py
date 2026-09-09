"""app/workbench/jobs.py — the one generation task's actual LLM work, private to this package
(container contract §1; only `app/workbench/__init__.py` exports anything from here).

One brief = one procrastinate job per part = one LLM call, JSON-only reply (ADR 0068 §6).
Body, in order: mark brief `running` -> build the prompt (`prompts.py`) -> `gateway.run_task()`
-> `validate.parse_json_only` -> `validate.check_<part>()` -> failing items are re-asked once,
together, in one follow-up call (`fix.md`) whose prompt names only the failing paths, never the
whole brief again -> write `workbench_output` -> brief `done`. A failed `llm_task`, a
non-JSON-only reply, or any other exception all become a `RuntimeError` that the outer wrapper
turns into `brief.status='failed'` + `last_error`, then re-raises — the exception is not
swallowed (ticket workbench/02 §2). Ticket 03 §3 adds one no-call exit: an `image_prompt` run
with neither an adopted/latest `copy` output's `headlines` nor `request_json.on_image_texts`
raises before `gateway.run_task()` is ever reached — zero LLM calls, not one.

`register_tasks()` follows the exact pattern of `app/schedule/jobs.py::register_tasks()` /
`app/meta/daily_pull.py::register_task()`: `app.background.app()`'s DSN-keyed rebuild means a
task registered once at import time silently stops being live after a DSN change, so every
caller that gets a fresh `background.app()` (each test module) must call this again.
"""

import json
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

# 任務型別 -> 方法論對照表列名（app/methodology/README.md，ADR 0068 §9；`free` 那一列
# 票 workbench/06 補：ADR 0068 §9 只點名前三個，`free` 沒有格式規則、只借
# humanizer-zh-tw.md 去 AI 味）。
_METHODOLOGY_LABELS = {
    "copy": "素材工作檯文案",
    "image_prompt": "素材工作檯圖片提示詞",
    "video_script": "素材工作檯影片腳本",
    "free": "素材工作檯自由生成",
}

_PATH_RE = re.compile(r"^([a-z_]+)(?:\[(\d+)\]|\.([a-z_]+))?$")


def _compile_brand_context(conn, brand_id: str, product_ids: list) -> tuple:
    """票 05：對 `request_json.product_ids`（落回單一 `product_id` 的呼叫端見 `_run()`）
    每個 id 各跑一次 `context_compiler.compile()`，用空行接起來；`knowledge_item_ids` 取
    聯集、保留原順序去重。複製自 `app.schedule.jobs._compile_brand_context`（不 import，
    app.schedule 私有，container contract 規則 5 允許複製）——一張 `ad_creative` 工單的
    `product_id` 只是方案的第一個產品，真正的品牌上下文要照方案全部產品組，跟排程模組退休
    前自己產內容那支 task body 同一份讀法。回傳 (prompt 片段, knowledge_item_ids, brand_version)。
    """
    texts, knowledge_item_ids, seen = [], [], set()
    brand_version = None
    for product_id in product_ids:
        text, ids, brand_version, _product_version = context_compiler.compile(
            conn, brand_id, product_id
        )
        texts.append(text)
        for kid in ids:
            if kid not in seen:
                seen.add(kid)
                knowledge_item_ids.append(kid)
    return "\n\n".join(texts), knowledge_item_ids, brand_version


def _replacement_ok(original, value) -> bool:
    """型別守門（票 workbench/04 walk round 2 amendment）：回覆的 `value` 型別要跟原欄位
    一模一樣（物件對物件、字串對字串），原欄位是物件的話，物件的每個鍵都要在——不合就讓
    呼叫端跳過，原值連同它的 ❌ 留著，不讓一段散文（型別不對）或缺鍵的半成品蓋掉一個
    原本結構完整的欄位。"""
    if type(value) is not type(original):
        return False
    if isinstance(original, dict) and not set(original.keys()) <= set(value.keys()):
        return False
    return True


def _original_value(data: dict, path: str):
    """讀出某個 `path`（跟下面 `_apply_replacements` 同一套定址規則）在 `data` 裡現在的值
    ——修正輪的 prompt 要把它連同問題描述一起附上，模型才知道「原本」長什麼樣子，不是
    憑空發明（票 workbench/04 walk round 2 amendment）。讀不到回傳 `None`。"""
    match = _PATH_RE.match(path) if isinstance(path, str) else None
    if not match:
        return None
    key, index, subkey = match.groups()
    if index is not None:
        items = data.get(key)
        i = int(index) - 1
        return items[i] if isinstance(items, list) and 0 <= i < len(items) else None
    if subkey is not None:
        obj = data.get(key)
        return obj.get(subkey) if isinstance(obj, dict) else None
    return data.get(key)


def _shape_hint(path: str, *, fixed_chars: int | None) -> str:
    """修正輪要附的「精確回覆形狀」一句話——數字／鍵名一律用程式算，不讓模型自己猜字數帶
    或欄位鍵（票 workbench/04 walk round 2 amendment）。只覆蓋兩種形狀：`prompts[N]`
    （物件，鍵照舊，字數帶要扣掉固定段）與 `short[N]`／`medium[N]`／`long[N]`（字串＋原字數
    帶）；其他 path 沿用 `fix.md` 本來就有的通用 JSON schema，不多加一句。"""
    match = _PATH_RE.match(path) if isinstance(path, str) else None
    if not match:
        return ""
    key, index, _subkey = match.groups()
    if key == "prompts" and index is not None and fixed_chars is not None:
        keys = ", ".join(validate.VARIABLE_KEYS)
        lo, hi = validate.PROMPT_MIN - fixed_chars, validate.PROMPT_MAX - fixed_chars
        return (
            f"回一個物件，鍵與原值相同（{keys}），外殼會組成 9 行並計字；"
            f"固定段已占 {fixed_chars} 字，變動段合計須落在 {lo}～{hi} 字"
        )
    if key in validate.BODY_BANDS and index is not None:
        lo, hi, _count = validate.BODY_BANDS[key]
        return f"回一個字串，{lo}～{hi} 字"
    return ""


def _fix_item_block(item: dict, *, original, fixed_chars: int | None) -> str:
    lines = [
        f"- path: {item['path']}",
        f"  原值：{json.dumps(original, ensure_ascii=False)}",
        f"  問題：{item['message']}",
    ]
    shape = _shape_hint(item["path"], fixed_chars=fixed_chars)
    if shape:
        lines.append(f"  形狀：{shape}")
    return "\n".join(lines)


def _apply_replacements(data: dict, replacements) -> None:
    """把修正輪回覆的 `replacements` 套進原始資料——只認得到的 path 才套，套不出來的
    （model 亂寫的 path）安靜跳過，不炸掉整個修正輪。`fixed` 整段鎖死：ADR 0068 §7，固定段
    一份 brief 只產一次、逐則比對用，修正輪不准動它，不管回覆點名哪個 path。型別對不上原欄位
    的、或物件缺了原欄位的鍵的，也安靜跳過（`_replacement_ok`，票 workbench/04 walk round 2
    amendment）——原值連同它的 ❌ 留著，不給第二次機會。"""
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
            if isinstance(items, list) and 0 <= i < len(items) and _replacement_ok(items[i], value):
                items[i] = value
        elif subkey is not None:
            obj = data.get(key)
            if isinstance(obj, dict) and subkey in obj and _replacement_ok(obj[subkey], value):
                obj[subkey] = value
        elif key in data and _replacement_ok(data[key], value):
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
    return validate.check_free(data), None  # 'free'


def _fix_call(conn, brand_id: str, context, task_type: str, failing: list, *,
               brief_section: str, original: dict, fixed_chars: int | None) -> dict:
    """ADR 0068 §6：失敗項目一次問完、只問失敗的那幾項——prompt 不重貼原本的部門任務檔／
    方法論（那些內容模型已經看過一次，批次不重生），但每一通 `gateway.run_task` 都是全新
    的無狀態呼叫（ADR 0032）：模型沒有上一通的記憶，所以工單段（`brief_section`，跟第一次
    生成時同一段文字）與每個失敗欄位的原值、問題描述、精確回覆形狀都要重貼一次，不然模型
    只能自己編（票 workbench/04 walk round 2 amendment，修的就是這個）。"""
    fix_text = (DEPARTMENTS_DIR / "fix.md").read_text(encoding="utf-8")
    listing = "\n".join(
        _fix_item_block(item, original=original.get(item["path"]), fixed_chars=fixed_chars)
        for item in failing
    )
    prompt = "\n\n".join([
        fix_text, brief_section, "## 這些欄位沒有通過驗證，只重新回答這些", listing,
    ])
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

    product_ids = request.get("product_ids") or ([product_id] if product_id else [])
    if request.get("use_brand_knowledge") and product_ids:
        brand_context, knowledge_item_ids, brand_version = _compile_brand_context(
            conn, brand_id, product_ids
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
        if not headlines:
            # 票 03 §3：手動 image_prompt 工單在 submit 就會被擋（repository.py
            # `_validate_on_image_texts`），會走到這裡的是 ad_creative 工單——copy／
            # image_prompt 兩個 part 一起排隊，這個 job 先跑到、copy 那個還沒寫出
            # headlines。
            headlines = request.get("on_image_texts") or []
        if not headlines:
            # 兩邊都沒有：不花錢打一通注定被規則擋下的 LLM 呼叫（ADR 0068 §6 money
            # 線），直接讓外層 workbench_generate() 的 except 寫 failed + 這句 last_error。
            raise RuntimeError("沒有圖上文字可用：先產文案，或在工單填圖上文字。")
        prompt = prompts.image_prompt_prompt(
            department_text, methodology_text, brief_section, brand_context, headlines, count
        )
    elif part == "video_script":
        prompt = prompts.video_script_prompt(
            department_text, methodology_text, brief_section, brand_context, count
        )
    else:
        # free：跟 copy 同一種組法，少座標詞彙表、少張數（自由生成沒有則數這個概念）。
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
        fixed_block = data.get("fixed")
        fixed_chars = (
            validate.fixed_block_chars(fixed_block) if isinstance(fixed_block, dict) else None
        )
        original = {item["path"]: _original_value(data, item["path"]) for item in failing}
        fix_row = _fix_call(
            conn, brand_id, context, task_type, failing,
            brief_section=brief_section, original=original, fixed_chars=fixed_chars,
        )
        if fix_row["status"] == "succeeded":
            fix_data = validate.parse_json_only(fix_row.get("rendered_output") or "")
            if fix_data is not None:
                _apply_replacements(data, fix_data.get("replacements"))
        # 批次不重生（ADR 0068 §6）：不管修正輪成不成功都只重跑一次驗證，還不合格就老實
        # 印 ❌，不再問第二次。
        results, rendered = _validate(part, data, vocabulary=vocabulary, count=count)

    if part == "copy":
        # 票 05（ADR 0068 §5 amendment）：文案任務跟著回視覺方向——寫角度的人順手命名畫面。
        # 壞值（不是兩個合法字串之一）退回 None，跟 `validate.check_copy` 同一條規則：
        # `workbench_brief.visual_tone` 的 DB CHECK 只收那兩個字串，寫壞值會讓整筆 UPDATE
        # 失敗，這裡不讓一格壞資料炸掉整個 job。
        # 票 05 fix round（2026-09-09 reject）：這個 sanitise 過的值也要寫回 `body_json`
        # 那份（下面 `body["visual_tone"]`）——之前只寫 `update_brief_visual` 那一份，
        # `body_json` 留著原始壞值，讓 `schedule/state.py` 讀到壞值又轉手塞進
        # `creative_candidate` 的 CHECK，炸掉整支排程 GET。一份值只有一個真身。
        visual_tone = data.get("visual_tone")
        if visual_tone not in validate.VISUAL_TONE_VALUES:
            visual_tone = None
        visual_concept = data.get("visual_concept")
        if not isinstance(visual_concept, str) or not visual_concept:
            visual_concept = None
        repository.update_brief_visual(
            conn, org_id, brand_id, brief_id, visual_tone, visual_concept,
        )

    round_no = repository.next_round(conn, org_id, brand_id, brief_id, part)
    body = dict(data)
    if part == "copy":
        body["visual_tone"] = visual_tone
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
