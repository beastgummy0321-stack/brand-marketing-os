# -*- coding: utf-8 -*-
"""app/ads/codes.py — 期別配碼＋上線前校驗＋訂單歸因（GitHub issue #35，決策 0025 補遺第 2、3、7 點）。

碼分身術（主防線，結構解）：每期發兩組等值碼——廣告碼、口播碼（親友單），短效期、
使用上限略高於預期量、期期換碼不重用。碼按流量來源分，不按切角分：一期一組廣告碼
對全部切角（0025 補遺第 3 點）。

字碼、使用上限、效期由系統自動決定（短效期＝比照檔期起訖、低使用上限＝保守預設）；
折數是行銷決策，不是「數字規則」，由使用者填（鐵則 4：數字走程式，但折扣多少% 是
人的商業判斷，不是可推導的規則）。

上線前校驗：規劃碼（這裡算出來的）vs 後台實際設定（EasyStore 無 API，人工輸入，
見決策 0025 第 2 點）逐欄比對，不符時留紀錄並顯示人話警示（verification_warning，
由畫面顯示），但不鎖任何動作——全系統一律只提醒、不擋（ADR 0006，取代已作廢的
0025 補遺第 7 點）。

訂單匹配歸因：voucher_code 比對這裡配的碼——廣告碼→淨歸因（毛歸因含存疑，
判讀一律用淨歸因）；口播碼／手動排除→排除；無碼→自然／未歸因（0025 補遺第 3 點）。

外洩輕量警示：只做「用碼量遠高於曝光」這種最簡單、防狼來了的比例檢查——0025 明定
統計外洩偵測的進階版（分群、趨勢模型）是陷阱／下一批，樣本小不值得建複雜模型。
"""

import json
from datetime import date
from typing import Optional

from app.ads import performance as ads_performance
from app.ads import repository as ads_repo
from app.core import interrupts as core_interrupts
from app.core.audit import write_audit
from app.core.db import new_id, now_iso

# 第 7 刀（A1 三層地界新規則：app/ads 不得 import app.orders，見
# test_architecture_boundaries.py）：orders_repo 不在這裡 import，改由組裝根
# app/main.py 啟動時注入真正的 app.orders.repository 模組（app/orders 允許 import
# app.ads，方向只能單向，注入點就設在唯一合法跨層組裝的地方）。
orders_repo = None

SOURCE_TYPES = ("ad", "word_of_mouth")
SOURCE_LABELS = {"ad": "廣告碼", "word_of_mouth": "口播碼"}
DISCOUNT_TYPE_LABELS = {"percent": "百分比", "fixed": "固定金額"}

# ponytail：低使用上限是防外洩的保守預設常數，不是精算——目前沒有訂單量預測模型可依據；
# 有歷史轉換率基準後可改成依預估訂單量算，升級路徑同 0025 回購樣本門檻先例。
DEFAULT_USAGE_LIMIT = 50

# ponytail：用碼／曝光比例超過門檻即示警，是最陽春的比例檢查，非趨勢或分群模型——
# 0025 明定統計外洩偵測進階版是陷阱／下一批（樣本小，防狼來了）。有更多期數據後
# 可升級成比對期間內用碼成長率 vs 曝光成長率。
CODE_SURGE_RATIO = 0.3
MIN_USAGE_FOR_SURGE_CHECK = 5


def _code_text(cycle: dict, source_type: str) -> str:
    """碼字自動生成：tag ＋ 檔期起始日 ＋ 檔期 id 尾碼。檔期 id 全域唯一，
    碼字因此天生「期期換碼不重用」，不需要額外查重或亂數重試。"""
    tag = {"ad": "AD", "word_of_mouth": "WOM"}[source_type]
    day = (cycle["start_date"] or date.today().isoformat()).replace("-", "")
    suffix = cycle["id"].split("_")[-1][-6:].upper()
    return f"{tag}{day}{suffix}"


def list_codes(conn, brand_id: str, cycle_id: str) -> list:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM cycle_voucher_code WHERE brand_id = ? AND campaign_cycle_id = ?"
        " ORDER BY source_type", (brand_id, cycle_id),
    )]


def generate_codes(conn, brand_id: str, cycle_id: str, *, discount_type: str,
                   discount_value, usage_limit: Optional[int] = None,
                   valid_from: Optional[str] = None, valid_to: Optional[str] = None,
                   actor: str) -> list:
    """期別自動配碼：廣告碼／口播碼各一組。已經配過的來源不重新產生——碼一旦配出去，
    使用者可能已經照著去 EasyStore 後台建立，中途換掉碼字只會讓已建好的對不上。
    """
    if discount_type not in DISCOUNT_TYPE_LABELS:
        raise ValueError("折扣類型只能是百分比或固定金額")
    if discount_value is None or discount_value <= 0:
        raise ValueError("折數請填大於 0 的數字")
    if not actor or not actor.strip():
        raise ValueError("actor 為必填")
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    if cycle is None:
        raise ValueError("找不到廣告檔期")

    usage_limit = usage_limit or DEFAULT_USAGE_LIMIT
    valid_from = valid_from or cycle["start_date"]
    valid_to = valid_to or cycle["end_date"]

    existing_sources = {c["source_type"] for c in list_codes(conn, brand_id, cycle_id)}
    ts = now_iso()
    created = []
    for source_type in SOURCE_TYPES:
        if source_type in existing_sources:
            continue
        conn.execute(
            "INSERT INTO cycle_voucher_code (id, brand_id, campaign_cycle_id, source_type, code,"
            " discount_type, discount_value, usage_limit, valid_from, valid_to, created_at,"
            " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id("vch"), brand_id, cycle_id, source_type, _code_text(cycle, source_type),
             discount_type, discount_value, usage_limit, valid_from, valid_to, ts, ts),
        )
        created.append(source_type)

    if created:
        write_audit(conn, brand_id=brand_id, entity_type="campaign_cycle", entity_id=cycle_id,
                    action="generate_voucher_codes", actor=actor, before=None,
                    after={"sources": created})
        conn.commit()
    return list_codes(conn, brand_id, cycle_id)


# ---------------------------------------------------------------------------
# 上線前校驗
# ---------------------------------------------------------------------------

def _mismatch_messages(planned: dict, actual: dict, label: str) -> list:
    """單一來源（廣告碼或口播碼）的逐欄比對，回傳不符欄位的人話訊息清單。"""
    out = []
    actual_code = (actual.get("code") or "").strip().upper()
    if actual_code != planned["code"].strip().upper():
        out.append(f"{label}字碼不符：規劃「{planned['code']}」，後台填的是"
                   f"「{actual.get('code') or '（未填）'}」。")

    actual_discount = ads_performance.to_number(actual.get("discount_value"))
    actual_type = (actual.get("discount_type") or "").strip()
    if actual_type != planned["discount_type"] or actual_discount != planned["discount_value"]:
        planned_label = DISCOUNT_TYPE_LABELS.get(planned["discount_type"], planned["discount_type"])
        actual_label = DISCOUNT_TYPE_LABELS.get(actual_type, actual_type or "未填")
        out.append(f"{label}折數不符：規劃 {planned['discount_value']}（{planned_label}），"
                   f"後台填的是 {actual.get('discount_value') or '（未填）'}（{actual_label}）。")

    actual_limit = ads_performance.to_number(actual.get("usage_limit"), int)
    if actual_limit != planned["usage_limit"]:
        out.append(f"{label}使用上限不符：規劃 {planned['usage_limit']}，後台填的是"
                   f"{actual.get('usage_limit') or '（未填）'}。")

    actual_from = (actual.get("valid_from") or "").strip()
    actual_to = (actual.get("valid_to") or "").strip()
    if actual_from != planned["valid_from"] or actual_to != planned["valid_to"]:
        out.append(f"{label}效期不符：規劃 {planned['valid_from']}～{planned['valid_to']}，"
                   f"後台填的是 {actual_from or '？'}～{actual_to or '？'}。")
    return out


def verify(conn, brand_id: str, cycle_id: str, *, actual: dict, actor: str) -> dict:
    """上線前逐欄校驗：規劃碼 vs 後台實際設定。通過留紀錄；不符也留紀錄並顯示人話警示
    （見 verification_warning），但不鎖任何動作，決定權在人（ADR 0006）。

    actual 格式：{"ad": {"code","discount_type","discount_value","usage_limit",
                         "valid_from","valid_to"}, "word_of_mouth": {...}}
    """
    if not actor or not actor.strip():
        raise ValueError("actor 為必填")
    codes = {c["source_type"]: c for c in list_codes(conn, brand_id, cycle_id)}
    if not codes:
        raise ValueError("這期還沒有配碼，先產出配碼再校驗")

    mismatches = []
    for source_type, planned in codes.items():
        entered = (actual or {}).get(source_type) or {}
        mismatches.extend(_mismatch_messages(planned, entered, SOURCE_LABELS[source_type]))

    passed = not mismatches
    ts = now_iso()
    verification_id = new_id("vcv")
    conn.execute(
        "INSERT INTO cycle_code_verification (id, brand_id, campaign_cycle_id, passed,"
        " mismatches_json, checked_by, checked_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (verification_id, brand_id, cycle_id, 1 if passed else 0,
         json.dumps(mismatches, ensure_ascii=False) if mismatches else None, actor, ts, ts),
    )
    write_audit(conn, brand_id=brand_id, entity_type="campaign_cycle", entity_id=cycle_id,
                action="verify_voucher_codes", actor=actor, before=None,
                after={"passed": passed, "mismatches": mismatches})
    conn.commit()
    return {"id": verification_id, "passed": passed, "mismatches": mismatches}


def latest_verification(conn, brand_id: str, cycle_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM cycle_code_verification WHERE brand_id = ? AND campaign_cycle_id = ?"
        " ORDER BY checked_at DESC LIMIT 1", (brand_id, cycle_id),
    ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["mismatches"] = json.loads(result["mismatches_json"]) if result["mismatches_json"] else []
    return result


def verification_warning(conn, brand_id: str, cycle_id: str) -> Optional[str]:
    """最近一次校驗不符時的人話警示，不擋任何動作（ADR 0006，取代已作廢的鎖住規則）。
    從沒校驗過＝無警示（校驗本身可跳過）；回傳警示文字，沒有不符或沒校驗過回 None。"""
    latest = latest_verification(conn, brand_id, cycle_id)
    if latest and not latest["passed"]:
        return ("上線前校驗沒過，規劃碼與後台實際設定不一致：" + "；".join(latest["mismatches"])
                + "要不要照這樣開跑由你決定，建議先改好後台設定再重新校驗。")
    return None


# ---------------------------------------------------------------------------
# 訂單歸因
# ---------------------------------------------------------------------------

def _normalize_code(text: Optional[str]) -> str:
    return (text or "").strip().upper()


def _revenue_summary(rows: list) -> dict:
    revenue = sum((r.get("total_amount") or 0) - (r.get("refunded_amount") or 0) for r in rows)
    return {"count": len(rows), "net_revenue": round(revenue, 2)}


def attribution_summary(conn, brand_id: str, cycle_id: str) -> dict:
    """訂單依碼匹配歸因，四類統計：

    - gross：比對到廣告碼的全部訂單（含後來被手動排除的，供對照——「毛歸因含存疑」）。
    - net：gross 扣掉手動排除，判讀一律用這個數字（決策 0025 補遺第 3 點）。
    - excluded：口播碼訂單＋手動標記非廣告來源的訂單（不論有沒有碼）。
    - natural：沒對到任何配碼、也沒被手動排除＝自然／未歸因，不計入廣告成效。
    """
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    if cycle is None:
        raise ValueError("找不到廣告檔期")
    codes = {c["source_type"]: c for c in list_codes(conn, brand_id, cycle_id)}
    ad_code = _normalize_code(codes["ad"]["code"]) if "ad" in codes else None
    wom_code = _normalize_code(codes["word_of_mouth"]["code"]) if "word_of_mouth" in codes else None

    orders = orders_repo.list_orders_in_range(conn, brand_id, cycle["start_date"], cycle["end_date"])

    buckets: dict = {"gross": [], "net": [], "excluded": [], "natural": []}
    for order in orders:
        code = _normalize_code(order.get("voucher_code"))
        excluded_manually = order.get("attribution_override") == "excluded"
        if ad_code and code == ad_code:
            buckets["gross"].append(order)
            buckets["excluded" if excluded_manually else "net"].append(order)
        elif (wom_code and code == wom_code) or excluded_manually:
            buckets["excluded"].append(order)
        else:
            buckets["natural"].append(order)

    return {key: _revenue_summary(rows) for key, rows in buckets.items()}


# ---------------------------------------------------------------------------
# 用碼異常輕量警示
# ---------------------------------------------------------------------------

def check_surge(conn, brand_id: str, cycle_id: str) -> Optional[str]:
    """用碼暴增但曝光沒動的輕量警示：用碼量遠高於曝光次數時進打斷佇列（規則警示）。
    回傳新排的 interrupt id；沒觸發或已經排過（去重）回 None。"""
    ad_code = next((c for c in list_codes(conn, brand_id, cycle_id) if c["source_type"] == "ad"),
                   None)
    if ad_code is None:
        return None

    usage_count = attribution_summary(conn, brand_id, cycle_id)["gross"]["count"]
    if usage_count < MIN_USAGE_FOR_SURGE_CHECK:
        return None

    impressions = ads_performance.totals(conn, brand_id, cycle_id).get("impressions") or 0
    surged = impressions == 0 or (usage_count / impressions) > CODE_SURGE_RATIO
    if not surged:
        return None

    interrupt_id = core_interrupts.enqueue(
        conn, category="code_surge_alert",
        dedupe_key=f"code_surge_alert:{cycle_id}:{ad_code['code']}",
        message="用碼量遠高於曝光，疑似碼外洩，去看訂單來源。",
        brand_id=brand_id, campaign_cycle_id=cycle_id,
        action_url=f"/brands/{brand_id}/orders",
    )
    if interrupt_id:
        conn.commit()
    return interrupt_id


def check_surge_for_brand(conn, brand_id: str) -> int:
    """訂單／成效資料匯入後呼叫：檢查這個品牌目前 LIVE／EVALUATING 檔期有沒有用碼異常。
    回傳這次新排了幾筆警示。"""
    created = 0
    for cycle in ads_repo.list_cycles(conn, brand_id):
        if cycle["status"] not in ("LIVE", "EVALUATING"):
            continue
        if check_surge(conn, brand_id, cycle["id"]):
            created += 1
    return created


def demo() -> None:
    """python -m app.ads.codes — 純函數自檢：碼字生成穩定、比對邏輯抓得到不符欄位。"""
    cycle = {"id": "ccy_ABCDEF123456", "start_date": "2026-08-01"}
    code_a = _code_text(cycle, "ad")
    code_b = _code_text(cycle, "ad")
    assert code_a == code_b, "同一期同來源碼字要穩定（不靠亂數，靠檔期 id）"
    assert code_a != _code_text(cycle, "word_of_mouth"), "廣告碼跟口播碼字要不一樣"

    planned = {"code": "ADX", "discount_type": "percent", "discount_value": 10,
              "usage_limit": 50, "valid_from": "2026-08-01", "valid_to": "2026-08-14"}
    assert _mismatch_messages(planned, dict(planned), "廣告碼") == [], "完全一致不應有不符訊息"
    wrong = {**planned, "discount_value": "20"}
    messages = _mismatch_messages(planned, wrong, "廣告碼")
    assert len(messages) == 1 and "折數不符" in messages[0]
    print("codes 自檢通過")


if __name__ == "__main__":
    demo()
