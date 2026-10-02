"""Advisory expression checks for fulfilment promises, not a semantic fact checker.

Only confirmed source statements can support a promise. Coordinate labels, prompts,
pack summaries and previous model output are never evidence. Read current sources for
old and new versions alike. These warnings never prevent adoption or pack approval.
One exception (F42 decision 「copy guard」): an offer word whose family is backed by a confirmed,
structured store policy available for the ad's product (`bi_repo.offer_sources`) is not flagged,
because the policy registry already knows its fulfilment place (the store's checkout). F43: the
sell-way's own confirmed list-price offer (「〈name〉優惠價 NT$x（原價 NT$y）」, also from
`offer_sources`) backs its family (`bundle` / `discount`) the same way.
F44 (Contract B): an ad's offer coordinate narrows those offer rows -- `sources(..., offer_key)`
keeps only the offer the ad was planned with (`"none"` = no offer row), so the prompt and the
guard both judge the copy against the one offer it may write.
F46 (Contract O): the family-wide backing above is replaced. A RISK offer word is backed only
when that exact term (whitespace ignored) occurs inside the text of one of the available offer
rows -- already narrowed to the ad's offer -- so 「買一送一」 is not backed by a bundle's price
sentence and 「優惠」 is not backed by a free-shipping sentence. Proof and endorsement words keep
the exact-sentence rule. `missing_offer` names the registered sentences of the ad's offer when
the copy writes none of them (「帶了就要寫」).
"""
import re
from urllib.parse import quote

from app.brand_intelligence import repository as bi_repo
from app.workbench import statutory_tw

# Bounded coverage: these are fulfilment/endorsement families, not all possible factual claims.
# F46 (Contract O) widens the offer words. A bare 「送」 is not one (送禮、送貨、贈送 are ordinary
# words); only 送 with a count, 再送／加送, 買 N 送 and 滿 N 送 promise something.
_N = r"[一二三四五六七八九十百千萬兩\d][一二三四五六七八九十百千萬兩\d,.]*"
RISK = re.compile(
    r"試飲|試喝|試吃|試用|體驗券|體驗價|免費體驗|折扣|優惠|折價|折抵|折價券|促銷|"
    r"免運|贈品|加贈|買[一二三四五六七八九十\d]+送|"
    r"第二件半價|半價|特價|特惠|下殺|限時|原價|早鳥價|加購價|組合價|現折|滿額|"
    rf"滿{_N}送|滿{_N}折|再送|加送|送{_N}|回饋|點數|抽獎|"
    r"[一二三四五六七八九十\d.]+折|"
    r"退款保證|保證退款|無效退款|專家推薦|專家背書|醫師推薦|顧客好評|顧客評論|"
    r"熱銷[\d萬千百]+|銷售[\d萬千百]+|free trial|free sample|discount|free shipping|testimonial",
    re.IGNORECASE,
)
# F42 decision 「copy guard」: RISK offer words -> the `offer` key (`app/core/vocab.py`
# OFFER_LABELS) of the family they promise; `*` = a word any offer may carry. Only these words
# can be backed by an offer row (F46: when the exact term is in its text). Proof and endorsement
# words, and offer words with no key (促銷、體驗券、抽獎, ...), keep the exact-sentence rule.
_OFFER_FAMILIES = [
    (re.compile(r"免運"), "free_shipping"),
    (re.compile(rf"折扣|折價|折抵|[一二三四五六七八九十\d.]+折|第二件半價|半價|特惠|下殺|"
                rf"早鳥價|現折|滿{_N}折|回饋|點數|discount", re.IGNORECASE), "discount"),
    (re.compile(rf"贈品|加贈|買[一二三四五六七八九十\d]+送|加購價|組合價|滿{_N}送|再送|加送|"
                rf"送{_N}"), "bundle"),
    (re.compile(r"試用|試吃|試飲|試喝"), "trial_sample"),
    (re.compile(r"退款保證|保證退款"), "guarantee"),
    (re.compile(r"限時"), "limited_time"),
    (re.compile(r"優惠|特價|原價|滿額"), "*"),
]
_META = {"validation", "warnings", "coordinates", "fingerprint", "round",
         "visual_tone", "visual_concept"}


def sources(conn, brand_id: str, product_id: str | None,
            offer_key: str | None = None) -> list[dict]:
    """Confirmed brand facts, then the confirmed facts and approved claims of every knowledge
    product of the sell-way (F43: a bundle has several, `bi_repo.knowledge_product_ids`), then
    one row per offer sentence of `bi_repo.offer_sources` (store policies, the sell-way's own
    list-price offer).

    F44 Contract B: `offer_key` is the ad's offer coordinate. `None` = every available offer
    row; `"none"` = no offer row; another key = only the offer rows with that `offer_key`.
    Rows without an `offer_key` are never filtered."""
    brand_rows = bi_repo.list_brand_facts(conn, brand_id, status="confirmed")
    knowledge_ids = bi_repo.knowledge_product_ids(conn, brand_id, product_id) if product_id else []
    rows = list(brand_rows)
    for knowledge_id in knowledge_ids:
        rows += bi_repo.list_product_facts(conn, brand_id, knowledge_id, status="confirmed")
    # Store policies (incl. the cooling-off exemption) reach the copy only through their one
    # resolver, `offer_sources` below, so a policy that does not cover this product never shows.
    result = [{"id": r["id"], "text": str(r.get("value") or ""),
               "proof": r.get("fact_type") == "proof"} for r in rows
              if r.get("fact_type") != "policy"]
    if knowledge_ids:
        # Brand-wide claims come back once per knowledge product; keep each claim once.
        by_id: dict[str, dict] = {}
        for knowledge_id in knowledge_ids:
            for r in bi_repo.list_claims_for_product(conn, brand_id, knowledge_id):
                by_id.setdefault(r["id"], r)
        claims = list(by_id.values())
    else:
        claims = [r for r in bi_repo.list_claims_for_brand(conn, brand_id)
                  if not r.get("product_id")]
    result += [{"id": r["id"], "text": r["claim_text"], "proof": False} for r in claims
               if r["claim_type"] == "approved"]
    # F42/F43: the offer families available for this product -- the brand's confirmed policies
    # (threshold policies against its price) and the sell-way's own list-price offer -- each with
    # its registered sentence. A policy and the sell-way (or two policies) may share an offer key,
    # so the id names its source (the policy fact, else the sell-way); one row per sentence.
    policy_ids = {str(r.get("value") or ""): r["id"] for r in brand_rows
                  if r.get("fact_type") == "policy"}
    seen: set[str] = set()
    for o in bi_repo.offer_sources(conn, brand_id, product_id):
        # `offer_sources` never yields `none`, so the `"none"` coordinate keeps no offer row.
        if offer_key is not None and o["offer_key"] != offer_key:
            continue
        if o["sentence"] in seen:
            continue
        seen.add(o["sentence"])
        source_id = policy_ids.get(o["sentence"]) or product_id or brand_id
        result.append({"id": f"offer:{o['offer_key']}:{source_id}", "text": o["sentence"],
                       "proof": False, "offer_key": o["offer_key"]})
    return result


def prompt_sources(rows: list[dict]) -> list[dict]:
    """Registered evidence (confirmed `proof` facts, F38 decision 1) first, then the available
    offers' registered sentences (F42), then the other rows that carry a RISK word; capped at
    20. The copy quotes these, never invents."""
    proof = [r for r in rows if r.get("proof")]
    offers = [r for r in rows if r.get("offer_key")]
    risky = [r for r in rows if not r.get("proof") and not r.get("offer_key")
             and RISK.search(r["text"])]
    return [*proof, *offers, *risky][:20]


_OFFER_NONE_LINE = "這則廣告的優惠座標是無優惠：不寫任何優惠、優惠價或原價（售價可以寫）。"
_OFFER_CARRY_LINE = "這則廣告要帶下面 [offer:…] 這個優惠：每一組文案都把它的原字句寫進標題或內文。"


def policy(rows: list[dict], offer_key: str | None = None) -> str:
    """The prompt block of the sources. `rows` are `sources(..., offer_key)`'s; with an
    `offer_key` (F44 Contract B) one more line says what the ad's offer coordinate asks for:
    carry the offer whose row is listed below, or -- `"none"`, or a key with no row left --
    write no offer at all. Without `offer_key` the text is unchanged."""
    relevant = prompt_sources(rows)
    lines = ["## 優惠、背書與已登記的證據來源（優先於座標、情境與自由指示）",
             "優惠與證明座標只是創意分類，不是品牌已提供的事實。",
             "未列於下方的試飲、折扣、贈品、保證、評論與背書，一律不得寫成可兌現承諾。",
             "沒有來源就寫無優惠、無背書的完整版本，不寫待確認優惠，也不虛構入口。",
             "有來源時僅可逐字引用完整已確認字句，不擴張適用對象、數量、期間或優惠條件；履約入口必須已存在。",
             "『模擬測試』不能解除此限制。"]
    if offer_key is not None:
        carried = any(r.get("offer_key") == offer_key for r in relevant)
        lines.append(_OFFER_CARRY_LINE if carried else _OFFER_NONE_LINE)
    lines += [f"- [{r['id']}] {r['text']}" for r in relevant]
    if any(r.get("offer_key") for r in relevant):
        lines.append("[offer:…] 是品牌已登記、本商品適用的優惠：全店政策（在店家結帳時兌現）"
                     "或這個賣法本身的優惠價與原價，可照原字句寫，不改門檻、價格或內容。")
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
    Exception (F42, narrowed by F46 Contract O): an offer word (`_OFFER_FAMILIES`) is not
    reported when that exact term occurs in the text of one of the rows' offer rows (the
    structured offers available for the product and the ad's offer, see `sources`).
    """
    offer_texts = [_squash(row["text"]) for row in rows if row.get("offer_key")]
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
        missing.extend(m.group(0) for m in RISK.finditer(text)
                       if not _offer_backed(m.group(0), offer_texts))
    return list(dict.fromkeys(missing))


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _offer_backed(term: str, offer_texts: list[str]) -> bool:
    """True when `term` is an offer word and that exact term is written in one of the
    available offer sentences (`offer_texts`, whitespace removed)."""
    if not any(pattern.fullmatch(term) for pattern, _family in _OFFER_FAMILIES):
        return False
    needle = _squash(term).lower()
    return any(needle in text.lower() for text in offer_texts)


def missing_offer(value, rows: list[dict], offer_key: str | None) -> list[str]:
    """F46 Contract O: the registered sentences of the ad's offer (`rows` with `offer_key`)
    when none of them is written in any string of `value` (whitespace removed on both sides);
    `[]` when one is, or when `offer_key` is `None`, `"none"` or a key with no row."""
    if offer_key is None or offer_key == "none":
        return []
    sentences = list(dict.fromkeys(row["text"] for row in rows
                                   if row.get("offer_key") == offer_key))
    if not sentences:
        return []
    texts = [_squash(text) for text in _strings(value)]
    if any(_squash(sentence) in text for sentence in sentences for text in texts):
        return []
    return sentences


def warning(value, rows: list[dict], brand_id: str,
            offer_key: str | None = None) -> dict | None:
    """The advisory on a version. With `offer_key` (F46 Contract O) a copy that leaves out the
    ad's registered offer sentence is named in the same message; without it, unchanged."""
    terms = unsupported(value, rows)
    absent = missing_offer(value, rows, offer_key)
    if not terms and not absent:
        return None
    parts = []
    if terms:
        parts.append(
            f"「{'、'.join(terms)}」可能包含未確認的優惠／試用／背書。"
            "請確認品牌能提供文案描述的內容；確認無誤即可選定，不必先新增智庫資料。"
        )
    if absent:
        quoted = "或".join(f"「{sentence}」" for sentence in absent)
        parts.append(f"這組文案沒有寫這則廣告要帶的優惠：{quoted}。")
    return {
        "message": "".join(parts),
        "href": f"/brands/{quote(brand_id, safe='')}/library?tab=claims",
    }


# -- F34-I02 (Contract S): 食安法 §28 wording reminder, warn-only like `warning` above ----------

STATUTORY_SENTENCE = "食品廣告通常不能這樣講（食安法第 28 條）。"


def regime(conn, brand_id: str) -> str | None:
    """The brand's `regulatory_regime` (`food_tw` or None) — the same read-only
    `bi_repo` dependency `sources` already uses."""
    brand = bi_repo.get_brand(conn, brand_id)
    return brand.get("regulatory_regime") if brand else None


def statutory(value, regime: str | None) -> list[dict]:
    """`statutory_tw.hits` over every string in `value` (same walk as `unsupported`),
    deduplicated by term across strings. `[]` unless `regime == "food_tw"`."""
    found: dict[str, dict] = {}
    for text in _strings(value):
        for hit in statutory_tw.hits(text, regime):
            found.setdefault(hit["term"], hit)
    return list(found.values())


def statutory_warning(hits: list[dict], *, closing: str = "確認無誤仍可選定。") -> dict | None:
    """Contract S shape for the screens: `{"terms": [{"term", "tier_label"}], "sentence",
    "href"}`, or `None` when there is nothing to remind about."""
    if not hits:
        return None
    return {
        "terms": [{"term": h["term"], "tier_label": statutory_tw.TIER_LABELS[h["tier"]]}
                  for h in hits],
        "sentence": STATUTORY_SENTENCE + closing,
        "href": statutory_tw.REGULATION_URL,
    }
