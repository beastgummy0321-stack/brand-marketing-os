"""F31-I05 Contract O: what ran. Launch approval freezes each batched ad's workbench outputs; the
learning readers (closeout visual learning and scope, the confirmed comparison) read those and
the coordinates snapshot of the dispatched set -- a selection changed or a coordinate edited
after the fact does not re-attribute the learning. The workbench is faked through its public
facade (`briefs_for_source` / `adopted_output`), as `test_ads_visual_learning.py` does."""

import unittest
from datetime import timedelta
from unittest import mock

from app.ads import (
    change_control_data,
    change_control_launch,
    closeout,
    experiments,
    handoff_assignment,
    live_creative,
    plan,
)
from app.ads import repository as campaigns
from app.ads import user_assets_repository as assets
from app.brand_intelligence import repository as brands
from app.core import db, settings
from app.tests.fixtures.ads_external import outcome_seed

ACTOR = "test"
_COORDS = {
    "audience": "cold", "pain": "p1", "angle": "a1", "hook": "h1", "proof": "pr1",
    "offer": "o1", "format": "single",
}


def _fp(look):
    return {
        dim: {"key": key, "label": f"{key}標籤"}
        for dim, key in {"look": look, "device": "d1", "layout": "l1", "subject_role": "s1",
                         "persuasion": "pe1"}.items()
    }


class LiveCreativeTest(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="上架素材品牌", actor=ACTOR, client_name=None
        )["id"]
        self.today = settings.today_for_org(self.conn, org_id=self.org)
        self.campaign = campaigns.create_campaign(
            self.conn, self.org, self.brand,
            {
                "name": "秋季上架", "goal_text": "檢驗學習", "objective": "awareness",
                "start_date": self.today - timedelta(days=6), "end_date": self.today,
            },
            created_by=ACTOR,
        )["id"]
        self.group = plan.create_group(
            self.conn, self.org, self.brand, self.campaign, name="新客", role="new",
            daily_budget=500,
        )["id"]
        # F37 Contract Q: closeout refuses an unread window; the window was read in full.
        outcome_seed.set_coverage(
            self.conn, self.org, self.brand, self.campaign,
            self.today - timedelta(days=6), self.today,
        )
        self.conn.commit()
        # ad_id -> the fake set; (set_id, part) -> the output its workbench selection shows now.
        self.sets: dict = {}
        self.selected: dict = {}
        fakes = (("briefs_for_source", self._briefs), ("adopted_output", self._adopted))
        for name, target in fakes:
            patcher = mock.patch.object(live_creative.workbench, name, side_effect=target)
            patcher.start()
            self.addCleanup(patcher.stop)

    # -- fakes and fixtures ----------------------------------------------------------------------

    def _briefs(self, conn, org, brand, source_kind, source_ref):
        return list(self.sets.values())

    def _adopted(self, conn, org, brand, brief_id, part):
        return self.selected.get((brief_id, part))

    def _select(self, ad_id, output_id, look):
        brief_id = self.sets[ad_id]["id"]
        self.selected[(brief_id, "image_prompt")] = {
            "id": output_id, "brief_id": brief_id, "part": "image_prompt", "is_adopted": True,
            "adopted_at": db.now_utc(), "body_json": {"fingerprint": _fp(look)},
        }

    def _ad(self, name, **coordinates):
        """A planned ad with a dispatched set (snapshot of its coordinates at dispatch) and a
        confirmed material, so it joins a launch batch."""
        coords = {**_COORDS, **coordinates}
        ad = plan.create_ad(
            self.conn, self.org, self.brand, self.campaign, self.group, name=name,
            coordinates=coords,
        )
        self.sets[ad["id"]] = {
            "id": f"wbb-{ad['id']}", "source_ref": {"ads_campaign_id": self.campaign,
                                                   "ads_ad_id": ad["id"]},
            "coordinates_snapshot_json": dict(coords),
            "parts": {"image_prompt": {"latest_round": 1, "adopted": True}},
        }
        asset = db.new_id("aua")
        self.conn.execute(
            "INSERT INTO ads_user_asset(id,org_id,brand_id,sha256,storage_key,filename,"
            "mime_type,byte_size,status) VALUES(%s,%s,%s,%s,%s,'a.png','image/png',1,'ready')",
            (asset, self.org, self.brand, asset, f"{self.org}/{asset}"),
        )
        placement = assets.attach(
            self.conn, self.org, self.brand, self.campaign, asset,
            {"headline": "標題", "body": "文案", "description": "說明"}, ACTOR,
        )
        self.conn.execute(
            "UPDATE ads_asset_placement SET confirmed_at=now(),confirmed_by='human' WHERE id=%s",
            (placement["id"],),
        )
        self.conn.commit()
        handoff_assignment.assign(
            self.conn, self.org, self.brand, self.campaign, ad["id"], placement["id"], 1
        )
        return ad

    def _launch(self):
        frozen = change_control_launch.snapshot(self.conn, self.org, self.brand, self.campaign)
        with mock.patch.object(
            change_control_launch.month_budget, "preflight", return_value={"can_increase": True}
        ):
            return change_control_launch.publish(
                self.conn, self.org, self.brand, self.campaign, "human", db.new_id("op"),
                change_control_data.digest(frozen),
            )["change_set_id"]

    def _ad_rows(self, ad_id, *, purchases):
        for offset in range(3):
            outcome_seed.seed_day(
                self.conn, self.org, self.brand, self.campaign, "ad", ad_id,
                self.today - timedelta(days=offset), spend=100, impressions=100, clicks=10,
                purchases=purchases, revenue=200, source="simulated",
            )
        self.conn.commit()

    def _edit(self, ad_id, **coordinates):
        plan.update_ad(
            self.conn, self.org, self.brand, ad_id, {"coordinates": coordinates}, actor=ACTOR
        )
        self.conn.commit()

    # -- tests -----------------------------------------------------------------------------------

    def test_approval_freezes_the_selection_and_a_later_change_does_not_move_it(self):
        ad = self._ad("A")
        self._select(ad["id"], "wbo-launched", "phone_raw")
        self.assertIsNone(
            live_creative.launched_outputs(self.conn, self.org, self.brand, self.campaign)[ad["id"]]
        )

        set_id = self._launch()
        self._select(ad["id"], "wbo-later", "studio_hero")

        record = live_creative.launched_outputs(
            self.conn, self.org, self.brand, self.campaign
        )[ad["id"]]
        self.assertEqual(record["change_set_id"], set_id)
        self.assertEqual(record["set_id"], self.sets[ad["id"]]["id"])
        self.assertEqual(record["outputs"]["image_prompt"]["id"], "wbo-launched")
        # The freeze is not a plan edit: the approved launch stays current.
        self.assertFalse(
            change_control_launch.is_stale(self.conn, self.org, self.brand, self.campaign)
        )

    def test_visual_learning_reads_the_launched_image_after_the_selection_changed(self):
        ad_a, ad_b = self._ad("A"), self._ad("B")
        self._select(ad_a["id"], "wbo-a", "phone_raw")
        self._select(ad_b["id"], "wbo-b", "studio_hero")
        self._launch()
        # After launch the user reselects B to the same look as A: nothing to compare any more
        # if closeout read the current selection.
        self._select(ad_b["id"], "wbo-b2", "phone_raw")
        self._ad_rows(ad_a["id"], purchases=10)
        self._ad_rows(ad_b["id"], purchases=5)

        closeout.close(self.conn, self.org, self.brand, self.campaign, actor=ACTOR)

        rows = brands.list_learnings(self.conn, self.brand, source_track="visual")
        self.assertEqual(
            [r["applicability_scope"] for r in rows], ["visual；audience=cold；look=phone_raw"]
        )
        self.assertIn("studio_hero標籤", rows[0]["learning_text"])

    def test_comparison_shows_the_launched_output_and_keeps_its_confirmation(self):
        ad_a, ad_b = self._ad("A"), self._ad("B", hook="h2")
        self._select(ad_a["id"], "wbo-a", "phone_raw")
        self._select(ad_b["id"], "wbo-b", "studio_hero")
        before, _ = experiments.propose(self.conn, self.org, self.brand, self.campaign)
        experiments.confirm(
            self.conn, self.org, self.brand, self.campaign, fingerprint=before["fingerprint"],
            controls_checked=True, actor=ACTOR,
        )
        self._launch()
        after_launch, _ = experiments.propose(self.conn, self.org, self.brand, self.campaign)
        self.assertEqual(after_launch["fingerprint"], before["fingerprint"])

        self._select(ad_b["id"], "wbo-b2", "phone_raw")
        proposal, _ = experiments.propose(self.conn, self.org, self.brand, self.campaign)

        shown = proposal["snapshot"]["materials"][ad_b["id"]]["outputs"]["image_prompt"]
        self.assertEqual(shown["id"], "wbo-b")
        self.assertFalse(experiments.read(self.conn, self.org, self.brand, self.campaign)["stale"])

    def test_comparison_pairs_on_the_dispatch_coordinates(self):
        ad_a, ad_b = self._ad("A"), self._ad("B", hook="h2")
        # After dispatch B's hook is edited back to A's: the creatives still differ in hook.
        self._edit(ad_b["id"], hook="h1")

        proposal, missing = experiments.propose(self.conn, self.org, self.brand, self.campaign)

        self.assertIsNone(missing)
        self.assertEqual(proposal["variable"], "開場")
        self.assertEqual({v["ad_id"] for v in proposal["variants"]}, {ad_a["id"], ad_b["id"]})

    def test_closeout_scope_names_the_dispatch_coordinates(self):
        ad = self._ad("A")
        self._edit(ad["id"], angle="a-edited")
        # F49 Contract L: only a campaign read back on a platform has a period to close.
        outcome_seed.bind_platform(self.conn, self.org, self.brand, self.campaign)

        closeout.close(self.conn, self.org, self.brand, self.campaign, actor=ACTOR)

        scopes = [
            r["applicability_scope"] for r in brands.list_learnings(self.conn, self.brand)
            if r.get("source_track") != "visual"
        ]
        self.assertEqual(len(scopes), 1)
        self.assertIn("a1", scopes[0].split("、"))
        self.assertNotIn("a-edited", scopes[0].split("、"))

    def test_f48_offer_for_reads_the_dispatch_snapshot_like_the_learning(self):
        """F48 Contract G: one resolver of the offer an ad's copy was written for -- the
        dispatched set's snapshot after an edit, the same offer the stored learning names."""
        ad = self._ad("A")
        bare = plan.create_ad(
            self.conn, self.org, self.brand, self.campaign, self.group, name="沒有交棒",
            coordinates={**_COORDS, "offer": "o3"},
        )
        self._edit(ad["id"], offer="o2")
        self.assertEqual(
            live_creative.offer_for(self.conn, self.org, self.brand, self.campaign,
                                    campaigns.get_ad(self.conn, self.org, self.brand, ad["id"])),
            "o1",
        )
        self.assertEqual(self._coords(ad["id"])["offer"], "o1")
        # No dispatched set: the ad's current key.
        self.assertEqual(
            live_creative.offers_for(self.conn, self.org, self.brand, self.campaign,
                                     [campaigns.get_ad(self.conn, self.org, self.brand,
                                                       bare["id"])]),
            {bare["id"]: "o3"},
        )

        # F49 Contract L: only a campaign read back on a platform has a period to close.
        outcome_seed.bind_platform(self.conn, self.org, self.brand, self.campaign)
        closeout.close(self.conn, self.org, self.brand, self.campaign, actor=ACTOR)
        scopes = [
            r["applicability_scope"] for r in brands.list_learnings(self.conn, self.brand)
            if r.get("source_track") != "visual"
        ]
        self.assertTrue(scopes)
        self.assertTrue(all("o2" not in s.split("、") for s in scopes))
        self.assertIn("o1", [part for s in scopes for part in s.split("、")])

    def test_an_ad_without_a_dispatched_set_uses_its_current_coordinates(self):
        ad = plan.create_ad(
            self.conn, self.org, self.brand, self.campaign, self.group, name="沒有交棒",
            coordinates=_COORDS,
        )
        self._edit(ad["id"], audience="warm")
        detail = campaigns.campaign_detail(self.conn, self.org, self.brand, self.campaign)
        ads = [a for g in detail["groups"] for a in g["ads"]]

        coords = live_creative.learning_coordinates(
            self.conn, self.org, self.brand, self.campaign, ads
        )

        self.assertEqual(coords[ad["id"]]["audience"], "warm")

    def _coords(self, ad_id):
        detail = campaigns.campaign_detail(self.conn, self.org, self.brand, self.campaign)
        ads = [a for g in detail["groups"] for a in g["ads"]]
        return live_creative.learning_coordinates(
            self.conn, self.org, self.brand, self.campaign, ads
        )[ad_id]

    def test_f46_the_uploaded_file_decides_the_learned_format(self):
        """Contract F: a carousel planned ad keeps 「carousel」 until a material is assigned; the
        one image in its slot makes it `single_image`, a video file `video`."""
        ad = plan.create_ad(
            self.conn, self.org, self.brand, self.campaign, self.group, name="輪播規劃",
            coordinates={**_COORDS, "format": "carousel"},
        )
        self.conn.commit()
        self.assertEqual(self._coords(ad["id"])["format"], "carousel")

        for mime, expected in (("image/png", "single_image"), ("video/mp4", "video")):
            with self.subTest(mime=mime):
                asset = db.new_id("aua")
                self.conn.execute(
                    "INSERT INTO ads_user_asset(id,org_id,brand_id,sha256,storage_key,filename,"
                    "mime_type,byte_size,status) VALUES(%s,%s,%s,%s,%s,'f',%s,1,'ready')",
                    (asset, self.org, self.brand, asset, f"{self.org}/{asset}", mime),
                )
                placement = assets.attach(
                    self.conn, self.org, self.brand, self.campaign, asset,
                    {"headline": "標題", "body": "文案", "description": "說明"}, ACTOR,
                )
                self.conn.execute(
                    "UPDATE ads_asset_placement SET confirmed_at=now(),confirmed_by='human' "
                    "WHERE id=%s",
                    (placement["id"],),
                )
                self.conn.commit()
                handoff_assignment.assign(
                    self.conn, self.org, self.brand, self.campaign, ad["id"], placement["id"], 1
                )
                coords = self._coords(ad["id"])
                self.assertEqual(coords["format"], expected)
                # Only the format follows the file; the other coordinates stay the plan's.
                self.assertEqual(coords["angle"], "a1")


class SnapshotKeysTest(unittest.TestCase):
    def test_both_stored_shapes_normalise_to_keys(self):
        self.assertEqual(
            live_creative.snapshot_keys(
                {"audience": "cold", "angle": {"key": "a1", "label": "角度"}, "hook": ""}
            ),
            {"audience": "cold", "pain": None, "angle": "a1", "hook": None, "proof": None,
             "offer": None, "format": None},
        )
        self.assertIsNone(live_creative.snapshot_keys(None))
