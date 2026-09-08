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
HEADLINE_MAX = 27
DESCRIPTION_MAX = 30
PROMPT_MIN, PROMPT_MAX = 200, 250
FIXED_KEYS = ("format", "capture_style", "human", "must_keep", "forbidden")
VARIABLE_KEYS = ("index", "theme", "text", "environment", "subject", "relation", "authenticity")


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


def check_copy(data, vocabulary: dict) -> list:
    """回傳 `[{"path", "ok", "message"}, ...]`，一個項目一個可定址的欄位（band 內每一則
    各自一項，供 `jobs.py` 的修正輪只重問失敗的那幾則，ADR 0068 §6「單則重問，批次不重
    生」）。"""
    if not isinstance(data, dict):
        return [{"path": "_root", "ok": False, "message": "頂層不是物件"}]

    results = []
    for band, (lo, hi, count) in BODY_BANDS.items():
        items = data.get(band)
        if not isinstance(items, list) or len(items) != count:
            got = len(items) if isinstance(items, list) else "缺欄位"
            results.append({"path": band, "ok": False, "message": f"數量應為 {count}，實際 {got}"})
            continue
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
    return results


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
    """`count == request`，每則非空——沒有字數帶（`meta-format-specs.md:52-53` 沒有給影片
    腳本字數上限，ADR 0047：影片腳本不設字數帶）。"""
    if not isinstance(data, dict):
        return [{"path": "_root", "ok": False, "message": "頂層不是物件"}]
    scripts = data.get("scripts")
    if not isinstance(scripts, list) or len(scripts) != count:
        got = len(scripts) if isinstance(scripts, list) else "缺欄位"
        return [{"path": "scripts", "ok": False, "message": f"要 {count} 則，實際 {got}"}]
    results = [{"path": "scripts", "ok": True, "message": f"{count} 則"}]
    for i, text in enumerate(scripts, start=1):
        ok = isinstance(text, str) and bool(text.strip())
        results.append({
            "path": f"scripts[{i}]", "ok": ok, "message": "符合" if ok else "空白或非字串",
        })
    return results
