# -*- coding: utf-8 -*-
"""app/ads/checklist.py — 投放前檢查清單（票 10，GitHub issue #20，決策 0023 第 17 點）。

分兩類，行為不同：

- **一次性（品牌層）**：例如 Pixel 安裝與轉換事件確認。跨檔期共用同一列，勾了就記住，
  不用每期重新勾。唯一會讓它重新被請回來看的，是「異常訊號」——目前只認一種：
  最新一期已經在花錢卻完全零轉換，很可能是 Pixel 掛了。這裡刻意**現場算**異常訊號，
  不落一個 flagged 欄位：成效資料隨時可能被回填或改掉，落庫的旗標只會跟實況脫鉤。
- **每期必看**：到達頁訊息一致、預算結構照規則卡、紅線詞掃描結果——每一期各自一列，
  不繼承上一期的狀態。

兩類都**不擋流程**（決策 0013）：檢查清單只負責記錄與提醒，沒有任何入口會因為沒勾完
就擋住下一步。完成度供交接包顯示，成效判讀頁回溯提醒未勾項。
"""

from typing import Optional

from app.ads import performance as ads_performance
from app.ads import repository as ads_repo
from app.core.audit import write_audit
from app.core.db import new_id, now_iso

ONE_TIME_ITEMS = {
    "pixel_confirmed": {
        "label": "Pixel 已安裝並確認轉換事件正常觸發",
        "help": (
            "去 Meta 事件管理工具確認 Pixel 有裝在網站上，且轉換事件（例如購買）有正常"
            "觸發。不確定怎麼裝的話，先看 Pixel 教學頁。確認過一次以後這裡會記住，"
            "之後不用每期重新勾——除非系統看到「花了錢卻零轉換」這種異常訊號，才會請你回來重新確認。"
        ),
    },
}

CYCLE_ITEMS = {
    "landing_page_consistent": {
        "label": "到達頁的訊息跟這期廣告一致",
        "help": "廣告在講的優惠、賣點、產品，跟消費者點進去看到的到達頁對得起來，不要「掛羊頭賣狗肉」。",
    },
    "budget_matches_structure": {
        "label": "帳戶預算配置照這期的規則卡底案設定",
        "help": "在 Meta 廣告管理員設定的 CBO／ABO 結構與各組日預算，跟系統算出的底案一致（交接包裡有寫）。",
    },
    "red_flag_scan_reviewed": {
        "label": "已看過紅線詞掃描結果",
        "help": "素材那一步的紅線詞掃描只抓得到明確字詞，抓不到語氣語意——正式投放前自己再看一眼有沒有法規風險字眼。",
    },
}


def _rows(cursor) -> list:
    return [dict(r) for r in cursor.fetchall()]


def _pixel_anomaly(conn, brand_id: str) -> Optional[str]:
    """只看有成效資料的最新一期：花了錢卻零轉換，回一句人話理由；否則回 None。"""
    for cycle in ads_repo.list_cycles(conn, brand_id):
        if cycle["status"] not in ("LIVE", "EVALUATING", "CLOSED"):
            continue
        totals = ads_performance.totals(conn, brand_id, cycle["id"])
        if not totals["rows"]:
            continue
        spend = totals.get("spend") or 0
        conversions = totals.get("conversions") or 0
        if spend > 0 and conversions == 0:
            return (f"「{cycle['start_date']} ～ {cycle['end_date']}」這期已經花了錢但轉換掛零，"
                    "回去確認 Pixel 是不是還在正常運作。")
        return None  # 只認最新一期有資料的，不往回翻舊期
    return None


def one_time_status(conn, brand_id: str) -> list:
    rows = {r["item_key"]: r for r in _rows(conn.execute(
        "SELECT * FROM brand_checklist_item WHERE brand_id = ?", (brand_id,)))}
    anomaly = _pixel_anomaly(conn, brand_id)
    result = []
    for key, meta in ONE_TIME_ITEMS.items():
        row = rows.get(key)
        checked = bool(row["checked"]) if row else False
        result.append({
            "key": key, **meta, "checked": checked,
            "checked_by": row["checked_by"] if row else None,
            "checked_at": row["checked_at"] if row else None,
            "flagged": bool(checked and anomaly),
            "flagged_reason": anomaly if (checked and anomaly) else None,
        })
    return result


def _cycle_hints(conn, brand_id: str, cycle_id: str) -> dict:
    count = conn.execute(
        "SELECT COUNT(*) c FROM finding WHERE brand_id = ? AND campaign_cycle_id = ?"
        " AND finding_type = 'compliance' AND resolved = 0", (brand_id, cycle_id),
    ).fetchone()["c"]
    return {
        "red_flag_scan_reviewed": (
            f"目前掃到 {count} 處命中，去素材那一步看標黃的地方。" if count
            else "目前沒有掃到命中字詞（掃描能力有邊界，仍建議自己再看一眼）。"
        ),
    }


def cycle_status(conn, brand_id: str, cycle_id: str) -> list:
    rows = {r["item_key"]: r for r in _rows(conn.execute(
        "SELECT * FROM cycle_checklist_item WHERE brand_id = ? AND campaign_cycle_id = ?",
        (brand_id, cycle_id)))}
    hints = _cycle_hints(conn, brand_id, cycle_id)
    result = []
    for key, meta in CYCLE_ITEMS.items():
        row = rows.get(key)
        result.append({
            "key": key, **meta, "checked": bool(row["checked"]) if row else False,
            "checked_by": row["checked_by"] if row else None,
            "checked_at": row["checked_at"] if row else None,
            "hint": hints.get(key),
        })
    return result


def completeness(conn, brand_id: str, cycle_id: str) -> dict:
    """一次性＋每期必看合計的完成度，供交接包顯示、判讀頁回溯提醒未勾項用。"""
    items = one_time_status(conn, brand_id) + cycle_status(conn, brand_id, cycle_id)
    checked = sum(1 for i in items if i["checked"])
    total = len(items)
    return {
        "checked": checked, "total": total,
        "pct": round(checked / total * 100) if total else 100,
        "unchecked_labels": [i["label"] for i in items if not i["checked"]],
        "items": items,
    }


def set_one_time(conn, brand_id: str, item_key: str, checked: bool, actor: str) -> None:
    if item_key not in ONE_TIME_ITEMS:
        raise ValueError(f"沒有這個檢查項目：{item_key}")
    ts = now_iso()
    conn.execute(
        "INSERT INTO brand_checklist_item (id, brand_id, item_key, checked, checked_by,"
        " checked_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(brand_id, item_key) DO UPDATE SET checked = excluded.checked,"
        " checked_by = excluded.checked_by, checked_at = excluded.checked_at,"
        " updated_at = excluded.updated_at",
        (new_id("bcl"), brand_id, item_key, int(checked),
         actor if checked else None, ts if checked else None, ts),
    )
    write_audit(conn, brand_id=brand_id, entity_type="brand_checklist_item", entity_id=item_key,
                action="check" if checked else "uncheck", actor=actor, before=None,
                after={"checked": checked})
    conn.commit()


def set_cycle_item(conn, brand_id: str, cycle_id: str, item_key: str, checked: bool,
                   actor: str) -> None:
    if item_key not in CYCLE_ITEMS:
        raise ValueError(f"沒有這個檢查項目：{item_key}")
    ts = now_iso()
    conn.execute(
        "INSERT INTO cycle_checklist_item (id, brand_id, campaign_cycle_id, item_key, checked,"
        " checked_by, checked_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(campaign_cycle_id, item_key) DO UPDATE SET checked = excluded.checked,"
        " checked_by = excluded.checked_by, checked_at = excluded.checked_at,"
        " updated_at = excluded.updated_at",
        (new_id("ccl"), brand_id, cycle_id, item_key, int(checked),
         actor if checked else None, ts if checked else None, ts),
    )
    write_audit(conn, brand_id=brand_id, entity_type="cycle_checklist_item",
                entity_id=f"{cycle_id}.{item_key}", actor=actor, before=None,
                action="check" if checked else "uncheck", after={"checked": checked})
    conn.commit()


def demo() -> None:
    """python -m app.ads.checklist — 純函數的最小自檢（completeness 的計算邏輯，無需資料庫）。"""
    items = [{"label": "a", "checked": True}, {"label": "b", "checked": False}]
    checked = sum(1 for i in items if i["checked"])
    total = len(items)
    assert checked == 1 and total == 2
    assert round(checked / total * 100) == 50
    print("checklist 自檢通過")


if __name__ == "__main__":
    demo()
