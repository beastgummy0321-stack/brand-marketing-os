"""app/meta/repository.py — private DB access for app/meta. Importers: app/meta/routes.py,
app/meta/daily_pull.py, and (since 票 S1) app/schedule/routes.py:60 — the schedule layer
sits above app.meta in LAYER_ORDER and is allowed to read this module's public functions
directly (container contract §1 governs what crosses a package boundary, not which package
does the crossing).
five read functions this ticket adds below. Never imported from outside app/schedule or
app/meta.

One function here is not pure DB access: `campaign_ids_by_exact_name` reads the account's
live campaign list through `graph.py`, because a campaign built by hand and left paused
exists on the platform but has no rows in any of our tables. Its docstring carries the
reason; everything else below is Postgres only.

Four tables (see supabase/migrations/20260829000002_meta_baseline.sql and
20260830000004_meta_entity_spend.sql):
    meta_credential        — one row per org, points at the Vault secret (never the token)
    meta_ad_account        — accounts a token has revealed, org-scoped; also carries
                              last_pull_at (ticket 05 — set only on a *successful* pull)
    brand_meta_ad_account  — which brand(s) use which account(s), the m:n mapping
    meta_entity_spend      — per account, per level (campaign/adset/ad), per entity, per day
                              (ticket S1, replaces meta_campaign_spend); org+account scoped,
                              not brand-scoped, for the same reason meta_ad_account isn't (an
                              account can serve more than one brand). `level` is NOT NULL
                              with no default on purpose — a WHERE clause can be forgotten,
                              a NOT NULL column cannot, and the three levels share one table.

The token itself never touches meta_credential (or any other table, audit_log, or a log
line) — it lives in Supabase Vault. `save_token` does not give the secret a name:
`vault.secrets` has a unique index on `name` in one global schema, while
app/tests/conftest.py gives every test module its own Postgres schema — a named secret
would collide across test modules and across organisations. `meta_credential.secret_id`
is the index instead.
"""

from datetime import date

import app.shared.web as web
from app.core import cleanup
from app.core.db import Conn, ConnProxy, jsonb, new_id, now_utc
from app.meta import graph

_AnyConn = Conn | ConnProxy


# ---- Vault ----------------------------------------------------------------------

def _vault_create_secret(conn: _AnyConn, token: str) -> str:
    # 票 R3b：走 core_vault_save_secret()（p_secret_id 傳 NULL＝建新的），不再直接呼叫
    # vault.create_secret。
    row = conn.execute("SELECT core_vault_save_secret(NULL, %s) AS id", (token,)).fetchone()
    assert row is not None, "core_vault_save_secret() 是純量函式，SELECT 一定回一列"
    return str(row["id"])


def _vault_update_secret(conn: _AnyConn, secret_id: str, token: str) -> None:
    conn.execute("SELECT core_vault_save_secret(%s, %s)", (secret_id, token))  # 票 R3b


# ---- meta_credential --------------------------------------------------------------

def get_credential(conn: _AnyConn, org_id: str) -> dict | None:
    return conn.execute(
        "SELECT org_id, secret_id, token_tail, updated_at FROM meta_credential WHERE org_id = %s",
        (org_id,),
    ).fetchone()


def save_token(conn: _AnyConn, org_id: str, token: str) -> str:
    """建立或更新這個組織的權杖：貼過一次就是更新（同一個 Vault secret 覆寫），
    回傳 token_tail 供路由組成人話。呼叫端已經先用這個權杖打過 Graph API 確認能用，
    這裡只管落地——不驗證。"""
    tail = token[-4:]
    existing = get_credential(conn, org_id)
    if existing:
        _vault_update_secret(conn, existing["secret_id"], token)
        conn.execute(
            "UPDATE meta_credential SET token_tail = %s, updated_at = %s WHERE org_id = %s",
            (tail, now_utc(), org_id),
        )
    else:
        secret_id = _vault_create_secret(conn, token)
        conn.execute(
            "INSERT INTO meta_credential (org_id, secret_id, token_tail, updated_at)"
            " VALUES (%s, %s, %s, %s)",
            (org_id, secret_id, tail, now_utc()),
        )
    return tail


def get_token(conn: _AnyConn, org_id: str) -> str | None:
    """讀回這個組織的真正權杖（從 Vault 解密），給背景拉取用——`get_credential` 只回
    `secret_id` 指標，這裡才是真正的 Vault round-trip 讀值端（同 repository 頂端說明的
    write 端 `_vault_create_secret`/`_vault_update_secret` 對稱）。"""
    credential = get_credential(conn, org_id)
    if credential is None:
        return None
    # 票 R3b：走 core_vault_read_secret()，不再直接讀 vault.decrypted_secrets（不在票的
    # 「Measured facts」清單裡，但同一份 grep 閘門 [8] 涵蓋這一行——用票已經定義好的同一道
    # 門，不是發明新東西）。
    row = conn.execute(
        "SELECT core_vault_read_secret(%s) AS decrypted_secret",
        (credential["secret_id"],),
    ).fetchone()
    return row["decrypted_secret"] if row else None


# ---- meta_ad_account ----------------------------------------------------------------

def upsert_accounts(conn: _AnyConn, org_id: str, accounts: list[dict]) -> None:
    """Upsert，絕不刪除——一個權杖的可見範圍縮小了，不該連鎖刪掉使用者已經做好的品牌
    綁定（brand_meta_ad_account 外鍵 ON DELETE CASCADE 會跟著清掉，見設計檔）。"""
    for acc in accounts:
        conn.execute(
            "INSERT INTO meta_ad_account (id, org_id, account_id, name, currency, connected_at)"
            " VALUES (%s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (org_id, account_id)"
            " DO UPDATE SET name = excluded.name, currency = excluded.currency",
            (new_id("mad"), org_id, acc["account_id"], acc["name"], acc["currency"], now_utc()),
        )


def list_accounts(conn: _AnyConn, org_id: str) -> list:
    return list(conn.execute(
        "SELECT id, account_id, name, currency, connected_at FROM meta_ad_account"
        " WHERE org_id = %s ORDER BY id",
        (org_id,),
    ))


def get_account(conn: _AnyConn, org_id: str, ad_account_id: str) -> dict | None:
    """org 篩選是租戶界線：另一個組織的帳號 id，這裡直接查不到（呼叫端因此回 404）。"""
    return conn.execute(
        "SELECT id, account_id, name, currency FROM meta_ad_account"
        " WHERE org_id = %s AND id = %s",
        (org_id, ad_account_id),
    ).fetchone()


def list_bound_accounts(conn: _AnyConn, org_id: str) -> list:
    """這個組織『至少綁了一個品牌』的帳號（[{"id","account_id"}]）——票 05 的每日拉取
    只打這些帳號：連了帳號但還沒綁任何品牌的，還沒有人真的在用它。"""
    return list(conn.execute(
        "SELECT DISTINCT maa.id, maa.account_id FROM meta_ad_account maa"
        " JOIN brand_meta_ad_account bmaa ON bmaa.ad_account_id = maa.id"
        " WHERE maa.org_id = %s ORDER BY maa.id",
        (org_id,),
    ))


def orgs_with_bound_accounts(conn: _AnyConn) -> list:
    """跨組織列舉『至少有一個綁定帳號』的組織 id——刻意不帶 org_id 篩選，因為這不是
    一個 handler，是每日觸發腳本用來決定要對哪些組織各自 defer 一個 job 的清單
    （daily_pull.py `__main__`；每個真正碰資料表的動作仍然是 org_id 範圍內的
    run_daily_pull()，這支只負責「有誰」）。"""
    rows = conn.execute(
        "SELECT DISTINCT maa.org_id FROM meta_ad_account maa"
        " JOIN brand_meta_ad_account bmaa ON bmaa.ad_account_id = maa.id"
    )
    return [r["org_id"] for r in rows]


def mark_pull_succeeded(conn: _AnyConn, org_id: str, ad_account_id: str) -> None:
    """只在成功時呼叫——失敗留舊資料、也留舊的『上次成功時間』（票 05 done-check）。"""
    conn.execute(
        "UPDATE meta_ad_account SET last_pull_at = %s WHERE org_id = %s AND id = %s",
        (now_utc(), org_id, ad_account_id),
    )


# ---- meta_entity_spend ------------------------------------------------------------------

# 三個層級的字彙，全站一份。`meta_entity_spend.level` 是 NOT NULL 沒有預設值（SPEC §2.4）：
# WHERE 條件會被忘記，NOT NULL 欄位不會——三層的列躺在同一張表裡，少篩一次就是把同一筆錢
# 算三遍。
LEVELS = ("campaign", "adset", "ad")


def _jsonb_or_null(value):
    """Meta 沒回這個 key 就存 SQL NULL，不是 JSON 的 `null`——兩者在 jsonb 欄位裡是不同的
    東西，而 `jsonb_array_elements('null'::jsonb)` 會直接報錯，一列就能讓 spend_summary
    的 CPA 查詢 500。存 SQL NULL 也才問得出「這一列到底有沒有 actions」。"""
    return jsonb(value) if value is not None else None


def upsert_entity_spend(
    conn: _AnyConn, org_id: str, ad_account_id: str, rows: list[dict],
) -> None:
    """Upsert 一個帳號的成效列，一列＝一個實體（活動／廣告組／廣告）的一天。

    `(ad_account_id, level, entity_id, spend_date)` 的唯一索引（migration）是重跑不重複、
    不 double count 的真正機制——這裡只是照著那個索引寫 ON CONFLICT，機制在資料庫，不是
    這段程式碼自己防呆。

    **沒有 `day` 參數了**（票 S1 D7）：`time_increment: 1` 的一次回應橫跨整個日期範圍，
    每一列自己帶從 `date_start` 換算來的 `spend_date`（見 `graph._to_entity_row`）。日期
    若從迴圈變數來，一整個月的資料會全部疊到同一天上，而且看起來完全正常。

    Meta 沒回的（實體, 日）組合就是沒有列，這裡也不補零（票 S1 D8）：2026-08-30 對真帳號
    實測，廣告層 35 個實體 x 91 天有 81% 的組合根本沒有列（GRILL.md §1(d)）。「沒投遞」跟
    「投了沒成效」是兩件事，補一列 0 會把前者變成後者。逐列 `conn.execute`（不是
    `executemany`）比照這個模組既有的 `upsert_accounts` 寫法——沒量過真的多帳號多層級
    backfill 的耗時，不先為了一個沒量過的效能數字換寫法。"""
    pulled_at = now_utc()  # 同一次拉取共用一個時間戳：它記的是「這批數字多新」，不是逐列時刻
    for row in rows:
        conn.execute(
            "INSERT INTO meta_entity_spend"
            " (id, org_id, ad_account_id, level, entity_id, entity_name, campaign_id,"
            "  adset_id, ad_id, spend_date, spend, impressions, clicks, roas, actions,"
            "  action_values, attribution_window, pulled_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (ad_account_id, level, entity_id, spend_date) DO UPDATE SET"
            "  entity_name = excluded.entity_name, campaign_id = excluded.campaign_id,"
            "  adset_id = excluded.adset_id, ad_id = excluded.ad_id, spend = excluded.spend,"
            "  impressions = excluded.impressions, clicks = excluded.clicks,"
            "  roas = excluded.roas, actions = excluded.actions,"
            "  action_values = excluded.action_values,"
            "  attribution_window = excluded.attribution_window, pulled_at = excluded.pulled_at",
            (new_id("mes"), org_id, ad_account_id, row["level"], row["entity_id"],
             row["entity_name"], row["campaign_id"], row["adset_id"], row["ad_id"],
             row["spend_date"], row["spend"], row["impressions"], row["clicks"], row["roas"],
             _jsonb_or_null(row["actions"]), _jsonb_or_null(row["action_values"]),
             row["attribution_window"], pulled_at),
        )


def bound_account_ids_for_brand(conn: _AnyConn, org_id: str, brand_id: str) -> list:
    rows = conn.execute(
        "SELECT ad_account_id FROM brand_meta_ad_account WHERE org_id = %s AND brand_id = %s",
        (org_id, brand_id),
    )
    return [r["ad_account_id"] for r in rows]


def campaign_ids_by_exact_name(
    conn: _AnyConn, org_id: str, ad_account_ids: list, name: str,
) -> list:
    """票 11／T3b：這批帳號裡，活動名稱逐字（區分大小寫、不 trim、不正規化）等於 `name`
    的 `[{"campaign_id", "external_status"}]`——外殼精準比對的唯一資料來源，`org_id`
    是租戶界線。`external_status` 是平台當下的 `effective_status`，原樣帶出去，呼叫端
    （`app.schedule._run_bind`）綁定時原樣存進 `channel_entity_map`（ADR 0055 §4）。

    資料來源是**平台上的活動清單**（`graph.list_campaigns`），不是 `meta_entity_spend`。
    2026-08-29 實測發現的缺陷：手動建好、維持關閉的活動沒有任何 insights 列，靠花費表比對
    永遠是「配對失敗」——而「先建成關閉、配對確認、才開跑」正是這條手動路徑該有的順序。
    比對完存下 id，之後讀數字一律靠 id（改名不斷線），那部分仍然走 meta_entity_spend。
    """
    if not ad_account_ids:
        return []
    token = get_token(conn, org_id)
    if token is None:
        return []  # 這個組織還沒接權杖：沒有可比對的清單，交給呼叫端當「配對失敗」處理
    rows = conn.execute(
        "SELECT account_id FROM meta_ad_account WHERE org_id = %s AND id = ANY(%s)",
        (org_id, ad_account_ids),
    )
    matched: dict = {}  # campaign_id -> effective_status，去重（見底下說明）
    for row in rows:
        try:
            campaigns = graph.list_campaigns(token, row["account_id"])
        except graph.GraphError as exc:
            raise web.ApiError(
                502, "meta_unreachable", f"連不上 Meta，沒辦法比對名稱：{exc.message}"
            ) from exc
        for c in campaigns:
            if c["name"] == name:
                matched[c["campaign_id"]] = c["effective_status"]
    return [{"campaign_id": cid, "external_status": status}
            for cid, status in sorted(matched.items())]


def last_pull_at(conn: _AnyConn, org_id: str, ad_account_ids: list):
    """這批帳號裡『最早的』上次成功拉取時間——品牌可能綁了不只一個帳號，畫面要誠實
    反映「最舊鮮度」，不是挑一個看起來最新的帳號蓋過去（票 05：失敗要讓使用者看得出
    哪些數字舊了）。一個帳號都沒有、或全部都還沒成功拉過，回 None。"""
    if not ad_account_ids:
        return None
    row = conn.execute(
        "SELECT min(last_pull_at) AS t FROM meta_ad_account WHERE org_id = %s AND id = ANY(%s)",
        (org_id, ad_account_ids),
    ).fetchone()
    return row["t"] if row else None


_EMPTY_TOTAL = {
    "spend": 0.0, "impressions": 0, "clicks": 0,
    "roas": None, "ctr": None, "cpc": None, "cpm": None, "cpa": None,
}

# 轉換目標 → `actions` 裡「算一次轉換」的 action_type 優先序：對得上的**第一個**就是那一列
# 的轉換數，不是全部相加（為什麼不能相加，見 `_CONVERSIONS_LATERAL` 上方的說明）。
#
# 對照來源：`app/methodology/README.md`「平台中立值 → Meta 標準事件對照」，出處是 Meta
# Pixel 標準事件官方參考文件（該檔記錄 2026-08-07 查證）。那張表列的是「這個目標相關的
# 標準事件」，不是「哪一個算一次獲客」：`purchase` 那列還寫了 AddToCart／InitiateCheckout，
# 這裡刻意不收——把加入購物車當成一次獲客，CPA 會被壓成一個假的好看數字。
#
# 大小寫：README 寫的是 Pixel 事件名（`Purchase`、`Lead`、`Schedule`），insights 的
# `actions` 回的是小寫底線形式。除了 purchase 那一組（下面有實測）之外，`lead`／
# `complete_registration`／`schedule` 三個都是**照這個規則推出來的形式，還沒有在真資料裡
# 看過**。
#
# purchase 直接沿用 `graph._ROAS_ACTION_PRIORITY`：同一組同義字、同一份優先序，分成兩份
# 只會各自漂移（動那份請一起看這裡）。2026-08-30 實測（GRILL.md §1(a)）該帳號的
# `purchase_roas` 回的正是它的第一個 `omni_purchase`；同一次實測 `actions` 裡看到的是
# `link_click`／`landing_page_view`／`post_engagement`／`page_engagement`／`view_content`／
# `omni_view_content`／`onsite_conversion.messaging_conversation_started_7d`（GRILL.md
# §1(b)）——**一個成交事件都沒有**，所以這個帳號今天算出來的 CPA 會是 NULL。那是誠實的
# 答案，不是壞掉。
#
# 目標的定義域正是 `app.brand_intelligence.repository.CONVERSION_GOALS`（"purchase"／
# "lead"／"booking"／"awareness"），但**不從那裡 import**——app/meta 不讀別的模組的常數
# （集裝箱憲章：接口即契約，不是互相 import 內部細節）；`awareness` 對應到空 tuple，
# 沒有分母，CPA 一律 NULL。
_CONVERSION_ACTION_PRIORITY: dict[str, tuple[str, ...]] = {
    "purchase": graph._ROAS_ACTION_PRIORITY,
    "lead": ("lead", "complete_registration"),
    "booking": ("schedule",),
    "awareness": (),  # README：無對應標準事件——沒有分母，CPA 一律 NULL
}


# CPA 的分母：**每一列先各自算出自己的轉換數，再相加**。LATERAL + LIMIT 1 是一列進一列出，
# 所以 SUM(spend)、count(*) 的列數完全沒變，才能跟 roas 待在同一個 SELECT 裡。
#
# 為什麼不能直接 join `jsonb_array_elements` 再 SUM：同一次成交會被好幾個同義 action_type
# 各回報一次（`omni_purchase`／`onsite_web_purchase`／`offsite_conversion.fb_pixel_purchase`，
# graph.py 檔頭已記錄這個形狀）——直接展開再 join 等於把那一列的 spend 乘上同義字的個數，
# 連 SUM(spend)、ROAS、CPC、CPM 全部跟著錯。`jsonb_typeof(...) = 'array'`：actions 是第三方
# 原封不動存進來的，SQL NULL、JSON null、哪天回一個物件，都不該讓整支看錢的查詢 500——
# 保護讓該列 CPA 是 NULL，其餘數字照算。
_CONVERSIONS_LATERAL = (
    " LEFT JOIN LATERAL ("
    "   SELECT (act.entry->>'value')::numeric AS conversions"
    "     FROM unnest(%s::text[]) WITH ORDINALITY AS want(action_type, priority)"
    "     JOIN jsonb_array_elements("
    "            CASE WHEN jsonb_typeof(mes.actions) = 'array'"
    "                 THEN mes.actions ELSE '[]'::jsonb END) AS act(entry)"
    "       ON act.entry->>'action_type' = want.action_type"
    "    ORDER BY want.priority LIMIT 1"
    " ) conv ON TRUE"
)

# 三個比率，兩支查詢共用同一份字串——分開寫會漂移，而「最下面那列總計的 CTR 跟上面每一列
# 的 CTR 用不同定義算出來」是使用者永遠看不出來的錯。
#
# 單位：ctr 是**百分比**（乘 100），因為 Meta 自己的 `ctr` 欄位回的就是百分比，畫面上的
# 數字要跟使用者在廣告管理員看到的對得起來；cpm 是每千次曝光（乘 1000）；cpc 是每次點擊。
#
# 分母 0 一律走 NULLIF → 整個值是 NULL 不是 0。曝光 5,000、點擊 0 的 ctr 是 0（真的沒人
# 點），曝光 0 的 ctr 是 NULL（根本沒得算）——這張表 null≠0 的規矩，對每一個數字都成立。
# SUM(bigint) 在 Postgres 回 numeric，所以這裡不會發生整數除法把 0.03 變成 0。
#
# **這三個不套用下面 roas 的 bool_and 規則**：impressions／clicks 是 Meta 每天一定回報的
# NOT NULL 欄位，某一天沒有 ROAS，不代表那天的點擊數不知道；把 ctr 一起拖成 None 是另一個
# 方向的不誠實（SPEC §2.4 P6）。cpa 不在這裡——它讀的 actions 跟 roas 讀的 purchase_roas
# 一樣稀疏（同一份 GRILL 決定1(d)／SPEC §3.3 實測：560 個有花費的廣告日只有 191 天有
# purchase_roas），所以 cpa 要跟 roas 一樣套 bool_and，見下面它自己的定義。
_RATE_METRICS = (
    # 前導逗號：兩處呼叫端都是接在 "... AS roas" 後面直接字串相加，這裡自己帶逗號，
    # 呼叫端不必各自記得補。
    ","
    " SUM(clicks) * 100.0 / NULLIF(SUM(impressions), 0) AS ctr,"
    " SUM(spend) / NULLIF(SUM(clicks), 0) AS cpc,"
    " SUM(spend) * 1000.0 / NULLIF(SUM(impressions), 0) AS cpm"
)

# cpa 沒有跟 ctr/cpc/cpm 放在 _RATE_METRICS 裡：它讀的 conv.conversions 來自
# _CONVERSIONS_LATERAL，任何一列的 actions 對不上（含 actions 本身是 SQL NULL）都會讓
# `conv.conversions` 是 SQL NULL；Postgres 的 SUM() 會跳過 NULL 不當 0 加總，所以沒有這條
# bool_and 保護的話，一個範圍裡「有花費、沒追蹤到轉換」的天數，花費照樣進分子、卻完全不
# 進分母——印出一個過度樂觀的假 CPA，這正是那部分花費最沒被追蹤到的時候。
# 跟 roas 用同一條規則、同一個理由：range 裡只要有一列「未追蹤」（conversions IS NULL），
# 整組直接回 None，不能假裝那些天貢獻了 0 次轉換。
_CPA_METRIC = (
    ","
    " CASE WHEN bool_and(conv.conversions IS NOT NULL)"
    "      THEN SUM(spend) / NULLIF(SUM(conv.conversions), 0) ELSE NULL END AS cpa"
)

# 三個層級躺在同一張表，這個 WHERE 少了 `level` 就是每一筆錢算三遍——所以它也只有一份。
_SPEND_WHERE = (
    " WHERE mes.org_id = %s AND mes.ad_account_id = ANY(%s) AND mes.level = %s"
    "   AND mes.spend_date >= %s AND mes.spend_date < %s"
)


def spend_summary(
    conn: _AnyConn, org_id: str, ad_account_ids: list, month_start: date, month_end: date,
    *, level: str, conversion_goal: str | None = None,
) -> dict:
    """[month_start, month_end) 這個半開區間裡，**這一層**逐實體加總＋一列總計。

    `level` 必填、只能用關鍵字傳、沒有預設值（SPEC §2.4，票 S1）：campaign／adset／ad
    三層的列在同一張表裡，漏掉它就是把同一筆錢算三遍。忘記傳會是 TypeError，打錯字會是
    ValueError——不會是一個看起來很合理、只是大三倍的數字。

    ROAS 是比率，加總不能直接平均（票 05：「加總比率沒有意義」）——用花費加權
    （SUM(spend*roas)/SUM(spend)，數學上等於「這個範圍的總營收 ÷ 總花費」）算出誠實的
    總 ROAS；但只要範圍裡有任何一列 roas 是 NULL（未追蹤），代表那部分花費的營收根本
    不知道，總數就不能假裝把它算進去了——整組（那個實體的小計，或最下面的總計）直接
    回 None，畫面一樣顯示未追蹤，不印一個不真實的數字。

    ctr／cpc／cpm／cpa 跟 roas 放同一個 SELECT，分母是 0 就回 None、不是 0（SPEC §2.4
    P6）。ctr／cpc／cpm 不套用下面那條 roas 的 bool_and 規則，因為 impressions／clicks 是
    Meta 每天都會回報的 NOT NULL 欄位，沒有 ROAS 不代表那天的點擊數不知道（見
    `_RATE_METRICS` 上方的說明）；但 cpa 要套——它讀的 actions 跟 roas 讀的
    purchase_roas 一樣稀疏（GRILL 決定1(d)／SPEC §3.3 實測：560 個有花費的廣告日只有
    191 天有 purchase_roas），沒追蹤到轉換的一天不是「轉換數是 0」的一天，把它當 0
    加總、花費卻照樣算進分子，印出來的是一個過度樂觀的假 CPA（見 `_CPA_METRIC` 上方的
    說明）。

    `conversion_goal` 是**參數，不是這裡去查的東西**（票 S1 D4）：CPA 該用哪個
    action_type 由品牌的 `brand.conversion_goal` 決定，而 `brand` 是別的模組的表（集裝箱
    憲章：不碰別人的表）——呼叫端讀好了傳進來。沒傳、或這個目標沒有對應事件
    （awareness）、或整個範圍裡一次都沒回報過那個事件，CPA 就是 None，不是 0。"""
    if level not in LEVELS:
        raise ValueError(f"level 只能是 {'/'.join(LEVELS)} 其中之一")
    if not ad_account_ids:
        return {"entities": [], "total": dict(_EMPTY_TOTAL)}
    # 沒設定目標（None）走 `or ""`：查不到 → 空陣列 → 沒有任何 action 對得上 → CPA 是
    # NULL，跟 awareness 同一條路，不必為「沒設定」另外寫一支 SQL。tuple 在 psycopg3 會被
    # 當成 record 送出去，array 參數一定要是 list。
    priority = list(_CONVERSION_ACTION_PRIORITY.get(conversion_goal or "", ()))
    args = (priority, org_id, ad_account_ids, level, month_start, month_end)
    entities = conn.execute(
        # 一個實體一列，GROUP BY 只按 entity_id——名稱不進 GROUP BY（票 11 審查發現）：
        # 使用者月中在平台上改名，改名前後的日列各自留著自己那天的 entity_name，按
        # (id, 名稱) 分組會把同一個實體裂成兩列、各拿半個月的花費。顯示的名稱取「最後
        # 一天用的那個」，也就是使用者現在在平台上看得到的那個。
        "SELECT entity_id,"
        " (array_agg(entity_name ORDER BY spend_date DESC))[1] AS entity_name,"
        " SUM(spend) AS spend,"
        " SUM(impressions) AS impressions, SUM(clicks) AS clicks,"
        " CASE WHEN bool_and(roas IS NOT NULL)"
        "      THEN SUM(spend * roas) / NULLIF(SUM(spend), 0) ELSE NULL END AS roas"
        + _RATE_METRICS
        + _CPA_METRIC
        + " FROM meta_entity_spend mes"
        + _CONVERSIONS_LATERAL
        + _SPEND_WHERE
        + " GROUP BY entity_id ORDER BY entity_id",
        args,
    ).fetchall()
    total = conn.execute(
        "SELECT COALESCE(SUM(spend), 0) AS spend, COALESCE(SUM(impressions), 0) AS impressions,"
        " COALESCE(SUM(clicks), 0) AS clicks,"
        " CASE WHEN count(*) > 0 AND bool_and(roas IS NOT NULL)"
        "      THEN SUM(spend * roas) / NULLIF(SUM(spend), 0) ELSE NULL END AS roas"
        + _RATE_METRICS
        + _CPA_METRIC
        + " FROM meta_entity_spend mes"
        + _CONVERSIONS_LATERAL
        + _SPEND_WHERE,
        args,
    ).fetchone()
    assert total is not None, "聚合查詢沒有 GROUP BY，SELECT 一定回一列"
    # 鍵名是 entity_*：一列可能是活動、廣告組或廣告（票 S1 D2）。HTTP 回應維持 campaign_*
    # 不變，由 app/meta/routes.py brand_spend 對回去——這張票不是 API 契約變更，
    # frontend/src/lib/metaApi.ts 與 CockpitPage.tsx 一個字都不動。
    return {
        "entities": [_spend_row(r) for r in entities],
        "total": _spend_row(total),
    }


def _spend_row(row: dict) -> dict:
    """numeric（Decimal）欄位單一收口轉 float，讀取端只轉這一次（比照
    app/orders/repository.py 的既有慣例）。None 一律原樣穿過——未追蹤就是未追蹤，
    分母是 0 就是「算不出來」，兩種都不能在這裡變成 0.0。"""
    out = {
        "spend": float(row["spend"]), "impressions": int(row["impressions"]),
        "clicks": int(row["clicks"]), "roas": _float_or_none(row["roas"]),
        "ctr": _float_or_none(row["ctr"]), "cpc": _float_or_none(row["cpc"]),
        "cpm": _float_or_none(row["cpm"]), "cpa": _float_or_none(row["cpa"]),
    }
    if "entity_id" in row:  # 總計那一列沒有 entity_id
        out["entity_id"] = row["entity_id"]
        out["entity_name"] = row["entity_name"]
    return out


def _float_or_none(value) -> float | None:
    return float(value) if value is not None else None


# ---- brand_meta_ad_account ----------------------------------------------------------

def bound_brand_ids_by_account(conn: _AnyConn, org_id: str) -> dict:
    rows = conn.execute(
        "SELECT ad_account_id, brand_id FROM brand_meta_ad_account WHERE org_id = %s",
        (org_id,),
    )
    out: dict = {}
    for row in rows:
        out.setdefault(row["ad_account_id"], []).append(row["brand_id"])
    return out


def bind(conn: _AnyConn, org_id: str, brand_id: str, ad_account_id: str) -> bool:
    """回傳這次是不是真的新綁了（已經綁過再綁一次回 False），呼叫端據此決定要不要
    寫稽核——重複綁定不是一次新的操作。"""
    result = conn.execute(
        "INSERT INTO brand_meta_ad_account (org_id, brand_id, ad_account_id, created_at)"
        " VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
        (org_id, brand_id, ad_account_id, now_utc()),
    )
    return result.rowcount > 0


def unbind(conn: _AnyConn, org_id: str, brand_id: str, ad_account_id: str) -> bool:
    result = conn.execute(
        "DELETE FROM brand_meta_ad_account"
        " WHERE org_id = %s AND brand_id = %s AND ad_account_id = %s",
        (org_id, brand_id, ad_account_id),
    )
    return result.rowcount > 0


# ---- 品牌刪除清理登記（第 2 刀「清理登記處」，app/core/cleanup.py）------------------
# brand_meta_ad_account 掛 brand_id，刪品牌時要連鎖清掉；本模組沒有產品層資料
# （product_dimension 明確傳 None／frozenset()，見設計檔「品牌刪除」節）。

def _count_brand(conn: _AnyConn, brand_id: str) -> list:
    row = conn.execute(
        "SELECT count(*) AS n FROM brand_meta_ad_account WHERE brand_id = %s", (brand_id,)
    ).fetchone()
    n = row["n"] if row else 0
    return [("Meta 廣告帳戶綁定", n)] if n else []


def _delete_brand(conn: _AnyConn, brand_id: str) -> dict:
    result = conn.execute("DELETE FROM brand_meta_ad_account WHERE brand_id = %s", (brand_id,))
    return {"brand_meta_ad_account": result.rowcount}


cleanup.register(
    "Meta 廣告帳戶",
    count_brand=_count_brand,
    delete_brand=_delete_brand,
    brand_tables=frozenset({"brand_meta_ad_account"}),
    count_product=None,
    delete_product=None,
    product_tables=frozenset(),
)
