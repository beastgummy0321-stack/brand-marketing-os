# -*- coding: utf-8 -*-
"""app/ads/routes_creative.py — 素材生成、反對／勾回、關卡二（第 8 刀從
app/ads/routes.py 拆出）。純搬移，網址與行為不變。

本檔負責的頁：
- `/brands/{b}/ads/{cycle}/creatives`                    素材頁
- `/brands/{b}/ads/{cycle}/creatives/progress`           素材生成進度頁
- `/brands/{b}/ads/{cycle}/creatives/{id}/reject`        反對制：不要這個
- `/brands/{b}/ads/{cycle}/creatives/{id}/restore`       一鍵勾回
- `/brands/{b}/ads/{cycle}/creatives/restore-batch`      批次勾回
- `/brands/{b}/ads/{cycle}/creatives/approve`            關卡二：素材勾選

背景進度引擎留在 app/ads/routes.py，本檔的 ads_creatives_progress 一律
`ads_routes.` 開頭即時查值，理由見 routes_sync.py 檔頭說明。
"""

import time
from urllib.parse import quote
from typing import Optional

from fastapi import APIRouter, Form, Request

import app.shared.web as main_mod
from app.ads import compliance
from app.ads import creative as ads_creative
from app.ads import fingerprint
from app.ads import repository as ads_repo
from app.ads import routes as ads_routes
from app.ads.routes_common import _crumb, _cycle_progress_items, _cycle_view, _require_cycle
from app.llm import providers as llm_providers

router = APIRouter()

_CREATIVE_STAGES = [
    ("prep", "整理這期的資料與素材規則"),
    ("ask_ai", "請 AI 生成素材"),
    ("save", "檢查與存檔"),
]


@router.get("/brands/{brand_id}/ads/{cycle_id}/creatives")
async def ads_creatives(request: Request, brand_id: str, cycle_id: str):
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    cycle = _require_cycle(brand_id, cycle_id)
    groups = ads_creative.group_by_cell(conn, brand_id, cycle_id)

    # 法務掃描：每次進頁重掃，結果整批換掉——素材改寫過就該重算，不留舊結論
    if groups:
        ads_repo.replace_findings(conn, brand_id, cycle_id, "compliance",
                                  compliance.scan_cycle(conn, brand_id, cycle_id))
    flags = compliance.load_findings(conn, brand_id, cycle_id)
    # 修憲落地 L2：命中內建法規詞庫的素材，第一次被掃到時預設值翻成「已挑掉」
    # （決策 0034 第 25 條）。只在從未被決定過時才寫，不會把使用者剛按過的「勾回」蓋回去；
    # 這次真的寫了新決定，groups 要重讀一次才會反映在畫面上。
    if flags and compliance.apply_default_holds(conn, brand_id, cycle_id, flags,
                                                 compliance.AUTO_HOLD_ACTOR):
        groups = ads_creative.group_by_cell(conn, brand_id, cycle_id)
    auto_held_count = sum(1 for g in groups for v in g["variants"] if v["auto_held"])
    # 這批素材是否在方法論資料缺席的情況下生成——每則變體都存了同一份清單，取第一則即可。
    methodology_missing = next(
        (v["methodology_missing"] for g in groups for v in g["variants"] if v["methodology_missing"]),
        [],
    )
    # 補打一次仍缺的素材型別（票 30）——每則變體都存了同一份清單，取第一則即可；
    # 轉成人話標籤給頁面顯示，不在模板裡做型別對照。
    missing_creative_types = next(
        (v["missing_creative_types"] for g in groups for v in g["variants"]
         if v["missing_creative_types"]),
        [],
    )
    missing_creative_type_labels = [ads_creative.VARIANT_LABELS.get(t, t)
                                    for t in missing_creative_types]
    # 這批素材生成時顧客原話語料庫是否有內容——每則變體都存了同一個值，取第一則即可
    # （票 7，決策 0023 第 18a 點：語料庫空時照樣生成，頁面誠實標注）。
    customer_voice_available = next(
        (v["customer_voice_available"] for g in groups for v in g["variants"]), True,
    )

    return main_mod.templates.TemplateResponse(
        request, "ads_creatives.html",
        main_mod.ctx(request, brand=brand, nav_current='ads', cycle=_cycle_view(conn, brand_id, cycle),
                     groups=groups, flags=flags, methodology_missing=methodology_missing,
                     missing_creative_type_labels=missing_creative_type_labels,
                     customer_voice_available=customer_voice_available,
                     compliance_note=compliance.SCAN_LIMITS_NOTE,
                     coverage_gaps=compliance.coverage_gaps(conn, brand_id),
                     flagged_count=sum(len(v) for v in flags.values()),
                     reject_reasons=fingerprint.REJECT_REASONS,
                     auto_held_count=auto_held_count,
                     show_batch_restore=auto_held_count >= ads_creative.BATCH_RESTORE_THRESHOLD,
                     kept=sum(1 for g in groups for v in g["variants"] if not v["rejected"]),
                     stage_items=_cycle_progress_items(conn, brand_id, cycle),
                     breadcrumb_items=_crumb(brand, (f"{cycle['start_date']} 檔期",
                                                     f"/brands/{brand_id}/ads/{cycle_id}")),
                     **main_mod.banner_ctx(request)),
    )


@router.get("/brands/{brand_id}/ads/{cycle_id}/creatives/progress")
def ads_creatives_progress(request: Request, brand_id: str, cycle_id: str,
                           run: Optional[str] = None,
                           model: Optional[str] = None, thinking: Optional[str] = None):
    """model／thinking：生成按鈕旁「本次會用」選單的當場覆寫（票 #27），見
    ads_plan_progress 同一參數的說明——只在真的生成那一次套用，不落資料庫。

    修憲落地 M3：生成丟背景執行緒跑，見 ads_plan_progress 同一套背景執行／冪等閘／
    逾時說明，這裡不重複。
    """
    brand = main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    result_url = f"/brands/{brand_id}/ads/{cycle_id}/creatives"
    leave_url = f"/brands/{brand_id}/ads/{cycle_id}"
    progress_key = ads_routes._progress_key("creative", brand_id, cycle_id)

    if run != "1":
        entry = ads_routes._progress_touch(progress_key, _CREATIVE_STAGES)
        run_url = f"{request.url.path}?run=1"
        if model:
            run_url += f"&model={quote(model)}"
        if thinking:
            run_url += f"&thinking={quote(thinking)}"
        return ads_routes._render_wait_page(
            request, brand, heading="正在做這期的素材", lede="", run_url=run_url,
            leave_url=leave_url, breadcrumb_tail="做素材中",
            progress_rows=ads_routes._progress_definition_rows(_CREATIVE_STAGES, "creative", entry))

    def work(on_stage):
        with llm_providers.request_overrides(model=model, thinking=thinking):
            return ads_creative.generate(main_mod.conn, brand_id, cycle_id, actor,
                                         on_stage=on_stage)

    entry = ads_routes._progress_start(progress_key, _CREATIVE_STAGES, work)

    if entry["status"] != "done":
        if time.time() - entry["started_at"] > ads_routes._PROGRESS_TIMEOUT_SECONDS:
            ads_routes._progress_clear(progress_key)
            return main_mod.redirect_with_message(
                leave_url, "AI 這次沒有在時間內回應。你的資料都還在，沒有掉。"
                          "可以再試一次，或先跳過這一步。", kind="warn")
        return ads_routes._render_wait_page(
            request, brand, heading="正在做這期的素材", lede="",
            run_url=f"{request.url.path}?run=1", leave_url=leave_url,
            breadcrumb_tail="做素材中",
            progress_rows=ads_routes._progress_definition_rows(_CREATIVE_STAGES, "creative", entry))

    outcome_kind, payload = entry["result"]
    ads_routes._progress_clear(progress_key)
    if outcome_kind == "error":
        return main_mod.redirect_with_message(leave_url, payload, kind="warn")
    ok, err = payload
    if not ok:
        return main_mod.redirect_with_message(leave_url, err, kind="warn")
    return main_mod.redirect_with_message(
        result_url, "素材好了。預設全部採用，把不要的挑掉就行。")


@router.post("/brands/{brand_id}/ads/{cycle_id}/creatives/{variant_id}/reject")
async def ads_creative_reject(request: Request, brand_id: str, cycle_id: str, variant_id: str,
                              reason_code: str = Form(""), reason_text: str = Form("")):
    """反對制的「不要這個」：記下結構化理由，當場改寫一版放回原位。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    back = f"/brands/{brand_id}/ads/{cycle_id}/creatives"

    try:
        variant = ads_creative.reject(main_mod.conn, brand_id, variant_id,
                                      reason_code=reason_code, reason_text=reason_text,
                                      actor=actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(back, str(exc), kind="warn")

    learned = ads_creative.learned_message(reason_code, variant["fingerprint"])
    ok, _ = ads_creative.rewrite(main_mod.conn, brand_id, variant_id,
                                 reason_code=reason_code, actor=actor)
    if not ok:
        return main_mod.redirect_with_message(
            back, f"{learned}（這次沒能馬上改寫出替代版本，你可以再產一次素材。）", kind="warn")
    return main_mod.redirect_with_message(back, f"{learned}已經改寫一版放在原本的位置。")


@router.post("/brands/{brand_id}/ads/{cycle_id}/creatives/{variant_id}/restore")
async def ads_creative_restore(request: Request, brand_id: str, cycle_id: str, variant_id: str):
    """一鍵勾回：把系統依法規掃描自動預設挑掉的素材改回採用（修憲落地 L2，決策 0034 第 25 條）。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    back = f"/brands/{brand_id}/ads/{cycle_id}/creatives"
    try:
        ads_creative.restore(main_mod.conn, brand_id, variant_id, actor=actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(back, str(exc), kind="warn")
    return main_mod.redirect_with_message(back, "已經勾回，這則會採用。")


@router.post("/brands/{brand_id}/ads/{cycle_id}/creatives/restore-batch")
async def ads_creative_restore_batch(request: Request, brand_id: str, cycle_id: str):
    """批次一鍵：把這期所有系統自動預設挑掉的素材一次勾回（決策 0034 第 25 條第 3 點）。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    back = f"/brands/{brand_id}/ads/{cycle_id}/creatives"
    restored = ads_creative.restore_all_auto_held(main_mod.conn, brand_id, cycle_id, actor=actor)
    if restored == 0:
        return main_mod.redirect_with_message(back, "目前沒有系統自動挑掉的素材可以勾回。",
                                              kind="warn")
    return main_mod.redirect_with_message(back, f"已經勾回 {restored} 則，都會採用。")


@router.post("/brands/{brand_id}/ads/{cycle_id}/creatives/approve")
async def ads_creatives_approve(request: Request, brand_id: str, cycle_id: str):
    """關卡二：素材勾選。反對制——沒被挑掉的就是採用，零操作也能過關。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    adopted = ads_creative.approve_selection(main_mod.conn, brand_id, cycle_id, actor)
    if adopted == 0:
        return main_mod.redirect_with_message(
            f"/brands/{brand_id}/ads/{cycle_id}/creatives",
            "這期所有素材都被挑掉了，先產一批新的再繼續。", kind="warn")
    return main_mod.redirect_with_message(
        f"/brands/{brand_id}/ads/{cycle_id}",
        f"採用了 {adopted} 則素材，接下來準備投放交接包。")


