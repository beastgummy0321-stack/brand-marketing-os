"""Conservative, deterministic checks for fulfilment promises, not a semantic fact checker.

Only confirmed source statements can support a promise. Coordinate labels, prompts,
pack summaries and previous model output are never evidence. Re-check on adoption so
old output and subsequently withdrawn sources use the same policy as new output.
"""
import re

from app.brand_intelligence import repository as bi_repo

MESSAGE = ("這版含尚未確認來源或履約方式的優惠／背書。"
           "請先在品牌智庫確認完整條件與入口，或重新生成無優惠版本。")
# Bounded coverage: these are fulfilment/endorsement families, not all possible factual claims.
RISK = re.compile(
    r"試飲|試喝|試吃|試用|體驗券|體驗價|免費體驗|折扣|優惠|折價|折抵|折價券|促銷|"
    r"免運|贈品|加贈|買[一二三四五六七八九十\d]+送|[一二三四五六七八九十\d.]+折|"
    r"退款保證|保證退款|無效退款|專家推薦|專家背書|醫師推薦|顧客好評|顧客評論|"
    r"熱銷[\d萬千百]+|銷售[\d萬千百]+|free trial|free sample|discount|free shipping|testimonial",
    re.IGNORECASE,
)
_META = {"validation", "warnings", "coordinates", "fingerprint", "round",
         "visual_tone", "visual_concept"}


def sources(conn, brand_id: str, product_id: str | None) -> list[dict]:
    rows = bi_repo.list_brand_facts(conn, brand_id, status="confirmed")
    knowledge_id = bi_repo.knowledge_product_id(conn, brand_id, product_id) if product_id else None
    if knowledge_id:
        rows += bi_repo.list_product_facts(conn, brand_id, knowledge_id, status="confirmed")
    result = [{"id": r["id"], "text": str(r.get("value") or "")} for r in rows]
    claims = (bi_repo.list_claims_for_product(conn, brand_id, knowledge_id) if knowledge_id
              else [r for r in bi_repo.list_claims_for_brand(conn, brand_id)
                    if not r.get("product_id")])
    result += [{"id": r["id"], "text": r["claim_text"]} for r in claims
               if r["claim_type"] == "approved"]
    return result


def policy(rows: list[dict]) -> str:
    relevant = [r for r in rows if RISK.search(r["text"])]
    lines = ["## 優惠與背書來源（優先於座標、情境與自由指示）",
             "優惠與證明座標只是創意分類，不是品牌已提供的事實。",
             "未列於下方的試飲、折扣、贈品、保證、評論與背書，一律不得寫成可兌現承諾。",
             "沒有來源就寫無優惠、無背書的完整版本，不寫待確認優惠，也不虛構入口。",
             "有來源時僅可逐字引用完整已確認字句，不擴張適用對象、數量、期間或優惠條件；履約入口必須已存在。",
             "『模擬測試』不能解除此限制。",
             *[f"- [{r['id']}] {r['text']}" for r in relevant]]
    if not relevant:
        lines.append("（沒有已確認的優惠或背書來源）")
    return "\n".join(lines)


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            if key not in _META:
                yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def unsupported(value, rows: list[dict]) -> list[str]:
    """Remove exact confirmed sentences before detecting remaining promises.

    A bare category never authorizes its paraphrases. Full confirmed statements are
    required, and offer sources also need a URL or explicit fulfilment location.
    Conservative false positives are preferable to silently enlarging a promise.
    """
    approved = []
    for row in rows:
        text = row["text"].strip()
        if not RISK.search(text):
            continue
        # A title like '試飲' is not a full statement or a fulfilment contract.
        if len(text) < 10:
            continue
        if re.search(r"待確認|未確認|尚未|不提供|禁止|不能|不可", text):
            continue
        offer = re.search(
            r"試飲|試喝|試吃|試用|優惠|折扣|贈|免運|退款|trial|sample|discount", text, re.I,
        )
        if offer and not re.search(r"https?://|門市|櫃台|結帳|客服|現場", text):
            continue
        approved.append(text)
    missing = []
    for text in _strings(value):
        for statement in sorted(approved, key=len, reverse=True):
            text = text.replace(statement, "")
        missing.extend(m.group(0) for m in RISK.finditer(text))
    return list(dict.fromkeys(missing))
