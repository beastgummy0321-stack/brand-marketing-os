# -*- coding: utf-8 -*-
"""app/ads/inflation.py — Meta 灌水係數＋期別對帳頁（GitHub issue #36，決策 0025 七題定案
第 1 點「系統累積『Meta 灌水係數』並記錄每次事後誤差」＋懶人優先總則第 1 點自適應降頻）。

對帳的兩邊：
- Meta 自報營收 = app/ads/performance.py 這期未隔離的 revenue 加總（含 ROAS 反推列，
  但用 revenue_by_source 拆開，讓人看得出哪些是反推——issue #36 acceptance 1）。
- 訂單實收營收 = app/ads/codes.py attribution_summary 的「淨歸因」（判讀一律用淨歸因，
  決策 0025 補遺第 3 點），不重寫一份歸因邏輯。

係數 = 訂單實收 ÷ Meta 自報。每次校準寫一筆新版本（valid_from/valid_to 生效區間），
並且拿「上一版係數 × 這期 Meta 自報」預測這期訂單實收，跟真正的訂單實收算誤差，
記進事後誤差紀錄（決策 0025：「係數統計誠實…每次引用後記事後誤差」）。

自適應降頻：最近幾次事後誤差都在容忍範圍內＝係數穩定，校準頻率從「每期」降為「每季」，
規則判定、不用 LLM（鐵則 4）。
"""

from datetime import date, timedelta
from typing import Optional

from app.ads import codes as ads_codes
from app.ads import ga4_sync as ads_ga4_sync
from app.ads import performance as ads_performance
from app.ads import repository as ads_repo
from app.core import interrupts as core_interrupts
from app.core.audit import write_audit
from app.core.db import new_id, now_utc, DEV_ORG_ID

# 第 7 刀（A1 三層地界新規則：app/ads 不得 import app.orders，見
# test_architecture_boundaries.py）：orders_repo 不在這裡 import，改由組裝根
# app/main.py 啟動時注入真正的 app.orders.repository 模組。
orders_repo = None

# 樣本量門檻：累積校準次數達到這個數字前，係數標「不可靠，暫用保守預設」
# （決策 0025：「灌水係數附樣本門檻，不足標『不可靠，暫用保守預設』」）。
SAMPLE_THRESHOLD = 3

# 保守預設＝未校準前不做任何灌水調整，直接採信 Meta 自報數字（1.0 倍）。
DEFAULT_COEFFICIENT = 1.0

# 自適應降頻：最近這幾次事後誤差都落在容忍範圍內才算「穩定」，觸發降頻為每季抽查。
STABILITY_WINDOW = 3
STABILITY_TOLERANCE = 0.15  # 誤差 ±15% 以內算穩定

QUARTERLY_INTERVAL_DAYS = 90
# 校準新鮮度衰減門檻：cadence 各自的「新鮮」「稍舊」分界（超過稍舊門檻＝已過期）。
FRESH_DAYS = {"per_cycle": 30, "quarterly": 90}
STALE_DAYS = {"per_cycle": 60, "quarterly": 180}


# ---------------------------------------------------------------------------
# 對帳：Meta 自報 vs 訂單實收
# ---------------------------------------------------------------------------

def reconcile_cycle(conn, brand_id: str, cycle_id: str) -> dict:
    """並列這期 Meta 自報營收與訂單實收營收。沒有訂單資料時誠實回覆對不了帳
    （0025 補遺第 3 點：無碼且無法歸因的訂單不計入廣告成效——這裡是反面：沒配碼
    或這段期間完全沒有訂單，代表訂單那一側的數字根本不存在，不是「剛好等於 0」）。
    """
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    if cycle is None:
        raise ValueError("找不到廣告檔期")

    revenue_breakdown = ads_performance.revenue_by_source(conn, brand_id, cycle_id)
    meta_revenue = revenue_breakdown["total"]

    codes = ads_codes.list_codes(conn, brand_id, cycle_id)
    has_ad_code = any(c["source_type"] == "ad" for c in codes)
    has_orders = bool(orders_repo.list_orders_in_range(
        conn, brand_id, cycle["start_date"], cycle["end_date"]))

    if not has_orders:
        return {"available": False, "reason": "這段期間沒有訂單資料，沒辦法對帳。",
                "meta_revenue": meta_revenue, "revenue_breakdown": revenue_breakdown}
    if not has_ad_code:
        return {"available": False,
                "reason": "這期還沒有配廣告碼，訂單沒辦法歸因到這次廣告，沒辦法對帳。",
                "meta_revenue": meta_revenue, "revenue_breakdown": revenue_breakdown}

    attribution = ads_codes.attribution_summary(conn, brand_id, cycle_id)
    order_revenue = attribution["net"]["net_revenue"]
    coefficient_now = (round(order_revenue / meta_revenue, 4) if meta_revenue else None)

    return {"available": True, "meta_revenue": meta_revenue, "order_revenue": order_revenue,
            "gross_order_revenue": attribution["gross"]["net_revenue"],
            "revenue_breakdown": revenue_breakdown, "coefficient_now": coefficient_now,
            "order_count": attribution["net"]["count"]}


# ---------------------------------------------------------------------------
# 係數表：版本、樣本門檻、事後誤差
# ---------------------------------------------------------------------------

def latest_coefficient(conn, brand_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM ad_revenue_coefficient WHERE brand_id = %s AND valid_to IS NULL"
        " ORDER BY version DESC LIMIT 1", (brand_id,),
    ).fetchone()
    return dict(row) if row else None


def effective_coefficient(conn, brand_id: str) -> dict:
    """判讀要引用的係數：樣本不足時回保守預設，並附上「為什麼」的人話說明。"""
    latest = latest_coefficient(conn, brand_id)
    if latest is None or not latest["reliable"]:
        return {"coefficient": DEFAULT_COEFFICIENT, "reliable": False, "version": None,
                "sample_size": latest["sample_size"] if latest else 0,
                "note": "不可靠，暫用保守預設（校準樣本不足 %d 次前，不做灌水調整）" % SAMPLE_THRESHOLD}
    return {"coefficient": latest["coefficient"], "reliable": True, "version": latest["version"],
            "sample_size": latest["sample_size"], "note": "已校準"}


def _error_pct(predicted: Optional[float], actual: float) -> Optional[float]:
    if not predicted:
        return None
    return round((actual - predicted) / predicted, 4)


def calibrate(conn, brand_id: str, cycle_id: str, *, actor: str,
              today: Optional[str] = None) -> dict:
    """用這期的對帳結果校準一版新係數。校準前先拿「上一版係數 predict 這期」跟這期實際
    訂單實收比對，記一筆事後誤差——係數的可信紀錄永遠是「用舊版猜、拿新資料對答案」。

    today 比照 app/ads/performance.py 匯入函式與 guardrails 的慣例：可覆寫，方便測試與
    補件驅動回溯重判（決策 0025 懶人優先第 3 點）指定「當作哪一天校準的」。
    """
    if not actor or not actor.strip():
        raise ValueError("actor 為必填")
    result = reconcile_cycle(conn, brand_id, cycle_id)
    if not result["available"]:
        raise ValueError(result["reason"])
    if not result["meta_revenue"]:
        raise ValueError("這期 Meta 沒有回報營收，沒辦法算係數。")

    ts = now_utc()
    today = today or date.today().isoformat()
    prev = latest_coefficient(conn, brand_id)

    if prev is not None:
        predicted = prev["coefficient"] * result["meta_revenue"]
        conn.execute(
            "INSERT INTO ad_revenue_coefficient_error_log (id, org_id, brand_id, coefficient_id,"
            " campaign_cycle_id, predicted_order_revenue, actual_order_revenue, error_pct,"
            " recorded_at, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (new_id("rce"), DEV_ORG_ID, brand_id, prev["id"], cycle_id, predicted, result["order_revenue"],
             _error_pct(predicted, result["order_revenue"]), ts, ts),
        )
        conn.execute("UPDATE ad_revenue_coefficient SET valid_to = %s WHERE id = %s",
                     (today, prev["id"]))

    version = (prev["version"] if prev else 0) + 1
    sample_size = (prev["sample_size"] if prev else 0) + 1
    reliable = sample_size >= SAMPLE_THRESHOLD
    coefficient_id = new_id("arc")
    conn.execute(
        "INSERT INTO ad_revenue_coefficient (id, org_id, brand_id, version, coefficient, meta_revenue,"
        " order_revenue, sample_size, reliable, source_cycle_id, valid_from, valid_to,"
        " created_by, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, %s, %s)",
        (coefficient_id, DEV_ORG_ID, brand_id, version, result["coefficient_now"], result["meta_revenue"],
         result["order_revenue"], sample_size, reliable, cycle_id, today, actor, ts),
    )

    write_audit(conn, brand_id=brand_id, entity_type="ad_revenue_coefficient",
                entity_id=coefficient_id, action="calibrate", actor=actor, before=None,
                after={"version": version, "coefficient": result["coefficient_now"],
                       "sample_size": sample_size, "reliable": reliable})
    conn.commit()

    _maybe_enqueue_next_due(conn, brand_id, today=today)
    return {"id": coefficient_id, "version": version, "coefficient": result["coefficient_now"],
            "sample_size": sample_size, "reliable": reliable}


# ---------------------------------------------------------------------------
# 自適應降頻
# ---------------------------------------------------------------------------

def _recent_error_pcts(conn, brand_id: str, limit: int) -> list:
    rows = conn.execute(
        "SELECT error_pct FROM ad_revenue_coefficient_error_log WHERE brand_id = %s"
        " AND error_pct IS NOT NULL ORDER BY recorded_at DESC LIMIT %s",
        (brand_id, limit),
    ).fetchall()
    return [r["error_pct"] for r in rows]


def _confidence_label(days_since: Optional[int], cadence: str) -> str:
    if days_since is None:
        return "尚未校準"
    if days_since <= FRESH_DAYS[cadence]:
        return "新鮮"
    if days_since <= STALE_DAYS[cadence]:
        return "稍舊，建議校準"
    return "已過期，判讀信心打折"


def cadence_state(conn, brand_id: str, *, today: Optional[str] = None) -> dict:
    """規則判定（不經 LLM，鐵則 4）：係數連續數期穩定就降頻為每季抽查。

    回傳「上次校準距今 X 天」與可信度衰減標籤，畫面直接顯示、不擋路。
    """
    today = today or date.today().isoformat()
    latest = latest_coefficient(conn, brand_id)
    if latest is None:
        return {"cadence": "per_cycle", "days_since_last": None, "due": True,
                "last_calibrated_at": None, "confidence_label": "尚未校準"}

    days_since = (date.fromisoformat(today) - latest["valid_from"]).days
    recent_errors = _recent_error_pcts(conn, brand_id, STABILITY_WINDOW)
    stable = (len(recent_errors) >= STABILITY_WINDOW
              and all(abs(e) <= STABILITY_TOLERANCE for e in recent_errors))
    cadence = "quarterly" if stable else "per_cycle"
    due = days_since >= QUARTERLY_INTERVAL_DAYS if cadence == "quarterly" else True

    return {"cadence": cadence, "days_since_last": days_since, "due": due,
            "last_calibrated_at": latest["valid_from"],
            "confidence_label": _confidence_label(days_since, cadence)}


def _maybe_enqueue_next_due(conn, brand_id: str, *, today: str) -> Optional[str]:
    """降頻為每季後，下次到期才提醒一次（比照 app/ads/onboarding.py create_reminders：
    排一筆帶 visible_from 的未來提醒，不用輪詢／排程器）。"""
    state = cadence_state(conn, brand_id, today=today)
    if state["cadence"] != "quarterly":
        return None
    due_date = date.fromisoformat(today) + timedelta(days=QUARTERLY_INTERVAL_DAYS)
    interrupt_id = core_interrupts.enqueue(
        conn, category="revenue_reconcile_due",
        dedupe_key=f"revenue_reconcile_due:{brand_id}:{due_date.isoformat()}",
        message="灌水係數已逾校準週期，建議重新對帳。",
        brand_id=brand_id, visible_from=due_date,
        action_url=f"/app/brands/{brand_id}/campaigns",
    )
    if interrupt_id:
        conn.commit()
    return interrupt_id


# ---------------------------------------------------------------------------
# 成色標籤（票 #41，決策 0025 懶人優先第 6 點；標籤文字修憲落地 G5 改正，決策 0035
# 第四節第 11 點）：資料完整度決定判讀成色標籤，永遠給結論、永不擋路——重用
# effective_coefficient() 的 reliable 判斷（已經是「累積真實訂單對帳達樣本門檻」這個
# 資料完整度規則），不重造一套判定邏輯。
#
# 修憲落地 G5：原本 calibrated 掛「已校準判讀」，但灌水係數從未真的乘進 judge() 用的
# revenue（全庫只有對帳頁 reconcile_cycle() 引用係數）——那個標籤描述了一個沒發生的
# 校準。決策 0035 給兩個選項二選一，這裡選 (b) 改名而不選 (a) 真的套係數：
# 套係數等於改動 judge() 的 ROAS 分子，牽動 SCALE_MARGIN／PAUSE_MARGIN 這些直接決定
# 加碼／停損建議的門檻，且係數本身還帶樣本不足時的保守預設，兩層不確定性疊在一起太冒險；
# 改名不動判讀邏輯、不增風險，只是把「有對過帳但數字沒調整」講清楚——跟現況算術一致。
# ---------------------------------------------------------------------------

DATA_GRADE_LABELS = {"meta_only": "Meta 視角判讀", "calibrated": "已對過帳（數字未調整）"}


def data_grade(conn, brand_id: str) -> dict:
    """判讀結論該掛哪個成色：灌水係數還沒校準過（樣本不足門檻）＝只看得到 Meta 自報
    數字＝「Meta 視角判讀」；校準過＝已經有真實訂單資料對過帳，但判讀用的 revenue 本身
    沒有被係數調整過＝「已對過帳（數字未調整）」（修憲落地 G5，不再稱「已校準判讀」，
    因為判讀數字從未真的被校準過）。"""
    kind = "calibrated" if effective_coefficient(conn, brand_id)["reliable"] else "meta_only"
    return {"kind": kind, "label": DATA_GRADE_LABELS[kind]}


# ---------------------------------------------------------------------------
# GA4 漏率反偵測（票 #41，決策 0025 小補丁組第 5 點）
# ---------------------------------------------------------------------------

def ga4_leak_estimate(conn, brand_id: str, cycle: dict) -> dict:
    """用「有廣告碼但 GA4 對不到」的訂單比例，估計 GA4 自己的追蹤流失（iOS 追蹤限制等），
    避免把這個缺口全部算成 Meta 灌水。

    訂單數用淨歸因筆數（判讀一律用淨歸因，決策 0025 補遺第 3 點）；GA4 轉換數只用
    「涵蓋這期日期範圍」的最新一次同步結果——涵蓋不到就誠實說看不出來，不硬湊
    （鐵則 16）。EasyStore 匯出無 UTM 欄（決策 0025 第 2 點實測），沒有逐筆比對的本錢，
    只能在彙總層做這個粗估。
    """
    order_count = ads_codes.attribution_summary(conn, brand_id, cycle["id"])["net"]["count"]
    if not order_count:
        return {"available": False, "reason": "這期沒有訂單用到廣告碼，看不出 GA4 漏率。"}

    status = ads_ga4_sync.get_sync_status(conn, brand_id)
    if status is None:
        return {"available": False, "reason": "還沒同步過 GA4 資料，看不出漏率。"}
    if status["date_range_start"] > cycle["start_date"] or status["date_range_end"] < cycle["end_date"]:
        return {"available": False,
                "reason": "GA4 目前同步的期間沒有完整涵蓋這期，看不出漏率。"}

    ga4_conversions = sum(r["conversions"] for r in ads_ga4_sync.latest_summary(conn, brand_id))
    leak_ratio = max(0.0, round((order_count - ga4_conversions) / order_count, 4))
    return {
        "available": True, "order_count": order_count,
        "ga4_conversions": round(ga4_conversions, 1), "leak_ratio": leak_ratio,
        "note": (f"這期有 {order_count} 筆訂單用到廣告碼，GA4 這段期間只記到"
                f" {ga4_conversions:.0f} 筆轉換，估計約 {leak_ratio:.0%} 是 GA4 自己沒追蹤到"
                "（可能是 iOS 追蹤限制），這部分缺口不是 Meta 灌水，判讀係數時不要全算進去。"),
    }


def demo() -> None:
    """python -m app.ads.inflation — 純函數自檢：誤差率與可信度衰減標籤。"""
    assert _error_pct(1000, 1100) == 0.1
    assert _error_pct(0, 500) is None
    assert _confidence_label(10, "per_cycle") == "新鮮"
    assert _confidence_label(45, "per_cycle") == "稍舊，建議校準"
    assert _confidence_label(90, "per_cycle") == "已過期，判讀信心打折"
    assert _confidence_label(None, "quarterly") == "尚未校準"
    print("inflation 自檢通過")


if __name__ == "__main__":
    demo()
