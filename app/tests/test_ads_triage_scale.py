"""app/tests/test_ads_triage_scale.py — F25-I01 falsifiers: program rules A (`scale_budget`) and
B (`refresh_creative`) over the per-ad triage `classify()` already produces.

Both rule functions take an already-classified `classified_items_by_campaign` dict, so items are
built by hand here (same isolation style as `test_ads_triage_queue.py::QueuePlumbingTest`) --
`classify()`'s own class/reason-code logic is exhaustively covered by `test_ads_triage.py`, not
re-proven here. Rule A's owner lookup reads real `ads_external_entity` rows (it has to: items
never carry `parent_native_id`, feature Decisions "Gaps kept honest"), so every ad/adset/campaign
entity in a scenario is inserted through `external.upsert_entity`, and the classify item's
`entity_id` is that inserted ad row's own `id` (never a literal like `"ent_1"`).
"""

import math
import unittest
from datetime import date, timedelta

from app.ads import external_repository as external
from app.ads import triage, triage_scale
from app.brand_intelligence import repository as brands
from app.core import db

WINDOW_END = date(2026, 1, 7)


class _CandidateFixture(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="規則測試品牌", actor="test", client_name=None,
        )["id"]
        self.campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="活動一",
        )["id"]
        self.conn.commit()

    def campaign_entity(self, *, native_id="c1", budget_type="unknown", budget_amount=None,
                        currency="TWD", name="活動一"):
        entity = external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "campaign",
             "native_id": native_id, "name": name, "budget_type": budget_type,
             "budget_amount": budget_amount, "currency": currency},
        )
        self.conn.commit()
        return entity

    def adset_entity(self, *, native_id, campaign_native_id="c1", budget_type="daily",
                     budget_amount=1000, currency="TWD", name="廣告組"):
        entity = external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "adset",
             "native_id": native_id, "name": name, "budget_type": budget_type,
             "budget_amount": budget_amount, "currency": currency,
             "parent_native_kind": "campaign", "parent_native_id": campaign_native_id},
        )
        self.conn.commit()
        return entity

    def ad_entity(self, *, native_id, parent_native_kind="campaign", parent_native_id="c1",
                 name="廣告", native_status=None):
        entity = external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "ad",
             "native_id": native_id, "name": name, "native_status": native_status,
             "parent_native_kind": parent_native_kind, "parent_native_id": parent_native_id},
        )
        self.conn.commit()
        return entity

    @staticmethod
    def item(*, entity_id, cls="flat", cost=80, previous=90, target_value=100,
             window_end=WINDOW_END, window_days=14, campaign_id=None, campaign_name="活動一",
             reason_code="cost_per_result_flat", thumbnail_url=None):
        return {
            "entity_id": entity_id, "native_id": entity_id, "name": "廣告",
            "campaign_id": campaign_id, "campaign_name": campaign_name,
            "thumbnail_url": thumbnail_url,
            "class": cls, "label": triage.LABELS[cls], "reason_code": reason_code,
            "window": {"start": window_end - timedelta(days=window_days - 1), "end": window_end,
                       "days": window_days, "previous_start": None, "previous_end": None,
                       "extended_from": None},
            "target": {"value": target_value, "basis": "own", "result_kind": "purchase",
                       "missing": [], "result_label": "購買"},
            "current": {"cost_per_result": cost}, "previous": {"cost_per_result": previous},
            "change_pct": None, "sample": {},
        }


class ScaleCandidatesTest(_CandidateFixture):
    """Rule A -- feature Decisions "Rule A"."""

    @staticmethod
    def month_view(available=500.0, reserved=0.0):
        return lambda additional: {"available": available, "reserved_increases": reserved}

    def _by_campaign(self, items):
        return {self.campaign: items}

    def candidates(self, items, *, native_status=None, month_view=None):
        return triage_scale.scale_candidates(
            self.conn, self.org, self.brand, self._by_campaign(items),
            native_status or {}, month_view or self.month_view(),
        )

    def test_positive_flat_and_better_owner_by_campaign_budget(self):
        self.campaign_entity(budget_type="daily", budget_amount=1000)
        ad1 = self.ad_entity(native_id="ad1")["id"]
        ad2 = self.ad_entity(native_id="ad2")["id"]
        items = [
            self.item(entity_id=ad1, cls="better", cost=70, previous=95, campaign_id=self.campaign),
            self.item(entity_id=ad2, cls="flat", cost=85, previous=88, campaign_id=self.campaign),
        ]
        candidates = self.candidates(items)
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate["scale"]["from"], 1000.0)
        self.assertEqual(candidate["scale"]["to"], 1200)  # ceil(1000*1.2)
        self.assertEqual(candidate["scale"]["owner"]["ads_count"], 2)
        # A `better` ad is not required, but is preferred as the row's own triage item when one
        # exists.
        self.assertEqual(candidate["triage"]["entity_id"], ad1)
        self.assertEqual(candidate["scale"]["cost_per_result"], 70)
        self.assertEqual(candidate["scale"]["previous_cost_per_result"], 95)
        self.assertEqual(candidate["scale"]["month"]["available"], 500.0)
        self.assertEqual(candidate["scale"]["month"]["extra_needed"], 0.0)

    def test_all_flat_owner_qualifies_without_a_better_ad(self):
        self.campaign_entity(budget_type="daily", budget_amount=500)
        ad1 = self.ad_entity(native_id="ad1")["id"]
        items = [self.item(entity_id=ad1, cls="flat", cost=90, previous=92,
                           campaign_id=self.campaign)]
        candidates = self.candidates(items)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["triage"]["entity_id"], ad1)

    def test_to_is_ceil_of_from_times_1_2(self):
        self.campaign_entity(budget_type="daily", budget_amount=999)
        ad1 = self.ad_entity(native_id="ad1")["id"]
        items = [self.item(entity_id=ad1, cls="flat", campaign_id=self.campaign)]
        candidates = self.candidates(items)
        self.assertEqual(candidates[0]["scale"]["to"], math.ceil(999 * 1.2))

    def test_a_worse_ad_among_active_ads_blocks_the_owner(self):
        self.campaign_entity(budget_type="daily", budget_amount=1000)
        ad1 = self.ad_entity(native_id="ad1")["id"]
        ad2 = self.ad_entity(native_id="ad2")["id"]
        items = [
            self.item(entity_id=ad1, cls="flat", campaign_id=self.campaign),
            self.item(entity_id=ad2, cls="worse", campaign_id=self.campaign),
        ]
        self.assertEqual(self.candidates(items), [])

    def test_insufficient_ad_among_active_ads_blocks_the_owner(self):
        self.campaign_entity(budget_type="daily", budget_amount=1000)
        ad1 = self.ad_entity(native_id="ad1")["id"]
        ad2 = self.ad_entity(native_id="ad2")["id"]
        items = [
            self.item(entity_id=ad1, cls="flat", campaign_id=self.campaign),
            self.item(entity_id=ad2, cls="insufficient", reason_code="below_sample_gate",
                     campaign_id=self.campaign),
        ]
        self.assertEqual(self.candidates(items), [])

    def test_current_cost_above_target_blocks_the_owner(self):
        self.campaign_entity(budget_type="daily", budget_amount=1000)
        ad1 = self.ad_entity(native_id="ad1")["id"]
        items = [self.item(entity_id=ad1, cls="flat", cost=101, previous=95, target_value=100,
                           campaign_id=self.campaign)]
        self.assertEqual(self.candidates(items), [])

    def test_previous_cost_above_target_blocks_the_owner(self):
        self.campaign_entity(budget_type="daily", budget_amount=1000)
        ad1 = self.ad_entity(native_id="ad1")["id"]
        items = [self.item(entity_id=ad1, cls="flat", cost=90, previous=101, target_value=100,
                           campaign_id=self.campaign)]
        self.assertEqual(self.candidates(items), [])

    def test_lifetime_budget_owner_never_qualifies(self):
        self.campaign_entity(budget_type="lifetime", budget_amount=30000)
        ad1 = self.ad_entity(native_id="ad1")["id"]
        items = [self.item(entity_id=ad1, cls="flat", campaign_id=self.campaign)]
        self.assertEqual(self.candidates(items), [])

    def test_unknown_budget_owner_never_qualifies(self):
        self.campaign_entity(budget_type="unknown", budget_amount=None)
        ad1 = self.ad_entity(native_id="ad1")["id"]
        items = [self.item(entity_id=ad1, cls="flat", campaign_id=self.campaign)]
        self.assertEqual(self.candidates(items), [])

    def test_no_target_blocks_the_owner(self):
        self.campaign_entity(budget_type="daily", budget_amount=1000)
        ad1 = self.ad_entity(native_id="ad1")["id"]
        items = [self.item(entity_id=ad1, cls="no_target", target_value=None,
                           campaign_id=self.campaign)]
        self.assertEqual(self.candidates(items), [])

    def test_month_available_null_blocks_the_row(self):
        self.campaign_entity(budget_type="daily", budget_amount=1000)
        ad1 = self.ad_entity(native_id="ad1")["id"]
        items = [self.item(entity_id=ad1, cls="flat", campaign_id=self.campaign)]
        candidates = self.candidates(items, month_view=self.month_view(available=None))
        self.assertEqual(candidates, [])

    def test_month_available_negative_blocks_the_row(self):
        self.campaign_entity(budget_type="daily", budget_amount=1000)
        ad1 = self.ad_entity(native_id="ad1")["id"]
        items = [self.item(entity_id=ad1, cls="flat", campaign_id=self.campaign)]
        candidates = self.candidates(items, month_view=self.month_view(available=-0.01))
        self.assertEqual(candidates, [])

    def test_month_available_exactly_zero_is_allowed(self):
        self.campaign_entity(budget_type="daily", budget_amount=1000)
        ad1 = self.ad_entity(native_id="ad1")["id"]
        items = [self.item(entity_id=ad1, cls="flat", campaign_id=self.campaign)]
        candidates = self.candidates(items, month_view=self.month_view(available=0.0))
        self.assertEqual(len(candidates), 1)

    def test_paused_ad_never_blocks_the_owner(self):
        """A paused ad from the stop-loss flow must not block the owner forever (feature
        Decisions)."""
        self.campaign_entity(budget_type="daily", budget_amount=1000)
        paused = self.ad_entity(native_id="ad1")["id"]
        active = self.ad_entity(native_id="ad2")["id"]
        items = [
            self.item(entity_id=paused, cls="stop_loss", campaign_id=self.campaign),
            self.item(entity_id=active, cls="flat", campaign_id=self.campaign),
        ]
        candidates = self.candidates(items, native_status={paused: "PAUSED"})
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["scale"]["owner"]["ads_count"], 2)

    def test_adset_paused_ad_never_blocks_the_owner(self):
        """F26-I01: `ADSET_PAUSED` (the ad's own parent adset paused on the platform) now comes
        from the shared `ad_status.CLOSED_STATUSES` (five values) rather than this file's old
        three-value set -- same "never blocks the owner" rule `test_paused_ad_never_blocks_the_
        owner` proves for `PAUSED`."""
        self.campaign_entity(budget_type="daily", budget_amount=1000)
        adset_paused = self.ad_entity(native_id="ad1")["id"]
        active = self.ad_entity(native_id="ad2")["id"]
        items = [
            self.item(entity_id=adset_paused, cls="worse", campaign_id=self.campaign),
            self.item(entity_id=active, cls="flat", campaign_id=self.campaign),
        ]
        candidates = self.candidates(items, native_status={adset_paused: "ADSET_PAUSED"})
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["scale"]["owner"]["ads_count"], 2)

    def test_owner_with_only_paused_ads_never_qualifies(self):
        self.campaign_entity(budget_type="daily", budget_amount=1000)
        ad1 = self.ad_entity(native_id="ad1")["id"]
        items = [self.item(entity_id=ad1, cls="flat", campaign_id=self.campaign)]
        candidates = self.candidates(items, native_status={ad1: "PAUSED"})
        self.assertEqual(candidates, [])

    def test_adset_budget_owner_used_when_adset_carries_the_budget(self):
        self.campaign_entity(budget_type="unknown", budget_amount=None)
        adset = self.adset_entity(native_id="as1", budget_type="daily", budget_amount=300)
        ad1 = self.ad_entity(native_id="ad1", parent_native_kind="adset",
                             parent_native_id="as1")["id"]
        items = [self.item(entity_id=ad1, cls="flat", campaign_id=self.campaign)]
        candidates = self.candidates(items)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["scale"]["owner"]["id"], adset["id"])
        self.assertEqual(candidates[0]["scale"]["owner"]["native_kind"], "adset")

    def test_falls_back_to_campaign_owner_when_the_adset_carries_no_budget(self):
        self.campaign_entity(budget_type="daily", budget_amount=800)
        self.adset_entity(native_id="as1", budget_type="unknown", budget_amount=None)
        ad1 = self.ad_entity(native_id="ad1", parent_native_kind="adset",
                             parent_native_id="as1")["id"]
        items = [self.item(entity_id=ad1, cls="flat", campaign_id=self.campaign)]
        candidates = self.candidates(items)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["scale"]["owner"]["native_kind"], "campaign")

    def test_month_view_called_at_most_once_per_qualifying_owner_plus_a_baseline(self):
        self.campaign_entity(budget_type="daily", budget_amount=1000)
        ad1 = self.ad_entity(native_id="ad1")["id"]
        items = [self.item(entity_id=ad1, cls="flat", campaign_id=self.campaign)]
        calls = []

        def month_view(additional):
            calls.append(additional)
            return {"available": 500.0, "reserved_increases": 0.0}

        self.candidates(items, month_view=month_view)
        self.assertEqual(len(calls), 2)  # one baseline (empty) + one with the proposed item
        self.assertEqual(calls[0], [])
        self.assertEqual(calls[1][0]["kind"], "budget")

    def test_month_view_never_called_when_no_owner_qualifies(self):
        self.campaign_entity(budget_type="daily", budget_amount=1000)
        ad1 = self.ad_entity(native_id="ad1")["id"]
        items = [self.item(entity_id=ad1, cls="worse", campaign_id=self.campaign)]
        calls = []

        def month_view(additional):
            calls.append(additional)
            return {"available": 500.0, "reserved_increases": 0.0}

        self.candidates(items, month_view=month_view)
        self.assertEqual(calls, [])


class RefreshCandidatesTest(_CandidateFixture):
    """Rule B -- feature Decisions "Rule B"."""

    def candidates(self, items, *, native_status=None):
        by_campaign = {self.campaign: items}
        return triage_scale.refresh_candidates(by_campaign, native_status or {})

    def _ad(self, native_id):
        # No parent set -- Rule B never reads the parent chain (only Rule A's owner lookup does),
        # so these ads skip the FK a `parent_native_id` would otherwise require against a
        # campaign-root entity this class never creates.
        return self.ad_entity(native_id=native_id, parent_native_kind=None,
                              parent_native_id=None)["id"]

    def test_positive_two_readable_of_three_active(self):
        a, b, c = self._ad("a1"), self._ad("a2"), self._ad("a3")
        items = [
            self.item(entity_id=a, cls="worse", campaign_id=self.campaign,
                     thumbnail_url="https://x/1.jpg"),
            self.item(entity_id=b, cls="flat", campaign_id=self.campaign),
            self.item(entity_id=c, cls="insufficient", reason_code="below_sample_gate",
                     campaign_id=self.campaign),
        ]
        candidates = self.candidates(items)
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate["refresh"]["readable_count"], 2)
        self.assertEqual(candidate["refresh"]["classified_count"], 3)
        self.assertEqual(candidate["triage"]["entity_id"], a)  # first readable, in order
        self.assertEqual(candidate["refresh"]["thumbnails"], ["https://x/1.jpg", None, None])

    def test_two_readable_of_two_total_ads_does_not_raise_a_row(self):
        a, b = self._ad("a1"), self._ad("a2")
        items = [
            self.item(entity_id=a, cls="worse", campaign_id=self.campaign),
            self.item(entity_id=b, cls="flat", campaign_id=self.campaign),
        ]
        self.assertEqual(self.candidates(items), [])

    def test_three_readable_of_three_does_not_raise_a_row(self):
        a, b, c = self._ad("a1"), self._ad("a2"), self._ad("a3")
        items = [
            self.item(entity_id=a, cls="worse", campaign_id=self.campaign),
            self.item(entity_id=b, cls="flat", campaign_id=self.campaign),
            self.item(entity_id=c, cls="better", campaign_id=self.campaign),
        ]
        self.assertEqual(self.candidates(items), [])

    def test_any_needs_resync_ad_skips_the_whole_campaign(self):
        a, b, c = self._ad("a1"), self._ad("a2"), self._ad("a3")
        items = [
            self.item(entity_id=a, cls="worse", campaign_id=self.campaign),
            self.item(entity_id=b, cls="flat", campaign_id=self.campaign),
            self.item(entity_id=c, cls="insufficient", reason_code="needs_resync",
                     campaign_id=self.campaign),
        ]
        self.assertEqual(self.candidates(items), [])

    def test_no_target_skips_the_campaign(self):
        a, b, c = self._ad("a1"), self._ad("a2"), self._ad("a3")
        items = [
            self.item(entity_id=a, cls="no_target", target_value=None, campaign_id=self.campaign),
            self.item(entity_id=b, cls="no_target", target_value=None, campaign_id=self.campaign),
            self.item(entity_id=c, cls="no_target", target_value=None, campaign_id=self.campaign),
        ]
        self.assertEqual(self.candidates(items), [])

    def test_paused_ads_excluded_from_both_counts(self):
        a, b, c, d = self._ad("a1"), self._ad("a2"), self._ad("a3"), self._ad("a4")
        items = [
            self.item(entity_id=a, cls="worse", campaign_id=self.campaign),
            self.item(entity_id=b, cls="flat", campaign_id=self.campaign),
            self.item(entity_id=c, cls="insufficient", reason_code="below_sample_gate",
                     campaign_id=self.campaign),
            self.item(entity_id=d, cls="worse", campaign_id=self.campaign),
        ]
        # d is paused -- active becomes {a,b,c} (still meets the >=3 gate), readable becomes
        # {a,b} (2, at the gate) instead of {a,b,d} (3, over it).
        candidates = self.candidates(items, native_status={d: "PAUSED"})
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["refresh"]["classified_count"], 3)
        self.assertEqual(candidates[0]["refresh"]["readable_count"], 2)

    def test_adset_paused_ads_excluded_too(self):
        """F26-I01: same exclusion as `test_paused_ads_excluded_from_both_counts`, but for
        `ADSET_PAUSED` -- only reachable now that the shared `ad_status.CLOSED_STATUSES` (five
        values) replaces this file's old three-value set."""
        a, b, c, d = self._ad("a1"), self._ad("a2"), self._ad("a3"), self._ad("a4")
        items = [
            self.item(entity_id=a, cls="worse", campaign_id=self.campaign),
            self.item(entity_id=b, cls="flat", campaign_id=self.campaign),
            self.item(entity_id=c, cls="insufficient", reason_code="below_sample_gate",
                     campaign_id=self.campaign),
            self.item(entity_id=d, cls="worse", campaign_id=self.campaign),
        ]
        candidates = self.candidates(items, native_status={d: "ADSET_PAUSED"})
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["refresh"]["classified_count"], 3)
        self.assertEqual(candidates[0]["refresh"]["readable_count"], 2)

    def test_all_insufficient_still_raises_with_first_classified_as_triage(self):
        a, b, c = self._ad("a1"), self._ad("a2"), self._ad("a3")
        items = [
            self.item(entity_id=a, cls="insufficient", reason_code="below_sample_gate",
                     campaign_id=self.campaign),
            self.item(entity_id=b, cls="insufficient", reason_code="below_sample_gate",
                     campaign_id=self.campaign),
            self.item(entity_id=c, cls="insufficient", reason_code="below_sample_gate",
                     campaign_id=self.campaign),
        ]
        candidates = self.candidates(items)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["refresh"]["readable_count"], 0)
        self.assertEqual(candidates[0]["triage"]["entity_id"], a)  # first classified, in order

    def test_thumbnails_capped_at_four(self):
        ids = [self._ad(f"a{i}") for i in range(5)]
        items = [
            self.item(entity_id=eid, cls="insufficient", reason_code="below_sample_gate",
                     campaign_id=self.campaign, thumbnail_url=f"https://x/{i}.jpg")
            for i, eid in enumerate(ids)
        ]
        candidates = self.candidates(items)
        self.assertEqual(len(candidates[0]["refresh"]["thumbnails"]), 4)


if __name__ == "__main__":
    unittest.main()
