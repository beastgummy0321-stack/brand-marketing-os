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
    ("proof", "證據"),
    # F42-I01: a store policy (registry `POLICY_TYPES` below). Written only by brand onboarding
    # (`repository.save_brand_policies`); the library fact form does not create it.
    ("policy", "全店政策"),
]

# F38-I01: the six evidence kinds a 「證據」 brand fact can be -- exactly the six `proof`
# coordinate keys (labels copied from the proof seed in app/schedule/repository.py, not
# imported; `none` is not evidence and is not listed here).
PROOF_KINDS = [
    ("customer_review", "顧客評論原話"),
    ("expert_endorsement", "專家背書"),
    ("lab_report", "檢驗報告／認證"),
    ("sales_numbers", "銷售數據"),
    ("media_coverage", "媒體報導"),
    ("founder_voice", "創辦人第一手"),
]

# F42-I01: the tones brand onboarding offers (pick 1–2, plus 「自訂」). Stored as these strings in
# the `tone` brand fact's `params_json.tones`.
TONES = ["親切", "專業", "直接", "幽默", "溫柔", "熱血"]

# F42-I01: what a store policy becomes in an ad -- the `offer` coordinate keys, labelled in the
# onboarding's words (prototype `OFFER` map). `none` = not an offer, a reassurance (安心賣點).
OFFER_LABELS = {
    "free_shipping": "免運",
    "discount": "折扣",
    "bundle": "組合加贈",
    "trial_sample": "試用",
    "guarantee": "保證",
    "limited_time": "限時",
    "none": "安心賣點",
}

# F42-I01: the store-policy registry (prototype `POLICIES`, research 2026-09-30: SHOPLINE /
# CYBERBIZ / Shopify / 蝦皮 / TW supplement shops). Data, not fields: each type has a group, its
# params (name, label, kind ∈ money|text|number|percent; `optional` params may be left empty),
# the offer key it becomes, whether it is shown by default (`common`), the param that is a
# spend threshold (`threshold`, compared with the product's price by `available_offer_keys`),
# and the Chinese `template` that composes the ad-ready sentence (`template_bare` = the sentence
# when the optional threshold is empty or 0). Python is the source; the API ships it to the
# screen. A policy fact stores `fact_key` = key, `params_json` = params, `value` = sentence.
POLICY_TYPES = [
    # 運送
    {"key": "ship_threshold", "group": "運送", "label": "滿額免運",
     "params": [{"name": "threshold", "label": "門檻 NT$", "kind": "money"}],
     "offer_key": "free_shipping", "common": True, "threshold": "threshold",
     "template": "滿 NT${threshold} 免運"},
    {"key": "ship_cvs", "group": "運送", "label": "超商取貨免運",
     "params": [{"name": "threshold", "label": "門檻 NT$（0＝不設）", "kind": "money", "optional": True}],
     "offer_key": "free_shipping", "common": True, "threshold": "threshold",
     "template": "超商取貨滿 NT${threshold} 免運", "template_bare": "超商取貨免運"},
    {"key": "ship_all", "group": "運送", "label": "全館免運", "params": [],
     "offer_key": "free_shipping", "common": False, "threshold": None,
     "template": "全館免運"},
    {"key": "ship_cold", "group": "運送", "label": "冷藏／冷凍配送", "params": [],
     "offer_key": "none", "common": False, "threshold": None,
     "template": "冷藏／冷凍配送"},
    # 首購與會員
    {"key": "first_order", "group": "首購與會員", "label": "新會員首購禮",
     "params": [{"name": "content", "label": "內容", "kind": "text"}],
     "offer_key": "discount", "common": True, "threshold": None,
     "template": "新會員首購禮：{content}"},
    {"key": "signup_credit", "group": "首購與會員", "label": "註冊送購物金",
     "params": [{"name": "amount", "label": "金額 NT$", "kind": "money"}],
     "offer_key": "discount", "common": False, "threshold": None,
     "template": "註冊就送 NT${amount} 購物金"},
    {"key": "tier", "group": "首購與會員", "label": "會員等級折扣",
     "params": [{"name": "tiers", "label": "級距與折扣", "kind": "text"}],
     "offer_key": "discount", "common": False, "threshold": None,
     "template": "會員等級折扣：{tiers}"},
    {"key": "birthday", "group": "首購與會員", "label": "生日禮",
     "params": [{"name": "content", "label": "內容", "kind": "text"}],
     "offer_key": "discount", "common": False, "threshold": None,
     "template": "會員生日禮：{content}"},
    {"key": "points", "group": "首購與會員", "label": "購物金／點數回饋",
     "params": [{"name": "rate", "label": "回饋 %", "kind": "percent"}],
     "offer_key": "discount", "common": False, "threshold": None,
     "template": "消費回饋 {rate}% 購物金"},
    {"key": "line", "group": "首購與會員", "label": "加 LINE 好友禮",
     "params": [{"name": "content", "label": "內容", "kind": "text"}],
     "offer_key": "discount", "common": False, "threshold": None,
     "template": "加 LINE 好友禮：{content}"},
    # 滿額與贈品
    {"key": "spend_off", "group": "滿額與贈品", "label": "滿額折",
     "params": [{"name": "threshold", "label": "滿 NT$", "kind": "money"},
                {"name": "off", "label": "折 NT$ 或 %", "kind": "text"}],
     "offer_key": "discount", "common": True, "threshold": "threshold",
     "template": "滿 NT${threshold} 折 {off}"},
    {"key": "spend_gift", "group": "滿額與贈品", "label": "滿額贈",
     "params": [{"name": "threshold", "label": "滿 NT$", "kind": "money"},
                {"name": "gift", "label": "送什麼", "kind": "text"}],
     "offer_key": "bundle", "common": True, "threshold": "threshold",
     "template": "滿 NT${threshold} 送{gift}"},
    {"key": "mix", "group": "滿額與贈品", "label": "任選 N 件／買 X 送 Y",
     "params": [{"name": "rule", "label": "規則", "kind": "text"}],
     "offer_key": "bundle", "common": True, "threshold": None,
     "template": "{rule}"},
    {"key": "addon", "group": "滿額與贈品", "label": "加價購",
     "params": [{"name": "item", "label": "加購品與價格", "kind": "text"}],
     "offer_key": "bundle", "common": False, "threshold": None,
     "template": "加價購：{item}"},
    {"key": "sample", "group": "滿額與贈品", "label": "免費試吃包",
     "params": [{"name": "how", "label": "怎麼拿", "kind": "text"}],
     "offer_key": "trial_sample", "common": False, "threshold": None,
     "template": "免費試吃包（{how}）"},
    # 訂閱與回購
    {"key": "subscribe", "group": "訂閱與回購", "label": "定期配送折扣",
     "params": [{"name": "discount", "label": "每期折扣", "kind": "text"},
                {"name": "min_cycles", "label": "最少幾期", "kind": "number"}],
     "offer_key": "discount", "common": True, "threshold": None,
     "template": "定期配送每期 {discount}（至少 {min_cycles} 期）"},
    {"key": "cancel_any", "group": "訂閱與回購", "label": "訂閱可隨時取消", "params": [],
     "offer_key": "none", "common": False, "threshold": None,
     "template": "訂閱可隨時取消"},
    # 退換與保證
    {"key": "satisfaction", "group": "退換與保證", "label": "延長退換／不滿意退費",
     "params": [{"name": "terms", "label": "天數與條件", "kind": "text"}],
     "offer_key": "guarantee", "common": True, "threshold": None,
     "template": "退換保證：{terms}"},
    {"key": "shelf", "group": "退換與保證", "label": "效期保證",
     "params": [{"name": "min_shelf", "label": "出貨效期至少", "kind": "text"}],
     "offer_key": "none", "common": False, "threshold": None,
     "template": "出貨效期至少 {min_shelf}"},
    # 付款
    {"key": "installment", "group": "付款", "label": "信用卡分期 0 利率",
     "params": [{"name": "terms", "label": "期數與門檻", "kind": "text"}],
     "offer_key": "none", "common": False, "threshold": None,
     "template": "信用卡分期 0 利率（{terms}）"},
    {"key": "cod", "group": "付款", "label": "貨到付款", "params": [],
     "offer_key": "none", "common": False, "threshold": None,
     "template": "可貨到付款"},
    {"key": "wallet_bonus", "group": "付款", "label": "行動支付回饋加碼",
     "params": [{"name": "terms", "label": "回饋與期間", "kind": "text"}],
     "offer_key": "limited_time", "common": False, "threshold": None,
     "template": "行動支付回饋加碼：{terms}"},
    # 出貨與服務
    {"key": "fast", "group": "出貨與服務", "label": "24 小時內出貨",
     "params": [{"name": "cutoff", "label": "截單時間", "kind": "text"}],
     "offer_key": "none", "common": False, "threshold": None,
     "template": "{cutoff}前下單，24 小時內出貨"},
    {"key": "gift_box", "group": "出貨與服務", "label": "禮盒包裝", "params": [],
     "offer_key": "none", "common": False, "threshold": None,
     "template": "提供禮盒包裝"},
    {"key": "consult", "group": "出貨與服務", "label": "營養師／專人諮詢", "params": [],
     "offer_key": "none", "common": False, "threshold": None,
     "template": "提供營養師／專人諮詢"},
    # 其他
    {"key": "promo_code", "group": "其他", "label": "常態優惠碼",
     "params": [{"name": "code", "label": "碼與額度", "kind": "text"}],
     "offer_key": "discount", "common": False, "threshold": None,
     "template": "常態優惠碼：{code}"},
]
POLICY_TYPES_BY_KEY = {p["key"]: p for p in POLICY_TYPES}

# The 7-day cooling-off (消保法 §19) always applies and is shown fixed; a brand selling a statutory
# exception stores ONE policy fact with this key and `params_json.disclosure` (the notice on its
# web page, ≥10 chars). No row = applies. Not an offer.
COOLING_OFF_EXEMPT_KEY = "cooling_off_exempt"
COOLING_OFF_EXEMPT_LABEL = "7 天猶豫期不適用"
COOLING_OFF_DISCLOSURE_MIN_CHARS = 10

# A brand's own policy (「自訂」): `params_json` = {label, offer_key ∈ OFFER_LABELS}; its sentence
# is written by the onboarding (user-confirmed), not composed from a template.
CUSTOM_POLICY_KEY = "custom"


def _policy_number(raw, *, label: str):
    """money / number / percent value -> int (or float when fractional); ValueError otherwise."""
    if isinstance(raw, bool):
        raise ValueError(f"「{label}」要填數字")
    if isinstance(raw, (int, float)):
        n = raw
    else:
        text = str(raw).strip().replace(",", "").replace("NT$", "").replace("%", "").strip()
        try:
            n = float(text)
        except ValueError:
            raise ValueError(f"「{label}」要填數字") from None
    if n < 0:
        raise ValueError(f"「{label}」不能是負數")
    return int(n) if float(n).is_integer() else float(n)


def normalize_policy_params(key: str, params: dict | None) -> dict:
    """Check a registry policy's params against `POLICY_TYPES` and return them normalized
    (numbers as numbers, text stripped; an empty optional param is dropped). Unknown key, unknown
    param, a missing required param or a bad value -> ValueError."""
    spec = POLICY_TYPES_BY_KEY.get(key)
    if spec is None:
        raise ValueError(f"未知的全店政策：{key}")
    params = dict(params or {})
    names = {p["name"] for p in spec["params"]}
    unknown = set(params) - names
    if unknown:
        raise ValueError(f"「{spec['label']}」沒有這個欄位：{'、'.join(sorted(unknown))}")
    out: dict = {}
    for p in spec["params"]:
        raw = params.get(p["name"])
        empty = raw is None or (isinstance(raw, str) and not raw.strip())
        if empty:
            if p.get("optional"):
                continue
            raise ValueError(f"「{spec['label']}」要填「{p['label']}」")
        if p["kind"] == "text":
            out[p["name"]] = str(raw).strip()
            continue
        n = _policy_number(raw, label=p["label"])
        if p["kind"] == "percent" and not (0 < n <= 100):
            raise ValueError(f"「{p['label']}」要介於 0 到 100")
        out[p["name"]] = n
    return out


def _policy_display(value, kind: str) -> str:
    if kind == "money":
        return f"{value:,}"
    return str(value)


def policy_sentence(key: str, params: dict | None) -> str:
    """Compose a registry policy's ad-ready sentence from its params (e.g. ship_threshold
    {threshold: 999} -> 「滿 NT$999 免運」). The cooling-off exemption's sentence is its disclosure.
    Validates like `normalize_policy_params`; custom policies carry their own sentence."""
    if key == COOLING_OFF_EXEMPT_KEY:
        disclosure = str((params or {}).get("disclosure") or "").strip()
        if len(disclosure) < COOLING_OFF_DISCLOSURE_MIN_CHARS:
            raise ValueError(f"不適用 7 天猶豫期，要填網頁上的告知文字（至少 {COOLING_OFF_DISCLOSURE_MIN_CHARS} 字）")
        return disclosure
    spec = POLICY_TYPES_BY_KEY.get(key)
    if spec is None:
        raise ValueError(f"未知的全店政策：{key}")
    clean = normalize_policy_params(key, params)
    if spec.get("template_bare") and not clean.get(spec["threshold"]):
        return spec["template_bare"]
    kinds = {p["name"]: p["kind"] for p in spec["params"]}
    return spec["template"].format(**{k: _policy_display(v, kinds[k]) for k, v in clean.items()})


def offer_label(v):
    return OFFER_LABELS.get(v, v)


PRODUCT_FACT_TYPES = [
    ("core_info", "核心資訊"),
    ("mechanism", "作用機制"),
    ("differentiation", "差異化"),
    ("scenario", "使用情境"),
    ("audience", "目標客群"),
    ("visual_style", "視覺風格"),
    # F43-I01: a product's own evidence; `product_fact.fact_key` names which of the six proof
    # kinds it is (same CHECK pair as brand_fact). Reader: available_proof_keys.
    ("proof", "證據"),
]

# F43-I01: the six `pain` keys a product customer group may name (1-2 each), with the seed labels
# of the brand `pain` coordinates (app/schedule/repository.py _SEED_COORDINATES, copied, not
# imported). The DB CHECK on product_customer_group.pain_keys holds the same keys.
PAIN_KINDS = [
    ("cost", "太貴"),
    ("effort", "太麻煩"),
    ("uncertainty", "怕買錯"),
    ("availability", "買不到"),
    ("experience", "用起來不舒服"),
    ("identity", "不像我"),
]
PAIN_KEYS = tuple(k for k, _ in PAIN_KINDS)

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
    ("product_photo", "商品參考照"),
    ("packaging", "包裝"),
    # F42-I01: brand photos asked at brand onboarding (`product_id` NULL).
    ("store", "門市／工作室"),
    ("team", "團隊／創辦人"),
    ("brand_image", "品牌形象"),
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


def proof_kind_label(v):
    return _label(PROOF_KINDS, v)


def product_fact_type_label(v):
    return _label(PRODUCT_FACT_TYPES, v)


def pain_label(v):
    return _label(PAIN_KINDS, v)


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
