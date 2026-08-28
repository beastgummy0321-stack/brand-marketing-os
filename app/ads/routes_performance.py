"""app/ads/routes_performance.py — 空殼（T4 廣告模組 Jinja 大清倉第 2 刀刪光本檔全部
路由：成效頁 `ads_performance_page`＋CSV／手動匯入兩個 POST——全部改直測業務層
`app/ads/performance.py`（`import_csv`／`import_manual`）或 `/api/campaigns/.../performance`
JSON 端點，見 test_ads_performance.py；判讀進度頁 `ads_reading_progress` 隨
`_render_wait_page`（app/ads/routes_progress.py）一併刪除，改直測 `app/ads/reading.py`
的 `run`／`finalize`，見 test_ads_weekly_proposal.py）。

router 沒有任何路徑，純為讓 `app/ads/routes.py` 既有 `from app.ads import
routes_performance` 這行 import 不必改（比照 routes_creative.py 的先例）。
"""

from fastapi import APIRouter

router = APIRouter()
