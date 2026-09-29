"""app/tests/test_ads_coordinate_learning.py — F39-I01 falsifiers: closing a campaign writes one
`source_track="coordinate"` learning per ad the one ruler grades over the campaign window, with
the grade and the seven coordinate keys in `applicability_scope`; an ad under the sample gate
writes nothing; a second write is a no-op; `scoreboard_section` says so on an empty brand and,
after the close, tallies the offer key and names the 划算 ad of the last closed campaign.
Everything goes through `closeout.close()` (same entry as `test_ads_closeout.py`); the platform
rows are written the way a read writes them (`outcome_seed.bind_platform` +
`external_repository.upsert_observation` with a result mapping, the `test_ads_period_grades.py`
precedent).
"""

import unittest
from datetime import timedelta

from app.ads import closeout, coordinate_learning, external_repository, plan
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.core import settings as coresettings
from app.shared import web
from app.tests.fixtures.ads_external import outcome_seed

ACTOR = "測試員"
CAP = 100.0
DAYS = 7

_FILLER = {"pain": "p1", "angle": "a1", "hook": "h1", "proof": "pr1", "format": "f1"}


class CoordinateLearningTestBase(unittest.TestCase):
    def setUp(self):
        self.conn = web.conn
        self.org_id = coredb.DEV_ORG_ID
        self.brand_id = bi_repo.create_brand(
            self.conn, org_id=self.org_id, name="測試品牌：座標學習", client_name=None,
            actor=ACTOR,
        )["id"]
        self.today = coresettings.today_for_org(self.conn, org_id=self.org_id)
        self.start = self.today - timedelta(days=DAYS - 1)
        self.conn.commit()

    def _campaign(self, name="測試 座標學習") -> dict:
        campaign = ads_repo.create_campaign(self.conn, self.org_id, self.brand_id, {
            "name": name, "goal_text": "衝一波", "objective": "購買", "target_cost": CAP,
            "start_date": self.start, "end_date": self.today, "status": "live",
        }, created_by=ACTOR)
        outcome_seed.set_coverage(
            self.conn, self.org_id, self.brand_id, campaign["id"], self.start, self.today,
        )
        self.conn.commit()
        return campaign

    def _group(self, campaign_id: str) -> dict:
        return plan.create_group(
            self.conn, self.org_id, self.brand_id, campaign_id, name="投放組", role="new",
            daily_budget=500,
        )

    def _ad(self, campaign_id: str, group_id: str, *, name: str, audience: str,
            offer: str) -> dict:
        return plan.create_ad(
            self.conn, self.org_id, self.brand_id, campaign_id, group_id, name=name,
            coordinates={"audience": audience, "offer": offer, **_FILLER},
        )

    def _observe(self, campaign_id: str, entity_id: str, *, days: int, spend: float,
                 results: int) -> None:
        """`days` platform days of one ad, the way a read writes them (result mapping included)."""
        for offset in range(days):
            external_repository.upsert_observation(
                self.conn, self.org_id, self.brand_id, campaign_id,
                {"entity_id": entity_id, "day": self.start + timedelta(days=offset),
                 "metric_scope": "ad", "attribution_key": outcome_seed.ATTRIBUTION_KEY,
                 "currency": "TWD", "source": "simulated", "spend": spend,
                 "impressions": 100, "clicks": 10, "purchases": results},
                result_kind="purchase", result_count=results, result_action="omni_purchase",
                result_attribution="7d_click+1d_view",
            )
        self.conn.commit()

    def _bind(self, campaign_id: str) -> dict:
        ids = outcome_seed.bind_platform(self.conn, self.org_id, self.brand_id, campaign_id)
        self.conn.commit()
        return ids

    def _coordinate_rows(self) -> list:
        return bi_repo.list_learnings(self.conn, self.brand_id, source_track="coordinate")

    def _two_graded_ads(self) -> tuple[dict, dict, dict]:
        """Campaign with ad A 划算 (7 × 50 spend, 1 result a day) and ad B 沒賣出 (7 × 50 spend,
        0 results): both past the sample gate (spend >= 3 × cap)."""
        campaign = self._campaign()
        group = self._group(campaign["id"])
        ad_a = self._ad(campaign["id"], group["id"], name="A", audience="cold_unaware",
                        offer="free_shipping")
        ad_b = self._ad(campaign["id"], group["id"], name="B", audience="warm_retarget",
                        offer="discount")
        ids = self._bind(campaign["id"])
        self._observe(campaign["id"], ids[ad_a["id"]], days=DAYS, spend=50.0, results=1)
        self._observe(campaign["id"], ids[ad_b["id"]], days=DAYS, spend=50.0, results=0)
        return campaign, ad_a, ad_b


class CloseWritesOneLearningPerGradedAdTest(CoordinateLearningTestBase):
    def test_two_graded_ads_write_two_coordinate_rows_with_the_exact_scope(self):
        campaign, ad_a, ad_b = self._two_graded_ads()

        closed = closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        rows = {row["source_cycle_id"]: row for row in self._coordinate_rows()}
        self.assertEqual(
            set(rows), {f"{campaign['id']}:{ad_a['id']}", f"{campaign['id']}:{ad_b['id']}"},
        )
        row_a = rows[f"{campaign['id']}:{ad_a['id']}"]
        self.assertEqual(
            row_a["applicability_scope"],
            "coord；grade=on_target；audience=cold_unaware；pain=p1；angle=a1；hook=h1；proof=pr1"
            "；offer=free_shipping；format=f1",
        )
        self.assertEqual(
            row_a["learning_text"],
            "「A」每筆 50（上限 100）＝划算；audience=cold_unaware、pain=p1、angle=a1、hook=h1"
            "、proof=pr1、offer=free_shipping、format=f1",
        )
        self.assertEqual(row_a["confidence"], "observed")
        self.assertEqual(row_a["sample_size"], "高")
        row_b = rows[f"{campaign['id']}:{ad_b['id']}"]
        self.assertEqual(
            row_b["applicability_scope"],
            "coord；grade=wasted；audience=warm_retarget；pain=p1；angle=a1；hook=h1；proof=pr1"
            "；offer=discount；format=f1",
        )
        self.assertTrue(row_b["learning_text"].startswith("「B」每筆 —（上限 100）＝沒賣出；"))
        self.assertEqual(row_b["sample_size"], "低")
        # The campaign sentence stays on the ads track; the closed row carries every id.
        self.assertEqual(
            len(bi_repo.list_learnings(self.conn, self.brand_id, source_track="ads")), 1,
        )
        self.assertEqual(
            set(closed["verdict_json"]["learning_ids"]) & {row_a["id"], row_b["id"]},
            {row_a["id"], row_b["id"]},
        )

    def test_an_ad_under_the_sample_gate_writes_no_coordinate_row(self):
        campaign = self._campaign()
        group = self._group(campaign["id"])
        ad = self._ad(campaign["id"], group["id"], name="C", audience="cold_unaware",
                      offer="free_shipping")
        ids = self._bind(campaign["id"])
        # 2 × 50 spend < 3 × cap and 2 results < 10: 剛開始, never graded.
        self._observe(campaign["id"], ids[ad["id"]], days=2, spend=50.0, results=1)

        closed = closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        self.assertEqual(self._coordinate_rows(), [])
        self.assertEqual(len(closed["verdict_json"]["learning_ids"]), 1)

    def test_writing_twice_adds_no_duplicate(self):
        campaign, _ad_a, _ad_b = self._two_graded_ads()
        closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)
        self.assertEqual(len(self._coordinate_rows()), 2)

        again = coordinate_learning.write_coordinate_learnings(
            self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR,
        )
        closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        self.assertEqual(again, [])
        self.assertEqual(len(self._coordinate_rows()), 2)


class ScoreboardSectionTest(CoordinateLearningTestBase):
    def test_empty_brand_says_there_is_no_scoreboard(self):
        text, ids = coordinate_learning.scoreboard_section(
            self.conn, self.org_id, self.brand_id,
        )
        self.assertEqual(text, "【座標成績表】（還沒有結案過的廣告，沒有成績表）")
        self.assertEqual(ids, [])

    def test_after_the_close_the_section_tallies_and_names_the_on_target_ad(self):
        self.conn.execute(
            "INSERT INTO brand_coordinate(id,org_id,brand_id,dimension,key,label) "
            "VALUES(%s,%s,%s,'offer','free_shipping','免運')",
            (coredb.new_id("crd"), self.org_id, self.brand_id),
        )
        campaign, _ad_a, _ad_b = self._two_graded_ads()
        closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        text, ids = coordinate_learning.scoreboard_section(
            self.conn, self.org_id, self.brand_id,
        )

        lines = text.split("\n")
        self.assertEqual(lines[0], "【座標成績表（已結案活動，程式統計；划算＝每筆成本在上限內）】")
        self.assertIn("- offer｜free_shipping｜免運：划算 1、偏貴 0、太貴 0、沒賣出 0", lines)
        self.assertIn("- offer｜discount｜discount：划算 0、偏貴 0、太貴 0、沒賣出 1", lines)
        self.assertIn("- audience｜cold_unaware｜cold_unaware：划算 1、偏貴 0、太貴 0、沒賣出 0",
                      lines)
        self.assertIn(
            "上一期「測試 座標學習」划算的：「A」（audience=cold_unaware、pain=p1、angle=a1"
            "、hook=h1、proof=pr1、offer=free_shipping、format=f1）",
            lines,
        )
        self.assertIn(
            "上一期太貴／沒賣出的：「B」沒賣出（audience=warm_retarget、pain=p1、angle=a1、hook=h1"
            "、proof=pr1、offer=discount、format=f1）",
            lines,
        )
        # Dimension order is the learning order: audience lines come before offer lines.
        self.assertLess(
            lines.index("- audience｜cold_unaware｜cold_unaware：划算 1、偏貴 0、太貴 0、沒賣出 0"),
            lines.index("- offer｜free_shipping｜免運：划算 1、偏貴 0、太貴 0、沒賣出 0"),
        )
        self.assertEqual(set(ids), {row["id"] for row in self._coordinate_rows()})


if __name__ == "__main__":
    unittest.main()
