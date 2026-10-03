"""app/tests/test_ads_visual_learning.py — F07-I11 falsifiers: 結案時比對「這次選中的圖」
的指紋跟成效,寫成 `source_track="visual"` 的學習——同一受眾裡兩支廣告只差一個維度時寫一條
那個維度的學習;第二次同方向升級成 `likely`;第三次反過來贏時,舊贏家最新一條被降級,較舊的
那條仍在;樣本小照樣比、樣本大小寫在學習上(F48-I02);購買數沒追蹤或看不出差別時寫「看不出」
但不降級任何人;沒有兩支可比廣告(不同受眾、
沒被採用)時不寫任何學習。全部透過 `closeout.close()` 走(跟 `test_ads_closeout.py` 同一個
入口),`workbench.briefs_for_source`/`adopted_output` 用 `mock.patch.object` 假造 §5.8 形狀
的列,不碰 workbench 內部或任何 `workbench_*` 表。
"""

import unittest
from datetime import timedelta
from unittest import mock

from app.ads import closeout, live_creative, plan
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.core import settings as coresettings
from app.shared import web
from app.tests.fixtures.ads_external import outcome_seed

ACTOR = "測試員"

_FILLER_COORDS = {"pain": "p1", "angle": "a1", "hook": "h1", "proof": "pr1", "offer": "o1",
                   "format": "f1"}


def _fp(*, look="phone_raw", device="d1", layout="l1", subject_role="s1", persuasion="pe1"):
    values = {"look": look, "device": device, "layout": layout, "subject_role": subject_role,
              "persuasion": persuasion}
    return {dim: {"key": key, "label": f"{key}標籤"} for dim, key in values.items()}


class VisualLearningTestBase(unittest.TestCase):
    def setUp(self):
        self.conn = web.conn
        self.org_id = coredb.DEV_ORG_ID
        self.brand_id = bi_repo.create_brand(
            self.conn, org_id=self.org_id, name="測試品牌：視覺學習", client_name=None,
            actor=ACTOR,
        )["id"]
        self.today = coresettings.today_for_org(self.conn, org_id=self.org_id)
        self.conn.commit()

    def _campaign(self, *, target=999999.0, start_date=None, end_date=None) -> dict:
        start_date = start_date or (self.today - timedelta(days=2))
        end_date = end_date or self.today
        campaign = ads_repo.create_campaign(self.conn, self.org_id, self.brand_id, {
            "name": f"測試 視覺學習 {start_date}", "goal_text": "衝一波", "objective": "購買",
            "target_cost": target,
            "start_date": start_date, "end_date": end_date, "status": "live",
        }, created_by=ACTOR)
        # F37 Contract Q: closeout refuses an unread window; the window was read in full.
        outcome_seed.set_coverage(
            self.conn, self.org_id, self.brand_id, campaign["id"], start_date, end_date,
        )
        self.conn.commit()
        return campaign

    def _group(self, campaign_id: str) -> dict:
        return plan.create_group(
            self.conn, self.org_id, self.brand_id, campaign_id, name="投放組", role="new",
            daily_budget=500,
        )

    def _ad(self, campaign_id: str, group_id: str, *, audience_key: str, name: str) -> dict:
        coordinates = {"audience": audience_key, **_FILLER_COORDS}
        return plan.create_ad(
            self.conn, self.org_id, self.brand_id, campaign_id, group_id,
            name=name, coordinates=coordinates,
        )

    def _group_outcome(self, campaign_id: str, group_id: str, day, *, spend: float,
                        purchases: int, revenue: float) -> None:
        outcome_seed.seed_day(
            self.conn, self.org_id, self.brand_id, campaign_id, "group", group_id, day,
            spend=spend, impressions=100, clicks=10, purchases=purchases, revenue=revenue,
            source="simulated",
        )
        self.conn.commit()

    def _ad_outcome(self, campaign_id: str, ad_id: str, day, *, spend: float, purchases: int,
                     revenue: float) -> None:
        outcome_seed.seed_day(
            self.conn, self.org_id, self.brand_id, campaign_id, "ad", ad_id, day,
            spend=spend, impressions=100, clicks=10, purchases=purchases, revenue=revenue,
            source="simulated",
        )
        self.conn.commit()

    def _spread(self, campaign_id: str, ad_id: str, start, days: int, *, daily_spend: float,
                daily_purchases: int, daily_revenue: float) -> None:
        for offset in range(days):
            self._ad_outcome(
                campaign_id, ad_id, start + timedelta(days=offset), spend=daily_spend,
                purchases=daily_purchases, revenue=daily_revenue,
            )

    def _patch_workbench(self, fingerprints: dict, *, unadopted: frozenset = frozenset(),
                          snapshots: dict | None = None):
        """`snapshots`: `ad_id -> coordinates_snapshot_json` of that ad's dispatched set;
        an ad without one gets a set without a snapshot (its current coordinates count)."""
        briefs = {
            ad_id: {
                "id": f"brief-{ad_id}", "source_ref": {"ads_ad_id": ad_id},
                "coordinates_snapshot_json": (snapshots or {}).get(ad_id),
            }
            for ad_id in fingerprints
        }
        brief_by_id = {b["id"]: ad_id for ad_id, b in briefs.items()}

        def fake_briefs_for_source(conn, org_id, brand_id, source_kind, source_ref):
            return list(briefs.values())

        def fake_adopted_output(conn, org_id, brand_id, brief_id, part):
            ad_id = brief_by_id[brief_id]
            return {
                "is_adopted": ad_id not in unadopted,
                "body_json": {"fingerprint": fingerprints[ad_id]},
            }

        p1 = mock.patch.object(
            live_creative.workbench, "briefs_for_source", side_effect=fake_briefs_for_source,
        )
        p2 = mock.patch.object(
            live_creative.workbench, "adopted_output", side_effect=fake_adopted_output,
        )
        p1.start()
        self.addCleanup(p1.stop)
        p2.start()
        self.addCleanup(p2.stop)


class LookDimensionWritesOneLearningTest(VisualLearningTestBase):
    def test_two_looks_same_audience_writes_one_look_learning(self):
        campaign = self._campaign()
        group = self._group(campaign["id"])
        ad_a = self._ad(campaign["id"], group["id"], audience_key="cold_unaware", name="A")
        ad_b = self._ad(campaign["id"], group["id"], audience_key="cold_unaware", name="B")
        start = campaign["start_date"]
        self._spread(campaign["id"], ad_a["id"], start, 3, daily_spend=100.0,
                     daily_purchases=10, daily_revenue=200.0)
        self._spread(campaign["id"], ad_b["id"], start, 3, daily_spend=100.0,
                     daily_purchases=5, daily_revenue=200.0)
        self._group_outcome(campaign["id"], group["id"], start, spend=600.0, purchases=45,
                             revenue=800.0)
        self._patch_workbench({
            ad_a["id"]: _fp(look="phone_raw"),
            ad_b["id"]: _fp(look="studio_hero"),
        })

        closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        visual_rows = bi_repo.list_learnings(self.conn, self.brand_id, source_track="visual")
        self.assertEqual(len(visual_rows), 1)
        row = visual_rows[0]
        self.assertIn("visual；audience=cold_unaware；look=phone_raw", row["applicability_scope"])
        self.assertEqual(row["confidence"], "observed")
        self.assertIn("phone_raw標籤", row["learning_text"])
        self.assertIn("studio_hero標籤", row["learning_text"])
        self.assertIn("這是相關，不代表是風格造成。", row["learning_text"])


class AudienceEditedAfterDispatchTest(VisualLearningTestBase):
    """F31-I05 Contract O (item 6 ruling): coordinates stay editable after dispatch, and the
    closeout strata read the audience snapshot the images were made for."""

    def test_strata_use_the_dispatch_audience_not_the_edited_one(self):
        campaign = self._campaign()
        group = self._group(campaign["id"])
        ad_a = self._ad(campaign["id"], group["id"], audience_key="cold_unaware", name="A")
        ad_b = self._ad(campaign["id"], group["id"], audience_key="cold_unaware", name="B")
        # Both sets were dispatched for cold_unaware (the two stored snapshot shapes).
        snapshots = {
            ad_a["id"]: {"audience": "cold_unaware", **_FILLER_COORDS},
            ad_b["id"]: {"audience": {"key": "cold_unaware", "label": "冷受眾"}},
        }
        # Editing stays allowed after dispatch.
        plan.update_ad(
            self.conn, self.org_id, self.brand_id, ad_b["id"],
            {"coordinates": {"audience": "warm_retarget"}}, actor=ACTOR,
        )
        self.conn.commit()
        start = campaign["start_date"]
        self._spread(campaign["id"], ad_a["id"], start, 3, daily_spend=100.0,
                     daily_purchases=10, daily_revenue=200.0)
        self._spread(campaign["id"], ad_b["id"], start, 3, daily_spend=100.0,
                     daily_purchases=5, daily_revenue=200.0)
        self._group_outcome(campaign["id"], group["id"], start, spend=600.0, purchases=45,
                             revenue=800.0)
        self._patch_workbench(
            {ad_a["id"]: _fp(look="phone_raw"), ad_b["id"]: _fp(look="studio_hero")},
            snapshots=snapshots,
        )

        closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        rows = bi_repo.list_learnings(self.conn, self.brand_id, source_track="visual")
        self.assertEqual(
            [r["applicability_scope"] for r in rows],
            ["visual；audience=cold_unaware；look=phone_raw"],
        )
        # The coordinate edit itself was kept.
        self.assertEqual(
            ads_repo.get_ad(self.conn, self.org_id, self.brand_id, ad_b["id"])["audience_key"],
            "warm_retarget",
        )

    def test_an_ad_without_a_dispatch_snapshot_uses_its_current_audience(self):
        campaign = self._campaign()
        group = self._group(campaign["id"])
        ad_a = self._ad(campaign["id"], group["id"], audience_key="cold_unaware", name="A")
        ad_b = self._ad(campaign["id"], group["id"], audience_key="cold_unaware", name="B")
        plan.update_ad(
            self.conn, self.org_id, self.brand_id, ad_b["id"],
            {"coordinates": {"audience": "warm_retarget"}}, actor=ACTOR,
        )
        self.conn.commit()
        start = campaign["start_date"]
        for ad, purchases in ((ad_a, 10), (ad_b, 5)):
            self._spread(campaign["id"], ad["id"], start, 3, daily_spend=100.0,
                         daily_purchases=purchases, daily_revenue=200.0)
        self._patch_workbench(
            {ad_a["id"]: _fp(look="phone_raw"), ad_b["id"]: _fp(look="studio_hero")},
        )

        closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        # Current audiences differ, so the two ads are not one stratum.
        self.assertEqual(
            bi_repo.list_learnings(self.conn, self.brand_id, source_track="visual"), [],
        )


class SecondCampaignSameWinnerUpgradesTest(VisualLearningTestBase):
    def _run(self, *, look_a="phone_raw", look_b="studio_hero", winner_purchases=10,
              loser_purchases=5):
        campaign = self._campaign()
        group = self._group(campaign["id"])
        ad_a = self._ad(campaign["id"], group["id"], audience_key="cold_unaware", name="A")
        ad_b = self._ad(campaign["id"], group["id"], audience_key="cold_unaware", name="B")
        start = campaign["start_date"]
        self._spread(campaign["id"], ad_a["id"], start, 3, daily_spend=100.0,
                     daily_purchases=winner_purchases, daily_revenue=200.0)
        self._spread(campaign["id"], ad_b["id"], start, 3, daily_spend=100.0,
                     daily_purchases=loser_purchases, daily_revenue=200.0)
        self._group_outcome(campaign["id"], group["id"], start, spend=600.0, purchases=45,
                             revenue=800.0)
        self._patch_workbench({ad_a["id"]: _fp(look=look_a), ad_b["id"]: _fp(look=look_b)})
        closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)
        return campaign

    def test_same_winner_twice_makes_it_likely_then_flipping_expires_the_newest(self):
        self._run()  # phone_raw wins, observed
        self._run()  # phone_raw wins again, likely

        rows = bi_repo.list_learnings(self.conn, self.brand_id, source_track="visual")
        phone_rows = [r for r in rows if r["applicability_scope"].endswith("look=phone_raw")]
        self.assertEqual(len(phone_rows), 2)
        confidences = sorted(r["confidence"] for r in phone_rows)
        self.assertEqual(confidences, ["likely", "observed"])

        # 第三次反過來,studio_hero 贏
        self._run(look_a="studio_hero", look_b="phone_raw")

        all_rows = bi_repo.list_learnings(
            self.conn, self.brand_id, source_track="visual", include_expired=True,
        )
        phone_rows = [r for r in all_rows if r["applicability_scope"].endswith("look=phone_raw")]
        studio_rows = [r for r in all_rows if r["applicability_scope"].endswith("look=studio_hero")]
        self.assertEqual(len(studio_rows), 1)
        self.assertEqual(studio_rows[0]["confidence"], "observed")
        self.assertEqual(len(phone_rows), 2)
        expired = [r for r in phone_rows if r["expired"]]
        non_expired = [r for r in phone_rows if not r["expired"]]
        self.assertEqual(len(expired), 1)
        self.assertEqual(len(non_expired), 1)
        self.assertEqual(expired[0]["confidence"], "likely")
        self.assertEqual(non_expired[0]["confidence"], "observed")

        # 第四次,phone_raw 再贏一次——只剩一條沒過期的舊 phone_raw 學習,新的一條該是
        # likely（1 條倖存 + 這條 = 2）,不是 validated（要 3 條才到 validated）。
        self._run()

        all_rows = bi_repo.list_learnings(
            self.conn, self.brand_id, source_track="visual", include_expired=True,
        )
        phone_rows = [r for r in all_rows if r["applicability_scope"].endswith("look=phone_raw")]
        self.assertEqual(len(phone_rows), 3)
        non_expired = [r for r in phone_rows if not r["expired"]]
        self.assertEqual(len(non_expired), 2)
        self.assertEqual(sorted(r["confidence"] for r in non_expired), ["likely", "observed"])


class DeviceOnlyDifferenceWritesDeviceLearningTest(VisualLearningTestBase):
    def test_ads_differing_in_device_only_writes_one_device_learning(self):
        campaign = self._campaign()
        group = self._group(campaign["id"])
        ad_a = self._ad(campaign["id"], group["id"], audience_key="cold_unaware", name="A")
        ad_b = self._ad(campaign["id"], group["id"], audience_key="cold_unaware", name="B")
        start = campaign["start_date"]
        self._spread(campaign["id"], ad_a["id"], start, 3, daily_spend=100.0,
                     daily_purchases=10, daily_revenue=200.0)
        self._spread(campaign["id"], ad_b["id"], start, 3, daily_spend=100.0,
                     daily_purchases=5, daily_revenue=200.0)
        self._group_outcome(campaign["id"], group["id"], start, spend=600.0, purchases=45,
                             revenue=800.0)
        self._patch_workbench({
            ad_a["id"]: _fp(device="close_up"),
            ad_b["id"]: _fp(device="wide_shot"),
        })

        closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        visual_rows = bi_repo.list_learnings(self.conn, self.brand_id, source_track="visual")
        self.assertEqual(len(visual_rows), 1)
        self.assertIn("device=close_up", visual_rows[0]["applicability_scope"])
        self.assertIn("視覺手法", visual_rows[0]["learning_text"])


class PersuasionOnlyDifferenceWritesPersuasionLearningTest(VisualLearningTestBase):
    def test_ads_differing_in_persuasion_only_writes_one_persuasion_learning(self):
        campaign = self._campaign()
        group = self._group(campaign["id"])
        ad_a = self._ad(campaign["id"], group["id"], audience_key="cold_unaware", name="A")
        ad_b = self._ad(campaign["id"], group["id"], audience_key="cold_unaware", name="B")
        start = campaign["start_date"]
        self._spread(campaign["id"], ad_a["id"], start, 3, daily_spend=100.0,
                     daily_purchases=10, daily_revenue=200.0)
        self._spread(campaign["id"], ad_b["id"], start, 3, daily_spend=100.0,
                     daily_purchases=5, daily_revenue=200.0)
        self._group_outcome(campaign["id"], group["id"], start, spend=600.0, purchases=45,
                             revenue=800.0)
        self._patch_workbench({
            ad_a["id"]: _fp(persuasion="proof_number"),
            ad_b["id"]: _fp(persuasion="urgency"),
        })

        closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        visual_rows = bi_repo.list_learnings(self.conn, self.brand_id, source_track="visual")
        self.assertEqual(len(visual_rows), 1)
        self.assertIn("persuasion=proof_number", visual_rows[0]["applicability_scope"])
        self.assertIn("說服元素", visual_rows[0]["learning_text"])


class LowSampleIsComparedAndShownTest(VisualLearningTestBase):
    """F48-I02 (Contract R): a small sample is compared and written with its bucket shown
    (`sample_size` 低), never skipped; only an untracked purchase count is left out."""

    def _close_low_sample_campaign(self):
        campaign = self._campaign()
        group = self._group(campaign["id"])
        ad_a = self._ad(campaign["id"], group["id"], audience_key="cold_unaware", name="A")
        ad_b = self._ad(campaign["id"], group["id"], audience_key="cold_unaware", name="B")
        start = campaign["start_date"]
        self._ad_outcome(campaign["id"], ad_a["id"], start, spend=100.0, purchases=2,
                          revenue=100.0)
        self._ad_outcome(campaign["id"], ad_b["id"], start, spend=100.0, purchases=1,
                          revenue=100.0)
        self._group_outcome(campaign["id"], group["id"], start, spend=200.0, purchases=3,
                             revenue=200.0)
        self._patch_workbench({
            ad_a["id"]: _fp(look="phone_raw"),
            ad_b["id"]: _fp(look="studio_hero"),
        })
        closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)
        return campaign

    def test_low_sample_writes_the_winner_with_its_sample_shown(self):
        self._close_low_sample_campaign()

        visual_rows = bi_repo.list_learnings(self.conn, self.brand_id, source_track="visual")
        self.assertEqual(len(visual_rows), 1)
        row = visual_rows[0]
        self.assertTrue(row["applicability_scope"].endswith("look=phone_raw"))
        self.assertEqual(row["sample_size"], "低")
        self.assertIn("樣本低", row["learning_text"])
        self.assertEqual(row["confidence"], "observed")

    def test_two_low_sample_campaigns_with_the_same_winner_count_as_two(self):
        # The sample is shown, never a gate: the visual level counts winners as before.
        self._close_low_sample_campaign()
        self._close_low_sample_campaign()

        rows = bi_repo.list_learnings(self.conn, self.brand_id, source_track="visual")
        phone = [r for r in rows if r["applicability_scope"].endswith("look=phone_raw")]
        self.assertEqual(sorted(r["confidence"] for r in phone), ["likely", "observed"])
        self.assertEqual({r["sample_size"] for r in phone}, {"低"})

    def test_untracked_purchases_write_no_winner_and_say_why(self):
        campaign = self._campaign()
        group = self._group(campaign["id"])
        ad_a = self._ad(campaign["id"], group["id"], audience_key="cold_unaware", name="A")
        ad_b = self._ad(campaign["id"], group["id"], audience_key="cold_unaware", name="B")
        start = campaign["start_date"]
        for ad in (ad_a, ad_b):
            for offset in range(3):
                outcome_seed.seed_day(
                    self.conn, self.org_id, self.brand_id, campaign["id"], "ad", ad["id"],
                    start + timedelta(days=offset), spend=100.0, impressions=100, clicks=10,
                    purchases=None, revenue=None, source="meta",
                )
        self.conn.commit()
        self._patch_workbench({
            ad_a["id"]: _fp(look="phone_raw"),
            ad_b["id"]: _fp(look="studio_hero"),
        })

        closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        rows = bi_repo.list_learnings(self.conn, self.brand_id, source_track="visual")
        # No look is named a winner; the only row is the 看不出 note, and it names the cause.
        self.assertEqual([r["applicability_scope"] for r in rows],
                         ["visual；audience=cold_unaware；look=看不出"])
        self.assertIn("成效未追蹤", rows[0]["learning_text"])
        self.assertNotIn("樣本", rows[0]["learning_text"])
        self.assertEqual(rows[0]["sample_size"], "未追蹤")


class DowngradeRequiresComparableStrictBestTest(VisualLearningTestBase):
    def _establish_phone_raw_winner(self):
        campaign = self._campaign()
        group = self._group(campaign["id"])
        ad_a = self._ad(campaign["id"], group["id"], audience_key="cold_unaware", name="A")
        ad_b = self._ad(campaign["id"], group["id"], audience_key="cold_unaware", name="B")
        start = campaign["start_date"]
        self._spread(campaign["id"], ad_a["id"], start, 3, daily_spend=100.0,
                     daily_purchases=10, daily_revenue=200.0)
        self._spread(campaign["id"], ad_b["id"], start, 3, daily_spend=100.0,
                     daily_purchases=5, daily_revenue=200.0)
        self._group_outcome(campaign["id"], group["id"], start, spend=600.0, purchases=45,
                             revenue=800.0)
        self._patch_workbench({
            ad_a["id"]: _fp(look="phone_raw"),
            ad_b["id"]: _fp(look="studio_hero"),
        })
        closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

    def test_a_low_sample_group_is_compared_and_the_same_winner_is_not_expired(self):
        self._establish_phone_raw_winner()
        campaign = self._campaign()
        group = self._group(campaign["id"])
        ad_a = self._ad(campaign["id"], group["id"], audience_key="cold_unaware", name="A")
        ad_b = self._ad(campaign["id"], group["id"], audience_key="cold_unaware", name="B")
        start = campaign["start_date"]
        self._spread(campaign["id"], ad_a["id"], start, 3, daily_spend=100.0,
                     daily_purchases=10, daily_revenue=200.0)
        # 3 purchases (低): compared all the same -- 33 a sale loses to 10 a sale.
        self._ad_outcome(campaign["id"], ad_b["id"], start, spend=100.0, purchases=3,
                          revenue=100.0)
        self._group_outcome(campaign["id"], group["id"], start, spend=400.0, purchases=13,
                             revenue=300.0)
        self._patch_workbench({
            ad_a["id"]: _fp(look="phone_raw"),
            ad_b["id"]: _fp(look="studio_hero"),
        })

        closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        rows = bi_repo.list_learnings(
            self.conn, self.brand_id, source_track="visual", include_expired=True,
        )
        self.assertEqual(
            [r for r in rows if r["applicability_scope"].endswith("look=看不出")], [],
        )
        phone_rows = [r for r in rows if r["applicability_scope"].endswith("look=phone_raw")]
        self.assertEqual(len(phone_rows), 2)
        self.assertFalse(any(r["expired"] for r in phone_rows))
        newest = max(phone_rows, key=lambda r: r["learned_at"])
        self.assertEqual((newest["confidence"], newest["sample_size"]), ("likely", "低"))

    def test_new_best_downgrades_every_compared_loser_the_low_sample_one_included(self):
        self._establish_phone_raw_winner()
        campaign = self._campaign()
        group = self._group(campaign["id"])
        ad_a = self._ad(campaign["id"], group["id"], audience_key="cold_unaware", name="A")
        ad_b = self._ad(campaign["id"], group["id"], audience_key="cold_unaware", name="B")
        ad_c = self._ad(campaign["id"], group["id"], audience_key="cold_unaware", name="C")
        start = campaign["start_date"]
        # studio_hero: 中, best cpa (spend 150 / purchases 30 = 5)
        self._spread(campaign["id"], ad_a["id"], start, 3, daily_spend=50.0,
                     daily_purchases=10, daily_revenue=200.0)
        # soft_light: 中, worse cpa (spend 300 / purchases 30 = 10)
        self._spread(campaign["id"], ad_b["id"], start, 3, daily_spend=100.0,
                     daily_purchases=10, daily_revenue=200.0)
        # phone_raw: 低 (3 purchases, 33 a sale) -- compared, and it lost
        self._ad_outcome(campaign["id"], ad_c["id"], start, spend=100.0, purchases=3,
                          revenue=100.0)
        self._group_outcome(campaign["id"], group["id"], start, spend=550.0, purchases=23,
                             revenue=500.0)
        self._patch_workbench({
            ad_a["id"]: _fp(look="studio_hero"),
            ad_b["id"]: _fp(look="soft_light"),
            ad_c["id"]: _fp(look="phone_raw"),
        })

        closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        rows = bi_repo.list_learnings(
            self.conn, self.brand_id, source_track="visual", include_expired=True,
        )
        studio_rows = [r for r in rows if r["applicability_scope"].endswith("look=studio_hero")]
        self.assertEqual(len(studio_rows), 1)
        self.assertFalse(studio_rows[0]["expired"])
        self.assertEqual(studio_rows[0]["sample_size"], "低")  # the smallest compared bucket
        phone_rows = [r for r in rows if r["applicability_scope"].endswith("look=phone_raw")]
        self.assertEqual(len(phone_rows), 1)
        self.assertTrue(phone_rows[0]["expired"])  # the low-sample loser was compared too


class DifferentAudiencesWriteNoVisualLearningTest(VisualLearningTestBase):
    def test_two_ads_in_different_audiences_write_no_visual_learning(self):
        campaign = self._campaign()
        group = self._group(campaign["id"])
        ad_a = self._ad(campaign["id"], group["id"], audience_key="cold_unaware", name="A")
        ad_b = self._ad(campaign["id"], group["id"], audience_key="warm_retarget", name="B")
        start = campaign["start_date"]
        self._spread(campaign["id"], ad_a["id"], start, 3, daily_spend=100.0,
                     daily_purchases=10, daily_revenue=200.0)
        self._spread(campaign["id"], ad_b["id"], start, 3, daily_spend=100.0,
                     daily_purchases=5, daily_revenue=200.0)
        self._group_outcome(campaign["id"], group["id"], start, spend=600.0, purchases=45,
                             revenue=800.0)
        self._patch_workbench({
            ad_a["id"]: _fp(look="phone_raw"),
            ad_b["id"]: _fp(look="studio_hero"),
        })

        closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        visual_rows = bi_repo.list_learnings(self.conn, self.brand_id, source_track="visual")
        self.assertEqual(visual_rows, [])


class UnadoptedAdWritesNoVisualLearningTest(VisualLearningTestBase):
    def test_one_ad_not_adopted_writes_no_visual_learning(self):
        campaign = self._campaign()
        group = self._group(campaign["id"])
        ad_a = self._ad(campaign["id"], group["id"], audience_key="cold_unaware", name="A")
        ad_b = self._ad(campaign["id"], group["id"], audience_key="cold_unaware", name="B")
        start = campaign["start_date"]
        self._spread(campaign["id"], ad_a["id"], start, 3, daily_spend=100.0,
                     daily_purchases=10, daily_revenue=200.0)
        self._spread(campaign["id"], ad_b["id"], start, 3, daily_spend=100.0,
                     daily_purchases=5, daily_revenue=200.0)
        self._group_outcome(campaign["id"], group["id"], start, spend=600.0, purchases=45,
                             revenue=800.0)
        self._patch_workbench({
            ad_a["id"]: _fp(look="phone_raw"),
            ad_b["id"]: _fp(look="studio_hero"),
        }, unadopted=frozenset({ad_b["id"]}))

        closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        visual_rows = bi_repo.list_learnings(self.conn, self.brand_id, source_track="visual")
        self.assertEqual(visual_rows, [])


class ClosingTwiceWritesNoAdditionalVisualLearningTest(VisualLearningTestBase):
    def test_closing_twice_does_not_duplicate_visual_learning(self):
        campaign = self._campaign()
        group = self._group(campaign["id"])
        ad_a = self._ad(campaign["id"], group["id"], audience_key="cold_unaware", name="A")
        ad_b = self._ad(campaign["id"], group["id"], audience_key="cold_unaware", name="B")
        start = campaign["start_date"]
        self._spread(campaign["id"], ad_a["id"], start, 3, daily_spend=100.0,
                     daily_purchases=10, daily_revenue=200.0)
        self._spread(campaign["id"], ad_b["id"], start, 3, daily_spend=100.0,
                     daily_purchases=5, daily_revenue=200.0)
        self._group_outcome(campaign["id"], group["id"], start, spend=600.0, purchases=45,
                             revenue=800.0)
        self._patch_workbench({
            ad_a["id"]: _fp(look="phone_raw"),
            ad_b["id"]: _fp(look="studio_hero"),
        })

        first = closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)
        second = closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        visual_rows = bi_repo.list_learnings(self.conn, self.brand_id, source_track="visual")
        self.assertEqual(len(visual_rows), 1)
        campaign_rows = bi_repo.list_learnings(self.conn, self.brand_id, source_track="ads")
        self.assertEqual(len(campaign_rows), 1)
        self.assertEqual(
            second["verdict_json"]["learning_ids"], first["verdict_json"]["learning_ids"],
        )
        self.assertEqual(len(second["verdict_json"]["learning_ids"]), 2)


if __name__ == "__main__":
    unittest.main()
