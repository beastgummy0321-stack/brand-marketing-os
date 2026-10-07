"""F13 real HTTP/DB/Storage lifecycle in a disposable schema; no paid/platform writes.

--isolated --timeout 180 runs the bounded runtime and always cleans its resources.
Only this test process injects source readers, providers, and a queue dispatcher.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.tests.fixtures.ads_external.runtime import (  # noqa: E402
    FIXTURE,
    install_assembly,
    read_json,
    write_json,
)


def child(args):
    import uvicorn
    from fastapi import Request

    globals()["Request"] = Request

    context = read_json(args.context)
    thread, stopped, stats = install_assembly(context)
    from app.main import app

    @app.get("/__f13/state")
    def state():
        return {**read_json(context["state_file"]), **stats}

    @app.post("/__f13/state")
    async def update(request: Request):
        body = await request.json()
        if set(body) - {"creative_revision", "fail_next", "paused"}:
            return {"error": "Only fixture source flags may change"}
        value = read_json(context["state_file"])
        value.update(body)
        write_json(context["state_file"], value)
        return value

    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)
    )

    @app.post("/__f13/stop")
    def shutdown():
        server.should_exit = True
        return {"stopping": True}

    thread.start()
    try:
        server.run()
    finally:
        stopped.set()
        thread.join(timeout=35)


def safe_env(args):
    allowed = {
        "DATABASE_URL",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_JWT_SECRET",
        "IDENTITY_ALLOW_HS256",
        "VITE_SUPABASE_URL",
        "VITE_SUPABASE_ANON_KEY",
    }
    path = Path(args.env_file) if args.env_file else ROOT / ".env"
    values = {}
    if path.exists():
        for line in path.read_text("utf-8-sig").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key in allowed:
                values[key] = value.strip().strip("\"'")
    for key in allowed:
        if key not in values and os.environ.get(key):
            values[key] = os.environ[key]
    if not values.get("DATABASE_URL") or not values.get("SUPABASE_SERVICE_ROLE_KEY"):
        raise RuntimeError(
            "Provide local DATABASE_URL and scoped Storage settings "
            "via --env-file or this worktree .env"
        )
    return values


def media_files(directory, remaining):
    image, video, corrupt = (
        directory / "runtime-image.png",
        directory / "runtime-video.mp4",
        directory / "runtime-corrupt.png",
    )
    commands = [
        (
            [
                "-f",
                "lavfi",
                "-i",
                "color=c=blue:s=320x240",
                "-frames:v",
                "1",
                "-threads",
                "1",
                str(image),
            ]
        ),
        (
            [
                "-f",
                "lavfi",
                "-i",
                "color=c=green:s=320x240:r=12",
                "-t",
                "2",
                "-c:v",
                "libx264",
                "-threads",
                "1",
                "-pix_fmt",
                "yuv420p",
                str(video),
            ]
        ),
    ]
    for command in commands:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", *command],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=True,
            timeout=remaining(),
        )
    corrupt.write_bytes(b"not-an-image")
    return {"image": str(image), "video": str(video), "corrupt": str(corrupt)}


def create_schema(
    settings, schema, org, brands, remaining, *, f53_schema_only=False, auth_identity=None
):
    import psycopg
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    params = conninfo_to_dict(settings["DATABASE_URL"])
    if params.get("host") not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("F13 isolated runtime requires a local PostgreSQL host")
    params.pop("options", None)
    admin_dsn = make_conninfo(**params)
    if not re.fullmatch(r"f13_runtime_[a-f0-9]{12}", schema):
        raise RuntimeError("Unsafe schema name")
    migrations = sorted((ROOT / "supabase/migrations").glob("*.sql"))
    if f53_schema_only:
        from scripts.drill.first_release_acceptance import migration_audit

        audit = migration_audit(ROOT)  # Admit exact bytes before connecting or creating anything.
        included = {entry["path"] for entry in audit["included"]}
        migrations = [path for path in migrations if path.name in included]
    with psycopg.connect(
        admin_dsn, autocommit=True, connect_timeout=max(1, int(remaining()))
    ) as conn:

        def execute(query, parameters=None):
            conn.execute(
                "SELECT set_config('statement_timeout', %s, false)",
                (str(max(1, int(remaining() * 1000))),),
            )
            return conn.execute(query, parameters)

        email = auth_identity["email"] if auth_identity else "123@example.com"
        if auth_identity:
            uuid.UUID(auth_identity["id"])
            user = execute(
                "SELECT id FROM auth.users WHERE id=%s AND email=%s", (auth_identity["id"], email)
            ).fetchone()
        else:
            user = execute("SELECT id FROM auth.users WHERE email=%s", (email,)).fetchone()
        if not user:
            raise RuntimeError(
                "Existing normal-login test account 123@example.com is required; "
                "runtime never creates Auth users"
            )
        if f53_schema_only:
            if auth_identity:
                if not re.fullmatch(r"f53_auth_[a-f0-9]{12}", params.get("dbname", "")):
                    raise RuntimeError("Auth fixture requires its own disposable database")
            else:
                bucket = execute(
                    "SELECT public,file_size_limit FROM storage.buckets WHERE id='assets'"
                )
                row = bucket.fetchone()
                if not row or row[0] is not False or row[1] != 52428800:
                    raise RuntimeError("F53 requires the existing private 50MB assets bucket")
        execute("SELECT pg_advisory_lock(913042027)")
        try:
            execute(
                f'CREATE SCHEMA "{schema}"; SET search_path TO "{schema}";'
                + "\n".join(p.read_text("utf-8") for p in migrations)
            )
        finally:
            execute("SELECT pg_advisory_unlock(913042027)")
        execute(f'GRANT USAGE ON SCHEMA "{schema}" TO authenticated')
        execute(
            "INSERT INTO organisation(id,name,kind) VALUES(%s,%s,'company')",
            (org, "F13 isolated runtime"),
        )
        execute("INSERT INTO app_user(id,email) VALUES(%s,%s)", (user[0], email))
        execute("INSERT INTO membership(org_id,user_id,role) VALUES(%s,%s,'owner')", (org, user[0]))
        for index, brand in enumerate(brands):
            execute(
                "INSERT INTO brand(id,org_id,name,status) VALUES(%s,%s,%s,'active')",
                (brand, org, FIXTURE["brand_name"] + ("｜隔離" if index else "")),
            )
    return (
        admin_dsn,
        make_conninfo(**params, options=f"-c search_path={schema},public"),
        str(user[0]),
    )


def stop_process(process, base_url=None):
    if process is not None and process.poll() is None:
        if base_url:
            try:
                import httpx

                httpx.post(base_url + "/__f13/stop", timeout=2)
                process.wait(timeout=10)
                return
            except (httpx.HTTPError, subprocess.TimeoutExpired):
                pass
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def main(args):
    started = time.monotonic()

    def remaining():
        value = args.timeout - (time.monotonic() - started)
        if value <= 0:
            raise TimeoutError("F13 runtime exceeded bounded timeout")
        return min(value, 15)

    if not args.isolated:
        raise RuntimeError("--isolated is required")
    import httpx
    import jwt
    import psycopg

    values = safe_env(args)
    if urlparse(values.get("SUPABASE_URL", "")).hostname not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("Only local Supabase Storage is permitted")
    schema = "f13_runtime_" + uuid.uuid4().hex[:12]
    org = "org_" + schema
    brands = ["brd_" + schema, "brd_other_" + schema]
    directory = (
        Path(args.context).resolve().parent
        if args.context
        else Path(tempfile.mkdtemp(prefix="f13-evidence-"))
    )
    directory.mkdir(parents=True, exist_ok=True)
    context_path = Path(args.context).resolve() if args.context else directory / "context.json"
    context = {
        "base_url": f"http://127.0.0.1:{args.port}",
        "org_id": org,
        "brand_id": brands[0],
        "second_brand_id": brands[1],
        "brand_ids": brands,
        "schema": schema,
        "state_file": str(directory / "source-state.json"),
        "evidence_dir": str(directory),
        "fixture_labels": FIXTURE,
        "primary_platform": "meta",
        "primary_account_id": FIXTURE["accounts"][0],
    }
    write_json(context["state_file"], {"creative_revision": 1, "fail_next": False, "paused": False})
    context["media_paths"] = {
        "image": str(directory / "runtime-image.png"),
        "video": str(directory / "runtime-video.mp4"),
        "corrupt": str(directory / "corrupt.png"),
    }
    process = None
    admin_dsn = None
    log = open(directory / "server.log", "w", encoding="utf-8")
    child_env = {
        key: val
        for key, val in os.environ.items()
        if not any(
            part in key.upper()
            for part in ("API_KEY", "TOKEN", "SECRET", "DATABASE_URL", "BRAND_OS_LLM_PROVIDER")
        )
    }
    child_env.update(values)
    child_env.update(
        BRAND_OS_ENV="local",
        BRAND_OS_JOB_QUEUE="memory",
        BRAND_OS_LLM_PROVIDER="scripted",
        IDENTITY_DEV_TOKEN="",
        IDENTITY_ALLOW_HS256="1",
        PYTHONUTF8="1",
    )

    def start_server():
        write_json(context_path, context)
        proc = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--child",
                "--context",
                str(context_path),
                "--port",
                str(args.port),
            ],
            cwd=ROOT,
            env=child_env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            while True:
                if proc.poll() is not None:
                    raise RuntimeError("Isolated server exited; inspect local server.log")
                try:
                    if (
                        httpx.get(
                            context["base_url"] + "/__f13/state", timeout=min(1, remaining())
                        ).status_code
                        == 200
                    ):
                        return proc
                except httpx.HTTPError:
                    pass
                remaining()
                time.sleep(0.1)
        except BaseException:
            stop_process(proc)
            raise

    try:
        context["media_paths"] = media_files(directory, remaining)
        with socket.socket() as check:
            check.bind(("127.0.0.1", args.port))
        from psycopg.conninfo import conninfo_to_dict, make_conninfo

        admin_params = conninfo_to_dict(values["DATABASE_URL"])
        if admin_params.get("host") not in {"localhost", "127.0.0.1", "::1"}:
            raise RuntimeError("Only local PostgreSQL is allowed")
        admin_params.pop("options", None)
        admin_dsn = make_conninfo(**admin_params)
        admin_dsn, scoped_dsn, user_id = create_schema(values, schema, org, brands, remaining)
        child_env["DATABASE_URL"] = scoped_dsn
        process = start_server()
        secret = values.get("SUPABASE_JWT_SECRET")
        if not secret:
            raise RuntimeError(
                "Local JWT secret is required for the HTTP runtime; browser still uses normal login"
            )
        token = jwt.encode(
            {
                "sub": user_id,
                "email": "123@example.com",
                "aud": "authenticated",
                "exp": int(time.time()) + 1800,
            },
            secret,
            algorithm="HS256",
        )
        client = httpx.Client(
            base_url=context["base_url"],
            headers={"Authorization": "Bearer " + token, "X-Org-Id": org},
        )
        result = runtime_flow(client, context, remaining)
        context.update(imported_campaign_id=result["campaign_id"])
        if getattr(args, "runtime_restart", True):
            # Persist a queued descriptor before restart, without marking any job successful.
            client.post(
                "/__f13/state", json={"paused": True}, timeout=remaining()
            ).raise_for_status()
            queued = client.post(
                f"/api/ads/brands/{brands[0]}/campaigns/{result['campaign_id']}/sync",
                json={},
                timeout=remaining(),
            )
            queued.raise_for_status()
            stop_process(process, context["base_url"])
            write_json(
                context["state_file"], {"creative_revision": 1, "fail_next": False, "paused": False}
            )
            process = start_server()
            wait_job(client, brands[0], queued.json()["job"]["id"], remaining)
            for asset, path in result["originals"]:
                response = client.get(
                    f"/api/ads/brands/{brands[0]}/user-assets/{asset}/download", timeout=remaining()
                )
                assert response.content == Path(path).read_bytes(), "Original changed after restart"
        result.update(
            restarted=getattr(args, "runtime_restart", True),
            elapsed_seconds=round(time.monotonic() - started, 2),
            context_path=str(context_path),
        )
        write_json(directory / "runtime-result.json", result)
        print(
            json.dumps(
                {
                    "ok": True,
                    "context_path": str(context_path),
                    "runtime_seconds": result["elapsed_seconds"],
                }
            ),
            flush=True,
        )
        client.close()
    finally:
        stop_process(process, context["base_url"])
        log.close()
        cleanup = {
            "process_stopped": process is None or process.poll() is not None,
            "storage": False,
            "schema": False,
        }
        # Cleanup has a separate bounded budget: process <=27s, Storage <=30s,
        # PostgreSQL connect <=5s / statement <=30s. Evidence is never removed.
        errors = []
        if admin_dsn:
            try:
                subprocess.run(
                    [sys.executable, str(Path(__file__).resolve()), "--cleanup-storage", org],
                    cwd=ROOT,
                    env=child_env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=30,
                    check=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                cleanup["storage"] = True
            except (subprocess.SubprocessError, OSError) as exc:
                errors.append("storage:" + type(exc).__name__)
            try:
                with psycopg.connect(admin_dsn, autocommit=True, connect_timeout=5) as conn:
                    conn.execute("SET statement_timeout='30s'")
                    conn.execute(
                        f'DROP SCHEMA IF EXISTS "{schema}" CASCADE; '
                        f'DROP SCHEMA IF EXISTS "{schema}__queue" CASCADE'
                    )
                    cleanup["schema"] = True
            except psycopg.Error as exc:
                errors.append("schema:" + type(exc).__name__)
        try:
            for media_path in context["media_paths"].values():
                media = Path(media_path).resolve()
                if media.parent != directory.resolve():
                    raise RuntimeError("Refusing cleanup outside fixture media directory")
                media.unlink(missing_ok=True)
            cleanup["fixture_media"] = True
        finally:
            cleanup["errors"] = errors
            write_json(directory / "cleanup.json", cleanup)
        if errors:
            raise RuntimeError("Isolated resource cleanup failed; inspect cleanup.json")


def wait_job(client, brand, job_id, remaining):
    while True:
        response = client.get(f"/api/ads/brands/{brand}/sync-jobs/{job_id}", timeout=remaining())
        response.raise_for_status()
        job = response.json()["job"]
        if job["status"] not in {"pending", "running"}:
            assert job["status"] == "succeeded", job
            return job
        time.sleep(0.1)


def runtime_flow(client, context, remaining):
    brand = context["brand_id"]
    base = f"/api/ads/brands/{brand}"

    def call(method, path, **kwargs):
        response = client.request(method, path, timeout=remaining(), **kwargs)
        response.raise_for_status()
        return response.json()

    page = call("GET", base + "/existing-campaigns")
    wait_job(client, brand, page["job"]["id"], remaining)
    page = call("GET", base + "/existing-campaigns")
    assert len(page["items"]) == 2 and all(
        p["snapshot"]["native_status"] == "PAUSED" for p in page["items"]
    )
    source = {
        "platform": "meta",
        "source_account": FIXTURE["accounts"][0],
        "native_kind": "campaign",
        "native_id": "root",
    }
    imported = call("POST", base + "/imports", json=source)
    campaign = imported["campaign"]["id"]
    wait_job(client, brand, imported["job"]["id"], remaining)
    assert call("POST", base + "/imports", json=source)["campaign"]["id"] == campaign
    route = base + "/campaigns/" + campaign
    call("PATCH", route, json={"goal_text": "品牌介紹", "objective": "品牌介紹"})
    view = call("GET", route + "/external")
    assert view["observations"][0]["spend"] == 0 and view["observations"][0]["purchases"] is None
    originals, placements = [], []
    for kind in ("image", "video"):
        path = Path(context["media_paths"][kind])
        original = {
            "headline": "品牌介紹",
            "body": "",
            "description": "",
            "caption": "額外原文保留",
        }
        batch = call(
            "POST",
            base + "/user-assets/batches",
            json={
                "files": [
                    {
                        "filename": path.name,
                        "size": path.stat().st_size,
                        "content_type": "application/octet-stream",
                        "copy_fields": original,
                    }
                ]
            },
        )["batch"]
        upload = call(
            "PUT",
            base + f"/user-assets/uploads/{batch['uploads'][0]['id']}/content",
            content=path.read_bytes(),
        )["upload"]
        originals.append((upload["asset_id"], str(path)))
        p = call("POST", route + "/placements", json={"upload_id": upload["id"]})["placement"]
        assert p["copy_fields"] == original
        placements.append(p)
    while True:
        current = call("GET", route + "/placements")["placements"]
        if all(p["asset_status"] == "ready" for p in current):
            break
        assert not any(p["asset_status"] == "error" for p in current), current
        time.sleep(0.1)
    suggestion = call(
        "POST",
        route + "/asset-suggestions",
        json={
            "placements": [{"id": p["id"], "revision": p["revision"]} for p in placements],
            "idempotency_key": "runtime-once",
            "summary": "自帶品牌素材，未做影片內容分析",
        },
    )["batch"]
    while suggestion["status"] in {"queued", "running"}:
        suggestion = call("GET", route + f"/asset-suggestions/{suggestion['id']}")["batch"]
        time.sleep(0.1)
    assert suggestion["status"] == "succeeded", suggestion.get("error")
    for p in placements:
        confirmed = call(
            "POST",
            route + f"/placements/{p['id']}/confirm",
            json={"expected_revision": p["revision"], "batch_id": suggestion["id"]},
        )["placement"]
        assert confirmed["confirmed_at"], confirmed
    p = placements[0]
    handoff_path = route + f"/placements/{p['id']}"
    handoff = call("GET", handoff_path + "/handoff?revision=1")
    assert handoff["effective_copy"]["headline"] == "品牌介紹" and handoff["effective_copy"]["body"]
    candidates = call(
        "GET",
        handoff_path + "/binding-candidates",
        params={"revision": 1, "platform": "meta", "account_id": FIXTURE["accounts"][0]},
    )
    binding = call(
        "POST",
        handoff_path + "/verify-binding",
        json={
            "expected_revision": 1,
            "entity_id": candidates["candidates"][0]["entity_id"],
            "user_verified": True,
        },
    )["binding"]
    assert (
        binding["existence_status"] == "platform_confirmed"
        and binding["evidence_level"] == "user_verified"
    )
    today = date.today().isoformat()
    metrics = call(
        "GET",
        handoff_path + "/version-metrics",
        params={"revision": 1, "start": today, "end": today},
    )
    assert metrics["observations"] and not metrics["attributed_observations"]
    call("POST", "/__f13/state", json={"creative_revision": 2})
    refresh = call("POST", route + "/sync", json={})["job"]
    wait_job(client, brand, refresh["id"], remaining)
    stale = call("GET", handoff_path + "/handoff?revision=1")["bindings"][0]
    assert stale["valid_to"] and stale["stale_reason"]
    other = client.get(
        f"/api/ads/brands/{context['second_brand_id']}/campaigns/{campaign}/placements",
        timeout=remaining(),
    )
    assert other.status_code in {403, 404, 409}
    stats = call("GET", "/__f13/state")
    assert not stats["errors"], stats["errors"]
    assert stats["provider_calls"] == 1
    return {
        "ok": True,
        "campaign_id": campaign,
        "originals": originals,
        "handlers": stats["handlers"],
        "provider_calls": stats["provider_calls"],
        "unknown_not_zero": True,
        "stale_evidence_preserved": True,
        "cross_brand_rejected": True,
        "real_platform_capability": "not tested by fixtures",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--isolated", action="store_true")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--env-file")
    parser.add_argument("--context")
    parser.add_argument("--port", type=int, default=8731)
    parser.add_argument("--cleanup-storage", help=argparse.SUPPRESS)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    if not 8731 <= arguments.port <= 65535:
        parser.error("Use an isolated port starting at 8731")
    if arguments.cleanup_storage:
        if not re.fullmatch(r"org_f13_runtime_[a-f0-9]{12}", arguments.cleanup_storage):
            parser.error("Invalid owned cleanup prefix")
        import pytest  # noqa: F401

        from app import storage

        storage.delete_prefix(
            org_id=arguments.cleanup_storage, prefix=arguments.cleanup_storage + "/"
        )
    elif arguments.child:
        child(arguments)
    else:
        main(arguments)
