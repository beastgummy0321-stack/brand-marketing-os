"""Existing task registration; dates prompt a review, never silently close an activity."""

import logging

from app import background
from app.core.db import connection

logger = logging.getLogger(__name__)

_TASK_NAME = "background.ads_close_expired"
_DISPATCH_TASK_NAME = "ads.close_expired_dispatch"
_DISPATCH_PERIODIC_ID = "ads_close_expired"
_CLOSE_CRON = "0 4 * * *"


def close_expired_campaigns(org_id: str) -> None:
    """Compatibility handler for already-queued jobs: enqueue monitoring, never close. Only the
    campaigns the lifecycle still monitors (F49 Contract N: live, or ended within the grace days),
    the same set `runtime.dispatch` reads."""
    from app.ads import lifecycle, runtime

    with connection() as conn:
        rows = [
            (brand["brand_id"], campaign_id)
            for brand in lifecycle.brands(conn, lifecycle.NOT_CLOSED) if brand["org_id"] == org_id
            for campaign_id in sorted(lifecycle.monitored_ids(conn, org_id, brand["brand_id"]))
        ]
    for brand_id, campaign_id in rows:
        lock = "ads-runtime:" + campaign_id
        if not background.is_active(lock):
            background.enqueue(runtime.TASK, org_id=org_id, lock=lock,
                               brand_id=brand_id, campaign_id=campaign_id)


def _dispatch_close_expired(timestamp: int) -> None:
    from app.ads import runtime

    runtime.dispatch(timestamp)


def _dispatch_queue_refresh(timestamp: int) -> None:  # noqa: ARG001 -- cron passes a timestamp
    """Contract I / Done #1: the daily brand-wide triage queue refresh -- runs
    `triage.refresh_queue` (re-classify + raise/supersede queue rows) for every brand that has at
    least one non-closed `ads_campaign`, right after the 05:00 external sync periodic
    (`ads_external_daily`, `_dispatch_close_expired`'s own `_CLOSE_CRON` runs at 04:00 -- this one
    is offset later so a freshly synced day's numbers are already committed before the queue
    re-reads them). Same "one distinct (org_id, brand_id) over non-closed campaigns" query shape
    `_dispatch_runtime_beat` above already uses -- never a second, divergent "active brand" list.

    F29-I08 Contract J: right after each brand's refresh, its daily digest is built from the
    payload that refresh just returned and handed to every `digest.SENDERS` channel. One brand
    failing (refresh or digest) is rolled back and logged; the other brands still run, and a brand
    whose refresh raised gets no digest.
    """
    from app.ads import digest, lifecycle, triage
    from app.core import settings as coresettings

    with connection() as conn:
        active_brands = lifecycle.brands(conn, lifecycle.NOT_CLOSED)
        for row in active_brands:
            org_id, brand_id = row["org_id"], row["brand_id"]
            try:
                queue = triage.refresh_queue(conn, org_id, brand_id)
                today = coresettings.today_for_org(conn, org_id=org_id)
                digest.deliver(conn, org_id, brand_id, today, queue=queue)
            except Exception:
                conn.rollback()
                logger.exception("daily queue refresh/digest failed for brand %s", brand_id)


def _dispatch_runtime_beat(timestamp: int):
    """Wraps the existing every-minute `runtime.dispatch` periodic task (F27-I00 Contract J,
    rescoped by F27-I24 correction 12) -- records one `beat` runtime event per (org_id, brand_id)
    that currently has at least one non-closed `ads_campaign` (one query per minute; the same
    `lifecycle.brands` selector `_dispatch_queue_refresh` uses), proving that brand's own slice of
    the ads background system is alive. Prunes rows older than 48h once an hour (`timestamp` is a
    whole-minute epoch second from the cron scheduler, so `% 3600 == 0` fires exactly once per
    hour), then runs the unchanged `runtime.dispatch(timestamp)`."""
    from app.ads import lifecycle, runtime, runtime_events

    with connection() as conn:
        active_brands = lifecycle.brands(conn, lifecycle.NOT_CLOSED)
        for row in active_brands:
            runtime_events.record(conn, "beat", org_id=row["org_id"], brand_id=row["brand_id"])
        if timestamp % 3600 == 0:
            runtime_events.prune(conn)
        conn.commit()
    return runtime.dispatch(timestamp)


def register_tasks() -> None:
    """掛 ads 的 task，冪等（可以呼叫任意次）——見本檔檔頭「為什麼不能只做一次」。
    F50-I07: every one goes through `background.register` (Contract J)."""
    background.register(_TASK_NAME, close_expired_campaigns)
    background.register(_DISPATCH_TASK_NAME, _dispatch_close_expired,
                        cron=_CLOSE_CRON, periodic_id=_DISPATCH_PERIODIC_ID)

    from app.ads import external_sync
    background.register(external_sync.TASK, external_sync.run_sync)
    background.register("ads.external_pending", external_sync.dispatch_pending,
                        cron="* * * * *", periodic_id="ads_external_pending")
    background.register("ads.external_daily", external_sync.dispatch_daily,
                        cron="0 5 * * *", periodic_id="ads_external_daily")
    background.register("ads.queue_refresh_daily", _dispatch_queue_refresh,
                        cron="30 6 * * *", periodic_id="ads_queue_refresh_daily")

    from app.ads import user_assets
    background.register(user_assets.TASK, user_assets.process_preview)
    background.register("ads.user_asset_pending", user_assets.dispatch_pending,
                        cron="* * * * *", periodic_id="ads_user_asset_pending")

    from app.ads import asset_suggestions
    background.register(asset_suggestions.TASK, asset_suggestions.run)
    background.register("ads.asset_suggestion_pending", asset_suggestions.dispatch_pending,
                        cron="* * * * *", periodic_id="ads_asset_suggestion_pending")

    from app.ads import runtime
    background.register(runtime.TASK, runtime.run_campaign)
    background.register("ads.runtime_dispatch", _dispatch_runtime_beat,
                        cron="* * * * *", periodic_id="ads_runtime")
