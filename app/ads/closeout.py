"""app/ads/closeout.py — F03-I12: the campaign is judged against its own success criterion and
leaves one sentence the next campaign can read (§0 the "verdict -> learning -> next goal" link
— this is where the golden path closes). Private to app/ads (container contract §1): only
`routes.py`/`jobs.py` import this.

`close()` reads `outcome.summary()`'s `totals` — never `repository._outcome_totals`: that
deriver's `0` for a Meta-sourced campaign is a missing purchase count wearing a number, not a
real zero (§0 "F03-I12's 結案 verdict reads outcome.summary()'s totals, never
_outcome_totals"). 看不出 is a real verdict, not a rounding of an unknown into a pass or a fail
— it is what gets written whenever the success target was never set, the sample bucket is 低,
or the metric being judged is itself untracked; it never falls back to 未達成.

Duplicate guard: `ads_campaign.status = 'closed'` on the row itself — a second `close()` call is
a no-op that returns the already-closed row unchanged, no second learning (§0 "the duplicate
guard stays status='closed' on the campaign row; do not query the ledger for it").
"""

from app.ads import learning as ads_learning
from app.ads import outcome, repository
from app.core.db import Conn, ConnProxy, jsonb

_AnyConn = Conn | ConnProxy

_METRIC_LABELS = {"cpa": "CPA", "roas": "ROAS", "purchases": "購買數"}
# CPA 是花費/購買，越低越好；ROAS／購買數是越高越好——兩種比對方向,不是同一個算子。
_LOWER_IS_BETTER = frozenset({"cpa"})


def _days(start_date, end_date) -> int:
    if start_date is None or end_date is None:
        return 0
    return (end_date - start_date).days + 1


def _metric_value(metric: str, totals: dict) -> float | None:
    if metric == "cpa":
        return totals["cpa"]
    if metric == "roas":
        return totals["roas_conservative"]  # 主數字是保守值（§0 ruling 7），不是樂觀的 roas
    return totals["purchases"]


def _judge(campaign: dict, totals: dict, sample_bucket: str) -> tuple[str, dict]:
    """回傳 (verdict, verdict_json)。`verdict_json` 一律帶 `metric`／`target`／`actual`／
    `window`／`sample_bucket`；只有 `看不出` 才多一個 `missing`，說清楚少了什麼。"""
    metric = campaign["success_metric"]
    target = campaign["success_target"]
    actual = _metric_value(metric, totals)
    verdict_json = {
        "metric": metric, "target": target, "actual": actual,
        "window": {"start": campaign["start_date"], "end": campaign["end_date"]},
        "sample_bucket": sample_bucket,
    }
    if target is None:
        verdict_json["missing"] = "success_target 沒有設定，成功條件本身沒有數字可比對"
        return "看不出", verdict_json
    if actual is None:
        verdict_json["missing"] = f"{_METRIC_LABELS.get(metric, metric)}未追蹤，沒有數字可以比對"
        return "看不出", verdict_json
    if sample_bucket == "低":
        verdict_json["missing"] = "樣本太小（低），比對出來的結果不可靠"
        return "看不出", verdict_json
    achieved = actual <= target if metric in _LOWER_IS_BETTER else actual >= target
    return ("達成" if achieved else "未達成"), verdict_json


def close(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str, *, actor: str,
          reason: str | None = None) -> dict:
    """結案：判 verdict → 寫一條學習（`app/ads/learning.py::write_learning`，它自己
    commit——檔案慣例）→ 一次 UPDATE 把 `verdict`／`verdict_json`／`status='closed'`／
    `closed_at` 落地，順序固定（§0「Close in the order record_learning(...) -> one UPDATE」）。
    已經是 `closed` 的 Campaign 直接照原樣回傳，不重判也不重寫學習。"""
    campaign = repository.get_campaign(conn, org_id, brand_id, campaign_id)
    if campaign is None:
        raise ValueError("campaign_unknown")
    if campaign["status"] == "closed":
        return campaign

    result = outcome.summary(conn, org_id, brand_id, campaign_id)
    totals = result["totals"]
    days = _days(campaign["start_date"], campaign["end_date"])
    # `sample_bucket` 吃 int，Meta 來源的 `purchases` 恆為 `None`（未追蹤）——未追蹤當低樣本
    # 處理，不是傳 `None` 進去（§0「an untracked campaign is 低樣本, ... never passes None」）。
    purchases_for_bucket = totals["purchases"] if totals["purchases"] is not None else 0
    sample_bucket = outcome.sample_bucket(purchases_for_bucket, days)

    verdict, verdict_json = _judge(campaign, totals, sample_bucket)
    if reason:
        verdict_json["close_reason"] = reason

    learning_row = ads_learning.write_learning(
        conn, org_id, brand_id, campaign_id, verdict, verdict_json, actor=actor,
    )
    verdict_json["learning_ids"] = [learning_row["id"]]

    conn.execute(
        "UPDATE ads_campaign SET verdict = %s, verdict_json = %s, status = 'closed',"
        " closed_at = now() WHERE org_id = %s AND brand_id = %s AND id = %s",
        (verdict, jsonb(verdict_json), org_id, brand_id, campaign_id),
    )
    row = repository.get_campaign(conn, org_id, brand_id, campaign_id)
    assert row is not None  # 剛更新過的那一列，一定讀得到
    return row
