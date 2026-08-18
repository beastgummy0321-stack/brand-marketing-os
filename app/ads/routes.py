# -*- coding: utf-8 -*-
"""app/ads/routes.py — 廣告分支的頁面路由（匯總檔）。

第 8 刀：原本這裡塞了 2213 行、61 個路由，改一個小按鈕都要在裡面找位置、還要確認
沒踩到旁邊 60 個入口。拆成 app/ads/routes_*.py 多個模組後，本檔只剩三件事：

1. 持有背景執行緒進度引擎（`_progress_state` 等）與跨模組注入變數
   （`orders_channel`／`orders_dispatch`／`orders_repo`）——理由見下方說明，
   這兩類狀態會被 main.py 或測試在 import 之後動態改值，只能留在這個模組路徑上。
2. 依序 `include_router()` 掛上各主題檔的 router，組成同一個 `router` 物件。
3. 讓 app/main.py 既有的 `from app.ads.routes import router` 這行 import 完全不必改。

純搬移，不改任何網址、HTTP 方法、或行為。各主題檔開頭都有自己負責哪些頁的清單：

- routes_common.py       共用小工具：麵包屑、檔期讀取、五格進度軌等各檔都要用的函式
- routes_sync.py         首頁、歷期戰績、Meta／GA4 同步與回填、待認領、提醒收起
- routes_connections.py  Pixel／GA4 教學頁、資料與連線頁、萬用匯入、把舊資料搬進來
- routes_interview.py    前朝教訓訪談、累積智慧、規則卡決定
- routes_plan.py         開新檔期、封存／刪除、檔期內頁（含萬用路由）、打法規劃與選擇
- routes_creative.py     素材生成、反對／勾回、關卡二
- routes_handoff.py      交接包、期別配碼、投放授權、投放前檢查清單
- routes_performance.py  成效頁、判讀、對帳、期中檢查點、CSV／手動匯入

`orders_channel`／`orders_dispatch`／`orders_repo`：第 7 刀（A1 三層地界新規則：
app/ads 不得 import app.orders，見 test_architecture_boundaries.py）留下的注入
變數，不在這裡 import，改由組裝根 app/main.py 啟動時注入真正的
app.orders.channel／dispatch／repository 模組。各主題檔要用時一律
`from app.ads import routes as ads_routes` 再即時查 `ads_routes.orders_repo`
等屬性——不能 `from app.ads.routes import orders_repo` 把名字靜態綁死，main.py
的注入發生在所有模組 import 完成之後，那樣綁到的值會永遠是 None。

背景進度引擎（`_progress_state`／`_PROGRESS_TIMEOUT_SECONDS` 等）留在本檔同一個
理由：test_ads_progress_background.py 直接改 `ads_routes._PROGRESS_TIMEOUT_SECONDS`
這個模組屬性來模擬逾時，這份狀態只能有一份、且要留在 `app.ads.routes` 這個路徑上；
各主題檔一律 `ads_routes.` 開頭即時查值呼叫，不搬進獨立檔案，理由相同。
"""

import threading
import time
from typing import Optional

from fastapi import APIRouter, Request

import app.shared.web as main_mod
from app.intake import state as intake_state
from app.ads.routes_common import _crumb

# 第 7 刀（A1 三層地界新規則：app/ads 不得 import app.orders，見
# test_architecture_boundaries.py）：orders_channel／orders_dispatch／orders_repo
# 不在這裡 import，改由組裝根 app/main.py 啟動時注入真正的
# app.orders.channel／dispatch／repository 模組。
orders_channel = None
orders_dispatch = None
orders_repo = None

router = APIRouter()

# 第 8 刀：首頁／歷期戰績／Meta·GA4 同步與回填／待認領／提醒收起，已搬進
# routes_sync.py。掛的位置沿用原本這批路由在檔案裡的相對順序——注意
# ads_cycle（下面 `GET /brands/{brand_id}/ads/{cycle_id}` 萬用路由）要在這批
# 之後掛，不然 "history"／"claims"／"ga4" 這些固定字會被萬用路由當成 cycle_id 吃掉。
from app.ads import routes_sync  # noqa: E402
router.include_router(routes_sync.router)


# 第 8 刀：Pixel／GA4 教學頁、資料與連線頁、把舊資料搬進來，已搬進
# routes_connections.py；前朝教訓訪談、累積智慧、規則卡決定，已搬進
# routes_interview.py。掛的位置同樣要在下面 ads_cycle 這條萬用路由之前
# （見 routes_sync.py 那段掛法註解，理由相同）。
from app.ads import routes_connections  # noqa: E402
from app.ads import routes_interview  # noqa: E402
router.include_router(routes_connections.router)
router.include_router(routes_interview.router)

# 第 8 刀：開新檔期、封存／刪除、檔期內頁（含 `GET /{cycle_id}` 這條萬用路由）、
# 打法規劃與選擇，已搬進 routes_plan.py。掛在這裡（sync／connections／interview
# 之後）——routes_plan.router 裡的萬用路由要在其他分支的固定字路徑之後才不會誤吃。
from app.ads import routes_plan  # noqa: E402
router.include_router(routes_plan.router)


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


# 第 8 刀：素材生成、反對／勾回、關卡二，已搬進 routes_creative.py；交接包、期別配碼、
# 投放授權、投放前檢查清單，已搬進 routes_handoff.py；成效頁、判讀、對帳、期中檢查點、
# CSV／手動匯入，已搬進 routes_performance.py。這三份都不含萬用路由，掛的順序不影響
# 比對結果，沿用原本檔案裡的相對順序。
from app.ads import routes_creative  # noqa: E402
from app.ads import routes_handoff  # noqa: E402
from app.ads import routes_performance  # noqa: E402
router.include_router(routes_creative.router)
router.include_router(routes_handoff.router)
router.include_router(routes_performance.router)

# 票 04-single-image-e2e：主題生成 JSON API，`/api/ads/...` 固定前綴，跟上面任何
# `/brands/{brand_id}/ads/{cycle_id}` 萬用路由都不會撞（前綴完全不同），掛的順序不影響。
from app.ads import routes_creative_theme  # noqa: E402
router.include_router(routes_creative_theme.router)

# 票 13-workbench-cards：素材工作檯任務卡衍生查詢，同樣固定 `/api/ads/...` 前綴，
# 掛在 routes_creative_theme 之後即可（GENERATORS 需要它先 import 完成）。
from app.ads import routes_workbench  # noqa: E402
router.include_router(routes_workbench.router)

# 票 01-quick-generate-endpoint：快速生成，固定 `/api/creative/...` 前綴（不落地，見該檔
# 檔頭），跟上面 `/api/ads/...` 前綴不會撞，掛的順序不影響。
from app.ads import routes_quick_generate  # noqa: E402
router.include_router(routes_quick_generate.router)

# 票 02-qa-reminder-reset：設定中心「廣告層面」詳細頁（規則卡＋上線前提醒），固定
# `/settings/ads` 前綴，跟上面任何 `/brands/{brand_id}/ads/...` 路由都不會撞，掛的順序
# 不影響。這頁本來在 app.brand_intelligence，搬過來的原因見該檔案頭註解。
from app.ads import routes_settings  # noqa: E402
router.include_router(routes_settings.router)

# 票 B4-campaigns／B4-warroom 接線：S7 檔期清單＋S8 檔期作戰室 JSON API，固定
# `/api/campaigns/...` 前綴，跟上面任何 `/brands/{brand_id}/ads/...` 頁面路由都不會撞。
# `routes_campaigns_list_api` 用字面 "brands" 這段（`/api/campaigns/brands/{brand_id}`），
# `routes_campaigns_open_api` 用通用兩段式萬用路由（`/api/campaigns/{brand_id}/{cycle_id}`）
# ——同樣是三段路徑，有真實品牌 id 恰好等於字面 "brands" 才會撞（理論上不會發生），
# list_api 仍必須排在 open_api 之前註冊，先到先贏（見兩檔各自檔頭說明）。
from app.ads import routes_campaigns_list_api  # noqa: E402
from app.ads import routes_campaigns_open_api  # noqa: E402
from app.ads import routes_campaigns_handoff_api  # noqa: E402
from app.ads import routes_campaigns_performance_api  # noqa: E402
from app.ads import routes_tracking_api  # noqa: E402
from app.ads import routes_weekly_proposals_api  # noqa: E402
router.include_router(routes_campaigns_list_api.router)
router.include_router(routes_campaigns_open_api.router)
router.include_router(routes_campaigns_handoff_api.router)
router.include_router(routes_campaigns_performance_api.router)
router.include_router(routes_tracking_api.router)
router.include_router(routes_weekly_proposals_api.router)
