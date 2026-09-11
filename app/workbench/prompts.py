"""app/workbench/prompts.py — pure functions that build prompt text. No DB, no LLM call:
`jobs.py` reads files and queries the DB, then hands the pieces here to be joined. Private to
app/workbench (container contract §1).

Join order is the ticket's own spec (workbench/02 §2), which matches `scripts/
workbench_probe.py`'s tested order (ticket 01), not the looser prose in the department files
themselves: department task file -> methodology -> brief text -> brand context ->
(copy only) coordinate vocabulary **last** — schedule contract "Position in the prompt
decides" (ADR/measurement T8b): the coordinate vocabulary is the one instruction that must run
*after* the model has already written, so it goes last or gets skipped 6/7 of the time.
"""

import json

# CONSTITUTION.md 規則 5 簽下的七個維度名稱（同一份清單也活在 app.workbench.validate，
# 那邊複製、不 import 這裡——兩檔互不依賴，各自從 app.schedule.creative 複製一份，
# container contract 規則 5 允許）。
COORDINATE_KEYS = ("audience", "pain", "angle", "hook", "proof", "offer", "format")


def brief_text(brief: dict, product_name: str | None, style: dict) -> str:
    """組『這張工單』段——比照 `scripts/workbench_probe.py::_worksheet_text`，改吃
    `workbench_brief` 列（工作檯的來源是一張工單，不是活動樹節點）。長度／變體數／字數帶
    已經寫在 `copy.md`／`image_prompt.md` 本身，這裡不重複。"""
    coordinates = brief.get("coordinates_snapshot_json") or {}
    lines = ["## 這張工單", f"產品：{product_name or '（無）'}"]
    if coordinates:
        # 票 05（ADR 0069 §3）：這組座標是樹交下來的，文案要照這組座標寫，不是可改可不改
        # 的參考——舊版那句只當語氣延續參考、非必須照抄的講法，在座標歸樹之後不再成立。
        lines.append(
            "這個節點的座標（文案照這組座標寫）：" + json.dumps(coordinates, ensure_ascii=False)
        )
    lines.append(f"visual_tone：{brief.get('visual_tone') or '（無）'}")
    lines.append(f"visual_concept：{brief.get('visual_concept') or '（無）'}")
    lines.append(f"風格：{style['label']}；{style['style_block']}")
    free_text = (brief.get("request_json") or {}).get("free_text")
    if free_text:
        lines.append(f"自由指示：{free_text}")
    return "\n".join(lines)


def copy_prompt(department_text: str, methodology_text: str, brief_section: str,
                 brand_context: str, coordinate_text: str, copy_length: str | None = None) -> str:
    """票 workbench/02 §2 的組法：copy.md · methodology · 工單文字 · 品牌上下文 ·
    座標詞彙表**最後**。票 T01-02：`copy_length` 給了值就在工單文字多帶一行「本次要出的
    長度」，字數區間讀自 `validate.BODY_BANDS`／`validate.BAND_LABELS`，組數讀自
    `validate.COPY_SET_COUNT`（ARCHITECTURE.md §5.6：一輪 5 組完整廣告，不是三個長度各自
    的則數），不在這裡另打一份——`import` 放在函式內（lazy import）：`validate.py` 在
    module level `from app.workbench.prompts import COORDINATE_KEYS`，兩檔互相在
    module level import 會循環失敗，延到呼叫期兩邊都已載完就沒事。`copy_length` 是
    `None` 時（`free` part 借用這個組法，沒有長度帶這個概念）不加這一行。"""
    length_line = ""
    if copy_length is not None:
        from app.workbench.validate import BAND_LABELS, BODY_BANDS, COPY_SET_COUNT

        lo, hi = BODY_BANDS[copy_length]
        length_line = (
            f"本次要出的長度：{BAND_LABELS[copy_length]}（{lo}～{hi} 字，{COPY_SET_COUNT} 組）"
        )
    worksheet = "\n\n".join(filter(None, [brief_section, length_line]))
    return "\n\n".join(filter(None, [
        department_text, methodology_text, worksheet, brand_context, coordinate_text,
    ]))


def image_prompt_prompt(department_text: str, methodology_text: str, brief_section: str,
                         brand_context: str, *, mode: str, count: int, quotable_lines: list,
                         headline_hint: str | None) -> str:
    """跟 `copy_prompt` 同一個組法，少座標詞彙表（圖片提示詞不用七維座標）。工單段
    （`brief_section`）後面接三行，各自在內容是空的時候整行不出現（票 F01-T03-I02，
    ARCHITECTURE.md §5.6-§5.9）：模式（含探索模式的角度數）、可用字句、可用的大標——
    後兩行取代舊版「這張工單要幾則」／「已採用的標題」那兩行。"""
    mode_line = "模式：變體模式" if mode == "variant" else f"模式：探索模式；角度數：{count}"
    lines = [brief_section, mode_line]
    if quotable_lines:
        lines.append(f"可用字句（逐字，不得改）：{'／'.join(quotable_lines)}")
    if headline_hint:
        lines.append(f"可用的大標（可用可不用）：「{headline_hint}」")
    worksheet = "\n".join(lines)
    return "\n\n".join(filter(None, [department_text, methodology_text, worksheet, brand_context]))


def video_script_prompt(department_text: str, methodology_text: str, brief_section: str,
                         brand_context: str, count: int) -> str:
    """跟 `copy_prompt` 同一個組法，少座標詞彙表（影片腳本不用七維座標），工單段多帶
    「這張工單要幾支」一行——`validate.check_video_script` 用工單本身的 count 比對，模型
    看得到才填得出這個數字（票 workbench/06，同 `image_prompt_prompt` 那招）。"""
    worksheet = f"{brief_section}\n這張工單要幾支影片腳本：工單指定的支數＝{count}。"
    return "\n\n".join(filter(None, [department_text, methodology_text, worksheet, brand_context]))


def coordinate_vocabulary_text(coordinates: list) -> str:
    """複製自 `app/schedule/jobs.py::_coordinate_vocabulary_text`（票 T8b；不 import，
    app.schedule 私有，container contract 規則 5 允許複製）。座標詞彙表放整份 prompt 的
    最後一段，理由見原函式的檔頭註解：同一顆模型、同一份詞彙表，指令排在兩萬字之前只
    填得出 1/7，排在最後填得出 7/7。"""
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


def render_hero_prompt(fields: dict, *, style_block: str, product_line: str,
                        audience_line: str, appeal_line: str, quotable_lines: list,
                        output_line: str) -> str:
    """`image-prompt-template.md` §2——① 主圖提示詞（變體模式）。外殼渲染，模型只回
    `fields`（`hero` 物件）；`jobs.py` 的渲染入口不論驗證通不通過都會呼叫這裡一次，
    所以這裡對缺欄位一律容忍（`.get(..., "")`），不假設 `fields` 已經合格。"""
    lines = [f"【風格】{style_block}", f"【商品】{product_line}"]
    if audience_line:
        lines.append(f"【受眾】{audience_line}")
    if appeal_line:
        lines.append(f"【這則的訴求】{appeal_line}")
    if quotable_lines:
        lines.append(f"【可用字句（逐字，不得改）】{'／'.join(quotable_lines)}")
    lines.append(
        f"【畫面】{fields.get('scene', '')}／{fields.get('person', '')}／"
        f"{fields.get('subject_position', '')}"
    )
    text_line = f"【圖上文字】大標：「{fields.get('headline', '')}」"
    if fields.get("subhead"):
        text_line += f"；副標：「{fields['subhead']}」"
    text_line += "；文字純色填滿，數字獨立成行"
    lines.append(text_line)
    lines.append(f"【輸出】{output_line}")
    return "\n".join(lines)


def render_variant_prompt(*, count: int, appeal_sentence: str, quotable_lines: list,
                           output_line: str, style_block: str) -> str:
    """`image-prompt-template.md` §3——② 變體提示詞，兩種模式共用，不呼叫模型，純函式
    組字串。"""
    lines = [
        f"以附上的這張圖為基底，分別生成 {count} 個完全不同風格排版與人物的圖片，"
        "主要訴求保持不變。一次一張。"
    ]
    parts = [f"訴求「{appeal_sentence}」"]
    if quotable_lines:
        parts.append(f"可用字句「{'／'.join(quotable_lines)}」（數字逐字）")
    parts.append("商品外型與 Logo")
    if output_line:
        parts.append(output_line)
    lines.append("不變：" + "、".join(parts) + "。")
    lines.append("可變：場景、人物、構圖、文字排版位置、配色。")
    lines.append(f"【風格】{style_block}")
    return "\n".join(lines)


def render_exploration_prompt(angles: list, *, style_block: str, product_line: str,
                               purpose_line: str, quotable_lines: list, count: int) -> str:
    """`image-prompt-template.md` §4——③ 探索提示詞（探索模式）。跟 `render_hero_prompt`
    一樣對 `angles` 裡每一項缺欄位容忍：驗證沒過也要照樣渲染。"""
    lines = [f"【風格】{style_block}", f"【商品】{product_line}", f"【目的與對象】{purpose_line}"]
    if quotable_lines:
        lines.append(f"【可用字句（逐字，不得改）】{'／'.join(quotable_lines)}")
    task_lines = [
        f"【任務】分別給我 {count} 張圖，每張一個不同的說服切角，排版與風格彼此差異要大："
    ]
    for i, angle in enumerate(angles, start=1):
        angle = angle if isinstance(angle, dict) else {}
        task_lines.append(
            f"{i}. {angle.get('name', '')}｜{angle.get('brief', '')}｜"
            f"圖上文字：「{angle.get('on_image_line', '')}」"
        )
    lines.append("\n".join(task_lines))
    lines.append("【圖上文字】每張圖只出現它自己那一行字；文字純色填滿，數字獨立成行")
    return "\n".join(lines)
