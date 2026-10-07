"""app/ads/visual_learning.py — F07-I11: 結案時把「這次選中的圖」跟成效兜起來，寫成
`source_track="visual"` 的學習（ARCHITECTURE.md §6.3 items 19-20；F07 決策 31）。沒有模型
呼叫——比對的數字全部來自 `outcome.rows`（F37 Contract P，平台同步列）經 `outcome._bucket`／
`sample_bucket`，跟 `closeout.py` 判活動本身用
的是同一套分桶規則,只是這裡按圖片指紋（`body_json.fingerprint`）分組而不是整個 Campaign。
"這是相關，不代表是造成" 這句話寫死在句子裡——一個維度贏不代表那個維度是原因。

Private to app/ads (container contract §1): only `closeout.py` imports this.

Never delete or overwrite anything under `data/`.
"""

from typing import cast

from app.ads import ads_learnings, live_creative, outcome, sell_way
from app.ads import learning as ads_learning
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core.db import Conn, ConnProxy

_AnyConn = Conn | ConnProxy

# CPA 越低越好；ROAS／購買數越高越好——跟 closeout.py 同一條規則，這裡不 import 私有函式
# 而是重寫一份短的（container contract §5：同一條規則,兩個檔案各自實作）。
_LOWER_IS_BETTER = frozenset({"cpa"})

_DIMENSIONS = (
    ("look", "風格"),
    ("device", "視覺手法"),
    ("layout", "版型"),
    ("subject_role", "主角出現方式"),
    ("persuasion", "說服元素"),
)

_BUCKET_RANK = {outcome.SAMPLE_UNTRACKED: -1, "低": 0, "中": 1, "高": 2}


def _metric_value(metric: str, bucket: dict) -> float | None:
    if metric == "cpa":
        return bucket["cpa"]
    if metric == "roas":
        return bucket["roas_all_spend"]
    return bucket["purchases"]


def _smallest_bucket(buckets: list[str]) -> str:
    return min(buckets, key=lambda b: _BUCKET_RANK[b])


def _kept_ads(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str, ads: list) -> dict:
    """`ad_id -> fingerprint dict`,只留 `is_adopted` 且 `body_json.fingerprint` 是 dict 的圖片
    版本;讀 §5.8 的 row contract,只碰 `fingerprint`（F07 決策 17）。F31-I05 Contract O：上架
    核准過的廣告讀核准當下凍結的那一版（`live_creative`），之後在工作檯改選不會改寫學習；
    還沒核准過的才讀目前的選定。"""
    creative = live_creative.materials(
        conn, org_id, brand_id, campaign_id, parts=("image_prompt",),
    )
    kept: dict = {}
    for ad in ads:
        found = creative.get(ad["id"])
        if found is None:
            continue
        row = found["outputs"].get("image_prompt")
        if row is None or not row.get("is_adopted"):
            continue
        fingerprint = (row.get("body_json") or {}).get("fingerprint")
        if not isinstance(fingerprint, dict):
            continue
        kept[ad["id"]] = fingerprint
    return kept


def _strata(ads: list, fingerprints: dict) -> dict:
    """`audience_key -> [ad, ...]`,只留有指紋且有受眾座標的廣告,只留 >=2 支廣告的受眾。
    `ads` 已帶學習座標（`live_creative.with_learning_coordinates`）。"""
    by_audience: dict[str, list] = {}
    for ad in ads:
        if ad["id"] not in fingerprints:
            continue
        audience_key = ad.get("audience_key")
        if not audience_key:
            continue
        by_audience.setdefault(audience_key, []).append(ad)
    return {key: rows for key, rows in by_audience.items() if len(rows) >= 2}


def _value_groups(ads: list, fingerprints: dict, dimension: str) -> dict:
    """`dimension key -> [ad_id, ...]` for this stratum's kept ads."""
    groups: dict[str, list] = {}
    for ad in ads:
        value = fingerprints[ad["id"]].get(dimension) or {}
        key = value.get("key")
        if not key:
            continue
        groups.setdefault(key, []).append(ad["id"])
    return groups


def _label_lookup(conn: _AnyConn, org_id: str, brand_id: str, dimension: str) -> dict:
    rows = ads_repo.coordinate_vocabulary(conn, org_id, brand_id)
    return {row["key"]: row["label"] for row in rows if row["dimension"] == dimension}


def write_visual_learnings(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str, *,
                            actor: str, days: int, labels: dict) -> list[dict]:
    detail = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)
    if detail is None:
        raise ValueError("campaign_unknown")
    # F31-I05 Contract O: strata group ads by the coordinates their images were made for (the
    # dispatched set's snapshot), not by coordinates edited after dispatch.
    detail = live_creative.with_learning_coordinates(conn, org_id, brand_id, detail)
    # F28-I01: every campaign is judged on cost per result against its one cap.
    metric = "cpa"
    metric_label = labels["cpa"]

    ads = [ad for group in detail["groups"] for ad in group["ads"]]
    fingerprints = _kept_ads(conn, org_id, brand_id, campaign_id, ads)
    strata = _strata(ads, fingerprints)
    if not strata:
        return []

    window = outcome.period_window(conn, org_id, brand_id, detail)
    outcome_rows = outcome.select_period(
        outcome.rows(conn, org_id, brand_id, campaign_id, "ad"), window,
    )
    days = window["days"]
    rows_by_entity: dict[str, list] = {}
    for row in outcome_rows:
        rows_by_entity.setdefault(row["entity_id"], []).append(row)

    audience_labels = _label_lookup(conn, org_id, brand_id, "audience")
    needs_revalidation = ads_learning._needs_revalidation(conn, brand_id, detail)  # noqa: SLF001
    product_id = sell_way.of_campaign(detail)  # F48 Contract W: the campaign's sell-way

    written: list[dict] = []
    for audience_key, stratum_ads in strata.items():
        audience_label = audience_labels.get(audience_key, audience_key)
        comparison = outcome.period_bucket([
            row for ad in stratum_ads for row in rows_by_entity.get(ad["id"], [])
        ])
        for dimension, dimension_name in _DIMENSIONS:
            value_groups = _value_groups(stratum_ads, fingerprints, dimension)
            if len(value_groups) < 2:
                continue

            buckets = {}
            for value_key, ad_ids in value_groups.items():
                rows = [r for ad_id in ad_ids for r in rows_by_entity.get(ad_id, [])]
                bucket = outcome.period_bucket(rows)
                buckets[value_key] = {
                    "label": fingerprints[ad_ids[0]][dimension].get("label", value_key),
                    "metric_value": (_metric_value(metric, bucket)
                                     if comparison["reason"] is None else None),
                    "purchases": bucket["purchases"],
                    "sample_bucket": outcome.sample_bucket(bucket["purchases"], days),
                    "ad_count": len(ad_ids),
                }

            # F48 Contract R: a small sample is compared and written with its bucket shown
            # (`sample_size` 低), never skipped; only a value with no cost to compare is left out.
            comparable = {k: b for k, b in buckets.items() if b["metric_value"] is not None}

            best_key = None
            if len(comparable) >= 2:
                values = [b["metric_value"] for b in comparable.values()]
                extreme = min(values) if metric in _LOWER_IS_BETTER else max(values)
                winners = [k for k, b in comparable.items() if b["metric_value"] == extreme]
                if len(winners) == 1:
                    best_key = winners[0]

            scope_prefix = f"visual；audience={audience_key}；{dimension}"

            if best_key is not None:
                scope = f"{scope_prefix}={best_key}"
                best = comparable[best_key]
                others = [
                    (k, b) for k, b in comparable.items() if k != best_key
                ]
                others_text = "、".join(
                    f"「{b['label']}」{metric_label} {_fmt(b['metric_value'])}"
                    f"（{b['ad_count']} 則，樣本{b['sample_bucket']}）"
                    for _k, b in others
                )
                sentence = (
                    f"{audience_label}：{dimension_name}「{best['label']}」{metric_label}"
                    f" {_fmt(best['metric_value'])}（{best['ad_count']} 則廣告，樣本"
                    f"{best['sample_bucket']}），好過 {others_text}。這是相關，不代表是"
                    f"{dimension_name}造成。"
                )
                sample_size = _smallest_bucket([b["sample_bucket"] for b in comparable.values()])
            else:
                # Untracked purchases are checked first: never reported as a small sample.
                if comparison["reason"] is not None:
                    reason = "資料範圍或金額尚未核實，不能比較"
                elif any(b["purchases"] is None for b in buckets.values()):
                    reason = "成效未追蹤"
                elif any(b["metric_value"] is None for b in buckets.values()):
                    reason = "有一組沒賣出"
                else:
                    reason = "數字一樣"
                scope = f"{scope_prefix}=看不出"
                sentence = f"{audience_label}：{dimension_name}這次看不出差別（{reason}）。"
                sample_size = _smallest_bucket([b["sample_bucket"] for b in buckets.values()])

            confidence = "observed"
            if best_key is not None:
                prior = [
                    row for row in bi_repo.list_learnings(
                        cast(Conn, conn), brand_id, source_track="visual", limit=500,
                    )
                    if row["applicability_scope"] == scope and row["source_cycle_id"] != campaign_id
                ]
                count = len(prior) + 1
                confidence = "validated" if count >= 3 else "likely" if count >= 2 else "observed"

                # 降級:這次贏的維度值,把之前贏過的別的值降下去(F07 決策 31)。
                for other_key in comparable:
                    if other_key == best_key:
                        continue
                    other_scope = f"{scope_prefix}={other_key}"
                    beaten = [
                        row for row in bi_repo.list_learnings(
                            cast(Conn, conn), brand_id, source_track="visual", limit=500,
                        )
                        if row["applicability_scope"] == other_scope
                        and row["source_cycle_id"] != campaign_id
                    ]
                    if beaten:
                        newest = max(beaten, key=lambda r: r["learned_at"])
                        bi_repo.expire_learning(
                            cast(Conn, conn), brand_id, newest["id"], actor=actor,
                        )

            written.append(ads_learnings.write(
                conn, org_id, brand_id, actor=actor, product_id=product_id, text=sentence,
                scope=scope, confidence=confidence, sample_size=sample_size,
                source_cycle_id=campaign_id, needs_revalidation=needs_revalidation,
                source_track="visual",
            ))

    return written


def _fmt(value: float | int | None) -> float | int | None:
    return round(value, 2) if isinstance(value, float) else value
