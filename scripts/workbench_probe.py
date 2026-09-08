"""scripts/workbench_probe.py — probe: run the two workbench LLM calls (copy, image prompt)
for one real ad node, and print the writing quality and the 200-250-character image-prompt
budget with real numbers.

Ticket: docs/issues/workbench/01-probe-methodology-and-cli.md

NOT A PRODUCT PATH. Nothing under app/ imports this file — `app/workbench/` does not exist yet
(ticket 02 builds it, ADR 0068). This script writes no table of its own; the only writes are
`gateway.run_task()`'s own `llm_task` rows, exactly like any other LLM call in this repo.

`app.schedule` internals (`tree.py`, `jobs.py`, `repository.py`, `creative.py`) are private
(docs/contracts/schedule.md: "Everything else in the package ... is private and imported by
nothing outside it"), so this script never imports them. What it needs from that module is
copied instead (container contract rule 5 — duplicate code across modules is fine): the "latest
succeeded task row" query (`app/schedule/state.py`'s pattern), the coordinate-vocabulary prompt
section (`app/schedule/jobs.py::_coordinate_vocabulary_text`, copied verbatim), and a minimal
first-deepest-node walk over the raw `schedule_tree` reply (schedule_tree is always exactly
three levels deep — `app/schedule/tree.py::_collect_nodes` enforces depth 3 has no children — so
"first deepest node" is unambiguous without reproducing that module's full validation).

CLI:
    uv run python -m scripts.workbench_probe --brand brd_bughunt --count 6 \
        [--node-key 1.1.1] [--selftest] [--split]

`--split` runs the copy call three times (short-only, medium-only, long-only — the task file's
"本次要出的長度" line switched each time) instead of once. It is a measurement variant for done
-check 5b, never a product decision.
"""

import argparse
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPARTMENTS_DIR = REPO_ROOT / "app" / "departments" / "workbench"
SCRATCH_DIR = REPO_ROOT / ".scratch" / "workbench-probe"

# CONSTITUTION.md 規則 5 簽下的七個維度名稱，逐字沿用（跟 app/schedule/creative.py 的
# COORDINATE_KEYS 同一份清單——複製,不 import，app.schedule 私有，見檔頭註解）。
COORDINATE_KEYS = ("audience", "pain", "angle", "hook", "proof", "offer", "format")

BODY_BANDS = {"short": (100, 150, 5), "medium": (300, 500, 3), "long": (800, 1000, 2)}
HEADLINE_MAX = 27
DESCRIPTION_MAX = 30
PROMPT_MIN, PROMPT_MAX = 200, 250
FIXED_KEYS = ("format", "capture_style", "human", "must_keep", "forbidden")
VARIABLE_KEYS = ("index", "theme", "text", "environment", "subject", "relation", "authenticity")
SUBJECT_PREFIX = "見參考商品照，"

# copy.md 裡逐字出現的那一行——`--split` 模式把它換成單一長度版本（票 §5b）。
COPY_LENGTH_LINE_ALL = "本次要出的長度：短版／中版／長版都要。"
BAND_LABELS = {"short": "短版", "medium": "中版", "long": "長版"}


def _char_len(text: str) -> int:
    """字數量法：不含換行符號，標點算在內（票的用詞決定，可逆）。"""
    return len((text or "").replace("\n", ""))


def _parse_strict_json(rendered_output: str) -> dict | None:
    """票的規則：回覆必須「整段」是一個 JSON 物件——去頭尾空白後直接 json.loads()，不找
    fenced code block、不容忍前後文字。不重用 `app.schedule.plan._extract_last_json_block`
    （那支函式容忍散文＋抓最後一個 fenced block，正是 ADR 0068 §6 JSON-only 規則要擋的）。
    `strict=False` 是標準函式庫本身的開關，只放寬一件事：字串裡的原始控制字元（round 1 發
    現：3/5 回覆的字串裡帶原始換行）。除此之外不寬容——多一個字、少一個括號都是失敗。"""
    text = (rendered_output or "").strip()
    try:
        data = json.loads(text, strict=False)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------------------
# 純函數：渲染與驗證，跟資料庫、跟 LLM 都無關——這段是 --selftest 測的對象。
# ---------------------------------------------------------------------------

def render_prompt(fixed: dict, variable: dict) -> str:
    """`image-prompt-template.md` 第 2 節的 9 行順序（2026-09-09 使用者裁決精簡）。外殼渲染，
    模型從不回傳這個字串；`subject` 由外殼補上「見參考商品照，」前綴（creative-matrix §3.3）。"""
    subject = str(variable["subject"])
    if not subject.startswith(SUBJECT_PREFIX):
        subject = SUBJECT_PREFIX + subject
    return "\n".join([
        f"{variable['index']}｜{variable['theme']} × 「{variable['text']}」",
        f"{fixed['format']}",
        f"攝影形式：{fixed['capture_style']}",
        f"場景：{variable['environment']}",
        f"人物：{fixed['human']}",
        f"主體：{subject}",
        f"關係：{variable['relation']}",
        f"真實感：{variable['authenticity']}",
        f"保留：{fixed['must_keep']}｜禁止：{fixed['forbidden']}",
    ])


def fixed_block_chars(fixed: dict) -> int:
    """固定段單獨的字數（不含變動段）——票要求印出來，讓使用者看見固定段吃掉多少
    200～250 字預算，剩多少給變動段（見票「Contradiction check」第 2 點）。"""
    lines = [
        fixed["format"],
        f"攝影形式：{fixed['capture_style']}",
        f"人物：{fixed['human']}",
        f"保留：{fixed['must_keep']}｜禁止：{fixed['forbidden']}",
    ]
    return sum(_char_len(line) for line in lines)


def _prompts_ok(fixed: dict, rendered: list) -> tuple:
    """兩條規則一起判：每則落在 200～250 字、五個固定欄位逐字出現在每一則裡。
    回傳 (整體是否全部通過, 問題清單)——這是 --selftest 直接測的函式。"""
    problems = []
    for i, text in enumerate(rendered, start=1):
        n = _char_len(text)
        if not (PROMPT_MIN <= n <= PROMPT_MAX):
            problems.append(f"第 {i} 則 {n} 字，超出 {PROMPT_MIN}～{PROMPT_MAX} 字範圍")
        missing = [k for k in FIXED_KEYS if fixed[k] not in text]
        if missing:
            problems.append(f"第 {i} 則缺少固定欄位逐字內容：{missing}")
    return (not problems), problems


def _band_check(items, lo: int, hi: int, expected_count: int, label: str) -> list:
    if not isinstance(items, list) or len(items) != expected_count:
        got = len(items) if isinstance(items, list) else "缺欄位"
        return [(f"{label} 數量＝{expected_count}", False, f"實際 {got}")]
    results = [(f"{label} 數量＝{expected_count}", True, "符合")]
    bad = [
        i + 1 for i, t in enumerate(items)
        if not isinstance(t, str) or not (lo <= _char_len(t) <= hi)
    ]
    results.append((f"{label} 每個 {lo}～{hi} 字", not bad,
                     "全部合格" if not bad else f"第 {bad} 個超出範圍"))
    return results


def _max_len_check(items, max_len: int, expected_count: int, label: str) -> list:
    if not isinstance(items, list) or len(items) != expected_count:
        got = len(items) if isinstance(items, list) else "缺欄位"
        return [(f"{label} 數量＝{expected_count}", False, f"實際 {got}")]
    results = [(f"{label} 數量＝{expected_count}", True, "符合")]
    bad = [i + 1 for i, t in enumerate(items) if not isinstance(t, str) or _char_len(t) > max_len]
    results.append((f"{label} 每個 ≤{max_len} 字", not bad,
                     "全部合格" if not bad else f"第 {bad} 個超字"))
    return results


def validate_copy(data, vocabulary: dict, only_band: str | None = None) -> list:
    """回傳 [(檢查名稱, 通過與否, 訊息)]，每一項印成一行驗證結果，不拋例外。

    回覆是扁平物件：`short`／`medium`／`long` 是頂層鍵，不是巢狀在 `bodies` 裡面（round 1
    發現：巢狀 `bodies` 物件的收尾括號被模型漏掉 5/5 次，票已改成扁平結構）。

    `only_band` 給 `--split` 模式用：只驗那一個長度鍵的數量與字數帶，並且驗另外兩個長度鍵
    確實缺席——模型被交代「只出某版」時，真的沒有多回另外兩版。"""
    if not isinstance(data, dict):
        return [("回覆是一個 JSON 物件", False, "頂層不是物件")]
    results = [("回覆是一個 JSON 物件", True, "是")]

    bands = (only_band,) if only_band else tuple(BODY_BANDS)
    for key in bands:
        lo, hi, count = BODY_BANDS[key]
        results += _band_check(data.get(key), lo, hi, count, key)
    if only_band:
        for other in BODY_BANDS:
            if other == only_band:
                continue
            present = bool(data.get(other))
            results.append((f"{other} 鍵應該缺席（只出 {only_band}）", not present,
                             "缺席" if not present else f"不該出現卻有：{data.get(other)!r}"))

    results += _max_len_check(data.get("headlines"), HEADLINE_MAX, 5, "headlines")
    results += _max_len_check(data.get("descriptions"), DESCRIPTION_MAX, 5, "descriptions")

    coordinates = data.get("coordinates")
    if not isinstance(coordinates, dict):
        results.append(("coordinates 七維都在詞彙表裡", False, "缺 coordinates 欄位"))
    else:
        bad_dims = [dim for dim in COORDINATE_KEYS
                    if coordinates.get(dim) is not None
                    and coordinates.get(dim) not in vocabulary.get(dim, set())]
        results.append(("coordinates 七維都在詞彙表裡", not bad_dims,
                         "全部合格" if not bad_dims else f"對不到：{bad_dims}"))
    return results


def validate_image_prompts(data, count: int) -> tuple:
    """回傳 (驗證結果清單, 渲染好的提示詞清單, fixed_block_chars)。"""
    if not isinstance(data, dict):
        return [("回覆是一個 JSON 物件", False, "頂層不是物件")], [], 0
    results = [("回覆是一個 JSON 物件", True, "是")]

    fixed = data.get("fixed")
    if not isinstance(fixed, dict) or any(
        not isinstance(fixed.get(k), str) or not fixed.get(k) for k in FIXED_KEYS
    ):
        results.append(("fixed 五個欄位齊全", False, "缺欄位或有空值"))
        return results, [], 0
    results.append(("fixed 五個欄位齊全", True, "齊全"))
    fbc = fixed_block_chars(fixed)

    prompts = data.get("prompts")
    if not isinstance(prompts, list) or len(prompts) != count:
        got = len(prompts) if isinstance(prompts, list) else "缺欄位"
        results.append(("prompts 則數＝工單指定的條數", False, f"要 {count} 則，實際 {got}"))
        return results, [], fbc
    results.append(("prompts 則數＝工單指定的條數", True, f"{count} 則"))

    rendered, shape_bad = [], []
    for i, item in enumerate(prompts, start=1):
        if not isinstance(item, dict) or any(k not in item for k in VARIABLE_KEYS):
            shape_bad.append(i)
            rendered.append("")
            continue
        rendered.append(render_prompt(fixed, item))
    results.append(("每則 prompts 欄位齊全", not shape_bad,
                     "全部合格" if not shape_bad else f"第 {shape_bad} 則缺欄位"))

    ok, problems = _prompts_ok(fixed, [r for r in rendered if r])
    results.append((f"每則 {PROMPT_MIN}～{PROMPT_MAX} 字、五個固定欄位逐字出現在每一則", ok,
                     "全部合格" if ok else "；".join(problems)))
    return results, rendered, fbc


# ---------------------------------------------------------------------------
# --selftest：三個 in-memory fixtures，不碰資料庫、不碰網路。
# ---------------------------------------------------------------------------

def _selftest_fixed() -> dict:
    # 基準字數刻意壓低（見 _run_selftest 的 mid_target）：這樣 `_pad_to_chars` 才有空間把
    # fixture 1 灌到 200～250 字帶內，而不是原地卡在一個已經超帶的固定長度。
    return {
        "format": "4:5｜Meta 動態消息", "capture_style": "UGC／iPhone",
        "human": "一位女性，居家便服", "must_keep": "商品輪廓、Logo", "forbidden": "卡通感、AI 感",
    }


def _selftest_variable(index: int) -> dict:
    return {
        "index": index, "theme": "早晨廚房", "text": "一杯搞定早餐",
        "environment": "台灣公寓廚房，晨光斜射進來",
        "subject": "置中，中景，焦點在商品",
        "relation": "咖啡杯在右前景",
        "authenticity": "流理台有使用痕跡",
    }


def _pad_to_chars(fixed: dict, variable: dict, target_chars: int) -> str:
    """把 `environment` 灌長到渲染結果達到 target_chars 字——用來造出剛好落在某個字數
    的 fixture，不必手動數中文字數。"""
    v = dict(variable)
    while _char_len(render_prompt(fixed, v)) < target_chars:
        v["environment"] += "、"
    return render_prompt(fixed, v)


def _run_selftest() -> int:
    fixed = _selftest_fixed()
    mid_target = (PROMPT_MIN + PROMPT_MAX) // 2

    clean = [_pad_to_chars(fixed, _selftest_variable(i), mid_target) for i in range(1, 4)]
    ok1, problems1 = _prompts_ok(fixed, clean)

    too_long = list(clean)
    too_long[1] = _pad_to_chars(fixed, _selftest_variable(2), 260)
    ok2, problems2 = _prompts_ok(fixed, too_long)

    # fixture 3：第二則的渲染結果裡，把 fixed['human'] 的逐字內容換成等長的別的字元
    # （長度不變，隔離「固定欄位逐字出現」這條規則，不跟字數帶規則混在一起）。
    tampered = list(clean)
    swapped = "＊" * len(fixed["human"])
    tampered[1] = tampered[1].replace(fixed["human"], swapped)
    ok3, problems3 = _prompts_ok(fixed, tampered)

    cases = [
        ("fixture 1（乾淨）", True, ok1, problems1),
        ("fixture 2（一則 260 字、超出上限）", False, ok2, problems2),
        ("fixture 3（第二則的 fixed 字串被換掉）", False, ok3, problems3),
    ]
    all_match = True
    for label, expected, actual, problems in cases:
        verdict = "pass" if actual else "fail"
        expect_label = "pass" if expected else "fail"
        match = actual == expected
        all_match = all_match and match
        mark = "" if match else f"（預期 {expect_label}，不符）"
        detail = "；".join(problems) if problems else "無問題"
        print(f"{label}：{verdict}{mark} — {detail}")

    print("selftest 總結：" + ("pass" if all_match else "fail"))
    return 0 if all_match else 1


# ---------------------------------------------------------------------------
# 複製自 app/schedule/（不 import——app.schedule 私有，見檔頭註解）。
# ---------------------------------------------------------------------------

def _latest_succeeded_task(conn, brand_id: str, task_type: str) -> dict | None:
    """跟 `app/schedule/state.py` 用的查法一樣（複製，不 import）：這個品牌這個 task_type
    最新一筆 status='succeeded' 的 llm_task 列。"""
    row = conn.execute(
        "SELECT * FROM llm_task WHERE brand_id = %s AND task_type = %s AND status = 'succeeded' "
        "ORDER BY started_at DESC LIMIT 1",
        (brand_id, task_type),
    ).fetchone()
    return dict(row) if row is not None else None


def _extract_last_json_block(text: str) -> dict | None:
    """讀舊格式（schedule_tree／schedule_creative 的回覆，代理原本被允許夾散文＋回覆最後
    一個 fenced json block）用的抓法，跟 `app.schedule.plan._extract_last_json_block` 同一
    招（複製，不 import）。這支腳本自己兩通呼叫走的是嚴格單一 JSON 物件，見
    `_parse_strict_json`，跟這支函式無關。"""
    matches = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text or "", re.DOTALL)
    if not matches:
        return None
    try:
        data = json.loads(matches[-1])
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _first_deepest_node(rendered_output: str, node_key: str | None):
    """回傳 (name, node_key) 或 None。schedule_tree 固定三層深，第三層永遠沒有 children
    （app/schedule/tree.py::_collect_nodes 的 `depth == 3` 分支強制 children = []），所以
    「最深層節點」就是文件順序（深度優先、前序）第一個沒有 children 的節點；這裡不呼叫
    `tree.build_tree()`（app.schedule 私有、且做了這支腳本用不到的比例加總驗證），只走一遍
    原始 JSON 找節點、順手算出跟 tree.py 同一套 node_key（1-based、點分隔）。"""
    data = _extract_last_json_block(rendered_output)
    if data is None:
        return None
    nodes = data.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return None

    found: dict = {}

    def walk(items, parent_key: str) -> None:
        if not isinstance(items, list):
            return
        for i, raw in enumerate(items, start=1):
            if not isinstance(raw, dict):
                continue
            key = f"{parent_key}.{i}" if parent_key else str(i)
            children = raw.get("children")
            if isinstance(children, list) and children:
                walk(children, key)
                continue
            name = raw.get("name")
            if isinstance(name, str) and name:
                found.setdefault(key, name)

    walk(nodes, "")
    if not found:
        return None
    if node_key:
        name = found.get(node_key)
        return (name, node_key) if name else None
    first_key = next(iter(found))
    return (found[first_key], first_key)


def _creative_for_node(rendered_output: str, node_name: str, node_key: str) -> dict:
    """回傳 {"visual_tone", "visual_concept", "coordinates"}，找不到都是 None／{}。
    比對規則簡化過——正式匹配見 `app.schedule.creative.build_creative`（私有、同名節點要
    排隊比對，這支探針只取第一筆對上的）：node_key 對得上就用那筆，否則退回第一筆
    node 名稱相同的。"""
    empty = {"visual_tone": None, "visual_concept": None, "coordinates": {}}
    data = _extract_last_json_block(rendered_output)
    if data is None:
        return empty
    creatives = data.get("creatives")
    if not isinstance(creatives, list):
        return empty
    by_key = [c for c in creatives if isinstance(c, dict) and c.get("node_key") == node_key]
    by_name = [c for c in creatives if isinstance(c, dict) and c.get("node") == node_name]
    chosen = (by_key or by_name or [None])[0]
    if not isinstance(chosen, dict):
        return empty
    coordinates = chosen.get("coordinates")
    return {
        "visual_tone": chosen.get("visual_tone"),
        "visual_concept": chosen.get("visual_concept"),
        "coordinates": coordinates if isinstance(coordinates, dict) else {},
    }


def _coordinate_rows(conn, org_id: str, brand_id: str) -> list:
    """跟 `app/schedule/repository.list_coordinates()` 同一份查法（複製，不 import）；不呼叫
    它的 `ensure_coordinates_seeded()`——探針只讀，不該幫使用者把座標種子寫進去。"""
    rows = conn.execute(
        "SELECT c.*, EXISTS (SELECT 1 FROM feedback f WHERE f.scope = 'coordinate'"
        " AND f.coordinate_id = c.id AND f.lifted_at IS NULL) AS rejected"
        " FROM brand_coordinate c WHERE c.org_id = %s AND c.brand_id = %s"
        " ORDER BY c.dimension, c.category NULLS LAST, c.label",
        (org_id, brand_id),
    ).fetchall()
    return [
        {"dimension": r["dimension"], "label": r["label"],
         "attributes": r["attributes_json"] or {}, "disabled_at": r["disabled_at"],
         "rejected": bool(r["rejected"])}
        for r in (dict(row) for row in rows)
    ]


def _coordinate_vocabulary_text(coordinates: list) -> str:
    """複製自 `app/schedule/jobs.py::_coordinate_vocabulary_text`（票 T8b；不 import，
    app.schedule 私有）。座標詞彙表放整份 prompt 的最後一段，理由見原函式的檔頭註解：
    同一顆模型、同一份詞彙表，指令排在兩萬字之前只填得出 1/7，排在最後填得出 7/7。"""
    by_dimension: dict = {}
    for row in coordinates:
        if row["disabled_at"] is not None or row["rejected"]:
            continue
        situation = (row["attributes"] or {}).get("situation") or ""
        by_dimension.setdefault(row["dimension"], []).append(
            f"- {row['label']}" + (f"——{situation}" if situation else "")
        )
    sections = [
        f"### {dimension}\n" + "\n".join(by_dimension[dimension])
        for dimension in COORDINATE_KEYS if by_dimension.get(dimension)
    ]
    if not sections:
        return ""
    return "\n\n".join([
        "## 這個品牌的座標詞彙表",
        "上面每一則內容的 `coordinates` 七個鍵**都要填**，值就是下面各段列出的 label 原文"
        "（破折號後面是這個值什麼時候用，是說明、不是值的一部分）。"
        "沒放證明填「無證明」、沒給優惠填「無優惠」——那是值，不是 `null`。",
        *sections,
    ])


def _vocabulary_by_dimension(coordinates: list) -> dict:
    """跟 `app.schedule.repository._resolve_coordinates()` 同一條比對規則（複製，不
    import）：比對這個品牌『所有』label（含停用／被否決的——那支函式的查詢本來就沒有排除
    它們），不是只比對餵給模型看的那份精簡詞彙表。"""
    by_dim: dict = {}
    for row in coordinates:
        by_dim.setdefault(row["dimension"], set()).add(row["label"])
    return by_dim


def _worksheet_text(*, node_name, node_key, product_name, coordinates, visual_tone,
                     visual_concept, count, headlines=None) -> str:
    lines = [
        "## 這張工單",
        f"節點名稱：{node_name}",
        f"node_key：{node_key}",
        f"產品：{product_name or '（無）'}",
    ]
    if coordinates:
        lines.append("既有座標（延續語氣參考用，非必須照抄）：" +
                      json.dumps(coordinates, ensure_ascii=False))
    lines.append(f"visual_tone：{visual_tone or '（無）'}")
    lines.append(f"visual_concept：{visual_concept or '（無）'}")
    lines.append("風格：UGC 手機實拍（預設；手機視角、現場光、生活雜物與不完美構圖是特色）")
    lines.append(
        "文案長度與變體數：短 100～150 字 5 個（目標 140）、中 300～500 字 3 個（目標 450）、"
        "長 800～1000 字 2 個（目標 950）、"
        "標題 5 個（各 27 字以內）、說明 5 個（各 30 字以內）。"
    )
    lines.append(f"這張工單要幾則圖片提示詞：工單指定的張數＝{count}。")
    if headlines:
        lines.append("已採用的標題（圖上文字只能從這裡逐字取用，不得自己發明）：" +
                      "、".join(f"「{h}」" for h in headlines))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# main：讀資料庫、組 prompt、打兩通 gateway.run_task()、印驗證結果、寫 .scratch 紀錄。
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.workbench_probe")
    parser.add_argument("--brand")
    parser.add_argument("--count", type=int)
    parser.add_argument("--node-key")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument(
        "--split", action="store_true",
        help="三個 workbench_copy 呼叫（短／中／長各一通）取代一通；同一份任務檔，只把"
             "「本次要出的長度」那一行換成單一長度（票 §5b 的測量變體，不是產品決策）。",
    )
    args = parser.parse_args(argv)

    if args.selftest:
        return _run_selftest()
    if not args.brand or not args.count:
        parser.error("--brand 與 --count 為必填（--selftest 除外）")

    # deferred (觸發 _load_dotenv() 與 BRAND_OS_ENV 驗證，跟 scripts/acceptance/*.py 同一套
    # 慣例，見那兩支檔案)：只為了它 import 時的副作用，本身不再被引用。
    import app.main  # noqa: E402,F401
    from app.brand_intelligence import repository as bi_repo
    from app.core.db import connection
    from app.llm import context_compiler, gateway, methodology, providers

    log_lines: list = []

    def emit(text: str = "") -> None:
        print(text)
        log_lines.append(text)

    with connection() as conn:
        brand = bi_repo.get_brand(conn, args.brand)
        if brand is None:
            print(f"找不到品牌：{args.brand}")
            return 1
        org_id = brand["org_id"]

        tree_row = _latest_succeeded_task(conn, args.brand, "schedule_tree")
        if tree_row is None:
            print("這個品牌沒有成功過的 schedule_tree，先展開一次活動樹再跑這支探針。")
            return 1
        node = _first_deepest_node(tree_row.get("rendered_output") or "", args.node_key)
        if node is None:
            print(f"在最新一次 schedule_tree 裡找不到節點：{args.node_key or '(第一個最深層節點)'}")
            return 1
        node_name, node_key = node

        plan_scope = tree_row.get("context_scope_json") or {}
        plan_row = gateway.get_task(conn, plan_scope.get("source_plan_task_id") or "")
        plan_row_scope = (plan_row.get("context_scope_json") or {}) if plan_row else {}
        product_ids = plan_row_scope.get("product_ids") or []
        product_id = product_ids[0] if product_ids else None
        product = bi_repo.get_product(conn, args.brand, product_id) if product_id else None

        creative_row = _latest_succeeded_task(conn, args.brand, "schedule_creative")
        creative = (
            _creative_for_node(creative_row.get("rendered_output") or "", node_name, node_key)
            if creative_row is not None
            else {"visual_tone": None, "visual_concept": None, "coordinates": {}}
        )

        coordinate_rows = _coordinate_rows(conn, org_id, args.brand)
        vocabulary = _vocabulary_by_dimension(coordinate_rows)
        coordinate_text = _coordinate_vocabulary_text(coordinate_rows)

        brand_context, knowledge_item_ids, brand_version, _product_version = (
            context_compiler.compile(conn, args.brand, product_id)
        )

        emit(f"節點：{node_name}（{node_key}）／product：{(product or {}).get('name') or '(無)'}")

        context = gateway.TaskContext(
            context_scope={
                "brand_id": args.brand, "probe": "workbench_probe", "node_key": node_key,
            },
            knowledge_item_ids=knowledge_item_ids, brand_version=brand_version,
            product_version=None,
        )

        # ---- 第一通：文案（--split 給的話拆成三通，短／中／長各一通；見票 §5b） ----
        copy_department = (DEPARTMENTS_DIR / "copy.md").read_text(encoding="utf-8")
        if args.split and COPY_LENGTH_LINE_ALL not in copy_department:
            emit(f"--split 需要的那一行不在 copy.md 裡：{COPY_LENGTH_LINE_ALL!r}")
            return 1
        copy_methodology = methodology.compile(conn, ["素材工作檯文案"], brand_id=args.brand)
        worksheet_copy = _worksheet_text(
            node_name=node_name, node_key=node_key, product_name=(product or {}).get("name"),
            coordinates=creative["coordinates"], visual_tone=creative["visual_tone"],
            visual_concept=creative["visual_concept"], count=args.count,
        )

        def _copy_call(department_text: str) -> dict:
            prompt = "\n\n".join(filter(None, [
                department_text, copy_methodology.text, worksheet_copy, brand_context,
                coordinate_text,
            ]))
            return gateway.run_task(
                conn, providers.AnthropicProvider(), brand_id=args.brand,
                task_type="workbench_copy", prompt_template_id="workbench_copy",
                prompt_template_version="probe", system=None,
                messages=[{"role": "user", "content": prompt}], context=context,
                options=gateway.TaskOptions(max_tokens=16000, timeout_s=480.0),
            )

        bands_to_run = list(BAND_LABELS) if args.split else [None]
        combined_copy: dict = {
            "coordinates": {}, "short": [], "medium": [], "long": [],
            "headlines": [], "descriptions": [], "warnings": [],
        }
        for band in bands_to_run:
            if band is None:
                department_text, call_label = copy_department, "workbench_copy"
            else:
                department_text = copy_department.replace(
                    COPY_LENGTH_LINE_ALL,
                    f"本次要出的長度：只出{BAND_LABELS[band]}。另外兩個長度鍵不要出現在"
                    "回覆裡。",
                )
                call_label = f"workbench_copy（只出{BAND_LABELS[band]}）"

            t0 = time.monotonic()
            copy_task = _copy_call(department_text)
            copy_seconds = time.monotonic() - t0

            if copy_task["status"] != "succeeded":
                emit(f"{call_label} 呼叫失敗：status={copy_task['status']}，"
                     f"error={copy_task.get('error')}")
                return 1
            copy_data = _parse_strict_json(copy_task.get("rendered_output") or "")
            if copy_data is None:
                emit(f"{call_label} 回覆不是單一 JSON 物件——這是紅燈，不是驗證發現。")
                emit("原文開頭 300 字：" + (copy_task.get("rendered_output") or "")[:300])
                return 1

            copy_usage = copy_task.get("usage_json") or {}
            emit("")
            emit(f"{call_label}：{copy_seconds:.1f} 秒，"
                 f"input_tokens={copy_usage.get('input_tokens')}，"
                 f"output_tokens={copy_usage.get('output_tokens')}，"
                 f"cost_usd={copy_task.get('cost')}")
            for label, ok, detail in validate_copy(copy_data, vocabulary, only_band=band):
                emit(("✅ " if ok else "❌ ") + f"{label}：{detail}")

            # 合併：--split 三通各自只填自己那個長度鍵；不 split 的一通三個鍵一次填齊。
            # coordinates／headlines／descriptions 取第一個有值的一通；warnings 全部接起來。
            for key in ("short", "medium", "long"):
                if band is None or key == band:
                    combined_copy[key] = copy_data.get(key) or combined_copy[key]
            if not combined_copy["coordinates"]:
                combined_copy["coordinates"] = copy_data.get("coordinates") or {}
            if not combined_copy["headlines"]:
                raw = copy_data.get("headlines")
                combined_copy["headlines"] = raw if isinstance(raw, list) else []
            if not combined_copy["descriptions"]:
                raw = copy_data.get("descriptions")
                combined_copy["descriptions"] = raw if isinstance(raw, list) else []
            combined_copy["warnings"] += copy_data.get("warnings") or []

        copy_data = combined_copy
        headlines = copy_data["headlines"]

        # ---- 第二通：圖片提示詞（工單帶上第一通的五個標題） ----
        image_department = (DEPARTMENTS_DIR / "image_prompt.md").read_text(encoding="utf-8")
        image_methodology = methodology.compile(conn, ["素材工作檯圖片提示詞"], brand_id=args.brand)
        worksheet_image = _worksheet_text(
            node_name=node_name, node_key=node_key, product_name=(product or {}).get("name"),
            coordinates=creative["coordinates"], visual_tone=creative["visual_tone"],
            visual_concept=creative["visual_concept"], count=args.count, headlines=headlines,
        )
        image_prompt_text = "\n\n".join(filter(None, [
            image_department, image_methodology.text, worksheet_image, brand_context,
        ]))

        t0 = time.monotonic()
        image_task = gateway.run_task(
            conn, providers.AnthropicProvider(), brand_id=args.brand,
            task_type="workbench_image_prompt", prompt_template_id="workbench_image_prompt",
            prompt_template_version="probe", system=None,
            messages=[{"role": "user", "content": image_prompt_text}], context=context,
            options=gateway.TaskOptions(max_tokens=16000, timeout_s=480.0),
        )
        image_seconds = time.monotonic() - t0

        if image_task["status"] != "succeeded":
            emit(f"workbench_image_prompt 呼叫失敗：status={image_task['status']}，"
                 f"error={image_task.get('error')}")
            return 1
        image_data = _parse_strict_json(image_task.get("rendered_output") or "")
        if image_data is None:
            emit("workbench_image_prompt 回覆不是單一 JSON 物件——這是紅燈，不是驗證發現。")
            emit("原文開頭 300 字：" + (image_task.get("rendered_output") or "")[:300])
            return 1

        image_usage = image_task.get("usage_json") or {}
        image_results, rendered_prompts, fbc = validate_image_prompts(image_data, args.count)
        emit("")
        emit(f"workbench_image_prompt：{image_seconds:.1f} 秒，"
             f"input_tokens={image_usage.get('input_tokens')}，"
             f"output_tokens={image_usage.get('output_tokens')}，"
             f"cost_usd={image_task.get('cost')}")
        for label, ok, detail in image_results:
            emit(("✅ " if ok else "❌ ") + f"{label}：{detail}")
        emit(f"fixed_block_chars={fbc}")

        emit("")
        emit("=== 文案全文 ===")
        band_titles = {
            "short": "短 100～150 字（折疊前一口氣講完，適合再行銷、已認識品牌的人）",
            "medium": "中 300～500 字（痛點→證明→優惠，適合第一次看到你的人）",
            "long": "長 800～1000 字（說故事，適合高單價、需要被說服的商品）",
        }
        for key, title in band_titles.items():
            emit(f"\n【{title}】")
            for i, text in enumerate(copy_data.get(key) or [], start=1):
                emit(f"{i}. （{_char_len(text)} 字）{text}")

        emit("\n標題：")
        for i, h in enumerate(headlines, start=1):
            emit(f"{i}. （{_char_len(h)} 字）{h}")

        emit("\n說明：")
        for i, d in enumerate(copy_data.get("descriptions") or [], start=1):
            emit(f"{i}. （{_char_len(d)} 字）{d}")

        emit(f"\n=== 圖片提示詞（共 {len(rendered_prompts)} 則） ===")
        for i, text in enumerate(rendered_prompts, start=1):
            emit(f"\n第 {i} 則（{_char_len(text)} 字）：\n{text}")

    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = SCRATCH_DIR / f"{ts}.md"
    out_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    print(f"\n已寫入：{out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
