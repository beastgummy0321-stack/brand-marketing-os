"""app/ads/coordinate_learning.py — F46 Contracts B and G: every closed campaign leaves a ranked
留下／換掉 list with its numbers, and both planners build on it (drill-10 root cause 1: the F39
grade rows tagged the 555 winner 太貴 beside 1,769, never entered the 290 winner under the sample
gate, and the next plan re-ran the themes it had just cut).

No model call:
- `write_coordinate_learnings` runs at closeout: the campaign's `period_grades.grade_period`
  rows over its window go through `learning_rank.rank` (the one rule), and every ranked ad gets
  one `source_track="coordinate"` learning whose `applicability_scope` is the `v=2` scope
  (`learning_rank.scope`: verdict, rank, sales, spend, cost per sale, cap, 樣本少, customer
  group, the seven coordinate keys -- format through `live_creative`'s learning coordinates).
  The owner-facing text names coordinates by label. `source_cycle_id = <campaign_id>:<ad_id>`
  keeps it idempotent per ad.
- `ranked_section` prints 【上幾期的排名】 for the strategy and delivery-plan prompts from
  `learning_view.learnings_view` (the same view the owner sees); `gate_pairs` gives the delivery
  plan's program gate its (customer group, angle) pairs.

Private to app/ads (container contract §1): only `closeout.py`, `plan.py` and `strategy.py`
import this. Ledger access goes through `app.brand_intelligence.repository`'s public functions.
"""

from typing import cast

from app.ads import customer_groups, learning_rank, learning_view, live_creative, period_grades
from app.ads import learning as ads_learning
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core.db import Conn, ConnProxy

_AnyConn = Conn | ConnProxy

SOURCE_TRACK = learning_view.SOURCE_TRACK
DIMENSIONS = learning_rank.DIMENSIONS
DIMENSION_LABELS = learning_rank.DIMENSION_LABELS
_MISSING_KEY = learning_rank.MISSING
_UNSET_LABEL = "未設定"
_UNASSIGNED_GROUP = "未指定"
# The planners read the newest three closed campaigns (Contract G).
PROMPT_CAMPAIGNS = 3


def _keys(ad: dict) -> dict:
    return {d: ad.get(f"{d}_key") or _MISSING_KEY for d in DIMENSIONS}


def _labels_text(keys: dict, labels: dict) -> str:
    """Owner-facing: 「受眾：陌生・知道問題、痛點：太麻煩…」; `none` coordinates are left out."""
    parts = [
        f"{DIMENSION_LABELS[d]}：{labels.get((d, keys[d]), keys[d])}"
        for d in DIMENSIONS if keys[d] != _MISSING_KEY
    ]
    return "、".join(parts) if parts else "座標未設定"


def _cap_text(cap) -> str:
    return "未設定" if cap is None else learning_rank.whole(cap)


def _flags_text(flags: list[str]) -> str:
    return f"（{'、'.join(flags)}）" if flags else ""


def _text(name: str, row: dict, who: str, keys: dict, labels: dict) -> str:
    """「第 r／n 名「〈ad〉」每筆 X（賣 s 筆、花 Y；上限 C）＝留下（樣本少）；顧客群：〈who〉；
    〈labels〉」; a 沒賣出 row reads 「沒賣出（花 Y；上限 C）」 in place of the numbers."""
    cap = _cap_text(row["cap"])
    spend = learning_rank.whole(row["spend"])
    if row["cost_per_sale"] is None:
        numbers = f"沒賣出（花 {spend}；上限 {cap}）"
    else:
        numbers = (
            f"每筆 {learning_rank.whole(row['cost_per_sale'])}"
            f"（賣 {row['sales']} 筆、花 {spend}；上限 {cap}）"
        )
    return (
        f"第 {row['rank']}／{row['of']} 名「{name}」{numbers}＝{row['verdict_label']}"
        f"{_flags_text(row['flags'])}；顧客群：{who}；{_labels_text(keys, labels)}"
    )


def _rows(conn: _AnyConn, brand_id: str) -> list[dict]:
    return bi_repo.list_learnings(
        cast(Conn, conn), brand_id, source_track=SOURCE_TRACK, limit=learning_view.SCAN_LIMIT,
    )


def write_coordinate_learnings(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str, *,
                               actor: str) -> list[dict]:
    """One `coordinate` learning per ranked ad of this campaign (Contract B over the campaign
    window). Unknown rows, ads not bound to a platform entity, and ads already written
    (`source_cycle_id`) write nothing. Returns the rows written this call."""
    detail = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)
    if detail is None:
        raise ValueError("campaign_unknown")
    start, end = detail.get("start_date"), detail.get("end_date")
    if start is None or end is None:
        return []
    # Same stance as the visual track: the coordinates the creatives went out with.
    detail = live_creative.with_learning_coordinates(conn, org_id, brand_id, detail)
    ads = [ad for group in detail["groups"] for ad in group["ads"]]
    if not ads:
        return []

    # Entity -> ad through `ads_ad.external_id = ads_external_entity.native_id` (the `_PERF_JOIN`
    # mapping), one read for the campaign's ad-kind entities.
    native_by_entity = {
        row["id"]: row["native_id"]
        for row in conn.execute(
            "SELECT id, native_id FROM ads_external_entity WHERE org_id = %s AND brand_id = %s"
            " AND campaign_id = %s AND native_kind = 'ad'",
            (org_id, brand_id, campaign_id),
        ).fetchall()
    }
    ad_by_native = {ad["external_id"]: ad for ad in ads if ad.get("external_id")}
    entries = []
    for row in period_grades.grade_period(conn, org_id, brand_id, start, end):
        if row["campaign_id"] != campaign_id:
            continue
        ad = ad_by_native.get(native_by_entity.get(row["entity_id"]))
        if ad is None:
            continue
        entries.append({**row, "name": ad.get("name") or row.get("name") or ad["id"], "ad": ad})
    ranked = learning_rank.rank(entries)
    if not ranked:
        return []

    existing = {row["source_cycle_id"] for row in _rows(conn, brand_id)}
    needs_revalidation = ads_learning._needs_revalidation(conn, brand_id, detail)  # noqa: SLF001
    labels = learning_view.vocabulary(conn, org_id, brand_id)
    groups = customer_groups.groups_by_id(conn, brand_id, detail)

    written: list[dict] = []
    for row in ranked:
        ad = row["ad"]
        cycle_id = f"{campaign_id}:{ad['id']}"
        if cycle_id in existing:
            continue
        keys = _keys(ad)
        group_id = ad.get("customer_group_id")
        if group_id is None:
            who = _UNASSIGNED_GROUP
        else:
            who = (groups.get(group_id) or {}).get("who") or learning_view.DELETED_GROUP
        written.append(bi_repo.record_learning(
            cast(Conn, conn), brand_id, actor=actor,
            learning_text=_text(row["name"], row, who, keys, labels),
            applicability_scope=learning_rank.scope(row, keys, group_id),
            confidence="observed",
            sample_size="低" if row["few"] or row["cost_per_sale"] is None else "高",
            source_cycle_id=cycle_id, source_track=SOURCE_TRACK,
            needs_revalidation=needs_revalidation,
        ))
        existing.add(cycle_id)
    return written


# -- planners ------------------------------------------------------------------------------------

HEADER = "【上幾期的排名（程式排的；每筆＝花費÷成交）】"
EMPTY_SECTION = "【上幾期的排名】（還沒有結案過的廣告）"


def prompt_view(conn: _AnyConn, org_id: str, brand_id: str) -> dict:
    """The view both planners prompt with: the newest `PROMPT_CAMPAIGNS` closed campaigns."""
    return learning_view.learnings_view(conn, org_id, brand_id, limit=PROMPT_CAMPAIGNS)


def _group_name(group: dict | None, numbers: dict) -> str:
    if group is None:
        return _UNASSIGNED_GROUP
    number = numbers.get(group["id"])
    return str(number) if number is not None else f"這期沒列：{group['who']}"


def _prompt_coordinates(row: dict, labels: dict) -> str:
    """`label（dim=key）` for all seven -- the model reads the words and can reuse the key."""
    keys = {c["dimension"]: c["key"] for c in row["coordinates"]}
    parts = []
    for d in DIMENSIONS:
        key = keys.get(d, _MISSING_KEY)
        label = _UNSET_LABEL if key == _MISSING_KEY else labels.get((d, key), key)
        parts.append(f"{label}（{d}={key}）")
    return "、".join(parts)


def _money_or(value, missing: str) -> str:
    return missing if value is None else learning_rank.whole(value)


def ranked_section(conn: _AnyConn, org_id: str, brand_id: str, campaign: dict, *,
                   view: dict | None = None,
                   listed: list[dict] | None = None) -> tuple[str, list[str]]:
    """Contract G: 【上幾期的排名】 text plus the learning ids it shows. Customer groups are
    numbered by this campaign's 【這個賣法的顧客】 (`listed`, read when omitted); a group the
    list does not carry reads 「這期沒列：〈who〉」, an ad without one 「未指定」. `view` = an
    already-read `prompt_view()` (strategy stores it), read here when omitted."""
    if view is None:
        view = prompt_view(conn, org_id, brand_id)
    ids = learning_view.learning_ids(view)
    if not ids:
        return EMPTY_SECTION, []
    if listed is None:
        _, listed = customer_groups.prompt_groups(conn, org_id, brand_id, campaign)
    numbers = {group["id"]: n for n, group in enumerate(listed, start=1)}
    labels = learning_view.vocabulary(conn, org_id, brand_id)

    lines = [HEADER]
    for group in view["groups"]:
        number = numbers.get(group["customer_group_id"])
        name = (
            f"第 {number} 群（{group['who']}）" if number is not None
            else f"這期沒列：{group['who']}"
        )
        lines.append(
            f"- 顧客群 {name}｜{group['ads']} 則廣告｜賣 {group['sales']} 筆"
            f"｜花 {learning_rank.whole(group['spend'])}"
            f"｜每筆 {_money_or(group['cost_per_sale'], '沒賣出')}"
            f"｜上限 {_cap_text(group['cap'])}"
        )
    for campaign_view in view["campaigns"]:
        lines.append(
            f"{campaign_view['campaign_name']}（上限 {_cap_text(campaign_view['cap'])}）："
            f"{campaign_view['rule_text'] or campaign_view['empty_reason']}"
        )
        for row in campaign_view["rows"]:
            verdict = "・".join([row["verdict_label"], *row["flags"]])
            lines.append(
                f"- {campaign_view['campaign_name']}第 {row['rank']}／{row['of']} 名｜{verdict}"
                f"｜顧客群 {_group_name(row['customer_group'], numbers)}｜「{row['ad_name']}」"
                f"｜每筆 {_money_or(row['cost_per_sale'], '沒賣出')}｜賣 {row['sales']} 筆"
                f"｜花 {learning_rank.whole(row['spend'])}｜{_prompt_coordinates(row, labels)}"
            )
    return "\n".join(lines), ids


def _angle(row: dict) -> str | None:
    return next((c["key"] for c in row["coordinates"] if c["dimension"] == "angle"), None)


def gate_pairs(view: dict, listed_ids: set) -> tuple[set, set]:
    """Contract G: `(keep_pairs, replace_pairs)` of (customer group id, angle key) over groups
    listed this time. keep = 留下 rows of the listed campaigns; replace = 換掉 rows of the newest
    closed campaign minus that campaign's own 留下 pairs. Rows with no group or angle never
    count."""

    def pairs(campaigns, keep: bool) -> set:
        found = set()
        for campaign_view in campaigns:
            for row in campaign_view["rows"]:
                group, angle = row["customer_group"], _angle(row)
                if group is None or angle is None or group["id"] not in listed_ids:
                    continue
                if learning_rank.is_keep(row["verdict"]) == keep:
                    found.add((group["id"], angle))
        return found

    campaigns = view["campaigns"]
    keep_pairs = pairs(campaigns, True)
    newest = campaigns[:1]
    replace_pairs = pairs(newest, False) - pairs(newest, True)
    return keep_pairs, replace_pairs
