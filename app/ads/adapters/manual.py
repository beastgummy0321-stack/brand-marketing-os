"""app/ads/adapters/manual.py — F03-I09: 手動發布——沒有平台寫入，使用者到平台後台照清單
自己建，回來按「配對」用精準名稱比對綁回這裡（決策 1）。Implements the `app.ads.adapters`
interface (`describe`/`publish`/`bind`); registered under the key `"manual"`.
"""

from app.ads import manual_settings, plan
from app.ads import repository as ads_repo
from app.core import approval as approval_mod
from app.meta import repository as meta_repo

# app/schedule/binding.py 的訊息規則「再實作一份行為」（§0「reused as behaviour,
# re-implemented here — do not import it」）：沒有帳戶可比對時原文回這一句，不接「名稱要一字
# 不差」的尾巴——那句對這個情況是錯的建議。
NO_ACCOUNT_BOUND_MESSAGE = (
    "還沒綁廣告帳戶：到「設定 → Meta 廣告連線」貼權杖並勾選這個品牌，再回來配對。"
)


def _failure_reason(name: str, matches: list) -> str:
    if not matches:
        return f"「{name}」在 Meta 上找不到"
    return f"「{name}」在 Meta 上有 {len(matches)} 個同名的"


def _failure_message(failures: list[str]) -> str:
    return (
        "配對失敗："
        + "、".join(dict.fromkeys(failures))
        + "。名稱要一字不差（區分大小寫，前後空白也算）。"
        "上一層沒有配對成功時，它底下的節點這次不會比對。"
    )


# -- describe：逐節點清單，campaign 節點打頭 ---------------------------------------------------

def _campaign_field(campaign: dict) -> dict:
    return {
        "level": "campaign", "id": campaign["id"], "name": campaign["name"],
        "fields": [
            {"label": "活動名稱", "value": campaign["name"],
             "reason": "平台上的活動名稱要跟這裡一字不差，之後「配對」靠它精準比對。"},
            {"label": "目標", "value": campaign["objective"],
             "reason": "我們自己的分類，選平台上意思最接近的目標。"},
        ],
    }


def _group_field(group: dict) -> dict:
    fields = [
        {"label": "廣告組合名稱", "value": group["name"],
         "reason": "名稱要跟這裡一字不差，之後「配對」靠它。"},
        {"label": "每日預算", "value": group["daily_budget"], "reason": "這組廣告一天要花多少。"},
    ]
    if group.get("start_date"):
        fields.append({"label": "開始日期", "value": group["start_date"],
                        "reason": "這組什麼時候開始投放。"})
    if group.get("end_date"):
        fields.append({"label": "結束日期", "value": group["end_date"],
                        "reason": "這組什麼時候停止投放。"})
    return {"level": "group", "id": group["id"], "name": group["name"], "fields": fields}


def _ad_field(ad: dict) -> dict:
    fields = [
        {"label": "廣告名稱", "value": ad["name"],
         "reason": "名稱要跟這裡一字不差，之後「配對」靠它。"},
    ]
    if ad.get("copy_text"):
        fields.append({"label": "文案", "value": ad["copy_text"],
                        "reason": "貼到平台的廣告文案內容。"})
    if ad.get("image_prompt_text"):
        fields.append({"label": "圖片提示詞", "value": ad["image_prompt_text"],
                        "reason": "拿去產圖或找素材用的提示詞。"})
    return {"level": "ad", "id": ad["id"], "name": ad["name"], "fields": fields}


def describe(campaign: dict) -> dict:
    """逐節點清單，campaign 節點打頭，然後每個投放組、再來是它底下每支廣告——使用者到
    平台後台照這份清單一字不差地建。"""
    checklist = [_campaign_field(campaign)]
    records = {g["id"]: g for g in manual_settings.handoff(campaign)["groups"]}
    for group in campaign.get("groups") or []:
        item = _group_field({**group,
                             "start_date": group.get("start_date") or campaign.get("start_date"),
                             "end_date": group.get("end_date") or campaign.get("end_date")})
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

def publish(conn, org_id: str, brand_id: str, campaign_id: str, *, actor: str) -> dict:
    """不建立任何平台物件——只留一列 `ads_action(kind='publish')` 記意圖，跟**每一次**都寫
    一列 `approval`（F03-I09 修正 2：不管這個 Campaign 有沒有排期，都要核准，`amount` 沒有
    期間時退回投放組日預算合計，絕不悄悄不核准）。"""
    campaign = ads_repo.get_campaign(conn, org_id, brand_id, campaign_id)
    if campaign is None:
        raise ValueError("campaign_unknown")

    daily_sum = ads_repo.group_budget_total(conn, org_id, brand_id, campaign_id)
    if daily_sum <= 0:
        # 發布一個沒有投放組的 Campaign 不是一件事：max_daily_amount=0 的核准會讓之後任何
        # 預算相關的操作都被 plan.py::_check_budget_ceiling 擋死，而 ads 沒有撤銷核准的路徑
        # （F03-I09 修正 2 的未決情況，planner 2026-09-12 裁決）。
        raise ValueError("no_groups_to_publish")
    detail = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)
    assert detail is not None
    amount = detail["budget_total"] if detail["budget_total"] is not None else daily_sum

    approval_mod.approve(
        conn, org_id=org_id, brand_id=brand_id, scope_type=plan.APPROVAL_SCOPE_TYPE,
        scope_ref=campaign_id, content_hash=campaign_id, amount=amount,
        max_daily_amount=daily_sum, actor=actor,
    )
    ads_repo.record_action(
        conn, org_id, brand_id, campaign_id, target_kind="campaign", target_id=campaign_id,
        kind="publish", before={}, after={"adapter": "manual"}, approved_by=actor,
        sync_state="pending_manual",
    )
    return {"ok": True}


# -- bind：逐節點由上往下精準名稱比對 -------------------------------------------------------------

def bind(conn, org_id: str, brand_id: str, campaign_id: str, *, actor: str) -> dict:
    """逐節點由上往下比對（campaign -> group -> ad），因為 Meta 的查找是階層式的：上一層
    沒綁成，底下整批不比對。全部綁完、且原本是 `ready` 才轉 `live`（F03-I09 修正 4：任何
    其他狀態原樣留著，重新配對不會救回一個已經 `closed` 的 Campaign）。"""
    campaign = ads_repo.get_campaign(conn, org_id, brand_id, campaign_id)
    if campaign is None:
        raise ValueError("campaign_unknown")

    account_ids = meta_repo.bound_account_ids_for_brand(conn, org_id, brand_id)
    if not account_ids:
        return {"message": NO_ACCOUNT_BOUND_MESSAGE,
                "campaign": ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)}

    failures: list[str] = []

    campaign_bound_id = campaign["external_id"] if campaign["local_state"] == "bound" else None
    if campaign_bound_id is None:
        matches = meta_repo.campaign_ids_by_exact_name(conn, org_id, account_ids, campaign["name"])
        if len(matches) != 1:
            failures.append(_failure_reason(campaign["name"], matches))
        else:
            campaign_bound_id = matches[0]["campaign_id"]
            ads_repo.bind_campaign(
                conn, org_id, brand_id, campaign_id, external_id=campaign_bound_id,
                external_name=campaign["name"], external_status=matches[0]["external_status"],
            )
            ads_repo.record_action(
                conn, org_id, brand_id, campaign_id, target_kind="campaign",
                target_id=campaign_id, kind="bind", before={},
                after={"external_id": campaign_bound_id}, approved_by=actor,
                sync_state="confirmed_manual", platform_ref=campaign_bound_id,
            )

    if campaign_bound_id is not None:
        detail = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)
        assert detail is not None
        for group in detail["groups"]:
            group_bound_id = group["external_id"] if group["local_state"] == "bound" else None
            if group_bound_id is None:
                matches = meta_repo.ad_set_ids_by_exact_name(
                    conn, org_id, campaign_bound_id, group["name"],
                )
                if len(matches) != 1:
                    failures.append(_failure_reason(group["name"], matches))
                    continue  # 沒有廣告組合可以當第三層的父層範圍，底下廣告整批不比對
                group_bound_id = matches[0]["adset_id"]
                ads_repo.bind_group(
                    conn, org_id, brand_id, group["id"], external_id=group_bound_id,
                    external_name=group["name"], external_status=matches[0]["external_status"],
                )
                ads_repo.record_action(
                    conn, org_id, brand_id, campaign_id, target_kind="group",
                    target_id=group["id"], kind="bind", before={},
                    after={"external_id": group_bound_id}, approved_by=actor,
                    sync_state="confirmed_manual", platform_ref=group_bound_id,
                )

            for ad in group["ads"]:
                ad_bound_id = ad["external_id"] if ad["local_state"] == "bound" else None
                if ad_bound_id is not None:
                    continue
                matches = meta_repo.ad_ids_by_exact_name(conn, org_id, group_bound_id, ad["name"])
                if len(matches) != 1:
                    failures.append(_failure_reason(ad["name"], matches))
                    continue
                ad_bound_id = matches[0]["ad_id"]
                ads_repo.bind_ad(
                    conn, org_id, brand_id, ad["id"], external_id=ad_bound_id,
                    external_name=ad["name"], external_status=matches[0]["external_status"],
                )
                ads_repo.record_action(
                    conn, org_id, brand_id, campaign_id, target_kind="ad", target_id=ad["id"],
                    kind="bind", before={}, after={"external_id": ad_bound_id},
                    approved_by=actor, sync_state="confirmed_manual", platform_ref=ad_bound_id,
                )

    reloaded = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)
    assert reloaded is not None
    all_bound = (
        reloaded["local_state"] == "bound"
        and all(g["local_state"] == "bound" for g in reloaded["groups"])
        and all(a["local_state"] == "bound" for g in reloaded["groups"] for a in g["ads"])
    )
    if all_bound and reloaded["status"] == "ready":  # F03-I09 修正 4：只有 ready -> live
        ads_repo.set_campaign_status(conn, org_id, brand_id, campaign_id, "live")
        reloaded = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)

    message = _failure_message(failures) if failures else None
    return {"message": message, "campaign": reloaded}
