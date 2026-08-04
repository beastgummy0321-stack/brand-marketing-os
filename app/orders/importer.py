# -*- coding: utf-8 -*-
"""app/orders/importer.py — EasyStore 訂單匯出檔解析＋萬用拖檔口分派層（GitHub issue #33）。

依賴：openpyxl（讀 .xlsx）。專案沒有 requirements.txt／Pipfile 等依賴管理檔（find 過整個
repo 只有這個模組要用到 xlsx），環境裡已裝 3.1.5——選最小方案：不新增依賴管理檔，直接
import，缺套件時會在啟動時明顯報錯，不是這裡刻意隱藏的風險。

分派層只做一件事：拖進來的檔案是 EasyStore 訂單匯出、還是 Meta 廣告 CSV？
兩階段欄名比對機制完全重用 app/ads/performance.match_columns（只是換一張別名表），
不重寫比對邏輯——這正是本票 DoR 指定的做法。

EasyStore 匯出格式（決策 0025：使用者真實 Export_Orders 檔已驗證，修正版）：一張訂單可能有
多列（一列一個商品品項）。真實檔案裡 Order Number **每一列都有填**，不是只有首列——分組依據
是「連續同一個 Order Number」，不是「Order Number 是否留空」。訂單層欄位（金額／狀態／
email 等）只認同一組裡的第一列，後續列即使 Order Number 有填也只拿來取商品品項。
"""

import io
from dataclasses import dataclass, field
from typing import Optional

from app.ads import performance as ads_performance

try:
    import openpyxl
except ImportError:  # pragma: no cover — 環境沒裝 openpyxl 時給人話而非 stack trace
    openpyxl = None

# EasyStore 欄位實況（票 33 DoR 附的真實欄名）。別名表刻意保守——這些是使用者真實匯出檔
# 驗證過的欄名，之後遇到不同語系或改版欄名再補別名，不先猜（鐵則：認不出就誠實說，不硬猜）。
ORDER_COLUMN_ALIASES = {
    "order_number": ["order number", "order no", "order#"],
    "order_date": ["date", "order date"],
    "total_amount": ["total amount", "total"],
    "refunded_amount": ["refunded amount", "refunded"],
    "financial_status": ["financial status"],
    "fulfillment_status": ["fulfillment status"],
    "order_status": ["order status"],
    "voucher_code": ["voucher code", "discount code"],
    "billing_email": ["billing email"],
    "billing_phone": ["billing phone"],
    "item_sku": ["item sku"],
    "item_price": ["item price"],
    "quantity": ["quantity", "qty"],
}

ORDER_REQUIRED_COLUMNS = ["order_number"]

# 判斷是不是「看起來像 EasyStore 訂單檔」的最低門檻：有訂單編號，且至少對得到
# 金額或商品欄位其中一種——只有訂單編號但什麼商品/金額資訊都沒有，可能只是巧合同名欄。
_EASYSTORE_CONFIRM_COLUMNS = ("total_amount", "item_sku", "billing_email")


@dataclass
class OrderImportResult:
    orders_imported: int = 0
    orders_updated: int = 0
    items_imported: int = 0
    errors: list = field(default_factory=list)
    unmatched_columns: list = field(default_factory=list)
    found_columns: list = field(default_factory=list)


def match_order_columns(headers: list) -> tuple:
    """重用 app.ads.performance.match_columns 的兩階段比對演算法，換上訂單別名表。"""
    return ads_performance.match_columns(headers, ORDER_COLUMN_ALIASES)


def looks_like_easystore_orders(headers: list) -> bool:
    mapping, _ = match_order_columns(headers)
    if "order_number" not in mapping:
        return False
    return any(col in mapping for col in _EASYSTORE_CONFIRM_COLUMNS)


def looks_like_meta_ads_csv(headers: list) -> bool:
    """跟現有 CSV 匯入用同一套判斷：對得到「花費」欄，就是 Meta 廣告成效檔。"""
    mapping, _ = ads_performance.match_columns(headers)
    return "spend" in mapping


def sniff_file_kind(filename: str, headers: list) -> str:
    """分派層：回傳 'easystore_orders' / 'meta_ads_csv' / 'unknown'。

    表頭比對優先：認得出訂單欄位就是訂單檔。認不出、但副檔名是 xlsx（Meta CSV 匯出
    從來不是 xlsx）就誠實回 unknown，不硬套 CSV 解析器去讀二進位內容。
    """
    if looks_like_easystore_orders(headers):
        return "easystore_orders"
    if (filename or "").lower().endswith((".xlsx", ".xlsm")):
        return "unknown"
    if looks_like_meta_ads_csv(headers):
        return "meta_ads_csv"
    return "unknown"


def _sheet_rows(workbook_bytes: bytes) -> list:
    """xlsx 二進位 → [表頭, 資料列...]（每列都是 cell 值的 list，openpyxl 唯讀模式）。"""
    if openpyxl is None:
        raise RuntimeError("openpyxl 沒有安裝，讀不了 .xlsx 檔（pip install openpyxl）。")
    wb = openpyxl.load_workbook(io.BytesIO(workbook_bytes), data_only=True, read_only=True)
    sheet = wb.worksheets[0]
    return [list(row) for row in sheet.iter_rows(values_only=True)]


def parse_easystore_xlsx(content: bytes) -> tuple:
    """EasyStore xlsx → (訂單列, OrderImportResult)。訂單列已按 Order Number 分組、
    合併同一張訂單的多個商品品項；不碰資料庫（比照 ads_performance.parse_csv 的分工）。

    每個訂單列的形狀：{**訂單層欄位, "items": [{"sku", "item_price", "quantity"}, ...]}
    """
    result = OrderImportResult()
    all_rows = _sheet_rows(content)
    if not all_rows:
        result.errors.append("檔案是空的，沒有東西可以匯入。")
        return [], result

    raw_headers = [str(h).strip() if h is not None else "" for h in all_rows[0]]
    headers = ads_performance.dedupe_headers(raw_headers)
    mapping, unmatched = match_order_columns(headers)
    result.found_columns = headers
    result.unmatched_columns = unmatched

    missing = [c for c in ORDER_REQUIRED_COLUMNS if c not in mapping]
    if missing:
        result.errors.append(
            "這個檔案裡找不到「訂單編號」欄位，沒有編號就沒辦法逐筆入庫。"
            f"檔案裡有的欄位是：{'、'.join(h for h in headers if h)[:200]}"
        )
        return [], result

    col_index = {header: i for i, header in enumerate(headers)}

    def _cell(data_row: list, concept: str):
        column = mapping.get(concept)
        if column is None:
            return None
        idx = col_index.get(column)
        if idx is None or idx >= len(data_row):
            return None
        return data_row[idx]

    orders: dict = {}
    order_sequence: list = []
    current = None  # 目前正在收集品項的訂單編號（分組靠「連續同號」，不是靠留白）
    for data_row in all_rows[1:]:
        if data_row is None or all(v is None for v in data_row):
            continue  # 空白列
        order_number = _cell(data_row, "order_number")
        order_number = str(order_number).strip() if order_number is not None else ""

        sku = _cell(data_row, "item_sku")
        item_price = ads_performance.to_number(_cell(data_row, "item_price"))
        quantity = ads_performance.to_number(_cell(data_row, "quantity"))

        if order_number and order_number != current:
            # 新訂單開頭列（Order Number 跟前一列不同）：訂單層欄位在這一列
            orders[order_number] = {
                "order_number": order_number,
                "order_date": _cell(data_row, "order_date"),
                "total_amount": ads_performance.to_number(_cell(data_row, "total_amount")),
                "refunded_amount": ads_performance.to_number(_cell(data_row, "refunded_amount")),
                "financial_status": _cell(data_row, "financial_status"),
                "fulfillment_status": _cell(data_row, "fulfillment_status"),
                "order_status": _cell(data_row, "order_status"),
                "voucher_code": _cell(data_row, "voucher_code"),
                "billing_email": _cell(data_row, "billing_email"),
                "billing_phone": _cell(data_row, "billing_phone"),
                "items": [],
            }
            order_sequence.append(order_number)
            current = order_number
        elif not order_number:
            # 續行留白：同一張訂單的下一個商品品項，沿用目前正在收集的訂單
            if current is None:
                continue  # 沒有前一筆訂單可歸屬的孤兒列，跳過（缺表頭列或格式跑版）
        # else: order_number == current（真實檔案常見：每列都填、但跟前一列同號）
        # → 續行，不覆寫已收集的訂單層欄位與 items，只往下取這一列的商品品項

        if sku or item_price is not None or quantity is not None:
            orders[current]["items"].append({
                "sku": (str(sku).strip() if sku is not None else None),
                "item_price": item_price,
                "quantity": quantity,
            })

    rows = [orders[num] for num in order_sequence]
    if not rows:
        result.errors.append("檔案讀得懂，但裡面沒有任何一筆訂單。")
    return rows, result
