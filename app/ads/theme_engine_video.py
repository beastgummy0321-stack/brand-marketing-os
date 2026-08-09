# -*- coding: utf-8 -*-
"""app/ads/theme_engine_video.py — 影片主題引擎的 ads 側入口（票 14-engine-move 拆分後）。

跟單圖／輪播（app/ads/theme_engine.py）同一套設計：組 prompt、驗證 AI 回覆的純邏輯搬進
app/creative/theme_engine_video.py（無狀態零件），AI 呼叫、花費上限查核、字數守門、相似度
標黃全部沿用 app/ads/theme_engine.py（同一個 PROVIDER、同一套守門，不另寫一套）。獨立成檔
而不是併進 theme_engine.py，純粹是行數理由（見 app/ads/theme_engine.py 現有行數）；本檔只
import theme_engine（單向），theme_engine.py 完全不 import 回來，避免循環 import。

本檔額外留兩件會碰 DB 的事，「資料表全部留在 ads」（spec A 段定案）具體落在影片格式上的
兩處：

1. **Hook 池是否已存在**（票 08 驗收 2）：查這個切角底下其他 video 格式主題有沒有既有
   `hook_pool` 元件——查完的結果（`needs_hook_pool`／`existing_hooks`）當純資料傳給
   creative 的 prompt 組裝／驗證函式。
2. **`combine_video_script`**（票 08 驗收 3）：給腳本 id＋Hook id，要先查 DB 認出這兩者、
   驗證同屬一個切角，才能把 Hook 套進插槽；純字串組裝那段
   （`app.creative.theme_engine_video.render_video_script_text`）已搬進 creative，這裡只
   呼叫它。
"""

import json

from app.ads import fingerprint as fp
from app.ads import theme_engine
from app.ads import theme_repository as theme_repo
from app.ads.brief_assembler import CreativeBrief
from app.core import settings as coresettings
from app.creative import theme_engine as core_theme_engine
from app.creative import theme_engine_video as _engine
from app.llm import gateway, pricing, providers
from typing import Callable, Optional

# 純轉發：既有呼叫端（routes_creative_theme.py、test_video_theme.py）繼續用
# theme_engine_video.X 拿得到。
HOOK_SLOT_PLACEHOLDER = _engine.HOOK_SLOT_PLACEHOLDER


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


def generate_video_theme(conn, brief: CreativeBrief, *, actor: str,
                         on_stage: Optional[Callable[[str], None]] = None) -> tuple:
    """影片腳本主題生成（票 08-video-theme）。跟單圖／輪播同一個形狀、同一套守門，一支
    腳本＝一個主題（票 08 驗收 4）。Hook 池重用邏輯見 `_existing_video_hook_pool()`
    （票 08 驗收 2）。"""
    if brief.format_key != "video":
        raise ValueError(_engine.VIDEO_FORMAT_MISMATCH_MESSAGE)
    plan = _engine.video_fields_plan(brief.cycle["objective"])
    existing_hooks = _existing_video_hook_pool(conn, brief.brand["id"], brief.cell["id"])
    needs_hook_pool = not existing_hooks

    model = providers.resolve_model(task_type="creative_theme", conn=conn)
    budget_err = coresettings.budget_exceeded_message(
        conn, brief.brand["id"], pricing.cost_ceiling(model, theme_engine.THEME_MAX_TOKENS),
        action="這個主題生成",
        fallback_hint="可以先採用已經產出的主題，或到設定頁調高上限後再試。")
    if budget_err:
        return None, budget_err

    user_text = _engine.build_video_prompt(
        brief, plan, fp, needs_hook_pool=needs_hook_pool, existing_hooks=existing_hooks)
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

    generated = _engine.normalize_video(
        gateway.parse_json_reply(task["rendered_output"]), plan, fp,
        needs_hook_pool=needs_hook_pool)
    if generated is None:
        return None, theme_engine.PARSE_FAIL_MESSAGE
    generated["components"] = theme_engine._apply_char_guard(
        conn, brief, generated["components"], plan)
    generated["components"] = core_theme_engine.apply_similarity_flag(
        brief, generated["components"], fp)
    return generated, None


def combine_video_script(conn, brand_id: str, theme_id: str, hook_component_id: str) -> tuple:
    """票 08 驗收 3：給腳本 id＋Hook id → 回完整腳本文字（Hook 已套入插槽）。純讀取＋字串
    組裝轉呼叫 app.creative.theme_engine_video.render_video_script_text()。找不到腳本／
    Hook，或 Hook 不屬於同一個切角，回 (None, 人話錯誤)。
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
    return _engine.render_video_script_text(script["framework"], segments), None
