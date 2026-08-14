# -*- coding: utf-8 -*-
"""T1 批次 B：四件事週報、收件匣通知與開檔方向二選一。"""

import atexit
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from unittest import mock

_tmpdir = tempfile.mkdtemp(prefix="brand_os_weekly_report_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import auto_sync  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.ads import routes_campaigns_open_api  # noqa: E402
from app.ads import weekly_reports  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import interrupts as core_interrupts  # noqa: E402


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"
TODAY = "2026-08-17"


class WeeklyReportTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(
            main.conn, name=f"虛構週報品牌{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR,
        )
        self.cycle = ads_repo.create_cycle(
            main.conn, self.brand["id"], product_ids=[], pain_value=12000,
            objective="sales", actor=ACTOR, start_date="2026-08-10", duration_days=14,
        )
        ads_repo.update_cycle_status(
            main.conn, self.brand["id"], self.cycle["id"], status="LIVE", actor=ACTOR,
        )

    def tearDown(self):
        main.conn.execute("DELETE FROM interrupt WHERE brand_id = ?", (self.brand["id"],))
        main.conn.execute("UPDATE campaign_cycle SET archived = 1 WHERE id = ?", (self.cycle["id"],))
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
            client_name=None, actor=ACTOR,
        )
        self.url = f"/api/campaigns/{self.brand['id']}/new-context/direction"

    def tearDown(self):
        bi_repo.update_brand(
            main.conn, self.brand["id"], name=self.brand["name"],
            client_name=self.brand["client_name"], status="archived", actor=ACTOR,
        )

    def test_history_states_are_ready_empty_or_unavailable_without_blocking_opening(self):
        with mock.patch.object(
            routes_campaigns_open_api.nextcycle,
            "historical_cell_performance",
            return_value=[{"creative_angle": "虛構回購方向", "conversions": 8, "spend": 1600}],
        ):
            ready = self.client.get(self.url)
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(ready.json()["data"], {"status": "ready", "direction": "虛構回購方向"})

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


if __name__ == "__main__":
    unittest.main()
