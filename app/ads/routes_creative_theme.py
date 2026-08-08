# -*- coding: utf-8 -*-
"""app/ads/routes_creative_theme.py — 主題生成 JSON API（票 04-single-image-e2e）。

新殼專用：`/api/ads/...` 前綴，比照 app/dashboard/routes.py 的 JSON 慣例——回應本身就是
最終結果，不是舊流程那種「等待頁、meta refresh 輪詢、完成才轉址」。跟舊的
`/brands/{b}/ads/{c}/creatives` 素材頁（HTML 表單）並存、互不干擾：舊生成路徑一行不動，
這裡是矩陣頁（畫面契約畫面 2、3）要打的第二條路（票 04 驗收 8）。

路由收請求 → 組簡報（brief_assembler）→ 引擎產主題（theme_engine）→ 存主題＋元件 → 回
JSON（票 04 What to build 原文，逐段對應下面 generate_theme() 的四行）。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import app.shared.web as main_mod
from app.ads import brief_assembler
from app.ads import theme_engine
from app.ads import theme_engine_video
from app.ads import theme_repository as theme_repo
from app.ads.routes_common import _require_cycle
from app.core import creative_assets

router = APIRouter(prefix="/api/ads")

# 格式 key → 生成函式：theme_engine.GENERATORS（單圖／輪播）＋ video（票 08，獨立成檔的理由
# 見 app/ads/theme_engine_video.py 檔頭——theme_engine.py 逼近 800 行上限，不能再加）。
# 在這裡合併而不是讓 theme_engine.py 匯入 theme_engine_video 回頭註冊，是為了不讓兩檔互相
# import（theme_engine_video 已經單向 import theme_engine，反過來會形成循環 import）。
GENERATORS = {**theme_engine.GENERATORS, "video": theme_engine_video.generate_video_theme}


@router.post("/brands/{brand_id}/ads/{cycle_id}/cells/{cell_id}/formats/{format_key}/themes")
async def generate_theme(request: Request, brand_id: str, cycle_id: str, cell_id: str,
                         format_key: str):
    """「生成一個主題」：矩陣頁灰卡按下去打這支。品牌／檔期查無此 id 沿用既有 404（HTML，
    跟其餘路由一致，dashboard JSON API 也是同一套，見 test_dashboard_cockpit.py）；切角格
    查無此 id、格式不支援、計畫未核准、AI 失敗——這些是使用者操作或環境會真的碰到的狀態，
    一律回 JSON 錯誤訊息，不是頁面等級的 404／500。
    """
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    conn = main_mod.conn

    generator = GENERATORS.get(format_key)
    if generator is None:
        return JSONResponse(
            {"error": f"這個格式（{format_key}）的生成引擎還沒做。"}, status_code=400)

    try:
        brief, err = brief_assembler.assemble_brief(
            conn, brand_id, cycle_id, cell_id, format_key, theme_count=1, actor=actor)
        if err:
            return JSONResponse({"error": err}, status_code=409)

        generated, err = generator(conn, brief, actor=actor)
        if err:
            # 花費超上限與 AI 沒能產出可用內容都是「這次沒能生出主題，理由如下」，
            # 用同一個狀態碼（422）——跟純輸入錯誤（400）、計畫未核准（409）分開即可，
            # 不必為兩種「引擎沒能產出」再細分狀態碼。
            return JSONResponse({"error": err}, status_code=422)

        theme = theme_engine.save_generated_theme(conn, brief, generated, actor=actor)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    return {"theme": theme}


@router.post("/brands/{brand_id}/ads/{cycle_id}/themes/{theme_id}/folder")
async def open_theme_folder(request: Request, brand_id: str, cycle_id: str, theme_id: str):
    """開這個主題的素材資料夾：沿用既有 os.startfile 先例（app/core/creative_assets.py，
    決策 0008），票 04 驗收 6。"""
    main_mod.require_brand(brand_id)
    _require_cycle(brand_id, cycle_id)
    conn = main_mod.conn
    theme = theme_repo.get_theme(conn, brand_id, theme_id)
    if theme is None or theme["campaign_cycle_id"] != cycle_id:
        raise main_mod.NotFoundKind("主題")
    path = creative_assets.open_folder(
        conn, brand_id, cycle_id, theme_engine.theme_folder_name(theme))
    return {"folder_path": str(path)}
