"""app/tests/test_ads_triage_queue.py — F18-I03 falsifiers: the brand decision queue over
program triage, through the existing `interrupts` inbox.

Two fixture styles:
- `QueueEndToEndTest` proves the real wiring (classify -> enqueue -> message/action_url/category)
  through the actual `triage.classify()` pipeline (same fixture shape as test_ads_triage.py),
  plus the non-closed / has-imported-ads campaign scoping.
- `QueuePlumbingTest` proves the queue orchestration itself (dedupe/resolve/window-move/stale
  filtering, counts) against `triage._classify_brand` patched to fixed items -- classify()'s own
  class/reason-code logic is already exhaustively covered by test_ads_triage.py, not re-proven
  here.
"""

import unittest
from datetime import date, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.ads import channels, repository, tracked_zero, triage
from app.ads import external_repository as external
from app.brand_intelligence import repository as brands
from app.core import db
from app.core import interrupts as core_interrupts

ACCOUNT_TZ = "Asia/Taipei"


class _Reader:
    def accounts(self, conn, org, brand):
        return [{"account_id": "act_1", "currency": "TWD", "name": "來源",
                  "timezone_name": ACCOUNT_TZ}]


class QueueEndToEndTest(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="決定佇列端到端測試", actor="test", client_name=None,
        )["id"]
        patcher = patch.object(channels, "external_reader", return_value=_Reader())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="活動一",
        )["id"]
        external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "campaign",
             "native_id": "c1"},
        )
        self.ad_stop = external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "ad",
             "native_id": "ad_stop",
             "name": "超長廣告名稱測試截斷用途一定超過二十個全形字這裡還沒完",
             "parent_native_kind": "campaign", "parent_native_id": "c1"},
        )
        self.ad_worse = external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "ad",
             "native_id": "ad_worse", "name": "廣告變差用",
             "parent_native_kind": "campaign", "parent_native_id": "c1"},
        )
        self.cutoff = (
            db.now_utc().astimezone(ZoneInfo(ACCOUNT_TZ)) - timedelta(days=1)
        ).date()
        external.record_sync(
            self.conn, self.org, self.brand, self.campaign, section="observations",
            state={
                "last_success_at": db.now_utc().isoformat(),
                "coverage": {"start": (self.cutoff - timedelta(days=90)).isoformat(),
                             "end": self.cutoff.isoformat()},
            },
        )
        repository.save_campaign_target(
            self.conn, self.org, self.brand, self.campaign,
            result_kind="purchase", basis="own", value=100, expected_revision=0, actor="測試員",
        )
        self.conn.commit()

        # ad_stop: known zero, spend over 3x target -- fires stop_loss.
        self.obs(self.ad_stop["id"], self.cutoff - timedelta(days=10), spend=50, result_count=5,
                 attribution_key="demo")
        for offset in range(7):
            self.obs(self.ad_stop["id"], self.cutoff - timedelta(days=offset), spend=50,
                      result_count=None, attribution_key=f"stop{offset}")
        tracked_zero.apply(
            self.conn, self.org, self.brand, self.campaign,
            self.cutoff - timedelta(days=6), self.cutoff, self.cutoff,
        )
        # ad_worse: cost_per_result rises past the flat band (10 -> 15, +50%).
        for offset in range(7):
            self.obs(self.ad_worse["id"], self.cutoff - timedelta(days=7 + offset), spend=100,
                      result_count=10, attribution_key=f"prevworse{offset}")
        for offset in range(7):
            self.obs(self.ad_worse["id"], self.cutoff - timedelta(days=offset), spend=150,
                      result_count=10, attribution_key=f"curworse{offset}")

    def obs(self, ad_id, day, *, spend, result_count, attribution_key):
        external.upsert_observation(
            self.conn, self.org, self.brand, self.campaign,
            {"entity_id": ad_id, "day": day, "metric_scope": "ad",
             "attribution_key": attribution_key, "currency": "TWD", "source": "meta",
             "spend": spend, "impressions": 1000, "purchases": None},
            result_kind="purchase", result_count=result_count, result_action="omni_purchase",
            result_attribution="7d_click+1d_view",
        )
        self.conn.commit()

    def test_refresh_enqueues_stop_loss_and_worse_with_message_and_action_url(self):
        result = triage.refresh_queue(self.conn, self.org, self.brand)
        by_category = {row["category"]: row for row in result["items"]}

        stop_row = by_category["ads_triage_stop_loss"]
        self.assertEqual(stop_row["severity"], "money_loss")
        self.assertLessEqual(len(stop_row["message"]), core_interrupts.MAX_MESSAGE_LEN)
        self.assertIn("…", stop_row["message"])  # long name truncated
        self.assertNotIn("Meta", stop_row["message"])
        self.assertNotIn("meta", stop_row["message"])
        self.assertEqual(
            stop_row["action_url"],
            f"/brands/{self.brand}/ads/campaigns/{self.campaign}?tab=performance",
        )
        # F19-I01: each queue row carries the current triage item that produced it (matched by
        # the same dedupe key the enqueue used), never null while it's still the live classification.
        self.assertEqual(stop_row["triage"]["class"], "stop_loss")
        self.assertEqual(stop_row["triage"]["entity_id"], self.ad_stop["id"])

        worse_row = by_category["ads_triage_worse"]
        self.assertEqual(worse_row["severity"], "rule_warning")
        self.assertIn("廣告變差用", worse_row["message"])
        self.assertLessEqual(len(worse_row["message"]), core_interrupts.MAX_MESSAGE_LEN)
        self.assertEqual(worse_row["triage"]["class"], "worse")
        self.assertEqual(worse_row["triage"]["entity_id"], self.ad_worse["id"])

        self.assertEqual(result["kinds_available"], ["stop_loss", "worse"])
        self.assertEqual(result["kinds_pending"], ["scale_budget", "refresh_creative"])
        self.assertEqual(result["counts"]["stop_loss"], 1)
        self.assertEqual(result["counts"]["worse"], 1)
        self.assertEqual(result["total_ads"], 2)

    def test_get_queue_matches_refresh_queue_without_writing(self):
        triage.refresh_queue(self.conn, self.org, self.brand)
        before = [dict(r) for r in self.conn.execute("SELECT * FROM interrupt ORDER BY id")]
        queue = triage.get_queue(self.conn, self.org, self.brand)
        after = [dict(r) for r in self.conn.execute("SELECT * FROM interrupt ORDER BY id")]
        self.assertEqual(before, after)
        self.assertEqual({row["category"] for row in queue["items"]},
                         {"ads_triage_stop_loss", "ads_triage_worse"})

    def test_closed_campaign_and_ad_less_campaign_contribute_nothing(self):
        closed_campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="已結案活動",
        )["id"]
        external.upsert_entity(
            self.conn, self.org, self.brand, closed_campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "campaign",
             "native_id": "c2"},
        )
        ad2 = external.upsert_entity(
            self.conn, self.org, self.brand, closed_campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "ad",
             "native_id": "ad2", "name": "已結案廣告",
             "parent_native_kind": "campaign", "parent_native_id": "c2"},
        )
        external.record_sync(
            self.conn, self.org, self.brand, closed_campaign, section="observations",
            state={
                "last_success_at": db.now_utc().isoformat(),
                "coverage": {"start": (self.cutoff - timedelta(days=90)).isoformat(),
                             "end": self.cutoff.isoformat()},
            },
        )
        repository.save_campaign_target(
            self.conn, self.org, self.brand, closed_campaign,
            result_kind="purchase", basis="own", value=100, expected_revision=0, actor="測試員",
        )
        for offset in range(7):
            external.upsert_observation(
                self.conn, self.org, self.brand, closed_campaign,
                {"entity_id": ad2["id"], "day": self.cutoff - timedelta(days=offset),
                 "metric_scope": "ad", "attribution_key": f"closed{offset}", "currency": "TWD",
                 "source": "meta", "spend": 50, "impressions": 1000, "purchases": None},
                result_kind="purchase", result_count=None, result_action="omni_purchase",
                result_attribution="7d_click+1d_view",
            )
        self.conn.commit()
        tracked_zero.apply(
            self.conn, self.org, self.brand, closed_campaign,
            self.cutoff - timedelta(days=6), self.cutoff, self.cutoff,
        )
        # Imported campaigns don't go through `repository.set_campaign_status` (internal-only,
        # `require_internal_campaign` rejects `origin='imported'`) -- direct fixture update, same
        # column the real Meta sync writes on campaign close.
        self.conn.execute(
            "UPDATE ads_campaign SET status='closed' WHERE id=%s", (closed_campaign,),
        )
        # third campaign: imported but no ad entities at all.
        external.create_imported_campaign(self.conn, self.org, self.brand, name="空活動")
        self.conn.commit()

        result = triage.refresh_queue(self.conn, self.org, self.brand)
        self.assertEqual(result["total_ads"], 2)  # only the two ads from the first campaign
        self.assertEqual(
            {row["category"] for row in result["items"]},
            {"ads_triage_stop_loss", "ads_triage_worse"},
        )


class QueuePlumbingTest(unittest.TestCase):
    """`triage._classify_brand` patched to fixed items -- isolates the queue orchestration
    (dedupe/resolve/window-move/stale filtering/counts) from `classify()`'s own logic."""

    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="決定佇列機制測試", actor="test", client_name=None,
        )["id"]

    @staticmethod
    def _item(cls, *, entity_id="ent_1", campaign_id="camp_1", window_end, name="廣告A"):
        return {
            "entity_id": entity_id, "native_id": "n1", "name": name, "campaign_id": campaign_id,
            "class": cls, "label": triage.LABELS[cls], "reason_code": "x",
            "window": {"start": window_end - timedelta(days=6), "end": window_end, "days": 7,
                       "previous_start": None, "previous_end": None, "extended_from": None},
            "target": {"value": 1}, "current": {}, "previous": {}, "change_pct": None,
            "sample": {},
        }

    def test_categories_registered_with_expected_severity_and_label(self):
        self.assertEqual(
            core_interrupts.CATEGORIES["ads_triage_stop_loss"],
            {"severity": "money_loss", "label": "廣告停損待決定"},
        )
        self.assertEqual(
            core_interrupts.CATEGORIES["ads_triage_worse"],
            {"severity": "rule_warning", "label": "廣告變差待決定"},
        )

    def test_refresh_is_idempotent_within_the_same_window(self):
        window_end = date(2026, 1, 7)
        items = [self._item("stop_loss", window_end=window_end)]
        with patch.object(triage, "_classify_brand", return_value=items):
            triage.refresh_queue(self.conn, self.org, self.brand)
            result = triage.refresh_queue(self.conn, self.org, self.brand)
        self.assertEqual(len(result["items"]), 1)
        rows = self.conn.execute(
            "SELECT COUNT(*) c FROM interrupt WHERE brand_id=%s"
            " AND category='ads_triage_stop_loss'",
            (self.brand,),
        ).fetchone()
        self.assertEqual(rows["c"], 1)

    def test_resolved_item_stays_resolved_until_window_moves(self):
        window_end = date(2026, 1, 7)
        items = [self._item("worse", window_end=window_end)]
        with patch.object(triage, "_classify_brand", return_value=items):
            first = triage.refresh_queue(self.conn, self.org, self.brand)
            interrupt_id = first["items"][0]["id"]
            core_interrupts.resolve(self.conn, interrupt_id, actor="測試員", org_id=self.org)
            second = triage.refresh_queue(self.conn, self.org, self.brand)
        self.assertEqual(second["items"], [])  # stays resolved, not reopened, not duplicated
        row = self.conn.execute(
            "SELECT status FROM interrupt WHERE id=%s", (interrupt_id,)
        ).fetchone()
        self.assertEqual(row["status"], "resolved")

    def test_new_window_end_raises_a_new_item_after_the_old_one_is_resolved(self):
        w1, w2 = date(2026, 1, 7), date(2026, 1, 8)
        item_w1 = self._item("stop_loss", window_end=w1)
        with patch.object(triage, "_classify_brand", return_value=[item_w1]):
            first = triage.refresh_queue(self.conn, self.org, self.brand)
        old_id = first["items"][0]["id"]
        core_interrupts.resolve(self.conn, old_id, actor="測試員", org_id=self.org)

        item_w2 = self._item("stop_loss", window_end=w2)
        with patch.object(triage, "_classify_brand", return_value=[item_w2]):
            second = triage.refresh_queue(self.conn, self.org, self.brand)

        self.assertEqual(len(second["items"]), 1)
        self.assertNotEqual(second["items"][0]["id"], old_id)
        old_row = self.conn.execute(
            "SELECT status FROM interrupt WHERE id=%s", (old_id,)
        ).fetchone()
        self.assertEqual(old_row["status"], "resolved")  # untouched by the new window's refresh

    def test_get_queue_marks_a_stale_open_row_with_null_triage_when_classification_moves_on(self):
        w1 = date(2026, 1, 7)
        stop_loss_item = self._item("stop_loss", window_end=w1)
        with patch.object(triage, "_classify_brand", return_value=[stop_loss_item]):
            triage.refresh_queue(self.conn, self.org, self.brand)

        # Same ad, same window_end, but a later refresh's classification has moved off stop_loss
        # (e.g. now flat) -- GET never writes, so the old open row still shows (F19-I01: no
        # longer hidden), but its `triage` is null: no CURRENT item produced this dedupe key.
        flat_item = self._item("flat", window_end=w1)
        with patch.object(triage, "_classify_brand", return_value=[flat_item]):
            queue = triage.get_queue(self.conn, self.org, self.brand)

        self.assertEqual(len(queue["items"]), 1)
        self.assertIsNone(queue["items"][0]["triage"])
        row = self.conn.execute(
            "SELECT status FROM interrupt WHERE brand_id=%s AND category='ads_triage_stop_loss'",
            (self.brand,),
        ).fetchone()
        # GET never writes -- the row is only actually superseded by the NEXT refresh_queue()
        # call (see test_refresh_closes_open_row_when_ad_recovers_to_flat below).
        self.assertEqual(row["status"], "open")

    def test_get_queue_attaches_the_matching_triage_item_by_dedupe_key(self):
        window_end = date(2026, 1, 7)
        item = self._item("worse", window_end=window_end)
        with patch.object(triage, "_classify_brand", return_value=[item]):
            triage.refresh_queue(self.conn, self.org, self.brand)  # raises the open row
            queue = triage.get_queue(self.conn, self.org, self.brand)
        self.assertEqual(len(queue["items"]), 1)
        self.assertEqual(queue["items"][0]["triage"], item)

    def _stop_loss_at(self, window_end):
        return patch.object(triage, "_classify_brand",
                             return_value=[self._item("stop_loss", window_end=window_end)])

    def test_refresh_supersedes_older_open_rows_when_window_advances_while_still_stop_loss(self):
        """Lead review arbitration: the cutoff advances daily, so an ad that stays in stop_loss
        gets a new dedupe key (new window_end) on every refresh -- without supersede this would
        pile up one open money_loss row per day for the same ad. After three refreshes across
        three window ends, exactly one open row survives; the older two are resolved by the
        "system" actor, not archived and not deleted."""
        w1, w2, w3 = date(2026, 1, 7), date(2026, 1, 8), date(2026, 1, 9)
        with self._stop_loss_at(w1):
            first = triage.refresh_queue(self.conn, self.org, self.brand)
        with self._stop_loss_at(w2):
            second = triage.refresh_queue(self.conn, self.org, self.brand)
        with self._stop_loss_at(w3):
            third = triage.refresh_queue(self.conn, self.org, self.brand)

        self.assertEqual(len(third["items"]), 1)
        rows = self.conn.execute(
            "SELECT id, status FROM interrupt WHERE brand_id=%s"
            " AND category='ads_triage_stop_loss' ORDER BY created_at",
            (self.brand,),
        ).fetchall()
        self.assertEqual(len(rows), 3)  # nothing deleted -- three distinct windows, three rows
        statuses = {row["id"]: row["status"] for row in rows}
        first_id, second_id, third_id = (
            first["items"][0]["id"], second["items"][0]["id"], third["items"][0]["id"],
        )
        self.assertEqual(statuses[first_id], "resolved")
        self.assertEqual(statuses[second_id], "resolved")
        self.assertEqual(statuses[third_id], "open")

        audit_rows = self.conn.execute(
            "SELECT actor FROM audit_log WHERE entity_type='interrupt' AND entity_id IN (%s,%s)",
            (first_id, second_id),
        ).fetchall()
        self.assertEqual({row["actor"] for row in audit_rows}, {"system"})

    def test_refresh_closes_open_row_when_ad_recovers_to_flat(self):
        w1 = date(2026, 1, 7)
        with self._stop_loss_at(w1):
            first = triage.refresh_queue(self.conn, self.org, self.brand)
        old_id = first["items"][0]["id"]

        flat_item = self._item("flat", window_end=w1)
        with patch.object(triage, "_classify_brand", return_value=[flat_item]):
            second = triage.refresh_queue(self.conn, self.org, self.brand)

        self.assertEqual(second["items"], [])
        row = self.conn.execute(
            "SELECT status FROM interrupt WHERE id=%s", (old_id,)
        ).fetchone()
        self.assertEqual(row["status"], "resolved")

    def test_supersede_never_touches_other_categories_or_other_brands(self):
        other_brand = brands.create_brand(
            self.conn, org_id=self.org, name="別的品牌測試", actor="test", client_name=None,
        )["id"]
        core_interrupts.enqueue(
            self.conn, org_id=self.org, brand_id=self.brand, category="ads_runtime_attention",
            dedupe_key="unrelated-1", message="測試訊息，不受影響。",
        )
        self.conn.commit()

        w1, w2 = date(2026, 1, 7), date(2026, 1, 8)
        with self._stop_loss_at(w1):
            triage.refresh_queue(self.conn, self.org, self.brand)
            triage.refresh_queue(self.conn, self.org, other_brand)
        # Only THIS brand advances to a new window -- other_brand's row must stay untouched.
        with self._stop_loss_at(w2):
            triage.refresh_queue(self.conn, self.org, self.brand)

        other_brand_row = self.conn.execute(
            "SELECT status FROM interrupt WHERE brand_id=%s AND category='ads_triage_stop_loss'",
            (other_brand,),
        ).fetchone()
        self.assertEqual(other_brand_row["status"], "open")

        unrelated_row = self.conn.execute(
            "SELECT status FROM interrupt WHERE dedupe_key='unrelated-1'"
        ).fetchone()
        self.assertEqual(unrelated_row["status"], "open")

    def test_get_queue_does_not_write(self):
        with patch.object(triage, "_classify_brand", return_value=[]):
            before = [dict(r) for r in self.conn.execute("SELECT * FROM interrupt ORDER BY id")]
            triage.get_queue(self.conn, self.org, self.brand)
            after = [dict(r) for r in self.conn.execute("SELECT * FROM interrupt ORDER BY id")]
        self.assertEqual(before, after)

    def test_counts_tally_over_all_six_classes_and_total_ads(self):
        window_end = date(2026, 1, 7)
        items = [
            self._item("stop_loss", entity_id="e1", window_end=window_end),
            self._item("worse", entity_id="e2", window_end=window_end),
            self._item("worse", entity_id="e3", window_end=window_end),
            self._item("better", entity_id="e4", window_end=window_end),
            self._item("flat", entity_id="e5", window_end=window_end),
            self._item("insufficient", entity_id="e6", window_end=window_end),
            self._item("no_target", entity_id="e7", window_end=window_end),
        ]
        with patch.object(triage, "_classify_brand", return_value=items):
            queue = triage.get_queue(self.conn, self.org, self.brand)
        self.assertEqual(queue["counts"], {
            "stop_loss": 1, "worse": 2, "better": 1, "flat": 1, "insufficient": 1, "no_target": 1,
        })
        self.assertEqual(queue["total_ads"], 7)

    def test_kinds_available_and_pending_present_even_with_no_data(self):
        with patch.object(triage, "_classify_brand", return_value=[]):
            queue = triage.get_queue(self.conn, self.org, self.brand)
        self.assertEqual(queue["items"], [])
        self.assertEqual(queue["total_ads"], 0)
        self.assertEqual(queue["kinds_available"], ["stop_loss", "worse"])
        self.assertEqual(queue["kinds_pending"], ["scale_budget", "refresh_creative"])
        self.assertEqual(queue["counts"], dict.fromkeys(triage.ALL_CLASSES, 0))


if __name__ == "__main__":
    unittest.main()
