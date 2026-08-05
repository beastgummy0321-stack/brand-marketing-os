# -*- coding: utf-8 -*-
"""app/ads/settlement.py — 結算版次＋判讀快照基建（GitHub issue #37，決策 0025 審查補遺 C：
「結算版本化＋判讀快照」）。

判讀流程改成「先凍結快照、再算判定」：app/ads/reading.py 的 run() 在算出這期的原始彙總
（cycle_totals／per_product）之後、丟進 judge() 算結論之前，先呼叫這裡的 freeze() 把
判讀當下的畫面定格——各源資料最後到達時間、缺席清單、生效中的灌水係數版本
（app/ads/inflation.py 的 ad_revenue_coefficient）、生效中的 SKU 成本版本
（app/orders/repository.py 的 sku_cost_version）、關鍵彙總數字。之後成本回改、係數重新
校準都不會偷改到這筆快照——它引用的是版本 id，不是現行值。

快照存兩層（issue #37 承重設計，避免踩雷）：
- reading_snapshot：一列，summary_json 給人看的彙總（畫面直接顯示用）。
- reading_snapshot_input：多列 key-value，把彙總攤平成一鍵一列——「這期第 2 版跟第 1 版
  差在哪」直接用 settlement_version.version 對兩批明細 join 比對，不用寫 JSON diff。

settlement_version 只負責版次號碼、觸發原因、是否結案後才動的旗標，不重複存數字——
沿用既有 ad_revenue_coefficient 的 valid_from/valid_to 版本模式與 audit_log 慣例，
不造新引擎（決策 0025：「沿用既有 append-only 與 audit_log 模式，不造新引擎」）。

不算判讀結論：這裡只負責「記下判讀當下看到了什麼」，狀態判定仍在 reading.judge()
（鐵則 4：數字走程式）。
"""

import json
from typing import Optional

from app.ads import inflation as ads_inflation
from app.core.db import new_id, now_iso

# 第 7 刀（A1 三層地界新規則：app/ads 不得 import app.orders，見
# test_architecture_boundaries.py）：orders_repo 不在這裡 import，改由組裝根
# app/main.py 啟動時注入真正的 app.orders.repository 模組。
orders_repo = None


def _next_version(conn, cycle_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(version), 0) v FROM settlement_version WHERE campaign_cycle_id = ?",
        (cycle_id,),
    ).fetchone()
    return row["v"] + 1


def _data_arrival(conn, brand_id: str, cycle: dict) -> tuple:
    """各源最後到達這期資料的時間；沒資料的源同時列進缺席清單（決策 0025 補遺 C）。"""
    meta_row = conn.execute(
        "SELECT MAX(snapshot_taken_at) t FROM performance_snapshot"
        " WHERE brand_id = ? AND campaign_cycle_id = ? AND quarantined = 0",
        (brand_id, cycle["id"]),
    ).fetchone()
    orders_rows = orders_repo.list_orders_in_range(
        conn, brand_id, cycle["start_date"], cycle["end_date"])
    orders_arrival = max((o["updated_at"] for o in orders_rows), default=None)
    ga4_row = conn.execute(
        "SELECT MAX(synced_at) t FROM ga4_sync_status WHERE brand_id = ?", (brand_id,)
    ).fetchone()

    arrival = {"meta": meta_row["t"] if meta_row else None, "orders": orders_arrival,
               "ga4": ga4_row["t"] if ga4_row else None}
    missing = [source for source, value in arrival.items() if not value]
    return arrival, missing


def _flatten(scope: str, data: dict) -> list:
    """把彙總 dict 攤平成 (scope, key, value)：巢狀 dict（如 kpis）攤成 `kpis.roas` 這種點記法，
    讓兩個版次的明細能逐鍵比對（issue #37 acceptance：快照逐位可比對）。"""
    out = []
    for key, value in data.items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                out.append((scope, f"{key}.{sub_key}", sub_value))
        else:
            out.append((scope, key, value))
    return out


def freeze(conn, brand_id: str, cycle: dict, *, actor: str, cycle_totals: dict,
          per_product: dict, trigger_reason: Optional[str] = None) -> dict:
    """凍結一版判讀快照：寫一筆新 settlement_version＋一筆 reading_snapshot（彙總＋明細兩層）。

    同一期每呼叫一次就多一版（append-only，不覆寫舊版），version 從 1 起遞增
    （issue #37 acceptance：同一期重跑判讀必產生新版次）。
    """
    if not actor or not actor.strip():
        raise ValueError("actor 為必填")
    cycle_id = cycle["id"]
    ts = now_iso()
    version = _next_version(conn, cycle_id)
    reason = trigger_reason or ("initial" if version == 1 else "manual_rerun")

    settlement_id = new_id("setv")
    conn.execute(
        "INSERT INTO settlement_version (id, brand_id, campaign_cycle_id, version,"
        " trigger_reason, is_post_close, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (settlement_id, brand_id, cycle_id, version, reason,
         1 if cycle.get("status") == "CLOSED" else 0, actor, ts),
    )

    arrival, missing = _data_arrival(conn, brand_id, cycle)
    coefficient = ads_inflation.latest_coefficient(conn, brand_id)
    sku_costs = orders_repo.list_effective_sku_costs(conn, brand_id)

    summary = {"cycle": cycle_totals, "products": per_product}
    snapshot_id = new_id("rsnap")
    conn.execute(
        "INSERT INTO reading_snapshot (id, brand_id, campaign_cycle_id, settlement_version_id,"
        " coefficient_version_id, data_arrival_json, missing_sources_json, summary_json,"
        " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (snapshot_id, brand_id, cycle_id, settlement_id,
         coefficient["id"] if coefficient else None,
         json.dumps(arrival, ensure_ascii=False), json.dumps(missing, ensure_ascii=False),
         json.dumps(summary, ensure_ascii=False, default=str), ts),
    )

    inputs = _flatten("cycle", cycle_totals)
    for product_id, totals in per_product.items():
        inputs.extend(_flatten(product_id, totals))
    for cost in sku_costs:
        scope = f"sku_cost:{cost['sku']}"
        inputs.append((scope, "unit_cost", cost["unit_cost"]))
        inputs.append((scope, "version_id", cost["id"]))
    for scope, key, value in inputs:
        conn.execute(
            "INSERT INTO reading_snapshot_input (id, brand_id, campaign_cycle_id,"
            " reading_snapshot_id, scope, key, value, created_at) VALUES"
            " (?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id("rsin"), brand_id, cycle_id, snapshot_id, scope, key,
             None if value is None else str(value), ts),
        )

    conn.commit()
    return {"settlement_version_id": settlement_id, "version": version,
           "reading_snapshot_id": snapshot_id, "trigger_reason": reason,
           "missing_sources": missing}


def load_snapshot(conn, brand_id: str, cycle_id: str, version: Optional[int] = None) -> Optional[dict]:
    """讀回某一版快照（不傳 version 給最新版）；沒判讀過回 None。"""
    # rs.* 已經帶 settlement_version_id（reading_snapshot 自己的外鍵欄），不用再從 sv.id 重複選一次。
    if version is None:
        row = conn.execute(
            "SELECT rs.*, sv.version AS settlement_version,"
            " sv.trigger_reason, sv.is_post_close, sv.diff_summary FROM reading_snapshot rs"
            " JOIN settlement_version sv ON sv.id = rs.settlement_version_id"
            " WHERE rs.brand_id = ? AND rs.campaign_cycle_id = ?"
            " ORDER BY sv.version DESC LIMIT 1", (brand_id, cycle_id),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT rs.*, sv.version AS settlement_version,"
            " sv.trigger_reason, sv.is_post_close, sv.diff_summary FROM reading_snapshot rs"
            " JOIN settlement_version sv ON sv.id = rs.settlement_version_id"
            " WHERE rs.brand_id = ? AND rs.campaign_cycle_id = ? AND sv.version = ?",
            (brand_id, cycle_id, version),
        ).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["data_arrival"] = json.loads(data.pop("data_arrival_json"))
    data["missing_sources"] = json.loads(data.pop("missing_sources_json"))
    data["summary"] = json.loads(data.pop("summary_json"))
    return data


def record_diff_summary(conn, brand_id: str, cycle_id: str, settlement_version_id: str,
                        summary_text: str) -> None:
    """補件觸發的重判把差異摘要人話說明記回那一版 settlement_version（issue #38：
    不靜默覆蓋——UI 看這欄有沒有值就知道這版是不是補件自動觸發的）。"""
    conn.execute(
        "UPDATE settlement_version SET diff_summary = ? WHERE id = ? AND brand_id = ?"
        " AND campaign_cycle_id = ?",
        (summary_text, settlement_version_id, brand_id, cycle_id),
    )
    conn.commit()


def diff_versions(conn, brand_id: str, cycle_id: str, version_a: int, version_b: int) -> list:
    """逐鍵比對兩個版次的快照明細，回傳有變動的 [(scope, key, before, after)]
    （issue #37 acceptance 自檢：快照逐位可比對）。"""
    def _inputs(version):
        return {
            (r["scope"], r["key"]): r["value"]
            for r in conn.execute(
                "SELECT rsin.scope, rsin.key, rsin.value FROM reading_snapshot_input rsin"
                " JOIN reading_snapshot rs ON rs.id = rsin.reading_snapshot_id"
                " JOIN settlement_version sv ON sv.id = rs.settlement_version_id"
                " WHERE rs.brand_id = ? AND rs.campaign_cycle_id = ? AND sv.version = ?",
                (brand_id, cycle_id, version),
            )
        }
    before, after = _inputs(version_a), _inputs(version_b)
    keys = sorted(set(before) | set(after))
    return [(scope, key, before.get((scope, key)), after.get((scope, key)))
           for scope, key in keys if before.get((scope, key)) != after.get((scope, key))]


def demo() -> None:
    """python -m app.ads.settlement — 純函數自檢：攤平邏輯。"""
    flat = _flatten("cycle", {"spend": 100, "kpis": {"roas": 2.5}})
    assert ("cycle", "spend", 100) in flat
    assert ("cycle", "kpis.roas", 2.5) in flat
    print("settlement 自檢通過")


if __name__ == "__main__":
    demo()
