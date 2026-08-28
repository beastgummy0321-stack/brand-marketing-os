"""app/ads/routes_common.py — 廣告分支路由的共用小工具（第 8 刀從 app/ads/routes.py 拆出）。

原本 2213 行的 app/ads/routes.py 裡，這些常數與私有函式被 8 個主題檔（routes_home 除外，
見 app/ads/routes.py 檔頭列表）反覆呼叫——麵包屑、檔期讀取、檔期加工成頁面用的樣子、
五格進度軌等。純粹是被搬出來的既有程式，邏輯一行沒改。
"""

from datetime import date

import app.shared.web as main_mod
from app.ads import budget as budget_calc
from app.ads import creative as ads_creative
from app.ads import handoff as ads_handoff
from app.ads import pacing_curve, stages
from app.ads import performance as ads_performance
from app.ads import plan as ads_plan
from app.ads import reading as ads_reading
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi

# 滑桿檔位（TWD）。刻意是離散檔位而非連續數值：新手要的是「大概這個量級」，
# 不是精確到個位數；離散檔位也讓每一檔的換算結果能由後端預先算好塞進頁面，
# 前端只查表顯示、不做任何算術——換算規則永遠只有 app/ads/budget.py 一份，不會漂移。
SLIDER_STEPS = [1000, 2000, 3000, 5000, 8000, 10000, 15000, 20000, 30000, 50000, 80000, 100000]
DEFAULT_STEP_INDEX = 3  # 5,000：新手預設保守

# 5 選項對齊 Meta 官方成效目標分類，砍「應用程式推廣」（決策 0023 第 4 點）。
# 順序依 Meta 廣告管理員慣用的漏斗順序排列：知名度 → 流量 → 互動 → 潛在顧客 → 銷售。
OBJECTIVES = [
    {"value": "awareness", "label": "知名度",
     "hint": "適合剛起步、還在找哪種說法有人理的階段，先求被更多人看到、記住這個品牌。"},
    {"value": "traffic", "label": "流量",
     "hint": "適合想把人導去網站或某個頁面，讓更多人點進去看內容或商品。"},
    {"value": "engagement", "label": "互動",
     "hint": "適合想累積留言、分享、按讚，經營粉專熱度的情況。"},
    {"value": "leads", "label": "潛在顧客",
     "hint": "適合單價高、需要先收名單、之後再慢慢聊成交的生意。"},
    {"value": "sales", "label": "銷售",
     "hint": "適合已經有商品頁、想直接看到訂單的情況。"},
]
OBJECTIVE_LABELS = {o["value"]: o["label"] for o in OBJECTIVES}

CYCLE_STATUS_LABELS = {
    "PLANNING": "計畫中",
    "PLAN_SELECT": "等你選方案",
    "REVIEW": "等你確認計畫",
    "PRODUCTION": "做素材中",
    "LIVE": "投放中",
    "EVALUATING": "等你回填成效",
    "CLOSED": "已結束",
}

PHASE_LABELS = {"simulation": "紙上模擬", "calibration": "校準期"}

# 廣告首頁「最近結案的檔期」賺／賠狀態膠囊顏色（修憲落地 V3，決策 0033 console-ui
# 說明句改資料）：沿用 reading.judge() 的錢門檻分群，只取顏色，不重複判讀理由。
VERDICT_BADGE_KIND = {
    "scale_candidate": "ok",
    "maintain": "ok",
    "pause_candidate": "danger",
}


def _crumb(brand: dict, *tail) -> list:
    items = [("品牌總覽", "/"), (brand["name"], f"/brands/{brand['id']}"),
             ("廣告", f"/brands/{brand['id']}/ads")]
    items.extend(tail)
    if items[-1][1] is not None:
        items[-1] = (items[-1][0], None)
    return items


def _slider_options() -> list:
    """每一檔滑桿位置預先算好的換算結果，供頁面即時顯示（不在前端重算）。"""
    options = []
    for amount in SLIDER_STEPS:
        plan = budget_calc.plan_from_pain(amount)
        options.append({
            "amount": amount,
            "amount_label": f"{amount:,}",
            "duration_days": plan.duration_days,
            "daily_budget": round(plan.daily_budget),
            "daily_budget_label": f"{round(plan.daily_budget):,}",
            "below_floor": plan.daily_below_floor,
            # 人話回饋：金額太小時誠實說看不出什麼，不用漂亮話蓋過去
            "note": (
                f"這筆金額約買到 {plan.duration_days} 天測試，"
                + ("但每天預算偏低，可能只看得出哪張圖有人點，看不出能不能賺錢。"
                   if plan.daily_below_floor
                   else "足夠看出哪些素材有人點、哪些帶得動成交。")
            ),
        })
    return options


def _duration_suggestion(amount: float) -> dict:
    """檔期長度的建議值＋白話理由（決策 0023 第 5 點）。

    建議值沿用 budget_calc.plan_from_pain 的自動換算（14 天，金額撐不起日預算下限時縮短），
    但表單上這個值只是「預先填好的建議」——使用者可以在 7–30 天自訂，不受這個值限制。
    """
    plan = budget_calc.plan_from_pain(amount)
    if plan.duration_days == budget_calc.DEFAULT_DURATION_DAYS:
        rationale = (f"建議 {plan.duration_days} 天：兩週是常見的檔期長度，"
                     "Meta 的學習期大約需要 3–7 天，這樣學習期之後還留得下一段時間看得出數據。")
    else:
        rationale = (f"這筆金額如果跑滿兩週，日預算會低於實務下限（每天約"
                     f"{budget_calc.MIN_DAILY_BUDGET:,.0f} 元），系統建議縮到 "
                     f"{plan.duration_days} 天，把日預算撐到看得出效果的水準。")
    return {"days": plan.duration_days, "rationale": rationale}


# 檔期長度即時短評用的門檻資料，原封不動交給前端——前端只查表比大小，不重算業務規則
# （跟滑桿選項同一套精神：換算規則只有 app/ads/budget.py 一份）。
DURATION_TIER_CONFIG = {
    "min": budget_calc.MIN_DURATION_DAYS,
    "max": budget_calc.MAX_DURATION_DAYS,
    "min_daily_budget": budget_calc.MIN_DAILY_BUDGET,
    "tiers": [{"upper": upper, "tier": tier, "note": note}
              for upper, tier, note in budget_calc.DURATION_TIERS],
}


def _recommended_objective(conn, brand_id: str, product_ids: list) -> str:
    """AI 推薦答案（鐵則 20）：有算得出毛利的產品就推「銷售」，否則推「知名度」。

    刻意用規則而不是 LLM——這是個封閉選擇，數字條件也很明確，
    交給 LLM 猜只會多花錢又不穩定（決策 0016 硬性原則 4）。其餘三個選項（流量／互動／
    潛在顧客）目前沒有夠明確的規則條件可判斷，就不勉強給推薦——每個選項本身的白話說明
    已經夠使用者自己判斷。
    """
    for product_id in product_ids:
        if budget_calc.gross_margin(bi.get_product_economics(conn, brand_id, product_id)):
            return "sales"
    return "awareness"


def _cycle_ended_unsettled(cycle: dict, today: date) -> bool:
    """B0-05：LIVE／EVALUATING 檔期的 end_date 已經過了，但還沒被收帳（自動排程或使用者
    手動「現在結算」）轉成 CLOSED。這裡只管「讀取時要不要照實講已經結束」，不改
    `campaign_cycle.status`、不跑任何排程——過期自動收帳排程器是 BOARD R5-S，另案批准。"""
    return cycle["status"] in ("LIVE", "EVALUATING") and cycle["end_date"] < today


def _display_status_label(cycle: dict, today: date) -> str:
    if _cycle_ended_unsettled(cycle, today):
        return "已結束・待收帳"
    return CYCLE_STATUS_LABELS.get(cycle["status"], cycle["status"])


def _cycle_view(conn, brand_id: str, cycle: dict) -> dict:
    """把一列 campaign_cycle 加工成頁面要用的樣子（人話狀態、期長、產品名）。"""
    plan = ads_repo.derived_plan(cycle)
    product_ids = cycle["product_scope_json"] or []
    names = []
    for pid in product_ids:
        product = bi.get_product(conn, brand_id, pid)
        if product:
            names.append(product["name"])
    return {
        **cycle,
        "status_label": _display_status_label(cycle, date.today()),
        "phase_label": PHASE_LABELS.get(cycle["phase"]),
        "objective_label": OBJECTIVE_LABELS.get(cycle["objective"], cycle["objective"]),
        "funnel_stage_label": ads_plan.FUNNEL_STAGE_LABELS.get(cycle["funnel_stage"]),
        "duration_days": plan.get("duration_days"),
        "daily_budget": plan.get("daily_budget"),
        "daily_below_floor": plan.get("daily_below_floor"),
        "product_names": names,
        # 排期策略（票 pacing-curve）：舊資料（本票上線前開的檔期）沒有這三個鍵，
        # .get() 給空預設，畫面看不到曲線就顯示「這期還沒有排期曲線資料」，不硬猜。
        "pacing_strategy": plan.get("pacing_strategy"),
        "pacing_strategy_label": (pacing_curve.STRATEGIES.get(plan.get("pacing_strategy") or "", {})
                                  .get("title")),
        "pacing_reason": plan.get("pacing_reason"),
        "daily_budgets": plan.get("daily_budgets") or [],
    }


def derive_cycle_stage(conn, brand_id: str, cycle: dict) -> int:
    """這期檔期落在五格進度軌的第幾格（1–5）。訊號取法：素材是否已採用、交接包是否已
    建置／已啟用，交給 app/ads/stages.derive_stage() 判斷（#43）。共用於 hub 卡片（#45）、
    五個階段頁頂端的進度軌（#46）、駕駛艙指南卡引擎（票 04-guide-card-engine），
    避免同一套判讀邏輯抄兩份。公開函式（無底線）：dashboard 模組接口鐵則只能透過
    各模組公開查詢函式取數。"""
    creatives = ads_creative.list_variants(conn, brand_id, cycle["id"])
    packages = ads_handoff.list_packages(conn, brand_id, cycle["id"])
    return stages.derive_stage(
        cycle["status"],
        has_adopted=any(v["decision"] and v["decision"]["decision"] == "adopted"
                        for v in creatives),
        package_count=len(packages),
        activated_count=sum(1 for p in packages if p["mapping"]),
    )


def _hub_stage_info(conn, brand_id: str, cycle: dict) -> dict:
    """hub「進行中檔期」卡用：這期落在五格的哪一格、剩幾天（GitHub issue #45；修憲落地 V3
    補上 stage_index，畫面要顯示「第 N 步／共 5 步」，不再只有格名一個詞）。

    B0-05：end_date 已過但還沒收帳（`_cycle_ended_unsettled`）時，「剩幾天」這個倒數概念
    已經不成立——回 None，別跟著 status_label 的「已結束・待收帳」一起印出誤導的「剩 0 天」。
    """
    stage_index = derive_cycle_stage(conn, brand_id, cycle)
    today = date.today()
    days_left = (None if _cycle_ended_unsettled(cycle, today)
                else max(0, (cycle["end_date"] - today).days))
    return {"stage_index": stage_index, "stage_label": stages.STAGE_LABELS[stage_index - 1],
            "days_left": days_left}


def _closed_cycle_reading(conn, brand_id: str, cycle: dict) -> dict | None:
    """單一已結案檔期的判讀摘要：讀已存的判讀快照（reading.load()，不重新算判讀邏輯，
    鐵則4 數字走程式不重複）。沒判讀過就回 None——hub「最近結案的檔期」卡（下面
    `_latest_closed_summary`）與歷期戰績跨期趨勢表（GitHub issue #63）共用同一份萃取邏輯，
    不各寫一份。"""
    reading_row = ads_reading.load(conn, brand_id, cycle["id"])["cycle"]
    if not reading_row:
        return None
    result = reading_row["result"] or {}
    return {
        "status_label": reading_row["status_label"],
        "verdict_kind": VERDICT_BADGE_KIND.get(reading_row["status"], "neutral"),
        "roas": (result.get("kpis") or {}).get("roas"),
        "data_grade": result.get("data_grade"),  # {kind, label}——渲染沿用 ads_performance.html
        # 既有的 badge kind 對照（'ok' if kind == 'calibrated' else 'neutral'），不再造第二套。
    }


def _latest_closed_summary(conn, brand_id: str, cycles: list) -> dict | None:
    """hub「最近結案的檔期」卡用（修憲落地 V3，決策 0033 console-ui 說明句改資料）：
    沒判讀過就整塊不顯示——日期雖然拿得到，但沒有判讀結論的「最近結案」卡片沒有資訊量，
    且 principles.md 鐵則 16「拿不到就不要放」對這裡的具體落地就是「沒有就不佔版面」，
    不是放一張只有日期的空卡。"""
    closed = [c for c in cycles if c["status"] == "CLOSED"]
    if not closed:
        return None
    cycle = closed[0]  # cycles 已依 start_date DESC 排序，最新的已結案排最前
    reading = _closed_cycle_reading(conn, brand_id, cycle)
    if reading is None:
        return None
    return {**cycle, **reading}


def _roas_trend_symbol(current: float | None, previous: float | None) -> str | None:
    """跟相鄰上一期（較舊的那期）比 ROAS 漲跌；任一邊算不出就不給箭頭（鐵則 16：拿不到
    就不要放，不硬猜方向）。"""
    if current is None or previous is None:
        return None
    if current > previous:
        return "▲"
    if current < previous:
        return "▼"
    return "－"


def _history_trend_rows(conn, brand_id: str, closed_cycles: list) -> list:
    """歷期戰績頁頂部跨期趨勢表（GitHub issue #63，決策 0039 第 12 點）：只列已結案檔期，
    花費／實收營收讀即時加總（跟 /performance 頁「這期成效」欄位同一份 ads_performance.totals()，
    不重算第二份公式）；ROAS／賺賠／成色沿用 `_closed_cycle_reading()` 的判讀快照——跟 hub
    「最近結案的檔期」卡同一份萃取邏輯，不複製貼上。沒判讀過的已結案期不出現在趨勢表
    （鐵則 16）。closed_cycles 沿用 list_cycles 既有排序（start_date DESC，最新在前），
    vs 上期＝跟陣列中下一筆（較舊的相鄰已結案期）比 ROAS。"""
    rows = []
    for cycle in closed_cycles:
        reading = _closed_cycle_reading(conn, brand_id, cycle)
        if reading is None:
            continue
        totals = ads_performance.totals(conn, brand_id, cycle["id"])
        rows.append({**cycle, **reading, "spend": totals["spend"], "revenue": totals["revenue"]})
    for i, row in enumerate(rows):
        previous_roas = rows[i + 1]["roas"] if i + 1 < len(rows) else None
        row["vs_previous"] = _roas_trend_symbol(row["roas"], previous_roas)
    return rows


def _require_cycle(brand_id: str, cycle_id: str) -> dict:
    cycle = ads_repo.get_cycle(main_mod.conn, brand_id, cycle_id)
    if cycle is None:
        raise main_mod.NotFoundKind("廣告檔期")
    return cycle
