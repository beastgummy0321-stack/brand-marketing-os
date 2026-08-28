"""T1 批次 B：四件事週報、收件匣通知與開檔方向二選一。"""

import unittest
from contextlib import contextmanager
from unittest import mock

from fastapi.testclient import TestClient

import app.main as main
from app.ads import auto_sync, routes_campaigns_open_api, weekly_reports
from app.ads import reading as ads_reading
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db
from app.core import interrupts as core_interrupts
from app.core.db import new_id, now_iso

ACTOR = "測試員"
TODAY = "2026-08-17"



def _seed_cell(conn, brand_id: str, cycle_id: str, *, creative_angle: str,
               spend: float, conversions: float, revenue: float) -> str:
    """建一條完整的 performance_snapshot → external_ad_mapping → publishing_package →
    experiment_cell 鏈（比照 test_ads_carry_forward.py 既有寫法，票 F11 done-check 4 要走
    真的 API 端到端，不能只靠 mock 掉 `carry_forward.prior_winners()`）。回傳 cell id。"""
    cell_id, pkg_id, mapping_id, ts = new_id("exc"), new_id("pkg"), new_id("xam"), now_iso()
    conn.execute(
        "INSERT INTO experiment_cell (id, org_id, campaign_cycle_id, brand_id, creative_angle,"
        " product_id, created_at) VALUES (%s, %s, %s, %s, %s, NULL, %s)",
        (cell_id, db.DEV_ORG_ID, cycle_id, brand_id, creative_angle, ts))
    conn.execute(
        "INSERT INTO publishing_package (id, org_id, brand_id, campaign_cycle_id, experiment_cell_id,"
        " campaign_name, adset_name, ad_name, destination_url, utm_json, status, created_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '{}', 'ready', %s)",
        (pkg_id, db.DEV_ORG_ID, brand_id, cycle_id, cell_id, "測試活動", "測試組合", f"{creative_angle}_ad",
         "https://example.test", ts))
    conn.execute(
        "INSERT INTO external_ad_mapping (id, org_id, brand_id, publishing_package_id,"
        " campaign_cycle_id, platform, claim_status, confirmed_by, confirmed_at, created_at)"
        " VALUES (%s, %s, %s, %s, %s, 'meta', 'confirmed', %s, %s, %s)",
        (mapping_id, db.DEV_ORG_ID, brand_id, pkg_id, cycle_id, ACTOR, ts, ts))
    conn.execute(
        "INSERT INTO performance_snapshot (id, org_id, brand_id, campaign_cycle_id, product_id,"
        " external_ad_mapping_id, platform, date_range_start, date_range_end, as_of_date,"
        " snapshot_taken_at, currency, spend, conversions, revenue, source, created_at)"
        " VALUES (%s, %s, %s, %s, NULL, %s, 'meta', '2026-01-01', '2026-01-07', '2026-01-07', %s, 'TWD',"
        " %s, %s, %s, 'manual', %s)",
        (new_id("psn"), db.DEV_ORG_ID, brand_id, cycle_id, mapping_id, ts, spend, conversions, revenue, ts))
    conn.commit()
    return cell_id


class WeeklyReportTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(
            main.conn, name=f"虛構週報品牌{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR, org_id=db.DEV_ORG_ID,
        )
        self.cycle = ads_repo.create_cycle(
            main.conn, self.brand["id"], product_ids=[], pain_value=12000,
            objective="sales", actor=ACTOR, start_date="2026-08-10", duration_days=14,
        )
        ads_repo.update_cycle_status(
            main.conn, self.brand["id"], self.cycle["id"], status="LIVE", actor=ACTOR,
        )

    def tearDown(self):
        main.conn.execute("DELETE FROM interrupt WHERE brand_id = %s", (self.brand["id"],))
        main.conn.execute("UPDATE campaign_cycle SET archived = true WHERE id = %s", (self.cycle["id"],))
        main.conn.commit()
        bi_repo.update_brand(
            main.conn, self.brand["id"], name=self.brand["name"],
            client_name=self.brand["client_name"], status="archived", actor=ACTOR,
        )

    def _cards(self):
        return [
            {
                "id": "rec-spend", "action": "加碼", "target": "虛構回購方向",
                "reason": "每筆訂單花費維持穩定", "status": "GENERATED",
                "suggested_amount": 18000,
            },
            {
                "id": "rec-save", "action": "停掉", "target": "虛構送禮方向",
                "reason": "花費增加但沒有帶來訂單", "status": "GENERATED",
            },
        ]

    @contextmanager
    def _report_sources(self, *, spend=2140, cards=None):
        with (
            mock.patch.object(weekly_reports.ads_performance, "brand_period_spend", return_value=spend) as spend_source,
            mock.patch.object(
                weekly_reports, "_order_stats",
                return_value={"has_history": True, "order_count": 14, "net_revenue": 9730},
            ) as order_source,
            mock.patch.object(
                weekly_reports.ads_reading, "load",
                return_value={"cycle": {"llm_explanation": "虛構回購方向持續帶來訂單，值得保留。"}},
            ) as reading_source,
            mock.patch.object(
                weekly_reports.weekly_proposals, "list_cards",
                return_value=cards if cards is not None else self._cards(),
            ) as proposal_source,
        ):
            yield (spend_source, order_source, reading_source, proposal_source)

    def test_assemble_uses_four_fixed_sources_and_prioritizes_loss_prevention(self):
        with self._report_sources() as patches:
            report = weekly_reports.assemble(
                main.conn, self.brand["id"], self.cycle["id"], today=TODAY,
            )

        self.assertEqual(report["week_start"], "2026-08-10")
        self.assertEqual(report["week_end"], "2026-08-16")
        self.assertEqual(report["spend"], 2140)
        self.assertEqual(report["orders"], 14)
        self.assertEqual(report["revenue"], 9730)
        self.assertEqual(report["keep"], "虛構回購方向持續帶來訂單，值得保留。")
        self.assertEqual(report["primary_proposal_id"], "rec-save")
        self.assertEqual(report["other_proposal_ids"], ["rec-spend"])
        self.assertTrue(all(p.called for p in patches))

    def test_incomplete_data_does_not_produce_a_partial_report_or_notification(self):
        with self._report_sources(spend=None):
            report = weekly_reports.assemble(
                main.conn, self.brand["id"], self.cycle["id"], today=TODAY,
            )
            interrupt_id = weekly_reports.enqueue_if_ready(
                main.conn, self.brand["id"], self.cycle["id"], today=TODAY,
            )

        self.assertIsNone(report)
        self.assertIsNone(interrupt_id)
        self.assertEqual(
            core_interrupts.list_open(
                main.conn, brand_id=self.brand["id"], category="weekly_report_ready",
                archive_stale=False,
            ),
            [],
        )

    def test_ready_report_is_enqueued_once_and_weekly_engine_uses_the_same_run(self):
        with self._report_sources():
            first = weekly_reports.enqueue_if_ready(
                main.conn, self.brand["id"], self.cycle["id"], today=TODAY,
            )
            second = weekly_reports.enqueue_if_ready(
                main.conn, self.brand["id"], self.cycle["id"], today=TODAY,
            )

        queued = core_interrupts.list_open(
            main.conn, brand_id=self.brand["id"], category="weekly_report_ready",
            archive_stale=False,
        )
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]["message"], "本週報告好了")

        with (
            mock.patch.object(auto_sync.bi_repo, "list_brands", return_value=[self.brand]),
            mock.patch.object(auto_sync.weekly_proposals, "current_cycle", return_value=self.cycle),
            mock.patch.object(auto_sync.reading, "run", return_value=(True, None)),
            mock.patch.object(auto_sync.weekly_proposals, "generate", return_value=self._cards()),
            mock.patch.object(auto_sync.weekly_reports, "enqueue_if_ready") as enqueue,
        ):
            auto_sync.run_weekly_engine(main.conn, today=TODAY)

        enqueue.assert_called_once_with(
            main.conn, self.brand["id"], self.cycle["id"], today=TODAY,
        )


class NewCycleDirectionApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(
            main.conn, name=f"虛構開檔品牌{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR, org_id=db.DEV_ORG_ID,
        )
        self.url = f"/api/campaigns/{self.brand['id']}/new-context/direction"

    def tearDown(self):
        bi_repo.update_brand(
            main.conn, self.brand["id"], name=self.brand["name"],
            client_name=self.brand["client_name"], status="archived", actor=ACTOR,
        )

    def test_history_states_are_ready_empty_or_unavailable_without_blocking_opening(self):
        # 票 F10：「ready」現在讀 carry_forward.prior_winners()（F7 的誠實贏家），不是
        # 直接對歷史切角取轉換數最大值——historical_cell_performance 只用來判斷「有沒有
        # 歷史資料可看」，內容不再直接決定畫面文字。
        with (
            mock.patch.object(
                routes_campaigns_open_api.nextcycle, "historical_cell_performance",
                return_value=[{"creative_angle": "虛構回購方向", "conversions": 8, "spend": 1600}],
            ),
            mock.patch.object(
                routes_campaigns_open_api.carry_forward, "prior_winners",
                return_value=[{"angle": "虛構回購方向", "roas": 3.5, "spend": 1600,
                              "conversions": 8, "source_cycle_id": "ccy_x"}],
            ),
        ):
            ready = self.client.get(self.url)
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(ready.json()["data"], {
            "status": "ready", "direction": "虛構回購方向", "roas": 3.5,
            "label": "沿用上期贏家：虛構回購方向（ROAS 3.50）",
        })

        with mock.patch.object(
            routes_campaigns_open_api.nextcycle, "historical_cell_performance", return_value=[],
        ):
            empty = self.client.get(self.url)
        self.assertEqual(empty.json()["data"], {"status": "empty"})

        with mock.patch.object(
            routes_campaigns_open_api.nextcycle,
            "historical_cell_performance",
            side_effect=RuntimeError("虛構讀取失敗"),
        ):
            unavailable = self.client.get(self.url)
        self.assertEqual(unavailable.json()["data"], {"status": "unavailable"})

    def test_no_qualified_winner_shows_generic_wording_not_a_code(self):
        """票 F10 驗收 2：歷史切角都是代號形狀（如驗收資料的 normal_1）／沒有誠實贏家
        （F7 的 evidence_sufficient 門檻沒過），畫面只能看到「沿用上期設定」，不能看到代號。"""
        with (
            mock.patch.object(
                routes_campaigns_open_api.nextcycle, "historical_cell_performance",
                return_value=[{"creative_angle": "normal_1", "conversions": 30, "spend": 4500,
                              "revenue": 29704.5, "product_id": None,
                              "campaign_cycle_id": "ccy_x", "evidence_sufficient": False}],
            ),
            mock.patch.object(
                routes_campaigns_open_api.carry_forward, "prior_winners", return_value=[],
            ),
        ):
            resp = self.client.get(self.url)
        self.assertEqual(resp.json()["data"], {"status": "ready", "label": "沿用上期設定"})
        self.assertNotIn("normal_", resp.text)

    def test_qualified_winner_shows_angle_name_and_roas(self):
        """票 F10 驗收 3：有 F7 贏家時，label 帶角名與 ROAS。"""
        with (
            mock.patch.object(
                routes_campaigns_open_api.nextcycle, "historical_cell_performance",
                return_value=[{"creative_angle": "實證成分", "conversions": 30, "spend": 4500,
                              "revenue": 19350.0, "product_id": None,
                              "campaign_cycle_id": "ccy_x", "evidence_sufficient": True}],
            ),
            mock.patch.object(
                routes_campaigns_open_api.carry_forward, "prior_winners",
                return_value=[{"angle": "實證成分", "roas": 4.3, "spend": 4500,
                              "conversions": 30, "source_cycle_id": "ccy_x"}],
            ),
        ):
            resp = self.client.get(self.url)
        self.assertEqual(resp.json()["data"], {
            "status": "ready", "direction": "實證成分", "roas": 4.3,
            "label": "沿用上期贏家：實證成分（ROAS 4.30）",
        })

    def test_signed_learning_naming_no_cell_shows_generic_wording_not_a_code(self):
        """票 F11 done-check 4：真實情境重現（不 mock `nextcycle`／`carry_forward`）——
        品牌歷史只有代號形狀的切角（`normal_1`／`fatigue`／`bad_cvr`），簽核學習的句子
        沒點名任何一個，畫面只能看到「沿用上期設定」，不能看到任何代號或掰出來的數字。
        這取代 F10 原本 done-check 1（只查「找不到 normal_ 」），因為 F7 的舊橋接曾經讓
        `fatigue` 這個代號直接冒出來，而那條檢查測不到。RED first。"""
        cycle_id = ads_repo.create_cycle(
            main.conn, self.brand["id"], product_ids=[], pain_value=10000,
            objective="sales", actor=ACTOR)["id"]
        for angle, conversions, spend, revenue in (
            ("normal_1", 30, 4500, 4500 * 6.60),
            ("fatigue", 30, 4500, 4500 * 6.60),
            ("bad_cvr", 30, 4500, 4500 * 0.99),
        ):
            _seed_cell(main.conn, self.brand["id"], cycle_id, creative_angle=angle,
                      spend=spend, conversions=conversions, revenue=revenue)
        hyp = bi_repo.create_strategy_hypothesis(
            main.conn, self.brand["id"], actor=ACTOR, hypothesis_type="message",
            statement="拿證據說話的切角比純促銷更能拉高轉換率", created_by=ACTOR,
            product_id=None, source_cycle_id=cycle_id)
        main.conn.execute(
            "INSERT INTO campaign_cycle_hypothesis (org_id, campaign_cycle_id, strategy_hypothesis_id,"
            " brand_id, role) VALUES (%s, %s, %s, %s, 'message')",
            (db.DEV_ORG_ID, cycle_id, hyp["id"], self.brand["id"]))
        main.conn.commit()
        updated = ads_reading.resolve_hypotheses(
            main.conn, self.brand["id"], cycle_id, {hyp["id"]: "supported"}, actor=ACTOR)
        self.assertEqual(updated, 1)

        resp = self.client.get(self.url)

        self.assertEqual(resp.json()["data"], {"status": "ready", "label": "沿用上期設定"})
        self.assertNotIn("normal_", resp.text)
        self.assertNotIn("fatigue", resp.text)
        self.assertNotIn("bad_cvr", resp.text)


if __name__ == "__main__":
    unittest.main()
