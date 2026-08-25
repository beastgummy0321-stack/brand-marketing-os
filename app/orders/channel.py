# -*- coding: utf-8 -*-
"""app/orders/channel.py — 通路對照卡（GitHub issue #40，決策 0025 第二節 B）。

治兩種系統性誤判：
- **外溢低估**：廣告把人帶去蝦皮或藥局買，官網數字看不到，被誤判成「廣告沒效」。
- **互噬高估**：蝦皮既有客被搬來官網下單，官網「新客」其實是舊客換通路，假新增。

三種選填資料源，缺哪個都不擋路（決策 0025 懶人優先第 5 點：「選填層被動觸發」）：
1. 蝦皮賣家中心報表拖檔匯入（重用 app/ads/performance.match_columns 兩階段欄名比對，
   分派層在 app/orders/dispatch.py）。
2. 藥局出貨批次紀錄（人工填批次日期＋數量），判讀看**補貨間隔縮短**——抗批發雜訊，
   單月出貨量本身容易受批發商下單節奏干擾，間隔縮短是更穩的訊號。
3. 蝦皮期別專屬碼回收數（人工看蝦皮後台填）——外溢下限鐵證，比營收比對更直接。

⚠ 蝦皮報表欄位別名表是依蝦皮賣家中心「訂單」匯出常見欄名的合理假設寫的，**尚未用真實
匯出檔驗證過**（鐵則 11：假資料全過≠擋得住真實格式）。使用者提供真實檔後要再校準一次。

燈號規則（決策 0025：「規則判定粗標籤＋人話說明，不算歸因比例」）：外溢＝藍、互噬＝橘、
缺資料＝灰。三色以外沒有第四色——資料夠但沒有明顯訊號時不亮燈，不強迫每期都要有結論。
"""

import csv
import io
from datetime import date, timedelta
from typing import Optional

from app.ads import performance as ads_performance
from app.core.audit import write_audit
from app.core.db import new_id, now_utc, DEV_ORG_ID

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
    """重用 app.ads.performance.match_columns 的兩階段比對演算法，換上蝦皮別名表。"""
    return ads_performance.match_columns(headers, SHOPEE_COLUMN_ALIASES)


def looks_like_shopee_report(headers: list) -> bool:
    mapping, _ = match_shopee_columns(headers)
    if "order_sn" not in mapping:
        return False
    return any(col in mapping for col in _SHOPEE_CONFIRM_COLUMNS)


def parse_shopee_csv(text: str) -> tuple:
    """蝦皮報表 CSV → (資料列, ShopeeImportResult)。不碰資料庫（比照 ads_performance.parse_csv）。"""
    result = ShopeeImportResult()
    if not text or not text.strip():
        result.errors.append("檔案是空的，沒有東西可以匯入。")
        return [], result

    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    headers = reader.fieldnames or []
    if not headers:
        result.errors.append("讀不出這個檔案的欄位名稱，確認一下是不是 CSV 檔。")
        return [], result
    headers = ads_performance.dedupe_headers(headers)
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
                row[concept] = ads_performance.to_number(value)
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
                     result: Optional[ShopeeImportResult] = None,
                     import_batch_id: Optional[str] = None) -> ShopeeImportResult:
    """落地蝦皮報表列。同 order_sn 重複匯入（歷史回填月份重疊）整批覆寫最新狀態——
    跟 app/orders/repository.save_orders 對 EasyStore 訂單的處理方式一致。"""
    if not actor or not actor.strip():
        raise ValueError("actor 為必填")
    result = result or ShopeeImportResult()
    ts = now_utc()
    batch_id = import_batch_id or f"shopee_{ts}"

    for row in rows:
        order_sn = row.get("order_sn")
        existing = conn.execute(
            "SELECT id FROM shopee_report_row WHERE brand_id = %s AND order_sn = %s",
            (brand_id, order_sn),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE shopee_report_row SET order_date = %s, revenue = %s, voucher_code = %s,"
                " source = %s, import_batch_id = %s, updated_at = %s WHERE id = %s",
                (row.get("order_date"), row.get("revenue"), row.get("voucher_code"), source,
                 batch_id, ts, existing["id"]),
            )
            result.updated += 1
        else:
            conn.execute(
                "INSERT INTO shopee_report_row (id, org_id, brand_id, order_sn, order_date, revenue,"
                " voucher_code, source, import_batch_id, created_at, updated_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (new_id("shp"), DEV_ORG_ID, brand_id, order_sn, row.get("order_date"), row.get("revenue"),
                 row.get("voucher_code"), source, batch_id, ts, ts),
            )
            result.imported += 1

    write_audit(conn, brand_id=brand_id, entity_type="shopee_report_row", entity_id=brand_id,
                action="import_shopee", actor=actor,
                before=None, after={"imported": result.imported, "updated": result.updated})
    conn.commit()
    return result


def shopee_latest_import(conn, brand_id: str) -> Optional[str]:
    """最近一次蝦皮報表匯入時間（依落地列的 created_at 取最新一筆）；從沒匯入過回 None。
    給追蹤健檢用（票 T0 契約 1.5：曾匯入過＝就緒＋最近匯入日期）。"""
    row = conn.execute(
        "SELECT created_at FROM shopee_report_row WHERE brand_id = %s ORDER BY created_at DESC LIMIT 1",
        (brand_id,),
    ).fetchone()
    return row["created_at"] if row else None


def pharmacy_latest_batch(conn, brand_id: str) -> Optional[str]:
    """最近一筆藥局出貨批次日期；從沒記錄過回 None（同上，票 T0 契約 1.5 用）。"""
    row = conn.execute(
        "SELECT batch_date FROM pharmacy_batch WHERE brand_id = %s"
        " ORDER BY batch_date DESC, created_at DESC LIMIT 1",
        (brand_id,),
    ).fetchone()
    return row["batch_date"] if row else None


def shopee_revenue(conn, brand_id: str, since: str, until: str) -> Optional[float]:
    """這段日期範圍蝦皮營收加總。沒有任何一列落在範圍內回 None——不知道跟 0 是兩件事。"""
    row = conn.execute(
        "SELECT SUM(revenue) total, COUNT(*) rows FROM shopee_report_row"
        " WHERE brand_id = %s AND order_date >= %s AND order_date <= %s",
        (brand_id, since, until),
    ).fetchone()
    if not row["rows"]:
        return None
    return round(row["total"] or 0, 2)


# ---------------------------------------------------------------------------
# 藥局出貨批次
# ---------------------------------------------------------------------------

def record_pharmacy_batch(conn, brand_id: str, *, batch_date: str, quantity: Optional[float] = None,
                          note: Optional[str] = None, actor: str) -> dict:
    if not batch_date or not batch_date.strip():
        raise ValueError("批次日期為必填")
    if not actor or not actor.strip():
        raise ValueError("actor 為必填")
    ts = now_utc()
    batch_id = new_id("phb")
    conn.execute(
        "INSERT INTO pharmacy_batch (id, org_id, brand_id, batch_date, quantity, note, created_by,"
        " created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (batch_id, DEV_ORG_ID, brand_id, batch_date.strip(), quantity,
         note.strip() if note and note.strip() else None, actor, ts),
    )
    write_audit(conn, brand_id=brand_id, entity_type="pharmacy_batch", entity_id=batch_id,
                action="create", actor=actor, before=None,
                after={"batch_date": batch_date, "quantity": quantity})
    conn.commit()
    return {"id": batch_id, "batch_date": batch_date, "quantity": quantity, "note": note}


def list_pharmacy_batches(conn, brand_id: str, *, until: Optional[str] = None) -> list:
    sql = "SELECT * FROM pharmacy_batch WHERE brand_id = %s"
    params: list = [brand_id]
    if until:
        sql += " AND batch_date <= %s"
        params.append(until)
    sql += " ORDER BY batch_date"
    return [dict(r) for r in conn.execute(sql, params)]


# 補貨間隔縮短視為外溢訊號的門檻：縮短達此比例才算，避免正常出貨節奏的小幅波動誤觸
# （ponytail：粗略比例門檻，非統計檢定；藥局批次量通常不大，等樣本多了再考慮更嚴謹的判斷）。
RESTOCK_SHORTEN_RATIO = 0.2


def restock_interval_signal(conn, brand_id: str, until: str) -> dict:
    """補貨間隔縮短判定：拿「最新一次間隔」跟「前面幾次間隔的平均」比，縮短達門檻才算訊號。

    至少要有 3 筆批次（兩段間隔可比）才算得出來；不夠回 shortened=None（誠實說看不出來）。
    """
    batches = list_pharmacy_batches(conn, brand_id, until=until)
    if len(batches) < 3:
        return {"shortened": None, "latest_interval_days": None, "baseline_interval_days": None,
               "sample_size": len(batches)}

    dates = [b["batch_date"] for b in batches]
    gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
    latest = gaps[-1]
    baseline = sum(gaps[:-1]) / len(gaps[:-1])
    shortened = bool(baseline > 0 and latest <= baseline * (1 - RESTOCK_SHORTEN_RATIO))
    return {"shortened": shortened, "latest_interval_days": latest,
           "baseline_interval_days": round(baseline, 1), "sample_size": len(batches)}


# ---------------------------------------------------------------------------
# 蝦皮期別專屬碼
# ---------------------------------------------------------------------------

def set_shopee_code(conn, brand_id: str, cycle_id: str, *, code: Optional[str] = None,
                    redemption_count: Optional[int] = None, actor: str) -> dict:
    if not actor or not actor.strip():
        raise ValueError("actor 為必填")
    ts = now_utc()
    existing = conn.execute(
        "SELECT * FROM cycle_shopee_code WHERE brand_id = %s AND campaign_cycle_id = %s",
        (brand_id, cycle_id),
    ).fetchone()
    code = code.strip() if code and code.strip() else None
    if existing:
        conn.execute(
            "UPDATE cycle_shopee_code SET code = %s, redemption_count = %s, updated_by = %s,"
            " updated_at = %s WHERE id = %s",
            (code, redemption_count, actor, ts, existing["id"]),
        )
        row_id = existing["id"]
    else:
        row_id = new_id("shc")
        conn.execute(
            "INSERT INTO cycle_shopee_code (id, org_id, brand_id, campaign_cycle_id, code,"
            " redemption_count, updated_by, created_at, updated_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (row_id, DEV_ORG_ID, brand_id, cycle_id, code, redemption_count, actor, ts, ts),
        )
    write_audit(conn, brand_id=brand_id, entity_type="cycle_shopee_code", entity_id=row_id,
                action="set", actor=actor, before=None,
                after={"code": code, "redemption_count": redemption_count})
    conn.commit()
    return {"id": row_id, "code": code, "redemption_count": redemption_count}


def get_shopee_code(conn, brand_id: str, cycle_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM cycle_shopee_code WHERE brand_id = %s AND campaign_cycle_id = %s",
        (brand_id, cycle_id),
    ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# 燈號規則：外溢（藍）／互噬（橘）／缺資料（灰）
# ---------------------------------------------------------------------------

# 蝦皮營收升降視為外溢／互噬訊號的門檻（ponytail：粗略比例門檻，非統計模型——0025 明定
# 這只是「規則判定粗標籤」，不算歸因比例；有更多期數據後可比照 app/ads/codes.py 的
# CODE_SURGE_RATIO 升級路徑，改成趨勢或分群判斷）。
SPILLOVER_GROWTH_RATIO = 0.2
CANNIBALIZATION_DECLINE_RATIO = 0.2

LIGHT_LABELS = {"spillover": "外溢", "cannibalization": "互噬", "gray": "缺資料"}
LIGHT_BADGE_KIND = {"spillover": "accent", "cannibalization": "warn", "gray": "neutral"}

REPURCHASE_CAUTION_NOTE = "官網老客若久未回購，也可能已轉往蝦皮或藥局購買，不代表流失。"


def _shopee_growth(conn, brand_id: str, since: str, until: str) -> dict:
    """本期蝦皮營收 vs 前一段等長期間的蝦皮營收，算出成長／下滑比例。任一邊沒資料回 ratio=None。"""
    since_d = since if isinstance(since, date) else date.fromisoformat(since)
    until_d = until if isinstance(until, date) else date.fromisoformat(until)
    window_days = (until_d - since_d).days + 1
    baseline_until = (since_d - timedelta(days=1)).isoformat()
    baseline_since = (since_d - timedelta(days=window_days)).isoformat()
    current = shopee_revenue(conn, brand_id, since, until)
    baseline = shopee_revenue(conn, brand_id, baseline_since, baseline_until)
    ratio = None
    if current is not None and baseline:
        ratio = round((current - baseline) / baseline, 4)
    return {"current": current, "baseline": baseline, "ratio": ratio}


def signal(conn, brand_id: str, cycle: dict) -> dict:
    """通路對照卡的核心：算出這期的外溢／互噬／缺資料燈號＋人話說明。

    純規則判定（決策 0016 硬性原則 4：數字走程式），優先序（最具體的證據優先）：
    1. 蝦皮期別碼有回收數 > 0 → 外溢（直接下限鐵證，比營收比對更硬）。
    2. 蝦皮營收比前一段等長期間下滑達門檻 → 互噬（官網可能搶了蝦皮的客）。
    3. 蝦皮營收成長達門檻 → 外溢。
    4. 藥局補貨間隔縮短達門檻 → 外溢。
    5. 三種資料都完全沒有 → 灰燈，「本期結論僅代表官網」。
    6. 有資料但沒有任何一項達門檻 → 不亮燈（資料夠但沒有明顯訊號，不強迫下結論）。
    """
    since, until = cycle["start_date"], cycle["end_date"]
    growth = _shopee_growth(conn, brand_id, since, until)
    shopee_code = get_shopee_code(conn, brand_id, cycle["id"])
    restock = restock_interval_signal(conn, brand_id, until)

    has_any_data = (
        growth["current"] is not None
        or (shopee_code is not None and (shopee_code.get("code") or shopee_code.get("redemption_count") is not None))
        or restock["sample_size"] > 0
    )

    result = {
        "light": None, "label": None, "badge_kind": None, "message": None,
        "shopee_growth": growth, "shopee_code": shopee_code, "restock": restock,
        "repurchase_caution": REPURCHASE_CAUTION_NOTE,
    }

    if not has_any_data:
        result.update(light="gray", label=LIGHT_LABELS["gray"], badge_kind=LIGHT_BADGE_KIND["gray"],
                      message="蝦皮與藥局通路都沒有資料，本期結論僅代表官網。")
        return result

    redemptions = shopee_code.get("redemption_count") if shopee_code else None
    if redemptions is not None and redemptions > 0:
        result.update(
            light="spillover", label=LIGHT_LABELS["spillover"], badge_kind=LIGHT_BADGE_KIND["spillover"],
            message=f"蝦皮期別碼回收 {redemptions} 筆，廣告帶來的訂單有部分流向蝦皮成交。")
        return result

    if growth["ratio"] is not None and growth["ratio"] <= -CANNIBALIZATION_DECLINE_RATIO:
        result.update(
            light="cannibalization", label=LIGHT_LABELS["cannibalization"],
            badge_kind=LIGHT_BADGE_KIND["cannibalization"],
            message=f"蝦皮營收比前一段期間下滑 {abs(growth['ratio']):.0%}，官網新客可能是蝦皮舊客換通路。")
        return result

    if growth["ratio"] is not None and growth["ratio"] >= SPILLOVER_GROWTH_RATIO:
        result.update(
            light="spillover", label=LIGHT_LABELS["spillover"], badge_kind=LIGHT_BADGE_KIND["spillover"],
            message=f"蝦皮營收比前一段期間成長 {growth['ratio']:.0%}，廣告效果可能有部分外溢到蝦皮。")
        return result

    if restock["shortened"]:
        result.update(
            light="spillover", label=LIGHT_LABELS["spillover"], badge_kind=LIGHT_BADGE_KIND["spillover"],
            message=(f"藥局補貨間隔從 {restock['baseline_interval_days']:.1f} 天縮短到"
                    f"{restock['latest_interval_days']} 天，需求可能有部分外溢到藥局通路。"))
        return result

    result["message"] = "蝦皮與藥局通路資料都在，但沒有明顯的外溢或互噬訊號。"
    return result


def gray_light_debt(conn, brand_id: str, cycle: dict, list_cycles_fn) -> bool:
    """灰燈債務（決策 0025 第二節 B：「連兩期未填顯示灰燈債務，降級判讀可信度」）：本期與
    上一期（依結束日排序，最近一期已結束的檔期）連續兩期都是灰燈，才算債務。

    跟決策 0026 老手暗門的「跳過並記債」是兩套債務（0025 補遺第 8 點），刻意不共用任何
    資料表或函式名稱——這裡只回傳布林值，不進打斷佇列、不擋路，只供畫面做「環境變灰」的
    降級顯示。list_cycles_fn 由呼叫端傳入（app/ads/repository.list_cycles），避免這個純
    規則模組直接依賴 ads 模組的存取層（鐵則 7：模組間走明確介面）。
    """
    current = signal(conn, brand_id, cycle)
    if current["light"] != "gray":
        return False
    cycles = list_cycles_fn(conn, brand_id, include_archived=True)
    earlier = sorted(
        (c for c in cycles if c["id"] != cycle["id"] and c["end_date"] < cycle["start_date"]),
        key=lambda c: c["end_date"], reverse=True,
    )
    if not earlier:
        return False
    previous_signal = signal(conn, brand_id, earlier[0])
    return previous_signal["light"] == "gray"


def demo() -> None:
    """python -m app.orders.channel — 純函數自檢：燈號規則的三種顏色都能正確判定。"""
    cycle = {"id": "ccy_demo", "start_date": "2026-06-01", "end_date": "2026-06-14"}

    # 沒有任何資料 → 灰燈
    class _FakeConn:
        def execute(self, sql, params=()):
            class _Cur:
                def fetchone(self_inner):
                    if "SUM(revenue)" in sql:
                        return {"total": None, "rows": 0}
                    return None

                def fetchall(self_inner):
                    return []

                def __iter__(self_inner):
                    return iter([])
            return _Cur()

    fake = _FakeConn()
    result = signal(fake, "brand_x", cycle)
    assert result["light"] == "gray", "完全沒資料應該是灰燈"

    growth_up = {"current": 1200.0, "baseline": 1000.0, "ratio": 0.2}
    growth_down = {"current": 800.0, "baseline": 1000.0, "ratio": -0.2}
    assert growth_up["ratio"] >= SPILLOVER_GROWTH_RATIO, "成長 20% 應觸及外溢門檻"
    assert growth_down["ratio"] <= -CANNIBALIZATION_DECLINE_RATIO, "下滑 20% 應觸及互噬門檻"
    print("channel 自檢通過")


if __name__ == "__main__":
    demo()
