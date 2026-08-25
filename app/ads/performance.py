# -*- coding: utf-8 -*-
"""app/ads/performance.py — 成效資料的匯入與 KPI 計算（票 10）。

決策 0016 硬性原則 2：手動貼 CSV 與 Meta 唯讀 API 兩軌都要通，**兩軌正規化為同一內部
格式，下游只認這一種格式**。那個格式就是 `performance_snapshot` 的正規化欄位
（impressions／clicks／spend／conversions／revenue）——API 軌在 app/ads/sync.py 寫入，
CSV 與手動輸入在這裡寫入，判讀（票 12）只讀這幾個欄位，不碰 raw_json。

CSV 解析的原則：**認概念欄，不認檔案格式**。Meta 匯出的欄位名會隨介面語言、
帳號設定與改版而不同，所以用一張別名表去對，而不是寫死欄位順序。認不出必要欄位時
不猜、不硬塞，直接告訴使用者檔案裡實際有哪些欄位——讓人看得懂問題出在哪（鐵則 16）。

⚠ 目前的別名表是照 Meta 官方文件與常見匯出格式寫的，**尚未用真實匯出檔驗證過**
（鐵則 11：假資料全過≠擋得住真實格式）。使用者提供真實檔後要再校準一次。
"""

import csv
import io
from dataclasses import dataclass, field
from typing import Optional

from app.ads import guardrails
from app.core.audit import write_audit
from app.core.db import new_id, now_utc, jsonb, DEV_ORG_ID

# 概念欄 → 可能的欄位名（全部小寫比對，去空白）。要加新別名就加在這裡，別動解析邏輯。
COLUMN_ALIASES = {
    "campaign_name": ["行銷活動名稱", "campaign name", "campaign_name", "活動名稱"],
    "adset_name": ["廣告組合名稱", "ad set name", "adset name", "廣告組名稱"],
    "ad_name": ["廣告名稱", "ad name", "ad_name"],
    "date_start": ["報告開始", "reporting starts", "date start", "開始日期", "day", "日期",
                   "分析報告開始"],
    "date_stop": ["報告結束", "reporting ends", "date stop", "結束日期", "分析報告結束"],
    "impressions": ["曝光次數", "impressions", "曝光數"],
    "clicks": ["連結點擊次數", "link clicks", "點擊次數（全部）", "點擊次數(全部)",
               "clicks (all)", "clicks", "點擊次數"],
    "spend": ["花費金額", "amount spent", "spend", "花費", "已花費金額"],
    "conversions": ["購買次數", "purchases", "results", "成果", "轉換次數", "conversions"],
    "revenue": ["購買轉換價值", "purchases conversion value", "conversion value",
                "轉換價值", "營收"],
    # 有些 Meta 匯出樣板不給實際營收欄，只給算好的比值欄（issue #23 追加：真實檔驗證回饋）。
    # 匯入層用它反推 revenue，不進正規化欄位——見 import_rows 的 _derive_revenue_from_roas。
    "roas_direct": ["成果 roas", "purchase roas", "roas"],
    "frequency": ["頻率", "frequency", "曝光頻率"],  # 素材疲勞判定要用（票 9）
    # 觸及（reach）：跟曝光（impressions）是兩個不同概念——曝光數含重複看到同一人，
    # 觸及數是不重複人數。Meta 匯出的正式欄位是「觸及人數」；「觸及次數」是常見口語變體，
    # 舊版曾誤把它列進 impressions 別名，會把觸及資料搶去當曝光算（票 03-add-reach-metric）。
    "reach": ["觸及人數", "觸及次數", "觸及", "reach", "people reached"],
}

REQUIRED_COLUMNS = ["spend"]  # 沒有花費就完全沒得判讀；其餘缺了還能用

MANUAL_FIELDS = ["impressions", "clicks", "spend", "conversions", "revenue", "reach"]


@dataclass
class ImportResult:
    imported: int = 0
    quarantined: int = 0
    skipped: int = 0
    matched_assets: int = 0  # 修憲落地 G2：這批裡有幾列靠廣告名稱對回素材（其餘誠實降級成檔期層）
    errors: list = field(default_factory=list)
    unmatched_columns: list = field(default_factory=list)
    found_columns: list = field(default_factory=list)


def _norm(name: str) -> str:
    return (name or "").strip().lower().replace(" ", "").replace("　", "")


def match_columns(headers: list, aliases_table: Optional[dict] = None) -> tuple:
    """檔案表頭 → {概念欄: 實際欄名}，外加沒對上的欄位清單。

    兩階段比對（issue #23 bug 1）：先讓**所有**概念欄跑一輪「完全相等」，
    剩下沒中的概念欄才跑第二輪「前綴」比對。單階段寬鬆比對會讓「成果類型」（文字欄，
    前綴含「成果」）搶在「成果」（真正的轉換數字欄）之前被 conversions 配走——
    完全相等優先，才不會被更長、只是恰好同前綴的欄名截胡。
    已配對的實際欄位一律排除，不會被下一個概念欄重複配。

    aliases_table 省略時用本檔的 Meta 廣告欄位表（COLUMN_ALIASES）；其他來源格式
    （例如 app/orders/importer.py 的 EasyStore 訂單欄位）傳自己的別名表進來，
    共用同一套兩階段比對演算法，不重寫比對邏輯（issue #33 分派層）。
    """
    aliases_table = aliases_table if aliases_table is not None else COLUMN_ALIASES
    mapping, used = {}, set()
    normalised = [(h, _norm(h)) for h in headers]

    def _match_pass(is_hit):
        for concept, aliases in aliases_table.items():
            if concept in mapping:
                continue
            for alias in aliases:
                target = _norm(alias)
                hit = next((original for original, norm_header in normalised
                            if original not in used and is_hit(norm_header, target)), None)
                if hit is not None:
                    mapping[concept] = hit
                    used.add(hit)
                    break

    _match_pass(lambda norm_header, target: norm_header == target)          # 第一輪：完全相等
    _match_pass(lambda norm_header, target: norm_header.startswith(target))  # 第二輪：前綴

    unmatched = [h for h in headers if h not in used]
    return mapping, unmatched


def to_number(raw, cast=float):
    """把 CSV／xlsx 的數字字串轉成數字。容忍千分位逗號、幣別符號、空字串。

    公開函式（原 _to_number）：app/orders/importer.py 的 EasyStore 欄位解析共用
    同一套數字容錯規則，不重寫一份。
    """
    if raw is None:
        return None
    text = str(raw).strip().replace(",", "").replace("$", "").replace("NT", "")
    if not text or text in ("-", "--"):
        return None
    try:
        return cast(float(text))
    except ValueError:
        return None


def dedupe_headers(headers: list) -> list:
    """重複欄名防禦（issue #23 bug 5）：Meta 匯出檔曾出現「廣告組合名稱」欄位重複兩次。

    csv.DictReader 組列時用欄名當 key，同名欄位後面會蓋掉前面，其中一欄的資料會
    整批消失、比對也可能認錯欄。這裡在讀資料列之前把重複的欄名加上序號分開
    （第二次出現變成「廣告組合名稱 (2)」），讓每一欄都留得住、配得到。
    """
    seen: dict = {}
    result = []
    for h in headers:
        seen[h] = seen.get(h, 0) + 1
        result.append(h if seen[h] == 1 else f"{h} ({seen[h]})")
    return result


def parse_csv(text: str) -> tuple:
    """CSV 文字 → (資料列, ImportResult 的初步結果)。不碰資料庫。"""
    result = ImportResult()
    if not text or not text.strip():
        result.errors.append("檔案是空的，沒有東西可以匯入。")
        return [], result

    # Excel 存的 CSV 常帶 BOM，不去掉的話第一個欄位名會多一個看不見的字元
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    headers = reader.fieldnames or []
    if not headers:
        result.errors.append("讀不出這個檔案的欄位名稱，確認一下是不是 CSV 檔。")
        return [], result
    headers = dedupe_headers(headers)
    reader.fieldnames = headers  # 逐列讀取也要用去重後的欄名，不然還是會撞名蓋資料

    mapping, unmatched = match_columns(headers)
    result.found_columns = headers
    result.unmatched_columns = unmatched

    missing = [c for c in REQUIRED_COLUMNS if c not in mapping]
    if missing:
        result.errors.append(
            "這個檔案裡找不到「花費」欄位，沒有花費就沒辦法判讀成效。"
            f"檔案裡有的欄位是：{'、'.join(headers[:12])}"
            + ("……" if len(headers) > 12 else "")
        )
        return [], result

    rows = []
    for line_no, raw_row in enumerate(reader, start=2):
        row = {"line_no": line_no}
        for concept, column in mapping.items():
            value = raw_row.get(column)
            if concept in ("impressions", "clicks", "reach"):
                row[concept] = to_number(value, int)
            elif concept in ("spend", "conversions", "revenue", "frequency", "roas_direct"):
                row[concept] = to_number(value)
            else:
                row[concept] = (value or "").strip() or None
        if row.get("spend") is None and not row.get("campaign_name"):
            continue  # 匯出檔常有空白行或總計列，跳過不報錯
        rows.append(row)

    if not rows:
        result.errors.append("檔案讀得懂，但裡面沒有任何一列成效資料。")
    return rows, result


def _derive_revenue_from_roas(row: dict) -> bool:
    """revenue 缺、但有算好的「成果 ROAS」（roas_direct）欄時，反推 revenue（就地修改）。

    revenue = roas_direct × spend 是 Meta 算 ROAS 的精確逆運算，不是估計。
    有實際 revenue 欄一律優先，不覆蓋；roas_direct 也沒有值的列維持 revenue=None，
    誠實顯示「不知道」，不硬塞 0（issue #23 追加：真實檔驗證回饋；鐵則 16）。

    回傳這一列的 revenue 是不是這次反推出來的（issue #36：灌水係數要能區分反推列與
    原始欄位列，回傳值供 import_rows 落地 revenue_source 標記用）。
    """
    if (row.get("revenue") is None and row.get("roas_direct") is not None
            and row.get("spend") is not None):
        row["revenue"] = row["roas_direct"] * row["spend"]
        return True
    return False


def _revenue_source(row: dict, derived: bool) -> Optional[str]:
    """revenue 來源標記：'reported' 原始欄位／'roas_derived' 反推／revenue 本身沒有值就沒有來源。"""
    if row.get("revenue") is None:
        return None
    return "roas_derived" if derived else "reported"


def match_asset_mapping(conn, brand_id: str, cycle_id: Optional[str],
                        ad_name: Optional[str]) -> tuple:
    """CSV「廣告名稱」欄 → 素材層歸屬（修憲落地 G2，決策 0035 第二節第 4 點）。
    廣告名稱是我們自己在 app/ads/handoff.py build_names() 產生的固定格式，同一檔期內唯一，
    所以拿 CSV 匯出的原始字串做「完全相等」比對就夠，不做模糊猜測（決策 0022 第 7 點）。
    回傳 (external_ad_mapping_id, publishing_package_id)：後者是票 11 D3 產品歸因要用的
    （見 resolve_product_id）——package 只要名稱對得上就回傳，不需要等關卡三具名授權；
    mapping_id 才需要 external_ad_mapping 已存在。對不上兩者皆回 None，呼叫端誠實降級。
    """
    ad_name = (ad_name or "").strip()
    if not cycle_id or not ad_name:
        return None, None
    packages = conn.execute(
        "SELECT id FROM publishing_package WHERE brand_id = %s AND campaign_cycle_id = %s"
        " AND ad_name = %s", (brand_id, cycle_id, ad_name),
    ).fetchall()
    if len(packages) != 1:
        return None, None  # 對不上，或者（不該發生的）撞名，一律不猜
    package_id = packages[0]["id"]
    mapping = conn.execute(
        "SELECT id FROM external_ad_mapping WHERE publishing_package_id = %s"
        " ORDER BY created_at DESC LIMIT 1", (package_id,),
    ).fetchone()
    return (mapping["id"] if mapping else None), package_id


def resolve_product_id(conn, brand_id: str, cycle_id: Optional[str],
                       publishing_package_id: Optional[str] = None) -> Optional[str]:
    """票 11 D3：這筆成效歸屬哪個產品，只在能確定時才填，模稜兩可一律 None（鐵則 16）。
    CSV／Meta 同步／模擬三個寫入口共用這份解析順序，不各寫一套。命中就停：
      a. 對到的 publishing_package 自己標的 product_id
      b. 否則看那個 package 掛的 experiment_cell 的 product_id
      c. 都不行，回 None
    （原本還有「檔期剛好只賣一個產品就算那個的」一條，複審拿掉了：規格要解決的是
    「一期賣兩個產品時分不出誰拖累」，這條路只在單一產品檔期觸發，對此毫無幫助，
    卻會讓 reading.py 的 per_product 分支多長出一條跟檔期層重複的結論。）
    品牌層（cycle_id 為 None）沒有檔期可查，直接回 None。
    """
    if not cycle_id or not publishing_package_id:
        return None
    package = conn.execute(
        "SELECT product_id, experiment_cell_id FROM publishing_package WHERE id = %s",
        (publishing_package_id,),
    ).fetchone()
    if not package:
        return None
    if package["product_id"]:
        return package["product_id"]
    if package["experiment_cell_id"]:
        cell = conn.execute(
            "SELECT product_id FROM experiment_cell WHERE id = %s",
            (package["experiment_cell_id"],),
        ).fetchone()
        if cell and cell["product_id"]:
            return cell["product_id"]
    return None


def _row_identity(row: dict) -> str:
    """廣告名稱＋活動名稱＋廣告組合名稱，解析器有給哪個算哪個（票 11 blocker 1）。
    剛匯入的列跟從 raw_json 讀回來的舊列都呼叫這支，兩邊才算得出一致的簽章——
    舊版拿 LEFT JOIN 反查名稱，沒對上素材的列全部塌成空字串，兩支還沒出量、
    數字剛好都是 0 的不同廣告會被誤判成同一列，第二支靜默丟掉。"""
    return "|".join((row.get(field) or "").strip()
                    for field in ("ad_name", "campaign_name", "adset_name"))


def _duplicate_signature(row: dict, date_start: str, date_stop: str, source: str,
                         currency: str, ad_identity: str = "") -> tuple:
    """匯入去重判斷依據的共用建構子（票 11）：日期範圍＋全部量測欄＋來源＋幣別完全
    相同，視為同一列重複匯入（issue #68 訂的品牌層判斷依據）。ad_identity 品牌層
    （cycle_id 為 None）留空——一列就是整個品牌的加總；檔期層填 `_row_identity`
    算出來的廣告身分（澄清 1）。"""
    return (date_start, date_stop, row.get("impressions"), row.get("clicks"),
            row.get("spend"), row.get("conversions"), row.get("revenue"),
            row.get("frequency"), row.get("reach"), source, currency, ad_identity)


def _existing_signatures(conn, brand_id: str, cycle_id: Optional[str]) -> set:
    """讀回這個範圍已入庫的快照，重建成跟 `_duplicate_signature` 同一組判斷依據。
    檔期層 ad_identity 從 raw_json 讀回原始列餵給 `_row_identity`（票 11 blocker 1：
    不再靠 external_ad_mapping LEFT JOIN 反查，那條路沒對上素材的列全塌成空字串）。
    raw_json 是 NULL 的舊列（D4 不回填）身分項留空——不知道就是不知道，不能猜。"""
    cols = ("date_range_start, date_range_end, impressions, clicks, spend, conversions,"
           " revenue, frequency, reach, source, currency")
    if cycle_id is None:
        query = f"SELECT {cols} FROM performance_snapshot WHERE brand_id = %s AND campaign_cycle_id IS NULL"
        params = (brand_id,)
    else:
        query = f"SELECT {cols}, raw_json FROM performance_snapshot WHERE brand_id = %s AND campaign_cycle_id = %s"
        params = (brand_id, cycle_id)
    signatures = set()
    for r in conn.execute(query, params):
        ad_identity = ("" if cycle_id is None else
                      _row_identity(r["raw_json"] or {}))
        signatures.add((r["date_range_start"], r["date_range_end"], r["impressions"],
                        r["clicks"], r["spend"], r["conversions"], r["revenue"],
                        r["frequency"], r["reach"], r["source"], r["currency"], ad_identity))
    return signatures


def import_rows(conn, brand_id: str, cycle_id: Optional[str], rows: list, *,
                source: str, actor: str, result: Optional[ImportResult] = None,
                today: Optional[str] = None, currency: str = "TWD") -> ImportResult:
    """把解析好的列寫成 performance_snapshot（只累積、不覆寫）。

    每一列先過合理性海關；命中的照樣入庫但標記隔離，判讀不會讀到它——
    壞資料要看得到（才知道匯錯檔），但不能污染結論。

    內容去重（票 11 擴大到檔期層，原本只有品牌層——issue #68）：判斷依據共用
    `_duplicate_signature`，身分項用 `_row_identity`。manual 走同一套判斷，不豁免——
    manual 沒有廣告名稱等身分欄位可填，ad_identity 留空，誠實的剩餘缺口是：同一天
    手動填兩筆數字剛好相同的「不同」資料（例如兩個廣告帳號各自手動填、剛好同一天
    同樣數字）會被誤判成重複而跳過。緩解不是猜身分，是讓畫面把 skipped 秀出來
    （票 11 D2）——使用者一看到「跳過了幾筆」就知道要改日期或數字，不會被靜默吃掉。
    """
    result = result or ImportResult()
    ts = now_utc()
    batch_id = f"import_{ts}"

    seen_signatures = _existing_signatures(conn, brand_id, cycle_id)

    for row in rows:
        derived = _derive_revenue_from_roas(row)
        revenue_source = _revenue_source(row, derived)

        date_start = row.get("date_start") or row.get("date_stop") or (today or "")
        date_stop = row.get("date_stop") or date_start

        ad_identity = _row_identity(row) if cycle_id else ""
        signature = _duplicate_signature(row, date_start, date_stop, source, currency,
                                         ad_identity)
        if signature in seen_signatures:
            result.skipped += 1
            continue
        seen_signatures.add(signature)

        sanity = guardrails.check_data_sanity(row, today=today)
        quarantined = bool(sanity)
        if quarantined:
            result.quarantined += 1

        # 修憲落地 G2：廣告名稱欄對得回已授權的素材才寫 external_ad_mapping_id，對不上就留空
        mapping_id, package_id = match_asset_mapping(conn, brand_id, cycle_id, row.get("ad_name"))
        if mapping_id:
            result.matched_assets += 1
        product_id = resolve_product_id(conn, brand_id, cycle_id, package_id)
        # 票 11：raw_json 存這一列解析後的原始內容——去重判斷回頭讀它算 ad_identity
        # （見 _existing_signatures），line_no 只是解析時的行號，不是資料本身，不存。
        raw_json = {k: v for k, v in row.items() if k != "line_no"}

        conn.execute(
            "INSERT INTO performance_snapshot (id, org_id, brand_id, campaign_cycle_id, product_id,"
            " external_ad_mapping_id, platform, meta_campaign_id, meta_adset_id, meta_ad_id,"
            " date_range_start, date_range_end, as_of_date, snapshot_taken_at, currency,"
            " impressions, clicks, spend, conversions, revenue, revenue_source, frequency,"
            " reach, raw_json, reconciled, source, import_batch_id, quarantined,"
            " quarantine_reason, created_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, 'meta', NULL, NULL, NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
            " %s, %s, %s, true, %s, %s, %s, %s, %s)",
            (new_id("psn"), DEV_ORG_ID, brand_id, cycle_id, product_id, mapping_id, date_start, date_stop,
             date_stop, ts, currency, row.get("impressions"), row.get("clicks"),
             row.get("spend"), row.get("conversions"), row.get("revenue"), revenue_source,
             row.get("frequency"), row.get("reach"), jsonb(raw_json), source, batch_id,
             quarantined, "；".join(f.message for f in sanity) or None, ts),
        )
        result.imported += 1

    write_audit(conn, brand_id=brand_id, entity_type="campaign_cycle",
                entity_id=cycle_id or brand_id, action="import_performance", actor=actor,
                before=None, after={"source": source, "imported": result.imported,
                                    "quarantined": result.quarantined,
                                    "skipped_duplicate": result.skipped})
    conn.commit()
    return result


def import_csv(conn, brand_id: str, cycle_id: Optional[str], text: str, *, actor: str,
               today: Optional[str] = None) -> ImportResult:
    rows, result = parse_csv(text)
    if result.errors:
        return result
    return import_rows(conn, brand_id, cycle_id, rows, source="csv", actor=actor,
                       result=result, today=today)


def import_manual(conn, brand_id: str, cycle_id: str, values: dict, *, actor: str,
                  today: Optional[str] = None) -> ImportResult:
    """手動輸入一列。API 掛掉、CSV 也匯不進來時的最後退路。"""
    row = {key: values.get(key) for key in MANUAL_FIELDS}
    row["date_start"] = values.get("date_start")
    row["date_stop"] = values.get("date_stop") or values.get("date_start")
    if row.get("spend") is None:
        result = ImportResult()
        result.errors.append("至少要填花費金額，不然沒辦法判讀。")
        return result
    return import_rows(conn, brand_id, cycle_id, [row], source="manual", actor=actor,
                       today=today)


# ---------------------------------------------------------------------------
# 彙總與 KPI（確定性計算，不經 LLM）
# ---------------------------------------------------------------------------

def _cycle_rows_for_totals(conn, brand_id: str, cycle_id: str,
                           include_quarantined: bool) -> list:
    """日粒度上線後，較細的 Meta 日列取代同一廣告、同期間的舊聚合列。"""
    sql = ("SELECT * FROM performance_snapshot WHERE brand_id = %s"
           " AND campaign_cycle_id = %s")
    if not include_quarantined:
        sql += " AND quarantined = false"
    rows = [dict(row) for row in conn.execute(sql, (brand_id, cycle_id))]
    daily_dates: dict = {}
    for row in rows:
        if (row["source"] != "meta_api" or row["date_range_start"] != row["date_range_end"]
                or not row.get("meta_campaign_id")):
            continue
        identity = (row.get("account_id"), row["meta_campaign_id"], row.get("meta_adset_id"),
                    row.get("meta_ad_id"))
        daily_dates.setdefault(identity, set()).add(row["date_range_start"])

    def superseded(row: dict) -> bool:
        if (row["source"] != "meta_api" or row["date_range_start"] == row["date_range_end"]
                or not row.get("meta_campaign_id")):
            return False
        identity = (row.get("account_id"), row["meta_campaign_id"], row.get("meta_adset_id"),
                    row.get("meta_ad_id"))
        return any(row["date_range_start"] <= day <= row["date_range_end"]
                   for day in daily_dates.get(identity, ()))

    return [row for row in rows if not superseded(row)]


def totals(conn, brand_id: str, cycle_id: str, include_quarantined: bool = False) -> dict:
    """本期成效加總。預設**不含**隔離區的資料——壞數字不進結論。"""
    # revenue 額外多算一份不 COALESCE 的版本（revenue_raw）只給 KPI 用：COALESCE 過的 0
    # 分不出「營收確實是 0」跟「這期完全沒收集營收資料」，後者要讓 roas 回 None，
    # 不能悄悄算成 0（issue #23 bug 2；鐵則 16）。顯示用的 revenue 欄位維持 COALESCE，
    # 不然沒收營收資料時模板格式化 None 會直接炸掉。
    rows = _cycle_rows_for_totals(conn, brand_id, cycle_id, include_quarantined)
    revenue_values = [r["revenue"] for r in rows if r["revenue"] is not None]
    row = {
        "impressions": sum(r["impressions"] or 0 for r in rows),
        "clicks": sum(r["clicks"] or 0 for r in rows),
        "spend": sum(r["spend"] or 0 for r in rows),
        "conversions": sum(r["conversions"] or 0 for r in rows),
        "revenue": sum(revenue_values),
        "reach": sum(r["reach"] or 0 for r in rows),
        "rows": len(rows),
    }
    revenue_raw = sum(revenue_values) if revenue_values else None
    row["kpis"] = compute_kpis({**row, "revenue": revenue_raw})
    return row


def revenue_by_source(conn, brand_id: str, cycle_id: str) -> dict:
    """本期 Meta 自報營收依來源標記拆開（issue #36：灌水係數要能區分反推列）。

    只算未隔離的列，跟 totals() 同一個範圍。'unknown' 是既有列回填（見 migration 0010），
    當初沒存 raw_json，事後無法分辨原始欄位還是反推值。"""
    rows = conn.execute(
        "SELECT COALESCE(revenue_source, 'unknown') src, COALESCE(SUM(revenue), 0) amount"
        " FROM performance_snapshot WHERE brand_id = %s AND campaign_cycle_id = %s AND"
        " quarantined = false AND revenue IS NOT NULL GROUP BY src",
        (brand_id, cycle_id),
    ).fetchall()
    out = {"reported": 0.0, "roas_derived": 0.0, "unknown": 0.0}
    for row in rows:
        out[row["src"]] = row["amount"]
    out["total"] = round(sum(out.values()), 2)
    return out


def max_frequency(conn, brand_id: str, cycle_id: str) -> Optional[float]:
    """這期目前收到的最高頻率（票 9：素材疲勞判定用）。取最大值而不是平均——

    看最嚴重的那一筆，不能讓平均把警訊稀釋掉。沒有任何一筆帶頻率資料時回 None，
    不假裝算得出來（鐵則 16）。"""
    row = conn.execute(
        "SELECT MAX(frequency) freq FROM performance_snapshot"
        " WHERE brand_id = %s AND campaign_cycle_id = %s AND quarantined = false",
        (brand_id, cycle_id),
    ).fetchone()
    return row["freq"] if row and row["freq"] is not None else None


def total_reach(conn, brand_id: str, cycle_id: str) -> Optional[int]:
    """這期目前收到的觸及加總（漏斗上層主指標，票 03-add-reach-metric）。沒有任何一筆
    帶觸及資料時回 None，不假裝算得出來（鐵則 16；比照 max_frequency 的既有寫法）。"""
    row = conn.execute(
        "SELECT SUM(reach) reach FROM performance_snapshot"
        " WHERE brand_id = %s AND campaign_cycle_id = %s AND quarantined = false",
        (brand_id, cycle_id),
    ).fetchone()
    return row["reach"] if row and row["reach"] is not None else None


def compute_kpis(totals_row: dict) -> dict:
    """CTR／CPC／CPA／ROAS。分母為 0 時回 None，不回 0——「沒得算」跟「等於 0」是兩件事。

    revenue 是 None（完全沒收集到營收資料）時 roas 也回 None，跟 revenue 明確是 0
    （有回填，就是沒賺）分開看待——前者是「不知道」，後者是「知道是 0」，
    混在一起會讓人誤以為廣告確定沒帶來營收（issue #23 bug 2；鐵則 16）。
    """
    impressions = totals_row.get("impressions") or 0
    clicks = totals_row.get("clicks") or 0
    spend = totals_row.get("spend") or 0
    conversions = totals_row.get("conversions") or 0
    revenue = totals_row.get("revenue")
    roas = round(revenue / spend, 2) if (revenue is not None and spend) else None
    return {
        "ctr": round(clicks / impressions, 4) if impressions else None,
        "cpc": round(spend / clicks, 2) if clicks else None,
        "cpa": round(spend / conversions, 2) if conversions else None,
        "roas": roas,
        # 票 C2-01：瓶頸判斷樹拆 CPA 恆等式（CPA = CPM/1000 ÷ (CTR × CVR)）要用到這兩個。
        "cpm": round(spend / impressions * 1000, 2) if impressions else None,
        "cvr": round(conversions / clicks, 4) if clicks else None,
    }


def save_derived_metrics(conn, brand_id: str, cycle_id: str) -> int:
    """把算出來的 KPI 落地成 derived_metric（判讀要回溯「當時算出來的數字」）。"""
    summary = totals(conn, brand_id, cycle_id)
    snapshot = conn.execute(
        "SELECT id FROM performance_snapshot WHERE brand_id = %s AND campaign_cycle_id = %s"
        " AND quarantined = false ORDER BY created_at DESC LIMIT 1", (brand_id, cycle_id),
    ).fetchone()
    if snapshot is None:
        return 0

    ts = now_utc()
    conn.execute(
        "DELETE FROM derived_metric WHERE brand_id = %s AND campaign_cycle_id = %s",
        (brand_id, cycle_id),
    )
    written = 0
    for metric, value in summary["kpis"].items():
        if value is None:
            continue
        conn.execute(
            "INSERT INTO derived_metric (id, org_id, brand_id, performance_snapshot_id,"
            " campaign_cycle_id, metric, value, calc_basis, computed_at, created_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (new_id("dmt"), DEV_ORG_ID, brand_id, snapshot["id"], cycle_id, metric, value,
             "本期未隔離資料加總", ts, ts),
        )
        written += 1
    conn.commit()
    return written


# ---------------------------------------------------------------------------
# 品牌層（無檔期）歷史——舊廣告認領、CSV 對不到檔期的列（決策 0039 第 7、8、10 條）
# ---------------------------------------------------------------------------

def _drop_superseded_cross_month_rows(rows: list) -> list:
    """跨月彙總列若已被同一支廣告的逐月回填覆蓋，排除該列（票 F13／issue #72）。

    根因：#70 把 sync_account() 改成逐月分開打 API 之後，之前（#70 之前）整段一次回填
    留下的跨月彙總列還留在資料庫裡（append-only，不刪舊資料）。使用者一重新回填，
    同一支廣告會多出涵蓋同一段期間的逐月列，兩者共存、`_brand_level_monthly_groups()`
    若照常全部加總，跨月列涵蓋的花費會跟新的逐月列重複算一次。

    判斷依據：account_id＋meta_campaign_id＋meta_adset_id＋meta_ad_id 相同＝同一支廣告；
    這支廣告底下如果已經有任何單月列（起訖同月）的日期落在跨月列的區間內，代表逐月資料
    已經涵蓋到這段期間，整列跨月彙總排除，不參與加總。只認有 meta_campaign_id 的 API
    來源列——CSV 匯入這幾欄本來就是 NULL，識別不到就不排除，寧可少排除也不誤刪 CSV
    資料（鐵則 16）。沒有相符逐月列時維持原樣，不影響 issue #70 既有的跨月列處理。"""
    monthly_spans: dict = {}
    for row in rows:
        if row["cross_month"] or not row.get("meta_campaign_id"):
            continue
        identity = (row.get("account_id"), row["meta_campaign_id"], row.get("meta_adset_id"),
                    row.get("meta_ad_id"))
        monthly_spans.setdefault(identity, []).append(row["date_range_start"])

    def _superseded(row) -> bool:
        if not row["cross_month"] or not row.get("meta_campaign_id"):
            return False
        identity = (row.get("account_id"), row["meta_campaign_id"], row.get("meta_adset_id"),
                    row.get("meta_ad_id"))
        starts = monthly_spans.get(identity) or []
        return any(row["date_range_start"] <= s <= row["date_range_end"] for s in starts)

    return [row for row in rows if not _superseded(row)]


def _brand_level_rows(conn, brand_id: str) -> list:
    """品牌層（campaign_cycle_id 為 NULL）未隔離成效列，已排除被同一支廣告逐月回填
    覆蓋的舊跨月彙總列（票 F13／issue #72）。`_brand_level_monthly_groups()`（點擊面
    中位數）與 `brand_level_totals()`（金額面參考總量）共用這份去重後的資料，不各寫
    一份加總、各自決定要不要排重複——兩處都會被同一顆跨月彙總列的重複計算問題影響。"""
    rows = [dict(r) for r in conn.execute(
        "SELECT id, date_range_start, date_range_end, impressions, clicks, spend, conversions,"
        " revenue, account_id, meta_campaign_id, meta_adset_id, meta_ad_id"
        " FROM performance_snapshot WHERE brand_id = %s AND campaign_cycle_id IS NULL"
        " AND quarantined = false ORDER BY created_at", (brand_id,),
    ).fetchall()]
    for row in rows:
        start_month = (row["date_range_start"] or "")[:7]  # YYYY-MM
        end_month = (row["date_range_end"] or "")[:7]
        row["cross_month"] = bool(start_month) and start_month != end_month
    return _drop_superseded_cross_month_rows(rows)


def _brand_level_monthly_groups(conn, brand_id: str) -> dict:
    """品牌層成效列依**資料期間**（date_range_start～date_range_end）所在月份分組——
    不是匯入時間，也不是任意的 as_of_date（issue #70：Meta 一次回填多個月若不逐月拆開
    索取，一整段時間範圍會壓成一列，用 as_of_date 分組會把橫跨多月的資料全部歸給資料期間
    最後一天所在的那個月，看起來像「只有一個月有資料」）。

    分組鍵＝資料期間的**末月**（這筆花費最終算在哪個月結算）。一列的起訖月不同（跨月彙總列，
    通常是舊資料一次性、未逐月拆分的回填）時標記 cross_month＝True，只算進末月這一組、
    不會同時出現在它涵蓋到的其他月份（鐵則 16：誠實、不重複計算）；
    `save_brand_level_derived_metrics()` 會在 calc_basis 裡誠實揭露這一組其實含跨月資料。
    已被同一支廣告的逐月列覆蓋的跨月列，`_brand_level_rows()` 已先排除，不進任何一組
    （票 F13：新月列與舊混合列並存不重複計算）。

    沒有可用日期的列跳過，不硬湊月份。"""
    grouped: dict = {}
    for row in _brand_level_rows(conn, brand_id):
        end_month = (row["date_range_end"] or "")[:7]
        if len(end_month) != 7:
            continue
        grouped.setdefault(end_month, []).append(row)
    return grouped


def save_brand_level_derived_metrics(conn, brand_id: str) -> int:
    """把品牌層（無檔期）舊廣告成效彙整成 derived_metric（決策 0039 第 7、8、10 條）。

    只寫點擊面三項指標（cpc／ctr／轉換率）；金額面（roas／revenue）不寫——Meta 自報營收
    未經對帳，不該混進 `reading.brand_baseline()` 的中位數（0022 第 1 點：Meta 自報＝線索）。
    參考用的 ROAS／營收見 `brand_level_totals()`。

    粒度＝每月一列：先依**資料期間**所在月份加總（見 `_brand_level_monthly_groups()`），
    再對每個月各算一次 KPI，避免同一批匯入（可能上百列原始資料）在中位數裡佔掉不成比例的
    權重（決策 0039 第 10 條）。calc_basis 標的月份＝資料月份，不是匯入當下的月份（issue #70）；
    組內若有跨月彙總列，calc_basis 會誠實列出那一列實際涵蓋的期間，不假裝是單月的乾淨數字。

    全量重算（先刪後寫）：呼叫端（認領後、CSV 匯入後、每次同步後）可以放心重複呼叫。
    """
    conn.execute(
        "DELETE FROM derived_metric WHERE brand_id = %s AND campaign_cycle_id IS NULL",
        (brand_id,),
    )
    groups = _brand_level_monthly_groups(conn, brand_id)
    ts = now_utc()
    written = 0
    for month, month_rows in groups.items():
        impressions = sum(r["impressions"] or 0 for r in month_rows)
        clicks = sum(r["clicks"] or 0 for r in month_rows)
        spend = sum(r["spend"] or 0 for r in month_rows)
        conversions = sum(r["conversions"] or 0 for r in month_rows)
        anchor_id = month_rows[-1]["id"]  # 任一代表列即可，外鍵只認存在性

        cross_rows = [r for r in month_rows if r.get("cross_month")]
        if cross_rows:
            spans = sorted({(r["date_range_start"], r["date_range_end"]) for r in cross_rows})
            span_note = "；".join(f"{s}~{e}" for s, e in spans)
            basis = (f"品牌層歷史（{month} 月加總，含跨月彙總列 {span_note}，"
                     "以資料期間末月歸屬、不重複計算，舊廣告或無檔期匯入，未對帳）")
        else:
            basis = f"品牌層歷史（{month} 月加總，舊廣告或無檔期匯入，未對帳）"

        metrics = {
            "cpc": round(spend / clicks, 2) if clicks else None,
            "ctr": round(clicks / impressions, 4) if impressions else None,
            "cvr": round(conversions / clicks, 4) if clicks else None,
        }
        for metric, value in metrics.items():
            if value is None:
                continue
            conn.execute(
                "INSERT INTO derived_metric (id, org_id, brand_id, performance_snapshot_id,"
                " campaign_cycle_id, metric, value, calc_basis, computed_at, created_at)"
                " VALUES (%s, %s, %s, %s, NULL, %s, %s, %s, %s, %s)",
                (new_id("dmt"), DEV_ORG_ID, brand_id, anchor_id, metric, value, basis, ts, ts),
            )
            written += 1
    conn.commit()
    return written


def brand_level_totals(conn, brand_id: str) -> dict:
    """品牌層（無檔期）成效加總，含 ROAS／營收供顯示參考（決策 0039 第 8 條：Meta 自報
    營收未對帳，畫面可看、標「未對帳參考值」，但不進 `save_brand_level_derived_metrics()`
    寫入的中位數基準）。用 `_brand_level_rows()` 去重後的資料加總，跟月度中位數同一份
    基礎資料、同樣排除被逐月回填覆蓋的舊跨月彙總列（票 F13：金額面參考值也不能重複計算）。
    """
    rows = _brand_level_rows(conn, brand_id)
    revenue_values = [r["revenue"] for r in rows if r["revenue"] is not None]
    revenue_raw = sum(revenue_values) if revenue_values else None
    row = {
        "impressions": sum(r["impressions"] or 0 for r in rows),
        "clicks": sum(r["clicks"] or 0 for r in rows),
        "spend": sum(r["spend"] or 0 for r in rows),
        "conversions": sum(r["conversions"] or 0 for r in rows),
        "revenue": revenue_raw or 0,
        "rows": len(rows),
    }
    row["kpis"] = compute_kpis({**row, "revenue": revenue_raw})
    clicks = row.get("clicks") or 0
    conversions = row.get("conversions") or 0
    row["kpis"]["cvr"] = round(conversions / clicks, 4) if clicks else None
    row["unreconciled_note"] = ("ROAS／營收是 Meta 自報且未對帳的參考值，只給看、"
                                "不計入品牌基準中位數（決策 0039 第 8 條）。")
    return row


# ---------------------------------------------------------------------------
# 駕駛艙 KPI（票 03-cockpit-kpi-chart）：橫跨所有檔期＋品牌層歷史的區間查詢，
# 給 app/dashboard/repository.py 當公開接縫用（接口鐵則：dashboard 只透過這裡取數，
# 不直接對 performance_snapshot／derived_metric 下 SQL）。
# ---------------------------------------------------------------------------

def brand_period_spend(conn, brand_id: str, since: str, until: str) -> Optional[float]:
    """指定區間的花費加總，不分檔期（規格 KPI 口徑：廣告花費＝成效快照 spend 加總）。

    依資料期間末日（date_range_end）落在區間內判斷歸屬，沿用 `_brand_level_monthly_groups()`
    「資料期間末月」的既有慣例。只算未隔離資料。區間內完全沒有資料列時回 None，
    不回 0——「沒得算」跟「花費確實是 0」是兩件事（鐵則 16）。
    """
    row = conn.execute(
        "SELECT SUM(spend) spend, COUNT(*) rows FROM performance_snapshot"
        " WHERE brand_id = %s AND quarantined = false"
        " AND date_range_end >= %s AND date_range_end <= %s",
        (brand_id, since, until),
    ).fetchone()
    return row["spend"] if row["rows"] else None


def last_snapshot_at(conn, brand_id: str) -> Optional[str]:
    """這個品牌最新一筆成效快照的抓取時間（snapshot_taken_at），給駕駛艙「最後同步
    時間」用（票 07-auto-sync）。從沒同步過時回 None——「還沒同步過」跟「同步時間是
    某個值」是兩件事（鐵則 16）。"""
    row = conn.execute(
        "SELECT MAX(snapshot_taken_at) AS ts FROM performance_snapshot WHERE brand_id = %s",
        (brand_id,),
    ).fetchone()
    return row["ts"] if row and row["ts"] else None


# delete_snapshots／list_snapshots 純搬去 performance_batches.py（票 S1-01：加 batch_id
# kwarg 會讓這檔破 800 行上限）。這裡留 re-export——既有呼叫端／測試全部認
# `perf.list_snapshots`／`ads_performance.delete_snapshots`，逐一改 import 的診斷成本
# 比一行 re-export 高，邏輯本身零改動（純搬，見 performance_batches.py 開頭說明）。
from app.ads.performance_batches import delete_snapshots, list_snapshots  # noqa: F401,E402
