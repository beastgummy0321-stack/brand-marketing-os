# -*- coding: utf-8 -*-
"""app/ads/routes_progress.py — 背景進度引擎＋等待頁共用渲染（T4 廣告模組 Jinja 大清倉，
從 app/ads/routes.py 搬出）。

修法前：「先渲染等待頁（meta refresh 導向 ?run=1），?run=1 那一次同步跑完整個生成再
轉址」——瀏覽器在那一次 ?run=1 導航整整凍住 20–90 秒，且沒有任何冪等保護（按 F5 就
再打一次付費 API）。決策 0037 第 5 條：正解是把生成丟到背景執行緒，路由只讀既有的
進度狀態，完成時才 303；meta refresh 機制不變，使用者才真的坐在一張每 3 秒真的會動的
頁上。用 brand_id/cycle_id 當 key 記一份「目前在哪一階段、狀態、結果」的模組級 dict：
  - status="waiting"：使用者看過等待頁，但還沒真的觸發生成（對應舊的 run!=1）。
  - status="running"：背景執行緒已經在跑（冪等閘：同一個 key 只會有一個 running 執行緒，
    _progress_start 用鎖判斷「查已有 entry」與「啟動執行緒」這組合是原子的）。
  - status="done"：執行緒跑完，result=(ok, err) 待下一次請求消化並清除。

`app.ads.routes`（匯總檔）在自己模組頂端 `from app.ads.routes_progress import ...`
把這裡的名字原樣接回去，讓既有 `from app.ads import routes as ads_routes` 再
`ads_routes._progress_key(...)` 這套跨檔慣例、以及測試對 `ads_routes._PROGRESS_
TIMEOUT_SECONDS` 之類的模組級屬性覆寫（test_ads_progress_background.py、
test_ads_plan_status_json_api.py）繼續原樣可用——名字在哪個模組被 import 進去，
屬性覆寫／dict 內容互動都是同一份物件，不受影響。仍在用這套引擎的呼叫端：
app/ads/routes_plan.py（打法生成）、routes_performance.py（判讀）、routes_sync.py
（Meta／GA4 回填精靈），以及 /api 端點 routes_campaigns_open_api.py、
routes_tracking_api.py、routes_weekly_proposals_api.py 等——全部一律
`ads_routes.` 開頭即時查值，不得改成 `from app.ads.routes_progress import X`
靜態綁死（同 orders_channel 那組注入變數的先例，理由見 app/ads/routes.py 檔頭）。

ponytail: _progress_state 的讀寫多數是單一鍵賦值（CPython 原子），只有「判斷 key 是否
已在跑、要不要啟動新執行緒」這個複合動作真的需要鎖，其餘沿用單純 dict。
"""

import threading
import time
from typing import Optional

from fastapi import Request

import app.shared.web as main_mod
from app.intake import state as intake_state
from app.ads.routes_common import _crumb

_progress_state: dict = {}
_progress_lock = threading.Lock()

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
