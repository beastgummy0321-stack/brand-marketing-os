"""app/ads/adapters/manual.py — F03-I09: 手動發布——沒有平台寫入，使用者到平台後台照清單
自己建（決策 1）。Implements the `app.ads.adapters` interface (`describe`/`publish`);
registered under the key `"manual"`. F31-I08: the name-match `bind` is gone -- launch readback
(`handoff_check`) binds each planned node to the platform object the user proved.
"""

from app.ads import change_control_launch, manual_settings, simulation_mode
from app.ads import repository as ads_repo

# -- describe：逐節點清單，campaign 節點打頭 ---------------------------------------------------

# F31-I08: the name-match 「配對」 is gone. Launch readback (`handoff_check`) never compares
# names -- the user picks the platform object in each check -- so the name only helps them
# recognise which one to pick.
_NAME_REASON = "平台上的名稱照這裡填，回來核對時比較容易認出要選哪一個。"

def _campaign_field(campaign: dict) -> dict:
    return {
        "level": "campaign", "id": campaign["id"], "name": campaign["name"],
        "fields": [
            {"label": "活動名稱", "value": campaign["name"],
             "reason": _NAME_REASON},
            {"label": "目標", "value": campaign["objective"],
             "reason": "我們自己的分類，選平台上意思最接近的目標。"},
        ],
    }


def _audience_hint_fields(campaign: dict) -> dict:
    """group id -> the 「受眾提示」 field, from the one helper `launch_view` uses for its own
    checklist (Contract V), so both lists print the same text. Lazy import: `launch_view` reaches
    `adapters/__init__` through `external_sync`, the same seam `adapters.platform_url` notes."""
    from app.ads import launch_view
    from app.core import db

    hints = launch_view.audience_hints(
        db.current(), campaign["org_id"], campaign["brand_id"], campaign
    )
    return {
        group_id: {
            "key": launch_view.AUDIENCE_HINT_KEY, "label": launch_view.AUDIENCE_HINT_LABEL,
            "value": text,
            "reason": "方案裡這組要打的人，只供參考；平台受眾照你自己的判斷設定，"
                      "回來核對時不比對這一項。",
        }
        for group_id, text in hints.items()
    }


def _group_field(group: dict, audience_hint: dict | None = None) -> dict:
    fields = [
        {"label": "廣告組合名稱", "value": group["name"], "reason": _NAME_REASON},
        {"label": "每日預算", "value": group["daily_budget"], "reason": "這組廣告一天要花多少。"},
    ]
    if group.get("start_date"):
        fields.append({"label": "開始日期", "value": group["start_date"],
                        "reason": "這組什麼時候開始投放。"})
    if group.get("end_date"):
        fields.append({"label": "結束日期", "value": group["end_date"],
                        "reason": "這組什麼時候停止投放。"})
    if audience_hint:
        # F36-I07 (Contract V): after the date rows, the same row `launch_view` shows -- the
        # plan's role and audience coordinates, read-only, never a platform targeting mapping.
        fields.append(audience_hint)
    return {"level": "group", "id": group["id"], "name": group["name"], "fields": fields}


def _ad_field(ad: dict) -> dict:
    fields = [
        {"label": "廣告名稱", "value": ad["name"], "reason": _NAME_REASON},
    ]
    material = ad.get("material_assignment")
    if material:
        fields.append({"label": "指定素材檔案", "value": material["filename"],
                       "reason": f"素材安排第 {material['placement_revision']} 版；請使用此原檔。"})
        for key, label in (("headline", "標題"), ("body", "文案"), ("description", "說明"),
                           ("cta", "行動呼籲"), ("landing_url", "連結")):
            value = material["copy_fields"].get(key)
            if value:
                fields.append({"label": label, "value": value,
                               "reason": "此計畫廣告明確指定的素材版本內容。"})
        if not change_control_launch.ready_material(material):
            fields.append({"label": "素材需重新指派", "value": material["reason"],
                           "reason": "失效版本不能沿用核准。"})
    elif ad.get("copy_text"):
        fields.append({"label": "文案", "value": ad["copy_text"],
                        "reason": "貼到平台的廣告文案內容。"})
    if not material and ad.get("image_prompt_text"):
        fields.append({"label": "圖片提示詞", "value": ad["image_prompt_text"],
                        "reason": "拿去產圖或找素材用的提示詞。"})
    return {"level": "ad", "id": ad["id"], "name": ad["name"], "fields": fields}


def describe(campaign: dict) -> dict:
    """逐節點清單，campaign 節點打頭，然後每個投放組、再來是它底下每支廣告——使用者到
    平台後台照這份清單一字不差地建。"""
    checklist = [_campaign_field(campaign)]
    records = {g["id"]: g for g in manual_settings.handoff(campaign)["groups"]}
    hints = _audience_hint_fields(campaign)
    for group in campaign.get("groups") or []:
        item = _group_field({**group,
                             "start_date": group.get("start_date") or campaign.get("start_date"),
                             "end_date": group.get("end_date") or campaign.get("end_date")},
                            hints.get(group["id"]))
        record = records[group["id"]]
        item["fields"].append({"label": "人工上架設定狀態", "value": record["status"],
                               "reason": "待補：" + "、".join(record["missing"])
                               if record["missing"] else "已填資料仍需在平台核對。"})
        item["fields"].extend(
            {"label": f["label"], "value": record["values"].get(f["key"]) or "尚未填寫",
             "reason": "手動紀錄；不代表已配對或已同步至平台。"}
            for f in manual_settings.FIELDS
        )
        checklist.append(item)
        for ad in group.get("ads") or []:
            checklist.append(_ad_field(ad))
    return {"adapter": "manual", "message": None, "checklist": checklist}


# -- publish：不碰平台，只記意圖＋寫一次核准 -----------------------------------------------------

def publish(conn, org_id: str, brand_id: str, campaign_id: str, *, actor: str,
            operation_id: str | None = None, content_hash: str | None = None) -> dict:
    """只保存核准與人工交接意圖；相同操作重送不重複核准，從不建立平台物件。"""
    ads_repo.require_internal_campaign(conn, org_id, brand_id, campaign_id)
    simulation_mode.require_real(conn, org_id, brand_id)
    campaign = ads_repo.get_campaign(conn, org_id, brand_id, campaign_id)
    if campaign is None:
        raise ValueError("campaign_unknown")

    daily_sum = ads_repo.group_budget_total(conn, org_id, brand_id, campaign_id)
    if daily_sum <= 0:
        # 發布一個沒有投放組的 Campaign 不是一件事：max_daily_amount=0 的核准會讓之後任何
        # 預算相關的操作都被 plan.py::_check_budget_ceiling 擋死，而 ads 沒有撤銷核准的路徑
        # （F03-I09 修正 2 的未決情況，planner 2026-09-12 裁決）。
        raise ValueError("no_groups_to_publish")
    return change_control_launch.publish(conn, org_id, brand_id, campaign_id, actor,
                                         operation_id, content_hash)

