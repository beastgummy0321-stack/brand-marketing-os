# -*- coding: utf-8 -*-
"""app/ads/offer.py — 檔期優惠（票 V1-01）。

`offer` 表（`app/ads/migrations/0001_tables.sql:133`）唯一的寫入口：INSERT／UPDATE／
DELETE 全部集中在這支檔案，其他模組要碰優惠一律經過這裡的公開函式（`brief_assembler.py`
的既有讀法例外——那邊只查，不寫，維持原樣）。

使用者只填三格（名稱／類型／條件）——決策見票面：`price_value`／`currency`／優惠自己的
起訖日不開放填，起訖日直接沿用檔期的 `start_date`／`end_date`（優惠是跟著檔期走的，不是
獨立實體，多期共用一個優惠、或優惠自訂比檔期短的效期，都是刻意排除的範圍）。

`offer` 沒有反向掛 `campaign_cycle` 的 FK（schema 註記見遷移檔），所以開期當下可以先建
optional 的 offer row、再把 id 傳給 `create_cycle()`（呼叫順序見
`routes_campaigns_open_api.py` 的 `create_cycle` 路由），不會撞外鍵。
"""

from typing import Optional

from app.core.db import new_id, now_utc, jsonb, Conn, DEV_ORG_ID

TYPES = (("discount", "折扣"), ("bundle", "組合"), ("gift", "贈品"))
_VALID_TYPES = {code for code, _ in TYPES}

_NAME_MAX_LEN = 60
_TERMS_MAX_LEN = 500


def validate(body: dict) -> tuple:
    """三格表單的驗證。成功回 (fields, None)；失敗回 (None, 人話錯誤)，不丟例外——呼叫端
    （API 路由、開期表單）直接把第二個值當 400 訊息用。"""
    name = str(body.get("name") or "").strip()
    offer_type = str(body.get("offer_type") or "").strip()
    terms = str(body.get("terms") or "").strip()

    if not name:
        return None, "請幫這個優惠取個名字，例如「全館 8 折」。"
    if len(name) > _NAME_MAX_LEN:
        return None, f"優惠名稱請控制在 {_NAME_MAX_LEN} 字以內。"
    if offer_type not in _VALID_TYPES:
        return None, "請選一種優惠類型：折扣、組合或贈品。"
    if not terms:
        return None, "請填一下這次優惠的使用條件，例如「滿 2000 折 300」。"
    if len(terms) > _TERMS_MAX_LEN:
        return None, f"優惠條件請控制在 {_TERMS_MAX_LEN} 字以內。"
    return {"name": name, "offer_type": offer_type, "terms": terms}, None


def _row(cursor_row) -> Optional[dict]:
    return dict(cursor_row) if cursor_row is not None else None


def get(conn: Conn, brand_id: str, offer_id: str) -> Optional[dict]:
    return _row(conn.execute(
        "SELECT * FROM offer WHERE brand_id = %s AND id = %s", (brand_id, offer_id)
    ).fetchone())


def create(conn: Conn, brand_id: str, *, product_scope_json: str,
          valid_from: str, valid_to: str, fields: dict) -> str:
    """插進一筆 offer row，回傳新 id。呼叫端已經跑過 `validate()`；`price_value`／
    `currency` 固定 NULL（3 格表單不問），`status` 固定 `active`（沒有草稿態）。"""
    offer_id = new_id("ofr")
    ts = now_utc()
    conn.execute(
        "INSERT INTO offer (id, org_id, brand_id, product_scope_json, name, offer_type, terms,"
        " price_value, currency, valid_from, valid_to, status, created_at, updated_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, NULL, %s, %s, 'active', %s, %s)",
        (offer_id, DEV_ORG_ID, brand_id, jsonb(product_scope_json), fields["name"], fields["offer_type"],
         fields["terms"], valid_from, valid_to, ts, ts),
    )
    conn.commit()
    return offer_id


def save_for_cycle(conn: Conn, brand_id: str, cycle: dict, fields: dict) -> dict:
    """PUT 端點用：檔期已經掛了 offer 就地改內容（名稱／類型／條件三格，效期跟產品範圍
    不變——那兩個欄位是開期當下定的，編輯優惠不重新框定範圍）；沒有就新開一筆，順便把
    `campaign_cycle.offer_id` 補上去。

    `derived_plan_json` 在這裡完全不碰——票面決策：後補或編輯優惠不重算排期／日預算，
    使用者已經看過的數字不會因為填了優惠而跳動（脈動排期只在**開期當下**帶優惠才會觸發，
    見 `repository.create_cycle()`）。"""
    existing_id = cycle.get("offer_id")
    if existing_id:
        conn.execute(
            "UPDATE offer SET name = %s, offer_type = %s, terms = %s, updated_at = %s"
            " WHERE brand_id = %s AND id = %s",
            (fields["name"], fields["offer_type"], fields["terms"], now_utc(),
             brand_id, existing_id),
        )
        conn.commit()
        return get(conn, brand_id, existing_id)

    offer_id = create(conn, brand_id, product_scope_json=cycle["product_scope_json"],
                      valid_from=cycle["start_date"], valid_to=cycle["end_date"], fields=fields)
    conn.execute("UPDATE campaign_cycle SET offer_id = %s WHERE brand_id = %s AND id = %s",
                (offer_id, brand_id, cycle["id"]))
    conn.commit()
    return get(conn, brand_id, offer_id)


def clear_for_cycle(conn: Conn, brand_id: str, cycle: dict) -> None:
    """DELETE 端點用：先鬆開 `campaign_cycle.offer_id`、再刪 offer row——row 是檔期專屬的
    （沒有其他表引用 `offer`，票面已確認 `grep "REFERENCES offer"` 零命中），刪了不留孤兒。"""
    offer_id = cycle.get("offer_id")
    conn.execute("UPDATE campaign_cycle SET offer_id = NULL WHERE brand_id = %s AND id = %s",
                (brand_id, cycle["id"]))
    if offer_id:
        conn.execute("DELETE FROM offer WHERE brand_id = %s AND id = %s", (brand_id, offer_id))
    conn.commit()
