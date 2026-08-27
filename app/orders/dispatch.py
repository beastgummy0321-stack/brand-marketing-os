# -*- coding: utf-8 -*-
"""app/orders/dispatch.py — 萬用拖檔口分派層（GitHub issue #33）。

單一入口 import_dropped_file()：不管拖進來的是 EasyStore 訂單匯出（.xlsx）還是
Meta 廣告成效 CSV，都丟進這裡，自動辨識檔案類型並路由到對應解析器——兩階段欄名
比對機制完全重用 app/ads/performance.match_columns，這裡只加「認出來、轉手」的
分派邏輯，不重寫解析或匯入本身（本票 DoR 指定做法）。

12 個月歷史回填走同一入口：使用者分批把不同月份的匯出檔拖進來，各自以
(brand_id, order_number) 為準覆寫最新狀態，重疊月份不會重複算（見
app/orders/repository.save_orders）。

Meta CSV 這條路徑額外做「自動對期別、跨期拆分」：這個入口在品牌層級（不掛在某一期
檔期底下），CSV 裡的資料列依日期自動配到重疊的廣告檔期，橫跨多期的檔案自動依期別
分組個別寫入；配不到任何檔期的列（多半是舊廣告）轉入品牌層（campaign_cycle_id=NULL，
決策 0039 第 7 條），老實回報筆數，不假裝塞進某一期。
"""

import csv
import io
from datetime import date as date_cls
from typing import Optional

from app.ads import codes as ads_codes
from app.ads import performance as ads_performance
from app.ads import repository as ads_repo
from app.ads import weekly_proposals
from app.orders import channel as orders_channel
from app.orders import importer as orders_importer
from app.orders import repository as orders_repo


class DispatchResult:
    def __init__(self):
        # 'easystore_orders' | 'meta_ads_csv' | 'shopee_report' | 'unknown'
        self.kind = "unknown"
        self.order_result = None       # app.orders.importer.OrderImportResult
        self.ads_imported = 0
        self.ads_quarantined = 0
        self.ads_unmatched_rows = 0
        self.shopee_result = None      # app.orders.channel.ShopeeImportResult
        self.late_reruns: list = []    # 晚到資料觸發的 v2+ 重判（見 _rerun_affected_cycles）
        self.errors: list = []


def _rerun_affected_cycles(conn, brand_id: str, actor: str, cycle_ids) -> list:
    """晚到檔案丟進拖檔口時，自動觸發受影響期別的重判（決策 0025 懶人優先第 3 點：
    「補件驅動回溯重判，不設死線」）。走 `weekly_proposals.rerun_after_late_data`——跟
    CSV／手動填成效走同一個共用出處（票 F1），不是只呼叫 `ads_reading.rerun_for_late_data`：
    以前這裡沒有 LIVE 檔期首判的 bootstrap 分支，也從不補建週提案卡，補件重判後
    `reading.run()` 清掉的舊卡沒人接著補（見 `reading.py` 的 `preserved_weekly` 刪除範圍）。"""
    results = []
    for cycle_id in cycle_ids:
        outcome = weekly_proposals.rerun_after_late_data(conn, brand_id, cycle_id, actor=actor)
        if outcome["rerun"] != "skipped":
            outcome["cycle_id"] = cycle_id
            results.append(outcome)
    return results


def _decode_text(content: bytes) -> tuple:
    for encoding in ("utf-8-sig", "utf-8", "cp950", "big5"):
        try:
            return content.decode(encoding), None
        except UnicodeDecodeError:
            continue
    return "", "這個檔案的文字編碼讀不出來，請用 Excel 另存成 UTF-8 的 CSV。"


def _csv_headers(text: str) -> list:
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    return next(reader, [])


def _order_date_range(rows: list) -> Optional[tuple]:
    """解析後（尚未落庫）的訂單列裡，日期最早到最晚是哪一段——用來找「受影響期別」，
    不用等落庫後再查一次 DB（比照 app.orders.repository.save_orders 同一套 str(...)[:10]
    正規化，兩邊算出來的日期字串才對得上）。"""
    dates = [str(row["order_date"])[:10] for row in rows if row.get("order_date")]
    return (min(dates), max(dates)) if dates else None


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
    # 用碼暴增輕量警示（GitHub issue #35）：新訂單進來，用碼量可能變了，順手檢查一次。
    ads_codes.check_surge_for_brand(conn, brand_id)

    # 晚到訂單資料觸發受影響期別的補件重判（GitHub issue #38）：訂單不掛檔期外鍵
    # （決策 0025 補遺第 1 點），受影響期別靠日期範圍重疊找，不是靠外鍵查。
    date_range = _order_date_range(rows)
    if date_range:
        # BUG 修復（route=C 02-3c，同 dispatch.py:141 那個根因，這裡是另一個發生點）：
        # since/until 是 _order_date_range() 算出來的字串，cycle["start_date"]/
        # ["end_date"] 是 Postgres date 欄位讀回來的 datetime.date，型別不同直接
        # TypeError。轉成 date 物件再比。
        since, until = (date_cls.fromisoformat(d) for d in date_range)
        cycles = ads_repo.list_cycles(conn, brand_id, include_archived=True)
        affected = [c["id"] for c in cycles if c["start_date"] <= until and since <= c["end_date"]]
        result.late_reruns = _rerun_affected_cycles(conn, brand_id, actor, affected)
    return result


def _import_shopee(conn, brand_id: str, text: str, actor: str) -> DispatchResult:
    """蝦皮賣家中心報表（GitHub issue #40）：品牌層落地，不掛檔期外鍵，不觸發補件重判
    ——通路對照卡是選填的輔助訊號，不是判讀主資料，晚到不需要驚動已判讀過的檔期。"""
    result = DispatchResult()
    result.kind = "shopee_report"
    rows, parse_result = orders_channel.parse_shopee_csv(text)
    if parse_result.errors:
        result.errors.extend(parse_result.errors)
        return result
    result.shopee_result = orders_channel.save_shopee_rows(
        conn, brand_id, rows, source="shopee_csv", actor=actor)
    return result


def _import_meta_csv(conn, brand_id: str, text: str, actor: str,
                     today: Optional[str]) -> DispatchResult:
    result = DispatchResult()
    result.kind = "meta_ads_csv"
    rows, parse_result = ads_performance.parse_csv(text)
    if parse_result.errors:
        result.errors.extend(parse_result.errors)
        return result

    today = today or date_cls.today().isoformat()
    cycles = ads_repo.list_cycles(conn, brand_id, include_archived=True)

    grouped: dict = {}
    brand_level_rows = []
    for row in rows:
        # BUG 修復（route=C 02-3c，app/orders/dispatch.py:141）：cycle["start_date"]/
        # ["end_date"] 是 date 欄位讀回來的 datetime.date，row_date 是字串；SQLite
        # 兩邊都當字串比，Postgres 型別不同直接 TypeError。轉成 date 物件再比。
        row_date = date_cls.fromisoformat(row.get("date_start") or row.get("date_stop") or today)
        cycle = next((c for c in cycles if c["start_date"] <= row_date <= c["end_date"]), None)
        if cycle is None:
            brand_level_rows.append(row)
            continue
        grouped.setdefault(cycle["id"], []).append(row)

    for cycle_id, cycle_rows in grouped.items():
        cycle_result = ads_performance.import_rows(
            conn, brand_id, cycle_id, cycle_rows, source="csv", actor=actor, today=today)
        result.ads_imported += cycle_result.imported
        result.ads_quarantined += cycle_result.quarantined
        ads_performance.save_derived_metrics(conn, brand_id, cycle_id)

    if brand_level_rows:
        # 決策 0039 第 7 條：對不到檔期的列不再整批丟棄，多半是系統誕生前的舊廣告匯出檔——
        # 轉品牌層（campaign_cycle_id=NULL），成效仍進品牌基準（只算點擊面，見
        # ads_performance.save_brand_level_derived_metrics）。
        brand_result = ads_performance.import_rows(
            conn, brand_id, None, brand_level_rows, source="csv", actor=actor, today=today)
        result.ads_imported += brand_result.imported
        result.ads_quarantined += brand_result.quarantined
        ads_performance.save_brand_level_derived_metrics(conn, brand_id)
        result.ads_unmatched_rows = len(brand_level_rows)
        note = (f"有 {len(brand_level_rows)} 列的日期對不到任何一期廣告檔期，"
               f"已入品牌層歷史 {brand_result.imported} 列。")
        if brand_result.skipped:
            # issue #68：同一份 CSV 重複匯入時如實列出略過幾列，不假裝全部都是新資料
            note += f"其中 {brand_result.skipped} 列跟已有資料完全重複，已略過不重複計入。"
        result.errors.append(note)
    # 用碼暴增輕量警示（GitHub issue #35）：曝光數字可能變了，順手檢查一次。
    ads_codes.check_surge_for_brand(conn, brand_id)
    # 晚到成效資料觸發受影響期別的補件重判（GitHub issue #38）：這期若已經判讀過、
    # 且不在投放中，才算「晚到」，ads_reading.rerun_for_late_data 自己判斷、原樣略過其餘情況。
    result.late_reruns = _rerun_affected_cycles(conn, brand_id, actor, grouped.keys())
    return result


def import_dropped_file(conn, brand_id: str, *, filename: str, content: bytes, actor: str,
                        today: Optional[str] = None) -> DispatchResult:
    """萬用拖檔口的唯一入口：認出檔案類型、轉交給對應解析器＋匯入函式。"""
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
    if orders_importer.looks_like_meta_ads_csv(headers):
        return _import_meta_csv(conn, brand_id, text, actor, today)

    result = DispatchResult()
    result.errors.append(
        f"認不出這個檔案的格式，確認一下是不是 EasyStore 訂單匯出或 Meta 廣告成效 CSV。"
        f"檔案裡有的欄位是：{'、'.join(h for h in headers if h)[:200]}"
    )
    return result
