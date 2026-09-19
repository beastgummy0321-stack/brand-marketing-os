"""Isolated A/B/C acceptance. Reuse the existing local lifecycle/cleanup runner.

The source changes below are test-only platform replacements, not live operations.
The browser uses normal login; runtime HTTP uses the runner's isolated tenant token.
"""

import argparse
import io
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.tests.fixtures.ads_external import runtime as assembly  # noqa: E402
from app.tests.fixtures.ads_external.cycle_reader import COPY_V2, CycleReader  # noqa: E402
from scripts import verify_existing_campaigns_assets as runtime  # noqa: E402


def cycle_flow(client, context, remaining):
    def call(method, url, **kwargs):
        response = client.request(method, url, timeout=remaining(), **kwargs)
        response.raise_for_status()
        return response.json()

    brand = context["brand_id"]
    base = f"/api/ads/brands/{brand}"
    source = {"platform": "meta", "source_account": assembly.FIXTURE["accounts"][0]}
    job = call("POST", base + "/existing-campaigns/refresh", json=source)["job"]
    runtime.wait_job(client, brand, job["id"], remaining)
    imported = call(
        "POST", base + "/imports", json={**source, "native_kind": "campaign", "native_id": "root"}
    )
    campaign = imported["campaign"]["id"]
    runtime.wait_job(client, brand, imported["job"]["id"], remaining)
    route = base + "/campaigns/" + campaign
    control = call("GET", route + "/change-control")
    ad = next(t for t in control["targets"] if t["native_kind"] == "ad")
    group = next(t for t in control["targets"] if t["native_kind"] == "adset")
    month = date.today().strftime("%Y-%m")
    cap = call(
        "PUT",
        base + "/monthly-budget",
        json={"month": month, "currency": "TWD", "amount": 30000, "expected_revision": 0},
    )["budget"]
    assert cap["available"] is None and cap["amount"] == 30000
    assert call("GET", base + "/monthly-budget?month=" + month)["budget"]["revision"] == 1
    payload = {
        "operation_id": "a-response-lost",
        "title": "修改原 B 文案，另暫停投放組",
        "month": month,
        "items": [
            {
                "kind": "copy",
                "target_id": ad["id"],
                "after": {"body": COPY_V2},
                "reason": "只修文案；保留既有圖片，結果不能歸因於一句文案。",
            },
            {
                "kind": "pause",
                "target_id": group["id"],
                "after": {"status": "PAUSED"},
                "reason": "獨立降低風險，不能先認列釋放額度。",
            },
        ],
    }
    draft = call("POST", route + "/change-sets", json=payload)["change_set"]
    replay = call("POST", route + "/change-sets", json=payload)["change_set"]
    assert replay["id"] == draft["id"]
    mismatch = client.post(route + "/change-sets", json={**payload, "title": "不同內容"})
    assert mismatch.status_code == 409
    item_url = route + "/change-sets/" + draft["id"]
    approved = call("POST", item_url + "/approve", json={"content_hash": draft["content_hash"]})[
        "change_set"
    ]
    replay = call("POST", item_url + "/approve", json={"content_hash": draft["content_hash"]})[
        "change_set"
    ]
    assert approved["approval_id"] == replay["approval_id"]
    action_id = draft["plan_json"]["items"][0]["id"]
    check_url = item_url + "/items/" + action_id
    reported = call("POST", check_url + "/report", json={})["change_set"]
    assert (
        next(a for a in reported["items"] if a["id"] == action_id)["verification_state"]
        == "reported"
    )
    call("POST", "/__f13/state", json={"fail_next": True})
    unknown = call("POST", check_url + "/check", json={})["change_set"]
    assert (
        next(a for a in unknown["items"] if a["id"] == action_id)["verification_state"] == "unknown"
    )
    call("POST", "/__f13/state", json={"fail_next": False, "creative_revision": 2})
    checked = call("POST", check_url + "/check", json={})["change_set"]
    assert (
        next(a for a in checked["items"] if a["id"] == action_id)["verification_state"]
        == "confirmed"
    )
    assert sum(a["verification_state"] == "confirmed" for a in checked["items"]) == 1
    reread = call("GET", item_url)["change_set"]
    assert reread["items"] == checked["items"]
    call("POST", "/__f13/state", json={"creative_revision": 3})
    deviated = call("POST", check_url + "/check", json={})["change_set"]
    assert next(a for a in deviated["items"] if a["id"] == action_id)["verification_state"] in {
        "deviated",
        "stale",
    }
    other = client.get(
        f"/api/ads/brands/{context['second_brand_id']}/campaigns/{campaign}/change-control"
    )
    assert other.status_code in {403, 404, 409}
    stats = call("GET", "/__f13/state")
    assert stats["provider_calls"] == 0
    context.update(change_set_id=draft["id"], ad_entity_id=ad["id"], group_entity_id=group["id"])
    return {
        "ok": True,
        "campaign_id": campaign,
        "originals": [],
        "provider_calls": 0,
        "same_operation_replayed": True,
        "same_key_different_payload_rejected": True,
        "partial_completion": True,
        "unknown_then_read_back": True,
        "outside_change_detected": True,
        "cross_brand_rejected": True,
        "real_platform_capability": "not tested; fixture source only",
    }


def review_cycle_flow(client, context, remaining):
    """Exercise real local handlers via HTTP; provider and platform stay explicit fakes."""
    from openpyxl import Workbook

    def call(method, url, **kwargs):
        response = client.request(method, url, timeout=remaining(), **kwargs)
        if response.is_error:
            raise AssertionError(f"{method} {url}: {response.status_code} {response.text}")
        return response.json()

    def ready(review):
        while review["status"] in {"queued", "running"}:
            time.sleep(min(0.1, remaining()))
            review = call("GET", route + "/reviews/" + review["id"])["review"]
        assert review["status"] == "ready", {
            "status": review["status"],
            "error": review.get("error"),
            "waiting": review["evidence_json"].get("waiting_reasons"),
        }
        return review

    brand = context["brand_id"]
    base = f"/api/ads/brands/{brand}"
    source = {"platform": "meta", "source_account": assembly.FIXTURE["accounts"][0]}
    listing = call("POST", base + "/existing-campaigns/refresh", json=source)
    runtime.wait_job(client, brand, listing["job"]["id"], remaining)
    imported = call(
        "POST", base + "/imports", json={**source, "native_kind": "campaign", "native_id": "root"}
    )
    campaign = imported["campaign"]["id"]
    job = runtime.wait_job(client, brand, imported["job"]["id"], remaining)
    route = base + "/campaigns/" + campaign
    call(
        "PATCH",
        route,
        json={
            "goal_text": "比較平台與商城證據後決定原廣告下一步",
            "objective": "購買",
            "success_metric": "roas",
            "success_target": 2,
            "success_basis": "隔離流程測試目標，不代表真實收益門檻。",
        },
    )
    controls = call("GET", route + "/change-control")
    ad = next(target for target in controls["targets"] if target["native_kind"] == "ad")
    today = date.today()
    first_start, first_end = today - timedelta(days=14), today - timedelta(days=8)
    next_start, next_end = today - timedelta(days=7), today - timedelta(days=1)
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
    for i in range(21):
        day = today - timedelta(days=21 - i)
        amount = 600 if day >= next_start else 1000
        sheet.append(
            [f"F15-B-{i}", day.isoformat(), amount, 0, "paid", "open", "fixture-product", amount, 1]
        )
    content = io.BytesIO()
    book.save(content)
    book.close()
    workbook = Path(context["evidence_dir"]) / "fixture-easystore-orders.xlsx"
    workbook.write_bytes(content.getvalue())
    order_result = call(
        "POST",
        f"/api/brands/{brand}/orders/import",
        files={
            "drop_file": (
                workbook.name,
                content.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert order_result["ok"]
    request = {
        "entity_id": ad["id"],
        "start": first_start.isoformat(),
        "end": first_end.isoformat(),
    }
    first = ready(call("POST", route + "/reviews", json=request)["review"])
    assembly.write_json(Path(context["evidence_dir"]) / "first-review.json", first)
    first_stats = call("GET", "/__f13/state")
    assert first_stats["provider_calls"] == 1, first_stats
    reused = call("POST", route + "/reviews", json=request)["review"]
    assert reused["id"] == first["id"]
    assert call("GET", "/__f13/state")["provider_calls"] == 1
    recommendation = first["result_json"]["recommendations"][0]
    assert recommendation["recommendation"] == "adjust"
    draft = call(
        "POST",
        route + "/change-sets",
        json={
            "operation_id": "b-linked-review-copy",
            "title": "檢討原 B 廣告後調整文案",
            "month": today.strftime("%Y-%m"),
            "review_id": first["id"],
            "recommendation_id": recommendation["id"],
            "items": [
                {
                    "kind": "copy",
                    "target_id": ad["id"],
                    "after": recommendation["suggested_copy"],
                    "reason": "隔離檢討建議；保持圖片，設定相符不代表成效改善。",
                }
            ],
        },
    )["change_set"]
    assert draft["plan_json"]["review_id"] == first["id"]
    set_url = route + "/change-sets/" + draft["id"]
    approved = call("POST", set_url + "/approve", json={"content_hash": draft["content_hash"]})[
        "change_set"
    ]
    action_id = approved["items"][0]["id"]
    action_url = set_url + "/items/" + action_id
    call("POST", action_url + "/report", json={})
    call("POST", "/__f13/state", json={"creative_revision": 4})
    confirmed = call("POST", action_url + "/check", json={})["change_set"]
    action = next(item for item in confirmed["items"] if item["id"] == action_id)
    assert action["verification_state"] == "confirmed", action
    next_request = {
        "entity_id": ad["id"],
        "start": next_start.isoformat(),
        "end": next_end.isoformat(),
        "previous_id": first["id"],
    }
    followup = ready(call("POST", route + "/reviews", json=next_request)["review"])
    evidence = followup["evidence_json"]
    assert followup["previous_id"] == first["id"]
    previous_actions = evidence["previous_review"]["actions"]
    assert any(
        item["id"] == action_id and item["verification_state"] == "confirmed"
        for item in previous_actions
    )
    assert evidence["current"]["missing_days"] == evidence["previous"]["missing_days"] == 0
    assert (
        evidence["current"]["series"][0]["metrics"]["revenue"]
        > evidence["previous"]["series"][0]["metrics"]["revenue"]
    )
    commerce_current = evidence["commerce"]["current"]["order_summary"]
    commerce_previous = evidence["commerce"]["previous"]["order_summary"]
    assert commerce_current["order_net_amount"] < commerce_previous["order_net_amount"]
    assert commerce_current["currency"] is None and commerce_current["coverage"] == "unknown"
    assert evidence["conditions"]["history"] == "unknown"
    assert followup["result_json"]["causality"] == "unavailable"
    assert followup["result_json"]["recommendations"][0]["recommendation"] == "observe"
    reused_followup = call("POST", route + "/reviews", json=next_request)["review"]
    assert reused_followup["id"] == followup["id"]
    stats = call("GET", "/__f13/state")
    assert stats["provider_calls"] == 2, stats
    assert not stats["errors"] and stats["blocked_external"] == 0, stats
    current_month = job["tasks"]["monthly:" + today.strftime("%Y-%m")]
    assert current_month["status"] == "succeeded"
    assert current_month["coverage"]["unassigned_native_ids"] == []
    context.update(
        phase="B",
        ad_entity_id=ad["id"],
        change_set_id=draft["id"],
        action_id=action_id,
        first_review_id=first["id"],
        followup_review_id=followup["id"],
        browser_review_id=first["id"],
        browser_review_window=request,
        browser_source_revision=1,
        browser_note="重啟後來源恢復原文案；首回保留可採用建議，次回保留反證與前次設定核對。歷史期間均是隔離替身，不能當作真實修改後效果。",
    )
    assembly.write_json(
        Path(context["evidence_dir"]) / "review-rounds.json",
        {"first": first, "followup": followup, "confirmed_change_set": confirmed},
    )
    return {
        "ok": True,
        "phase": "B",
        "campaign_id": campaign,
        "originals": [],
        "provider_calls": 2,
        "first_review_id": first["id"],
        "followup_review_id": followup["id"],
        "same_evidence_reused": True,
        "linked_copy_confirmed": True,
        "previous_action_preserved": True,
        "account_month_coverage": current_month["coverage"],
        "platform_revenue": [
            evidence["previous"]["series"][0]["metrics"]["revenue"],
            evidence["current"]["series"][0]["metrics"]["revenue"],
        ],
        "commerce_order_net_amount": [
            commerce_previous["order_net_amount"],
            commerce_current["order_net_amount"],
        ],
        "commerce_currency": "unknown",
        "commerce_coverage": "unknown",
        "creative_history": "unknown",
        "causality": "unavailable",
        "real_platform_capability": "not tested; fixture source and scripted model only",
        "chronology": (
            "Synthetic historical periods; observed setting change happened during this run, "
            "not proof of historical effect."
        ),
    }


def cold_start_flow(call, base, context, asset_id):
    """Cold lifecycle through public HTTP only; this is API evidence, not UI evidence."""
    today = date.today()
    cold = call(
        "POST",
        base + "/campaigns",
        json={
            "goal_text": (
                "請沿用品牌已知資料建立首次計畫，已有成品，不需要生圖；未知條件保留待確認。"
            ),
            "start_date": today.isoformat(),
            "end_date": (today + timedelta(days=7)).isoformat(),
            "constraints": {"platform": "meta"},
        },
    )["campaign"]
    route = base + "/campaigns/" + cold["id"]
    call(
        "PATCH",
        route,
        json={
            "name": "API 冷啟動完整交接",
            "objective": "購買",
            "success_metric": "roas",
            "success_target": 2,
        },
    )
    call("POST", route + "/strategy", json={})
    call("POST", route + "/strategy/scenario", json={"scenario_key": "custom", "custom_total": 800})
    call("POST", route + "/plan", json={})
    planned = call("GET", route)["campaign"]
    groups = planned["groups"]
    assert len(groups) == 3 and all(len(group["ads"]) == 1 for group in groups)
    task = call(
        "POST",
        route + "/material-tasks",
        json={
            "operation_id": "c-cold-material",
            "title": "首檔已有成品",
            "mode": "existing",
            "copy_fields": {"headline": "探索品牌", "body": "了解更多", "description": "品牌介紹"},
        },
    )["task"]
    task_url = route + "/material-tasks/" + task["id"]
    gathered = call(
        "POST",
        task_url + "/candidates",
        json={
            "operation_id": "c-cold-candidate",
            "expected_revision": 1,
            "asset_ids": [asset_id],
        },
    )["task"]
    selected = call(
        "POST",
        task_url + "/select",
        json={
            "operation_id": "c-cold-select",
            "expected_revision": gathered["revision"],
            "content_hash": gathered["content_hash"],
            "candidate_id": gathered["candidates"][0]["id"],
        },
    )["task"]
    placement_url = route + "/placements/" + selected["placement_id"]
    placement = call(
        "PATCH",
        placement_url,
        json={
            "expected_revision": selected["placement_revision"],
            "purpose": "品牌介紹",
        },
    )["placement"]
    placement = call(
        "POST",
        placement_url + "/confirm",
        json={
            "expected_revision": placement["revision"],
            "batch_id": None,
        },
    )["placement"]
    assert placement["confirmed_at"], placement
    assignment_url = route + "/launch-materials"
    initial = call("GET", assignment_url)
    assert len(initial["planned_ads"]) == 3
    for group in groups:
        call(
            "PUT",
            assignment_url + "/" + group["ads"][0]["id"],
            json={
                "placement_id": placement["id"],
                "revision": placement["revision"],
            },
        )
    reopened = call("GET", assignment_url)
    assert all(row["assignment_status"] == "confirmed" for row in reopened["planned_ads"])
    description = call("GET", route + "/publish?adapter=manual")["describe"]
    approval = {
        "adapter": "manual",
        "operation_id": "c-cold-launch",
        "content_hash": description["content_hash"],
    }
    call("POST", route + "/publish", json=approval)
    call("POST", route + "/publish", json=approval)
    items = call("GET", route + "/handoff")["items"]
    assert len(items) == 7
    native_ids = {cold["id"]: "cold-root"}
    for group in groups:
        native_ids[group["id"]] = f"cold-{group['role']}-group"
        native_ids[group["ads"][0]["id"]] = f"cold-{group['role']}-ad"
    checks = []
    for kind in ("campaign", "group", "ad"):
        for item in (r for r in items if r["planned_kind"] == kind):
            item_url = route + "/handoff/" + item["id"]
            reported = call("POST", item_url + "/report", json={})["item"]
            assert reported["status"] == "reported" and not reported["entity_exists"]
            checked = call(
                "POST",
                item_url + "/check",
                json={
                    "platform": "meta",
                    "source_account": assembly.FIXTURE["accounts"][0],
                    "native_kind": "adset" if kind == "group" else kind,
                    "native_id": native_ids[item["planned_id"]],
                    "user_verified": kind == "ad",
                },
            )["item"]
            assert (
                checked["entity_exists"] and not checked["evidence_json"]["delivery_confirmed"]
            ), checked
            assert checked["status"] == ("unknown" if kind == "group" else "confirmed"), checked
            checks.append(checked)
    context.update(
        cold_campaign_id=cold["id"],
        cold_material_task_id=task["id"],
        cold_planned_ad_ids=[group["ads"][0]["id"] for group in groups],
        cold_placement_id=placement["id"],
        cold_placement_revision=placement["revision"],
        cold_handoff_item_ids=[item["id"] for item in items],
    )
    assembly.write_json(
        Path(context["evidence_dir"]) / "cold-start-api.json",
        {
            "campaign": planned,
            "assigned": reopened,
            "handoff": checks,
            "evidence_boundary": "Real local HTTP submissions; not browser UI evidence.",
            "unknown": "Group manual settings remain unknown; platform delivery is not confirmed.",
        },
    )


def material_cycle_flow(client, context, remaining):
    """Real HTTP/storage trace for C; all generated text and native reads are fixtures."""
    import struct
    import zlib

    def call(method, url, **kwargs):
        response = client.request(method, url, timeout=remaining(), **kwargs)
        if response.is_error:
            raise AssertionError(f"{method} {url}: {response.status_code} {response.text}")
        return response.json()

    brand = context["brand_id"]
    base = f"/api/ads/brands/{brand}"
    source = {"platform": "meta", "source_account": assembly.FIXTURE["accounts"][0]}
    listing = call("POST", base + "/existing-campaigns/refresh", json=source)
    runtime.wait_job(client, brand, listing["job"]["id"], remaining)
    imported = call(
        "POST",
        base + "/imports",
        json={
            **source,
            "native_kind": "campaign",
            "native_id": "root",
        },
    )
    campaign = imported["campaign"]["id"]
    runtime.wait_job(client, brand, imported["job"]["id"], remaining)
    route = base + "/campaigns/" + campaign
    call("PATCH", route, json={"goal_text": "保留原廣告，另開素材測試", "objective": "知名度"})
    controls = call("GET", route + "/change-control")
    ad = next(t for t in controls["targets"] if t["native_kind"] == "ad")
    group = next(t for t in controls["targets"] if t["native_kind"] == "adset")
    original_copy = ad["creative_json"] if "creative_json" in ad else None
    originals, uploaded = [], []

    def chunk(kind, value):
        return (
            struct.pack("!I", len(value))
            + kind
            + value
            + struct.pack("!I", zlib.crc32(kind + value) & 0xFFFFFFFF)
        )

    # Distinct original bytes, all clearly synthetic colored squares.
    for index, label in enumerate(["R", *[f"I{i}" for i in range(1, 11)]]):
        path = Path(context["evidence_dir"]) / f"fixture-{label}.png"
        raw = b"".join(b"\x00" + bytes([index * 20, 100, 200]) * 32 for _ in range(32))
        path.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack("!2I5B", 32, 32, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b"")
        )
        context["media_paths"][label] = str(path)
        batch = call(
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
        upload = call(
            "PUT",
            base + f"/user-assets/uploads/{batch['uploads'][0]['id']}/content",
            content=path.read_bytes(),
        )["upload"]
        uploaded.append(upload["asset_id"])
        originals.append((upload["asset_id"], str(path)))
    while True:
        library = call("GET", base + "/user-assets")["assets"]
        pending = [r for r in library if r["id"] in uploaded and r["status"] != "ready"]
        if not pending:
            break
        # Asset state is rendered on the normal library API, never patched in SQL.
        assert not any(r["status"] == "error" for r in pending), pending
        time.sleep(min(0.1, remaining()))
    assert call("GET", "/__f13/state")["provider_calls"] == 0
    tasks = route + "/material-tasks"
    existing = call(
        "POST", tasks, json={"operation_id": "c-existing", "title": "自帶成品", "mode": "existing"}
    )["task"]
    external = call(
        "POST",
        tasks,
        json={
            "operation_id": "c-external",
            "title": "外部圖片回收",
            "mode": "external_image",
            "copy_fields": {"headline": "探索品牌", "body": "了解更多", "description": "品牌介紹"},
            "prompt": {"source": "manual", "text": "P2：合成色塊測試", "origin": "隔離驗收提示詞"},
            "reference_asset_ids": [uploaded[0]],
        },
    )["task"]
    task_url = tasks + "/" + external["id"]
    batch_payload = {
        "operation_id": "c-batch-ten",
        "expected_revision": external["revision"],
        "asset_ids": uploaded[1:],
        "prompt": external["prompt"],
        "reference_asset_ids": [uploaded[0]],
    }
    gathered = call("POST", task_url + "/candidates", json=batch_payload)["task"]
    replay = call("POST", task_url + "/candidates", json=batch_payload)["task"]
    assert replay["revision"] == gathered["revision"] and len(replay["candidates"]) == 10
    seven = gathered["candidates"][6]
    assert seven["asset_id"] == uploaded[7] and seven["filename"] == "fixture-I7.png"
    selected = call(
        "POST",
        task_url + "/select",
        json={
            "operation_id": "c-select-I7",
            "expected_revision": gathered["revision"],
            "content_hash": gathered["content_hash"],
            "candidate_id": seven["id"],
        },
    )["task"]
    reopened = call("GET", task_url)["task"]
    history = call("GET", task_url + "?revision=2")["task"]
    assert reopened["selected_candidate_id"] == seven["id"]
    assert reopened["placement_current"] is True and history["selected_candidate_id"] is None
    assert seven["prompt"]["text"] == external["prompt"]["text"]
    assert seven["reference_asset_ids"] == [uploaded[0]]
    assert call("GET", "/__f13/state")["provider_calls"] == 0
    assert client.get(
        f"/api/ads/brands/{context['second_brand_id']}/campaigns/{campaign}"
        f"/material-tasks/{external['id']}"
    ).status_code in {403, 404, 409}

    today = date.today()
    review = call(
        "POST",
        route + "/reviews",
        json={
            "entity_id": ad["id"],
            "start": (today - timedelta(days=7)).isoformat(),
            "end": (today - timedelta(days=1)).isoformat(),
        },
    )["review"]
    while review["status"] in {"queued", "running"}:
        time.sleep(min(0.1, remaining()))
        review = call("GET", route + "/reviews/" + review["id"])["review"]
    assert review["status"] == "ready", review
    recommendation = review["result_json"]["recommendations"][0]
    assert recommendation["recommendation"] == "new_test"
    next_task = call(
        "POST",
        tasks,
        json={
            "operation_id": "c-next-round",
            "title": "下一輪文案",
            "mode": "copy",
            "instruction": "保留原廣告，另準備新測試。",
            "review_id": review["id"],
            "recommendation_id": recommendation["id"],
        },
    )["task"]
    assert next_task["review_context"]["evidence_refs"] == recommendation["evidence_refs"]
    next_url = tasks + "/" + next_task["id"]
    dispatch_payload = {
        "operation_id": "c-dispatch",
        "expected_revision": 1,
        "content_hash": next_task["content_hash"],
    }
    dispatched = call("POST", next_url + "/dispatch", json=dispatch_payload)["task"]
    assert dispatched["pack_id"] and dispatched["dispatch_status"] == "queued"
    assert (
        call("POST", next_url + "/dispatch", json=dispatch_payload)["task"]["pack_id"]
        == dispatched["pack_id"]
    )
    while True:
        options = call("GET", next_url + "/prompt-options")["options"]
        stats = call("GET", "/__f13/state")
        assert not stats["errors"], stats
        if options:
            break
        time.sleep(min(0.1, remaining()))
    assert len(options) == 5
    assert stats["provider_calls"] == 2 and stats["blocked_external"] == 0, stats
    copied = call(
        "PATCH",
        next_url,
        json={
            "operation_id": "c-save-generated-version",
            "expected_revision": dispatched["revision"],
            "prompt": {
                "source": "workbench",
                "set_id": options[0]["set_id"],
                "version_id": options[0]["version_id"],
            },
        },
    )["task"]
    assert copied["prompt"]["version_id"] == options[0]["version_id"]
    assert copied["copy_fields"] == options[0]["copy_fields"]
    assert copied["pack_id"] == dispatched["pack_id"]

    placement_url = route + "/placements/" + selected["placement_id"]
    arranged = call(
        "PATCH",
        placement_url,
        json={
            "expected_revision": selected["placement_revision"],
            "purpose": "品牌介紹",
            "destination_entity_id": group["id"],
        },
    )["placement"]
    confirmed = call(
        "POST",
        placement_url + "/confirm",
        json={
            "expected_revision": arranged["revision"],
            "batch_id": None,
        },
    )["placement"]
    assert confirmed["confirmed_at"], confirmed
    assert call("GET", task_url)["task"]["placement_current"] is False
    selected = call(
        "POST",
        task_url + "/select",
        json={
            "operation_id": "c-reselect-current",
            "expected_revision": selected["revision"],
            "content_hash": selected["content_hash"],
            "candidate_id": seven["id"],
        },
    )["task"]
    assert selected["placement_revision"] == confirmed["revision"]
    month = today.strftime("%Y-%m")
    call(
        "PUT",
        base + "/monthly-budget",
        json={
            "month": month,
            "currency": "TWD",
            "amount": 30000,
            "expected_revision": 0,
        },
    )
    budget = call("GET", base + "/monthly-budget?month=" + month)["budget"]
    assert budget["available"] is not None, budget
    new_request = {
        "operation_id": "c-new-B2",
        "title": "另建 B2，保留原廣告",
        "month": month,
        "placement_id": confirmed["id"],
        "revision": confirmed["revision"],
        "destination_entity_id": group["id"],
        "reason": "獨立驗證下一個素材假設",
        "review_id": review["id"],
        "recommendation_id": recommendation["id"],
    }
    draft = call("POST", route + "/new-ad-handoffs", json=new_request)["change_set"]
    assert (
        call("POST", route + "/new-ad-handoffs", json=new_request)["change_set"]["id"]
        == draft["id"]
    )
    call(
        "POST",
        route + "/change-sets/" + draft["id"] + "/approve",
        json={"content_hash": draft["content_hash"]},
    )
    handoff = next(
        row
        for row in call("GET", route + "/handoff")["items"]
        if row["change_set_id"] == draft["id"]
    )
    handoff_url = route + "/handoff/" + handoff["id"]
    reported = call("POST", handoff_url + "/report", json={})["item"]
    assert reported["status"] == "reported" and not reported["entity_id"]
    checked = call(
        "POST",
        handoff_url + "/check",
        json={**source, "native_kind": "ad", "native_id": "B2", "user_verified": True},
    )["item"]
    assert checked["status"] == "confirmed", checked
    assert checked["native_id"] == "B2" and checked["entity_id"] != ad["id"]
    assert checked["evidence_json"]["delivery_confirmed"] is False

    cold_start_flow(call, base, context, uploaded[1])
    unchanged = next(
        t for t in call("GET", route + "/change-control")["targets"] if t["id"] == ad["id"]
    )
    if original_copy is not None:
        assert unchanged["creative_json"] == original_copy
    assert unchanged["native_status"] == "ACTIVE"
    stats = call("GET", "/__f13/state")
    assert stats["provider_calls"] == 5 and not stats["errors"], stats
    context.update(
        phase="C",
        ad_entity_id=ad["id"],
        group_entity_id=group["id"],
        existing_material_task_id=existing["id"],
        material_task_id=external["id"],
        selected_candidate_id=seven["id"],
        selected_asset_id=uploaded[7],
        reference_asset_id=uploaded[0],
        placement_id=selected["placement_id"],
        placement_revision=selected["placement_revision"],
        next_material_task_id=next_task["id"],
        material_pack_id=dispatched["pack_id"],
        first_review_id=review["id"],
        browser_review_id=review["id"],
        recommendation_id=recommendation["id"],
        new_ad_change_set_id=draft["id"],
        handoff_item_id=checked["id"],
        new_ad_entity_id=checked["entity_id"],
        browser_note="合成色塊與 FakeProvider 隔離驗收；原廣告未被停止。",
    )
    assembly.write_json(
        Path(context["evidence_dir"]) / "material-cycle.json",
        {"selected": selected, "history": history, "next_round": copied, "review": review},
    )
    return {
        "ok": True,
        "phase": "C",
        "campaign_id": campaign,
        "originals": originals,
        "provider_calls": stats["provider_calls"],
        "ten_candidates_selected_I7": True,
        "P2_reference_R_preserved": True,
        "same_operation_replayed": True,
        "old_revision_reopened": True,
        "review_hypothesis_preserved": True,
        "generated_copy_version_saved": True,
        "new_B2_separate_from_original": True,
        "reported_not_published": True,
        "cold_campaign_material_saved": True,
        "cold_strategy_plan_assignment_launch_readback": True,
        "cold_group_manual_settings": "unknown",
        "cross_brand_rejected": True,
        "real_platform_capability": "not tested; fixture reads only",
        "model_capability": "scripted review and FakeProvider workbench; no real AI",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--isolated", action="store_true")
    parser.add_argument(
        "--phase", choices=("A", "B", "C", "D"), default=os.environ.get("F15_ACCEPTANCE_PHASE", "A")
    )
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--env-file")
    parser.add_argument("--context")
    parser.add_argument("--port", type=int, default=8731)
    parser.add_argument("--cleanup-storage")
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--drain", action="store_true")
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--browser-timeout", type=int, default=3600)
    args = parser.parse_args()
    if not 8731 <= args.port <= 65535:
        parser.error("Use an isolated port starting at 8731")
    os.environ["F15_ACCEPTANCE_PHASE"] = args.phase
    if args.phase == "D" and not args.cleanup_storage:
        from scripts import verify_ads_cycle_runtime

        if args.child or args.worker:
            from app.tests.fixtures.ads_external.worker_runtime import child

            child(args)
        else:
            verify_ads_cycle_runtime.main(args)
        return
    assembly.ReadOnlyReader = CycleReader
    runtime.runtime_flow = {"A": cycle_flow, "B": review_cycle_flow, "C": material_cycle_flow}.get(
        args.phase, cycle_flow
    )
    runtime.__file__ = __file__  # Child and bounded cleanup use this same assembly.
    if args.cleanup_storage:
        import re

        if not re.fullmatch(r"org_f13_runtime_[a-f0-9]{12}", args.cleanup_storage):
            parser.error("Invalid fixture prefix")
        import pytest  # noqa: F401

        from app import storage

        storage.delete_prefix(org_id=args.cleanup_storage, prefix=args.cleanup_storage + "/")
    elif args.child:
        runtime.child(args)
    else:
        from psycopg.conninfo import conninfo_to_dict

        values = runtime.safe_env(args)
        if (
            not conninfo_to_dict(values["DATABASE_URL"])
            .get("dbname", "")
            .startswith("f15_validation_")
        ):
            parser.error("Use the dedicated local F15 validation database, never shared public")
        runtime.main(args)


if __name__ == "__main__":
    main()
