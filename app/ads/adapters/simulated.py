"""app/ads/adapters/simulated.py — F03-I10: 沒有平台的通路（演練／驗收用），實作跟
`manual` 同一份兩方法介面（`app.ads.adapters` 的介面）。`publish` 不等使用者到平台後台，
直接自己造假外部 id、綁定每一個節點、把 Campaign 推到 `live`，接著把 `start_date` 到今天
的每一天成效都補齊——所以一個人在瀏覽器裡點「模擬發布」，下一秒切到成效分頁就有數字可看，
不必再跑一次命令列（§0「pluggable — delete it and the product still works, but acceptance
and drills lose their legs」）。

F37 Contract R: 模擬通路就是一個平台（platform `"simulated"`、source account `"sim"`）。
`publish` 先把 campaign → adset → ad 這條鏈登記成 `ads_external_entity`（native id 就是
`sim_…` 假 id），再照舊綁定本地節點；成效逐日寫進 `ads_external_daily`
（`external_repository.upsert_observation`），每補完一段就用 `record_sync` 把這段併進活動
已讀到的範圍——跟真平台同步寫的是同一張表、同一個覆蓋紀錄，讀的人不必分真假。

`day_rows()` 是唯一的產生器（純函式）：一天、每個投放組先一列投放組層（穩定，永遠有），再灑
一批廣告層（刻意稀疏，比照 `app/tools/simulate_meta_spend.py` 檔頭量到的「81% 廣告×日沒有列」，
這裡用「~80% 出現」換算），金額拆分只是把投放組那天的花費／購買／營收按權重分掉，不是另一套
獨立算出來的數字——campaign 層的花費永遠只讀投放組層（§0「money totals belong to the group
level」），廣告層只是拿來算花費占比。`generate_outcomes()` 逐日檢查：那一天這個投放組已經有
一列成效就跳過（含底下的廣告），沒有才寫。
"""

import random
import uuid
from datetime import date, timedelta

from app.ads import external_repository, outcome
from app.ads import repository as ads_repo
from app.core import settings as coresettings
from app.core.db import Conn, ConnProxy, now_utc

_AnyConn = Conn | ConnProxy

PLATFORM = "simulated"
SOURCE_ACCOUNT = "sim"
SOURCE = "simulated"
ATTRIBUTION_KEY = "simulated"
CURRENCY = "TWD"

DESCRIBE_MESSAGE = (
    "模擬發布（演練用）：不會連到任何平台，程式會直接幫這個 Campaign 產生一整套"
    "示意資料——綁定、成效都是假的，只是為了讓畫面走得完整。"
)


def describe(campaign: dict) -> dict:  # noqa: ARG001 — 介面要求收 campaign，這裡用不到內容
    return {"adapter": "simulated", "message": DESCRIBE_MESSAGE, "checklist": []}


def _fake_external_id() -> str:
    return f"sim_{uuid.uuid4().hex[:10]}"


def _bind_and_record(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str, *,
                      target_kind: str, target_id: str, name: str, actor: str,
                      external_id: str, bind_row) -> None:
    bind_row(external_id=external_id, external_name=name, external_status="ACTIVE")
    ads_repo.record_action(
        conn, org_id, brand_id, campaign_id, target_kind=target_kind, target_id=target_id,
        kind="publish", before={}, after={"external_id": external_id, "external_name": name},
        approved_by=actor, sync_state="auto_synced", platform_ref=external_id,
    )


def _register_chain(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str,
                     detail: dict, ids: dict) -> None:
    """Contract R: campaign → adset → ad as `ads_external_entity` rows of the simulated
    platform; native ids = the fake ids the local nodes are about to be bound to."""
    campaign_native = ids[campaign_id]

    def entity(kind, native_id, name, parent=None, **extra):
        fields = {
            "platform": PLATFORM, "source_account": SOURCE_ACCOUNT, "native_kind": kind,
            "native_id": native_id, "name": name, "native_status": "ACTIVE",
            "start_date": detail["start_date"], "end_date": detail["end_date"], **extra,
        }
        if parent is not None:
            fields["parent_native_kind"], fields["parent_native_id"] = parent
        external_repository.upsert_entity(conn, org_id, brand_id, campaign_id, fields)

    entity("campaign", campaign_native, detail["name"])
    for group in detail["groups"]:
        entity(
            "adset", ids[group["id"]], group["name"], ("campaign", campaign_native),
            budget_type="daily", budget_amount=float(group["daily_budget"]), currency=CURRENCY,
        )
        for ad in group["ads"]:
            entity("ad", ids[ad["id"]], ad["name"], ("adset", ids[group["id"]]))


def publish(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str, *,
            actor: str) -> dict:
    """造假外部 id、先登記平台實體鏈（Contract R）、再逐節點綁定（campaign → 每個投放組 →
    每支廣告）、Campaign 轉 `live`，最後補齊成效——跟 `manual.publish` 不同的是這裡不留「等
    使用者回來配對」這一步，一次做完（決策 19：兩個通路實作，手動／模擬）。"""
    ads_repo.require_internal_campaign(conn, org_id, brand_id, campaign_id)
    detail = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)
    if detail is None:
        raise ValueError("campaign_unknown")
    daily_sum = ads_repo.group_budget_total(conn, org_id, brand_id, campaign_id)
    if daily_sum <= 0:
        raise ValueError("no_groups_to_publish")

    ids = {campaign_id: _fake_external_id()}
    for group in detail["groups"]:
        ids[group["id"]] = _fake_external_id()
        for ad in group["ads"]:
            ids[ad["id"]] = _fake_external_id()
    _register_chain(conn, org_id, brand_id, campaign_id, detail, ids)

    _bind_and_record(
        conn, org_id, brand_id, campaign_id, target_kind="campaign", target_id=campaign_id,
        name=detail["name"], actor=actor, external_id=ids[campaign_id],
        bind_row=lambda **kw: ads_repo.bind_campaign(conn, org_id, brand_id, campaign_id, **kw),
    )
    for group in detail["groups"]:
        _bind_and_record(
            conn, org_id, brand_id, campaign_id, target_kind="group", target_id=group["id"],
            name=group["name"], actor=actor, external_id=ids[group["id"]],
            bind_row=lambda g=group, **kw: ads_repo.bind_group(
                conn, org_id, brand_id, g["id"], **kw,
            ),
        )
        for ad in group["ads"]:
            _bind_and_record(
                conn, org_id, brand_id, campaign_id, target_kind="ad", target_id=ad["id"],
                name=ad["name"], actor=actor, external_id=ids[ad["id"]],
                bind_row=lambda a=ad, **kw: ads_repo.bind_ad(conn, org_id, brand_id, a["id"], **kw),
            )

    ads_repo.set_campaign_status(conn, org_id, brand_id, campaign_id, "live")
    generate_outcomes(conn, org_id, brand_id, campaign_id)
    return {"ok": True}


def _row(kind: str, native_id: str, day: date, *, spend, impressions, clicks, purchases,
         revenue) -> dict:
    return {
        "native_kind": kind, "native_id": native_id, "metric_scope": kind, "day": day,
        "spend": spend, "impressions": impressions, "clicks": clicks, "purchases": purchases,
        "revenue": revenue, "currency": CURRENCY, "attribution_key": ATTRIBUTION_KEY,
        "source": SOURCE,
    }


def day_rows(detail: dict, day: date, rng: random.Random) -> list[dict]:
    """Contract R: one day of simulated delivery for every bound group of `detail` -- a group
    (`adset`) row, then the ad rows of the ~80% of its bound ads that delivered that day, the
    group's numbers split by weight. Pure: no database; the numbers come from `rng` only."""
    out = []
    for group in detail["groups"]:
        if not group.get("external_id"):
            continue
        daily_budget = float(group["daily_budget"])
        spend = round(daily_budget * rng.uniform(0.7, 1.05), 2)
        cpa = rng.uniform(150, 450)
        purchases = max(0, round(spend / cpa)) if spend > 0 and cpa > 0 else 0
        roas = rng.uniform(0.8, 3.5)
        revenue = round(spend * roas, 2)
        impressions = int(spend * rng.uniform(28, 55))
        clicks = int(impressions * rng.uniform(0.008, 0.028))
        out.append(_row(
            "adset", group["external_id"], day, spend=spend, impressions=impressions,
            clicks=clicks, purchases=purchases, revenue=revenue,
        ))

        ads = [ad for ad in group.get("ads") or [] if ad.get("external_id")]
        active_ads = [ad for ad in ads if rng.random() < 0.8]  # ~81% 稀疏度量到的倒數（檔頭）
        if not active_ads:
            continue
        weights = [rng.uniform(0.5, 1.5) for _ in active_ads]
        weight_total = sum(weights)
        for ad, weight in zip(active_ads, weights, strict=True):
            share = weight / weight_total
            out.append(_row(
                "ad", ad["external_id"], day, spend=round(spend * share, 2),
                impressions=int(impressions * share), clicks=int(clicks * share),
                purchases=round(purchases * share), revenue=round(revenue * share, 2),
            ))
    return out


def day_rng(campaign_id: str, day: date, seed: int | None = None) -> random.Random:
    """The one seed rule for a simulated day: keyed by the campaign (or an explicit `seed`) and
    the day only, so a day's rows never depend on the window they were generated in --
    publish-time `generate_outcomes` and a later 重新讀取 (`SimulatedReader`) agree."""
    return random.Random(f"{campaign_id if seed is None else seed}:{day.isoformat()}")


def entity_ids(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str) -> dict:
    """`(native_kind, native_id) -> ads_external_entity.id` of this campaign's simulated chain."""
    return {
        (row["native_kind"], row["native_id"]): row["id"]
        for row in conn.execute(
            "SELECT id, native_kind, native_id FROM ads_external_entity WHERE org_id = %s"
            " AND brand_id = %s AND campaign_id = %s AND platform = %s AND source_account = %s",
            (org_id, brand_id, campaign_id, PLATFORM, SOURCE_ACCOUNT),
        ).fetchall()
    }


def write_rows(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str, rows: list,
               ids: dict) -> None:
    """Each row through `external_repository.upsert_observation`, like a platform read; a row
    whose node was never registered on the simulated platform is not written."""
    for row in rows:
        entity_id = ids.get((row["native_kind"], row["native_id"]))
        if entity_id is None:
            continue
        fields = {k: v for k, v in row.items() if k not in ("native_kind", "native_id")}
        external_repository.upsert_observation(
            conn, org_id, brand_id, campaign_id, {**fields, "entity_id": entity_id},
        )


def extend_coverage(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str,
                    campaign: dict, start: date, end: date) -> None:
    """Record `[start, end]` as read (F49 Contract V): `record_sync` joins it to the campaign's
    recorded ranges (`coverage.with_range`), so a disjoint range is kept beside the earlier ones
    and the days in between stay missing. `campaign` is kept in the signature for its callers."""
    del campaign
    external_repository.record_sync(
        conn, org_id, brand_id, campaign_id, section="observations",
        state={"status": "success", "last_success_at": now_utc().isoformat(),
               "coverage": {"start": start.isoformat(), "end": end.isoformat()}},
    )


def generate_outcomes(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str, *,
                       until: date | None = None, seed: int | None = None) -> None:
    """補齊 `start_date` 到 `min(end_date, until or today)` 每一天缺的成效——`until` 之外／
    今天之後一律不生（§0「nothing beyond today」）。每天的數字由 `day_rng(campaign_id, day)`
    決定，所以之後重新讀取平台（`SimulatedReader`）產生同一份數字；`seed` 給定時改用它當鍵，
    不同 Campaign 也得到同一份螢幕（驗收要能重跑）。寫完把這段範圍併進活動已讀到的覆蓋紀錄
    （Contract R）。"""
    ads_repo.require_internal_campaign(conn, org_id, brand_id, campaign_id)
    detail = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)
    if detail is None:
        raise ValueError("campaign_unknown")
    recovery = (detail.get("context_json") or {}).get("simulation_recovery")
    if detail["status"] == "closed" or recovery:
        return
    start_date = detail["start_date"]
    if start_date is None:
        return  # 沒有排期的 Campaign——沒有天數可以補

    today = coresettings.today_for_org(conn, org_id=org_id)
    end_date = until or today
    if detail["end_date"] is not None:
        end_date = min(end_date, detail["end_date"])
    end_date = min(end_date, today)  # 今天以後一律不生，即使 until 傳了未來的日期
    if end_date < start_date:
        return  # 還沒開始投放（未來才開始）——成效分頁誠實地空著

    existing = {
        (row["entity_id"], row["day"])
        for row in outcome.rows(conn, org_id, brand_id, campaign_id, "group")
    }
    ids = entity_ids(conn, org_id, brand_id, campaign_id)
    day = start_date
    while day <= end_date:
        # 這天已經有這個投放組的成效——整組（含底下廣告）跳過，不覆寫也不補洞
        skip = set()
        for group in detail["groups"]:
            if group.get("external_id") and (group["id"], day) in existing:
                skip.add(group["external_id"])
                skip.update(a["external_id"] for a in group["ads"] if a.get("external_id"))
        rows = [
            r for r in day_rows(detail, day, day_rng(campaign_id, day, seed))
            if r["native_id"] not in skip
        ]
        write_rows(conn, org_id, brand_id, campaign_id, rows, ids)
        day += timedelta(days=1)
    if ids:  # no simulated entity chain -> nothing was written, so nothing is marked read
        extend_coverage(conn, org_id, brand_id, campaign_id, detail, start_date, end_date)
