# -*- coding: utf-8 -*-
"""app/ads/routes.py — 廣告分支的頁面路由。

依 app/intake/routes.py 的既有做法：APIRouter ＋ 在函式內以 `main_mod` 動態取用
app.shared.web 的共用工具（修憲落地 A4：共用工具搬去 app/shared/web.py 之前，
這裡 import 的是 app.main，會跟 main → ads.routes → main 兜成一圈；現在單向依賴
app.shared.web，main.py 不再需要反向認得這個分支）。`main_mod.conn` 在測試會被
reopen_connection() 換掉，所以一律即時查值（`main_mod.conn`），不做靜態 import。

本檔負責的頁：
- `/brands/{b}/ads`            廣告首頁：歷期清單、開新檔期入口
- `/brands/{b}/ads/new`        開新檔期：選產品、拉滑桿、選目標
- `/brands/{b}/ads/{cycle}`    單一檔期頁
"""

import json
import threading
import time
from datetime import date
from typing import List, Optional
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse

import app.shared.web as main_mod
from app.ads import account_structure
from app.ads import budget as budget_calc
from app.ads import checklist as ads_checklist
from app.ads import checkpoint as ads_checkpoint
from app.ads import codes as ads_codes
from app.ads import compliance
from app.ads import creative as ads_creative
from app.ads import data_onboarding
from app.ads import fingerprint
from app.ads import ga4_sync
from app.ads import guardrails
from app.ads import handoff as ads_handoff
from app.ads import inflation as ads_inflation
from app.ads import interview as ads_interview
from app.ads import nextcycle
from app.ads import onboarding
from app.ads import performance as ads_performance
from app.ads import plan as ads_plan
from app.ads import reading as ads_reading
from app.ads import reconcile as ads_reconcile_mod
from app.ads import repository as ads_repo
from app.ads import settlement as ads_settlement
from app.ads import simulation
from app.ads import stages
from app.ads import sync as ads_sync
from app.brand_intelligence import repository as bi
from app.intake import state as intake_state
from app.llm import providers as llm_providers
from app.orders import channel as orders_channel
from app.orders import dispatch as orders_dispatch
from app.orders import repository as orders_repo

router = APIRouter()

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


def _cycle_view(conn, brand_id: str, cycle: dict) -> dict:
    """把一列 campaign_cycle 加工成頁面要用的樣子（人話狀態、期長、產品名）。"""
    plan = ads_repo.derived_plan(cycle)
    product_ids = json.loads(cycle["product_scope_json"] or "[]")
    names = []
    for pid in product_ids:
        product = bi.get_product(conn, brand_id, pid)
        if product:
            names.append(product["name"])
    return {
        **cycle,
        "status_label": CYCLE_STATUS_LABELS.get(cycle["status"], cycle["status"]),
        "phase_label": PHASE_LABELS.get(cycle["phase"]),
        "objective_label": OBJECTIVE_LABELS.get(cycle["objective"], cycle["objective"]),
        "duration_days": plan.get("duration_days"),
        "daily_budget": plan.get("daily_budget"),
        "daily_below_floor": plan.get("daily_below_floor"),
        "product_names": names,
    }


def _derive_cycle_stage(conn, brand_id: str, cycle: dict) -> int:
    """這期檔期落在五格進度軌的第幾格（1–5）。訊號取法：素材是否已採用、交接包是否已
    建置／已啟用，交給 app/ads/stages.derive_stage() 判斷（#43）。共用於 hub 卡片（#45）
    與五個階段頁頂端的進度軌（#46），避免同一套判讀邏輯抄兩份。"""
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
    補上 stage_index，畫面要顯示「第 N 步／共 5 步」，不再只有格名一個詞）。"""
    stage_index = _derive_cycle_stage(conn, brand_id, cycle)
    days_left = max(0, (date.fromisoformat(cycle["end_date"]) - date.today()).days)
    return {"stage_index": stage_index, "stage_label": stages.STAGE_LABELS[stage_index - 1],
            "days_left": days_left}


def _closed_cycle_reading(conn, brand_id: str, cycle: dict) -> Optional[dict]:
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


def _latest_closed_summary(conn, brand_id: str, cycles: list) -> Optional[dict]:
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


def _roas_trend_symbol(current: Optional[float], previous: Optional[float]) -> Optional[str]:
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


def _cycle_progress_items(conn, brand_id: str, cycle: dict) -> list:
    """五個階段頁頂端進度軌要的清單（GitHub issue #46），餵給
    progress_rail(items, collapsed=True)：只有當前格與下一格會渲染完整名稱，其餘一律收合成
    序號。已完成的格額外帶上對應階段頁網址——collapsed 模式下 macro 會把它收合成小圖示但
    仍可點（「已完成階段可點回顧」），未完成的格網址一律傳 None，天生不可點。"""
    stage_index = _derive_cycle_stage(conn, brand_id, cycle)
    cycle_id = cycle["id"]
    stage_urls = [
        f"/brands/{brand_id}/ads/{cycle_id}",
        f"/brands/{brand_id}/ads/{cycle_id}/creatives",
        f"/brands/{brand_id}/ads/{cycle_id}/handoff",
        f"/brands/{brand_id}/ads/{cycle_id}/checklist",
        f"/brands/{brand_id}/ads/{cycle_id}/performance",
    ]
    return [(num, label, stage_urls[num - 1] if num < stage_index else None,
             "current" if num == stage_index else ("done" if num < stage_index else "future"))
            for num, label in enumerate(stages.STAGE_LABELS, start=1)]


@router.get("/brands/{brand_id}/ads")
async def ads_home(request: Request, brand_id: str):
    """廣告首頁（修憲落地 V3，遷 B｜工作台式，決策 0033／0038）：卡片牆拿掉，改成單欄
    清單——進行中檔期／最近結案的檔期兩塊摘要（`kind=content`，不計入 §20.1 規則 1 的
    主欄 ≤5 上限）＋底部開新檔期等動作按鈕。全部檔期清單仍在 /ads/history，Meta 同步與
    待認領提醒仍在 /ads/connections（#44），本頁不留操作列。"""
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    cycles = [_cycle_view(conn, brand_id, c) for c in ads_repo.list_cycles(conn, brand_id)]
    in_progress = [c for c in cycles if c["status"] != "CLOSED"]
    primary_cycle = in_progress[0] if in_progress else None  # list_cycles 已依 start_date DESC 排序
    return main_mod.templates.TemplateResponse(
        request, "ads_home.html",
        main_mod.ctx(request, brand=brand,
                     has_cycles=bool(cycles) or ads_repo.list_archived_cycles(conn, brand_id) != [],
                     primary_cycle=primary_cycle,
                     stage=_hub_stage_info(conn, brand_id, primary_cycle) if primary_cycle else None,
                     stage_total=len(stages.STAGE_LABELS),
                     other_in_progress_count=len(in_progress) - 1 if in_progress else 0,
                     latest_closed=_latest_closed_summary(conn, brand_id, cycles),
                     inbox_count=len(main_mod.core_interrupts.list_open(conn, brand_id=brand_id)),
                     nav_current='ads',
                     breadcrumb_items=_crumb(brand),
                     **main_mod.banner_ctx(request)),
    )


@router.get("/brands/{brand_id}/ads/history")
async def ads_history(request: Request, brand_id: str):
    """歷期戰績（GitHub issue #45）：全部檔期清單，分進行中／已結案／已封存三段。
    原本廣告首頁表格＋底部封存收合區的內容搬到這裡，恢復／永久刪除沿用既有路由，行為不變。
    註冊在 /ads/{cycle_id} 萬用路由之前，避免被吃掉（比照 #44 的 /ads/connections）。"""
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    cycles = [_cycle_view(conn, brand_id, c) for c in ads_repo.list_cycles(conn, brand_id)]
    archived_cycles = [_cycle_view(conn, brand_id, c)
                       for c in ads_repo.list_archived_cycles(conn, brand_id)]
    closed_cycles = [c for c in cycles if c["status"] == "CLOSED"]
    return main_mod.templates.TemplateResponse(
        request, "ads_history.html",
        main_mod.ctx(request, brand=brand, nav_current='ads',
                     in_progress_cycles=[c for c in cycles if c["status"] != "CLOSED"],
                     closed_cycles=closed_cycles,
                     trend_rows=_history_trend_rows(conn, brand_id, closed_cycles),
                     archived_cycles=archived_cycles,
                     breadcrumb_items=_crumb(brand, ("歷期戰績", None)),
                     **main_mod.banner_ctx(request)),
    )


def _describe_sync_result(result) -> list:
    """SyncResult → 人話清單（票 F3 從 ads_sync_now 抽出，回填路由共用同一份措辭，
    不重寫第二份）。"""
    parts = [f"抓回 {result.snapshots} 筆成效"]
    if result.discovered:
        parts.append(f"發現 {result.discovered} 個新的廣告活動要你認領")
    if result.skipped_unclaimed:
        parts.append(f"{result.skipped_unclaimed} 筆因為還沒認領歸屬先沒收")
    if result.skipped_duplicate:
        parts.append(f"已略過重複 {result.skipped_duplicate} 列")
    if result.quarantined:
        parts.append(f"{result.quarantined} 筆數字不合理已擱置")
    return parts


@router.post("/brands/{brand_id}/ads/sync")
async def ads_sync_now(request: Request, brand_id: str):
    """從 Meta 抓一次資料回來。沒設定連線就給人話提示，不當機（鐵則 16）。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    conn = main_mod.conn
    back = f"/brands/{brand_id}/ads"

    if not ads_sync.is_configured(conn):
        return main_mod.redirect_with_message(
            back, "還沒設定 Meta 廣告帳號的唯讀連線，先去設定頁填一下。", kind="warn")

    result = ads_sync.sync_account(conn, actor)
    if result.error:
        return main_mod.redirect_with_message(back, result.error, kind="warn")

    return main_mod.redirect_with_message(back, "、".join(_describe_sync_result(result)) + "。")


@router.get("/brands/{brand_id}/ads/connections/meta/backfill")
def ads_meta_backfill_progress(request: Request, brand_id: str, run: Optional[str] = None):
    """回填精靈第①格（票 F3，決策 0039 第 3 條）：一鍵把 Meta 回填 12 個月，僅精靈用——
    日常同步（`/ads/sync`）維持 30 天視窗不動。背景執行＋只讀進度頁＋F5 冪等，
    比照 ads_ga4_sync_progress 同一套機制；sync_account 沒有 on_stage，借用單一階段
    （比照判讀 _READING_STAGES 的先例）。"""
    brand = main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    conn = main_mod.conn
    result_url = f"/brands/{brand_id}/ads/connections"

    if not ads_sync.is_configured(conn):
        return main_mod.redirect_with_message(
            result_url, "還沒設定 Meta 廣告帳號的唯讀連線，先去設定頁填一下。", kind="warn")

    progress_key = _progress_key("meta_backfill", brand_id, "_brand_")
    if run != "1":
        entry = _progress_touch(progress_key, _META_BACKFILL_STAGES)
        return _render_wait_page(
            request, brand, heading="正在回填 Meta 廣告成效",
            lede=f"這次會嘗試抓回過去 {BACKFILL_MONTHS} 個月的資料。",
            run_url=f"{request.url.path}?run=1", leave_url=result_url,
            breadcrumb_tail="Meta 回填中",
            progress_rows=_progress_definition_rows(_META_BACKFILL_STAGES, "meta_backfill", entry))

    def work(on_stage):
        since, until, actual_months = ads_sync.backfill_range(BACKFILL_MONTHS)
        result = ads_sync.sync_account(main_mod.conn, actor, since=since, until=until)
        return result, actual_months

    entry = _progress_start(progress_key, _META_BACKFILL_STAGES, work)

    if entry["status"] != "done":
        if time.time() - entry["started_at"] > _PROGRESS_TIMEOUT_SECONDS:
            _progress_clear(progress_key)
            return main_mod.redirect_with_message(
                result_url, "Meta 這次沒有在時間內回應，可以再試一次。", kind="warn")
        return _render_wait_page(
            request, brand, heading="正在回填 Meta 廣告成效",
            lede=f"這次會嘗試抓回過去 {BACKFILL_MONTHS} 個月的資料。",
            run_url=f"{request.url.path}?run=1", leave_url=result_url,
            breadcrumb_tail="Meta 回填中",
            progress_rows=_progress_definition_rows(_META_BACKFILL_STAGES, "meta_backfill", entry))

    outcome_kind, payload = entry["result"]
    _progress_clear(progress_key)
    if outcome_kind == "error":
        return main_mod.redirect_with_message(result_url, payload, kind="warn")
    result, actual_months = payload
    if result.error:
        return main_mod.redirect_with_message(result_url, result.error, kind="warn")
    parts = [f"實際拿到 {actual_months} 個月"] + _describe_sync_result(result)
    return main_mod.redirect_with_message(result_url, "、".join(parts) + "。")


@router.get("/brands/{brand_id}/ads/claims")
async def ads_claims(request: Request, brand_id: str):
    """待認領的廣告活動。只列「猜是這個品牌的」與「完全沒歸屬的」，
    已認領給別的品牌的不會出現在這裡（鐵則 13 品牌隔離）。"""
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    return main_mod.templates.TemplateResponse(
        request, "ads_claims.html",
        main_mod.ctx(request, brand=brand, nav_current='ads',
                     pending=ads_sync.list_pending_claims(conn, brand_id),
                     breadcrumb_items=_crumb(brand, ("還沒認領的廣告", None)),
                     **main_mod.banner_ctx(request)),
    )


@router.post("/brands/{brand_id}/ads/claims/{discovered_id}/{action}")
async def ads_claim_action(request: Request, brand_id: str, discovered_id: str, action: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    conn = main_mod.conn
    back = f"/brands/{brand_id}/ads/claims"
    try:
        if action == "claim":
            row = ads_sync.claim(conn, brand_id, discovered_id, actor)
            msg = f"「{row['campaign_name']}」記成這個品牌的了，它的成效數字會算進來。"
        elif action == "ignore":
            ads_sync.ignore(conn, brand_id, discovered_id, actor)
            msg = "好，這個活動不算這個品牌的。"
        else:
            raise main_mod.NotFoundKind("頁面")
    except ValueError as exc:
        return main_mod.redirect_with_message(back, str(exc), kind="warn")
    return main_mod.redirect_with_message(back, msg)


def _new_page_ctx(request: Request, conn, brand: dict, brand_id: str, *, selected: list,
                  errors: dict, form: dict, recommended_objective: str) -> dict:
    """開新檔期頁的共用 context（GET 首次載入、POST 驗證失敗回顯都走這裡，避免兩份漂移）。"""
    products = [p for p in bi.list_products(conn, brand_id) if p.get("status") == "active"]
    amount = form.get("_amount") or SLIDER_STEPS[DEFAULT_STEP_INDEX]
    return main_mod.ctx(
        request, brand=brand, nav_current='ads', products=products,
        slider_options=_slider_options(), default_index=DEFAULT_STEP_INDEX,
        objectives=OBJECTIVES, recommended_objective=recommended_objective,
        duration_suggestion=_duration_suggestion(amount),
        duration_tier_config=DURATION_TIER_CONFIG,
        default_start_date=date.today().isoformat(),
        readiness_notes=ads_repo.check_readiness(conn, brand_id, selected),
        offer_simulation=simulation.offer_simulation(conn, brand_id),
        breadcrumb_items=_crumb(brand, ("開新檔期", None)),
        errors=errors, form=form,
    )


@router.get("/brands/{brand_id}/ads/new")
async def ads_new_get(request: Request, brand_id: str):
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    product_ids = [p["id"] for p in bi.list_products(conn, brand_id)
                  if p.get("status") == "active"]
    return main_mod.templates.TemplateResponse(
        request, "ads_new.html",
        _new_page_ctx(request, conn, brand, brand_id, selected=product_ids, errors={}, form={},
                     recommended_objective=_recommended_objective(conn, brand_id, product_ids)),
    )


@router.post("/brands/{brand_id}/ads/new")
async def ads_new_post(request: Request, brand_id: str,
                       product_ids: Optional[List[str]] = Form(None),
                       slider_index: str = Form(""),
                       custom_amount: str = Form(""),
                       objective: str = Form(""),
                       duration_days: str = Form(""),
                       start_date: str = Form(""),
                       background: str = Form(""),
                       mode: str = Form("real")):
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    actor = main_mod.require_actor(request)

    selected = product_ids or []
    # 「我知道要投多少」展開後直接填的金額優先於滑桿（決策 0022 第 10 點）
    amount, amount_ok = main_mod.parse_number(custom_amount)
    if amount is None:
        try:
            amount = SLIDER_STEPS[int(slider_index)]
        except (ValueError, IndexError):
            amount = SLIDER_STEPS[DEFAULT_STEP_INDEX]

    errors = {}
    if not amount_ok or (amount is not None and amount <= 0):
        errors["amount"] = "請填一個大於 0 的金額。"
    if objective not in OBJECTIVE_LABELS:
        errors["objective"] = "請選一個本期目標。"

    duration_value = None
    duration_text = duration_days.strip()
    if duration_text:
        try:
            duration_value = int(duration_text)
        except ValueError:
            errors["duration_days"] = "檔期長度請填數字。"
        else:
            if not (budget_calc.MIN_DURATION_DAYS <= duration_value <= budget_calc.MAX_DURATION_DAYS):
                errors["duration_days"] = (f"檔期長度請填 {budget_calc.MIN_DURATION_DAYS}"
                                            f"–{budget_calc.MAX_DURATION_DAYS} 天之間。")

    start_date_text = start_date.strip()
    if start_date_text:
        try:
            date.fromisoformat(start_date_text)
        except ValueError:
            errors["start_date"] = "開始日期格式不對。"

    form = {"product_ids": selected, "custom_amount": custom_amount, "objective": objective,
            "duration_days": duration_days, "start_date": start_date, "background": background,
            "_amount": amount if amount_ok and amount else None}

    if errors:
        return main_mod.templates.TemplateResponse(
            request, "ads_new.html",
            _new_page_ctx(request, conn, brand, brand_id, selected=selected, errors=errors,
                         form=form, recommended_objective=objective or _recommended_objective(
                             conn, brand_id, selected)),
            status_code=400,
        )

    # 模擬期只有這個品牌一期都還沒跑過時才成立，避免熟手誤開（或表單被動手腳）
    phase = "simulation" if (mode == "simulation"
                             and simulation.offer_simulation(conn, brand_id)) else "normal"
    cycle = ads_repo.create_cycle(conn, brand_id, product_ids=selected, pain_value=amount,
                                  objective=objective, actor=actor, phase=phase,
                                  start_date=start_date_text or None,
                                  duration_days=duration_value, background=background)
    message = ("模擬檔期開好了。接下來的每一步都跟真的一樣，只有最後的成效數字是模擬的。"
               if phase == "simulation" else "檔期已建立，接下來確認這期的計畫。")
    return main_mod.redirect_with_message(f"/brands/{brand_id}/ads/{cycle['id']}", message)


def _require_cycle(brand_id: str, cycle_id: str) -> dict:
    cycle = ads_repo.get_cycle(main_mod.conn, brand_id, cycle_id)
    if cycle is None:
        raise main_mod.NotFoundKind("廣告檔期")
    return cycle


def _cycle_label(cycle: dict) -> str:
    """檔期沒有名稱欄位，畫面與刪除確認一律用日期範圍當識別文字。"""
    return f"{cycle['start_date']} ～ {cycle['end_date']}"


@router.post("/brands/{brand_id}/ads/{cycle_id}/archive")
async def ads_cycle_archive(request: Request, brand_id: str, cycle_id: str):
    """封存／恢復檔期（GitHub issue #28）。任何狀態（進行中、已結束）都能封存。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    cycle = _require_cycle(brand_id, cycle_id)
    new_archived = not cycle["archived"]
    ads_repo.set_cycle_archived(main_mod.conn, brand_id, cycle_id, archived=new_archived,
                                actor=actor)
    msg = (f"已封存 {_cycle_label(cycle)} 這期檔期。" if new_archived
           else f"已恢復 {_cycle_label(cycle)} 這期檔期。")
    return main_mod.redirect_with_message(f"/brands/{brand_id}/ads/{cycle_id}", msg)


def _cycle_delete_counts(brand_id: str, cycle_id: str) -> list:
    """刪除確認頁要列的「會一起消失的資料」，只留有東西的項目（比照產品刪除）。"""
    rows = ads_repo.count_cycle_data(main_mod.conn, brand_id, cycle_id)
    return [(label, n) for label, n in rows if n > 0]


@router.get("/brands/{brand_id}/ads/{cycle_id}/delete")
async def ads_cycle_delete_get(request: Request, brand_id: str, cycle_id: str):
    brand = main_mod.require_brand(brand_id)
    cycle = _require_cycle(brand_id, cycle_id)
    if not cycle["archived"]:
        return main_mod.redirect_with_message(
            f"/brands/{brand_id}/ads/{cycle_id}", "要先把檔期封存，才能永久刪除。", kind="warn")
    return main_mod.templates.TemplateResponse(
        request, "ads_cycle_delete.html",
        main_mod.ctx(request, brand=brand, nav_current='ads', cycle=cycle, cycle_label=_cycle_label(cycle),
                     counts=_cycle_delete_counts(brand_id, cycle_id), error=None,
                     breadcrumb_items=_crumb(brand, (f"{cycle['start_date']} 檔期",
                                                     f"/brands/{brand_id}/ads/{cycle_id}"),
                                             ("永久刪除檔期", None))),
    )


@router.post("/brands/{brand_id}/ads/{cycle_id}/delete")
async def ads_cycle_delete_post(request: Request, brand_id: str, cycle_id: str,
                                confirm_name: str = Form("")):
    brand = main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    cycle = _require_cycle(brand_id, cycle_id)
    if not cycle["archived"]:
        return main_mod.redirect_with_message(
            f"/brands/{brand_id}/ads/{cycle_id}", "要先把檔期封存，才能永久刪除。", kind="warn")

    label = _cycle_label(cycle)
    if main_mod.clean(confirm_name) != label:
        return main_mod.templates.TemplateResponse(
            request, "ads_cycle_delete.html",
            main_mod.ctx(request, brand=brand, nav_current='ads', cycle=cycle, cycle_label=label,
                         counts=_cycle_delete_counts(brand_id, cycle_id),
                         error="輸入的檔期名稱跟上面顯示的不一樣，請照著再打一次。",
                         breadcrumb_items=_crumb(brand, (f"{cycle['start_date']} 檔期",
                                                         f"/brands/{brand_id}/ads/{cycle_id}"),
                                                 ("永久刪除檔期", None))),
            status_code=400,
        )

    main_mod.corebackup.snapshot(f"before-delete-{cycle_id}")
    ads_repo.delete_cycle(main_mod.conn, brand_id, cycle_id, actor=actor)
    return main_mod.redirect_with_message(
        f"/brands/{brand_id}/ads",
        f"已永久刪除 {label} 這期檔期。刪除前的備份已存進 backups 資料夾。")


@router.get("/brands/{brand_id}/ads/pixel-guide")
async def ads_pixel_guide(request: Request, brand_id: str):
    """Pixel 教學頁：簡短介紹＋導向各平台官方教學連結（決策 0023 第 13 點）。

    註冊順序要在 `/brands/{brand_id}/ads/{cycle_id}` 之前——不然 "pixel-guide" 會被那條路由
    當成 cycle_id 吃掉，變成「找不到廣告檔期」的 404。
    """
    brand = main_mod.require_brand(brand_id)
    return main_mod.templates.TemplateResponse(
        request, "ads_pixel_guide.html",
        main_mod.ctx(request, brand=brand, nav_current='ads',
                     breadcrumb_items=_crumb(brand, ("Pixel 安裝教學", None)),
                     **main_mod.banner_ctx(request)),
    )


@router.get("/brands/{brand_id}/ads/ga4-guide")
async def ads_ga4_guide(request: Request, brand_id: str):
    """GA4 服務帳戶設定教學頁：簡短介紹＋逐步操作＋官方連結（GitHub issue #34）。

    版型比照 ads_pixel_guide：簡介＋逐步＋官方連結。註冊順序同理要在
    `/brands/{brand_id}/ads/{cycle_id}` 之前，避免被那條路由當成 cycle_id 吃掉。
    """
    brand = main_mod.require_brand(brand_id)
    return main_mod.templates.TemplateResponse(
        request, "ads_ga4_guide.html",
        main_mod.ctx(request, brand=brand, nav_current='ads',
                     breadcrumb_items=_crumb(brand, ("GA4 服務帳戶教學", None)),
                     **main_mod.banner_ctx(request)),
    )


@router.get("/brands/{brand_id}/ads/ga4")
async def ads_ga4_page(request: Request, brand_id: str):
    """GA4 同步結果頁：來源／媒介 × 工作階段／轉換／收益，含 purchase 事件驗證狀態。"""
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    return main_mod.templates.TemplateResponse(
        request, "ads_ga4.html",
        main_mod.ctx(request, brand=brand, nav_current='ads',
                     ga4_configured=ga4_sync.is_configured(conn),
                     summary_rows=ga4_sync.latest_summary(conn, brand_id),
                     sync_status=ga4_sync.get_sync_status(conn, brand_id),
                     breadcrumb_items=_crumb(brand, ("GA4 網站數據", None)),
                     **main_mod.banner_ctx(request)),
    )


@router.get("/brands/{brand_id}/ads/ga4/sync")
def ads_ga4_sync_progress(request: Request, brand_id: str, run: Optional[str] = None):
    """從 GA4 抓一次最新資料。沿用既有等待頁模式（決策 0025 補遺第 6 點：設定耗時
    以熟悉 Google Cloud 者為前提，抓資料本身另計，不長，仍走等待頁誠實顯示已等秒數）。

    修憲落地 M3：同樣改背景執行緒＋冪等閘＋逾時，理由見 ads_plan_progress——GA4
    同步不花錢，但一樣會凍住畫面、一樣可能被 F5 重複觸發。
    """
    brand = main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    conn = main_mod.conn
    result_url = f"/brands/{brand_id}/ads/ga4"

    if not ga4_sync.is_configured(conn):
        return main_mod.redirect_with_message(
            result_url, "還沒設定 GA4 服務帳戶金鑰，先去設定頁填一下。", kind="warn")

    progress_key = _progress_key("ga4", brand_id, "_brand_")
    if run != "1":
        entry = _progress_touch(progress_key, _GA4_SYNC_STAGES)
        return _render_wait_page(
            request, brand, heading="正在從 GA4 抓最新資料",
            lede="這次會抓來源／媒介的工作階段、轉換與收益。",
            run_url=f"{request.url.path}?run=1", leave_url=result_url,
            breadcrumb_tail="GA4 同步中",
            progress_rows=_progress_definition_rows(_GA4_SYNC_STAGES, "ga4", entry))

    def work(on_stage):
        return ga4_sync.sync_brand(main_mod.conn, brand_id, actor, on_stage=on_stage)

    entry = _progress_start(progress_key, _GA4_SYNC_STAGES, work)

    if entry["status"] != "done":
        if time.time() - entry["started_at"] > _PROGRESS_TIMEOUT_SECONDS:
            _progress_clear(progress_key)
            return main_mod.redirect_with_message(
                result_url, "GA4 這次沒有在時間內回應，可以再試一次。", kind="warn")
        return _render_wait_page(
            request, brand, heading="正在從 GA4 抓最新資料",
            lede="這次會抓來源／媒介的工作階段、轉換與收益。",
            run_url=f"{request.url.path}?run=1", leave_url=result_url,
            breadcrumb_tail="GA4 同步中",
            progress_rows=_progress_definition_rows(_GA4_SYNC_STAGES, "ga4", entry))

    outcome_kind, payload = entry["result"]
    _progress_clear(progress_key)
    if outcome_kind == "error":
        return main_mod.redirect_with_message(result_url, payload, kind="warn")
    result = payload
    if result.error:
        return main_mod.redirect_with_message(result_url, result.error, kind="warn")
    return main_mod.redirect_with_message(
        result_url, "、".join(_describe_ga4_result(result)) + "。")


def _describe_ga4_result(result) -> list:
    """GA4SyncResult → 人話清單（票 F3 從 ads_ga4_sync_progress 抽出，回填路由共用同一份
    措辭，不重寫第二份）。"""
    parts = [f"抓回 {result.rows} 列來源／媒介資料"]
    if result.purchase_event_seen:
        parts.append("purchase 事件有收到")
    else:
        parts.append("purchase 事件目前沒收到，確認 GA4 轉換設定或看設定教學")
    return parts


@router.get("/brands/{brand_id}/ads/connections/ga4/backfill")
def ads_ga4_backfill_progress(request: Request, brand_id: str, run: Optional[str] = None):
    """回填精靈第③格（票 F3，決策 0039 第 3 條）：一鍵把 GA4 回填 12 個月，僅精靈用——
    日常同步（`/ads/ga4/sync`）維持 30 天視窗不動。GA4 沒有 Meta 那種寫死的官方月數
    上限可夾（見 ga4_sync.py 常數區註解：天花板是 property 建立日，系統查不到），
    優雅降級＝照樣送出 12 個月請求，GA4 對還不存在的日子誠實回傳 0 而不是報錯。
    背景執行＋只讀進度頁＋F5 冪等，沿用既有 _GA4_SYNC_STAGES 三階段。"""
    brand = main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    conn = main_mod.conn
    result_url = f"/brands/{brand_id}/ads/connections"

    if not ga4_sync.is_configured(conn):
        return main_mod.redirect_with_message(
            result_url, "還沒設定 GA4 服務帳戶金鑰，先去設定頁填一下。", kind="warn")

    progress_key = _progress_key("ga4_backfill", brand_id, "_brand_")
    if run != "1":
        entry = _progress_touch(progress_key, _GA4_SYNC_STAGES)
        return _render_wait_page(
            request, brand, heading="正在回填 GA4 網站數據",
            lede=f"這次會嘗試抓回過去 {BACKFILL_MONTHS} 個月的來源／媒介彙總。",
            run_url=f"{request.url.path}?run=1", leave_url=result_url,
            breadcrumb_tail="GA4 回填中",
            progress_rows=_progress_definition_rows(_GA4_SYNC_STAGES, "ga4_backfill", entry))

    def work(on_stage):
        until = date.today().isoformat()
        since = ads_sync.months_before(until, BACKFILL_MONTHS)
        return ga4_sync.sync_brand(main_mod.conn, brand_id, actor, since=since, until=until,
                                   on_stage=on_stage)

    entry = _progress_start(progress_key, _GA4_SYNC_STAGES, work)

    if entry["status"] != "done":
        if time.time() - entry["started_at"] > _PROGRESS_TIMEOUT_SECONDS:
            _progress_clear(progress_key)
            return main_mod.redirect_with_message(
                result_url, "GA4 這次沒有在時間內回應，可以再試一次。", kind="warn")
        return _render_wait_page(
            request, brand, heading="正在回填 GA4 網站數據",
            lede=f"這次會嘗試抓回過去 {BACKFILL_MONTHS} 個月的來源／媒介彙總。",
            run_url=f"{request.url.path}?run=1", leave_url=result_url,
            breadcrumb_tail="GA4 回填中",
            progress_rows=_progress_definition_rows(_GA4_SYNC_STAGES, "ga4_backfill", entry))

    outcome_kind, payload = entry["result"]
    _progress_clear(progress_key)
    if outcome_kind == "error":
        return main_mod.redirect_with_message(result_url, payload, kind="warn")
    result = payload
    if result.error:
        return main_mod.redirect_with_message(result_url, result.error, kind="warn")
    parts = [f"實際回填 {BACKFILL_MONTHS} 個月"] + _describe_ga4_result(result)
    return main_mod.redirect_with_message(result_url, "、".join(parts) + "。")


def _late_rerun_note(late_reruns: list) -> str:
    """跟 app/orders/routes.py 同名函式邏輯一致（那邊是私有函式，不便跨模組匯入，
    這裡是純粹的訊息組字，不是嗅探／匯入邏輯，複製這幾行不算重寫本票禁區）。"""
    if not late_reruns:
        return ""
    reversed_count = sum(1 for r in late_reruns if r["shift"] == "reversal")
    if reversed_count:
        return f" 有 {reversed_count} 期因此重判翻盤，已排進收件匣。"
    return f" 有 {len(late_reruns)} 期因此自動重判過一次。"


@router.get("/brands/{brand_id}/ads/connections")
async def ads_connections_page(request: Request, brand_id: str):
    """資料與連線頁（GitHub issue #44）：萬用檔案口＋Meta／GA4／訂單三個入口對稱排列＋
    待認領入口；金鑰一律深連結到 /settings 對應分區錨點（決策 0028、0029 第 12 點）。"""
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    order_stats = orders_repo.stats(conn, brand_id, today=date.today().isoformat())
    return main_mod.templates.TemplateResponse(
        request, "ads_connections.html",
        main_mod.ctx(request, brand=brand, nav_current='ads',
                     meta_connected=ads_sync.is_configured(conn),
                     ga4_configured=ga4_sync.is_configured(conn),
                     pending_claims=len(ads_sync.list_pending_claims(conn, brand_id)),
                     has_order_data=order_stats["has_history"],
                     breadcrumb_items=_crumb(brand, ("資料與連線", None)),
                     **main_mod.banner_ctx(request)),
    )


@router.post("/brands/{brand_id}/ads/connections/import")
async def ads_connections_import(request: Request, brand_id: str,
                                 drop_file: UploadFile = File(...)):
    """廣告區薄匯入路由（GitHub issue #44）：收檔 → 呼叫既有的
    app.orders.dispatch.import_dropped_file() → 導回本頁。嗅探與匯入邏輯一行不重寫；
    既有 app/orders/routes.py 的 orders_import 導回目的地寫死是 /orders，這裡的
    使用情境需要留在資料與連線頁看結果，所以另開這條薄路由（決策 0029 第 13 點）。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    back = f"/brands/{brand_id}/ads/connections"

    if not drop_file.filename:
        return main_mod.redirect_with_message(back, "沒有選到檔案。", kind="danger")
    content = await drop_file.read()
    if not content:
        return main_mod.redirect_with_message(back, "這個檔案是空的。", kind="danger")

    result = orders_dispatch.import_dropped_file(
        main_mod.conn, brand_id, filename=drop_file.filename, content=content, actor=actor,
        today=date.today().isoformat())

    if result.kind == "unknown":
        return main_mod.redirect_with_message(
            back, result.errors[0] if result.errors else "認不出這個檔案的格式。", kind="danger")

    if result.kind == "easystore_orders":
        if result.errors:
            return main_mod.redirect_with_message(back, result.errors[0], kind="danger")
        r = result.order_result
        msg = f"匯入 {r.orders_imported} 筆新訂單、更新 {r.orders_updated} 筆、{r.items_imported} 個商品品項。"
        msg += _late_rerun_note(result.late_reruns)
        return main_mod.redirect_with_message(back, msg)

    if result.kind == "shopee_report":
        if result.errors:
            return main_mod.redirect_with_message(back, result.errors[0], kind="danger")
        r = result.shopee_result
        return main_mod.redirect_with_message(
            back, f"匯入 {r.imported} 筆新蝦皮訂單、更新 {r.updated} 筆。")

    # meta_ads_csv
    msg = f"匯入 {result.ads_imported} 筆廣告成效資料到對應檔期。"
    if result.ads_quarantined:
        msg += f"其中 {result.ads_quarantined} 筆數字不合理，先擱在一旁不列入計算。"
    msg += _late_rerun_note(result.late_reruns)
    kind = "warn" if result.errors else "ok"
    if result.errors:
        msg += result.errors[0]
    return main_mod.redirect_with_message(back, msg, kind=kind)


@router.get("/brands/{brand_id}/ads/data-migration")
async def ads_data_migration(request: Request, brand_id: str):
    """把舊資料搬進來（票 F7，決策 0039 第一節）：一次性導入檢查清單。四格狀態、部分
    基線小結、成熟門檻報告全部從既有資料查詢推導（app/ads/data_onboarding.py），不建新表、
    不存精靈狀態，天然冪等。

    註冊順序要在 `/brands/{brand_id}/ads/{cycle_id}` 之前——同 pixel-guide／ga4-guide／
    interview／learnings 的先例，不然 "data-migration" 會被那條萬用路由當成 cycle_id 吃掉。
    """
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    checklist = data_onboarding.build_checklist(conn, brand_id)
    progress = data_onboarding.completion(checklist)
    maturity_rows = data_onboarding.maturity_report(conn, brand_id)
    return main_mod.templates.TemplateResponse(
        request, "ads_data_migration.html",
        main_mod.ctx(request, brand=brand, nav_current='ads',
                     checklist=checklist, progress=progress,
                     rail_items=data_onboarding.rail_items(checklist, progress["next_item"]),
                     maturity_rows=maturity_rows,
                     maturity_all_met=all(row["met"] for row in maturity_rows),
                     any_data=any(item["has_data"] for item in checklist if not item["optional"]),
                     breadcrumb_items=_crumb(brand, ("把舊資料搬進來", None)),
                     **main_mod.banner_ctx(request)),
    )


def _safe_next(brand_id: str, next_url: Optional[str]) -> Optional[str]:
    """`next` 跳轉參數的白名單檢查（票 F7）：只接受同品牌底下的路徑，避免這個公開可帶
    query string 的參數被拿去開放轉址；不合規就靜靜退回 None，呼叫端自己接預設值。"""
    if next_url and next_url.startswith(f"/brands/{brand_id}/"):
        return next_url
    return None


@router.get("/brands/{brand_id}/ads/interview")
async def ads_interview_get(request: Request, brand_id: str, next: Optional[str] = None):
    """前朝教訓訪談（GitHub issue #55）：老品牌第一天就能把既有經驗交給系統。

    註冊順序要在 `/brands/{brand_id}/ads/{cycle_id}` 之前——不然 "interview" 會被那條路由
    當成 cycle_id 吃掉，變成「找不到廣告檔期」的 404（同 pixel-guide／ga4-guide 的先例）。

    `next`（票 F7）：搬家精靈檢查清單頁把這格標「選做」的同時，需要訪談送出後跳回清單頁
    而不是廣告首頁——加這個跳轉參數，不重寫第二份訪談流程。
    """
    brand = main_mod.require_brand(brand_id)
    next_url = _safe_next(brand_id, next)
    return main_mod.templates.TemplateResponse(
        request, "ads_interview.html",
        main_mod.ctx(request, brand=brand, nav_current='ads', axes=fingerprint.AXES,
                     next_url=next_url,
                     breadcrumb_items=_crumb(brand, ("前朝教訓訪談", None)),
                     **main_mod.banner_ctx(request)),
    )


@router.post("/brands/{brand_id}/ads/interview")
async def ads_interview_post(request: Request, brand_id: str,
                             bad_angle: Optional[List[str]] = Form(None),
                             good_angle: Optional[List[str]] = Form(None),
                             bad_tone: Optional[List[str]] = Form(None),
                             good_tone: Optional[List[str]] = Form(None),
                             bad_format: Optional[List[str]] = Form(None),
                             good_format: Optional[List[str]] = Form(None),
                             bad_selling_point: Optional[List[str]] = Form(None),
                             good_selling_point: Optional[List[str]] = Form(None),
                             note: str = Form(""), next: Optional[str] = Form(None)):
    """全程選填、跳過不擋任何流程（決策 0025）：什麼都不勾也能送出，等同跳過。"""
    main_mod.require_brand(brand_id)
    conn = main_mod.conn
    actor = main_mod.require_actor(request)

    bad = {"angle": bad_angle or [], "tone": bad_tone or [],
           "format": bad_format or [], "selling_point": bad_selling_point or []}
    good = {"angle": good_angle or [], "tone": good_tone or [],
            "format": good_format or [], "selling_point": good_selling_point or []}
    result = ads_interview.submit(conn, brand_id, bad=bad, good=good, note=note, actor=actor)

    card_count = len(result["rule_cards"])
    hyp_count = len(result["hypotheses"])
    if not card_count and not hyp_count:
        message = "這次沒有勾選任何項目，之後隨時可以回來補。"
    else:
        message = f"記下了 {card_count} 條想避開的方向、{hyp_count} 條想再驗證的方向。"
    if result["conflicts"]:
        # 兩邊都勾＝矛盾，系統不替使用者挑一邊，誠實說哪幾項沒記（見 interview._drop_conflicts）
        message += "；" + "、".join(result["conflicts"]) + " 兩邊都勾了，這幾項先沒記，之後可以回來擇一。"
    back = _safe_next(brand_id, next) or f"/brands/{brand_id}/ads"
    return main_mod.redirect_with_message(back, message)


_PENDING_HYPOTHESIS_LABELS = {"proposed": "待驗證", "testing": "驗證中"}


def _learning_meta_line(conn, brand_id: str, entry: dict) -> str:
    """組「依據」欄的人話：適用範圍／來源期別／樣本數／可信度，程式組字不經 LLM
    （決策 0030 第 11 點：這些值本來就是程式帶入，不是模型判斷）。

    修憲落地 G4（決策 0035 第三節第 8、10 點）：`confidence` 是 ledger 自己的可信度分級
    （`reading.LEDGER_CONFIDENCE_LABELS`，樣本數＋是否重測過），不是資料成色標籤——兩者
    意義不同，不能互換顯示。`needs_revalidation` 這個欄位以前全庫沒有一行寫入過，這裡是
    它第一次真的被讀出來用。"""
    parts = []
    if entry["product_id"]:
        product = bi.get_product(conn, brand_id, entry["product_id"])
        parts.append(product["name"] if product else "已刪除的產品")
    else:
        parts.append("品牌整體")
    if entry["source_cycle_id"]:
        cycle = ads_repo.get_cycle(conn, brand_id, entry["source_cycle_id"])
        if cycle:
            parts.append(f"來源：{cycle['start_date']} 期")
    if entry["sample_size"]:
        parts.append(f"樣本 {entry['sample_size']}")
    if entry["confidence"]:
        parts.append(ads_reading.LEDGER_CONFIDENCE_LABELS.get(entry["confidence"],
                                                              entry["confidence"]))
    if entry["needs_revalidation"]:
        parts.append("建議找機會重新驗證")
    return " ・ ".join(parts)


@router.get("/brands/{brand_id}/ads/learnings")
async def ads_learnings_page(request: Request, brand_id: str):
    """累積智慧頁（GitHub issue #56）：三段——已確認學習／生效中的禁令／還沒處理的候選。

    註冊順序要在 `/brands/{brand_id}/ads/{cycle_id}` 之前——不然 "learnings" 會被那條路由
    當成 cycle_id 吃掉，變成「找不到廣告檔期」的 404（同 pixel-guide／ga4-guide／interview
    的先例）。
    """
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn

    learnings = ads_repo.list_learning_ledger(conn, brand_id)
    for entry in learnings:
        entry["meta_line"] = _learning_meta_line(conn, brand_id, entry)

    active_bans = nextcycle.list_active_bans(conn, brand_id)
    pending_cards = nextcycle.list_pending_rule_cards(conn, brand_id)
    observing_signals = nextcycle.list_observing_signals(conn, brand_id)
    pending_hypotheses = [
        {**h, "status_label": _PENDING_HYPOTHESIS_LABELS.get(h["status"], h["status"])}
        for h in bi.list_strategy_hypotheses(conn, brand_id)
        if h["status"] in ads_reading.PENDING_HYPOTHESIS_STATUSES
    ]

    return main_mod.templates.TemplateResponse(
        request, "ads_learnings.html",
        main_mod.ctx(request, brand=brand, nav_current='ads',
                     learnings=learnings, active_bans=active_bans,
                     pending_cards=pending_cards, observing_signals=observing_signals,
                     pending_hypotheses=pending_hypotheses,
                     breadcrumb_items=_crumb(brand, ("累積智慧", None)),
                     **main_mod.banner_ctx(request)),
    )


@router.post("/brands/{brand_id}/ads/learnings/ledger/{entry_id}/deactivate")
async def ads_learnings_deactivate_ledger(request: Request, brand_id: str, entry_id: str):
    """下架一條已確認學習，下架後不再進 context_compiler 組出的 prompt（票 #56）。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    back = f"/brands/{brand_id}/ads/learnings"
    try:
        ads_repo.deactivate_learning_ledger_entry(main_mod.conn, brand_id, entry_id, actor=actor)
    except ValueError as err:
        return main_mod.redirect_with_message(back, str(err), kind="danger")
    return main_mod.redirect_with_message(back, "已下架這條學習，之後生成內容不會再引用它。")


@router.post("/brands/{brand_id}/ads/learnings/rules/{rule_id}/deactivate")
async def ads_learnings_deactivate_rule(request: Request, brand_id: str, rule_id: str):
    """下架一條生效中的禁令，下架後不再進 context_compiler 組出的 prompt（票 #56）。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    back = f"/brands/{brand_id}/ads/learnings"
    try:
        bi.deactivate_rule(main_mod.conn, brand_id, rule_id, actor=actor)
    except ValueError as err:
        return main_mod.redirect_with_message(back, str(err), kind="danger")
    return main_mod.redirect_with_message(back, "已下架這條禁令，之後生成內容不會再避開它。")


@router.get("/brands/{brand_id}/ads/{cycle_id}")
async def ads_cycle(request: Request, brand_id: str, cycle_id: str):
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    cycle = _require_cycle(brand_id, cycle_id)

    view = _cycle_view(conn, brand_id, cycle)
    allocations = ads_repo.list_cycle_products(conn, brand_id, cycle_id)
    plan_row = ads_plan.get_latest_plan(conn, brand_id, cycle_id)
    pending_options = (ads_plan.get_pending_options(conn, brand_id, cycle_id)
                       if cycle["status"] == "PLAN_SELECT" else [])
    creatives = ads_creative.list_variants(conn, brand_id, cycle_id)
    packages = ads_handoff.list_packages(conn, brand_id, cycle_id)
    return main_mod.templates.TemplateResponse(
        request, "ads_cycle.html",
        main_mod.ctx(request, brand=brand, nav_current='ads', cycle=view, allocations=allocations,
                     plan_row=plan_row, plan=plan_row["plan"] if plan_row else None,
                     pending_option_count=len(pending_options),
                     audience_tier_labels=ads_plan.AUDIENCE_TIER_LABELS,
                     audience_tier_order=ads_plan.AUDIENCE_TIERS,
                     rule_cards=nextcycle.list_pending_rule_cards(conn, brand_id),
                     forecast=onboarding.forecast_snapshot(cycle),
                     diff=onboarding.diff_with_previous(conn, brand_id, cycle_id),
                     # 兌現預言卡出口(b)：第二期檔期內頁頂部常駐卡（票 F5，決策 0039 第 15 條），
                     # 讀「上一期」的快照與實際結果，不是這期自己的——只有上一期存過快照
                     # （目前只有校準期會存）prediction 才非 None，自然只在第二期出現。
                     prediction=ads_reading.prediction_settlement(
                         conn, brand_id, onboarding.previous_cycle(conn, brand_id, cycle)),
                     plan_cost=_plan_cost(conn, plan_row),
                     has_creatives=bool(creatives), creative_count=len(creatives),
                     has_adopted=any(v["decision"] and v["decision"]["decision"] == "adopted"
                                     for v in creatives),
                     package_count=len(packages),
                     activated_count=sum(1 for p in packages if p["mapping"]),
                     snapshot_count=len(ads_performance.list_snapshots(conn, brand_id, cycle_id)),
                     is_simulation=simulation.is_simulation(cycle),
                     readiness_notes=ads_repo.check_readiness(
                         conn, brand_id, [a["product_id"] for a in allocations]),
                     stage_items=_cycle_progress_items(conn, brand_id, cycle),
                     breadcrumb_items=_crumb(brand, (f"{cycle['start_date']} 檔期", None)),
                     # 生成按鈕旁「本次會用」選單（票 #27）：模型清單沿用設定頁同一份，
                     # 思考等級固定五檔；預設值＝這個任務目前真的會用到的模型／思考等級
                     # （不帶覆寫時的 resolve 結果），不是憑空寫死。
                     model_choices=main_mod.MODEL_CHOICES,
                     thinking_choices=[(code, llm_providers.THINKING_LEVEL_LABELS[code])
                                       for code in llm_providers.THINKING_LEVEL_ORDER],
                     plan_default_model=llm_providers.resolve_model(
                         task_type="campaign_plan", conn=conn),
                     plan_default_thinking=llm_providers.resolve_thinking(task_type="campaign_plan"),
                     creative_default_model=llm_providers.resolve_model(
                         task_type="creative_batch", conn=conn),
                     creative_default_thinking=llm_providers.resolve_thinking(
                         task_type="creative_batch"),
                     **main_mod.banner_ctx(request)),
    )


def _plan_cost(conn, plan_row: Optional[dict]):
    """這份計畫花了多少錢（誠實揭露，比照顧問報告頁）。"""
    if not plan_row:
        return None
    task_id = plan_row["plan"].get("llm_task_id")
    if not task_id:
        return None
    row = conn.execute("SELECT cost FROM llm_task WHERE id = ?", (task_id,)).fetchone()
    return row["cost"] if row else None


# ---------------------------------------------------------------------------
# 等待頁誠實化（票 29）＋背景執行＋冪等閘＋逾時（修憲落地 M3）。
#
# 修法前：「先渲染等待頁（meta refresh 導向 ?run=1），?run=1 那一次同步跑完整個生成再
# 轉址」——瀏覽器在那一次 ?run=1 導航整整凍住 20–90 秒，且沒有任何冪等保護（按 F5 就
# 再打一次付費 API）。決策 0037 第 5 條：正解是把生成丟到背景執行緒，路由只讀既有的
# 進度狀態，完成時才 303；meta refresh 機制不變，使用者才真的坐在一張每 3 秒真的會動的
# 頁上。用 brand_id/cycle_id 當 key 記一份「目前在哪一階段、狀態、結果」的模組級 dict：
#   - status="waiting"：使用者看過等待頁，但還沒真的觸發生成（對應舊的 run!=1）。
#   - status="running"：背景執行緒已經在跑（冪等閘：同一個 key 只會有一個 running 執行緒，
#     _progress_start 用鎖判斷「查已有 entry」與「啟動執行緒」這組合是原子的）。
#   - status="done"：執行緒跑完，result=(ok, err) 待下一次請求消化並清除。
#
# ponytail: _progress_state 的讀寫多數是單一鍵賦值（CPython 原子），只有「判斷 key 是否
# 已在跑、要不要啟動新執行緒」這個複合動作真的需要鎖，其餘沿用單純 dict。
_progress_state: dict = {}
_progress_lock = threading.Lock()

_PLAN_STAGES = [
    ("prep", "整理這期的資料與方法論"),
    ("ask_ai", "請 AI 生成方案"),
    ("save", "把方案存起來"),
]
_CREATIVE_STAGES = [
    ("prep", "整理這期的資料與素材規則"),
    ("ask_ai", "請 AI 生成素材"),
    ("save", "檢查與存檔"),
]
_GA4_SYNC_STAGES = [
    ("connect", "連線 GA4 服務帳戶"),
    ("fetch", "抓取來源／媒介成效與 purchase 事件"),
    ("save", "寫入彙總表"),
]
# 判讀沒有細分階段可回報（ads_reading.run／finalize 不接受 on_stage），只借用同一套
# 背景執行／冪等閘／逾時機制，不顯示 progress_rows（沿用原本就沒有階段清單的畫面）。
_READING_STAGES = [("run", "判讀中")]
# 回填（票 F3，決策 0039 第 3 條）：只有精靈用，日常同步（ads_sync_now／
# ads_ga4_sync_progress）維持既有行為與 30 天視窗不動。sync_account 不接受 on_stage，
# 比照判讀借用單一階段；GA4 sync_brand 有 on_stage，沿用既有 _GA4_SYNC_STAGES 三階段。
_META_BACKFILL_STAGES = [("run", "回填 Meta 廣告成效中")]
BACKFILL_MONTHS = 12
# 首版寫死的合理初值（決策 0023 第 9 條修訂）；之後可換成近幾次實測生成耗時的統計範圍。
_USUAL_RANGE = {"plan": "30 到 60 秒", "creative": "40 到 90 秒", "ga4": "5 到 20 秒",
                "meta_backfill": "1 到 3 分鐘", "ga4_backfill": "30 秒到 2 分鐘"}

# 與 DESIGN.md §19.4 規則 6「逾時 90 秒視為失敗」對齊：等待頁不再無限等下去；背景執行緒
# 若真的還在跑（例如撞到 llm/gateway.py 的 120 秒逾時＋一次重試），就讓它安靜跑完，
# 結果寫進一個已經被使用者放棄、之後不會再被讀到的 entry（見 _progress_run 的 None 檢查）。
_PROGRESS_TIMEOUT_SECONDS = 90


def _progress_key(kind: str, brand_id: str, cycle_id: str) -> str:
    return f"{kind}:{brand_id}:{cycle_id}"


def _progress_touch(key: str, stages: list) -> dict:
    """使用者看到等待頁，但還沒觸發生成：第一次碰到這個 key 才記開始時間，已經有紀錄
    （不管是 waiting／running／done）就沿用，不重置——已等秒數才不會被重刷歸零。"""
    with _progress_lock:
        return _progress_state.setdefault(
            key, {"stage": stages[0][0], "started_at": time.time(),
                 "status": "waiting", "result": None})


def _progress_start(key: str, stages: list, work) -> dict:
    """冪等啟動背景生成：同一個 key 已經在跑（running）或已經跑完還沒被消化（done）就
    原樣回傳，不重新啟動執行緒——這是 F5／多分頁重整不會重複打付費 API 的關鍵。

    work 是一個 zero-arg callable：`work(on_stage) -> (ok, err)`，實際呼叫哪個 generate
    函式由呼叫端決定（薄殼：這裡不認識任何一種生成流程的細節）。
    """
    with _progress_lock:
        entry = _progress_state.get(key)
        if entry is None:
            entry = {"stage": stages[0][0], "started_at": time.time(),
                     "status": "running", "result": None}
            _progress_state[key] = entry
            should_start = True
        elif entry["status"] == "waiting":
            entry["status"] = "running"
            should_start = True
        else:
            should_start = False  # running 或 done：已經有一份在跑／跑完了，冪等略過
    if should_start:
        threading.Thread(target=_progress_run, args=(key, work), daemon=True).start()
    return entry


def _progress_run(key: str, work) -> None:
    """背景執行緒實際跑的函式：不假設 work() 回傳值的形狀（plan/creative 回 (ok, err)
    二元組，ga4_sync 回一個 SyncResult 物件，各自語意由呼叫端自己拆），一律包成
    `("ok", 原始回傳值)`；連 work() 本身都爆例外這種非預期狀況才是 `("error", 人話錯誤)`
    ——不吞成靜默失敗（鐵則 6：一切可追溯，至少要讓下一個請求看到「背景執行發生未預期錯誤」）。
    """
    try:
        result = work(lambda s: _progress_set_stage(key, s))
        outcome = ("ok", result)
    except Exception as exc:  # noqa: BLE001 — 背景執行緒的最後一道防線，不能讓例外憑空消失
        outcome = ("error", f"背景執行發生未預期錯誤：{exc}")
    entry = _progress_state.get(key)
    if entry is not None:  # entry 可能已被逾時處理清除；使用者已經離開，安靜結束即可
        entry["status"] = "done"
        entry["result"] = outcome


def _progress_set_stage(key: str, stage: str) -> None:
    entry = _progress_state.get(key)
    if entry is not None:
        entry["stage"] = stage


def _progress_clear(key: str) -> None:
    _progress_state.pop(key, None)


def _progress_definition_rows(stages: list, kind: str, entry: dict) -> list:
    """組出等待頁要的清單：每個實際階段一列（完成／進行中／還沒開始），
    最後加一列「已等 X 秒／通常範圍 Y」——沒有任何百分比或假進度條。"""
    seen_current = False
    rows = []
    for key, label in stages:
        if key == entry["stage"]:
            state, seen_current = "進行中", True
        elif seen_current:
            state = "還沒開始"
        else:
            state = "完成"
        rows.append((label, state, False))
    elapsed = max(0, int(time.time() - entry["started_at"]))
    rows.append(("已等", f"{elapsed} 秒／通常範圍 {_USUAL_RANGE[kind]}", False))
    return rows


def _render_wait_page(request: Request, brand: dict, *, heading: str, lede: str,
                       run_url: str, leave_url: str, breadcrumb_tail: str,
                       progress_rows: Optional[list] = None):
    """等待頁共用渲染（票 M3 從四個進度路由抽出）：run != 1、與 run == 1 但仍在跑，
    畫面長得一模一樣，差別只在 entry 的來源。"""
    return main_mod.templates.TemplateResponse(
        request, "ads_progress.html",
        main_mod.ctx(request, brand=brand, nav_current='ads', heading=heading, lede=lede,
                     run_url=run_url, leave_url=leave_url,
                     refresh=intake_state.REFRESH_SECONDS, progress_rows=progress_rows,
                     breadcrumb_items=_crumb(brand, (breadcrumb_tail, None))),
    )


@router.get("/brands/{brand_id}/ads/{cycle_id}/plan/progress")
def ads_plan_progress(request: Request, brand_id: str, cycle_id: str,
                      run: Optional[str] = None, direction: Optional[str] = None,
                      model: Optional[str] = None, thinking: Optional[str] = None):
    """生成方案要 30–60 秒。修憲落地 M3：生成丟背景執行緒跑，這條路由只讀進度狀態，
    完成時才 303——不再讓瀏覽器在 ?run=1 那次導航整個凍住。

    direction 有值＝老闆在方案選擇頁自己寫了方向，要求重新生成一批（票 4：自由輸入框）。
    model／thinking：生成按鈕旁「本次會用」選單的當場覆寫（票 #27），經 query string
    帶過第一跳 meta-refresh；只有真正啟動生成的那次呼叫會採用（見 _progress_start 的
    冪等閘：後續重整就算網址還帶著這兩個參數，也不會再影響已經在跑的那次呼叫）。
    """
    brand = main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    cycle = _require_cycle(brand_id, cycle_id)
    result_url = f"/brands/{brand_id}/ads/{cycle_id}"
    select_url = f"{result_url}/plan/select"
    was_selecting = cycle["status"] == "PLAN_SELECT"  # 這次是「重新生成」而不是第一次生成
    leave_url = select_url if was_selecting else result_url
    progress_key = _progress_key("plan", brand_id, cycle_id)

    if run != "1":
        entry = _progress_touch(progress_key, _PLAN_STAGES)
        run_url = f"{request.url.path}?run=1"
        if direction:
            run_url += f"&direction={quote(direction)}"
        if model:
            run_url += f"&model={quote(model)}"
        if thinking:
            run_url += f"&thinking={quote(thinking)}"
        return _render_wait_page(
            request, brand, heading="正在規劃這期的打法", lede="這次會出 2 到 4 個方案讓你選。",
            run_url=run_url, leave_url=leave_url, breadcrumb_tail="規劃中",
            progress_rows=_progress_definition_rows(_PLAN_STAGES, "plan", entry))

    def work(on_stage):
        with llm_providers.request_overrides(model=model, thinking=thinking):
            return ads_plan.generate_options(
                main_mod.conn, brand_id, cycle_id, actor, custom_direction=direction,
                on_stage=on_stage)

    entry = _progress_start(progress_key, _PLAN_STAGES, work)

    if entry["status"] != "done":
        if time.time() - entry["started_at"] > _PROGRESS_TIMEOUT_SECONDS:
            _progress_clear(progress_key)
            return main_mod.redirect_with_message(
                leave_url, "AI 這次沒有在時間內回應。你的資料都還在，沒有掉。"
                          "可以再試一次，或先跳過這一步。", kind="warn")
        return _render_wait_page(
            request, brand, heading="正在規劃這期的打法", lede="這次會出 2 到 4 個方案讓你選。",
            run_url=f"{request.url.path}?run=1", leave_url=leave_url, breadcrumb_tail="規劃中",
            progress_rows=_progress_definition_rows(_PLAN_STAGES, "plan", entry))

    outcome_kind, payload = entry["result"]
    _progress_clear(progress_key)
    if outcome_kind == "error":
        return main_mod.redirect_with_message(leave_url, payload, kind="warn")
    ok, err = payload
    if not ok:
        return main_mod.redirect_with_message(leave_url, err, kind="warn")
    return main_mod.redirect_with_message(select_url, "這期的方案準備好了，選一個或自己寫方向。")


@router.get("/brands/{brand_id}/ads/{cycle_id}/plan/select")
async def ads_plan_select_page(request: Request, brand_id: str, cycle_id: str):
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    cycle = _require_cycle(brand_id, cycle_id)
    options = ads_plan.get_pending_options(conn, brand_id, cycle_id)
    if not options:
        return main_mod.redirect_with_message(
            f"/brands/{brand_id}/ads/{cycle_id}", "這期還沒有可選的方案。", kind="warn")
    structure = account_structure.recommend(conn, ads_repo.derived_plan(cycle)["daily_budget"])
    dissents = ads_repo.list_dissents(conn, brand_id, cycle_id, status="pending")
    return main_mod.templates.TemplateResponse(
        request, "ads_plan_select.html",
        main_mod.ctx(request, brand=brand, nav_current='ads', cycle=_cycle_view(conn, brand_id, cycle),
                     options=options,
                     audience_tier_labels=ads_plan.AUDIENCE_TIER_LABELS,
                     audience_tier_order=ads_plan.AUDIENCE_TIERS,
                     methodology_missing=options[0].get("methodology_missing") or [],
                     structure=structure,
                     dissents=dissents,
                     dissent_target_labels=ads_plan.DISSENT_TARGET_LABELS,
                     breadcrumb_items=_crumb(brand, ("選方案", None)),
                     **main_mod.banner_ctx(request)),
    )


@router.post("/brands/{brand_id}/ads/{cycle_id}/dissents/{dissent_id}/decide")
async def ads_dissent_decide(request: Request, brand_id: str, cycle_id: str, dissent_id: str,
                             decision: str = Form(...)):
    """老闆對一筆 AI 具名異議拍板：採納或不採納（決策 0023 第 14、25 點）。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    back_url = f"/brands/{brand_id}/ads/{cycle_id}/plan/select"
    try:
        ads_repo.decide_dissent(main_mod.conn, brand_id, cycle_id, dissent_id, decision, actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(back_url, str(exc), kind="warn")
    label = "採納" if decision == "adopted" else "不採納"
    return main_mod.redirect_with_message(back_url, f"已記錄：{label}這條異議。")


@router.post("/brands/{brand_id}/ads/{cycle_id}/plan/select")
async def ads_plan_select_submit(request: Request, brand_id: str, cycle_id: str,
                                 option_id: Optional[str] = Form(None)):
    """老闆選定一個方案，落地成正式計畫（沿用既有版本機制），接著走既有關卡一。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    result_url = f"/brands/{brand_id}/ads/{cycle_id}"
    try:
        ads_plan.select_option(main_mod.conn, brand_id, cycle_id, actor,
                               option_id=option_id or None)
    except ValueError as exc:
        return main_mod.redirect_with_message(f"{result_url}/plan/select", str(exc), kind="warn")
    return main_mod.redirect_with_message(result_url, "方案選好了，看一下再決定要不要照做。")


@router.get("/brands/{brand_id}/ads/{cycle_id}/creatives")
async def ads_creatives(request: Request, brand_id: str, cycle_id: str):
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    cycle = _require_cycle(brand_id, cycle_id)
    groups = ads_creative.group_by_cell(conn, brand_id, cycle_id)

    # 法務掃描：每次進頁重掃，結果整批換掉——素材改寫過就該重算，不留舊結論
    if groups:
        ads_repo.replace_findings(conn, brand_id, cycle_id, "compliance",
                                  compliance.scan_cycle(conn, brand_id, cycle_id))
    flags = compliance.load_findings(conn, brand_id, cycle_id)
    # 修憲落地 L2：命中內建法規詞庫的素材，第一次被掃到時預設值翻成「已挑掉」
    # （決策 0034 第 25 條）。只在從未被決定過時才寫，不會把使用者剛按過的「勾回」蓋回去；
    # 這次真的寫了新決定，groups 要重讀一次才會反映在畫面上。
    if flags and compliance.apply_default_holds(conn, brand_id, cycle_id, flags,
                                                 compliance.AUTO_HOLD_ACTOR):
        groups = ads_creative.group_by_cell(conn, brand_id, cycle_id)
    auto_held_count = sum(1 for g in groups for v in g["variants"] if v["auto_held"])
    # 這批素材是否在方法論資料缺席的情況下生成——每則變體都存了同一份清單，取第一則即可。
    methodology_missing = next(
        (v["methodology_missing"] for g in groups for v in g["variants"] if v["methodology_missing"]),
        [],
    )
    # 補打一次仍缺的素材型別（票 30）——每則變體都存了同一份清單，取第一則即可；
    # 轉成人話標籤給頁面顯示，不在模板裡做型別對照。
    missing_creative_types = next(
        (v["missing_creative_types"] for g in groups for v in g["variants"]
         if v["missing_creative_types"]),
        [],
    )
    missing_creative_type_labels = [ads_creative.VARIANT_LABELS.get(t, t)
                                    for t in missing_creative_types]
    # 這批素材生成時顧客原話語料庫是否有內容——每則變體都存了同一個值，取第一則即可
    # （票 7，決策 0023 第 18a 點：語料庫空時照樣生成，頁面誠實標注）。
    customer_voice_available = next(
        (v["customer_voice_available"] for g in groups for v in g["variants"]), True,
    )

    return main_mod.templates.TemplateResponse(
        request, "ads_creatives.html",
        main_mod.ctx(request, brand=brand, nav_current='ads', cycle=_cycle_view(conn, brand_id, cycle),
                     groups=groups, flags=flags, methodology_missing=methodology_missing,
                     missing_creative_type_labels=missing_creative_type_labels,
                     customer_voice_available=customer_voice_available,
                     compliance_note=compliance.SCAN_LIMITS_NOTE,
                     coverage_gaps=compliance.coverage_gaps(conn, brand_id),
                     flagged_count=sum(len(v) for v in flags.values()),
                     reject_reasons=fingerprint.REJECT_REASONS,
                     auto_held_count=auto_held_count,
                     show_batch_restore=auto_held_count >= ads_creative.BATCH_RESTORE_THRESHOLD,
                     kept=sum(1 for g in groups for v in g["variants"] if not v["rejected"]),
                     stage_items=_cycle_progress_items(conn, brand_id, cycle),
                     breadcrumb_items=_crumb(brand, (f"{cycle['start_date']} 檔期",
                                                     f"/brands/{brand_id}/ads/{cycle_id}")),
                     **main_mod.banner_ctx(request)),
    )


@router.get("/brands/{brand_id}/ads/{cycle_id}/creatives/progress")
def ads_creatives_progress(request: Request, brand_id: str, cycle_id: str,
                           run: Optional[str] = None,
                           model: Optional[str] = None, thinking: Optional[str] = None):
    """model／thinking：生成按鈕旁「本次會用」選單的當場覆寫（票 #27），見
    ads_plan_progress 同一參數的說明——只在真的生成那一次套用，不落資料庫。

    修憲落地 M3：生成丟背景執行緒跑，見 ads_plan_progress 同一套背景執行／冪等閘／
    逾時說明，這裡不重複。
    """
    brand = main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    result_url = f"/brands/{brand_id}/ads/{cycle_id}/creatives"
    leave_url = f"/brands/{brand_id}/ads/{cycle_id}"
    progress_key = _progress_key("creative", brand_id, cycle_id)

    if run != "1":
        entry = _progress_touch(progress_key, _CREATIVE_STAGES)
        run_url = f"{request.url.path}?run=1"
        if model:
            run_url += f"&model={quote(model)}"
        if thinking:
            run_url += f"&thinking={quote(thinking)}"
        return _render_wait_page(
            request, brand, heading="正在做這期的素材", lede="", run_url=run_url,
            leave_url=leave_url, breadcrumb_tail="做素材中",
            progress_rows=_progress_definition_rows(_CREATIVE_STAGES, "creative", entry))

    def work(on_stage):
        with llm_providers.request_overrides(model=model, thinking=thinking):
            return ads_creative.generate(main_mod.conn, brand_id, cycle_id, actor,
                                         on_stage=on_stage)

    entry = _progress_start(progress_key, _CREATIVE_STAGES, work)

    if entry["status"] != "done":
        if time.time() - entry["started_at"] > _PROGRESS_TIMEOUT_SECONDS:
            _progress_clear(progress_key)
            return main_mod.redirect_with_message(
                leave_url, "AI 這次沒有在時間內回應。你的資料都還在，沒有掉。"
                          "可以再試一次，或先跳過這一步。", kind="warn")
        return _render_wait_page(
            request, brand, heading="正在做這期的素材", lede="",
            run_url=f"{request.url.path}?run=1", leave_url=leave_url,
            breadcrumb_tail="做素材中",
            progress_rows=_progress_definition_rows(_CREATIVE_STAGES, "creative", entry))

    outcome_kind, payload = entry["result"]
    _progress_clear(progress_key)
    if outcome_kind == "error":
        return main_mod.redirect_with_message(leave_url, payload, kind="warn")
    ok, err = payload
    if not ok:
        return main_mod.redirect_with_message(leave_url, err, kind="warn")
    return main_mod.redirect_with_message(
        result_url, "素材好了。預設全部採用，把不要的挑掉就行。")


@router.post("/brands/{brand_id}/ads/{cycle_id}/creatives/{variant_id}/reject")
async def ads_creative_reject(request: Request, brand_id: str, cycle_id: str, variant_id: str,
                              reason_code: str = Form(""), reason_text: str = Form("")):
    """反對制的「不要這個」：記下結構化理由，當場改寫一版放回原位。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    back = f"/brands/{brand_id}/ads/{cycle_id}/creatives"

    try:
        variant = ads_creative.reject(main_mod.conn, brand_id, variant_id,
                                      reason_code=reason_code, reason_text=reason_text,
                                      actor=actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(back, str(exc), kind="warn")

    learned = ads_creative.learned_message(reason_code, variant["fingerprint"])
    ok, _ = ads_creative.rewrite(main_mod.conn, brand_id, variant_id,
                                 reason_code=reason_code, actor=actor)
    if not ok:
        return main_mod.redirect_with_message(
            back, f"{learned}（這次沒能馬上改寫出替代版本，你可以再產一次素材。）", kind="warn")
    return main_mod.redirect_with_message(back, f"{learned}已經改寫一版放在原本的位置。")


@router.post("/brands/{brand_id}/ads/{cycle_id}/creatives/{variant_id}/restore")
async def ads_creative_restore(request: Request, brand_id: str, cycle_id: str, variant_id: str):
    """一鍵勾回：把系統依法規掃描自動預設挑掉的素材改回採用（修憲落地 L2，決策 0034 第 25 條）。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    back = f"/brands/{brand_id}/ads/{cycle_id}/creatives"
    try:
        ads_creative.restore(main_mod.conn, brand_id, variant_id, actor=actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(back, str(exc), kind="warn")
    return main_mod.redirect_with_message(back, "已經勾回，這則會採用。")


@router.post("/brands/{brand_id}/ads/{cycle_id}/creatives/restore-batch")
async def ads_creative_restore_batch(request: Request, brand_id: str, cycle_id: str):
    """批次一鍵：把這期所有系統自動預設挑掉的素材一次勾回（決策 0034 第 25 條第 3 點）。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    back = f"/brands/{brand_id}/ads/{cycle_id}/creatives"
    restored = ads_creative.restore_all_auto_held(main_mod.conn, brand_id, cycle_id, actor=actor)
    if restored == 0:
        return main_mod.redirect_with_message(back, "目前沒有系統自動挑掉的素材可以勾回。",
                                              kind="warn")
    return main_mod.redirect_with_message(back, f"已經勾回 {restored} 則，都會採用。")


@router.post("/brands/{brand_id}/ads/{cycle_id}/creatives/approve")
async def ads_creatives_approve(request: Request, brand_id: str, cycle_id: str):
    """關卡二：素材勾選。反對制——沒被挑掉的就是採用，零操作也能過關。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    adopted = ads_creative.approve_selection(main_mod.conn, brand_id, cycle_id, actor)
    if adopted == 0:
        return main_mod.redirect_with_message(
            f"/brands/{brand_id}/ads/{cycle_id}/creatives",
            "這期所有素材都被挑掉了，先產一批新的再繼續。", kind="warn")
    return main_mod.redirect_with_message(
        f"/brands/{brand_id}/ads/{cycle_id}",
        f"採用了 {adopted} 則素材，接下來準備投放交接包。")


@router.get("/brands/{brand_id}/ads/{cycle_id}/handoff")
async def ads_handoff_page(request: Request, brand_id: str, cycle_id: str):
    """交接包：一頁照著貼，每格一鍵複製，欄位名用 Meta 現行介面的字。"""
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    cycle = _require_cycle(brand_id, cycle_id)
    packages = ads_handoff.list_packages(conn, brand_id, cycle_id)
    extras = ads_handoff.build_extras(conn, brand_id, cycle_id)
    codes = ads_codes.list_codes(conn, brand_id, cycle_id)
    return main_mod.templates.TemplateResponse(
        request, "ads_handoff.html",
        main_mod.ctx(request, brand=brand, nav_current='ads', cycle=_cycle_view(conn, brand_id, cycle),
                     packages=packages, labels=ads_handoff.FIELD_LABELS, extras=extras,
                     codes=codes, source_labels=ads_codes.SOURCE_LABELS,
                     verification=ads_codes.latest_verification(conn, brand_id, cycle_id),
                     lock_reason=ads_codes.is_activation_locked(conn, brand_id, cycle_id),
                     attribution=(ads_codes.attribution_summary(conn, brand_id, cycle_id)
                                  if codes else None),
                     stage_items=_cycle_progress_items(conn, brand_id, cycle),
                     breadcrumb_items=_crumb(brand, (f"{cycle['start_date']} 檔期",
                                                     f"/brands/{brand_id}/ads/{cycle_id}")),
                     **main_mod.banner_ctx(request)),
    )


@router.post("/brands/{brand_id}/ads/{cycle_id}/handoff/codes")
async def ads_handoff_generate_codes(request: Request, brand_id: str, cycle_id: str,
                                     discount_type: str = Form("percent"),
                                     discount_value: str = Form("")):
    """期別自動配碼：字碼／使用上限／效期由系統決定，折數是行銷決策由使用者填
    （GitHub issue #35）。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    back = f"/brands/{brand_id}/ads/{cycle_id}/handoff"
    value, ok = main_mod.parse_number(discount_value)
    if not ok or value is None:
        return main_mod.redirect_with_message(back, "折數請填數字。", kind="warn")
    try:
        ads_codes.generate_codes(main_mod.conn, brand_id, cycle_id,
                                 discount_type=discount_type, discount_value=value, actor=actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(back, str(exc), kind="warn")
    return main_mod.redirect_with_message(
        back, "配碼好了，去 EasyStore 後台照著建立這兩組折扣碼。")


@router.post("/brands/{brand_id}/ads/{cycle_id}/handoff/codes/verify")
async def ads_handoff_verify_codes(request: Request, brand_id: str, cycle_id: str,
                                   ad_code: str = Form(""), ad_discount_type: str = Form(""),
                                   ad_discount_value: str = Form(""), ad_usage_limit: str = Form(""),
                                   ad_valid_from: str = Form(""), ad_valid_to: str = Form(""),
                                   wom_code: str = Form(""), wom_discount_type: str = Form(""),
                                   wom_discount_value: str = Form(""), wom_usage_limit: str = Form(""),
                                   wom_valid_from: str = Form(""), wom_valid_to: str = Form("")):
    """上線前逐欄校驗：規劃碼 vs 後台實際設定，不符鎖住這期的開跑動作（決策 0025 補遺第 7 點）。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    back = f"/brands/{brand_id}/ads/{cycle_id}/handoff"
    actual = {
        "ad": {"code": ad_code, "discount_type": ad_discount_type,
               "discount_value": ad_discount_value, "usage_limit": ad_usage_limit,
               "valid_from": ad_valid_from, "valid_to": ad_valid_to},
        "word_of_mouth": {"code": wom_code, "discount_type": wom_discount_type,
                          "discount_value": wom_discount_value, "usage_limit": wom_usage_limit,
                          "valid_from": wom_valid_from, "valid_to": wom_valid_to},
    }
    try:
        result = ads_codes.verify(main_mod.conn, brand_id, cycle_id, actual=actual, actor=actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(back, str(exc), kind="warn")
    if result["passed"]:
        return main_mod.redirect_with_message(back, "校驗過了，規劃碼跟後台設定一致。")
    return main_mod.redirect_with_message(
        back, "校驗沒過，這期開跑動作先鎖住，改好後台設定再重新校驗。", kind="warn")


@router.post("/brands/{brand_id}/ads/{cycle_id}/handoff/build")
async def ads_handoff_build(request: Request, brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    count = ads_handoff.build_packages(main_mod.conn, brand_id, cycle_id, actor)
    back = f"/brands/{brand_id}/ads/{cycle_id}/handoff"
    if count == 0:
        return main_mod.redirect_with_message(
            back, "這期還沒有採用的素材，先去素材那一步確認。", kind="warn")
    return main_mod.redirect_with_message(back, f"交接包好了，共 {count} 組廣告設定。")


@router.post("/brands/{brand_id}/ads/{cycle_id}/handoff/missing-field")
async def ads_handoff_missing_field(request: Request, brand_id: str, cycle_id: str,
                                    field_key: str = Form("")):
    """「我找不到這欄位」：Meta 介面改版時，這是我們唯一會知道的管道。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    ads_handoff.report_missing_field(main_mod.conn, brand_id, cycle_id, field_key, actor)
    return main_mod.redirect_with_message(
        f"/brands/{brand_id}/ads/{cycle_id}/handoff",
        "收到了，我們會確認 Meta 是不是改了介面。這欄先跳過沒關係。")


@router.post("/brands/{brand_id}/ads/{cycle_id}/handoff/{package_id}/activate")
async def ads_handoff_activate(request: Request, brand_id: str, cycle_id: str, package_id: str,
                               meta_account_id: str = Form(""),
                               meta_campaign_id: str = Form(""),
                               meta_adset_id: str = Form(""),
                               meta_ad_id: str = Form("")):
    """關卡三：具名投放授權。使用者明確確認「已經在 Meta 開始跑了」才成立（鐵則 4）。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    back = f"/brands/{brand_id}/ads/{cycle_id}/handoff"
    try:
        ads_handoff.authorize_and_map(
            main_mod.conn, brand_id, cycle_id, package_id,
            meta_ids={"meta_account_id": meta_account_id,
                      "meta_campaign_id": meta_campaign_id,
                      "meta_adset_id": meta_adset_id, "meta_ad_id": meta_ad_id},
            actor=actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(back, str(exc), kind="warn")
    return main_mod.redirect_with_message(
        back, "記下來了。之後回填成效時，系統就對得上這組廣告的數字。")


@router.get("/brands/{brand_id}/ads/{cycle_id}/checklist")
async def ads_checklist_page(request: Request, brand_id: str, cycle_id: str):
    """投放前檢查清單：一次性（品牌層）＋每期必看，兩類都不擋流程，只記錄勾選（票 10）。"""
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    cycle = _require_cycle(brand_id, cycle_id)
    return main_mod.templates.TemplateResponse(
        request, "ads_checklist.html",
        main_mod.ctx(request, brand=brand, nav_current='ads', cycle=_cycle_view(conn, brand_id, cycle),
                     one_time_items=ads_checklist.one_time_status(conn, brand_id),
                     cycle_items=ads_checklist.cycle_status(conn, brand_id, cycle_id),
                     stage_items=_cycle_progress_items(conn, brand_id, cycle),
                     breadcrumb_items=_crumb(brand, (f"{cycle['start_date']} 檔期",
                                                     f"/brands/{brand_id}/ads/{cycle_id}")),
                     **main_mod.banner_ctx(request)),
    )


@router.post("/brands/{brand_id}/ads/{cycle_id}/checklist/one-time/{item_key}")
async def ads_checklist_one_time_toggle(request: Request, brand_id: str, cycle_id: str,
                                        item_key: str, checked: str = Form("1")):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    try:
        ads_checklist.set_one_time(main_mod.conn, brand_id, item_key, checked == "1", actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(
            f"/brands/{brand_id}/ads/{cycle_id}/checklist", str(exc), kind="warn")
    return main_mod.redirect_with_message(f"/brands/{brand_id}/ads/{cycle_id}/checklist", "記下來了。")


@router.post("/brands/{brand_id}/ads/{cycle_id}/checklist/cycle/{item_key}")
async def ads_checklist_cycle_toggle(request: Request, brand_id: str, cycle_id: str,
                                     item_key: str, checked: str = Form("1")):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    try:
        ads_checklist.set_cycle_item(main_mod.conn, brand_id, cycle_id, item_key,
                                     checked == "1", actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(
            f"/brands/{brand_id}/ads/{cycle_id}/checklist", str(exc), kind="warn")
    return main_mod.redirect_with_message(f"/brands/{brand_id}/ads/{cycle_id}/checklist", "記下來了。")


@router.get("/brands/{brand_id}/ads/{cycle_id}/performance")
async def ads_performance_page(request: Request, brand_id: str, cycle_id: str):
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    cycle = _require_cycle(brand_id, cycle_id)
    snapshots = ads_performance.list_snapshots(conn, brand_id, cycle_id)
    return main_mod.templates.TemplateResponse(
        request, "ads_performance.html",
        main_mod.ctx(request, brand=brand, nav_current='ads', cycle=_cycle_view(conn, brand_id, cycle),
                     summary=ads_performance.totals(conn, brand_id, cycle_id),
                     quarantined=[s for s in snapshots if s["quarantined"]],
                     reconciliation=ads_reconcile_mod.load(conn, brand_id, cycle_id),
                     self_answer_questions=guardrails.SELF_ANSWER_QUESTIONS,
                     reading=ads_reading.load(conn, brand_id, cycle_id),
                     prediction=ads_reading.prediction_settlement(conn, brand_id, cycle),
                     repurchase_dissents=[
                         d for d in ads_repo.list_dissents(conn, brand_id, cycle_id, status="pending")
                         if d["target_type"] == "repurchase_breakeven"
                     ],
                     settlement=ads_settlement.load_snapshot(conn, brand_id, cycle_id),
                     shopee_code=orders_channel.get_shopee_code(conn, brand_id, cycle_id),
                     next_cycle=nextcycle.load(conn, brand_id, cycle_id),
                     checklist=ads_checklist.completeness(conn, brand_id, cycle_id),
                     is_simulation=simulation.is_simulation(cycle),
                     simulation_note=simulation.SIMULATION_NOTE,
                     stage_items=_cycle_progress_items(conn, brand_id, cycle),
                     breadcrumb_items=_crumb(brand, (f"{cycle['start_date']} 檔期",
                                                     f"/brands/{brand_id}/ads/{cycle_id}")),
                     errors={}, **main_mod.banner_ctx(request)),
    )


@router.post("/brands/{brand_id}/ads/{cycle_id}/performance/hypotheses")
async def ads_hypotheses_resolve(request: Request, brand_id: str, cycle_id: str):
    """判讀頁假設結案（GitHub issue #53）：表單欄位是 verdict_<假設id>，AI 已預填三選一，
    使用者零操作也能過——直接送出就照 AI 的預選結案。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    form = await request.form()
    back = f"/brands/{brand_id}/ads/{cycle_id}/performance"
    verdicts = {key[len("verdict_"):]: value for key, value in form.items()
               if key.startswith("verdict_")}
    if not verdicts:
        return main_mod.redirect_with_message(back, "沒有可結案的假設。", kind="warn")
    try:
        updated = ads_reading.resolve_hypotheses(main_mod.conn, brand_id, cycle_id, verdicts,
                                                 actor=actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(back, str(exc), kind="warn")
    if not updated:
        return main_mod.redirect_with_message(back, "這些假設已經結案過了。", kind="warn")
    return main_mod.redirect_with_message(back, f"已結案 {updated} 條假設。")


@router.post("/brands/{brand_id}/ads/{cycle_id}/performance/reconcile")
async def ads_reconcile(request: Request, brand_id: str, cycle_id: str,
                        budget_same: str = Form(""), schedule_same: str = Form(""),
                        other_campaign_running: str = Form("")):
    """對帳：自動比對總花費，加上使用者自答的三題（API 掛掉時的退路）。

    三題都沒答也可以按——自答是補充資訊，不是新的必經關卡。
    """
    main_mod.require_brand(brand_id)
    main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)

    def _tri(raw):
        return {"yes": True, "no": False}.get(raw)

    answers = {"budget_same": _tri(budget_same), "schedule_same": _tri(schedule_same),
               "other_campaign_running": _tri(other_campaign_running)}
    result = ads_reconcile_mod.run(main_mod.conn, brand_id, cycle_id, self_answers=answers)

    back = f"/brands/{brand_id}/ads/{cycle_id}/performance/data"
    if not result["findings"]:
        return main_mod.redirect_with_message(back, "對過了，數字跟計畫對得上。")
    return main_mod.redirect_with_message(
        back, f"對過了，發現 {len(result['findings'])} 處跟計畫不一樣，"
              f"本期判讀標為「{result['label']}」。", kind="warn")


@router.get("/brands/{brand_id}/ads/{cycle_id}/revenue-reconcile")
async def ads_revenue_reconcile_page(request: Request, brand_id: str, cycle_id: str):
    """舊網址（票 #36）已併入資料操作子頁（GitHub issue #47：成效頁拆層），302 轉址，
    不再是旁支暗頁。"""
    main_mod.require_brand(brand_id)
    _require_cycle(brand_id, cycle_id)
    return RedirectResponse(
        f"/brands/{brand_id}/ads/{cycle_id}/performance/data#revenue-reconcile",
        status_code=302)


@router.get("/brands/{brand_id}/ads/{cycle_id}/performance/data")
async def ads_performance_data_page(request: Request, brand_id: str, cycle_id: str):
    """資料操作子頁（GitHub issue #47）：匯入 CSV、手動填、蝦皮碼、對帳自答、營收校準
    全部收在這裡；成效頁本身只留判讀結論（拆層，決策 0029 第 10 點）。"""
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    cycle = _require_cycle(brand_id, cycle_id)
    reading = ads_reading.load(conn, brand_id, cycle_id)
    return main_mod.templates.TemplateResponse(
        request, "ads_performance_data.html",
        main_mod.ctx(request, brand=brand, nav_current='ads', cycle=_cycle_view(conn, brand_id, cycle),
                     summary=ads_performance.totals(conn, brand_id, cycle_id),
                     snapshots=ads_performance.list_snapshots(conn, brand_id, cycle_id),
                     is_simulation=simulation.is_simulation(cycle),
                     channel=(reading["cycle"]["result"].get("channel_comparison")
                              if reading["cycle"] else None),
                     shopee_code=orders_channel.get_shopee_code(conn, brand_id, cycle_id),
                     self_answer_questions=guardrails.SELF_ANSWER_QUESTIONS,
                     reconcile=ads_inflation.reconcile_cycle(conn, brand_id, cycle_id),
                     coefficient=ads_inflation.effective_coefficient(conn, brand_id),
                     cadence=ads_inflation.cadence_state(conn, brand_id),
                     breadcrumb_items=_crumb(brand, (f"{cycle['start_date']} 檔期",
                                                     f"/brands/{brand_id}/ads/{cycle_id}"),
                                             ("成效", f"/brands/{brand_id}/ads/{cycle_id}/performance"),
                                             ("資料操作", None)),
                     **main_mod.banner_ctx(request)),
    )


@router.post("/brands/{brand_id}/ads/{cycle_id}/revenue-reconcile/calibrate")
async def ads_revenue_reconcile_calibrate(request: Request, brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    back = f"/brands/{brand_id}/ads/{cycle_id}/performance/data"
    try:
        result = ads_inflation.calibrate(main_mod.conn, brand_id, cycle_id, actor=actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(back, str(exc), kind="warn")
    return main_mod.redirect_with_message(
        back, f"係數校準到第 {result['version']} 版：{result['coefficient']:.2f} 倍。")


@router.post("/brands/{brand_id}/ads/{cycle_id}/performance/shopee-code")
async def ads_shopee_code(request: Request, brand_id: str, cycle_id: str,
                          code: str = Form(""), redemption_count: str = Form("")):
    """蝦皮期別專屬碼＋回收數（GitHub issue #40）：全部選填，外溢下限鐵證。重新判讀後
    才會反映到通路對照卡的燈號（比照 repurchase_line／baseline_comparison 只在判讀時算）。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    back = f"/brands/{brand_id}/ads/{cycle_id}/performance/data"

    count_value = None
    if redemption_count.strip():
        count_value, ok = main_mod.parse_number(redemption_count)
        if not ok:
            return main_mod.redirect_with_message(back, "回收數請填數字，或留空。", kind="warn")
        count_value = int(count_value)
    try:
        orders_channel.set_shopee_code(main_mod.conn, brand_id, cycle_id, code=code or None,
                                       redemption_count=count_value, actor=actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(back, str(exc), kind="warn")
    return main_mod.redirect_with_message(back, "已記下蝦皮期別碼資料，重新判讀後會反映在通路對照卡。")


@router.get("/brands/{brand_id}/ads/{cycle_id}/reading/progress")
def ads_reading_progress(request: Request, brand_id: str, cycle_id: str,
                         run: Optional[str] = None, final: Optional[str] = None):
    """判讀：狀態由規則判，LLM 只把結論翻成人話（決策 0016 硬性原則 4）。

    final=1 是期末＋14 天最終結算入口（票 #38，決策 0025 判讀節奏第 5 點）：重用同一條
    等待頁與 run 流程，只是跑完後多把檔期標成 CLOSED——不為此另開一份等待頁模板。

    修憲落地 M3：同樣改背景執行緒＋冪等閘＋逾時，理由見 ads_plan_progress。
    """
    brand = main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    result_url = f"/brands/{brand_id}/ads/{cycle_id}/performance"
    is_final = final == "1"
    heading = "正在做最終結算" if is_final else "正在判讀這期的成效"
    progress_key = _progress_key("reading", brand_id, cycle_id)

    if run != "1":
        run_url = f"{request.url.path}?run=1" + ("&final=1" if is_final else "")
        _progress_touch(progress_key, _READING_STAGES)
        return _render_wait_page(
            request, brand, heading=heading, lede="通常要 20 到 40 秒。", run_url=run_url,
            leave_url=result_url, breadcrumb_tail="判讀中")

    def work(on_stage):
        if is_final:
            return ads_reading.finalize(main_mod.conn, brand_id, cycle_id, actor)
        return ads_reading.run(main_mod.conn, brand_id, cycle_id, actor)

    entry = _progress_start(progress_key, _READING_STAGES, work)

    if entry["status"] != "done":
        if time.time() - entry["started_at"] > _PROGRESS_TIMEOUT_SECONDS:
            _progress_clear(progress_key)
            return main_mod.redirect_with_message(
                result_url, "AI 這次沒有在時間內回應。你的資料都還在，沒有掉。"
                           "可以再試一次，或先跳過這一步。", kind="warn")
        run_url = f"{request.url.path}?run=1" + ("&final=1" if is_final else "")
        return _render_wait_page(
            request, brand, heading=heading, lede="通常要 20 到 40 秒。", run_url=run_url,
            leave_url=result_url, breadcrumb_tail="判讀中")

    outcome_kind, payload = entry["result"]
    _progress_clear(progress_key)
    if outcome_kind == "error":
        return main_mod.redirect_with_message(result_url, payload, kind="warn")
    ok, err = payload
    if not ok:
        return main_mod.redirect_with_message(result_url, err, kind="warn")
    ok_message = "最終結算完成，這期正式結案。" if is_final else "判讀好了。"
    return main_mod.redirect_with_message(result_url, ok_message)


@router.post("/brands/{brand_id}/ads/{cycle_id}/performance/simulate")
async def ads_simulate(request: Request, brand_id: str, cycle_id: str):
    """替模擬檔期產生假成效。數字由程式算，不讓 LLM 編。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    back = f"/brands/{brand_id}/ads/{cycle_id}/performance"
    ok, note = simulation.generate(main_mod.conn, brand_id, cycle_id, actor)
    if not ok:
        return main_mod.redirect_with_message(back, note, kind="warn")
    return main_mod.redirect_with_message(back, f"模擬成效出來了（{note}）。")


async def _decode_csv_upload(csv_file: Optional[UploadFile], csv_text: str) -> tuple:
    """上傳檔案或直接貼內容都可以；回傳 (內容文字, 編碼錯誤訊息或 None)。"""
    if csv_file is not None and csv_file.filename:
        raw = await csv_file.read()
        for encoding in ("utf-8-sig", "utf-8", "cp950", "big5"):
            try:
                return raw.decode(encoding), None
            except UnicodeDecodeError:
                continue
        return "", "這個檔案的文字編碼讀不出來，請用 Excel 另存成 UTF-8 的 CSV。"
    return csv_text, None


@router.post("/brands/{brand_id}/ads/{cycle_id}/performance/csv")
async def ads_performance_csv(request: Request, brand_id: str, cycle_id: str,
                              csv_file: UploadFile = File(None), csv_text: str = Form("")):
    """CSV 匯入。上傳檔案或直接貼內容都可以。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    back = f"/brands/{brand_id}/ads/{cycle_id}/performance/data"

    text, decode_error = await _decode_csv_upload(csv_file, csv_text)
    if decode_error:
        return main_mod.redirect_with_message(back, decode_error, kind="warn")

    # 缺日期欄的資料列要退回今天，不能留空字串（issue #23 bug 4）
    result = ads_performance.import_csv(main_mod.conn, brand_id, cycle_id, text, actor=actor,
                                        today=date.today().isoformat())
    if result.errors:
        return main_mod.redirect_with_message(back, result.errors[0], kind="warn")

    ads_performance.save_derived_metrics(main_mod.conn, brand_id, cycle_id)
    msg = f"匯入 {result.imported} 筆成效資料。"
    if result.quarantined:
        msg += f"其中 {result.quarantined} 筆數字不合理，先擱在一旁不列入計算。"
    return main_mod.redirect_with_message(back, msg)


@router.post("/brands/{brand_id}/ads/{cycle_id}/performance/manual")
async def ads_performance_manual(request: Request, brand_id: str, cycle_id: str,
                                 spend: str = Form(""), impressions: str = Form(""),
                                 clicks: str = Form(""), conversions: str = Form(""),
                                 revenue: str = Form(""), date_start: str = Form(""),
                                 date_stop: str = Form("")):
    """手動輸入。API 掛掉、CSV 也匯不進來時的最後退路。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    back = f"/brands/{brand_id}/ads/{cycle_id}/performance/data"

    values = {}
    for key, raw in (("spend", spend), ("impressions", impressions), ("clicks", clicks),
                     ("conversions", conversions), ("revenue", revenue)):
        value, ok = main_mod.parse_number(raw)
        if not ok:
            return main_mod.redirect_with_message(back, "數字欄位請只填數字。", kind="warn")
        values[key] = value
    values["date_start"] = date_start or None
    values["date_stop"] = date_stop or None

    result = ads_performance.import_manual(main_mod.conn, brand_id, cycle_id, values,
                                           actor=actor)
    if result.errors:
        return main_mod.redirect_with_message(back, result.errors[0], kind="warn")
    ads_performance.save_derived_metrics(main_mod.conn, brand_id, cycle_id)
    return main_mod.redirect_with_message(back, "記下來了。")


@router.post("/brands/{brand_id}/ads/reminders/{reminder_id}/dismiss")
async def ads_reminder_dismiss(request: Request, brand_id: str, reminder_id: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    onboarding.dismiss(main_mod.conn, brand_id, reminder_id, actor=actor)
    back = (request.headers.get("referer") or f"/brands/{brand_id}/ads").split("?")[0]
    return main_mod.redirect_with_message(back, "好，這則提醒收起來了。")


@router.get("/brands/{brand_id}/ads/{cycle_id}/checkpoint/{kind}")
async def ads_checkpoint_page(request: Request, brand_id: str, cycle_id: str, kind: str):
    """期中檢查點頁（票 9）：第 3／7 天提醒卡點進來就是這裡。健康檢查模式，明文不判勝負。"""
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    cycle = _require_cycle(brand_id, cycle_id)
    if kind not in ads_checkpoint.KIND_LABELS:
        raise main_mod.NotFoundKind("檢查點")

    history = ads_checkpoint.list_checkpoints(conn, brand_id, cycle_id)
    return main_mod.templates.TemplateResponse(
        request, "ads_checkpoint.html",
        main_mod.ctx(request, brand=brand, nav_current='ads', cycle=_cycle_view(conn, brand_id, cycle),
                     kind=kind, kind_label=ads_checkpoint.KIND_LABELS[kind],
                     latest=next((c for c in history if c["kind"] == kind), None),
                     history=[c for c in history if c["status"] == "active"],
                     breadcrumb_items=_crumb(brand, (f"{cycle['start_date']} 檔期",
                                                     f"/brands/{brand_id}/ads/{cycle_id}"),
                                             (ads_checkpoint.KIND_LABELS[kind], None)),
                     **main_mod.banner_ctx(request)),
    )


@router.post("/brands/{brand_id}/ads/{cycle_id}/checkpoint/{kind}")
async def ads_checkpoint_run(request: Request, brand_id: str, cycle_id: str, kind: str,
                             csv_file: UploadFile = File(None), csv_text: str = Form("")):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    back = f"/brands/{brand_id}/ads/{cycle_id}/checkpoint/{kind}"
    if kind not in ads_checkpoint.KIND_LABELS:
        raise main_mod.NotFoundKind("檢查點")

    text, decode_error = await _decode_csv_upload(csv_file, csv_text)
    if decode_error:
        return main_mod.redirect_with_message(back, decode_error, kind="warn")

    result = ads_checkpoint.run(main_mod.conn, brand_id, cycle_id, kind, actor=actor,
                                csv_text=text or None)
    if result.get("merged_into_final"):
        return main_mod.redirect_with_message(
            f"/brands/{brand_id}/ads/{cycle_id}/performance",
            "這期已經進入期末判讀，期中檢查不用再補做，直接看期末結論。")
    if result["import_errors"]:
        return main_mod.redirect_with_message(back, result["import_errors"][0], kind="warn")
    msg = "健康檢查跑完了。" if result["data_sufficient"] else "還沒有成效資料，先匯入 CSV 再檢查。"
    return main_mod.redirect_with_message(back, msg)


@router.post("/brands/{brand_id}/ads/checkpoints/{checkpoint_id}/{action}")
async def ads_checkpoint_manage(request: Request, brand_id: str, checkpoint_id: str, action: str):
    """檢查點紀錄的封存／恢復／刪除（決策 0023 第 8 條：新資料實體必附封存＋刪除）。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    back = (request.headers.get("referer") or f"/brands/{brand_id}/ads").split("?")[0]
    try:
        if action == "archive":
            ads_checkpoint.set_status(main_mod.conn, brand_id, checkpoint_id,
                                      status="archived", actor=actor)
            return main_mod.redirect_with_message(back, "已封存這筆檢查點紀錄。")
        if action == "restore":
            ads_checkpoint.set_status(main_mod.conn, brand_id, checkpoint_id,
                                      status="active", actor=actor)
            return main_mod.redirect_with_message(back, "已恢復這筆檢查點紀錄。")
        if action == "delete":
            ads_checkpoint.delete(main_mod.conn, brand_id, checkpoint_id, actor=actor)
            return main_mod.redirect_with_message(back, "已刪除這筆檢查點紀錄。")
    except ValueError as exc:
        return main_mod.redirect_with_message(back, str(exc), kind="warn")
    raise main_mod.NotFoundKind("動作")


@router.post("/brands/{brand_id}/ads/rule-cards/{card_id}/{action}")
async def ads_rule_card_decide(request: Request, brand_id: str, card_id: str, action: str):
    """規則卡的決定。接受才升級為品牌智庫的長期規則——學習不會自己變成規則（鐵則 3）。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    back = request.headers.get("referer") or f"/brands/{brand_id}/ads"
    try:
        card = nextcycle.decide_rule_card(main_mod.conn, brand_id, card_id,
                                          accept=(action == "accept"), actor=actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(back.split("?")[0], str(exc), kind="warn")
    if card["fingerprint_axis"] == nextcycle.OVERCLAIM_CLAIM_AXIS:
        msg = ("已經登記為禁用宣稱，之後掃描與生成都會避開這句話。" if card["status"] == "accepted"
               else "好，這句先不登記。")
    else:
        msg = ("記住了，以後產素材會避開這個方向。" if card["status"] == "accepted"
               else "好，這條不記成長期規則。")
    return main_mod.redirect_with_message(back.split("?")[0], msg)


@router.post("/brands/{brand_id}/ads/{cycle_id}/plan/approve")
async def ads_plan_approve(request: Request, brand_id: str, cycle_id: str):
    """關卡一：計畫確認。這是三道人工關卡的第一道，不可由系統自動代按。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    try:
        ads_plan.approve(main_mod.conn, brand_id, cycle_id, actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(
            f"/brands/{brand_id}/ads/{cycle_id}", str(exc), kind="warn")
    return main_mod.redirect_with_message(
        f"/brands/{brand_id}/ads/{cycle_id}", "計畫確認了，接下來做素材。")
