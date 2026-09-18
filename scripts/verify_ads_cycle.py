"""Isolated A acceptance. Reuse the existing local lifecycle/cleanup runner.

The source changes below are test-only platform replacements, not live operations.
The browser uses normal login; runtime HTTP uses the runner's isolated tenant token.
"""

import argparse
import sys
from datetime import date
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
        return value

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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--isolated", action="store_true")
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
    assembly.ReadOnlyReader = CycleReader
    runtime.runtime_flow = cycle_flow
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
