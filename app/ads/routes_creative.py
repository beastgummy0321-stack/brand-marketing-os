"""app/ads/routes_creative.py — 曾經是素材生成、反對／勾回、關卡二的舊頁（第 8 刀從
app/ads/routes.py 拆出）；T4 廣告模組 Jinja 大清倉全部路由都已刪除——生成流程改走
routes_creative_theme.py／routes_workbench.py 的新殼機制（`/api/ads/...`），反對／
勾回改走同一套元件層 reject（frontend/src/lib/workbenchApi.ts rejectComponent()）。

本檔只剩 `_CREATIVE_STAGES` 這個常數還留著：app/tests/test_ads_creative.py 直接
`from app.ads.routes_creative import _CREATIVE_STAGES` 拿去跟 `ads_routes._progress_
touch()` 搭配測「等待秒數不因重整歸零」——這個常數不屬於任何一支已刪的路由，是純資料，
不影響本票「刪 handler」的範圍，留著不刪。`router` 因此是空的（沒有任何路徑），
main.py 的 `include_router` 仍照掛，等同無操作。
"""

from fastapi import APIRouter

router = APIRouter()

_CREATIVE_STAGES = [
    ("prep", "整理這期的資料與素材規則"),
    ("ask_ai", "請 AI 生成素材"),
    ("save", "檢查與存檔"),
]


