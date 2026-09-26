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

Tables (see supabase/migrations/20260829000002_meta_baseline.sql,
20260830000004_meta_entity_spend.sql and 20260903000012_schedule_channel_credential.sql):
    channel_credential      — this module's earlier one-row-per-org credential table is gone
                              (ticket T4, ADR 0056 §4 — see that migration's own header for
                              the table it replaced). Owned by the schedule module (ADR 0050),
                              not this one — but the code
                              that reads and writes it stays here, because there is still
                              only one channel and ADR 0056 §4 says so explicitly. Keyed
                              (org_id, channel_id, account_scope); v1 writes only
                              account_scope='*', so today's behaviour — one token per org —
                              is unchanged. Points at the Vault secret, never the token.
    meta_ad_account        — accounts a token has revealed, org-scoped; also carries
                              last_pull_at (ticket 05 — set only on a *successful* pull) and
                              timezone_name (ticket T4 — the AdAccount's own IANA zone,
                              nullable: accounts connected before T4 have none)
    brand_meta_ad_account  — which brand(s) use which account(s), the m:n mapping
    meta_entity_spend      — per account, per level (campaign/adset/ad), per entity, per day
                              (ticket S1, replaces meta_campaign_spend); org+account scoped,
                              not brand-scoped, for the same reason meta_ad_account isn't (an
                              account can serve more than one brand). `level` is NOT NULL
                              with no default on purpose — a WHERE clause can be forgotten,
                              a NOT NULL column cannot, and the three levels share one table.
    channel_entity_map     — owned by the schedule module (ADR 0055 §1), not this one.
                              `_refuse_if_parent_owned_by_another_org` (ticket 06) reads it
                              read-only, same precedent as channel_credential above: the table
                              belongs elsewhere, the one place that needs to touch it from here
                              stays here. It never writes this table. Since F31-I13 the guard
                              asks the schedule module's `schedule_channel_entity_owned_elsewhere`
                              SQL function (boolean only), because RLS hides other orgs' rows
                              from a request connection.

The token itself never touches channel_credential (or any other table, audit_log, or a log
line) — it lives in Supabase Vault. `save_token` does not give the secret a name:
`vault.secrets` has a unique index on `name` in one global schema, while
app/tests/conftest.py gives every test module its own Postgres schema — a named secret
would collide across test modules and across organisations. `channel_credential.secret_id`
is the index instead.
"""

import math
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


# ---- channel_credential (ticket T4, ADR 0056 §4) ----------------------------------

# The one channel this module knows about, and the one account_scope v1 ever writes.
# channel_credential is keyed (org_id, channel_id, account_scope) so a second scope is a
# new row later, not a migration (constitution rule 3).
_META_CHANNEL_KEY = "meta"
_ACCOUNT_SCOPE_ALL = "*"


def get_credential(conn: _AnyConn, org_id: str) -> dict | None:
    """This org's Meta credential row, joined from channel_credential to ad_channel so the
    caller never needs a channel id of its own. The join resolves channel_id by
    channel_key='meta' rather than calling app.schedule.repository.ensure_meta_channel:
    schedule -> meta is the established import direction (app/schedule/binding.py etc.), so
    the reverse call would close a package cycle ImportCycleScanTest records."""
    return conn.execute(
        "SELECT cc.org_id, cc.channel_id, cc.secret_id, cc.token_tail, cc.updated_at"
        " FROM channel_credential cc JOIN ad_channel ac"
        "   ON ac.id = cc.channel_id AND ac.org_id = cc.org_id"
        " WHERE cc.org_id = %s AND ac.channel_key = %s AND cc.account_scope = %s",
        (org_id, _META_CHANNEL_KEY, _ACCOUNT_SCOPE_ALL),
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
            "UPDATE channel_credential SET token_tail = %s, updated_at = %s"
            " WHERE org_id = %s AND channel_id = %s AND account_scope = %s",
            (tail, now_utc(), org_id, existing["channel_id"], _ACCOUNT_SCOPE_ALL),
        )
    else:
        secret_id = _vault_create_secret(conn, token)
        # ponytail: second copy of schedule.repository.ensure_meta_channel; the import
        # direction is schedule -> meta so it cannot be called from here. Third caller
        # extracts it to a shared accessor (container contract §5; ADR 0056 §4).
        conn.execute(
            "INSERT INTO ad_channel (id, org_id, channel_key, enabled)"
            " VALUES (%s, %s, %s, true) ON CONFLICT (org_id, channel_key) DO NOTHING",
            (new_id("adch"), org_id, _META_CHANNEL_KEY),
        )
        channel_row = conn.execute(
            "SELECT id FROM ad_channel WHERE org_id = %s AND channel_key = %s",
            (org_id, _META_CHANNEL_KEY),
        ).fetchone()
        assert channel_row is not None  # 上面剛 INSERT／DO NOTHING 過，這一列必然存在
        conn.execute(
            "INSERT INTO channel_credential"
            " (id, org_id, channel_id, account_scope, secret_id, token_tail, updated_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (new_id("chcr"), org_id, channel_row["id"], _ACCOUNT_SCOPE_ALL, secret_id, tail,
             now_utc()),
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
    綁定（brand_meta_ad_account 外鍵 ON DELETE CASCADE 會跟著清掉，見設計檔）。

    `timezone_name`（票 T4）：Meta 沒回這個欄位就存 NULL，不是猜一個——`graph._to_account`
    只在 Meta 真的回了這個欄位時才放進字典，`.get()` 在缺席時回 None，跟 name／currency
    永遠有預設值不同（`daily_pull.py` 讀到 NULL 會退回組織時區）。"""
    for acc in accounts:
        conn.execute(
            "INSERT INTO meta_ad_account"
            " (id, org_id, account_id, name, currency, timezone_name, connected_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (org_id, account_id)"
            " DO UPDATE SET name = excluded.name, currency = excluded.currency,"
            "   timezone_name = excluded.timezone_name",
            (new_id("mad"), org_id, acc["account_id"], acc["name"], acc["currency"],
             acc.get("timezone_name"), now_utc()),
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
    """這個組織『至少綁了一個品牌』的帳號
    （[{"id","account_id","timezone_name"}]）——票 05 的每日拉取只打這些帳號：連了帳號但
    還沒綁任何品牌的，還沒有人真的在用它。`timezone_name`（票 T4）給
    `daily_pull._pull_one_account` 決定拉哪一天，NULL 就是這個帳號 T4 之前就連了。"""
    return list(conn.execute(
        "SELECT DISTINCT maa.id, maa.account_id, maa.timezone_name FROM meta_ad_account maa"
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
    backfill 的耗時，不先為了一個沒量過的效能數字換寫法。

    `currency`（票 T5，ADR 0057 §4）：現在是 `meta_entity_spend` 的 NOT NULL 欄位，值來自
    純量子查詢 `(SELECT currency FROM meta_ad_account WHERE id = %s)`，`ad_account_id`
    在參數列尾端再傳一次——簽章跟呼叫端一個字都不用改（`daily_pull.py` 兩個呼叫點原封不
    動），也不接受呼叫端自己帶一個 `currency` 參數：能傳的呼叫端就是能傳錯的呼叫端，這一
    欄唯一的事實來源是 `meta_ad_account.currency`，寫入當下就凍住，不是讀取時才跟帳戶現在
    的設定重新對答案（憲法規則 7）。"""
    pulled_at = now_utc()  # 同一次拉取共用一個時間戳：它記的是「這批數字多新」，不是逐列時刻
    for row in rows:
        conn.execute(
            "INSERT INTO meta_entity_spend"
            " (id, org_id, ad_account_id, level, entity_id, entity_name, campaign_id,"
            "  adset_id, ad_id, spend_date, spend, impressions, clicks, roas, actions,"
            "  action_values, attribution_window, pulled_at, currency)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
            "  (SELECT currency FROM meta_ad_account WHERE id = %s))"
            " ON CONFLICT (ad_account_id, level, entity_id, spend_date) DO UPDATE SET"
            "  entity_name = excluded.entity_name, campaign_id = excluded.campaign_id,"
            "  adset_id = excluded.adset_id, ad_id = excluded.ad_id, spend = excluded.spend,"
            "  impressions = excluded.impressions, clicks = excluded.clicks,"
            "  roas = excluded.roas, actions = excluded.actions,"
            "  action_values = excluded.action_values,"
            "  attribution_window = excluded.attribution_window, pulled_at = excluded.pulled_at,"
            "  currency = excluded.currency",
            (new_id("mes"), org_id, ad_account_id, row["level"], row["entity_id"],
             row["entity_name"], row["campaign_id"], row["adset_id"], row["ad_id"],
             row["spend_date"], row["spend"], row["impressions"], row["clicks"], row["roas"],
             _jsonb_or_null(row["actions"]), _jsonb_or_null(row["action_values"]),
             row["attribution_window"], pulled_at, ad_account_id),
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


def _refuse_if_parent_owned_by_another_org(conn: _AnyConn, org_id: str, parent_id: str,
                                            *, noun: str, code: str) -> None:
    """票 06（`docs/issues/deploy/06-meta-name-lookup-tenant-symmetry.md`）：`campaign_id`／
    `adset_id` 究竟屬不屬於 `org_id`，這兩支函式自己以前不驗——呼叫端（`app.schedule.
    binding.bind_tree`）今天剛好只餵得進自己組織的 id，但那是呼叫端自律，不是這裡的規則。

    這裡補的第二行防線：`channel_entity_map`（schedule 模組的表，這裡只讀不寫——ADR 0056
    §4 那種「表歸誰、程式碼可以在哪」的既有先例，`get_credential`/`save_token` 讀寫
    `channel_credential` 就是同一個道理）有沒有把這個 id 記成屬於**別的**組織
    （`org_id != %s`）。同一個組織自己的紀錄，或者根本沒有任何紀錄的 id（還沒綁過任何
    人；或者這次呼叫鏈裡剛比對完、`binding.py` 一綁完就先 upsert 才遞迴下一層，所以真的
    走到這裡時該有的那一列早就寫好了），都不算，照舊放行——`AdSetMatchUnreachableTest`／
    `AdMatchUnreachableTest` 那種「org 有權杖、id 沒有任何綁定紀錄」的情境因此不受影響，
    照舊一路走到 Meta、連不上就變成 `meta_unreachable`。只有一個通路（ADR 0056 §4），
    不必再 JOIN `ad_channel` 篩 `channel_key`。"""
    # F31-I13: through the schedule module's SECURITY DEFINER boolean lookup, not a raw SELECT.
    # A request connection runs as `authenticated` under org-isolation RLS, where other orgs'
    # `channel_entity_map` rows are invisible and a plain SELECT never found them.
    row = conn.execute(
        "SELECT schedule_channel_entity_owned_elsewhere(%s, %s) AS owned",
        (parent_id, org_id),
    ).fetchone()
    assert row is not None, "a scalar function SELECT always returns one row"
    # F31-I03: the ads center keeps its own bindings (`ads_*` rows), which this module may not
    # read (meta sits below ads in LAYER_ORDER). The owning module registers a check instead.
    if row["owned"] or any(
        check(conn, org_id, parent_id) for check in _PARENT_OWNER_CHECKS.values()
    ):
        raise web.ApiError(403, code, f"這個{noun}不屬於這個組織，已拒絕比對。")


# F31-I03 (item 5): other modules that record which org bound a platform id register a check
# `(conn, org_id, external_id) -> bool` ("another org bound or lists this id"). Keyed by name so
# a second registration (module reload, tests) replaces instead of stacking. `app/ads/__init__.py`
# registers at import; both the API (`app.main`) and the worker (`app.worker` imports `app.main`
# and `app.ads`) import it before any request or job runs.
_PARENT_OWNER_CHECKS: dict = {}


def register_parent_owner_check(name: str, check) -> None:
    _PARENT_OWNER_CHECKS[name] = check


def ad_set_ids_by_exact_name(
    conn: _AnyConn, org_id: str, campaign_id: str, name: str,
) -> list:
    """票 T3c（ADR 0055 §7）：這個活動底下，廣告組合名稱逐字（區分大小寫、不 trim、
    不正規化）等於 `name` 的 `[{"adset_id", "external_status"}]`——比對只在傳進來的這一個
    活動內部找，不是這批帳號全部，`org_id` 是租戶界線：先用
    `_refuse_if_parent_owned_by_another_org`（票 06）擋掉一個已知記錄成別組織的
    `campaign_id`，權杖也只認自己組織。

    跟 `campaign_ids_by_exact_name` 同一套規矩：資料來源是**平台上的廣告組合清單**
    （`graph.list_ad_sets`），不是 `meta_entity_spend`，理由同上（手動建好、還沒開跑的
    廣告組合沒有任何 insights 列）；連不上 Meta 時同樣把 `graph.GraphError` 轉成人話
    `web.ApiError(502, "meta_unreachable", …)`，不是兩種錯誤形狀混在一起。
    """
    _refuse_if_parent_owned_by_another_org(
        conn, org_id, campaign_id, noun="活動", code="campaign_not_owned",
    )
    token = get_token(conn, org_id)
    if token is None:
        return []  # 這個組織還沒接權杖：沒有可比對的清單，交給呼叫端當「配對失敗」處理
    try:
        ad_sets = graph.list_ad_sets(token, campaign_id)
    except graph.GraphError as exc:
        raise web.ApiError(
            502, "meta_unreachable", f"連不上 Meta，沒辦法比對名稱：{exc.message}"
        ) from exc
    matched = {a["adset_id"]: a["external_status"] for a in ad_sets if a["name"] == name}
    return [{"adset_id": aid, "external_status": status}
            for aid, status in sorted(matched.items())]


def ad_ids_by_exact_name(
    conn: _AnyConn, org_id: str, adset_id: str, name: str,
) -> list:
    """票 T5（ADR 0055 §7 留給這張票開；ADR 0057）：這個廣告組合底下，廣告名稱逐字（區分
    大小寫、不 trim、不正規化）等於 `name` 的 `[{"ad_id", "external_status"}]`——比對只在
    傳進來的這一個廣告組合內部找，不是這批帳號全部，`org_id` 是租戶界線：跟
    `ad_set_ids_by_exact_name` 完全同一套規矩，僅深一層，一樣先用
    `_refuse_if_parent_owned_by_another_org`（票 06）擋掉一個已知記錄成別組織的
    `adset_id`——這支函式以前繼承的是「呼叫端自律、這裡不驗」那個寫法（見
    `docs/contracts/meta.md` 收這張票之前那份記錄），票 06 把這句改成不再成立。

    資料來源是**平台上的廣告清單**（`graph.list_ads`），不是 `meta_entity_spend`，理由同
    `ad_set_ids_by_exact_name`（手動建好、還沒開跑的廣告沒有任何 insights 列）；連不上
    Meta 時同樣把 `graph.GraphError` 轉成人話 `web.ApiError(502, "meta_unreachable", …)`。
    """
    _refuse_if_parent_owned_by_another_org(
        conn, org_id, adset_id, noun="廣告組合", code="adset_not_owned",
    )
    token = get_token(conn, org_id)
    if token is None:
        return []  # 這個組織還沒接權杖：沒有可比對的清單，交給呼叫端當「配對失敗」處理
    try:
        ads = graph.list_ads(token, adset_id)
    except graph.GraphError as exc:
        raise web.ApiError(
            502, "meta_unreachable", f"連不上 Meta，沒辦法比對名稱：{exc.message}"
        ) from exc
    matched = {a["ad_id"]: a["external_status"] for a in ads if a["name"] == name}
    return [{"ad_id": aid, "external_status": status}
            for aid, status in sorted(matched.items())]


def budgets_for_bound_ids(conn: _AnyConn, org_id: str, external_ids: list[str]) -> dict[str, dict]:
    """票 05：讀 Meta 上這些 id（活動或廣告組合）掛的預算欄位——`app.schedule.binding` 拿
    它判斷「這棵樹以為預算在哪一層，Meta 實際把預算掛在哪一層」。租戶界線是**正面表列**：
    只有 `channel_entity_map` 記過是這個組織綁定的 id 才會被拿去問 Meta，不在清單裡的 id
    悄悄丟掉（fail-closed，比 `_refuse_if_parent_owned_by_another_org` 更嚴——那支只擋
    「記錄成別組織」，這支連「誰都沒綁過」也不放行；讀 schedule 的表沿用同一個先例，
    ADR 0056 §4）。沒權杖或輸入是空清單都回 `{}`，不打 Meta；連不上 Meta 轉成人話
    `web.ApiError(502, "meta_unreachable", …)`，同 `repository.py:326`。"""
    if not external_ids:
        return {}
    token = get_token(conn, org_id)
    if token is None:
        return {}
    rows = conn.execute(
        "SELECT DISTINCT external_id FROM channel_entity_map"
        " WHERE org_id = %s AND external_id = ANY(%s)",
        (org_id, external_ids),
    )
    owned_ids = [r["external_id"] for r in rows]
    if not owned_ids:
        return {}
    try:
        return graph.fetch_budgets(token, owned_ids)
    except graph.GraphError as exc:
        raise web.ApiError(
            502, "meta_unreachable", f"連不上 Meta，沒辦法讀預算：{exc.message}"
        ) from exc


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


# F31-I03 (Contract N): the one mapping from a stored `attribution_window` (graph.py joins
# `_ATTRIBUTION_WINDOWS` with ",", e.g. "7d_click,1d_view") to the words the cockpit prints.
_WINDOW_KIND_LABELS = {"click": "點擊後", "view": "瀏覽後"}


def attribution_label(window: str | None) -> str | None:
    """"7d_click,1d_view" → 「點擊後 7 天＋瀏覽後 1 天」. A part this mapping does not know is
    kept as written rather than guessed; None/empty → None."""
    if not window:
        return None
    labels = []
    for part in window.split(","):
        days, _, kind = part.strip().partition("d_")
        if days.isdigit() and kind in _WINDOW_KIND_LABELS:
            labels.append(f"{_WINDOW_KIND_LABELS[kind]} {int(days)} 天")
        else:
            labels.append(part.strip())
    return "＋".join(labels)


def spend_freshness(
    conn: _AnyConn, org_id: str, ad_account_ids: list, start: date, end: date, *, level: str,
) -> dict:
    """F31-I03 (Contract N): for exactly the rows `spend_summary` sums (same `_SPEND_WHERE`), the
    newest `pulled_at` and the attribution label. `last_pull_at` is per account and stays None
    while any bound account never finished a pull, so it cannot say how old *these* numbers
    are. Rows with more than one window get every label joined with 「／」 (the sum mixes them;
    saying so beats naming one)."""
    if level not in LEVELS:
        raise ValueError(f"level 只能是 {'/'.join(LEVELS)} 其中之一")
    if not ad_account_ids:
        return {"data_pulled_at": None, "attribution_label": None}
    row = conn.execute(
        "SELECT max(pulled_at) AS pulled_at,"
        " array_agg(DISTINCT attribution_window ORDER BY attribution_window)"
        "   FILTER (WHERE attribution_window IS NOT NULL) AS windows"
        " FROM meta_entity_spend mes" + _SPEND_WHERE,
        (org_id, ad_account_ids, level, start, end),
    ).fetchone()
    windows = (row["windows"] if row else None) or []
    labels = [label for label in (attribution_label(w) for w in windows) if label]
    return {
        "data_pulled_at": row["pulled_at"] if row else None,
        "attribution_label": "／".join(labels) or None,
    }


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


def daily_entity_spend(
    conn: _AnyConn, org_id: str, ad_account_ids: list, start: date, end: date, *, level: str,
) -> list[dict]:
    """[start, end) 這個半開區間裡，**這一層**逐日逐實體的花費——`spend_summary()` 加總整段
    期間成一列，這支給每一天自己一列，`app/schedule/period.py` 的 `node_level_spend()`
    （票 T3e，ADR 0055 §11）要逐日判斷一個實體那天算誰的檔期。

    `level` 必填、只能用關鍵字傳、沒有預設值——理由跟 `spend_summary()` 一樣：campaign／
    adset／ad 三層的列躺在同一張表，漏掉這個篩選就是把同一筆錢算三遍。`org_id` 篩選加
    呼叫端傳進來的 `ad_account_ids` 是租戶界線。

    票 T5（ADR 0057 §1／§7）：多回 `impressions`／`clicks`／`roas`／`currency` 四欄——
    這不是違反票 T3e 那句「不准長成 `spend_summary`」：那句話擋的是把
    `spend_summary()` 逐實體整段月份的**誠實加總**（`bool_and(roas IS NOT NULL)` 那條
    規則，任一天沒追蹤就讓整個月的 ROAS 回 None）搬進這裡；這裡的 GROUP BY 仍然是
    `(spend_date, entity_id)`，跟原本一樣是逐日逐實體，SQL 端沒有一行做「跨天」的誠實
    判斷——`bool_and` 在這裡只在**同一天同一個實體**的範圍內生效（唯一索引已經保證那通常
    就是一整個群組一列，等於原樣傳遞那一列的 `roas`），真正跨天、跨廣告的誠實加總（T5
    要的 `roas_coverage`）留給呼叫端 `app/schedule/performance.py` 用 Python 做，正是
    ADR 0057 §1 要求的「join 在 Python 做，不是一支跨模組的 SQL」。`currency`
    （ADR 0057 §4）直接讀這一列自己凍住的欄位，不用另外 JOIN `meta_ad_account`。

    F16-I05：多回 `purchases`／`revenue`／`action_type`／`attribution_window` 四欄——沒有
    新讀取，`mes.actions`／`mes.action_values`／`mes.attribution_window` 是這一列早就存好
    的欄位，這裡只是也選出來。同義字判定整段沿用 `external_purchase_values()`（`purchase`
    目標的唯一定義是 `graph._ROAS_ACTION_PRIORITY`，不在這裡另外挑一次、也不 SUM 展開後的
    `jsonb_array_elements`——理由跟 `_CONVERSIONS_LATERAL` 上方註解一樣：同一次成交會被
    好幾個同義 action_type 各回報一次，展開再加總會把同一筆購買算成好幾筆）。做法：把每個
    physical row 的 `actions`／`action_values`／`attribution_window` 用 `jsonb_build_object`
    包成一組（`array_agg` 保留 SQL NULL，一個 physical row 一個陣列元素，三個欄位天生配對，
    不必依賴多個 `array_agg` 之間的順序一致），SQL 只做「同一列打包」，真正的同義字判定、
    『一列有沒有追蹤到購買』、以及『這幾個 physical row 講不講得通同一件事』全部留給
    `_combine_purchases()`／`external_purchase_values()`。`(spend_date, entity_id, currency)`
    通常只有一個 physical row（唯一索引 `(ad_account_id, level, entity_id, spend_date)`
    保證），但這裡的聚合规则在有多列時一樣成立：跟 `roas`／`cpa` 同一條 all-or-nothing
    規則（`_combine_purchases()`），一列沒追蹤到購買、或幾列對不上同一個 `action_type`／
    `attribution_window`，整組就不能假裝湊得出一個數字——未追蹤永遠不是 0，講不清楚的加總
    永遠不是一個看似有根據的數字。"""
    if level not in LEVELS:
        raise ValueError(f"level 只能是 {'/'.join(LEVELS)} 其中之一")
    if not ad_account_ids:
        return []
    rows = conn.execute(
        "SELECT spend_date, entity_id, currency, SUM(spend) AS spend,"
        " SUM(impressions) AS impressions, SUM(clicks) AS clicks,"
        " CASE WHEN bool_and(roas IS NOT NULL)"
        "      THEN SUM(spend * roas) / NULLIF(SUM(spend), 0) ELSE NULL END AS roas,"
        " array_agg(jsonb_build_object('actions', mes.actions,"
        "                              'action_values', mes.action_values,"
        "                              'attribution_window', mes.attribution_window))"
        "   AS purchase_rows"
        " FROM meta_entity_spend mes"
        + _SPEND_WHERE
        + " GROUP BY spend_date, entity_id, currency ORDER BY spend_date, entity_id",
        (org_id, ad_account_ids, level, start, end),
    ).fetchall()
    return [
        {"spend_date": r["spend_date"], "entity_id": r["entity_id"], "currency": r["currency"],
         "spend": float(r["spend"]), "impressions": int(r["impressions"]),
         "clicks": int(r["clicks"]), "roas": _float_or_none(r["roas"]),
         **_combine_purchases(r["purchase_rows"])}
        for r in rows
    ]


def _combine_purchases(purchase_rows: list[dict]) -> dict:
    """一個 `(spend_date, entity_id, currency)` group 裡的每個 physical row 各自用
    `external_purchase_values()` 判定（同一份 purchase 同義字優先序，不另挑一次）；通常
    只有一個 physical row，這裡的規則是給「萬一不只一個」的誠實保底：跟 `_CPA_METRIC`／
    `roas` 同一條 all-or-nothing 規則——任何一個 physical row 沒追蹤到購買，整組直接回
    `None`，不能讓一列的『沒追蹤』被其他列的數字蓋過去、悄悄當成貢獻了 0。revenue 套同一條
    規則：任何一個有追蹤到購買數的 row 卻沒追蹤到營收，整組營收也是 `None`——不能拿
    "有些天有營收" 去補"有些天沒有" 的洞。

    同一條 all-or-nothing 規則也管『不一致』，不是只管『缺席』：如果 tracked 的 physical row
    彼此對到的 `action_type` 不一樣，或者 `attribution_window` 不只一種，代表這幾個 physical
    row 講的根本不是同一件事——把它們的 `purchases` 加起來、只印其中一個 row 的 `action_type`
    /`attribution_window` 當作整組的說明，等於印一個算對了、標籤卻是亂猜的數字，比印「不知
    道」更糟（看起來有根據，其實沒有）。唯一索引 `(ad_account_id, level, entity_id,
    spend_date)` 讓同一天同一個實體通常真的只有一個 physical row，這個分支平常走不到——但
    正因為走不到、沒有真實資料驗證過，才必須直接失敗成『未知』，不能放著一條沒人驗證過的
    加總邏輯去猜一個看起來合理的答案。"""
    parsed = [
        external_purchase_values(item.get("actions"), item.get("action_values"))
        for item in purchase_rows
    ]
    windows = {item.get("attribution_window") for item in purchase_rows}
    if any(p["purchases"] is None for p in parsed):
        return {"purchases": None, "revenue": None, "action_type": None,
                "attribution_window": None}
    action_types = {p["action_type"] for p in parsed}
    if len(action_types) > 1 or len(windows) > 1:
        return {"purchases": None, "revenue": None, "action_type": None,
                "attribution_window": None}
    revenue = (
        None if any(p["revenue"] is None for p in parsed)
        else round(sum(p["revenue"] for p in parsed), 2)
    )
    return {
        "purchases": int(round(sum(p["purchases"] for p in parsed))),
        "revenue": revenue,
        "action_type": action_types.pop(),
        "attribution_window": windows.pop(),
    }


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



def external_sync_scopes(conn):
    """Bound account scopes for the trusted background dispatcher, including empty brands."""
    return [dict(row) for row in conn.execute(
        "SELECT DISTINCT b.org_id,b.brand_id,a.account_id AS source_account "
        "FROM brand_meta_ad_account b JOIN meta_ad_account a "
        "ON a.id=b.ad_account_id AND a.org_id=b.org_id"
    ).fetchall()]


def external_bound_accounts(conn, org_id, brand_id):
    """Source facade: expose only accounts currently bound to this tenant and brand."""
    rows = conn.execute(
        "SELECT a.account_id,a.name,a.currency,a.timezone_name FROM meta_ad_account a "
        "JOIN brand_meta_ad_account b ON b.ad_account_id=a.id AND b.org_id=a.org_id "
        "WHERE a.org_id=%s AND b.brand_id=%s ORDER BY a.account_id", (org_id, brand_id),
    ).fetchall()
    return [dict(row) for row in rows]


class ExternalReadError(ValueError):
    """Sanitized external transport failure; never contains a provider URL or token."""
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


def read_external_page(conn, org_id, brand_id, account_id, section, **kwargs):
    if account_id not in {a["account_id"] for a in external_bound_accounts(conn, org_id, brand_id)}:
        raise ValueError("來源帳號已解除或不屬於此品牌。")
    token = get_token(conn, org_id)
    if not token:
        raise ValueError("來源連線沒有可用的憑證。")
    # This facade is used by the read-only background worker; no transaction waits on HTTP.
    conn.commit()
    try:
        return graph.external_page(token, account_id, section, **kwargs)
    except graph.GraphError as exc:
        code = ("permission_denied" if exc.code in {10, 190, 200} else
                "source_error" if exc.retryable or exc.code in {1, 2, 4, 17, 32, 613} else
                "invalid_source_page")
        raise ExternalReadError(str(exc),code) from None



def external_purchase_values(actions, values):
    """One explicit synonymous action defines both count and value; absent is unavailable."""
    counts = {a.get("action_type"):a.get("value") for a in (actions or []) if isinstance(a, dict)}
    revenues = {a.get("action_type"):a.get("value") for a in (values or []) if isinstance(a, dict)}
    def number(value):
        try:
            result = float(value)
            return result if math.isfinite(result) else None
        except (TypeError, ValueError):
            return None
    for kind in graph._ROAS_ACTION_PRIORITY:
        if kind in counts:
            return {"purchases":number(counts[kind]), "revenue":number(revenues.get(kind)),
                    "action_type":kind}
    return {"purchases":None,"revenue":None,"action_type":None}


def read_external_object(conn, org_id, brand_id, account_id, kind, native_id):
    """Fresh, bounded node GET through the existing credential and tenant facade."""
    if kind not in {"ad", "adset", "campaign"}:
        raise ValueError("不支援的單物件讀取。")
    page=read_external_page(conn,org_id,brand_id,account_id,kind,native_id=native_id)
    if len(page["data"])!=1 or str(page["data"][0].get("id"))!=str(native_id):
        raise ValueError("平台沒有回傳指定物件。")
    return page["data"][0]


_PIXEL_PAGES = 5


def read_external_pixels(conn, org_id, brand_id, account_id):
    """F29-I07: the bound account's tracking pixels `[{id, name}]` through the same credential and
    tenant facade as every other external read (read only; a bounded number of pages). A failure
    raises `ExternalReadError` with the stored code (`permission_denied` for a missing grant)."""
    pixels, cursor = [], None
    for _ in range(_PIXEL_PAGES):
        page = read_external_page(conn, org_id, brand_id, account_id, "pixels", cursor=cursor)
        for item in page["data"]:
            if item.get("id"):
                pixels.append({"id": str(item["id"]), "name": str(item.get("name") or item["id"])})
        cursor = page["cursor"]
        if not cursor:
            return pixels
    raise ExternalReadError("像素清單超過一次可讀的範圍，這次沒有全部讀到。", "invalid_source_page")
