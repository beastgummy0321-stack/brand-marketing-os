"""app/ads/adapters/simulated.py — F03-I10: 沒有平台的通路（演練／驗收用），實作跟
`manual` 同一份三方法介面（`app.ads.adapters` 的介面）。`publish` 不等使用者到平台後台，
直接自己造假外部 id、綁定每一個節點、把 Campaign 推到 `live`，接著把 `start_date` 到今天
的每一天成效都補齊——所以一個人在瀏覽器裡點「模擬發布」，下一秒切到成效分頁就有數字可看，
不必再跑一次命令列（§0「pluggable — delete it and the product still works, but acceptance
and drills lose their legs」）。

`generate_outcomes()` 是這個檔案唯一會被 `demo.py`／`routes.py`（F03-I11 的更新鈕）再叫一次
的函式，逐日、逐投放組地檢查──那一天這個投放組已經有一列成效就整天跳過（含底下的廣告），
沒有才生：先寫一列投放組層（穩定，永遠有），再灑一批廣告層（刻意稀疏，比照
`app/tools/simulate_meta_spend.py` 檔頭量到的「81% 廣告×日沒有列」，這裡用「~80% 出現」
換算），金額拆分只是把投放組那天的花費／購買／營收按權重分掉，不是另一套獨立算出來的數字
——campaign 層的花費永遠只讀投放組層（§0「money totals belong to the group level」），
廣告層只是拿來算花費占比。
"""

import random
import uuid
from datetime import date, timedelta

from app.ads import repository as ads_repo
from app.core import settings as coresettings
from app.core.db import Conn, ConnProxy, new_id

_AnyConn = Conn | ConnProxy

DESCRIBE_MESSAGE = (
    "模擬發布（演練用）：不會連到任何平台，程式會直接幫這個 Campaign 產生一整套"
    "示意資料——綁定、成效都是假的，只是為了讓畫面走得完整。"
)
BOUND_MESSAGE = "模擬發布已自動配對"


def describe(campaign: dict) -> dict:  # noqa: ARG001 — 介面要求收 campaign，這裡用不到內容
    return {"adapter": "simulated", "message": DESCRIBE_MESSAGE, "checklist": []}


def _fake_external_id() -> str:
    return f"sim_{uuid.uuid4().hex[:10]}"


def _bind_and_record(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str, *,
                      target_kind: str, target_id: str, name: str, actor: str,
                      bind_row) -> None:
    external_id = _fake_external_id()
    bind_row(external_id=external_id, external_name=name, external_status="ACTIVE")
    ads_repo.record_action(
        conn, org_id, brand_id, campaign_id, target_kind=target_kind, target_id=target_id,
        kind="publish", before={}, after={"external_id": external_id, "external_name": name},
        approved_by=actor, sync_state="auto_synced", platform_ref=external_id,
    )


def publish(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str, *,
            actor: str) -> dict:
    """造假外部 id、逐節點綁定（campaign → 每個投放組 → 每支廣告）、Campaign 轉 `live`，
    最後補齊成效——跟 `manual.publish` 不同的是這裡不留「等使用者回來配對」這一步，
    一次做完（決策 19：兩個通路實作，手動／模擬）。"""
    detail = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)
    if detail is None:
        raise ValueError("campaign_unknown")
    daily_sum = ads_repo.group_budget_total(conn, org_id, brand_id, campaign_id)
    if daily_sum <= 0:
        raise ValueError("no_groups_to_publish")

    _bind_and_record(
        conn, org_id, brand_id, campaign_id, target_kind="campaign", target_id=campaign_id,
        name=detail["name"], actor=actor,
        bind_row=lambda **kw: ads_repo.bind_campaign(conn, org_id, brand_id, campaign_id, **kw),
    )
    for group in detail["groups"]:
        _bind_and_record(
            conn, org_id, brand_id, campaign_id, target_kind="group", target_id=group["id"],
            name=group["name"], actor=actor,
            bind_row=lambda g=group, **kw: ads_repo.bind_group(
                conn, org_id, brand_id, g["id"], **kw,
            ),
        )
        for ad in group["ads"]:
            _bind_and_record(
                conn, org_id, brand_id, campaign_id, target_kind="ad", target_id=ad["id"],
                name=ad["name"], actor=actor,
                bind_row=lambda a=ad, **kw: ads_repo.bind_ad(conn, org_id, brand_id, a["id"], **kw),
            )

    ads_repo.set_campaign_status(conn, org_id, brand_id, campaign_id, "live")
    generate_outcomes(conn, org_id, brand_id, campaign_id)
    return {"ok": True}


def bind(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str, *,
         actor: str) -> dict:  # noqa: ARG001 — 介面要求收 actor，模擬通路不需要它
    """冪等空操作——`publish` 已經自己綁完了，「配對」只是把同一份 campaign_detail 原樣
    回報一次（決策 19：模擬通路不需要使用者再按一次配對）。"""
    campaign = ads_repo.get_campaign(conn, org_id, brand_id, campaign_id)
    if campaign is None:
        raise ValueError("campaign_unknown")
    return {"message": BOUND_MESSAGE, "campaign": ads_repo.campaign_detail(
        conn, org_id, brand_id, campaign_id,
    )}


def _group_day_exists(conn: _AnyConn, org_id: str, brand_id: str, group_id: str,
                       day: date) -> bool:
    row = conn.execute(
        "SELECT 1 FROM ads_outcome_daily WHERE org_id = %s AND brand_id = %s"
        " AND entity_kind = 'group' AND entity_id = %s AND day = %s",
        (org_id, brand_id, group_id, day),
    ).fetchone()
    return row is not None


def _insert_outcome(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str, *,
                     entity_kind: str, entity_id: str, day: date, spend: float,
                     impressions: int, clicks: int, purchases: int, revenue: float) -> None:
    conn.execute(
        "INSERT INTO ads_outcome_daily (id, org_id, brand_id, campaign_id, entity_kind,"
        " entity_id, day, spend, impressions, clicks, purchases, revenue, source)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'simulated')",
        (new_id("ado"), org_id, brand_id, campaign_id, entity_kind, entity_id, day, spend,
         impressions, clicks, purchases, revenue),
    )


def _generate_group_day(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str,
                         group: dict, day: date, rng: random.Random) -> None:
    if _group_day_exists(conn, org_id, brand_id, group["id"], day):
        return  # 這天已經有這個投放組的成效——整天（含底下廣告）跳過，不覆寫也不補洞

    daily_budget = float(group["daily_budget"])
    spend = round(daily_budget * rng.uniform(0.7, 1.05), 2)
    cpa = rng.uniform(150, 450)
    purchases = max(0, round(spend / cpa)) if spend > 0 and cpa > 0 else 0
    roas = rng.uniform(0.8, 3.5)
    revenue = round(spend * roas, 2)
    impressions = int(spend * rng.uniform(28, 55))
    clicks = int(impressions * rng.uniform(0.008, 0.028))
    _insert_outcome(
        conn, org_id, brand_id, campaign_id, entity_kind="group", entity_id=group["id"],
        day=day, spend=spend, impressions=impressions, clicks=clicks, purchases=purchases,
        revenue=revenue,
    )

    ads = group.get("ads") or []
    active_ads = [ad for ad in ads if rng.random() < 0.8]  # ~81% 稀疏度量到的倒數（檔頭）
    if not active_ads:
        return
    weights = [rng.uniform(0.5, 1.5) for _ in active_ads]
    weight_total = sum(weights)
    for ad, weight in zip(active_ads, weights, strict=True):
        share = weight / weight_total
        _insert_outcome(
            conn, org_id, brand_id, campaign_id, entity_kind="ad", entity_id=ad["id"], day=day,
            spend=round(spend * share, 2), impressions=int(impressions * share),
            clicks=int(clicks * share), purchases=round(purchases * share),
            revenue=round(revenue * share, 2),
        )


def generate_outcomes(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str, *,
                       until: date | None = None, seed: int | None = None) -> None:
    """補齊 `start_date` 到 `min(end_date, until or today)` 每一天缺的成效——`until` 之外／
    今天之後一律不生（§0「nothing beyond today」），`seed` 給定時整批可重現（驗收要能重跑同
    一份螢幕）。"""
    detail = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)
    if detail is None:
        raise ValueError("campaign_unknown")
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

    rng = random.Random(seed)
    day = start_date
    while day <= end_date:
        for group in detail["groups"]:
            _generate_group_day(conn, org_id, brand_id, campaign_id, group, day, rng)
        day += timedelta(days=1)
