"""Isolated A/B acceptance. Reuse the existing local lifecycle/cleanup runner.

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
from scripts import verify_existing_campaigns_assets as runtime  # noqa: E402

COPY_V2 = "先了解適合自己的補給方式，再選擇日常所需。"


class CycleReader(assembly.ReadOnlyReader):
    def node(self, account, native_id, kind, **fields):
        return super().node(account, native_id, kind, **{"native_status": "ACTIVE", **fields})

    def creative(self):
        value = super().creative()
        revision = self.state()["creative_revision"]
        value["fields"]["body"] = (
            "平台原始文案" if revision == 1 else COPY_V2 if revision == 2 else "平台外部另改的文案"
        )
        if revision == 4:
            value["fields"].update(title="探索品牌", body="了解更多")
        return value

    def read_observations(self, conn, org, brand, account, *, native_id, start, end, **kwargs):
        if os.environ.get("F15_ACCEPTANCE_PHASE") != "B":
            return super().read_observations(
                conn, org, brand, account, native_id=native_id, start=start, end=end, **kwargs
            )
        from app.ads.adapters.external import SourcePage

        first, last = date.fromisoformat(str(start)), date.fromisoformat(str(end))
        rows = []
        for offset in range((last - first).days + 1):
            day = first + timedelta(days=offset)
            later = day >= date.today() - timedelta(days=7)
            rows.append(
                {
                    "native_kind": self.kinds()[2],
                    "native_id": f"{native_id}-ad",
                    "day": day.isoformat(),
                    "metric_scope": self.kinds()[2],
                    "attribution_key": "fixture_7d_click",
                    "currency": "TWD",
                    "spend": 100,
                    "impressions": 2000 if later else 1000,
                    "clicks": 80 if later else 30,
                    "purchases": 6 if later else 3,
                    "revenue": 600 if later else 300,
                    "source": "fixture",
                }
            )
        return SourcePage(rows)

    def read_monthly(self, conn, org, brand, account, *, start, end, **kwargs):
        page = super().read_monthly(conn, org, brand, account, start=start, end=end, **kwargs)
        if os.environ.get("F15_ACCEPTANCE_PHASE") != "B":
            return page
        first, last = date.fromisoformat(str(start)), date.fromisoformat(str(end))
        page.items = [
            {
                "native_kind": self.kinds()[0],
                "native_id": "root",
                "day": (first + timedelta(days=i)).isoformat(),
                "metric_scope": self.kinds()[0],
                "attribution_key": "account_monthly_spend",
                "currency": "TWD",
                "spend": 100,
                "source": "fixture",
            }
            for i in range((last - first).days + 1)
        ]
        return page

    def verify_native(self, *args, **kwargs):
        if self.state().get("fail_next"):
            raise ValueError("隔離替身暫時無法讀回。")
        return super().verify_native(*args, **kwargs)


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--isolated", action="store_true")
    parser.add_argument(
        "--phase", choices=("A", "B"), default=os.environ.get("F15_ACCEPTANCE_PHASE", "A")
    )
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--env-file")
    parser.add_argument("--context")
    parser.add_argument("--port", type=int, default=8731)
    parser.add_argument("--cleanup-storage")
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--browser-timeout", type=int, default=3600)
    args = parser.parse_args()
    if not 8731 <= args.port <= 65535:
        parser.error("Use an isolated port starting at 8731")
    os.environ["F15_ACCEPTANCE_PHASE"] = args.phase
    assembly.ReadOnlyReader = CycleReader
    runtime.runtime_flow = review_cycle_flow if args.phase == "B" else cycle_flow
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
