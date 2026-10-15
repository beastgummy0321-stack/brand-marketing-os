"""D public-API evidence: commerce counterevidence and a separate B2 source review."""

import io
import struct
import zlib
from datetime import date, timedelta

from app.tests.fixtures.ads_external import runtime as fixture


def import_commerce(run):
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.append(
        [
            "Order Number",
            "Date",
            "Total Amount",
            "Refunded Amount",
            "Financial Status",
            "Order Status",
            "Item SKU",
            "Item Price",
            "Quantity",
        ]
    )
    today = date.today()
    for index in range(28):
        day = today - timedelta(days=28 - index)
        amount = 600 if day >= today - timedelta(days=7) else 1000
        sheet.append(
            [f"F15-D-{index}", str(day), amount, 0, "paid", "open", "fixture-product", amount, 1]
        )
    content = io.BytesIO()
    book.save(content)
    book.close()
    result = run.call(
        "POST",
        f"/api/brands/{run.context['brand_id']}/orders/import",
        files={
            "drop_file": (
                "D-commerce.xlsx",
                content.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert result["ok"]


def next_round(run, route):
    today = date.today()
    previous = run.call("GET", route + "/reviews/" + run.context["first_review_id"])["review"]
    created = run.call(
        "POST",
        route + "/reviews",
        json={
            "entity_id": run.context["ad_entity_id"],
            "start": str(today - timedelta(days=7)),
            "end": str(today - timedelta(days=1)),
            "previous_id": previous["id"],
        },
    )["review"]
    run.drain()
    current = run.call("GET", route + "/reviews/" + created["id"])["review"]
    assert current["status"] == "ready", current
    evidence = current["evidence_json"]
    assert current["previous_id"] == previous["id"]
    assert (
        evidence["current"]["series"][0]["metrics"]["revenue"]
        > evidence["previous"]["series"][0]["metrics"]["revenue"]
    )
    commerce = evidence["commerce"]
    assert (
        commerce["current"]["order_summary"]["order_net_amount"]
        < commerce["previous"]["order_summary"]["order_net_amount"]
    )
    assert commerce["current"]["order_summary"]["currency"] is None
    assert commerce["current"]["order_summary"]["coverage"] == "unknown"
    assert current["result_json"]["recommendations"][0]["recommendation"] == "observe"
    assert current["result_json"]["causality"] == "unavailable"
    run.context["followup_review_id"] = current["id"]
    fixture.write_json(
        run.directory / "commerce-rounds.json",
        {
            "first": previous,
            "followup": current,
            "chronology": "Synthetic historical periods; not proof of real ad effect.",
        },
    )


def monitor_conditions(run, route):
    monitor_url = route + "/review-monitors/" + run.context["ad_entity_id"]
    monitor = run.call("GET", monitor_url)["monitor"]
    assert monitor["review_id"] == run.context["recovered_gap_review_id"]
    before = run.count_calls()
    # F50 Contract K: a deferral is an org calendar date after the org's today.
    today = date.fromisoformat(run.call("GET", "/api/identity/me")["org"]["today"])
    deferred = run.call(
        "POST",
        route + "/reviews/" + monitor["review_id"] + "/decision",
        json={
            "decision": "deferred",
            "reason": "隔離驗證：到期才重看一次，不更改平台。",
            "revisit_on": (today + timedelta(days=1)).isoformat(),
        },
    )["review"]
    assert deferred["status"] == "deferred"
    run.drain()
    assert run.count_calls() == before, "Defer must not invoke the provider before its due time"
    # The isolated run moves the due instant to now instead of waiting for the org's tomorrow;
    # `review_monitor.on_decision` copied it into the monitor's `next_check_at`, so both move.
    run.advance_review_due(deferred["id"], run.context["ad_entity_id"])
    run.drain()
    monitor = run.call("GET", monitor_url)["monitor"]
    followup = run.call("GET", route + "/reviews/" + monitor["review_id"])["review"]
    assert monitor["state"] == "ready", monitor
    assert followup["previous_id"] == deferred["id"]
    assert followup["window_end"] > deferred["window_end"]
    assert run.count_calls() == before + 1

    def check_now(url):
        current = run.call("GET", url)["monitor"]
        return run.call(
            "PUT",
            url,
            json={
                "expected_revision": current["revision"],
                "enabled": True,
                "window_days": current["window_days"],
                "cadence_days": current["cadence_days"],
                "reset_window": False,
            },
        )["monitor"]

    check_now(monitor_url)
    run.drain()
    assert run.count_calls() == before + 1
    assert run.call("GET", monitor_url)["monitor"]["review_id"] == followup["id"]
    waiting_url = route + "/review-monitors/" + run.context["b2_entity_id"]
    check_now(waiting_url)
    run.drain()
    waiting = run.call("GET", waiting_url)["monitor"]
    snapshot = run.call("GET", route + "/reviews/" + waiting["review_id"])["review"]
    counts = len(run.query("SELECT id FROM ads_review_round"))
    calls = run.count_calls()
    check_now(waiting_url)
    run.drain()
    repeated = run.call("GET", waiting_url)["monitor"]
    assert repeated["window"] == waiting["window"]
    assert repeated["review_id"] == waiting["review_id"]
    assert repeated["state"] == "waiting"
    assert len(run.query("SELECT id FROM ads_review_round")) == counts
    assert run.count_calls() == calls
    run.context.update(
        b2_review_id=waiting["review_id"],
        deferred_review_id=deferred["id"],
        automatic_followup_id=followup["id"],
    )
    fixture.write_json(
        run.directory / "monitor-conditions.json",
        {
            "deferred": deferred["id"],
            "automatic_followup": followup["id"],
            "followup_has_new_complete_day": True,
            "defer_once_provider_delta": 1,
            "unchanged_waiting_provider_delta": 0,
            "fixed_window": waiting["window"],
            "waiting_evidence_hash": snapshot["evidence_hash"],
            "waiting_review_id": waiting["review_id"],
            "same_review_after_repeat": True,
        },
    )


def new_test_source(run, route):
    brand = run.context["brand_id"]
    base = f"/api/ads/brands/{brand}"
    path = run.directory / "D-existing-original.png"

    def chunk(kind, value):
        return (
            struct.pack("!I", len(value))
            + kind
            + value
            + struct.pack("!I", zlib.crc32(kind + value) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + bytes([55, 125, 190]) * 640 for _ in range(640))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!2I5B", 640, 640, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    run.context["media_paths"]["original"] = str(path)
    batch = run.call(
        "POST",
        base + "/user-assets/batches",
        json={
            "files": [
                {
                    "filename": path.name,
                    "size": path.stat().st_size,
                    "content_type": "image/png",
                    "copy_fields": {},
                }
            ]
        },
    )["batch"]
    upload = run.call(
        "PUT",
        base + f"/user-assets/uploads/{batch['uploads'][0]['id']}/content",
        content=path.read_bytes(),
    )["upload"]
    run.drain()
    library = run.call("GET", base + "/user-assets")["assets"]
    assert any(row["id"] == upload["asset_id"] and row["status"] == "ready" for row in library)
    review = run.call("GET", route + "/reviews/" + run.context["first_review_id"])["review"]
    recommendation = review["result_json"]["recommendations"][0]
    assert recommendation["recommendation"] == "new_test"
    task = run.call(
        "POST",
        route + "/material-tasks",
        json={
            "operation_id": "d-source-B2",
            "title": "D來源檢討的獨立B2",
            "mode": "existing",
            "review_id": review["id"],
            "recommendation_id": recommendation["id"],
            "copy_fields": {"headline": "探索品牌", "body": "了解更多", "description": "品牌介紹"},
        },
    )["task"]
    task_url = route + "/material-tasks/" + task["id"]
    task = run.call(
        "POST",
        task_url + "/candidates",
        json={
            "operation_id": "d-B2-original",
            "expected_revision": task["revision"],
            "asset_ids": [upload["asset_id"]],
        },
    )["task"]
    selected = run.call(
        "POST",
        task_url + "/select",
        json={
            "operation_id": "d-B2-select",
            "expected_revision": task["revision"],
            "content_hash": task["content_hash"],
            "candidate_id": task["candidates"][0]["id"],
        },
    )["task"]
    placement_url = route + "/placements/" + selected["placement_id"]
    placement = run.call(
        "PATCH",
        placement_url,
        json={
            "expected_revision": selected["placement_revision"],
            "purpose": "品牌介紹",
            "destination_entity_id": run.context["group_entity_id"],
        },
    )["placement"]
    placement = run.call(
        "POST",
        placement_url + "/confirm",
        json={
            "expected_revision": placement["revision"],
            "batch_id": None,
        },
    )["placement"]
    assert placement["confirmed_at"]
    task = run.call(
        "POST",
        task_url + "/select",
        json={
            "operation_id": "d-B2-confirmed-version",
            "expected_revision": selected["revision"],
            "content_hash": selected["content_hash"],
            "candidate_id": selected["selected_candidate_id"],
        },
    )["task"]
    month = date.today().strftime("%Y-%m")
    run.call(
        "PUT",
        base + "/monthly-budget",
        json={
            "month": month,
            "currency": "TWD",
            "amount": 30000,
            "expected_revision": 0,
        },
    )
    draft = run.call(
        "POST",
        route + "/new-ad-handoffs",
        json={
            "operation_id": "d-B2-handoff",
            "title": "保留原廣告，新增來源可追溯的B2",
            "month": month,
            "placement_id": placement["id"],
            "revision": placement["revision"],
            "destination_entity_id": run.context["group_entity_id"],
            "reason": "隔離來源關係驗證",
            "review_id": review["id"],
            "recommendation_id": recommendation["id"],
        },
    )["change_set"]
    run.call(
        "POST",
        route + "/change-sets/" + draft["id"] + "/approve",
        json={"content_hash": draft["content_hash"]},
    )
    item = next(
        row
        for row in run.call("GET", route + "/handoff")["items"]
        if row["change_set_id"] == draft["id"]
    )
    handoff_url = route + "/handoff/" + item["id"]
    run.call("POST", handoff_url + "/report", json={})
    checked = run.call(
        "POST",
        handoff_url + "/check",
        json={
            "platform": "meta",
            "source_account": fixture.FIXTURE["accounts"][0],
            "native_kind": "ad",
            "native_id": "B2",
            "user_verified": True,
        },
    )["item"]
    assert checked["status"] == "confirmed" and checked["entity_id"] != run.context["ad_entity_id"]
    assert checked["evidence_json"]["delivery_confirmed"] is False
    calls = run.count_calls()
    current = run.call(
        "POST",
        route + "/reviews",
        json={
            "entity_id": checked["entity_id"],
            "start": str(date.today() - timedelta(days=7)),
            "end": str(date.today() - timedelta(days=1)),
        },
    )["review"]
    assert current["status"] == "waiting" and current["previous_id"] is None
    assert current["evidence_json"]["source_review"]["review_id"] == review["id"]
    assert current["evidence_json"]["source_review"]["relation"] == "new_test"
    run.drain()
    assert run.count_calls() == calls
    run.context.update(
        b2_entity_id=checked["entity_id"],
        b2_review_id=current["id"],
        reference_asset_id=upload["asset_id"],
        source_material_task_id=task["id"],
    )
    fixture.write_json(
        run.directory / "B2-source-review.json",
        {
            "source": review["id"],
            "handoff": checked,
            "B2": current,
            "different_ad_not_previous_round": True,
        },
    )
