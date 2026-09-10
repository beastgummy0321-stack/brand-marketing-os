"""app/workbench/validate.py — program-side validation, no tokens (ADR 0068 §6): character
ranges, variant counts, coordinates in the vocabulary, headline/description limits, image-prompt
character band and fixed-block presence. Private to app/workbench (container contract §1).

Moved here unchanged in behaviour from `scripts/workbench_probe.py` (ticket 01's probe, now
deleted by ticket 02 — its purpose, one node's output read by a human, is served by this
package instead). The return shape changed from the probe's `(label, ok, message)` tuples to
`{"path", "ok", "message"}` dicts: ticket 02 adds a fix round that re-asks failing items *by
path* (`jobs.py`), a consumer the probe never had, so each check now names one addressable item
instead of one aggregate band.

`parse_json_only` is deliberately strict (a whole-string `json.loads`, not "find the last
`{...}` block") — ADR 0068 §6's JSON-only rule exists precisely to reject prose the model
wraps around a reply; a version that finds a JSON object anywhere in the text would tolerate
prose both before *and after* it and defeat the rule it is supposed to enforce.
"""

import json

from app.workbench.prompts import COORDINATE_KEYS, render_image_prompt

BODY_BANDS = {"short": (100, 150, 5), "medium": (300, 500, 3), "long": (800, 1000, 2)}
# 中文標籤，只在這裡打一次——`prompts.copy_prompt` 用 lazy import 讀這兩個字典（見該檔
# `copy_prompt` 檔頭註解：避免跟這支模組的 module-level import 互相循環）。
BAND_LABELS = {"short": "短版", "medium": "中版", "long": "長版"}
HEADLINE_MAX = 27
DESCRIPTION_MAX = 30
PROMPT_MIN, PROMPT_MAX = 200, 250
FIXED_KEYS = ("format", "capture_style", "human", "must_keep", "forbidden")
VARIABLE_KEYS = ("index", "theme", "text", "environment", "subject", "relation", "authenticity")

# ADR 0047「`visual_tone`：一個欄位、兩個值」——`creative_candidate.visual_tone` 的 DB CHECK
# 逐字沿用這兩個字串；這支模組不發明第三個值。
VISUAL_TONE_VALUES = ("暗調強對比", "暖調生活")


def _char_len(text: str) -> int:
    """字數量法：不含換行符號，標點算在內（票 01 的用詞決定，可逆）。"""
    return len((text or "").replace("\n", ""))


def parse_json_only(rendered_output: str) -> dict | None:
    """整段回覆必須「就是」一個 JSON 物件——去頭尾空白後直接 `json.loads()`，不找 fenced
    code block、不容忍前後文字（ADR 0068 §6）。`strict=False` 只放寬一件事：字串裡的原始
    控制字元（票 01 round 1 發現的模型習慣）；除此之外一個字都不寬容。"""
    text = (rendered_output or "").strip()
    try:
        data = json.loads(text, strict=False)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def vocabulary_by_dimension(coordinates: list) -> dict:
    """`{dimension: {label, ...}}`——`check_copy` 用來判斷模型填的座標值是不是這個品牌
    詞彙表裡真的存在的 label（跟 `app.schedule.repository._resolve_coordinates()` 同一條
    比對規則：比對這個品牌『所有』label，含停用／被否決的，複製、不 import）。"""
    by_dim: dict = {}
    for row in coordinates:
        by_dim.setdefault(row["dimension"], set()).add(row["label"])
    return by_dim


def check_copy(data, vocabulary: dict, copy_length: str) -> list:
    """回傳 `[{"path", "ok", "message"}, ...]`，一個項目一個可定址的欄位（band 內每一則
    各自一項，供 `jobs.py` 的修正輪只重問失敗的那幾則，ADR 0068 §6「單則重問，批次不重
    生」）。票 workbench/T01-02：一次只出 `copy_length` 指定的那一個長度帶——回覆裡若
    夾帶其他 band 的鍵，安靜略過，不報告、不算它壞。"""
    if not isinstance(data, dict):
        return [{"path": "_root", "ok": False, "message": "頂層不是物件"}]

    results = []
    band = copy_length
    lo, hi, count = BODY_BANDS[band]
    items = data.get(band)
    if not isinstance(items, list) or len(items) != count:
        got = len(items) if isinstance(items, list) else "缺欄位"
        results.append({"path": band, "ok": False, "message": f"數量應為 {count}，實際 {got}"})
    else:
        for i, text in enumerate(items, start=1):
            ok = isinstance(text, str) and lo <= _char_len(text) <= hi
            n = _char_len(text) if isinstance(text, str) else 0
            msg = "符合" if ok else f"{n} 字，超出 {lo}～{hi} 字範圍"
            results.append({"path": f"{band}[{i}]", "ok": ok, "message": msg})

    for label, max_len in (("headlines", HEADLINE_MAX), ("descriptions", DESCRIPTION_MAX)):
        items = data.get(label)
        if not isinstance(items, list) or len(items) != 5:
            got = len(items) if isinstance(items, list) else "缺欄位"
            results.append({"path": label, "ok": False, "message": f"數量應為 5，實際 {got}"})
            continue
        for i, text in enumerate(items, start=1):
            n = _char_len(text) if isinstance(text, str) else 0
            ok = isinstance(text, str) and n <= max_len
            msg = "符合" if ok else f"{n} 字，超過 {max_len} 字上限"
            results.append({"path": f"{label}[{i}]", "ok": ok, "message": msg})

    coordinates = data.get("coordinates")
    if not isinstance(coordinates, dict):
        results.append({"path": "coordinates", "ok": False, "message": "缺 coordinates 欄位"})
    else:
        bad_dims = [
            dim for dim in COORDINATE_KEYS
            if coordinates.get(dim) is not None
            and coordinates.get(dim) not in vocabulary.get(dim, set())
        ]
        msg = "全部合格" if not bad_dims else f"對不到：{bad_dims}"
        results.append({"path": "coordinates", "ok": not bad_dims, "message": msg})

    # ADR 0068 §5 amendment（票 05）：文案任務跟著回視覺方向，寫角度的人順手命名畫面。
    visual_tone = data.get("visual_tone")
    tone_ok = visual_tone is None or visual_tone in VISUAL_TONE_VALUES
    results.append({
        "path": "visual_tone", "ok": tone_ok,
        "message": "符合" if tone_ok else f"不是兩個合法值之一或 null：{visual_tone!r}",
    })
    visual_concept = data.get("visual_concept")
    concept_ok = isinstance(visual_concept, str) and bool(visual_concept)
    results.append({
        "path": "visual_concept", "ok": concept_ok,
        "message": "符合" if concept_ok else "缺欄位或空字串",
    })
    return results


def fixed_block_chars(fixed: dict) -> int:
    """固定段（含外殼補的 `prompts.SUBJECT_PREFIX`、模板本身的標籤文字如「場景：」）在渲染
    結果裡占幾字——修正輪（`jobs._fix_call`）用這個數字告訴模型「你要寫的變動段」該落在
    `PROMPT_MIN/MAX` 扣掉這個數字之後的範圍，不讓模型自己猜或用整段 200～250 字誤導。拿
    `render_image_prompt` 對全空的變動段跑一次算出來——模板只有這一份，這裡不重刻。"""
    blank = {k: "" for k in VARIABLE_KEYS}
    return _char_len(render_image_prompt(fixed, blank))


def check_image_prompts(data, count: int) -> tuple:
    """回傳 `(結果清單, 渲染好的提示詞清單)`——跟 `scripts/workbench_probe.py::
    validate_image_prompts` 同一套檢查邏輯（未改行為：字數帶＋固定欄位逐字出現），結果
    清單換成 `{"path", "ok", "message"}`。`fixed` 只驗一次、不逐則重複（ADR 0068 §7：
    固定段整份 brief 只產一次，每一則提示詞的檢查是「這份固定段的逐字內容有沒有出現在
    這一則的渲染結果裡」，不是「這一則自己有沒有另一份固定段」——回覆的形狀本來就只有
    一份頂層 `fixed`，沒有逐則欄位）。渲染呼叫 `prompts.render_image_prompt`——渲染邏輯
    只有一份，這裡不重複實作。"""
    if not isinstance(data, dict):
        return [{"path": "_root", "ok": False, "message": "頂層不是物件"}], []

    fixed = data.get("fixed")
    if not isinstance(fixed, dict) or any(
        not isinstance(fixed.get(k), str) or not fixed.get(k) for k in FIXED_KEYS
    ):
        return [{"path": "fixed", "ok": False, "message": "缺欄位或有空值"}], []

    prompts = data.get("prompts")
    if not isinstance(prompts, list) or len(prompts) != count:
        got = len(prompts) if isinstance(prompts, list) else "缺欄位"
        return (
            [{"path": "prompts", "ok": False, "message": f"要 {count} 則，實際 {got}"}],
            [],
        )

    results = [
        {"path": "fixed", "ok": True, "message": "齊全"},
        {"path": "prompts", "ok": True, "message": f"{count} 則"},
    ]
    rendered = []
    for i, item in enumerate(prompts, start=1):
        if not isinstance(item, dict) or any(k not in item for k in VARIABLE_KEYS):
            results.append({"path": f"prompts[{i}]", "ok": False, "message": "缺欄位"})
            rendered.append("")
            continue
        text = render_image_prompt(fixed, item)
        rendered.append(text)
        n = _char_len(text)
        missing = [k for k in FIXED_KEYS if fixed[k] not in text]
        if missing:
            msg = f"{n} 字；缺少固定欄位逐字內容：{missing}"
            ok = False
        elif not (PROMPT_MIN <= n <= PROMPT_MAX):
            msg = f"{n} 字，超出 {PROMPT_MIN}～{PROMPT_MAX} 字範圍"
            ok = False
        else:
            msg = f"{n} 字，符合"
            ok = True
        results.append({"path": f"prompts[{i}]", "ok": ok, "message": msg})
    return results, rendered


def check_video_script(data, count: int) -> list:
    """`scripts` 長度 == request，每支至少 3 個 beats、`framework` 非空——沒有字數帶
    （`meta-format-specs.md:52-53` 沒有給影片腳本字數上限，ADR 0047：影片腳本不設字數
    帶）。`hook_pool` 長度至少等於 count 但不逐項比對內容——模型自己挑哪個 hook 配哪支
    腳本，程式只驗「池子夠大」。"""
    if not isinstance(data, dict):
        return [{"path": "_root", "ok": False, "message": "頂層不是物件"}]
    scripts = data.get("scripts")
    if not isinstance(scripts, list) or len(scripts) != count:
        got = len(scripts) if isinstance(scripts, list) else "缺欄位"
        return [{"path": "scripts", "ok": False, "message": f"要 {count} 支，實際 {got}"}]
    results = [{"path": "scripts", "ok": True, "message": f"{count} 支"}]
    for i, script in enumerate(scripts, start=1):
        if not isinstance(script, dict):
            results.append({"path": f"scripts[{i}]", "ok": False, "message": "不是物件"})
            continue
        framework = script.get("framework")
        framework_ok = isinstance(framework, str) and bool(framework.strip())
        beats = script.get("beats")
        beats_ok = isinstance(beats, list) and len(beats) >= 3
        ok = framework_ok and beats_ok
        if ok:
            msg = "符合"
        elif not framework_ok and not beats_ok:
            msg = "framework 空白，beats 不足 3 個"
        elif not framework_ok:
            msg = "framework 空白"
        else:
            n = len(beats) if isinstance(beats, list) else "缺欄位"
            msg = f"beats 應至少 3 個，實際 {n}"
        results.append({"path": f"scripts[{i}]", "ok": ok, "message": msg})
    hook_pool = data.get("hook_pool")
    pool_ok = isinstance(hook_pool, list) and len(hook_pool) >= count
    got = len(hook_pool) if isinstance(hook_pool, list) else "缺欄位"
    results.append({
        "path": "hook_pool", "ok": pool_ok,
        "message": "符合" if pool_ok else f"至少要 {count} 個，實際 {got}",
    })
    return results


def check_free(data) -> list:
    """`items` 非空清單，每則 `{label, value}` 都要是非空字串——ADR 0068 §9 沒有給
    `free` 自己的方法論或格式規則，這是它唯一的驗證（票 workbench/06 contradiction
    check 第三條：型別對但是空字串不算合格，那不是使用者能用的內容）。"""
    if not isinstance(data, dict):
        return [{"path": "_root", "ok": False, "message": "頂層不是物件"}]
    items = data.get("items")
    if not isinstance(items, list) or not items:
        got = len(items) if isinstance(items, list) else "缺欄位"
        return [{"path": "items", "ok": False, "message": f"至少要 1 則，實際 {got}"}]
    results = [{"path": "items", "ok": True, "message": f"{len(items)} 則"}]
    for i, item in enumerate(items, start=1):
        ok = (
            isinstance(item, dict)
            and isinstance(item.get("label"), str) and bool(item["label"])
            and isinstance(item.get("value"), str) and bool(item["value"])
        )
        results.append({
            "path": f"items[{i}]", "ok": ok,
            "message": "符合" if ok else "缺欄位、型別不對，或 label／value 是空字串",
        })
    return results
