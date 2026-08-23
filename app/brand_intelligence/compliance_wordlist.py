# -*- coding: utf-8 -*-
"""app/brand_intelligence/compliance_wordlist.py — 內建法定紅線詞庫（修憲落地 L1，決策
0034 第 4 條）＋文字比對純函式。

`compliance.py`（`app/ads/`）的比對來源原本 100% 來自使用者自己登錄的 claim／rule：
新品牌一開始什麼都沒登錄，掃描就回空陣列、畫面顯示「沒有命中」——**綠燈，但根本沒
檢查**。本檔補上「不用使用者自己設定也看得到」的最低限度來源，涵蓋台灣食品法規最
常見、罰則最重的兩塊：

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

## 為什麼搬來 app.brand_intelligence（原本在 app/ads/）

票 03-claim-wordlist-todo（決議 2026-08-23）要讓「存宣稱」「宣稱列表」（都在
`app.brand_web`）也能對這份詞庫做同一套字詞比對，不開第二套比對邏輯。但 A1 三層地界
（`app/tests/test_architecture_boundaries.py` `ImportBoundaryScanTest`／`LayerDirectionTest`）
禁止 `app.brand_web` import `app.ads`（分支專屬層）——`app.brand_intelligence`（品牌永久層）
排在兩邊都夠得到的位置（`app.ads`／`app.brand_web` 都可以往前依賴它），所以資料＋比對
純函式一起搬來這裡；`app/ads/compliance.py` 的 `_sources()`／`scan_cycle()` 等仍是唯一
組來源清單、跑整批素材掃描、寫 Finding 的地方，那段業務邏輯留在原處不搬。
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


def scan_text(text: str, sources: list) -> list:
    """一段文字對一組來源做比對，回傳命中的 (source, term) 清單。

    原本定義在 `app/ads/compliance.py`；票 03-claim-wordlist-todo 搬來這裡，讓
    `app.brand_web`（存宣稱／宣稱列表）也能重用同一顆函式，見檔頭「為什麼搬來」。
    `compliance.py` 仍以 `compliance_wordlist.scan_text` 呼叫，不重複定義第二套。
    """
    hits = []
    lowered = (text or "").lower()
    for source in sources:
        for term in source["terms"]:
            if term.lower() in lowered:
                hits.append((source, term))
                break  # 同一條規則命中一次就夠，不重複報同一條
    return hits


def claim_wordlist_hits(claim_text: str) -> list:
    """存宣稱／宣稱列表用：這句宣稱的文字本身有沒有命中內建法定詞庫（決議 2026-08-23，
    `.scratch/e2e-adflow/issues/03-claim-wordlist-todo.md`）——任何類別（可用／高風險／
    禁用）命中都要標紅字警告，不必等它出現在素材文案裡才被發現。純函式，讀取時現算，
    不落欄位、不擋存檔。
    """
    return [{"term": term, "detail": source["detail"], "source_id": source["source_id"]}
            for source, term in scan_text(claim_text, builtin_sources())]
