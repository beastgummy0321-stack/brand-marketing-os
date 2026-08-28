"""app/ads/routes_campaigns_handoff_api.py — S8 交接＋期中檢查點 JSON API（票 B4-warroom
接線，契約 `.scratch/grill/GRILL-B4-warroom.md`＋`GRILL-B4R-performance.md`，型別逐欄對照
`frontend/src/lib/warroomApi.ts`）。

對外進入點：本檔的 `router`。誰依賴它：只有 `app/ads/routes.py`。
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Request

import app.shared.web as main_mod
from app.ads import checklist as ads_checklist
from app.ads import checkpoint as ads_checkpoint
from app.ads import codes as ads_codes
from app.ads import handoff as ads_handoff
from app.ads import meta_mcp, qa_autocheck
from app.ads.routes_common import _require_cycle
from app.shared.web import JSONResponse

router = APIRouter()

_KIND_LABEL_TO_TS = {"ad": "ad", "word_of_mouth": "voiceover"}


def _envelope(data) -> dict:
    return {"data": data, "generated_at": datetime.now(UTC).isoformat()}


def _error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


async def _json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


# ---- 投放前檢查清單（S8.25-27） ----

@router.get("/api/campaigns/{brand_id}/{cycle_id}/checklist")
async def checklist_get(brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    conn = main_mod.conn
    _require_cycle(brand_id, cycle_id)
    items = ads_checklist.one_time_status(conn, brand_id) + ads_checklist.cycle_status(conn, brand_id, cycle_id)
    return _envelope(items)


@router.post("/api/campaigns/{brand_id}/{cycle_id}/checklist/{scope}/{item_key}")
async def checklist_toggle(request: Request, brand_id: str, cycle_id: str, scope: str, item_key: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    conn = main_mod.conn
    _require_cycle(brand_id, cycle_id)
    try:
        if scope == "one-time":
            current = next((i for i in ads_checklist.one_time_status(conn, brand_id) if i["key"] == item_key), None)
            if current is None:
                return _error(404, "沒有這個檢查項目")
            ads_checklist.set_one_time(conn, brand_id, item_key, not current["checked"], actor)
        elif scope == "cycle":
            current = next((i for i in ads_checklist.cycle_status(conn, brand_id, cycle_id) if i["key"] == item_key), None)
            if current is None:
                return _error(404, "沒有這個檢查項目")
            ads_checklist.set_cycle_item(conn, brand_id, cycle_id, item_key, not current["checked"], actor)
        else:
            return _error(400, "scope 只能是 one-time 或 cycle")
    except ValueError as exc:
        return _error(400, str(exc))
    return JSONResponse(None, status_code=204)


@router.post("/api/campaigns/{brand_id}/{cycle_id}/handoff/qa-launch/{item_key}")
async def qa_launch_toggle(request: Request, brand_id: str, cycle_id: str, item_key: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    conn = main_mod.conn
    _require_cycle(brand_id, cycle_id)
    current = next((i for i in ads_checklist.qa_launch_status(conn, brand_id) if i["key"] == item_key), None)
    if current is None:
        return _error(404, "沒有這個檢查項目")
    try:
        ads_checklist.set_qa_launch_item(conn, brand_id, item_key, not current["checked"], actor)
    except ValueError as exc:
        return _error(400, str(exc))
    return JSONResponse(None, status_code=204)


# ---- QA 系統覆核（S8.32-35，票 Q1-01：五項全部改真的打 Meta 查）----

@router.get("/api/campaigns/{brand_id}/{cycle_id}/handoff/qa-auto-check")
async def qa_auto_check(brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    conn = main_mod.conn
    _require_cycle(brand_id, cycle_id)
    return _envelope(qa_autocheck.results(conn, brand_id, cycle_id))


@router.get("/api/campaigns/{brand_id}/{cycle_id}/handoff/naming-check")
async def naming_check_get(brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    conn = main_mod.conn
    _require_cycle(brand_id, cycle_id)
    packages = ads_handoff.list_packages(conn, brand_id, cycle_id)
    return _envelope({
        "naming": ads_handoff.naming_check(conn, brand_id, cycle_id, packages),
        "utm": ads_handoff.utm_check(packages),
    })


# ---- 交接包本體（S8.37-46） ----

def _package_json(pkg: dict) -> dict:
    mapping = None
    if pkg.get("mapping"):
        m = pkg["mapping"]
        mapping = {"meta_campaign_id": m["meta_campaign_id"], "confirmed_by": m["confirmed_by"],
                  "confirmed_at": m["confirmed_at"]}
    return {
        "id": pkg["id"], "campaign_name": pkg["campaign_name"], "adset_name": pkg["adset_name"],
        "ad_name": pkg["ad_name"], "objective_label": pkg["objective_label"],
        "daily_budget": pkg["daily_budget"], "schedule_text": pkg["schedule_text"],
        "hook_text": pkg.get("hook_text") or None, "copy_text": pkg.get("copy_text") or None,
        "full_url": pkg.get("full_url") or None, "image_prompts": pkg.get("image_prompts") or [],
        "mapping": mapping,
    }


def _code_json(row: dict) -> dict:
    return {
        "kind": _KIND_LABEL_TO_TS.get(row["source_type"], row["source_type"]),
        "kind_label": ads_codes.SOURCE_LABELS.get(row["source_type"], row["source_type"]),
        "code": row["code"],
        "discount_pct": row["discount_value"] if row["discount_type"] == "percent" else None,
        "usage_cap": row["usage_limit"], "valid_until": row["valid_to"],
    }


@router.get("/api/campaigns/{brand_id}/{cycle_id}/handoff")
async def handoff_get(brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    conn = main_mod.conn
    _require_cycle(brand_id, cycle_id)
    packages = ads_handoff.list_packages(conn, brand_id, cycle_id)
    codes = ads_codes.list_codes(conn, brand_id, cycle_id)
    verification = ads_codes.latest_verification(conn, brand_id, cycle_id)
    extras = ads_handoff.build_extras(conn, brand_id, cycle_id)
    structure = extras["structure"]
    return _envelope({
        "packages": [_package_json(p) for p in packages],
        "codes": [_code_json(c) for c in codes],
        "codes_verify_mismatch": (verification["mismatches"] if verification and not verification["passed"] else None),
        "account_structure": {
            "tier": structure.tier, "tier_label": structure.tier_label,
            "structure_label": structure.structure_label,
            "groups": [{"role": g.role, "label": g.label, "ratio": g.ratio,
                       "daily_budget": g.daily_budget, "below_floor": g.below_floor}
                      for g in structure.groups],
            "note": structure.note,
        },
    })


@router.post("/api/campaigns/{brand_id}/{cycle_id}/handoff/build")
async def handoff_build(request: Request, brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    try:
        ads_handoff.build_packages(main_mod.conn, brand_id, cycle_id, actor)
    except ValueError as exc:
        return _error(400, str(exc))
    return JSONResponse(None, status_code=204)


@router.post("/api/campaigns/{brand_id}/{cycle_id}/handoff/codes")
async def handoff_codes_generate(request: Request, brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    body = await _json_body(request)
    try:
        ads_codes.generate_codes(main_mod.conn, brand_id, cycle_id, discount_type="percent",
                                 discount_value=body.get("discount_pct"), actor=actor)
    except ValueError as exc:
        return _error(400, str(exc))
    return JSONResponse(None, status_code=204)


@router.post("/api/campaigns/{brand_id}/{cycle_id}/handoff/codes/verify")
async def handoff_codes_verify(request: Request, brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    body = await _json_body(request)
    try:
        result = ads_codes.verify(main_mod.conn, brand_id, cycle_id, actual=body.get("actual") or {}, actor=actor)
    except ValueError as exc:
        return _error(400, str(exc))
    return {"mismatches": result["mismatches"]}


@router.post("/api/campaigns/{brand_id}/{cycle_id}/handoff/{package_id}/activate")
async def handoff_activate(request: Request, brand_id: str, cycle_id: str, package_id: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    body = await _json_body(request)
    meta_ids = {"meta_campaign_id": body.get("meta_campaign_id")}
    try:
        ads_handoff.authorize_and_map(main_mod.conn, brand_id, cycle_id, package_id,
                                      meta_ids=meta_ids, actor=actor)
    except ValueError as exc:
        return _error(400, str(exc))
    return JSONResponse(None, status_code=204)


# ---- Meta 官方 Ads MCP：一鍵建（暫停）＋發布（票 M1-01，ADR 0023） ----

@router.get("/api/campaigns/{brand_id}/{cycle_id}/handoff/meta-status")
async def handoff_meta_status(brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    _require_cycle(brand_id, cycle_id)
    return _envelope(meta_mcp.connect(main_mod.conn))


@router.post("/api/campaigns/{brand_id}/{cycle_id}/handoff/create-all")
async def handoff_create_all(request: Request, brand_id: str, cycle_id: str):
    """只處理 status='ready' 且尚無 mapping 的包；已有 mapping 的跳過（手填過的也算）。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    conn = main_mod.conn
    targets = [p for p in ads_handoff.list_packages(conn, brand_id, cycle_id)
              if p["status"] == "ready" and not p.get("mapping")]
    created, failed = 0, []
    # 同期第一包成功或失敗（只要 Meta campaign 建成功）都可能帶出這期的 campaign_id；
    # 往後每一包都傳進去，跳過各自重找，不會因為第一包卡在素材那關就各建一個 campaign
    # （meta_mcp.create_package() 的 DB 查詢只在 authorize_and_map 成功後才寫得進去，
    # 素材失敗那包永遠查不到，這裡用回應本身把 campaign_id 接力傳下去）。
    campaign_id = None
    for pkg in targets:
        result = meta_mcp.create_package(conn, brand_id, cycle_id, pkg["id"], actor=actor,
                                         campaign_id=campaign_id)
        if result["ok"]:
            created += 1
            campaign_id = campaign_id or result["meta_ids"]["meta_campaign_id"]
        else:
            failed.append({"package_id": pkg["id"], "package_name": pkg["adset_name"],
                           "reason": result["reason"]})
            campaign_id = campaign_id or result.get("meta_campaign_id")
    return {"ok": True, "created": created, "failed": failed}


@router.post("/api/campaigns/{brand_id}/{cycle_id}/handoff/publish-all")
async def handoff_publish_all(request: Request, brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    result = meta_mcp.activate_cycle(main_mod.conn, brand_id, cycle_id, actor=actor)
    if not result["ok"]:
        return _error(400, result["reason"])
    return result


# ---- 交接總分環（S8R.13-17） ----

@router.get("/api/campaigns/{brand_id}/{cycle_id}/readiness")
async def readiness(brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    conn = main_mod.conn
    _require_cycle(brand_id, cycle_id)
    ring = ads_handoff.readiness_ring(conn, brand_id, cycle_id)
    # 票 Q1-01：merge 留在路由層，不是 handoff.py——readiness_ring() 的契約是「純聚合既有
    # 狀態，不重算判定邏輯」（見該函式 docstring），系統覆核會打 Meta，不算「既有狀態」。
    # 這裡跟 qa_auto_check() 一樣呼叫 qa_autocheck.results()（60 秒快取，同一個
    # brand_id/cycle_id 兩邊幾乎同時打不會重複連線），依賴方向只有 qa_autocheck → handoff
    # 一條，不繞回去。
    auto_checks = {c["key"]: c for c in qa_autocheck.results(conn, brand_id, cycle_id)}
    for item in ring["items"]:
        if item["section"] != "qa_launch":
            continue
        auto = auto_checks.get(item["key"])
        item["passed"] = item["passed"] or bool(auto and auto["available"] and auto["passed"])
    ring["items"].sort(key=lambda i: i["passed"])  # 未過項排最前（False < True），同 readiness_ring() 原本的排序規則
    ring["passed"] = sum(1 for i in ring["items"] if i["passed"])
    return _envelope(ring)


# ---- 期中檢查點（S8.47-50） ----

@router.get("/api/campaigns/{brand_id}/{cycle_id}/checkpoint/{kind}")
async def checkpoint_get(brand_id: str, cycle_id: str, kind: str):
    main_mod.require_brand(brand_id)
    conn = main_mod.conn
    _require_cycle(brand_id, cycle_id)
    if kind not in ads_checkpoint.KIND_LABELS:
        return _error(404, "沒有這個檢查點類型")
    history = ads_checkpoint.list_checkpoints(conn, brand_id, cycle_id)
    latest = next((c["result"] for c in history if c["kind"] == kind), None)
    if latest is None:
        latest = {"kind": kind, "data_sufficient": False, "spend_ok": None, "learning_normal": None,
                  "learning_note": "還沒有跑過這個檢查點。", "reach": None, "fatigue": None}
    elif latest.get("fatigue"):
        # `CheckpointResult.fatigue.status`（`warroomApi.ts`）只收 "safe"|"warn" 兩態，
        # `rule_cards.classify_ad_frequency()` 既有三態（safe/warning/danger）——warning／
        # danger 都算「該注意」，一律收斂成 "warn"，不擴充前端型別（前端不改，後端對齊）。
        fatigue = dict(latest["fatigue"])
        fatigue["status"] = "safe" if fatigue.get("status") == "safe" else "warn"
        latest = {**latest, "fatigue": fatigue}
    return _envelope(latest)
