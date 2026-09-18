"""app/ads/jobs.py — F03-I12: closes campaigns unattended, 7 days after they end, the same
verdict+learning a manual close would write. Private to app/ads (container contract §1): only
`app/ads/__init__.py` imports this.

`register_tasks()` follows `app/meta/daily_pull.py`'s exact pattern (docstring there has the
full "why"): `app.background.app()` rebuilds whenever the DSN changes, so a task registered once
at import time silently stops being live after any DSN change — every caller that gets a fresh
`background.app()` (each test module) must call this again. The handler
(`close_expired_campaigns`) is `"background."`-prefixed and takes a required `org_id`
(`TaskSignatureOrgIdGateTest`, ADR 0038); the periodic dispatch (`ads.close_expired_dispatch`)
is not — it has no single org to scope to, same reasoning as `meta.daily_pull_dispatch`.
"""

from datetime import timedelta

from app.ads import closeout
from app.background import app as background_app
from app.core import settings as coresettings
from app.core.db import connection

_TASK_NAME = "background.ads_close_expired"
_DISPATCH_TASK_NAME = "ads.close_expired_dispatch"
_DISPATCH_PERIODIC_ID = "ads_close_expired"
_CLOSE_CRON = "0 4 * * *"  # 每天一次，晚於 Meta 每日拉取（3am）——結案讀的是已經拉好的成效。

_EXPIRY_DAYS = 7


def close_expired_campaigns(org_id: str) -> None:
    """procrastinate task body：這個組織裡，`end_date` 超過 7 天、狀態還停在 `live`／
    `ended` 的 Campaign 全部結案。冪等——`closeout.close()` 本身對已經 `closed` 的列是
    no-op，一段結完就 commit，一個 Campaign 結案失敗不擋其他 Campaign（跟
    `daily_pull.backfill()` 同一個「一段一存」理由）。"""
    with connection() as conn:
        today = coresettings.today_for_org(conn, org_id=org_id)
        cutoff = today - timedelta(days=_EXPIRY_DAYS)
        rows = conn.execute(
            "SELECT id, brand_id FROM ads_campaign WHERE org_id = %s"
            " AND origin = 'internal' AND status IN ('live', 'ended')"
            " AND end_date IS NOT NULL AND end_date <= %s",
            (org_id, cutoff),
        ).fetchall()
        for row in rows:
            closeout.close(
                conn, org_id, row["brand_id"], row["id"], actor="system:auto_close",
            )
            conn.commit()


def _dispatch_close_expired(timestamp: int) -> None:  # noqa: ARG001 — procrastinate periodic 簽名要求
    """一天觸發一次，對每個有 `live`／`ended` Campaign 的組織各 defer 一個
    `background.ads_close_expired` job——同 `meta.daily_pull_dispatch` 的兩段式模式。"""
    with connection() as conn:
        org_ids = [
            row["org_id"] for row in conn.execute(
                "SELECT DISTINCT org_id FROM ads_campaign WHERE origin = 'internal'"
                " AND status IN ('live', 'ended')",
            ).fetchall()
        ]
    a = background_app()
    for org_id in org_ids:
        a.configure_task(_TASK_NAME).defer(org_id=org_id)


def register_tasks() -> None:
    """掛兩個 task，冪等（可以呼叫任意次）——見本檔檔頭「為什麼不能只做一次」。"""
    a = background_app()
    if _TASK_NAME not in a.tasks:
        a.task(name=_TASK_NAME)(close_expired_campaigns)
    if _DISPATCH_TASK_NAME not in a.tasks:
        a.periodic(cron=_CLOSE_CRON, periodic_id=_DISPATCH_PERIODIC_ID)(
            a.task(name=_DISPATCH_TASK_NAME)(_dispatch_close_expired)
        )
