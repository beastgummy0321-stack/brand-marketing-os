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

    def add_cycle(self) -> str:
        cycle_id = new_id("ccy")
        ts = now_iso()
        main.conn.execute(
            "INSERT INTO campaign_cycle (id, brand_id, product_scope_json, objective, currency, start_date, "
            "end_date, channels_json, status, archived, plan_version, phase, created_at, updated_at) "
            "VALUES (?, ?, '[]', 'sales', 'TWD', '2026-08-01', '2026-08-14', '[]', 'PLANNING', 0, 0, "
            "'normal', ?, ?)",
            (cycle_id, self.bid, ts, ts),
        )
        main.conn.commit()
        return cycle_id

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
        self.assertEqual(set(body), {"available", "summary", "suggestion", "channel_ask"})
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
