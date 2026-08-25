# -*- coding: utf-8 -*-
"""app/brand_web/routes.py — 品牌智庫舊版 Jinja handler 的最後殘留（T4 步驟 1，2026-08-22）。

原本 87 條路由的大檔，經多輪拆分＋T4 刪光純頁面渲染部分後，只剩極少數東西还留在這裡：

1. 素材檔案服務 `GET /brands/{brand_id}/assets/file/{asset_id}/{filename}`
   （`FileResponse`，不是頁面渲染，前端 `<img>`／下載連結還在直接打這支，必留）。
2. 品牌報告生成的相容轉接層 `generate()` / `PROVIDER` / `SECTION_KEYS`——
   `app/tests/test_brand_report.py` 還在對這幾個名字打 `mock.patch`，實際邏輯早搬到
   `report_service.py`，這裡只保留呼叫點與名字。
3. `_create_source_ref` / `_persona_conversion_goal_default`——`app/brand_web/routes_library_write.py`
   與 `routes_products.py` 兩個新版 `/api` 檔案 import 這兩支小工具，不重複維護第二份。

T4 步驟 1 刪掉的東西：7 支 GET 頁（`brand_menu`／六支 `hub_*`）＋它們的表單 POST
handler（品牌編輯、品牌事實／限制規則／宣稱新增改刪確認、官方素材刪除、自有渠道
新增、顧客原話封存刪除）。刪除理由：`frontend/src/lib/libraryApi.ts` 已經全部改打
`/api/library/brands/{id}/...`（`routes_library_write.py`），不再依賴這裡的舊表單
POST 端點與它們 303 redirect 落地用的 GET 頁。

也一併刪掉 `POST /interrupts/{id}/resolve`——`app/brand_web/routes_inbox.py` 的
`POST /api/interrupts/{id}/resolve` 才是現在唯一的呼叫點（`frontend/src/lib/api.ts`
`resolveAlert()`），舊版 HTML 端點沒人在用了。`app/tests/test_inbox_api.py` 已改打
`/api` 版本。
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from app.core import vocab as md
from app.brand_intelligence import report as brand_report_mod
from app.brand_intelligence import repository as repo
from app.shared import web
from app.shared.web import NotFoundKind, clean, require_brand
from app.brand_web import report_service

router = APIRouter()

PROVIDER = report_service.PROVIDER
SECTION_KEYS = brand_report_mod.SECTION_KEYS


def generate(conn, brand_id: str, actor: str) -> tuple:
    """保留舊頁測試的 provider 注入點，實際生成邏輯已搬至 report_service。"""
    return report_service.generate(conn, brand_id, actor, provider=PROVIDER)


# ---------------------------------------------------------------------------
# 小工具：`routes_library_write.py` / `routes_products.py` 還在用，不重複維護第二份。
# ---------------------------------------------------------------------------

def _create_source_ref(brand_id: str, actor: str, text: str) -> Optional[str]:
    """使用者填的「資料來源」自由文字 -> source_reference 表一筆列的 id；空字串回 None。"""
    text = clean(text)
    if not text:
        return None
    row = repo.create_source_reference(
        web.conn, brand_id, actor=actor, title=text, source_type="other",
        captured_date=datetime.now(timezone.utc).date(),
    )
    return row["id"]


def _persona_conversion_goal_default(persona: str) -> Optional[str]:
    """人設沒填 conversion_goal 時的預設值：從既有的 persona_switch_defaults() 開關表
    推回轉換目標，不另外發明第二張人設對照表。推法對齊
    repo.compute_methodology_switches() 對「站內交易」的定義本身就是
    conversion_goal == 'purchase'：站內交易開＝purchase；沒有站內交易但有自有網站
    （服務／預約制）＝booking；兩者都沒有（KOL／其他）＝awareness。"""
    if persona not in md.PERSONA_SWITCH_DEFAULTS:
        return None
    switches = md.persona_switch_defaults(persona)
    if switches["站內交易"]:
        return "purchase"
    if switches["有自有網站"]:
        return "booking"
    return "awareness"


# ---------------------------------------------------------------------------
# 官方素材檔案服務（issue #3）：上傳／刪除都已改走 /api（routes_library.py／
# routes_library_write.py），這支 FileResponse 不是頁面渲染，必留。
# ---------------------------------------------------------------------------

_ASSET_CONTENT_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                         "webp": "image/webp", "gif": "image/gif"}


@router.get("/brands/{brand_id}/assets/file/{asset_id}/{filename}")
async def asset_file(request: Request, brand_id: str, asset_id: str, filename: str):
    """只回傳「這筆官方素材登記過的檔案」——不從網址參數直接組路徑，天生擋掉路徑穿越；
    找不到品牌、找不到素材、或檔名跟登記的不一致，一律 404（比照 intake 照片的做法）。"""
    require_brand(brand_id)
    asset = repo.get_official_asset(web.conn, brand_id, asset_id)
    if asset is None or Path(asset["file_path"]).name != filename:
        raise NotFoundKind("這個素材檔案")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return FileResponse(asset["file_path"], media_type=_ASSET_CONTENT_TYPES.get(ext, "application/octet-stream"),
                         filename=filename)
