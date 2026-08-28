"""app/orders/dispatch.py — 萬用拖檔口分派層（GitHub issue #33）。

單一入口 import_dropped_file()：拖進來的檔案自動辨識類型並路由到對應解析器——兩階段
欄名比對機制重用 app/shared/csv_columns.match_columns，這裡只加「認出來、轉手」的
分派邏輯，不重寫解析或匯入本身。

12 個月歷史回填走同一入口：使用者分批把不同月份的匯出檔拖進來，各自以
(brand_id, order_number) 為準覆寫最新狀態，重疊月份不會重複算（見
app/orders/repository.save_orders）。

外殼切片（2026-08-28）：Meta 廣告成效 CSV 那條路徑跟著 `app/ads/` 一起刪掉——匯入
成效、自動對期別、跨期拆分、補件重判都是廣告模組的東西，v1 範圍不含成效回收。
現在認得的是 EasyStore 訂單匯出（.xlsx）與蝦皮賣家中心報表（.csv）兩種。
"""

import csv
import io

from app.orders import channel as orders_channel
from app.orders import importer as orders_importer
from app.orders import repository as orders_repo


class DispatchResult:
    def __init__(self):
        # 'easystore_orders' | 'shopee_report' | 'unknown'
        self.kind = "unknown"
        self.order_result = None       # app.orders.importer.OrderImportResult
        self.shopee_result = None      # app.orders.channel.ShopeeImportResult
        self.errors: list = []


def _decode_text(content: bytes) -> tuple:
    for encoding in ("utf-8-sig", "utf-8", "cp950", "big5"):
        try:
            return content.decode(encoding), None
        except UnicodeDecodeError:
            continue
    return "", "這個檔案的文字編碼讀不出來，請用 Excel 另存成 UTF-8 的 CSV。"


def _csv_headers(text: str) -> list:
    reader = csv.reader(io.StringIO(text.lstrip("\ufeff")))
    return next(reader, [])


def _import_easystore(conn, brand_id: str, content: bytes, actor: str) -> DispatchResult:
    result = DispatchResult()
    result.kind = "easystore_orders"
    try:
        rows, parse_result = orders_importer.parse_easystore_xlsx(content)
    except RuntimeError as exc:
        result.kind = "unknown"
        result.errors.append(str(exc))
        return result
    if parse_result.errors:
        result.errors.extend(parse_result.errors)
        return result
    result.order_result = orders_repo.save_orders(conn, brand_id, rows,
                                                   source="easystore_xlsx", actor=actor)
    return result


def _import_shopee(conn, brand_id: str, text: str, actor: str) -> DispatchResult:
    """蝦皮賣家中心報表（GitHub issue #40）：品牌層落地，不掛檔期外鍵。"""
    result = DispatchResult()
    result.kind = "shopee_report"
    rows, parse_result = orders_channel.parse_shopee_csv(text)
    if parse_result.errors:
        result.errors.extend(parse_result.errors)
        return result
    result.shopee_result = orders_channel.save_shopee_rows(
        conn, brand_id, rows, source="shopee_csv", actor=actor)
    return result


def import_dropped_file(conn, brand_id: str, *, filename: str, content: bytes, actor: str,
                        today: str | None = None) -> DispatchResult:
    """萬用拖檔口的唯一入口：認出檔案類型、轉交給對應解析器＋匯入函式。

    `today` 目前不影響任何路徑（成效匯入拿掉後沒有需要對期別的東西），保留參數是為了
    呼叫端不必跟著改；有需要按「今天」判斷的匯入再接回來。
    """
    is_xlsx = (filename or "").lower().endswith((".xlsx", ".xlsm"))
    if is_xlsx:
        return _import_easystore(conn, brand_id, content, actor)

    text, decode_error = _decode_text(content)
    if decode_error:
        result = DispatchResult()
        result.errors.append(decode_error)
        return result

    headers = _csv_headers(text)
    if orders_channel.looks_like_shopee_report(headers):
        return _import_shopee(conn, brand_id, text, actor)
    if orders_importer.looks_like_easystore_orders(headers):
        result = DispatchResult()
        result.errors.append("這個檔案看起來是訂單資料，但目前訂單匯入只支援 EasyStore 匯出的 .xlsx 檔。")
        return result

    result = DispatchResult()
    result.errors.append(
        f"認不出這個檔案的格式，確認一下是不是 EasyStore 訂單匯出或蝦皮賣家中心報表。"
        f"檔案裡有的欄位是：{'、'.join(h for h in headers if h)[:200]}"
    )
    return result
