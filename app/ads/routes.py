# -*- coding: utf-8 -*-
"""app/ads/routes.py — 廣告分支的頁面路由（匯總檔）。

T4 廣告模組 Jinja 大清倉：舊頁 66 實頁已被 React 新殼取代，本票刪掉 25 處
TemplateResponse handler（連同只服務這些舊頁表單的 POST handler）。routes_connections.py
／routes_handoff.py／routes_interview.py 三個主題檔的路由全數被 /api 等價端點取代、
測試與 React 都不再打舊路徑，整檔清空後跟著這一刀一併刪除。

本檔現在只剩兩件事：

1. 持有跨模組注入變數（`orders_channel`／`orders_dispatch`／`orders_repo`）——理由見
   下方說明，這份狀態會被 main.py 或測試在 import 之後動態改值，只能留在這個模組路徑上。
   背景進度引擎（`_progress_state` 等）已搬到 app/ads/routes_progress.py，這裡原樣
   `from ... import` 回來，讓既有 `ads_routes._progress_key(...)` 等呼叫慣例與測試對
   `ads_routes._PROGRESS_TIMEOUT_SECONDS` 之類的模組屬性覆寫不必改一行（見
   routes_progress.py 檔頭的完整理由）。
2. 依序 `include_router()` 掛上各主題檔的 router，組成同一個 `router` 物件，讓
   app/main.py 既有的 `from app.ads.routes import router` 這行 import 完全不必改。

各主題檔開頭都有自己負責哪些頁（或 /api 端點）的清單：

- routes_common.py       共用小工具：麵包屑、檔期讀取、五格進度軌等各檔都要用的函式
- routes_progress.py     背景進度引擎（等待頁共用渲染 `_render_wait_page` 已隨大清倉
                          第 2 刀刪除，改走各自的 /api 端點）
- routes_sync.py         空殼（Meta／GA4 回填精靈已隨大清倉第 2 刀刪除，改走
                          routes_onboarding_api.py 的 /api 端點）
- routes_plan.py         空殼（打法生成進度頁已隨大清倉第 2 刀刪除，改走
                          routes_campaigns_open_api.py 的 plan/generate＋plan/status）
- routes_creative.py     `_CREATIVE_STAGES`（供測試 import；生成流程已隨 T4 刪除，改走
                          routes_creative_theme.py／routes_workbench.py 的新殼機制）
- routes_performance.py  空殼（成效頁、CSV／手動匯入、判讀進度頁已隨大清倉第 2 刀刪除）
- routes_settings.py     設定中心「廣告層面」規則卡／節日提醒 /api 端點（Jinja 舊頁已刪）

`orders_channel`／`orders_dispatch`／`orders_repo`：第 7 刀（A1 三層地界新規則：
app/ads 不得 import app.orders，見 test_architecture_boundaries.py）留下的注入
變數，不在這裡 import，改由組裝根 app/main.py 啟動時注入真正的
app.orders.channel／dispatch／repository 模組。各主題檔要用時一律
`from app.ads import routes as ads_routes` 再即時查 `ads_routes.orders_repo`
等屬性——不能 `from app.ads.routes import orders_repo` 把名字靜態綁死，main.py
的注入發生在所有模組 import 完成之後，那樣綁到的值會永遠是 None。
"""

from fastapi import APIRouter

from app.ads.routes_progress import (  # noqa: F401 — 原樣接回去給 `ads_routes.` 這套慣例用
    _progress_state, _progress_lock, _USUAL_RANGE, _PROGRESS_TIMEOUT_SECONDS,
    _progress_key, _progress_touch, _progress_start, _progress_run,
    _progress_set_stage, _progress_clear, _progress_fail, _progress_definition_rows,
)

# 第 7 刀（A1 三層地界新規則：app/ads 不得 import app.orders，見
# test_architecture_boundaries.py）：orders_channel／orders_dispatch／orders_repo
# 不在這裡 import，改由組裝根 app/main.py 啟動時注入真正的
# app.orders.channel／dispatch／repository 模組。
orders_channel = None
orders_dispatch = None
orders_repo = None

router = APIRouter()

# T4 廣告模組 Jinja 大清倉第 2 刀：routes_sync.py 僅剩的 Meta／GA4 回填精靈也已刪除
# （改走 routes_onboarding_api.py 的 /api 端點），router 空殼，include_router 保留純為
# import 路徑不必改（比照 routes_creative.py 的先例）。
from app.ads import routes_sync  # noqa: E402
router.include_router(routes_sync.router)

# T4：routes_connections.py（Pixel／GA4 教學頁、資料與連線頁、萬用匯入、把舊資料搬進來）
# 與 routes_interview.py（前朝教訓訪談、累積智慧、規則卡決定）全部路由都已被 /api 等價
# 端點取代，整檔清空後隨這一刀一併刪除，這裡不再 include_router。

# T4 第 2 刀：routes_plan.py 僅剩的打法生成進度頁 `ads_plan_progress` 也已刪除（改走
# routes_campaigns_open_api.py 的 plan/generate＋plan/status），router 空殼。
from app.ads import routes_plan  # noqa: E402
router.include_router(routes_plan.router)

# T4：素材生成流程改走 routes_creative_theme.py／routes_workbench.py 的新殼機制，
# routes_creative.py 只剩 `_CREATIVE_STAGES`（test_ads_creative.py 直接 import）留著，
# 路由清空（router 沒有任何路徑），純為保留這個 import 路徑，不刪檔。交接包／期別配碼／
# 投放授權／投放前檢查清單（routes_handoff.py）全部路由都已被 /api 等價端點取代，整檔
# 清空後隨這一刀一併刪除，不再 include_router。T4 第 2 刀：routes_performance.py 僅剩的
# 成效頁、CSV／手動匯入、判讀進度頁也已刪除（改直測 app/ads/performance.py／reading.py
# 業務函式或 /api/campaigns/.../performance 端點），router 空殼。
from app.ads import routes_creative  # noqa: E402
from app.ads import routes_performance  # noqa: E402
router.include_router(routes_creative.router)
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
from app.ads import routes_campaigns_delivery_api  # noqa: E402
from app.ads import routes_campaigns_performance_api  # noqa: E402
from app.ads import routes_tracking_api  # noqa: E402
from app.ads import routes_weekly_proposals_api  # noqa: E402
router.include_router(routes_campaigns_list_api.router)
router.include_router(routes_campaigns_open_api.router)
router.include_router(routes_campaigns_handoff_api.router)
router.include_router(routes_campaigns_delivery_api.router)
router.include_router(routes_campaigns_performance_api.router)
router.include_router(routes_tracking_api.router)
router.include_router(routes_weekly_proposals_api.router)
