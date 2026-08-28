"""T3 的管道計畫與任務卡存取層。

對外進入點：本檔公開 CRUD 函式。
輸入輸出：每個函式都收 SQLite 連線、brand_id 與必要識別值，回傳 dict、dict list 或 None。
誰依賴它：opening_suggestion.py 與 routes_campaigns_open_api.py。
不碰什麼：不 import app.orders、app.dashboard，也不修改既有 ads repository。
"""


from app.brand_intelligence import repository as bi
from app.core.db import Conn, new_id, now_utc

CHANNELS = ("social", "google_search", "line_email", "kol_media", "website_landing")
CHANNEL_LABELS = {
    "social": "社群", "google_search": "Google 搜尋", "line_email": "LINE-Email",
    "kol_media": "KOL 媒體", "website_landing": "官網落地頁",
}
DEPTHS = ("full", "task_card", "healthcheck")


def _row(row) -> dict | None:
    return dict(row) if row is not None else None


def _rows(cursor) -> list:
    return [dict(row) for row in cursor.fetchall()]


def _require_text(value, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} 為必填")
    return text


def _validate_plan(channel: str, pct: int, depth: str) -> None:
    if channel not in CHANNEL_LABELS:
        raise ValueError("channel 不在五類固定管道中")
    if not isinstance(pct, int) or not 0 <= pct <= 100:
        raise ValueError("pct 必須是 0 到 100 的整數")
    if depth not in DEPTHS:
        raise ValueError("depth 只能是 full、task_card 或 healthcheck")


def create_channel_plan(conn: Conn, brand_id: str, cycle_id: str, *, channel: str,
                        job: str, pct: int, expected: str, enabled: bool = True,
                        depth: str = "full") -> dict:
    org_id = bi.get_brand(conn, brand_id)["org_id"]
    _require_text(brand_id, "brand_id")
    _require_text(cycle_id, "cycle_id")
    _validate_plan(channel, pct, depth)
    row = {
        "id": new_id("chp"), "org_id": org_id, "brand_id": brand_id, "cycle_id": cycle_id,
        "channel": channel,
        "job": _require_text(job, "job"), "pct": pct, "expected": _require_text(expected, "expected"),
        "enabled": bool(enabled), "depth": depth, "created_at": now_utc(),
    }
    conn.execute(
        "INSERT INTO channel_plan (id, org_id, brand_id, cycle_id, channel, job, pct, expected, enabled, depth, "
        "created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        tuple(row.values()),
    )
    conn.commit()
    return row


def get_channel_plan(conn: Conn, brand_id: str, plan_id: str) -> dict | None:
    return _row(conn.execute(
        "SELECT * FROM channel_plan WHERE id = %s AND brand_id = %s", (plan_id, brand_id)
    ).fetchone())


def list_channel_plans(conn: Conn, brand_id: str, cycle_id: str) -> list:
    return _rows(conn.execute(
        "SELECT * FROM channel_plan WHERE brand_id = %s AND cycle_id = %s ORDER BY created_at, channel",
        (brand_id, cycle_id),
    ))


def update_channel_plan(conn: Conn, brand_id: str, plan_id: str, *, job: str, pct: int,
                        expected: str, enabled: bool, depth: str) -> dict:
    before = get_channel_plan(conn, brand_id, plan_id)
    if before is None:
        raise ValueError(f"找不到管道計畫：{plan_id}")
    _validate_plan(before["channel"], pct, depth)
    conn.execute(
        "UPDATE channel_plan SET job = %s, pct = %s, expected = %s, enabled = %s, depth = %s "
        "WHERE id = %s AND brand_id = %s",
        (_require_text(job, "job"), pct, _require_text(expected, "expected"), bool(enabled), depth,
         plan_id, brand_id),
    )
    conn.commit()
    return get_channel_plan(conn, brand_id, plan_id)


def delete_channel_plan(conn: Conn, brand_id: str, plan_id: str) -> None:
    if get_channel_plan(conn, brand_id, plan_id) is None:
        raise ValueError(f"找不到管道計畫：{plan_id}")
    conn.execute("DELETE FROM channel_plan WHERE id = %s AND brand_id = %s", (plan_id, brand_id))
    conn.commit()


def previous_enabled_defaults(conn: Conn, brand_id: str, cycle_id: str | None = None) -> dict:
    """讀同品牌最近一個已有管道計畫的檔期，供下期預填「用／不用」。"""
    filters = "WHERE cp.brand_id = %s"
    params = [brand_id]
    if cycle_id:
        filters += " AND cp.cycle_id != %s"
        params.append(cycle_id)
    previous = conn.execute(
        "SELECT cp.cycle_id FROM channel_plan cp JOIN campaign_cycle cc ON cc.id = cp.cycle_id "
        f"{filters} ORDER BY cc.created_at DESC, cp.created_at DESC LIMIT 1", params,
    ).fetchone()
    if previous is None:
        return {}
    rows = list_channel_plans(conn, brand_id, previous["cycle_id"])
    return {row["channel"]: bool(row["enabled"]) for row in rows}


def create_task_card(conn: Conn, brand_id: str, cycle_id: str, *, channel: str, title: str,
                     draft_hint: str | None = None) -> dict:
    org_id = bi.get_brand(conn, brand_id)["org_id"]
    _require_text(brand_id, "brand_id")
    _require_text(cycle_id, "cycle_id")
    row = {
        "id": new_id("tsk"), "org_id": org_id, "brand_id": brand_id, "cycle_id": cycle_id,
        "channel": _require_text(channel, "channel"), "title": _require_text(title, "title"),
        "draft_hint": draft_hint or None, "done": False, "created_at": now_utc(), "done_at": None,
    }
    conn.execute(
        "INSERT INTO task_card (id, org_id, brand_id, cycle_id, channel, title, draft_hint, done, created_at, done_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", tuple(row.values()),
    )
    conn.commit()
    return row


def get_task_card(conn: Conn, brand_id: str, card_id: str) -> dict | None:
    return _row(conn.execute(
        "SELECT * FROM task_card WHERE id = %s AND brand_id = %s", (card_id, brand_id)
    ).fetchone())


def list_task_cards(conn: Conn, brand_id: str, cycle_id: str) -> list:
    return _rows(conn.execute(
        "SELECT * FROM task_card WHERE brand_id = %s AND cycle_id = %s ORDER BY created_at", (brand_id, cycle_id)
    ))


def update_task_card(conn: Conn, brand_id: str, card_id: str, *, title: str,
                     draft_hint: str | None, done: bool) -> dict:
    if get_task_card(conn, brand_id, card_id) is None:
        raise ValueError(f"找不到任務卡：{card_id}")
    done_at = now_utc() if done else None
    conn.execute(
        "UPDATE task_card SET title = %s, draft_hint = %s, done = %s, done_at = %s "
        "WHERE id = %s AND brand_id = %s",
        (_require_text(title, "title"), draft_hint or None, bool(done), done_at, card_id, brand_id),
    )
    conn.commit()
    return get_task_card(conn, brand_id, card_id)


def delete_task_card(conn: Conn, brand_id: str, card_id: str) -> None:
    if get_task_card(conn, brand_id, card_id) is None:
        raise ValueError(f"找不到任務卡：{card_id}")
    conn.execute("DELETE FROM task_card WHERE id = %s AND brand_id = %s", (card_id, brand_id))
    conn.commit()
