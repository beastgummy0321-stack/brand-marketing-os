# -*- coding: utf-8 -*-
"""app/mock_data.py — UI 用語對照表（固定選項清單／label 函式）與示範資料內容定義。

Phase 0 SQLite 資料層上線後（見 app/brand_intelligence/repository.py），本檔不再是
即時資料來源：沒有 BRANDS/PRODUCTS 這類記憶體內的活資料，也不提供任何 CRUD 函式，
那些工作全部交給 repository.py（見 app/main.py 怎麼呼叫）。

留下來的東西只有兩類：
1. 畫面固定選項清單與內部值 -> 人話對照表（*_TYPES 常數、*_label 函式、幣別符號），
   這些是 UI 用語規範，不是資料，繼續由這裡當唯一來源（畫面渲染一律經這裡的對照表
   轉成人話，不得把內部值直接印到畫面上）。
2. DEMO_BRANDS：示範資料的「內容」定義（文字、金額、選項），供 app/seed_demo.py 寫進
   DB 用；建立時間、確認時間、版本號等一律由資料層在寫入當下產生，不在這裡預先寫死。
"""

# ---------------------------------------------------------------------------
# 固定選項清單（畫面用語 -> 內部值 由各自的 *_LABELS dict 提供）
# ---------------------------------------------------------------------------

BRAND_FACT_TYPES = [
    ("positioning", "定位"),
    ("audience", "受眾"),
    ("tone", "語調"),
    ("channel", "通路"),
    ("regulatory", "法規限制"),
    ("visual_base", "視覺基礎"),
]

PRODUCT_FACT_TYPES = [
    ("core_info", "核心資訊"),
    ("mechanism", "作用機制"),
    ("differentiation", "差異化"),
    ("scenario", "使用情境"),
    ("audience", "目標客群"),
    ("visual_style", "視覺風格"),
]

RULE_TYPES = [
    ("tone", "語氣"),
    ("visual", "視覺"),
    ("forbidden_word", "禁用字詞"),
    ("asset_usage", "素材使用"),
    ("platform_spec", "平台規格"),
    ("policy", "政策"),
]

CLAIM_TYPES = [
    ("approved", "可用"),
    ("high_risk", "高風險"),
    ("forbidden", "禁用"),
]

CHANNEL_TYPES = [
    ("website", "官方網站"),
    ("fb_page", "粉絲專頁"),
    ("ig_account", "Instagram 帳號"),
]

ASSET_KINDS = [
    ("logo", "Logo"),
    ("product_photo", "產品照"),
    ("packaging", "包裝"),
    ("other", "其他"),
]

CUSTOMER_VOICE_CHANNELS = [
    ("shopee", "蝦皮商品評論"),
    ("momo", "momo 商品評論"),
    ("dcard", "Dcard"),
    ("ptt", "PTT"),
    ("fb_group", "FB 社團／粉專留言"),
    ("customer_service", "客服對話紀錄"),
    ("other", "其他"),
]

CUSTOMER_VOICE_TASK_LAYERS = {
    "functional": "功能任務",
    "emotional": "情感任務",
    "social": "社會任務",
}

CUSTOMER_VOICE_SIGNALS = {
    "unprompted": "主動提及（訊號較強）",
    "prompted": "被提示才講（訊號較弱）",
}

CURRENCIES = [
    ("TWD", "新台幣（TWD）"),
    ("USD", "美元（USD）"),
    ("CNY", "人民幣（CNY）"),
]

CURRENCY_SYMBOLS = {"TWD": "NT$", "USD": "$", "CNY": "¥"}

BRAND_COLOR_PALETTE = [
    "#1A5FB4",  # 藍
    "#1E7A46",  # 綠
    "#8A5B00",  # 琥珀
    "#8B2F6B",  # 紫紅
    "#0F6E75",  # 青
    "#7A4A1E",  # 棕
]


def _label(pairs, value):
    for internal, human in pairs:
        if internal == value:
            return human
    return value


def brand_fact_type_label(v):
    return _label(BRAND_FACT_TYPES, v)


def product_fact_type_label(v):
    return _label(PRODUCT_FACT_TYPES, v)


def rule_type_label(v):
    return _label(RULE_TYPES, v)


def claim_type_label(v):
    return _label(CLAIM_TYPES, v)


def channel_type_label(v):
    return _label(CHANNEL_TYPES, v)


def asset_kind_label(v):
    return _label(ASSET_KINDS, v)


def customer_voice_channel_label(v):
    return _label(CUSTOMER_VOICE_CHANNELS, v)


def customer_voice_task_layer_label(v):
    return CUSTOMER_VOICE_TASK_LAYERS.get(v, v)


def customer_voice_signal_label(v):
    return CUSTOMER_VOICE_SIGNALS.get(v, v)


def currency_label(v):
    return _label(CURRENCIES, v)


def currency_symbol(v):
    return CURRENCY_SYMBOLS.get(v, v)


# ---------------------------------------------------------------------------
# 示範資料內容定義（供 app/seed_demo.py 寫進 DB；欄位名沿用資料模型的內部名）
# ---------------------------------------------------------------------------

DEMO_BRANDS = [
    {
        # ---- 品牌 A：青原生活（示範資料）—— 完整示範 ----
        "name": "青原生活（示範資料）",
        "client_name": "自營",
        "brand_facts": [
            {
                "fact_type": "positioning", "label": "價格帶與訴求",
                "value": "主打台灣本地小農原料的日常保健品牌，價格帶落在市面同類產品中段，"
                         "訴求「成分看得懂」而不是最低價。",
                "status": "confirmed", "confirmed_by": "小陳",
                "source_reference": "2025-03 客戶提供的品牌手冊 p.4",
            },
            {
                "fact_type": "audience", "label": "主要購買者輪廓",
                "value": "30–45 歲女性上班族，家中多有學齡子女，習慣在 Facebook 與 LINE 群組接收資訊，"
                         "購買前會查成分表與產地。",
                "status": "confirmed", "confirmed_by": "小陳",
                "source_reference": "2025-03 客戶訪談紀錄",
            },
            {
                "fact_type": "tone", "label": "說話的方式",
                "value": "像認識很久的營養師朋友：講人話、給具體建議、不用驚嘆號，"
                         "也不用「最強」「第一」這類字眼。",
                "status": "confirmed", "confirmed_by": "小陳",
                "source_reference": "2025-04 客戶溝通會議紀錄",
            },
            {
                "fact_type": "channel", "label": "銷售通路分布",
                "value": "官網直營為主，約占七成營收；其餘來自蝦皮商城與兩家實體藥局寄售。",
                "status": "confirmed", "confirmed_by": "小陳",
                "source_reference": "2025-05 業主口頭提供",
            },
            {
                "fact_type": "regulatory", "label": "食品廣告規範",
                "value": "所有文案不得出現療效字樣，食品類廣告需符合食品安全衛生管理法第 28 條與健康食品"
                         "管理法相關規定；任何功能性宣稱一律先回查第三方檢驗或官方公告來源再使用，行銷"
                         "團隊不得自行推論保健功效，不得使用「治療」「根治」「替代藥物」等字樣，也不得暗示"
                         "可預防或治癒任何疾病；圖片、影片字卡與網紅口播的用詞比照本規範辦理，若不確定用詞"
                         "是否合規，一律先送法務或客戶確認後才可對外露出，避免事後下架造成商譽損失。",
                "status": "confirmed", "confirmed_by": "小陳",
                "source_reference": "2025-03 客戶提供的品牌手冊 p.12",
            },
            {
                "fact_type": "visual_base", "label": "主色與字體",
                "value": "主色為淺米與深綠，字體使用思源黑體；但 2024 年之後的新包裝似乎改過一次配色，"
                         "需要向客戶確認現行版本再寫成事實。",
                "status": "pending",
            },
            {
                "fact_type": "audience", "label": "高齡客群回購",
                "value": "業主口頭提到近期有較多 50 歲以上客群回購，目前還沒有看到後台數據佐證，"
                         "先不列入受眾事實。",
                "status": "pending",
            },
            {
                "fact_type": "channel", "label": "量販通路洽談中",
                "value": "聽說正在談量販通路上架，還沒簽約，等確定之後再更新通路事實。",
                "status": "pending",
            },
        ],
        "rules": [
            {"rule_type": "forbidden_word", "severity": "hard", "product_ref": None,
             "content": "文案禁止出現「療效」「治療」「根治」「替代藥物」等字樣，圖片上的文字也算。"},
            {"rule_type": "asset_usage", "severity": "hard", "product_ref": None,
             "content": "未經客戶提供的產品照不得用 AI 生成替代；產品外包裝一律使用官方素材。"},
            {"rule_type": "tone", "severity": "soft", "product_ref": None,
             "content": "盡量不用驚嘆號，一則貼文最多一個。"},
            {"rule_type": "visual", "severity": "soft", "product_ref": "p1",
             "content": "盡量避免純白背景的去背圖，品牌偏好有生活感的情境照。"},
        ],
        "claims": [
            {"claim_text": "每份含 500 毫克台灣產薑黃萃取物", "claim_type": "approved",
             "evidence_source_reference": "2025-03 第三方成分檢驗報告", "product_ref": "p1"},
            {"claim_text": "原料通過 481 項農藥殘留檢驗", "claim_type": "approved",
             "evidence_source_reference": "2025-03 檢驗機構報告", "product_ref": None},
            {"claim_text": "有助於維持消化道機能", "claim_type": "high_risk",
             "evidence_source_reference": None, "product_ref": "p1"},
            {"claim_text": "改善關節疼痛", "claim_type": "forbidden",
             "evidence_source_reference": None, "product_ref": None},
            {"claim_text": "可以取代醫師處方", "claim_type": "forbidden",
             "evidence_source_reference": None, "product_ref": None},
        ],
        "channels": [
            {
                "channel_type": "website", "name": "青原生活官方商店", "status": "active",
                # 刻意使用較長網址，驗收長網址在表格內不撐破版面（DESIGN.md §14.3 邊界情境）
                "identifier": "https://example.com/store?utm_source=demo&utm_medium=referral"
                               "&utm_campaign=brand-profile-showcase&ref=longurl-test",
            },
            {"channel_type": "fb_page", "name": "青原生活", "identifier": "@qingyuan-example",
             "status": "active"},
        ],
        "products": [
            {
                "ref": "p1", "name": "日常薑黃錠 60 錠",
                "facts": [
                    {"fact_type": "core_info", "label": "規格與售價定位",
                     "value": "一瓶 60 錠，一日一錠，一瓶約可吃兩個月；定價落在同類產品中段。",
                     "status": "confirmed", "confirmed_by": "小陳", "source_reference": "2025-04 產品規格書"},
                    {"fact_type": "mechanism", "label": "主要成分",
                     "value": "以台灣產薑黃萃取物為主，搭配黑胡椒萃取物以協助吸收。",
                     "status": "confirmed", "confirmed_by": "小陳", "source_reference": "2025-04 產品規格書"},
                    {"fact_type": "scenario", "label": "什麼時候吃",
                     "value": "多數回購者在早餐後服用，主要動機是應酬多、外食比例高。",
                     "status": "confirmed", "confirmed_by": "小陳", "source_reference": "2025-04 產品規格書"},
                    {"fact_type": "differentiation", "label": "與競品的差別",
                     "value": "業主說吸收率比市面產品高，但目前只有原料商提供的資料，沒有第三方比較試驗，"
                              "先列待確認。",
                     "status": "pending"},
                ],
                "economics": {
                    "selling_price": 1280, "fixed_cost": 0, "unit_variable_cost": 430, "shipping_cost": 60,
                    "currency": "TWD",
                    "cpa_roas_basis": "以完成結帳的訂單計算 CPA，運費由品牌吸收，ROAS 以含稅售價計算",
                    "effective_from": "2025-06-01", "confirmed_by": "小陳",
                },
            },
            {
                # 刻意留空產品經濟數字，展示區塊級 empty state
                "ref": "p2", "name": "舒眠複方飲 14 入",
                "facts": [
                    {"fact_type": "core_info", "label": "規格",
                     "value": "一盒 14 入，每入 50 毫升，建議睡前 30 分鐘飲用。",
                     "status": "confirmed", "confirmed_by": "小陳", "source_reference": "2025-04 產品規格書"},
                    {"fact_type": "audience", "label": "主要購買者",
                     "value": "初步觀察是加班族與輪班工作者，還在等客戶提供訂單資料驗證。",
                     "status": "pending"},
                ],
                "economics": None,
            },
        ],
    },
    {
        # ---- 品牌 B：森野工坊（示範資料）—— 全空，展示 empty state ----
        "name": "森野工坊（示範資料）",
        "client_name": "森野國際（示範資料）",
        "brand_facts": [], "rules": [], "claims": [], "channels": [], "products": [],
    },
    {
        # ---- 品牌 C：小滿製茶（示範資料）—— 建檔精靈進行中（DESIGN.md §14.3） ----
        # 品牌檔案頁跟品牌 B 一樣全空：精靈還沒有把任何內容變成事實，這正是鐵律 R5
        # （貼回內容必須人工逐條確認）的視覺證據。草稿本身（第 3 步、已答 2 題、花費
        # $7.20）由 app/seed_demo.py 呼叫 app.intake.state.seed_in_progress_draft() 生出，
        # 寫進 intake_draft 資料表（含三筆示範 llm_task 撐起花費明細），不在這裡。
        "name": "小滿製茶（示範資料）",
        "client_name": "小滿食品（示範資料）",
        "brand_facts": [], "rules": [], "claims": [], "channels": [], "products": [],
        "seed_intake_draft": True,
    },
]
