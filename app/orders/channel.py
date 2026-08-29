"""app/orders/channel.py — 通路對照卡（GitHub issue #40，決策 0025 第二節 B）。

治兩種系統性誤判：
- **外溢低估**：廣告把人帶去平台商店或實體通路買，官網數字看不到，被誤判成「廣告沒效」。
- **互噬高估**：平台商店既有客被搬來官網下單，官網「新客」其實是舊客換通路，假新增。

兩種選填資料源，缺哪個都不擋路（決策 0025 懶人優先第 5 點：「選填層被動觸發」）：
1. 蝦皮賣家中心報表拖檔匯入（重用 app/shared/csv_columns.match_columns 兩階段欄名比對，
   分派層在 app/orders/dispatch.py）。
2. 手動通路營收登記——任何一種實體通路（藥局、車行、批發，任何行業），一個通用表單。

⚠ 蝦皮報表欄位別名表是依蝦皮賣家中心「訂單」匯出常見欄名的合理假設寫的，**尚未用真實
匯出檔驗證過**（鐵則 11：假資料全過≠擋得住真實格式）。使用者提供真實檔後要再校準一次。

票 12（ADR 0035「通路是資料，離線通路只有一種」，2026-08-29）：通路營收統一落在
app/orders/repository.channel_revenue 這一張表，`channel` 值來自
app.core.vocab.CHANNEL_TYPES，不再是各通路各自一張表。藥局出貨批次的補貨間隔訊號隨
`app/ads/` 一起刪除（訊號的呼叫端已經不存在），留下的日期／數量／備註併入通用列
（revenue 留 NULL，代表「不知道」，不是 0）。
"""

import csv
import io

from app.brand_intelligence import repository as bi_repo
from app.core import vocab
from app.core.audit import write_audit
from app.core.db import new_id, now_utc
from app.shared import csv_columns

# 蝦皮賣家中心「訂單」匯出常見欄名（未經真實檔驗證，見檔頭誠實標注）。order_sn 是
# 唯一識別欄，跟 EasyStore 的 order_number 別名表刻意不重疊，分派層才分得清兩種檔案。
SHOPEE_COLUMN_ALIASES = {
    "order_sn": ["order sn", "訂單編號", "訂單流水號"],
    "order_date": ["order creation date", "訂單成立時間", "建立時間"],
    "revenue": ["order amount", "訂單金額", "buyer paid amount", "買家實付金額", "結算金額"],
    "voucher_code": ["voucher code", "優惠碼", "促銷代碼"],
}
SHOPEE_REQUIRED_COLUMNS = ["order_sn"]
_SHOPEE_CONFIRM_COLUMNS = ("revenue", "order_date", "voucher_code")


class ShopeeImportResult:
    def __init__(self):
        self.imported = 0
        self.updated = 0
        self.errors: list = []
        self.unmatched_columns: list = []
        self.found_columns: list = []


def match_shopee_columns(headers: list) -> tuple:
    """重用 app.shared.csv_columns.match_columns 的兩階段比對演算法，換上蝦皮別名表。"""
    return csv_columns.match_columns(headers, SHOPEE_COLUMN_ALIASES)


def looks_like_shopee_report(headers: list) -> bool:
    mapping, _ = match_shopee_columns(headers)
    if "order_sn" not in mapping:
        return False
    return any(col in mapping for col in _SHOPEE_CONFIRM_COLUMNS)


def parse_shopee_csv(text: str) -> tuple:
    """蝦皮報表 CSV → (資料列, ShopeeImportResult)。不碰資料庫（解析與落庫分工）。"""
    result = ShopeeImportResult()
    if not text or not text.strip():
        result.errors.append("檔案是空的，沒有東西可以匯入。")
        return [], result

    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    headers = reader.fieldnames or []
    if not headers:
        result.errors.append("讀不出這個檔案的欄位名稱，確認一下是不是 CSV 檔。")
        return [], result
    headers = csv_columns.dedupe_headers(headers)
    reader.fieldnames = headers

    mapping, unmatched = match_shopee_columns(headers)
    result.found_columns = headers
    result.unmatched_columns = unmatched

    missing = [c for c in SHOPEE_REQUIRED_COLUMNS if c not in mapping]
    if missing:
        result.errors.append(
            "這個檔案裡找不到「訂單編號」欄位，沒有編號就沒辦法去重入庫。"
            f"檔案裡有的欄位是：{'、'.join(headers[:12])}"
            + ("……" if len(headers) > 12 else "")
        )
        return [], result

    rows = []
    for raw_row in reader:
        row = {}
        for concept, column in mapping.items():
            value = raw_row.get(column)
            if concept == "revenue":
                row[concept] = csv_columns.to_number(value)
            elif concept == "order_date":
                row[concept] = (str(value).strip()[:10] or None) if value else None
            else:
                row[concept] = (value or "").strip() or None
        if not row.get("order_sn"):
            continue  # 空白行或總計列
        rows.append(row)

    if not rows:
        result.errors.append("檔案讀得懂，但裡面沒有任何一筆訂單。")
    return rows, result


def save_shopee_rows(conn, brand_id: str, rows: list, *, source: str, actor: str,
                     result: ShopeeImportResult | None = None,
                     import_batch_id: str | None = None) -> ShopeeImportResult:
    """落地蝦皮報表列到 channel_revenue（channel='marketplace'，external_id=order_sn）。
    同 order_sn 重複匯入（歷史回填月份重疊）整批覆寫最新狀態——跟
    app/orders/repository.save_orders 對 EasyStore 訂單的處理方式一致（票 12）。"""
    if not actor or not actor.strip():
        raise ValueError("actor 為必填")
    org_id = bi_repo.get_brand(conn, brand_id)["org_id"]
    result = result or ShopeeImportResult()
    ts = now_utc()
    batch_id = import_batch_id or f"shopee_{ts}"

    for row in rows:
        order_sn = row.get("order_sn")
        existing = conn.execute(
            "SELECT id FROM channel_revenue WHERE brand_id = %s AND channel = 'marketplace'"
            " AND external_id = %s",
            (brand_id, order_sn),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE channel_revenue SET entry_date = %s, revenue = %s, source = %s,"
                " import_batch_id = %s, updated_at = %s WHERE id = %s",
                (row.get("order_date"), row.get("revenue"), source, batch_id, ts, existing["id"]),
            )
            result.updated += 1
        else:
            conn.execute(
                "INSERT INTO channel_revenue (id, org_id, brand_id, channel, entry_date, external_id,"
                " revenue, source, import_batch_id, created_at, updated_at)"
                " VALUES (%s, %s, %s, 'marketplace', %s, %s, %s, %s, %s, %s, %s)",
                (new_id("chr"), org_id, brand_id, row.get("order_date"), order_sn,
                 row.get("revenue"), source, batch_id, ts, ts),
            )
            result.imported += 1

    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="channel_revenue", entity_id=brand_id,
                action="import_shopee", actor=actor,
                before=None, after={"imported": result.imported, "updated": result.updated})
    conn.commit()
    return result


# ---------------------------------------------------------------------------
# 手動通路營收登記（票 12：一個通用表單，取代藥局專屬表單）
# ---------------------------------------------------------------------------

# 官網那一列帳是 `repository.save_orders()` 從訂單推出來的（票 12 settled 段第 4 點：
# 一個通路的帳只有一條寫入路徑）。手動再輸一筆，帳本就會跟訂單頁的實收永遠對不起來，
# 而且手動列沒有 external_id、連唯一索引都去不了重——票 12 審查抓到的錯，這裡擋掉。
AUTO_LEDGER_CHANNELS = frozenset({"website"})
HAND_ENTRY_CHANNEL_FORBIDDEN_MESSAGE = "官網營收由訂單匯入自動記帳，不能手動登錄。"


def record_channel_entry(conn, brand_id: str, *, channel: str, entry_date: str,
                         revenue: float | None = None, quantity: float | None = None,
                         note: str | None = None, actor: str) -> dict:
    valid_channels = {code for code, _ in vocab.CHANNEL_TYPES}
    if channel not in valid_channels:
        raise ValueError(f"不認得的通路：{channel}")
    if channel in AUTO_LEDGER_CHANNELS:
        raise ValueError(HAND_ENTRY_CHANNEL_FORBIDDEN_MESSAGE)
    if not entry_date or not entry_date.strip():
        raise ValueError("日期為必填")
    if not actor or not actor.strip():
        raise ValueError("actor 為必填")
    ts = now_utc()
    org_id = bi_repo.get_brand(conn, brand_id)["org_id"]
    entry_id = new_id("chr")
    note = note.strip() if note and note.strip() else None
    conn.execute(
        "INSERT INTO channel_revenue (id, org_id, brand_id, channel, entry_date, revenue, quantity,"
        " note, source, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'manual',"
        " %s, %s)",
        (entry_id, org_id, brand_id, channel, entry_date.strip(), revenue, quantity, note, ts, ts),
    )
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="channel_revenue", entity_id=entry_id,
                action="create", actor=actor,
                before=None, after={"channel": channel, "entry_date": entry_date,
                                    "revenue": revenue, "quantity": quantity})
    conn.commit()
    return {"id": entry_id, "channel": channel, "entry_date": entry_date, "revenue": revenue,
           "quantity": quantity, "note": note}


def list_channel_entries(conn, brand_id: str, *, limit: int = 10) -> list:
    """最近的手動登記列（source='manual'），最新的在前面，給訂單頁的通路區塊用。"""
    return [dict(r) for r in conn.execute(
        "SELECT * FROM channel_revenue WHERE brand_id = %s AND source = 'manual'"
        " ORDER BY entry_date DESC, created_at DESC LIMIT %s",
        (brand_id, limit),
    )]


def demo() -> None:
    """python -m app.orders.channel — 純函數自檢：蝦皮報表表頭認得出來、數字容錯正常。"""
    assert looks_like_shopee_report(["訂單編號", "訂單成立時間", "訂單金額"])
    assert not looks_like_shopee_report(["Order Number", "Total Amount"]), (
        "EasyStore 訂單表頭不該被誤認成蝦皮報表")
    csv_text = "訂單編號,訂單成立時間,訂單金額\nSP-1,2026-06-01,\"1,200\"\n"
    rows, result = parse_shopee_csv(csv_text)
    assert result.errors == [], result.errors
    assert rows == [{"order_sn": "SP-1", "order_date": "2026-06-01", "revenue": 1200.0}], rows
    print("channel 自檢通過")


if __name__ == "__main__":
    demo()
