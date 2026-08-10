# -*- coding: utf-8 -*-
"""app/creative/theme_engine.py — 主題生成引擎的純函式庫（票 14-engine-move，搬自
app/ads/theme_engine.py）。

無狀態零件：規格表＋簡報進、prompt 文字或驗證結果出，不呼叫 AI、不碰 DB、不 import
app.ads（依賴方向鐵則，見 app/creative/__init__.py）——連 app.llm 都不 import：AI 呼叫
（`gateway.run_task`）、花費上限查核（`app.core.settings`）是「跑」這個引擎的責任，留在
app/ads/theme_engine.py 當呼叫端的orchestration；本檔只管兩件事：組 prompt 文字、驗證＋
整理 AI 回覆。這樣「未來 blog／SEO 上游接上時零改動」（spec 使用者故事 22）才成立——換一個
呼叫端，AI 客戶端／花費規則可能整套不同，但組 prompt 與驗證回覆的邏輯不必重寫。

**指紋（`fp`）一律用參數注入，不 import**：`app/ads/fingerprint.py` 一行不改留在 ads
（spec 明文），本檔因此不能 `from app.ads import fingerprint`——凡是原本呼叫
`fp.normalize()`／`fp.describe()`／`fp.distance()` 的地方，改成吃呼叫端傳進來的 `fp`
參數（ads 端傳真正的 `app.ads.fingerprint` 模組進來）；`fp.prompt_vocabulary()` 那則已經
在 brief 組裝階段（app/ads/brief_assembler.py）算成字串放進 `brief.fingerprint_vocabulary`，
本檔原本就只吃這個字串，不必額外注入。

原本模組內部函式（`_build_user_text` 等）跨到 ads 呼叫後不再是「同檔內部」，票 14 搬家時
一併拿掉前導底線改成公開名字——純屬搬家造成的可見度調整，邏輯本身一行未改。

字數守門（票 05-char-guard）：`over_budget_items()` 算出哪些元件超字並組好重寫請求，AI
真正重寫的呼叫是 ads 的事；重寫結果回來後呼叫 `apply_char_rewrites()` 寫回、標記
`over_budget`，仍超就標、不截斷、不擋採用。

同批次相似度標黃（票 06-similarity-flag）：`apply_similarity_flag()` 用呼叫端傳入的
`fp.distance()` 比對本批新元件彼此、以及對同格既有主題的元件，過近寫 `similarity_flag`，
不擋存檔、不自動重生。

影片格式（票 08-video-theme）在 app/creative/theme_engine_video.py（獨立成檔的理由見該檔
檔頭），共用本檔的字數守門與相似度標黃函式，不另寫一套。
"""

from typing import Optional

from app.creative.format_specs import FORMAT_SPECS, QUICK_GENERATE_SCOPES

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

SYSTEM_PROMPT = (
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


def single_image_fields_plan(objective: str) -> dict:
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


def carousel_fields_plan(objective: str) -> dict:
    """規格表 → carousel 各欄位的字數預算。跟單圖不同，carousel 五種行銷目標的
    media_cap_per_theme 都固定是 1（一套敘事＝一則廣告），沒有目標差異可查，這裡只做
    「目標存在於規格表」的輸入驗證（沿用 single_image_fields_plan 同款防呆），卡片數量
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


def build_quick_generate_plan(scope: str) -> dict:
    """快速生成（票 01-quick-generate-endpoint）：scope → 該類型要顯示的欄位子集與數量。

    沒有行銷目標（objective）可查，因此不呼叫 single_image_fields_plan()／
    video_fields_plan()（那兩支函式的 image_prompt 數量依 media_cap_per_theme 調整），直接
    從 FORMAT_SPECS 原始欄位定義取 QUICK_GENERATE_SCOPES[scope]["fields"] 那個子集——不是
    新邏輯，只是換一張表挑欄位。回傳值只給呼叫端拿去判斷「這個類型要顯示哪些欄位」，不是
    餵給 build_single_image_prompt()／build_video_prompt() 的 plan 參數（那兩支函式的 plan
    引數結構固定要求 image_prompt/body/title/description 或 body/title/description 全部
    到齊，是既有生成引擎的介面，不因為快速生成而改）。
    """
    if scope not in QUICK_GENERATE_SCOPES:
        raise ValueError(f"快速生成不支援「{scope}」這個類型")
    scope_spec = QUICK_GENERATE_SCOPES[scope]
    fields = FORMAT_SPECS[scope_spec["base_format"]]["fields"]
    return {name: dict(fields[name]) for name in scope_spec["fields"]}


def build_single_image_prompt(brief, plan: dict, fp) -> str:
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


def build_carousel_prompt(brief, plan: dict, fp) -> str:
    """組輪播 prompt：跟 build_single_image_prompt 共用前半段材料組裝（品牌／打法／切角／
    品牌 context／優惠／方法論／拒絕記憶／顧客語料／防撞衫摘要），差異只在最後「這次要產
    什麼」那段——輪播多一段敘事骨架三選一的說明，且沒有骨架參數可以指定（票 07 驗收 3：
    骨架完全由這次呼叫的 AI 回覆決定，簡報跟這個函式都不吃骨架輸入）。
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


def normalize_single_image(data, plan: dict, fp) -> Optional[dict]:
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


def normalize_carousel(data, plan: dict, fp) -> Optional[dict]:
    """驗證輪播形狀，回傳跟 normalize_single_image 同一種扁平 {"name", "components"}——
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


def char_budgets(plan: dict) -> dict:
    """{component_type: char_budget}——沒有字數預算的型別（image_prompt）不進來。"""
    return {name: spec["char_budget"] for name, spec in plan.items() if spec.get("char_budget")}


def char_rewrite_prompt(brief, items: list) -> str:
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


def over_budget_items(components: list, plan: dict) -> tuple:
    """字數守門（票 05）第一步：量每個文字元件長度（預算來自規格表），抓出超字的位置與
    要送進重寫呼叫的資料。回傳 (over_idx, items, budgets)；over_idx 空代表沒有超字元件，
    呼叫端可以直接跳過整段重寫流程（未超字元件零呼叫，不多花錢）。
    """
    budgets = char_budgets(plan)
    over_idx = [i for i, c in enumerate(components)
               if c["component_type"] in budgets
               and len(c["content"]) > budgets[c["component_type"]]]
    items = [{"component_type": components[i]["component_type"],
             "char_budget": budgets[components[i]["component_type"]],
             "content": components[i]["content"]} for i in over_idx]
    return over_idx, items, budgets


def apply_char_rewrites(components: list, over_idx: list, budgets: dict,
                        rewrites: Optional[list]) -> list:
    """字數守門（票 05）第二步：AI 重寫呼叫（ads 端執行）回來後，寫回內容並標記
    `over_budget`——重寫後仍超就標，不截斷、不擋採用；`rewrites` 為 None（呼叫失敗／格式
    讀不成）時 fallback＝保留原文、標超字。
    """
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


def apply_similarity_flag(brief, components: list, fp) -> list:
    """存檔前的同批次相似度查核（票 06）：比對「同切角內的變體」——本批新元件彼此之間，
    以及對同格既有主題的元件（brief.existing_themes_summary，brief_assembler 已依切角格
    查好、不再重查 DB）。距離 ≤ SIMILARITY_THRESHOLD 視為幾乎相同，兩則裡較晚出現的那個
    寫 similarity_flag=True；差異夠大就不標。比對重用呼叫端傳入的 fp.distance()，不新寫
    演算法。
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


# ---------------------------------------------------------------------------
# 元件重打指紋（票 12-attribution-adjust D 段）：無狀態入口——只吃文字組 prompt、驗回覆，
# 不碰 DB、不知道呼叫端是哪個元件。app/ads/theme_attribution.py 偵測到 Meta 端文案跟
# 系統存檔不一致（被人工改過）時呼叫這兩個函式（ads 端夾一個 AI 呼叫），自己另外把結果
# 寫回 creative_theme_component 與稽核紀錄——重打指紋這件事本身不在同步碼裡手刻，一律走
# 這個引擎入口（票 12 驗收 3）。
# ---------------------------------------------------------------------------

COMPONENT_FINGERPRINT_MAX_TOKENS = 1000  # 只分類一則短文案，遠小於整包主題生成


def build_refingerprint_prompt(text: str, fp) -> str:
    return (
        "這則 Meta 廣告文案的內容如下，請幫它標四軸指紋，值只能從下面挑，不可以自己"
        "發明：\n" + fp.prompt_vocabulary()
        + f"\n\n文案內容：「{text}」\n\n只回傳 JSON："
        '{"fingerprint": {"angle":"...","tone":"...","format":"...","selling_point":"..."}}'
    )


def parse_refingerprint_reply(data, fp) -> Optional[dict]:
    fingerprint = fp.normalize(data.get("fingerprint")) if isinstance(data, dict) else {}
    return fingerprint or None
