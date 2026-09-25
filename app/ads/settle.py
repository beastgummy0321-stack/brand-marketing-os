"""app/ads/settle.py — F29-I03 Contract E: the period settle. One period is the calendar month in
the org timezone (user ruling 2026-09-25, feature Unresolved 1; `app/schedule/period.py` is not
used).

Step 1 (這期成績) is `period_grades.grade_period` over the month -- the same rows the month review
of that month reads -- with one settle-only rule on top: an ad whose campaign has unsynced days
inside the month reads 資料不足 (its numbers could be the gap), so it is never written. Each row's
fate follows the one ruler (ads.md §6.33): 划算 -> effective, 太貴／沒賣出 -> ineffective, anything
else -> skip. Step 2 reuses `angles.get` (F27 Contract C: one enqueue per ad per copy hash) for
every row that will be written. Step 3 (`write`) writes one brand-notebook learning per non-skip
row through `bi_repo.record_learning`, idempotent by `source_cycle_id = settle:<month>:<entity>`.

The learning text carries no numbers, so the same conclusion reached twice promotes confidence
(F27 Contract D, same counting rule as `ads_learnings`). Program-only reads and one user-confirmed
write; no platform write. `queue_candidate` feeds the brand queue's `settle` row (`triage.py`)
without any model call -- only `view` (the page read) may enqueue the angle job.
"""

import calendar
import re
from datetime import date, timedelta
from typing import cast

from app.ads import ads_learnings, angles, period_grades, repository, targets, triage
from app.ads import change_control_data as changes
from app.brand_intelligence import repository as bi_repo
from app.core import interrupts
from app.core import settings as coresettings
from app.core.db import Conn

QUEUE_KIND = "settle"
QUEUE_CATEGORY = "ads_triage_settle"
# The settle row appears from the 2nd day after the month ends: the 1st day's morning sync may not
# yet hold the month's last day.
RAISE_AFTER_DAYS = 2
MAX_ANGLE_CHARS = 12
_FATE = {"on_target": "effective", "over": "ineffective", "wasted": "ineffective"}
_MONTH_RE = re.compile(r"\d{4}-\d{2}")
_TEXT_RE = re.compile(r"^「(.+)」對這群受眾(有效|無效)$")
_SCAN_LIMIT = 500  # same scan ceiling as `ads_learnings._SCAN_LIMIT` / `visual_learning.py`


class SettleError(ValueError):
    """A refused settle request: `status` + `code` are the route's error envelope."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def effective_text(angle: str) -> str:
    return f"「{angle}」對這群受眾有效"


def learning_text(fate: str, angle: str) -> str:
    # Ineffective reuses the cleanup learning's own words (`ads_learnings._text`), so a settle and
    # a confirmed cleanup that reach the same conclusion promote the same row text.
    return effective_text(angle) if fate == "effective" else ads_learnings._text(angle)


def _require_month(month) -> str:
    if not isinstance(month, str) or not _MONTH_RE.fullmatch(month):
        raise SettleError(422, "settle_invalid", "請提供 YYYY-MM 格式的月份。")
    try:
        date.fromisoformat(month + "-01")
    except ValueError:
        raise SettleError(422, "settle_invalid", "請提供 YYYY-MM 格式的月份。") from None
    return month


def _window(month: str) -> tuple[date, date]:
    start = date.fromisoformat(month + "-01")
    return start, start.replace(day=calendar.monthrange(start.year, start.month)[1])


def _today(conn, org_id) -> date:
    return coresettings.today_for_org(conn, org_id=org_id)


def previous_month(conn, org_id) -> str:
    """The latest ended calendar month in the org timezone (the route's default)."""
    return (_today(conn, org_id).replace(day=1) - timedelta(days=1)).strftime("%Y-%m")


def _cycle_prefix(month: str) -> str:
    return f"settle:{month}:"


def _cycle_id(month: str, entity_id: str) -> str:
    return _cycle_prefix(month) + entity_id


def _ads_learnings(conn, brand_id) -> list[dict]:
    return bi_repo.list_learnings(
        cast(Conn, conn), brand_id, source_track="ads", limit=_SCAN_LIMIT,
    )


def _written_rows(learnings, month) -> dict:
    prefix = _cycle_prefix(month)
    return {
        row["source_cycle_id"][len(prefix):]: row
        for row in learnings
        if (row.get("source_cycle_id") or "").startswith(prefix)
    }


def _written_view(written: dict):
    if not written:
        return None
    rows = sorted(written.values(), key=lambda row: row["created_at"])
    effective = sum(1 for row in rows if row["learning_text"].endswith("有效"))
    return {
        "at": rows[-1]["created_at"], "by": rows[-1]["created_by"], "count": len(rows),
        "effective": effective, "ineffective": len(rows) - effective,
    }


def _graded(conn, org_id, brand_id, start, end):
    """`grade_period` rows with the settle's missing-days rule applied, plus `missing`."""
    rows = period_grades.grade_period(conn, org_id, brand_id, start, end)
    missing = {
        entry["campaign_id"]: entry["missing_days"]
        for entry in period_grades.missing(conn, org_id, brand_id, start, end)
    }
    out = []
    for row in rows:
        if row["campaign_id"] in missing:
            row = {**row, "grade": "insufficient", "grade_label": triage.NO_DATA_LABEL}
        out.append({**row, "fate": _FATE.get(row["grade"], "skip")})
    return out, missing


def _known_total(values):
    if any(value is None for value in values):
        return None
    return sum(values)


def _totals(rows, budget) -> dict:
    summary = period_grades.summarize(rows)
    currencies = {row["currency"] for row in rows}
    currency = next(iter(currencies)) if len(currencies) == 1 else None
    spent = summary["spent"]
    results = _known_total([row["results"] for row in rows]) if rows else None
    on_target = [row for row in rows if row["grade"] == "on_target"]
    on_target_spend = _known_total([row["spend"] for row in on_target])
    return {
        "currency": currency, "spent": spent,
        # The month budget only when it is in the same currency as the spend (never compared
        # across two currencies).
        "budget": budget[0] if budget and (currency is None or budget[1] == currency) else None,
        "results": results,
        "cost_per_result": spent / results if spent is not None and results else None,
        "on_target_results": _known_total([row["results"] for row in on_target]) if rows else None,
        "on_target_spend_share": (
            on_target_spend / spent if spent and on_target_spend is not None else None
        ),
        "buckets": summary["buckets"],
    }


def _budget(conn, org_id, brand_id, start):
    row = conn.execute(
        "SELECT amount,currency FROM ads_month_budget WHERE org_id=%s AND brand_id=%s AND month=%s",
        (org_id, brand_id, start),
    ).fetchone()
    return (float(row["amount"]), row["currency"]) if row else None


def _status(today, end, written) -> str:
    if today <= end:
        return "not_ended"
    return "written" if written else "open"


def queue_candidate(conn, org_id, brand_id) -> dict | None:
    """The brand queue's `settle` row for the latest ended month, or `None`: raised from the 2nd
    day after the month ends, while at least one row would be written and nothing is written yet.
    No model call and no enqueue here -- only program reads."""
    today = _today(conn, org_id)
    month = previous_month(conn, org_id)
    start, end = _window(month)
    if today < end + timedelta(days=RAISE_AFTER_DAYS):
        return None
    if _written_rows(_ads_learnings(conn, brand_id), month):
        return None
    rows, _missing = _graded(conn, org_id, brand_id, start, end)
    learnable = [row for row in rows if row["fate"] != "skip"]
    if not learnable:
        return None
    campaigns = {row["campaign_id"]: row["origin"] for row in rows}
    return {
        "kind": QUEUE_KIND, "identity_id": brand_id, "window_start": start, "window_end": end,
        "message": f"結算上一期（{start.month} 月），待寫進筆記本",
        "action_url": f"/brands/{brand_id}/ads/settle/{month}/result",
        "payload": {
            "triage": None,
            "settle": {
                "month": month, "start": start.isoformat(), "end": end.isoformat(),
                "campaign_count": len(campaigns),
                "imported_count": sum(1 for origin in campaigns.values() if origin == "imported"),
                "learnable_count": len(learnable),
                "buckets": period_grades.summarize(rows)["buckets"],
            },
        },
    }


def _copy_text(entity) -> str | None:
    fields = changes.copy_fields(entity)
    for key in ("body", "bodies", "title", "titles"):
        value = fields.get(key)
        if isinstance(value, list):
            value = next((v for v in value if isinstance(v, str) and v.strip()), None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _entities(conn, org_id, brand_id, entity_ids) -> dict:
    if not entity_ids:
        return {}
    return {
        row["id"]: dict(row)
        for row in conn.execute(
            "SELECT * FROM ads_external_entity WHERE org_id=%s AND brand_id=%s AND id = ANY(%s)",
            (org_id, brand_id, list(entity_ids)),
        ).fetchall()
    }


def _angles(conn, org_id, brand_id, row, copy_text, *, needed):
    """Contract E `angles`: `not_needed` unless this row still needs a pick and has copy to read;
    otherwise `angles.get` (which enqueues the one job for this copy on its first read)."""
    if not needed or copy_text is None:
        return {"status": "not_needed", "candidates": []}
    try:
        result = angles.get(conn, org_id, brand_id, row["campaign_id"], row["entity_id"])
    except ValueError:
        return {"status": "failed", "candidates": []}
    return {"status": result["status"], "candidates": result["candidates"]}


def _written_angle(learning) -> str | None:
    if learning is None:
        return None
    match = _TEXT_RE.match(learning["learning_text"])
    return match.group(1) if match else None


def _campaigns(conn, org_id, brand_id, rows, missing) -> list[dict]:
    out, accounts_cache = [], {}
    for campaign_id in dict.fromkeys(row["campaign_id"] for row in rows):
        campaign = repository.get_campaign(conn, org_id, brand_id, campaign_id)
        if campaign is None:
            continue
        target = targets.resolve(conn, org_id, brand_id, campaign)
        out.append({
            "campaign_id": campaign_id, "name": campaign["name"], "origin": campaign["origin"],
            "cap": (
                {"value": target["value"], "basis": target["basis"]}
                if target["value"] is not None else None
            ),
            "break_even": target.get("break_even"),
            "data_status": repository.campaign_data_status(
                conn, org_id, brand_id, campaign, has_rows=True,
                missing_days=missing.get(campaign_id, []), accounts_cache=accounts_cache,
            ),
        })
    return out


def view(conn, org_id, brand_id, month) -> dict:
    """`GET .../settle?month=` (Contract E)."""
    month = _require_month(month)
    start, end = _window(month)
    today = _today(conn, org_id)
    learnings = _ads_learnings(conn, brand_id)
    written = _written_rows(learnings, month)
    status = _status(today, end, written)
    rows, missing = _graded(conn, org_id, brand_id, start, end)
    entities = _entities(conn, org_id, brand_id, {row["entity_id"] for row in rows})
    out_rows = []
    for row in rows:
        entity = entities.get(row["entity_id"])
        copy_text = _copy_text(entity) if entity is not None else None
        learning = written.get(row["entity_id"])
        needed = status != "not_ended" and row["fate"] != "skip" and learning is None
        out_rows.append({
            **row, "copy_text": copy_text,
            "angles": _angles(conn, org_id, brand_id, row, copy_text, needed=needed),
            "written_angle": _written_angle(learning),
        })
    return {
        "month": month, "start": start.isoformat(), "end": end.isoformat(),
        "days": (end - start).days + 1, "status": status,
        **_totals(rows, _budget(conn, org_id, brand_id, start)),
        "campaigns": _campaigns(conn, org_id, brand_id, rows, missing),
        "rows": out_rows,
        "notebook": {"count": len(learnings)},
        "written": _written_view(written),
    }


def _picked_angles(rows, written, picks) -> dict:
    """`entity_id -> angle` for every non-skip row not written yet; every such row must carry a
    1–12 character pick. Picks for skip rows, written rows or unknown ads are ignored."""
    by_entity = {}
    for pick in picks or []:
        if isinstance(pick, dict) and isinstance(pick.get("entity_id"), str):
            by_entity[pick["entity_id"]] = pick.get("angle")
    out = {}
    for row in rows:
        if row["fate"] == "skip" or row["entity_id"] in written:
            continue
        angle = by_entity.get(row["entity_id"])
        angle = angle.strip() if isinstance(angle, str) else ""
        name = row["name"] or "(未命名廣告)"
        if not angle:
            raise SettleError(400, "settle_angle_missing", f"「{name}」還沒選主打什麼。")
        if len(angle) > MAX_ANGLE_CHARS:
            raise SettleError(
                400, "settle_angle_invalid", f"「{name}」的主打需為一至十二字。",
            )
        out[row["entity_id"]] = angle
    return out


def _sample_size(results) -> str:
    if results is None:
        return "0"
    return str(int(results)) if float(results).is_integer() else str(results)


def _resolve_queue_rows(conn, org_id, brand_id, end, actor) -> None:
    key = triage._dedupe_key(QUEUE_KIND, brand_id, end)
    for row in interrupts.list_open(conn, brand_id=brand_id, category=QUEUE_CATEGORY,
                                    archive_stale=False):
        if row["dedupe_key"] == key:
            interrupts.resolve(conn, row["id"], actor=actor, org_id=org_id)


def write(conn, org_id, brand_id, month, picks, actor) -> dict:
    """`POST .../settle` (Contract E): one learning per non-skip row not written yet. Every pick
    is checked before the first write; a repeat writes nothing twice. Resolves the month's open
    queue row, then returns the fresh view."""
    month = _require_month(month)
    start, end = _window(month)
    if _today(conn, org_id) <= end:
        raise SettleError(409, "settle_not_ended", "這個月還沒結束，結束後才能結算。")
    learnings = _ads_learnings(conn, brand_id)
    written = _written_rows(learnings, month)
    rows, _missing = _graded(conn, org_id, brand_id, start, end)
    chosen = _picked_angles(rows, written, picks)
    texts = [row["learning_text"] for row in learnings]
    for row in rows:
        angle = chosen.get(row["entity_id"])
        if angle is None:
            continue
        text = learning_text(row["fate"], angle)
        prior = texts.count(text)
        bi_repo.record_learning(
            cast(Conn, conn), brand_id, actor=actor, learning_text=text,
            applicability_scope=f"ads;campaign={row['campaign_id']}",
            confidence=ads_learnings._confidence_for_count(prior),
            sample_size=_sample_size(row["results"]),
            source_cycle_id=_cycle_id(month, row["entity_id"]), source_track="ads",
        )
        texts.append(text)
    _resolve_queue_rows(conn, org_id, brand_id, end, actor)
    return view(conn, org_id, brand_id, month)
