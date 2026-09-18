"""app/ads/plan.py — F03-I06: 採用策略 turns the strategy into real rows a person can edit
(§0 "plan" link). Input: the campaign's stored strategy allocation and adopted `budget_planned`
(nothing is re-asked); output: `ads_delivery_group` and `ads_ad` rows the pack, the publish
adapter and the outcome attribution all key off; trace: the `llm_task` row for the generated
names/coordinates and one `ads_action` row for every edit that lands on an already-bound node.
Private to app/ads (container contract §1): only `routes.py` imports this module's functions.
"""

from datetime import date

from app.ads import budget, channels
from app.ads import repository as ads_repo
from app.core import approval as approval_mod
from app.core.db import APP_DIR
from app.llm import gateway, providers

DEPARTMENT_PATH = APP_DIR / "departments" / "ads" / "delivery_plan.md"

# 唯一的供應商實例，比照 app/ads/strategy.py：測試用
# `mock.patch.object(plan, "PROVIDER", FakeProvider(...))` 換掉。
PROVIDER = providers.AnthropicProvider()

# ARCHITECTURE.md §6.5「Budget raises still pass through app/core/approval.py」——ads 自己的
# scope_type，跟 schedule 的 "schedule_tree" 分開（兩個模組各自的核准煞車，不共用一列）。
APPROVAL_SCOPE_TYPE = "ads_campaign"

_ROLES = frozenset({"new", "retarget", "explore"})
_COORDINATE_DIMENSIONS = ("audience", "pain", "angle", "hook", "proof", "offer", "format")
_MAX_GROUPS = 4
_MAX_ADS_PER_GROUP = 3

PLAN_FAILED_MESSAGE = "AI 沒能整理出可用的投放結構，請再試一次。"
BUDGET_EXCEEDS_APPROVAL_MESSAGE = "這個金額超過目前核准的每日上限，請先重新核准這個品牌的投放預算。"


def _days(start_date, end_date) -> int:
    if start_date is None or end_date is None:
        return 0
    return max((end_date - start_date).days + 1, 0)


def _check_budget_ceiling(
    conn, org_id: str, brand_id: str, campaign_id: str, new_daily_total: float,
) -> None:
    """沒有核准過就沒有煞車（跟 `app/schedule/tree_approval.py` 同一條「approval 可以是
    None」慣例）；核准過就不准悄悄超過那次核准當時定的每日上限。**煞車是逐 Campaign 的**
    （F03-I09 修正）：傳 `scope_ref=campaign_id`，A 的核准不會拿來判 B 的預算。"""
    approval_row = approval_mod.latest(
        conn, org_id=org_id, brand_id=brand_id, scope_type=APPROVAL_SCOPE_TYPE,
        scope_ref=campaign_id,
    )
    if approval_row is None:
        return
    if new_daily_total > float(approval_row["max_daily_amount"]):
        raise ValueError("budget_exceeds_approval")


def _vocabulary_text(rows: list) -> str:
    if not rows:
        return "【座標詞彙】（這個品牌還沒有任何座標詞彙）"
    lines = [f"- {row['dimension']}｜{row['key']}｜{row['label']}" for row in rows]
    return "【座標詞彙（dimension｜key｜label，coordinates 只能填 key）】\n" + "\n".join(lines)


def _vocabulary_lookup(rows: list) -> dict:
    return {(row["dimension"], row["key"]): row for row in rows}


def _validate_reply(data, roles: set) -> list | None:
    """回覆形狀對不上、角色沒有一字不差對上給的角色集合、座標少一個維度或不是字串，一律
    `None`——呼叫端翻成 `ValueError("delivery_plan_failed")`，不落地半份投放結構。"""
    if not isinstance(data, dict):
        return None
    groups = data.get("groups")
    if not isinstance(groups, list) or not groups or len(groups) > _MAX_GROUPS:
        return None

    validated_groups = []
    seen_roles = set()
    seen_ad_names = set()
    for group in groups:
        if not isinstance(group, dict):
            return None
        role = group.get("role")
        if role not in roles or role in seen_roles:
            return None
        seen_roles.add(role)
        name = group.get("name")
        if not isinstance(name, str) or not name.strip():
            return None
        ads = group.get("ads")
        if not isinstance(ads, list) or not ads or len(ads) > _MAX_ADS_PER_GROUP:
            return None

        validated_ads = []
        for ad in ads:
            if not isinstance(ad, dict):
                return None
            ad_name = ad.get("name")
            if not isinstance(ad_name, str) or not ad_name.strip():
                return None
            ad_name = ad_name.strip()
            if ad_name in seen_ad_names:  # §0「unique inside the campaign」
                return None
            coordinates = ad.get("coordinates")
            if not isinstance(coordinates, dict):
                return None
            coords = {}
            for dim in _COORDINATE_DIMENSIONS:
                value = coordinates.get(dim)
                if not isinstance(value, str) or not value.strip():
                    return None
                coords[dim] = value.strip()
            seen_ad_names.add(ad_name)
            validated_ads.append({"name": ad_name, "coordinates": coords})
        validated_groups.append({"role": role, "name": name.strip(), "ads": validated_ads})

    if seen_roles != roles:  # 角色不能少也不能多（department file 的規則）
        return None
    return validated_groups


def adopt_strategy(conn, org_id: str, brand_id: str, campaign_id: str, *, actor: str) -> dict:
    """草稿 -> `ready`：把已採用的策略角色分配展開成投放組／廣告。再跑一次（`status` 已經
    不是 `draft`）一律拒絕——第二次展開會讓已經綁定平台的節點變孤兒（§0）。"""
    ads_repo.require_internal_campaign(conn, org_id, brand_id, campaign_id)
    campaign = ads_repo.get_campaign(conn, org_id, brand_id, campaign_id)
    if campaign is None:
        raise ValueError("campaign_unknown")
    if campaign["status"] != "draft":
        raise ValueError("plan_already_adopted")

    budget_basis = campaign.get("budget_basis_json") or {}
    strategy_payload = budget_basis.get("strategy")
    if not strategy_payload or campaign.get("budget_planned") is None:
        raise ValueError("strategy_not_adopted")
    allocation = strategy_payload["allocation"]
    roles = {row["role"] for row in allocation}

    days = _days(campaign["start_date"], campaign["end_date"])
    if days <= 0:
        raise ValueError("dates_required")
    daily_total = round(float(campaign["budget_planned"]) / days)
    _check_budget_ceiling(conn, org_id, brand_id, campaign_id, daily_total)

    vocabulary_rows = ads_repo.coordinate_vocabulary(conn, org_id, brand_id)
    vocab_lookup = _vocabulary_lookup(vocabulary_rows)

    allocation_text = "\n".join(
        f"- {row['role']}（{row['label']}）：{row['pct']:g}%"
        + (f"，{row['rationale']}" if row.get("rationale") else "")
        for row in allocation
    )
    department_text = DEPARTMENT_PATH.read_text(encoding="utf-8")
    prompt = (
        department_text
        + "\n\n## 這次投放已採用的角色分配\n\n" + allocation_text
        + "\n\n" + _vocabulary_text(vocabulary_rows)
    )

    context = gateway.TaskContext(
        context_scope={"brand_id": brand_id, "campaign_id": campaign_id},
        knowledge_item_ids=[],
        brand_version=(campaign.get("context_json") or {}).get("brand_version") or 0,
    )
    task_row = gateway.run_task(
        conn, PROVIDER, brand_id=brand_id, task_type="ads_delivery_plan",
        prompt_template_id="ads_delivery_plan", prompt_template_version="v1",
        system=None, messages=[{"role": "user", "content": prompt}], context=context,
        options=gateway.TaskOptions(max_tokens=2000, timeout_s=60.0, max_retries=0),
    )
    if task_row["status"] != "succeeded":
        raise ValueError("delivery_plan_failed")
    data = gateway.parse_json_reply(task_row.get("rendered_output") or "")
    validated_groups = _validate_reply(data, roles) if data is not None else None
    if validated_groups is None:
        raise ValueError("delivery_plan_failed")

    # 金額只由程式算：`budget.split()` 是唯一分餘數的地方，總和精準等於 daily_total
    # （F03-I06「這個 issue 的第一件事」——split() 已經是 F03-I04 驗過的邏輯，這裡不重寫）。
    weights = {str(i): (row["pct"] or 0) / 100 for i, row in enumerate(allocation)}
    split_rows = budget.split(daily_total, weights)
    amounts_by_index = {row["label"]: row["amount"] for row in split_rows}
    amount_by_role = {
        allocation[i]["role"]: amounts_by_index[str(i)] for i in range(len(allocation))
    }
    groups_by_role = {group["role"]: group for group in validated_groups}

    declared_platform = (campaign.get("constraints_json") or {}).get("platform")
    channel_key = channels.default_channel_key(conn, org_id, brand_id, declared_platform)

    for role in roles:
        plan_group = groups_by_role[role]
        group_row = ads_repo.create_group(
            conn, org_id, brand_id, campaign_id, channel_key=channel_key,
            name=plan_group["name"], role=role, daily_budget=amount_by_role[role],
        )
        for ad in plan_group["ads"]:
            snapshot = {
                dim: vocab_lookup.get((dim, key), {"key": key})
                for dim, key in ad["coordinates"].items()
            }
            ads_repo.create_ad(
                conn, org_id, brand_id, campaign_id, group_row["id"], name=ad["name"],
                coordinates=ad["coordinates"], coordinates_snapshot=snapshot,
            )

    ads_repo.set_campaign_status(conn, org_id, brand_id, campaign_id, "ready")
    detail = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)
    assert detail is not None
    return detail


# -- 投放組／廣告編輯 -------------------------------------------------------------------------

_GROUP_ACTION_KIND_FIELDS = (
    ("daily_budget", "budget"),
    ("start_date", "date"),
    ("end_date", "date"),
)


def _parse_date(value) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(value)


def update_group(conn, org_id: str, brand_id: str, group_id: str, updates: dict, *,
                  actor: str) -> dict:
    group = ads_repo.get_group(conn, org_id, brand_id, group_id)
    if group is None:
        raise ValueError("group_unknown")

    if "name" in updates and (not isinstance(updates["name"], str) or not updates["name"].strip()):
        raise ValueError("name_unknown")
    if "role" in updates and updates["role"] not in _ROLES:
        raise ValueError("role_unknown")
    if "daily_budget" in updates:
        value = updates["daily_budget"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError("daily_budget_invalid")
        if value > float(group["daily_budget"]):  # 只有「加碼」才過核准煞車，降預算不擋
            other_total = (
                ads_repo.group_budget_total(conn, org_id, brand_id, group["campaign_id"])
                - float(group["daily_budget"])
            )
            _check_budget_ceiling(conn, org_id, brand_id, group["campaign_id"], other_total + value)
    for field in ("start_date", "end_date"):
        if field in updates and updates[field] is not None:
            updates[field] = _parse_date(updates[field])

    before = {k: group.get(k) for k in updates}
    updated = ads_repo.update_group_fields(conn, org_id, brand_id, group_id, updates)

    if group["local_state"] == "bound" and updates:
        kind = next(
            (k for field, k in _GROUP_ACTION_KIND_FIELDS if field in updates), "creative",
        )
        after = {k: updated.get(k) for k in updates}
        ads_repo.record_action(
            conn, org_id, brand_id, group["campaign_id"], target_kind="group",
            target_id=group_id, kind=kind, before=before, after=after, approved_by=actor,
        )
    return updated


def create_group(conn, org_id: str, brand_id: str, campaign_id: str, *, name: str, role: str,
                  daily_budget: float, start_date=None, end_date=None) -> dict:
    ads_repo.require_internal_campaign(conn, org_id, brand_id, campaign_id)
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name_unknown")
    if role not in _ROLES:
        raise ValueError("role_unknown")
    if isinstance(daily_budget, bool) or not isinstance(daily_budget, (int, float)) \
            or daily_budget <= 0:
        raise ValueError("daily_budget_invalid")
    campaign = ads_repo.get_campaign(conn, org_id, brand_id, campaign_id)
    if campaign is None:
        raise ValueError("campaign_unknown")
    other_total = ads_repo.group_budget_total(conn, org_id, brand_id, campaign_id)
    _check_budget_ceiling(conn, org_id, brand_id, campaign_id, other_total + daily_budget)
    declared_platform = (campaign.get("constraints_json") or {}).get("platform")
    channel_key = channels.default_channel_key(conn, org_id, brand_id, declared_platform)
    return ads_repo.create_group(
        conn, org_id, brand_id, campaign_id, channel_key=channel_key, name=name.strip(),
        role=role, daily_budget=daily_budget, start_date=_parse_date(start_date),
        end_date=_parse_date(end_date),
    )


def delete_group(conn, org_id: str, brand_id: str, group_id: str) -> None:
    group = ads_repo.get_group(conn, org_id, brand_id, group_id)
    if group is None:
        raise ValueError("group_unknown")
    if group["local_state"] == "bound":
        raise ValueError("group_bound")
    ads_repo.delete_group(conn, org_id, brand_id, group_id)


def create_ad(conn, org_id: str, brand_id: str, campaign_id: str, group_id: str, *, name: str,
              coordinates: dict) -> dict:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name_unknown")
    group = ads_repo.get_group(conn, org_id, brand_id, group_id)
    if group is None or group["campaign_id"] != campaign_id:
        raise ValueError("group_unknown")
    coords = {}
    for dim in _COORDINATE_DIMENSIONS:
        value = coordinates.get(dim)
        if not isinstance(value, str) or not value.strip():
            raise ValueError("coordinates_incomplete")
        coords[dim] = value.strip()
    vocabulary_rows = ads_repo.coordinate_vocabulary(conn, org_id, brand_id)
    vocab_lookup = _vocabulary_lookup(vocabulary_rows)
    snapshot = {dim: vocab_lookup.get((dim, key), {"key": key}) for dim, key in coords.items()}
    return ads_repo.create_ad(
        conn, org_id, brand_id, campaign_id, group_id, name=name.strip(), coordinates=coords,
        coordinates_snapshot=snapshot,
    )


def update_ad(conn, org_id: str, brand_id: str, ad_id: str, updates: dict, *, actor: str) -> dict:
    ad = ads_repo.get_ad(conn, org_id, brand_id, ad_id)
    if ad is None:
        raise ValueError("ad_unknown")
    if "name" in updates and (not isinstance(updates["name"], str) or not updates["name"].strip()):
        raise ValueError("name_unknown")
    if "coordinates" in updates:
        for dim, value in updates["coordinates"].items():
            if dim not in _COORDINATE_DIMENSIONS or not isinstance(value, str) or not value.strip():
                raise ValueError("coordinates_incomplete")

    before = {k: ad.get(k) for k in updates if k != "coordinates"}
    if "coordinates" in updates:
        before["coordinates"] = {
            dim: ad.get(f"{dim}_key") for dim in updates["coordinates"]
        }
    updated = ads_repo.update_ad_fields(conn, org_id, brand_id, ad_id, updates)

    if ad["local_state"] == "bound" and updates:
        after = {k: updated.get(k) for k in updates if k != "coordinates"}
        if "coordinates" in updates:
            after["coordinates"] = {
                dim: updated.get(f"{dim}_key") for dim in updates["coordinates"]
            }
        ads_repo.record_action(
            conn, org_id, brand_id, ad["campaign_id"], target_kind="ad", target_id=ad_id,
            kind="creative", before=before, after=after, approved_by=actor,
        )
    return updated


def delete_ad(conn, org_id: str, brand_id: str, ad_id: str) -> None:
    ad = ads_repo.get_ad(conn, org_id, brand_id, ad_id)
    if ad is None:
        raise ValueError("ad_unknown")
    if ad["local_state"] == "bound":
        raise ValueError("ad_bound")
    ads_repo.delete_ad(conn, org_id, brand_id, ad_id)
