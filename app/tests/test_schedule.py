"""app/tests/test_schedule.py — 票 07：檔期規劃最薄路徑；票 08：表單擴成 N 個方案。

只寫這些事（docs/workflow-diet.md 第 4 條；票 07／08 settled 段都明講畫面行為不寫單元
測試）：金額算法（最大餘數法）、比例不合法／方案格式不合法的拒絕、租戶隔離、API 契約
（含 ADR 0029「原樣貼進 prompt」的可驗證證據、票 08 的平台／目標／方案數驗證）、
「查詢不是排程的先決條件」這條資料正確性規則。全程只用 FakeProvider，不發任何真實
網路請求；網路搜尋工具本身怎麼解析 SDK 回應（成功／出錯兩種形狀）不在這裡測，那是
`AnthropicProvider.complete()` 的責任，見 test_llm_web_search.py。
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

# 有效的平台／目標——照 app/schedule/platform_objectives.json 的內容取，測試不重寫一份
# 平行的資料（改資料檔不用跟著改這裡）。
_DATA = schedule_routes._load_platform_data()
VALID_PLATFORM = next(p["id"] for p in _DATA["platforms"] if p["enabled"])
VALID_OBJECTIVE = next(o["value"] for o in _DATA["objectives"] if o["platform"] == VALID_PLATFORM)
DISABLED_PLATFORM = next(p["id"] for p in _DATA["platforms"] if not p["enabled"])


def _fenced(splits: list) -> str:
    body = json.dumps({"splits": splits}, ensure_ascii=False)
    return f"這是一段給老闆看的說明文字。\n\n```json\n{body}\n```"


def _fenced_plans(plans: list) -> str:
    body = json.dumps({"plans": plans}, ensure_ascii=False)
    return f"這是一段給老闆看的說明文字。\n\n```json\n{body}\n```"


def _one_plan(**overrides) -> dict:
    plan = {
        "summary": "主打驗證過的受眾，小額測試新概念。",
        "reasoning": "過去表現穩定，先守住再小額試新的。",
        "splits": [
            {"label": "主力方向", "share": 0.7, "why": "已驗證的受眾，先守住"},
            {"label": "測試方向", "share": 0.3, "why": "新概念，小額試"},
        ],
    }
    plan.update(overrides)
    return plan


def _fake(rendered_output: str, search_sources: list | None = None) -> providers.FakeProvider:
    return providers.FakeProvider(response=providers.ProviderResponse(
        output_text=rendered_output, structured=None,
        usage=providers.Usage(input_tokens=500, output_tokens=200), stop_reason="end_turn",
        search_sources=search_sources,
    ))


def _post_body(**overrides) -> dict:
    body = {
        "product_ids": [],  # 呼叫端自己補
        "platform": VALID_PLATFORM,
        "objective": VALID_OBJECTIVE,
        "promotion_note": "",
        "plan_count": 2,
    }
    body.update(overrides)
    return body


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


# -- 2b. 票 08：N 個方案，任何一個壞掉整批失敗 -----------------------------------------

class BuildPlansTest(unittest.TestCase):
    def test_n_plans_all_succeed(self):
        plans, failure = plan_mod.build_plans(
            _fenced_plans([_one_plan(), _one_plan(summary="第二個方案")]), daily_budget=1000,
        )
        self.assertIsNone(failure)
        self.assertEqual(len(plans), 2)
        self.assertEqual(sum(s["daily_amount"] for s in plans[0]["splits"]), 1000)
        self.assertEqual(plans[1]["summary"], "第二個方案")

    def test_one_bad_plan_fails_the_whole_batch(self):
        good = _one_plan()
        bad = _one_plan(splits=[{"label": "x", "share": 0.5, "why": "y"}])  # 只有 0.5，加總不是 1
        plans, failure = plan_mod.build_plans(_fenced_plans([good, bad]), daily_budget=1000)
        self.assertEqual(plans, [])
        self.assertTrue(failure)

    def test_missing_plans_key_is_a_failure(self):
        plans, failure = plan_mod.build_plans(_fenced([{"label": "x", "share": 1.0, "why": "y"}]),
                                              daily_budget=1000)
        self.assertEqual(plans, [])
        self.assertTrue(failure)


# -- 3／4／5：API 契約、租戶隔離、prompt 原樣貼入（ADR 0029）、票 08 表單驗證 -----------

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

    def _post(self, **overrides):
        body = _post_body(product_ids=[self.product["id"]], **overrides)
        return self.client.post(f"/api/schedule/brands/{self.brand['id']}/plans", json=body)


class PlanApiContractTest(_ScheduleApiTestBase):
    def test_get_before_any_run_returns_null_plan_and_form_data(self):
        resp = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["daily_budget"], 3000.0)
        self.assertIsNone(body["plan"])
        # 方案數上下限來自規則卡 schedule_plan_count，預設 1～5（票 08）。
        self.assertEqual(body["plan_count_min"], 1)
        self.assertEqual(body["plan_count_max"], 5)
        # 平台／目標來自資料檔，不是外殼寫死——Meta 開放，Google／TikTok 列出但停用。
        platform_ids = {p["id"]: p["enabled"] for p in body["platforms"]}
        self.assertEqual(platform_ids, {"meta": True, "google": False, "tiktok": False})
        self.assertTrue(all(o["source_url"] for o in body["objectives"]))

    def test_post_returns_n_plan_cards_and_prompt_carries_department_file(self):
        fake = _fake(_fenced_plans([_one_plan(), _one_plan(summary="第二個方案")]))
        schedule_routes.PROVIDER = fake

        resp = self._post(plan_count=2)
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        plan = body["plan"]
        self.assertIsNone(plan["failure"])
        self.assertEqual(plan["product_ids"], [self.product["id"]])
        self.assertEqual(plan["platform"], VALID_PLATFORM)
        self.assertEqual(plan["objective"], VALID_OBJECTIVE)
        self.assertEqual(len(plan["plans"]), 2)  # 要求 2 個，回 2 張卡
        self.assertEqual(sum(s["daily_amount"] for s in plan["plans"][0]["splits"]), 3000)

        # ADR 0029：部門任務檔原樣貼進 prompt，不解讀——用檔案裡的識別行證明真的貼進去了。
        self.assertEqual(len(fake.calls), 1)
        prompt_text = fake.calls[0]["messages"][0]["content"]
        self.assertIn("SCHEDULE-PLAN-TASK-V1", prompt_text)

    def test_get_after_post_returns_identical_plans(self):
        schedule_routes.PROVIDER = _fake(_fenced_plans([_one_plan()]))
        post_resp = self._post(plan_count=1)
        get_resp = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(post_resp.json()["plan"], get_resp.json()["plan"])

    def test_budget_not_set_refuses_before_calling_agent(self):
        rule_cards.set_value(
            web.conn, self.brand["id"], "schedule_budget", "daily_budget", 0.0,
            ACTOR, org_id=coredb.DEV_ORG_ID,
        )
        fake = _fake(_fenced_plans([_one_plan()]))
        schedule_routes.PROVIDER = fake
        resp = self._post()
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["message"], plan_mod.BUDGET_NOT_SET_MESSAGE)
        self.assertEqual(fake.calls, [])  # 沒打到代理

    def test_disabled_platform_is_rejected_before_calling_agent(self):
        fake = _fake(_fenced_plans([_one_plan()]))
        schedule_routes.PROVIDER = fake
        resp = self._post(platform=DISABLED_PLATFORM)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(fake.calls, [])

    def test_objective_not_belonging_to_platform_is_rejected(self):
        fake = _fake(_fenced_plans([_one_plan()]))
        schedule_routes.PROVIDER = fake
        resp = self._post(objective="這不是有效的目標值")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(fake.calls, [])

    def test_plan_count_out_of_rule_card_range_is_rejected(self):
        fake = _fake(_fenced_plans([_one_plan()]))
        schedule_routes.PROVIDER = fake
        resp = self._post(plan_count=6)  # 規則卡預設上限 5
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(fake.calls, [])

    def test_another_orgs_brand_is_404(self):
        _org_b, token_b = self._make_org("b")
        resp = self.client.get(
            f"/api/schedule/brands/{self.brand['id']}", headers=self._headers(token_b, _org_b)
        )
        self.assertEqual(resp.status_code, 404)

        post_resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/plans",
            json=_post_body(product_ids=[self.product["id"]]),
            headers=self._headers(token_b, _org_b),
        )
        self.assertEqual(post_resp.status_code, 404)


class SearchSourcesReadbackTest(_ScheduleApiTestBase):
    """票 08 兩條不可妥協規則之一：查詢不是排程的先決條件——這裡只驗證 gateway →
    usage_json → plan_from_task_row 這段管線本身接得起來；SDK 回應怎麼解析成
    search_sources（成功／出錯兩種形狀）在 test_llm_web_search.py 測，不在這裡重測。
    """

    def test_search_sources_are_stored_and_read_back(self):
        sources = [{"title": "雙十一活動頁", "url": "https://example.com/1111"}]
        schedule_routes.PROVIDER = _fake(_fenced_plans([_one_plan()]), search_sources=sources)
        resp = self._post(plan_count=1)
        self.assertEqual(resp.json()["plan"]["sources"], sources)

    def test_no_search_sources_still_returns_plans(self):
        # FakeProvider 預設 search_sources=None（沒開搜尋、或搜尋沒找到東西）：排程照樣成功，
        # 不會因為沒有搜尋結果就整個排程失敗。
        schedule_routes.PROVIDER = _fake(_fenced_plans([_one_plan()]))
        resp = self._post(plan_count=1)
        body = resp.json()
        self.assertIsNone(body["plan"]["failure"])
        self.assertEqual(body["plan"]["sources"], [])


if __name__ == "__main__":
    unittest.main()
