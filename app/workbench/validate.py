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

from app.workbench import visual
from app.workbench.prompts import COORDINATE_KEYS

BODY_BANDS = {"short": (100, 150), "medium": (300, 500), "long": (800, 1000)}
# 中文標籤，只在這裡打一次——`prompts.copy_prompt` 用 lazy import 讀這兩個字典（見該檔
# `copy_prompt` 檔頭註解：避免跟這支模組的 module-level import 互相循環）。
BAND_LABELS = {"short": "短版", "medium": "中版", "long": "長版"}
# ARCHITECTURE.md §5.6：一輪文案是 5 組完整廣告（body+headline+description），不是
# 三個長度各給不同則數的三個池子——這是「一輪 5 組」唯一寫死的地方，band 本身不再帶數量。
COPY_SET_COUNT = 5
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
    """回傳 `[{"path", "ok", "message"}, ...]`，一個項目一個可定址的欄位——`sets` 裡每組的
    `body`／`headline`／`description` 各自一項，供 `jobs.py` 的修正輪只重問失敗的那幾項
    （ADR 0068 §6「單則重問，批次不重生」）。ARCHITECTURE.md §5.6：一輪是 `COPY_SET_COUNT`
    組完整廣告，每組落在 `copy_length` 指定的那一個長度帶（`BODY_BANDS`，band 本身不再帶
    數量）。"""
    if not isinstance(data, dict):
        return [{"path": "_root", "ok": False, "message": "頂層不是物件"}]

    results = []
    lo, hi = BODY_BANDS[copy_length]
    sets = data.get("sets")
    if not isinstance(sets, list) or len(sets) != COPY_SET_COUNT:
        got = len(sets) if isinstance(sets, list) else "缺欄位"
        results.append({
            "path": "sets", "ok": False, "message": f"數量應為 {COPY_SET_COUNT}，實際 {got}",
        })
    else:
        for i, item in enumerate(sets, start=1):
            if not isinstance(item, dict):
                results.append({"path": f"sets[{i}]", "ok": False, "message": "不是物件"})
                continue
            body = item.get("body")
            body_ok = isinstance(body, str) and lo <= _char_len(body) <= hi
            n = _char_len(body) if isinstance(body, str) else 0
            body_msg = "符合" if body_ok else f"{n} 字，超出 {lo}～{hi} 字範圍"
            results.append({"path": f"sets[{i}].body", "ok": body_ok, "message": body_msg})

            for key, max_len in (("headline", HEADLINE_MAX), ("description", DESCRIPTION_MAX)):
                text = item.get(key)
                n = _char_len(text) if isinstance(text, str) else 0
                ok = isinstance(text, str) and n <= max_len
                msg = "符合" if ok else f"{n} 字，超過 {max_len} 字上限"
                results.append({"path": f"sets[{i}].{key}", "ok": ok, "message": msg})

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


# -- F07-I06: image-prompt round checks (ARCHITECTURE.md §5.8) -------------------------------

_QUOTE_RE = re.compile(r"「([^」]*)」")
_CODE_RE = re.compile(r"(?<![A-Za-z])[a-z]+_[a-z_]+")
_HEADLINE_MAX = 14
_QUOTE_MAX = 22
_QUOTE_COUNT_MAX = 6
_MIN_LAYOUTS = 5
_MIN_DEVICES = 4
_HEADLINE_PREFIX_LEN = 3
_HEADLINE_PREFIX_MAX_SHARE = 2

# 圖上數字：一個數字段（含逗號、小數點）接在計量單位後，或前面接 $／NT$／滿／剩／第，或是一個倒數
# 時間戳 hh:mm:ss——純時鐘 hh:mm 與日期不算（ARCHITECTURE.md §5.8）。
_UNIT_SUFFIX = "元|折|%|％|mg|g|ml|盒|包|入|組|件|顆|堂|次|位|人|天|小時|分鐘"
_FACT_NUMBER_RE = re.compile(
    rf"(?:\$|NT\$|滿|剩|第)(\d[\d,.]*)"
    rf"|(\d[\d,.]*)(?:{_UNIT_SUFFIX})"
    rf"|(\d{{1,2}}:\d{{2}}:\d{{2}})"
)


def trim_image_reply(data, shape: str) -> None:
    """More than `IMAGE_PROMPT_COUNT` `items`（單圖）／2 `concepts`（輪播）are cut to that count,
    in place — ARCHITECTURE.md §5.8's "更多的更多先裁到十／二"。"""
    if not isinstance(data, dict):
        return
    key, limit = ("items", visual.IMAGE_PROMPT_COUNT) if shape == "single" else ("concepts", 2)
    value = data.get(key)
    if isinstance(value, list) and len(value) > limit:
        del value[limit:]


def _fact_numbers(text: str) -> list[str]:
    numbers = []
    for match in _FACT_NUMBER_RE.finditer(text):
        numbers.append(next(g for g in match.groups() if g))
    return numbers


def _check_look(path: str, item, look: str | None) -> dict:
    ok = isinstance(item, dict) and item.get("look") == look
    got = item.get("look") if isinstance(item, dict) else None
    message = "符合" if ok else f"應為 {look}，實際 {got!r}"
    return {"path": f"{path}.look", "ok": ok, "message": message}


def _check_in(path_suffix: str, path: str, item, field: str, choices) -> dict:
    value = item.get(field) if isinstance(item, dict) else None
    ok = value in choices
    return {
        "path": f"{path}.{path_suffix}", "ok": ok,
        "message": "符合" if ok else f"{field} 不在允許清單：{value!r}",
    }


def _check_headline(path: str, headline, quotes: list[str]) -> dict:
    shape_ok = (
        isinstance(headline, list) and 1 <= len(headline) <= 2
        and all(isinstance(h, str) and h for h in headline)
    )
    if not shape_ok:
        return {"path": f"{path}.headline", "ok": False, "message": "headline 應為 1～2 個非空字串"}
    bad = [h for h in headline if len(h) > _HEADLINE_MAX or h not in quotes]
    ok = not bad
    return {
        "path": f"{path}.headline", "ok": ok,
        "message": "符合" if ok else f"未逐字出現在提示詞或超過 {_HEADLINE_MAX} 字：{bad}",
    }


def _check_prompt_ratio(path: str, prompt: str, ratio_token: str) -> dict:
    first = prompt.split("。", 1)[0]
    ok = ratio_token in first
    return {
        "path": f"{path}.prompt_ratio", "ok": ok,
        "message": "符合" if ok else f"第一句沒有比例「{ratio_token}」",
    }


def _check_prompt_format(path: str, prompt: str) -> dict:
    bad = "【" in prompt or bool(_CODE_RE.search(prompt))
    return {
        "path": f"{path}.prompt_format", "ok": not bad,
        "message": "符合" if not bad else "出現「【」或英文代碼片段",
    }


def _check_quotes(path: str, quotes: list[str]) -> dict:
    bad = [s for s in quotes if len(s) > _QUOTE_MAX or "「" in s]
    ok = not bad and len(quotes) <= _QUOTE_COUNT_MAX
    if not ok and not bad:
        message = f"「」字串應 ≤{_QUOTE_COUNT_MAX} 個，實際 {len(quotes)}"
    elif not ok:
        message = f"字串超過 {_QUOTE_MAX} 字或含巢狀「：{bad}"
    else:
        message = "符合"
    return {"path": f"{path}.prompt_quotes", "ok": ok, "message": message}


def _check_leak(path: str, quotes: list[str], leak_terms: list[str], quotable_text: str) -> dict:
    bad = [
        (s, term) for s in quotes for term in leak_terms
        if term and term in s and term not in quotable_text
    ]
    ok = not bad
    return {
        "path": f"{path}.prompt_leak", "ok": ok,
        "message": "符合" if ok else f"圖上出現分類術語：{bad}",
    }


def _check_numbers(path: str, quotes: list[str], quotable_text: str) -> dict:
    bad = [n for s in quotes for n in _fact_numbers(s) if n not in quotable_text]
    ok = not bad
    return {
        "path": f"{path}.prompt_numbers", "ok": ok,
        "message": "符合" if ok else f"數字未出現在可用字句或品牌資料：{bad}",
    }


def _check_negative(path: str, prompt: str) -> dict:
    n = len(visual.NEGATIVE_PATTERN.findall(prompt))
    ok = n <= 1
    message = "符合" if ok else f"負向句 {n} 句，應 ≤1"
    return {"path": f"{path}.prompt_negative", "ok": ok, "message": message}


def _check_item(
    path: str, item, look: str | None, allowed: dict, leak_terms: list[str], quotable_text: str,
    ratio_token: str,
) -> list:
    results = [
        _check_look(path, item, look),
        _check_in("device", path, item, "device", visual.DEVICES),
        _check_in("layout", path, item, "layout", visual.LAYOUTS),
        _check_in("subject_role", path, item, "subject_role", allowed["subject_role"]),
        _check_in("persuasion", path, item, "persuasion", allowed["persuasion"]),
    ]
    prompt = item.get("prompt") if isinstance(item, dict) else None
    if not isinstance(prompt, str):
        results.append({"path": f"{path}.prompt", "ok": False, "message": "缺欄位或型別不對"})
        return results
    quotes = _QUOTE_RE.findall(prompt)
    results.append(_check_headline(path, item.get("headline"), quotes))
    results.append(_check_prompt_ratio(path, prompt, ratio_token))
    results.append(_check_prompt_format(path, prompt))
    results.append(_check_quotes(path, quotes))
    results.append(_check_leak(path, quotes, leak_terms, quotable_text))
    results.append(_check_numbers(path, quotes, quotable_text))
    results.append(_check_negative(path, prompt))
    return results


def _check_card_text(
    path: str, card, leak_terms: list[str], quotable_text: str, ratio_token: str,
) -> list:
    """A 輪播 card's text-only checks (no look／device／layout／subject_role — those live on the
    concept, ARCHITECTURE.md §5.7's "一個 concept 共用一個 device、layout、look 與人物")."""
    prompt = card.get("prompt") if isinstance(card, dict) else None
    if not isinstance(prompt, str):
        return [{"path": f"{path}.prompt", "ok": False, "message": "缺欄位或型別不對"}]
    quotes = _QUOTE_RE.findall(prompt)
    return [
        _check_headline(path, card.get("headline"), quotes),
        _check_prompt_ratio(path, prompt, ratio_token),
        _check_prompt_format(path, prompt),
        _check_quotes(path, quotes),
        _check_leak(path, quotes, leak_terms, quotable_text),
        _check_numbers(path, quotes, quotable_text),
        _check_negative(path, prompt),
    ]


def check_image_reply(
    data, *, shape: str, plan: list, allowed: dict | None, task_rows: dict, leak_terms: list[str],
    quotable_text: str,
) -> list:
    """回傳 `[{"path", "ok", "message"}, ...]`——ARCHITECTURE.md §5.7／§5.8 的圖片提示詞程式檢查，
    不吃任何 token。`plan` 是每一項（單圖）或每一個 concept（輪播）的 `(look, slot)`；`allowed`
    是 `None` 時改讀 `task_rows[image_task]`（自由創作或表格外的受眾——決定 11）。"""
    if not isinstance(data, dict):
        return [{"path": "_root", "ok": False, "message": "頂層不是物件"}]

    results: list = []
    if allowed is None:
        image_task = data.get("image_task")
        row = (task_rows or {}).get(image_task)
        if row is None:
            message = f"缺欄位或不在任務表：{image_task!r}"
            return [{"path": "image_task", "ok": False, "message": message}]
        results.append({"path": "image_task", "ok": True, "message": "符合"})
        resolved_allowed: dict = row
    else:
        resolved_allowed = allowed

    ratio_token = visual.RATIO[shape][0]

    if shape == "single":
        items = data.get("items")
        if not isinstance(items, list):
            return results + [{"path": "items", "ok": False, "message": "缺欄位"}]
        n = len(items)
        count_ok = n >= visual.IMAGE_PROMPT_COUNT
        results.append({
            "path": "items", "ok": count_ok,
            "message": "符合" if count_ok else f"應有 {visual.IMAGE_PROMPT_COUNT} 項，實際 {n}",
        })
        layouts_seen, devices_seen, prefixes = set(), set(), {}
        for i, item in enumerate(items, start=1):
            look = plan[i - 1][0] if i - 1 < len(plan) else None
            results += _check_item(
                f"items[{i}]", item, look, resolved_allowed, leak_terms, quotable_text, ratio_token,
            )
            if isinstance(item, dict):
                if item.get("layout") in visual.LAYOUTS:
                    layouts_seen.add(item["layout"])
                if item.get("device") in visual.DEVICES:
                    devices_seen.add(item["device"])
                headline = item.get("headline")
                if isinstance(headline, list) and headline and isinstance(headline[0], str):
                    prefix = headline[0][:_HEADLINE_PREFIX_LEN]
                    prefixes.setdefault(prefix, []).append(i)
        for prefix, indices in prefixes.items():
            for i in indices[_HEADLINE_PREFIX_MAX_SHARE:]:
                results.append({
                    "path": f"items[{i}].headline_repeat", "ok": False,
                    "message": f"開頭「{prefix}」重複超過 {_HEADLINE_PREFIX_MAX_SHARE} 次",
                })
        n_layouts, n_devices = len(layouts_seen), len(devices_seen)
        layouts_ok = n_layouts >= _MIN_LAYOUTS
        layouts_msg = "符合" if layouts_ok else f"版型應至少 {_MIN_LAYOUTS} 種，實際 {n_layouts}"
        results.append({"path": "items_layouts", "ok": layouts_ok, "message": layouts_msg})
        devices_ok = n_devices >= _MIN_DEVICES
        devices_msg = "符合" if devices_ok else f"手法應至少 {_MIN_DEVICES} 種，實際 {n_devices}"
        results.append({"path": "items_devices", "ok": devices_ok, "message": devices_msg})
        return results

    # carousel
    concepts = data.get("concepts")
    if not isinstance(concepts, list) or len(concepts) != 2:
        got = len(concepts) if isinstance(concepts, list) else "缺欄位"
        return results + [{"path": "concepts", "ok": False, "message": f"要 2 個，實際 {got}"}]
    layouts = []
    for c, concept in enumerate(concepts, start=1):
        cpath = f"concepts[{c}]"
        look = plan[c - 1][0] if c - 1 < len(plan) else None
        if not isinstance(concept, dict):
            results.append({"path": cpath, "ok": False, "message": "不是物件"})
            continue
        subject_choices = resolved_allowed["subject_role"]
        results.append(_check_look(cpath, concept, look))
        results.append(_check_in("device", cpath, concept, "device", visual.DEVICES))
        results.append(_check_in("layout", cpath, concept, "layout", visual.LAYOUTS))
        results.append(_check_in("subject_role", cpath, concept, "subject_role", subject_choices))
        persuasion_choices = resolved_allowed["persuasion"]
        results.append(_check_in("persuasion", cpath, concept, "persuasion", persuasion_choices))
        layouts.append(concept.get("layout"))
        cards = concept.get("cards")
        if not isinstance(cards, list) or len(cards) != 5:
            got = len(cards) if isinstance(cards, list) else "缺欄位"
            cards_path = f"{cpath}.cards"
            results.append({"path": cards_path, "ok": False, "message": f"要 5 張，實際 {got}"})
            continue
        for k, card in enumerate(cards, start=1):
            card_path = f"{cpath}.cards[{k}]"
            results += _check_card_text(card_path, card, leak_terms, quotable_text, ratio_token)
    results.append({
        "path": "concepts_layout", "ok": len(set(layouts)) == len(layouts),
        "message": "符合" if len(set(layouts)) == len(layouts) else "兩個 concept 用了相同版型",
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
