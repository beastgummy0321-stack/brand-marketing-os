"""app/tests/test_ads_busy.py — F50 Contract J (R7 B4): a long planner call survives a reload and a
second press. Falsifiers: the session advisory lock survives the commits and rollbacks a planner
call makes on its connection (`gateway.run_task` commits mid-call) and is released afterwards, even
from an aborted transaction; two concurrent adopt calls -> one runs, the other 409
`campaign_busy`; while the adopt runs the campaign read serves `busy {kind: "plan"}`; a running row
older than the call's timeout + 30 s is not busy; after the call `busy` is null; strategy and the
brief parse are refused the same way while their lock is held.
"""

import datetime
import threading
import unittest
from unittest import mock

import psycopg
from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.ads import busy, plan
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.llm import providers

from .test_ads_strategy_decision import bind_fixture

ACTOR = "測試員"


class _HeldProvider:
    """Answers the plan reply only after `release` is set; `entered` is set once it is asked."""

    name = "fake"

    def __init__(self):
        self.entered, self.release = threading.Event(), threading.Event()
        self.delivery = providers.ScriptedProvider(providers.SCRIPTED_REPLIES["ads_delivery_plan"])

    def complete(self, *, model, system, messages, max_tokens, timeout_s=120.0, effort=None,
                 tools=None, org_id=None):
        self.entered.set()
        self.release.wait(30)
        return self.delivery.complete(model=model, system=system, messages=messages,
                                      max_tokens=max_tokens, timeout_s=timeout_s, effort=effort,
                                      tools=tools, org_id=org_id)


class BusyTestBase(unittest.TestCase):
    def setUp(self):
        self.org_id = coredb.DEV_ORG_ID
        brand = bi_repo.create_brand(web.conn, org_id=self.org_id, name="測試品牌：處理中",
                                     client_name=None, actor=ACTOR)
        self.brand_id = brand["id"]
        self.campaign = ads_repo.create_campaign(web.conn, self.org_id, self.brand_id, {
            "name": "測試 Campaign", "goal_text": "幫產品衝購買", "objective": "購買",
            "target_cost": 300, "start_date": "2026-10-01", "end_date": "2026-10-14",
            "status": "draft", "budget_planned": 14000, "budget_scenario": "recommended",
            "budget_basis_json": {"strategy": {"allocation": [
                {"role": "new", "label": "新客", "pct": 100, "rationale": None}]}},
        }, created_by=ACTOR)
        web.conn.commit()  # the routes read it on their own connections
        self._orig_provider = plan.PROVIDER

    def tearDown(self):
        plan.PROVIDER = self._orig_provider

    def _path(self, suffix: str = "") -> str:
        return f"/api/ads/brands/{self.brand_id}/campaigns/{self.campaign['id']}{suffix}"


class SessionLockTest(BusyTestBase):
    def _claimable_elsewhere(self, scope_id: str) -> bool:
        with coredb.connection() as other:
            try:
                with busy.claim(other, scope_id, "plan"):
                    return True
            except busy.CampaignBusy:
                return False

    def test_the_lock_survives_commits_and_rollbacks_and_is_released_after(self):
        with busy.claim(web.conn, self.campaign["id"], "plan"):
            web.conn.commit()
            web.conn.rollback()
            web.conn.commit()
            self.assertFalse(self._claimable_elsewhere(self.campaign["id"]))
            self.assertTrue(self._claimable_elsewhere("another-campaign"))
        self.assertTrue(self._claimable_elsewhere(self.campaign["id"]))

    def test_the_lock_is_released_from_an_aborted_transaction(self):
        with self.assertRaises(psycopg.errors.DivisionByZero), \
                busy.claim(web.conn, self.campaign["id"], "plan"):
            web.conn.execute("SELECT 1 / 0")
        self.assertTrue(self._claimable_elsewhere(self.campaign["id"]))
        web.conn.execute("SELECT 1")  # the connection is usable again

    def test_a_held_lock_refuses_with_campaign_busy(self):
        with busy.claim(web.conn, self.campaign["id"], "strategy"), \
                self.assertRaises(busy.CampaignBusy) as ctx, \
                coredb.connection() as other, busy.claim(other, self.campaign["id"], "plan"):
            pass
        self.assertEqual((str(ctx.exception), ctx.exception.kind), ("campaign_busy", "plan"))


class ConcurrentAdoptTest(BusyTestBase):
    def setUp(self):
        super().setUp()
        self.revision = bind_fixture(web.conn, self.org_id, self.brand_id, self.campaign["id"])
        self.approval = {"operation_id": "busy-adopt", "expected_revision": self.revision}
        web.conn.commit()

    def test_missing_confirmation_or_stale_revision_never_enters_provider(self):
        provider = _HeldProvider()
        plan.PROVIDER = provider
        client = TestClient(main.app)
        for approval, code in (
            ({}, "strategy_confirmation_required"),
            ({"operation_id": "missing-revision"}, "strategy_confirmation_required"),
            ({**self.approval, "expected_revision": "old"}, "strategy_changed"),
        ):
            with self.subTest(approval=approval):
                response = client.post(self._path("/plan"), json=approval)
                self.assertEqual((response.status_code, response.json()["error"]["code"]),
                                 (409, code))
                self.assertFalse(provider.entered.is_set())
                self.assertIsNone(client.get(self._path()).json()["campaign"]["busy"])

    def test_one_adopt_runs_the_other_is_409_and_the_read_serves_busy_until_it_ends(self):
        provider = _HeldProvider()
        plan.PROVIDER = provider
        first: dict = {}

        def adopt():
            first["response"] = TestClient(main.app).post(self._path("/plan"), json=self.approval)

        worker = threading.Thread(target=adopt)
        worker.start()
        try:
            self.assertTrue(provider.entered.wait(20))
            client = TestClient(main.app)
            second = client.post(self._path("/plan"), json={
                **self.approval, "operation_id": "competing-adopt",
            })
            self.assertEqual(second.status_code, 409)
            self.assertEqual(second.json()["error"]["code"], "campaign_busy")
            self.assertEqual(second.json()["error"]["message"], "上一次還在處理，等它好了再看。")

            served = client.get(self._path()).json()["campaign"]["busy"]
            self.assertEqual(served["kind"], "plan")
            since = datetime.datetime.fromisoformat(served["since"])
            # The window is the call's timeout + 30 s: just inside -> busy, just past -> not.
            window = plan.TIMEOUT_S + busy.GRACE_S
            for offset, expected in ((window - 1, "plan"), (window + 1, None)):
                now = since + datetime.timedelta(seconds=offset)
                with mock.patch.object(busy.db, "now_utc", return_value=now):
                    state = busy.busy_state(web.conn, self.org_id, self.brand_id,
                                            self.campaign["id"])
                self.assertEqual(state and state["kind"], expected)
        finally:
            provider.release.set()
            worker.join(30)

        self.assertEqual(first["response"].status_code, 200, first["response"].text)
        self.assertEqual(first["response"].json()["campaign"]["status"], "ready")
        adopted = first["response"].json()["campaign"]
        decision = adopted["budget_basis_json"]["strategy"]["decision"]
        self.assertEqual(decision["state"], "adopted")
        accepted = decision["receipt"]
        self.assertEqual(accepted["operation_id"], self.approval["operation_id"])
        self.assertEqual(accepted["revision"], self.revision)
        receipt = accepted["slots"]
        self.assertEqual({s["slot_id"] for s in receipt}, {s["id"] for s in decision["slots"]})
        self.assertEqual(len(adopted["groups"]), 1)
        self.assertEqual(adopted["groups"][0]["role"], "new")
        self.assertEqual(len(adopted["groups"][0]["ads"]), 1)
        self.assertEqual(receipt[0]["group_id"], adopted["groups"][0]["id"])
        self.assertEqual(receipt[0]["ad_id"], adopted["groups"][0]["ads"][0]["id"])
        self.assertIsNone(receipt[0]["carry_from_ad_id"])
        self.assertIsNone(first["response"].json()["campaign"]["busy"])
        self.assertIsNone(TestClient(main.app).get(self._path()).json()["campaign"]["busy"])


class OtherPlannerCallsTest(BusyTestBase):
    def test_strategy_generation_is_refused_while_the_campaign_is_held(self):
        with busy.claim(web.conn, self.campaign["id"], "plan"):
            response = TestClient(main.app).post(self._path("/strategy"))
        self.assertEqual((response.status_code, response.json()["error"]["code"]),
                         (409, "campaign_busy"))

    def test_a_create_is_refused_while_this_brands_parse_runs(self):
        with busy.claim(web.conn, self.brand_id, "brief"):
            response = TestClient(main.app).post(
                f"/api/ads/brands/{self.brand_id}/campaigns", json={"goal_text": "衝一波購買"})
        self.assertEqual((response.status_code, response.json()["error"]["code"]),
                         (409, "campaign_busy"))

    def test_a_campaign_without_a_running_call_is_not_busy(self):
        self.assertIsNone(busy.busy_state(web.conn, self.org_id, self.brand_id,
                                          self.campaign["id"]))


if __name__ == "__main__":
    unittest.main()
