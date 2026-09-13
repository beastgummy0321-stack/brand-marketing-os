"""app/ads/assets.py — F03-I08: the plan orders its artifacts and knows when they are ready
(§0 "artifact" link). Input: the `ads_ad` rows and their coordinates; output: one 任務包 in
素材工作檯 (`workbench.submit_pack`) or a manual tick, and a readiness state per ad the publish
checklist reads; trace: who ticked 素材已就位 and when, or which pack approval made a set ready.
Pluggable — an ad can be ready without the workbench ever being used (the manual tick is the
point). Private to app/ads (container contract §1): only `routes.py` imports this module's
functions.

Readiness is read through the workbench's **existing** public entries only
(`pack_for_source` / `briefs_for_source`) — no SQL against `workbench_*` tables here, and no new
workbench public entry for per-set counts (§0 "Workbench handoff", feature-3 fidelity).
"""

from app import workbench
from app.ads import channels
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo

# §0「Workbench handoff」：這是既有 DB token（「上游派工」），不是新值——§5.7 變體模式就是
# 靠這個字串鍵住的，這裡沿用，不發明新的 source_kind。
PACK_SOURCE_KIND = "schedule_node"

_COORDINATE_DIMENSIONS = ("audience", "pain", "angle", "hook", "proof", "offer", "format")

# F05-I05：通路標籤只住在 channels.py（§0「不寫死平台」）——沒列到的 channel_key 原樣顯示。
_CHANNEL_LABELS = {c["key"]: c["label"] for c in channels.CHANNELS}

PACK_ALREADY_EXISTS_MESSAGE = "這個 Campaign 已經交棒過素材任務包了。"


def _pack_source_ref(campaign_id: str) -> dict:
    return {"ads_campaign_id": campaign_id}


def _set_source_ref(campaign_id: str, ad_id: str) -> dict:
    return {"ads_campaign_id": campaign_id, "ads_ad_id": ad_id}


def _coordinates(ad: dict) -> dict:
    return {
        dim: ad.get(f"{dim}_key") for dim in _COORDINATE_DIMENSIONS if ad.get(f"{dim}_key")
    }


def _image_prompt_count(ad: dict) -> int:
    """跟舊派工（`app/schedule/jobs.py`）同一條規則：格式是「彈性格式」給 10 張，其餘給
    3 張——這裡讀 `coordinates_snapshot_json` 裡的 label（廣告座標欄存的是 key，label 才是
    這句中文，見 `app/ads/plan.py::create_ad` 怎麼存 snapshot）。"""
    snapshot = ad.get("coordinates_snapshot_json") or {}
    format_label = (snapshot.get("format") or {}).get("label")
    return 10 if format_label == "彈性格式" else 3


def _copy_length(_ad: dict) -> str:
    # ponytail: ads_ad 沒有存 LLM 給的 copy_length 欄位（跟 schedule 的樹節點不同，那邊
    # 展開時逐節點填過一個）；沿用舊派工遇到節點沒填時的同一個預設值 "short"
    # （`app/schedule/jobs.py`: `leaf.get("copy_length") or "short"`）。要逐廣告判斷，
    # 得先在 `ads_ad` 加一個 copy_length 欄位——不在這張票範圍內。
    return "short"


def _origin(brand_id: str, brand_name: str, campaign: dict, groups: list) -> dict:
    """§0「Workbench handoff」的 `context.origin_label`／`origin_href`——一個 pack 對應
    整個 Campaign（可能不只一個投放組），標籤把用到的通路跟投放組都列出來，不是挑一個
    代表。"""
    channel_labels: list[str] = sorted({
        str(_CHANNEL_LABELS.get(g["channel_key"], g["channel_key"])) for g in groups
    }) or ["（尚無通路）"]
    group_names = "、".join(g["name"] for g in groups) or "（尚無投放組）"
    origin_label = (
        f"投放中心 → {brand_name}｜{campaign['name']} → {'／'.join(channel_labels)}"
        f" → {group_names}"
    )
    origin_href = f"/brands/{brand_id}/ads/campaigns/{campaign['id']}?tab=assets"
    return {"origin_label": origin_label, "origin_href": origin_href}


def _ad_set(ad: dict, campaign_id: str, fallback_product_id: str | None) -> dict:
    # 一則廣告只打一個商品（ARCHITECTURE §5.4）；用同一個 product_id 決定 set 欄位與
    # request.product_ids，不各算一次——否則工作檯 (jobs.py:49-68) 會替 Campaign 裡的每個
    # 商品各編一次品牌上下文，重複付 N 份品牌層知識的錢（ARCHITECTURE.md §1 第 1 條）。
    product_id = ad.get("product_id") or fallback_product_id
    return {
        "name": ad["name"],
        "source_ref": _set_source_ref(campaign_id, ad["id"]),
        "product_id": product_id,
        "coordinates": _coordinates(ad),
        "style_key": "ugc",  # 沒有品牌預設風格這件事（見票面），沿用其他派工同值
        "required_outputs": {"copy": 1, "image_prompt": 1},
        "request": {
            "copy_length": _copy_length(ad),
            "image_prompt_count": _image_prompt_count(ad),
            "use_brand_knowledge": True,
            "product_ids": [product_id] if product_id else [],
        },
    }


def dispatch_pack(conn, org_id: str, brand_id: str, campaign_id: str) -> str:
    """一個 Campaign 一個任務包、一個 `ads_ad` 一個 set；回傳 pack id。`ValueError`：
    `campaign_unknown`、`pack_already_exists`（再交棒一次——已經有一份了）；其餘（
    `sets_unknown`／`required_outputs_unknown`／...）是 `workbench.submit_pack` 自己的驗證，
    原樣往上丟，這裡不重新包一次。"""
    campaign = ads_repo.get_campaign(conn, org_id, brand_id, campaign_id)
    if campaign is None:
        raise ValueError("campaign_unknown")
    if workbench.pack_for_source(
        conn, org_id, brand_id, PACK_SOURCE_KIND, _pack_source_ref(campaign_id),
    ) is not None:
        raise ValueError("pack_already_exists")

    detail = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)
    assert detail is not None
    groups = detail["groups"]
    ads = [ad for group in groups for ad in group["ads"]]

    brand = bi_repo.get_brand(conn, brand_id)
    brand_name = brand["name"] if brand else brand_id
    context_json = campaign.get("context_json") or {}
    campaign_product_ids = context_json.get("product_ids") or []
    fallback_product_id = campaign_product_ids[0] if campaign_product_ids else None

    summary: dict = {"情境": campaign["goal_text"]}
    if context_json.get("audience_hint"):
        summary["目標受眾"] = context_json["audience_hint"]
    if context_json.get("notes"):
        summary["重點訊息"] = context_json["notes"]

    pack = {
        "source_kind": PACK_SOURCE_KIND,
        "source_ref": _pack_source_ref(campaign_id),
        "name": campaign["name"],
        "summary": summary,
        "context": _origin(brand_id, brand_name, campaign, groups),
        "sets": [
            _ad_set(ad, campaign_id, fallback_product_id) for ad in ads
        ],
    }
    return workbench.submit_pack(conn, org_id, brand_id, pack)


def readiness(conn, org_id: str, brand_id: str, campaign_id: str) -> list:
    """每支廣告的就緒狀態：`ready_workbench`（所屬 pack 已核准）／`in_progress`（pack 存在但
    還沒核准）／`ready_manual`（沒進工作檯，使用者自己勾了「素材已就位」）／
    `not_started`。只透過工作檯既有的公開入口讀（`pack_for_source`／`briefs_for_source`），
    不碰 `workbench_*` 表。"""
    ads = ads_repo.list_ads_for_campaign(conn, org_id, brand_id, campaign_id)
    pack = workbench.pack_for_source(
        conn, org_id, brand_id, PACK_SOURCE_KIND, _pack_source_ref(campaign_id),
    )
    approved = pack is not None and pack.get("approved_at") is not None

    briefs_by_ad_id: dict = {}
    if pack is not None:
        for brief in workbench.briefs_for_source(
            conn, org_id, brand_id, PACK_SOURCE_KIND, _pack_source_ref(campaign_id),
        ):
            ad_id = (brief.get("source_ref") or {}).get("ads_ad_id")
            if ad_id:
                briefs_by_ad_id[ad_id] = brief

    rows = []
    for ad in ads:
        brief = briefs_by_ad_id.get(ad["id"])
        if brief is not None:
            assert pack is not None
            if approved:
                rows.append({
                    "ad_id": ad["id"], "state": "ready_workbench", "pack_id": pack["id"],
                    "brief_id": brief["id"], "source": "workbench",
                    "by": None, "at": pack.get("approved_at"),
                })
            elif ad.get("asset_ready_source") == "manual":
                # ruling 8: 手動勾是逃生口，交棒（尚未核准）不能把它蓋掉——兩個來源是 OR。
                rows.append({
                    "ad_id": ad["id"], "state": "ready_manual", "pack_id": pack["id"],
                    "brief_id": brief["id"], "source": "manual",
                    "by": ad.get("asset_ready_by"), "at": ad.get("asset_ready_at"),
                })
            else:
                rows.append({
                    "ad_id": ad["id"], "state": "in_progress", "pack_id": pack["id"],
                    "brief_id": brief["id"], "source": "workbench",
                    "by": None, "at": None,
                })
        elif ad.get("asset_ready_source") == "manual":
            rows.append({
                "ad_id": ad["id"], "state": "ready_manual", "pack_id": None,
                "brief_id": None, "source": "manual",
                "by": ad.get("asset_ready_by"), "at": ad.get("asset_ready_at"),
            })
        else:
            rows.append({
                "ad_id": ad["id"], "state": "not_started", "pack_id": None,
                "brief_id": None, "source": None, "by": None, "at": None,
            })
    return rows


def readiness_summary(rows: list) -> dict:
    """`ready_count`／`total`——素材 tab 跟發布畫面共用同一組數字（§0）。"""
    ready = sum(1 for r in rows if r["state"] in ("ready_workbench", "ready_manual"))
    return {"ready_count": ready, "total": len(rows)}


def mark_ready(conn, org_id: str, brand_id: str, ad_id: str, *, actor: str,
                ready: bool) -> dict:
    """使用者手動勾／取消勾「素材已就位」——不是 `ads_action`（沒有東西碰到平台），單純這一
    列自己的事實（誰、何時）。`ValueError("ad_unknown")` 找不到那支廣告。"""
    ad = ads_repo.get_ad(conn, org_id, brand_id, ad_id)
    if ad is None:
        raise ValueError("ad_unknown")
    return ads_repo.set_ad_asset_ready(conn, org_id, brand_id, ad_id, actor=actor, ready=ready)
