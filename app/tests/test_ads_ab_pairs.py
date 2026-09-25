"""F29-I04 Contract F: automatic A/B pairs on real (`source='meta'`) daily ad rows, the
pause-loser change set through the normal approval flow, and the learning its confirmed pause
writes. Nothing here writes to a platform: the readback uses a fake reader."""

import copy
from datetime import timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as main
from app.ads import ab_pairs, external_sync, plan
from app.ads import change_control as service
from app.ads import change_control_verify as verification
from app.ads import external_repository as external
from app.ads import repository as ads_repo
from app.core.db import new_id
from app.shared import web

from .test_ads_publish_simulated import ACTOR, SimulatedPublishTestBase


class AbPairsTest(SimulatedPublishTestBase):
    def setUp(self):
        super().setUp()
        campaign = self._campaign(
            start_date=self.today - timedelta(days=30), groups=1, ads_per_group=2
        )
        self.cid = campaign["id"]
        self.args = (web.conn, self.org_id, self.brand_id, self.cid)
        detail = ads_repo.campaign_detail(*self.args)
        self.group = detail["groups"][0]
        self.a, self.b = sorted(self.group["ads"], key=lambda ad: ad["id"])
        plan.update_ad(
            web.conn, self.org_id, self.brand_id, self.b["id"],
            {"coordinates": {"hook": "price"}}, actor=ACTOR,
        )
        for key, label in (("hook", "先講痛點"), ("price", "先講價格")):
            web.conn.execute(
                "INSERT INTO brand_coordinate (id, org_id, brand_id, dimension, key, label)"
                " VALUES (%s, %s, %s, 'hook', %s, %s)",
                (new_id("crd"), self.org_id, self.brand_id, key, label),
            )
        self.root = self.entity("c1", "campaign")
        self.adset = self.entity(
            "s1", "adset", parent_native_kind="campaign", parent_native_id="c1"
        )
        self.entities = {}
        for ad, native in ((self.a, "n-a"), (self.b, "n-b")):
            self.bind(ad, native)
        self.yesterday = self.today - timedelta(days=1)
        web.conn.commit()

    # -- fixtures -------------------------------------------------------------------------------

    def entity(self, native_id, native_kind, **extra):
        return external.upsert_entity(
            web.conn, self.org_id, self.brand_id, self.cid,
            {"platform": "fake", "source_account": "account", "native_id": native_id,
             "native_kind": native_kind, "native_status": "ACTIVE", **extra},
        )

    def bind(self, ad, native):
        self.entities[ad["id"]] = self.entity(
            native, "ad", parent_native_kind="adset", parent_native_id="s1",
            creative={"kind": "image", "fields": {"body": "文案", "image_hash": native,
                                                    "thumbnail_url": f"https://x/{native}.jpg"}},
        )
        ads_repo.bind_ad(
            web.conn, self.org_id, self.brand_id, ad["id"], external_id=native,
            external_name=ad["name"], external_status="ACTIVE",
        )

    def fill(self, ad, *, days=7, spend=100.0, purchases=2, skip=(), untracked=()):
        """`days` days ending yesterday. `purchases` is per day, or a list (oldest first); `skip`
        and `untracked` are offsets back from yesterday (0 = yesterday)."""
        per_day = purchases if isinstance(purchases, list) else [purchases] * days
        for offset in range(days):
            if offset in skip:
                continue
            day = self.yesterday - timedelta(days=offset)
            count = None if offset in untracked else per_day[days - 1 - offset]
            web.conn.execute(
                "INSERT INTO ads_outcome_daily (id, org_id, brand_id, campaign_id, entity_kind,"
                " entity_id, day, spend, impressions, clicks, purchases, revenue, currency,"
                " source) VALUES (%s,%s,%s,%s,'ad',%s,%s,%s,1000,10,%s,NULL,'TWD','meta')"
                " ON CONFLICT (entity_kind, entity_id, day) DO UPDATE SET spend=excluded.spend,"
                " purchases=excluded.purchases",
                (new_id("ado"), self.org_id, self.brand_id, self.cid, ad["id"], day, spend,
                 count),
            )
        web.conn.commit()

    def pair(self):
        view = ab_pairs.read(*self.args)
        self.assertIsNone(view["unavailable"])
        self.assertEqual(len(view["pairs"]), 1)
        return view["pairs"][0]

    def judged(self):
        """a: 700 / 14 = 50 per result; b: 560 / 14 = 40 -> b wins by 20%."""
        self.fill(self.a, spend=100.0)
        self.fill(self.b, spend=80.0)

    def pause(self, operation_id=None):
        return ab_pairs.pause_loser(
            *self.args, self.pair()["pair_id"], operation_id or new_id("op"), "tester"
        )

    def ab_sets(self):
        return web.conn.execute(
            "SELECT id FROM ads_change_set WHERE campaign_id=%s AND plan_json->>'source'='ab'",
            (self.cid,),
        ).fetchall()

    def learnings(self):
        return web.conn.execute(
            "SELECT * FROM learning_ledger WHERE brand_id=%s AND source_track='ads'",
            (self.brand_id,),
        ).fetchall()

    def confirm(self, change_set):
        target = change_set["items"][0]["target_id"]
        leaf = copy.deepcopy(next(e for e in self.entities.values() if e["id"] == target))
        leaf["native_status"] = "PAUSED"
        proof = {"entity": leaf, "parents": [self.adset, self.root]}

        class Reader:
            def verify_native(self, *args, **kwargs):
                return proof

        with patch.object(external_sync, "account_reader", return_value=(Reader(), {})):
            return verification.check(
                *self.args, change_set["id"], change_set["items"][0]["id"], "system"
            )

    # -- pair reading ---------------------------------------------------------------------------

    def test_pair_shape_and_a_judged_winner(self):
        self.judged()
        pair = self.pair()
        self.assertEqual(pair["pair_id"], f"{self.a['id']}:{self.b['id']}")
        self.assertEqual(pair["group_id"], self.group["id"])
        self.assertEqual(pair["dimension"], "hook")
        self.assertEqual(pair["dimension_label"], "開場")
        self.assertEqual(pair["rules"],
                         {"min_days": 7, "min_conversions_each": 10, "relative_difference": 0.1})
        self.assertEqual(pair["window"], {"start": str(self.yesterday - timedelta(days=6)),
                                          "end": str(self.yesterday)})
        self.assertEqual(pair["days"], 7)
        self.assertEqual(pair["state"], "judged")
        self.assertEqual(pair["winner"], "b")
        self.assertEqual(pair["difference_pct"], 20.0)
        self.assertEqual(pair["missing"], {"days": 0, "a_results": 0, "b_results": 0})
        self.assertIsNone(pair["decision"])
        self.assertEqual(pair["a"], {
            "ad_id": self.a["id"], "entity_id": self.entities[self.a["id"]]["id"],
            "name": self.a["name"], "value_label": "先講痛點",
            "thumbnail_url": "https://x/n-a.jpg", "spend": 700.0, "results": 14,
            "cost_per_result": 50.0,
        })
        self.assertEqual(pair["b"]["value_label"], "先講價格")
        self.assertEqual(pair["b"]["cost_per_result"], 40.0)

    def test_day_six_collects_and_day_seven_judges(self):
        self.fill(self.a, days=6, spend=100.0)
        self.fill(self.b, days=6, spend=80.0)
        pair = self.pair()
        self.assertEqual(pair["state"], "collecting")
        self.assertEqual(pair["days"], 6)
        self.assertEqual(pair["missing"]["days"], 1)
        self.assertIsNone(pair["winner"])
        self.judged()
        self.assertEqual(self.pair()["state"], "judged")

    def test_window_starts_at_the_later_ads_first_delivery(self):
        self.fill(self.a, days=10, spend=100.0)
        self.fill(self.b, days=3, spend=80.0)
        pair = self.pair()
        self.assertEqual(pair["window"]["start"], str(self.yesterday - timedelta(days=2)))
        self.assertEqual((pair["state"], pair["days"]), ("collecting", 3))
        self.assertEqual(pair["a"]["spend"], 300.0)  # only the shared window counts

    def test_an_ad_that_never_delivered_keeps_the_pair_collecting(self):
        self.fill(self.a)
        pair = self.pair()
        self.assertEqual(pair["state"], "collecting")
        self.assertIsNone(pair["window"])
        self.assertEqual(pair["missing"], {"days": 7, "a_results": 10, "b_results": 10})

    def test_one_side_at_nine_conversions_is_still_collecting(self):
        self.fill(self.a, purchases=[3, 1, 1, 1, 1, 1, 1])  # 9
        self.fill(self.b, spend=80.0)
        pair = self.pair()
        self.assertEqual(pair["state"], "collecting")
        self.assertEqual(pair["a"]["results"], 9)
        self.assertEqual(pair["missing"], {"days": 0, "a_results": 1, "b_results": 0})
        self.assertIn("10 次轉換", pair["reason"])

    def test_nine_percent_is_no_difference_and_ten_percent_is_judged(self):
        ten = [4, 1, 1, 1, 1, 1, 1]  # 10 results
        self.fill(self.a, spend=100.0, purchases=ten)  # 70 per result
        self.fill(self.b, spend=91.0, purchases=ten)  # 63.7 -> 9%
        pair = self.pair()
        self.assertEqual(pair["state"], "no_difference")
        self.assertEqual(pair["difference_pct"], 9.0)
        self.assertIsNone(pair["winner"])
        self.fill(self.b, spend=90.0, purchases=ten)  # 63 -> 10%
        pair = self.pair()
        self.assertEqual((pair["state"], pair["winner"], pair["difference_pct"]),
                         ("judged", "b", 10.0))

    def test_a_missing_day_is_unreadable_never_zero(self):
        self.fill(self.a)
        self.fill(self.b, spend=80.0, skip=(3,))
        pair = self.pair()
        self.assertEqual(pair["state"], "unreadable")
        self.assertIn("缺日", pair["reason"])
        self.assertIsNone(pair["b"]["spend"])
        self.assertIsNone(pair["b"]["results"])
        self.assertIsNone(pair["missing"]["b_results"])
        self.assertIsNone(pair["winner"])

    def test_untracked_purchases_are_unreadable_never_zero(self):
        self.fill(self.a)
        self.fill(self.b, spend=80.0, untracked=(2,))
        pair = self.pair()
        self.assertEqual(pair["state"], "unreadable")
        self.assertIn("未追蹤", pair["reason"])
        self.assertEqual(pair["b"]["spend"], 560.0)
        self.assertIsNone(pair["b"]["results"])
        self.assertIsNone(pair["b"]["cost_per_result"])

    def _third_ad(self):
        coordinates = {d: self.a[f"{d}_key"] for d in
                       ("audience", "pain", "angle", "hook", "proof", "offer", "format")}
        plan.create_ad(
            web.conn, self.org_id, self.brand_id, self.cid, self.group["id"], name="廣告0-2",
            coordinates={**coordinates, "offer": "other-offer"},
        )
        web.conn.commit()
        ads = ads_repo.campaign_detail(*self.args)["groups"][0]["ads"]
        return next(ad for ad in ads if ad["id"] not in {self.a["id"], self.b["id"]})

    def test_two_pairs_in_one_group(self):
        c = self._third_ad()  # differs from a in offer, from b in hook and offer
        pairs = ab_pairs.read(*self.args)["pairs"]
        self.assertEqual(
            sorted((p["pair_id"], p["dimension"]) for p in pairs),
            sorted([(ab_pairs.pair_id(self.a["id"], self.b["id"]), "hook"),
                    (ab_pairs.pair_id(self.a["id"], c["id"]), "offer")]),
        )
        self.assertTrue(all(p["group_id"] == self.group["id"] for p in pairs))

    def test_an_ad_in_two_pairs_is_judged_in_each(self):
        c = self._third_ad()
        self.judged()
        self.fill(c, spend=100.0)
        pairs = {p["pair_id"]: p for p in ab_pairs.read(*self.args)["pairs"]}
        ab = pairs[ab_pairs.pair_id(self.a["id"], self.b["id"])]
        ac = pairs[ab_pairs.pair_id(self.a["id"], c["id"])]
        self.assertEqual(ab["state"], "judged")
        self.assertEqual(ac["state"], "no_difference")
        self.assertIn(self.a["id"], (ac["a"]["ad_id"], ac["b"]["ad_id"]))
        self.assertIsNone((ac["a"] if ac["a"]["ad_id"] == c["id"] else ac["b"])["entity_id"])

    def test_imported_campaign_is_unavailable(self):
        imported = external.create_imported_campaign(
            web.conn, self.org_id, self.brand_id, name="匯入活動"
        )
        view = ab_pairs.read(web.conn, self.org_id, self.brand_id, imported["id"])
        self.assertEqual(view["pairs"], [])
        self.assertEqual(view["unavailable"], ab_pairs.IMPORTED_REASON)

    def test_budget_hit_days_do_not_stop_an_automatic_pair(self):
        # Real delivery spends the whole daily budget (500) every day -- still judged.
        web.conn.execute(
            "INSERT INTO ads_outcome_daily (id, org_id, brand_id, campaign_id, entity_kind,"
            " entity_id, day, spend, purchases, source) VALUES (%s,%s,%s,%s,'group',%s,%s,500,"
            "28,'meta')",
            (new_id("ado"), self.org_id, self.brand_id, self.cid, self.group["id"],
             self.yesterday),
        )
        self.judged()
        self.assertEqual(self.pair()["state"], "judged")

    # -- pause the loser ------------------------------------------------------------------------

    def test_pause_loser_builds_one_ab_pause_item_on_the_losers_platform_ad(self):
        self.judged()
        created = self.pause()
        self.assertEqual(created["status"], "draft")
        self.assertEqual(created["source"], "ab")
        self.assertEqual(created["plan_json"]["source"], "ab")
        ab = created["ab"]
        self.assertEqual(ab["pair_id"], self.pair()["pair_id"])
        self.assertEqual(ab["dimension_label"], "開場")
        self.assertEqual(ab["winner"]["value_label"], "先講價格")
        self.assertEqual(ab["loser"]["value_label"], "先講痛點")
        self.assertEqual(ab["window"], self.pair()["window"])
        [item] = created["items"]
        self.assertEqual(item["kind"], "pause")
        self.assertEqual(item["target_id"], self.entities[self.a["id"]]["id"])
        self.assertEqual(item["after"], {"status": "PAUSED"})
        self.assertEqual(self.pair()["decision"], {
            "change_set_id": created["id"], "status": "draft", "verification_state": None,
        })

    def test_pause_loser_twice_returns_the_open_set(self):
        self.judged()
        first = self.pause()
        second = self.pause()
        self.assertEqual(first["id"], second["id"])
        approved = service.approve(*self.args, first["id"], first["content_hash"], "tester")
        self.assertEqual(self.pause()["id"], approved["id"])
        self.assertEqual(len(self.ab_sets()), 1)

    def test_same_operation_id_replays_the_same_set(self):
        self.judged()
        first = self.pause("stable-op")
        self.assertEqual(self.pause("stable-op")["id"], first["id"])

    def test_pause_loser_refuses_an_unjudged_pair_or_an_unbound_loser(self):
        self.fill(self.a, days=3)
        self.fill(self.b, days=3, spend=80.0)
        with self.assertRaises(ab_pairs.NotJudged):
            self.pause()
        self.judged()
        web.conn.execute(
            "UPDATE ads_ad SET external_id=NULL WHERE id=%s", (self.a["id"],)
        )
        web.conn.commit()
        self.assertIsNone(self.pair()["a"]["entity_id"])
        with self.assertRaises(ab_pairs.LoserUnbound):
            self.pause()
        self.assertEqual(self.ab_sets(), [])

    def test_public_create_refuses_the_ab_source(self):
        self.judged()
        item = {"kind": "pause", "target_id": self.entities[self.a["id"]]["id"],
                "after": {"status": "PAUSED"}, "reason": "x"}
        payload = {"operation_id": new_id("op"), "title": "t",
                   "month": self.today.strftime("%Y-%m"), "items": [item]}
        with self.assertRaisesRegex(ValueError, "不支援的清單來源"):
            service.create(*self.args, {**payload, "source": "ab"}, "tester")
        with self.assertRaises(ValueError):
            service.create(*self.args, {**payload, "ab": {"pair_id": "x"}}, "tester")

    def test_rejected_ab_set_writes_no_learning_and_a_new_proposal_is_allowed(self):
        self.judged()
        created = self.pause()
        service.decide(*self.args, created["id"], "rejected", "先不要停", None, "tester")
        decision = self.pair()["decision"]
        self.assertEqual((decision["change_set_id"], decision["status"]),
                         (created["id"], "rejected"))
        self.assertEqual(self.learnings(), [])
        again = self.pause()
        self.assertNotEqual(again["id"], created["id"])
        self.assertEqual(self.pair()["decision"]["change_set_id"], again["id"])

    def test_confirmed_pause_writes_one_learning_across_runtime_rechecks(self):
        self.judged()
        created = self.pause()
        approved = service.approve(*self.args, created["id"], created["content_hash"], "tester")
        checked = self.confirm(approved)
        self.assertEqual(checked["items"][0]["verification_state"], "confirmed")
        again = self.confirm(approved)  # runtime re-check of an already-confirmed item
        rows = self.learnings()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["learning_text"], "「開場」用「先講價格」比「先講痛點」划算")
        self.assertEqual(rows[0]["source_cycle_id"], approved["items"][0]["id"])
        self.assertEqual(again["items"][0]["learning"],
                         {"recorded": True, "confidence": "observed", "count": 1})
        self.assertEqual(self.pair()["decision"]["verification_state"], "confirmed")

    # -- HTTP -----------------------------------------------------------------------------------

    def test_http_contract(self):
        self.fill(self.a, days=3)
        self.fill(self.b, days=3, spend=80.0)
        client = TestClient(main.app)
        base = f"/api/ads/brands/{self.brand_id}/campaigns/{self.cid}/ab-pairs"
        read = client.get(base)
        self.assertEqual(read.status_code, 200, read.text)
        pair_id = read.json()["pairs"][0]["pair_id"]
        url = f"{base}/{pair_id}/pause-loser"
        not_judged = client.post(url, json={"operation_id": "op-1"})
        self.assertEqual(not_judged.status_code, 409, not_judged.text)
        self.assertEqual(not_judged.json()["error"]["code"], "ab_not_judged")
        unknown = client.post(f"{base}/x:y/pause-loser", json={"operation_id": "op-2"})
        self.assertEqual(unknown.status_code, 404, unknown.text)
        self.assertEqual(unknown.json()["error"]["code"], "ab_pair_unknown")
        self.judged()
        web.conn.execute(
            "UPDATE ads_ad SET external_id=NULL WHERE id=%s", (self.a["id"],)
        )
        web.conn.commit()
        unbound = client.post(url, json={"operation_id": "op-3"})
        self.assertEqual(unbound.status_code, 409, unbound.text)
        self.assertEqual(unbound.json()["error"]["code"], "ab_loser_unbound")
        self.bind(self.a, "n-a")
        web.conn.commit()
        created = client.post(url, json={"operation_id": "op-4"})
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["change_set"]["source"], "ab")
        self.assertEqual(client.post(url, json={"operation_id": "op-5"})
                         .json()["change_set"]["id"], created.json()["change_set"]["id"])
        self.assertEqual(client.post(url, json={}).status_code, 422)
