# -*- coding: utf-8 -*-
"""app/ads/theme_engine.py — 主題生成引擎（票 04-single-image-e2e、07-carousel-theme）。

「切角 × 廣告格式 → 主題」已落地兩個格式：single_image（單圖）、carousel（敘事型輪播）。
吃 app/ads/brief_assembler.py 組好的創意簡報，照 app/creative/format_specs.py 的規格表
產出各格式的欄位，回傳純資料（`generate_single_image_theme`／`generate_carousel_theme`，
不落地，供假 gateway 測試只驗產出形狀）；存檔另一步（`save_generated_theme`：建主題＋
元件、配短碼、建資料夾），兩格式共用同一個存檔函式——回傳形狀都是扁平
`{"name", "components"}`。格式 key → 生成函式的對照表見 `GENERATORS`。

字數守門（票 05-char-guard）：兩個 generate_*_theme 產出後、回傳前跑 `_apply_char_guard`
——超字文字元件重寫一次（同一個 gateway 入口，只送超字那幾則），仍超就標 `over_budget`
存檔，不截斷、不擋採用；是存檔前唯一的字數守門點，兩格式共用本函式，不各自另建一套。

同批次相似度標黃（票 06-similarity-flag）：字數守門後緊接著跑 `_apply_similarity_flag`——
用既有 `fp.distance()` 比對本批新元件彼此、以及對同格既有主題的元件，過近寫
`similarity_flag`，不擋存檔、不自動重生。兩格式共用本函式；沒有指紋的元件型別（輪播的
卡片與骨架標記）在函式裡自然被跳過，不必另外分支。

影片格式（票 08-video-theme）的 `generate_video_theme()` 共用本檔的存檔、資料夾與字數
守門函式，但邏輯本身在 app/ads/theme_engine_video.py（獨立成檔的理由見該檔檔頭：本檔
加完輪播已經 600 行出頭，逼近 800 行硬上限）；`GENERATORS` 這張表因此只收單圖／輪播兩個
key，video 這個 key 掛在 app/ads/routes_creative_theme.py 自己合併的那張表，不在這裡。

ponytail：引擎目前還在 app/ads——票 14（A 段收尾）要等 04～08 全部格式定形後才整批搬進
app/creative 變無狀態零件。
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
CAROUSEL_FORMAT_MISMATCH_MESSAGE = "這份簡報的格式不是輪播（carousel），不能呼叫輪播生成引擎。"

# 多商品型輪播每卡的商品連結（票 07 驗收 4）：引擎不生成連結——多商品型只有一個
# product_id 進得了簡報（brief_assembler 一次只查單一切角格），真正各卡各自的商品連結要等
# 未來的組裝層拿既有商品資料填入，這裡先用固定佔位文字佔住這個元件型別的位置。
CARD_PRODUCT_LINK_PLACEHOLDER = "（待組裝：這張卡的商品連結，由既有商品資料帶入）"

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

# 輪播版的主題層規則（票 07）：單圖版第 2 條講「圖上文字跟文案一律相同」，輪播沒有單一張
# 圖、卡片彼此講不同段落，這條規則換成「body 是整段敘事的摘要，不能講故事以外的東西」。
_CAROUSEL_CREATIVE_RULES = (
    "三條創意規則，各自標明適用層級：\n"
    "1.〔切角層〕不同切角要真的不一樣，不能只是換句話說（既有規則，先讓你知道，"
    "這次只服務單一切角，不用你在這裡比較）。\n"
    "2.〔主題層〕整個輪播從第一卡到最後一卡要講同一個故事，body 主要文案是這個故事的"
    "摘要或收尾，不能講故事以外的賣點或情境。\n"
    "3.〔主題層〕5 則 body 主要文案彼此的差異只准在「說法」（用詞、句子結構不同），不准"
    "換故事或換賣點——同一個主題只服務同一種媒體情境。"
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


def _carousel_fields_plan(objective: str) -> dict:
    """規格表 → carousel 各欄位的字數預算。跟單圖不同，carousel 五種行銷目標的
    media_cap_per_theme 都固定是 1（一套敘事＝一則廣告），沒有目標差異可查，這裡只做
    「目標存在於規格表」的輸入驗證（沿用 _single_image_fields_plan 同款防呆），卡片數量
    不查這張表——卡片數由引擎選的敘事骨架決定（票 07 驗收 3），不是規格表常數。
    """
    spec = FORMAT_SPECS["carousel"]
    if objective not in spec["objectives"]:
        raise ValueError(f"carousel 格式不支援「{objective}」這個行銷目標")
    fields = spec["fields"]
    return {
        "card_image_prompt": dict(fields["card_image_prompt"]),
        "card_title": dict(fields["card_title"]),
        "card_description": dict(fields["card_description"]),
        "body": dict(fields["body"]),
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


def _build_carousel_user_text(brief: CreativeBrief, plan: dict) -> str:
    """組輪播 prompt：跟 _build_user_text 共用前半段材料組裝（品牌／打法／切角／品牌
    context／優惠／方法論／拒絕記憶／顧客語料／防撞衫摘要），差異只在最後「這次要產什麼」
    那段——輪播多一段敘事骨架三選一的說明，且沒有骨架參數可以指定（票 07 驗收 3：骨架完全
    由這次呼叫的 AI 回覆決定，簡報跟這個函式都不吃骨架輸入）。
    """
    spec = FORMAT_SPECS["carousel"]
    narrative_lines = "\n".join(
        f"- {key}：{desc}" for key, desc in spec["narrative_types"].items())
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

    parts.append(_CAROUSEL_CREATIVE_RULES)
    parts.append(
        "這次要產一個新的敘事型輪播主題。先從以下三種敘事骨架挑一種最適合這個切角的：\n"
        + narrative_lines + "\n"
        f"卡片數必須在 {spec['card_count_min']}–{spec['card_count_max']} 張之間"
        "（步驟型＝步驟數、對比型固定 2 張、多商品型＝商品數），卡片要照播放順序排列，"
        "每張卡只負責講故事裡的一段，合起來要能講完整個故事。\n"
        "這次要產出：\n"
        "- name：一句話主題名稱（給人看的識別名，不是廣告文案本身）\n"
        "- narrative_type：你選的敘事骨架 key，只能填 steps／before_after／multi_product"
        " 三選一（不可以自己發明其他字串）\n"
        "- cards：依播放順序排列的卡片陣列，每張卡包含：\n"
        "  - image_prompt：這張卡的圖片提示詞，能直接貼進生圖工具，寫清楚畫面內容、構圖"
        "與風格，並清楚描述圖上出現的文字（如果有）\n"
        f"  - title：卡標題，不超過 {plan['card_title']['char_budget']} 字\n"
        "  - description：卡說明，把這張卡標題講的事，用完整的一句話再說一次，不超過"
        f" {plan['card_description']['char_budget']} 字\n"
        f"- body：{plan['body']['count']} 則廣告層主要文案（全部卡片共用，不是逐卡各自的"
        f"文案），每則不超過 {plan['body']['char_budget']} 字，每一則都要標四軸指紋，值只能"
        "從下面挑，不可以自己發明：\n" + brief.fingerprint_vocabulary
    )
    parts.append(
        "只能使用上面已登錄的品牌與產品事實／宣稱，不得新增、不得誇大；不要編造規格、成分、"
        "檢驗數據或名人推薦。不要生成任何 CTA（行動呼籲按鈕文字）；即使是多商品型，每張卡的"
        "商品連結也不是你的工作，不要輸出任何網址或連結文字。\n"
        "輸出格式：只回傳以下 JSON：\n"
        '{"name": "一句話主題名稱", "narrative_type": "steps",'
        ' "cards": [{"image_prompt": "...", "title": "...", "description": "..."}, ...],'
        ' "body": [{"content": "...", "fingerprint": {"angle":"...","tone":"...",'
        '"format":"...","selling_point":"..."}}, ...]}'
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


def _normalize_carousel(data, plan: dict) -> Optional[dict]:
    """驗證輪播形狀，回傳跟 _normalize_single_image 同一種扁平 {"name", "components"}——
    save_generated_theme() 因此不必為輪播另寫一份（票 07：走 04 的同一條存檔路徑）。

    卡片跟單圖的 body/title/description 不一樣：卡片是有序敘事，缺一張就斷了故事，不能
    像單圖那樣「單則缺內容就丟掉、其餘照樣算數」——這裡任何一張卡結構不對，整批直接判失敗
    （回 None，呼叫端走 PARSE_FAIL_MESSAGE 重生），不做「湊出能用的殘卡」這種猜測。
    骨架標記存成 component_type="narrative_type" 的一則元件（sequence 給 None，它不是卡，
    是整個主題的屬性），沿用既有的自由文字 component_type 欄位，不必新增資料表欄位。
    """
    if not isinstance(data, dict):
        return None
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        return None

    spec = FORMAT_SPECS["carousel"]
    narrative_type = data.get("narrative_type")
    if narrative_type not in spec["narrative_types"]:
        return None

    cards = data.get("cards")
    if not isinstance(cards, list):
        return None
    if narrative_type == "before_after":
        if len(cards) != 2:  # 對比型固定 2 卡（規格表 narrative_types 定案）
            return None
    elif not (spec["card_count_min"] <= len(cards) <= spec["card_count_max"]):
        return None

    components = [
        {"component_type": "narrative_type", "content": narrative_type, "fingerprint_json": None},
    ]
    for sequence, card in enumerate(cards, start=1):  # 1 起算，對齊既有卡片序號測試先例
        if not isinstance(card, dict):
            return None
        image_prompt, title, description = (
            card.get("image_prompt"), card.get("title"), card.get("description"))
        if not all(isinstance(v, str) and v.strip() for v in (image_prompt, title, description)):
            return None
        components.append({"component_type": "card_image_prompt", "sequence": sequence,
                           "content": image_prompt.strip(), "fingerprint_json": None})
        components.append({"component_type": "card_title", "sequence": sequence,
                           "content": title.strip(), "fingerprint_json": None})
        components.append({"component_type": "card_description", "sequence": sequence,
                           "content": description.strip(), "fingerprint_json": None})
        if narrative_type == "multi_product":
            # 票 07 驗收 4：連結不生成，只佔位——不讀 card 裡任何 link／url 鍵，即使模型
            # 夾帶了也不會被存進去（跟單圖丟棄 cta／link 的做法一致：只認列在上面的三個鍵）。
            components.append({"component_type": "card_product_link", "sequence": sequence,
                               "content": CARD_PRODUCT_LINK_PLACEHOLDER,
                               "fingerprint_json": None})

    raw_body = data.get("body")
    if not isinstance(raw_body, list):
        return None
    for item in raw_body:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        components.append({
            "component_type": "body", "content": content.strip(),
            "fingerprint_json": fp.normalize(item.get("fingerprint")),
        })
    if not any(c["component_type"] == "body" for c in components):
        return None

    return {"name": name.strip(), "components": components}


def _char_budgets(plan: dict) -> dict:
    """{component_type: char_budget}——沒有字數預算的型別（image_prompt）不進來。"""
    return {name: spec["char_budget"] for name, spec in plan.items() if spec.get("char_budget")}


def _char_rewrite_user_text(brief: CreativeBrief, items: list) -> str:
    lines = [
        f"品牌名稱：{brief.brand['name']}",
        "以下幾則 Meta 廣告素材超過字數上限，請逐則改寫到規定字數以內：意思、語氣、宣稱範圍"
        "完全不變，只能精簡用字，不得新增品牌沒有登錄過的宣稱、規格或數據。",
    ]
    for i, item in enumerate(items, start=1):
        lines.append(
            f"{i}. 型別：{item['component_type']}，上限 {item['char_budget']} 字，"
            f"原文（{len(item['content'])} 字）：「{item['content']}」")
    lines.append(
        '輸出格式：只回傳 {"rewrites": ["改寫後第1則", "改寫後第2則", ...]}，陣列長度與順序'
        "要跟上面列出的則數完全對應，每一則只放改寫後的內容本身。"
    )
    return "\n\n".join(lines)


def _call_char_rewrite(conn, brief: CreativeBrief, items: list) -> Optional[list]:
    """走引擎同一生成入口（同一個 PROVIDER、同一個 gateway.run_task）批次重寫超字元件——
    一次呼叫帶全部超字則數，不逐則各打一次（票 05 驗收「觸發一次重寫呼叫」）。
    失敗（AI 沒回、格式讀不成）回 None，呼叫端 fallback＝保留原文、標超字，不擋採用。
    """
    task = gateway.run_task(
        conn, PROVIDER, brand_id=brief.brand["id"], task_type="creative_rewrite",
        prompt_template_id="creative_theme_char_rewrite", prompt_template_version="v1",
        system=_SYSTEM, messages=[{"role": "user",
                                   "content": _char_rewrite_user_text(brief, items)}],
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
    """字數守門（票 05）：量每個文字元件長度（預算來自規格表），超字的帶「壓到 N 字內」
    指令重寫一次，只送超字那幾則（未超字元件零呼叫，不多花錢）；重寫後仍超就標
    `over_budget`，不截斷、不擋採用。這是 ads 存檔前唯一的字數守門點——與 fp.normalize()
    （見 _normalize_single_image()）同一路徑，carousel／video（07／08）的
    generate_*_theme() 之後共用本函式，不各自另建一套。
    """
    budgets = _char_budgets(plan)
    over_idx = [i for i, c in enumerate(components)
               if c["component_type"] in budgets
               and len(c["content"]) > budgets[c["component_type"]]]
    if not over_idx:
        return components

    items = [{"component_type": components[i]["component_type"],
             "char_budget": budgets[components[i]["component_type"]],
             "content": components[i]["content"]} for i in over_idx]
    rewrites = _call_char_rewrite(conn, brief, items)

    for pos, i in enumerate(over_idx):
        candidate = rewrites[pos] if rewrites and pos < len(rewrites) else None
        content = candidate.strip() if isinstance(candidate, str) and candidate.strip() \
            else components[i]["content"]
        components[i]["content"] = content
        components[i]["over_budget"] = len(content) > budgets[components[i]["component_type"]]
    return components


# 相似度標黃門檻（票 06）：兩則元件的指紋 fp.distance()（四軸打分，見
# app/ads/fingerprint.py）小於等於此值視為「幾乎相同」——四軸裡最多 1 軸不同。只寫旗標、
# 不擋存檔、不自動重生，對齊 Meta Andromeda 相似度合併機制：太相似的變體投放端可能被判定
# 成同一支蓋牌，先讓使用者看到、自己決定要不要手動分散。
SIMILARITY_THRESHOLD = 0.25


def _apply_similarity_flag(brief: CreativeBrief, components: list) -> list:
    """存檔前的同批次相似度查核（票 06）：比對「同切角內的變體」——本批新元件彼此之間，
    以及對同格既有主題的元件（brief.existing_themes_summary，brief_assembler 已依切角格
    查好、不再重查 DB）。距離 ≤ SIMILARITY_THRESHOLD 視為幾乎相同，兩則裡較晚出現的那個
    寫 similarity_flag=True；差異夠大就不標。比對重用既有 fp.distance()，不新寫演算法。
    """
    seen = [f for theme in brief.existing_themes_summary for f in theme["fingerprints"] if f]
    for component in components:
        fingerprint = component.get("fingerprint_json")
        if not fingerprint:
            continue
        component["similarity_flag"] = any(
            fp.distance(fingerprint, other) <= SIMILARITY_THRESHOLD for other in seen)
        seen.append(fingerprint)
    return components


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
    generated["components"] = _apply_char_guard(conn, brief, generated["components"], plan)
    generated["components"] = _apply_similarity_flag(brief, generated["components"])
    return generated, None


def generate_carousel_theme(conn, brief: CreativeBrief, *, actor: str,
                            on_stage: Optional[Callable[[str], None]] = None) -> tuple:
    """輪播主題生成（票 07-carousel-theme）。跟 generate_single_image_theme 同一個形狀、
    同一套守門，只有 prompt 組裝（_build_carousel_user_text）與驗證（_normalize_carousel）
    是輪播專屬的；字數守門（_apply_char_guard）與相似度標黃（_apply_similarity_flag）原封
    不動共用單圖那兩個函式（票 07 驗收要求，不得另寫）。

    骨架（narrative_type）沒有參數可傳——brief 跟這支函式的參數都沒有骨架欄位，完全由這次
    AI 回覆決定（_normalize_carousel 驗證用），也因此「改骨架」在使用者操作上只能是整個
    主題退掉重生，沒有「改骨架、卡片留著」這種介面。
    """
    if brief.format_key != "carousel":
        raise ValueError(CAROUSEL_FORMAT_MISMATCH_MESSAGE)
    plan = _carousel_fields_plan(brief.cycle["objective"])

    model = providers.resolve_model(task_type="creative_theme", conn=conn)
    budget_err = coresettings.budget_exceeded_message(
        conn, brief.brand["id"], pricing.cost_ceiling(model, THEME_MAX_TOKENS),
        action="這個主題生成",
        fallback_hint="可以先採用已經產出的主題，或到設定頁調高上限後再試。")
    if budget_err:
        return None, budget_err

    user_text = _build_carousel_user_text(brief, plan)
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

    generated = _normalize_carousel(gateway.parse_json_reply(task["rendered_output"]), plan)
    if generated is None:
        return None, PARSE_FAIL_MESSAGE
    generated["components"] = _apply_char_guard(conn, brief, generated["components"], plan)
    generated["components"] = _apply_similarity_flag(brief, generated["components"])
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
