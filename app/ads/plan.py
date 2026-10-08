"""app/ads/plan.py — F03-I06: 採用策略 turns the strategy into real rows a person can edit
(§0 "plan" link). Input: the campaign's stored strategy allocation and adopted `budget_planned`
(nothing is re-asked); output: `ads_delivery_group` and `ads_ad` rows the pack, the publish
adapter and the outcome attribution all key off; trace: the `llm_task` row for the generated
names/coordinates and one `ads_action` row for every edit that lands on an already-bound node.
F39-I03: every planned ad also carries one `scene` (6–60 chars, the moment its copy happens
in) and ads for different audiences must carry different scenes, or the plan is rejected.
F44-I02: the prompt lists the registered sentence of every offer the menu kept, and a plan in
which no ad uses one of them is rejected.
F46-I01 (Contracts A and P): every planned ad binds one listed customer group (`customer_group`
= 第 N 群, all ads of one delivery group share it, `pain` within that group's pains), and the
prompt says how many photos and videos the brand has in hand.
F46-I04 (Contract G): the prompt carries 【上幾期的排名】 (`coordinate_learning.ranked_section`) and
a plan that re-runs a 換掉 (customer group, angle) of the newest closed campaign is refused.
F48-I06 (Contracts P, C, K): the prompt is built from `planner_context` (one menu, one 「不能講」
list, one capacity line); the plan never holds more ads than the capacity ceiling; last period's
留下 ads are carried in with their creative before the model is asked (so the keep half of the
Contract G gate is met by construction); hand edits obey the same menu and 「不能講」 list.
Private to app/ads (container contract §1): only `routes.py` imports this module's functions.
"""

import json
import logging
import re
from collections.abc import Set as AbstractSet
from datetime import date

from app import workbench
from app.ads import (
    budget,
    calendar_tw,
    channels,
    coordinate_learning,
    learning_rank,
    planner_context,
    user_assets_repository,
)
from app.ads import repository as ads_repo
from app.ads import sell_way as sell_way_mod
from app.brand_intelligence import repository as bi_repo
from app.core import approval as approval_mod
from app.core import input_rules
from app.core.db import APP_DIR
from app.llm import gateway, providers

DEPARTMENT_PATH = APP_DIR / "departments" / "ads" / "delivery_plan.md"

logger = logging.getLogger(__name__)

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
_SCENE_MIN_CHARS = 6
_SCENE_MAX_CHARS = 60

PLAN_FAILED_MESSAGE = "AI 沒能整理出可用的投放結構，請再試一次。"
BUDGET_EXCEEDS_APPROVAL_MESSAGE = "這個金額超過目前核准的每日上限，請先重新核准這個品牌的投放預算。"

# The delivery-plan call's timeout; `busy.py` reads it (a running row older than this + 30 s is
# not busy, F50 Contract J).
TIMEOUT_S = 60.0

#: F50 Contract J (R7 B3): every rule that refuses a delivery-plan reply, code -> reason (a short
#: plain sentence; the route prints it after `PLAN_FAILED_MESSAGE`). `llm_failed` gets the
#: provider's kind appended (`llm_failed_reason`).
REFUSALS = {
    "llm_failed": "AI 這次沒有回覆",
    "reply_unreadable": "AI 的回覆不是看得懂的格式",
    "reply_invalid": "AI 的回覆缺了欄位、廣告名稱重複，或情境不合規定",
    "menu_violation": "AI 排的角色或廣告則數超出這期給的範圍",
    "offer_unused": "這期有優惠，AI 排的廣告都沒用上",
    "name_forbidden": "AI 取的廣告名稱用了不能講的字",
    "group_unbound": "AI 排的廣告沒有對上這期列出的顧客群",
    "carried_changed": "AI 讓沿用廣告的投放組換了一群人",
    "replace_rerun": "又排了上一期要換掉的組合",
}

#: `llm_task.error_code` (the gateway's kinds) in plain words, for `llm_failed`.
LLM_ERROR_WORDS = {
    "timeout": "等太久沒有回應",
    "refused": "模型婉拒了這次請求",
    "provider": "AI 服務出錯",
    "truncated": "回覆太長被截斷",
    "spend_cap": "這個月的 AI 用量已達上限",
    "no_credentials": "還沒有可用的 AI 金鑰",
}

RETRY_HEADER = "【上一次的回覆被程式退回】"


class PlannerRefused(ValueError):
    """F50 Contract J: a planner reply (delivery plan or strategy) refused by one program rule.
    `str()` stays the module's failed code (`delivery_plan_failed`／`strategy_failed`, the
    routes' existing mappings); `code` names the rule (the module's `REFUSALS`), `reason` is its
    sentence, `task_id` the `llm_task` row judged (`None` when no model was asked)."""

    def __init__(self, failed: str, code: str, reason: str, task_id: str | None = None):
        super().__init__(failed)
        self.code, self.reason, self.task_id = code, reason, task_id


def llm_failed_reason(task_row: dict) -> str:
    """「AI 這次沒有回覆（{the provider's kind in plain words}）」 -- an unknown kind reads as a
    provider error, never as a guessed cause."""
    words = LLM_ERROR_WORDS.get(task_row.get("error_code") or "", LLM_ERROR_WORDS["provider"])
    return f"{REFUSALS['llm_failed']}（{words}）"


def refusal_section(refused: list[PlannerRefused]) -> str:
    """The retry prompt's section: each refusal's code and sentence (user ruling 2026-10-04)."""
    lines = [f"- {exc.code}：{exc.reason}" for exc in refused]
    return (RETRY_HEADER + "（這次請改掉下面的問題，其他規則照舊）\n" + "\n".join(lines))


def note_refusal(conn, exc: PlannerRefused, *, campaign_id: str | None, attempt: int,
                 brand_id: str | None = None) -> None:
    """Writes the refusal on its task row (`gateway.record_refusal`) and logs it at INFO with the
    campaign (a brief parse has none yet: its brand). An `llm_failed` row already holds the
    provider's own `error`／`error_code`, which is never overwritten."""
    if exc.task_id is not None and exc.code != "llm_failed":
        gateway.record_refusal(conn, exc.task_id, exc.code, exc.reason)
    logger.info("ads planner refused: %s campaign=%s brand=%s code=%s attempt=%s task=%s",
                str(exc), campaign_id, brand_id, exc.code, attempt, exc.task_id)


def ask_with_one_retry(conn, ask, *, campaign_id: str):
    """User ruling 2026-10-04 (F50 lead note): a reply refused by a program rule is asked once
    more, the second prompt carrying the refusals (`ask(refused)` builds the prompt from them);
    a second refusal is raised. A provider failure (`llm_failed`) is no rule's refusal and is
    raised at once. At most one extra model call per press."""
    refused: list[PlannerRefused] = []
    while True:
        try:
            return ask(refused)
        except PlannerRefused as exc:
            note_refusal(conn, exc, campaign_id=campaign_id, attempt=len(refused) + 1)
            if refused or exc.code == "llm_failed" or exc.task_id is None:
                raise
            refused.append(exc)


def _refused(code: str, task_id: str | None) -> PlannerRefused:
    return PlannerRefused("delivery_plan_failed", code, REFUSALS[code], task_id)


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


def _uses_an_offer(groups: list) -> bool:
    return any(ad["coordinates"]["offer"] != "none" for group in groups for ad in group["ads"])


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _forbidden_in(name: str, terms: list[str]) -> str | None:
    """The first 「不能講」 entry written in `name` (whitespace-free, case-blind -- the way
    `workbench.validate_claims` matches copy), else None."""
    squashed = _squash(name)
    return next((term for term in terms if term and _squash(term) in squashed), None)


class CoordinateUnavailable(ValueError):
    """A hand edit picked a vocabulary key this period's menu leaves out (`planner_context.menu`).
    `str()` is the code `coordinate_unavailable`; the route words the dimension and the reason."""

    def __init__(self, dimension: str, key: str, reason: str):
        super().__init__("coordinate_unavailable")
        self.dimension, self.key, self.reason = dimension, key, reason

    @property
    def dimension_label(self) -> str:
        return learning_rank.DIMENSION_LABELS.get(self.dimension, self.dimension)


class NameForbidden(ValueError):
    """An ad name carries a 「不能講」 entry (`workbench.forbidden_terms`); `str()` is the code
    `name_forbidden`, `term` the entry the route quotes."""

    def __init__(self, term: str):
        super().__init__("name_forbidden")
        self.term = term


def _first_format(rows: list) -> str | None:
    """The first `format` key of the filtered menu -- where a stray format reply lands (F42)."""
    return next((row["key"] for row in rows if row["dimension"] == "format"), None)


def _gate_reply(groups: list, lookup: dict, first_format: str | None) -> None:
    """A proof/offer key outside the filtered menu becomes `none` in place (F38 agent choice:
    the menu already told the model what exists; a stray key is a wording slip, not a retry).
    F42: a format key outside the menu (e.g. `video` for a photo-only brand) becomes the menu's
    first format; a menu with no format rows at all leaves the reply's key as it is."""
    for group in groups:
        for ad in group["ads"]:
            coords = ad["coordinates"]
            for dim in ("proof", "offer"):
                if (dim, coords[dim]) not in lookup:
                    coords[dim] = "none"
            if first_format is not None and ("format", coords["format"]) not in lookup:
                coords["format"] = first_format


def _validate_scene(value) -> str | None:
    """F39-I03 (outcome 3): one sentence, 6–60 chars after strip, else `None`."""
    if not isinstance(value, str):
        return None
    scene = value.strip()
    if not _SCENE_MIN_CHARS <= len(scene) <= _SCENE_MAX_CHARS:
        return None
    return scene


def _scenes_differ_across_audiences(validated_groups: list) -> bool:
    """F39-I03: two ads whose `audience` keys differ must not share one scene string (exact match
    after strip); ads of the same audience may. Drill-7 §3 #3 saw 12 ads with one scene."""
    audiences_by_scene: dict[str, set] = {}
    for group in validated_groups:
        for ad in group["ads"]:
            audiences_by_scene.setdefault(ad["scene"], set()).add(ad["coordinates"]["audience"])
    return all(len(audiences) == 1 for audiences in audiences_by_scene.values())


def _validate_reply(data, roles: set, *, covered: AbstractSet[str] = frozenset(),
                    room: dict | None = None, limit: int | None = None,
                    taken: AbstractSet[str] = frozenset()) -> list | None:
    """回覆形狀對不上、角色沒有一字不差對上給的角色集合、座標少一個維度或不是字串、情境
    缺了或長度不對、不同受眾共用同一個情境，一律 `None`——呼叫端翻成
    `ValueError("delivery_plan_failed")`，不落地半份投放結構。

    F48-I06 (Contracts K, C): `covered` = roles that already hold carried ads (the reply may leave
    them out), `room` = role -> how many ads the reply may still add there (default
    `_MAX_ADS_PER_GROUP`), `limit` = the most ads the reply may hold in all (`ceiling − carried`,
    refused above it like the scene rule), `taken` = carried ad names (a reply name may not
    repeat one). F50 Contract J: `_check_reply` is the same judgement naming the rule."""
    return _check_reply(data, roles, covered=covered, room=room, limit=limit, taken=taken)[0]


def _check_reply(data, roles: AbstractSet[str], *, covered: AbstractSet[str] = frozenset(),
                 room: dict | None = None, limit: int | None = None,
                 taken: AbstractSet[str] = frozenset()) -> tuple[list | None, str | None]:
    """`_validate_reply`'s rules, returning `(groups, None)` or `(None, code)` (F50 Contract J):
    `menu_violation` = the reply left what the program gave it (a role outside the adopted
    allocation, a role twice or missing, more ads than a group's room or the ceiling);
    `reply_invalid` = every other rule (shape, names, the seven coordinates, the scene)."""
    invalid = (None, "reply_invalid")
    menu = (None, "menu_violation")
    if not isinstance(data, dict):
        return invalid
    groups = data.get("groups")
    if not isinstance(groups, list) or not groups:
        return invalid
    if len(groups) > _MAX_GROUPS:
        return menu

    validated_groups = []
    seen_roles = set()
    seen_ad_names = set(taken)
    for group in groups:
        if not isinstance(group, dict):
            return invalid
        role = group.get("role")
        if role not in roles or role in seen_roles:
            return menu
        seen_roles.add(role)
        name = group.get("name")
        if not isinstance(name, str) or not name.strip():
            return invalid
        ads = group.get("ads")
        most = _MAX_ADS_PER_GROUP if room is None else room.get(role, _MAX_ADS_PER_GROUP)
        if not isinstance(ads, list) or not ads:
            return invalid
        if len(ads) > most:
            return menu

        validated_ads = []
        for ad in ads:
            if not isinstance(ad, dict):
                return invalid
            ad_name = ad.get("name")
            if not isinstance(ad_name, str) or not ad_name.strip():
                return invalid
            ad_name = ad_name.strip()
            if ad_name in seen_ad_names:  # §0「unique inside the campaign」
                return invalid
            coordinates = ad.get("coordinates")
            if not isinstance(coordinates, dict):
                return invalid
            coords = {}
            for dim in _COORDINATE_DIMENSIONS:
                value = coordinates.get(dim)
                if not isinstance(value, str) or not value.strip():
                    return invalid
                coords[dim] = value.strip()
            scene = _validate_scene(ad.get("scene"))
            if scene is None:
                return invalid
            seen_ad_names.add(ad_name)
            # F46 Contract A: the raw 第 N 群 number; `_bind_customer_groups` judges it against
            # the groups this prompt listed (it is ignored when none were listed).
            validated_ads.append({
                "name": ad_name, "coordinates": coords, "scene": scene,
                "customer_group": ad.get("customer_group"),
                "slot_id": ad.get("slot_id"),
            })
        validated_groups.append({"role": role, "name": name.strip(), "ads": validated_ads})

    # 角色不能多；不能少——除非那個角色已經有沿用的廣告（department file 的規則）。
    if not set(roles) - set(covered) <= seen_roles:
        return menu
    if limit is not None and sum(len(g["ads"]) for g in validated_groups) > limit:
        return menu
    if not _scenes_differ_across_audiences(validated_groups):
        return invalid
    return validated_groups, None


def _bind_customer_groups(groups: list, listed: list, menu_pain_keys: set) -> bool:
    """F46 Contract A. `listed` = the 【這個賣法的顧客】 groups in prompt order (第 N 群 =
    `listed[N-1]`). No group listed -> every ad's `customer_group` becomes `None` (the key is
    ignored). Otherwise each ad needs an integer 1..N; its `pain` must be one of that group's
    `pain_keys` when that set meets the filtered menu's pain keys (else no pain check); and all
    ads of one delivery group carry the same group (one ad set = one set of people). On success
    each ad's `customer_group` is replaced by the group row; `False` = refuse the whole reply."""
    for group in groups:
        if not listed:
            for ad in group["ads"]:
                ad["customer_group"] = None
            continue
        bound_ids = set()
        for ad in group["ads"]:
            number = ad.get("customer_group")
            if isinstance(number, bool) or not isinstance(number, int):
                return False
            if not 1 <= number <= len(listed):
                return False
            customer_group = listed[number - 1]
            pains = set(customer_group.get("pain_keys") or [])
            if pains & menu_pain_keys and ad["coordinates"]["pain"] not in pains:
                return False
            bound_ids.add(customer_group["id"])
            ad["customer_group"] = customer_group
        if len(bound_ids) > 1:
            return False
    return True


def _builds_on_learnings(groups: list, replace_pairs: set) -> bool:
    """F46 Contract G, after `_bind_customer_groups`: an ad's (customer group, angle) pair may not
    be a 換掉 pair of the newest closed campaign. Ads without a group never match; `False` =
    refuse the whole reply. F48 Contract K: the keep half is met by construction -- the newest
    closed campaign's 留下 ads are carried in before the model is asked."""
    pairs = {
        (ad["customer_group"]["id"], ad["coordinates"]["angle"])
        for group in groups for ad in group["ads"] if ad.get("customer_group") is not None
    }
    return not pairs & replace_pairs


def _same_people_as_carried(groups: list, carried: list) -> bool:
    """F46 Contract A (one ad set = one set of people) across carried and planned ads: a reply
    group whose role holds carried ads bound to one customer group binds that group too."""
    carried_groups: dict = {}
    for item in carried:
        if item["ad"].get("customer_group_id"):
            carried_groups.setdefault(item["target"], set()).add(item["ad"]["customer_group_id"])
    for group in groups:
        ids = carried_groups.get(group["role"])
        if not ids or len(ids) > 1:
            continue
        for ad in group["ads"]:
            if ad.get("customer_group") is not None and ad["customer_group"]["id"] not in ids:
                return False
    return True


def _checked_groups(groups: list, task_id: str | None, *, vocabulary_rows: list, ctx: dict,
                    carried: list, listed_groups: list, replace_pairs: set) -> list:
    """The program's rules over a shape-valid reply (`groups`, `[]` when nothing was asked),
    in this order; the first rule broken raises its `PlannerRefused` and nothing is written."""
    _gate_reply(groups, _vocabulary_lookup(vocabulary_rows), _first_format(vocabulary_rows))
    # Contract S permits an explicitly accepted no-offer test. _match_slots still requires
    # each generated ad to retain the exact accepted offer, including none.
    # F48 Contract P: an ad name carrying a 「不能講」 entry is refused like the scene rule.
    if any(_forbidden_in(ad["name"], ctx["forbidden"]) for group in groups for ad in group["ads"]):
        raise _refused("name_forbidden", task_id)
    menu_pain_keys = {row["key"] for row in vocabulary_rows if row["dimension"] == "pain"}
    if not _bind_customer_groups(groups, listed_groups, menu_pain_keys):
        raise _refused("group_unbound", task_id)
    if not _same_people_as_carried(groups, carried):
        raise _refused("carried_changed", task_id)
    # F46 Contract G: never re-run a 換掉 customer group + angle unchanged (the keep half is met
    # by the carried ads).
    if not _builds_on_learnings(groups, replace_pairs):
        raise _refused("replace_rerun", task_id)
    return groups


MATERIALS_HEADER = "【手上的素材】"
_USER_ASSET_PAGE_GUARD = 100  # pages of 100 rows; a brand with >10 000 originals is not real


def _ready_user_asset_mimes(conn, org_id: str, brand_id: str) -> list[str]:
    """`mime_type` of the brand's ready ads user assets, read page by page through the
    user-asset repository (its own cursor); an empty mime comes back as ''."""
    mimes: list[str] = []
    after = None
    for _ in range(_USER_ASSET_PAGE_GUARD):
        page = user_assets_repository.list_assets(conn, org_id, brand_id, after=after)
        mimes.extend(
            str(row.get("mime_type") or "") for row in page["assets"]
            if row.get("status") == "ready"
        )
        after = page["next_cursor"]
        if after is None:
            break
    return mimes


def _materials_text(conn, org_id: str, brand_id: str) -> str:
    """F46 Contract P: 「照片 N 張、影片 M 支」. Photos = the brand's active official assets other
    than `logo` plus its ready user assets whose mime is set and not `video/*`; videos = ready
    user assets with a `video/*` mime. An unready asset or one with no mime is not counted."""
    official = [
        row for row in bi_repo.list_official_assets(conn, brand_id)
        if row.get("status") == "active" and row.get("asset_kind") != "logo"
    ]
    mimes = _ready_user_asset_mimes(conn, org_id, brand_id)
    videos = sum(1 for mime in mimes if mime.startswith("video/"))
    photos = len(official) + sum(1 for mime in mimes if mime and not mime.startswith("video/"))
    return f"{MATERIALS_HEADER}照片 {photos} 張、影片 {videos} 支"


def _snapshot(ad: dict, vocab_lookup: dict) -> dict:
    """The seven vocabulary rows, plus `customer_group: {id, who}` when the ad is bound (F46)."""
    snapshot = {
        dim: vocab_lookup.get((dim, key), {"key": key}) for dim, key in ad["coordinates"].items()
    }
    customer_group = ad.get("customer_group")
    if customer_group is not None:
        snapshot["customer_group"] = {"id": customer_group["id"], "who": customer_group["who"]}
    return snapshot


def _role_amounts(allocation: list[dict], daily_total: int) -> dict:
    """role -> whole daily amount: `budget.split` of `daily_total` by the allocation pcts (sums
    exactly to `daily_total`)."""
    weights = {str(i): (row["pct"] or 0) / 100 for i, row in enumerate(allocation)}
    amounts_by_index = {row["label"]: row["amount"] for row in budget.split(daily_total, weights)}
    return {allocation[i]["role"]: amounts_by_index[str(i)] for i in range(len(allocation))}


def resplit_groups(
    conn, org_id: str, brand_id: str, campaign: dict, total,
) -> tuple[list, float]:
    """F48 decision 8: a new total chosen after adoption re-splits every ad set's daily budget by
    the stored allocation pcts (`budget.resplit` of `budget.daily_of(total, days)`). Only on a
    `ready` campaign whose groups are all unbound (`ValueError("campaign_bound")` otherwise: a live
    ad set changes through the change list); the approval ceiling applies. Both checks run before
    any write. Returns (`[{group_id, role, before, after}]`, the new `budget_planned` =
    `total_of(Σ group daily, days)` -- adopt's rounding; the caller stores it)."""
    campaign_id = campaign["id"]
    groups = ads_repo.list_groups(conn, org_id, brand_id, campaign_id)
    if campaign["status"] != "ready" or any(g["local_state"] != "unbound" for g in groups):
        raise ValueError("campaign_bound")
    days = _days(campaign["start_date"], campaign["end_date"])
    if days <= 0:
        raise ValueError("dates_required")
    daily_total = budget.daily_of(total, days)
    assert daily_total is not None  # a known total over a positive length
    _check_budget_ceiling(conn, org_id, brand_id, campaign_id, daily_total)
    allocation = ((campaign.get("budget_basis_json") or {}).get("strategy") or {}).get(
        "allocation") or []
    after = budget.resplit(daily_total, groups, allocation)
    changes = []
    for group in groups:
        before = float(group["daily_budget"])
        ads_repo.update_group_fields(
            conn, org_id, brand_id, group["id"], {"daily_budget": after[group["id"]]},
        )
        changes.append({
            "group_id": group["id"], "role": group["role"],
            "before": int(before) if before.is_integer() else before, "after": after[group["id"]],
        })
    new_planned = budget.total_of(sum(after.values()), days)
    assert new_planned is not None  # a whole daily over a positive length
    return changes, new_planned


CARRIED_HEADER = "【已沿用的廣告】"
_CARRIED_NONE = "（上一期沒有留下的廣告可以沿用）"


def _ceiling(capacity: dict | None) -> int:
    """Contract C: the most ads this plan may hold -- `capacity.ceiling` (`max(can_support + 1,
    roles)`), or `_MAX_GROUPS × _MAX_ADS_PER_GROUP` when the cap or the budget is unknown."""
    return capacity["ceiling"] if capacity is not None else _MAX_GROUPS * _MAX_ADS_PER_GROUP


def _target_role(previous_role: str | None, role_order: list[str]) -> str:
    """Contract K: the new group whose role equals the previous ad's group role; a role this
    plan did not adopt goes to the `new` group, else the first adopted group."""
    if previous_role is not None and previous_role in role_order:
        return previous_role
    raise ValueError("strategy_infeasible")


def _select_carried(kept: list[dict], role_order: list[str], ceiling: int) -> list[dict]:
    """Contract K + C: the 留下 rows (rank order) that become carried ads, each with its
    `target` role. A row is taken while its group has room (`_MAX_ADS_PER_GROUP`) and the
    ceiling still leaves one ad for every adopted role no carried ad covers -- so the model can
    always complete the plan inside the ceiling."""
    chosen: list[dict] = []
    per_role: dict = {}
    for item in kept:
        role = _target_role(item["role"], role_order)
        if per_role.get(role, 0) >= _MAX_ADS_PER_GROUP:
            continue
        uncovered = set(role_order) - set(per_role) - {role}
        if len(chosen) + 1 + len(uncovered) > ceiling:
            continue
        chosen.append({**item, "target": role})
        per_role[role] = per_role.get(role, 0) + 1
    return chosen


def _carried_text(carried: list[dict], listed: list[dict], remaining: int) -> str:
    """【已沿用的廣告】: one line per carried ad -- name, delivery group role, customer group
    (第 N 群 of this prompt's list, 「未指定」, or 「這期沒列」) and the seven coordinate keys --
    then 「請再規劃 K 則」. Nothing carried -> one line saying so (and no K line)."""
    if not carried:
        return CARRIED_HEADER + _CARRIED_NONE
    numbers = {group["id"]: n for n, group in enumerate(listed, start=1)}
    lines = [CARRIED_HEADER + "（程式已經放進投放組，名稱和七個座標照上一期，不要再寫一次）"]
    for item in carried:
        ad = item["ad"]
        group_id = ad.get("customer_group_id")
        if group_id is None:
            who = "未指定"
        else:
            who = str(numbers[group_id]) if group_id in numbers else "這期沒列"
        keys = "、".join(
            f"{dim}={ad.get(f'{dim}_key') or 'none'}" for dim in _COORDINATE_DIMENSIONS
        )
        lines.append(f"- 「{ad['name']}」｜投放組 {item['target']}｜顧客群 {who}｜{keys}")
    lines.append(f"請再規劃 {remaining} 則")
    return "\n".join(lines)


def _capacity_text(capacity: dict | None, ceiling: int) -> str:
    """【這期撐得起幾則】: the capacity line (daily, can_support, the explore slot, the ceiling,
    the cap); unknown cap or budget -> no capacity line, only the plan's upper bound."""
    if capacity is not None:
        return planner_context.section_text({"capacity": capacity}, "capacity")
    return (planner_context.CAPACITY_HEADER + "\n" + planner_context.capacity_line(None)
            + f"；這期最多 {ceiling} 則")


def _carried_snapshot(previous: dict, lookup: dict) -> dict:
    """The carried ad's `coordinates_snapshot_json`: the seven vocabulary rows of the previous
    keys, the previous customer group entry, and `carried_from` (Contract K, no migration)."""
    snapshot: dict = {
        dim: lookup.get((dim, previous.get(f"{dim}_key")), {"key": previous.get(f"{dim}_key")})
        for dim in _COORDINATE_DIMENSIONS
    }
    group = (previous.get("coordinates_snapshot_json") or {}).get("customer_group")
    if previous.get("customer_group_id") and group:
        snapshot["customer_group"] = group
    snapshot["carried_from"] = {"campaign_id": previous["campaign_id"], "ad_id": previous["id"]}
    if previous.get("native_ref"):
        snapshot["carried_from"]["native_ref"] = previous["native_ref"]
        snapshot["carried_from"]["entity_id"] = previous["native_ref"]["id"]
        if previous["id"] == previous["native_ref"]["id"]:
            snapshot["carried_from"].pop("ad_id")
    return snapshot


def served(conn, org_id: str, brand_id: str, campaign: dict) -> dict:
    """The campaign payload's plan fields (F48-I06; the structure editor reads them):
    `menu` = this period's coordinate menu `[{dimension, key, label}]` (`planner_context.menu`,
    the rows the delivery plan offered and the hand edits accept) and `capacity` = `{daily, cap,
    can_support, ceiling, carried}` (Contract C; `None` while the cap or the budget is unknown).
    Both `None` on an imported campaign (no plan of ours)."""
    if campaign.get("origin") == "imported":
        return {"menu": None, "capacity": None}
    rows = planner_context.menu(
        conn, org_id, brand_id, sell_way_mod.of_campaign(campaign),
        campaign.get("end_date") is not None,
    )["rows"]
    cap = (campaign.get("cap") or {}).get("value")
    daily = budget.daily_of(campaign.get("budget_planned"),
                            _days(campaign.get("start_date"), campaign.get("end_date")))
    capacity = planner_context.capacity_of(daily, cap)
    if capacity is not None:
        capacity["carried"] = sum(
            1 for group in campaign.get("groups") or [] for ad in group.get("ads") or []
            if ad.get("carried_label")
        )
    return {
        "menu": [{"dimension": r["dimension"], "key": r["key"], "label": r["label"]}
                 for r in rows],
        "capacity": capacity,
    }


class StrategyConflict(ValueError):
    """An actionable revision exit, with feasibility details for the API."""
    def __init__(self, code, reasons=()):
        super().__init__(code)
        self.reasons = list(reasons)


def _checked_decision(conn, org, brand, campaign, expected_revision):
    from app.ads import strategy
    payload = (campaign.get("budget_basis_json") or {}).get("strategy") or {}
    decision = payload.get("decision")
    if not expected_revision or not decision or decision.get("schema_version") != 1:
        raise StrategyConflict("strategy_confirmation_required")
    if decision["revision"] != expected_revision:
        raise StrategyConflict("strategy_changed")
    scenarios = (campaign.get("budget_basis_json") or {}).get("scenarios") or {}
    key = campaign.get("budget_scenario")
    row = next((r for r in scenarios.get("scenarios", []) if r["key"] == key), None)
    if ((key == "retain" and (row is None or row.get("currency") != "TWD"))
            or (row and row.get("currency") not in {None, "TWD"})
            or (row and scenarios.get("mode") == "cold_start" and key != budget.CAP_KEY
                and row.get("total") is None)):
        raise StrategyConflict("strategy_changed")
    refreshed = {**payload}
    strategy.refresh_decision(conn, org, brand, campaign, refreshed)
    current = refreshed["decision"]
    if current["feasibility"]["state"] == "blocked":
        raise StrategyConflict("strategy_infeasible", current["feasibility"]["reasons"])
    if current["revision"] != expected_revision:
        raise StrategyConflict("strategy_changed")
    return decision


def _match_slots(groups, slots):
    """Delivery may fill creative details; it cannot replace any accepted binding."""
    planned = {s["id"]: s for s in slots if not s["carry_from_ad_id"]}
    seen = set()
    for group in groups:
        for ad in group["ads"]:
            sid = ad.get("slot_id")
            slot = planned.get(sid)
            gid = (ad.get("customer_group") or {}).get("id")
            if (not slot or sid in seen or slot["role"] != group["role"]
                    or slot["customer_group_id"] != gid
                    or slot["offer_key"] != ad["coordinates"]["offer"]):
                raise StrategyConflict("strategy_infeasible", [{
                    "code": "delivery_binding_changed",
                    "message": "生成的投放安排與你確認的策略不同，請修訂後再確認。",
                    "slot_ids": [sid] if sid else [],
                }])
            seen.add(sid)
    if seen != set(planned):
        raise StrategyConflict("strategy_infeasible", [{
            "code": "delivery_slot_missing", "message": "生成結果漏了已確認的安排，請重試。",
            "slot_ids": sorted(set(planned) - seen),
        }])


def _persist_decision(conn, org, brand, campaign, decision, groups, carried, allocation,
                      daily_total, days, vocab_lookup, actor, operation_id):
    """All groups, ads, carry placements and the receipt share one transaction."""
    from app.ads import slots
    campaign_id = campaign["id"]
    amounts = _role_amounts(allocation, daily_total)
    by_role = {g["role"]: g for g in groups}
    full_lookup = _vocabulary_lookup(ads_repo.coordinate_vocabulary(conn, org, brand))
    platform = (campaign.get("constraints_json") or {}).get("platform")
    channel = channels.default_channel_key(conn, org, brand, platform)
    receipt = {"revision": decision["revision"], "operation_id": operation_id, "slots": []}
    conn.execute("SAVEPOINT ads_strategy_adoption")
    try:
        for row in allocation:
            role = row["role"]
            planned = by_role.get(role) or {}
            group = ads_repo.create_group(conn, org, brand, campaign_id, channel_key=channel,
                                          name=planned.get("name") or f"{row['label']}組",
                                          role=role, daily_budget=amounts[role])
            for item in carried:
                if item["target"] != role:
                    continue
                prior = item["ad"]
                snapshot = _carried_snapshot(prior, full_lookup)
                snapshot["carried_from"].update({
                    "placement_id": item["creative"].get("placement_id"),
                    "placement_revision": item["creative"].get("placement_revision"),
                })
                snapshot["strategy_slot"] = {"slot_id": item["slot_id"],
                                              "revision": decision["revision"]}
                ad = ads_repo.create_ad(conn, org, brand, campaign_id, group["id"],
                        name=prior["name"],
                        coordinates={d: prior.get(f"{d}_key") for d in _COORDINATE_DIMENSIONS},
                        coordinates_snapshot=snapshot, scene=prior.get("scene"),
                        customer_group_id=prior.get("customer_group_id"))
                creative = item["creative"]
                slots.carry(conn, org, brand, campaign_id, ad["id"], creative["asset_id"],
                            creative["copy_fields"], actor, atomic=True)
                receipt["slots"].append({"slot_id": item["slot_id"], "group_id": group["id"],
                                         "ad_id": ad["id"], "carry_from_ad_id": prior["id"]})
            for planned_ad in planned.get("ads") or []:
                snapshot = _snapshot(planned_ad, vocab_lookup)
                snapshot["strategy_slot"] = {"slot_id": planned_ad["slot_id"],
                                             "revision": decision["revision"]}
                ad = ads_repo.create_ad(conn, org, brand, campaign_id, group["id"],
                        name=planned_ad["name"], coordinates=planned_ad["coordinates"],
                        coordinates_snapshot=snapshot, scene=planned_ad["scene"],
                        customer_group_id=(planned_ad.get("customer_group") or {}).get("id"))
                receipt["slots"].append({"slot_id": planned_ad["slot_id"], "group_id": group["id"],
                                         "ad_id": ad["id"], "carry_from_ad_id": None})
        basis = campaign["budget_basis_json"]
        payload = {**basis["strategy"], "decision": {**decision, "state": "adopted",
                                                    "receipt": receipt}}
        ads_repo.save_strategy(conn, org, brand, campaign_id,
                                budget_basis_json={**basis, "strategy": payload})
        ads_repo.set_budget_planned(conn, org, brand, campaign_id,
                                   budget_planned=budget.total_of(sum(amounts.values()), days))
        ads_repo.set_campaign_status(conn, org, brand, campaign_id, "ready")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT ads_strategy_adoption")
        conn.execute("RELEASE SAVEPOINT ads_strategy_adoption")
        raise
    conn.execute("RELEASE SAVEPOINT ads_strategy_adoption")
    conn.commit()


def adopt_strategy(conn, org_id: str, brand_id: str, campaign_id: str, *, actor: str,
                   expected_revision: str | None = None, operation_id: str | None = None) -> dict:
    """Adopt exactly the displayed decision, or replay its successful operation receipt.

    Resolve every carry before generation. Gateway IO finishes before the campaign write lock;
    the accepted slots, placements and receipt are then persisted in one transaction."""
    ads_repo.require_internal_campaign(conn, org_id, brand_id, campaign_id)
    campaign = ads_repo.get_campaign(conn, org_id, brand_id, campaign_id)
    if campaign is None:
        raise ValueError("campaign_unknown")
    if not isinstance(operation_id, str) or not operation_id.strip() or len(operation_id) > 128:
        raise StrategyConflict("strategy_confirmation_required")
    saved = ((campaign.get("budget_basis_json") or {}).get("strategy") or {}).get("decision") or {}
    receipt = saved.get("receipt") or {}
    if (saved.get("state") == "adopted" and receipt.get("operation_id") == operation_id
            and receipt.get("revision") == expected_revision):
        detail = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)
        assert detail is not None
        return detail
    decision = _checked_decision(conn, org_id, brand_id, campaign, expected_revision)
    if campaign["status"] != "draft":
        raise StrategyConflict("strategy_changed")

    budget_basis = campaign.get("budget_basis_json") or {}
    strategy_payload = budget_basis.get("strategy")
    if not strategy_payload or campaign.get("budget_planned") is None:
        raise ValueError("strategy_not_adopted")
    allocation = strategy_payload["allocation"]
    roles = {row["role"] for row in allocation}
    role_order = list(dict.fromkeys(row["role"] for row in allocation))

    days = _days(campaign["start_date"], campaign["end_date"])
    if days <= 0:
        raise ValueError("dates_required")
    # F48 Contract M: the whole daily the chosen total buys (`floor`, never above the total).
    daily_total = budget.daily_of(campaign["budget_planned"], days)
    assert daily_total is not None  # `budget_planned` and a positive length were checked above
    _check_budget_ceiling(conn, org_id, brand_id, campaign_id, daily_total)

    # F48 Contract P: one context -- the menu (F42: offers judged against the campaign's
    # sell-way; `None` = brand level), the 「不能講」 list, the customer groups, the ranking and
    # the capacity line all come from `planner_context`.
    sell_way = sell_way_mod.of_campaign(campaign)
    ctx = planner_context.planner_context(conn, org_id, brand_id, sell_way, campaign=campaign)
    vocabulary_rows = ctx["menu"]
    vocab_lookup = _vocabulary_lookup(vocabulary_rows)
    listed_groups = ctx["customer_groups"]
    customer_group_ids = [group["id"] for group in listed_groups]

    # F48 Contracts C + K: the ceiling, and last period's 留下 ads carried in before the model.
    ceiling = _ceiling(ctx["capacity"])
    candidates = {i["ad"]["id"]: i for i in ctx["carried_candidates"]}
    if any(s["carry_from_ad_id"] and s["carry_from_ad_id"] not in candidates
           for s in decision["slots"]):
        raise StrategyConflict("strategy_changed")
    carried = [{**candidates[s["carry_from_ad_id"]], "target": s["role"], "slot_id": s["id"]}
               for s in decision["slots"] if s["carry_from_ad_id"]]
    remaining = len(decision["slots"]) - len(carried)
    covered = {item["target"] for item in carried}
    room = {
        role: _MAX_ADS_PER_GROUP - sum(1 for item in carried if item["target"] == role)
        for role in role_order
    }

    allocation_text = "\n".join(
        f"- {row['role']}（{row['label']}）：{row['pct']:g}%"
        + (f"，{row['rationale']}" if row.get("rationale") else "")
        for row in allocation
    )
    department_text = DEPARTMENT_PATH.read_text(encoding="utf-8")
    # F33-I02（Contract Q）：行事曆接在角色分配那幾行之後——那幾行的格式是 Contract P，不動。
    # F48-I06：其後依序是這個賣法、不能講、顧客群、優惠、排名、手上的素材、撐得起幾則、
    # 已沿用的廣告；詞彙表永遠最後，模型答題前最後讀到的是可用的 key。
    prompt_head = (
        department_text
        + "\n\n## 這次投放已採用的角色分配\n\n" + allocation_text
        + "\n\n" + calendar_tw.prompt_section(campaign["start_date"], campaign["end_date"])
        + "\n\n" + planner_context.section_text(ctx, "product")
        + "\n\n" + planner_context.section_text(ctx, "forbidden")
        + "\n\n" + planner_context.section_text(ctx, "customers")
        + "\n\n" + planner_context.section_text(ctx, "offers")
        + "\n\n" + planner_context.section_text(ctx, "ranked")
        + "\n\n" + _materials_text(conn, org_id, brand_id)
        + "\n\n" + _capacity_text(ctx["capacity"], ceiling)
        + "\n\n" + _carried_text(carried, listed_groups, remaining)
        + "\n\n【已確認的新安排】\n" + json.dumps(
            [s for s in decision["slots"] if not s["carry_from_ad_id"]], ensure_ascii=False)
        + "\n\n【安排可用的顧客】\n" + json.dumps(listed_groups, ensure_ascii=False, default=str)
    )
    _, replace_pairs = coordinate_learning.gate_pairs(
        ctx["learnings"]["ranked"], set(customer_group_ids),
    )
    checks = {"vocabulary_rows": vocabulary_rows, "ctx": ctx, "carried": carried,
              "listed_groups": listed_groups, "replace_pairs": replace_pairs}

    def ask(refused: list[PlannerRefused]) -> list:
        # F50 (user ruling 2026-10-04): a retry carries the refusal just before the vocabulary,
        # which stays last.
        prompt = (prompt_head + ("\n\n" + refusal_section(refused) if refused else "")
                  + "\n\n" + _vocabulary_text(vocabulary_rows))
        context = gateway.TaskContext(
            context_scope={"brand_id": brand_id, "campaign_id": campaign_id},
            knowledge_item_ids=(
                [row["product_id"] for row in ctx["prices"]] + ctx["ranked_ids"]
                + customer_group_ids
            ),
            brand_version=(campaign.get("context_json") or {}).get("brand_version") or 0,
        )
        task_row = gateway.run_task(
            conn, PROVIDER, brand_id=brand_id, task_type="ads_delivery_plan",
            prompt_template_id="ads_delivery_plan", prompt_template_version="v1",
            system=None, messages=[{"role": "user", "content": prompt}], context=context,
            options=gateway.TaskOptions(max_tokens=2000, timeout_s=TIMEOUT_S, max_retries=0),
        )
        if task_row["status"] != "succeeded":
            raise PlannerRefused("delivery_plan_failed", "llm_failed",
                                 llm_failed_reason(task_row), task_row["id"])
        data = gateway.parse_json_reply(task_row.get("rendered_output") or "")
        if data is None:
            raise _refused("reply_unreadable", task_row["id"])
        validated, code = _check_reply(
            data, roles, covered=covered, room=room, limit=remaining,
            taken={item["ad"]["name"] for item in carried},
        )
        if validated is None:
            raise _refused(code or "reply_invalid", task_row["id"])
        checked = _checked_groups(validated, task_row["id"], **checks)
        _match_slots(checked, decision["slots"])
        return checked

    if remaining > 0:
        validated_groups = ask_with_one_retry(conn, ask, campaign_id=campaign_id)
    else:
        try:  # nothing for the model to plan: the program's own rules still judge the carried ads
            validated_groups = _checked_groups([], None, **checks)
        except PlannerRefused as exc:
            note_refusal(conn, exc, campaign_id=campaign_id, attempt=1)
            raise

    # The gateway commits its task before this final lock; no plan writes precede it.
    conn.execute("SELECT id FROM ads_campaign WHERE org_id=%s AND brand_id=%s AND id=%s "
                 "FOR UPDATE", (org_id, brand_id, campaign_id))
    current = ads_repo.get_campaign(conn, org_id, brand_id, campaign_id)
    if current is None:
        raise StrategyConflict("strategy_changed")
    saved = ((current.get("budget_basis_json") or {}).get("strategy") or {}).get("decision") or {}
    receipt = saved.get("receipt") or {}
    if (saved.get("state") == "adopted" and receipt.get("operation_id") == operation_id
            and receipt.get("revision") == expected_revision):
        detail = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)
        assert detail is not None
        return detail
    decision = _checked_decision(conn, org_id, brand_id, current, expected_revision)
    if current["status"] != "draft":
        raise StrategyConflict("strategy_changed")
    _match_slots(validated_groups, decision["slots"])
    _persist_decision(conn, org_id, brand_id, current, decision, validated_groups, carried,
                      allocation, daily_total, days, vocab_lookup, actor, operation_id)
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
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError("date_invalid") from None


def _check_date_order(start, end) -> None:
    """End ``>=`` start (`app.core.input_rules.date_order`); refused as `dates_reversed`, which
    the route maps to its sentence."""
    try:
        input_rules.date_order(start, end)
    except input_rules.InputRuleError:
        raise ValueError("dates_reversed") from None


class GroupDatesOutside(ValueError):
    """F50 Contract I (c1-08): an ad-set date outside its campaign's dates. `str()` is the code
    `group_dates_outside`; `sentence` is `input_rules.date_within`'s refusal naming the window."""

    def __init__(self, sentence: str):
        super().__init__("group_dates_outside")
        self.sentence = sentence


def _check_group_window(campaign: dict, *days) -> None:
    """Each given ad-set date lies inside the campaign's `start_date … end_date`
    (`input_rules.date_within`); an unset date, or an unset campaign side, is no bound."""
    for day in days:
        if day is None:
            continue
        try:
            input_rules.date_within(
                day, campaign.get("start_date"), campaign.get("end_date"), "投放組日期", "活動期間",
            )
        except input_rules.InputRuleError as exc:
            raise GroupDatesOutside(str(exc)) from None


def _check_daily_budget(value) -> None:
    """A group's daily budget: a number (never a bool or text) > 0 (`input_rules.positive`);
    refused as `daily_budget_invalid`, which the route maps to its sentence."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("daily_budget_invalid")
    try:
        input_rules.positive(value, "日預算")
    except input_rules.InputRuleError:
        raise ValueError("daily_budget_invalid") from None


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
        _check_daily_budget(value)
        if value > float(group["daily_budget"]):  # 只有「加碼」才過核准煞車，降預算不擋
            other_total = (
                ads_repo.group_budget_total(conn, org_id, brand_id, group["campaign_id"])
                - float(group["daily_budget"])
            )
            _check_budget_ceiling(conn, org_id, brand_id, group["campaign_id"], other_total + value)
    for field in ("start_date", "end_date"):
        if field in updates and updates[field] is not None:
            updates[field] = _parse_date(updates[field])
    if "start_date" in updates or "end_date" in updates:
        # F47 Contract A: the stored side counts when only one side is patched.
        _check_date_order(
            updates.get("start_date", group.get("start_date")),
            updates.get("end_date", group.get("end_date")),
        )
        campaign = ads_repo.get_campaign(conn, org_id, brand_id, group["campaign_id"]) or {}
        _check_group_window(campaign, updates.get("start_date"), updates.get("end_date"))

    before = {k: group.get(k) for k in updates}
    updated = ads_repo.update_group_fields(conn, org_id, brand_id, group_id, updates)
    if updates:
        ads_repo.invalidate_strategy_decision(conn, org_id, brand_id, group["campaign_id"])

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
    _check_daily_budget(daily_budget)
    _check_date_order(_parse_date(start_date), _parse_date(end_date))
    campaign = ads_repo.get_campaign(conn, org_id, brand_id, campaign_id)
    if campaign is None:
        raise ValueError("campaign_unknown")
    _check_group_window(campaign, _parse_date(start_date), _parse_date(end_date))
    other_total = ads_repo.group_budget_total(conn, org_id, brand_id, campaign_id)
    _check_budget_ceiling(conn, org_id, brand_id, campaign_id, other_total + daily_budget)
    declared_platform = (campaign.get("constraints_json") or {}).get("platform")
    channel_key = channels.default_channel_key(conn, org_id, brand_id, declared_platform)
    created = ads_repo.create_group(
        conn, org_id, brand_id, campaign_id, channel_key=channel_key, name=name.strip(),
        role=role, daily_budget=daily_budget, start_date=_parse_date(start_date),
        end_date=_parse_date(end_date),
    )
    ads_repo.invalidate_strategy_decision(conn, org_id, brand_id, campaign_id)
    return created


def delete_group(conn, org_id: str, brand_id: str, group_id: str) -> None:
    group = ads_repo.get_group(conn, org_id, brand_id, group_id)
    if group is None:
        raise ValueError("group_unknown")
    if group["local_state"] == "bound":
        raise ValueError("group_bound")
    ads_repo.delete_group(conn, org_id, brand_id, group_id)
    ads_repo.invalidate_strategy_decision(conn, org_id, brand_id, group["campaign_id"])


def _refuse_off_menu(excluded: dict, coordinates: dict) -> None:
    """F48 Contract P: a vocabulary key this period's menu leaves out (`planner_context.menu`'s
    `excluded`) is refused, naming the dimension and why; a key absent from the vocabulary passes
    as before (hand-made keys)."""
    for dim, key in coordinates.items():
        reason = excluded.get((dim, key))
        if reason is not None:
            raise CoordinateUnavailable(dim, key, reason)


def _refuse_forbidden_name(conn, org_id: str, brand_id: str, campaign: dict, name: str) -> None:
    """F48 Contract P／G: an ad name carrying an entry of this sell-way's 「不能講」 list."""
    terms = workbench.forbidden_terms(conn, org_id, brand_id, sell_way_mod.of_campaign(campaign))
    term = _forbidden_in(name, terms)
    if term is not None:
        raise NameForbidden(term)


def create_ad(conn, org_id: str, brand_id: str, campaign_id: str, group_id: str, *, name: str,
              coordinates: dict) -> dict:
    """A hand-made ad: seven coordinates, a name; the same menu and 「不能講」 list as the planner
    (`coordinate_unavailable`／`name_forbidden`)."""
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
    campaign = ads_repo.get_campaign(conn, org_id, brand_id, campaign_id)
    if campaign is None:
        raise ValueError("campaign_unknown")
    the_menu = planner_context.menu(
        conn, org_id, brand_id, sell_way_mod.of_campaign(campaign),
        campaign.get("end_date") is not None,
    )
    _refuse_off_menu(the_menu["excluded"], coords)
    _refuse_forbidden_name(conn, org_id, brand_id, campaign, name)
    vocabulary_rows = ads_repo.coordinate_vocabulary(conn, org_id, brand_id)
    vocab_lookup = _vocabulary_lookup(vocabulary_rows)
    snapshot = {dim: vocab_lookup.get((dim, key), {"key": key}) for dim, key in coords.items()}
    created = ads_repo.create_ad(
        conn, org_id, brand_id, campaign_id, group_id, name=name.strip(), coordinates=coords,
        coordinates_snapshot=snapshot,
    )
    ads_repo.invalidate_strategy_decision(conn, org_id, brand_id, campaign_id)
    return created


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
    campaign = ads_repo.get_campaign(conn, org_id, brand_id, ad["campaign_id"])
    if campaign is None:
        raise ValueError("ad_unknown")
    # F48 Contract P: only a key the edit changes is judged -- a key the ad already holds stays
    # (the editor shows it marked 「這期不能用」).
    the_menu = planner_context.menu(
        conn, org_id, brand_id, sell_way_mod.of_campaign(campaign),
        campaign.get("end_date") is not None,
    )
    _refuse_off_menu(the_menu["excluded"], {
        dim: value.strip() for dim, value in (updates.get("coordinates") or {}).items()
        if value.strip() != ad.get(f"{dim}_key")
    })
    if "name" in updates:
        _refuse_forbidden_name(conn, org_id, brand_id, campaign, updates["name"])

    before = {k: ad.get(k) for k in updates if k != "coordinates"}
    if "coordinates" in updates:
        before["coordinates"] = {
            dim: ad.get(f"{dim}_key") for dim in updates["coordinates"]
        }
    updated = ads_repo.update_ad_fields(conn, org_id, brand_id, ad_id, updates)
    if updates:
        ads_repo.invalidate_strategy_decision(conn, org_id, brand_id, ad["campaign_id"])

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
    ads_repo.invalidate_strategy_decision(conn, org_id, brand_id, ad["campaign_id"])
