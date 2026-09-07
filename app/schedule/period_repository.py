"""app/schedule/period_repository.py — private DB access for `campaign_period` and
`period_node_result` (ticket smart-loop 02): moved out of `repository.py`, verbatim, to keep
that file under the 800-line cap (`FileLineCapTest`). No behaviour change — same functions,
same signatures, same bodies.

Private to app/schedule (container contract §1): imported by `period.py`, `routes.py`,
`binding.py`, `scoring.py` and `jobs.py` (ticket smart-loop 03: `latest_settled_period()`, for
the plan/tree prompts' last section). Imports nothing from elsewhere in `app.schedule`
(docs/contracts/schedule.md).
"""

from app.core.db import Conn, ConnProxy, jsonb, new_id

_AnyConn = Conn | ConnProxy


# ---- campaign_period（票 T2b，ADR 0053）--------------------------------------------------
# 誕生在表單、結算靠手動：草稿（status='planning'）一個品牌最多一列，出方案第二次以後
# 改的是同一列的日期／預算（決策 1）；結算的算法（哪天算誰的、算多少錢）留在 routes.py，
# 這裡只管落地。

def upsert_draft_period(conn: _AnyConn, org_id: str, brand_id: str, *, name: str,
                         start_date, end_date, daily_budget: float, currency: str) -> str:
    """按 `出方案` 一次：這個品牌還有草稿就改日期／預算，沒有就新開一列——三次按下去
    不留三個檔期（ADR 0053 決策 1）。"""
    updated = conn.execute(
        "UPDATE campaign_period SET name = %s, start_date = %s, end_date = %s,"
        " daily_budget = %s, currency = %s, updated_at = now()"
        " WHERE org_id = %s AND brand_id = %s AND status = 'planning' RETURNING id",
        (name, start_date, end_date, daily_budget, currency, org_id, brand_id),
    ).fetchone()
    if updated is not None:
        conn.commit()
        return updated["id"]
    period_id = new_id("cpd")
    conn.execute(
        "INSERT INTO campaign_period (id, org_id, brand_id, name, start_date, end_date,"
        " daily_budget, currency) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (period_id, org_id, brand_id, name, start_date, end_date, daily_budget, currency),
    )
    conn.commit()
    return period_id


def get_latest_period(conn: _AnyConn, org_id: str, brand_id: str) -> dict | None:
    """畫面目前顯示的那一個——「最新一列是真相」，跟 `routes._latest_task_row()` 同一個
    既有慣例（ADR 0053 consequences 段：這條慣例的收斂留給 T5，T2b 不先改）。"""
    row = conn.execute(
        "SELECT * FROM campaign_period WHERE org_id = %s AND brand_id = %s"
        " ORDER BY created_at DESC LIMIT 1",
        (org_id, brand_id),
    ).fetchone()
    return dict(row) if row is not None else None


def latest_settled_period(conn: _AnyConn, org_id: str, brand_id: str) -> dict | None:
    """Ticket smart-loop 03: the prompts' "last period" — the most recently *settled* one, by
    `settled_at`, not by `created_at`. A newer `planning`/`running` period never shadows it
    (that is a different period the user has not yet closed out)."""
    row = conn.execute(
        "SELECT * FROM campaign_period WHERE org_id = %s AND brand_id = %s AND status = 'settled'"
        " ORDER BY settled_at DESC LIMIT 1",
        (org_id, brand_id),
    ).fetchone()
    return dict(row) if row is not None else None


def get_period(conn: _AnyConn, org_id: str, brand_id: str, period_id: str) -> dict | None:
    """結算端點專用：`org_id`／`brand_id` 都在 WHERE 裡——`period_id` 是呼叫端（使用者）
    給的，不能只信任主鍵比對，另一個組織的檔期 id 必須查不到（租戶界線）。"""
    row = conn.execute(
        "SELECT * FROM campaign_period WHERE id = %s AND org_id = %s AND brand_id = %s",
        (period_id, org_id, brand_id),
    ).fetchone()
    return dict(row) if row is not None else None


def list_non_draft_periods(conn: _AnyConn, org_id: str, brand_id: str) -> list[dict]:
    """ADR 0053 決策 4：日子的擁有權只看「結算當下存在」的非草稿檔期——草稿從沒被使用者
    核准過，不佔任何一天。"""
    rows = conn.execute(
        "SELECT * FROM campaign_period WHERE org_id = %s AND brand_id = %s"
        " AND status != 'planning'",
        (org_id, brand_id),
    ).fetchall()
    return [dict(r) for r in rows]


def approve_draft_period(conn: _AnyConn, org_id: str, brand_id: str) -> None:
    """ADR 0053 決策 1：核准活動樹的那一press＝「這期真的要投」，草稿在這裡變 running。
    找不到草稿就什麼都不做——這個品牌上一次的草稿可能已經被核准過了，這次核准只是
    撤回又核准同一棵樹。"""
    conn.execute(
        "UPDATE campaign_period SET status = 'running', updated_at = now()"
        " WHERE org_id = %s AND brand_id = %s AND status = 'planning'",
        (org_id, brand_id),
    )
    conn.commit()


def advance_period_to_awaiting_data(conn: _AnyConn, org_id: str, period_id: str) -> None:
    """ADR 0053 決策 2：`running` 過了 `end_date` 自動變 `awaiting_data`——讀的時候順手算，
    不是背景工作；一次 UPDATE，冪等（讀第二次不會出事，WHERE 沒有狀態條件單純是覆寫同一個
    值）。"""
    conn.execute(
        "UPDATE campaign_period SET status = 'awaiting_data', updated_at = now()"
        " WHERE id = %s AND org_id = %s",
        (period_id, org_id),
    )
    conn.commit()


def write_settlement(conn: _AnyConn, *, org_id: str, period_id: str, spend: float,
                      revenue: float, settled_at, force_early: bool) -> None:
    """落地一次結算（或重新結算）的快照——呼叫端負責在重新結算時先把舊的三個數字寫進
    audit_log（ADR 0053 §3：快照可以被換掉，不能悄悄換掉）。`status` 一律變成 `settled`
    （ADR 0053 consequences：四態機的最後一態），`force_settled_*` 只在提早結算時才寫。"""
    if force_early:
        conn.execute(
            "UPDATE campaign_period SET status = 'settled', settled_spend = %s,"
            " settled_revenue = %s, settled_at = %s, version = version + 1,"
            " force_settled_at = %s, force_settled_reason = 'early', updated_at = now()"
            " WHERE id = %s AND org_id = %s",
            (spend, revenue, settled_at, settled_at, period_id, org_id),
        )
    else:
        conn.execute(
            "UPDATE campaign_period SET status = 'settled', settled_spend = %s,"
            " settled_revenue = %s, settled_at = %s, version = version + 1, updated_at = now()"
            " WHERE id = %s AND org_id = %s",
            (spend, revenue, settled_at, period_id, org_id),
        )
    conn.commit()


# ---- Ticket smart-loop 01 (ADR 0066): period_node_result, scored at settle -------------

def period_node_memberships_for_period(conn: _AnyConn, org_id: str, brand_id: str,
                                        period_id: str) -> list[dict]:
    """This period's own `period_node_membership` rows: just the columns
    score_period() needs (`channel_id`/`node_key`/`source_tree_task_id`/`created_at`)."""
    rows = conn.execute(
        "SELECT channel_id, node_key, source_tree_task_id, created_at"
        " FROM period_node_membership"
        " WHERE org_id = %s AND brand_id = %s AND campaign_period_id = %s",
        (org_id, brand_id, period_id),
    ).fetchall()
    return [dict(r) for r in rows]


def replace_period_node_results(conn: _AnyConn, org_id: str, brand_id: str, period_id: str,
                                 rows: list[dict]) -> int:
    """One settle replaces this period's period_node_result rows: DELETE, INSERT, commit."""
    conn.execute(
        "DELETE FROM period_node_result"
        " WHERE org_id = %s AND brand_id = %s AND campaign_period_id = %s",
        (org_id, brand_id, period_id),
    )
    for r in rows:
        conn.execute(
            "INSERT INTO period_node_result (id, org_id, brand_id, campaign_period_id,"
            " source_tree_task_id, channel_id, node_key, depth, node_name, external_id,"
            " approved_share, approved_daily_amount, actual_spend, revenue_tracked,"
            " roas_conservative, roas_optimistic, roas_coverage, breakeven_roas,"
            " breakeven_source, verdict, coordinates_json, settled_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
            " %s, %s, %s, %s, %s)",
            (new_id("pnr"), org_id, brand_id, period_id, r["source_tree_task_id"],
             r["channel_id"], r["node_key"], r["depth"], r["node_name"], r["external_id"],
             r["approved_share"], r["approved_daily_amount"], r["actual_spend"],
             r["revenue_tracked"], r["roas_conservative"], r["roas_optimistic"],
             r["roas_coverage"], r["breakeven_roas"], r["breakeven_source"], r["verdict"],
             jsonb(r["coordinates_json"]) if r["coordinates_json"] is not None else None,
             r["settled_at"]),
        )
    conn.commit()
    return len(rows)


_NODE_RESULT_NUMERIC_COLS = ("approved_share", "approved_daily_amount", "actual_spend",
                             "revenue_tracked", "roas_conservative", "roas_optimistic",
                             "roas_coverage", "breakeven_roas")


def period_node_results(conn: _AnyConn, org_id: str, brand_id: str, period_id: str) -> list[dict]:
    """This period's scored nodes for the API/prompt: Decimal columns cast to float (same
    convention as `period.brand_period_response()`), ordered by depth then node_key.

    `source_tree_task_id`（票 04 Amendment 2026-09-08）：一期所有列同一個值（`scoring.
    score_period()` 寫入時就是這樣，取自那一批 `period_node_membership` 裡最新一列）——
    `jobs._continuity_campaign_names()` 拿它去找**那一棵樹自己**的第一層（活動）綁定列
    （`repository.bindings_for_tree()`，ADR 0064：綁定屬於做出它的那棵樹），depth 1 從沒
    被記分，不會自己出現在這張表裡。"""
    rows = conn.execute(
        "SELECT source_tree_task_id, node_key, depth, node_name, external_id, approved_share,"
        " approved_daily_amount, actual_spend, revenue_tracked, roas_conservative,"
        " roas_optimistic, roas_coverage, breakeven_roas, breakeven_source, verdict,"
        " coordinates_json FROM period_node_result"
        " WHERE org_id = %s AND brand_id = %s AND campaign_period_id = %s"
        " ORDER BY depth, node_key",
        (org_id, brand_id, period_id),
    ).fetchall()
    for r in rows:
        for c in _NODE_RESULT_NUMERIC_COLS:
            if r[c] is not None:
                r[c] = float(r[c])
    return [dict(r) for r in rows]
