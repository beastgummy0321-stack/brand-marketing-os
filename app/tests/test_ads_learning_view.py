"""app/tests/test_ads_learning_view.py — F46-I04 Contract L falsifiers: `learnings_view` lists the
brand's closed internal campaigns newest closed first with their ranked rows (numbers straight
from the stored `v=2` scope; old grade rows are not read), the per-campaign totals, counts and
rule text, an `empty_reason` for a campaign with no row (missing days vs nothing spent), the
customer-group summary (a deleted group reads 已刪除的顧客群), `closed_on` as the org-local
date, the `campaign_id` / `sell_way_id` filters and the next-campaign link.

Rows are seeded with the public `record_learning` (the scope the closeout writes is proven in
`test_ads_coordinate_learning.py`); each ranked ad also spends on the platform inside the window,
because a campaign's own totals are its closed-window platform totals over every ad (F51 planning
#16: an unranked ad that spent counts; a customer group across campaigns with different caps has
no one cap).
"""

import unittest
from datetime import UTC, date, datetime

from app.ads import external_repository, learning_view, outcome, plan
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.shared import web
from app.tests.fixtures.ads_external import outcome_seed

ACTOR = "測試員"


class LearningViewTestBase(unittest.TestCase):
    def setUp(self):
        self.conn = web.conn
        self.org_id = coredb.DEV_ORG_ID
        self.brand_id = bi_repo.create_brand(
            self.conn, org_id=self.org_id, name="測試品牌：學到的", client_name=None,
            actor=ACTOR,
        )["id"]
        self.product = bi_repo.create_product(self.conn, self.brand_id, name="三盒組",
                                              actor=ACTOR)
        self.other_product = bi_repo.create_product(self.conn, self.brand_id, name="單盒",
                                                    actor=ACTOR)
        self.groups = bi_repo.save_customer_groups(
            self.conn, self.brand_id, self.product["id"],
            [{"who": "學生備考", "pain_keys": ["effort"]},
             {"who": "通勤上班族", "pain_keys": ["experience"]}], actor=ACTOR,
        )
        self.conn.execute(
            "INSERT INTO brand_coordinate(id,org_id,brand_id,dimension,key,label) "
            "VALUES(%s,%s,%s,'angle','box','書包裡放一盒')",
            (coredb.new_id("crd"), self.org_id, self.brand_id),
        )
        self.conn.commit()

    def _closed(self, name: str, closed_at: datetime, *, product_id: str | None = None,
                verdict_json: dict | None = None) -> dict:
        campaign = ads_repo.create_campaign(self.conn, self.org_id, self.brand_id, {
            "name": name, "goal_text": "x", "objective": "購買", "target_cost": 450,
            "start_date": "2026-09-05", "end_date": "2026-09-18", "status": "closed",
            # F48 Contract M: a non-draft campaign's sell-way is fixed (no PATCH after adoption).
            "context_json": {"product_ids": [product_id or self.product["id"]]},
        }, created_by=ACTOR)
        self.conn.execute(
            "UPDATE ads_campaign SET closed_at = %s, verdict_json = %s WHERE id = %s",
            (closed_at, coredb.jsonb(verdict_json or {}), campaign["id"]),
        )
        self.conn.commit()
        return campaign

    def _ad(self, campaign: dict, name: str, angle: str = "box") -> dict:
        group_obj = plan.create_group(
            self.conn, self.org_id, self.brand_id, campaign["id"], name=f"組 {name}",
            role="new", daily_budget=500,
        )
        return plan.create_ad(
            self.conn, self.org_id, self.brand_id, campaign["id"], group_obj["id"], name=name,
            coordinates={"audience": "cold", "pain": "effort", "angle": angle, "hook": "h",
                         "proof": "none", "offer": "none", "format": "single_image"},
        )

    def _spent(self, campaign: dict, ad: dict, *, spend: int, sales: int) -> None:
        """One platform day of `ad` inside the window, written the way a read writes it."""
        ids = outcome_seed.bind_platform(self.conn, self.org_id, self.brand_id, campaign["id"])
        external_repository.upsert_observation(
            self.conn, self.org_id, self.brand_id, campaign["id"],
            {"entity_id": ids[ad["id"]], "day": date(2026, 9, 6), "metric_scope": "ad",
             "attribution_key": outcome_seed.ATTRIBUTION_KEY, "currency": "TWD",
             "source": "test", "spend": spend, "impressions": 100, "purchases": sales},
            result_kind="purchase", result_count=sales, result_action="omni_purchase",
            result_attribution="7d_click",
        )
        self.conn.commit()

    def _ranked(self, campaign: dict, name: str, *, verdict: str, rank: int, of: int,
                sales: int, spend: int, group: str | None, few: int = 0,
                angle: str = "box", cap: int = 450) -> dict:
        ad = self._ad(campaign, name, angle)
        self._spent(campaign, ad, spend=spend, sales=sales)
        cpr = round(spend / sales) if sales else "none"
        scope = (
            f"coord；v=2；verdict={verdict}；rank={rank}；of={of}；sales={sales}；spend={spend}"
            f"；cpr={cpr}；cap={cap}；few={few}；group={group or 'none'}；audience=cold"
            f"；pain=effort；angle={angle}；hook=h；proof=none；offer=none；format=single_image；cur=TWD"
        )
        bi_repo.record_learning(
            self.conn, self.brand_id, actor=ACTOR, learning_text=name,
            applicability_scope=scope, confidence="observed", sample_size="高",
            source_cycle_id=f"{campaign['id']}:{ad['id']}", source_track="coordinate",
        )
        return ad

    def _view(self, **kwargs) -> dict:
        return learning_view.learnings_view(self.conn, self.org_id, self.brand_id, **kwargs)


class ViewShapeTest(LearningViewTestBase):
    def test_campaigns_rows_totals_and_groups_come_from_the_stored_scope(self):
        students, commuters = self.groups[0]["id"], self.groups[1]["id"]
        older = self._closed("三盒組・第一期", datetime(2026, 9, 19, 2, 0, tzinfo=UTC))
        self._ranked(older, "備考生・讀到深夜", verdict="keep", rank=1, of=2, sales=4,
                     spend=1160, group=students, few=1)
        self._ranked(older, "會議前・午休", verdict="replace", rank=2, of=2, sales=0,
                     spend=1420, group=commuters, angle="nap")
        # Closed 2026-10-01 18:30 UTC = 2026-10-02 in Taipei.
        newer = self._closed("三盒組・第二期", datetime(2026, 10, 1, 18, 30, tzinfo=UTC))
        self._ranked(newer, "考前一週・書包一盒", verdict="keep_relative", rank=1, of=3, sales=5,
                     spend=2775, group=students)
        self._ranked(newer, "通勤族・地鐵十分鐘", verdict="replace", rank=2, of=3, sales=2,
                     spend=3286, group="pcg_gone", few=1, angle="metro")
        self._ranked(newer, "沒有群", verdict="replace", rank=3, of=3, sales=0, spend=300,
                     group=None, angle="nap")
        # An F39 grade row of the same campaign is not read.
        bi_repo.record_learning(
            self.conn, self.brand_id, actor=ACTOR, learning_text="舊格式",
            applicability_scope="coord；grade=on_target；cpr=50；cap=100；audience=a；pain=p"
            "；angle=g；hook=h；proof=r；offer=o；format=f",
            confidence="observed", sample_size="高",
            source_cycle_id=f"{newer['id']}:ad_old", source_track="coordinate",
        )

        view = self._view()

        self.assertEqual([c["campaign_name"] for c in view["campaigns"]],
                         ["三盒組・第二期", "三盒組・第一期"])
        latest = view["campaigns"][0]
        self.assertEqual(
            {k: latest[k] for k in ("sell_way_id", "start_date", "end_date", "closed_on", "cap",
                                    "currency", "spend", "sales", "counts", "empty_reason")},
            {"sell_way_id": self.product["id"], "start_date": "2026-09-05",
             "end_date": "2026-09-18", "closed_on": "2026-10-02", "cap": 450, "currency": "TWD",
             "spend": 6361, "sales": 7, "counts": {"keep": 1, "replace": 2},
             "empty_reason": None},
        )
        self.assertAlmostEqual(latest["cost_per_sale"], 6361 / 7)
        self.assertEqual(latest["rule_text"],
                         "沒有一則低於上限 450 → 留下最好的 555 和 722 以內的；其餘換掉")
        first = latest["rows"][0]
        self.assertEqual(
            {k: first[k] for k in ("rank", "of", "ad_name", "customer_group", "spend", "sales",
                                   "cost_per_sale", "verdict", "verdict_label", "flags")},
            {"rank": 1, "of": 3, "ad_name": "考前一週・書包一盒",
             "customer_group": {"id": students, "who": "學生備考"}, "spend": 2775, "sales": 5,
             "cost_per_sale": 555, "verdict": "keep_relative", "verdict_label": "留下",
             "flags": ["相對最好，仍高於上限"]},
        )
        self.assertIn(
            {"dimension": "angle", "dimension_label": "角度", "key": "box",
             "label": "書包裡放一盒"},
            first["coordinates"],
        )
        # `none` coordinates are omitted.
        self.assertNotIn("offer", [c["dimension"] for c in first["coordinates"]])
        second, third = latest["rows"][1], latest["rows"][2]
        self.assertEqual(second["customer_group"], {"id": "pcg_gone", "who": "已刪除的顧客群"})
        self.assertEqual(second["flags"], ["樣本少"])
        self.assertIsNone(third["customer_group"])
        self.assertIsNone(third["cost_per_sale"])

        self.assertEqual(view["campaigns"][1]["rule_text"], "1 則每筆低於上限 450 → 留下；其餘換掉")
        self.assertEqual(view["campaigns"][1]["rows"][0]["flags"], ["樣本少"])

        self.assertEqual(
            [(g["who"], g["ads"], g["spend"], g["sales"]) for g in view["groups"]],
            [("學生備考", 2, 3935, 9), ("已刪除的顧客群", 1, 3286, 2),
             ("通勤上班族", 1, 1420, 0)],
        )
        self.assertIsNone(view["groups"][2]["cost_per_sale"])
        self.assertEqual(view["groups"][0]["cap"], 450)
        self.assertFalse(view["groups"][0]["caps_differ"])
        self.assertEqual(view["next"], {
            "sell_way_id": self.product["id"],
            "new_campaign_href": f"/brands/{self.brand_id}/ads/new?sell_way={self.product['id']}",
        })


class CampaignTotalsTest(LearningViewTestBase):
    """F51 planning #16: 上一期花費 counts every ad of the window, ranked or not."""

    def test_an_unranked_spending_ad_counts_in_the_campaign_spend(self):
        campaign = self._closed("三盒組・第三期", datetime(2026, 9, 19, tzinfo=UTC))
        self._ranked(campaign, "賣得動", verdict="keep", rank=1, of=1, sales=3, spend=900,
                     group=self.groups[0]["id"])
        # A known zero under the 沒賣出 line (3 × 450): never ranked, but it spent.
        self._spent(campaign, self._ad(campaign, "剛開始"), spend=400, sales=0)

        listed = self._view()["campaigns"][0]

        platform_spend = sum(
            float(r["spend"]) for r in outcome.rows(
                self.conn, self.org_id, self.brand_id, campaign["id"], "ad")
        )
        self.assertEqual(platform_spend, 1300)
        self.assertEqual((listed["spend"], listed["sales"]), (platform_spend, 3))
        self.assertAlmostEqual(listed["cost_per_sale"], 1300 / 3)
        self.assertEqual(len(listed["rows"]), 1)  # the ranking itself is unchanged

    def test_no_platform_row_is_unknown_never_zero(self):
        campaign = self._closed("沒讀到", datetime(2026, 9, 19, tzinfo=UTC))
        listed = self._view(campaign_id=campaign["id"])["campaigns"][0]
        self.assertEqual((listed["spend"], listed["sales"], listed["cost_per_sale"]),
                         (None, None, None))

    def test_a_group_across_campaigns_with_different_caps_has_no_one_cap(self):
        students = self.groups[0]["id"]
        older = self._closed("第一期", datetime(2026, 9, 19, tzinfo=UTC))
        self._ranked(older, "甲", verdict="keep", rank=1, of=1, sales=2, spend=600,
                     group=students, cap=450)
        newer = self._closed("第二期", datetime(2026, 9, 20, tzinfo=UTC))
        self._ranked(newer, "乙", verdict="keep", rank=1, of=1, sales=2, spend=500,
                     group=students, cap=300)

        group = self._view()["groups"][0]

        self.assertEqual((group["who"], group["spend"], group["sales"]), ("學生備考", 1100, 4))
        self.assertEqual((group["cap"], group["caps_differ"]), (None, True))


class EmptyAndFilterTest(LearningViewTestBase):
    def test_empty_reason_names_missing_days_or_no_spend(self):
        self._closed("缺天的一期", datetime(2026, 9, 20, tzinfo=UTC),
                     verdict_json={"missing_days": ["2026-09-06"]})
        self._closed("模擬缺天", datetime(2026, 9, 19, tzinfo=UTC),
                     verdict_json={"missing": "模擬回收尚有缺日或缺廣告，不把缺資料視為零。"})
        self._closed("沒花錢", datetime(2026, 9, 18, tzinfo=UTC))

        view = self._view()

        self.assertEqual(
            [(c["campaign_name"], c["empty_reason"], c["rows"], c["rule_text"])
             for c in view["campaigns"]],
            [("缺天的一期", "資料缺天，這期沒有記學習", [], None),
             ("模擬缺天", "資料缺天，這期沒有記學習", [], None),
             ("沒花錢", "這期沒有花到錢的廣告", [], None)],
        )
        self.assertEqual(view["groups"], [])

    def test_filters_by_campaign_and_sell_way_and_limit(self):
        mine = self._closed("三盒組", datetime(2026, 9, 19, tzinfo=UTC))
        self._ranked(mine, "甲", verdict="keep", rank=1, of=1, sales=6, spend=1200,
                     group=self.groups[0]["id"])
        other = self._closed("單盒", datetime(2026, 9, 20, tzinfo=UTC),
                             product_id=self.other_product["id"])
        # Open and draft campaigns are never listed.
        ads_repo.create_campaign(self.conn, self.org_id, self.brand_id, {
            "name": "進行中", "goal_text": "x", "objective": "購買", "status": "live",
        }, created_by=ACTOR)
        self.conn.commit()

        self.assertEqual([c["campaign_name"] for c in self._view()["campaigns"]],
                         ["單盒", "三盒組"])
        self.assertEqual(
            [c["campaign_name"] for c in self._view(sell_way_id=self.product["id"])["campaigns"]],
            ["三盒組"],
        )
        only = self._view(campaign_id=other["id"])
        self.assertEqual([c["campaign_name"] for c in only["campaigns"]], ["單盒"])
        self.assertEqual(only["next"]["sell_way_id"], self.other_product["id"])
        self.assertEqual([c["campaign_name"] for c in self._view(limit=1)["campaigns"]], ["單盒"])
        self.assertEqual(learning_view.learning_ids(self._view(campaign_id=mine["id"])),
                         [self._view()["campaigns"][1]["rows"][0]["learning_id"]])

    def test_brand_without_closed_campaigns_is_empty(self):
        self.assertEqual(self._view(), {"campaigns": [], "groups": [], "next": None})


if __name__ == "__main__":
    unittest.main()
