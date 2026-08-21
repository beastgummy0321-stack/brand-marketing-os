# -*- coding: utf-8 -*-
"""app/ads/routes_sync.py — 空殼（T4 廣告模組 Jinja 大清倉第 2 刀刪光本檔僅剩的兩條路由
`ads_meta_backfill_progress`／`ads_ga4_backfill_progress`（Meta／GA4 回填精靈），隨
`_render_wait_page`（app/ads/routes_progress.py）一併刪除——已被
`/api/campaigns/brands/{brand_id}/backfill/meta`／`backfill/ga4`
（app/ads/routes_onboarding_api.py，資料上線 React 頁在用）取代，測試改直呼業務層
`app/ads/sync.py::sync_account`／`backfill_range`、`app/ads/ga4_sync.py::sync_brand`，
見 test_ads_backfill.py。

router 沒有任何路徑，純為讓 `app/ads/routes.py` 既有 `from app.ads import routes_sync`
這行 import 不必改（比照 routes_creative.py 的先例）。
"""

from fastapi import APIRouter

router = APIRouter()
