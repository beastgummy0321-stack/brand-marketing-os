"""app/tests/test_schedule.py — 票 07：檔期規劃最薄路徑。

只寫四件事（docs/workflow-diet.md 第 4 條；票 07 settled 段「Tests」節明講畫面行為不寫
單元測試）：金額算法（最大餘數法）、比例不合法的拒絕、租戶隔離、API 契約（含 ADR 0029
「原樣貼進 prompt」的可驗證證據）。全程只用 FakeProvider，不發任何真實網路請求。
"""

import json
import unittest

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.core import rule_cards
from app.identity import repository as identity_repo
from app.llm import providers
from app.schedule import plan as plan_mod
from app.schedule import routes as schedule_routes

from .identity_test_helpers import mint_hs256

ACTOR = "測試員"


def _fenced(splits: list) -> str:
    body = json.dumps({"splits": splits}, ensure_ascii=False)
    return f"這是一段給老闆看的說明文字。\n\n```json\n{body}\n```"


def _fake(rendered_output: str) -> providers.FakeProvider:
    return providers.FakeProvider(response=providers.ProviderResponse(
        output_text=rendered_output, structured=None,
        usage=providers.Usage(input_tokens=500, output_tokens=200), stop_reason="end_turn",
    ))


# -- 1. 最大餘數法：整數金額，加總精確等於預算 ----------------------------------------

class LargestRemainderAllocationTest(unittest.TestCase):
    def test_amounts_are_integers_and_sum_exactly_to_budget(self):
        amounts = plan_mod.largest_remainder_allocation(3000, [0.7, 0.3])
        self.assertTrue(all(isinstance(a, int) for a in amounts))
        self.assertEqual(sum(amounts), 3000)

    def test_three_way_split_still_sums_exactly(self):
        amounts = plan_mod.largest_remainder_allocation(1000, [1 / 3, 1 / 3, 1 / 3])
        self.assertTrue(all(isinstance(a, int) for a in amounts))
        self.assertEqual(sum(amounts), 1000)

    def test_build_splits_success_shape(self):
        splits, failure = plan_mod.build_splits(_fenced([
            {"label": "主力方向", "share": 0.7, "why": "已驗證的受眾"},
            {"label": "測試方向", "share": 0.3, "why": "新概念"},
        ]), daily_budget=3000)
        self.assertIsNone(failure)
        self.assertEqual(sum(s["daily_amount"] for s in splits), 3000)
        self.assertEqual([s["label"] for s in splits], ["主力方向", "測試方向"])


# -- 2. 比例加總不是 1.0 → failure 設定，splits 清空，沒有金額 -------------------------

class BadSharesTest(unittest.TestCase):
    def test_shares_not_summing_to_one_is_a_failure(self):
        splits, failure = plan_mod.build_splits(_fenced([
            {"label": "主力方向", "share": 0.5, "why": "x"},
            {"label": "測試方向", "share": 0.2, "why": "y"},
        ]), daily_budget=3000)
        self.assertEqual(splits, [])
        self.assertTrue(failure)

    def test_missing_json_block_is_a_failure(self):
        splits, failure = plan_mod.build_splits(
            "這裡面沒有任何 fenced json 區塊。", daily_budget=3000
        )
        self.assertEqual(splits, [])
        self.assertTrue(failure)

    def test_float_slack_within_tolerance_still_succeeds(self):
        # 0.7 + 0.3 == 0.9999999999999999（IEEE-754），不得被當成失敗。
        splits, failure = plan_mod.build_splits(_fenced([
            {"label": "A", "share": 0.7, "why": "x"},
            {"label": "B", "share": 0.3, "why": "y"},
        ]), daily_budget=100)
        self.assertIsNone(failure)
        self.assertEqual(sum(s["daily_amount"] for s in splits), 100)


# -- 3／4／5：API 契約、租戶隔離、prompt 原樣貼入（ADR 0029）--------------------------

class _ScheduleApiTestBase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(
            web.conn, org_id=coredb.DEV_ORG_ID, name="測試品牌：晨露茶飲",
            client_name=None, actor=ACTOR,
        )
        self.product = bi_repo.create_product(
            web.conn, self.brand["id"], name="測試產品：蜂蜜柚子茶", actor=ACTOR,
        )
        rule_cards.set_value(
            web.conn, self.brand["id"], "schedule_budget", "daily_budget", 3000.0,
            ACTOR, org_id=coredb.DEV_ORG_ID,
        )
        self._orig_provider = schedule_routes.PROVIDER

    def tearDown(self):
        schedule_routes.PROVIDER = self._orig_provider

    def _make_org(self, suffix: str) -> tuple:
        org_id = f"org_schedule_test_{suffix}"
        web.conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
            " ON CONFLICT (id) DO NOTHING",
            (org_id, org_id),
        )
        import uuid

        user_id = uuid.uuid4()
        email = f"schedule-test-{suffix}-{user_id.hex[:8]}@example.com"
        identity_repo.create_user(web.conn, user_id, email)
        identity_repo.create_membership(web.conn, org_id, user_id, "owner")
        web.conn.commit()
        token = mint_hs256(sub=str(user_id), email=email)
        return org_id, token

    @staticmethod
    def _headers(token: str, org_id: str) -> dict:
        return {"Authorization": f"Bearer {token}", "X-Org-Id": org_id}


class PlanApiContractTest(_ScheduleApiTestBase):
    def test_get_before_any_run_returns_null_plan(self):
        resp = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"daily_budget": 3000.0, "plan": None})

    def test_post_with_fake_provider_succeeds_and_prompt_carries_department_file(self):
        fake = _fake(_fenced([
            {"label": "主力方向", "share": 0.7, "why": "已驗證的受眾，先守住"},
            {"label": "測試方向", "share": 0.3, "why": "新概念，小額試"},
        ]))
        schedule_routes.PROVIDER = fake

        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/plans",
            json={"product_ids": [self.product["id"]]},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["daily_budget"], 3000.0)
        plan = body["plan"]
        self.assertIsNone(plan["failure"])
        self.assertEqual(plan["product_ids"], [self.product["id"]])
        self.assertEqual(sum(s["daily_amount"] for s in plan["splits"]), 3000)

        # ADR 0029：部門任務檔原樣貼進 prompt，不解讀——用檔案裡的識別行證明真的貼進去了。
        self.assertEqual(len(fake.calls), 1)
        prompt_text = fake.calls[0]["messages"][0]["content"]
        self.assertIn("SCHEDULE-PLAN-TASK-V1", prompt_text)

    def test_get_after_post_returns_identical_amounts(self):
        schedule_routes.PROVIDER = _fake(_fenced([
            {"label": "主力方向", "share": 0.7, "why": "已驗證的受眾"},
            {"label": "測試方向", "share": 0.3, "why": "新概念"},
        ]))
        post_resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/plans",
            json={"product_ids": [self.product["id"]]},
        )
        get_resp = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(post_resp.json()["plan"], get_resp.json()["plan"])

    def test_budget_not_set_refuses_before_calling_agent(self):
        rule_cards.set_value(
            web.conn, self.brand["id"], "schedule_budget", "daily_budget", 0.0,
            ACTOR, org_id=coredb.DEV_ORG_ID,
        )
        fake = _fake(_fenced([{"label": "x", "share": 1.0, "why": "y"}]))
        schedule_routes.PROVIDER = fake
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/plans",
            json={"product_ids": [self.product["id"]]},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["message"], plan_mod.BUDGET_NOT_SET_MESSAGE)
        self.assertEqual(fake.calls, [])  # 沒打到代理

    def test_another_orgs_brand_is_404(self):
        _org_b, token_b = self._make_org("b")
        resp = self.client.get(
            f"/api/schedule/brands/{self.brand['id']}", headers=self._headers(token_b, _org_b)
        )
        self.assertEqual(resp.status_code, 404)

        post_resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/plans",
            json={"product_ids": [self.product["id"]]},
            headers=self._headers(token_b, _org_b),
        )
        self.assertEqual(post_resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
