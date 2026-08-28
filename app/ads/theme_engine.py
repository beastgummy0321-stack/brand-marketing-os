"""app/ads/theme_engine.py — 主題生成引擎的 ads 側入口（票 14-engine-move 拆分後）。

「切角 × 廣告格式 → 主題」已落地兩個格式：single_image（單圖）、carousel（敘事型輪播）。
組 prompt、驗證 AI 回覆的純邏輯已搬進 app/creative/theme_engine.py（無狀態零件：規格表＋
簡報進、prompt 文字或驗證結果出，不呼叫 AI、不碰 DB、不 import app.ads——見該檔檔頭）。
本檔留住「跑」這個引擎需要的一切：

1. **AI 呼叫與花費上限查核**——`gateway.run_task`／`coresettings.budget_exceeded_message`
   都要碰 DB（settings 表、稽核）、都要知道目前用哪個 `PROVIDER`；creative 那邊只給組好的
   prompt 文字，這裡真正打出去、算花費、判斷擋不擋。`PROVIDER` 是模組層可變常數，測試靠它
   整包換成假 Provider（見 app/tests/test_theme_engine.py `theme_engine.PROVIDER =` 慣例）。
2. **存檔**（`save_generated_theme`／`theme_folder_name`）：建主題＋元件、配短碼、建資料夾，
   全部碰 DB／檔案系統——「資料表全部留在 ads」（spec A 段定案）。
3. **`GENERATORS` 表**：format_key → 生成函式，供路由（routes_creative_theme.py）與批次
   （theme_batch.py）呼叫端用。

字數守門（票 05-char-guard）：兩個 generate_*_theme 產出後、回傳前跑 `_apply_char_guard`
——超字文字元件重寫一次（同一個 gateway 入口，只送超字那幾則），仍超就標 `over_budget`
存檔，不截斷、不擋採用；是存檔前唯一的字數守門點，兩格式共用本函式，不各自另建一套。

同批次相似度標黃（票 06-similarity-flag）：字數守門後緊接著跑
`_engine.apply_similarity_flag`——用既有 `fp.distance()` 比對本批新元件彼此、以及對同格
既有主題的元件，過近寫 `similarity_flag`，不擋存檔、不自動重生。

影片格式（票 08-video-theme）的 `generate_video_theme()` 在 app/ads/theme_engine_video.py
（獨立成檔的理由見該檔檔頭），共用本檔的存檔、資料夾與字數守門函式。
"""

import re
from collections.abc import Callable

from app.ads import fingerprint as fp
from app.ads import theme_repository as theme_repo
from app.ads.brief_assembler import CreativeBrief
from app.brand_intelligence import repository as bi_repo
from app.core import creative_assets
from app.core import settings as coresettings
from app.core.db import new_id
from app.creative import theme_engine as _engine
from app.llm import gateway, pricing, providers

PROVIDER = providers.AnthropicProvider()  # 測試整包換掉，比照 app/ads/creative.py 慣例

# 純轉發：既有呼叫端（theme_batch.py、routes_creative_theme.py、測試檔）繼續用
# theme_engine.X 拿得到。
THEME_MAX_TOKENS = _engine.THEME_MAX_TOKENS
PARSE_FAIL_MESSAGE = _engine.PARSE_FAIL_MESSAGE
UNSUPPORTED_FORMAT_MESSAGE = _engine.UNSUPPORTED_FORMAT_MESSAGE
CAROUSEL_FORMAT_MISMATCH_MESSAGE = _engine.CAROUSEL_FORMAT_MISMATCH_MESSAGE
CARD_PRODUCT_LINK_PLACEHOLDER = _engine.CARD_PRODUCT_LINK_PLACEHOLDER
_SYSTEM = _engine.SYSTEM_PROMPT


def _single_image_fields_plan(objective: str) -> dict:
    return _engine.single_image_fields_plan(objective)


def _carousel_fields_plan(objective: str) -> dict:
    return _engine.carousel_fields_plan(objective)


# 資料夾名不可含的字元：Windows 保留字元＋換行，理由見 theme_folder_name()。
_UNSAFE_FOLDER_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def _call_char_rewrite(conn, brief: CreativeBrief, items: list) -> list | None:
    """走引擎同一生成入口（同一個 PROVIDER、同一個 gateway.run_task）批次重寫超字元件——
    一次呼叫帶全部超字則數，不逐則各打一次（票 05 驗收「觸發一次重寫呼叫」）。
    失敗（AI 沒回、格式讀不成）回 None，呼叫端 fallback＝保留原文、標超字，不擋採用。
    """
    task = gateway.run_task(
        conn, PROVIDER, brand_id=brief.brand["id"], task_type="creative_rewrite",
        prompt_template_id="creative_theme_char_rewrite", prompt_template_version="v1",
        system=_SYSTEM, messages=[{"role": "user",
                                   "content": _engine.char_rewrite_prompt(brief, items)}],
        context=gateway.TaskContext(
            context_scope={"brand_id": brief.brand["id"], "campaign_cycle_id": brief.cycle["id"],
                          "experiment_cell_id": brief.cell["id"], "format_key": brief.format_key},
            knowledge_item_ids=[], brand_version=0,
        ),
        options=gateway.TaskOptions(max_tokens=4000),  # 同 app/ads/creative.py rewrite() 的保守值
    )
    if task["status"] != "succeeded":
        return None
    data = gateway.parse_json_reply(task["rendered_output"])
    rewrites = data.get("rewrites") if isinstance(data, dict) else None
    return rewrites if isinstance(rewrites, list) else None


def _apply_char_guard(conn, brief: CreativeBrief, components: list, plan: dict) -> list:
    """字數守門（票 05）：算超字元件（app.creative.theme_engine.over_budget_items）、超字
    的帶「壓到 N 字內」指令重寫一次，只送超字那幾則（未超字元件零呼叫，不多花錢）；重寫
    結果交回 apply_char_rewrites() 寫回、標記 over_budget，不截斷、不擋採用。這是 ads
    存檔前唯一的字數守門點，carousel／video（07／08）的 generate_*_theme() 之後共用本
    函式，不各自另建一套。
    """
    over_idx, items, budgets = _engine.over_budget_items(components, plan)
    if not over_idx:
        return components
    rewrites = _call_char_rewrite(conn, brief, items)
    return _engine.apply_char_rewrites(components, over_idx, budgets, rewrites)


def refresh_component_fingerprint(conn, brand_id: str, text: str) -> dict | None:
    """text 進、fingerprint dict 出。AI 失敗或花費超上限回 None——呼叫端保留舊指紋，
    不擋文字本身的同步更新（AC2：文字一律跟著 Meta 同步，指紋是錦上添花，不是前提）。
    """
    org_id = bi_repo._org_id_for_brand(conn, brand_id)
    model = providers.resolve_model(task_type="creative_theme", conn=conn, brand_id=brand_id)
    budget_err = coresettings.budget_exceeded_message(
        conn, brand_id, pricing.cost_ceiling(model, _engine.COMPONENT_FINGERPRINT_MAX_TOKENS),
        org_id=org_id,
        action="重打指紋", fallback_hint="可以先跳過這則，之後到設定頁調高上限後再試。")
    if budget_err:
        return None

    task = gateway.run_task(
        conn, PROVIDER, brand_id=brand_id, task_type="creative_theme",
        prompt_template_id="creative_theme_component_refingerprint", prompt_template_version="v1",
        system=_SYSTEM,
        messages=[{"role": "user", "content": _engine.build_refingerprint_prompt(text, fp)}],
        context=gateway.TaskContext(
            context_scope={"brand_id": brand_id}, knowledge_item_ids=[], brand_version=0),
        options=gateway.TaskOptions(max_tokens=_engine.COMPONENT_FINGERPRINT_MAX_TOKENS),
    )
    if task["status"] != "succeeded":
        return None
    data = gateway.parse_json_reply(task["rendered_output"])
    return _engine.parse_refingerprint_reply(data, fp)


def generate_single_image_theme(conn, brief: CreativeBrief, *, actor: str,
                                on_stage: Callable[[str], None] | None = None) -> tuple:
    """單圖主題生成。成功回 (generated_dict, None)；失敗回 (None, 人話錯誤)，不落地。

    generated_dict 形狀：{"name": str, "components": [{"component_type", "content",
    "fingerprint_json"}, ...]}——純資料，呼叫端另外呼叫 save_generated_theme() 存檔。
    產出與存檔分開，讓假 gateway 測試只驗產出形狀，不必碰 DB（票 04 測試決策）。

    on_stage（比照票 29／app/ads/creative.py generate() 同一套誠實階段字："ask_ai"／
    "save"）：目前沒有等待頁輪詢接它，前端包接上矩陣頁三態格時直接照抄
    app/ads/routes.py 的背景執行緒＋輪詢機制即可，介面不必再改。
    """
    if brief.format_key != "single_image":
        raise ValueError(UNSUPPORTED_FORMAT_MESSAGE)
    plan = _engine.single_image_fields_plan(brief.cycle["objective"])

    model = providers.resolve_model(
        task_type="creative_theme", conn=conn, brand_id=brief.brand["id"])
    budget_err = coresettings.budget_exceeded_message(
        conn, brief.brand["id"], pricing.cost_ceiling(model, THEME_MAX_TOKENS),
        org_id=brief.brand["org_id"],
        action="這個主題生成",
        fallback_hint="可以先採用已經產出的主題，或到設定頁調高上限後再試。")
    if budget_err:
        return None, budget_err

    from app.ads import style_preference
    user_text = _engine.build_single_image_prompt(
        brief, plan, fp, style_preference=style_preference.get_text(conn, brief.brand["id"]))
    if on_stage:
        on_stage("ask_ai")
    task = gateway.run_task(
        conn, PROVIDER, brand_id=brief.brand["id"], task_type="creative_theme",
        prompt_template_id="creative_theme_single_image", prompt_template_version="v1",
        system=_SYSTEM, messages=[{"role": "user", "content": user_text}],
        context=gateway.TaskContext(
            context_scope={"brand_id": brief.brand["id"], "campaign_cycle_id": brief.cycle["id"],
                          "experiment_cell_id": brief.cell["id"], "format_key": brief.format_key},
            # ponytail：brief_assembler（票 03）刻意不帶 knowledge_item_ids／brand_version
            # 回簡報（「簡報沒給的資訊等於不存在」），這裡因此填不出真正對應的知識項 id——
            # 已知的稽核落差，不是本票新引入的；要補只能在 brief_assembler 那層決定要不要
            # 破例多帶這兩項回來。
            knowledge_item_ids=[], brand_version=0,
        ),
        options=gateway.TaskOptions(max_tokens=THEME_MAX_TOKENS),
    )
    if task["status"] != "succeeded":
        return None, task["error"]
    if on_stage:
        on_stage("save")

    generated = _engine.normalize_single_image(
        gateway.parse_json_reply(task["rendered_output"]), plan, fp)
    if generated is None:
        return None, PARSE_FAIL_MESSAGE
    generated["components"] = _apply_char_guard(conn, brief, generated["components"], plan)
    generated["components"] = _engine.apply_similarity_flag(brief, generated["components"], fp)
    return generated, None


def generate_carousel_theme(conn, brief: CreativeBrief, *, actor: str,
                            on_stage: Callable[[str], None] | None = None) -> tuple:
    """輪播主題生成（票 07-carousel-theme）。跟 generate_single_image_theme 同一個形狀、
    同一套守門，只有 prompt 組裝（build_carousel_prompt）與驗證（normalize_carousel）
    是輪播專屬的；字數守門（_apply_char_guard）與相似度標黃（apply_similarity_flag）原封
    不動共用單圖那兩個函式（票 07 驗收要求，不得另寫）。

    骨架（narrative_type）沒有參數可傳——brief 跟這支函式的參數都沒有骨架欄位，完全由這次
    AI 回覆決定（normalize_carousel 驗證用），也因此「改骨架」在使用者操作上只能是整個
    主題退掉重生，沒有「改骨架、卡片留著」這種介面。
    """
    if brief.format_key != "carousel":
        raise ValueError(CAROUSEL_FORMAT_MISMATCH_MESSAGE)
    plan = _engine.carousel_fields_plan(brief.cycle["objective"])

    model = providers.resolve_model(
        task_type="creative_theme", conn=conn, brand_id=brief.brand["id"])
    budget_err = coresettings.budget_exceeded_message(
        conn, brief.brand["id"], pricing.cost_ceiling(model, THEME_MAX_TOKENS),
        org_id=brief.brand["org_id"],
        action="這個主題生成",
        fallback_hint="可以先採用已經產出的主題，或到設定頁調高上限後再試。")
    if budget_err:
        return None, budget_err

    user_text = _engine.build_carousel_prompt(brief, plan, fp)
    if on_stage:
        on_stage("ask_ai")
    task = gateway.run_task(
        conn, PROVIDER, brand_id=brief.brand["id"], task_type="creative_theme",
        prompt_template_id="creative_theme_carousel", prompt_template_version="v1",
        system=_SYSTEM, messages=[{"role": "user", "content": user_text}],
        context=gateway.TaskContext(
            context_scope={"brand_id": brief.brand["id"], "campaign_cycle_id": brief.cycle["id"],
                          "experiment_cell_id": brief.cell["id"], "format_key": brief.format_key},
            knowledge_item_ids=[], brand_version=0,  # 同單圖：簡報刻意不帶這兩項，見上面註解
        ),
        options=gateway.TaskOptions(max_tokens=THEME_MAX_TOKENS),
    )
    if task["status"] != "succeeded":
        return None, task["error"]
    if on_stage:
        on_stage("save")

    generated = _engine.normalize_carousel(
        gateway.parse_json_reply(task["rendered_output"]), plan, fp)
    if generated is None:
        return None, PARSE_FAIL_MESSAGE
    generated["components"] = _apply_char_guard(conn, brief, generated["components"], plan)
    generated["components"] = _engine.apply_similarity_flag(brief, generated["components"], fp)
    return generated, None


# 格式 key → 生成函式（路由層 app/ads/routes_creative_theme.py 用這張表分派，不必寫
# if format_key == "single_image" / elif == "carousel" 的分支）。video（票 08）的生成函式
# 在 app/ads/theme_engine_video.py，routes_creative_theme.py 自己合併一張多加 "video" 這個
# key 的表使用——本檔不 import theme_engine_video（避免循環 import），這裡刻意只收兩個 key。
GENERATORS = {
    "single_image": generate_single_image_theme,
    "carousel": generate_carousel_theme,
}


def theme_folder_name(theme: dict) -> str:
    """主題資料夾名＝人話名＋四碼短碼（ADR 0008：「名字在前，短碼在後，短碼是系統認回來的
    依據」）。名稱來自 AI 輸出，是信任邊界輸入——先濾掉 Windows 路徑不能用的字元，
    再擋一次空字串，不讓被濾光的名稱生出一個只剩短碼的資料夾。
    """
    safe_name = _UNSAFE_FOLDER_CHARS.sub("", theme["name"]).strip() or "主題"
    return f"{safe_name}_{theme['folder_code']}"


def save_generated_theme(conn, brief: CreativeBrief, generated: dict, *, actor: str) -> dict:
    """引擎產出存進 DB：建主題＋元件（照 app/ads/theme_repository.py 慣例，指紋已在
    normalize_single_image() 正規化過），配四碼短碼並建素材資料夾（票 04 驗收 5、6）。

    回傳值＝theme_repository.get_theme() 的形狀，多一個 folder_path 欄位。
    """
    folder_code = new_id("code")[-4:]  # 沿用 app/ads/codes.py 的做法：拿高熵 id 的尾段當短碼
    theme = theme_repo.create_theme(
        conn, brief.brand["id"], campaign_cycle_id=brief.cycle["id"],
        experiment_cell_id=brief.cell["id"], format_key=brief.format_key,
        name=generated["name"], folder_code=folder_code, actor=actor,
        components=generated["components"],
    )
    folder_path = creative_assets.theme_dir(
        conn, brief.brand["id"], brief.cycle["id"], theme_folder_name(theme),
        org_id=brief.brand["org_id"])
    folder_path.mkdir(parents=True, exist_ok=True)
    theme["folder_path"] = str(folder_path)
    return theme
