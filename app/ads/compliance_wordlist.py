# -*- coding: utf-8 -*-
"""app/ads/compliance_wordlist.py — 內建法定紅線詞庫（修憲落地 L1，決策 0034 第 4 條）。

`compliance.py` 的比對來源原本 100% 來自使用者自己登錄的 claim／rule：新品牌一開始
什麼都沒登錄，掃描就回空陣列、畫面顯示「沒有命中」——**綠燈，但根本沒檢查**。
本檔補上「不用使用者自己設定也看得到」的最低限度來源，涵蓋台灣食品法規最常見、
罰則最重的兩塊：

1. **食品安全衛生管理法 §28 II 醫療效能**：標示、宣傳或廣告涉及預防、改善、減輕、
   診斷或治療疾病或特定生理情形，一律不得使用。違者罰鍰新台幣 60 萬～500 萬元。
2. **健康食品管理法 §6／§21 法定保健功效用語**：未取得健康食品許可證（俗稱小綠人）
   卻宣稱下列 13 項法定保健功效，可能涉刑事責任（三年以下有期徒刑，得併科新台幣
   100 萬元以下罰金）。

這份詞庫只是本票（L1）的範圍：內建詞庫本身＋標成「法規」來源。品牌自訂的 claim／rule
仍標成「品牌自訂」來源，兩者並列但意義不同——命中法規來源代表可能違法（罰鍰／刑責），
命中品牌自訂只代表這個品牌自己定的偏好。「平台政策」（例如 Meta 廣告政策）是第三種
來源類別，本票先把 `source_category` 的三選一空間留好，實際內容留給後續票補（決策 0034
第 7 條／`docs/design/20-amendment-implementation-plan.md` L5）。

**複查到期日：2027-02-01**（決策 0034 第 10 條）。到期代表這份詞庫可能已經過時——
例如衛福部已於 2025 年預告將健康食品保健功效項目從 13 項增至 14 項（新增「膝關節保健」，
尚未生效，本檔未收），到期時應重新核對衛福部食品藥物管理署最新公告，更新詞庫並把
到期日往後推。

來源依據（皆為公開法規／公告，2026-08-03 查證）：
- 食品安全衛生管理法 §28（全國法規資料庫）。
- 衛生福利部食品藥物管理署 2019-06-12 訂定「食品及相關產品標示宣傳廣告涉及不實誇張
  易生誤解或醫療效能認定準則」。
- 衛生福利部「健康食品管理法所稱保健功效之項目」公告（13 項版本）。

本檔只放資料，不放比對邏輯——邏輯在 `app/ads/compliance.py`。
"""

REVIEW_DUE_DATE = "2027-02-01"

_MEDICAL_EFFICACY_DETAIL = (
    "食品安全衛生管理法 §28 II：食品標示、宣傳或廣告不得涉及醫療效能"
    "（預防、改善、減輕、診斷或治療疾病或特定生理情形）。違者罰鍰新台幣 60 萬～500 萬元。"
)

_HEALTH_FOOD_DETAIL = (
    "健康食品管理法 §6／§21：「{term}」是法定保健功效，未取得健康食品許可證（小綠人）"
    "不得宣稱，違者可能涉刑事責任（三年以下有期徒刑，得併科新台幣 100 萬元以下罰金）。"
)

# 食安法 §28 II 醫療效能字群。除決策 0034 原文點名的「治療／改善／預防／根治／消除」，
# 併入決策背景段同樣點名的「療效」，以及本庫既有示範資料（app/mock_data.py）沿用的
# 「替代藥物」——不臆測擴充其他同義詞，避免把法規詞庫寫成一份自製清單。
STATUTORY_MEDICAL_EFFICACY_TERMS = ["療效", "治療", "改善", "預防", "根治", "消除", "替代藥物"]

# 健管法 13 項法定保健功效（衛福部公告的 13 項版本；2025 年預告新增「膝關節保健」
# 尚未生效，不收）。
STATUTORY_HEALTH_FOOD_FUNCTIONS = [
    "調節血脂", "胃腸功能改善", "免疫調節", "骨質保健", "牙齒保健", "護肝",
    "抗疲勞", "延緩衰老", "促進鐵吸收", "調節血糖", "不易形成體脂肪",
    "調節血壓", "調整過敏體質",
]


def builtin_sources() -> list:
    """內建法定詞庫來源清單，格式對齊 `compliance._sources()` 的其他來源（可直接併入）。"""
    sources = []
    for term in STATUTORY_MEDICAL_EFFICACY_TERMS:
        sources.append({
            "terms": [term],
            "severity": "warn",
            "kind": "違反食品法規的字詞",
            "detail": _MEDICAL_EFFICACY_DETAIL,
            "source_id": f"builtin_law_medical:{term}",
            "source_type": "builtin_law",
            "source_category": "law",
        })
    for term in STATUTORY_HEALTH_FOOD_FUNCTIONS:
        sources.append({
            "terms": [term],
            "severity": "warn",
            "kind": "健康食品法定保健功效用語",
            "detail": _HEALTH_FOOD_DETAIL.format(term=term),
            "source_id": f"builtin_law_health_food:{term}",
            "source_type": "builtin_law",
            "source_category": "law",
        })
    return sources
