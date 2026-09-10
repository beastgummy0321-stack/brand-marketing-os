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

_PATH_RE = re.compile(r"^([a-z_]+)(?:\[(\d+)\])?(?:\.([a-z_]+))?$")

NO_PHOTO_LINE = "無參考商品照，畫面以情境與人物為主，不畫商品特寫。"


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
    """讀出某個 `path`（跟下面 `_apply_replacements` 同一套定址規則，含
    `angles[3].on_image_line` 這種索引後接子鍵的形狀）在 `data` 裡現在的值——修正輪的
    prompt 要把它連同問題描述一起附上，模型才知道「原本」長什麼樣子，不是憑空發明（票
    workbench/04 walk round 2 amendment）。讀不到回傳 `None`。"""
    match = _PATH_RE.match(path) if isinstance(path, str) else None
    if not match:
        return None
    key, index, subkey = match.groups()
    if index is not None:
        items = data.get(key)
        i = int(index) - 1
        if not (isinstance(items, list) and 0 <= i < len(items)):
            return None
        item = items[i]
        if subkey is not None:
            return item.get(subkey) if isinstance(item, dict) else None
        return item
    if subkey is not None:
        obj = data.get(key)
        return obj.get(subkey) if isinstance(obj, dict) else None
    return data.get(key)


def _shape_hint(path: str) -> str:
    """修正輪要附的「精確回覆形狀」一句話——數字／鍵名一律用程式算，不讓模型自己猜字數帶
    （票 workbench/04 walk round 2 amendment）。只覆蓋一種形狀：`short[N]`／`medium[N]`／
    `long[N]`（字串＋原字數帶）；其他 path（含 `hero.*`、`angles[n].*`）沿用 `fix.md` 本來
    就有的通用 JSON schema，不多加一句。"""
    match = _PATH_RE.match(path) if isinstance(path, str) else None
    if not match:
        return ""
    key, index, _subkey = match.groups()
    if key in validate.BODY_BANDS and index is not None:
        lo, hi, _count = validate.BODY_BANDS[key]
        return f"回一個字串，{lo}～{hi} 字"
    return ""


def _fix_item_block(item: dict, *, original) -> str:
    lines = [
        f"- path: {item['path']}",
        f"  原值：{json.dumps(original, ensure_ascii=False)}",
        f"  問題：{item['message']}",
    ]
    shape = _shape_hint(item["path"])
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
            if not (isinstance(items, list) and 0 <= i < len(items)):
                continue
            if subkey is not None:
                obj = items[i]
                if isinstance(obj, dict) and subkey in obj and _replacement_ok(obj[subkey], value):
                    obj[subkey] = value
            elif _replacement_ok(items[i], value):
                items[i] = value
        elif subkey is not None:
            obj = data.get(key)
            if isinstance(obj, dict) and subkey in obj and _replacement_ok(obj[subkey], value):
                obj[subkey] = value
        elif key in data and _replacement_ok(data[key], value):
            data[key] = value


def _validate(part: str, data, *, vocabulary: dict, count, copy_length: str = "short",
              mode: str | None = None, quotable_text: str = "") -> tuple:
    """回傳 `(結果清單, 渲染清單或 None)`——`image_prompt` 的渲染不從這裡出來，見
    `_render_image_prompt()`；這裡第二個值一律 `None`。"""
    if part == "copy":
        return validate.check_copy(data, vocabulary, copy_length), None
    if part == "image_prompt":
        assert mode is not None  # 呼叫端（`_run`）永遠帶 mode，這裡只是讓型別檢查放行
        return (
            validate.check_image_prompt(data, mode=mode, count=count, quotable_text=quotable_text),
            None,
        )
    if part == "video_script":
        return validate.check_video_script(data, count), None
    return validate.check_free(data), None  # 'free'


def _product_line(conn, brand_id: str, product_id: str | None, product: dict | None) -> str:
    """『這則圖片提示詞【商品】那一行寫什麼』的唯一判斷規則（票 F01-T03-I02）：這張工單
    有 `product_id`，且 `bi_repo.list_official_assets()` 至少有一列 `asset_kind ==
    "product_photo"` 且 `product_id` 跟這張工單的相同——兩個條件都成立才敢說「有參考商品
    照」，其他情況（沒有 product_id、或有 product_id 但找不到那張商品的產品照）一律回
    `NO_PHOTO_LINE`，不去猜模型看不到的東西。這個讀取不包 try/except：同一條連線
    （`app/core/db.py` `connection()`）上一個失敗的敘述會讓整條交易中止，吞掉例外只會
    藏住第一個真正的原因，讓後面的敘述跟著失敗卻看不出來是為什麼。"""
    if product_id is None:
        return NO_PHOTO_LINE
    assets = bi_repo.list_official_assets(conn, brand_id)
    has_photo = any(
        row["asset_kind"] == "product_photo" and row["product_id"] == product_id
        for row in assets
    )
    if not has_photo:
        return NO_PHOTO_LINE
    name = (product or {}).get("name") or ""
    return f"見參考商品照：{name}。不重述外觀。"


def _vocabulary_phrase(rows: list, dimension: str, label: str) -> str:
    """`<label>——<situation>`；那個 label 在詞彙表裡沒有 `situation` 說明時只回 label
    本身。用在【這則的訴求】與【輸出】兩行，跟 `prompts.coordinate_vocabulary_text` 同一條
    「破折號後面是說明」規則。"""
    for row in rows:
        if row["dimension"] == dimension and row["label"] == label:
            situation = (row["attributes"] or {}).get("situation") or ""
            return f"{label}——{situation}" if situation else label
    return label


def _fix_call(conn, brand_id: str, context, task_type: str, failing: list, *,
               brief_section: str, original: dict) -> dict:
    """ADR 0068 §6：失敗項目一次問完、只問失敗的那幾項——prompt 不重貼原本的部門任務檔／
    方法論（那些內容模型已經看過一次，批次不重生），但每一通 `gateway.run_task` 都是全新
    的無狀態呼叫（ADR 0032）：模型沒有上一通的記憶，所以工單段（`brief_section`，跟第一次
    生成時同一段文字）與每個失敗欄位的原值、問題描述、精確回覆形狀都要重貼一次，不然模型
    只能自己編（票 workbench/04 walk round 2 amendment，修的就是這個）。"""
    fix_text = (DEPARTMENTS_DIR / "fix.md").read_text(encoding="utf-8")
    listing = "\n".join(
        _fix_item_block(item, original=original.get(item["path"])) for item in failing
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


def _render_image_prompt(data: dict, *, mode: str, style_block: str, product_line: str,
                          audience_line: str, appeal_line: str, appeal_sentence: str,
                          quotable_lines: list, output_line: str, purpose_line: str,
                          count: int) -> dict:
    """`image_prompt` 的渲染不從這裡出來——`_run` 在修正輪結束後一律呼叫
    `_render_image_prompt()`，不論驗證是否通過；沒過的項目照樣渲染，❌ 記在
    `body_json.validation`（票 F01-T03-I02）。渲染邏輯只有一份，`prompts.render_*` 對
    缺欄位容忍，這裡不重複實作、也不擋壞資料。"""
    variant_prompt = prompts.render_variant_prompt(
        count=count, appeal_sentence=appeal_sentence, quotable_lines=quotable_lines,
        output_line=output_line if mode == "variant" else "", style_block=style_block,
    )
    if mode == "variant":
        hero_raw = data.get("hero")
        hero: dict = hero_raw if isinstance(hero_raw, dict) else {}
        hero_prompt = prompts.render_hero_prompt(
            hero, style_block=style_block, product_line=product_line,
            audience_line=audience_line, appeal_line=appeal_line,
            quotable_lines=quotable_lines, output_line=output_line,
        )
        return {"hero": hero_prompt, "variant": variant_prompt}
    angles_raw = data.get("angles")
    angles: list = angles_raw if isinstance(angles_raw, list) else []
    exploration_prompt = prompts.render_exploration_prompt(
        angles, style_block=style_block, product_line=product_line,
        purpose_line=purpose_line, quotable_lines=quotable_lines, count=count,
    )
    return {"exploration": exploration_prompt, "variant": variant_prompt}


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

    copy_length = request.get("copy_length") or "short"
    vocabulary: dict = {}
    image_prompt_ctx: dict = {}
    image_prompt_quotable_text = ""
    if part == "copy":
        coordinate_rows = repository.list_coordinate_vocabulary(conn, org_id, brand_id)
        vocabulary = validate.vocabulary_by_dimension(coordinate_rows)
        coordinate_text = prompts.coordinate_vocabulary_text(coordinate_rows)
        prompt = prompts.copy_prompt(
            department_text, methodology_text, brief_section, brand_context, coordinate_text,
            copy_length,
        )
    elif part == "image_prompt":
        # 模式只看工單來源，其他都不決定（票 F01-T03-I02）。
        mode = "variant" if brief.get("source_kind") == "schedule_node" else "exploration"
        coordinate_rows = repository.list_coordinate_vocabulary(conn, org_id, brand_id)
        coordinates_snapshot = brief.get("coordinates_snapshot_json") or {}
        audience = coordinates_snapshot.get("audience") or ""
        pain = coordinates_snapshot.get("pain") or ""
        audience_line = f"{audience}；痛點：{pain}" if (audience or pain) else ""
        angle_label = coordinates_snapshot.get("angle") or ""
        hook_label = coordinates_snapshot.get("hook") or ""
        appeal_parts = []
        if angle_label:
            angle_phrase = _vocabulary_phrase(coordinate_rows, "angle", angle_label)
            appeal_parts.append(f"切角：{angle_phrase}")
        if hook_label:
            hook_phrase = _vocabulary_phrase(coordinate_rows, "hook", hook_label)
            appeal_parts.append(f"標題公式：{hook_phrase}")
        appeal_line = "；".join(appeal_parts)
        format_label = coordinates_snapshot.get("format") or ""
        if format_label:
            format_phrase = _vocabulary_phrase(coordinate_rows, "format", format_label)
            output_line = f"{format_phrase}，一張"
        else:
            output_line = "一張"
        appeal_sentence = (
            angle_label if (mode == "variant" and angle_label) else "以這張圖原本的主訴求為準"
        )
        purpose_line = request.get("free_text") or "未指定"
        promotion_note = request.get("promotion_note") or ""
        quotable_lines = [line for line in promotion_note.split("\n") if line.strip()]
        image_prompt_quotable_text = "\n".join(quotable_lines) + "\n" + brand_context
        product_line = _product_line(conn, brand_id, product_id, product)

        headline_hint = None
        headlines_output = repository.adopted_output(conn, org_id, brand_id, brief_id, "copy")
        headlines = (headlines_output or {}).get("body_json", {}).get("headlines") or []
        if headlines:
            headline_hint = headlines[0]

        image_prompt_ctx = {
            "mode": mode, "style_block": style["style_block"], "product_line": product_line,
            "audience_line": audience_line, "appeal_line": appeal_line,
            "appeal_sentence": appeal_sentence, "quotable_lines": quotable_lines,
            "output_line": output_line, "purpose_line": purpose_line,
        }
        prompt = prompts.image_prompt_prompt(
            department_text, methodology_text, brief_section, brand_context,
            mode=mode, count=count, quotable_lines=quotable_lines, headline_hint=headline_hint,
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

    validate_kwargs = (
        {"mode": image_prompt_ctx["mode"], "quotable_text": image_prompt_quotable_text}
        if part == "image_prompt" else {}
    )
    results, rendered = _validate(
        part, data, vocabulary=vocabulary, count=count, copy_length=copy_length,
        **validate_kwargs,
    )
    failing = [r for r in results if not r["ok"]]
    if failing:
        original = {item["path"]: _original_value(data, item["path"]) for item in failing}
        fix_row = _fix_call(
            conn, brand_id, context, task_type, failing,
            brief_section=brief_section, original=original,
        )
        if fix_row["status"] == "succeeded":
            fix_data = validate.parse_json_only(fix_row.get("rendered_output") or "")
            if fix_data is not None:
                _apply_replacements(data, fix_data.get("replacements"))
        # 批次不重生（ADR 0068 §6）：不管修正輪成不成功都只重跑一次驗證，還不合格就老實
        # 印 ❌，不再問第二次。
        results, rendered = _validate(
            part, data, vocabulary=vocabulary, count=count, copy_length=copy_length,
            **validate_kwargs,
        )

    if part == "image_prompt":
        # 渲染不論驗證是否通過都跑一次（`_render_image_prompt` 檔頭），不放進上面的
        # `_validate`——渲染跟驗證是兩件事，`rendered` 的形狀（`hero`/`exploration` 一個 +
        # `variant` 一個）跟驗證結果清單完全獨立。
        rendered = _render_image_prompt(data, count=count, **image_prompt_ctx)

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
        body["copy_length"] = copy_length
    if part == "image_prompt":
        body["mode"] = image_prompt_ctx["mode"]
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
