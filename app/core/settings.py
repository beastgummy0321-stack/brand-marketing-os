"""app/core/settings.py — 全站設定（app_setting 表）的最小存取層。

只做兩件事：讀一個鍵、寫一個鍵；外加三個語意函式（金鑰、模型、精靈花費上限），
把「DB 設定 > 環境變數 > 程式預設」這條優先順序寫在一個地方，呼叫端不各自實作。

介面契約原文件已被 5eca0db 清除；權威現在是這三個函式本身的簽章與行為。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psycopg

from app.core import config, db

logger = logging.getLogger(__name__)

API_KEY_SETTING = "anthropic_api_key"  # 舊世界的明文鍵：只用來認得、刪掉遺留資料，不再當金鑰讀
API_KEY_SECRET_ID_SETTING = "anthropic_api_key_secret_id"  # 指標，值是 vault.secrets.id
LLM_MODEL_SETTING = "llm_model"
DEFAULT_LLM_MODEL = "claude-opus-5"
INTAKE_BUDGET_SETTING = "intake_budget_limit"

# 誰的金鑰付錢（票 04-1a，D4-3）。'platform'＝操作者付錢（預設，今天唯一真的能用的值）；
# 'own'＝組織自帶金鑰付錢（Vault 儲存是 04-2 的事，這裡先讀跟 'platform' 同一個 DB 欄位）。
# 日後開放付費層要加第三個值，只改 resolve_ai_credentials() 這一個函式——不准在別的檔案
# 對這把設定值的內容（'platform'／'own' 字面值）做 if 判斷，見
# test_architecture_boundaries.py 的 AiKeySourceSingleSourceOfTruthTest。
AI_KEY_SOURCE_SETTING = "ai_key_source"
_AI_KEY_SOURCES = ("platform", "own")

# 組織每月 AI 花費上限（US$，票 04-1a，D4-2）：操作者的錢包保護閥，跟品牌花費上限
# （INTAKE_BUDGET_SETTING，per-brand、all-time）是不同的兩道關卡，見
# resolve_ai_credentials() 與 org_ai_spent_this_month() 的檔頭說明。
AI_MONTHLY_COST_LIMIT_SETTING = "ai_monthly_cost_limit"
# 預設 US$200／月／組織：比單一品牌的 US$30（DEFAULT_BUDGET，全期一次性）高一個數量級，
# 讓一個組織底下開好幾個品牌、每個都在跑建檔精靈／廣告生成時不會平白被擋，但仍然是
# 「就算整月忘記調整，操作者也賠得起」的量級（20 個品牌同時打滿全期精靈預算才會碰到）。
# 這是本票作者提出的數字，不是使用者定案——設定頁可隨時調整。
DEFAULT_AI_MONTHLY_COST_LIMIT = 200.0

# 組織所在時區（票 04-1b）：IANA 名稱，例如 Asia/Taipei、America/New_York。
# 預設值的來源是使用者本人所在地（2026-08-30 裁決），不是猜的門檻。今天沒有設定畫面
# （全系統只有一個組織，比照「切換金鑰來源」同一個理由留到里程碑之後）；要改就改
# app_setting 這一列，程式不必動。
ORG_TIMEZONE_SETTING = "org_timezone"
DEFAULT_ORG_TIMEZONE = "Asia/Taipei"


def get_setting(conn: db.Conn | db.ConnProxy | None, key: str, default=None, *, org_id: str):
    """讀一個設定值；沒設過（或 app_setting 表還沒建起來）回 default。

    org_id 必填、不給預設值（票 04-0）：`app_setting` 主鍵是 (org_id, key)，沒有 org_id
    篩選就是跨租戶讀——上一版曾經漏掉這道篩選，任一組織都可能讀到另一組織存的值
    （含 Meta 權杖、GA4 服務帳戶、AI 金鑰），此為該次修復。

    conn 傳 None 代表「自己開一條短命連線讀」——給 providers 這種手上沒有連線的呼叫端用。
    表不存在時不噴錯誤碼而是回 default（principles 16 優雅缺席：沒設定就是沒設定）。

    票 02-3a：連線模型改成一條連線一個 request／一個背景工作（app/core/db.py
    connection()），不再有「自己開一條短命連線、用完手動 close()」這件事——沒帶 conn
    進來就跟連線池借一條、離開 with 區塊自動歸還。
    """
    if conn is not None:
        return _get_setting(conn, key, default, org_id=org_id)
    with db.connection() as owned_conn:
        return _get_setting(owned_conn, key, default, org_id=org_id)


def _get_setting(conn: db.Conn | db.ConnProxy, key: str, default=None, *, org_id: str):
    try:
        row = conn.execute(
            "SELECT value FROM app_setting WHERE org_id = %s AND key = %s", (org_id, key)
        ).fetchone()
    except psycopg.Error:
        return default
    return row["value"] if row else default


# ---- Vault（AI 金鑰唯一落地位置，票 04-2 D4-1；形狀抄 app/meta/repository.py 的 Meta
# 權杖 create/update/decrypt-read：secret 不取名字，app_setting 的 secret_id 就是索引）。

def _vault_read_secret(conn: db.Conn | db.ConnProxy, secret_id: str) -> str | None:
    # 走 core_vault_read_secret()（票 R3b），不再直接讀 vault.decrypted_secrets——
    # SECURITY DEFINER，只在呼叫端帶了 app.org_id claim 時才驗證這把 secret 是不是自己
    # 組織的；今天 claim 還沒設（R3c 才切），行為跟原本直接讀完全一樣。
    row = conn.execute(
        "SELECT core_vault_read_secret(%s) AS decrypted_secret", (secret_id,)
    ).fetchone()
    return row["decrypted_secret"] if row else None


def _read_vault_api_key(conn: db.Conn | db.ConnProxy | None, *, org_id: str) -> str | None:
    """三道讀門共用的底層讀取；conn 傳 None 比照 get_setting() 自己借一條連線。"""
    secret_id = get_setting(conn, API_KEY_SECRET_ID_SETTING, org_id=org_id)
    if not secret_id:
        return None
    if conn is not None:
        return _vault_read_secret(conn, secret_id)
    with db.connection() as owned_conn:
        return _vault_read_secret(owned_conn, secret_id)


def save_api_key(conn: db.Conn, key: str, *, org_id: str) -> None:
    """設定頁存金鑰唯一路徑（票 04-2 D4-1），'platform'／'own' 都走這裡不分流，否則
    預設層繼續明文落地；已有 secret 就地覆寫，沒有就新建，順手清掉舊世界的明文列。"""
    # 走 core_vault_save_secret()（票 R3b）：帶 id 就地更新、不帶就新建，合併原本
    # vault.update_secret／vault.create_secret 兩條路徑成一道門。
    existing_secret_id = get_setting(conn, API_KEY_SECRET_ID_SETTING, org_id=org_id)
    row = conn.execute(
        "SELECT core_vault_save_secret(%s, %s) AS id", (existing_secret_id, key)
    ).fetchone()
    assert row is not None, "core_vault_save_secret() 是純量函式，SELECT 一定回一列"
    if not existing_secret_id:
        set_setting(conn, API_KEY_SECRET_ID_SETTING, str(row["id"]), org_id=org_id)
    conn.execute("DELETE FROM app_setting WHERE org_id = %s AND key = %s", (org_id, API_KEY_SETTING))
    conn.commit()


def set_setting(conn: db.Conn, key: str, value: str, *, org_id: str) -> None:
    """寫一個設定值（有則覆蓋）。value 一律存字串，數字請呼叫端先 str()。

    不寫 audit_log：app_setting 沒有 brand_id，也不是品牌事實；金鑰更不該被抄進稽核紀錄。
    """
    conn.execute(
        """INSERT INTO app_setting (org_id, key, value, updated_at) VALUES (%s, %s, %s, %s)
           ON CONFLICT(org_id, key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
        (org_id, key, str(value), db.now_utc()),
    )
    conn.commit()


@dataclass(frozen=True)
class AiCredentials:
    """resolve_ai_credentials() 的回傳形狀（票 04-1a，D4-3）：誰的金鑰、要不要管月費上限，
    一次問清楚，呼叫端不必自己再判斷 source 的字面值。"""

    api_key: str | None  # None＝沒設定，呼叫端既有的優雅缺席處理照舊生效
    source: str  # 'platform' | 'own'
    cap_applies: bool  # True＝操作者付錢，月費上限是硬性關卡；False＝上限只是參考數字


def resolve_ai_credentials(conn: db.Conn | None, *, org_id: str) -> AiCredentials:
    """誰的金鑰付錢、月費上限管不管得到——集中在這裡回答一次（票 04-1a，D4-3）。

    'platform'（預設，DB 沒設這把鍵時）：跟修憲落地 M4 以前的 get_api_key() 完全同一套
    優先序——環境變數 ANTHROPIC_API_KEY 優先，DB 設定回退——操作者的錢付這筆帳，月費上限
    是硬性關卡（cap_applies=True）。

    'own'：組織自帶金鑰付錢（Vault 儲存是 04-2 的事，這裡先讀 API_KEY_SETTING 這個既有
    DB 欄位——今天金鑰放哪裡不變，只是「誰付錢」的認定變了）。刻意不看環境變數：那是
    操作者自己的金鑰，'own' 層的組織不能偷用，否則「上限只是參考數字」會變成操作者
    平白倒貼的免費額度。月費上限只顯示、不擋（cap_applies=False）。

    DB 裡存了看不懂的值（設定打錯字）→ 當 'platform' 處理並記警告，不讓 AI 功能因為
    一個打錯的字整個掛掉（誠實狀態，principles 第 16 條：能繼續運作就不裝死）。
    """
    raw_source = get_setting(conn, AI_KEY_SOURCE_SETTING, org_id=org_id)
    if raw_source in _AI_KEY_SOURCES:
        source = raw_source
    else:
        if raw_source:
            logger.warning(
                "org %s 的 %s 設定值不是合法值：%r，當作 'platform' 處理",
                org_id, AI_KEY_SOURCE_SETTING, raw_source,
            )
        source = "platform"

    if source == "own":
        api_key = _read_vault_api_key(conn, org_id=org_id)
        return AiCredentials(api_key=api_key, source="own", cap_applies=False)

    api_key = config.settings().anthropic_api_key or _read_vault_api_key(conn, org_id=org_id)
    return AiCredentials(api_key=api_key, source="platform", cap_applies=True)


def get_api_key(conn: db.Conn | None = None, *, org_id: str) -> str | None:
    """AI 金鑰：厚度為零的包裝，實際邏輯全部在 resolve_ai_credentials()（票 04-1a）。

    既有呼叫端（intake、providers…）不用跟著改：'platform' 層（今天唯一有資料的層）
    的優先序跟修憲落地 M4 那版一模一樣——環境變數 ANTHROPIC_API_KEY 優先 > DB 設定
    回退 > None（代表尚未設定）。
    """
    return resolve_ai_credentials(conn, org_id=org_id).api_key


def api_key_source(conn: db.Conn | None = None, *, org_id: str) -> str | None:
    """目前生效的金鑰實際放在哪裡：'env'（環境變數，安全）／'db'（本系統的保管庫
    Vault，加密存放，票 04-2 D4-1）／None（兩邊都沒設）。設定頁靠這個誠實顯示金鑰
    來源，不讓使用者以為改用了環境變數、其實系統還在用 DB 裡的舊值（修憲落地 M4）。

    這是「金鑰實際存放位置」的誠實回報，跟 resolve_ai_credentials() 的 source
    （'platform'／'own'，「誰付錢」）是不同的問題——見票 04-1a：'own' 層的組織一定是
    讀 DB（該層刻意不看環境變數，見 resolve_ai_credentials() 說明），這裡照實回報
    'db'，不會因為操作者剛好也設了環境變數就誤報成 'env'。
    """
    creds = resolve_ai_credentials(conn, org_id=org_id)
    if creds.api_key is None:
        return None
    if creds.source == "own":
        return "db"
    return "env" if config.settings().anthropic_api_key else "db"


def get_ai_monthly_cost_limit(conn: db.Conn | None = None, *, org_id: str) -> float:
    """組織每月 AI 花費上限（US$），DB 設定 > DEFAULT_AI_MONTHLY_COST_LIMIT（票 04-1a）。

    壞值（空字串、非數字）當作沒設定，回預設值——設定頁壞一格不該讓 AI 功能整個打不開
    （比照 get_intake_budget_limit() 同一套容錯）。
    """
    raw = get_setting(conn, AI_MONTHLY_COST_LIMIT_SETTING, org_id=org_id)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return DEFAULT_AI_MONTHLY_COST_LIMIT


def org_ai_spent_this_month(conn: db.Conn, *, org_id: str, since: str) -> float:
    """這個組織這個月已經花了多少 AI 費用（US$，累加全組織所有品牌成功呼叫的
    llm_task.cost；票 04-1a，D4-2／D4-3）。

    跟 brand_llm_spent() 是兩道不同的關卡，刻意不合併：brand_llm_spent() 是單一品牌、
    all-time，保護的是客戶自己設的品牌預算；這裡是整個組織、當月，保護的是操作者的
    帳單（操作者付的是 'platform' 層每個組織每個月的總帳，不分品牌）。

    since 由呼叫端算好傳入（當月 1 號的時間戳記字串），這裡不呼叫 db.now_utc() 或
    date.today()——比照 app/dashboard/repository.py `today` 參數的既有慣例：呼叫端在
    正式路徑用真實時鐘算，測試可以帶假的 since 精準驗證月份邊界，不必等到月初才測得到。
    """
    row = conn.execute(
        "SELECT SUM(cost) AS n FROM llm_task WHERE org_id = %s AND status = 'succeeded'"
        " AND started_at >= %s",
        (org_id, since),
    ).fetchone()
    return float(row["n"] or 0.0)


def clear_api_key_from_db(conn: db.Conn, *, org_id: str) -> None:
    """把 DB 裡存的金鑰刪掉，不影響環境變數來源（修憲落地 M4；票 04-2 D4-1 起連 Vault secret 一起刪）。

    這是不可逆動作，只能由使用者在設定頁明確按下按鈕才會呼叫——本函式本身不自動執行、
    不在任何啟動流程或排程中被呼叫。刪掉後若環境變數也沒設，get_api_key() 回 None，
    等同「尚未設定金鑰」，既有的優雅缺席處理（例如 providers 的人話錯誤）照常生效。

    org_id 必填（票 04-0）：沒有這道篩選會刪掉別的組織存在 DB 裡的金鑰。
    """
    secret_id = get_setting(conn, API_KEY_SECRET_ID_SETTING, org_id=org_id)
    if secret_id:
        conn.execute("SELECT core_vault_delete_secret(%s)", (secret_id,))  # 票 R3b
    conn.execute(
        "DELETE FROM app_setting WHERE org_id = %s AND key IN (%s, %s)",
        (org_id, API_KEY_SECRET_ID_SETTING, API_KEY_SETTING),
    )
    conn.commit()


def get_llm_model(conn: db.Conn | None = None, *, org_id: str) -> str:
    """使用的模型：DB 設定 > 環境變數 BRAND_OS_LLM_MODEL > 預設 claude-opus-5。"""
    return (
        get_setting(conn, LLM_MODEL_SETTING, org_id=org_id)
        or config.settings().brand_os_llm_model
        or DEFAULT_LLM_MODEL
    )


def org_timezone(conn: db.Conn | db.ConnProxy | None, *, org_id: str) -> ZoneInfo:
    """這個組織的時區物件。`today_for_org()` 的姊妹函式，兩者共用同一套容錯（票 M1，
    ADR 0058）：核准超支比對要把 `approved_at`（存 UTC 的 timestamptz）換到跟
    `today_for_org()` 同一個時區才能相減，退路因此收在這裡一份，`today_for_org()`
    不再自己重複一份、也不會漏掉。

    壞值（打錯的時區名、空字串）當作沒設定，回預設值——比照
    `get_ai_monthly_cost_limit()` 同一套容錯，設定頁壞一格不該讓每日花費拉取整個停擺。
    但預設值本身載不起來（部署環境沒有 IANA 時區資料庫）就讓它炸：那不是設定壞了，是
    機器缺東西，安靜地退回 UTC 等於把 M1 要修的 bug 藏起來。
    """
    name = get_setting(conn, ORG_TIMEZONE_SETTING, org_id=org_id) or DEFAULT_ORG_TIMEZONE
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("組織 %s 的時區設定 %r 不是合法的 IANA 名稱，改用 %s",
                       org_id, name, DEFAULT_ORG_TIMEZONE)
        return ZoneInfo(DEFAULT_ORG_TIMEZONE)


def today_for_org(conn: db.Conn | db.ConnProxy | None, *, org_id: str) -> date:
    """這個組織所在時區的「今天」（票 04-1b）。

    為什麼不是 `date.today()` 也不是 `datetime.now(UTC).date()`：那兩個問的都是「機器的
    今天」。台北比 UTC 早 8 小時，所以每個月 1 號的台北凌晨到早上 8 點之間，UTC 還停在
    上個月——排程頁與 Meta 花費頁的「本月」會整段端出上個月的數字，核准超支的
    `days_elapsed` 每天也有 8 小時少算一天。上雲後伺服器多半跑 UTC，這件事會從「每月
    8 小時」變成常態。改成問組織自己的時區，答案就跟伺服器擺在哪一國無關。

    範圍只有排程面問「今天幾號」的地方（票 04-1b）：稽核時間戳、`started_at` 這類
    事件發生時刻一律維持 UTC，不走這裡。容錯規則見 `org_timezone()`（票 M1 從這裡
    抽出的姊妹函式）——這裡只是把它給的時區換成日期。
    """
    return datetime.now(org_timezone(conn, org_id=org_id)).date()


def get_intake_budget_limit(conn: db.Conn | None = None, *, org_id: str) -> float:
    """AI 生成的花費上限：DB 設定 > app/intake/script.py 的 DEFAULT_BUDGET。

    設定鍵沿用 intake_budget_limit 這個舊名（原本只管建檔精靈），票 M2 起改成全站共用的
    同一道上限——建檔精靈、品牌智庫的產品調研／交接包修復、廣告分支的計畫與素材生成，
    全部比對同一個值，不各自訂一個（不要改設定鍵名是為了不動 DB schema／既有設定值）。

    DB 裡存的是壞值（空字串、非數字）時當作沒設定，回預設值——設定頁壞一格不該讓精靈開不起來。
    """
    from app.intake import script  # 延遲 import：避免 core 在 import 期就相依 intake

    raw = get_setting(conn, INTAKE_BUDGET_SETTING, org_id=org_id)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return script.DEFAULT_BUDGET


def brand_llm_spent(conn: db.Conn, brand_id: str, *, since: str | None = None) -> float:
    """這個品牌到目前為止真的花了多少 AI 生成費用（美元，累加所有成功呼叫的 llm_task.cost）。

    跨模組共用的花費上限查詢（票 M2）：品牌智庫調研、廣告分支計畫／素材生成都算進來，
    不分模組各自統計——上限本來就是同一道。

    since：只給下限（票 05 駕駛艙油錢錶「本月已花」用，since＝當月 1 號）。不設上限——
    llm_task.started_at 是完整時間戳記，跟純日期字串比較會有字串長度誤判（"2026-08-05"
    小於 "2026-08-05T09:00:00"），且花費紀錄本來就不會有未來時間，不需要上限。
    """
    sql = "SELECT SUM(cost) AS n FROM llm_task WHERE brand_id = %s AND status = 'succeeded'"
    params: list = [brand_id]
    if since:
        sql += " AND started_at >= %s"
        params.append(since)
    row = conn.execute(sql, params).fetchone()
    # BUG 修復（route=C 02-3c）：SUM(cost) 讀回來是 numeric -> Decimal，這裡宣告
    # -> float；讀取端單一收口轉型，呼叫端（budget_exceeded_message 的 spent + cost）
    # 才能放心跟 float 算術，不必自己 float() 一次。
    return float(row["n"] or 0.0)


def budget_exceeded_message(conn: db.Conn, brand_id: str, cost: float, *, org_id: str,
                            action: str = "這次調研",
                            fallback_hint: str = "或先用「新增這個產品」手動建立。") -> str | None:
    """這個品牌已花的錢加上這次預估要花的，會不會超過花費上限。沒有超過回 None；
    超過回一句人話錯誤，呼叫端接住轉成表單錯誤或導頁訊息（票 M2：原本只有品牌智庫的
    產品調研／交接包修復在用這道檢查，廣告分支的計畫與素材生成現在也共用同一個函式
    ——同一道上限、同一套訊息文字，不要各自造一份）。

    幣別統一為美元（US$）並在訊息中明講——跟 app/llm/pricing.calculate_cost() 回傳的
    真實成本同一幣別直接比較，不做匯率換算（避免引入會過期的匯率常數；理由詳見
    app/intake/script.py DEFAULT_BUDGET 註解，票 M2）。

    org_id 必填（票 04-0）：本檔（app.core）依 LAYER_ORDER 不得 import app.brand_intelligence
    自己反查，呼叫端（app.brand_web 等分支層）已經有 brand_id，反查 org_id 傳進來。
    """
    spent = brand_llm_spent(conn, brand_id)
    limit = get_intake_budget_limit(conn, org_id=org_id)
    if spent + cost > limit:
        return (
            f"這個品牌目前已經花了 US$ {spent:.2f}，{action}預估要花 US$ {cost:.2f}，"
            f"會超過設定頁目前的 US$ {limit:.2f} 花費上限。可以到「設定」頁調高上限，{fallback_hint}"
        )
    return None
