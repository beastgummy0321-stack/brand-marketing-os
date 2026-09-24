"""app/ads/demo.py — F03-I10 CLI convenience: 一個人在瀏覽器裡點過每一個分頁，不用先讓
Meta 真的跑一支廣告（鐵律：不要求、不提醒使用者實機投放 Meta）。建一個（或沿用既有的）
示範 Campaign、用 `app.ads.adapters.simulated` 發布它、把成效補到今天——三步都做完才印結果，
所以跑完這支腳本，直接開瀏覽器就能看到有資料的成效分頁。

CLI：`uv run --env-file .env python -m app.ads.demo --org <org> --brand <brand> [--days 14]`。
只准在 `BRAND_OS_ENV != production` 執行——跟 `app/tools/simulate_meta_spend.py` 同一條既有環境宣告。
"""

import argparse
from datetime import timedelta

from app.ads import plan
from app.ads import repository as ads_repo
from app.ads.adapters import simulated
from app.core import settings as coresettings
from app.core.db import connection

ACTOR = "demo"
CAMPAIGN_NAME = "示範 Campaign（模擬發布）"

_COORDINATES = {
    "audience": "demo_audience", "pain": "demo_pain", "angle": "demo_angle",
    "hook": "demo_hook", "proof": "demo_proof", "offer": "demo_offer", "format": "demo_format",
}


def _existing_campaign(conn, org_id: str, brand_id: str) -> dict | None:
    for row in ads_repo.list_campaigns(conn, org_id, brand_id):
        if row["name"] == CAMPAIGN_NAME:
            return ads_repo.get_campaign(conn, org_id, brand_id, row["id"])
    return None


def _create_campaign(conn, org_id: str, brand_id: str, *, days: int) -> dict:
    today = coresettings.today_for_org(conn, org_id=org_id)
    start = today - timedelta(days=max(days - 1, 0))
    campaign = ads_repo.create_campaign(conn, org_id, brand_id, {
        "name": CAMPAIGN_NAME, "goal_text": "示範投放中心整個閉環，從發布走到成效",
        "objective": "購買", "target_cost": 300,
        "start_date": start, "end_date": today, "status": "draft",
    }, created_by=ACTOR)
    group = plan.create_group(
        conn, org_id, brand_id, campaign["id"], name="示範投放組", role="new", daily_budget=500,
    )
    plan.create_ad(
        conn, org_id, brand_id, campaign["id"], group["id"], name="示範廣告一",
        coordinates=_COORDINATES,
    )
    row = ads_repo.get_campaign(conn, org_id, brand_id, campaign["id"])
    assert row is not None
    return row


def run(org_id: str, brand_id: str, *, days: int = 14) -> dict:
    with connection() as conn:
        campaign = _existing_campaign(conn, org_id, brand_id)
        if campaign is None:
            campaign = _create_campaign(conn, org_id, brand_id, days=days)
        if campaign["status"] == "live":
            simulated.generate_outcomes(conn, org_id, brand_id, campaign["id"])
        else:
            simulated.publish(conn, org_id, brand_id, campaign["id"], actor=ACTOR)
        detail = ads_repo.campaign_detail(conn, org_id, brand_id, campaign["id"])
        assert detail is not None
        return detail


if __name__ == "__main__":
    # `.env` 靠 `uv run --env-file .env` 載入，不 `import app.main`：A4 憲法禁止
    # `app/ads/**` 匯入組裝根（`test_no_branch_imports_app_main.py` 掃 __main__ 匯入）。
    from app.core.config import settings

    if settings().brand_os_env == "production":
        raise SystemExit(
            "app.ads.demo 只能在 BRAND_OS_ENV != production 時執行——這支腳本會直接灌一個"
            "模擬發布的示範 Campaign，正式環境絕對不能跑到。"
        )

    _parser = argparse.ArgumentParser(
        prog="uv run --env-file .env python -m app.ads.demo",
        description="示範投放中心整個閉環：建（或沿用）一個 Campaign、模擬發布、補齊成效。",
    )
    _parser.add_argument("--org", required=True, help="組織 id，例如 org_bughunt")
    _parser.add_argument("--brand", required=True, help="品牌 id，例如 brd_bughunt")
    _parser.add_argument("--days", type=int, default=14, help="示範 Campaign 的天數（預設 14）")
    _args = _parser.parse_args()

    _detail = run(_args.org, _args.brand, days=_args.days)
    print(
        f"示範資料完成：campaign_id={_detail['id']} status={_detail['status']} "
        f"成效={_detail['outcome']}"
    )
