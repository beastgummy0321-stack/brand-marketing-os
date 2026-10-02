"""Deterministic source and resource guards for suggestions, not platform configuration."""

import json
import math
import re

from app import workbench
from app.brand_intelligence import repository as brands
from app.llm import pricing

INPUT_CHARS = 12000  # Python len: Unicode code points, complete system + message.
OUTPUT_CHARS = 16384  # Accepted response length, never a generation-token guarantee.
OUTPUT_TOKENS = 4096
TIMEOUT_SECONDS = 120
CODEX_NOTICE = (
    "單次執行、120 秒、回傳最多 16,384 字元；無法保證生成用量硬上限。"
    "API 美元費用為零，仍消耗訂閱額度。"
)
# Official model context windows include every input token, even hidden framing overhead.
# No cache or server tools are requested. count_tokens/UTF-8 length are not hard bounds.
# https://platform.claude.com/docs/en/models/overview (2026-09-18)
CONTEXT_WINDOWS = {
    "claude-haiku-4-5": 200000,
    "claude-sonnet-5": 1000000,
    "claude-opus-5": 1000000,
    "claude-fable-5": 1000000,
}
NEUTRAL = ("了解更多", "查看商品資訊", "探索品牌", "歡迎了解", "立即查看")
FIELDS = ("headline", "body", "description")


def ceiling(provider_name, model):
    if provider_name == "codex_cli" and model == "gpt-5.6-luna":
        return 0.0
    if provider_name != "anthropic" or model not in CONTEXT_WINDOWS:
        raise ValueError("此模型沒有可靠的費用與輸出上界，未送出生成。")
    amount = pricing.calculate_cost(model, CONTEXT_WINDOWS[model], OUTPUT_TOKENS)
    if not math.isfinite(amount) or amount > 0.50:
        raise ValueError("目前模型的保守費用上界超過 US$0.50，未送出，也不自動切換模型。")
    return amount


def source_rows(conn, brand, knowledge_ids, sell_way=None):
    """`sell_way` (F44): the approved claims of the sell-way's own knowledge products are sources
    too, each once -- the copy may cite sell-way-level claims. Brand-wide rows stay bounded by
    `knowledge_ids`; the caller adds the returned ids to the batch's knowledge ids."""
    facts = brands.list_brand_facts(conn, brand, status="confirmed")
    claims = brands.list_claims_for_brand(conn, brand)
    sources = [{"id": r["id"], "text": str(r["value"])} for r in facts if r["id"] in knowledge_ids]
    sources += [
        {"id": r["id"], "text": r["claim_text"]}
        for r in claims
        if r["claim_type"] == "approved" and not r.get("product_id") and r["id"] in knowledge_ids
    ]
    if sell_way:
        seen = {s["id"] for s in sources}
        for knowledge_id in brands.knowledge_product_ids(conn, brand, sell_way):
            for r in brands.list_claims_for_product(conn, brand, knowledge_id):
                if r["claim_type"] == "approved" and r.get("product_id") and r["id"] not in seen:
                    seen.add(r["id"])
                    sources.append({"id": r["id"], "text": r["claim_text"]})
    forbidden = [r["claim_text"] for r in claims if r["claim_type"] == "forbidden"]
    return sources, forbidden


def detail(kind, text, terms=()):
    """F44 Contract C: one refusal. `kind` names the exit that fixes it (`copy` | `file` |
    `campaign`; `wait` = nothing to fix, the original's preview is not made yet); `terms` are the
    offending words quoted in `text`."""
    return {"kind": kind, "text": text, "terms": list(terms)}


def violations(
    conn, org, brand, copy, sources, forbidden, *, generated,
    sell_way=None, offer_key=None, offer_label=None,
):
    """Contract C details (kind `copy`) for one copy. The promise words are judged against the
    sources the copy step used: first the sell-way (every offer it has), then the ad's offer
    coordinate -- a word the sell-way backs but the coordinate does not is a mismatch with the
    plan, not a missing registration. `offer_key=None` (a library placement, an ad without that
    coordinate) skips the second check."""
    unbacked = workbench.validate_claims(conn, org, brand, sell_way, copy)["unsupported_promises"]
    problems = []
    if unbacked:
        problems.append(
            detail(
                "copy",
                f"文案寫了「{'、'.join(unbacked)}」，品牌資料裡沒有登記這個優惠或背書。",
                unbacked,
            )
        )
    if offer_key is not None:
        narrowed = workbench.validate_claims(
            conn, org, brand, sell_way, copy, offer_key=offer_key
        )["unsupported_promises"]
        mismatched = [term for term in narrowed if term not in unbacked]
        if mismatched:
            problems.append(
                detail(
                    "copy",
                    f"這則規劃的是「{offer_label or offer_key}」，"
                    f"文案卻寫了「{'、'.join(mismatched)}」。",
                    mismatched,
                )
            )
    text = "\n".join(copy.values())
    if any(word and word in text for word in forbidden):
        problems.append(detail("copy", "含品牌禁止宣稱，請修訂此安排的文案。"))
    if generated:
        for value in copy.values():
            rest = value
            for sentence in sorted(
                [s["text"] for s in sources] + list(NEUTRAL), key=len, reverse=True
            ):
                if sentence:
                    rest = rest.replace(sentence, "")
            if re.sub(r"[\s，。！？、；：,.!?;:—\-()（）]", "", rest):
                problems.append(
                    detail("copy", "補齊文案含無法逐字追溯的事實，未採用，請補充品牌來源。")
                )
                break
    return problems


def missing_offer(conn, org, brand, copy, *, sell_way=None, offer_key=None, offer_label=None):
    """F46 Contract O (「帶了就要寫」): a Contract C detail (kind `copy`) when the ad is planned
    with a real offer (`offer_key` not None / "none") and `copy` -- the whole copy that will be
    confirmed, never a part of it -- writes none of that offer's registered sentences
    (`validate_claims(...)["missing_offer"]`); else None."""
    if offer_key is None or offer_key == "none":
        return None
    absent = workbench.validate_claims(
        conn, org, brand, sell_way, copy, offer_key=offer_key
    )["missing_offer"]
    if not absent:
        return None
    return detail(
        "copy",
        f"這則規劃的是「{offer_label or offer_key}」，文案沒有寫這個優惠：「{absent[0]}」。",
    )


def statutory_note(conn, org, brand, copy, sell_way=None):
    """F34 Contract S note for 補文案 `notes` (plain strings), or None. Never a `problems`
    entry: the reminder is for the human reading the copy (ruling 2B, warn only)."""
    warning = workbench.validate_claims(conn, org, brand, sell_way, copy)["statutory_warning"]
    if warning is None:
        return None
    return "食安法提醒：" + "、".join(t["term"] for t in warning["terms"]) + warning["sentence"]


def validate_reply(data, placements):
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError("模型回覆格式不完整，未採用。")
    items = data["items"]
    ids = [p["id"] for p in placements]
    if len(items) != len(ids) or any(not isinstance(i, dict) for i in items):
        raise ValueError("模型沒有完整涵蓋本批素材，未採用。")
    returned = [i.get("id") for i in items]
    if (
        any(not isinstance(i, str) for i in returned)
        or len(set(returned)) != len(ids)
        or set(returned) != set(ids)
    ):
        raise ValueError("模型漏列、重複或回傳其他素材，未採用。")
    for item in items:
        copy = item.get("copy_fields")
        if (
            not isinstance(copy, dict)
            or set(copy) - set(FIELDS)
            or any(not isinstance(v, str) or len(v) > 4000 for v in copy.values())
        ):
            raise ValueError("補齊文案格式無效，未採用。")
        if not isinstance(item.get("purpose"), str) or len(item["purpose"]) > 1000:
            raise ValueError("建議用途格式無效，未採用。")
    return {i["id"]: i for i in items}


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
