"""app/tests/test_ads_readiness.py — F05-I04 / F42-I02 falsifiers: the checklist lists the five
brand rows of the onboarding completion screen in order (identity, evidence, media, channel,
offering), each with its own fix link; identity/media are yellow until set, evidence is green
with one confirmed proof or store policy (the cooling-off exemption does not count); the ad
account row carries the conversion goal and turns red without one (the old `goal` row is merged);
a brand with no finished sell-way is red 「還沒有商品」 with 「建第一個商品」 to product onboarding
(F43-I04: `/products/new`; a bare or 建到一半 product does not count); an
economics row carrying `assumptions_json` turns `offering` yellow (never red); the overall state
follows the worst row; `notes[0]` always names the confirmed fact count, including 0.
"""

import unittest
import uuid
from unittest import mock

import app.shared.web as web
from app.ads import channels, readiness
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.meta import repository as meta_repo

ACTOR = "測試員"

_KEYS = ["identity", "evidence", "media", "channel", "offering"]


class ReadinessTestBase(unittest.TestCase):
    def setUp(self):
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：可投放檢查表", client_name=None,
            actor=ACTOR,
        )
        self.brand_id = self.brand["id"]
        web.conn.commit()

    def _result(self, *, background_active: bool = False) -> dict:
        with mock.patch.object(channels, "background_is_active", return_value=background_active):
            return readiness.launch_readiness(web.conn, self.org_id, self.brand_id)

    def _item(self, key: str, **kwargs) -> dict:
        return next(i for i in self._result(**kwargs)["items"] if i["key"] == key)

    def _connect_account(self, *, backfill_done: bool) -> None:
        meta_repo.save_token(web.conn, self.org_id, "tok")
        external_id = f"act_{uuid.uuid4().hex[:10]}"
        meta_repo.upsert_accounts(web.conn, self.org_id, [
            {"account_id": external_id, "name": "測試廣告帳號", "currency": "TWD"},
        ])
        row = next(a for a in meta_repo.list_accounts(web.conn, self.org_id)
                   if a["account_id"] == external_id)
        meta_repo.bind(web.conn, self.org_id, self.brand_id, row["id"])
        if backfill_done:
            meta_repo.upsert_entity_spend(web.conn, self.org_id, row["id"], [{
                "level": "ad", "entity_id": "ad-1", "entity_name": "ad-1",
                "campaign_id": "camp-1", "adset_id": "as-1", "ad_id": "ad-1",
                "spend_date": coresettings_today(self.org_id), "spend": 100.0,
                "impressions": 1000, "clicks": 20, "roas": None,
                "actions": None, "action_values": None, "attribution_window": "7d_click,1d_view",
            }])
        web.conn.commit()

    def _fact(self, fact_type: str, value: str, *, status: str = "confirmed",
              fact_key: str | None = None) -> None:
        bi_repo.create_brand_fact(
            web.conn, self.brand_id, actor=ACTOR, fact_type=fact_type, label=fact_type,
            value=value, status=status, confirmed_by=ACTOR if status == "confirmed" else None,
            fact_key=fact_key,
        )
        web.conn.commit()

    def _set_goal(self) -> None:
        bi_repo.set_brand_switches(
            web.conn, self.brand_id, market_region="TW", conversion_goal="purchase", actor=ACTOR,
        )
        web.conn.commit()

    def _add_product(self, name: str = "測試商品", **economics) -> str:
        """A knowledge product; with `economics`, also its one sell-way (F43-I04: the offering
        row is judged on finished sell-ways, the ones the new-campaign wizard offers)."""
        product_id = bi_repo.create_product(web.conn, self.brand_id, name=name, actor=ACTOR)["id"]
        if economics:
            bi_repo.save_sell_way(
                web.conn, self.brand_id, name="單品", actor=ACTOR, economics=economics,
                product_id=product_id,
            )
            # F50 Contract R: a product with zero customer groups is not ready (not offered).
            bi_repo.save_customer_groups(web.conn, self.brand_id, product_id,
                                         [{"who": "測試客群", "pain_keys": ["cost"]}], actor=ACTOR)
        web.conn.commit()
        return product_id

    def _fill_other_rows(self):
        """Every row but the ad account green."""
        self._fact("positioning", "給忙到沒空吃飯的人的維他命軟糖")
        self._fact("tone", "親切、直接")
        self._fact("proof", "創辦人自己每天吃", fact_key="founder_voice")
        bi_repo.set_media_capability(web.conn, self.brand_id, "photo", actor=ACTOR)
        self._real_product()
        self._set_goal()

    def _real_product(self, name: str = "測試商品", **extra) -> str:
        return self._add_product(name, selling_price=500, unit_variable_cost=150,
                                 shipping_cost=50, **extra)


def coresettings_today(org_id):
    from app.core import settings as coresettings
    return coresettings.today_for_org(web.conn, org_id=org_id)


class BrandNewBrandTest(ReadinessTestBase):
    def test_five_brand_rows_in_order(self):
        result = self._result()
        self.assertEqual([item["key"] for item in result["items"]], _KEYS)
        self.assertEqual([item["label"] for item in result["items"]],
                         ["品牌是誰", "證據與政策", "素材", "廣告帳戶", "商品"])
        self.assertNotIn("goal", [item["key"] for item in result["items"]])

    def test_new_brand_colours_and_secondary_action(self):
        result = self._result()
        states = {item["key"]: item["state"] for item in result["items"]}
        self.assertEqual(states, {"identity": "yellow", "evidence": "yellow", "media": "yellow",
                                  "channel": "red", "offering": "red"})
        self.assertEqual(result["state"], "red")
        self.assertEqual(result["primary"]["label"], "先補齊地基")
        self.assertIsNotNone(result["secondary"])
        self.assertEqual(result["secondary"]["label"], "還是要先建立")

    def test_fix_href_names_the_onboarding_step_or_the_products_page(self):
        by_key = {item["key"]: item for item in self._result()["items"]}
        base = f"/brands/{self.brand_id}"
        self.assertEqual(by_key["identity"]["fix_href"], f"{base}/intake?step=3")
        self.assertEqual(by_key["evidence"]["fix_href"], f"{base}/intake?step=4")
        self.assertEqual(by_key["media"]["fix_href"], f"{base}/intake?step=5")
        self.assertEqual(by_key["channel"]["fix_href"], f"{base}/intake?step=6")
        # No finished sell-way yet: product onboarding (F43-I04).
        self.assertEqual(by_key["offering"]["fix_href"], f"{base}/products/new")

    def test_red_primary_jumps_to_the_first_worst_rows_own_link(self):
        result = self._result()
        worst = next(i for i in result["items"] if i["state"] == "red")
        self.assertEqual(worst["key"], "channel")
        self.assertEqual(result["primary"]["href"], worst["fix_href"])

    def test_notes_report_zero_confirmed_facts_without_blocking(self):
        self.assertIn("0", self._result()["notes"][0]["text"])


class IdentityTest(ReadinessTestBase):
    def test_confirmed_positioning_and_tone_make_identity_green(self):
        self._fact("positioning", "給忙到沒空吃飯的人的維他命軟糖")
        self._fact("tone", "親切、直接")
        self.assertEqual(self._item("identity")["state"], "green")

    def test_positioning_alone_or_unconfirmed_tone_stays_yellow(self):
        self._fact("positioning", "給忙到沒空吃飯的人的維他命軟糖")
        self.assertEqual(self._item("identity")["state"], "yellow")
        self._fact("tone", "親切、直接", status="pending")
        self.assertEqual(self._item("identity")["state"], "yellow")


class EvidenceTest(ReadinessTestBase):
    def test_one_confirmed_proof_makes_evidence_green_with_counts(self):
        self._fact("proof", "創辦人自己每天吃", fact_key="founder_voice")
        item = self._item("evidence")
        self.assertEqual(item["state"], "green")
        self.assertEqual(item["reason"], "品牌證據 1 項・政策 0 項")

    def test_one_policy_makes_evidence_green_with_counts(self):
        bi_repo.save_brand_policies(web.conn, self.brand_id, [
            {"key": "ship_threshold", "params": {"threshold": 999}},
            {"key": "cod", "params": {}},
        ], actor=ACTOR)
        item = self._item("evidence")
        self.assertEqual(item["state"], "green")
        self.assertEqual(item["reason"], "品牌證據 0 項・政策 2 項")

    def test_nothing_or_only_the_cooling_off_exemption_is_yellow(self):
        item = self._item("evidence")
        self.assertEqual(item["state"], "yellow")
        self.assertEqual(item["reason"], "還沒有登記證據或政策；廣告只會講產品本身")
        bi_repo.save_brand_policies(web.conn, self.brand_id, [
            {"key": "cooling_off_exempt",
             "params": {"disclosure": "本商品為易腐敗食品，不適用七天猶豫期"}},
        ], actor=ACTOR)
        self.assertEqual(self._item("evidence")["state"], "yellow")

    def test_pending_proof_does_not_count(self):
        self._fact("proof", "創辦人自己每天吃", status="pending", fact_key="founder_voice")
        self.assertEqual(self._item("evidence")["state"], "yellow")


class MediaTest(ReadinessTestBase):
    def test_never_asked_is_yellow(self):
        self.assertEqual(self._item("media")["state"], "yellow")

    def test_each_capability_is_green_with_its_own_reason(self):
        for value, reason in (("photo", "素材：只有照片"), ("photo_video", "素材：照片和影片")):
            bi_repo.set_media_capability(web.conn, self.brand_id, value, actor=ACTOR)
            item = self._item("media")
            self.assertEqual((item["state"], item["reason"]), ("green", reason))


class OfferingTest(ReadinessTestBase):
    def test_no_product_is_red_with_build_first_product(self):
        item = self._item("offering")
        self.assertEqual(item["state"], "red")
        self.assertEqual(item["reason"], "還沒有商品")
        self.assertEqual(item["fix_label"], "建第一個商品")
        self.assertEqual(item["fix_href"], f"/brands/{self.brand_id}/products/new")

    def test_product_without_a_finished_sell_way_is_still_no_product(self):
        # F43-I04: a knowledge product with no sell-way, or a 建到一半 product's sell-way, is
        # nothing a campaign can pick -> the same red row, opening product onboarding.
        self._add_product("只有商品")
        half = self._real_product("建到一半")
        bi_repo.set_product_onboarding_step(web.conn, self.brand_id, half, 3, actor=ACTOR)
        web.conn.commit()
        item = self._item("offering")
        self.assertEqual((item["state"], item["reason"], item["fix_label"]),
                         ("red", "還沒有商品", "建第一個商品"))
        self.assertEqual(item["fix_href"], f"/brands/{self.brand_id}/products/new")

    def test_sell_way_without_numbers_stays_red(self):
        self._add_product(selling_price=500)  # a price, no cost -> no break-even
        item = self._item("offering")
        self.assertEqual(item["state"], "red")
        self.assertIn("數字", item["reason"])
        self.assertEqual(item["fix_href"], f"/brands/{self.brand_id}/products")

    def test_real_numbers_make_offering_green(self):
        self._real_product()
        self.assertEqual(self._item("offering")["state"], "green")

    def test_assumptions_make_offering_yellow_not_red(self):
        self._real_product(assumptions=["cost"])
        item = self._item("offering")
        self.assertEqual(item["state"], "yellow")
        self.assertIn("假設", item["reason"])
        self.assertEqual(item["fix_label"], "去改")

    def test_assumption_reason_names_the_assumed_product_not_the_real_one(self):
        self._real_product("A商品")
        self._real_product("B商品", assumptions=["close_rate"])
        item = self._item("offering")
        self.assertEqual(item["state"], "yellow")
        self.assertIn("B商品", item["reason"])
        self.assertIn("成交率", item["reason"])
        self.assertNotIn("A商品的", item["reason"])


class ChannelTest(ReadinessTestBase):
    def test_goal_without_account_is_red_and_names_the_goal(self):
        self._set_goal()
        item = self._item("channel")
        self.assertEqual(item["state"], "red")
        self.assertIn("還沒接上廣告帳戶", item["reason"])
        self.assertTrue(item["reason"].endswith("・成效目標：購買"))
        self.assertEqual(item["fix_label"], "去接廣告帳戶")

    def test_missing_goal_turns_a_finished_account_red(self):
        self._connect_account(backfill_done=True)
        item = self._item("channel")
        self.assertEqual(item["state"], "red")
        self.assertTrue(item["reason"].endswith("・成效目標：還沒設定"))
        self.assertEqual(item["fix_label"], "去設定成效目標")

    def test_bound_but_not_backfilled_is_yellow_and_overall_state_follows(self):
        self._fill_other_rows()
        self._connect_account(backfill_done=False)
        result = self._result()
        channel = next(i for i in result["items"] if i["key"] == "channel")
        self.assertEqual(channel["state"], "yellow")
        self.assertIn("還沒有任何花費紀錄", channel["reason"])
        self.assertIn("・成效目標：購買", channel["reason"])
        self.assertEqual(result["state"], "yellow")
        self.assertEqual(result["primary"]["label"], "進入投放中心（有假設值）")
        self.assertIsNone(result["secondary"])

    def test_backfill_still_running_is_yellow(self):
        self._set_goal()
        self._connect_account(backfill_done=True)
        channel = self._item("channel", background_active=True)
        self.assertEqual(channel["state"], "yellow")
        self.assertIn("花費還在拉", channel["reason"])


class AllGreenTest(ReadinessTestBase):
    def test_every_row_set_and_a_finished_backfill_are_all_green(self):
        self._fill_other_rows()
        self._connect_account(backfill_done=True)
        result = self._result()
        self.assertEqual([item["state"] for item in result["items"]], ["green"] * 5)
        self.assertEqual(result["state"], "green")
        self.assertEqual(result["primary"]["label"], "進入投放中心")
        self.assertIsNone(result["secondary"])
        channel = next(i for i in result["items"] if i["key"] == "channel")
        self.assertTrue(channel["reason"].endswith("花費資料齊全・成效目標：購買"))


if __name__ == "__main__":
    unittest.main()
