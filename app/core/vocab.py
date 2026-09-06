"""app/core/vocab.py — UI 用語對照表（固定選項清單／label 函式）。

票 02-3a 從 app/mock_data.py 搬來（ADR 0027，SaaS 資料層重寫）：這裡只留 UI 用語規範，
不是資料，畫面渲染一律經這裡的對照表轉成人話，不得把內部值直接印到畫面上。

示範資料的「內容」定義（原 DEMO_BRANDS）隨 app/seed_demo.py 一併刪除（票 02-3a）：
SaaS 目標下示範品牌改走別的路徑，不在啟動流程寫死種子資料。
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
    # 票 10-feedback-entries（ADR 0037）：檔期排程模組的偏好類別，soft 回饋專用；
    # hard 回饋一律強制 forbidden_word，不接受下面這五種。
    ("angle", "切角"),
    ("audience", "受眾"),
    ("product_pick", "商品選擇"),
    ("budget_split", "預算分配"),
    ("other", "其他"),
    # issue adopted-advice-can-invert（2026-09-06 演練）：採用一條成效判讀寫出來的那一列。
    # 它是「這一期要去做的事」，不是「不准做的事」——三個角色各採用一條，其中一條被下一期
    # 的方案讀成相反的意思（建議「測試加入證明內容」，方案寫成「不加入未被證實的見證」），
    # 因為 `context_compiler` 把所有規則都放進【限制】那一段。行動與限制從此分兩個抽屜。
    ("experiment", "本期要測的"),
]

# 採用成效判讀寫出來的規則型別。`app/schedule/routes.py` 寫、`app/llm/context_compiler.py`
# 讀，兩邊都指這一個名字，不各自寫一次字串。
EXPERIMENT_RULE_TYPE = "experiment"

CLAIM_TYPES = [
    ("approved", "可用"),
    ("high_risk", "高風險"),
    ("forbidden", "禁用"),
]

CHANNEL_TYPES = [
    ("website", "官方網站"),
    ("fb_page", "粉絲專頁"),
    ("ig_account", "Instagram 帳號"),
    ("line", "LINE 官方帳號"),
    ("marketplace", "平台商店"),
    ("physical_store", "實體店"),
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

# 人設 → 方法論開關預設值（票 A：填表捷徑，不進 DB、不進 prompt。選人設＝一次填好
# app.brand_intelligence.repository.compute_methodology_switches 四個開關的預設值，
# 之後每個開關仍可個別覆寫，不做 UI，先只留常數＋展開函式）。
PERSONA_TYPES = [
    ("kol", "KOL／創作者"),
    ("brand", "品牌／商家"),
    ("solo_seller", "個人賣家"),
    ("service_booking", "服務／預約制"),
    ("other", "其他"),
]

PERSONA_SWITCH_DEFAULTS = {
    "kol": {"有商品": False, "站內交易": False, "有自有網站": False, "健康類法規": False},
    "brand": {"有商品": True, "站內交易": True, "有自有網站": True, "健康類法規": False},
    "solo_seller": {"有商品": True, "站內交易": True, "有自有網站": False, "健康類法規": False},
    "service_booking": {"有商品": False, "站內交易": False, "有自有網站": True, "健康類法規": False},
    "other": {"有商品": False, "站內交易": False, "有自有網站": False, "健康類法規": False},
}


def persona_switch_defaults(persona: str) -> dict:
    """把人設代號展開成方法論開關預設值；只是填表捷徑，每個開關之後都可個別覆寫。"""
    if persona not in PERSONA_SWITCH_DEFAULTS:
        raise ValueError(f"未知人設：{persona}")
    return dict(PERSONA_SWITCH_DEFAULTS[persona])


# 品牌編輯頁用語（票 C：market_region／conversion_goal 下拉選單）。
# MARKET_REGIONS：這一版方法論只有台灣市場的內容，所以只給一個實值；「未設定」是
# 選單的另一個選項，模板另外手寫，不放進這份清單（比照 fact_new.html「請選擇」的寫法）。
MARKET_REGIONS = [
    ("TW", "台灣"),
]

# conversion_goal 內部值→白話中文，順序對齊
# app.brand_intelligence.repository.CONVERSION_GOALS（該檔是值域的唯一來源，不得存
# Meta 事件名，見該檔註解）。畫面只顯示這裡的中文，不印英文值。
CONVERSION_GOAL_LABELS = {
    "purchase": "購買",
    "lead": "留資料",
    "booking": "預約",
    "awareness": "認識品牌",
}

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
