"""app/workbench/validate.py — program-side validation, no tokens (ADR 0068 §6): character
ranges, variant counts, coordinates in the vocabulary, headline/description limits, image-prompt
field shape and the on-image number rule. Private to app/workbench (container contract §1).

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
import re

from app.workbench.prompts import COORDINATE_KEYS

BODY_BANDS = {"short": (100, 150, 5), "medium": (300, 500, 3), "long": (800, 1000, 2)}
# 中文標籤，只在這裡打一次——`prompts.copy_prompt` 用 lazy import 讀這兩個字典（見該檔
# `copy_prompt` 檔頭註解：避免跟這支模組的 module-level import 互相循環）。
BAND_LABELS = {"short": "短版", "medium": "中版", "long": "長版"}
HEADLINE_MAX = 27
DESCRIPTION_MAX = 30

# 票 F01-T03-I02：圖上數字規則（ARCHITECTURE.md §5.6-§5.9）——一個數字連續段，逗號、
# 小數點都算在同一段裡。
_NUMBER_RE = re.compile(r"\d[\d,.]*")

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


def _number_rule_item(path: str, text: str, quotable_text: str) -> dict:
    """圖上數字規則（ARCHITECTURE.md §5.6-§5.9）：`text` 裡每一段連續數字都要逐字出現在
    `quotable_text`（促銷說明的非空行＋品牌上下文）裡，否則整個欄位不合格；訊息只點名
    第一個違規的數字段，不列出全部。"""
    for match in _NUMBER_RE.finditer(text):
        n = match.group(0)
        if n not in quotable_text:
            return {"path": path, "ok": False, "message": f"數字「{n}」未出現在可用字句或品牌資料"}
    return {"path": path, "ok": True, "message": "符合"}


def _on_image_field_item(path: str, value, quotable_text: str, *, required: bool) -> dict:
    """一個圖上文字欄位（`headline`／`subhead`／`on_image_line`）只出一個 `{"path", "ok",
    "message"}`：形狀不對就是形狀那條訊息，形狀對了再過數字規則——不讓同一個 `path` 出現
    兩筆結果（`jobs.py` 的修正輪照 `path` 定址，一個 path 兩筆會讓它讀到不確定的那一筆）。
    `required=False`（`subhead`）允許 `None`；`required=True`（`headline`／
    `on_image_line`）要求非空字串。"""
    if required:
        if not (isinstance(value, str) and value):
            return {"path": path, "ok": False, "message": "缺欄位或空字串"}
    elif value is None:
        return {"path": path, "ok": True, "message": "符合"}
    elif not isinstance(value, str):
        return {"path": path, "ok": False, "message": "型別必須是字串或 null"}
    return _number_rule_item(path, value, quotable_text)


def check_image_prompt(data, *, mode: str, count: int, quotable_text: str) -> list:
    """回傳 `[{"path", "ok", "message"}, ...]`——票 F01-T03-I02 的新形狀：變體模式驗
    `hero`（`scene`／`person`／`subject_position`／`headline` 非空字串，`subhead` 字串或
    `null`），探索模式驗 `angles`（剛好 `count` 個物件，各自 `name`／`brief`／
    `on_image_line` 非空字串）；`headline`／`subhead`／`on_image_line` 這三個圖上文字欄位
    形狀通過後再過一次數字規則（`_on_image_field_item`），一個 path 只出一筆結果。"""
    if not isinstance(data, dict):
        return [{"path": "_root", "ok": False, "message": "頂層不是物件"}]

    results: list = []
    if mode == "variant":
        hero = data.get("hero")
        if not isinstance(hero, dict):
            return [{"path": "hero", "ok": False, "message": "缺欄位或型別不對"}]
        for key in ("scene", "person", "subject_position"):
            value = hero.get(key)
            ok = isinstance(value, str) and bool(value)
            results.append({
                "path": f"hero.{key}", "ok": ok, "message": "符合" if ok else "缺欄位或空字串",
            })
        results.append(_on_image_field_item(
            "hero.headline", hero.get("headline"), quotable_text, required=True,
        ))
        results.append(
            _on_image_field_item("hero.subhead", hero.get("subhead"), quotable_text, required=False)
        )
        return results

    angles = data.get("angles")
    if not isinstance(angles, list) or len(angles) != count:
        got = len(angles) if isinstance(angles, list) else "缺欄位"
        return [{"path": "angles", "ok": False, "message": f"要 {count} 個，實際 {got}"}]
    for i, angle in enumerate(angles, start=1):
        if not isinstance(angle, dict):
            results.append({"path": f"angles[{i}]", "ok": False, "message": "不是物件"})
            continue
        for key in ("name", "brief"):
            value = angle.get(key)
            ok = isinstance(value, str) and bool(value)
            results.append({
                "path": f"angles[{i}].{key}", "ok": ok,
                "message": "符合" if ok else "缺欄位或空字串",
            })
        results.append(_on_image_field_item(
            f"angles[{i}].on_image_line", angle.get("on_image_line"), quotable_text, required=True,
        ))
    return results


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
