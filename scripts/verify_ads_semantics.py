"""Bounded F55 proof on owned PostgreSQL/services, with platform/model transports stubbed."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

import httpx
import psycopg
from psycopg.conninfo import conninfo_to_dict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class IsolationError(RuntimeError):
    pass


def preflight(args):
    from scripts import verify_existing_campaigns_assets as lifecycle

    if not args.isolated:
        raise IsolationError("isolation_confirmation_required")
    values = lifecycle.resolved_env(args, root=ROOT)
    params = conninfo_to_dict(values.get("DATABASE_URL", ""))
    database = params.get("dbname", "")
    if params.get("host") not in {"localhost", "127.0.0.1", "::1"} or not re.fullmatch(
        r"f15_validation_f55_[a-f0-9]{10}", database
    ):
        raise IsolationError("shared_or_remote_database_refused")
    receipt = json.loads(Path(args.ownership_file).read_text("utf-8-sig"))
    if receipt.get("owner") != "F55" or receipt.get("database") != database:
        raise IsolationError("database_ownership_mismatch")
    service = urlparse(values.get("SUPABASE_URL", ""))
    if service.hostname not in {"localhost", "127.0.0.1"} or service.username or service.password:
        raise IsolationError("external_service_refused")
    health = httpx.get(values["SUPABASE_URL"] + "/health", timeout=3, trust_env=False).json()
    if health.get("mode") != "owned-auth-storage-stub" or health.get("database") != database:
        raise IsolationError("service_ownership_unverified")
    with psycopg.connect(values["DATABASE_URL"], connect_timeout=3) as observer:
        if observer.execute("SELECT current_database()").fetchone()[0] != database:
            raise IsolationError("database_identity_mismatch")
    return {"database": database, "service_mode": health["mode"], "writes": "owned_schema_only"}


def concurrent_close(run):
    from psycopg.rows import dict_row

    from app.ads import coverage, plan, repository
    from app.core.db import Conn
    from app.tests.fixtures.ads_external import outcome_seed

    org, brand = run.context["org_id"], run.context["brand_id"]
    with psycopg.connect(run.scoped_dsn, row_factory=dict_row) as pg:
        conn = Conn(pg)
        day = coverage.last_complete_day(conn, org, brand)
        campaign = repository.create_campaign(
            conn,
            org,
            brand,
            {
                "name": "F55 lead close",
                "goal_text": "Lead followup",
                "objective": "名單",
                "status": "live",
                "start_date": day - timedelta(days=2),
                "end_date": day,
            },
            created_by="isolated-runtime",
        )
        repository.save_campaign_target(
            conn,
            org,
            brand,
            campaign["id"],
            basis="own",
            value=100,
            expected_revision=0,
            actor="isolated-runtime",
        )
        group = plan.create_group(
            conn, org, brand, campaign["id"], name="F55 group", role="new", daily_budget=1000
        )
        for offset in range(3):
            outcome_seed.seed_day(
                conn,
                org,
                brand,
                campaign["id"],
                "group",
                group["id"],
                day - timedelta(days=offset),
                spend=1000,
                purchases=1,
                result_kind="lead",
                result_count=10,
            )
        outcome_seed.set_coverage(conn, org, brand, campaign["id"], day - timedelta(days=2), day)
        conn.commit()
    route = f"/api/ads/brands/{brand}/campaigns/{campaign['id']}"
    perf = run.call("GET", route + "/performance")
    assert perf["result_view"]["count"] == 30 and perf["result_view"]["cost_per_result"] == 100
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run.call, "POST", route + "/close", json={}) for _ in range(2)]
        rows = [future.result()["campaign"] for future in futures]
    assert rows[0]["verdict_json"]["learning_ids"] == rows[1]["verdict_json"]["learning_ids"]
    assert rows[0]["closed_at"] == rows[1]["closed_at"]
    assert rows[0]["verdict_json"]["actual"] == 100
    assert rows[0]["verdict_json"]["result_kind"] == "lead"
    ids = rows[0]["verdict_json"]["learning_ids"]
    stored = run.query("SELECT id FROM learning_ledger WHERE id=ANY(%s)", (ids,))
    assert len(stored) == len(ids) == 1
    again = run.call("POST", route + "/close", json={})["campaign"]
    assert again["verdict_json"]["learning_ids"] == ids
    reread = run.call("GET", route)["campaign"]
    assert "每次名單成本" in reread["learning_sentence"]
    foreign = run.client.post(
        route.replace(brand, run.context["second_brand_id"]) + "/close",
        json={},
        timeout=run.remaining(),
    )
    assert foreign.status_code == 404
    return {
        "concurrent_http_close": True,
        "learning_sets": 1,
        "repeat_identity_preserved": True,
        "foreign_brand_refused": True,
        "lead_cost": 100,
        "purchase_cpa_not_used": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--isolated", action="store_true")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--env-file")
    parser.add_argument(
        "--ownership-file", default=str(ROOT / ".harness/scratch/F55/database-ownership.json")
    )
    parser.add_argument("--context")
    parser.add_argument("--port", type=int, default=18756)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.timeout <= 300 or not 8731 <= args.port <= 65535:
        parser.error("Use a timeout of at most 300 seconds and an isolated port")
    try:
        isolation = preflight(args)
    except (IsolationError, OSError, ValueError, httpx.HTTPError, psycopg.Error) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "preflight": "refused",
                    "code": str(exc) if isinstance(exc, IsolationError) else type(exc).__name__,
                }
            )
        )
        return 2
    if args.check_only:
        print(json.dumps({"ok": True, "preflight": isolation}))
        return 0
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        os.environ.pop(key, None)
    os.environ["NO_PROXY"] = "127.0.0.1,localhost,::1"
    from scripts import verify_ads_cycle_evidence as evidence
    from scripts import verify_ads_cycle_runtime as cycle

    if not args.context:
        directory = ROOT / ".harness/scratch/F55/runtime"
        directory.mkdir(parents=True, exist_ok=True)
        args.context = str(directory / "context.json")
    run = cycle.Runtime(args)
    result = {
        "ok": False,
        "isolation": isolation,
        "data_mode": "synthetic-platform-model-auth-storage; real PostgreSQL/HTTP/worker",
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    try:
        run.setup()
        route = cycle.source_recovery(run)
        evidence.import_commerce(run)
        cycle.review_recovery(run, route)
        evidence.new_test_source(run, route)
        evidence.monitor_conditions(run, route)
        evidence.next_round(run, route)
        result.update(concurrent_close(run))
        result.update(
            ok=True,
            source_worker_recovery=True,
            saved_output_zero_repeat=True,
            unknown_call_not_resent=True,
            queue="owned PostgreSQL",
            simulated_provider_calls=run.count_calls(),
            elapsed_seconds=round(time.monotonic() - run.started, 2),
            manual_work={
                "A": [
                    "verify source/unknowns",
                    "approve or defer",
                    "confirm platform action/readback",
                    "judge next-period applicability",
                ],
                "B": [
                    "verify product/audience/claims",
                    "adopt strategy/budget",
                    "produce final image/video",
                    "approve and perform platform handoff",
                ],
            },
            human_usefulness="pending",
            commercial_effect="unverified",
        )
    except Exception as exc:
        result["failure_type"] = type(exc).__name__
        raise
    finally:
        try:
            run.cleanup()
            result["cleanup"] = json.loads((run.directory / "cleanup.json").read_text("utf-8"))
        finally:
            (run.directory / "semantics-result.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), "utf-8"
            )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
