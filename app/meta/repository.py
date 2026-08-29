"""app/meta/repository.py — private DB access for app/meta. Only app/meta/routes.py
imports this (container contract §1); it is never imported outside the package.

Three tables (see supabase/migrations/20260829000002_meta_baseline.sql):
    meta_credential        — one row per org, points at the Vault secret (never the token)
    meta_ad_account        — accounts a token has revealed, org-scoped
    brand_meta_ad_account  — which brand(s) use which account(s), the m:n mapping

The token itself never touches meta_credential (or any other table, audit_log, or a log
line) — it lives in Supabase Vault. `save_token` does not give the secret a name:
`vault.secrets` has a unique index on `name` in one global schema, while
app/tests/conftest.py gives every test module its own Postgres schema — a named secret
would collide across test modules and across organisations. `meta_credential.secret_id`
is the index instead.
"""

from app.core import cleanup
from app.core.db import Conn, ConnProxy, new_id, now_utc

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
