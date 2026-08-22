# -*- coding: utf-8 -*-
"""T3 開檔建議、管道計畫與任務卡的可判定驗收。"""

import atexit
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_tmpdir = tempfile.mkdtemp(prefix="brand_os_opening_suggestion_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import opening_suggestion  # noqa: E402
from app.ads import repository_channel_plan as plan_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core.db import new_id, now_iso  # noqa: E402


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)
ACTOR = "測試員"
FORBIDDEN_SUMMARY_WORDS = ("受眾", "漏斗", "CPA", "CTR", "CPC", "ROAS", "KPI")


class _BaseOpeningSuggestionTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(
            main.conn, name=f"虛構開檔茶行{abs(hash(self.id())) % 100000}", client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]

    def add_product(self, name: str, *, selling_price: float = 100, cost: float = 0) -> dict:
        product = bi_repo.create_product(main.conn, self.bid, name=name, actor=ACTOR)
        bi_repo.save_product_economics(
            main.conn, self.bid, product["id"], actor=ACTOR, selling_price=selling_price,
            unit_variable_cost=cost, currency="TWD", confirmed_by=ACTOR,
        )
        return product

    def add_channel(self):
        return bi_repo.create_channel(
            main.conn, self.bid, actor=ACTOR, channel_type="website", name="虛構官網",
            identifier="https://example.test",
        )

    def add_cycle(self, *, status: str = "PLANNING", start_date: str = "2026-08-01") -> str:
        cycle_id = new_id("ccy")
        ts = now_iso()
        main.conn.execute(
            "INSERT INTO campaign_cycle (id, brand_id, product_scope_json, objective, currency, start_date, "
            "end_date, channels_json, status, archived, plan_version, phase, created_at, updated_at) "
            "VALUES (?, ?, '[]', 'sales', 'TWD', ?, '2026-08-14', '[]', ?, 0, 0, "
            "'normal', ?, ?)",
            (cycle_id, self.bid, start_date, status, ts, ts),
        )
        main.conn.commit()
        return cycle_id

    def store_next_cycle_recommendation(self, cycle_id: str, proposed_budget: float) -> None:
        """比照 nextcycle.build() 的寫法存一筆下期建議（洞 A 測試用）。"""
        import json

        main.conn.execute(
            "INSERT INTO recommendation (id, brand_id, campaign_cycle_id, recommendation_type,"
            " content_json, status, created_at, updated_at)"
            " VALUES (?, ?, ?, 'next_cycle', ?, 'GENERATED', ?, ?)",
            (new_id("rec"), self.bid, cycle_id,
             json.dumps({"budget": {"proposed_budget": proposed_budget}}, ensure_ascii=False),
             now_iso(), now_iso()),
        )
        main.conn.commit()

    def add_history_without_product(self, cycle_id: str, conversions: float) -> None:
        """product_id 為 NULL 的歷史切角（洞 B 測試用），並且把該期產品登記進
        campaign_cycle_product 讓退路（D4）有東西可用。"""
        ts = now_iso()
        cell_id, package_id, mapping_id = (new_id(prefix) for prefix in ("exc", "pkg", "xam"))
        main.conn.execute(
            "INSERT INTO experiment_cell (id, campaign_cycle_id, brand_id, product_id, creative_angle, created_at) "
            "VALUES (?, ?, ?, NULL, '虛構切角', ?)", (cell_id, cycle_id, self.bid, ts))
        main.conn.execute(
            "INSERT INTO publishing_package (id, brand_id, campaign_cycle_id, experiment_cell_id, product_id, "
            "campaign_name, adset_name, ad_name, destination_url, utm_json, status, created_at) "
            "VALUES (?, ?, ?, ?, NULL, '虛構活動', '虛構組', '虛構廣告', 'https://example.test', '{}', 'ready', ?)",
            (package_id, self.bid, cycle_id, cell_id, ts))
        main.conn.execute(
            "INSERT INTO external_ad_mapping (id, brand_id, publishing_package_id, campaign_cycle_id, platform, "
            "created_at) VALUES (?, ?, ?, ?, 'meta', ?)",
            (mapping_id, self.bid, package_id, cycle_id, ts))
        main.conn.execute(
            "INSERT INTO performance_snapshot (id, brand_id, campaign_cycle_id, external_ad_mapping_id, platform, "
            "date_range_start, date_range_end, as_of_date, snapshot_taken_at, currency, conversions, source, "
            "created_at) VALUES (?, ?, ?, ?, 'meta', '2026-08-01', '2026-08-01', '2026-08-01', ?, 'TWD', ?, "
            "'manual', ?)",
            (new_id("psn"), self.bid, cycle_id, mapping_id, ts, conversions, ts))
        main.conn.commit()

    def add_cycle_product(self, cycle_id: str, product_id: str) -> None:
        main.conn.execute(
            "INSERT INTO campaign_cycle_product (id, campaign_cycle_id, brand_id, product_id, allocated_budget,"
            " allocation_ratio, allocation_basis, economics_missing, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, 0, 0, 'even', 0, ?, ?)",
            (new_id("ccp"), cycle_id, self.bid, product_id, now_iso(), now_iso()),
        )
        main.conn.commit()

    def add_history(self, cycle_id: str, product_id: str, conversions: float) -> None:
        ts = now_iso()
        cell_id, package_id, mapping_id = (new_id(prefix) for prefix in ("exc", "pkg", "xam"))
        main.conn.execute(
            "INSERT INTO experiment_cell (id, campaign_cycle_id, brand_id, product_id, creative_angle, created_at) "
            "VALUES (?, ?, ?, ?, '虛構切角', ?)", (cell_id, cycle_id, self.bid, product_id, ts))
        main.conn.execute(
            "INSERT INTO publishing_package (id, brand_id, campaign_cycle_id, experiment_cell_id, product_id, "
            "campaign_name, adset_name, ad_name, destination_url, utm_json, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, '虛構活動', '虛構組', '虛構廣告', 'https://example.test', '{}', 'ready', ?)",
            (package_id, self.bid, cycle_id, cell_id, product_id, ts))
        main.conn.execute(
            "INSERT INTO external_ad_mapping (id, brand_id, publishing_package_id, campaign_cycle_id, platform, "
            "created_at) VALUES (?, ?, ?, ?, 'meta', ?)",
            (mapping_id, self.bid, package_id, cycle_id, ts))
        main.conn.execute(
            "INSERT INTO performance_snapshot (id, brand_id, campaign_cycle_id, external_ad_mapping_id, platform, "
            "date_range_start, date_range_end, as_of_date, snapshot_taken_at, currency, conversions, source, "
            "created_at) VALUES (?, ?, ?, ?, 'meta', '2026-08-01', '2026-08-01', '2026-08-01', ?, 'TWD', ?, "
            "'manual', ?)",
            (new_id("psn"), self.bid, cycle_id, mapping_id, ts, conversions, ts))
        main.conn.commit()


class OpeningSuggestionApiTest(_BaseOpeningSuggestionTest):
    def test_multiple_products_without_history_uses_highest_margin(self):
        self.add_channel()
        lower = self.add_product("低毛利商品", selling_price=200, cost=150)
        higher = self.add_product("高毛利商品", selling_price=300, cost=80)

        response = self.client.get(f"/api/campaigns/brands/{self.bid}/opening-suggestion")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["available"])
        self.assertEqual(set(body), {"available", "summary", "suggestion", "channel_ask", "budget_basis"})
        self.assertEqual(
            set(body["suggestion"]),
            {"platform", "product_id", "product_name", "budget", "duration_days", "direction"},
        )
        self.assertEqual(body["suggestion"]["product_id"], higher["id"])
        self.assertNotEqual(body["suggestion"]["product_id"], lower["id"])
        for word in FORBIDDEN_SUMMARY_WORDS:
            self.assertNotIn(word, body["summary"])

    def test_history_uses_product_with_most_conversions(self):
        self.add_channel()
        lower = self.add_product("歷史較少", selling_price=100, cost=20)
        higher = self.add_product("歷史較多", selling_price=100, cost=20)
        cycle_id = self.add_cycle()
        self.add_history(cycle_id, lower["id"], conversions=2)
        self.add_history(cycle_id, higher["id"], conversions=7)

        body = self.client.get(f"/api/campaigns/brands/{self.bid}/opening-suggestion").json()

        self.assertTrue(body["available"])
        self.assertEqual(body["suggestion"]["product_id"], higher["id"])
        self.assertEqual(body["suggestion"]["direction"], "沿用有效方向")

    def test_single_product_is_selected(self):
        self.add_channel()
        product = self.add_product("唯一商品")

        body = self.client.get(f"/api/campaigns/brands/{self.bid}/opening-suggestion").json()

        self.assertTrue(body["available"])
        self.assertEqual(body["suggestion"]["product_id"], product["id"])
        self.assertEqual(body["suggestion"]["direction"], "首次")

    def test_no_channel_returns_question(self):
        self.add_product("未填通路商品")

        body = self.client.get(f"/api/campaigns/brands/{self.bid}/opening-suggestion").json()

        self.assertFalse(body["available"])
        self.assertEqual(body["channel_ask"], opening_suggestion.CHANNEL_ASK)

    def test_channel_answer_persists_then_get_returns_suggestion(self):
        self.add_product("回答後商品")
        url = f"/api/campaigns/brands/{self.bid}/opening-suggestion"

        answer = self.client.post(f"{url}/channel-answer", json={"answer": "LINE"})
        after = self.client.get(url)

        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertTrue(answer.json()["available"])
        self.assertTrue(after.json()["available"])
        self.assertTrue(any(channel["channel_type"] == "line" for channel in bi_repo.list_channels(main.conn, self.bid)))

    def test_uses_last_closed_cycle_recommendation_as_budget_basis(self):
        """驗收 1：最近一期 CLOSED、存了 proposed_budget=10000 → 沿用它，不是重算。"""
        self.add_channel()
        self.add_product("覆盤茶葉")
        closed_cycle = self.add_cycle(status="CLOSED", start_date="2026-07-01")
        self.store_next_cycle_recommendation(closed_cycle, proposed_budget=10000)

        body = self.client.get(f"/api/campaigns/brands/{self.bid}/opening-suggestion").json()

        self.assertTrue(body["available"])
        self.assertEqual(body["suggestion"]["budget"], 10000)
        self.assertEqual(body["budget_basis"], "closing_review")
        self.assertIn("依上一期覆盤建議", body["summary"])

    def test_no_closed_cycle_falls_back_to_pain_amount(self):
        """驗收 2：沒有 CLOSED 檔期 → 用今天的痛點金額，並且白話說明基準。"""
        self.add_channel()
        product = self.add_product("痛點茶葉")

        body = self.client.get(f"/api/campaigns/brands/{self.bid}/opening-suggestion").json()
        pain = opening_suggestion.target_cpa.suggest_pain_value(
            main.conn, self.bid, "sales", [product["id"]])
        expected = opening_suggestion.budget.plan_from_pain(pain["amount"]).total_budget

        self.assertTrue(body["available"])
        self.assertEqual(body["suggestion"]["budget"], expected)
        self.assertEqual(body["budget_basis"], "pain_amount")
        self.assertIn("依你設定的痛點金額", body["summary"])

    def test_summary_first_cycle_wording_only_when_truly_first(self):
        """驗收 3：情境 1（有 CLOSED 檔期）summary 不講「首次」；真正第一次仍講「首次」。"""
        self.add_channel()
        self.add_product("覆盤茶葉二號")
        closed_cycle = self.add_cycle(status="CLOSED", start_date="2026-07-01")
        self.store_next_cycle_recommendation(closed_cycle, proposed_budget=10000)

        with_history = self.client.get(f"/api/campaigns/brands/{self.bid}/opening-suggestion").json()
        self.assertNotIn("首次", with_history["summary"])

        fresh_brand = bi_repo.create_brand(
            main.conn, name=f"真正第一次茶行{abs(hash(self.id())) % 100000}", client_name=None, actor=ACTOR)
        bi_repo.create_channel(main.conn, fresh_brand["id"], actor=ACTOR, channel_type="website",
                               name="虛構官網", identifier="https://example.test")
        bi_repo.create_product(main.conn, fresh_brand["id"], name="第一次商品", actor=ACTOR)

        first_ever = self.client.get(f"/api/campaigns/brands/{fresh_brand['id']}/opening-suggestion").json()
        self.assertIn("首次", first_ever["summary"])

    def test_direction_falls_back_to_cycle_products_when_cell_product_id_is_null(self):
        """驗收 4：有轉換、但 experiment_cell.product_id 為 NULL 時仍能認出「沿用有效方向」
        （D4 的退路：均分該檔期登記的產品）。"""
        self.add_channel()
        product = self.add_product("退路商品")
        cycle_id = self.add_cycle()
        self.add_cycle_product(cycle_id, product["id"])
        self.add_history_without_product(cycle_id, conversions=5)

        body = self.client.get(f"/api/campaigns/brands/{self.bid}/opening-suggestion").json()

        self.assertTrue(body["available"])
        self.assertEqual(body["suggestion"]["direction"], "沿用有效方向")

    def test_internal_error_is_non_blocking_200(self):
        self.add_channel()
        self.add_product("故障測試商品")
        with mock.patch.object(opening_suggestion, "_choose_product", side_effect=RuntimeError("測試錯誤")):
            response = self.client.get(f"/api/campaigns/brands/{self.bid}/opening-suggestion")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["available"])
        self.assertIn("手動開檔", response.json()["reason"])


class ChannelPlanAndTaskCardRepositoryTest(_BaseOpeningSuggestionTest):
    def test_channel_plan_crud_and_previous_enabled_default(self):
        old_cycle = self.add_cycle()
        plan = plan_repo.create_channel_plan(
            main.conn, self.bid, old_cycle, channel="social", job="發文導購", pct=60,
            expected="讓更多人看到商品", enabled=False, depth="full")

        self.assertEqual(plan_repo.get_channel_plan(main.conn, self.bid, plan["id"])["enabled"], 0)
        updated = plan_repo.update_channel_plan(
            main.conn, self.bid, plan["id"], job="調整後分工", pct=70,
            expected="有更清楚的安排", enabled=True, depth="task_card")
        self.assertEqual(updated["depth"], "task_card")
        new_cycle = self.add_cycle()
        self.assertEqual(plan_repo.previous_enabled_defaults(main.conn, self.bid, new_cycle), {"social": True})
        plan_repo.delete_channel_plan(main.conn, self.bid, plan["id"])
        self.assertEqual(plan_repo.list_channel_plans(main.conn, self.bid, old_cycle), [])

    def test_task_card_crud_records_completion_time(self):
        cycle_id = self.add_cycle()
        card = plan_repo.create_task_card(
            main.conn, self.bid, cycle_id, channel="line_email", title="準備熟客訊息", draft_hint="草稿")

        self.assertEqual(plan_repo.get_task_card(main.conn, self.bid, card["id"])["done"], 0)
        done = plan_repo.update_task_card(
            main.conn, self.bid, card["id"], title="已準備熟客訊息", draft_hint="新版草稿", done=True)
        self.assertEqual(done["done"], 1)
        self.assertIsNotNone(done["done_at"])
        plan_repo.delete_task_card(main.conn, self.bid, card["id"])
        self.assertEqual(plan_repo.list_task_cards(main.conn, self.bid, cycle_id), [])


if __name__ == "__main__":
    unittest.main()
