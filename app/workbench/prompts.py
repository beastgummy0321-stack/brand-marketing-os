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

from app.workbench import looks, visual

# CONSTITUTION.md 規則 5 簽下的七個維度名稱（同一份清單也活在 app.workbench.validate，
# 那邊複製、不 import 這裡——兩檔互不依賴，各自從 app.schedule.creative 複製一份，
# container contract 規則 5 允許）。
COORDINATE_KEYS = ("audience", "pain", "angle", "hook", "proof", "offer", "format")

# F07-I07：這則廣告的座標——`image_worksheet()` 只列六維（不含 format，那一維另外算
# ratio／platform），每一維一句中文名稱。`jobs.py` 用這份表把 `coordinates_snapshot_json`
# 的每一維組成一行（公開常數，不加底線：跨模組讀，不是這個檔案的實作細節）。
IMAGE_COORDINATE_LABELS = {
    "audience": "受眾", "pain": "痛點", "angle": "切角",
    "hook": "標題公式", "proof": "證明", "offer": "誘因",
}


# F38 decision 3: the 限時限量 offer, by key or by label (a snapshot may carry either).
_LIMITED_TIME = {"limited_time", "限時限量"}


def brief_text(brief: dict, product_name: str | None) -> str:
    """組『這張工單』段——比照 `scripts/workbench_probe.py::_worksheet_text`，改吃
    `workbench_brief` 列（工作檯的來源是一張工單，不是活動樹節點）。長度／變體數／字數帶
    已經寫在 `copy.md`／`image_prompt.md` 本身，這裡不重複。F07-I09（Decision 25）：舊全域
    風格庫退休，這裡不再帶「風格：」那一行——看圖片提示詞怎麼決定視覺是 §5.9 的事，這支只服務
    copy／video_script。F39-I04（outcomes 3–4）：`request_json.scene`（這則廣告的情境，一句）
    與 `request_json.calendar_note`（投放期間的行事曆，ads 側用程式算好的行）由交件方帶進
    `request_json`，有值才各印一段——順序：座標 → 情境 → 截止日 → 行事曆 → visual_tone。"""
    coordinates = brief.get("coordinates_snapshot_json") or {}
    request = brief.get("request_json") or {}
    lines = ["## 這張工單", f"產品：{product_name or '（無）'}"]
    if coordinates:
        # 票 05（ADR 0069 §3）：這組座標是樹交下來的，文案要照這組座標寫，不是可改可不改
        # 的參考——舊版那句只當語氣延續參考、非必須照抄的講法，在座標歸樹之後不再成立。
        lines.append(
            "這個節點的座標（文案照這組座標寫）：" + json.dumps(coordinates, ensure_ascii=False)
            + "\n例外：優惠與證明分類不是已確認事實；須另有已確認來源，"
            "否則使用無優惠／無證明。"
        )
    scene = request.get("scene")
    if isinstance(scene, str) and scene.strip():
        lines.append(
            f"情境：{scene.strip()}（五組文案的畫面都發生在這個情境裡，不得換成別的情境；"
            "標題與內文要看得出這個情境）"
        )
    deadline = request.get("offer_deadline")
    if deadline:
        lines.append(
            f"限時截止日：{deadline}（限時限量文案只能寫這一個日期，不得另造期限或數量）"
        )
    elif coordinates.get("offer") in _LIMITED_TIME:
        lines.append("這組座標寫了限時限量但沒有截止日：寫無優惠版本，不提期限。")
    calendar_note = request.get("calendar_note")
    if isinstance(calendar_note, str) and calendar_note.strip():
        # Same caveat the plan／strategy prompts carry (F38 calendar_tw.prompt_section).
        lines.append(
            "投放期間的行事曆：\n" + calendar_note.strip()
            + "\n（只在它真的會影響買家時寫進標題或 hook，不必硬套節慶）"
        )
    lines.append(f"visual_tone：{brief.get('visual_tone') or '（無）'}")
    lines.append(f"visual_concept：{brief.get('visual_concept') or '（無）'}")
    free_text = request.get("free_text")
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


def image_worksheet(
    *, shape: str, reference_line: str, identity_text: str, plan: list,
    coordinate_lines: list, task_line: str, task_rows_lines: list, device_order: list,
    quotable_lines: list, situation: str, key_messages: str, free_text: str | None,
    prior_titles: list, learning_lines: list, learning_omitted: int,
) -> str:
    """F07-I07（ARCHITECTURE.md §5.7 Decision 9-11／§5.9-§5.10）：一輪圖片提示詞的工作單，
    純函式，不含品牌上下文（那段由 `jobs.py` 接在這個字串後面，跟 `copy_prompt` 同一種
    組法）。`plan` 是 `looks.allocate()["plan"]` 的 `(look, slot)` tuple 清單，項數等於這輪
    要出的則數（單圖 10）或概念數（輪播 2）——每一項各自的風格分配寫成一行，不能讓模型自己
    挑。一行只在內容真的存在時才出現。"""
    unit = "則" if shape == "single" else "組"
    platform = "Meta 單圖廣告" if shape == "single" else "Meta 輪播廣告"
    ratio_sentence = visual.RATIO[shape][1]

    groups: list[list[str]] = []

    groups.append([f"用途：{ratio_sentence}（{platform}）"])
    groups.append([reference_line, f"品牌視覺規範：{identity_text}"])

    plan_lines = [
        f"- 第 {i} {unit}：{look}（{looks.look_label(look)}）"
        for i, (look, _slot) in enumerate(plan, 1)
    ]
    groups.append(["每則風格分配：", *plan_lines])

    if coordinate_lines:
        groups.append(["這則廣告的座標：", *coordinate_lines])

    groups.append([task_line, *task_rows_lines])

    groups.append([f"這一輪手法清單順序（可任選，不必照順序）：{'、'.join(device_order)}"])

    quotable_line = (
        f"可用字句（逐字，不得改）：{'／'.join(quotable_lines)}" if quotable_lines
        else "可用字句（逐字，不得改）：（無）"
    )
    groups.append([quotable_line])

    subject_group: list[str] = []
    if situation and key_messages:
        subject_group.append(f"題材：{situation}；{key_messages}")
    elif situation or key_messages:
        subject_group.append(f"題材：{situation or key_messages}")
    if free_text:
        subject_group.append(f"自由指示：{free_text}")
    if prior_titles:
        subject_group.append("上一輪的標題：" + "、".join(prior_titles))
    if subject_group:
        groups.append(subject_group)

    if learning_lines:
        learning_group = ["已知的視覺學習：", *[f"- {line}" for line in learning_lines]]
        if learning_omitted:
            learning_group.append(f"另有 {learning_omitted} 條沒列出")
    else:
        learning_group = ["已知的視覺學習：（無）"]
    groups.append(learning_group)

    body = "\n\n".join("\n".join(group) for group in groups if group)
    return "## 工作單\n\n" + body


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


# F07-I07：`render_hero_prompt`／`render_variant_prompt`／`render_exploration_prompt`
# 連同它們的模式（變體／探索）一起退休——`image_worksheet()` 是唯一的圖片提示詞組法。
