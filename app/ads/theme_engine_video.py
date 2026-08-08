# -*- coding: utf-8 -*-
"""app/ads/theme_engine_video.py — 影片腳本主題生成（票 08-video-theme）。

跟單圖／輪播（app/ads/theme_engine.py）同一個「一次呼叫＝一個主題」形狀、同一套字數守門
與相似度標黃（呼叫 theme_engine._apply_char_guard／_apply_similarity_flag，不另寫一套）：
一支腳本＝一個主題（一列 creative_theme，票 08 驗收 4）。獨立成檔而不是加進
theme_engine.py，純粹是行數理由——加了輪播（票 07）後 theme_engine.py 已經 600 行出頭，
逼近 app/tests/test_architecture_boundaries.py 的 800 行硬上限（見 CLAUDE.md／task 交付
時的提醒）；本檔只 import theme_engine（單向），theme_engine.py 完全不 import 回來，
避免循環 import，也不必為此改動它一行。

Hook 池（票 08 驗收 2）：Hook 池「掛切角層」不是掛單一主題——查這個切角底下既有的 video
格式主題，已經有 hook_pool 元件就直接重用（連內容都塞進這支腳本的 prompt 當參考），不再
問 AI、不重複落庫；還沒有時才問 AI 生（規格表 FORMAT_SPECS["video"]["fields"]["hook_pool"]
的則數），隨這支（第一支）腳本一起存。要湊出一個切角完整的 3 支跨框架腳本，呼叫端
（09-preselect-autogen 的批次生成職責）要呼叫 generate_video_theme() 3 次——本函式不知道
也不管這個切角總共要幾支，比照單圖／輪播不知道「這一格總共要幾個主題」的既有分工。

Hook 段插槽（方法論 app/methodology/creative-matrix.md 第 5 節腳本輸出規則 1：「Hook 段
一律留插槽，不寫死」）：無論選哪個框架，第一段的口播台詞一律由程式碼強制蓋成
HOOK_SLOT_PLACEHOLDER，不管 AI 有沒有自己寫——「不寫死」用程式碼保證，不只靠 prompt 要求。

組合輸出（票 08 驗收 3，`combine_video_script`）：純讀取＋字串組裝，不呼叫 AI；9:16／
30 秒基準資訊取自 FORMAT_SPECS["video"]，不在這裡寫死數字。純函式，本票不掛新路由——
接縫二（前端要打的複製按鈕）屬 11-copy-flows 的範圍，那票再決定要不要包一層 HTTP。

框架清單／段落標籤／Hook 切法不在這裡另外宣告一份常數：已經完整寫在
app/methodology/creative-matrix.md，經 brief.methodology（既有 methodology.compile()）
整段送進 prompt，AI 從那裡面挑，程式碼只驗「有挑、有段落」，不驗成一份封閉列舉——這點跟
carousel 的 narrative_type（3 選 1、程式碼要用它算卡片數）不一樣：框架數量與卡片邏輯無關，
在 Python 裡另外複製一份 12 套框架表只會製造兩處要同步的風險。
"""

import json
from typing import Callable, Optional

from app.ads import fingerprint as fp
from app.ads import theme_engine
from app.ads import theme_repository as theme_repo
from app.ads.brief_assembler import CreativeBrief
from app.creative.format_specs import FORMAT_SPECS
from app.core import settings as coresettings
from app.llm import gateway, pricing, providers

VIDEO_FORMAT_MISMATCH_MESSAGE = "這份簡報的格式不是影片（video），不能呼叫影片生成引擎。"

# Hook 段插槽佔位字串：segments[0]["dialogue"] 一律被蓋成這個值，見檔頭說明。
HOOK_SLOT_PLACEHOLDER = "（Hook 插槽：套入 Hook 後這裡才有台詞）"

# 主題層規則（跟單圖／輪播並列的第三份格式專屬版本）：video 沒有「圖上文字」（單圖）也沒有
# 「故事摘要」（輪播），主題層一致性改成「body 文案要跟腳本傳達的訊息一致」。
_VIDEO_CREATIVE_RULES = (
    "三條創意規則，各自標明適用層級：\n"
    "1.〔切角層〕不同切角要真的不一樣，不能只是換句話說（既有規則，先讓你知道，"
    "這次只服務單一切角，不用你在這裡比較）。\n"
    "2.〔主題層〕body 主要文案要跟這支腳本傳達的訊息一致，不能講腳本以外的賣點或情境。\n"
    "3.〔主題層〕5 則 body 主要文案彼此的差異只准在「說法」（用詞、句子結構不同），不准"
    "換賣點或換情境——同一個主題只服務同一種媒體情境。"
)


def _video_fields_plan(objective: str) -> dict:
    """規格表 → video 的 body／title／description 字數預算（重用單圖規則，票 08 What to
    build 原文）。跟 carousel 一樣，五個行銷目標的 media_cap_per_theme 都是 1（一支腳本＝
    一則廣告），這裡只做「目標存在於規格表」的輸入驗證；script／hook_pool 沒有字數預算，
    不進這張 plan（讓 theme_engine._char_budgets() 自然跳過，不必幫它們加特例）。
    """
    spec = FORMAT_SPECS["video"]
    if objective not in spec["objectives"]:
        raise ValueError(f"video 格式不支援「{objective}」這個行銷目標")
    fields = spec["fields"]
    return {
        "body": dict(fields["body"]),
        "title": dict(fields["title"]),
        "description": dict(fields["description"]),
    }


def _existing_video_hook_pool(conn, brand_id: str, experiment_cell_id: str) -> list:
    """這個切角是否已經有共用 Hook 池：掃這個切角底下所有 video 格式主題的元件，收集
    component_type=="hook_pool" 的內容（票 08 驗收 2）。沒有就回空 list。"""
    hooks = []
    for theme in theme_repo.list_themes_for_cell(conn, brand_id, experiment_cell_id):
        if theme["format_key"] != "video":
            continue
        hooks.extend(
            c["content"] for c in theme["components"] if c["component_type"] == "hook_pool")
    return hooks


def _build_video_user_text(brief: CreativeBrief, plan: dict, *,
                           needs_hook_pool: bool, existing_hooks: list) -> str:
    spec = FORMAT_SPECS["video"]
    parts = [
        f"品牌名稱：{brief.brand['name']}",
        f"本期打法：{brief.plan['summary']}",
        f"這一格的切角：{brief.cell['creative_angle']}",
        brief.brand_context if brief.brand_context else "（目前沒有任何已確認的品牌資料。）",
    ]
    if brief.offer:
        parts.append(f"本期優惠：{brief.offer['name']}（{brief.offer['terms']}）")
    if brief.methodology:
        parts.append("【方法論】產出素材時請依循以下專業行銷準則：\n" + brief.methodology)
    if brief.rejection_constraints:
        parts.append(
            "這個品牌過去被退過的東西，這次不要再出現：\n"
            + "\n".join(f"- {c}" for c in brief.rejection_constraints)
        )
    parts.append(brief.customer_voice)

    if brief.existing_themes_summary:
        lines = []
        for theme in brief.existing_themes_summary:
            described = "；".join(fp.describe(f) for f in theme["fingerprints"] if f)
            lines.append(f"- 「{theme['name']}」" + (f"（{described}）" if described else ""))
        parts.append(
            "這一格已經有以下主題了，這次要真的不一樣，不要撞衫：\n" + "\n".join(lines)
        )

    parts.append(_VIDEO_CREATIVE_RULES)

    if needs_hook_pool:
        hook_instruction = (
            f"這是這個切角第一支腳本，另外請你也生成這個切角共用的"
            f" {spec['fields']['hook_pool']['count']} 個 Hook（開場第一句台詞候選）。這批"
            "Hook 之後會給同一個切角所有腳本共用，不是只給這支腳本用，寫的時候不要只考慮這支"
            "腳本的畫面。Hook 判準＝吸睛強度＋兌現，方法論裡的 Hook 切法要至少橫跨 5 種以上"
            "切法，不可以 10 組全是同一種切法的換句話說。"
        )
    else:
        hook_instruction = (
            "這個切角已經有共用的 Hook 池了，不用你再生 Hook。這支腳本一樣把第一段留給"
            "Hook（不要自己寫這段的台詞），已經有的 Hook 如下，寫這支腳本時要確保接得上、"
            "兌現得了其中任何一個：\n" + "\n".join(f"- {h}" for h in existing_hooks)
        )

    parts.append(
        "這次要產一個新的影片腳本主題。先從方法論的框架清單挑一套最適合這個切角的框架"
        "（框架名稱照方法論寫的填，不要自己發明新框架），再依框架的段落順序產出，同一批腳本"
        "要跟這個切角已經出過的腳本框架不一樣（至少橫跨 2 種框架，不可以全部同一套）。\n"
        "這次要產出：\n"
        "- name：一句話主題名稱（給人看的識別名，不是廣告文案本身）\n"
        "- framework：你選的框架名稱\n"
        "- segments：依播放順序排列的段落陣列，每個段落包含：\n"
        "  - label：段落標籤（只能從你選的框架的段落名挑，不可自創）\n"
        "  - dialogue：這段的口播台詞（第一段是 Hook 段，一律留空插槽，不要自己寫台詞）\n"
        "  - visual：這段的畫面說明（一句話，不寫運鏡、不寫轉場）\n"
        + hook_instruction + "\n"
        f"- body：{plan['body']['count']} 則廣告層主要文案，每則不超過"
        f" {plan['body']['char_budget']} 字，每一則都要標四軸指紋，值只能從下面挑，"
        "不可以自己發明：\n" + brief.fingerprint_vocabulary + "\n"
        f"- title：{plan['title']['count']} 則標題，每則不超過 {plan['title']['char_budget']} 字\n"
        f"- description：{plan['description']['count']} 則說明，每則不超過"
        f" {plan['description']['char_budget']} 字"
    )
    parts.append(
        "只能使用上面已登錄的品牌與產品事實／宣稱，不得新增、不得誇大；不要編造規格、成分、"
        "檢驗數據或名人推薦。不要生成任何 CTA（行動呼籲按鈕文字）或連結——這則廣告的 CTA"
        "由投放設定另外決定，不是你的工作。\n"
        "輸出格式：只回傳以下 JSON：\n"
        '{"name": "一句話主題名稱", "framework": "PAS",'
        ' "segments": [{"label": "...", "dialogue": "...", "visual": "..."}, ...], '
        + ('"hook_pool": ["Hook1", "Hook2", ...], ' if needs_hook_pool else "")
        + '"body": [{"content": "...", "fingerprint": {"angle":"...","tone":"...",'
        '"format":"...","selling_point":"..."}}, ...],'
        ' "title": [{"content": "...", "fingerprint": {...}}, ...],'
        ' "description": [{"content": "...", "fingerprint": {...}}, ...]}'
    )
    return "\n\n".join(parts)


def _normalize_video(data, plan: dict, *, needs_hook_pool: bool) -> Optional[dict]:
    """驗證影片腳本形狀：跟 carousel 一樣整批判失敗（缺一段就斷了腳本，不猜殘缺版）；
    body/title/description 沿用 single_image 的「單則缺內容就丟掉」寬鬆規則。

    Hook 段（segments[0]）的台詞不驗證內容、直接蓋成 HOOK_SLOT_PLACEHOLDER（見檔頭說明）。
    hook_pool 只在 needs_hook_pool 時才收；否則即使 AI 多回了也丟掉，跟單圖丟棄 cta／link
    是同一種「不該出現的欄位一律忽略」處理（票 08 驗收 2：不重複落庫共用資源）。
    """
    if not isinstance(data, dict):
        return None
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    framework = data.get("framework")
    if not isinstance(framework, str) or not framework.strip():
        return None

    raw_segments = data.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        return None
    segments = []
    for seg in raw_segments:
        if not isinstance(seg, dict):
            return None
        label, visual = seg.get("label"), seg.get("visual")
        if not all(isinstance(v, str) and v.strip() for v in (label, visual)):
            return None
        dialogue = seg.get("dialogue")
        segments.append({
            "label": label.strip(), "visual": visual.strip(),
            "dialogue": dialogue.strip() if isinstance(dialogue, str) else "",
        })
    # Hook 段一律留插槽（方法論規則）：不管 AI 有沒有寫、寫了什麼，第一段的台詞一律蓋成
    # HOOK_SLOT_PLACEHOLDER；只覆蓋第一段，其餘段落的台詞原樣保留（上面剛存進去的那份）。
    segments[0]["dialogue"] = HOOK_SLOT_PLACEHOLDER

    components = [{
        "component_type": "script",
        "content": json.dumps({"framework": framework.strip(), "segments": segments},
                              ensure_ascii=False),
        "fingerprint_json": None,
    }]

    if needs_hook_pool:
        raw_hooks = data.get("hook_pool")
        if not isinstance(raw_hooks, list):
            return None
        hooks = [h.strip() for h in raw_hooks if isinstance(h, str) and h.strip()]
        if not hooks:
            return None
        components += [
            {"component_type": "hook_pool", "sequence": i, "content": hook,
             "fingerprint_json": None}
            for i, hook in enumerate(hooks, start=1)
        ]

    for field in ("body", "title", "description"):
        raw_items = data.get(field)
        if not isinstance(raw_items, list):
            return None
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, str) or not content.strip():
                continue
            components.append({
                "component_type": field, "content": content.strip(),
                "fingerprint_json": fp.normalize(item.get("fingerprint")),
            })

    return {"name": name.strip(), "components": components}


def generate_video_theme(conn, brief: CreativeBrief, *, actor: str,
                         on_stage: Optional[Callable[[str], None]] = None) -> tuple:
    """影片腳本主題生成（票 08-video-theme）。跟單圖／輪播同一個形狀、同一套守門，一支
    腳本＝一個主題（票 08 驗收 4）。Hook 池重用邏輯見 `_existing_video_hook_pool()`
    （票 08 驗收 2）。"""
    if brief.format_key != "video":
        raise ValueError(VIDEO_FORMAT_MISMATCH_MESSAGE)
    plan = _video_fields_plan(brief.cycle["objective"])
    existing_hooks = _existing_video_hook_pool(conn, brief.brand["id"], brief.cell["id"])
    needs_hook_pool = not existing_hooks

    model = providers.resolve_model(task_type="creative_theme", conn=conn)
    budget_err = coresettings.budget_exceeded_message(
        conn, brief.brand["id"], pricing.cost_ceiling(model, theme_engine.THEME_MAX_TOKENS),
        action="這個主題生成",
        fallback_hint="可以先採用已經產出的主題，或到設定頁調高上限後再試。")
    if budget_err:
        return None, budget_err

    user_text = _build_video_user_text(
        brief, plan, needs_hook_pool=needs_hook_pool, existing_hooks=existing_hooks)
    if on_stage:
        on_stage("ask_ai")
    task = gateway.run_task(
        conn, theme_engine.PROVIDER, brand_id=brief.brand["id"], task_type="creative_theme",
        prompt_template_id="creative_theme_video", prompt_template_version="v1",
        system=theme_engine._SYSTEM, messages=[{"role": "user", "content": user_text}],
        context=gateway.TaskContext(
            context_scope={"brand_id": brief.brand["id"], "campaign_cycle_id": brief.cycle["id"],
                          "experiment_cell_id": brief.cell["id"], "format_key": brief.format_key},
            knowledge_item_ids=[], brand_version=0,  # 同單圖／輪播：簡報刻意不帶這兩項
        ),
        options=gateway.TaskOptions(max_tokens=theme_engine.THEME_MAX_TOKENS),
    )
    if task["status"] != "succeeded":
        return None, task["error"]
    if on_stage:
        on_stage("save")

    generated = _normalize_video(
        gateway.parse_json_reply(task["rendered_output"]), plan, needs_hook_pool=needs_hook_pool)
    if generated is None:
        return None, theme_engine.PARSE_FAIL_MESSAGE
    generated["components"] = theme_engine._apply_char_guard(
        conn, brief, generated["components"], plan)
    generated["components"] = theme_engine._apply_similarity_flag(
        brief, generated["components"])
    return generated, None


def _render_video_script_text(framework: str, segments: list) -> str:
    spec = FORMAT_SPECS["video"]
    header = f"{spec['ratio']}，{spec['duration_seconds_default']} 秒基準｜框架：{framework}"
    body = "\n\n".join(
        f"{seg['label']}：{seg['dialogue']}\n畫面：{seg['visual']}" for seg in segments)
    return f"{header}\n\n{body}"


def combine_video_script(conn, brand_id: str, theme_id: str, hook_component_id: str) -> tuple:
    """票 08 驗收 3：給腳本 id＋Hook id → 回完整腳本文字（Hook 已套入插槽）。純讀取＋字串
    組裝，不呼叫 AI；9:16／30 秒基準資訊取自 FORMAT_SPECS["video"]，不在這裡寫死數字。
    找不到腳本／Hook，或 Hook 不屬於同一個切角，回 (None, 人話錯誤)。
    """
    theme = theme_repo.get_theme(conn, brand_id, theme_id)
    if theme is None or theme["format_key"] != "video":
        return None, "找不到這支影片腳本主題。"
    script_component = next(
        (c for c in theme["components"] if c["component_type"] == "script"), None)
    if script_component is None:
        return None, "這個主題還沒有腳本內容。"
    script = json.loads(script_component["content"])

    hook_content = None
    for sibling in theme_repo.list_themes_for_cell(
            conn, brand_id, theme["experiment_cell_id"]):
        if sibling["format_key"] != "video":
            continue
        for component in sibling["components"]:
            if (component["component_type"] == "hook_pool"
                    and component["id"] == hook_component_id):
                hook_content = component["content"]
                break
        if hook_content is not None:
            break
    if hook_content is None:
        return None, "找不到這個 Hook，或它不屬於同一個切角的 Hook 池。"

    segments = [dict(seg) for seg in script["segments"]]
    segments[0]["dialogue"] = hook_content
    return _render_video_script_text(script["framework"], segments), None
