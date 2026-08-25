# -*- coding: utf-8 -*-
"""app/ads/data_onboarding.py — 搬家精靈（畫面用語「把舊資料搬進來」）四格檢查清單狀態與
基線成熟門檻（票 F7，決策 0039 第一、四節）。

四格狀態一律從既有資料查詢推導，不建新表、不存精靈狀態——完成與否天然冪等，使用者
切著切著回來看永遠是當下最新狀態，不會跟實際資料脫節。每格完成即顯示的「部分基線
小結」與「基線是否成熟」報告刻意共用同一批數字（zero 新計算），避免兩處漂移。
"""

from datetime import date
from typing import Optional

from app.ads import ga4_sync
from app.ads import performance as ads_performance
from app.ads import sync as ads_sync
from app.core import rule_cards

# 第 7 刀（A1 三層地界新規則：app/ads 不得 import app.orders，見
# test_architecture_boundaries.py）：orders_repo 不在這裡 import，改由組裝根
# app/main.py 啟動時注入真正的 app.orders.repository 模組。
orders_repo = None

# 訂單史成熟門檻（決策 0039 第 4 條新設，180 天）：跟 app/shared/web.py 的
# FACT_STALE_DAYS（事實鮮度，180 天）數字恰好相同但意義不同（訂單史夠不夠長 vs
# 品牌事實多久沒重新調研），刻意分開命名、不共用常數，避免以後調整其中一邊時誤改到另一邊。
ORDER_HISTORY_MATURE_DAYS = 180

# GA4 涵蓋月數成熟門檻（決策 0039 第 4 條，本模組新設，沒有業界慣例可抄，先落一個務實值）。
GA4_COVERAGE_MATURE_MONTHS = 3

REQUIRED_KEYS = ("meta_claim", "order_backfill", "ga4_backfill")

_STATUS_BADGE = {
    "not_started": ("尚未開始", "neutral"),
    "in_progress": ("進行中", "warn"),
    "done": ("已完成", "ok"),
}

_META_DESC = {
    "not_started": "連上 Meta、同步一次，把舊廣告的成效認領回來。",
    "in_progress": "已經連上，樣本還不夠或還有活動等你確認歸屬。",
    "done": "舊廣告成效已經算進品牌基線。",
}
_ORDER_DESC = {
    "not_started": "把系統啟用前的訂單檔拖進來，開始累積訂單史。",
    "in_progress": "已經匯入訂單，訂單史還沒到門檻天數。",
    "done": "訂單史已經超過門檻天數。",
}
_GA4_DESC = {
    "not_started": "連上 GA4 之後可以一鍵回填最多 12 個月資料。",
    "in_progress": "已經同步過，涵蓋月數還沒到門檻。",
    "done": "GA4 涵蓋月數已經達標。",
}

# AI「建議下一步」的理由（決策 0039 第 1 條：只標建議，不強制順序）：固定文案＋固定優先序
# （REQUIRED_KEYS 的順序），不做動態評分——四格獨立、使用者本來就可以自己選，這裡只是
# 給一個預設起點，不是唯一正確路徑。
_HINTS = {
    "meta_claim": "把舊廣告的點擊面成效算進品牌基線，是四格裡最先影響得到判讀的一格。",
    "order_backfill": "訂單史越長，回購樣本與訂單史門檻越快達標。",
    "ga4_backfill": "補齊 Meta 廣告觸及不到的那段全站流量。",
}


def order_history(conn, brand_id: str, today: Optional[str] = None) -> dict:
    """這個品牌最早一筆訂單到今天隔了幾天，外加已匯入筆數。完全沒有訂單時
    `days`／`earliest` 回 None（鐵則 16：算不出就是算不出，不補算）。"""
    row = conn.execute(
        "SELECT MIN(order_date) earliest, COUNT(*) c FROM order_record WHERE brand_id = %s",
        (brand_id,),
    ).fetchone()
    if row is None or not row["earliest"]:
        return {"days": None, "earliest": None, "order_count": 0}
    today = today or date.today().isoformat()
    days = (date.fromisoformat(today) - date.fromisoformat(row["earliest"])).days
    return {"days": days, "earliest": row["earliest"], "order_count": row["c"]}


def ga4_coverage(conn, brand_id: str) -> dict:
    """GA4 累積涵蓋範圍：取這個品牌 `ga4_summary` 全部列的最早開始日到最晚結束日
    （不是只看最近一次同步的視窗——一次 12 個月回填之後如果又跑過日常 30 天同步，
    最近一次的視窗會變回 30 天，但歷史彙總列還在，涵蓋月數不該因此往回掉）。
    從沒同步過時 `months` 回 None。"""
    row = conn.execute(
        "SELECT MIN(date_range_start) earliest, MAX(date_range_end) latest"
        " FROM ga4_summary WHERE brand_id = %s", (brand_id,),
    ).fetchone()
    if row is None or not row["earliest"]:
        return {"months": None, "start": None, "end": None}
    start = date.fromisoformat(row["earliest"])
    end = date.fromisoformat(row["latest"])
    return {"months": max((end - start).days // 30, 0),
            "start": row["earliest"], "end": row["latest"]}


def meta_click_tier(conn, brand_id: str) -> dict:
    """品牌層（舊廣告）點擊面樣本分級：重用 F2 的 `brand_level_totals()` 加總，
    餵進既有的 `rule_cards.sample_size_tier()`——跟成效判讀頁同一套統計等級判斷，
    不另立第二套標準。"""
    totals = ads_performance.brand_level_totals(conn, brand_id)
    clicks = totals["clicks"] or 0
    conversions = totals["conversions"] or 0
    cvr = (conversions / clicks) if clicks else None
    return {"tier": rule_cards.sample_size_tier(conn, brand_id, clicks, cvr), "totals": totals}


def interview_done(conn, brand_id: str) -> bool:
    """前朝教訓訪談是否記錄過任何東西。`app.ads.interview.submit()` 只在真的有勾選
    或補充文字時才寫 audit_log，全部留白送出等同沒記——不建第二張狀態表，直接查
    audit_log 本身。"""
    row = conn.execute(
        "SELECT 1 FROM audit_log WHERE brand_id = %s AND entity_type = 'lesson_interview'"
        " LIMIT 1", (brand_id,),
    ).fetchone()
    return row is not None


def build_checklist(conn, brand_id: str, today: Optional[str] = None) -> list:
    """四格檢查清單的目前狀態＋動作連結＋（有資料就有的）部分基線小結。"""
    today = today or date.today().isoformat()
    items = []

    # ① Meta 認領
    meta_configured = ads_sync.is_configured(conn)
    pending = len(ads_sync.list_pending_claims(conn, brand_id)) if meta_configured else 0
    meta = meta_click_tier(conn, brand_id)
    meta_totals = meta["totals"]
    meta_has_data = meta_totals["rows"] > 0
    if meta["tier"]["level"] == "statistical":
        meta_status = "done"
    elif meta_has_data or meta_configured:
        meta_status = "in_progress"
    else:
        meta_status = "not_started"
    if not meta_configured:
        meta_action = ("前往設定頁連線", "/app/settings")
    elif pending:
        meta_action = ("前往認領舊廣告", f"/app/brands/{brand_id}/ads-claims")
    elif not meta_has_data:
        meta_action = ("回填近 12 個月成效", f"/app/brands/{brand_id}/data-onboarding")
    else:
        meta_action = ("看目前的認領清單", f"/app/brands/{brand_id}/ads-claims")
    meta_baseline = None
    if meta_has_data:
        kpis = meta_totals["kpis"]
        meta_baseline = [
            ("已認領的舊成效", f"{meta_totals['rows']:,} 筆", False),
            ("CPC", f"{kpis['cpc']:,.1f} 元" if kpis["cpc"] is not None else "算不出", True),
            ("CTR", f"{kpis['ctr']:.2%}" if kpis["ctr"] is not None else "算不出", True),
            ("轉換率", f"{kpis['cvr']:.2%}" if kpis["cvr"] is not None else "算不出", True),
            ("樣本分級", rule_cards.STATISTICAL_LEVEL_LABELS[meta["tier"]["level"]], False),
        ]
    items.append({
        "key": "meta_claim", "label": "Meta 認領", "optional": False,
        "status": meta_status, "has_data": meta_has_data,
        "badge_label": _STATUS_BADGE[meta_status][0], "badge_kind": _STATUS_BADGE[meta_status][1],
        "description": _META_DESC[meta_status],
        "action_text": meta_action[0], "action_url": meta_action[1],
        "baseline": meta_baseline,
        "baseline_note": meta_totals.get("unreconciled_note") if meta_has_data else None,
        "hint": _HINTS["meta_claim"],
    })

    # ② 訂單回填
    history = order_history(conn, brand_id, today=today)
    repurchase = orders_repo.repurchase_multiplier(conn, brand_id, today=today)
    order_has_data = history["days"] is not None
    if order_has_data and history["days"] >= ORDER_HISTORY_MATURE_DAYS:
        order_status = "done"
    elif order_has_data:
        order_status = "in_progress"
    else:
        order_status = "not_started"
    order_baseline = None
    if order_has_data:
        order_baseline = [
            ("已匯入筆數", f"{history['order_count']:,} 筆", True),
            ("訂單史涵蓋", f"{history['days']} 天", True),
            ("回購樣本", f"{repurchase['sample_size']} 筆", True),
        ]
    items.append({
        "key": "order_backfill", "label": "訂單回填", "optional": False,
        "status": order_status, "has_data": order_has_data,
        "badge_label": _STATUS_BADGE[order_status][0], "badge_kind": _STATUS_BADGE[order_status][1],
        "description": _ORDER_DESC[order_status],
        "action_text": "前往訂單頁匯入", "action_url": f"/app/brands/{brand_id}/orders",
        "baseline": order_baseline, "baseline_note": None,
        "hint": _HINTS["order_backfill"],
    })

    # ③ GA4 回填
    ga4_configured = ga4_sync.is_configured(conn)
    coverage = ga4_coverage(conn, brand_id)
    ga4_has_data = coverage["months"] is not None
    if ga4_has_data and coverage["months"] >= GA4_COVERAGE_MATURE_MONTHS:
        ga4_status = "done"
    elif ga4_has_data or ga4_configured:
        ga4_status = "in_progress"
    else:
        ga4_status = "not_started"
    if not ga4_configured:
        ga4_action = ("前往設定頁連線", "/app/settings")
    else:
        ga4_action = ("開始回填近 12 個月", f"/app/brands/{brand_id}/data-onboarding")
    ga4_baseline = None
    if ga4_has_data:
        ga4_baseline = [
            ("涵蓋範圍", f"{coverage['start']} ～ {coverage['end']}", False),
            ("涵蓋月數", f"{coverage['months']} 個月", True),
        ]
    items.append({
        "key": "ga4_backfill", "label": "GA4 回填", "optional": False,
        "status": ga4_status, "has_data": ga4_has_data,
        "badge_label": _STATUS_BADGE[ga4_status][0], "badge_kind": _STATUS_BADGE[ga4_status][1],
        "description": _GA4_DESC[ga4_status],
        "action_text": ga4_action[0], "action_url": ga4_action[1],
        "baseline": ga4_baseline, "baseline_note": None,
        "hint": _HINTS["ga4_backfill"],
    })

    # ④ 前朝教訓訪談（選做，不計入完成度——決策 0039 第 1 條）
    done = interview_done(conn, brand_id)
    items.append({
        "key": "interview", "label": "前朝教訓訪談", "optional": True,
        "status": "done" if done else "not_started", "has_data": done,
        "badge_label": "已完成" if done else "選做",
        "badge_kind": "ok" if done else "neutral",
        "description": "已經記錄過前朝教訓。" if done else "選填，把過去踩過的雷交給系統參考。",
        "action_text": "再訪談一次（選做）" if done else "開始訪談（選做）",
        "action_url": f"/app/brands/{brand_id}/campaigns",
        "baseline": None, "baseline_note": None, "hint": None,
    })

    return items


def completion(checklist: list) -> dict:
    """三個必要格（訪談選做不算）的完成度＋建議下一步（決策 0039 第 1 條固定優先序：
    Meta → 訂單 → GA4，不做動態評分——四格本來就順序自由，這裡只給一個預設起點）。"""
    required = [item for item in checklist if not item["optional"]]
    done_count = sum(1 for item in required if item["status"] == "done")
    next_item = next((item for item in required if item["status"] != "done"), None)
    return {"done": done_count, "total": len(required), "next_item": next_item,
            "all_done": done_count == len(required)}


def rail_items(checklist: list, next_item: Optional[dict]) -> list:
    """餵給 `_components/wizard_steps.html` 的 `progress_rail()`：已完成格→done（可點回顧）、
    建議下一步的那一格→current，其餘→future。不隱含強制順序——四格本來就能跳著做，
    這裡只是視覺上標出「現在建議看哪格」。"""
    items = []
    for i, item in enumerate(checklist, start=1):
        if item["status"] == "done":
            status, url = "done", item["action_url"]
        elif next_item is not None and item["key"] == next_item["key"]:
            status, url = "current", None
        else:
            status, url = "future", None
        items.append((i, item["label"], url, status))
    return items


def maturity_report(conn, brand_id: str, today: Optional[str] = None) -> list:
    """「基線是否成熟」報告：四項門檻逐項打勾＋還缺什麼（決策 0039 第 4 條）。
    數字全部重用既有函式（訂單史／回購樣本／Meta 樣本分級／GA4 涵蓋月數），
    跟四格檢查清單的部分基線小結是同一批計算，不重算第二份。"""
    today = today or date.today().isoformat()
    rows = []

    history = order_history(conn, brand_id, today=today)
    days = history["days"]
    met = bool(days is not None and days >= ORDER_HISTORY_MATURE_DAYS)
    if days is None:
        gap = "還沒有任何訂單資料，先完成上面「訂單回填」那格。"
    elif not met:
        gap = f"還缺 {ORDER_HISTORY_MATURE_DAYS - days} 天，補拖更早的訂單檔，或等待自然累積。"
    else:
        gap = None
    rows.append({"label": "訂單史天數", "value_label": f"{days} 天" if days is not None else "算不出",
                 "threshold_label": f"≥ {ORDER_HISTORY_MATURE_DAYS} 天", "met": met, "gap": gap})

    repurchase = orders_repo.repurchase_multiplier(conn, brand_id, today=today)
    sample = repurchase["sample_size"]
    met = not repurchase["insufficient_sample"]
    if days is None:
        gap = "訂單檔還沒匯入，先完成上面「訂單回填」那格。"
    elif not met:
        gap = (f"還缺 {orders_repo.REPURCHASE_MIN_SAMPLE - sample} 筆回購訂單，"
               "通常會跟訂單史一起補齊。")
    else:
        gap = None
    rows.append({"label": "回購樣本數", "value_label": f"{sample} 筆",
                 "threshold_label": f"≥ {orders_repo.REPURCHASE_MIN_SAMPLE} 筆",
                 "met": met, "gap": gap})

    meta = meta_click_tier(conn, brand_id)
    met = meta["tier"]["level"] == "statistical"
    if meta["totals"]["rows"] == 0:
        gap = "還沒有任何舊廣告成效，先完成上面「Meta 認領」那格。"
    elif not met:
        gap = "認領到的舊廣告樣本還不夠，會隨認領更多舊廣告或投放持續累積。"
    else:
        gap = None
    rows.append({"label": "Meta 點擊面樣本分級",
                 "value_label": rule_cards.STATISTICAL_LEVEL_LABELS[meta["tier"]["level"]],
                 "threshold_label": rule_cards.STATISTICAL_LEVEL_LABELS["statistical"],
                 "met": met, "gap": gap})

    coverage = ga4_coverage(conn, brand_id)
    months = coverage["months"]
    met = bool(months is not None and months >= GA4_COVERAGE_MATURE_MONTHS)
    if months is None:
        gap = "還沒開始回填，先完成上面「GA4 回填」那格。"
    elif not met:
        gap = f"還缺 {GA4_COVERAGE_MATURE_MONTHS - months} 個月，可以再回填一次。"
    else:
        gap = None
    rows.append({"label": "GA4 涵蓋月數",
                 "value_label": f"{months} 個月" if months is not None else "0 個月",
                 "threshold_label": f"≥ {GA4_COVERAGE_MATURE_MONTHS} 個月", "met": met, "gap": gap})

    return rows
