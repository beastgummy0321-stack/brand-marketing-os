"""app/tests/test_ads_coordinate_learning.py — F46-I04 falsifiers (Contracts B and G): closing a
campaign writes one ranked `v=2` coordinate learning per ad the ranking rule enters (the drill-10
P1 shape: nothing under the cap 450 -> the 555 ad is kept relative, 1,643 / 1,769 / 沒賣出 are
replaced), an ad the old sample gate skipped now enters, a second write is a no-op, partial data
writes nothing, the customer group is stored and named (a deleted one reads 已刪除的顧客群);
`ranked_section` prints 【上幾期的排名】 numbered by this campaign's customer groups;
`gate_pairs` gives the plan gate its keep / replace pairs.

Everything goes through `closeout.close()`; the platform rows are written the way a read writes
them (`outcome_seed.bind_platform` + `external_repository.upsert_observation`).
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
CAP = 450.0
DAYS = 7

_FILLER = {"audience": "cold", "hook": "h1", "proof": "pr1", "offer": "none", "format": "f1"}


class CoordinateLearningTestBase(unittest.TestCase):
    def setUp(self):
        self.conn = web.conn
        self.org_id = coredb.DEV_ORG_ID
        self.brand_id = bi_repo.create_brand(
            self.conn, org_id=self.org_id, name="測試品牌：排名學習", client_name=None,
            actor=ACTOR,
        )["id"]
        self.today = coresettings.today_for_org(self.conn, org_id=self.org_id)
        self.start = self.today - timedelta(days=DAYS - 1)
        product = bi_repo.create_product(self.conn, self.brand_id, name="三盒組", actor=ACTOR)
        self.product_id = product["id"]
        self.groups = bi_repo.save_customer_groups(self.conn, self.brand_id, product["id"], [
            {"who": "學生備考", "pain_keys": ["effort"]},
            {"who": "通勤上班族", "pain_keys": ["experience"]},
        ], actor=ACTOR)
        self.conn.commit()

    def _campaign(self, name="三盒組・第一期") -> dict:
        campaign = ads_repo.create_campaign(self.conn, self.org_id, self.brand_id, {
            "name": name, "goal_text": "衝一波", "objective": "購買", "target_cost": CAP,
            "start_date": self.start, "end_date": self.today, "status": "live",
        }, created_by=ACTOR)
        ads_repo.update_campaign(self.conn, self.org_id, self.brand_id, campaign["id"],
                                 {"product_ids": [self.product_id]})
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

    def _ad(self, campaign_id: str, group_id: str, *, name: str, angle: str, pain: str,
            customer_group_id: str | None) -> dict:
        ad = plan.create_ad(
            self.conn, self.org_id, self.brand_id, campaign_id, group_id, name=name,
            coordinates={"angle": angle, "pain": pain, **_FILLER},
        )
        self.conn.execute(
            "UPDATE ads_ad SET customer_group_id = %s WHERE id = %s",
            (customer_group_id, ad["id"]),
        )
        self.conn.commit()
        return ad

    def _observe(self, campaign_id: str, entity_id: str, *, days: int, spend: float,
                 results: int) -> None:
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

    def _coordinate_rows(self) -> list:
        return bi_repo.list_learnings(self.conn, self.brand_id, source_track="coordinate")

    def _vocabulary(self) -> None:
        for dimension, key, label in (
            ("angle", "box", "書包裡放一盒"), ("angle", "metro", "十分鐘醒腦"),
            ("angle", "overtime", "六點後的第二段"), ("pain", "effort", "熬夜讀不完"),
        ):
            self.conn.execute(
                "INSERT INTO brand_coordinate(id,org_id,brand_id,dimension,key,label) "
                "VALUES(%s,%s,%s,%s,%s,%s)",
                (coredb.new_id("crd"), self.org_id, self.brand_id, dimension, key, label),
            )
        self.conn.commit()

    def _drill_ten(self, name="三盒組・第一期") -> tuple[dict, dict]:
        """Drill-10 P1: 555 × 6 sales, 1,643 × 2, 1,769 × 2 and one ad that sold nothing on 900,
        all under cap 450 -- nothing under the cap."""
        campaign = self._campaign(name)
        group = self._group(campaign["id"])
        students, commuters = self.groups[0]["id"], self.groups[1]["id"]
        ads = {
            "box": self._ad(campaign["id"], group["id"], name="考前一週・書包一盒", angle="box",
                            pain="effort", customer_group_id=students),
            "metro": self._ad(campaign["id"], group["id"], name="通勤族・地鐵十分鐘",
                              angle="metro", pain="experience", customer_group_id=commuters),
            "overtime": self._ad(campaign["id"], group["id"], name="通勤族・下班後加班",
                                 angle="overtime", pain="experience", customer_group_id=commuters),
            "nap": self._ad(campaign["id"], group["id"], name="會議前・午休五分鐘", angle="nap",
                            pain="experience", customer_group_id=None),
        }
        ids = outcome_seed.bind_platform(self.conn, self.org_id, self.brand_id, campaign["id"])
        self.conn.commit()
        self._observe(campaign["id"], ids[ads["box"]["id"]], days=6, spend=555.0, results=1)
        self._observe(campaign["id"], ids[ads["metro"]["id"]], days=2, spend=1643.0, results=1)
        self._observe(campaign["id"], ids[ads["overtime"]["id"]], days=2, spend=1769.0,
                      results=1)
        self._observe(campaign["id"], ids[ads["nap"]["id"]], days=3, spend=300.0, results=0)
        return campaign, ads

    def _close(self, campaign: dict) -> dict:
        return closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)


class CloseWritesRankedRowsTest(CoordinateLearningTestBase):
    def test_drill_ten_shape_writes_four_ranked_rows_with_the_exact_scope(self):
        self._vocabulary()
        campaign, ads = self._drill_ten()

        closed = self._close(campaign)

        rows = {row["source_cycle_id"]: row for row in self._coordinate_rows()}
        self.assertEqual(set(rows), {f"{campaign['id']}:{ad['id']}" for ad in ads.values()})
        box = rows[f"{campaign['id']}:{ads['box']['id']}"]
        self.assertEqual(
            box["applicability_scope"],
            f"coord；v=2；verdict=keep_relative；rank=1；of=4；sales=6；spend=3330；cpr=555"
            f"；cap=450；few=0；group={self.groups[0]['id']}；audience=cold；pain=effort；angle=box"
            "；hook=h1；proof=pr1；offer=none；format=f1；cur=TWD",
        )
        self.assertEqual(
            box["learning_text"],
            "第 1／4 名「考前一週・書包一盒」每筆 555（賣 6 筆、花 3,330；上限 450）＝留下"
            "（相對最好，仍高於上限）；顧客群：學生備考；受眾：cold、痛點：熬夜讀不完"
            "、角度：書包裡放一盒、標題：h1、證據：pr1、格式：f1",
        )
        self.assertEqual(box["sample_size"], "高")
        metro = rows[f"{campaign['id']}:{ads['metro']['id']}"]
        self.assertIn("verdict=replace；rank=2；of=4；sales=2；spend=3286；cpr=1643",
                      metro["applicability_scope"])
        self.assertIn("few=1", metro["applicability_scope"])
        self.assertEqual(metro["sample_size"], "低")
        overtime = rows[f"{campaign['id']}:{ads['overtime']['id']}"]
        self.assertIn("rank=3；of=4", overtime["applicability_scope"])
        nap = rows[f"{campaign['id']}:{ads['nap']['id']}"]
        self.assertIn("verdict=replace；rank=4；of=4；sales=0；spend=900；cpr=none；cap=450；few=0"
                      "；group=none", nap["applicability_scope"])
        self.assertTrue(nap["learning_text"].startswith(
            "第 4／4 名「會議前・午休五分鐘」沒賣出（花 900；上限 450）＝換掉；顧客群：未指定；",
        ))
        self.assertEqual(nap["sample_size"], "低")
        self.assertEqual(
            set(closed["verdict_json"]["learning_ids"]) & {r["id"] for r in rows.values()},
            {r["id"] for r in rows.values()},
        )

    def test_an_ad_the_old_sample_gate_skipped_now_enters_kept_and_flagged_few(self):
        campaign = self._campaign()
        group = self._group(campaign["id"])
        ad = self._ad(campaign["id"], group["id"], name="備考生・讀到深夜", angle="box",
                      pain="effort", customer_group_id=self.groups[0]["id"])
        ids = outcome_seed.bind_platform(self.conn, self.org_id, self.brand_id, campaign["id"])
        self.conn.commit()
        # 4 × 290 spend < 3 × cap and 4 results < 10: the F39 gate wrote nothing for this ad.
        self._observe(campaign["id"], ids[ad["id"]], days=4, spend=290.0, results=1)

        closed = self._close(campaign)

        (row,) = self._coordinate_rows()
        self.assertIn("verdict=keep；rank=1；of=1；sales=4；spend=1160；cpr=290；cap=450；few=1",
                      row["applicability_scope"])
        self.assertIn("＝留下（樣本少）", row["learning_text"])
        self.assertEqual(len(closed["verdict_json"]["learning_ids"]), 2)

    def test_writing_twice_adds_no_duplicate(self):
        campaign, _ads = self._drill_ten()
        self._close(campaign)
        self.assertEqual(len(self._coordinate_rows()), 4)

        again = coordinate_learning.write_coordinate_learnings(
            self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR,
        )
        self._close(campaign)

        self.assertEqual(again, [])
        self.assertEqual(len(self._coordinate_rows()), 4)

    def test_a_deleted_customer_group_is_named_as_deleted(self):
        campaign = self._campaign()
        group = self._group(campaign["id"])
        ad = self._ad(campaign["id"], group["id"], name="舊群廣告", angle="box", pain="effort",
                      customer_group_id="pcg_gone")
        ids = outcome_seed.bind_platform(self.conn, self.org_id, self.brand_id, campaign["id"])
        self.conn.commit()
        self._observe(campaign["id"], ids[ad["id"]], days=2, spend=100.0, results=1)

        self._close(campaign)

        (row,) = self._coordinate_rows()
        self.assertIn("group=pcg_gone", row["applicability_scope"])
        self.assertIn("；顧客群：已刪除的顧客群；", row["learning_text"])

    def test_partial_data_writes_no_ranked_row(self):
        campaign, _ads = self._drill_ten()
        outcome_seed.set_coverage(
            self.conn, self.org_id, self.brand_id, campaign["id"],
            self.start + timedelta(days=2), self.today,
        )
        external_repository.record_sync(
            self.conn, self.org_id, self.brand_id, campaign["id"], section="observations",
            state={"status": "error", "error": "平台逾時"},
        )
        self.conn.commit()
        # Days 0–1 carry rows, so delete them to open a real gap before the covered range.
        self.conn.execute(
            "DELETE FROM ads_external_daily WHERE campaign_id = %s AND day < %s",
            (campaign["id"], self.start + timedelta(days=2)),
        )
        self.conn.commit()

        closed = closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"],
                                actor=ACTOR, skip_missing=True)

        self.assertEqual(closed["verdict"], "看不出")
        self.assertEqual(self._coordinate_rows(), [])


class RankedSectionTest(CoordinateLearningTestBase):
    def test_empty_brand_says_there_is_nothing_ranked(self):
        campaign = self._campaign("新的一期")
        text, ids = coordinate_learning.ranked_section(
            self.conn, self.org_id, self.brand_id, campaign,
        )
        self.assertEqual(text, "【上幾期的排名】（還沒有結案過的廣告）")
        self.assertEqual(ids, [])

    def test_section_numbers_groups_by_this_campaigns_list(self):
        self._vocabulary()
        campaign, _ads = self._drill_ten()
        self._close(campaign)
        draft = ads_repo.create_campaign(self.conn, self.org_id, self.brand_id, {
            "name": "三盒組・第二期", "goal_text": "再一波", "objective": "購買",
            "target_cost": CAP, "status": "draft",
        }, created_by=ACTOR)
        ads_repo.update_campaign(self.conn, self.org_id, self.brand_id, draft["id"],
                                 {"product_ids": [self.product_id]})
        self.conn.commit()
        draft = ads_repo.get_campaign(self.conn, self.org_id, self.brand_id, draft["id"])

        text, ids = coordinate_learning.ranked_section(
            self.conn, self.org_id, self.brand_id, draft,
        )

        lines = text.split("\n")
        self.assertEqual(lines[0], "【上幾期的排名（程式排的；每筆＝花費÷成交）】")
        self.assertEqual(lines[1:3], [
            "- 顧客群 第 1 群（學生備考）｜1 則廣告｜賣 6 筆｜花 3,330｜每筆 555｜上限 450",
            "- 顧客群 第 2 群（通勤上班族）｜2 則廣告｜賣 4 筆｜花 6,824｜每筆 1,706｜上限 450",
        ])
        self.assertEqual(
            lines[3],
            "三盒組・第一期（上限 450）：沒有一則低於上限 450 → 留下最好的 555 和 722 以內的"
            "；其餘換掉",
        )
        self.assertEqual(
            lines[4],
            "- 三盒組・第一期第 1／4 名｜留下・相對最好，仍高於上限｜顧客群 1"
            "｜「考前一週・書包一盒」｜每筆 555｜賣 6 筆｜花 3,330｜cold（audience=cold）"
            "、熬夜讀不完（pain=effort）、書包裡放一盒（angle=box）、h1（hook=h1）"
            "、pr1（proof=pr1）、未設定（offer=none）、f1（format=f1）",
        )
        self.assertTrue(lines[5].startswith(
            "- 三盒組・第一期第 2／4 名｜換掉・樣本少｜顧客群 2｜「通勤族・地鐵十分鐘」"
            "｜每筆 1,643｜",
        ))
        self.assertTrue(lines[7].startswith(
            "- 三盒組・第一期第 4／4 名｜換掉｜顧客群 未指定｜「會議前・午休五分鐘」"
            "｜每筆 沒賣出｜賣 0 筆",
        ))
        self.assertEqual(set(ids), {row["id"] for row in self._coordinate_rows()})

        # A campaign that does not list the group reads 「這期沒列」.
        bare = ads_repo.create_campaign(self.conn, self.org_id, self.brand_id, {
            "name": "沒商品", "goal_text": "x", "objective": "購買", "status": "draft",
        }, created_by=ACTOR)
        self.conn.commit()
        text, _ = coordinate_learning.ranked_section(self.conn, self.org_id, self.brand_id, bare)
        self.assertIn("｜顧客群 這期沒列：學生備考｜「考前一週・書包一盒」", text)
        self.assertIn("- 顧客群 這期沒列：學生備考｜", text)


class GatePairsTest(CoordinateLearningTestBase):
    def test_keep_and_replace_pairs_only_count_listed_groups(self):
        campaign, _ads = self._drill_ten()
        self._close(campaign)
        view = coordinate_learning.prompt_view(self.conn, self.org_id, self.brand_id)
        students, commuters = self.groups[0]["id"], self.groups[1]["id"]

        keep, replace = coordinate_learning.gate_pairs(view, {students, commuters})
        self.assertEqual(keep, {(students, "box")})
        self.assertEqual(replace, {(commuters, "metro"), (commuters, "overtime")})

        keep, replace = coordinate_learning.gate_pairs(view, {commuters})
        self.assertEqual(keep, set())
        self.assertEqual(replace, {(commuters, "metro"), (commuters, "overtime")})


if __name__ == "__main__":
    unittest.main()
