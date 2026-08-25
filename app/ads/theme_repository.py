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
from typing import Optional

from app.ads import fingerprint as fp
from app.core.audit import write_audit
from app.core.db import new_id, now_iso, Conn, DEV_ORG_ID


def _rows(cursor) -> list:
    return [dict(r) for r in cursor.fetchall()]


def _row(cursor_row) -> Optional[dict]:
    return dict(cursor_row) if cursor_row is not None else None


def _insert_component(conn: Conn, brand_id: str, campaign_cycle_id: str,
                      theme_id: str, component: dict, ts: str) -> None:
    component_type = component.get("component_type")
    content = component.get("content")
    if not component_type or not str(component_type).strip():
        raise ValueError("元件型別（component_type）為必填")
    if content is None or not str(content).strip():
        raise ValueError("元件內容（content）為必填")
    fingerprint = component.get("fingerprint_json")
    conn.execute(
        "INSERT INTO creative_theme_component (id, org_id, brand_id, campaign_cycle_id,"
        " creative_theme_id, component_type, sequence, content, fingerprint_json,"
        " over_budget, similarity_flag, created_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (new_id("cthc"), DEV_ORG_ID, brand_id, campaign_cycle_id, theme_id, str(component_type).strip(),
         component.get("sequence"), str(content), json.dumps(fingerprint, ensure_ascii=False)
             if fingerprint is not None else None,
         1 if component.get("over_budget") else 0,
         1 if component.get("similarity_flag") else 0, ts),
    )


def create_theme(conn: Conn, brand_id: str, *, campaign_cycle_id: str,
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
        "INSERT INTO creative_theme (id, org_id, brand_id, campaign_cycle_id, experiment_cell_id,"
        " format_key, name, folder_code, status, created_at, updated_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (theme_id, DEV_ORG_ID, brand_id, campaign_cycle_id, experiment_cell_id, format_key.strip(),
         name.strip(), folder_code.strip(), status, ts, ts),
    )
    for component in (components or []):
        _insert_component(conn, brand_id, campaign_cycle_id, theme_id, component, ts)

    after = get_theme(conn, brand_id, theme_id)
    write_audit(conn, brand_id=brand_id, entity_type="creative_theme", entity_id=theme_id,
                action="create", actor=actor, before=None, after=after)
    conn.commit()
    return after


def get_theme(conn: Conn, brand_id: str, theme_id: str) -> Optional[dict]:
    theme = _row(conn.execute(
        "SELECT * FROM creative_theme WHERE brand_id = %s AND id = %s", (brand_id, theme_id)
    ).fetchone())
    if theme is None:
        return None
    theme["components"] = list_theme_components(conn, brand_id, theme_id)
    return theme


def list_theme_components(conn: Conn, brand_id: str, theme_id: str) -> list:
    rows = _rows(conn.execute(
        "SELECT * FROM creative_theme_component WHERE brand_id = %s AND creative_theme_id = %s"
        " ORDER BY sequence, created_at", (brand_id, theme_id),
    ))
    for row in rows:
        if row["fingerprint_json"]:
            row["fingerprint_json"] = json.loads(row["fingerprint_json"])
        _attach_component_decision(conn, brand_id, row)
    return rows


def _attach_component_decision(conn: Conn, brand_id: str, row: dict) -> None:
    """元件退件狀態（票 10）：比照 app/ads/creative.py list_variants() 的既有查法——每則
    元件查一次最新決策，不整批 join（元件數量小，維持既有寫法一致優先於效能）。

    target_type 同時認 'theme_component' 與 'variant'（票 03-close-repoint-gaps）：
    compliance.apply_default_holds()（app/ads/compliance.py:296-320）寫決策時仍用舊代號
    'variant'，target_id 是元件 id（cthc_*，沒有跟舊 variant id 的 cvr_* 撞號的問題）。
    ORDER BY decided_at DESC LIMIT 1 維持「最新決策為準」，restore() 補寫的 theme_component／
    adopted 較晚，會蓋過較早的 variant／rejected，翻案照樣成立。"""
    decision = conn.execute(
        "SELECT * FROM adoption_decision WHERE brand_id = %s"
        " AND target_type IN ('theme_component', 'variant') AND target_id = %s"
        " ORDER BY decided_at DESC LIMIT 1",
        (brand_id, row["id"]),
    ).fetchone()
    row["rejected"] = bool(decision and decision["decision"] == "rejected")
    row["reject_reason_label"] = (
        fp.REJECT_REASON_LABELS.get(decision["reason_code"]) if row["rejected"] else None)
    row["auto_held"] = bool(
        row["rejected"] and decision["reason_code"] == fp.AUTO_HOLD_REASON_CODE)


def get_component(conn: Conn, brand_id: str, component_id: str) -> Optional[dict]:
    row = _row(conn.execute(
        "SELECT * FROM creative_theme_component WHERE brand_id = %s AND id = %s",
        (brand_id, component_id),
    ).fetchone())
    if row is None:
        return None
    if row["fingerprint_json"]:
        row["fingerprint_json"] = json.loads(row["fingerprint_json"])
    _attach_component_decision(conn, brand_id, row)
    return row


def list_themes_for_cell(conn: Conn, brand_id: str,
                         experiment_cell_id: str) -> list:
    """依格查詢：同一個切角格底下的全部主題（含各自元件）。"""
    themes = _rows(conn.execute(
        "SELECT * FROM creative_theme WHERE brand_id = %s AND experiment_cell_id = %s"
        " ORDER BY created_at", (brand_id, experiment_cell_id),
    ))
    for theme in themes:
        theme["components"] = list_theme_components(conn, brand_id, theme["id"])
    return themes


def list_themes_for_cycle(conn: Conn, brand_id: str, campaign_cycle_id: str, *,
                          status: Optional[str] = None) -> list:
    """依期查詢：整個檔期底下的全部主題（含各自元件），可選狀態篩選（票
    02-repoint-creative-readers D2：app/ads/creative.py 的讀取三函式改源後只能透過本檔
    取資料，不得直接查 creative_theme／creative_theme_component，這支補上「依期」的
    查詢入口，比照 list_themes_for_cell()「依格」的既有寫法）。"""
    sql = "SELECT * FROM creative_theme WHERE brand_id = %s AND campaign_cycle_id = %s"
    params = [brand_id, campaign_cycle_id]
    if status:
        sql += " AND status = %s"
        params.append(status)
    sql += " ORDER BY experiment_cell_id, created_at"
    themes = _rows(conn.execute(sql, params))
    for theme in themes:
        theme["components"] = list_theme_components(conn, brand_id, theme["id"])
    return themes


def count_components_by_adoption(conn: Conn, brand_id: str) -> dict:
    """品牌全部元件依「所屬主題是否已採用」計數，跨全部檔期不分期（票
    03-close-repoint-gaps：app/ads/creative_pipeline.py 的駕駛艙內容產線小計改讀本表——
    creative_variant 沒有存活寫入路徑，直接查它兩個數字恆為 0）。`creative.list_variants()`
    是逐期、只回已採用的，表達不了 pending，所以另開這支跨期計數，不透過 creative.py。
    pending＝主題狀態非 adopted 的元件，published＝主題狀態是 adopted 的元件，保留舊表
    逐則計數的細度。沒有任何元件時兩者皆回 0。"""
    row = conn.execute(
        "SELECT"
        " SUM(CASE WHEN t.status = 'adopted' THEN 1 ELSE 0 END) AS published,"
        " SUM(CASE WHEN t.status != 'adopted' THEN 1 ELSE 0 END) AS pending"
        " FROM creative_theme_component c JOIN creative_theme t ON t.id = c.creative_theme_id"
        " WHERE c.brand_id = %s", (brand_id,),
    ).fetchone()
    return {"pending": row["pending"] or 0, "published": row["published"] or 0}


def update_theme_status(conn: Conn, brand_id: str, theme_id: str, *,
                        status: str, actor: str) -> dict:
    before = get_theme(conn, brand_id, theme_id)
    if before is None:
        raise ValueError(f"找不到主題：{theme_id}")
    if not status or not status.strip():
        raise ValueError("狀態為必填")
    if not actor or not actor.strip():
        raise ValueError("actor 為必填")

    conn.execute(
        "UPDATE creative_theme SET status = %s, updated_at = %s WHERE brand_id = %s AND id = %s",
        (status.strip(), now_iso(), brand_id, theme_id),
    )
    after = get_theme(conn, brand_id, theme_id)
    write_audit(conn, brand_id=brand_id, entity_type="creative_theme", entity_id=theme_id,
                action="update_status", actor=actor, before=before, after=after)
    conn.commit()
    return after


# ---------------------------------------------------------------------------
# 採用／退件（票 10-adopt-reject）：決策對象擴為「主題整包」與「單一元件」兩種顆粒度，
# 沿用既有 adoption_decision 表與 fingerprint.REJECT_REASON_LABELS 理由碼清單，不新造。
# ---------------------------------------------------------------------------

def adopt_theme(conn: Conn, brand_id: str, theme_id: str, *, actor: str) -> dict:
    """一鍵採用：主題狀態改採用，一次動作寫一筆主題級決策紀錄（AC1）。全部元件隨主題狀態
    一併算採用——不逐元件建決策列（AC3：不提供逐欄位勾選採用），元件層沒有獨立的
    「已採用」狀態可查，是否算數看主題本身的 status。
    """
    before = get_theme(conn, brand_id, theme_id)
    if before is None:
        raise ValueError(f"找不到主題：{theme_id}")
    if not actor or not actor.strip():
        raise ValueError("actor 為必填")

    ts = now_iso()
    conn.execute(
        "UPDATE creative_theme SET status = 'adopted', updated_at = %s WHERE brand_id = %s AND id = %s",
        (ts, brand_id, theme_id),
    )
    conn.execute(
        "INSERT INTO adoption_decision (id, org_id, brand_id, campaign_cycle_id, target_type, target_id,"
        " decision, decided_by, decided_at) VALUES (%s, %s, %s, %s, 'theme', %s, 'adopted', %s, %s)",
        (new_id("adp"), DEV_ORG_ID, brand_id, before["campaign_cycle_id"], theme_id, actor, ts),
    )
    after = get_theme(conn, brand_id, theme_id)
    write_audit(conn, brand_id=brand_id, entity_type="creative_theme", entity_id=theme_id,
                action="adopt", actor=actor, before=before, after=after)
    conn.commit()
    return after


def reject_component(conn: Conn, brand_id: str, component_id: str, *,
                     reason_code: str, actor: str, reason_text: Optional[str] = None) -> dict:
    """單一元件退件＋理由（AC2）：元件除名——不從資料表刪掉（append-only 稽核慣例），
    `list_theme_components()`／`get_component()` 之後回傳時標 `rejected=True`。理由碼與
    元件當下的指紋快照寫進 adoption_decision，跟 app/ads/creative.py `reject()`／
    `_rejection_constraints()` 走同一張表、同一套讀法，下次簡報的拒絕約束天生帶得到它
    （brief_assembler 已經在用 `_rejection_constraints()`，不必另寫一套）。
    只影響這一個元件，同主題其他元件與主題本身狀態都不動（AC3）。
    """
    component = get_component(conn, brand_id, component_id)
    if component is None:
        raise ValueError(f"找不到元件：{component_id}")
    if reason_code not in fp.REJECT_REASON_LABELS:
        raise ValueError("請選一個理由")
    if not actor or not actor.strip():
        raise ValueError("actor 為必填")

    before = {"rejected": component["rejected"]}
    ts = now_iso()
    conn.execute(
        "INSERT INTO adoption_decision (id, org_id, brand_id, campaign_cycle_id, target_type, target_id,"
        " decision, reason_code, reason_text, fingerprint_json, decided_by, decided_at)"
        " VALUES (%s, %s, %s, %s, 'theme_component', %s, 'rejected', %s, %s, %s, %s, %s)",
        (new_id("adp"), DEV_ORG_ID, brand_id, component["campaign_cycle_id"], component_id, reason_code,
         (reason_text or "").strip() or None,
         json.dumps(component["fingerprint_json"] or {}, ensure_ascii=False), actor, ts),
    )
    after = get_component(conn, brand_id, component_id)
    write_audit(conn, brand_id=brand_id, entity_type="creative_theme_component",
                entity_id=component_id, action="reject", actor=actor,
                before=before, after={"rejected": after["rejected"], "reason_code": reason_code})
    conn.commit()
    return after
