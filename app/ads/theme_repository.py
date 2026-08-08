# -*- coding: utf-8 -*-
"""app/ads/theme_repository.py — 主題資料模型存取層（票 02-theme-tables）。

主題（creative_theme）＝一則廣告：屬於某個切角格（experiment_cell），對應某個廣告格式
（format_key，查 app/creative/format_specs.py FORMAT_SPECS），底下掛多個主題元件
（creative_theme_component：文案／標題／說明／圖片提示詞／輪播卡／腳本…）。

比照 app/ads/repository.py 的規則：所有查詢一律以 brand_id 過濾；每次異動寫一筆
audit_log。刪檔期／刪品牌的 cascade 清單登記在 app/ads/repository.py 的
CYCLE_CASCADE_TABLES／_PRODUCT_CASCADE_LABELS（該檔已頂到 800 行檔案上限，本檔另開新檔，
不把 CRUD 也塞進去），本檔只管建立／讀取／依格查詢／狀態更新。
"""

import json
import sqlite3
from typing import Optional

from app.core.audit import write_audit
from app.core.db import new_id, now_iso


def _rows(cursor) -> list:
    return [dict(r) for r in cursor.fetchall()]


def _row(cursor_row) -> Optional[dict]:
    return dict(cursor_row) if cursor_row is not None else None


def _insert_component(conn: sqlite3.Connection, brand_id: str, campaign_cycle_id: str,
                      theme_id: str, component: dict, ts: str) -> None:
    component_type = component.get("component_type")
    content = component.get("content")
    if not component_type or not str(component_type).strip():
        raise ValueError("元件型別（component_type）為必填")
    if content is None or not str(content).strip():
        raise ValueError("元件內容（content）為必填")
    fingerprint = component.get("fingerprint_json")
    conn.execute(
        "INSERT INTO creative_theme_component (id, brand_id, campaign_cycle_id,"
        " creative_theme_id, component_type, sequence, content, fingerprint_json,"
        " over_budget, similarity_flag, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (new_id("cthc"), brand_id, campaign_cycle_id, theme_id, str(component_type).strip(),
         component.get("sequence"), str(content), json.dumps(fingerprint, ensure_ascii=False)
             if fingerprint is not None else None,
         1 if component.get("over_budget") else 0,
         1 if component.get("similarity_flag") else 0, ts),
    )


def create_theme(conn: sqlite3.Connection, brand_id: str, *, campaign_cycle_id: str,
                 experiment_cell_id: str, format_key: str, name: str, folder_code: str,
                 actor: str, status: str = "draft", components: Optional[list] = None) -> dict:
    """建一個主題，可一併帶入元件清單（components：每項 dict 至少含
    component_type／content，選填 sequence／fingerprint_json／over_budget／similarity_flag）。
    """
    if not format_key or not format_key.strip():
        raise ValueError("格式 key（format_key）為必填")
    if not name or not name.strip():
        raise ValueError("主題名稱為必填")
    if not folder_code or not folder_code.strip():
        raise ValueError("資料夾短碼為必填")
    if not actor or not actor.strip():
        raise ValueError("actor 為必填")

    theme_id = new_id("cth")
    ts = now_iso()
    conn.execute(
        "INSERT INTO creative_theme (id, brand_id, campaign_cycle_id, experiment_cell_id,"
        " format_key, name, folder_code, status, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (theme_id, brand_id, campaign_cycle_id, experiment_cell_id, format_key.strip(),
         name.strip(), folder_code.strip(), status, ts, ts),
    )
    for component in (components or []):
        _insert_component(conn, brand_id, campaign_cycle_id, theme_id, component, ts)

    after = get_theme(conn, brand_id, theme_id)
    write_audit(conn, brand_id=brand_id, entity_type="creative_theme", entity_id=theme_id,
                action="create", actor=actor, before=None, after=after)
    conn.commit()
    return after


def get_theme(conn: sqlite3.Connection, brand_id: str, theme_id: str) -> Optional[dict]:
    theme = _row(conn.execute(
        "SELECT * FROM creative_theme WHERE brand_id = ? AND id = ?", (brand_id, theme_id)
    ).fetchone())
    if theme is None:
        return None
    theme["components"] = list_theme_components(conn, brand_id, theme_id)
    return theme


def list_theme_components(conn: sqlite3.Connection, brand_id: str, theme_id: str) -> list:
    rows = _rows(conn.execute(
        "SELECT * FROM creative_theme_component WHERE brand_id = ? AND creative_theme_id = ?"
        " ORDER BY sequence, created_at", (brand_id, theme_id),
    ))
    for row in rows:
        if row["fingerprint_json"]:
            row["fingerprint_json"] = json.loads(row["fingerprint_json"])
    return rows


def list_themes_for_cell(conn: sqlite3.Connection, brand_id: str,
                         experiment_cell_id: str) -> list:
    """依格查詢：同一個切角格底下的全部主題（含各自元件）。"""
    themes = _rows(conn.execute(
        "SELECT * FROM creative_theme WHERE brand_id = ? AND experiment_cell_id = ?"
        " ORDER BY created_at", (brand_id, experiment_cell_id),
    ))
    for theme in themes:
        theme["components"] = list_theme_components(conn, brand_id, theme["id"])
    return themes


def update_theme_status(conn: sqlite3.Connection, brand_id: str, theme_id: str, *,
                        status: str, actor: str) -> dict:
    before = get_theme(conn, brand_id, theme_id)
    if before is None:
        raise ValueError(f"找不到主題：{theme_id}")
    if not status or not status.strip():
        raise ValueError("狀態為必填")
    if not actor or not actor.strip():
        raise ValueError("actor 為必填")

    conn.execute(
        "UPDATE creative_theme SET status = ?, updated_at = ? WHERE brand_id = ? AND id = ?",
        (status.strip(), now_iso(), brand_id, theme_id),
    )
    after = get_theme(conn, brand_id, theme_id)
    write_audit(conn, brand_id=brand_id, entity_type="creative_theme", entity_id=theme_id,
                action="update_status", actor=actor, before=before, after=after)
    conn.commit()
    return after
