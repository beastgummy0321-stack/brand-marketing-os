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

from typing import Optional

from app.ads import inflation as ads_inflation
from app.core.db import new_id, now_utc, jsonb, DEV_ORG_ID

# 第 7 刀（A1 三層地界新規則：app/ads 不得 import app.orders，見
# test_architecture_boundaries.py）：orders_repo 不在這裡 import，改由組裝根
# app/main.py 啟動時注入真正的 app.orders.repository 模組。
orders_repo = None


def _next_version(conn, cycle_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(version), 0) v FROM settlement_version WHERE campaign_cycle_id = %s",
        (cycle_id,),
    ).fetchone()
    return row["v"] + 1


def _data_arrival(conn, brand_id: str, cycle: dict) -> tuple:
    """各源最後到達這期資料的時間；沒資料的源同時列進缺席清單（決策 0025 補遺 C）。"""
    meta_row = conn.execute(
        "SELECT MAX(snapshot_taken_at) t FROM performance_snapshot"
        " WHERE brand_id = %s AND campaign_cycle_id = %s AND quarantined = false",
        (brand_id, cycle["id"]),
    ).fetchone()
    orders_rows = orders_repo.list_orders_in_range(
        conn, brand_id, cycle["start_date"], cycle["end_date"])
    orders_arrival = max((o["updated_at"] for o in orders_rows), default=None)
    ga4_row = conn.execute(
        "SELECT MAX(synced_at) t FROM ga4_sync_status WHERE brand_id = %s", (brand_id,)
    ).fetchone()

    # 三個來源的到達時間都是 timestamptz，isoformat() 轉字串再落 jsonb——data_arrival_json
    # 存的是給人看／給前端顯示的快照，不是要保留 datetime 物件（02-3b）。
    arrival = {
        "meta": meta_row["t"].isoformat() if meta_row and meta_row["t"] else None,
        "orders": orders_arrival.isoformat() if orders_arrival else None,
        "ga4": ga4_row["t"].isoformat() if ga4_row and ga4_row["t"] else None,
    }
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
    ts = now_utc()
    version = _next_version(conn, cycle_id)
    reason = trigger_reason or ("initial" if version == 1 else "manual_rerun")

    settlement_id = new_id("setv")
    conn.execute(
        "INSERT INTO settlement_version (id, org_id, brand_id, campaign_cycle_id, version,"
        " trigger_reason, is_post_close, created_by, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (settlement_id, DEV_ORG_ID, brand_id, cycle_id, version, reason,
         cycle.get("status") == "CLOSED", actor, ts),
    )

    arrival, missing = _data_arrival(conn, brand_id, cycle)
    coefficient = ads_inflation.latest_coefficient(conn, brand_id)
    sku_costs = orders_repo.list_effective_sku_costs(conn, brand_id)

    summary = {"cycle": cycle_totals, "products": per_product}
    snapshot_id = new_id("rsnap")
    conn.execute(
        "INSERT INTO reading_snapshot (id, org_id, brand_id, campaign_cycle_id, settlement_version_id,"
        " coefficient_version_id, data_arrival_json, missing_sources_json, summary_json,"
        " created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (snapshot_id, DEV_ORG_ID, brand_id, cycle_id, settlement_id,
         coefficient["id"] if coefficient else None,
         jsonb(arrival), jsonb(missing),
         # summary 混雜多來源算出來的數字（可能含 Decimal／datetime）；db.jsonb() 內建
         # 的 _json_default 已經接住這兩種型別，不用再自己包一層 dumps（02-3b）。
         jsonb(summary), ts),
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
            "INSERT INTO reading_snapshot_input (id, org_id, brand_id, campaign_cycle_id,"
            " reading_snapshot_id, scope, key, value, created_at) VALUES"
            " (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (new_id("rsin"), DEV_ORG_ID, brand_id, cycle_id, snapshot_id, scope, key,
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
            " WHERE rs.brand_id = %s AND rs.campaign_cycle_id = %s"
            " ORDER BY sv.version DESC LIMIT 1", (brand_id, cycle_id),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT rs.*, sv.version AS settlement_version,"
            " sv.trigger_reason, sv.is_post_close, sv.diff_summary FROM reading_snapshot rs"
            " JOIN settlement_version sv ON sv.id = rs.settlement_version_id"
            " WHERE rs.brand_id = %s AND rs.campaign_cycle_id = %s AND sv.version = %s",
            (brand_id, cycle_id, version),
        ).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["data_arrival"] = data.pop("data_arrival_json")
    data["missing_sources"] = data.pop("missing_sources_json")
    data["summary"] = data.pop("summary_json")
    return data


def record_diff_summary(conn, brand_id: str, cycle_id: str, settlement_version_id: str,
                        summary_text: str) -> None:
    """補件觸發的重判把差異摘要人話說明記回那一版 settlement_version（issue #38：
    不靜默覆蓋——UI 看這欄有沒有值就知道這版是不是補件自動觸發的）。"""
    conn.execute(
        "UPDATE settlement_version SET diff_summary = %s WHERE id = %s AND brand_id = %s"
        " AND campaign_cycle_id = %s",
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
                " WHERE rs.brand_id = %s AND rs.campaign_cycle_id = %s AND sv.version = %s",
                (brand_id, cycle_id, version),
            )
        }
    before, after = _inputs(version_a), _inputs(version_b)
    keys = sorted(set(before) | set(after))
    return [(scope, key, before.get((scope, key)), after.get((scope, key)))
           for scope, key in keys if before.get((scope, key)) != after.get((scope, key))]


# 票 R4-late-data-downstream：翻盤警示訊息組裝集中放這裡（不是 reading.py）——`reading.py`
# 跟 `nextcycle.py` 都已經頂在 800 行上限邊緣（見 docs/tech-debt.md 第一節），這兩顆函式
# 都只是讀 `diff_versions()`／`settlement_version` 現有資料，跟這個檔案本來的主題（版次
# 差異）同一國，不必為了塞位置硬去拆已經滿版的檔案。
REVERSAL_MESSAGE = "補件後判讀翻盤，這期結論整個變了，去看新結論。"

# B0-35 加查核提醒版：收件匣卡片「一卡一句 ≤30 全形字」（DESIGN.md §20 規則 4，
# `app/core/interrupts.py:71` MAX_MESSAGE_LEN）——晚到營收占比與百分比放不進同一句，
# 完整說明改放在匯入訊息（`late_revenue_share_warning()` 回傳值，接進 `explanation`，
# 沒有這個字數上限），這裡的卡片訊息只換一句同樣≤30字、但點名要查核的版本。
REVERSAL_MESSAGE_WITH_LATE_REVENUE = "補件翻盤但晚到營收占比高，去看新結論並查核。"

# B0-35：單筆晚到訂單佔了這期營收快一半，系統卻直接把它當真翻案。45% 是驗收 B0 演練踩到
# 的真實案例；30% 取一個明顯低於那個案例、但高於零星幾筆訂單的正常補件波動（實務上一成
# 上下）的量級——單一批次占比一旦過三分之一，才值得先停下來查是不是誤植或灌水，不是每次
# 補件都要吵。
LATE_REVENUE_SHARE_WARNING_THRESHOLD = 0.30


def late_revenue_share_warning(diffs: list) -> Optional[str]:
    """`diffs`＝`diff_versions()` 的回傳值。只看檔期層營收這一鍵，算這次補件新增的營收
    占補件後總營收的比例；沒有營收變動、算不出來、或沒超過門檻都回 None（分級不吵，
    決策 0025）。"""
    revenue_diff = next(((b, a) for scope, key, b, a in diffs if scope == "cycle" and key == "revenue"), None)
    if revenue_diff is None:
        return None
    try:
        before, after = float(revenue_diff[0] or 0), float(revenue_diff[1] or 0)
    except (TypeError, ValueError):
        return None
    if after <= 0 or after <= before:
        return None
    share = (after - before) / after
    if share <= LATE_REVENUE_SHARE_WARNING_THRESHOLD:
        return None
    return f"這筆晚到營收占本期營收 {share:.0%}，建議先查核是真的晚到訂單還是誤植，再決定要不要翻案"


def latest_version_delta(conn, brand_id: str, cycle_id: str) -> Optional[dict]:
    """這期最近兩個判讀版次之間，營收／ROAS 差了多少（B0-25：下期預算建議悄悄改了金額卻
    不說原因，要靠這個現算出「為什麼」）。只有一個版次或找不到快照就回 None——不硬編。"""
    versions = [r["version"] for r in conn.execute(
        "SELECT version FROM settlement_version WHERE brand_id = %s AND campaign_cycle_id = %s"
        " ORDER BY version DESC LIMIT 2", (brand_id, cycle_id)).fetchall()]
    if len(versions) < 2:
        return None
    after, before = load_snapshot(conn, brand_id, cycle_id, version=versions[0]), \
                    load_snapshot(conn, brand_id, cycle_id, version=versions[1])
    if not after or not before:
        return None
    prev_cycle, cur_cycle = (before["summary"].get("cycle") or {}), (after["summary"].get("cycle") or {})
    return {
        "prev_revenue": prev_cycle.get("revenue"), "cur_revenue": cur_cycle.get("revenue"),
        "prev_roas": (prev_cycle.get("kpis") or {}).get("roas"),
        "cur_roas": (cur_cycle.get("kpis") or {}).get("roas"),
    }


def demo() -> None:
    """python -m app.ads.settlement — 純函數自檢：攤平邏輯＋晚到營收占比警語。"""
    flat = _flatten("cycle", {"spend": 100, "kpis": {"roas": 2.5}})
    assert ("cycle", "spend", 100) in flat
    assert ("cycle", "kpis.roas", 2.5) in flat
    assert late_revenue_share_warning([("cycle", "revenue", 55, 100)]) is not None
    assert late_revenue_share_warning([("cycle", "revenue", 90, 100)]) is None  # 10% 不吵
    assert late_revenue_share_warning([("cycle", "spend", 1, 2)]) is None  # 沒有營收這一鍵
    print("settlement 自檢通過")


if __name__ == "__main__":
    demo()
