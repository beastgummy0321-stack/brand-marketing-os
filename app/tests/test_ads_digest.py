"""app/tests/test_ads_digest.py — F29-I08 Contract J falsifiers for the daily digest
(`app/ads/digest.py`): built from the queue payload the 06:30 refresh just produced, delivered into
the in-app inbox only (`SENDERS = {"inbox": ...}`), one row per brand per day, never counted as a
home decision.

Fixture: one brand with a live imported campaign whose queue carries only the brand-level settle
row (per-ad classification is stubbed empty, the settle candidate is a real-shaped Contract E row),
and a second brand with nothing open.
"""

import unittest
from datetime import date
from unittest.mock import patch

from app.ads import digest, jobs, settle, status_summary, triage
from app.ads import external_repository as external
from app.brand_intelligence import repository as brands
from app.core import db, interrupts


def _settle_candidate(brand_id):
    return {
        "kind": "settle", "identity_id": brand_id,
        "window_start": date(2026, 8, 1), "window_end": date(2026, 8, 31),
        "message": "結算上一期（8 月），待寫進筆記本",
        "action_url": f"/brands/{brand_id}/ads/settle/2026-08/result",
        "payload": {"triage": None, "settle": {
            "month": "2026-08", "start": "2026-08-01", "end": "2026-08-31",
            "campaign_count": 1, "imported_count": 1, "learnable_count": 2, "buckets": [],
        }},
    }


class DigestTest(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = self._brand("每日摘要（有待辦）")
        self.quiet = self._brand("每日摘要（沒有待辦）")
        patch.object(triage, "_classify_brand", return_value=[]).start()
        patch.object(settle, "queue_candidate", side_effect=self._candidate).start()
        self.addCleanup(patch.stopall)

    def _brand(self, name):
        brand = brands.create_brand(
            self.conn, org_id=self.org, name=name, actor="test", client_name=None,
        )["id"]
        external.create_imported_campaign(self.conn, self.org, brand, name="投放中活動")
        self.conn.commit()
        return brand

    def _candidate(self, conn, org_id, brand_id):
        return _settle_candidate(brand_id) if brand_id == self.brand else None

    def digest_rows(self, brand_id, status=None):
        sql = "SELECT * FROM interrupt WHERE brand_id=%s AND category=%s"
        params = [brand_id, digest.CATEGORY]
        if status:
            sql += " AND status=%s"
            params.append(status)
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def run_daily(self):
        jobs._dispatch_queue_refresh(int(db.now_utc().timestamp()))

    def test_senders_hold_the_inbox_only(self):
        self.assertEqual(list(digest.SENDERS), ["inbox"])
        self.assertIs(digest.SENDERS["inbox"], digest.send_inbox)

    def test_nothing_open_writes_no_row(self):
        self.run_daily()
        self.assertEqual(self.digest_rows(self.quiet), [])
        self.assertIsNone(digest.build(self.conn, self.org, self.quiet, date(2026, 9, 25)))

    def test_settle_row_is_included_and_the_inbox_row_opens_the_ads_home(self):
        self.run_daily()
        [row] = self.digest_rows(self.brand)
        self.assertEqual(row["status"], "open")
        self.assertEqual(row["severity"], "informational")
        self.assertEqual(row["action_url"], f"/brands/{self.brand}/ads")
        today = db.now_utc().date()
        self.assertTrue(row["dedupe_key"].startswith(f"ads-digest:{self.brand}:"))
        self.assertIn("1 件待處理", row["message"])

        built = digest.build(self.conn, self.org, self.brand, today)
        self.assertEqual(built["open_count"], 1)
        self.assertEqual(built["items"], [{
            "kind": "settle", "message": "結算上一期（8 月），待寫進筆記本",
            "action_url": f"/brands/{self.brand}/ads/settle/2026-08/result",
        }])

    def test_digest_row_never_counts_as_a_home_decision(self):
        self.run_daily()
        self.assertEqual(len(self.digest_rows(self.brand)), 1)
        queue = triage.get_queue(self.conn, self.org, self.brand)
        self.assertEqual([row["kind_key"] for row in queue["items"]], ["settle"])
        self.assertNotIn(digest.CATEGORY, triage.QUEUE_CATEGORY.values())
        summary = status_summary.get_status_summary(self.conn, self.org, self.brand)
        self.assertEqual(summary["open_items"], 1)

    def test_same_day_twice_leaves_one_row(self):
        self.run_daily()
        self.run_daily()
        self.assertEqual(len(self.digest_rows(self.brand)), 1)

    def test_a_new_day_replaces_the_earlier_open_digest(self):
        triage.refresh_queue(self.conn, self.org, self.brand)
        digest.deliver(self.conn, self.org, self.brand, date(2026, 9, 24))
        digest.deliver(self.conn, self.org, self.brand, date(2026, 9, 25))
        [open_row] = self.digest_rows(self.brand, status="open")
        self.assertEqual(open_row["dedupe_key"], f"ads-digest:{self.brand}:2026-09-25")
        self.assertEqual(len(self.digest_rows(self.brand, status="resolved")), 1)

    def test_a_day_with_nothing_open_closes_the_earlier_digest_and_sends_none(self):
        triage.refresh_queue(self.conn, self.org, self.brand)
        digest.deliver(self.conn, self.org, self.brand, date(2026, 9, 24))
        self.assertEqual(len(self.digest_rows(self.brand, status="open")), 1)
        sent = digest.deliver(self.conn, self.org, self.brand, date(2026, 9, 25),
                              queue={"items": []})
        self.assertIsNone(sent)
        self.assertEqual(self.digest_rows(self.brand, status="open"), [])
        [closed] = self.digest_rows(self.brand, status="resolved")
        self.assertEqual(closed["dedupe_key"], f"ads-digest:{self.brand}:2026-09-24")

    def test_a_brand_whose_refresh_raised_gets_no_digest_and_others_still_do(self):
        real_refresh = triage.refresh_queue
        other = self._brand("每日摘要（刷新失敗）")

        def refresh(conn, org_id, brand_id):
            if brand_id == other:
                raise RuntimeError("refresh failed")
            return real_refresh(conn, org_id, brand_id)

        with patch.object(settle, "queue_candidate",
                          side_effect=lambda c, o, b: _settle_candidate(b)
                          if b in (self.brand, other) else None), \
                patch.object(triage, "refresh_queue", side_effect=refresh):
            self.run_daily()
        self.assertEqual(self.digest_rows(other), [])
        self.assertEqual(len(self.digest_rows(self.brand)), 1)


class DigestShapeTest(unittest.TestCase):
    def rows(self, n, name="很長很長很長很長很長很長很長很長很長很長的活動名稱"):
        return {"items": [
            {"kind_key": "cleanup", "message": f"「{name}{i}」花錢沒效，待決定",
             "action_url": f"/brands/b/ads/campaigns/c{i}/detail"}
            for i in range(n)
        ]}

    def test_at_most_five_items_and_the_full_open_count(self):
        built = digest.build(None, "org", "b", date(2026, 9, 25), queue=self.rows(7))
        self.assertEqual(built["date"], "2026-09-25")
        self.assertEqual(built["open_count"], 7)
        self.assertEqual(len(built["items"]), 5)
        self.assertEqual(built["items"][0]["kind"], "cleanup")

    def test_inbox_message_stays_within_the_inbox_limit(self):
        long_digest = digest.build(None, "org", "b", date(2026, 9, 25), queue=self.rows(12))
        message = digest.inbox_message(long_digest)
        self.assertLessEqual(len(message), interrupts.MAX_MESSAGE_LEN)
        self.assertEqual(message, "投放今日 12 件待處理")

        short_digest = digest.build(None, "org", "b", date(2026, 9, 25),
                                    queue=self.rows(1, name="夏季"))
        message = digest.inbox_message(short_digest)
        self.assertLessEqual(len(message), interrupts.MAX_MESSAGE_LEN)
        self.assertEqual(message, "投放今日 1 件待處理：「夏季0」花錢沒效，待決定")
