"""Existing task registration; dates prompt a review, never silently close an activity."""

from app import background
from app.background import app as background_app
from app.core.db import connection

_TASK_NAME = "background.ads_close_expired"
_DISPATCH_TASK_NAME = "ads.close_expired_dispatch"
_DISPATCH_PERIODIC_ID = "ads_close_expired"
_CLOSE_CRON = "0 4 * * *"


def close_expired_campaigns(org_id: str) -> None:
    """Compatibility handler for already-queued jobs: enqueue monitoring, never close."""
    from app.ads import runtime

    with connection() as conn:
        rows = conn.execute(
            "SELECT id,brand_id FROM ads_campaign WHERE org_id=%s "
            "AND status IN ('live','ended') AND end_date IS NOT NULL",
            (org_id,),
        ).fetchall()
    for row in rows:
        lock = "ads-runtime:" + row["id"]
        if not background.is_active(lock):
            background.enqueue(runtime.TASK, org_id=org_id, lock=lock,
                               brand_id=row["brand_id"], campaign_id=row["id"])


def _dispatch_close_expired(timestamp: int) -> None:
    from app.ads import runtime

    runtime.dispatch(timestamp)


def _dispatch_runtime_beat(timestamp: int):
    """Wraps the existing every-minute `runtime.dispatch` periodic task (F27-I00 Contract J) --
    records one `beat` runtime event (org_id/brand_id both `None`: a beat proves the whole ads
    background system is alive, never any one brand's own worker), prunes rows older than 48h once
    an hour (`timestamp` is a whole-minute epoch second from the cron scheduler, so `% 3600 == 0`
    fires exactly once per hour), then runs the unchanged `runtime.dispatch(timestamp)`."""
    from app.ads import runtime, runtime_events

    with connection() as conn:
        runtime_events.record(conn, "beat")
        if timestamp % 3600 == 0:
            runtime_events.prune(conn)
        conn.commit()
    return runtime.dispatch(timestamp)


def register_tasks() -> None:
    """掛兩個 task，冪等（可以呼叫任意次）——見本檔檔頭「為什麼不能只做一次」。"""
    a = background_app()
    if _TASK_NAME not in a.tasks:
        a.task(name=_TASK_NAME)(close_expired_campaigns)
    if _DISPATCH_TASK_NAME not in a.tasks:
        a.periodic(cron=_CLOSE_CRON, periodic_id=_DISPATCH_PERIODIC_ID)(
            a.task(name=_DISPATCH_TASK_NAME)(_dispatch_close_expired)
        )

    from app.ads import external_sync
    if external_sync.TASK not in a.tasks:
        a.task(name=external_sync.TASK)(external_sync.run_sync)
    if "ads.external_pending" not in a.tasks:
        a.periodic(cron="* * * * *",periodic_id="ads_external_pending")(
            a.task(name="ads.external_pending")(external_sync.dispatch_pending))
    if "ads.external_daily" not in a.tasks:
        a.periodic(cron="0 5 * * *",periodic_id="ads_external_daily")(
            a.task(name="ads.external_daily")(external_sync.dispatch_daily))

    from app.ads import user_assets
    if user_assets.TASK not in a.tasks:
        a.task(name=user_assets.TASK)(user_assets.process_preview)
    if "ads.user_asset_pending" not in a.tasks:
        a.periodic(cron="* * * * *",periodic_id="ads_user_asset_pending")(
            a.task(name="ads.user_asset_pending")(user_assets.dispatch_pending))

    from app.ads import asset_suggestions
    if asset_suggestions.TASK not in a.tasks:
        a.task(name=asset_suggestions.TASK)(asset_suggestions.run)
    if "ads.asset_suggestion_pending" not in a.tasks:
        a.periodic(cron="* * * * *",periodic_id="ads_asset_suggestion_pending")(
            a.task(name="ads.asset_suggestion_pending")(asset_suggestions.dispatch_pending))

    from app.ads import runtime
    if runtime.TASK not in a.tasks:
        a.task(name=runtime.TASK)(runtime.run_campaign)
    if "ads.runtime_dispatch" not in a.tasks:
        a.periodic(cron="* * * * *", periodic_id="ads_runtime")(
            a.task(name="ads.runtime_dispatch")(_dispatch_runtime_beat))
