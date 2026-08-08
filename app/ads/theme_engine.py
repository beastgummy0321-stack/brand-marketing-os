# -*- coding: utf-8 -*-
"""app/ads/theme_engine.py — 單圖主題生成引擎（票 04-single-image-e2e）。

「切角 × 廣告格式 → 主題」第一個落地格式：single_image。吃 app/ads/brief_assembler.py
組好的創意簡報，照 app/creative/format_specs.py 的規格表產出一句話名稱＋圖片提示詞／
主要文案／標題／說明，回傳純資料（`generate_single_image_theme`，不落地，供假 gateway
測試只驗產出形狀）；存檔另一步（`save_generated_theme`：建主題＋元件、配短碼、建資料夾）。

ponytail：引擎目前還在 app/ads——票 14（A 段收尾）要等 04～08 全部格式定形後才整批搬進
app/creative 變無狀態零件；07（輪播）、08（影片）會在這裡加自己的
`generate_carousel_theme()`／`generate_video_theme()`，共用本檔的存檔與資料夾函式。
"""

import re
from typing import Callable, Optional

from app.ads import fingerprint as fp
from app.ads import theme_repository as theme_repo
from app.ads.brief_assembler import CreativeBrief
from app.core import creative_assets
from app.core import settings as coresettings
from app.core.db import new_id
from app.creative.format_specs import FORMAT_SPECS
from app.llm import gateway, pricing, providers

PROVIDER = providers.AnthropicProvider()  # 測試整包換掉，比照 app/ads/creative.py 慣例

# 沿用 app/ads/creative.py CREATIVE_MAX_TOKENS 同一個保守值（票 6／M2 花費上限攔截的呼叫前
# 估計依據）：單一主題產出量比整批切角小，之後有真實 token 用量校準可以調降。
THEME_MAX_TOKENS = 16000

PARSE_FAIL_MESSAGE = "AI 有回覆，但格式讀不成預期的樣子。可以再試一次。"
UNSUPPORTED_FORMAT_MESSAGE = "這個格式的生成引擎還沒做（目前只有單圖 single_image）。"

_SYSTEM = (
    "你是資深廣告文案，正在替客戶產出一則 Meta 廣告的完整素材主題。"
    "只回傳 JSON，不要任何 JSON 以外的文字。除了圖片提示詞可用英文，其餘一律繁體中文。"
)

# 三條創意規則並列、各標適用層級，一條都不能少（ADR 0008 一、GRILL-PENDING C.6，
# 票 04 驗收 3）：第 1 條管切角層（既有規則，這裡先聲明給模型知道，這次呼叫本身只服務
# 單一切角格，不要求模型比較），第 2、3 條管主題層——本次輸出全部要遵守。
_CREATIVE_RULES = (
    "三條創意規則，各自標明適用層級：\n"
    "1.〔切角層〕不同切角要真的不一樣，不能只是換句話說（既有規則，先讓你知道，"
    "這次只服務單一切角，不用你在這裡比較）。\n"
    "2.〔主題層〕這次要出的全部素材彼此是同一則廣告的替身：主要文案的說法，要跟"
    "圖片提示詞裡描述的圖上文字一律相同、講同一件事，只能在配色、模特兒、拍攝角度這些"
    "跟訊息無關的地方不一樣。\n"
    "3.〔主題層〕5 則主要文案彼此的差異只准在「說法」（用詞、句子結構不同），不准講"
    "不同的情境或不同的賣點——同一個主題只服務同一種媒體情境。"
)

# 資料夾名不可含的字元：Windows 保留字元＋換行。理由見 _theme_folder_name()。
_UNSAFE_FOLDER_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def _single_image_fields_plan(objective: str) -> dict:
    """規格表 → 這個行銷目標下，single_image 各欄位實際要出的則數與字數預算。

    唯一的「目標差異」來源是 objectives[objective]['media_cap_per_theme']（圖片提示詞
    欄位的媒體上限）；body／title／description 一律照 fields 表的 count，沒有
    `if objective == "sales"` 這種分支——五種行銷目標走同一段程式碼（票 04 驗收 2）。
    """
    spec = FORMAT_SPECS["single_image"]
    if objective not in spec["objectives"]:
        raise ValueError(f"single_image 格式不支援「{objective}」這個行銷目標")
    media_cap = spec["objectives"][objective]["media_cap_per_theme"]
    fields = spec["fields"]
    return {
        "image_prompt": {"count": media_cap, "char_budget": fields["image_prompt"]["char_budget"]},
        "body": dict(fields["body"]),
        "title": dict(fields["title"]),
        "description": dict(fields["description"]),
    }


def _build_user_text(brief: CreativeBrief, plan: dict) -> str:
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

    parts.append(_CREATIVE_RULES)
    parts.append(
        "這次要產一個新主題，包含：\n"
        "- name：一句話主題名稱（給人看的識別名，不是廣告文案本身）\n"
        f"- image_prompt：{plan['image_prompt']['count']} 則圖片提示詞，字串陣列，"
        "能直接貼進生圖工具，寫清楚畫面內容、構圖與風格，並清楚描述圖上出現的文字（如果有）\n"
        f"- body：{plan['body']['count']} 則主要文案，每則不超過"
        f" {plan['body']['char_budget']} 字\n"
        f"- title：{plan['title']['count']} 則標題，每則不超過 {plan['title']['char_budget']} 字\n"
        f"- description：{plan['description']['count']} 則說明，每則不超過"
        f" {plan['description']['char_budget']} 字\n"
        "body／title／description 每一則都要標四軸指紋，值只能從下面挑，不可以自己發明：\n"
        + brief.fingerprint_vocabulary
    )
    parts.append(
        "只能使用上面已登錄的品牌與產品事實／宣稱，不得新增、不得誇大；不要編造規格、成分、"
        "檢驗數據或名人推薦。不要生成任何 CTA（行動呼籲按鈕文字）或連結——這則廣告的 CTA"
        "由投放設定另外決定，不是你的工作。\n"
        "輸出格式：只回傳以下 JSON：\n"
        '{"name": "一句話主題名稱",'
        ' "image_prompt": ["提示詞1", "提示詞2", ...],'
        ' "body": [{"content": "...", "fingerprint": {"angle":"...","tone":"...",'
        '"format":"...","selling_point":"..."}}, ...],'
        ' "title": [{"content": "...", "fingerprint": {...}}, ...],'
        ' "description": [{"content": "...", "fingerprint": {...}}, ...]}'
    )
    return "\n\n".join(parts)


def _normalize_single_image(data, plan: dict) -> Optional[dict]:
    """驗證形狀：缺 name／欄位不是陣列就整批判失敗；單則缺內容的直接丟掉，不猜。

    ponytail：不強制核對則數對規格表（AI 沒照 plan 要求的數量出時，有多少存多少）——
    05（字數守門）與之後的「補打缺型別」需求真的出現再加，這裡先信任 prompt 裡寫明的數量。
    """
    if not isinstance(data, dict):
        return None
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        return None

    image_prompts = data.get("image_prompt")
    if not isinstance(image_prompts, list):
        return None
    components = [
        {"component_type": "image_prompt", "content": item.strip(), "fingerprint_json": None}
        for item in image_prompts if isinstance(item, str) and item.strip()
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
                # 指紋經 normalize 才寫入（票 04 驗收 5）：認不得的軸值在這裡就丟掉，
                # 不留到存檔那一刻才處理。
                "fingerprint_json": fp.normalize(item.get("fingerprint")),
            })

    if not components:
        return None
    return {"name": name.strip(), "components": components}


def generate_single_image_theme(conn, brief: CreativeBrief, *, actor: str,
                                on_stage: Optional[Callable[[str], None]] = None) -> tuple:
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
    plan = _single_image_fields_plan(brief.cycle["objective"])

    model = providers.resolve_model(task_type="creative_theme", conn=conn)
    budget_err = coresettings.budget_exceeded_message(
        conn, brief.brand["id"], pricing.cost_ceiling(model, THEME_MAX_TOKENS),
        action="這個主題生成",
        fallback_hint="可以先採用已經產出的主題，或到設定頁調高上限後再試。")
    if budget_err:
        return None, budget_err

    user_text = _build_user_text(brief, plan)
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

    generated = _normalize_single_image(gateway.parse_json_reply(task["rendered_output"]), plan)
    if generated is None:
        return None, PARSE_FAIL_MESSAGE
    return generated, None


def theme_folder_name(theme: dict) -> str:
    """主題資料夾名＝人話名＋四碼短碼（ADR 0008：「名字在前，短碼在後，短碼是系統認回來的
    依據」）。名稱來自 AI 輸出，是信任邊界輸入——先濾掉 Windows 路徑不能用的字元，
    再擋一次空字串，不讓被濾光的名稱生出一個只剩短碼的資料夾。
    """
    safe_name = _UNSAFE_FOLDER_CHARS.sub("", theme["name"]).strip() or "主題"
    return f"{safe_name}_{theme['folder_code']}"


def save_generated_theme(conn, brief: CreativeBrief, generated: dict, *, actor: str) -> dict:
    """引擎產出存進 DB：建主題＋元件（照 app/ads/theme_repository.py 慣例，指紋已在
    _normalize_single_image() 正規化過），配四碼短碼並建素材資料夾（票 04 驗收 5、6）。

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
        conn, brief.brand["id"], brief.cycle["id"], theme_folder_name(theme))
    folder_path.mkdir(parents=True, exist_ok=True)
    theme["folder_path"] = str(folder_path)
    return theme
