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
from app.ads import theme_attribution
from app.ads import theme_engine
from app.ads import theme_engine_video
from app.ads import theme_repository as theme_repo
from app.ads.routes_common import _require_cycle
from app.core import creative_assets
from app.core import settings as coresettings
from app.creative.format_specs import FORMAT_SPECS
from app.llm import pricing, providers

router = APIRouter(prefix="/api/ads")

# 圖片提示詞的元件型別（票 11-copy-flows）：只有這兩種算「整組複製」的內容，文案／標題／
# 說明一律不進去（ADR 0008 三「主要文案／標題／說明不進整組複製」）；影片格式沒有圖片提示詞
# 元件型別，天然被排除，不必為它另寫判斷分支。
IMAGE_PROMPT_COMPONENT_TYPES = ("image_prompt", "card_image_prompt")

# 外部生圖工具單次貼上的上限（ADR 0008 三：「一組上限 10 則（外部生圖工具單次上限）」）。
IMAGE_PROMPT_BATCH_SIZE = 10

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


@router.get("/brands/{brand_id}/ads/{cycle_id}/matrix")
async def theme_matrix(request: Request, brand_id: str, cycle_id: str):
    """矩陣資料端點（票 09-preselect-autogen 驗收 3）：列＝切角格、欄＝格式，全展開一格
    不藏（C.3）——即使某格從沒生成過，回應仍列出該格式欄，值是空灰卡的樣子，不是整欄消失。

    每格三態之一：
    - `themed`：已經有主題，附主題摘要（給矩陣頁小卡＋側板連結用）。
    - `empty`：灰卡，附這個格式生一次的預估費用（沿用跟引擎內部相同的
      `pricing.cost_ceiling` 算法，不是另外編一個數字）。
    - `generating`：目前恆不出現——本票只做批次與矩陣資料，背景執行緒＋輪詢屬前端包範圍
      （見 app/ads/theme_engine.py on_stage 註解），這裡先把 state 留成一個開放列舉，
      前端包接上背景執行緒後，值改成看得到 generating 也不必動這支路由的回應形狀。
    """
    main_mod.require_brand(brand_id)
    _require_cycle(brand_id, cycle_id)
    conn = main_mod.conn

    cells = [dict(r) for r in conn.execute(
        "SELECT * FROM experiment_cell WHERE brand_id = ? AND campaign_cycle_id = ?"
        " ORDER BY id", (brand_id, cycle_id))]
    model = providers.resolve_model(task_type="creative_theme", conn=conn)
    estimated_cost = pricing.cost_ceiling(model, theme_engine.THEME_MAX_TOKENS)

    rows = []
    for cell in cells:
        themes_by_format: dict = {}
        for theme in theme_repo.list_themes_for_cell(conn, brand_id, cell["id"]):
            themes_by_format.setdefault(theme["format_key"], []).append(theme)

        formats = {}
        for format_key in GENERATORS:
            themes = themes_by_format.get(format_key, [])
            if themes:
                formats[format_key] = {
                    "state": "themed",
                    "themes": [{"id": t["id"], "name": t["name"], "status": t["status"]}
                              for t in themes],
                }
            else:
                formats[format_key] = {"state": "empty", "estimated_cost": estimated_cost}
        rows.append({"experiment_cell_id": cell["id"], "creative_angle": cell["creative_angle"],
                    "formats": formats})

    return {"cells": rows}


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


@router.get("/brands/{brand_id}/ads/{cycle_id}/themes/{theme_id}/components/performance")
async def theme_component_performance(request: Request, brand_id: str, cycle_id: str,
                                      theme_id: str):
    """元件層相對排名（票 12-attribution-adjust 驗收 4）：同一則廣告裡 body／title／
    description 誰贏誰輸，只回排名所需的比較用資料，不提供絕對值對帳介面（ADR 0008 二）。"""
    main_mod.require_brand(brand_id)
    _require_cycle(brand_id, cycle_id)
    conn = main_mod.conn
    theme = theme_repo.get_theme(conn, brand_id, theme_id)
    if theme is None or theme["campaign_cycle_id"] != cycle_id:
        raise main_mod.NotFoundKind("主題")
    return {"components": theme_attribution.rank_theme_components(conn, brand_id, theme_id)}


@router.post("/brands/{brand_id}/ads/{cycle_id}/themes/{theme_id}/adopt")
async def adopt_theme(request: Request, brand_id: str, cycle_id: str, theme_id: str):
    """一鍵採用整個主題（票 10-adopt-reject AC1）：主 CTA 只有這一顆，沒有逐欄位勾選採用。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    conn = main_mod.conn
    theme = theme_repo.get_theme(conn, brand_id, theme_id)
    if theme is None or theme["campaign_cycle_id"] != cycle_id:
        raise main_mod.NotFoundKind("主題")
    theme = theme_repo.adopt_theme(conn, brand_id, theme_id, actor=actor)
    return {"theme": theme}


@router.post("/brands/{brand_id}/ads/{cycle_id}/components/{component_id}/reject")
async def reject_theme_component(request: Request, brand_id: str, cycle_id: str,
                                 component_id: str):
    """單一元件退件＋理由（票 10-adopt-reject AC2）：理由碼沿用 app/ads/fingerprint.py
    既有的 REJECT_REASON_LABELS 清單，不新造；退件只除名這一則，不影響同主題其他元件。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    conn = main_mod.conn
    component = theme_repo.get_component(conn, brand_id, component_id)
    if component is None or component["campaign_cycle_id"] != cycle_id:
        raise main_mod.NotFoundKind("這則素材")

    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"error": "請求格式不是合法的 JSON"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "請求格式不是合法的 JSON"}, status_code=400)

    try:
        component = theme_repo.reject_component(
            conn, brand_id, component_id, reason_code=body.get("reason_code", ""),
            reason_text=body.get("reason_text"), actor=actor)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return {"component": component}


# ---------------------------------------------------------------------------
# 複製流程（票 11-copy-flows；ADR 0008 三）：整組複製圖片提示詞（開頭＋尺寸張數行＋提示詞，
# 一組上限 10 超過拆 10＋N）＋文字元件逐則純內容端點。前端純圖示複製鈕屬前端包範圍，
# 這裡只提供內容，不碰剪貼簿。
# ---------------------------------------------------------------------------

def _theme_image_prompts(theme: dict) -> list:
    """依序取出這個主題裡算「圖片提示詞」的元件內容（單圖：image_prompt；輪播：依卡序排列
    的 card_image_prompt；影片沒有這兩種元件型別，天然回空 list）。"""
    return [c["content"] for c in theme["components"]
            if c["component_type"] in IMAGE_PROMPT_COMPONENT_TYPES]


def _prompt_copy_groups(theme: dict, header: str) -> list:
    """整組複製內容：自訂開頭 ＋ 尺寸張數行（照該主題格式從規格表帶）＋ 該組提示詞，
    一組上限 IMAGE_PROMPT_BATCH_SIZE、超過拆成 10＋N 組（ADR 0008 三）。"""
    prompts = _theme_image_prompts(theme)
    ratio = FORMAT_SPECS[theme["format_key"]]["ratio"]
    width, height = FORMAT_SPECS[theme["format_key"]]["pixels"]
    groups = []
    for start in range(0, len(prompts), IMAGE_PROMPT_BATCH_SIZE):
        chunk = prompts[start:start + IMAGE_PROMPT_BATCH_SIZE]
        size_line = f"尺寸 {width}×{height}（{ratio}）｜本組共 {len(chunk)} 張"
        lines = [line for line in (header, size_line) if line] + chunk
        groups.append({"content": "\n\n".join(lines), "count": len(chunk)})
    return groups


@router.get("/brands/{brand_id}/ads/{cycle_id}/themes/{theme_id}/image-prompts/copy")
async def copy_theme_image_prompts(request: Request, brand_id: str, cycle_id: str,
                                   theme_id: str):
    """整組複製端點（票 11 AC2／AC3）：回這個主題全部圖片提示詞，已依自訂開頭＋尺寸張數行
    組好、按 10 則拆組。沒有任何圖片提示詞元件（例如影片格式）時回人話錯誤，不回空陣列——
    呼叫端不必自己判斷「空陣列代表什麼」。"""
    main_mod.require_brand(brand_id)
    _require_cycle(brand_id, cycle_id)
    conn = main_mod.conn
    theme = theme_repo.get_theme(conn, brand_id, theme_id)
    if theme is None or theme["campaign_cycle_id"] != cycle_id:
        raise main_mod.NotFoundKind("主題")
    if not _theme_image_prompts(theme):
        return JSONResponse(
            {"error": "這個主題沒有圖片提示詞可以複製。"}, status_code=400)

    header = coresettings.get_setting(conn, coresettings.IMAGE_PROMPT_HEADER_SETTING, "") or ""
    return {"groups": _prompt_copy_groups(theme, header.strip())}


@router.get("/brands/{brand_id}/ads/{cycle_id}/components/{component_id}/copy")
async def copy_theme_component(request: Request, brand_id: str, cycle_id: str,
                               component_id: str):
    """逐則內容端點（票 11 AC4）：文案／標題／說明等文字元件各一顆純圖示複製鈕要打這支，
    回該則純內容，不夾任何裝飾文字或前後綴——貼上 Meta 後台要能直接一格一格用。"""
    main_mod.require_brand(brand_id)
    _require_cycle(brand_id, cycle_id)
    conn = main_mod.conn
    component = theme_repo.get_component(conn, brand_id, component_id)
    if component is None or component["campaign_cycle_id"] != cycle_id:
        raise main_mod.NotFoundKind("這則素材")
    return {"content": component["content"]}
