# -*- coding: utf-8 -*-
"""app/ads/fingerprint.py — 素材指紋與拒絕理由的封閉枚舉（票 6，定版票 C 線 #52）。

拒絕記憶（ADHD 設計輸入方向二）整套押在這張表上：使用者按「不要這個」時，
系統記下的不是一段自由文字，而是這幾個軸上的**結構化標籤**。因為是封閉枚舉，
所以「累積了哪些拒絕」「下期要避開什麼」「同一類被拒幾次了」全部由程式判定，
LLM 只負責把結果翻成人話（決策 0016 硬性原則 4）。

**本表為定版**（決策 0030 第二節，使用者 2026-08-02 逐條審畢；承決策 0022 第 25 點的草案待審）。
四軸從此互相獨立：媒體規格與內容手法不再混在同一軸、近義值不再分裂統計。

軸的選法：四個軸互相獨立，各自回答一個不同的問題——
- angle（切角）：為什麼要買
- tone（語氣）：用什麼口氣講
- format（形式）：長什麼樣子
- selling_point（賣點）：主打哪個好處
"""

AXES = {
    "angle": {
        "label": "切角",
        "question": "這則素材從哪個角度切入？",
        "values": {
            "pain": "點出痛點",
            "benefit": "直說好處",
            "proof": "拿證據說話",
            "testimonial": "真人見證",
            "scene": "描繪使用情境",
            "comparison": "對比",
            "identity": "訴諸身份認同",
            "curiosity": "製造好奇",
        },
    },
    "tone": {
        "label": "語氣",
        "question": "這則素材用什麼口氣講？",
        "values": {
            "warm": "親切溫暖",
            "professional": "專業可靠",
            "humorous": "幽默有趣",
            "urgent": "急迫催促",
            "blunt": "直白不修飾",
        },
    },
    "format": {
        "label": "形式",
        "question": "這則素材長什麼樣子？",
        "values": {
            "single_image": "單張圖",
            "carousel": "多圖輪播",
            "short_video": "短影片",
            "text_focus": "文字圖卡",
        },
    },
    "selling_point": {
        "label": "賣點",
        "question": "這則素材主打什麼？",
        "values": {
            "efficacy": "有感有效",
            "quality": "品質好",
            "price": "價格划算",
            "convenience": "方便省事",
            "uniqueness": "別人沒有",
            "safety": "安全無添加",
        },
    },
}

# 拒絕理由。刻意都是「使用者會脫口而出的話」，不是行銷術語——
# 選單看不懂就等於沒有選單（鐵則 12、14）。
REJECT_REASONS = [
    ("too_stiff", "太生硬，不像真人講話"),
    ("off_brand", "不是我們品牌的調性"),
    ("too_ad_like", "太像廣告，人會直接滑掉"),
    ("too_similar", "跟其他張太像"),
    ("discount_too_deep", "折扣或促銷講得太重"),
    ("overclaim", "講得太滿，有風險"),
    ("wrong_product", "產品資訊不對"),
    ("visual_weird", "畫面感覺怪"),
    ("hook_weak", "開頭抓不住人"),
]
REJECT_REASON_LABELS = dict(REJECT_REASONS)

# 法規自動預設挑掉的理由代碼（修憲落地 L2，決策 0034 第 25 條）。刻意不放進 REJECT_REASONS：
# 那是給使用者手動點選的封閉選單，這個代碼專屬「系統掃到內建法規詞庫命中，自動預設挑掉」，
# 不該出現在人工選單裡；`REASON_TO_AXIS.get()` 對未知代碼回 None，所以它天生不會被
# `nextcycle.build_rule_cards()` 拿去累積成風格規則卡——這不是使用者的風格偏好，不該進學習迴路。
AUTO_HOLD_REASON_CODE = "compliance_law_hit"
AUTO_HOLD_REASON_LABEL = "命中法規禁用字詞，系統已先幫你挑掉"

# 拒絕理由 → 主要對應的指紋軸。同一軸被拒到門檻本來就可能產規則卡（票 13），但能不能真的
# 升級成永久禁令另外由 RULE_UPGRADABLE_REASONS 白名單把關（票 T1，使用者 2026-08-06 拍板）。
#
# 四條沒有軸（決策 0030 第二節第 6 點）：too_similar（問題是重複不是切角，反回音室機制
# 已在管）、visual_weird（執行品質問題，format 軸從此不產生規則卡）、overclaim（法規寫法
# 問題，該走 claim／rule 層）、wrong_product（資料錯誤，不是風格偏好）——這四條連「觀察中」
# 都不會出現，_axis_value_stats() 直接跳過。
#
# 另有三條有軸、只觀察、永不升級（票 T1，推翻決策 0030 第二節第 6 點原本「本表為定版」的
# 說法）：too_stiff、too_ad_like、hook_weak——這三條猜的是消費者會怎麼反應，不是使用者
# 自己的品牌或商業政策，全程沒有真實成效數據驗證過，不該被兩次隨手的拒絕就鑄成永久寫進
# prompt 的約束。仍可升級的只剩 off_brand（品牌調性）、discount_too_deep（折扣力度）——
# 這兩條是使用者自己的政策，要改由使用者自己改，見 RULE_UPGRADABLE_REASONS。
REASON_TO_AXIS = {
    "too_stiff": "tone",
    "off_brand": "tone",
    "too_ad_like": "tone",
    "too_similar": None,
    "discount_too_deep": "selling_point",
    "overclaim": None,
    "wrong_product": None,
    "visual_weird": None,
    "hook_weak": "angle",
}

# 能不能升級成永久禁令的白名單（票 T1）。刻意用白名單不用黑名單：日後新增拒絕理由，預設
# 不能鑄成永久禁令，除非明確把它加進這裡——不讓「忘記排除」意外解鎖新的永久約束。
RULE_UPGRADABLE_REASONS = {"off_brand", "discount_too_deep"}


def is_valid(fingerprint: dict) -> bool:
    """四個軸都在、值都在枚舉內才算有效。壞掉的指紋寧可不存，也不要存進去汙染統計。"""
    if not isinstance(fingerprint, dict):
        return False
    for axis, spec in AXES.items():
        value = fingerprint.get(axis)
        if value not in spec["values"]:
            return False
    return True


def normalize(fingerprint) -> dict:
    """把模型給的指紋收斂成合法值；認不得的軸值丟掉（不猜、不硬塞預設值）。"""
    if not isinstance(fingerprint, dict):
        return {}
    return {axis: fingerprint.get(axis) for axis, spec in AXES.items()
            if fingerprint.get(axis) in spec["values"]}


def describe(fingerprint: dict) -> str:
    """指紋 → 一行人話，例如「直說好處・親切溫暖・單張圖・品質好」。"""
    parts = [AXES[axis]["values"][value]
             for axis, value in (fingerprint or {}).items()
             if axis in AXES and value in AXES[axis]["values"]]
    return "・".join(parts)


def axis_value_label(axis: str, value: str) -> str:
    return AXES.get(axis, {}).get("values", {}).get(value, value)


def distance(a: dict, b: dict) -> float:
    """兩則素材的差異度：四個軸裡有幾個不一樣（0＝一模一樣，1＝完全不同）。

    只比雙方都有值的軸——缺值不算「不同」，否則指紋殘缺的素材會被誤判成很有創意。
    """
    axes = [axis for axis in AXES if (a or {}).get(axis) and (b or {}).get(axis)]
    if not axes:
        return 1.0  # 沒得比就當作不同，不因為缺資料而誤報「太像」
    different = sum(1 for axis in axes if a[axis] != b[axis])
    return round(different / len(axes), 3)


# 修憲落地 G3（決策 0035 第9點）：四軸 distance 只有離散值 0／0.25／0.5／0.75／1.0；
# 舊門檻 0.25 搭配「novelty < 門檻」等於要求四軸「全部」相同（novelty=0）才算重複，
# 前十幾期幾乎不可能觸發——而它是防 AI 讀自己的產出越轉越像自己的唯一防線。
# 放寬到 0.5：新素材跟某則舊素材四軸裡有 3 軸以上相同（novelty 0 或 0.25）就算在原地打轉，
# 不必要求完全一模一樣。
ECHO_THRESHOLD = 0.5  # 與歷史素材的最大差異度低於此值，視為在原地打轉


def novelty(candidate: dict, history: list, weights: list = None) -> float:
    """一則素材相對於歷史素材的新鮮度＝與最相近那一則的差異度。

    取「最相近」而不是平均：只要跟其中任何一則幾乎一樣，它就是舊東西，
    再多不相干的歷史素材也稀釋不掉這件事。

    `weights`（票 02-occasion-weighted-recommendations，ADR 0011 第五節）：跟 `history`
    等長、逐筆對應的情境權重，省略時等同全部權重 1.0（現行的無加權比較）。距離除以權重——
    權重低（跟這次檔期不同場合）的歷史素材要離得更近才會被算進「還在原地打轉」，權重高
    （同場合）的則按實際距離算，不是直接排除掉權重低的那些。
    """
    if not history:
        return 1.0
    if weights is None:
        return min(distance(candidate, old) for old in history)
    return min(distance(candidate, old) / w for old, w in zip(history, weights))


def echo_chamber_ratio(candidates: list, history: list, weights: list = None) -> float:
    """這批素材裡有多少比例是在重複過去。用來偵測 AI 讀自己的產出越轉越像自己。

    `weights`：見 `novelty()`，逐筆對應 `history` 的情境權重，省略時無加權。
    """
    if not candidates:
        return 0.0
    stale = sum(1 for c in candidates if novelty(c, history, weights) < ECHO_THRESHOLD)
    return round(stale / len(candidates), 3)


# selling_point 的 efficacy／safety 是食安法 §28 最常見的入罪與易生誤解用語（修憲落地 L4，
# 決策 0034 第 9 點）。這兩個值本身保留（拿掉會讓模型無標可貼、統計更糟），但寫手看到的
# 枚舉清單要附上法規註記提醒——`overclaim → None`（見上）已經讓這兩個值的被拒次數永遠是 0，
# 不能讓字詞比對之外的地方也對它們免疫。
AXIS_VALUE_LAW_NOTES = {
    ("selling_point", "efficacy"): "食安法§28 入罪重點，別寫成醫療效能／保健功效字樣",
    ("selling_point", "safety"): "食安法§28 易生誤解，別暗示醫療用途或誇大安全宣稱",
}


def prompt_vocabulary() -> str:
    """給模型看的枚舉清單——模型只能從這些值裡挑，不能自己發明標籤。"""
    lines = []
    for axis, spec in AXES.items():
        options = []
        for k, v in spec["values"].items():
            note = AXIS_VALUE_LAW_NOTES.get((axis, k))
            options.append(f"{k}（{v}，{note}）" if note else f"{k}（{v}）")
        lines.append(f"- {axis}：{'、'.join(options)}")
    return "\n".join(lines)
