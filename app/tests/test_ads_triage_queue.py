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
- `QueueProposalTest` (F22-I01) proves the `proposal` field of a `stop_loss` row against real
  `ads_change_set`/`ads_action` rows, inserted directly (not through `change_control.create()`
  /`approve()`) so each scenario's status/`revisit_at`/`created_at` can be set precisely without
  driving the whole approval workflow -- `triage._classify_brand` stays patched to fixed items,
  same isolation as `QueuePlumbingTest`.
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
        # F20-I01: newly enqueued rows land on the detail page, anchored on the ad that fired.
        self.assertEqual(
            stop_row["action_url"],
            f"/brands/{self.brand}/ads/campaigns/{self.campaign}/detail?ad={self.ad_stop['id']}",
        )
        # F19-I01: each queue row carries the current triage item that produced it (matched by
        # the same dedupe key the enqueue used) -- never null, it's filtered to only live rows.
        self.assertEqual(stop_row["triage"]["class"], "stop_loss")
        self.assertEqual(stop_row["triage"]["entity_id"], self.ad_stop["id"])
        # F19-I07: the queue is brand-level across campaigns -- each row's triage item carries
        # its own campaign's name so the frontend can label/filter rows by campaign.
        self.assertEqual(stop_row["triage"]["campaign_name"], "活動一")

        worse_row = by_category["ads_triage_worse"]
        self.assertEqual(worse_row["severity"], "rule_warning")
        self.assertIn("廣告變差用", worse_row["message"])
        self.assertLessEqual(len(worse_row["message"]), core_interrupts.MAX_MESSAGE_LEN)
        self.assertEqual(worse_row["triage"]["class"], "worse")
        self.assertEqual(worse_row["triage"]["entity_id"], self.ad_worse["id"])
        self.assertEqual(worse_row["triage"]["campaign_name"], "活動一")

        # F27-I06: six kinds are live now -- neither of these two campaigns' owners/ads qualifies
        # for `scale_budget`/`refresh_creative`/`cleanup` (no budget owner configured, too few
        # ads), and this campaign's own sync is fully covered (`setUp`'s `record_sync`), so
        # `kinds_available` growing to six doesn't itself raise more rows here.
        self.assertEqual(
            result["kinds_available"],
            ["stop_loss", "worse", "scale_budget", "refresh_creative", "insufficient_data",
             "cleanup"],
        )
        self.assertEqual(result["kinds_pending"], [])
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

    def test_get_queue_filters_a_stale_open_row_when_classification_moves_on(self):
        w1 = date(2026, 1, 7)
        stop_loss_item = self._item("stop_loss", window_end=w1)
        with patch.object(triage, "_classify_brand", return_value=[stop_loss_item]):
            triage.refresh_queue(self.conn, self.org, self.brand)

        # Same ad, same window_end, but a later refresh's classification has moved off stop_loss
        # (e.g. now flat) -- the old open row is stale and must not be reported to GET.
        flat_item = self._item("flat", window_end=w1)
        with patch.object(triage, "_classify_brand", return_value=[flat_item]):
            queue = triage.get_queue(self.conn, self.org, self.brand)

        self.assertEqual(queue["items"], [])
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
        self.assertEqual(
            queue["kinds_available"],
            ["stop_loss", "worse", "scale_budget", "refresh_creative", "insufficient_data",
             "cleanup"],
        )
        self.assertEqual(queue["kinds_pending"], [])
        self.assertEqual(queue["counts"], dict.fromkeys(triage.ALL_CLASSES, 0))


class QueueProposalTest(unittest.TestCase):
    """F22-I01: `proposal` on a `stop_loss` row -- against real `ads_change_set`/`ads_action`
    rows, inserted directly so each scenario's status/`revisit_at`/`created_at` is exact."""

    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="停損提案測試", actor="test", client_name=None,
        )["id"]
        self.campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="活動一",
        )["id"]
        self.other_campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="活動二",
        )["id"]

    def _item(self, *, entity_id="ent_1", campaign_id=None, window_end=None, cls="stop_loss"):
        window_end = window_end or date(2026, 1, 7)
        campaign_id = campaign_id or self.campaign
        return {
            "entity_id": entity_id, "native_id": "n1", "name": "廣告A", "campaign_id": campaign_id,
            "class": cls, "label": triage.LABELS[cls], "reason_code": "x",
            "window": {"start": window_end - timedelta(days=6), "end": window_end, "days": 7,
                       "previous_start": None, "previous_end": None, "extended_from": None},
            "target": {"value": 1}, "current": {}, "previous": {}, "change_pct": None,
            "sample": {},
        }

    @staticmethod
    def _pause_item(target_id):
        # `ads_action.id` is a global primary key (not scoped per brand/test) -- a fresh id every
        # call, never a literal like "i1" reused across test methods in the same shared dev DB.
        return {"id": db.new_id("adx"), "kind": "pause", "target_id": target_id, "target": {},
                "before": {"status": "ACTIVE"}, "after": {"status": "PAUSED"}, "reason": "x"}

    def _insert_set(self, *, campaign_id, status, items, revisit_at=None, decision_reason=None,
                     created_at=None):
        set_id = db.new_id("acs")
        self.conn.execute(
            "INSERT INTO ads_change_set(id,org_id,brand_id,campaign_id,operation_id,"
            "request_hash,content_hash,title,month,status,plan_json,revisit_at,decision_reason,"
            "created_by,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (set_id, self.org, self.brand, campaign_id, set_id, set_id, set_id, "測試清單",
             "2026-01", status, db.jsonb({"items": items}), revisit_at, decision_reason, "test",
             created_at or db.now_utc()),
        )
        self.conn.commit()
        return set_id

    def _insert_action(self, action_id, set_id, campaign_id, target_id, verification_state):
        self.conn.execute(
            "INSERT INTO ads_action(id,org_id,brand_id,campaign_id,target_kind,target_id,kind,"
            "change_set_id,verification_state) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (action_id, self.org, self.brand, campaign_id, "ad", target_id, "pause", set_id,
             verification_state),
        )
        self.conn.commit()

    def _queue(self, items):
        # `refresh_queue()`, not `get_queue()`: the row has to actually exist as an open
        # `interrupt` row before `_queue_payload` will report it at all (same reason
        # `QueuePlumbingTest` calls `refresh_queue()` first).
        with patch.object(triage, "_classify_brand", return_value=items):
            return triage.refresh_queue(self.conn, self.org, self.brand)

    def test_no_matching_set_is_null(self):
        item = self._item()
        queue = self._queue([item])
        self.assertIsNone(queue["items"][0]["proposal"])

    def test_worse_row_is_always_null_even_with_a_matching_set(self):
        item = self._item(cls="worse")
        self._insert_set(
            campaign_id=self.campaign, status="draft",
            items=[self._pause_item(item["entity_id"])],
        )
        queue = self._queue([item])
        self.assertIsNone(queue["items"][0]["proposal"])

    def test_draft_set_counts_with_pending_verification_state(self):
        item = self._item()
        set_id = self._insert_set(
            campaign_id=self.campaign, status="draft",
            items=[self._pause_item(item["entity_id"])],
        )
        proposal = self._queue([item])["items"][0]["proposal"]
        self.assertEqual(proposal, {
            "change_set_id": set_id, "campaign_id": self.campaign, "kind": "pause",
            "status": "draft", "verification_state": "pending", "reason": None,
            "revisit_at": None, "multi": False,
        })

    def test_approved_pending_readback_counts(self):
        item = self._item()
        pause = self._pause_item(item["entity_id"])
        set_id = self._insert_set(campaign_id=self.campaign, status="approved", items=[pause])
        self._insert_action(pause["id"], set_id, self.campaign, item["entity_id"], "pending")
        proposal = self._queue([item])["items"][0]["proposal"]
        self.assertEqual(proposal["status"], "approved")
        self.assertEqual(proposal["verification_state"], "pending")

    def test_confirmed_counts_only_while_entity_still_paused(self):
        entity = external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "ad",
             "native_id": "ad1", "name": "廣告A", "native_status": "PAUSED"},
        )
        self.conn.commit()
        item = self._item(entity_id=entity["id"])
        pause = self._pause_item(entity["id"])
        set_id = self._insert_set(campaign_id=self.campaign, status="approved", items=[pause])
        self._insert_action(pause["id"], set_id, self.campaign, entity["id"], "confirmed")
        proposal = self._queue([item])["items"][0]["proposal"]
        self.assertEqual(proposal["verification_state"], "confirmed")

        # The entity has since been reactivated on the platform -- triage never reads
        # native_status itself, so only this proposal lookup can tell the ad needs a fresh one.
        external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "ad",
             "native_id": "ad1", "name": "廣告A", "native_status": "ACTIVE"},
        )
        self.conn.commit()
        self.assertIsNone(self._queue([item])["items"][0]["proposal"])

    def test_rejected_counts_only_inside_the_current_triage_window(self):
        item = self._item(window_end=date(2026, 1, 7))
        self._insert_set(
            campaign_id=self.campaign, status="rejected",
            items=[self._pause_item(item["entity_id"])],
            decision_reason="先觀察",
            created_at=db.now_utc().replace(year=2026, month=1, day=5),
        )
        proposal = self._queue([item])["items"][0]["proposal"]
        self.assertEqual(proposal["status"], "rejected")
        self.assertEqual(proposal["reason"], "先觀察")

        # Same rejected set, but the window has since moved past it entirely.
        later_item = self._item(window_end=date(2026, 2, 20))
        self.assertIsNone(self._queue([later_item])["items"][0]["proposal"])

    def test_deferred_counts_only_before_revisit_at(self):
        item = self._item()
        self._insert_set(
            campaign_id=self.campaign, status="deferred",
            items=[self._pause_item(item["entity_id"])],
            decision_reason="等一週", revisit_at=db.now_utc() + timedelta(days=7),
        )
        proposal = self._queue([item])["items"][0]["proposal"]
        self.assertEqual(proposal["status"], "deferred")

        past_item = self._item(entity_id="ent_past")
        self._insert_set(
            campaign_id=self.campaign, status="deferred",
            items=[self._pause_item(past_item["entity_id"])],
            decision_reason="等一週", revisit_at=db.now_utc() - timedelta(days=1),
        )
        self.assertIsNone(self._queue([past_item])["items"][0]["proposal"])

    def test_superseded_set_never_counts(self):
        item = self._item()
        self._insert_set(
            campaign_id=self.campaign, status="superseded",
            items=[self._pause_item(item["entity_id"])],
        )
        self.assertIsNone(self._queue([item])["items"][0]["proposal"])

    def test_another_entitys_set_does_not_match(self):
        item = self._item(entity_id="ent_mine")
        self._insert_set(
            campaign_id=self.campaign, status="draft",
            items=[self._pause_item("ent_someone_else")],
        )
        self.assertIsNone(self._queue([item])["items"][0]["proposal"])

    def test_another_campaigns_set_does_not_match(self):
        item = self._item(entity_id="ent_1", campaign_id=self.campaign)
        self._insert_set(
            campaign_id=self.other_campaign, status="draft",
            items=[self._pause_item("ent_1")],
        )
        self.assertIsNone(self._queue([item])["items"][0]["proposal"])

    def test_multi_item_set_is_reported_as_multi(self):
        item = self._item()
        self._insert_set(
            campaign_id=self.campaign, status="draft",
            items=[
                self._pause_item(item["entity_id"]),
                {"id": db.new_id("adx"), "kind": "budget", "target_id": "ent_other",
                 "target": {}, "before": {}, "after": {"daily_amount": 100}, "reason": "x"},
            ],
        )
        proposal = self._queue([item])["items"][0]["proposal"]
        self.assertTrue(proposal["multi"])


class QueueReviewProposalTest(unittest.TestCase):
    """F23-I01: `proposal` on a `worse` row -- against real `ads_review_round`/`ads_change_set`
    rows, inserted directly (same isolation style as `QueueProposalTest`)."""

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
        # `refresh_queue()`, not `get_queue()`: same reason `QueueProposalTest` uses it -- the row
        # has to exist as an open `interrupt` row before `_queue_payload` reports it at all.
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
            "multi": False,
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

    def test_stop_loss_row_unaffected_by_a_matching_review_round(self):
        # Same entity/window a `worse` row would match on -- proves `_queue_payload` branches by
        # `triage.class`, never letting a review round leak into a `stop_loss` row's own proposal.
        self._round(status="ready")
        stop_item = {
            "entity_id": self.entity, "native_id": "n1", "name": "廣告A",
            "campaign_id": self.campaign, "class": "stop_loss",
            "label": triage.LABELS["stop_loss"], "reason_code": "x",
            "window": {"start": date(2026, 1, 1), "end": date(2026, 1, 7), "days": 7,
                       "previous_start": None, "previous_end": None, "extended_from": None},
            "target": {"value": 1}, "current": {}, "previous": {}, "change_pct": None,
            "sample": {},
        }
        self.assertIsNone(self._queue([stop_item])["items"][0]["proposal"])


class ScaleRefreshQueueTest(unittest.TestCase):
    """F25-I01: `scale_budget`/`refresh_creative` rows through the full `refresh_queue`/
    `get_queue` pipeline -- `kind_key`, `scale`/`refresh` payload, category/severity, dedupe/
    supersede (the same generic mechanism `QueuePlumbingTest` already proves for stop_loss/worse
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
            "window": {"start": window_end - timedelta(days=13), "end": window_end, "days": 14,
                       "previous_start": None, "previous_end": None, "extended_from": None},
            "target": {"value": 100, "basis": "own", "result_kind": "purchase", "missing": [],
                       "result_label": "購買"},
            "current": {"cost_per_result": 80}, "previous": {"cost_per_result": 85},
            "change_pct": None, "sample": {},
        }

    @staticmethod
    def _refresh_item(entity_id, campaign_id, window_end, cls, thumbnail_url=None):
        return {
            "entity_id": entity_id, "native_id": entity_id, "name": "廣告",
            "campaign_id": campaign_id, "campaign_name": "活動一", "thumbnail_url": thumbnail_url,
            "class": cls, "label": triage.LABELS[cls], "reason_code": "x",
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

    def test_scale_row_is_idempotent_and_supersedes_across_windows(self):
        w1, w2 = date(2026, 1, 7), date(2026, 1, 8)
        first = self._refresh_queue([self._scale_item(self.ad, self.campaign, w1)])
        first_id = first["items"][0]["id"]
        # Same window again -- no duplicate row.
        again = self._refresh_queue([self._scale_item(self.ad, self.campaign, w1)])
        self.assertEqual(again["items"][0]["id"], first_id)

        second = self._refresh_queue([self._scale_item(self.ad, self.campaign, w2)])
        self.assertEqual(len(second["items"]), 1)
        self.assertNotEqual(second["items"][0]["id"], first_id)
        old_row = self.conn.execute(
            "SELECT status FROM interrupt WHERE id=%s", (first_id,)
        ).fetchone()
        self.assertEqual(old_row["status"], "resolved")

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

    def test_deduped_within_the_same_window_and_superseded_when_it_recovers(self):
        self.set_coverage(self.cutoff - timedelta(days=10), self.cutoff)
        first_row = self._insufficient_rows(
            triage.refresh_queue(self.conn, self.org, self.brand),
        )[0]
        again_row = self._insufficient_rows(
            triage.refresh_queue(self.conn, self.org, self.brand),
        )[0]
        self.assertEqual(again_row["id"], first_row["id"])  # same window -> no duplicate row

        self.set_coverage(self.cutoff - timedelta(days=90), self.cutoff)  # recovers
        recovered = triage.refresh_queue(self.conn, self.org, self.brand)
        self.assertEqual(self._insufficient_rows(recovered), [])
        row = self.conn.execute(
            "SELECT status FROM interrupt WHERE id=%s", (first_row["id"],),
        ).fetchone()
        self.assertEqual(row["status"], "resolved")

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
    def _item(entity_id, campaign_id, *, cls="insufficient", target_value=100, name="廣告"):
        return {
            "entity_id": entity_id, "native_id": entity_id, "name": name,
            "campaign_id": campaign_id, "campaign_name": "活動一", "thumbnail_url": None,
            "class": cls, "label": triage.LABELS[cls], "reason_code": "x",
            "window": {"start": date(2026, 1, 1), "end": date(2026, 1, 7), "days": 7,
                       "previous_start": None, "previous_end": None, "extended_from": None},
            "target": {"value": target_value, "basis": "own", "result_kind": "purchase",
                       "missing": [], "result_label": "購買"},
            "current": {}, "previous": {}, "change_pct": None, "sample": {},
        }

    def _items(self):
        return [
            self._item(self.ad1, self.campaign, name="廣告甲"),
            self._item(self.ad2, self.campaign, name="廣告乙"),
        ]

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
        self.assertEqual(row["severity"], "informational")
        self.assertEqual(
            row["action_url"],
            f"/brands/{self.brand}/ads/campaigns/{self.campaign}/propose/cleanup/{self.campaign}",
        )
        self.assertEqual(row["cleanup"]["campaign_id"], self.campaign)
        self.assertEqual(row["cleanup"]["can_support"], 1)
        self.assertEqual(row["cleanup"]["active_ads"], 2)
        self.assertEqual(len(row["cleanup"]["ads"]), 1)
        self.assertEqual(row["cleanup"]["ads"][0]["entity_id"], self.ad1)  # lowest 7-day spend
        self.assertEqual(row["cleanup"]["ads"][0]["spend_7d"], 70.0)
        self.assertIsNone(row["proposal"])

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
            self._item(self.ad1, self.campaign, name="廣告甲"),
            self._item(self.ad2, self.campaign, name="廣告乙"),
            self._item(third, self.campaign, cls="worse", name="廣告丙"),
        ]
        result = self._refresh(items)
        categories = {r["category"] for r in result["items"]}
        self.assertIn("ads_triage_cleanup", categories)
        self.assertNotIn("ads_triage_refresh_creative", categories)

    def test_cleanup_row_supersedes_once_campaign_returns_within_capacity(self):
        first_id = self._cleanup_row(self._refresh())["id"]

        # Both ads now `no_target` (target unresolved) -- `capacity_view`'s own `can_support`
        # goes null, so the campaign no longer qualifies at all.
        items = [
            self._item(self.ad1, self.campaign, cls="no_target", target_value=None, name="廣告甲"),
            self._item(self.ad2, self.campaign, cls="no_target", target_value=None, name="廣告乙"),
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

    def test_category_registered_with_expected_severity_and_label(self):
        self.assertEqual(
            core_interrupts.CATEGORIES["ads_triage_cleanup"],
            {"severity": "informational", "label": "廣告清理待決定"},
        )


if __name__ == "__main__":
    unittest.main()
