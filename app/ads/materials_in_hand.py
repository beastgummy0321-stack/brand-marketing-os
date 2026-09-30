"""app/ads/materials_in_hand.py — F42-I02: what the brand has in hand for a campaign, the data
behind the strategy tab's 「這期會用：…」 row. Read-only, no LLM; one reader per fact:

- offers = `bi_repo.offer_sources` (the same rule as the planner's `available_offer_keys`,
  judged against the campaign's first product, brand level when it has none) -- each with the
  store-policy sentence that supports it;
- proof = the brand's confirmed proof facts, plus customer review when
  `bi_repo.available_proof_keys` has it from customer voices alone;
- media = `brand.media_capability` (`None` = never asked).

Labels come from the brand's coordinate vocabulary (`ads_repo.coordinate_vocabulary`, the
planner's menu words); a key the brand has no row for falls back to the shared vocabulary.
Private to app/ads: only `routes.py` imports it.
"""

from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import vocab


def _label(labels: dict, dimension: str, key: str) -> str:
    if (dimension, key) in labels:
        return labels[(dimension, key)]
    if dimension == "offer":
        return vocab.OFFER_LABELS.get(key, key)
    return vocab.proof_kind_label(key)


def read(conn, org_id: str, brand_id: str, product_ids: list | None) -> dict:
    """`{"offers": [{"key", "label", "sentence"}], "proof": [{"key", "label", "text"}],
    "media": "photo" | "photo_video" | None}`."""
    labels = {(row["dimension"], row["key"]): row["label"]
              for row in ads_repo.coordinate_vocabulary(conn, org_id, brand_id)}
    product_id = product_ids[0] if product_ids else None

    offers = [
        {"key": source["offer_key"], "label": _label(labels, "offer", source["offer_key"]),
         "sentence": source["sentence"]}
        for source in bi_repo.offer_sources(conn, brand_id, product_id)
    ]

    proof = [
        {"key": fact["fact_key"], "label": _label(labels, "proof", fact["fact_key"]),
         "text": fact["value"]}
        for fact in bi_repo.list_brand_facts(conn, brand_id, status="confirmed")
        if fact["fact_type"] == "proof" and fact.get("fact_key")
    ]
    if ("customer_review" in bi_repo.available_proof_keys(conn, brand_id)
            and not any(item["key"] == "customer_review" for item in proof)):
        voices = bi_repo.list_customer_voices(conn, brand_id, status="active")
        if voices:  # newest first
            proof.append({"key": "customer_review",
                          "label": _label(labels, "proof", "customer_review"),
                          "text": voices[0]["raw_text"]})

    brand = bi_repo.get_brand(conn, brand_id) or {}
    return {"offers": offers, "proof": proof, "media": brand.get("media_capability")}
