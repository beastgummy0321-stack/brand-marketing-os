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
F48 Contract G (one claims guard; supersedes F46 Contract O for the discount family only,
decision 7): a word of the discount family (`_OFFER_FAMILIES` `discount`, which now also holds
優惠／原價／特價) is backed when any of the rows is a `discount` offer row; every other family keeps
the exact-term rule above (滿額 too). Registered product and sell-way names
(`registered_names`) are stripped before any scan, so 「超能特惠組」 is a name, not a promise.
Approved product claims are taken as the user typed them (the length / negation / fulfilment
filters are for brand facts only). `forbidden_terms` is the one list of 「不能講」 -- forbidden
claims and `forbidden_word` rules, scoped to the sell-way -- that the workbench warns on and the
slot blocks on (`forbidden_hits`). A 食安法 hit is a reminder (`statutory`), never forbidden.
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
    # F48 decision 7: 優惠／原價／特價 belong to the discount family (a registered discount
    # sentence backs them); the family is backed by any `discount` offer row.
    (re.compile(rf"折扣|折價|折抵|[一二三四五六七八九十\d.]+折|第二件半價|半價|特惠|特價|下殺|"
                rf"早鳥價|現折|滿{_N}折|回饋|點數|優惠|原價|discount", re.IGNORECASE), "discount"),
    (re.compile(rf"贈品|加贈|買[一二三四五六七八九十\d]+送|加購價|組合價|滿{_N}送|再送|加送|"
                rf"送{_N}"), "bundle"),
    (re.compile(r"試用|試吃|試飲|試喝"), "trial_sample"),
    (re.compile(r"退款保證|保證退款"), "guarantee"),
    (re.compile(r"限時"), "limited_time"),
    (re.compile(r"滿額"), "*"),
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
    # F48 Contract G: an approved claim of the product is a statement the user typed and
    # approved; `as_typed` exempts it from the brand-fact filters in `unsupported`.
    result += [{"id": r["id"], "text": r["claim_text"], "proof": False,
                **({"as_typed": True} if r.get("product_id") else {})} for r in claims
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


def _approved(rows: list[dict]) -> list[str]:
    """The statements `unsupported` removes before scanning. An approved product claim
    (`as_typed`) enters as the user typed it; a brand fact needs a full statement (≥ 10 chars,
    not a negation) and an offer fact also its fulfilment place."""
    approved = []
    for row in rows:
        text = row["text"].strip()
        if not text:
            continue
        if row.get("as_typed"):
            approved.append(text)
            continue
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
    return approved


def _strip(text: str, statements) -> str:
    for statement in sorted(statements, key=len, reverse=True):
        if statement:
            text = text.replace(statement, "")
    return text


def unsupported(value, rows: list[dict], *, names=()) -> list[str]:
    """Remove registered names (`names`, F48) and exact confirmed sentences before detecting
    remaining promises.

    A bare category never authorizes its paraphrases. Full confirmed statements are
    required, and offer sources also need a URL or explicit fulfilment location.
    Conservative false positives are preferable to silently enlarging a promise.
    Exception (F42, narrowed by F46 Contract O, widened for one family by F48 decision 7): an
    offer word (`_OFFER_FAMILIES`) is not reported when that exact term occurs in the text of
    one of the rows' offer rows (the structured offers available for the product and the ad's
    offer, see `sources`); a discount-family word also when one of them is a `discount` row.
    """
    offer_rows = [row for row in rows if row.get("offer_key")]
    offer_texts = [_squash(row["text"]) for row in offer_rows]
    has_discount = any(row["offer_key"] == "discount" for row in offer_rows)
    approved = _approved(rows)
    missing = []
    for text in _strings(value):
        text = _strip(_strip(text, names), approved)
        missing.extend(m.group(0) for m in RISK.finditer(text)
                       if not _offer_backed(m.group(0), offer_texts, has_discount))
    return list(dict.fromkeys(missing))


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _offer_backed(term: str, offer_texts: list[str], has_discount: bool = False) -> bool:
    """True when `term` is an offer word and that exact term is written in one of the
    available offer sentences (`offer_texts`, whitespace removed); a discount-family word
    (F48 decision 7) also when a `discount` offer row is available (`has_discount`)."""
    families = [family for pattern, family in _OFFER_FAMILIES if pattern.fullmatch(term)]
    if not families:
        return False
    if has_discount and "discount" in families:
        return True
    needle = _squash(term).lower()
    return any(needle in text.lower() for text in offer_texts)


# -- F48 Contract G: one list of 「不能講」 and the registered names ------------------------------


def forbidden_terms(conn, brand_id: str, product_id: str | None) -> list[str]:
    """Every 「不能講」 entry for copy of this sell-way, whitespace squashed, each once: the
    forbidden claims and `forbidden_word` rules of the sell-way's knowledge products
    (`bi_repo.knowledge_product_ids`) plus the brand-level ones (no product); without a
    sell-way, the brand-level ones only. Another product's entries never apply. A 食安法 hit is
    never one of these (F34: reminder only)."""
    knowledge_ids = bi_repo.knowledge_product_ids(conn, brand_id, product_id) if product_id else []
    if knowledge_ids:
        claim_rows = [r for k in knowledge_ids
                      for r in bi_repo.list_claims_for_product(conn, brand_id, k)]
        rule_rows = [r for k in knowledge_ids
                     for r in bi_repo.list_rules_for_product(conn, brand_id, k)]
    else:
        claim_rows = [r for r in bi_repo.list_claims_for_brand(conn, brand_id)
                      if not r.get("product_id")]
        rule_rows = [r for r in bi_repo.list_rules_for_brand(conn, brand_id)
                     if not r.get("product_id")]
    texts = [r["claim_text"] for r in claim_rows if r["claim_type"] == "forbidden"]
    texts += [r["content"] for r in rule_rows if r["rule_type"] == "forbidden_word"]
    return list(dict.fromkeys(t for t in (_squash(str(x or "")) for x in texts) if t))


def registered_names(conn, brand_id: str) -> list[str]:
    """The active product and sell-way names of the brand (both are `product` rows), longest
    first, so a name holding an offer word (「超能特惠組」) is stripped before any scan. A sell-way
    under a product is stored 「〈商品〉 · 〈賣法〉」; both that and its sell-way part count."""
    rows = bi_repo.list_products(conn, brand_id)
    by_id = {r["id"]: r for r in rows}
    names: set[str] = set()
    for row in rows:
        if row.get("status") != "active":
            continue
        name = str(row.get("name") or "").strip()
        names.add(name)
        parent = by_id.get(row.get("parent_id"))
        prefix = f"{parent['name']} · " if parent else None
        if prefix and name.startswith(prefix):
            names.add(name[len(prefix):].strip())
    return sorted((n for n in names if n), key=lambda n: (-len(n), n))


def forbidden_hits(value, terms: list[str], *, names=()) -> list[str]:
    """The entries of `terms` (squashed) written in any string of `value` once the registered
    `names` are removed, compared whitespace-free and case-blind; in `terms` order."""
    texts = [_squash(_strip(text, names)).lower() for text in _strings(value)]
    return [term for term in terms if any(term.lower() in text for text in texts)]


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
            offer_key: str | None = None, *, names=(), forbidden=()) -> dict | None:
    """The advisory on a version. With `offer_key` (F46 Contract O) a copy that leaves out the
    ad's registered offer sentence is named in the same message; without it, unchanged.
    F48 Contract G: `names` (`registered_names`) are stripped like in `unsupported`, and the
    entries of `forbidden` (`forbidden_terms`) the copy writes are named first -- the same list
    the slot blocks on."""
    banned = forbidden_hits(value, list(forbidden), names=names)
    terms = unsupported(value, rows, names=names)
    absent = missing_offer(value, rows, offer_key)
    if not banned and not terms and not absent:
        return None
    parts = []
    if banned:
        parts.append(f"「{'、'.join(banned)}」是你標了不能講的話。")
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
