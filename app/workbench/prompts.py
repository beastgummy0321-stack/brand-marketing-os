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

SUBJECT_PREFIX = "見參考商品照，"  # creative-matrix §3.3；外殼補上，模型不用自己寫


def brief_text(brief: dict, product_name: str | None, style: dict) -> str:
    """組『這張工單』段——比照 `scripts/workbench_probe.py::_worksheet_text`，改吃
    `workbench_brief` 列（工作檯的來源是一張工單，不是活動樹節點）。長度／變體數／字數帶
    已經寫在 `copy.md`／`image_prompt.md` 本身，這裡不重複。"""
    coordinates = brief.get("coordinates_snapshot_json") or {}
    lines = ["## 這張工單", f"產品：{product_name or '（無）'}"]
    if coordinates:
        lines.append(
            "既有座標（延續語氣參考用，非必須照抄）：" + json.dumps(coordinates, ensure_ascii=False)
        )
    lines.append(f"visual_tone：{brief.get('visual_tone') or '（無）'}")
    lines.append(f"visual_concept：{brief.get('visual_concept') or '（無）'}")
    lines.append(f"風格：{style['label']}（{style['authenticity_hint']}）；攝影形式：{style['capture_line']}")
    free_text = (brief.get("request_json") or {}).get("free_text")
    if free_text:
        lines.append(f"自由指示：{free_text}")
    return "\n".join(lines)


def copy_prompt(department_text: str, methodology_text: str, brief_section: str,
                 brand_context: str, coordinate_text: str) -> str:
    """票 workbench/02 §2 的組法：copy.md · methodology · 工單文字 · 品牌上下文 ·
    座標詞彙表**最後**。"""
    return "\n\n".join(filter(None, [
        department_text, methodology_text, brief_section, brand_context, coordinate_text,
    ]))


def image_prompt_prompt(department_text: str, methodology_text: str, brief_section: str,
                         brand_context: str, headlines: list, count: int) -> str:
    """跟 `copy_prompt` 同一個組法，少座標詞彙表（圖片提示詞不用七維座標），工單段多帶
    「這張工單要幾則」與「已採用的標題」兩行。"""
    lines = [brief_section, f"這張工單要幾則圖片提示詞：工單指定的張數＝{count}。"]
    if headlines:
        lines.append(
            "已採用的標題（圖上文字只能從這裡逐字取用，不得自己發明）："
            + "、".join(f"「{h}」" for h in headlines)
        )
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


def render_image_prompt(fixed: dict, variable: dict) -> str:
    """`image-prompt-template.md` 第 2 節的 9 行順序（2026-09-09 使用者裁決精簡）。外殼
    渲染，模型從不回傳這個字串。逐字照抄 `scripts/workbench_probe.py:82` 的
    `render_prompt`，刪腳本前搬進這裡。"""
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
