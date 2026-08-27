# -*- coding: utf-8 -*-
"""app/ads/sync.py — Meta 唯讀同步與品牌歸屬認領（票 9）。

一個廣告帳號可以服務多個品牌（決策 0022 第 6 點），所以同步回來的每一個行銷活動
都必須先確定它屬於哪個品牌。做法（第 7 點）：

1. 同步時把帳號上看到的活動寫進 `discovered_campaign`——這張表**沒有 brand_id**，
   因為還沒認領的東西不屬於任何品牌。
2. 系統依命名規則猜一個歸屬，寫進 `suggested_brand_id`，但**只是預選，不生效**。
3. 使用者確認後才寫 `claimed_brand_id`，成效數字這時候才進得了那個品牌。

命名猜測靠得住的原因：交接包的命名是我們自己用固定格式產的（app/ads/handoff.py
build_names），所以反解得回來。使用者在 Meta 上手改名字，猜測就會落空——那正是
為什麼猜測不能直接生效、一定要人按一下。
"""

import calendar
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Optional

from app.ads import guardrails
from app.ads import handoff as ads_handoff
from app.ads import meta_api
from app.ads import performance as ads_performance
from app.ads import repository as ads_repo
from app.ads import theme_attribution
from app.ads import tracking
from app.brand_intelligence import repository as bi
from app.core import settings as coresettings
from app.core.audit import write_audit
from app.core.db import new_id, now_utc, jsonb, DEV_ORG_ID

TOKEN_SETTING = "meta_access_token"
ACCOUNT_SETTING = "meta_ad_account_id"

DEFAULT_LOOKBACK_DAYS = 30

# 決策 0039 第 3 條「回填一鍵 12 個月」：Meta 約 37 個月上限實作前查證官方文件，
# 不得憑記憶寫死。出處：Meta Business Help Center「關於 Meta 廣告分析報告」
# （https://www.facebook.com/business/help/1695754927158071）與 Meta for Developers
# Marketing API 文件同步公告——彙總（非 breakdown）欄位的歷史報表視窗自 2021-02-23 起
# 訂為 37 個月，逾期請求 Meta 是整批拒絕、不是悄悄少給，所以回填一定要「先夾住再問」。
META_MAX_HISTORY_MONTHS = 37


def months_before(until: str, months: int) -> str:
    """`until` 往回推 `months` 個日曆月（比照使用者理解的「N 個月前」，不是 30N 天的近似值）。

    ponytail: 用 stdlib calendar.monthrange 處理跨年與月底日期（例如 1/31 往回推一個月落在
    2 月，會夾到 2/28 或 2/29），不用第三方套件（沒有 dateutil 依賴）。
    """
    d = date.fromisoformat(until)
    total = d.year * 12 + (d.month - 1) - months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day).isoformat()


def _month_windows(since: str, until: str) -> list:
    """`[since, until]` 拆成逐月的 `(chunk_since, chunk_until)` 區間（issue #70 根因）：
    Meta `/insights` 沒指定 time_increment 時，一段 time_range 只會回**一列聚合資料**——
    一次回填 12 個月若整段一次問完，就會變成「一列扛 12 個月」，date_start/date_stop
    橫跨整段範圍，花費全部倒進資料期間最後一天所在的那個月，其餘月份完全看不到
    （品牌層月度分組見 `app/ads/performance.py` 的 `_brand_level_monthly_groups()`）。

    改成逐月各打一次 API，讓每一列 insight 的 date_start/date_stop 天然落在同一個
    日曆月內，月度分組才分得出真正的資料月份。"""
    start, end = date.fromisoformat(since), date.fromisoformat(until)
    windows = []
    cursor = start
    while cursor <= end:
        last_day = calendar.monthrange(cursor.year, cursor.month)[1]
        chunk_until = min(date(cursor.year, cursor.month, last_day), end)
        windows.append((cursor.isoformat(), chunk_until.isoformat()))
        cursor = chunk_until + timedelta(days=1)
    return windows


def backfill_range(requested_months: int, *, until: Optional[str] = None,
                    today: Optional[str] = None) -> tuple:
    """回填用的 (since, until, actual_months)：夾住 Meta 官方歷史上限，讓呼叫端能誠實顯示
    「實際拿到 N 個月」，不是每次都宣稱拿到當初要求的數字（決策 0039 第 3 條）。"""
    today = today or date.today().isoformat()
    until = until or today
    actual_months = min(requested_months, META_MAX_HISTORY_MONTHS)
    since = months_before(until, actual_months)
    return since, until, actual_months


def get_token(conn) -> Optional[str]:
    return coresettings.get_setting(conn, TOKEN_SETTING) or None


def get_account_id(conn) -> Optional[str]:
    return coresettings.get_setting(conn, ACCOUNT_SETTING) or None


def is_configured(conn) -> bool:
    return bool(get_token(conn) and get_account_id(conn))


def make_client(conn) -> meta_api.MetaClient:
    return meta_api.MetaClient(get_token(conn))


@dataclass
class SyncResult:
    discovered: int = 0        # 這次新看到的活動
    snapshots: int = 0         # 寫進來的成效列數
    quarantined: int = 0       # 數字不合理、進隔離區的列數
    skipped_unclaimed: int = 0  # 因為還沒認領歸屬而沒收的列數
    skipped_duplicate: int = 0  # 品牌層（無檔期）重複回填而略過的列數（issue #69）
    error: Optional[str] = None


def _sig_date(v):
    """date 物件（DB date 欄位讀回來）跟 ISO 字串（Meta API 回傳）統一轉字串再比對，
    型別不同會讓 tuple 永遠比不上（02-3c）。"""
    return v.isoformat() if hasattr(v, "isoformat") else v


def _sig_money(v):
    """Decimal（DB numeric 欄位）跟 float（Meta API 回傳）統一轉 float 再比對（02-3c）。"""
    return v if v is None else float(v)


def _duplicate_signature(account_external: str, insight) -> tuple:
    """成效的重複判斷依據（issue #69，比照 F9／issue #68 的思路）：帳號＋活動／組合／
    廣告 ID＋日期範圍＋全部量測欄完全相同，視為同一列重複回填。

    票 11：這組簽章原本只給品牌層（cycle_id 為 None）用，現在檔期層回填也共用同一套
    ——不必另外加「廣告身分」欄位，因為 insight.ad_id 從一開始就已經是簽章的一部分
    （一支 Meta 廣告的洞察報告天生帶著自己的廣告 ID），不會有 CSV 匯入那種「同一列
    分不出是哪支廣告」的問題。差別只在查詢既有簽章時的範圍（品牌層／某個檔期），
    見 `_existing_signatures`。"""
    return (account_external, insight.campaign_id, insight.adset_id, insight.ad_id,
            _sig_date(insight.date_start), _sig_date(insight.date_stop),
            insight.impressions, insight.clicks, _sig_money(insight.spend),
            insight.conversions, _sig_money(insight.revenue), insight.frequency,
            insight.reach)


def _existing_signatures(conn, brand_id: str, cycle_id: Optional[str]) -> set:
    """讀回這個範圍（品牌層或某個檔期）目前已入庫的快照，重建成跟 `_duplicate_signature`
    同一組判斷依據，供這次回填比對——品牌層與檔期層各自獨立比對，互不影響。"""
    if cycle_id is None:
        rows = conn.execute(
            "SELECT account_id, meta_campaign_id, meta_adset_id, meta_ad_id,"
            " date_range_start, date_range_end, impressions, clicks, spend, conversions,"
            " revenue, frequency, reach FROM performance_snapshot"
            " WHERE brand_id = %s AND campaign_cycle_id IS NULL", (brand_id,))
    else:
        rows = conn.execute(
            "SELECT account_id, meta_campaign_id, meta_adset_id, meta_ad_id,"
            " date_range_start, date_range_end, impressions, clicks, spend, conversions,"
            " revenue, frequency, reach FROM performance_snapshot"
            " WHERE brand_id = %s AND campaign_cycle_id = %s", (brand_id, cycle_id))
    return {
        (r["account_id"], r["meta_campaign_id"], r["meta_adset_id"], r["meta_ad_id"],
         _sig_date(r["date_range_start"]), _sig_date(r["date_range_end"]),
         r["impressions"], r["clicks"], _sig_money(r["spend"]),
         r["conversions"], _sig_money(r["revenue"]), r["frequency"], r["reach"])
        for r in rows
    }


def _guess_brand(conn, campaign_name: str) -> tuple:
    """依命名猜歸屬，回 (brand_id, 人話理由)；猜不到回 (None, None)。

    只認我們自己產的命名格式開頭的品牌名片段。刻意不做模糊比對——
    猜錯比猜不到更糟，猜不到至少使用者會自己選。
    """
    if not campaign_name:
        return None, None
    head = campaign_name.split("_")[0]
    if not head:
        return None, None
    for brand in bi.list_brands(conn):
        if ads_handoff._slug(brand["name"]) == head:
            return brand["id"], f"活動名稱開頭是「{head}」，跟這個品牌的命名一樣"
    return None, None


def _upsert_discovered(conn, ad_account_id: str, campaign, ts: str) -> bool:
    """回傳 True 代表這是第一次看到這個活動。"""
    existing = conn.execute(
        "SELECT * FROM discovered_campaign WHERE ad_account_id = %s AND meta_campaign_id = %s",
        (ad_account_id, campaign.campaign_id),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE discovered_campaign SET campaign_name = %s, objective = %s,"
            " effective_status = %s, last_seen_at = %s, updated_at = %s WHERE id = %s",
            (campaign.name, campaign.objective, campaign.effective_status, ts, ts,
             existing["id"]),
        )
        return False

    suggested_brand_id, reason = _guess_brand(conn, campaign.name)
    conn.execute(
        "INSERT INTO discovered_campaign (id, org_id, ad_account_id, platform, meta_campaign_id,"
        " campaign_name, objective, effective_status, first_seen_at, last_seen_at,"
        " suggested_brand_id, suggested_reason, claim_status, created_at, updated_at)"
        " VALUES (%s, %s, %s, 'meta', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (new_id("dsc"), DEV_ORG_ID, ad_account_id, campaign.campaign_id, campaign.name,
         campaign.objective, campaign.effective_status, ts, ts,
         suggested_brand_id, reason,
         "suggested" if suggested_brand_id else "unclaimed", ts, ts),
    )
    return True


# issue #73：活動清單 API 只回目前還存在的活動，已刪除／已封存的活動不在裡面，
# 但 insights 歷史成效裡還有它們的 campaign_id——這裡標明來源，讓使用者知道這筆是
# 補登的歷史資料，不是目前投放中的活動。
HISTORICAL_STATUS = "已刪除或已封存的活動（從歷史成效補登，狀態未知）"


def _upsert_discovered_from_insight(conn, ad_account_id: str, insight, ts: str) -> bool:
    """insights 裡有、但這次 list_campaigns 沒回來的活動（八成已被刪除或封存）——
    照樣補進待認領清單，不然它的成效永遠卡在「查無歸屬」進不了任何品牌（issue #73）。
    回傳 True 代表這是第一次看到；已經在 discovered_campaign 裡的（不論是這次同步的
    活動清單剛寫進去的，還是先前同步留下的）一律不動，活動清單的資料比較新、不能被
    insights 的殘缺資訊蓋掉。"""
    existing = conn.execute(
        "SELECT id FROM discovered_campaign WHERE ad_account_id = %s AND meta_campaign_id = %s",
        (ad_account_id, insight.campaign_id),
    ).fetchone()
    if existing:
        return False

    campaign_name = insight.campaign_name
    suggested_brand_id, reason = _guess_brand(conn, campaign_name)
    conn.execute(
        "INSERT INTO discovered_campaign (id, org_id, ad_account_id, platform, meta_campaign_id,"
        " campaign_name, objective, effective_status, first_seen_at, last_seen_at,"
        " suggested_brand_id, suggested_reason, claim_status, created_at, updated_at)"
        " VALUES (%s, %s, %s, 'meta', %s, %s, NULL, %s, %s, %s, %s, %s, %s, %s, %s)",
        (new_id("dsc"), DEV_ORG_ID, ad_account_id, insight.campaign_id, campaign_name,
         HISTORICAL_STATUS, ts, ts, suggested_brand_id, reason,
         "suggested" if suggested_brand_id else "unclaimed", ts, ts),
    )
    return True


def _claimed_brand_for(conn, ad_account_id: str, meta_campaign_id: str,
                       meta_ad_id: Optional[str] = None) -> Optional[str]:
    """這個活動的歸屬品牌。只有 claimed 才算數——suggested 是預選，不生效。"""
    row = conn.execute(
        "SELECT claimed_brand_id FROM discovered_campaign WHERE ad_account_id = %s"
        " AND meta_campaign_id = %s AND claim_status = 'claimed'",
        (ad_account_id, meta_campaign_id),
    ).fetchone()
    if row and row["claimed_brand_id"]:
        return row["claimed_brand_id"]
    # 人工回填過 ID 的（票 8 關卡三）本來就是確認過歸屬的，直接算數。優先用 meta_ad_id：
    # 同一活動底下可能有多支廣告，只認 meta_campaign_id 會全部對到同一筆（I1，程式碼自己
    # 標的既有缺口）。人工回填沒填廣告 ID 時 meta_ad_id 是 None，退回 meta_campaign_id。
    if meta_ad_id:
        mapping = conn.execute(
            "SELECT brand_id FROM external_ad_mapping WHERE meta_ad_id = %s"
            " AND claim_status = 'confirmed' LIMIT 1", (meta_ad_id,),
        ).fetchone()
        if mapping:
            return mapping["brand_id"]
    mapping = conn.execute(
        "SELECT brand_id FROM external_ad_mapping WHERE meta_campaign_id = %s"
        " AND claim_status = 'confirmed' LIMIT 1", (meta_campaign_id,),
    ).fetchone()
    return mapping["brand_id"] if mapping else None


def _cycle_for(conn, brand_id: str, meta_campaign_id: str,
               meta_ad_id: Optional[str] = None) -> tuple:
    """哪個檔期／哪筆 mapping／哪個 publishing_package。優先用 meta_ad_id：同一活動底下
    可能有多支廣告分屬不同檔期，只用 meta_campaign_id 查詢會全部對到最後建立的那一筆
    （I1）。meta_ad_id 缺值（人工回填時沒填廣告 ID）才退回 meta_campaign_id，維持既有
    行為。publishing_package_id 是票 11 加的：D3 產品歸因要用它反查 product_id／
    experiment_cell，不再另外寫一次查詢。"""
    if meta_ad_id:
        row = conn.execute(
            "SELECT campaign_cycle_id, id, publishing_package_id FROM external_ad_mapping"
            " WHERE brand_id = %s AND meta_ad_id = %s ORDER BY created_at DESC LIMIT 1",
            (brand_id, meta_ad_id),
        ).fetchone()
        if row:
            return row["campaign_cycle_id"], row["id"], row["publishing_package_id"]
    row = conn.execute(
        "SELECT campaign_cycle_id, id, publishing_package_id FROM external_ad_mapping"
        " WHERE brand_id = %s AND meta_campaign_id = %s ORDER BY created_at DESC LIMIT 1",
        (brand_id, meta_campaign_id),
    ).fetchone()
    return ((row["campaign_cycle_id"], row["id"], row["publishing_package_id"]) if row
            else (None, None, None))


def sync_account(conn, actor: str, *, client=None, account_id: Optional[str] = None,
                 since: Optional[str] = None, until: Optional[str] = None,
                 today: Optional[str] = None,
                 brand_id_filter: Optional[str] = None) -> SyncResult:
    """把帳號上的活動與成效抓回來。失敗一律回帶 error 的結果，不拋例外、不半途留髒資料。"""
    account_external = account_id or get_account_id(conn)
    if not account_external:
        return SyncResult(error=meta_api.NO_TOKEN_MESSAGE)

    client = client or make_client(conn)
    today = today or date.today().isoformat()
    until = until or today
    since = since or (date.fromisoformat(until) - timedelta(days=DEFAULT_LOOKBACK_DAYS)).isoformat()

    ts = now_utc()
    ad_account_id = ads_handoff._ensure_ad_account(conn, account_external, ts)
    result = SyncResult()
    # 決策 0039 第 7 條：認領過但查無檔期對應（沒有 external_ad_mapping）的活動＝舊廣告，
    # 它的成效落在品牌層（campaign_cycle_id NULL）。這裡記下哪些品牌這次收到了品牌層成效，
    # 迴圈跑完後各自重算一次品牌層基準——不必等使用者手動觸發。
    brand_ids_with_brand_level_rows = set()
    # issue #69／票 11：去重簽章快取，依 (brand_id, cycle_id) 分開查一次既有資料庫內容
    # （品牌層與每個檔期各自獨立比對），同一輪回填內新寫入的列也要立刻併入，避免同一輪裡
    # 本身就重複的插入互相漏擋。
    seen_signatures = {}

    try:
        campaigns = client.list_campaigns(account_external)
        insights = []
        for chunk_since, chunk_until in _month_windows(since, until):
            insights.extend(client.list_insights(account_external, chunk_since, chunk_until))
    except meta_api.MetaApiError as exc:
        return SyncResult(error=str(exc))

    for campaign in campaigns:
        previous = conn.execute(
            "SELECT campaign_name FROM discovered_campaign WHERE ad_account_id = %s"
            " AND meta_campaign_id = %s", (ad_account_id, campaign.campaign_id),
        ).fetchone()
        if _upsert_discovered(conn, ad_account_id, campaign, ts):
            result.discovered += 1
        if previous:
            tracking.alert_campaign_renamed(
                conn, ad_account_id, campaign.campaign_id,
                previous["campaign_name"] or "", campaign.name)
        tracking.suggest_cycle_mapping(
            conn, ad_account_id, account_external, campaign.campaign_id)

    for insight in insights:
        if _upsert_discovered_from_insight(conn, ad_account_id, insight, ts):
            result.discovered += 1
        tracking.suggest_cycle_mapping(
            conn, ad_account_id, account_external, insight.campaign_id)
        brand_id = _claimed_brand_for(conn, ad_account_id, insight.campaign_id, insight.ad_id)
        if not brand_id:
            # 沒認領歸屬的活動，成效一律不收——寧可少一筆，也不把別的品牌的數字算進來
            tracking.alert_unmapped_spend(
                conn, ad_account_id, insight.campaign_id, insight.spend, insight.date_stop)
            result.skipped_unclaimed += 1
            continue
        if brand_id_filter and brand_id != brand_id_filter:
            continue

        cycle_id, mapping_id, package_id = _cycle_for(
            conn, brand_id, insight.campaign_id, insight.ad_id)
        if cycle_id is None:
            tracking.alert_unmapped_spend(
                conn, ad_account_id, insight.campaign_id, insight.spend, insight.date_stop)

        # issue #69／票 11：品牌層與檔期層各自獨立去重，範圍鍵是 (brand_id, cycle_id)——
        # cycle_id 為 None 時就是品牌層那組既有簽章，不會互相污染。
        seen_key = (brand_id, cycle_id)
        if seen_key not in seen_signatures:
            seen_signatures[seen_key] = _existing_signatures(conn, brand_id, cycle_id)
        signature = _duplicate_signature(account_external, insight)
        if signature in seen_signatures[seen_key]:
            result.skipped_duplicate += 1
            continue
        seen_signatures[seen_key].add(signature)

        row = {"impressions": insight.impressions, "clicks": insight.clicks,
               "spend": insight.spend, "conversions": insight.conversions,
               "revenue": insight.revenue, "as_of_date": insight.date_stop}
        sanity = guardrails.check_data_sanity(row, today=today)
        quarantined = bool(sanity)
        if quarantined:
            result.quarantined += 1
        product_id = ads_performance.resolve_product_id(conn, brand_id, cycle_id, package_id)
        # 票 11：raw_json 存這一列 Meta 回傳的原始洞察報告（不影響去重——sync.py 的
        # 簽章從一開始就直接用 meta_ad_id 等真實欄位，見 `_duplicate_signature`）。
        raw_json = asdict(insight)

        conn.execute(
            "INSERT INTO performance_snapshot (id, org_id, brand_id, campaign_cycle_id, product_id,"
            " external_ad_mapping_id, platform, account_id, meta_campaign_id, meta_adset_id,"
            " meta_ad_id, date_range_start, date_range_end, as_of_date, snapshot_taken_at,"
            " currency, impressions, clicks, spend, conversions, revenue, frequency, reach,"
            " raw_json, reconciled, source, import_batch_id, quarantined, quarantine_reason,"
            " created_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, 'meta', %s, %s, %s, %s, %s, %s, %s, %s, 'TWD', %s, %s, %s, %s, %s, %s, %s,"
            " %s, true, 'meta_api', %s, %s, %s, %s)",
            (new_id("psn"), DEV_ORG_ID, brand_id, cycle_id, product_id, mapping_id, account_external,
             insight.campaign_id, insight.adset_id, insight.ad_id,
             insight.date_start, insight.date_stop, insight.date_stop, ts,
             insight.impressions, insight.clicks, insight.spend, insight.conversions,
             insight.revenue, insight.frequency, insight.reach, jsonb(raw_json), f"sync_{ts}",
             quarantined,
             "；".join(f.message for f in sanity) or None, ts),
        )
        result.snapshots += 1
        if cycle_id is None:
            brand_ids_with_brand_level_rows.add(brand_id)

    # D 段元件層歸因（票 12）：body／title／description breakdown，image_asset 不拉
    # （ADR 0008）。這條路掛了（Meta 拒絕 breakdown 請求、格式不相容等）不能拖累廣告層
    # 同步本身——元件層排名是加分項，廣告層數字才是花錢判讀的地基，這裡單獨接住失敗。
    try:
        component_rows = []
        for chunk_since, chunk_until in _month_windows(since, until):
            component_rows.extend(
                client.list_component_breakdowns(account_external, chunk_since, chunk_until))
    except meta_api.MetaApiError:
        component_rows = []

    for row in component_rows:
        brand_id = _claimed_brand_for(conn, ad_account_id, None, row.ad_id)
        if not brand_id:
            continue
        cycle_id, _mapping_id, _package_id = _cycle_for(conn, brand_id, None, row.ad_id)
        theme_attribution.record_component_breakdown(conn, brand_id, cycle_id, row, actor=actor)

    conn.commit()
    for bid in brand_ids_with_brand_level_rows:
        ads_performance.save_brand_level_derived_metrics(conn, bid)
    return result


# ---------------------------------------------------------------------------
# 歸屬認領
# ---------------------------------------------------------------------------

def list_pending_claims(conn, brand_id: str) -> list:
    """這個品牌可以認領的活動：系統猜是它的，加上完全沒歸屬的。

    刻意不列出「已經認領給別的品牌」的活動——那會在 A 品牌的頁面上顯示 B 品牌的內容，
    違反品牌隔離（鐵則 13）。
    """
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM discovered_campaign WHERE claim_status IN ('unclaimed', 'suggested')"
        " AND (suggested_brand_id IS NULL OR suggested_brand_id = %s)"
        " ORDER BY first_seen_at DESC", (brand_id,),
    )]
    for row in rows:
        row["is_suggested"] = row["suggested_brand_id"] == brand_id
    return rows


def claim(conn, brand_id: str, discovered_id: str, actor: str) -> dict:
    """使用者確認：這個活動是這個品牌的。認領後它的成效才進得了這個品牌。"""
    row = conn.execute(
        "SELECT * FROM discovered_campaign WHERE id = %s", (discovered_id,)
    ).fetchone()
    if row is None:
        raise ValueError("找不到這個廣告活動")
    if row["claim_status"] == "claimed" and row["claimed_brand_id"] != brand_id:
        raise ValueError("這個活動已經認領給別的品牌了")

    ts = now_utc()
    conn.execute(
        "UPDATE discovered_campaign SET claim_status = 'claimed', claimed_brand_id = %s,"
        " claimed_by = %s, claimed_at = %s, updated_at = %s WHERE id = %s",
        (brand_id, actor, ts, ts, discovered_id),
    )
    write_audit(conn, brand_id=brand_id, entity_type="discovered_campaign",
                entity_id=discovered_id, action="claim", actor=actor,
                before=dict(row), after={"claimed_brand_id": brand_id})
    conn.commit()
    # 決策 0039 第 7 條：認領當下如果已經有品牌層（無檔期）舊成效在等（例如先前 CSV
    # 匯入的對不到檔期列），立刻重算一次基準，不必等下一次同步才看得到。全量重算、
    # 可重複呼叫（app/ads/performance.py 的品牌層寫入函式）。
    ads_performance.save_brand_level_derived_metrics(conn, brand_id)
    return dict(conn.execute("SELECT * FROM discovered_campaign WHERE id = %s",
                             (discovered_id,)).fetchone())


def ignore(conn, brand_id: str, discovered_id: str, actor: str) -> None:
    """「這不是這個品牌的」：從這個品牌的待認領清單移走，不歸屬給任何人。"""
    row = conn.execute("SELECT * FROM discovered_campaign WHERE id = %s",
                       (discovered_id,)).fetchone()
    if row is None:
        raise ValueError("找不到這個廣告活動")
    ts = now_utc()
    conn.execute(
        "UPDATE discovered_campaign SET claim_status = 'ignored', suggested_brand_id = NULL,"
        " updated_at = %s WHERE id = %s", (ts, discovered_id),
    )
    write_audit(conn, brand_id=brand_id, entity_type="discovered_campaign",
                entity_id=discovered_id, action="ignore_claim", actor=actor,
                before=dict(row), after=None)
    conn.commit()
