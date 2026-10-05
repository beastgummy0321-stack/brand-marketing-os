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
import random
import re

from app import background
from app.brand_intelligence import repository as bi_repo
from app.core.db import APP_DIR, connection, now_utc
from app.llm import context_compiler, gateway, methodology, providers
from app.workbench import claims, prompts, repository, validate, visual
from app.workbench import identity as identity_mod
from app.workbench import looks as looks_mod

DEPARTMENTS_DIR = APP_DIR / "departments" / "workbench"

# F07-I07（Decision 12）：這一輪的手法清單順序由程式洗牌——測試把它換成 `random.Random(0)`
# 拿到可重現的順序。獨立的 `Random` 實例，不動全域 `random` 模組的狀態。
RNG = random.Random()

# 唯一的供應商實例，比照 app/schedule/jobs.py：測試用
# `mock.patch.object(jobs, "PROVIDER", FakeProvider(...))` 換掉。
PROVIDER = providers.AnthropicProvider()

# 任務型別 -> 方法論對照表列名（app/methodology/README.md，ADR 0068 §9；`free` 那一列
# 票 workbench/06 補：ADR 0068 §9 只點名前三個，`free` 沒有格式規則、只借
# humanizer-zh-tw.md 去 AI 味）。
_METHODOLOGY_LABELS = {
    "copy": "素材工作檯文案",
    "video_script": "素材工作檯影片腳本",
    "free": "素材工作檯自由生成",
}

_PATH_RE = re.compile(r"^([a-z_]+)(?:\[(\d+)\])?(?:\.([a-z_]+))?$")


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


def _shape_hint(path: str, copy_length: str | None) -> str:
    """修正輪要附的「精確回覆形狀」一句話——數字／鍵名一律用程式算，不讓模型自己猜字數帶
    （票 workbench/04 walk round 2 amendment）。`sets[i].body` 讀 `copy_length` 對應的字數
    帶；`sets[i].headline`／`sets[i].description` 讀固定上限。其他 path（含 `hero.*`、
    `angles[n].*`、非文案 part）沿用 `fix.md` 本來就有的通用 JSON schema，不多加一句。"""
    match = _PATH_RE.match(path) if isinstance(path, str) else None
    if not match:
        return ""
    key, index, subkey = match.groups()
    if key == "sets" and index is not None and copy_length is not None:
        if subkey == "body":
            lo, hi = validate.BODY_BANDS[copy_length]
            return f"回一個字串，{lo}～{hi} 字"
        if subkey == "headline":
            return f"回一個字串，{validate.HEADLINE_MAX} 字以內"
        if subkey == "description":
            return f"回一個字串，{validate.DESCRIPTION_MAX} 字以內"
    return ""


def _fix_item_block(item: dict, *, original, copy_length: str | None) -> str:
    lines = [
        f"- path: {item['path']}",
        f"  原值：{json.dumps(original, ensure_ascii=False)}",
        f"  問題：{item['message']}",
    ]
    shape = _shape_hint(item["path"], copy_length)
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


def _validate(part: str, data, *, vocabulary: dict, count, copy_length: str = "short") -> tuple:
    """回傳 `(結果清單, 渲染清單或 None)`——`image_prompt` 不經過這裡，見
    `_run_image_prompt()`：它的檢查（`validate.check_image_reply`）要吃 `plan`／`allowed`
    這些跟這支函式其餘 part 完全無關的東西，混進同一個介面只會逼其他呼叫端也傳這些參數。"""
    if part == "copy":
        return validate.check_copy(data, vocabulary, copy_length), None
    if part == "video_script":
        return validate.check_video_script(data, count), None
    return validate.check_free(data), None  # 'free'


def _fix_call(conn, brand_id: str, context, task_type: str, failing: list, *,
               brief_section: str, original: dict, copy_length: str | None = None) -> dict:
    """ADR 0068 §6：失敗項目一次問完、只問失敗的那幾項——prompt 不重貼原本的部門任務檔／
    方法論（那些內容模型已經看過一次，批次不重生），但每一通 `gateway.run_task` 都是全新
    的無狀態呼叫（ADR 0032）：模型沒有上一通的記憶，所以工單段（`brief_section`，跟第一次
    生成時同一段文字）與每個失敗欄位的原值、問題描述、精確回覆形狀都要重貼一次，不然模型
    只能自己編（票 workbench/04 walk round 2 amendment，修的就是這個）。`copy_length` 只有
    文案任務會傳非 `None`——`sets[i].body` 的字數帶形狀要靠它才算得出來。"""
    fix_text = (DEPARTMENTS_DIR / "fix.md").read_text(encoding="utf-8")
    listing = "\n".join(
        _fix_item_block(item, original=original.get(item["path"]), copy_length=copy_length)
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


# ---------------------------------------------------------------------------
# F07-I07（ARCHITECTURE.md §5.7-§5.10）：一輪圖片提示詞——程式先決定每一格要用哪個風格
# （`looks.allocate()`），模型只填格子；一個 path 只出一筆結果，跟其餘 part 共用
# `_fix_call`／`_apply_replacements`／`_original_value` 的定址規則（`items[n]`／
# `concepts[n]`，一個索引後面可以再接一個子鍵）。
# ---------------------------------------------------------------------------

_IMAGE_COORDINATE_DIMS = ("audience", "pain", "angle", "hook", "proof", "offer")


# F44: the rule itself moved to `repository.resolve_coordinate` so the version reader resolves
# a brief's offer coordinate exactly as this job does; the callers here keep this name.
_resolve_coordinate = repository.resolve_coordinate


def _proof_evidenced(rows: list, available: set[str]) -> list:
    """F38 decision 1: the copy prompt offers only the proof kinds the brand has registered
    evidence for (plus `none`). Drops the other `proof` rows so neither the vocabulary text
    nor `validate.vocabulary_by_dimension` sees them. Only the copy branch filters; the image
    task context keeps resolving old proof keys from the unfiltered rows."""
    allowed = available | {"none"}
    return [r for r in rows if r["dimension"] != "proof" or r.get("key") in allowed]


def _coordinate_label(rows: list, dimension: str, value: str | None) -> tuple[str | None, str]:
    """回 `(label, situation)`——`value` 解不出詞彙表列時，`label` 就是 `value` 本身、
    `situation` 是空字串（工作單照樣看得懂一個品牌自建的座標值，只是沒有補充說明）。"""
    if not value:
        return None, ""
    for row in rows:
        if row["dimension"] == dimension and (row.get("key") == value or row["label"] == value):
            return row["label"], (row["attributes"] or {}).get("situation") or ""
    return value, ""


def _image_task_context(conn, org_id: str, brand_id: str, brand: dict, brief: dict) -> dict:
    """組出這一輪要問模型「這張圖的任務」需要的一切：受眾解析、允許的 subject_role／
    persuasion，以及沒有受眾（或受眾解不出任務表）時整張任務表要怎麼呈現（Decision 11）。"""
    coordinate_rows = repository.list_coordinate_vocabulary(conn, org_id, brand_id)
    snapshot = brief.get("coordinates_snapshot_json") or {}
    audience_raw = snapshot.get("audience")
    audience_key = _resolve_coordinate(coordinate_rows, "audience", audience_raw)
    offer_key = _resolve_coordinate(coordinate_rows, "offer", snapshot.get("offer"))
    proof_key = _resolve_coordinate(coordinate_rows, "proof", snapshot.get("proof"))
    task_row = visual.task_row(audience_key, brand.get("conversion_goal"))

    if task_row is not None:
        allowed: dict | None = {
            "subject_role": task_row["subject_roles"],
            "persuasion": visual.allowed_persuasion(task_row["key"], offer_key, proof_key),
        }
        task_rows_all: dict = {}
        round_audience_key = audience_key
        learnings_audience_key = audience_key
    else:
        allowed = None
        task_rows_all = visual.all_task_rows(brand.get("conversion_goal"), offer_key, proof_key)
        round_audience_key = audience_raw
        learnings_audience_key = None

    audience_label, _situation = _coordinate_label(coordinate_rows, "audience", audience_raw)
    angle_label, _s = _coordinate_label(coordinate_rows, "angle", snapshot.get("angle"))
    hook_label, _s = _coordinate_label(coordinate_rows, "hook", snapshot.get("hook"))
    proof_label, _s = _coordinate_label(coordinate_rows, "proof", snapshot.get("proof"))
    leak_terms = visual.leak_terms(
        audience_label=audience_label, angle_label=angle_label, hook_label=hook_label,
        proof_none_label=proof_label if proof_key == "none" else None,
        task_label=task_row["label"] if task_row is not None else None,
    )
    return {
        "coordinate_rows": coordinate_rows, "snapshot": snapshot, "task_row": task_row,
        "allowed": allowed, "task_rows_all": task_rows_all,
        "round_audience_key": round_audience_key, "learnings_audience_key": learnings_audience_key,
        "leak_terms": leak_terms,
    }


def _image_coordinate_lines(coordinate_rows: list, snapshot: dict) -> list:
    lines = []
    for dim in _IMAGE_COORDINATE_DIMS:
        raw = snapshot.get(dim)
        if not raw:
            continue
        label, situation = _coordinate_label(coordinate_rows, dim, raw)
        text = f"{label}（{situation}）" if situation else str(label)
        lines.append(f"- {prompts.IMAGE_COORDINATE_LABELS[dim]}：{text}")
    return lines


def _image_task_lines(ctx: dict) -> tuple[str, list]:
    task_row = ctx["task_row"]
    if task_row is not None:
        allowed = ctx["allowed"]
        subject_text = "／".join(task_row["subject_roles"])
        persuasion_text = "／".join(allowed["persuasion"])
        task_line = (
            f"這張圖的任務：{task_row['label']}——{task_row['how']}"
            f"（subject_role 只能 {subject_text}；persuasion 只能 {persuasion_text}）"
        )
        return task_line, []
    task_line = "這張圖的任務：先從下表選一個，回在 image_task"
    rows_lines = [
        f"- {key}：{row['label']}——{row['how']}"
        f"（subject_role 只能 {'／'.join(row['subject_role'])}；persuasion 只能 {'／'.join(row['persuasion'])}）"  # noqa: E501
        for key, row in ctx["task_rows_all"].items()
    ]
    return task_line, rows_lines


def _image_tool_schema(shape: str, plan: list, ctx: dict) -> dict:
    plan_looks = list(dict.fromkeys(look for look, _slot in plan))
    if ctx["allowed"] is not None:
        subject_choices = ctx["allowed"]["subject_role"]
        persuasion_choices = ctx["allowed"]["persuasion"]
    else:
        rows = ctx["task_rows_all"].values()
        subject_choices = sorted({r for row in rows for r in row["subject_role"]})
        persuasion_choices = sorted({p for row in rows for p in row["persuasion"]})

    item_props = {
        "title": {"type": "string"},
        "device": {"type": "string", "enum": list(visual.DEVICES)},
        "layout": {"type": "string", "enum": list(visual.LAYOUTS)},
        "look": {"type": "string", "enum": plan_looks},
        "subject_role": {"type": "string", "enum": subject_choices},
        "persuasion": {"type": "string", "enum": persuasion_choices},
        "headline": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 2},
        "prompt": {"type": "string"},
    }
    if shape == "single":
        item_schema = {
            "type": "object", "properties": item_props, "required": list(item_props),
            "additionalProperties": False,
        }
        root_props = {
            "items": {
                "type": "array", "items": item_schema,
                "minItems": visual.IMAGE_PROMPT_COUNT, "maxItems": visual.IMAGE_PROMPT_COUNT,
            },
            "warnings": {"type": "array", "items": {"type": "string"}},
        }
        root_required = ["items", "warnings"]
    else:
        card_schema = {
            "type": "object",
            "properties": {"headline": item_props["headline"], "prompt": {"type": "string"}},
            "required": ["headline", "prompt"], "additionalProperties": False,
        }
        concept_props = {k: v for k, v in item_props.items() if k not in ("headline", "prompt")}
        concept_props["cards"] = {
            "type": "array", "items": card_schema, "minItems": 5, "maxItems": 5,
        }
        concept_schema = {
            "type": "object", "properties": concept_props, "required": list(concept_props),
            "additionalProperties": False,
        }
        root_props = {
            "concepts": {"type": "array", "items": concept_schema, "minItems": 2, "maxItems": 2},
            "warnings": {"type": "array", "items": {"type": "string"}},
        }
        root_required = ["concepts", "warnings"]
    if ctx["allowed"] is None:
        root_props["image_task"] = {"type": "string", "enum": list(ctx["task_rows_all"])}
        root_required = ["image_task", *root_required]
    return {
        "name": "workbench_image_prompt",
        "description": "提交這一輪的圖片提示詞，look 一定要用工作單分配的那一個。",
        "input_schema": {
            "type": "object", "properties": root_props, "required": root_required,
            "additionalProperties": False,
        },
    }


_IMAGE_ITEM_PATH_RE = re.compile(r"^(items|concepts)\[(\d+)\]")


def _image_failing_items(results: list) -> dict:
    """把逐欄位的失敗 path（`items[3].look`、`concepts[1].cards[2].headline`⋯）收斂成
    「整項重問」（`items[3]`／`concepts[1]`），一項可能對到好幾條失敗訊息全部列出；沒有索引
    的整輪失敗（`items_layouts`、`image_task` 等）不收在這裡——那些是 ❌ 留著，不重問
    （票面 Done：「a round-level failure stays ❌」）。"""
    grouped: dict = {}
    for r in results:
        if r["ok"]:
            continue
        match = _IMAGE_ITEM_PATH_RE.match(r["path"])
        if not match:
            continue
        key = f"{match.group(1)}[{match.group(2)}]"
        grouped.setdefault(key, []).append(f"{r['path']}：{r['message']}")
    return grouped


def _image_shape_line(path: str, plan: list, ctx: dict) -> str:
    match = re.match(r"^(items|concepts)\[(\d+)\]$", path)
    assert match is not None  # 呼叫端只會傳 `_image_failing_items()` 產生的 path
    key, index = match.group(1), int(match.group(2))
    look = plan[index - 1][0] if index - 1 <= len(plan) - 1 else None
    if key == "items":
        keys_text = "title、headline、device、layout、look、subject_role、persuasion、prompt"
    else:
        keys_text = (
            "title、device、layout、look、subject_role、persuasion、"
            "cards（5 張，各自 headline／prompt）"
        )
    if ctx["allowed"] is not None:
        allow_text = (
            f"subject_role∈{ctx['allowed']['subject_role']}；persuasion∈{ctx['allowed']['persuasion']}"
        )
    else:
        allow_text = "subject_role／persuasion 依這一輪已經選定的 image_task 那一列"
    return f"回一個物件，鍵：{keys_text}；look 固定回 {look}；{allow_text}"


def _image_fix_call(conn, brand_id: str, context, worksheet: str, data: dict, grouped: dict,
                     plan: list, ctx: dict) -> dict:
    fix_text = (DEPARTMENTS_DIR / "fix.md").read_text(encoding="utf-8")
    blocks = []
    for path, messages in grouped.items():
        original = _original_value(data, path)
        blocks.append("\n".join([
            f"- path: {path}",
            f"  原值：{json.dumps(original, ensure_ascii=False)}",
            f"  問題：{'；'.join(messages)}",
            f"  形狀：{_image_shape_line(path, plan, ctx)}",
        ]))
    prompt = "\n\n".join([
        fix_text, worksheet, "## 這些欄位沒有通過驗證，只重新回答這些", "\n\n".join(blocks),
    ])
    return gateway.run_task(
        conn, PROVIDER, brand_id=brand_id, task_type="workbench_image_prompt",
        prompt_template_id="workbench_image_prompt_fix", prompt_template_version="v1",
        system=None, messages=[{"role": "user", "content": prompt}], context=context,
        options=gateway.TaskOptions(max_tokens=16000, timeout_s=480.0),
    )


def _image_tail(identity: dict, look: str | None) -> str:
    texture = looks_mod.look_texture(look, identity["brand_spec_text"]) if look else ""
    return f"品牌視覺規範：{identity['identity_text']}\n風格規範：{texture}"


def _fingerprint(*, image_task_key, image_task_label, device: str | None, layout: str | None,
                  look: str | None, subject_role: str | None, persuasion: str | None,
                  slot: str | None) -> dict:
    return {
        "image_task": {"key": image_task_key, "label": image_task_label},
        "device": {"key": device, "label": visual.DEVICES.get(device or "", device)},
        "layout": {"key": layout, "label": visual.LAYOUTS.get(layout or "", layout)},
        "look": {"key": look, "label": looks_mod.look_label(look) if look else None},
        "subject_role": {
            "key": subject_role,
            "label": visual.SUBJECT_ROLES.get(subject_role or "", subject_role),
        },
        "persuasion": {
            "key": persuasion, "label": visual.PERSUASIONS.get(persuasion or "", persuasion),
        },
        "slot": {"key": slot, "label": visual.SLOTS.get(slot or "", slot)},
    }


def photo_product_id(assets: list, knowledge_ids: list) -> str | None:
    """F43: the knowledge product whose 商品照 the worksheet's reference line uses -- the first of
    `knowledge_ids` (a bundle has several) with a `product_photo` in `assets`, else the first
    one (`reference_line` then falls back to brand-level photos), else None."""
    for knowledge_id in knowledge_ids:
        if any(a.get("asset_kind") == "product_photo" and a.get("product_id") == knowledge_id
               for a in assets):
            return knowledge_id
    return knowledge_ids[0] if knowledge_ids else None


def _run_image_prompt(conn, org_id: str, brand_id: str, brief_id: str, brief: dict,
                       product: dict | None, product_id: str | None,
                       department_text: str, methodology_text: str, brand_context: str,
                       knowledge_item_ids: list, brand_version: int) -> None:
    brand = bi_repo.get_brand(conn, brand_id)
    assert brand is not None
    request = brief.get("request_json") or {}

    format_key = _resolve_coordinate(
        repository.list_coordinate_vocabulary(conn, org_id, brand_id), "format",
        (brief.get("coordinates_snapshot_json") or {}).get("format"),
    )
    shape = visual.shape_for(format_key)
    n = visual.IMAGE_PROMPT_COUNT if shape == "single" else 2

    ctx = _image_task_context(conn, org_id, brand_id, brand, brief)
    identity = identity_mod.ensure_identity(conn, org_id, brand_id, PROVIDER)
    today = now_utc()
    learn = looks_mod.visual_learnings(conn, brand_id, ctx["learnings_audience_key"], today=today)
    history = repository.look_history(conn, org_id, brand_id, ctx["round_audience_key"])
    alloc = looks_mod.allocate(
        n, fit_looks=identity["fit_looks"],
        excluded=[e["look"] for e in identity["excluded_looks"]],
        winners=learn["winners"], history=history, rng=RNG,
    )
    plan = alloc["plan"]
    round_history = repository.image_round_history(conn, org_id, brand_id)
    recommended_index = looks_mod.recommend(
        plan, alloc["explore_first"], rounds=round_history["rounds"],
        explore_recommended=round_history["explore_recommended"],
    )

    assets = bi_repo.list_official_assets(conn, brand_id)
    knowledge_id = photo_product_id(
        assets, bi_repo.knowledge_product_ids(conn, brand_id, product_id) if product_id else [],
    )
    reference = repository.reference_line(assets, knowledge_id, (product or {}).get("name"))

    promotion_note = request.get("promotion_note") or ""
    quotable_lines = [line for line in promotion_note.split("\n") if line.strip()]
    summary = repository.get_pack_summary(conn, org_id, brand_id, brief.get("pack_id"))
    situation = summary.get("情境") or ""
    key_messages_raw = summary.get("重點訊息")
    key_messages = (
        "、".join(key_messages_raw) if isinstance(key_messages_raw, list)
        else (key_messages_raw or "")
    )
    quotable_text = "\n".join([*quotable_lines, key_messages, brand_context])

    devices = list(visual.DEVICES)
    RNG.shuffle(devices)
    task_line, task_rows_lines = _image_task_lines(ctx)
    prior_titles = repository.previous_round_titles(
        conn, org_id, brand_id, brief_id, "image_prompt",
    )
    coordinate_lines = _image_coordinate_lines(ctx["coordinate_rows"], ctx["snapshot"])

    worksheet = prompts.image_worksheet(
        shape=shape, reference_line=reference, identity_text=identity["identity_text"],
        plan=plan, coordinate_lines=coordinate_lines,
        task_line=task_line, task_rows_lines=task_rows_lines, device_order=devices,
        quotable_lines=quotable_lines, situation=situation, key_messages=key_messages,
        free_text=request.get("free_text"), prior_titles=prior_titles,
        learning_lines=learn["lines"], learning_omitted=learn["omitted"],
    )
    prompt = "\n\n".join(
        filter(None, [department_text, methodology_text, worksheet, brand_context])
    )

    context = gateway.TaskContext(
        context_scope={"brand_id": brand_id, "brief_id": brief_id, "part": "image_prompt"},
        knowledge_item_ids=knowledge_item_ids, brand_version=brand_version, product_version=None,
    )
    tool_schema = _image_tool_schema(shape, plan, ctx)
    task_row = gateway.run_task(
        conn, PROVIDER, brand_id=brand_id, task_type="workbench_image_prompt",
        prompt_template_id="workbench_image_prompt", prompt_template_version="v1",
        system=None, messages=[{"role": "user", "content": prompt}], context=context,
        options=gateway.TaskOptions(max_tokens=16000, timeout_s=480.0, tools=[tool_schema]),
    )
    if task_row["status"] != "succeeded":
        raise RuntimeError(task_row.get("error") or "生成失敗。")

    data = task_row.get("structured_output_json")
    if data is None:
        data = validate.parse_json_only(task_row.get("rendered_output") or "")
    if data is None:
        raise RuntimeError("代理沒有回傳純 JSON，請重新產出一次。")

    validate.trim_image_reply(data, shape)
    task_rows_for_check = ctx["task_rows_all"] if ctx["allowed"] is None else {}
    results = validate.check_image_reply(
        data, shape=shape, plan=plan, allowed=ctx["allowed"], task_rows=task_rows_for_check,
        leak_terms=ctx["leak_terms"], quotable_text=quotable_text,
    )
    grouped = _image_failing_items(results)
    if grouped:
        fix_row = _image_fix_call(conn, brand_id, context, worksheet, data, grouped, plan, ctx)
        if fix_row["status"] == "succeeded":
            fix_data = validate.parse_json_only(fix_row.get("rendered_output") or "")
            if fix_data is not None:
                _apply_replacements(data, fix_data.get("replacements"))
        validate.trim_image_reply(data, shape)
        results = validate.check_image_reply(
            data, shape=shape, plan=plan, allowed=ctx["allowed"], task_rows=task_rows_for_check,
            leak_terms=ctx["leak_terms"], quotable_text=quotable_text,
        )

    if ctx["allowed"] is not None:
        image_task_key = ctx["task_row"]["key"]
        image_task_label = ctx["task_row"]["label"]
    else:
        image_task_key = data.get("image_task")
        image_task_label = ctx["task_rows_all"].get(image_task_key, {}).get("label", image_task_key)

    round_dict = {
        "format": format_key, "audience_key": ctx["round_audience_key"],
        "image_task": image_task_key, "identity_id": identity["id"],
        "identity_text": identity["identity_text"],
        "plan": [{"look": look, "slot": slot} for look, slot in plan],
        "look_order": {"exploit": alloc["exploit_looks"], "explore": alloc["explore_looks"]},
        "recommended_index": recommended_index,
        "recommended_slot": plan[recommended_index - 1][1] if plan else None,
        "learning_ids": learn["ids"],
    }
    validation_lines = [
        ("✅ " if r["ok"] else "❌ ") + f"{r['path']}：{r['message']}" for r in results
    ]
    warnings = data.get("warnings") if isinstance(data.get("warnings"), list) else []

    bodies = []
    if shape == "single":
        items_raw = data.get("items")
        items: list = items_raw if isinstance(items_raw, list) else []
        for i in range(1, n + 1):
            raw_item = items[i - 1] if i - 1 < len(items) else None
            item = raw_item if isinstance(raw_item, dict) else {}
            look, slot = plan[i - 1] if i - 1 < len(plan) else (None, None)
            tail = _image_tail(identity, look)
            prompt_text = item.get("prompt") or ""
            bodies.append({
                "title": item.get("title"), "headline": item.get("headline"),
                "prompt": prompt_text, "text": f"{prompt_text}\n\n{tail}",
                "fingerprint": _fingerprint(
                    image_task_key=image_task_key, image_task_label=image_task_label,
                    device=item.get("device"), layout=item.get("layout"), look=look,
                    subject_role=item.get("subject_role"), persuasion=item.get("persuasion"),
                    slot=slot,
                ),
                "cards": None, "round": round_dict, "validation": validation_lines,
                "warnings": warnings,
            })
    else:
        concepts_raw = data.get("concepts")
        concepts: list = concepts_raw if isinstance(concepts_raw, list) else []
        for c in range(1, 3):
            raw_concept = concepts[c - 1] if c - 1 < len(concepts) else None
            concept = raw_concept if isinstance(raw_concept, dict) else {}
            look, slot = plan[c - 1] if c - 1 < len(plan) else (None, None)
            tail = _image_tail(identity, look)
            cards_value = concept.get("cards")
            cards_raw: list = cards_value if isinstance(cards_value, list) else []
            cards, card_texts = [], []
            for card_raw in cards_raw:
                card_raw = card_raw if isinstance(card_raw, dict) else {}
                card_prompt = card_raw.get("prompt") or ""
                card_text = f"{card_prompt}\n\n{tail}"
                cards.append({
                    "headline": card_raw.get("headline"), "prompt": card_prompt, "text": card_text,
                })
                card_texts.append(card_text)
            first_card = cards[0] if cards else {}
            bodies.append({
                "title": concept.get("title"), "headline": first_card.get("headline"),
                "prompt": first_card.get("prompt"), "text": "\n\n".join(card_texts),
                "fingerprint": _fingerprint(
                    image_task_key=image_task_key, image_task_label=image_task_label,
                    device=concept.get("device"), layout=concept.get("layout"), look=look,
                    subject_role=concept.get("subject_role"), persuasion=concept.get("persuasion"),
                    slot=slot,
                ),
                "cards": cards, "round": round_dict, "validation": validation_lines,
                "warnings": warnings,
            })

    round_no = repository.next_round(conn, org_id, brand_id, brief_id, "image_prompt")
    repository.write_output(
        conn, org_id=org_id, brand_id=brand_id, brief_id=brief_id, part="image_prompt",
        generation_round=round_no, body_json=bodies, coordinates_json=None,
        llm_task_id=task_row["id"],
    )
    repository.mark_brief_status(conn, org_id, brand_id, brief_id, "done")


def _run(conn, org_id: str, brand_id: str, brief_id: str, part: str, count) -> None:
    brief = repository.get_brief(conn, org_id, brand_id, brief_id)
    if brief is None:
        raise RuntimeError(f"找不到工單：{brief_id}")

    product_id = brief.get("product_id")
    product = bi_repo.get_product(conn, brand_id, product_id) if product_id else None
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

    # F44 Contract B: the brief's offer coordinate (a snapshot may carry a key or a label)
    # decides which offer the sources list and what the policy block asks for -- for every part
    # below. A brief without an offer coordinate passes `None`: every available offer, as before.
    vocabulary_rows = repository.list_coordinate_vocabulary(conn, org_id, brand_id)
    offer_key = _resolve_coordinate(
        vocabulary_rows, "offer", (brief.get("coordinates_snapshot_json") or {}).get("offer"),
    )
    claim_sources = claims.sources(conn, brand_id, product_id, offer_key)
    knowledge_item_ids = list(dict.fromkeys([
        *knowledge_item_ids, *[r["id"] for r in claims.prompt_sources(claim_sources)],
    ]))
    brand_context = claims.policy(claim_sources, offer_key) + "\n\n" + brand_context

    task_type = f"workbench_{part}"
    department_text = (DEPARTMENTS_DIR / f"{part}.md").read_text(encoding="utf-8")
    methodology_label = _METHODOLOGY_LABELS.get(part)
    methodology_text = methodology.compile(
        conn, [methodology_label] if methodology_label else [], brand_id=brand_id
    ).text

    if part == "image_prompt":
        # F07-I07：一輪圖片提示詞完全是自己的形狀（程式分配風格、一輪一次模型呼叫寫出
        # 剛好 10 則或 2 組），跟這支函式其餘 part 共用的「一個 body、一份驗證」尾段合不
        # 起來——`_run_image_prompt()` 自己收尾（`write_output`／`mark_brief_status`）。
        _run_image_prompt(
            conn, org_id, brand_id, brief_id, brief, product, product_id,
            department_text, methodology_text, brand_context, knowledge_item_ids, brand_version,
        )
        return

    brief_section = prompts.brief_text(brief, (product or {}).get("name"))
    copy_length = request.get("copy_length") or "short"
    vocabulary: dict = {}
    if part == "copy":
        coordinate_rows = _proof_evidenced(
            vocabulary_rows, bi_repo.available_proof_keys(conn, brand_id),
        )
        vocabulary = validate.vocabulary_by_dimension(coordinate_rows)
        coordinate_text = prompts.coordinate_vocabulary_text(coordinate_rows)
        prompt = prompts.copy_prompt(
            department_text, methodology_text, brief_section, brand_context, coordinate_text,
            copy_length,
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

    results, rendered = _validate(
        part, data, vocabulary=vocabulary, count=count, copy_length=copy_length,
    )
    failing = [r for r in results if not r["ok"]]
    if failing:
        original = {item["path"]: _original_value(data, item["path"]) for item in failing}
        fix_row = _fix_call(
            conn, brand_id, context, task_type, failing,
            brief_section=brief_section, original=original, copy_length=copy_length,
        )
        if fix_row["status"] == "succeeded":
            fix_data = validate.parse_json_only(fix_row.get("rendered_output") or "")
            if fix_data is not None:
                _apply_replacements(data, fix_data.get("replacements"))
        # 批次不重生（ADR 0068 §6）：不管修正輪成不成功都只重跑一次驗證，還不合格就老實
        # 印 ❌，不再問第二次。
        results, rendered = _validate(
            part, data, vocabulary=vocabulary, count=count, copy_length=copy_length,
        )

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
    body["validation"] = [
        ("✅ " if r["ok"] else "❌ ") + f"{r['path']}：{r['message']}" for r in results
    ]
    if rendered is not None:
        body["rendered"] = rendered

    # F02-I02（ARCHITECTURE.md §5.2）：一輪寫幾列版本，逐 part 決定——copy 一輪
    # `COPY_SET_COUNT`（5）版，`video_script` 一輪一支腳本一版（回覆的 `scripts` 沒過
    # `COPY_SET_COUNT`/count 也照實際收到的支數寫，紅燈那一支不假裝湊出使用者要的張數），
    # `free` 一輪 1 版（`image_prompt` 有自己的整套寫法，見 `_run_image_prompt()`，不會
    # 走到這裡）。每一版的 `body_json` 是同一份整輪回覆——`schedule/state.py::
    # _copy_summary()` 讀 `body_json["sets"]` 要看到全部 5 組，不是只看到那一版自己的
    # 那一組（那份契約不在這張票改，見 ARCHITECTURE.md §5.6）。
    if part == "copy":
        version_count = validate.COPY_SET_COUNT
    elif part == "video_script":
        scripts = body.get("scripts")
        version_count = len(scripts) if isinstance(scripts, list) and scripts else 1
    else:
        version_count = 1
    repository.write_output(
        conn, org_id=org_id, brand_id=brand_id, brief_id=brief_id, part=part,
        generation_round=round_no, body_json=[body] * version_count,
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
    background.register("background.workbench_generate", workbench_generate)
