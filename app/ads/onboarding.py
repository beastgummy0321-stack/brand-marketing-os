"""app/ads/onboarding.py — 新手心理曲線（票 15）。

ADHD 設計輸入方向三：第一期數字通常很難看，新手歸咎「我不行」就放棄了。三個對策：

1. **校準期預告**：第一期真檔期標記為校準期，在計畫確認時就先講明「這期預期會是什麼樣」。
   事先講的叫預期，事後講的叫藉口——順序很重要。
2. **提醒卡**：投放後第 3 天「可以看但先別動」、第 7 天與到期日「回填成效」。
   空窗期系統不能沉默，但也不能逼人天天盯盤（那違反懶人定位）。
3. **差異視圖**：第二期起只展開「跟上期不一樣的地方」，相同的摺疊起來。
   第 N 期還要重看一次全部設定，人就會變成盲按確認。

差異只比檔期設定（預算、天數、產品、目標）這些**可比對的欄位**，
不比計畫內文——自由文字每次都不一樣，比了只會噪音。

提醒卡自身不再擁有專屬資料表：GitHub issue #32（決策 0026 第 4 點）把它遷進全站打斷佇列
（app/core/interrupts.py），這裡只負責「投放授權成立時該排哪三筆、什麼時候該浮出」這段
廣告模組的專屬知識，實際儲存／去重／嚴重度都交給佇列那層統一處理。
"""

from datetime import timedelta

from app.ads import checkpoint as ads_checkpoint
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi
from app.core import interrupts as core_interrupts

# 提醒卡：投放後第幾天、要說什麼。內容與門檻共用這一張表，避免兩套邏輯漂移
# （ADHD 設計輸入的衍生建議）。message 為卡片一句話，需守 DESIGN.md §20 規則 4（≤30 全形字）。
# offset_days 相對檔期開始日；offset_from_end_days 相對檔期結束日（final_settlement 專用，
# 決策 0025 判讀節奏第 5 點：期末＋14 天最終結算，治貨到付款棄單退款遲滯）。
REMINDERS = [
    {"kind": "day3_look_dont_touch", "offset_days": 3, "offset_from_end_days": None,
     "message": "投放滿 3 天，數據仍在學習期，先觀察、不調整設定。"},
    {"kind": "day7_report", "offset_days": 7, "offset_from_end_days": None,
     "message": "投放滿 7 天，數據具參考價值，可回填成效判讀。"},
    {"kind": "cycle_end", "offset_days": None, "offset_from_end_days": None,
     "message": "檔期已到期，回填最終成效，系統會給出本期結論。"},
    {"kind": "final_settlement", "offset_days": None, "offset_from_end_days": 14,
     "message": "檔期結束滿 14 天，未結案訂單已定案，可執行最終結算。"},
]

# 期中檢查點的兩種 kind：檔期一旦不再是 LIVE 就沒有意義了，見 resolve_stale_checkpoint_reminders。
_MID_CYCLE_KINDS = ("day3_look_dont_touch", "day7_report")


def _reminder_action_url(brand_id: str, cycle_id: str, kind: str) -> str:
    """「詳情」導向：day3／day7 直接深連到對應的期中健康檢查頁（一條龍走完，不多繞一頁），
    final_settlement 導去最終結算流程，其餘（cycle_end）導去回填成效頁。
    checkpoint 對照表沿用 app/ads/checkpoint.py 單一權威。"""
    checkpoint_kind = ads_checkpoint.REMINDER_TO_CHECKPOINT_KIND.get(kind)
    if checkpoint_kind:
        return f"/app/brands/{brand_id}/campaigns/{cycle_id}"
    if kind == "final_settlement":
        return f"/app/brands/{brand_id}/campaigns/{cycle_id}"
    return f"/app/brands/{brand_id}/campaigns/{cycle_id}"


def create_reminders(conn, brand_id: str, cycle_id: str) -> int:
    """投放授權成立時把四筆提醒排進打斷佇列。已經排過（同去重鍵）就不重複排。"""
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    if cycle is None:
        return 0
    start = cycle["start_date"]
    end = cycle["end_date"]
    created = 0
    brand = bi.get_brand(conn, brand_id)
    assert brand is not None, f"找不到品牌：{brand_id}"
    org_id = brand["org_id"]
    for reminder in REMINDERS:
        if reminder["offset_from_end_days"] is not None:
            due = end + timedelta(days=reminder["offset_from_end_days"])
        elif reminder["offset_days"] is None:
            due = cycle["end_date"]
        else:
            due = start + timedelta(days=reminder["offset_days"])
        interrupt_id = core_interrupts.enqueue(
            conn, org_id=org_id, category="cycle_reminder", kind=reminder["kind"],
            dedupe_key=f"cycle_reminder:{cycle_id}:{reminder['kind']}",
            message=reminder["message"], brand_id=brand_id, campaign_cycle_id=cycle_id,
            action_url=_reminder_action_url(brand_id, cycle_id, reminder["kind"]),
            visible_from=due,
        )
        if interrupt_id:
            created += 1
    conn.commit()
    return created


def resolve_stale_checkpoint_reminders(conn, brand_id: str, cycle_id: str, *, actor: str) -> int:
    """期末判讀一旦跑過，還沒被處理的期中提醒（day3／day7）就併入期末結論，不用使用者
    事後回頭補做（決策 0025 審查補遺第 4 點：期中檢查點是事件不是死線）。由
    app/ads/reading.py run() 在判讀完成時呼叫——單一觸發點，不靠使用者自己來關。"""
    rows = core_interrupts.list_open(conn, brand_id=brand_id, category="cycle_reminder")
    merged = 0
    for row in rows:
        if row["campaign_cycle_id"] != cycle_id or row["kind"] not in _MID_CYCLE_KINDS:
            continue
        core_interrupts.resolve(conn, row["id"], actor=actor)
        merged += 1
    return merged


def due_reminders(conn, brand_id: str | None = None, today: str | None = None) -> list:
    """到期而且還沒被關掉的提醒。brand_id 省略時跨品牌查（只有首頁待辦用）。

    只有 LIVE／EVALUATING 且未封存的檔期才會浮出——這段檔期狀態知識只有廣告模組有，
    佇列本身（core.interrupts）不認得 campaign_cycle.status，過濾放在這一層。
    """
    rows = core_interrupts.list_open(conn, brand_id=brand_id, category="cycle_reminder",
                                     today=today)
    out = []
    for row in rows:
        cycle = ads_repo.get_cycle(conn, row["brand_id"], row["campaign_cycle_id"])
        if cycle is None or cycle["status"] not in ("LIVE", "EVALUATING") or cycle["archived"]:
            continue
        out.append(row)
    return out


def dismiss(conn, brand_id: str, reminder_id: str, *, actor: str) -> None:
    row = conn.execute(
        "SELECT brand_id FROM interrupt WHERE id = %s", (reminder_id,)
    ).fetchone()
    if row is None or row["brand_id"] != brand_id:
        raise ValueError("找不到這則提醒")
    core_interrupts.resolve(conn, reminder_id, actor=actor)


# ---------------------------------------------------------------------------
# 校準期
# ---------------------------------------------------------------------------

def mark_calibration_if_first(conn, brand_id: str, cycle_id: str) -> bool:
    """如果這是這個品牌第一期真的要投的檔期，標記為校準期。回傳有沒有標記。"""
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    if cycle is None or cycle["phase"] != "normal":
        return False
    earlier = conn.execute(
        "SELECT COUNT(*) c FROM campaign_cycle WHERE brand_id = %s AND phase != 'simulation'"
        " AND id != %s AND created_at < %s",
        (brand_id, cycle_id, cycle["created_at"]),
    ).fetchone()["c"]
    if earlier:
        return False
    conn.execute("UPDATE campaign_cycle SET phase = 'calibration' WHERE id = %s", (cycle_id,))
    conn.commit()
    return True


def calibration_forecast(conn, brand_id: str, cycle_id: str) -> dict | None:
    """校準期的預期區間。事先講明「大概會落在哪裡」，第一期就不會被難看的數字嚇跑。"""
    from app.ads import simulation

    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    if cycle is None or cycle["phase"] != "calibration":
        return None

    basis, basis_note = simulation._basis(conn, brand_id, exclude_cycle_id=cycle_id)
    budget = cycle["budget"] or 0
    clicks_low = int(budget / (basis["cpc"] * 1.35)) if basis["cpc"] else 0
    clicks_high = int(budget / (basis["cpc"] * 0.65)) if basis["cpc"] else 0
    conv_low = int(clicks_low * basis["conversion_rate"] * 0.65)
    conv_high = int(clicks_high * basis["conversion_rate"] * 1.35)
    return {
        "clicks_low": clicks_low, "clicks_high": clicks_high,
        "conversions_low": conv_low, "conversions_high": conv_high,
        "basis_note": basis_note,
    }


def in_forecast(forecast: dict | None, totals: dict) -> bool | None:
    """實際結果有沒有落在事先預告的範圍內。沒有預告就回 None。"""
    if not forecast:
        return None
    conversions = totals.get("conversions") or 0
    return forecast["conversions_low"] <= conversions <= forecast["conversions_high"]


def forecast_gap(forecast: dict, totals: dict) -> dict:
    """兌現預言卡用（票 F5，決策 0039 第 16 條）：實際結果跟預告的落差方向，
    區間外時進一步機械式拆解是哪一環拖累——點擊量本身就沒到預告下限（同樣預算買到的
    點擊變少，代表 CPC 比預期高），還是點擊量落在範圍內但成交轉換率比預期低。
    程式算，AI 不猜。呼叫端須先確認 forecast 存在（forecast_snapshot 非 None）才會走到這裡。
    """
    if in_forecast(forecast, totals):
        return {"direction": "within", "segment": None}
    conversions = totals.get("conversions") or 0
    if conversions > forecast["conversions_high"]:
        return {"direction": "above", "segment": None}  # 好於區間：預測偏保守
    clicks = totals.get("clicks") or 0
    segment = "clicks" if clicks < forecast["clicks_low"] else "conversion_rate"
    return {"direction": "below", "segment": segment}


def forecast_snapshot(cycle: dict) -> dict | None:
    """讀開期當下寫入 derived_plan_json 的區間快照（票 F1，決策 0039 第 14 條）。

    顯示端（ads_cycle.html）與後續兌現預言卡（F5）一律經由這個函式取值，不得另外
    自行解析 derived_plan_json——對帳只能讀這份快照，基線之後再怎麼換，數字都不會
    跟著變。舊檔期（本票上線前開的校準期）沒存過快照時老實回 None，呼叫端顯示
    「本期未存預告」，不補算（鐵則 16）。寫入邏輯見 app/ads/repository.py create_cycle()。
    """
    return ads_repo.derived_plan(cycle).get("forecast")


# ---------------------------------------------------------------------------
# 差異視圖
# ---------------------------------------------------------------------------

COMPARABLE_FIELDS = [
    ("budget", "總預算"),
    ("objective", "本期目標"),
    ("duration_days", "檔期長度"),
    ("product_names", "推的產品"),
]


def _comparable(conn, brand_id: str, cycle: dict) -> dict:
    from app.brand_intelligence import repository as bi

    derived = ads_repo.derived_plan(cycle)
    names = []
    for product_id in cycle["product_scope_json"] or []:
        product = bi.get_product(conn, brand_id, product_id)
        if product:
            names.append(product["name"])
    return {
        "budget": cycle["budget"],
        "objective": cycle["objective"],
        "duration_days": derived.get("duration_days"),
        "product_names": "、".join(sorted(names)) or "整個品牌",
    }


def previous_cycle(conn, brand_id: str, cycle: dict) -> dict | None:
    """跟這期同一品牌、時間序上最近的前一個「真的」檔期（跳過模擬期）。差異視圖
    （diff_with_previous）與兌現預言卡第二個出口（票 F5，決策 0039 第 15 條：第二期檔期
    內頁頂部常駐卡）共用同一份查詢，不重複寫第二份 SQL。"""
    row = conn.execute(
        "SELECT * FROM campaign_cycle WHERE brand_id = %s AND id != %s AND phase != 'simulation'"
        " AND created_at < %s ORDER BY created_at DESC LIMIT 1",
        (brand_id, cycle["id"], cycle["created_at"]),
    ).fetchone()
    if row is None:
        return None
    result = dict(row)
    # budget 跟 ads_repo.get_cycle() 一樣轉 float——diff_with_previous() 下面拿它跟
    # get_cycle() 讀回的 cycle["budget"] 比較，兩邊型別要一致（02-3b）。
    if result.get("budget") is not None:
        result["budget"] = float(result["budget"])
    return result


def diff_with_previous(conn, brand_id: str, cycle_id: str) -> dict | None:
    """跟上一期比，哪些變了、哪些沒變。沒有上一期就回 None（第一期不需要差異視圖）。"""
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    if cycle is None:
        return None
    previous = previous_cycle(conn, brand_id, cycle)
    if previous is None:
        return None

    current = _comparable(conn, brand_id, cycle)
    before = _comparable(conn, brand_id, previous)
    changed, same = [], []
    for key, label in COMPARABLE_FIELDS:
        entry = {"label": label, "before": before.get(key), "after": current.get(key)}
        (changed if before.get(key) != current.get(key) else same).append(entry)
    return {"changed": changed, "same": same, "previous_start": previous["start_date"]}
