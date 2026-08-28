"""app/core/settings.py — 全站設定（app_setting 表）的最小存取層。

只做兩件事：讀一個鍵、寫一個鍵；外加三個語意函式（金鑰、模型、精靈花費上限），
把「DB 設定 > 環境變數 > 程式預設」這條優先順序寫在一個地方，呼叫端不各自實作。

介面契約見 docs/design/07-settings-and-intake-contract.md。
"""

from __future__ import annotations

import os

import psycopg

from app.core import db

API_KEY_SETTING = "anthropic_api_key"
API_KEY_ENV_VAR = "ANTHROPIC_API_KEY"
LLM_MODEL_SETTING = "llm_model"
LLM_MODEL_ENV_VAR = "BRAND_OS_LLM_MODEL"
DEFAULT_LLM_MODEL = "claude-opus-5"
INTAKE_BUDGET_SETTING = "intake_budget_limit"
# 整組複製提示詞的自訂開頭（票 11-copy-flows；ADR 0008 三）：全站一份，不分品牌——
# 它描述的是「使用者用哪個生圖工具」，不是品牌事實。
IMAGE_PROMPT_HEADER_SETTING = "image_prompt_batch_header"


def get_setting(conn: db.Conn | None, key: str, default=None):
    """讀一個設定值；沒設過（或 app_setting 表還沒建起來）回 default。

    conn 傳 None 代表「自己開一條短命連線讀」——給 providers 這種手上沒有連線的呼叫端用。
    表不存在時不噴錯誤碼而是回 default（principles 16 優雅缺席：沒設定就是沒設定）。

    票 02-3a：連線模型改成一條連線一個 request／一個背景工作（app/core/db.py
    connection()），不再有「自己開一條短命連線、用完手動 close()」這件事——沒帶 conn
    進來就跟連線池借一條、離開 with 區塊自動歸還。
    """
    if conn is not None:
        return _get_setting(conn, key, default)
    with db.connection() as owned_conn:
        return _get_setting(owned_conn, key, default)


def _get_setting(conn: db.Conn, key: str, default=None):
    try:
        row = conn.execute("SELECT value FROM app_setting WHERE key = %s", (key,)).fetchone()
    except psycopg.Error:
        return default
    return row["value"] if row else default


def set_setting(conn: db.Conn, key: str, value: str) -> None:
    """寫一個設定值（有則覆蓋）。value 一律存字串，數字請呼叫端先 str()。

    不寫 audit_log：app_setting 沒有 brand_id，也不是品牌事實；金鑰更不該被抄進稽核紀錄。
    """
    conn.execute(
        """INSERT INTO app_setting (org_id, key, value, updated_at) VALUES (%s, %s, %s, %s)
           ON CONFLICT(org_id, key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
        (db.DEV_ORG_ID, key, str(value), db.now_utc()),
    )
    conn.commit()


def get_api_key(conn: db.Conn | None = None) -> str | None:
    """AI 金鑰：環境變數 ANTHROPIC_API_KEY 優先 > DB 設定回退 > None（代表尚未設定）。

    修憲落地 M4：優先序反轉。環境變數不落地在任何檔案；DB 裡的金鑰是明文，
    而決策 0008 指示使用者把整個 `backups/` 資料夾同步進雲端硬碟，明文金鑰會跟著
    每日備份外流。環境變數優先，才不會出現「使用者已經設好環境變數，AI 功能卻仍在
    偷用 DB 裡那把舊金鑰」的情況。
    """
    return os.environ.get(API_KEY_ENV_VAR) or get_setting(conn, API_KEY_SETTING) or None


def api_key_source(conn: db.Conn | None = None) -> str | None:
    """get_api_key() 實際採用的來源：'env'（環境變數，安全）／'db'（資料庫回退，明文、
    會被備份）／None（兩邊都沒設）。設定頁靠這個誠實顯示金鑰來源，不讓使用者以為
    改用了環境變數、其實系統還在用 DB 裡的舊值（修憲落地 M4）。"""
    if os.environ.get(API_KEY_ENV_VAR):
        return "env"
    if get_setting(conn, API_KEY_SETTING):
        return "db"
    return None


def clear_api_key_from_db(conn: db.Conn) -> None:
    """把 DB 裡存的金鑰刪掉，不影響環境變數來源（修憲落地 M4）。

    這是不可逆動作，只能由使用者在設定頁明確按下按鈕才會呼叫——本函式本身不自動執行、
    不在任何啟動流程或排程中被呼叫。刪掉後若環境變數也沒設，get_api_key() 回 None，
    等同「尚未設定金鑰」，既有的優雅缺席處理（例如 providers 的人話錯誤）照常生效。
    """
    conn.execute("DELETE FROM app_setting WHERE key = %s", (API_KEY_SETTING,))
    conn.commit()


def get_llm_model(conn: db.Conn | None = None) -> str:
    """使用的模型：DB 設定 > 環境變數 BRAND_OS_LLM_MODEL > 預設 claude-opus-5。"""
    return (
        get_setting(conn, LLM_MODEL_SETTING)
        or os.environ.get(LLM_MODEL_ENV_VAR)
        or DEFAULT_LLM_MODEL
    )


def get_intake_budget_limit(conn: db.Conn | None = None) -> float:
    """AI 生成的花費上限：DB 設定 > app/intake/script.py 的 DEFAULT_BUDGET。

    設定鍵沿用 intake_budget_limit 這個舊名（原本只管建檔精靈），票 M2 起改成全站共用的
    同一道上限——建檔精靈、品牌智庫的產品調研／交接包修復、廣告分支的計畫與素材生成，
    全部比對同一個值，不各自訂一個（不要改設定鍵名是為了不動 DB schema／既有設定值）。

    DB 裡存的是壞值（空字串、非數字）時當作沒設定，回預設值——設定頁壞一格不該讓精靈開不起來。
    """
    from app.intake import script  # 延遲 import：避免 core 在 import 期就相依 intake

    raw = get_setting(conn, INTAKE_BUDGET_SETTING)
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


def budget_exceeded_message(conn: db.Conn, brand_id: str, cost: float, *,
                            action: str = "這次調研",
                            fallback_hint: str = "或先用「新增這個產品」手動建立。") -> str | None:
    """這個品牌已花的錢加上這次預估要花的，會不會超過花費上限。沒有超過回 None；
    超過回一句人話錯誤，呼叫端接住轉成表單錯誤或導頁訊息（票 M2：原本只有品牌智庫的
    產品調研／交接包修復在用這道檢查，廣告分支的計畫與素材生成現在也共用同一個函式
    ——同一道上限、同一套訊息文字，不要各自造一份）。

    幣別統一為美元（US$）並在訊息中明講——跟 app/llm/pricing.calculate_cost() 回傳的
    真實成本同一幣別直接比較，不做匯率換算（避免引入會過期的匯率常數；理由詳見
    app/intake/script.py DEFAULT_BUDGET 註解，票 M2）。
    """
    spent = brand_llm_spent(conn, brand_id)
    limit = get_intake_budget_limit(conn)
    if spent + cost > limit:
        return (
            f"這個品牌目前已經花了 US$ {spent:.2f}，{action}預估要花 US$ {cost:.2f}，"
            f"會超過設定頁目前的 US$ {limit:.2f} 花費上限。可以到「設定」頁調高上限，{fallback_hint}"
        )
    return None
