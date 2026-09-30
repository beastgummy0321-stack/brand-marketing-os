"""app/ads/coordinate_learning.py — F39-I01: per-ad coordinate grades become learnings, and the
program tallies them into the scoreboard both planners read (drill-7 report §3 #1: the root cause
of the red items was that the coordinate-choosing model in `plan.py` received no learning at all
and strategy only the campaign sentence -- what the last campaign's ads did with which coordinates
never reached the next choice).

Two writers, no model call:
- `write_coordinate_learnings` runs at closeout: every ad the one ruler grades
  (`period_grades.grade_period` over the campaign window -- the month review's ruler and sample
  gate, never a second grading rule) gets one `source_track="coordinate"` learning whose
  `applicability_scope` carries the grade, the ad's cost per result and cap, and its seven
  coordinate keys:
  `coord；grade=<g>；cpr=<n>；cap=<n>；audience=<k>；pain=<k>；angle=<k>；hook=<k>；proof=<k>；offer=<k>；format=<k>`
  (a missing key or number reads `none`; rows written before F41-I02 have no `cpr`/`cap` and
  read back as `None`). The owner-facing `learning_text` names each coordinate by its label
  (drill-8 #11), never by key. Ungraded ads (資料不足／剛開始／未判斷) write nothing.
  `source_cycle_id = <campaign_id>:<ad_id>` keeps it idempotent per ad.
- `scoreboard` / `scoreboard_section` read those rows back into per-dimension tallies plus the
  last closed campaign's 划算 and 太貴／沒賣出 ads with their coordinates (prompt lines print
  `label（dim=key）`); `learning_rows` turns those same ads into the labelled rows the strategy
  basis shows (「用到的學習」). The bias toward reusing a
  划算 combination is a prompt rule in the department files, not a gate here (CLAUDE.md
  「程式整理，LLM 判斷」).

Private to app/ads (container contract §1): only `closeout.py`, `plan.py` and `strategy.py`
import this. Ledger access goes through `app.brand_intelligence.repository`'s public functions;
this module never touches `learning_ledger` directly.
"""

from typing import cast

from app.ads import learning as ads_learning
from app.ads import live_creative, period_grades
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core.db import Conn, ConnProxy

_AnyConn = Conn | ConnProxy

SOURCE_TRACK = "coordinate"
_SCOPE_PREFIX = "coord"
_GRADED = ("on_target", "watch", "over", "wasted")
_GRADE_LABELS = {"on_target": "划算", "watch": "偏貴", "over": "太貴", "wasted": "沒賣出"}
_BAD = ("over", "wasted")
_MISSING_KEY = "none"
# Same ceiling as `visual_learning.py` / `ads_learnings.py`'s idempotency scans.
_SCAN_LIMIT = 500

# `audience, pain, angle, hook, proof, offer, format` -- the seven learning coordinates, in the
# order `learning._applicability_scope` reads them (`*_key` on a `with_learning_coordinates` ad).
DIMENSIONS = tuple(d.removesuffix("_key") for d in ads_learning._COORDINATE_DIMENSIONS)  # noqa: SLF001


def _keys(ad: dict) -> dict:
    return {d: ad.get(f"{d}_key") or _MISSING_KEY for d in DIMENSIONS}


# The dimension names the owner reads (drill-8 #11: no English codes on screen or in stored text).
DIMENSION_LABELS = {
    "audience": "受眾", "pain": "痛點", "angle": "角度", "hook": "標題", "proof": "證據",
    "offer": "優惠", "format": "格式",
}
_UNSET_LABEL = "未設定"


def _vocabulary(conn: _AnyConn, org_id: str, brand_id: str) -> dict:
    """`{(dimension, key): label}` from the brand vocabulary; `_label` falls back to the key."""
    return {
        (row["dimension"], row["key"]): row["label"]
        for row in ads_repo.coordinate_vocabulary(conn, org_id, brand_id)
    }


def _label(labels: dict, dim: str, key: str) -> str:
    return labels.get((dim, key), key)


def _keys_text(keys: dict, joiner: str) -> str:
    return joiner.join(f"{d}={keys[d]}" for d in DIMENSIONS)


def _labels_text(keys: dict, labels: dict) -> str:
    """Owner-facing: 「受眾：陌生・知道問題、痛點：太麻煩…」; `none` coordinates are left out."""
    parts = [
        f"{DIMENSION_LABELS[d]}：{_label(labels, d, keys[d])}"
        for d in DIMENSIONS if keys[d] != _MISSING_KEY
    ]
    return "、".join(parts) if parts else "座標未設定"


def _prompt_coordinates(keys: dict, labels: dict) -> str:
    """Planner-facing: `label（dim=key）` -- the model reads the words and can still reuse the
    key verbatim."""
    return "、".join(
        f"{_UNSET_LABEL if keys[d] == _MISSING_KEY else _label(labels, d, keys[d])}"
        f"（{d}={keys[d]}）"
        for d in DIMENSIONS
    )


def _money(value) -> str:
    return "—" if value is None else str(ads_learning._number(float(value)))  # noqa: SLF001


def _scope_number(value) -> str:
    return _MISSING_KEY if value is None else _money(value)


def _parse_number(value: str | None):
    if value is None or value == _MISSING_KEY:
        return None
    try:
        return ads_learning._number(float(value))  # noqa: SLF001
    except ValueError:
        return None


def _scope(grade: str, keys: dict, cost_per_result=None, cap=None) -> str:
    return (
        f"{_SCOPE_PREFIX}；grade={grade}；cpr={_scope_number(cost_per_result)}"
        f"；cap={_scope_number(cap)}；{_keys_text(keys, '；')}"
    )


def _parse_scope(scope: str) -> dict | None:
    """Inverse of `_scope`: `{grade, keys, cost_per_result, cap}`, or `None` for a row that is
    not ours. A row without `cpr`/`cap` (written before F41-I02) reads them as `None`."""
    parts = scope.split("；")
    if not parts or parts[0] != _SCOPE_PREFIX:
        return None
    fields = {}
    for part in parts[1:]:
        name, sep, value = part.partition("=")
        if sep:
            fields[name] = value
    grade = fields.get("grade")
    if grade not in _GRADED:
        return None
    return {
        "grade": grade,
        "keys": {d: fields.get(d, _MISSING_KEY) for d in DIMENSIONS},
        "cost_per_result": _parse_number(fields.get("cpr")),
        "cap": _parse_number(fields.get("cap")),
    }


def _text(ad_name: str, row: dict, keys: dict, labels: dict) -> str:
    return (
        f"「{ad_name}」每筆 {_money(row['cost_per_result'])}（上限 {_money(row['cap'])}）"
        f"＝{_GRADE_LABELS[row['grade']]}；{_labels_text(keys, labels)}"
    )


def _rows(conn: _AnyConn, brand_id: str) -> list[dict]:
    return bi_repo.list_learnings(
        cast(Conn, conn), brand_id, source_track=SOURCE_TRACK, limit=_SCAN_LIMIT,
    )


def write_coordinate_learnings(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str, *,
                               actor: str) -> list[dict]:
    """One `coordinate` learning per ad of this campaign the one ruler grades over the campaign
    window. Skips ungraded rows, ads not bound to a platform entity, and ads already written
    (`source_cycle_id`). Returns the rows written this call."""
    detail = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)
    if detail is None:
        raise ValueError("campaign_unknown")
    start, end = detail.get("start_date"), detail.get("end_date")
    if start is None or end is None:
        return []
    # Same stance as the visual track: the coordinates the creatives were made for.
    detail = live_creative.with_learning_coordinates(conn, org_id, brand_id, detail)
    ads = [ad for group in detail["groups"] for ad in group["ads"]]
    if not ads:
        return []

    graded = [
        row for row in period_grades.grade_period(conn, org_id, brand_id, start, end)
        if row["campaign_id"] == campaign_id and row["grade"] in _GRADED
    ]
    if not graded:
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
    existing = {row["source_cycle_id"] for row in _rows(conn, brand_id)}
    needs_revalidation = ads_learning._needs_revalidation(conn, brand_id, detail)  # noqa: SLF001
    labels = _vocabulary(conn, org_id, brand_id)

    written: list[dict] = []
    for row in graded:
        ad = ad_by_native.get(native_by_entity.get(row["entity_id"]))
        if ad is None:
            continue
        cycle_id = f"{campaign_id}:{ad['id']}"
        if cycle_id in existing:
            continue
        keys = _keys(ad)
        written.append(bi_repo.record_learning(
            cast(Conn, conn), brand_id, actor=actor,
            learning_text=_text(ad.get("name") or row.get("name") or ad["id"], row, keys, labels),
            applicability_scope=_scope(
                row["grade"], keys, row.get("cost_per_result"), row.get("cap"),
            ),
            confidence="observed",
            sample_size="高" if row["grade"] in ("on_target", "watch", "over") else "低",
            source_cycle_id=cycle_id, source_track=SOURCE_TRACK,
            needs_revalidation=needs_revalidation,
        ))
        existing.add(cycle_id)
    return written


def _split_cycle(source_cycle_id: str | None) -> tuple[str, str] | None:
    if not source_cycle_id:
        return None
    campaign_id, sep, ad_id = source_cycle_id.rpartition(":")
    if not sep or not campaign_id or not ad_id:
        return None
    return campaign_id, ad_id


def scoreboard(conn: _AnyConn, org_id: str, brand_id: str) -> dict:
    """`{tally, last, learning_ids}` over the brand's live `coordinate` rows: `tally[dim][key]` =
    the four grade counts (a `none` key -- no coordinate to reuse -- is not tallied); `last` = the
    latest closed campaign (`closed_at desc`) that has rows, with its 划算 ads and its 太貴／沒賣出
    ads and their coordinates, `None` when no closed campaign has rows."""
    parsed = []
    for row in _rows(conn, brand_id):
        found = _parse_scope(row["applicability_scope"] or "")
        cycle = _split_cycle(row.get("source_cycle_id"))
        if found is None or cycle is None:
            continue
        parsed.append({"id": row["id"], **found, "campaign_id": cycle[0], "ad_id": cycle[1]})

    tally: dict = {}
    for item in parsed:
        for dim in DIMENSIONS:
            key = item["keys"][dim]
            if key == _MISSING_KEY:
                continue
            counts = tally.setdefault(dim, {}).setdefault(
                key, dict.fromkeys(_GRADED, 0),
            )
            counts[item["grade"]] += 1

    last = None
    by_campaign: dict = {}
    for item in parsed:
        by_campaign.setdefault(item["campaign_id"], []).append(item)
    if by_campaign:
        closed = conn.execute(
            "SELECT id, name FROM ads_campaign WHERE org_id = %s AND brand_id = %s"
            " AND status = 'closed' AND id = ANY(%s) ORDER BY closed_at DESC NULLS LAST, id",
            (org_id, brand_id, list(by_campaign)),
        ).fetchall()
        if closed:
            campaign = closed[0]
            items = by_campaign[campaign["id"]]
            names = {
                row["id"]: row["name"]
                for row in conn.execute(
                    "SELECT id, name FROM ads_ad WHERE org_id = %s AND brand_id = %s"
                    " AND id = ANY(%s)",
                    (org_id, brand_id, [item["ad_id"] for item in items]),
                ).fetchall()
            }
            items.sort(key=lambda item: (names.get(item["ad_id"]) or "", item["ad_id"]))

            def _ad(item: dict) -> dict:
                return {
                    "name": names.get(item["ad_id"]) or item["ad_id"],
                    "grade": item["grade"], "grade_label": _GRADE_LABELS[item["grade"]],
                    "cost_per_result": item["cost_per_result"], "cap": item["cap"],
                    "coordinates": dict(item["keys"]),
                }

            last = {
                "campaign_name": campaign["name"],
                "on_target": [_ad(item) for item in items if item["grade"] == "on_target"],
                "bad": [_ad(item) for item in items if item["grade"] in _BAD],
            }
    return {"tally": tally, "last": last, "learning_ids": [item["id"] for item in parsed]}


def learning_rows(conn: _AnyConn, org_id: str, brand_id: str, board: dict) -> list[dict]:
    """The strategy basis's 「用到的學習」 rows (F41-I02): the last closed campaign's ads the
    prompt showed (`board["last"]`: 划算 first, then 太貴／沒賣出), each with its grade, cost per
    result and coordinates by label (`none` coordinates omitted). Numbers come from the stored
    scope, never recomputed from outcome rows; an old row without them carries `None`."""
    last = board.get("last")
    if last is None:
        return []
    labels = _vocabulary(conn, org_id, brand_id)
    return [
        {
            "grade": ad["grade"], "grade_label": ad["grade_label"],
            "cost_per_result": ad["cost_per_result"], "ad_name": ad["name"],
            "campaign_name": last["campaign_name"],
            "coordinates": [
                {"dimension": d, "dimension_label": DIMENSION_LABELS[d],
                 "label": _label(labels, d, ad["coordinates"][d])}
                for d in DIMENSIONS if ad["coordinates"][d] != _MISSING_KEY
            ],
        }
        for ad in [*last["on_target"], *last["bad"]]
    ]


EMPTY_SECTION = "【座標成績表】（還沒有結案過的廣告，沒有成績表）"
_HEADER = "【座標成績表（已結案活動，程式統計；划算＝每筆成本在上限內）】"


def scoreboard_section(conn: _AnyConn, org_id: str, brand_id: str, *,
                       board: dict | None = None) -> tuple[str, list[str]]:
    """Prompt text for the strategy and delivery-plan prompts, plus the learning ids it was built
    from. One tally line per dimension/key with at least one graded row (label through the brand
    vocabulary, key as the fallback), then the last closed campaign's 划算 ads and its 太貴／沒賣出
    ads, each coordinate as `label（dim=key）` so the model reads the words and a combination can
    still be reused verbatim. `board` = an already-read `scoreboard()` (strategy reuses it for
    its basis rows), read here when omitted."""
    if board is None:
        board = scoreboard(conn, org_id, brand_id)
    if not board["learning_ids"]:
        return EMPTY_SECTION, []
    labels = _vocabulary(conn, org_id, brand_id)
    lines = [_HEADER]
    for dim in DIMENSIONS:
        for key in sorted(board["tally"].get(dim, {})):
            counts = board["tally"][dim][key]
            tallies = "、".join(f"{_GRADE_LABELS[g]} {counts[g]}" for g in _GRADED)
            lines.append(f"- {dim}｜{key}｜{_label(labels, dim, key)}：{tallies}")
    last = board["last"]
    if last is not None:
        for ad in last["on_target"]:
            lines.append(
                f"上一期「{last['campaign_name']}」划算的：「{ad['name']}」"
                f"（{_prompt_coordinates(ad['coordinates'], labels)}）"
            )
        for ad in last["bad"]:
            lines.append(
                f"上一期太貴／沒賣出的：「{ad['name']}」{ad['grade_label']}"
                f"（{_prompt_coordinates(ad['coordinates'], labels)}）"
            )
    return "\n".join(lines), board["learning_ids"]
