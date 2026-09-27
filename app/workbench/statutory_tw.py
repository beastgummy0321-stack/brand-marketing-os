"""app/workbench/statutory_tw.py — F34-I02 (Contract S): the 食安法 §28 wording table the shared
`workbench.validate_claims` facade reads, as a hand-maintained literal table like
`app/ads/calendar_tw.py`. Regime `food_tw` only (台灣食品); a brand with no
`regulatory_regime` gets no hits at all.

Sources (lead's read, 2026-09-27; extend when the regulation changes):
- 食品安全衛生管理法 §28 and 食品標示宣傳或廣告詞句涉及不實誇張易生誤解或醫療效能之認定準則
  (衛福部): `REGULATION_URL`. §4 defines wording that 不實、誇張或易生誤解 (incl.
  維持或改變人體器官、組織、生理或外觀之功能 and the 「健康」 product-name rule); §5 defines
  醫療效能 (預防、改善、減輕、診斷或治療疾病; 降低導致疾病有關之體內成分; 中藥材效能).
  附件一 lists 27 「通常得使用之詞句」,
  copied verbatim into `ALLOWED_PHRASES` and stripped before matching.
- 健康食品管理法 §6 (「健康食品」／保健功效 need a permit): `HEALTH_FOOD_ACT_URL`.

The regulation names categories, not words, so `PATTERNS` are curated trigger patterns per
category with the article as `basis`. Substring／regex only, no semantics: a hit is a reminder for
the human reading the copy, never a block (F34 ruling 2B + extra). 附件二 (nutrient-function
phrases, allowed only with the nutrient present and labelled) is not modelled this round.
Private to app/workbench — other modules reach it through `workbench.validate_claims`.
"""

import re

REGULATION_URL = "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=L0040140"
HEALTH_FOOD_ACT_URL = "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=L0040012"

# Short chip labels (the prototype's `.statute .term i`); the chip has no room for the article.
TIER_LABELS = {
    "medical": "醫療效能",
    "function": "改變生理功能",
    "health_food": "未取得許可不得使用",
}

# 認定準則 附件一「通常得使用之詞句」, verbatim (source: REGULATION_URL, 附件一).
ALLOWED_PHRASES: tuple[str, ...] = (
    "幫助牙齒骨骼正常發育", "幫助消化", "幫助維持消化道機能", "改變細菌叢生態", "使排便順暢",
    "調整體質", "調節生理機能", "滋補強身", "增強體力", "精神旺盛", "養顏美容", "幫助入睡",
    "營養補給", "健康維持", "青春美麗", "產前產後或病後之補養", "促進新陳代謝", "清涼解渴",
    "生津止渴", "促進食慾", "開胃", "退火", "降火氣", "使口氣芬芳", "促進唾液分泌", "潤喉",
    "生津解渴",
)

_BASIS_MEDICAL_1 = "認定準則第 5 條第 1 款：預防、改善、減輕、診斷或治療疾病"
_BASIS_MEDICAL_2 = "認定準則第 5 條第 2 款：減輕或降低導致疾病有關之體內成分"
_BASIS_MEDICAL_3 = "認定準則第 5 條第 3 款：中藥材效能"
_BASIS_FUNCTION = "認定準則第 4 條第 1 項第 3 款：維持或改變人體器官、組織、生理或外觀之功能"
_BASIS_HEALTH_FOOD = "健康食品管理法第 6 條；認定準則第 4 條第 2 項（「健康」品名）"

# ponytail: the conditional rule fires only when a bare 改善／預防／減輕／緩解／舒緩 sits within 6
# characters before a symptom or disease word. Six characters is the ceiling of this heuristic —
# the next step up is a tokenizer nobody asked for, and 附件一's 改善-free phrases already pass.
_CONDITIONAL = (
    r"(?:預防|改善|減輕|緩解|舒緩)[^，。！？、\s]{0,6}"
    r"(?:疲勞|失眠|便秘|過敏|發炎|疼痛|痠痛|症狀|疾病|感冒|咳嗽|頭痛|經痛|脹氣|胃痛|血壓|血糖|血脂|"
    r"膽固醇|體脂|肥胖|痘|斑|皺紋)"
)


def _rule(pattern: str, tier: str, basis: str, source: str = REGULATION_URL) -> dict:
    return {"pattern": pattern, "tier": tier, "basis": basis, "source": source}


PATTERNS: list[dict] = [
    _rule(r"治療|療效|根治|痊癒|診斷|止痛|消炎|抗發炎|抗癌|防癌|抗過敏|治失眠|治便秘",
          "medical", _BASIS_MEDICAL_1),
    _rule(_CONDITIONAL, "medical", _BASIS_MEDICAL_1),
    _rule(r"降血壓|降血糖|降血脂|降膽固醇|降尿酸|護肝|保肝|解毒|排毒", "medical", _BASIS_MEDICAL_2),
    _rule(r"補氣|活血|去濕|祛濕|袪寒|驅寒", "medical", _BASIS_MEDICAL_3),
    _rule(r"減肥|瘦身|減重|燃脂|消脂|塑身|豐胸|美白|淡斑|抗老|抗皺|逆齡|生髮|壯陽|增強免疫|提升免疫|"
          r"增強記憶|提升記憶|增高|長高|提升專注", "function", _BASIS_FUNCTION),
    _rule(r"健康食品|保健功效|保健食品|小綠人|國家認證", "health_food", _BASIS_HEALTH_FOOD,
          HEALTH_FOOD_ACT_URL),
]

_COMPILED = [(re.compile(row["pattern"]), row) for row in PATTERNS]
_ALLOWED_LONGEST_FIRST = sorted(ALLOWED_PHRASES, key=len, reverse=True)


def hits(text: str, regime: str | None) -> list[dict]:
    """Matches of `PATTERNS` in `text` after stripping 附件一 phrases, as
    `{"term", "tier", "basis"}`, deduplicated by term, in text order. `[]` unless `regime` is
    `food_tw`."""
    if regime != "food_tw" or not text:
        return []
    for phrase in _ALLOWED_LONGEST_FIRST:
        text = text.replace(phrase, " ")
    found: dict[str, dict] = {}
    matches = []
    for regex, row in _COMPILED:
        for m in regex.finditer(text):
            matches.append((m.start(), m.group(0), row))
    for _, term, row in sorted(matches, key=lambda item: item[0]):
        if term not in found:
            found[term] = {"term": term, "tier": row["tier"], "basis": row["basis"]}
    return list(found.values())
