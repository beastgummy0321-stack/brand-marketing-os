"""app/meta/repository.py — private DB access for app/meta. Only app/meta/routes.py and
app/meta/daily_pull.py import this (both inside this package; container contract §1) —
it is never imported outside the package.

One function here is not pure DB access: `campaign_ids_by_exact_name` reads the account's
live campaign list through `graph.py`, because a campaign built by hand and left paused
exists on the platform but has no rows in any of our tables. Its docstring carries the
reason; everything else below is Postgres only.

Four tables (see supabase/migrations/20260829000002_meta_baseline.sql and
20260829000004_meta_daily_spend.sql):
    meta_credential        — one row per org, points at the Vault secret (never the token)
    meta_ad_account        — accounts a token has revealed, org-scoped; also carries
                              last_pull_at (ticket 05 — set only on a *successful* pull)
    brand_meta_ad_account  — which brand(s) use which account(s), the m:n mapping
    meta_campaign_spend    — per account, per campaign, per day (ticket 05); org+account
                              scoped, not brand-scoped, for the same reason meta_ad_account
                              isn't (an account can serve more than one brand)

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
from app.core.db import Conn, ConnProxy, new_id, now_utc
from app.meta import graph

_AnyConn = Conn | ConnProxy


# ---- Vault ----------------------------------------------------------------------

def _vault_create_secret(conn: _AnyConn, token: str) -> str:
    row = conn.execute("SELECT vault.create_secret(%s) AS id", (token,)).fetchone()
    assert row is not None, "vault.create_secret() 是純量函式，SELECT 一定回一列"
    return str(row["id"])


def _vault_update_secret(conn: _AnyConn, secret_id: str, token: str) -> None:
    conn.execute("SELECT vault.update_secret(%s, %s)", (secret_id, token))


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
    row = conn.execute(
        "SELECT decrypted_secret FROM vault.decrypted_secrets WHERE id = %s",
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


# ---- meta_campaign_spend --------------------------------------------------------------

def upsert_campaign_spend(
    conn: _AnyConn, org_id: str, ad_account_id: str, day: date, rows: list[dict],
) -> None:
    """Upsert 一個帳號『某一天』每個活動的成效。(ad_account_id, campaign_id, spend_date)
    的唯一索引（migration）是重跑同一天不重複、不 double count 的真正機制——這裡只是
    照著那個索引寫 ON CONFLICT，機制在資料庫，不是這段程式碼自己防呆。"""
    for row in rows:
        conn.execute(
            "INSERT INTO meta_campaign_spend"
            " (id, org_id, ad_account_id, campaign_id, campaign_name, spend_date,"
            "  spend, impressions, clicks, roas, pulled_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (ad_account_id, campaign_id, spend_date) DO UPDATE SET"
            "  campaign_name = excluded.campaign_name, spend = excluded.spend,"
            "  impressions = excluded.impressions, clicks = excluded.clicks,"
            "  roas = excluded.roas, pulled_at = excluded.pulled_at",
            (new_id("mcs"), org_id, ad_account_id, row["campaign_id"], row["campaign_name"],
             day, row["spend"], row["impressions"], row["clicks"], row["roas"], now_utc()),
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
    """票 11：這批帳號裡，活動名稱逐字（區分大小寫、不 trim、不正規化）等於 `name` 的
    campaign_id——外殼精準比對的唯一資料來源，`org_id` 是租戶界線。

    資料來源是**平台上的活動清單**（`graph.list_campaigns`），不是 `meta_campaign_spend`。
    2026-08-29 實測發現的缺陷：手動建好、維持關閉的活動沒有任何 insights 列，靠花費表比對
    永遠是「配對失敗」——而「先建成關閉、配對確認、才開跑」正是這條手動路徑該有的順序。
    比對完存下 id，之後讀數字一律靠 id（改名不斷線），那部分仍然走 meta_campaign_spend。
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
    matched: list = []
    for row in rows:
        try:
            campaigns = graph.list_campaigns(token, row["account_id"])
        except graph.GraphError as exc:
            raise web.ApiError(
                502, "meta_unreachable", f"連不上 Meta，沒辦法比對名稱：{exc.message}"
            ) from exc
        matched.extend(c["campaign_id"] for c in campaigns if c["name"] == name)
    return sorted(set(matched))


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


_EMPTY_TOTAL = {"spend": 0.0, "impressions": 0, "clicks": 0, "roas": None}


def spend_summary(
    conn: _AnyConn, org_id: str, ad_account_ids: list, month_start: date, month_end: date,
) -> dict:
    """[month_start, month_end) 這個半開區間裡，這批帳號逐活動加總＋一列總計。

    ROAS 是比率，加總不能直接平均（票 05：「加總比率沒有意義」）——用花費加權
    （SUM(spend*roas)/SUM(spend)，數學上等於「這個範圍的總營收 ÷ 總花費」）算出誠實的
    總 ROAS；但只要範圍裡有任何一列 roas 是 NULL（未追蹤），代表那部分花費的營收根本
    不知道，總數就不能假裝把它算進去了——整組（那個活動的小計，或最下面的總計）直接
    回 None，畫面一樣顯示未追蹤，不印一個不真實的數字。"""
    if not ad_account_ids:
        return {"campaigns": [], "total": dict(_EMPTY_TOTAL)}
    args = (org_id, ad_account_ids, month_start, month_end)
    campaigns = conn.execute(
        # 一個活動一列，GROUP BY 只按 campaign_id——名稱不進 GROUP BY（票 11 審查發現）：
        # 使用者月中在平台上改名，改名前後的日列各自留著自己那天的 campaign_name，按
        # (id, 名稱) 分組會把同一個活動裂成兩列、各拿半個月的花費。顯示的名稱取「最後
        # 一天用的那個」，也就是使用者現在在平台上看得到的那個。
        "SELECT campaign_id,"
        " (array_agg(campaign_name ORDER BY spend_date DESC))[1] AS campaign_name,"
        " SUM(spend) AS spend,"
        " SUM(impressions) AS impressions, SUM(clicks) AS clicks,"
        " CASE WHEN bool_and(roas IS NOT NULL)"
        "      THEN SUM(spend * roas) / NULLIF(SUM(spend), 0) ELSE NULL END AS roas"
        " FROM meta_campaign_spend"
        " WHERE org_id = %s AND ad_account_id = ANY(%s)"
        "   AND spend_date >= %s AND spend_date < %s"
        " GROUP BY campaign_id ORDER BY campaign_id",
        args,
    ).fetchall()
    total = conn.execute(
        "SELECT COALESCE(SUM(spend), 0) AS spend, COALESCE(SUM(impressions), 0) AS impressions,"
        " COALESCE(SUM(clicks), 0) AS clicks,"
        " CASE WHEN count(*) > 0 AND bool_and(roas IS NOT NULL)"
        "      THEN SUM(spend * roas) / NULLIF(SUM(spend), 0) ELSE NULL END AS roas"
        " FROM meta_campaign_spend"
        " WHERE org_id = %s AND ad_account_id = ANY(%s)"
        "   AND spend_date >= %s AND spend_date < %s",
        args,
    ).fetchone()
    assert total is not None, "聚合查詢沒有 GROUP BY，SELECT 一定回一列"
    return {
        "campaigns": [_spend_row(r) for r in campaigns],
        "total": _spend_row(total),
    }


def _spend_row(row: dict) -> dict:
    """numeric（Decimal）欄位單一收口轉 float，讀取端只轉這一次（比照
    app/orders/repository.py 的既有慣例）。roas 是 None 原樣穿過——未追蹤就是未追蹤。"""
    roas = row["roas"]
    out = {
        "spend": float(row["spend"]), "impressions": int(row["impressions"]),
        "clicks": int(row["clicks"]), "roas": float(roas) if roas is not None else None,
    }
    if "campaign_id" in row:
        out["campaign_id"] = row["campaign_id"]
        out["campaign_name"] = row["campaign_name"]
    return out


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
