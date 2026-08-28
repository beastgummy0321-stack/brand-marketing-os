"""app/ads/routes_plan.py — 空殼（T4 廣告模組 Jinja 大清倉第 2 刀刪光本檔唯一的路由
`ads_plan_progress` 打法生成進度頁，隨 `_render_wait_page`（app/ads/routes_progress.py）
一併刪除——已被 `/api/campaigns/{brand_id}/{cycle_id}/plan/generate`＋`/plan/status`
（app/ads/routes_campaigns_open_api.py）取代，同一套 `_progress_state` 背景引擎，只是
「轉址＋帶訊息」換成「JSON 狀態＋人話訊息」，測試改打這兩個 /api 端點，見
test_ads_progress_background.py。

router 沒有任何路徑，純為讓 `app/ads/routes.py` 既有 `from app.ads import routes_plan`
這行 import 不必改（比照 routes_creative.py 的先例）。
"""

from fastapi import APIRouter

router = APIRouter()
