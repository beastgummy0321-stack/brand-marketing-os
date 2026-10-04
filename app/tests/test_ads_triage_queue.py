"""app/tests/test_ads_triage_queue.py — F18-I03 falsifiers: the brand decision queue over
program triage, through the existing `interrupts` inbox.

Three fixture styles:
- `QueueEndToEndTest` proves the real wiring (classify -> enqueue -> message/action_url/category)
  through the actual `triage.classify()` pipeline (same fixture shape as test_ads_triage.py),
  plus the non-closed / has-imported-ads campaign scoping.
- `QueuePlumbingTest` proves the queue orchestration itself (dedupe/resolve/window-move/stale
  filtering, counts) against `triage._classify_brand` patched to fixed items -- classify()'s own
  class/reason-code logic is already exhaustively covered by test_ads_triage.py, not re-proven
  here.
F28-I02 retired the `stop_loss` row (and with it F22-I01's pause-proposal tests): a 沒賣出 ad closes
through its campaign's `cleanup` row, proven end to end on the real-shaped fixture in
`GradedCleanupEndToEndTest`.
"""

import unittest
from datetime import date, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.ads import channels, queue_done, repository, tracked_zero, triage
from app.ads import external_repository as external
from app.brand_intelligence import repository as brands
from app.core import db
from app.core import interrupts as core_interrupts

ACCOUNT_TZ = "Asia/Taipei"

# F29-I03: the `settle` row depends on the calendar (it reads last month from the 2nd day of this
# one), so fixtures dated "N days before yesterday" would raise it during the first days of every
# month. This file proves the per-ad/per-campaign kinds; the settle row is proven on a fixed month
# in `test_ads_settle.py`.
_settle_patch = patch.object(triage, "_settle_candidates", return_value=[])


def setUpModule():
    _settle_patch.start()


def tearDownModule():
    _settle_patch.stop()


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
        # ad_worse: F29-I01 -- its grade moves from 划算 (80 a purchase, cap 100) to 太貴 (150 a
        # purchase, over 1.2 x cap); both windows pass the gate (spend >= 3 x cap).
        for offset in range(7):
            self.obs(self.ad_worse["id"], self.cutoff - timedelta(days=7 + offset), spend=80,
                      result_count=1, attribution_key=f"prevworse{offset}")
        for offset in range(7):
            self.obs(self.ad_worse["id"], self.cutoff - timedelta(days=offset), spend=150,
                      result_count=1, attribution_key=f"curworse{offset}")

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

    def test_refresh_raises_cleanup_for_the_wasted_ad_and_worse_with_message_and_action_url(self):
        result = triage.refresh_queue(self.conn, self.org, self.brand)
        by_category = {row["category"]: row for row in result["items"]}
        # F28-I02: no stop_loss row any more -- the 沒賣出 ad closes through its campaign's
        # cleanup row, even with no daily budget owner (capacity unknown).
        self.assertEqual(set(by_category), {"ads_triage_cleanup", "ads_triage_worse"})

        cleanup_row = by_category["ads_triage_cleanup"]
        self.assertLessEqual(len(cleanup_row["message"]), core_interrupts.MAX_MESSAGE_LEN)
        self.assertEqual(cleanup_row["message"], "「活動一」花錢沒效，待決定")
        self.assertNotIn("meta", cleanup_row["message"].lower())
        self.assertEqual(
            cleanup_row["action_url"],
            f"/brands/{self.brand}/ads/campaigns/{self.campaign}/propose/cleanup/{self.campaign}",
        )
        cleanup = cleanup_row["cleanup"]
        self.assertEqual([ad["entity_id"] for ad in cleanup["ads"]], [self.ad_stop["id"]])
        self.assertEqual(cleanup["ads"][0]["grade"], "wasted")
        self.assertEqual(cleanup["ads"][0]["result_count"], 0)
        self.assertIsNone(cleanup["can_support"])
        self.assertEqual(cleanup["short"], 0)
        self.assertEqual([ad["entity_id"] for ad in cleanup["keep"]], [self.ad_worse["id"]])

        worse_row = by_category["ads_triage_worse"]
        self.assertEqual(worse_row["severity"], "rule_warning")
        self.assertIn("廣告變差用", worse_row["message"])
        self.assertLessEqual(len(worse_row["message"]), core_interrupts.MAX_MESSAGE_LEN)
        self.assertEqual(
            worse_row["action_url"],
            f"/brands/{self.brand}/ads/campaigns/{self.campaign}/detail?ad={self.ad_worse['id']}",
        )
        self.assertEqual(worse_row["triage"]["class"], "worse")
        # F29-I01: the row is raised by the grade move 划算 -> 太貴, never by the trend note.
        self.assertEqual(worse_row["triage"]["grade"], "over")
        self.assertEqual(worse_row["triage"]["previous_grade"], "on_target")
        self.assertEqual(worse_row["triage"]["grade_move"], {"from": "on_target", "to": "over"})
        self.assertEqual(worse_row["triage"]["entity_id"], self.ad_worse["id"])
        self.assertEqual(worse_row["triage"]["campaign_name"], "活動一")

        self.assertEqual(
            result["kinds_available"],
            ["cleanup", "worse", "closeout", "settle", "refresh_creative", "scale_budget",
             "insufficient_data"],
        )
        self.assertEqual(result["kinds_pending"], [])
        # `class` keeps its meaning: the 沒賣出 ad still counts as the stop_loss trend class.
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
                         {"ads_triage_cleanup", "ads_triage_worse"})


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
            {"ads_triage_cleanup", "ads_triage_worse"},
        )
        self.assertEqual(
            {row["cleanup"]["campaign_id"] for row in result["items"] if "cleanup" in row},
            {self.campaign},
        )


class QueuePlumbingTest(unittest.TestCase):
    """`triage._classify_brand` patched to fixed items -- isolates the queue orchestration
    (dedupe/resolve/window-move/stale filtering/counts) from `classify()`'s own logic."""

    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="決定佇列機制測試", actor="test", client_name=None,
        )["id"]

    _WORSE_MOVE = {"from": "on_target", "to": "over"}

    @classmethod
    def _item(cls_, cls, *, entity_id="ent_1", campaign_id="camp_1", window_end, name="廣告A",
              grade_move="auto"):
        # F29-I01: a `worse` row is raised by the grade move 划算 -> 偏貴／太貴 only; by default a
        # "worse" item here carries that move (so the plumbing tests keep raising a row) and every
        # other class carries none.
        if grade_move == "auto":
            grade_move = cls_._WORSE_MOVE if cls == "worse" else None
        return {
            "entity_id": entity_id, "native_id": "n1", "name": name, "campaign_id": campaign_id,
            "grade": grade_move["to"] if grade_move else "on_target",
            "previous_grade": grade_move["from"] if grade_move else None,
            "grade_move": grade_move,
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

    def test_worse_row_follows_the_grade_move_never_the_trend_class(self):
        # F29-I01 (ads.md §6.33): 變貴 = 划算 -> 偏貴／太貴. A trend-"worse" ad with no move, a move
        # between two costly grades, and an improving move raise nothing; a trend-"flat" ad whose
        # grade moved 划算 -> 偏貴 does.
        window_end = date(2026, 1, 7)
        cases = [
            (self._item("worse", entity_id="e1", window_end=window_end, grade_move=None), False),
            (self._item("worse", entity_id="e2", window_end=window_end,
                        grade_move={"from": "watch", "to": "over"}), False),
            (self._item("better", entity_id="e3", window_end=window_end,
                        grade_move={"from": "over", "to": "on_target"}), False),
            (self._item("flat", entity_id="e4", window_end=window_end,
                        grade_move={"from": "on_target", "to": "watch"}), True),
            (self._item("insufficient", entity_id="e5", window_end=window_end,
                        grade_move={"from": "on_target", "to": "over"}), True),
        ]
        with patch.object(triage, "_classify_brand", return_value=[c for c, _ in cases]):
            result = triage.refresh_queue(self.conn, self.org, self.brand)
        raised = {row["triage"]["entity_id"] for row in result["items"]}
        self.assertEqual(raised, {c["entity_id"] for c, expected in cases if expected})

    def test_refresh_is_idempotent_within_the_same_window(self):
        window_end = date(2026, 1, 7)
        items = [self._item("worse", window_end=window_end)]
        with patch.object(triage, "_classify_brand", return_value=items):
            triage.refresh_queue(self.conn, self.org, self.brand)
            result = triage.refresh_queue(self.conn, self.org, self.brand)
        self.assertEqual(len(result["items"]), 1)
        rows = self.conn.execute(
            "SELECT COUNT(*) c FROM interrupt WHERE brand_id=%s"
            " AND category='ads_triage_worse'",
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
        item_w1 = self._item("worse", window_end=w1)
        with patch.object(triage, "_classify_brand", return_value=[item_w1]):
            first = triage.refresh_queue(self.conn, self.org, self.brand)
        old_id = first["items"][0]["id"]
        core_interrupts.resolve(self.conn, old_id, actor="測試員", org_id=self.org)

        item_w2 = self._item("worse", window_end=w2)
        with patch.object(triage, "_classify_brand", return_value=[item_w2]):
            second = triage.refresh_queue(self.conn, self.org, self.brand)

        self.assertEqual(len(second["items"]), 1)
        self.assertNotEqual(second["items"][0]["id"], old_id)
        old_row = self.conn.execute(
            "SELECT status FROM interrupt WHERE id=%s", (old_id,)
        ).fetchone()
        self.assertEqual(old_row["status"], "resolved")  # untouched by the new window's refresh

    def test_get_queue_filters_a_stale_open_row_when_classification_moves_on(self):
        w1 = date(2026, 1, 7)
        worse_item = self._item("worse", window_end=w1)
        with patch.object(triage, "_classify_brand", return_value=[worse_item]):
            triage.refresh_queue(self.conn, self.org, self.brand)

        # Same ad, same window_end, but a later refresh's classification has moved off worse
        # (e.g. now flat) -- the old open row is stale and must not be reported to GET.
        flat_item = self._item("flat", window_end=w1)
        with patch.object(triage, "_classify_brand", return_value=[flat_item]):
            queue = triage.get_queue(self.conn, self.org, self.brand)

        self.assertEqual(queue["items"], [])
        row = self.conn.execute(
            "SELECT status FROM interrupt WHERE brand_id=%s AND category='ads_triage_worse'",
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

    def _worse_at(self, window_end):
        return patch.object(triage, "_classify_brand",
                             return_value=[self._item("worse", window_end=window_end)])

    def test_refresh_supersedes_older_open_rows_when_window_advances_while_still_worse(self):
        """Lead review arbitration: the cutoff advances daily, so an ad that stays in worse
        gets a new dedupe key (new window_end) on every refresh -- without supersede this would
        pile up one open row per day for the same ad. After three refreshes across
        three window ends, exactly one open row survives; the older two are resolved by the
        "system" actor, not archived and not deleted."""
        w1, w2, w3 = date(2026, 1, 7), date(2026, 1, 8), date(2026, 1, 9)
        with self._worse_at(w1):
            first = triage.refresh_queue(self.conn, self.org, self.brand)
        with self._worse_at(w2):
            second = triage.refresh_queue(self.conn, self.org, self.brand)
        with self._worse_at(w3):
            third = triage.refresh_queue(self.conn, self.org, self.brand)

        self.assertEqual(len(third["items"]), 1)
        rows = self.conn.execute(
            "SELECT id, status FROM interrupt WHERE brand_id=%s"
            " AND category='ads_triage_worse' ORDER BY created_at",
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
        with self._worse_at(w1):
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
        with self._worse_at(w1):
            triage.refresh_queue(self.conn, self.org, self.brand)
            triage.refresh_queue(self.conn, self.org, other_brand)
        # Only THIS brand advances to a new window -- other_brand's row must stay untouched.
        with self._worse_at(w2):
            triage.refresh_queue(self.conn, self.org, self.brand)

        other_brand_row = self.conn.execute(
            "SELECT status FROM interrupt WHERE brand_id=%s AND category='ads_triage_worse'",
            (other_brand,),
        ).fetchone()
        self.assertEqual(other_brand_row["status"], "open")

        unrelated_row = self.conn.execute(
            "SELECT status FROM interrupt WHERE dedupe_key='unrelated-1'"
        ).fetchone()
        self.assertEqual(unrelated_row["status"], "open")

    def test_stop_loss_items_no_longer_raise_a_row_and_an_open_one_is_superseded(self):
        """F28-I02: a 白花 ad closes through its campaign's cleanup row. A `stop_loss` row still
        open from before is resolved by the existing supersede on the next refresh, and never
        listed by GET in the meantime."""
        window_end = date(2026, 1, 7)
        core_interrupts.enqueue(
            self.conn, org_id=self.org, brand_id=self.brand, category="ads_triage_stop_loss",
            dedupe_key=triage._dedupe_key("stop_loss", "ent_1", window_end),
            message="廣告「廣告A」停損，待決定",
        )
        self.conn.commit()
        items = [self._item("stop_loss", window_end=window_end)]
        with patch.object(triage, "_classify_brand", return_value=items):
            self.assertEqual(triage.get_queue(self.conn, self.org, self.brand)["items"], [])
            result = triage.refresh_queue(self.conn, self.org, self.brand)
        self.assertEqual(result["items"], [])
        rows = self.conn.execute(
            "SELECT status FROM interrupt WHERE brand_id=%s AND category='ads_triage_stop_loss'",
            (self.brand,),
        ).fetchall()
        self.assertEqual([row["status"] for row in rows], ["resolved"])  # none newly raised

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
        self.assertEqual(
            queue["kinds_available"],
            ["cleanup", "worse", "closeout", "settle", "refresh_creative", "scale_budget",
             "insufficient_data"],
        )
        self.assertEqual(queue["kinds_pending"], [])
        self.assertEqual(queue["counts"], dict.fromkeys(triage.ALL_CLASSES, 0))
        self.assertEqual(queue["decisions"], {"kinds": list(queue_done.DECISION_KINDS), "open": 0})


class QueueReviewProposalTest(unittest.TestCase):
    """F23-I01: `proposal` on a `worse` row -- against real `ads_review_round`/`ads_change_set`
    rows, inserted directly (`triage._classify_brand` patched to fixed items)."""

    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="檢討提案測試", actor="test", client_name=None,
        )["id"]
        self.campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="活動一",
        )["id"]
        self.entity = external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "ad",
             "native_id": "ad1", "name": "廣告A"},
        )["id"]

    def _item(self, *, entity_id=None, window_end=None):
        window_end = window_end or date(2026, 1, 7)
        return {
            "entity_id": entity_id or self.entity, "native_id": "n1", "name": "廣告A",
            "campaign_id": self.campaign, "class": "worse", "label": triage.LABELS["worse"],
            "reason_code": "x",
            # F29-I01: the `worse` row is raised by the grade move 划算 -> 太貴.
            "grade": "over", "previous_grade": "on_target",
            "grade_move": {"from": "on_target", "to": "over"},
            "window": {"start": window_end - timedelta(days=6), "end": window_end, "days": 7,
                       "previous_start": None, "previous_end": None, "extended_from": None},
            "target": {"value": 1}, "current": {}, "previous": {}, "change_pct": None,
            "sample": {},
        }

    def _round(self, *, entity_id=None, window_end=None, status="ready", decision=None,
               reason=None, revisit_at=None, result_json=None, created_at=None):
        entity_id = entity_id or self.entity
        window_end = window_end or date(2026, 1, 7)
        round_id = db.new_id("arv")
        self.conn.execute(
            "INSERT INTO ads_review_round(id,org_id,brand_id,campaign_id,entity_id,window_start,"
            "window_end,evidence_json,evidence_hash,result_json,status,decision,reason,revisit_at,"
            "created_by,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (round_id, self.org, self.brand, self.campaign, entity_id,
             window_end - timedelta(days=6), window_end, db.jsonb({}), round_id,
             db.jsonb(result_json or {}), status, decision, reason, revisit_at, "test",
             created_at or db.now_utc()),
        )
        self.conn.commit()
        return round_id

    @staticmethod
    def _copy_item(target_id):
        return {"id": db.new_id("adx"), "kind": "copy", "target_id": target_id, "target": {},
                "before": {"title": "old"}, "after": {"title": "new"}, "reason": "x"}

    def _insert_review_set(self, *, review_id, status, items):
        set_id = db.new_id("acs")
        self.conn.execute(
            "INSERT INTO ads_change_set(id,org_id,brand_id,campaign_id,operation_id,"
            "request_hash,content_hash,title,month,status,plan_json,created_by) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (set_id, self.org, self.brand, self.campaign, set_id, set_id, set_id, "測試清單",
             "2026-01", status, db.jsonb({"items": items, "review_id": review_id}), "test"),
        )
        self.conn.commit()
        return set_id

    def _queue(self, items):
        # `refresh_queue()`, not `get_queue()`: the row has to exist as an open `interrupt` row
        # before `_queue_payload` reports it at all.
        with patch.object(triage, "_classify_brand", return_value=items):
            return triage.refresh_queue(self.conn, self.org, self.brand)

    def test_no_round_is_null(self):
        item = self._item()
        self.assertIsNone(self._queue([item])["items"][0]["proposal"])

    def test_queued_round_without_change_set(self):
        item = self._item()
        round_id = self._round(status="queued")
        proposal = self._queue([item])["items"][0]["proposal"]
        self.assertEqual(proposal, {
            "kind": "review", "review_id": round_id, "status": "queued", "decision": None,
            "reason": None, "revisit_at": None, "recommendation_id": None,
            "change_set_id": None, "change_set_status": None, "verification_state": None,
            "verification_label": None, "multi": False,
        })

    def test_ready_round_recommendation_id_is_first_adjust(self):
        item = self._item()
        self._round(status="ready", result_json={"recommendations": [
            {"id": "recommendation-1", "target_id": self.entity, "recommendation": "observe"},
            {"id": "recommendation-2", "target_id": self.entity, "recommendation": "adjust"},
        ]})
        proposal = self._queue([item])["items"][0]["proposal"]
        self.assertEqual(proposal["status"], "ready")
        self.assertEqual(proposal["recommendation_id"], "recommendation-2")

    def test_ready_round_with_no_adjust_recommendation_has_null_recommendation_id(self):
        item = self._item()
        self._round(status="ready", result_json={"recommendations": [
            {"id": "recommendation-1", "target_id": self.entity, "recommendation": "retain"},
        ]})
        proposal = self._queue([item])["items"][0]["proposal"]
        self.assertIsNone(proposal["recommendation_id"])

    def test_completed_with_copy_set_reports_change_set_fields(self):
        item = self._item()
        round_id = self._round(status="completed", decision="completed", reason="改文案")
        set_id = self._insert_review_set(
            review_id=round_id, status="draft", items=[self._copy_item(self.entity)],
        )
        proposal = self._queue([item])["items"][0]["proposal"]
        self.assertEqual(proposal["decision"], "completed")
        self.assertEqual(proposal["change_set_id"], set_id)
        self.assertEqual(proposal["change_set_status"], "draft")
        self.assertEqual(proposal["verification_state"], "pending")
        self.assertFalse(proposal["multi"])

    def test_completed_without_copy_set_leaves_change_set_fields_null(self):
        item = self._item()
        self._round(status="completed", decision="completed", reason="先觀察")
        proposal = self._queue([item])["items"][0]["proposal"]
        self.assertEqual(proposal["decision"], "completed")
        self.assertIsNone(proposal["change_set_id"])
        self.assertIsNone(proposal["change_set_status"])
        self.assertIsNone(proposal["verification_state"])

    def test_deferred_round_carries_reason_and_revisit_at(self):
        item = self._item()
        revisit = db.now_utc() + timedelta(days=7)
        self._round(status="deferred", decision="deferred", reason="等一週", revisit_at=revisit)
        proposal = self._queue([item])["items"][0]["proposal"]
        self.assertEqual(proposal["status"], "deferred")
        self.assertEqual(proposal["reason"], "等一週")
        self.assertIsNotNone(proposal["revisit_at"])

    def test_unjudgeable_round(self):
        item = self._item()
        self._round(status="unjudgeable", decision="unjudgeable", reason="資料不足")
        proposal = self._queue([item])["items"][0]["proposal"]
        self.assertEqual(proposal["status"], "unjudgeable")

    def test_failed_round_has_no_decision(self):
        item = self._item()
        self._round(status="failed")
        proposal = self._queue([item])["items"][0]["proposal"]
        self.assertEqual(proposal["status"], "failed")
        self.assertIsNone(proposal["decision"])

    def test_round_outside_current_window_does_not_match(self):
        item = self._item(window_end=date(2026, 2, 20))
        self._round(status="ready", window_end=date(2026, 1, 7))
        self.assertIsNone(self._queue([item])["items"][0]["proposal"])


class ScaleRefreshQueueTest(unittest.TestCase):
    """F25-I01: `scale_budget`/`refresh_creative` rows through the full `refresh_queue`/
    `get_queue` pipeline -- `kind_key`, `scale`/`refresh` payload, category/severity, dedupe/
    supersede (the same generic mechanism `QueuePlumbingTest` already proves for worse
    -- `QUEUE_CATEGORY`/`_supersede_stale_open_rows` never special-case by kind), and the budget
    proposal match. `triage._classify_brand` patched to fixed items (same isolation as
    `QueuePlumbingTest`), but the `scale_budget` scenarios reference a REAL `ads_external_entity`
    ad/campaign pair so Rule A's owner lookup (a real, brand-wide DB read) finds them;
    `month_budget.view` patched so the budget gate is deterministic without a full month-budget
    fixture."""

    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="加預算補素材佇列測試", actor="test",
            client_name=None,
        )["id"]
        self.campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="活動一",
        )["id"]
        external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "campaign",
             "native_id": "c1", "name": "活動一", "budget_type": "daily", "budget_amount": 1000,
             "currency": "TWD"},
        )
        self.ad = external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "ad",
             "native_id": "ad1", "name": "廣告A",
             "parent_native_kind": "campaign", "parent_native_id": "c1"},
        )["id"]
        self.conn.commit()

    @staticmethod
    def _scale_item(entity_id, campaign_id, window_end):
        return {
            "entity_id": entity_id, "native_id": "n1", "name": "廣告A", "campaign_id": campaign_id,
            "campaign_name": "活動一", "thumbnail_url": None,
            "class": "flat", "label": triage.LABELS["flat"], "reason_code": "cost_per_result_flat",
            "grade": "on_target", "grade_label": "划算",
            "window": {"start": window_end - timedelta(days=13), "end": window_end, "days": 14,
                       "previous_start": None, "previous_end": None, "extended_from": None},
            "target": {"value": 100, "basis": "own", "result_kind": "purchase", "missing": [],
                       "result_label": "購買"},
            # F48-I02: enough sales that the raise is not held on sample size.
            "current": {"cost_per_result": 80, "result_count": triage.MIN_RESULT_EVENTS},
            "previous": {"cost_per_result": 85},
            "change_pct": None, "sample": {},
        }

    @staticmethod
    def _refresh_item(entity_id, campaign_id, window_end, cls, thumbnail_url=None):
        return {
            "entity_id": entity_id, "native_id": entity_id, "name": "廣告",
            "campaign_id": campaign_id, "campaign_name": "活動一", "thumbnail_url": thumbnail_url,
            "class": cls, "label": triage.LABELS[cls], "reason_code": "x",
            # F29-I01: readability follows the grade -- a trend class maps to 划算 here, a thin or
            # unjudged ad stays ungraded.
            "grade": cls if cls in ("insufficient", "no_target") else "on_target",
            "window": {"start": window_end - timedelta(days=13), "end": window_end, "days": 14,
                       "previous_start": None, "previous_end": None, "extended_from": None},
            "target": {"value": 100, "basis": "own", "result_kind": "purchase", "missing": [],
                       "result_label": "購買"},
            "current": {}, "previous": {}, "change_pct": None, "sample": {},
        }

    def _refresh_queue(self, items, available=500.0):
        with patch.object(triage, "_classify_brand", return_value=items), \
             patch.object(triage.month_budget, "view",
                         return_value={"available": available, "reserved_increases": 0.0}):
            return triage.refresh_queue(self.conn, self.org, self.brand)

    def test_scale_row_shape_kind_key_and_category(self):
        window_end = date(2026, 1, 7)
        item = self._scale_item(self.ad, self.campaign, window_end)
        result = self._refresh_queue([item])
        self.assertEqual(len(result["items"]), 1)
        row = result["items"][0]
        self.assertEqual(row["category"], "ads_triage_scale_budget")
        self.assertEqual(row["severity"], "informational")
        self.assertEqual(row["kind_key"], "scale_budget")
        self.assertEqual(row["scale"]["from"], 1000.0)
        self.assertEqual(row["scale"]["to"], 1200)
        self.assertNotIn("refresh", row)
        self.assertIsNone(row["proposal"])
        self.assertEqual(row["scale"]["reason_text"], "近期每筆 80 都在上限 100 內，加碼 2 成擴量")
        self.assertEqual(result["scale_hold"], [])

    def test_too_few_sales_raise_no_scale_row_and_the_queue_says_why(self):
        item = self._scale_item(self.ad, self.campaign, date(2026, 1, 7))
        item["current"]["result_count"] = triage.MIN_RESULT_EVENTS - 1
        result = self._refresh_queue([item])
        self.assertEqual(result["items"], [])
        self.assertEqual(len(result["scale_hold"]), 1)
        hold = result["scale_hold"][0]
        self.assertEqual((hold["campaign_id"], hold["reason_text"]),
                         (self.campaign, "樣本少，先不加碼"))
        with patch.object(triage, "_classify_brand", return_value=[item]):
            self.assertEqual(
                triage.get_queue(self.conn, self.org, self.brand)["scale_hold"],
                result["scale_hold"],
            )

    def test_scale_row_is_a_notice_never_an_interrupt(self):
        """F49 Contract Q: `scale_budget` is a money-card notice -- served from its candidate
        (`id` = its dedupe key, `decision: false`), never enqueued; an open row left from before
        resolves at the next refresh."""
        w1, w2 = date(2026, 1, 7), date(2026, 1, 8)
        legacy = core_interrupts.enqueue(
            self.conn, org_id=self.org, brand_id=self.brand, category="ads_triage_scale_budget",
            dedupe_key="ads-triage:scale_budget:legacy:2026-01-01", message="舊的加預算列",
        )
        self.conn.commit()
        first = self._refresh_queue([self._scale_item(self.ad, self.campaign, w1)])
        [row] = first["items"]
        self.assertEqual(row["id"], row["dedupe_key"])
        self.assertIs(row["decision"], False)
        self.assertIsNone(row["position"])
        self.assertEqual(first["decisions"]["open"], 0)
        again = self._refresh_queue([self._scale_item(self.ad, self.campaign, w1)])
        self.assertEqual(again["items"][0]["id"], row["id"])
        second = self._refresh_queue([self._scale_item(self.ad, self.campaign, w2)])
        self.assertEqual(len(second["items"]), 1)
        self.assertNotEqual(second["items"][0]["id"], row["id"])
        self.assertEqual(
            core_interrupts.list_open(self.conn, org_id=self.org, brand_id=self.brand,
                                      category="ads_triage_scale_budget", archive_stale=False),
            [],
        )
        status = self.conn.execute(
            "SELECT status FROM interrupt WHERE id=%s", (legacy,),
        ).fetchone()["status"]
        self.assertEqual(status, "resolved")

    def test_scale_row_never_raised_when_budget_gate_fails(self):
        window_end = date(2026, 1, 7)
        item = self._scale_item(self.ad, self.campaign, window_end)
        result = self._refresh_queue([item], available=None)
        self.assertEqual(result["items"], [])

    def test_scale_row_proposal_matches_a_budget_change_set(self):
        window_end = date(2026, 1, 7)
        item = self._scale_item(self.ad, self.campaign, window_end)
        owner_row = self.conn.execute(
            "SELECT id FROM ads_external_entity WHERE org_id=%s AND brand_id=%s "
            "AND native_kind='campaign' AND native_id='c1'", (self.org, self.brand),
        ).fetchone()
        owner_id = owner_row["id"]
        set_id = db.new_id("acs")
        self.conn.execute(
            "INSERT INTO ads_change_set(id,org_id,brand_id,campaign_id,operation_id,"
            "request_hash,content_hash,title,month,status,plan_json,created_by) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (set_id, self.org, self.brand, self.campaign, set_id, set_id, set_id, "測試清單",
             "2026-01", "draft",
             db.jsonb({"items": [
                 {"id": db.new_id("adx"), "kind": "budget", "target_id": owner_id, "target": {},
                  "before": {"daily_amount": 1000}, "after": {"daily_amount": 1200},
                  "reason": "x"},
             ]}), "test"),
        )
        self.conn.commit()
        result = self._refresh_queue([item])
        self.assertEqual(len(result["items"]), 1)
        proposal = result["items"][0]["proposal"]
        self.assertEqual(proposal["change_set_id"], set_id)
        self.assertEqual(proposal["kind"], "budget")
        self.assertEqual(proposal["status"], "draft")
        self.assertEqual(proposal["verification_state"], "pending")

    def test_refresh_row_shape_kind_key_and_category(self):
        # `worse` never used here -- it would independently raise its own `worse` queue row too
        # (unrelated to Rule B), which would throw off the "exactly one row" assertions below.
        window_end = date(2026, 1, 7)
        items = [
            self._refresh_item("ad_a", self.campaign, window_end, "flat"),
            self._refresh_item("ad_b", self.campaign, window_end, "better"),
            self._refresh_item("ad_c", self.campaign, window_end, "insufficient"),
        ]
        result = self._refresh_queue(items)
        self.assertEqual(len(result["items"]), 1)
        row = result["items"][0]
        self.assertEqual(row["category"], "ads_triage_refresh_creative")
        self.assertEqual(row["severity"], "informational")
        self.assertEqual(row["kind_key"], "refresh_creative")
        self.assertEqual(row["refresh"]["readable_count"], 2)
        self.assertEqual(row["refresh"]["classified_count"], 3)
        self.assertIsNone(row["proposal"])
        self.assertNotIn("scale", row)

    def test_refresh_row_is_idempotent_and_supersedes_across_windows(self):
        w1, w2 = date(2026, 1, 7), date(2026, 1, 8)

        def items(window_end):
            return [
                self._refresh_item("ad_a", self.campaign, window_end, "flat"),
                self._refresh_item("ad_b", self.campaign, window_end, "better"),
                self._refresh_item("ad_c", self.campaign, window_end, "insufficient"),
            ]

        first = self._refresh_queue(items(w1))
        first_id = first["items"][0]["id"]
        second = self._refresh_queue(items(w2))
        self.assertEqual(len(second["items"]), 1)
        self.assertNotEqual(second["items"][0]["id"], first_id)
        old_row = self.conn.execute(
            "SELECT status FROM interrupt WHERE id=%s", (first_id,)
        ).fetchone()
        self.assertEqual(old_row["status"], "resolved")

    def test_refresh_row_never_raised_when_readable_count_is_too_high(self):
        window_end = date(2026, 1, 7)
        items = [
            self._refresh_item("ad_a", self.campaign, window_end, "flat"),
            self._refresh_item("ad_b", self.campaign, window_end, "flat"),
            self._refresh_item("ad_c", self.campaign, window_end, "better"),
        ]
        result = self._refresh_queue(items)
        self.assertEqual(result["items"], [])


class InsufficientDataQueueTest(unittest.TestCase):
    """F26-I01: the campaign-level 「資料不足」 queue row -- real `classify()` pipeline (needs a
    real campaign/account for `_account_cutoff`/`campaign_sync_state`, same reason
    `QueueEndToEndTest` above never patches `_classify_brand`)."""

    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="資料不足佇列測試", actor="test", client_name=None,
        )["id"]
        self.reader = _Reader()
        patcher = patch.object(
            channels, "external_reader", side_effect=lambda platform: self.reader,
        )
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
        self.ad = external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "ad",
             "native_id": "ad1", "name": "廣告A",
             "parent_native_kind": "campaign", "parent_native_id": "c1"},
        )
        self.conn.commit()
        self.cutoff = (
            db.now_utc().astimezone(ZoneInfo(ACCOUNT_TZ)) - timedelta(days=1)
        ).date()

    def set_coverage(self, start, end):
        external.record_sync(
            self.conn, self.org, self.brand, self.campaign, section="observations",
            state={"last_success_at": db.now_utc().isoformat(),
                   "coverage": {"start": start.isoformat(), "end": end.isoformat()}},
        )
        self.conn.commit()

    def _insufficient_rows(self, result):
        return [r for r in result["items"] if r["category"] == "ads_triage_insufficient_data"]

    def test_missing_days_raises_the_row(self):
        self.set_coverage(self.cutoff - timedelta(days=10), self.cutoff)  # < 28-day window
        result = triage.refresh_queue(self.conn, self.org, self.brand)
        rows = self._insufficient_rows(result)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["kind_key"], "insufficient_data")
        self.assertEqual(row["severity"], "rule_warning")
        self.assertIsNone(row["proposal"])
        self.assertEqual(
            row["action_url"], f"/brands/{self.brand}/ads/campaigns/{self.campaign}/wait",
        )
        self.assertEqual(row["insufficient"]["campaign_id"], self.campaign)
        self.assertEqual(row["insufficient"]["campaign_name"], "活動一")
        self.assertTrue(row["insufficient"]["missing_days"])
        self.assertEqual(row["insufficient"]["sync_state"], "ok")
        self.assertIn("insufficient_data", result["kinds_available"])

    def test_failed_sync_raises_the_row_even_with_full_coverage(self):
        self.set_coverage(self.cutoff - timedelta(days=90), self.cutoff)
        external.record_sync(
            self.conn, self.org, self.brand, self.campaign, section="observations",
            state={"status": "error", "error": "讀取失敗",
                   "last_attempt_at": db.now_utc().isoformat()},
        )
        self.conn.commit()
        rows = self._insufficient_rows(triage.refresh_queue(self.conn, self.org, self.brand))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["insufficient"]["sync_state"], "failed")
        self.assertEqual(rows[0]["insufficient"]["missing_days"], [])

    def test_disconnected_raises_the_row(self):
        self.set_coverage(self.cutoff - timedelta(days=90), self.cutoff)
        self.reader.accounts = lambda conn, org, brand: []
        rows = self._insufficient_rows(triage.refresh_queue(self.conn, self.org, self.brand))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["insufficient"]["sync_state"], "disconnected")

    def test_full_coverage_and_ok_sync_never_raises(self):
        self.set_coverage(self.cutoff - timedelta(days=90), self.cutoff)
        rows = self._insufficient_rows(triage.refresh_queue(self.conn, self.org, self.brand))
        self.assertEqual(rows, [])

    def test_never_raised_without_an_active_ad(self):
        # The only ad is closed -- `classify()` never judges it, so this campaign contributes no
        # items to `by_campaign` at all, and the row never fires no matter how bad the sync is.
        external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "ad",
             "native_id": "ad1", "name": "廣告A", "native_status": "PAUSED",
             "parent_native_kind": "campaign", "parent_native_id": "c1"},
        )
        self.conn.commit()  # never synced at all -- would otherwise definitely qualify
        rows = self._insufficient_rows(triage.refresh_queue(self.conn, self.org, self.brand))
        self.assertEqual(rows, [])

    def test_served_as_a_notice_and_gone_when_it_recovers(self):
        """F49 Contract Q: `insufficient_data` is a notice (the campaign row and `/wait`) --
        served from its candidate, never an interrupt."""
        self.set_coverage(self.cutoff - timedelta(days=10), self.cutoff)
        first_row = self._insufficient_rows(
            triage.refresh_queue(self.conn, self.org, self.brand),
        )[0]
        self.assertIs(first_row["decision"], False)
        again_row = self._insufficient_rows(
            triage.refresh_queue(self.conn, self.org, self.brand),
        )[0]
        self.assertEqual(again_row["id"], first_row["id"])  # same window -> same row
        self.assertEqual(
            core_interrupts.list_open(self.conn, org_id=self.org, brand_id=self.brand,
                                      category="ads_triage_insufficient_data",
                                      archive_stale=False),
            [],
        )

        self.set_coverage(self.cutoff - timedelta(days=90), self.cutoff)  # recovers
        recovered = triage.refresh_queue(self.conn, self.org, self.brand)
        self.assertEqual(self._insufficient_rows(recovered), [])

    def test_category_registered_with_expected_severity_and_label(self):
        self.assertEqual(
            core_interrupts.CATEGORIES["ads_triage_insufficient_data"],
            {"severity": "rule_warning", "label": "活動資料不足待處理"},
        )


class CleanupQueueTest(unittest.TestCase):
    """F27-I06: Contract F's `cleanup` row through the full `refresh_queue`/`get_queue` pipeline.
    `triage._classify_brand` stays patched to fixed items (`_cleanup_candidates` only needs its
    OWN real DB reads -- owner lookup, sync coverage, daily rows -- never a full real `classify()`
    per-ad judgement), but the campaign/account/entities are real (same reason
    `ScaleRefreshQueueTest` uses a real campaign/ad pair for Rule A's owner lookup). Item classes
    stay off `{"better", "flat"}` on purpose so `triage_scale.scale_candidates` (always run inside
    `_queue_candidates`, real owner lookup finds these real entities) skips this owner's cost
    checks entirely rather than crashing on the fake items' empty `current`/`previous`."""

    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="清理佇列端到端測試", actor="test", client_name=None,
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
             "native_id": "c1", "name": "活動一", "budget_type": "daily", "budget_amount": 200,
             "currency": "TWD"},
        )
        self.ad1 = external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "ad",
             "native_id": "ad1", "name": "廣告甲", "native_status": "ACTIVE",
             "parent_native_kind": "campaign", "parent_native_id": "c1"},
        )["id"]
        self.ad2 = external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "ad",
             "native_id": "ad2", "name": "廣告乙", "native_status": "ACTIVE",
             "parent_native_kind": "campaign", "parent_native_id": "c1"},
        )["id"]
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
        self.conn.commit()
        # ad1: 10/day (lowest, 70 total); ad2: 50/day (350 total) -- can_support=1 (200/(100*2)),
        # active_ads=2, so exactly one gets proposed: ad1.
        for offset in range(7):
            self.obs(self.ad1, self.cutoff - timedelta(days=offset), spend=10)
            self.obs(self.ad2, self.cutoff - timedelta(days=offset), spend=50)

    def obs(self, entity_id, day, *, spend):
        external.upsert_observation(
            self.conn, self.org, self.brand, self.campaign,
            {"entity_id": entity_id, "day": day, "metric_scope": "ad",
             "attribution_key": f"{entity_id}-{day}", "currency": "TWD", "source": "meta",
             "spend": spend, "impressions": 100, "purchases": None},
            result_kind="purchase", result_count=1, result_action="omni_purchase",
            result_attribution="7d_click+1d_view",
        )
        self.conn.commit()

    @staticmethod
    def _item(entity_id, campaign_id, *, cls="insufficient", grade="on_target", cost=50,
              target_value=100, name="廣告", grade_move=None):
        return {
            "previous_grade": grade_move["from"] if grade_move else None,
            "grade_move": grade_move,
            "entity_id": entity_id, "native_id": entity_id, "name": name,
            "campaign_id": campaign_id, "campaign_name": "活動一", "thumbnail_url": None,
            "class": cls, "label": triage.LABELS[cls], "reason_code": "no_previous_window",
            "grade": grade, "grade_label": "x",
            "window": {"start": date(2026, 1, 1), "end": date(2026, 1, 7), "days": 7,
                       "previous_start": None, "previous_end": None, "extended_from": None},
            "target": {"value": target_value, "basis": "own", "result_kind": "purchase",
                       "missing": [], "result_label": "購買"},
            # F48-I02: the cleanup ranks spend ÷ results, so they agree with `cost`.
            "current": {"cost_per_result": cost, "spend": cost * 7, "result_count": 7,
                        "currency": "TWD"},
            "previous": {"cost_per_result": None}, "change_pct": None, "sample": {},
        }

    def _items(self):
        # can_support = floor(200 / (100 * 2)) = 1, two active ads: the 太貴 one closes.
        return [
            self._item(self.ad1, self.campaign, grade="over", cost=150, name="廣告甲"),
            self._item(self.ad2, self.campaign, name="廣告乙"),
        ]

    def _refresh_with_month(self, items):
        with patch.object(triage, "_classify_brand", return_value=items), \
             patch.object(triage.month_budget, "view",
                          return_value={"available": 5000.0, "reserved_increases": 0.0}):
            return triage.refresh_queue(self.conn, self.org, self.brand)

    def _refresh(self, items=None):
        with patch.object(triage, "_classify_brand", return_value=items or self._items()):
            return triage.refresh_queue(self.conn, self.org, self.brand)

    def _cleanup_row(self, result):
        rows = [r for r in result["items"] if r["kind_key"] == "cleanup"]
        return rows[0] if rows else None

    def test_cleanup_row_shape_kind_key_category_and_payload(self):
        result = self._refresh()
        row = self._cleanup_row(result)
        self.assertIsNotNone(row)
        self.assertEqual(row["category"], "ads_triage_cleanup")
        self.assertEqual(row["severity"], "money_loss")
        self.assertEqual(
            row["action_url"],
            f"/brands/{self.brand}/ads/campaigns/{self.campaign}/propose/cleanup/{self.campaign}",
        )
        self.assertEqual(row["cleanup"]["campaign_id"], self.campaign)
        self.assertEqual(row["cleanup"]["can_support"], 1)
        self.assertEqual(row["cleanup"]["active_ads"], 2)
        self.assertEqual(len(row["cleanup"]["ads"]), 1)
        self.assertEqual(row["cleanup"]["ads"][0]["entity_id"], self.ad1)  # the 太貴 one
        self.assertEqual(row["cleanup"]["ads"][0]["grade"], "over")
        self.assertEqual(row["cleanup"]["ads"][0]["spend_7d"], 70.0)
        self.assertEqual(row["cleanup"]["ads"][0]["daily_spend"], 10.0)
        self.assertEqual(row["cleanup"]["daily_saving"], 10.0)
        self.assertEqual([ad["entity_id"] for ad in row["cleanup"]["keep"]], [self.ad2])
        self.assertEqual(row["cleanup"]["short"], 0)
        self.assertIsNone(row["cleanup"]["scale_owner_id"])
        self.assertIsNone(row["proposal"])

    def test_worse_row_not_raised_for_an_ad_inside_the_cleanup(self):
        # F29-I01: both ads moved from 划算; the 太貴 one is decided in the cleanup row, the 偏貴
        # one (kept: capacity only asks for one) raises its own 變貴 row.
        items = [
            self._item(self.ad1, self.campaign, cls="worse", grade="over", cost=150,
                       grade_move={"from": "on_target", "to": "over"}),
            self._item(self.ad2, self.campaign, cls="worse", grade="watch", cost=110,
                       grade_move={"from": "on_target", "to": "watch"}),
        ]
        result = self._refresh(items)
        worse_ids = {r["triage"]["entity_id"] for r in result["items"] if r["kind_key"] == "worse"}
        self.assertEqual(worse_ids, {self.ad2})  # ad1 is decided in the cleanup row
        self.assertEqual(
            [ad["entity_id"] for ad in self._cleanup_row(result)["cleanup"]["ads"]], [self.ad1],
        )

    def test_over_capacity_with_only_on_target_ads_raises_scale_not_cleanup(self):
        items = [self._item(self.ad1, self.campaign), self._item(self.ad2, self.campaign)]
        result = self._refresh_with_month(items)
        self.assertIsNone(self._cleanup_row(result))
        self.assertEqual({r["kind_key"] for r in result["items"]}, {"scale_budget"})

    def test_short_cleanup_points_at_the_qualifying_scale_owner(self):
        # ABO: adset A (all 划算) qualifies for +20%; adset B carries the 太貴 ad. Capacity
        # floor((100 + 100) / 200) = 1 after the campaign-level budget is cleared: 3 active ads,
        # close the 太貴 one, 1 stays over -> the cleanup names adset A's scale row.
        self.conn.execute(
            "UPDATE ads_external_entity SET budget_type='unknown', budget_amount=NULL "
            "WHERE org_id=%s AND brand_id=%s AND native_kind='campaign'", (self.org, self.brand),
        )
        adsets = {}
        for native_id in ("asA", "asB"):
            adsets[native_id] = external.upsert_entity(
                self.conn, self.org, self.brand, self.campaign,
                {"platform": "meta", "source_account": "act_1", "native_kind": "adset",
                 "native_id": native_id, "name": native_id, "budget_type": "daily",
                 "budget_amount": 100, "currency": "TWD",
                 "parent_native_kind": "campaign", "parent_native_id": "c1"},
            )["id"]
        ads = {}
        for native_id, parent in (("ad1", "asA"), ("ad2", "asA"), ("ad3", "asB")):
            ads[native_id] = external.upsert_entity(
                self.conn, self.org, self.brand, self.campaign,
                {"platform": "meta", "source_account": "act_1", "native_kind": "ad",
                 "native_id": native_id, "name": native_id, "native_status": "ACTIVE",
                 "parent_native_kind": "adset", "parent_native_id": parent},
            )["id"]
        self.conn.commit()
        for offset in range(7):
            self.obs(ads["ad3"], self.cutoff - timedelta(days=offset), spend=150)
        items = [
            self._item(ads["ad1"], self.campaign),
            self._item(ads["ad2"], self.campaign, cost=60),
            self._item(ads["ad3"], self.campaign, grade="over", cost=150),
        ]
        result = self._refresh_with_month(items)
        cleanup = self._cleanup_row(result)["cleanup"]
        self.assertEqual([ad["entity_id"] for ad in cleanup["ads"]], [ads["ad3"]])
        self.assertEqual(cleanup["can_support"], 1)
        self.assertEqual(cleanup["short"], 1)
        self.assertEqual(cleanup["scale_owner_id"], adsets["asA"])
        scale_rows = [r for r in result["items"] if r["kind_key"] == "scale_budget"]
        self.assertEqual([r["scale"]["owner"]["id"] for r in scale_rows], [adsets["asA"]])

    def test_cleanup_row_is_idempotent(self):
        first_id = self._cleanup_row(self._refresh())["id"]
        again_id = self._cleanup_row(self._refresh())["id"]
        self.assertEqual(first_id, again_id)

    def test_refresh_creative_suppressed_while_cleanup_row_is_open(self):
        """Correction 4: while a campaign has an open cleanup row, its own refresh_creative row
        is not raised (cleanup first)."""
        third = external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "ad",
             "native_id": "ad3", "name": "廣告丙", "native_status": "ACTIVE",
             "parent_native_kind": "campaign", "parent_native_id": "c1"},
        )["id"]
        for offset in range(7):
            self.obs(third, self.cutoff - timedelta(days=offset), spend=5)
        items = [
            self._item(self.ad1, self.campaign, grade="over", cost=150, name="廣告甲"),
            self._item(self.ad2, self.campaign, name="廣告乙"),
            self._item(third, self.campaign, cls="worse", cost=40, name="廣告丙"),
        ]
        result = self._refresh(items)
        categories = {r["category"] for r in result["items"]}
        self.assertIn("ads_triage_cleanup", categories)
        self.assertNotIn("ads_triage_refresh_creative", categories)

    def test_cleanup_row_supersedes_once_campaign_returns_within_capacity(self):
        first_id = self._cleanup_row(self._refresh())["id"]

        # Both ads now `no_target` (target unresolved) -- nothing is graded, so nothing closes.
        items = [
            self._item(self.ad1, self.campaign, cls="no_target", grade="no_target",
                       target_value=None, name="廣告甲"),
            self._item(self.ad2, self.campaign, cls="no_target", grade="no_target",
                       target_value=None, name="廣告乙"),
        ]
        second = self._refresh(items)
        self.assertIsNone(self._cleanup_row(second))
        row = self.conn.execute(
            "SELECT status FROM interrupt WHERE id=%s", (first_id,),
        ).fetchone()
        self.assertEqual(row["status"], "resolved")

    def test_cleanup_row_proposal_matches_a_cleanup_pause_set(self):
        pause_item = {"id": db.new_id("adx"), "kind": "pause", "target_id": self.ad1,
                      "before": {}, "after": {"status": "PAUSED"}, "reason": "x"}
        set_id = db.new_id("acs")
        self.conn.execute(
            "INSERT INTO ads_change_set(id,org_id,brand_id,campaign_id,operation_id,"
            "request_hash,content_hash,title,month,status,plan_json,created_by) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (set_id, self.org, self.brand, self.campaign, set_id, set_id, set_id, "測試清單",
             "2026-01", "draft", db.jsonb({"source": "cleanup", "items": [pause_item]}), "test"),
        )
        self.conn.commit()
        row = self._cleanup_row(self._refresh())
        proposal = row["proposal"]
        self.assertEqual(proposal["change_set_id"], set_id)
        self.assertEqual(proposal["kind"], "cleanup")
        self.assertEqual(proposal["status"], "draft")
        self.assertEqual(proposal["verification_state"], "pending")
        self.assertTrue(proposal["multi"])

    def _cleanup_set(self, status, *, revisit_at=None):
        pause_item = {"id": db.new_id("adx"), "kind": "pause", "target_id": self.ad1,
                      "before": {}, "after": {"status": "PAUSED"}, "reason": "x"}
        set_id = db.new_id("acs")
        self.conn.execute(
            "INSERT INTO ads_change_set(id,org_id,brand_id,campaign_id,operation_id,"
            "request_hash,content_hash,title,month,status,revisit_at,plan_json,created_by) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (set_id, self.org, self.brand, self.campaign, set_id, set_id, set_id, "測試清單",
             "2026-01", status, revisit_at,
             db.jsonb({"source": "cleanup", "items": [pause_item]}), "test"),
        )
        self.conn.commit()
        return set_id

    def test_every_row_carries_done_from_the_one_rule(self):
        """F47 Contract D: `done` rides on the row -- no proposal / a draft is open, a deferred
        set (revisit still ahead) is done and keeps its `revisit_at` for the home chip."""
        row = self._cleanup_row(self._refresh())
        self.assertIs(row["done"], False)
        self._cleanup_set("draft")
        self.assertIs(self._cleanup_row(self._refresh())["done"], False)
        revisit = db.now_utc() + timedelta(days=3)
        set_id = self._cleanup_set("deferred", revisit_at=revisit)
        row = self._cleanup_row(self._refresh())
        self.assertEqual(row["proposal"]["change_set_id"], set_id)
        self.assertIs(row["done"], True)
        self.assertEqual(row["proposal"]["revisit_at"], revisit)
        self.assertTrue(all(isinstance(r["done"], bool) for r in self._refresh()["items"]))

    def test_a_cleanup_with_nothing_to_close_raises_no_row(self):
        """drill-10 Q1: a cleanup whose close list is empty (every ad left is data-insufficient)
        is no decision -- never an open row offering 「核准清理（關 0 則）」."""
        empty = {"campaign_id": self.campaign, "campaign_name": "活動一", "can_support": 1,
                 "active_ads": 2, "ads": [], "keep": [], "short": 0, "daily_saving": 0,
                 "scale_owner_id": None}
        with patch.object(triage.triage_capacity, "cleanup_candidates", return_value=empty):
            result = self._refresh()
        self.assertIsNone(self._cleanup_row(result))

    def _cleanup_set_with_action(self, target_id, *, verification_state):
        pause_item = {"id": db.new_id("adx"), "kind": "pause", "target_id": target_id,
                      "before": {}, "after": {"status": "PAUSED"}, "reason": "x"}
        set_id = db.new_id("acs")
        self.conn.execute(
            "INSERT INTO ads_change_set(id,org_id,brand_id,campaign_id,operation_id,"
            "request_hash,content_hash,title,month,status,plan_json,created_by) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (set_id, self.org, self.brand, self.campaign, set_id, set_id, set_id, "測試清單",
             "2026-01", "approved", db.jsonb({"source": "cleanup", "items": [pause_item]}),
             "test"),
        )
        self.conn.execute(
            "INSERT INTO ads_action(id,org_id,brand_id,campaign_id,target_kind,target_id,kind,"
            "change_set_id,verification_state) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (pause_item["id"], self.org, self.brand, self.campaign, "ad", target_id, "pause",
             set_id, verification_state),
        )
        self.conn.commit()
        return set_id

    def test_confirmed_cleanup_counts_while_its_paused_ads_stay_out_of_the_close_list(self):
        # The confirmed set paused ad2; today's close list is ad1 only -- the set still answers.
        set_id = self._cleanup_set_with_action(self.ad2, verification_state="confirmed")
        proposal = self._cleanup_row(self._refresh())["proposal"]
        self.assertEqual(proposal["change_set_id"], set_id)
        self.assertEqual(proposal["verification_state"], "confirmed")

    def test_confirmed_cleanup_whose_ad_is_active_again_needs_a_fresh_proposal(self):
        # Carried over from the retired stop-loss proposal: the confirmed set paused ad1, yet ad1
        # is active and back in the close list -- never report the old set as done.
        self._cleanup_set_with_action(self.ad1, verification_state="confirmed")
        self.assertIsNone(self._cleanup_row(self._refresh())["proposal"])

    # -- F29-I01 Contract B: rejected cleanup memory through the queue ---------------------------

    def _rejected_cleanup(self, target_id, *, grades):
        pause_item = {"id": db.new_id("adx"), "kind": "pause", "target_id": target_id,
                      "before": {}, "after": {"status": "PAUSED"}, "reason": "x"}
        set_id = db.new_id("acs")
        self.conn.execute(
            "INSERT INTO ads_change_set(id,org_id,brand_id,campaign_id,operation_id,"
            "request_hash,content_hash,title,month,status,plan_json,created_by,"
            "decision_reason,decision_grades,created_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (set_id, self.org, self.brand, self.campaign, set_id, set_id, set_id, "清理：活動一",
             "2026-01", "rejected", db.jsonb({"source": "cleanup", "items": [pause_item]}),
             "test", "還在測試", db.jsonb(grades) if grades is not None else None,
             db.now_utc() - timedelta(days=2)),  # inside the row's 7-day window
        )
        self.conn.commit()
        return set_id

    def test_a_rejection_at_the_same_grade_raises_no_row(self):
        self._rejected_cleanup(self.ad1, grades={
            self.ad1: {"grade": "over", "cost_per_result": 150, "cap": 100,
                       "at": db.now_utc().isoformat()},
        })
        self.assertIsNone(self._cleanup_row(self._refresh()))

    def test_a_worse_grade_raises_a_fresh_row_carrying_rejected_before(self):
        set_id = self._rejected_cleanup(self.ad1, grades={
            self.ad1: {"grade": "watch", "cost_per_result": 110, "cap": 100,
                       "at": db.now_utc().isoformat()},
        })
        row = self._cleanup_row(self._refresh())
        ad = row["cleanup"]["ads"][0]
        self.assertEqual(ad["entity_id"], self.ad1)
        self.assertEqual(ad["rejected_before"]["change_set_id"], set_id)
        self.assertEqual(ad["rejected_before"]["grade_label"], "偏貴")
        self.assertEqual(ad["rejected_before"]["reason"], "還在測試")
        # The rejected set does not answer the re-raised row: it is a new proposal.
        self.assertIsNone(row["proposal"])

    def test_a_legacy_rejection_without_memory_keeps_the_window_rule(self):
        set_id = self._rejected_cleanup(self.ad1, grades=None)
        row = self._cleanup_row(self._refresh())
        self.assertIsNone(row["cleanup"]["ads"][0]["rejected_before"])
        self.assertEqual(row["proposal"]["change_set_id"], set_id)
        self.assertEqual(row["proposal"]["status"], "rejected")

    def test_category_registered_with_expected_severity_and_label(self):
        self.assertEqual(
            core_interrupts.CATEGORIES["ads_triage_cleanup"],
            {"severity": "money_loss", "label": "花錢沒效的廣告待決定"},
        )


class GradedCleanupEndToEndTest(unittest.TestCase):
    """F28-I02 Done #4: the drill-5 shape (8 active ads, cap 450) through the real `classify()`
    -> `refresh_queue()` pipeline, nothing patched but the account reader. Four winners at 50 a
    purchase, three ads at 400+ (431 划算, 520 偏貴, 617 太貴), and one ad that spent over 3 x
    cap with no purchase. The campaign's own daily budget 5,600 carries floor(5600 / 900) = 6 ads,
    so two must go: the 白花 ad and the most expensive one -- never a winner (the old lowest-spend
    rule proposed pausing winners and kept the 0-purchase ad)."""

    CAP = 450

    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="對上限分級清理測試", actor="test", client_name=None,
        )["id"]
        patcher = patch.object(channels, "external_reader", return_value=_Reader())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="日常商品推廣・轉換",
        )["id"]
        external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "campaign",
             "native_id": "c1", "name": "日常商品推廣・轉換", "budget_type": "daily",
             "budget_amount": 5600, "currency": "TWD"},
        )
        self.cutoff = (
            db.now_utc().astimezone(ZoneInfo(ACCOUNT_TZ)) - timedelta(days=1)
        ).date()
        external.record_sync(
            self.conn, self.org, self.brand, self.campaign, section="observations",
            state={"last_success_at": db.now_utc().isoformat(),
                   "coverage": {"start": (self.cutoff - timedelta(days=90)).isoformat(),
                                "end": self.cutoff.isoformat()}},
        )
        repository.save_campaign_target(
            self.conn, self.org, self.brand, self.campaign, result_kind="purchase",
            basis="own", value=self.CAP, expected_revision=0, actor="測試員",
        )
        self.conn.commit()
        # (native_id, daily spend, daily purchases, previous-week daily spend or None)
        shape = [
            ("w1", 200, 4, None), ("w2", 200, 4, None), ("w3", 200, 4, None),
            ("w4", 200, 4, None),
            ("fit", 431, 1, None),        # 431 a purchase: 划算
            ("pricey", 520, 1, 400),      # 520: 偏貴, and 30 % worse than last week
            ("costly", 617, 1, 400),      # 617: 太貴, 54 % worse than last week
            ("wasted", 220, 0, None),     # 1,540 over 7 days, 0 purchases: 白花 (>= 1,350)
        ]
        self.ids = {}
        for native_id, spend, purchases, previous in shape:
            ad_id = external.upsert_entity(
                self.conn, self.org, self.brand, self.campaign,
                {"platform": "meta", "source_account": "act_1", "native_kind": "ad",
                 "native_id": native_id, "name": native_id, "native_status": "ACTIVE",
                 "parent_native_kind": "campaign", "parent_native_id": "c1"},
            )["id"]
            self.ids[native_id] = ad_id
            for offset in range(7):
                self.obs(ad_id, self.cutoff - timedelta(days=offset), spend=spend,
                         result_count=purchases, key=f"{native_id}-cur{offset}")
                if previous is not None:
                    self.obs(ad_id, self.cutoff - timedelta(days=7 + offset), spend=previous,
                             result_count=1, key=f"{native_id}-prev{offset}")

    def obs(self, ad_id, day, *, spend, result_count, key):
        external.upsert_observation(
            self.conn, self.org, self.brand, self.campaign,
            {"entity_id": ad_id, "day": day, "metric_scope": "ad", "attribution_key": key,
             "currency": "TWD", "source": "meta", "spend": spend, "impressions": 1000,
             "purchases": None},
            result_kind="purchase", result_count=result_count, result_action="omni_purchase",
            result_attribution="7d_click+1d_view",
        )
        self.conn.commit()

    def test_grades_against_the_one_cap(self):
        items = {
            item["entity_id"]: item
            for item in triage.classify(self.conn, self.org, self.brand, self.campaign)["items"]
        }
        grades = {name: items[ad_id]["grade"] for name, ad_id in self.ids.items()}
        self.assertEqual(grades, {
            "w1": "on_target", "w2": "on_target", "w3": "on_target", "w4": "on_target",
            "fit": "on_target", "pricey": "watch", "costly": "over", "wasted": "wasted",
        })
        self.assertEqual(items[self.ids["wasted"]]["grade_label"], "沒賣出")
        self.assertEqual(items[self.ids["costly"]]["grade_label"], "太貴")

    def test_cleanup_closes_the_wasted_and_the_most_expensive_and_keeps_the_winners(self):
        result = triage.refresh_queue(self.conn, self.org, self.brand)
        kinds = sorted(row["kind_key"] for row in result["items"])
        # No stop_loss row; the 太貴 ad's own `worse` trend is decided inside the cleanup, the
        # 偏貴 one keeps its `worse` row; no scale-up (not every ad is 划算).
        self.assertEqual(kinds, ["cleanup", "worse"])
        cleanup = next(row for row in result["items"] if row["kind_key"] == "cleanup")["cleanup"]
        self.assertEqual(cleanup["can_support"], 6)
        self.assertEqual(cleanup["active_ads"], 8)
        # F48-I02: served in learning_rank order (7th and 8th of 8), each with its own reason.
        self.assertEqual(
            [ad["entity_id"] for ad in cleanup["ads"]],
            [self.ids["costly"], self.ids["wasted"]],
        )
        self.assertEqual([ad["grade"] for ad in cleanup["ads"]], ["over", "wasted"])
        self.assertEqual([(ad["rank"], ad["of"]) for ad in cleanup["ads"]], [(7, 8), (8, 8)])
        self.assertEqual(
            [ad["reason_text"] for ad in cleanup["ads"]],
            ["第 7／8 名，每筆 617 對上限 450（太貴）", "花了 1,540，一筆都沒賣出"],
        )
        self.assertEqual(
            [ad["entity_id"] for ad in cleanup["keep"]],
            [self.ids[n] for n in ("w1", "w2", "w3", "w4", "fit", "pricey")],
        )
        self.assertEqual([ad["rank"] for ad in cleanup["keep"]], [1, 2, 3, 4, 5, 6])
        self.assertEqual(cleanup["short"], 0)
        self.assertEqual(cleanup["daily_saving"], 220 + 617)
        self.assertIsNone(cleanup["scale_owner_id"])
        worse = next(row for row in result["items"] if row["kind_key"] == "worse")
        self.assertEqual(worse["triage"]["entity_id"], self.ids["pricey"])
        self.assertEqual(result["counts"]["stop_loss"], 1)  # the trend class keeps its meaning


class _RealCampaignQueue(unittest.TestCase):
    """F49 Contract Q fixtures through the real pipeline: an ad that spent 500 with no sale against
    a cap of 100 (沒賣出) raises its campaign's cleanup row."""

    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="佇列與收件匣測試", actor="test", client_name=None,
        )["id"]
        patcher = patch.object(channels, "external_reader", return_value=_Reader())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cutoff = (
            db.now_utc().astimezone(ZoneInfo(ACCOUNT_TZ)) - timedelta(days=1)
        ).date()

    def _internal(self, name, *, end_date):
        campaign_id = repository.create_campaign(self.conn, self.org, self.brand, {
            "name": name, "goal_text": "g", "objective": "購買", "target_cost": 100,
            "start_date": self.cutoff - timedelta(days=60), "end_date": end_date,
            "status": "live",
        }, created_by="test")["id"]
        self.conn.commit()
        return campaign_id

    def _imported(self, name, native_id, **root):
        campaign_id = external.create_imported_campaign(
            self.conn, self.org, self.brand, name=name,
        )["id"]
        self.conn.commit()
        self._entity(campaign_id, "campaign", native_id, native_status="ACTIVE", **root)
        repository.save_campaign_target(
            self.conn, self.org, self.brand, campaign_id, result_kind="purchase", basis="own",
            value=100, expected_revision=0, actor="test",
        )
        self.conn.commit()
        return campaign_id

    def _entity(self, campaign_id, kind, native_id, parent=None, **extra):
        row = {"platform": "meta", "source_account": "act_1", "native_kind": kind,
               "native_id": native_id, "name": native_id, **extra}
        if parent is not None:
            row["parent_native_kind"], row["parent_native_id"] = parent
        entity = external.upsert_entity(self.conn, self.org, self.brand, campaign_id, row)
        self.conn.commit()
        return entity["id"]

    def _wasted_ad(self, campaign_id, root_native_id, ad_native_id, day):
        ad = self._entity(campaign_id, "ad", ad_native_id, ("campaign", root_native_id),
                          native_status="ACTIVE")
        external.record_sync(
            self.conn, self.org, self.brand, campaign_id, section="observations",
            state={"status": "success", "last_success_at": db.now_utc().isoformat(),
                   "coverage": {"start": (self.cutoff - timedelta(days=90)).isoformat(),
                                "end": self.cutoff.isoformat()}},
        )
        external.upsert_observation(
            self.conn, self.org, self.brand, campaign_id,
            {"entity_id": ad, "day": day, "metric_scope": "ad", "attribution_key": "a",
             "currency": "TWD", "source": "meta", "spend": 500, "impressions": 100,
             "purchases": None},
            result_kind="purchase", result_count=0, result_action="omni_purchase",
            result_attribution="7d_click+1d_view",
        )
        self.conn.commit()
        return ad

    def _open(self, kind):
        return core_interrupts.list_open(
            self.conn, org_id=self.org, brand_id=self.brand,
            category=triage.QUEUE_CATEGORY[kind],
            archive_stale=False,
        )

    @staticmethod
    def _rows(queue, kind):
        return [row for row in queue["items"] if row["kind_key"] == kind]


class EndedCampaignQueueTest(_RealCampaignQueue):
    """F49 Contract Q, decision 6: an ended campaign gets a closeout row instead of new proposals;
    a row raised before the end stays until closeout; an imported ended campaign leaves the
    queue."""

    def test_a_row_raised_before_the_end_stays_and_the_closeout_row_joins_it(self):
        campaign = self._internal("夏季活動", end_date=self.cutoff + timedelta(days=5))
        self._entity(campaign, "campaign", "c_end")
        self._wasted_ad(campaign, "c_end", "a_end", self.cutoff - timedelta(days=1))
        before = triage.refresh_queue(self.conn, self.org, self.brand)
        [cleanup] = self._rows(before, "cleanup")
        self.assertEqual(self._rows(before, "closeout"), [])

        # The campaign ends the day before the account's last complete day: its judged window
        # now ends at the end date, so the candidate's own key names another day.
        self.conn.execute("UPDATE ads_campaign SET end_date=%s WHERE id=%s",
                          (self.cutoff - timedelta(days=1), campaign))
        self.conn.commit()
        after = triage.refresh_queue(self.conn, self.org, self.brand)
        [kept] = self._rows(after, "cleanup")
        self.assertEqual(kept["id"], cleanup["id"])
        self.assertEqual(kept["campaign_id"], campaign)
        self.assertEqual(len(self._open("cleanup")), 1)
        [closeout] = self._rows(after, "closeout")
        self.assertEqual(closeout["category"], "ads_triage_closeout")
        self.assertEqual(closeout["message"], "「夏季活動」已結束，待結案")
        self.assertEqual(
            closeout["action_url"],
            f"/brands/{self.brand}/ads/campaigns/{campaign}?tab=perf&close=1",
        )
        self.assertIsNone(closeout["triage"])
        self.assertEqual(closeout["closeout"], {
            "campaign_id": campaign, "campaign_name": "夏季活動",
            "end_date": self.cutoff - timedelta(days=1),
            "running": {"count": 1, "read_at": None},
        })
        self.assertEqual(
            [(r["kind_key"], r["position"]) for r in after["items"] if r["decision"]],
            [("cleanup", 1), ("closeout", 2)],
        )
        self.assertEqual(after["decisions"]["open"], 2)
        # Read-only `get_queue` serves the same rows.
        self.assertEqual(
            {r["id"] for r in triage.get_queue(self.conn, self.org, self.brand)["items"]},
            {cleanup["id"], closeout["id"]},
        )

        # Closing the campaign resolves every row of it.
        self.conn.execute("UPDATE ads_campaign SET status='closed' WHERE id=%s", (campaign,))
        self.conn.commit()
        triage.resolve_campaign(self.conn, self.org, self.brand, campaign)
        self.assertEqual(self._open("cleanup"), [])
        self.assertEqual(self._open("closeout"), [])

    def test_an_ended_campaign_raises_no_new_proposal(self):
        campaign = self._internal("已結束活動", end_date=self.cutoff - timedelta(days=1))
        self._entity(campaign, "campaign", "c_done")
        self._wasted_ad(campaign, "c_done", "a_done", self.cutoff - timedelta(days=1))
        # The cleanup candidate exists (the ad is 沒賣出 inside the judged window) ...
        self.assertIsNotNone(triage.campaign_cleanup(self.conn, self.org, self.brand, campaign))
        queue = triage.refresh_queue(self.conn, self.org, self.brand)
        # ... but an ended campaign only gets its closeout row.
        self.assertEqual([r["kind_key"] for r in queue["items"]], ["closeout"])
        self.assertEqual(self._open("cleanup"), [])
        self.assertEqual(len(self._open("closeout")), 1)
        # Idempotent: one closeout row per campaign.
        triage.refresh_queue(self.conn, self.org, self.brand)
        self.assertEqual(len(self._open("closeout")), 1)

    def test_an_imported_ended_campaign_has_no_rows(self):
        live = self._imported("進行中", "c_live")
        self._wasted_ad(live, "c_live", "a_live", self.cutoff)
        raised = triage.refresh_queue(self.conn, self.org, self.brand)
        self.assertEqual(len(self._rows(raised, "cleanup")), 1)

        # Its root is switched off on the platform: imported and ended -- no closeout exists for it.
        self._entity(live, "campaign", "c_live", native_status="PAUSED")
        queue = triage.refresh_queue(self.conn, self.org, self.brand)
        self.assertEqual(queue["items"], [])
        self.assertEqual(self._open("cleanup"), [])
        self.assertEqual(self._open("closeout"), [])


class InboxFollowsTheQueueTest(_RealCampaignQueue):
    """F49 Contract Q: a row whose `done` turns true has no open interrupt once the decision has
    committed -- in the same request, not at the next refresh."""

    def setUp(self):
        super().setUp()
        self.campaign = self._imported("春季活動", "c_spring")
        self.ad = self._wasted_ad(self.campaign, "c_spring", "a_spring", self.cutoff)
        queue = triage.refresh_queue(self.conn, self.org, self.brand)
        [self.row] = self._rows(queue, "cleanup")

    def _cleanup_set(self):
        from app.ads import change_control

        return change_control.create(self.conn, self.org, self.brand, self.campaign, {
            "operation_id": db.new_id("op"), "title": "清理", "source": "cleanup",
            "month": self.cutoff.strftime("%Y-%m"),
            "items": [{"kind": "pause", "target_id": self.ad, "after": {"status": "PAUSED"},
                       "reason": "清理"}],
        }, "test")

    def test_rejecting_the_cleanup_set_empties_the_inbox_row(self):
        from app.ads import change_control

        created = self._cleanup_set()
        self.assertEqual(len(self._open("cleanup")), 1)
        change_control.decide(self.conn, self.org, self.brand, self.campaign, created["id"],
                              "rejected", "先不關", None, "test")
        self.assertEqual(self._open("cleanup"), [])

    def test_deferring_resolves_the_row_the_queue_serves_as_done(self):
        from app.ads import change_control

        created = self._cleanup_set()
        change_control.decide(self.conn, self.org, self.brand, self.campaign, created["id"],
                              "deferred", "下週再看",
                              (db.now_utc() + timedelta(days=3)).isoformat(), "test")
        self.assertEqual(self._open("cleanup"), [])
        # Resolved because it is done, not because it stopped qualifying: the candidate is still
        # raised, and its resolved key is never raised again within the same window.
        self.assertIsNotNone(triage.campaign_cleanup(self.conn, self.org, self.brand,
                                                     self.campaign))
        queue = triage.refresh_queue(self.conn, self.org, self.brand)
        self.assertEqual(self._rows(queue, "cleanup"), [])
        self.assertEqual(queue["decisions"]["open"], 0)

    def test_a_draft_set_leaves_the_row_open(self):
        self._cleanup_set()
        triage.resolve_done(self.conn, self.org, self.brand, kind="cleanup",
                            identity_id=self.campaign)
        self.assertEqual([r["id"] for r in self._open("cleanup")], [self.row["id"]])

    def test_a_launch_set_answers_no_queue_row(self):
        """The launch handoff (whose re-approval carries `confirmed` forward,
        `handoff_data.carry_launch`) answers no decision row: resolving for it leaves the
        campaign's waiting cleanup row open."""
        set_id = db.new_id("acs")
        self.conn.execute(
            "INSERT INTO ads_change_set(id,org_id,brand_id,campaign_id,operation_id,request_hash,"
            "content_hash,title,month,plan_json,created_by,status) "
            "VALUES(%s,%s,%s,%s,%s,'h','h','上架','2026-01',%s,'test','approved')",
            (set_id, self.org, self.brand, self.campaign, db.new_id("op"),
             db.jsonb({"launch_snapshot": {}, "items": [{"id": "x", "kind": "launch"}]})),
        )
        self.conn.commit()
        triage.resolve_change_set(self.conn, self.org, self.brand, set_id)
        self.assertEqual([r["id"] for r in self._open("cleanup")], [self.row["id"]])

    def test_one_count_everywhere(self):
        from app.ads import digest, status_summary

        queue = triage.get_queue(self.conn, self.org, self.brand)
        summary = status_summary.get_status_summary(self.conn, self.org, self.brand)
        built = digest.build(self.conn, self.org, self.brand, self.cutoff)
        self.assertEqual(queue["decisions"]["open"], 1)
        self.assertEqual(summary["open_items"], queue["decisions"]["open"])
        self.assertEqual(built["open_count"], queue["decisions"]["open"])


if __name__ == "__main__":
    unittest.main()
