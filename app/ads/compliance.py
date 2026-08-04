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
"""

import json
import re
from typing import Optional

from app.ads import compliance_wordlist
from app.ads import creative as ads_creative
from app.ads import fingerprint as fp
from app.ads import guardrails
from app.brand_intelligence import repository as bi
from app.core.audit import write_audit
from app.core.db import new_id, now_iso

# 中文與英文常見的引號形式，抽「規則裡被特別標出來的字詞」用。
_QUOTE_PATTERN = re.compile(r"[「『\"'“”]([^「」『』\"'“”]{1,20})[」』\"'“”]")

MIN_TERM_LENGTH = 2  # 一個字的詞誤判率太高（例如「藥」會打到「藥妝」），不列入

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
        if claim.get("claim_type") not in ("forbidden", "high_risk"):
            continue
        terms = extract_terms(claim["claim_text"])
        if not terms:
            if gaps is not None:
                gaps.append({"kind": "宣稱", "detail": claim["claim_text"],
                             "source_id": claim["id"], "source_type": "claim"})
            continue
        forbidden = claim["claim_type"] == "forbidden"
        sources.append({
            "terms": terms,
            "severity": "warn" if forbidden else "info",
            "kind": "不能講的話" if forbidden else "要小心的話",
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


def scan_text(text: str, sources: list) -> list:
    """一段文字對一組來源做比對，回傳命中的 (source, term) 清單。"""
    hits = []
    lowered = (text or "").lower()
    for source in sources:
        for term in source["terms"]:
            if term.lower() in lowered:
                hits.append((source, term))
                break  # 同一條規則命中一次就夠，不重複報同一條
    return hits


def scan_cycle(conn, brand_id: str, cycle_id: str) -> list:
    """掃描本期所有素材，回傳 Finding 清單（與護欄同一種結構，共用 finding 資料表）。"""
    brand_sources = _sources(conn, brand_id)
    product_sources: dict = {}
    findings = []

    for variant in ads_creative.list_variants(conn, brand_id, cycle_id):
        if variant["rejected"] and not variant.get("auto_held"):
            continue  # 使用者手動挑掉、已經被改寫掉的不必再嫌；系統自動預設挑掉的（修憲落地
            # L2）內容還是原本那則，繼續掃才能讓「為什麼」的說明在下次進頁時還在
        sources = list(brand_sources)
        product_id = variant.get("product_id")
        if product_id:
            if product_id not in product_sources:
                product_sources[product_id] = _sources(conn, brand_id, product_id)
            sources = product_sources[product_id]

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
        "SELECT * FROM finding WHERE brand_id = ? AND campaign_cycle_id = ?"
        " AND finding_type = 'compliance' AND resolved = 0 ORDER BY created_at",
        (brand_id, cycle_id),
    ).fetchall()
    grouped: dict = {}
    for row in rows:
        evidence = json.loads(row["evidence_json"] or "{}")
        variant_id = evidence.get("variant_id")
        if variant_id:
            grouped.setdefault(variant_id, []).append(dict(row))
    return grouped


# 這是系統自動判定（掃到法規詞庫命中就翻預設值），不是哪個人的操作，所以稽核 actor 用
# 固定值，不借用「目前設定的操作人」cookie——GET 這個檢視頁本身不該因為操作人還沒設定就
# 進不去（修憲落地 L2 修正）。使用者自己按下勾回時才會用他自己的操作人身份。
AUTO_HOLD_ACTOR = "compliance_auto"


def apply_default_holds(conn, brand_id: str, cycle_id: str, flags: dict, actor: str) -> int:
    """命中內建法定詞庫的素材，預設值從「已採用」翻成「已挑掉」（修憲落地 L2，決策 0034
    第 25 條）。只翻**法規類**（`source_category == "law"`，即 L1 建立的那份內建詞庫）；
    品牌自訂的 claim／rule 命中（含 `high_risk`）維持原樣，只標黃不動預設值。

    `actor` 應傳系統固定值（見 `AUTO_HOLD_ACTOR`），不是操作人 cookie——這是系統判定，
    不是使用者的決定。

    這不是新增關卡：沒有法規命中的素材完全不受影響；命中的素材使用者仍可一鍵勾回
    （`creative.restore`／`creative.restore_all_auto_held`），路還在，只是預設方向反過來。

    只在**這則從未被決定過**（`adoption_decision` 一筆都沒有）時才寫，這樣才是冪等的——
    每次進頁都會重掃，若不分青紅皂白每次都寫，會把使用者剛按過的「勾回」又蓋回去。
    回傳這次新寫入的則數（供頁面判斷是否要重讀 groups）。
    """
    law_variant_ids = []
    seen = set()
    for variant_id, findings in flags.items():
        for finding in findings:
            evidence = json.loads(finding.get("evidence_json") or "{}")
            if evidence.get("source_category") == "law" and variant_id not in seen:
                seen.add(variant_id)
                law_variant_ids.append(variant_id)
                break
    if not law_variant_ids:
        return 0

    decided_ids = {row["target_id"] for row in conn.execute(
        "SELECT DISTINCT target_id FROM adoption_decision WHERE brand_id = ?"
        " AND campaign_cycle_id = ? AND target_type = 'variant'", (brand_id, cycle_id),
    ).fetchall()}
    to_hold = [vid for vid in law_variant_ids if vid not in decided_ids]
    if not to_hold:
        return 0

    variants_by_id = {v["id"]: v for v in ads_creative.list_variants(conn, brand_id, cycle_id)}
    ts = now_iso()
    held = 0
    for variant_id in to_hold:
        variant = variants_by_id.get(variant_id)
        if variant is None:
            continue
        conn.execute(
            "INSERT INTO adoption_decision (id, brand_id, campaign_cycle_id, target_type,"
            " target_id, decision, reason_code, fingerprint_json, decided_by, decided_at)"
            " VALUES (?, ?, ?, 'variant', ?, 'rejected', ?, ?, ?, ?)",
            (new_id("adp"), brand_id, cycle_id, variant_id, fp.AUTO_HOLD_REASON_CODE,
             json.dumps(variant["fingerprint"], ensure_ascii=False), actor, ts),
        )
        write_audit(conn, brand_id=brand_id, entity_type="creative_variant", entity_id=variant_id,
                    action="compliance_auto_hold", actor=actor, before=None,
                    after={"decision": "rejected", "reason_code": fp.AUTO_HOLD_REASON_CODE})
        held += 1
    if held:
        conn.commit()
    return held
