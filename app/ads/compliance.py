# -*- coding: utf-8 -*-
"""app/ads/compliance.py — 素材輸出前的法務掃描（票 7）。

廣告分支第一次真正引用品牌智庫的**限制層**：拿 claim（宣稱）與 rule（限制規則）
去比對這批素材，命中就在那則素材上標黃並寫明命中哪一條。**只標示、不擋路**（決策 0013）。

## 為什麼是程式比對，不是叫 LLM 判斷

限制規則是自然語言（「文案禁止出現『療效』『治療』等字樣」），要完整判斷得靠語意理解。
但這裡刻意只做程式比對，理由有三：

1. 明確字詞的違規佔絕大多數，而且是最貴的那種（禁用字直接違反廣告法規）。
2. 程式比對即時、免費、結果可重現、可被測試釘死；LLM 判斷每次結果可能不同，
   而「這批素材能不能出」不該是每次跑都不一樣的答案。
3. 拿 LLM 檢查 LLM 自己的產出，共用同一套盲點——它剛寫出來的東西，它多半覺得沒問題。

代價是**抓不到語意層面的違規**，所以介面必須誠實說明這道掃描的能力邊界，
不能讓使用者以為綠燈就等於法務過關（鐵則 16 狀態誠實）。

比對來源：
- claim 為 forbidden：整句與其引號關鍵詞都比。
- claim 為 high_risk：同上，但嚴重度較低（提醒要有佐證）。
- rule 為 hard／soft：抽出規則文字裡「引號內的詞」當禁用字——中文規則慣用引號標出
  具體字詞，這個慣例涵蓋大多數可程式化的規則。沒有引號的規則抽不出東西，會被跳過。
- **內建法定紅線詞庫**（`compliance_wordlist.py`，修憲落地 L1／決策 0034 第4條）：
  不依賴使用者登錄任何東西，新品牌也掃得到。與上面三種品牌自訂來源並列，但
  `source_category` 標成 `"law"`（品牌自訂的三種一律標 `"brand"`）——命中法規來源
  代表可能違法（罰鍰／刑責），命中品牌自訂只代表這個品牌自己的偏好，兩者後果不同。
- **產品規格／交易條件掃描**（票 12）：跟上面四種不同形狀——不是字詞比對，是數字＋
  單位的樣式比對（保存期限、庫存數字、倒數斷貨），`source_category` 標成
  `"unbacked_claim"`。細節見本檔 `_UNBACKED_CLAIM_SOURCES` 附近的說明。
"""

import re
from typing import Optional

from app.brand_intelligence import compliance_wordlist
from app.ads import creative as ads_creative
from app.ads import fingerprint as fp
from app.ads import guardrails
from app.brand_intelligence import repository as bi
from app.core.audit import write_audit
from app.core.db import new_id, now_utc, jsonb, DEV_ORG_ID

# 中文與英文常見的引號形式，抽「規則裡被特別標出來的字詞」用。
_QUOTE_PATTERN = re.compile(r"[「『\"'“”]([^「」『』\"'“”]{1,20})[」』\"'“”]")

MIN_TERM_LENGTH = 2  # 一個字的詞誤判率太高（例如「藥」會打到「藥妝」），不列入

# 素材文案命中某條登錄宣稱的人話標籤（`_sources()` 組 claim 來源用）。
CLAIM_KIND_BY_TYPE = {
    "forbidden": "不能講的話",
    "high_risk": "要小心的話",
    "approved": "已標可用但仍命中規則的話",
}

SCAN_LIMITS_NOTE = (
    "這道檢查只抓得到明確的字詞命中，抓不到語氣或語意層面的問題。"
    "沒被標記不等於法務過關，正式投放前請自己再看一眼。"
)


def extract_terms(text: str) -> list:
    """從規則或宣稱文字裡抽出可比對的字詞。

    優先取引號內的詞（規則慣例就是把該禁的字用引號標出來）；沒有引號時，
    整句夠短就整句拿來比，太長則放棄——長句子逐字比對只會製造誤判。
    """
    if not text:
        return []
    quoted = [t.strip() for t in _QUOTE_PATTERN.findall(text)]
    if quoted:
        # 有引號就只認引號內的詞。即使全部都太短而被濾掉也不退回整句——
        # 帶引號的那句是「規則的描述」，拿它整句去比對素材是沒有意義的。
        return [t for t in quoted if len(t) >= MIN_TERM_LENGTH]
    stripped = text.strip()
    if MIN_TERM_LENGTH <= len(stripped) <= 20:
        return [stripped]
    return []


def _sources(conn, brand_id: str, product_id: Optional[str] = None,
             gaps: Optional[list] = None) -> list:
    """要比對的來源清單：(terms, severity, 人話標籤, 出處說明, 來源 id, 來源分類)。

    來源分類（`source_category`）三選一：`"law"`＝內建法定詞庫、`"platform"`＝平台政策
    （本票尚未收錄內容，留給後續票）、`"brand"`＝品牌自訂的 claim／rule。
    （`selling_point_law_finding()` 另外用的 `"law_advisory"` 不算在這裡的三選一之內，
    那是提醒而非命中，見該函式的 docstring。）

    `gaps`（修憲落地 L5，決策 0034 第 12 點）：傳一個 list 進來時，凡是收下了但
    `extract_terms()` 抽不出任何字詞（`MIN_TERM_LENGTH` 太短或無引號超過 20 字）的
    claim／rule，會額外記一筆到這個 list，讓呼叫端能誠實揭露「這幾條規則沒有被本次
    掃描涵蓋」，而不是像原本一樣靜靜跳過、畫面完全不說。
    """
    sources = list(compliance_wordlist.builtin_sources())

    claims = (bi.list_claims_for_product(conn, brand_id, product_id) if product_id
              else bi.list_claims_for_brand(conn, brand_id))
    for claim in claims:
        # approved（可用）不再跳過（票 03-claim-wordlist-todo，決議 2026-08-23）：
        # F3 踩到的洞是「可用」宣稱完全沒被掃過，掛著「可以講」的標籤卻可能整句就是
        # 違規字詞。三類都掃、都只警告（見 CLAIM_KIND_BY_TYPE 的 severity）——不擋、
        # 不自動改類別（`apply_default_holds()` 只認 source_category=="law"，
        # 不看這裡的 severity，brand 分類命中一律不會被自動預設值翻掉）。
        terms = extract_terms(claim["claim_text"])
        if not terms:
            if gaps is not None:
                gaps.append({"kind": "宣稱", "detail": claim["claim_text"],
                             "source_id": claim["id"], "source_type": "claim"})
            continue
        kind = CLAIM_KIND_BY_TYPE[claim["claim_type"]]
        sources.append({
            "terms": terms,
            "severity": "info" if claim["claim_type"] == "high_risk" else "warn",
            "kind": kind,
            "detail": claim["claim_text"],
            "source_id": claim["id"],
            "source_type": "claim",
            "source_category": "brand",
        })

    rules = (bi.list_rules_for_product(conn, brand_id, product_id) if product_id
             else bi.list_rules_for_brand(conn, brand_id))
    for rule in rules:
        terms = extract_terms(rule["content"])
        if not terms:
            if gaps is not None:
                gaps.append({"kind": "規則", "detail": rule["content"],
                             "source_id": rule["id"], "source_type": "rule"})
            continue
        hard = rule.get("severity") == "hard"
        sources.append({
            "terms": terms,
            "severity": "warn" if hard else "info",
            "kind": "必須遵守的規則" if hard else "建議遵守的規則",
            "detail": rule["content"],
            "source_id": rule["id"],
            "source_type": "rule",
            "source_category": "brand",
        })
    return sources


def coverage_gaps(conn, brand_id: str) -> list:
    """這個品牌裡，被登錄了但字詞比對抽不出可比對字詞、沒有被掃描涵蓋的 claim／rule
    （修憲落地 L5，決策 0034 第 12 點：`MIN_TERM_LENGTH` 讓單字規則永遠不觸發、
    無引號且超過 20 字的規則直接回空，這兩條路徑原本收下規則、靜默忽略、畫面不說）。

    傳品牌層級（不分產品）即可涵蓋全部——`list_claims_for_brand`／`list_rules_for_brand`
    本身就回傳品牌整體與各產品專屬的全部，字詞抽取本身也與 product_id 無關。
    去重用 `source_id`，避免同一條規則因為別的呼叫路徑重複列出。
    """
    gaps: list = []
    _sources(conn, brand_id, gaps=gaps)
    seen = set()
    deduped = []
    for gap in gaps:
        if gap["source_id"] not in seen:
            seen.add(gap["source_id"])
            deduped.append(gap)
    return deduped


# 純比對邏輯搬去 compliance_wordlist.py 了（票 03-claim-wordlist-todo，見該檔檔頭
# 「為什麼搬來 app.brand_intelligence」）——app.brand_web 存宣稱／宣稱列表也要重用
# 同一顆函式，但 A1 三層地界不准它 import app.ads。這裡保留原名字當作這個模組的公開
# 介面，呼叫的地方（下面 scan_cycle()）完全不用改，不重複定義第二套比對。
scan_text = compliance_wordlist.scan_text


# --- 產品規格／交易條件掃描（票 12：generated copy 編造規格或交易條件）---------------
#
# 範圍是使用者拍板收窄過的（見 .scratch/adloop/tickets/12-hold-spec-and-transaction-claims.md）：
# 只抓兩類——產品規格（保存期限這類）與交易條件（庫存數字、倒數斷貨、折扣深度）。品牌故事與
# 社會認同（「60年老字號」「3,000 個送禮人已選」）刻意不抓：使用者自己人工複審，
# 抓太寬只會把文案改得死板沒人想看，這個代價使用者已經衡量過，不要「順手」擴大範圍。
#
# ponytail：這是逐字比對數字＋單位的樣式掃描，不是語意理解。抓不到換句話說的講法
# （「本產品耐放，可以放到明年」）、抓不到把數字寫成國字（「三年」）、抓不到單位
# 拆兩句寫。上限就是「字面上長得像規格／交易條件的數字」，抓不到的留給人工複審——
# 假陰性可接受（使用者本來就要自己看一遍），假陽性不可接受（那才是把文案逼成無聊的
# 元凶），所以每個樣式都刻意配了關鍵字前綴，不是看到數字就抓。真的要做到語意層級的
# 判斷，上限在這裡——升級路徑另開票評估（比照 D2 生成 prompt 接地，不在本票範圍內）。
#
# 折扣深度（_DISCOUNT_DEPTH_PATTERN）是這條上限唯一的例外：「N折」的「折」字本身在中文
# 廣告文案裡幾乎不做別的用途（不像「年」「個」這種單位到處都會出現），所以「折」分支
# 不強制要求前面有促銷關鍵字，光「3折起」四個字就足以判斷是折扣深度，不算「看到數字就抓」
# ——單位本身已經夠專屬。但百分比（30%）沒有這個專屬性，市占率、轉換率、回購率都用
# 百分比，所以百分比分支維持原本的規矩：前面一定要有促銷關鍵字（限時／下殺／殺到／
# 優惠／特價／全館／第N件）才算數，裸百分比一律放行。
_SHELF_LIFE_PATTERN = re.compile(
    r"(?:保存(?:期限)?|保固(?:期)?|效期|賞味期限|有效期限?)\D{0,4}"
    r"(?P<qty>\d+\s*(?:年|個月|月|天|日))"
)

_STOCK_COUNT_PATTERN = re.compile(
    r"(?:現貨|庫存|僅剩|限量|最後)\D{0,6}"
    r"(?P<qty>\d+\s*(?:盒|件|份|組|箱|瓶|支|個|人份))"
)

_DEADLINE_PATTERN = re.compile(
    r"倒數\D{0,8}(?P<qty>\d+\s*(?:天|小時|日))\D{0,6}"
    r"(?:無貨|缺貨|下架|截止|售完|結束)"
)

# 交易條件的第四種樣式：折扣深度（票 12 使用者拍板只加這一種，裸價不加——見下方註解）。
# 「N折」不需要促銷關鍵字前綴（見上方 ponytail 註解），數字後面接「折」本身就夠專屬；
# 「N%」需要，因為裸百分比在文案裡太常見（轉換率、回購率、市占率都用百分比），沒有
# 促銷關鍵字就不知道是不是折扣。用一個 `(?(1)...)` 條件式把兩種規則放進同一個
# re.compile：group(1) 是促銷關鍵字（可省略），「折」分支永遠可以比對，「%」分支只在
# group(1) 真的抓到東西時才開放，抓不到就用 `(?!)` 讓這個分支永遠失敗。
# 兩位數「折」是台灣慣用簡寫（「66折」＝6.6折），照抄字面比對，不做小數換算。
#
# 刻意不加裸價格樣式（「只要590元」「原價1200元」）：那是使用者拍板刻意不加的部分——
# 折扣深度是 spec 點名的「人為製造急迫感」案例，賣家講了折扣就等於對顧客承諾這個折數；
# 裸價格幾乎每則廣告都會出現，若也要求佐證，文案會被逼得無聊到沒人想看，這正是 spec
# 講的「不惜一切代價都要避免」的成本，不能為了「順手」多抓一種而讓文案變死板。
_DISCOUNT_DEPTH_PATTERN = re.compile(
    r"(限時|下殺|殺到|優惠|特價|全館|第\d+件)?\D{0,4}"
    r"(?P<qty>\d{1,3}(?:折(?:起)?|(?(1)[%％]|(?!))))"
)

# 新的來源分類——刻意不是 "law"：`apply_default_holds()` 一看到 `"law"` 就會自動翻成
# 已挑掉，那個分類專屬 L1 內建法定詞庫的字詞命中，誤標會讓一個提醒被授權成自動關卡
# （見 compliance.py 檔頭與 selling_point_law_finding() docstring 的同一個警告）。
UNBACKED_CLAIM_CATEGORY = "unbacked_claim"

# (規則名稱, 人話分類, 樣式, 講給使用者聽的一句話)。分類名稱只用來組訊息，不落庫比對。
_UNBACKED_CLAIM_SOURCES = [
    ("shelf_life", "產品規格", _SHELF_LIFE_PATTERN,
     "標錯保存期限不只是文案問題，食品標示不實本身就違法，也可能讓顧客誤判食品有沒有過期。"),
    ("stock_count", "交易條件", _STOCK_COUNT_PATTERN,
     "如果現場其實沒有這個數字，等於對顧客做了不實的庫存宣稱，屬於引人錯誤。"),
    ("deadline", "交易條件", _DEADLINE_PATTERN,
     "編造的缺貨倒數會催促顧客搶購，但賣家不一定真的能兌現這個期限。"),
    ("discount_depth", "交易條件", _DISCOUNT_DEPTH_PATTERN,
     "寫出具體折數就是對顧客承諾這個折扣，如果品牌資料庫裡沒登記這個檔期真的有打這個折，"
     "等於用假的折扣催促顧客下單，屬於引人錯誤。"),
]


def _backing_texts(conn, brand_id: str, product_id: Optional[str] = None) -> list:
    """D3：能佐證一句宣稱的文字——已核准的宣稱（`claim.claim_type == "approved"`）
    ＋已確認的品牌／產品事實（`brand_fact`／`product_fact` 的 `status == "confirmed"`）。
    有品牌做過功課、登記了佐證，這句話就不該被當成無中生有。

    claim 的品牌／產品範圍查法比照 `_sources()`：product_id 給了就用
    `list_claims_for_product`（品牌整體＋這個產品專屬），沒給就用 `list_claims_for_brand`
    （否則會把「品牌整體」以外、其他產品專屬的宣稱也算進來，佐證範圍算錯）。
    """
    claims = (bi.list_claims_for_product(conn, brand_id, product_id) if product_id
              else bi.list_claims_for_brand(conn, brand_id))
    texts = [c["claim_text"] for c in claims if c.get("claim_type") == "approved"]
    texts += [f["value"] for f in bi.list_brand_facts(conn, brand_id, status="confirmed")]
    if product_id:
        texts += [f["value"] for f in
                  bi.list_product_facts(conn, brand_id, product_id, status="confirmed")]
    return texts


def _is_backed(qty: str, backing_texts: list) -> bool:
    """數字＋單位（例如「3年」）只要原封不動出現在任何一則佐證文字裡就算有靠——
    跟 `scan_text()` 一樣是字面比對，不判斷語意，佐證文字寫法要跟文案對得上。"""
    needle = re.sub(r"\s+", "", qty)
    return any(needle in re.sub(r"\s+", "", text or "") for text in backing_texts)


def unbacked_claim_findings(variant: dict, backing_texts: list) -> list:
    """一則素材對三種產品規格／交易條件樣式逐一比對，命中且查無佐證才算一則 Finding。"""
    findings = []
    content = variant.get("content") or ""
    for name, category_label, pattern, note in _UNBACKED_CLAIM_SOURCES:
        match = pattern.search(content)
        if not match or _is_backed(match.group("qty"), backing_texts):
            continue
        findings.append(guardrails.Finding(
            finding_type="compliance",
            code="unbacked_claim_hit",
            severity="warn",
            message=(f"這則{variant['type_label']}寫了具體的{category_label}「{match.group(0)}」，"
                     f"但品牌資料庫裡沒有登記任何宣稱或事實可以佐證這個數字。{note}"
                     "系統先幫你保留起來，請自己確認清楚之後再決定要不要用這則文案。"),
            source="rule_scan",
            confidence_penalty=0.0,  # 這是內容問題，不影響成效判讀的可信度
            evidence={"variant_id": variant["id"], "term": match.group(0),
                      "source_type": "unbacked_claim", "source_id": f"unbacked_claim:{name}",
                      "source_category": UNBACKED_CLAIM_CATEGORY},
        ))
    return findings


def scan_cycle(conn, brand_id: str, cycle_id: str) -> list:
    """掃描本期所有素材，回傳 Finding 清單（與護欄同一種結構，共用 finding 資料表）。"""
    brand_sources = _sources(conn, brand_id)
    product_sources: dict = {}
    brand_backing = _backing_texts(conn, brand_id)
    product_backing: dict = {}
    findings = []

    for variant in ads_creative.list_variants(conn, brand_id, cycle_id):
        if variant["rejected"] and not variant.get("auto_held"):
            continue  # 使用者手動挑掉、已經被改寫掉的不必再嫌；系統自動預設挑掉的（修憲落地
            # L2）內容還是原本那則，繼續掃才能讓「為什麼」的說明在下次進頁時還在
        sources = list(brand_sources)
        backing = brand_backing
        product_id = variant.get("product_id")
        if product_id:
            if product_id not in product_sources:
                product_sources[product_id] = _sources(conn, brand_id, product_id)
            sources = product_sources[product_id]
            if product_id not in product_backing:
                product_backing[product_id] = _backing_texts(conn, brand_id, product_id)
            backing = product_backing[product_id]

        for source, term in scan_text(variant["content"], sources):
            findings.append(guardrails.Finding(
                finding_type="compliance",
                code=f"{source['source_type']}_hit",
                severity=source["severity"],
                message=(f"這則{variant['type_label']}出現了「{term}」，"
                         f"命中{source['kind']}：{source['detail']}"),
                source="rule_scan",
                confidence_penalty=0.0,  # 這是內容問題，不影響成效判讀的可信度
                evidence={"variant_id": variant["id"], "term": term,
                          "source_type": source["source_type"],
                          "source_id": source["source_id"],
                          "source_category": source["source_category"]},
            ))
        findings.extend(unbacked_claim_findings(variant, backing))
        law_note = selling_point_law_finding(variant)
        if law_note:
            findings.append(law_note)
    return findings


# selling_point 為 efficacy／safety 的素材一律附一則提醒，不管有沒有命中字詞比對
# （修憲落地 L4，決策 0034 第 9 點）：這兩個賣點是食安法 §28 最常見的入罪與易生誤解用語，
# 而 `overclaim → None`（fingerprint.REASON_TO_AXIS）已經讓它們的被拒次數永遠是 0，
# 字詞比對之外不能再讓系統對這兩個值免疫。
SELLING_POINT_LAW_NOTES = {
    "efficacy": "這則主打「有感有效」。食安法 §28 II 對醫療效能用語罰最重（60 萬起跳，"
                "未取得健康食品許可證宣稱法定保健功效還帶刑責），下筆前再檢查一次有沒有寫成療效字樣。",
    "safety": "這則主打「安全無添加」。這類用語常被誤讀成醫療或保健功效宣稱，"
              "下筆前再檢查一次有沒有暗示療效。",
}


def selling_point_law_finding(variant: dict) -> Optional[guardrails.Finding]:
    """`efficacy`／`safety` 兩個賣點值的法規提醒（見 SELLING_POINT_LAW_NOTES 註解）。
    不比對字詞、只認指紋——選了這個賣點就一律附提醒，不管內容寫得多小心。

    `source_category` 故意標成 `"law_advisory"`，不是 `"law"`：`"law"` 專屬於 L1 內建
    法定詞庫的**字詞命中**，`apply_default_holds()`（L2）看到 `"law"` 就會把預設值翻成
    「已挑掉」。這則提醒不是命中，是「選了這個賣點就一律附上」的提示——內容再乾淨也會出現，
    如果標成 `"law"` 會讓完全沒踩到任何禁用字的素材被系統自動預設打掉，變成把「附提醒」
    做成「預設挑掉」，超出決策 0034 第 9 點的授權範圍（修憲落地 L4 修正）。"""
    value = (variant.get("fingerprint") or {}).get("selling_point")
    note = SELLING_POINT_LAW_NOTES.get(value)
    if not note:
        return None
    return guardrails.Finding(
        finding_type="compliance",
        code="selling_point_law_note",
        severity="info",
        message=note,
        source="rule_scan",
        confidence_penalty=0.0,
        evidence={"variant_id": variant["id"], "source_category": "law_advisory",
                  "selling_point": value},
    )


def variant_findings_map(findings: list) -> dict:
    """Finding 清單 → {variant_id: [finding, ...]}，供素材頁逐則標黃。"""
    grouped: dict = {}
    for finding in findings:
        variant_id = finding.evidence.get("variant_id")
        if variant_id:
            grouped.setdefault(variant_id, []).append(finding)
    return grouped


def load_findings(conn, brand_id: str, cycle_id: str) -> dict:
    """從資料庫讀回本期的法務掃描結果，整理成 {variant_id: [...]}。"""
    rows = conn.execute(
        "SELECT * FROM finding WHERE brand_id = %s AND campaign_cycle_id = %s"
        " AND finding_type = 'compliance' AND resolved = false ORDER BY created_at",
        (brand_id, cycle_id),
    ).fetchall()
    grouped: dict = {}
    for row in rows:
        evidence = row["evidence_json"] or {}
        variant_id = evidence.get("variant_id")
        if variant_id:
            grouped.setdefault(variant_id, []).append(dict(row))
    return grouped


# 這是系統自動判定（掃到法規詞庫命中就翻預設值），不是哪個人的操作，所以稽核 actor 用
# 固定值，不借用「目前設定的操作人」cookie——GET 這個檢視頁本身不該因為操作人還沒設定就
# 進不去（修憲落地 L2 修正）。使用者自己按下勾回時才會用他自己的操作人身份。
AUTO_HOLD_ACTOR = "compliance_auto"


def apply_default_holds(conn, brand_id: str, cycle_id: str, flags: dict, actor: str) -> int:
    """命中內建法定詞庫、或編造了查無佐證的產品規格／交易條件的素材，預設值從「已採用」
    翻成「已挑掉」（修憲落地 L2，決策 0034 第 25 條；票 12 併入 `"unbacked_claim"`）。
    只翻這兩類（`source_category in ("law", "unbacked_claim")`）；品牌自訂的 claim／rule
    命中（含 `high_risk`）維持原樣，只標黃不動預設值。

    `"unbacked_claim"` 併進來的理由跟法規類一樣：兩者都不是「品牌自己的偏好」，而是
    賣家對顧客的具體承諾——沒有佐證的保存期限／庫存數字／倒數斷貨一旦上線就要賣家
    自己兌現，兌現不了就是引人錯誤，性質上跟法規紅線一樣重，該用同一套「預設先擋、
    使用者確認後再勾回」的機制，不是新開一條路（見票 12 spec D1）。

    `actor` 應傳系統固定值（見 `AUTO_HOLD_ACTOR`），不是操作人 cookie——這是系統判定，
    不是使用者的決定。

    這不是新增關卡：沒有法規命中的素材完全不受影響；命中的素材使用者仍可一鍵勾回
    （`creative.restore`／`creative.restore_all_auto_held`），路還在，只是預設方向反過來。

    只在**這則從未被決定過**（`adoption_decision` 一筆都沒有）時才寫，這樣才是冪等的——
    每次進頁都會重掃，若不分青紅皂白每次都寫，會把使用者剛按過的「勾回」又蓋回去。
    回傳這次新寫入的則數（供頁面判斷是否要重讀 groups）。
    """
    holdable_categories = ("law", UNBACKED_CLAIM_CATEGORY)
    hold_variant_ids = []
    seen = set()
    for variant_id, findings in flags.items():
        for finding in findings:
            evidence = finding.get("evidence_json") or {}
            if evidence.get("source_category") in holdable_categories and variant_id not in seen:
                seen.add(variant_id)
                hold_variant_ids.append(variant_id)
                break
    if not hold_variant_ids:
        return 0

    decided_ids = {row["target_id"] for row in conn.execute(
        "SELECT DISTINCT target_id FROM adoption_decision WHERE brand_id = %s"
        " AND campaign_cycle_id = %s AND target_type = 'variant'", (brand_id, cycle_id),
    ).fetchall()}
    to_hold = [vid for vid in hold_variant_ids if vid not in decided_ids]
    if not to_hold:
        return 0

    variants_by_id = {v["id"]: v for v in ads_creative.list_variants(conn, brand_id, cycle_id)}
    ts = now_utc()
    held = 0
    for variant_id in to_hold:
        variant = variants_by_id.get(variant_id)
        if variant is None:
            continue
        conn.execute(
            "INSERT INTO adoption_decision (id, org_id, brand_id, campaign_cycle_id, target_type,"
            " target_id, decision, reason_code, fingerprint_json, decided_by, decided_at)"
            " VALUES (%s, %s, %s, %s, 'variant', %s, 'rejected', %s, %s, %s, %s)",
            (new_id("adp"), DEV_ORG_ID, brand_id, cycle_id, variant_id, fp.AUTO_HOLD_REASON_CODE,
             jsonb(variant["fingerprint"]), actor, ts),
        )
        write_audit(conn, brand_id=brand_id, entity_type="creative_variant", entity_id=variant_id,
                    action="compliance_auto_hold", actor=actor, before=None,
                    after={"decision": "rejected", "reason_code": fp.AUTO_HOLD_REASON_CODE})
        held += 1
    if held:
        conn.commit()
    return held


# --- 生成當下即掃（票 S1-01：scan-on-generate）-----------------------------------------
#
# 上面 scan_cycle() 掃的是「已採用」主題底下的元件（ads_creative.list_variants() 只回
# adopted 主題的元件）；這支掃的是「剛生成、還沒決定採不採用」的主題元件——矩陣頁生成一個
# 主題、側板讀主題內容、工作檯快速生成，三個進入點都要在使用者看到內容的當下就看到標記，
# 不必等採用之後才知道命中了什麼（.scratch/scan-on-generate/tickets/S1-01-scan-on-generate.md）。
#
# 只標示、不動決策：呼叫端不得拿這支的結果去寫 adoption_decision 或落 finding 表
# （那是 apply_default_holds()／replace_findings() 的事，本票刻意不碰，見票面決策 2）。

COMPONENT_TYPE_LABELS = {
    "body": "主要文案", "title": "標題", "description": "說明",
    "card_title": "卡片標題", "card_description": "卡片說明",
    "script": "影片腳本", "hook_pool": "開場白",
}


def scan_components(conn, brand_id: str, components: list, *,
                    product_id: Optional[str] = None) -> dict:
    """一批生成中的主題／快速生成元件逐則掃描，回傳 `{key: [hit, ...]}`——`key` 是元件的
    `id`（有的話），沒有 `id`（快速生成不落地，元件沒有 DB 主鍵）就用它在輸入清單裡的索引
    （int）。只有命中至少一則的元件才會出現在回傳的 dict 裡。

    `_sources()`／`_backing_texts()` 只在整批開頭各查一次，不是逐元件查——同一批元件通常
    屬於同一個品牌／產品，逐元件重查是浪費。

    ponytail：`image_prompt`／`card_image_prompt` 兩種元件型別刻意跳過——那是給圖片生成
    工具看的指令，不是顧客會看到的文案，而且經常整句是英文，字詞比對套上去只會製造噪音。
    上限是「這支只認 COMPONENT_TYPE_LABELS 裡列的型別」，真要涵蓋圖片提示詞另開票評估。
    """
    sources = _sources(conn, brand_id, product_id)
    backing = _backing_texts(conn, brand_id, product_id)
    result: dict = {}
    for index, component in enumerate(components):
        label = COMPONENT_TYPE_LABELS.get(component.get("component_type"))
        if label is None:
            continue  # image_prompt / card_image_prompt：見上方 ponytail 說明
        content = component.get("content") or ""
        key = component["id"] if component.get("id") is not None else index

        hits = []
        for source, term in scan_text(content, sources):
            hits.append({
                "category": source["source_category"],
                "severity": source["severity"],
                "term": term,
                "message": f"這則{label}出現了「{term}」，命中{source['kind']}：{source['detail']}",
            })
        # 借用 unbacked_claim_findings() 既有的規格／交易條件比對邏輯，不重寫第二份——
        # 外面塞一顆假 variant dict 讓它吃得下（它的介面認 variant，不是裸內容＋標籤）。
        fake_variant = {"id": key, "type_label": label, "content": content}
        for finding in unbacked_claim_findings(fake_variant, backing):
            hits.append({
                "category": finding.evidence["source_category"],
                "severity": finding.severity,
                "term": finding.evidence["term"],
                "message": finding.message,
            })

        if hits:
            result[key] = hits
    return result
