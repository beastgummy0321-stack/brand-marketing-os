# -*- coding: utf-8 -*-
"""真相卡的機械分格與批次答案解析；不碰資料庫。"""

import re


_PRICE_TERMS = ("價格", "售價", "定價", "金額", "價錢", "單價")
_MONEY_PATTERN = re.compile(r"(?:NT\$|TWD|USD|新台幣|元|塊)\s*\d|\d\s*(?:元|塊)", re.IGNORECASE)
_CAN_SAY = {"can_say", "allowed", "可以", "可以講", "可講", "true"}
_CANNOT_SAY = {"cannot_say", "forbidden", "不能", "不能講", "不可講", "false"}


def is_price_item(item: dict) -> bool:
    """價格只在事實列判定，避免把顧客原話裡的「怕太貴」誤當商業數字。"""
    if item.get("kind") not in ("品牌事實", "產品事實"):
        return False
    text = " ".join(str(item.get(key) or "") for key in ("category", "title", "content"))
    return any(term in text for term in _PRICE_TERMS) or bool(_MONEY_PATTERN.search(text))


def bucket_name(item: dict) -> str:
    if item.get("_moved_to_needs_confirmation"):
        return "needs_confirmation"
    if (item.get("kind") == "宣稱" and item.get("outcome") != "pending"
            and item.get("category") == "禁用"):
        return "forbidden"
    if item.get("outcome") == "pending" and (is_price_item(item) or item.get("kind") == "宣稱"):
        return "needs_confirmation"
    return "accepted"


def answer_kind(item: dict):
    if is_price_item(item):
        return "price"
    if item.get("kind") == "宣稱" and item.get("outcome") == "pending":
        return "claim_permission"
    return None


def split_items(items: list) -> dict:
    buckets = {"accepted": [], "needs_confirmation": [], "forbidden": []}
    for item in items:
        shaped = {**item, "answer_kind": answer_kind(item)}
        shaped.pop("_moved_to_needs_confirmation", None)
        buckets[bucket_name(item)].append(shaped)
    return buckets


def answers_by_item(raw) -> dict:
    """同時接受物件對照與列陣列，讓前端可用最自然的表單狀態送出。"""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        return {
            str(entry.get("item_id")): entry
            for entry in raw if isinstance(entry, dict) and entry.get("item_id")
        }
    return {}


def price_answer(raw):
    value = raw.get("value") if isinstance(raw, dict) else raw
    if isinstance(value, bool) or value is None:
        return None
    value = str(value).strip()
    return value or None


def claim_answer(raw):
    if isinstance(raw, dict):
        raw = raw.get("decision", raw.get("can_say"))
    if isinstance(raw, bool):
        return "approved" if raw else "forbidden"
    value = str(raw or "").strip().lower()
    if value in _CAN_SAY:
        return "approved"
    if value in _CANNOT_SAY:
        return "forbidden"
    return None
