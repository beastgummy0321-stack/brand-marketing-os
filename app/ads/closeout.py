"""app/ads/closeout.py — F03-I12: the campaign is judged against its one cap (F28-I01) and
leaves one sentence the next campaign can read (§0 the "verdict -> learning -> next goal" link
— this is where the golden path closes). Private to app/ads (container contract §1): only
`routes.py`/`jobs.py` import this.

`close()` reads `outcome.summary()`'s `totals` — never `repository._outcome_totals`: that
deriver's `0` for a Meta-sourced campaign is a missing purchase count wearing a number, not a
real zero (§0 "F03-I12's 結案 verdict reads outcome.summary()'s totals, never
_outcome_totals"). 看不出 is a real verdict, not a rounding of an unknown into a pass or a fail
— it is what gets written whenever no cap resolves or the metric being judged is itself
untracked; it never falls back to 未達成. F48-I02 (Contract R): a small sample is shown
(`verdict_json.sample`), never turned into 看不出.

F39-I01 / F46-I04: after the visual track, `coordinate_learning.write_coordinate_learnings` writes
one `source_track='coordinate'` learning per ad the ranking rule enters (`learning_rank`: 留下／換掉
by cost per sale, Contract B); partial data (skipped gap, incomplete recovery) writes none of
them, and their ids join `verdict_json["learning_ids"]`.

Duplicate guard: `ads_campaign.status = 'closed'` on the row itself — a second `close()` call is
a no-op that returns the already-closed row unchanged, no second learning (§0 "the duplicate
guard stays status='closed' on the campaign row; do not query the ledger for it").
"""

from datetime import date, timedelta

from app.ads import (
    coordinate_learning,
    lifecycle,
    outcome,
    repository,
    runtime,
    simulation_mode,
    targets,
    visual_learning,
)
from app.ads import learning as ads_learning
from app.ads.judgment import conversion_labels
from app.brand_intelligence import repository as bi_repo
from app.core.db import Conn, ConnProxy, jsonb

_AnyConn = Conn | ConnProxy


def _days(start_date, end_date) -> int:
    if start_date is None or end_date is None:
        return 0
    return (end_date - start_date).days + 1


def _judge(cap: dict, campaign: dict, totals: dict, sample: dict,
           labels: dict) -> tuple[str, dict]:
    """F28-I01: cost per result against the campaign's one cap (`targets.resolve`) -- lower is
    better, 達成 when at or under the cap. Returns (verdict, verdict_json); `verdict_json`
    always carries `metric`/`target`/`basis`/`actual`/`window`/`sample`/`sample_bucket`, plus
    `missing` only for 看不出, naming what was missing. `labels` is `judgment.conversion_labels()`.

    F48 Contract R: the sample size is shown, never a verdict switch -- `sample` is
    `{purchases, days, bucket}` (`outcome.sample_bucket`), `sample_bucket` its bucket (the key
    older readers print). 看不出 only when the cap or the actual cost is unknown."""
    target = cap["value"]
    actual = totals["cpa"]
    verdict_json = {
        "metric": "cpa", "target": target, "basis": cap["basis"], "actual": actual,
        "window": {"start": campaign["start_date"], "end": campaign["end_date"]},
        "sample": sample, "sample_bucket": sample["bucket"],
    }
    if target is None:
        verdict_json["missing"] = "上限沒有設定，沒有數字可比對"
        return "看不出", verdict_json
    if actual is None:
        verdict_json["missing"] = f"{labels['cpa']}未追蹤，沒有數字可以比對"
        return "看不出", verdict_json
    return ("達成" if actual <= target else "未達成"), verdict_json


class CoverageMissing(ValueError):
    """F37 Contract Q: the campaign window has days the platform read never covered (or nothing
    was ever read). `str(exc)` is the route code `coverage_missing`; `payload` is what the route
    returns so the user sees which days and whether the skip is open."""

    def __init__(self, payload: dict):
        super().__init__("coverage_missing")
        self.payload = payload


def _missing_sentence(gap: dict) -> str:
    if gap["never_synced"]:
        return "還沒讀過平台資料"
    days = gap["missing_days"]
    listed = "、".join(date.fromisoformat(day).strftime("%m/%d") for day in days)
    return f"有 {len(days)} 天沒讀到平台資料：{listed}"


def _coverage_check(campaign: dict, coverage: dict, skip_missing: bool) -> dict | None:
    """F37 Contract Q (ruling 3): refuse a window the platform read does not cover. `coverage` is
    `outcome.summary()`'s block -- `coverage.gap` (F49 Contract V) over `start_date …
    min(end_date, org yesterday)`, the one rule the performance tab and review share. The skip
    opens only after the last observations read ended `error` (every successful read resets the
    status), or for an
    isolated simulation recovery, whose only "read" is the user typing days in. Returns the gap
    when a permitted skip goes ahead, `None` when the window is fully covered."""
    gap = {"never_synced": coverage["never_synced"], "missing_days": coverage["missing_days"]}
    if not gap["never_synced"] and not gap["missing_days"]:
        return None
    context = campaign.get("context_json") or {}
    status = ((context.get("external_sync") or {}).get("observations") or {}).get("status")
    can_skip = status == "error" or bool(context.get("simulation_recovery"))
    if skip_missing and can_skip:
        return gap
    raise CoverageMissing({**gap, "can_skip": can_skip})


def close(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str, *, actor: str,
          reason: str | None = None, skip_missing: bool = False) -> dict:
    """結案：判 verdict → 寫一條學習（`app/ads/learning.py::write_learning`，它自己
    commit——檔案慣例）→ 一次 UPDATE 把 `verdict`／`verdict_json`／`status='closed'`／
    `closed_at` 落地，順序固定（§0「Close in the order record_learning(...) -> one UPDATE」）。
    已經是 `closed` 的 Campaign 直接照原樣回傳，不重判也不重寫學習。"""
    repository.require_internal_campaign(conn, org_id, brand_id, campaign_id)
    simulation_mode.lock(conn, org_id, brand_id)
    campaign = repository.get_campaign(conn, org_id, brand_id, campaign_id)
    if campaign is None:
        raise ValueError("campaign_unknown")
    if campaign["status"] == "closed":
        return campaign
    # F49 Contract L (planning #19): a campaign never on a platform has no period to close.
    if lifecycle.of(conn, org_id, brand_id, campaign)["state"] == "draft":
        raise ValueError("campaign_not_launched")

    result = outcome.summary(conn, org_id, brand_id, campaign_id)
    skipped_gap = _coverage_check(campaign, result["coverage"], skip_missing)

    recovery = (campaign.get("context_json") or {}).get("simulation_recovery")
    if recovery:
        # record_learning commits internally. Freeze recovery before that commit releases the lock.
        recovery["closing"] = True
        conn.execute(
            "UPDATE ads_campaign SET context_json=%s WHERE org_id=%s AND brand_id=%s AND id=%s",
            (jsonb(campaign["context_json"]), org_id, brand_id, campaign_id),
        )
    brand = bi_repo.get_brand(conn, brand_id)
    labels = conversion_labels(brand.get("conversion_goal") if brand else None)

    totals = result["totals"]
    days = _days(campaign["start_date"], campaign["end_date"])
    # `purchases` is `None` only when no day of the campaign carries a tracked purchase count
    # (Meta purchases are tracked since F16-I05; a legacy or untracked day stays NULL) -- passed
    # as is: the bucket reads 「未追蹤」, never 低 or 0 (F48-I02).
    sample = {
        "purchases": totals["purchases"], "days": days,
        "bucket": outcome.sample_bucket(totals["purchases"], days),
    }

    cap = targets.resolve(conn, org_id, brand_id, campaign)
    verdict, verdict_json = _judge(cap, campaign, totals, sample, labels)
    if simulation_mode.enabled(conn, org_id, brand_id):
        verdict_json["data_source"] = "isolated_simulation"
        verdict_json["simulation_receipts"] = recovery.get("days", {}) if recovery else {}
    incomplete_simulation = False
    if recovery:
        receipts = recovery.get("days", {})
        incomplete_simulation = not days or any(
            not receipts.get((campaign["start_date"] + timedelta(days=i)).isoformat())
            or receipts[(campaign["start_date"] + timedelta(days=i)).isoformat()].get(
                "missing_ad_count", 1
            )
            for i in range(days)
        )
        if incomplete_simulation:
            verdict = "看不出"
            verdict_json["missing"] = "模擬回收尚有缺日或缺廣告，不把缺資料視為零。"
    if skipped_gap is not None:
        # A skipped gap is 看不出 whatever the partial rows say; a recovery campaign keeps its
        # receipts sentence (the existing rule already names what is missing there).
        verdict = "看不出"
        if not incomplete_simulation:
            verdict_json["missing"] = _missing_sentence(skipped_gap)
        verdict_json["missing_days"] = skipped_gap["missing_days"]
    if reason:
        verdict_json["close_reason"] = reason

    learning_row = ads_learning.write_learning(
        conn, org_id, brand_id, campaign_id, verdict, verdict_json, actor=actor,
    )
    # Partial data teaches no visual pattern: the same stance the incomplete recovery takes.
    visual_rows = [] if incomplete_simulation or skipped_gap is not None else (
        visual_learning.write_visual_learnings(
            conn, org_id, brand_id, campaign_id, actor=actor, days=days, labels=labels,
        )
    )
    coordinate_rows = [] if incomplete_simulation or skipped_gap is not None else (
        coordinate_learning.write_coordinate_learnings(
            conn, org_id, brand_id, campaign_id, actor=actor,
        )
    )
    verdict_json["learning_ids"] = [
        learning_row["id"],
        *[r["id"] for r in visual_rows],
        *[r["id"] for r in coordinate_rows],
    ]

    conn.execute(
        "UPDATE ads_campaign SET verdict = %s, verdict_json = %s, status = 'closed',"
        " closed_at = now() WHERE org_id = %s AND brand_id = %s AND id = %s",
        (verdict, jsonb(verdict_json), org_id, brand_id, campaign_id),
    )
    # F49 Contract N: a closed campaign is no longer monitored -- its open runtime alerts resolve
    # with the close (each `interrupts.resolve` commits, so the close lands with the first one).
    runtime.resolve_alerts(conn, org_id, brand_id, campaign_id)
    row = repository.get_campaign(conn, org_id, brand_id, campaign_id)
    assert row is not None  # 剛更新過的那一列，一定讀得到
    return row
