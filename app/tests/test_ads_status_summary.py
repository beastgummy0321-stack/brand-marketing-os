"""app/tests/test_ads_status_summary.py — F27-I09 Contract I falsifiers: the brand-wide
`status_summary.get_status_summary()` (`last_success_at`/`attention`/`open_items`), plus
Done #7's `campaign_objective` on `repository.list_campaigns()`'s own cards (the triage-item side
of Done #7 is falsified in `test_ads_triage.py`, alongside `classify()`'s other read-only
enrichments).
"""

import unittest
from unittest.mock import patch

from app.ads import channels, connections, repository, status_summary, triage
from app.ads import external_repository as external
from app.brand_intelligence import repository as brands
from app.core import db, interrupts


class _Reader:
    """Reports one bound account, `act_1` (same stand-in shape as `test_ads_triage.py::_Reader`/
    `test_ads_repository.py::_Reader`)."""

    def accounts(self, conn, org, brand):
        return [{"account_id": "act_1", "currency": "TWD", "name": "來源",
                  "timezone_name": "Asia/Taipei"}]


class StatusSummaryTest(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="F27-I09 status-summary 測試", actor="test",
            client_name=None,
        )["id"]
        self.reader = _Reader()
        patcher = patch.object(
            channels, "external_reader", side_effect=lambda platform: self.reader,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _campaign(self, *, native_id, account="act_1", name="狀態測試活動"):
        campaign_id = external.create_imported_campaign(
            self.conn, self.org, self.brand, name=name,
        )["id"]
        external.upsert_entity(
            self.conn, self.org, self.brand, campaign_id,
            {"platform": "meta", "source_account": account, "native_kind": "campaign",
             "native_id": native_id},
        )
        self.conn.commit()
        return campaign_id

    def summary(self):
        return status_summary.get_status_summary(self.conn, self.org, self.brand)

    def test_no_campaigns_reads_null_and_zero_open_items(self):
        summary = self.summary()
        self.assertIsNone(summary["last_success_at"])
        self.assertEqual(summary["open_items"], 0)
        self.assertNotIn("failing_campaigns", summary)

    def test_attention_is_the_connections_pages_own_count_and_first_note(self):
        """drill-10 Q4: the top bar said 「N 個活動讀取異常」 while the page it links to said
        「✓ 正常」. The count and the note are now that page's own."""
        self._campaign(native_id="c1")
        page = connections.get_connections(self.conn, self.org, self.brand)
        first = next(s for s in page["sources"] if s["state"] not in {"ok", "unsupported"})
        self.assertEqual(self.summary()["attention"],
                         {"count": page["attention_count"], "note": first["note"]})

    def test_attention_note_is_the_first_counted_source_in_page_order(self):
        page = {"attention_count": 2, "sources": [
            {"state": "ok", "note": "每天的資料都有讀到"},
            {"state": "failed", "note": "Meta 暫時讀不到；10/01 讀不到"},
            {"state": "never", "note": "還沒有匯入訂單"},
            {"state": "unsupported", "note": "尚未支援，接上後開放"},
        ]}
        with patch.object(connections, "get_connections", return_value=page):
            self.assertEqual(self.summary()["attention"],
                             {"count": 2, "note": "Meta 暫時讀不到；10/01 讀不到"})
        clean = {"attention_count": 0, "sources": [{"state": "ok", "note": "x"}]}
        with patch.object(connections, "get_connections", return_value=clean):
            self.assertEqual(self.summary()["attention"], {"count": 0, "note": None})

    def test_a_draft_never_on_a_platform_is_never_counted(self):
        before = self.summary()["attention"]
        repository.create_campaign(
            self.conn, self.org, self.brand,
            {"name": "草稿活動", "goal_text": "目標", "objective": "購買"},
        )
        self.conn.commit()
        self.assertEqual(self.summary()["attention"], before)

    def test_ok_campaign_contributes_last_success_at(self):
        campaign_id = self._campaign(native_id="c1")
        external.record_sync(
            self.conn, self.org, self.brand, campaign_id, section="observations",
            state={"status": "success", "last_success_at": db.now_utc().isoformat(),
                   "coverage": {"start": "2026-08-01", "end": "2026-08-30"}},
        )
        self.conn.commit()
        self.assertIsNotNone(self.summary()["last_success_at"])

    def test_auth_expired_campaign_gives_no_last_success(self):
        campaign_id = self._campaign(native_id="c1")
        external.record_sync(
            self.conn, self.org, self.brand, campaign_id, section="observations",
            state={"status": "error", "error": "沒有讀取權限", "error_code": "permission_denied"},
        )
        self.conn.commit()
        self.assertIsNone(self.summary()["last_success_at"])

    def test_newest_ok_last_success_at_wins_across_campaigns(self):
        older = self._campaign(native_id="c1", name="舊的")
        newer = self._campaign(native_id="c2", name="新的")
        external.record_sync(
            self.conn, self.org, self.brand, older, section="observations",
            state={"status": "success", "last_success_at": "2026-01-01T00:00:00+00:00",
                   "coverage": {"start": "2025-12-01", "end": "2025-12-30"}},
        )
        external.record_sync(
            self.conn, self.org, self.brand, newer, section="observations",
            state={"status": "success", "last_success_at": "2026-06-01T00:00:00+00:00",
                   "coverage": {"start": "2026-05-01", "end": "2026-05-30"}},
        )
        self.conn.commit()
        self.assertEqual(self.summary()["last_success_at"], "2026-06-01T00:00:00+00:00")

    def test_closed_campaign_is_excluded_from_last_success(self):
        campaign_id = self._campaign(native_id="c1")
        external.record_sync(
            self.conn, self.org, self.brand, campaign_id, section="observations",
            state={"status": "success", "last_success_at": "2026-06-01T00:00:00+00:00",
                   "coverage": {"start": "2026-05-01", "end": "2026-05-30"}},
        )
        self.conn.execute(
            "UPDATE ads_campaign SET status='closed' WHERE id=%s", (campaign_id,),
        )
        self.conn.commit()
        summary = self.summary()
        self.assertIsNone(summary["last_success_at"])
        self.assertEqual(summary["open_items"], 0)

    def test_open_interrupt_without_a_live_queue_row_is_not_counted(self):
        """F47 Contract D: `open_items` reads the brand queue, not open interrupts on their own -- a
        stale open row (no live candidate) and a non-queue category never count."""
        self.conn.commit()
        interrupts.enqueue(
            self.conn, org_id=self.org, brand_id=self.brand, category="ads_triage_stop_loss",
            dedupe_key="status-summary-test:stop_loss:1", message="廣告「測試」停損，待決定",
        )
        interrupts.enqueue(
            self.conn, org_id=self.org, brand_id=self.brand, category="ads_review_ready",
            dedupe_key="status-summary-test:review_ready:1", message="廣告檢討已備妥",
        )
        self.conn.commit()
        self.assertEqual(self.summary()["open_items"], 0)

    def test_open_items_ignores_done_rows_and_counts_what_the_home_board_counts(self):
        """drill-10 Q2: a deferred row is done, so the top bar no longer says 「1 項待處理」 while
        the home says 「今天沒有要決定的事」. Only the home board's kinds count."""
        rows = [
            {"kind_key": "cleanup", "done": True},
            {"kind_key": "cleanup", "done": False},
            {"kind_key": "worse", "done": False},
            {"kind_key": "refresh_creative", "done": False},
            {"kind_key": "settle", "done": False},
            {"kind_key": "scale_budget", "done": False},
            {"kind_key": "insufficient_data", "done": False},
        ]
        with patch.object(triage, "get_queue", return_value={"items": rows}):
            self.assertEqual(self.summary()["open_items"], 4)


class CampaignObjectiveFamilyCardTest(unittest.TestCase):
    """F27-I09 Done #7: `repository.list_campaigns()`'s own cards carry `campaign_objective` --
    the triage-item side of the same Done item is falsified in `test_ads_triage.py`."""

    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="F27-I09 campaign_objective 卡片測試", actor="test",
            client_name=None,
        )["id"]

    def _card(self, campaign_id):
        cards = repository.list_campaigns(self.conn, self.org, self.brand)
        return next(card for card in cards if card["id"] == campaign_id)

    def test_internal_objective_family_mapping(self):
        self.assertEqual(repository.objective_family("購買"), "sales")
        self.assertEqual(repository.objective_family("加購物車"), "sales")
        self.assertEqual(repository.objective_family("流量"), "traffic")
        self.assertEqual(repository.objective_family("名單"), "other")
        self.assertEqual(repository.objective_family("知名度"), "other")
        self.assertEqual(repository.objective_family(None), "other")

    def test_internal_campaign_card_carries_sales_family(self):
        campaign = repository.create_campaign(
            self.conn, self.org, self.brand,
            {"name": "內部購買活動", "goal_text": "目標", "objective": "購買"},
        )
        self.conn.commit()
        self.assertEqual(self._card(campaign["id"])["campaign_objective"], "sales")

    def test_imported_campaign_card_routes_through_meta_adapter(self):
        campaign_id = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="匯入銷售活動",
        )["id"]
        external.upsert_entity(
            self.conn, self.org, self.brand, campaign_id,
            {"platform": "meta", "source_account": "act_1", "native_kind": "campaign",
             "native_id": "c1", "objective": "OUTCOME_SALES"},
        )
        self.conn.commit()
        self.assertEqual(self._card(campaign_id)["campaign_objective"], "sales")

    def test_imported_campaign_with_no_root_entity_yet_reads_other(self):
        campaign_id = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="還沒同步的匯入活動",
        )["id"]
        self.conn.commit()
        self.assertEqual(self._card(campaign_id)["campaign_objective"], "other")


if __name__ == "__main__":
    unittest.main()
