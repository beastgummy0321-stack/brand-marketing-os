"""Queue-only startup recovery. Caller must already own the schema worker lock."""

import asyncio
from collections.abc import Collection
from datetime import UTC, datetime

import procrastinate
from procrastinate.exceptions import UniqueViolation
from procrastinate.jobs import Status
from procrastinate.manager import QUEUEING_LOCK_CONSTRAINT

# No prefix matching: adding a task requires checking its side effects first.
# The legacy Meta handlers recompute their existing date window on restart;
# only ads_external_sync promises to resume saved per-page conditions/cursors.
READ_ONLY_TASKS = frozenset(
    {
        "background.ads_external_sync",
        "ads.external_pending",
        "ads.external_daily",
        "background.meta_daily_pull",
        "background.meta_backfill",
        "meta.daily_pull_dispatch",
        "background.ads_runtime_campaign",
        "ads.runtime_dispatch",
    }
)
FAILED_TASKS = frozenset({"background.ads_review_round"})


def recover(
    dsn: str,
    *,
    retry_tasks: Collection[str] | None,
    fail_tasks: Collection[str] | None,
    limit: int,
) -> dict:
    retry = READ_ONLY_TASKS if retry_tasks is None else frozenset(retry_tasks)
    fail = FAILED_TASKS if fail_tasks is None else frozenset(fail_tasks)
    if not retry <= READ_ONLY_TASKS or not fail <= FAILED_TASKS:
        raise ValueError("Recovery requires an explicitly supported task name")
    if not 1 <= limit <= 1000:
        raise ValueError("Recovery limit must be between 1 and 1000")
    return asyncio.run(_recover(dsn, retry, fail, limit))


async def _recover(dsn: str, retry: frozenset[str], fail: frozenset[str], limit: int) -> dict:
    receipt: dict[str, list[int]] = {
        "retried_ids": [],
        "failed_ids": [],
        "aborted_ids": [],
        "deferred_ids": [],
    }
    # A short-lived async app avoids mixing the worker's later event loop with the
    # sync enqueue connector; finish_job has only an async public manager method.
    app = procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=dsn))
    async with app.open_async():
        manager = app.job_manager
        orphans = []
        for task in sorted(retry | fail):
            orphans.extend(await manager.list_jobs_async(task=task, status="doing"))
        orphans.sort(key=lambda job: job.id or 0)
        # list_jobs has no SQL limit; this bounds mutations, not query pagination.
        receipt["deferred_ids"] = [job.id for job in orphans[limit:] if job.id is not None]
        for job in orphans[:limit]:
            assert job.id is not None
            if job.abort_requested:
                await manager.finish_job_by_id_async(job.id, Status.ABORTED, delete_job=False)
                receipt["aborted_ids"].append(job.id)
                continue
            waiting = job.queueing_lock and await manager.list_jobs_async(
                queueing_lock=job.queueing_lock,
                status="todo",
            )
            if job.task_name in fail or waiting:
                await manager.finish_job_by_id_async(job.id, Status.FAILED, delete_job=False)
                receipt["failed_ids"].append(job.id)
                continue
            try:
                await manager.retry_job_by_id_async(job.id, retry_at=datetime.now(UTC))
            except UniqueViolation as exc:
                # Enqueue can race the initial check; its transaction is separate.
                if exc.constraint_name != QUEUEING_LOCK_CONSTRAINT or not job.queueing_lock:
                    raise
                if not await manager.list_jobs_async(
                    queueing_lock=job.queueing_lock,
                    status="todo",
                ):
                    raise
                await manager.finish_job_by_id_async(job.id, Status.FAILED, delete_job=False)
            # The retry SQL atomically honors a concurrent abort by ending failed.
            status = await manager.get_job_status_async(job.id)
            key = "retried_ids" if status == Status.TODO else "failed_ids"
            receipt[key].append(job.id)
    return receipt
