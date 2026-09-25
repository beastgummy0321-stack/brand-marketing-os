"""app/core/interrupts.py — 全站打斷佇列（GitHub issue #32，決策 0025／0026）。

全站所有「需要人看」的訊息只剩一個出口：這裡的 enqueue()。各模組只能認領 CATEGORIES
裡登記好的一個類別，嚴重度由類別反查、呼叫端不得自報數字——避免每個模組都覺得自己最急。

嚴重度分級（單一中央位置，原設計文件已被 5eca0db 清除，決策 0026）：金額損失 ＞ 不可逆 ＞ 規則警示 ＞ 資訊性。
排序＝嚴重度為主，同級內按行動價值（CATEGORIES 的登記順序，越早登記代表價值越高）。

去重：同一品牌下同一 dedupe_key 二次 enqueue 只留第一筆（INSERT 前用 brand_id ＋ dedupe_key
查重，命中就不寫，回傳 None），呼叫端可用回傳值判斷這次是不是新排的。不同品牌就算 dedupe_key
剛好相同也各自獨立去重，不會互相蓋掉（票 M6，DB 唯一索引見 migrations/0007）。

資訊性項目逾期自動降級封存：見 _archive_stale_informational（每次 list_open 前跑一次）。
"""

from datetime import date, datetime, timedelta

from app.core import cleanup
from app.core.audit import write_audit
from app.core.db import new_id, now_utc

# 嚴重度分級（決策 0025／0026 定案；原設計文件規則 4 的資料層對應，文件已刪）。
SEVERITY_ORDER = ["money_loss", "irreversible", "rule_warning", "informational"]
SEVERITY_RANK = {level: i for i, level in enumerate(SEVERITY_ORDER)}
SEVERITY_LABELS = {
    "money_loss": "金額損失",
    "irreversible": "不可逆",
    "rule_warning": "規則警示",
    "informational": "資訊性",
}

# 類別登記表（單一權威）：新模組要送打斷佇列，在這裡登記一筆，不得在呼叫端自報 severity。
# dict 順序＝同嚴重度內的行動價值排序。
CATEGORIES = {
    # F18-I03: brand-level decision queue over program triage (`app/ads/triage.py`) -- one entry
    # per class the queue actually carries in this batch (`worse` is a decision to make, not yet
    # a loss, so it ranks below `stop_loss` but above the pre-existing informational entries).
    "ads_triage_stop_loss": {"severity": "money_loss", "label": "廣告停損待決定"},
    # F27-I06 cleanup row, F28-I02/I06: it now also carries the 白花 ads (spent >= 3x the cap with
    # no result) that used to raise `stop_loss` -- money already being lost -- so it ranks
    # money_loss right after stop_loss, never lower than the rows it replaced.
    "ads_triage_cleanup": {"severity": "money_loss", "label": "花錢沒效的廣告待決定"},
    "ads_triage_worse": {"severity": "rule_warning", "label": "廣告變差待決定"},
    "ads_runtime_attention": {"severity": "rule_warning", "label": "廣告追蹤待確認"},
    # F26-I01: the campaign-level "insufficient data" row (missing sync days, or a failed/
    # disconnected sync, over an otherwise-live campaign) -- a rule about the data itself, not yet
    # a loss, so it ranks after the other rule_warning entries.
    "ads_triage_insufficient_data": {"severity": "rule_warning", "label": "活動資料不足待處理"},
    # F25-I01: the two remaining queue kinds -- program proposals, not yet losses or warnings
    # (feature Decisions "Rule A"/"Rule B"), so both rank informational, after the F18 entries.
    "ads_triage_scale_budget": {"severity": "informational", "label": "可加預算待決定"},
    # F29-I03: the brand's period settle (last month's grades written to the brand notebook) --
    # nothing is lost while it waits, so informational, but it is never auto-archived while
    # unwritten (`_NEVER_STALE_CATEGORIES`); `app/ads` resolves it once written.
    "ads_triage_settle": {"severity": "informational", "label": "上一期待結算"},
    "ads_triage_refresh_creative": {"severity": "informational", "label": "素材待補待決定"},
    "ads_review_ready": {"severity": "informational", "label": "廣告檢討已備妥"},
    # F29-I08: the brand's daily digest of its ads decision queue (`app/ads/digest.py`) -- a
    # summary pointing at rows already in the queue, never a decision of its own, so informational
    # and outside the ads queue categories (it never counts toward the home decisions).
    "ads_daily_digest": {"severity": "informational", "label": "投放每日摘要"},
    # 顧客原話貼入後背景 AI 抽取，完成／失敗都進這裡（票 B2-library，五鐵則③生成不擋路）。
    "customer_voice_extraction_done": {"severity": "informational", "label": "顧客原話分析完成"},
    # 產品 AI 調研（新建與再次調研共用）背景工作，完成／失敗都進這裡（票 B2-products）。
    "product_research_done": {"severity": "informational", "label": "產品調研完成"},
    # 建檔精靈初掃／貼回修格式背景工作，完成／失敗都進這裡；出下一題不進（票 B3-intake）。
    "intake_ai_step_done": {"severity": "informational", "label": "建檔精靈 AI 步驟完成"},
    # 顧問分析報告背景生成，完成／失敗都進這裡（票 dead-code-sweep 02：漏登記導致背景
    # 執行緒在 _notify() 炸 ValueError、job 狀態卡在 running 永遠不會變成 done/failed）。
    "brand_report_done": {"severity": "informational", "label": "顧問分析報告完成"},
    "personas_ready": {"severity": "informational", "label": "人物誌好了"},
}
_CATEGORY_RANK = {name: i for i, name in enumerate(CATEGORIES)}

MAX_MESSAGE_LEN = 30  # 原設計文件規則 4（已刪）：一卡一句 ≤30 全形字
STALE_AFTER_DAYS = 14  # 資訊性項目逾期自動降級封存的門檻（比照 0025 期末＋14 天結算節奏）


def enqueue(conn, *, org_id: str, category: str, dedupe_key: str, message: str,
            brand_id: str | None = None, campaign_period_id: str | None = None,
            action_url: str | None = None, kind: str | None = None,
            visible_from: date | datetime | None = None) -> str | None:
    """送進打斷佇列；同去重鍵已存在就不重複塞（回傳 None）。不自動 commit（比照 write_audit，
    交由呼叫端決定交易邊界，方便一次排多筆用同一個交易）。"""
    spec = CATEGORIES.get(category)
    if spec is None:
        raise ValueError(f"未登記的打斷類別：{category}（見 CATEGORIES，模組不得自報嚴重度）")
    if not dedupe_key or not dedupe_key.strip():
        raise ValueError("interrupt.dedupe_key 為必填（用於去重）")
    if not message or not message.strip():
        raise ValueError("interrupt.message 為必填")
    if len(message) > MAX_MESSAGE_LEN:
        raise ValueError(
            f"卡片內文超過 {MAX_MESSAGE_LEN} 全形字上限（原設計文件規則 4，已刪）：{message}"
        )

    # 去重比對要連 brand_id 一起看（票 M6）：SQLite 的 IS 運算子對 NULL 也能正確比對，
    # brand_id 為 None 時會比對「brand_id IS NULL」而不是誤判成跟別的品牌撞鍵。
    # BUG 修復（route=C 02-3c）：Postgres 的 IS 不接受綁參數（只認 IS NULL/IS NOT NULL
    # 字面），改用 IS NOT DISTINCT FROM——NULL 對 NULL 一樣判真，效果同原本的 SQLite IS。
    existing = conn.execute(
        "SELECT id FROM interrupt WHERE dedupe_key = %s AND brand_id IS NOT DISTINCT FROM %s",
        (dedupe_key, brand_id),
    ).fetchone()
    if existing:
        return None

    interrupt_id = new_id("itr")
    conn.execute(
        "INSERT INTO interrupt (id, org_id, brand_id, campaign_period_id, dedupe_key, category, kind,"
        " severity, message, action_url, visible_from, status, created_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'open', %s)",
        (interrupt_id, org_id, brand_id, campaign_period_id, dedupe_key, category, kind,
         spec["severity"], message, action_url, visible_from, now_utc()),
    )
    return interrupt_id


# 期中檢查點（app/ads/onboarding.py 的 day3／day7 提醒）不吃這條規則——它們有自己專屬的
# 生命週期（onboarding.resolve_stale_checkpoint_reminders，決策 0025 審查補遺第 4 點：
# 「提醒進佇列不過期；使用者過時才來則直接併入期末判讀」）。逾期不代表沒用，逾期只代表
# 該併入期末結論，不是該悄悄消失（票 #38）。
_NEVER_STALE_KINDS = ("day3_look_dont_touch", "day7_report")
# 同理，這些類別逾期也不自動封存：期結算（F29-I03）在寫進筆記本之前一直要留著，寫完由
# app/ads 自己 resolve——悄悄封存等於那一期的學習永遠沒寫進去。
_NEVER_STALE_CATEGORIES = ("ads_triage_settle",)


def _archive_stale_informational(conn, today: str | None = None) -> int:
    """資訊性項目逾期自動降級封存：**到期**超過 STALE_AFTER_DAYS 天沒人處理，自動轉
    archived，不再佔待辦清單（不擋路，見 0025 懶人優先總則）。

    逾期起算點是 visible_from（這則提醒實際浮出、使用者才看得到的那天），不是
    created_at（enqueue 當下）——很多提醒是提早排入佇列、visible_from 訂在未來
    （例如票 #38 的 final_settlement 排在檔期結束＋14 天），起算點若用 created_at，
    這類提醒還沒被使用者看過就已經因為「早就存在資料庫裡」而被判定逾期、悄悄消失，
    等於從沒機會被看到（曾是真實的潛在 bug，不是本函式故意的行為）。
    """
    today_date = date.fromisoformat(today) if today else date.today()
    cutoff = today_date - timedelta(days=STALE_AFTER_DAYS)
    placeholders = ",".join("%s" for _ in _NEVER_STALE_KINDS)
    category_placeholders = ",".join("%s" for _ in _NEVER_STALE_CATEGORIES)
    cursor = conn.execute(
        "UPDATE interrupt SET status = 'archived', resolved_at = %s"
        " WHERE status = 'open' AND severity = 'informational'"
        " AND COALESCE(visible_from, created_at) < %s"
        f" AND (kind IS NULL OR kind NOT IN ({placeholders}))"
        f" AND category NOT IN ({category_placeholders})",
        (now_utc(), cutoff, *_NEVER_STALE_KINDS, *_NEVER_STALE_CATEGORIES),
    )
    conn.commit()
    return cursor.rowcount


def _sort_key(row: dict):
    return (
        SEVERITY_RANK.get(row["severity"], len(SEVERITY_ORDER)),
        _CATEGORY_RANK.get(row["category"], len(CATEGORIES)),
        row["visible_from"] or row["created_at"],
        row["created_at"],
    )


def list_open(conn, brand_id: str | None = None, category: str | None = None,
              today: str | None = None, archive_stale: bool = True,
              org_id: str | None = None) -> list:
    """待辦清單：已到 visible_from 的 open 項目，嚴重度為主、同級按行動價值排序。

    brand_id 省略＝跨品牌查（首頁待辦、全站收件匣用）——這時租戶界線改由 org_id 守
    （票 03-1：不然沒帶 brand_id 的呼叫會查到別的組織的資料）。有 brand_id 時本來就
    已經被上游 require_brand() 驗過該品牌屬於哪個組織，org_id 這裡不必重複。

    archive_stale＝False：跳過逾期資訊性項目自動封存（唯讀呼叫端專用，例如
    app/dashboard——「查詢函式」若順手寫資料庫就不是真的唯讀，見票 02 第 2 輪）。
    預設 True：保留既有呼叫端（app/shared/web.py、app/ads/onboarding.py 等）原行為。
    """
    if archive_stale:
        _archive_stale_informational(conn, today)
    today = today or date.today().isoformat()
    sql = "SELECT * FROM interrupt WHERE status = 'open' AND (visible_from IS NULL OR visible_from <= %s)"
    params: list = [today]
    if brand_id:
        sql += " AND brand_id = %s"
        params.append(brand_id)
    elif org_id:
        sql += " AND org_id = %s"
        params.append(org_id)
    if category:
        sql += " AND category = %s"
        params.append(category)
    rows = [dict(r) for r in conn.execute(sql, params)]
    rows.sort(key=_sort_key)
    return rows


def list_done(conn, brand_id: str | None = None, org_id: str | None = None) -> list:
    """已結清單（人工處理 resolved ＋ 逾期自動封存 archived），最近結案的排前面。
    org_id：同 list_open() 的說明，只有沒帶 brand_id 時才需要（沒帶會跨品牌查）。"""
    sql = "SELECT * FROM interrupt WHERE status IN ('resolved', 'archived')"
    params: list = []
    if brand_id:
        sql += " AND brand_id = %s"
        params.append(brand_id)
    elif org_id:
        sql += " AND org_id = %s"
        params.append(org_id)
    sql += " ORDER BY resolved_at DESC"
    return [dict(r) for r in conn.execute(sql, params)]


def resolve(conn, interrupt_id: str, *, actor: str, org_id: str) -> None:
    """人工處理完畢，轉 resolved；寫一筆 audit_log（write_audit 會擋空 actor）。會 commit。

    org_id 為必填租戶界線（票 03-1 r1 defect 1）：只能結掉自己組織的中斷提醒——找不到
    這筆、或這筆屬於別的組織，一律同一個 ValueError（呼叫端，例如
    app/brand_web/routes_inbox.py，轉成 404，不區分「不存在」跟「不是你的」，同
    app/shared/web.py require_brand() 對跨租戶資源的處理方式）。"""
    row = conn.execute(
        "SELECT * FROM interrupt WHERE id = %s AND org_id = %s", (interrupt_id, org_id)
    ).fetchone()
    if row is None:
        raise ValueError(f"找不到打斷佇列項目：{interrupt_id}")
    conn.execute(
        "UPDATE interrupt SET status = 'resolved', resolved_at = %s WHERE id = %s",
        (now_utc(), interrupt_id),
    )
    write_audit(conn, org_id=row["org_id"], brand_id=row["brand_id"], entity_type="interrupt",
                entity_id=interrupt_id, action="resolve", actor=actor)
    conn.commit()


# ---------------------------------------------------------------------------
# 刪品牌（第 5 刀「核心模組接上清理登記處」）：interrupt 掛 brand_id，刪品牌時要一併
# 清掉。向 app.core.cleanup 登記——這是 core 內部依賴（cleanup.py 零 app 依賴，本檔
# import 它不違反「app/core 不得 import 任何上層模組」的地界，本來就在 core 裡面）。
# ---------------------------------------------------------------------------

BRAND_CASCADE_TABLES = (
    ("interrupt", "中斷提醒"),
)


def count_brand_data(conn, brand_id: str) -> list:
    """刪品牌前的清點，給刪除確認頁列出「按下去會消失什麼」。跟 delete_brand_data
    讀同一份 BRAND_CASCADE_TABLES——不各寫一份，避免清點與清除不同步。"""
    counts = []
    for table, label in BRAND_CASCADE_TABLES:
        n = conn.execute(
            f"SELECT COUNT(*) AS c FROM {table} WHERE brand_id = %s", (brand_id,)
        ).fetchone()["c"]
        if n:
            counts.append((label, n))
    return counts


def delete_brand_data(conn, brand_id: str) -> dict:
    """清掉本模組掛在該品牌下的資料，登記進 app.core.cleanup 給 delete_brand() 呼叫用。
    只下 DELETE、不 commit、不 rollback（commit 與 rollback 統一在
    brand_intelligence.delete_brand()）。"""
    counts = dict(count_brand_data(conn, brand_id))
    for table, _label in BRAND_CASCADE_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE brand_id = %s", (brand_id,))
    return counts


cleanup.register("中斷提醒", count_brand=count_brand_data, delete_brand=delete_brand_data,
                 brand_tables={t for t, _ in BRAND_CASCADE_TABLES},
                 count_product=None, delete_product=None, product_tables=frozenset())
