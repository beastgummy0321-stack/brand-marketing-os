"""app/tests/test_ads_settle.py — F29-I03 Contract E falsifiers for the period settle
(`app/ads/settle.py`): one calendar month in the org timezone, graded by the one ruler against each
ad's own campaign cap, written to the brand notebook once, and raised as the brand queue's
`settle` row. F48-I02: each row's fate is its campaign's `learning_rank` verdict (留下 -> 有效,
換掉 -> 無效, unrankable -> skip), and the written scope names the ad's customer group.

Fixture: a real-shaped August 2026 -- an internal campaign (cap 450) and an imported one (cap 480),
eight ads covering 划算／偏貴／太貴／沒賣出／剛開始, one imported ad with no copy. "Today" is pinned
through `settle._today` (or, for the timezone edge, the clock `today_for_org` reads), so no test
depends on the day it runs.
"""

import unittest
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

from app.ads import (
    ads_learnings,
    angles,
    channels,
    learning_rank,
    period_grades,
    repository,
    settle,
    strategy,
    triage,
)
from app.ads import external_repository as external
from app.brand_intelligence import repository as brands
from app.core import db, interrupts
from app.core import settings as coresettings
from app.workbench import base_learning_scope

ACCOUNT_TZ = "Asia/Taipei"
MONTH = "2026-08"
START, END = date(2026, 8, 1), date(2026, 8, 31)
AFTER = date(2026, 9, 10)  # a day well after August ended
# F48-I02: every fixture ad the ranking places (留下 or 換掉) is written. F48-I13: p5 (a known
# zero under 3 x cap -- triage's 剛開始) is not ranked, so it is a skip.
LEARNABLE = ("p1", "p2", "p3", "p4", "i1", "i2", "i3")


class _Reader:
    def accounts(self, conn, org, brand):
        return [{"account_id": "act_1", "currency": "TWD", "name": "來源",
                  "timezone_name": ACCOUNT_TZ}]


def _creative(body, title="標題"):
    return {"kind": "image", "fields": {"title": title, "body": body, "image_hash": "h"}}


class SettleFixture(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="期結算測試", actor="test", client_name=None,
        )["id"]
        patch.object(channels, "external_reader", return_value=_Reader()).start()
        self.enqueue = patch.object(angles, "enqueue").start()
        self.today_patch = patch.object(settle, "_today", return_value=AFTER)
        self.today = self.today_patch.start()
        self.addCleanup(patch.stopall)
        self.daily = self.campaign("日常商品推廣・轉換", "c_daily", cap=450, internal=True)
        self.imp = self.campaign("夏季清倉・舊帳戶", "c_imp", cap=480)
        self.ads = {}
        # campaign daily (cap 450): 划算 353.8, 偏貴 508.3, 太貴 614.3, 沒賣出, 剛開始 (F48: a known
        # zero under 3 x cap -- a sold ad is always graded now, whatever its sample size)
        self.add("p1", self.daily, "晨光隨行杯・日常出發", days=20, spend=9200, results=26,
                 copy="早上七點半倒好咖啡出門，到公司還是熱的。")
        self.add("p2", self.daily, "辦公室一角・質感桌面", days=20, spend=6100, results=12,
                 copy="放在桌上也好看的杯子。")
        self.add("p3", self.daily, "健身情境・保冷 12 小時", days=10, spend=4300, results=7,
                 copy="練完喝一口，12 小時還是冰的。")
        self.add("p4", self.daily, "秋季新色預告", days=8, spend=1600, results=0,
                 copy="秋天的顏色，先讓你看。")
        self.add("p5", self.daily, "開箱 15 秒・單手開蓋", days=7, spend=700, results=0,
                 copy="單手就能開。")
        # imported campaign (cap 480): 划算 360, 太貴 780, 沒賣出 with no copy at all
        self.add("i1", self.imp, "夏日冰飲・保冷一整天", days=14, spend=5040, results=14,
                 copy="早上放的冰塊，下午還在。")
        self.add("i2", self.imp, "限時 79 折・最後三天", days=10, spend=3900, results=5,
                 copy="最後三天，全館 79 折。")
        self.add("i3", self.imp, "五種用法輪播", days=10, spend=1500, results=0, copy=None)
        self.conn.commit()

    # -- fixtures -------------------------------------------------------------------------------

    def campaign(self, name, native_id, *, cap, internal=False, coverage_start="2026-07-01"):
        campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name=name,
        )["id"]
        if internal:
            self.conn.execute(
                "UPDATE ads_campaign SET origin='internal', goal_text='賣杯子', objective='購買' "
                "WHERE id=%s", (campaign,),
            )
        external.upsert_entity(
            self.conn, self.org, self.brand, campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "campaign",
             "native_id": native_id},
        )
        external.upsert_entity(
            self.conn, self.org, self.brand, campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "adset",
             "native_id": f"{native_id}_set", "name": "廣泛受眾",
             "parent_native_kind": "campaign", "parent_native_id": native_id},
        )
        external.record_sync(
            self.conn, self.org, self.brand, campaign, section="observations",
            state={"last_success_at": db.now_utc().isoformat(),
                   "coverage": {"start": coverage_start, "end": "2026-09-20"}},
        )
        if cap is not None:
            repository.save_campaign_target(
                self.conn, self.org, self.brand, campaign, result_kind="purchase", basis="own",
                value=cap, expected_revision=0, actor="測試員",
            )
        self.conn.commit()
        return campaign

    def add(self, key, campaign, name, *, days, spend, results, copy, first=START):
        native = self.conn.execute(
            "SELECT native_id FROM ads_external_entity WHERE campaign_id=%s "
            "AND native_kind='adset'", (campaign,),
        ).fetchone()["native_id"]
        entity = external.upsert_entity(
            self.conn, self.org, self.brand, campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "ad",
             "native_id": f"n_{key}_{campaign}", "name": name, "native_status": "ACTIVE",
             "parent_native_kind": "adset", "parent_native_id": native,
             **({"creative": _creative(copy)} if copy else {})},
        )["id"]
        self.ads[key] = entity
        per_day, extra = divmod(results, days)
        for offset in range(days):
            external.upsert_observation(
                self.conn, self.org, self.brand, campaign,
                {"entity_id": entity, "day": first + timedelta(days=offset), "metric_scope": "ad",
                 "attribution_key": f"{key}{offset}", "currency": "TWD", "source": "meta",
                 "spend": spend / days, "impressions": 1000, "purchases": None},
                result_kind="purchase",
                result_count=per_day + (1 if offset < extra else 0),
                result_action="omni_purchase", result_attribution="7d_click+1d_view",
            )
        return entity

    def view(self, month=MONTH):
        return settle.view(self.conn, self.org, self.brand, month)

    def rows(self, result=None):
        result = result or self.view()
        return {row["entity_id"]: row for row in result["rows"]}

    def picks(self, *keys, angle="保溫到公司"):
        return [{"entity_id": self.ads[key], "angle": angle} for key in keys]

    def learnings(self):
        return [
            row for row in brands.list_learnings(self.conn, self.brand, limit=500)
            if (row["source_cycle_id"] or "").startswith("settle:")
        ]


class SettleViewTest(SettleFixture):
    def test_every_ad_is_graded_against_its_own_campaign_cap_with_fates(self):
        result = self.view()
        self.assertEqual(
            {k: result[k] for k in ("month", "start", "end", "days", "status", "written")},
            {"month": MONTH, "start": "2026-08-01", "end": "2026-08-31", "days": 31,
             "status": "open", "written": None},
        )
        rows = self.rows(result)
        # F48-I02: the fate is the campaign's learning_rank verdict (留下 -> effective, 換掉 ->
        # ineffective), the grade stays the month review's.
        expected = {
            "p1": ("on_target", "effective"), "p2": ("watch", "ineffective"),
            "p3": ("over", "ineffective"), "p4": ("wasted", "ineffective"),
            "p5": ("insufficient", "skip"), "i1": ("on_target", "effective"),
            "i2": ("over", "ineffective"), "i3": ("wasted", "ineffective"),
        }
        self.assertEqual(
            {key: (rows[eid]["grade"], rows[eid]["fate"]) for key, eid in self.ads.items()},
            expected,
        )
        # Ranked per campaign: sold by cost per sale, 沒賣出 after (cheapest spend first);
        # F48-I13: p5 (0 sales, 700 < 3 x 450) is not ranked.
        self.assertEqual(
            {key: (rows[eid]["rank"], rows[eid]["of"], rows[eid]["sales"], rows[eid]["few"])
             for key, eid in self.ads.items()},
            {"p1": (1, 4, 26, False), "p2": (2, 4, 12, False), "p3": (3, 4, 7, False),
             "p4": (4, 4, 0, False), "p5": (None, None, None, False),
             "i1": (1, 3, 14, False), "i2": (2, 3, 5, False), "i3": (3, 3, 0, False)},
        )
        self.assertEqual(rows[self.ads["p5"]]["skip_reason"], "還沒賣出，花費也還沒到門檻")
        self.assertIsNone(rows[self.ads["p5"]]["verdict"])
        self.assertEqual(rows[self.ads["p1"]]["verdict_label"], "留下")
        self.assertEqual(rows[self.ads["p2"]]["verdict_label"], "換掉")
        self.assertEqual(rows[self.ads["p5"]]["grade_label"], "剛開始、數字還不夠")
        self.assertEqual(rows[self.ads["p5"]]["reason_code"], "too_new")
        self.assertEqual(rows[self.ads["p1"]]["cap"], 450.0)
        self.assertEqual(rows[self.ads["i1"]]["cap"], 480.0)
        self.assertEqual(rows[self.ads["p1"]]["copy_text"],
                         "早上七點半倒好咖啡出門，到公司還是熱的。")
        self.assertIsNone(rows[self.ads["i3"]]["copy_text"])
        self.assertEqual(rows[self.ads["i1"]]["origin"], "imported")
        self.assertEqual(rows[self.ads["p1"]]["origin"], "internal")
        campaigns = {c["campaign_id"]: c for c in result["campaigns"]}
        self.assertEqual(campaigns[self.daily]["cap"], {"value": 450.0, "basis": "own"})
        self.assertEqual(campaigns[self.imp]["cap"], {"value": 480.0, "basis": "own"})
        self.assertEqual(campaigns[self.imp]["origin"], "imported")
        self.assertEqual(campaigns[self.daily]["data_status"]["state"], "ready")

    def test_fates_equal_the_rankings_keep_verdict_and_an_unrankable_row_is_skipped(self):
        # An ad whose result count is unknown cannot be placed: skipped with a named reason.
        unknown = external.upsert_entity(
            self.conn, self.org, self.brand, self.imp,
            {"platform": "meta", "source_account": "act_1", "native_kind": "ad",
             "native_id": "n_unknown", "name": "結果未知", "native_status": "ACTIVE",
             "parent_native_kind": "adset", "parent_native_id": "c_imp_set"},
        )["id"]
        for offset in range(3):
            external.upsert_observation(
                self.conn, self.org, self.brand, self.imp,
                {"entity_id": unknown, "day": START + timedelta(days=offset),
                 "metric_scope": "ad", "attribution_key": f"u{offset}", "currency": "TWD",
                 "source": "meta", "spend": 100, "impressions": 1000, "purchases": None},
                result_kind="purchase", result_count=None, result_action="omni_purchase",
                result_attribution="7d_click+1d_view",
            )
        self.conn.commit()
        rows = self.rows()
        row = rows[unknown]
        self.assertEqual((row["fate"], row["skip_reason"], row["rank"]),
                         ("skip", "沒有可排名的數字", None))
        month = period_grades.grade_period(self.conn, self.org, self.brand, START, END)
        for campaign in (self.daily, self.imp):
            for ranked in learning_rank.rank([r for r in month if r["campaign_id"] == campaign]):
                fate = rows[ranked["entity_id"]]["fate"]
                self.assertEqual(fate == "effective", learning_rank.is_keep(ranked["verdict"]))

    def test_a_zero_under_the_unsold_line_is_skipped_and_at_the_line_is_replaced(self):
        # F48-I13: one answer to "is this ad judged yet?" -- 0 sales at 0.5 x cap (225 of 450)
        # is not ranked (triage's 剛開始), 0 sales at 3 x cap (1,350) is 沒賣出／換掉.
        half = self.add("h", self.daily, "半倍上限沒賣", days=5, spend=225, results=0,
                        copy="還在跑。")
        line = self.add("l", self.daily, "三倍上限沒賣", days=5, spend=1350, results=0,
                        copy="花到門檻。")
        self.conn.commit()
        rows = self.rows()
        self.assertEqual(
            (rows[half]["grade"], rows[half]["rank"], rows[half]["fate"],
             rows[half]["skip_reason"]),
            ("insufficient", None, "skip", "還沒賣出，花費也還沒到門檻"),
        )
        self.assertEqual(
            (rows[line]["grade"], rows[line]["verdict"], rows[line]["fate"],
             rows[line]["skip_reason"]),
            ("wasted", "replace", "ineffective", None),
        )

    def test_rows_are_served_in_each_campaigns_rank_order_unranked_last(self):
        # F48-I13: the page prints served order -- rank asc, unranked after by name.
        served = [row["entity_id"] for row in self.view()["rows"]]
        by_campaign = {
            self.daily: [self.ads[k] for k in ("p1", "p2", "p3", "p4", "p5")],
            self.imp: [self.ads[k] for k in ("i1", "i2", "i3")],
        }
        for expected in by_campaign.values():
            self.assertEqual([eid for eid in served if eid in expected], expected)
        # each campaign's rows are contiguous
        first = served[0] in by_campaign[self.daily]
        split = len(by_campaign[self.daily if first else self.imp])
        self.assertTrue(all((eid in by_campaign[self.daily]) == first for eid in served[:split]))

    def test_totals_are_program_sums_and_unknown_never_zero(self):
        self.conn.execute(
            "INSERT INTO ads_month_budget (id,org_id,brand_id,month,currency,amount,confirmed_by) "
            "VALUES (%s,%s,%s,%s,'TWD',33000,'測試員')",
            (db.new_id("amb"), self.org, self.brand, START),
        )
        self.conn.commit()
        result = self.view()
        spent = 9200 + 6100 + 4300 + 1600 + 700 + 5040 + 3900 + 1500
        self.assertEqual(result["currency"], "TWD")
        self.assertAlmostEqual(result["spent"], spent)
        self.assertEqual(result["budget"], 33000.0)
        self.assertEqual(result["results"], 64.0)
        self.assertAlmostEqual(result["cost_per_result"], spent / 64)
        self.assertEqual(result["on_target_results"], 40.0)
        self.assertAlmostEqual(result["on_target_spend_share"], (9200 + 5040) / spent)
        buckets = {b["grade"]: b for b in result["buckets"]}
        self.assertEqual((buckets["on_target"]["count"], buckets["wasted"]["count"]), (2, 2))
        self.assertEqual(result["notebook"], {"count": 0})

    def test_angles_enqueue_once_per_learnable_ad_with_copy_only(self):
        rows = self.rows()
        queued = {call.args[3] for call in self.enqueue.call_args_list}
        self.assertEqual(queued,
                         {self.ads[k] for k in ("p1", "p2", "p3", "p4", "i1", "i2")})
        self.assertEqual(self.enqueue.call_count, 6)
        self.assertEqual(rows[self.ads["p1"]]["angles"], {"status": "pending", "candidates": []})
        # the imported ad with no copy, and the unranked p5, never ask the model
        for key in ("i3", "p5"):
            self.assertEqual(rows[self.ads[key]]["angles"],
                             {"status": "not_needed", "candidates": []})

    def test_failed_angle_read_is_reported_and_the_row_still_needs_a_pick(self):
        def fake_get(conn, org, brand, campaign, entity_id):
            if entity_id == self.ads["p1"]:
                return {"status": "failed", "candidates": [], "error": "逾時"}
            return {"status": "ready", "candidates": ["通勤帶著走", "保溫到公司", "早晨的小儀式"],
                    "error": None}

        with patch.object(angles, "get", side_effect=fake_get):
            rows = self.rows()
        self.assertEqual(rows[self.ads["p1"]]["angles"], {"status": "failed", "candidates": []})
        self.assertEqual(rows[self.ads["p3"]]["angles"]["status"], "ready")
        self.assertEqual(len(rows[self.ads["p3"]]["angles"]["candidates"]), 3)
        with self.assertRaises(settle.SettleError) as caught:
            settle.write(self.conn, self.org, self.brand, MONTH,
                         self.picks("p3", "p4", "i1", "i2", "i3"), "user_1")
        self.assertEqual((caught.exception.status, caught.exception.code),
                         (400, "settle_angle_missing"))
        self.assertEqual(self.learnings(), [])

    def test_campaign_with_missing_days_keeps_its_grade_and_is_skipped_with_a_reason(self):
        # rows 08-01..08-10, synced coverage only from 08-15: 08-11..08-14 were never read
        gap = self.campaign("缺天活動", "c_gap", cap=100, coverage_start="2026-08-15")
        self.add("g1", gap, "缺天廣告", days=10, spend=500, results=10, copy="有文案。")
        self.conn.commit()
        result = self.view()
        row = self.rows(result)[self.ads["g1"]]
        # the grade is the month review's own (no second grading rule); only the fate changes
        self.assertEqual((row["grade"], row["grade_label"], row["fate"], row["skip_reason"]),
                         ("on_target", "划算", "skip", "資料缺天，這期不記"))
        review = {r["entity_id"]: r for r in period_grades.grade_period(
            self.conn, self.org, self.brand, START, END)}
        self.assertEqual(
            {eid: (r["grade"], r["grade_label"]) for eid, r in self.rows(result).items()},
            {eid: (r["grade"], r["grade_label"]) for eid, r in review.items()},
        )
        self.assertEqual(row["angles"]["status"], "not_needed")
        self.assertIsNone(self.rows(result)[self.ads["p1"]]["skip_reason"])
        with self.assertRaises(settle.SettleError):  # still no pick needed for it
            settle.write(self.conn, self.org, self.brand, MONTH, self.picks("g1"), "user_1")
        settle.write(self.conn, self.org, self.brand, MONTH,
                     self.picks(*LEARNABLE), "user_1")
        self.assertNotIn(f"settle:{MONTH}:{self.ads['g1']}",
                         {r["source_cycle_id"] for r in self.learnings()})
        status = {c["campaign_id"]: c for c in result["campaigns"]}[gap]["data_status"]
        self.assertEqual(status["state"], "partial")
        self.assertEqual(status["missing_days"],
                         ["2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14"])
        # the other campaigns are untouched by this one's gap
        self.assertEqual(self.rows(result)[self.ads["p1"]]["fate"], "effective")

    def test_month_not_ended_reads_not_ended_and_refuses_a_write(self):
        self.today.return_value = END
        result = self.view()
        self.assertEqual(result["status"], "not_ended")
        self.enqueue.assert_not_called()
        with self.assertRaises(settle.SettleError) as caught:
            settle.write(self.conn, self.org, self.brand, MONTH,
                         self.picks(*LEARNABLE), "user_1")
        self.assertEqual((caught.exception.status, caught.exception.code),
                         (409, "settle_not_ended"))


class SettleWriteTest(SettleFixture):
    def write(self, picks):
        return settle.write(self.conn, self.org, self.brand, MONTH, picks, "user_1")

    def bind_customer_group(self, key, group_id):
        """The platform ad `key` has a local `ads_ad` (same campaign, `external_id = native_id`)
        planned for customer group `group_id`."""
        campaign = self.daily
        delivery_group = db.new_id("adg")
        self.conn.execute(
            "INSERT INTO ads_delivery_group(id,org_id,brand_id,campaign_id,channel_key,name,role,"
            "daily_budget) VALUES(%s,%s,%s,%s,'meta','投放組','new',100)",
            (delivery_group, self.org, self.brand, campaign),
        )
        self.conn.execute(
            "INSERT INTO ads_ad(id,org_id,brand_id,campaign_id,group_id,name,external_id,"
            "local_state,customer_group_id) VALUES(%s,%s,%s,%s,%s,%s,%s,'bound',%s)",
            (db.new_id("ada"), self.org, self.brand, campaign, delivery_group, "本地廣告",
             f"n_{key}_{campaign}", group_id),
        )
        self.conn.commit()

    def test_one_learning_per_non_skip_row_idempotent_and_skip_picks_ignored(self):
        gap = self.campaign("缺天活動", "c_gap", cap=100, coverage_start="2026-08-15")
        self.add("g1", gap, "缺天廣告", days=10, spend=500, results=10, copy="有文案。")
        self.bind_customer_group("p1", "pcg_morning")
        self.conn.commit()
        picks = [
            *self.picks("p1", angle="保溫到公司"), *self.picks("p2", angle="桌面質感"),
            *self.picks("p3", angle="運動後保冷"), *self.picks("p4", angle="新色搶先看"),
            *self.picks("p5", angle="單手開蓋"),  # not ranked (F48-I13): a skip, ignored
            *self.picks("i1", angle="保冷一整天"),
            *self.picks("i2", angle="限時折扣"), *self.picks("i3", angle="  多種用法 "),
            *self.picks("g1", angle="缺天"),  # a skip row (its campaign has gaps): ignored
        ]
        result = self.write(picks)
        rows = {row["source_cycle_id"]: row for row in self.learnings()}
        self.assertEqual(set(rows), {f"settle:{MONTH}:{self.ads[k]}" for k in LEARNABLE})
        p1 = rows[f"settle:{MONTH}:{self.ads['p1']}"]
        # F48-I02: the scope names the customer group the ad spoke to (none when unbound).
        self.assertEqual(
            {k: base_learning_scope(p1[k]) if k == "applicability_scope" else p1[k]
             for k in ("learning_text", "applicability_scope", "sample_size",
                                "confidence", "source_track", "created_by")},
            {"learning_text": "「保溫到公司」本期每筆成本未超過宣告上限；僅表示相關",
             "applicability_scope": f"ads;campaign={self.daily};group=pcg_morning"
                                    ";settle_fate=effective;settle_basis=absolute",
             "sample_size": "26", "confidence": "observed", "source_track": "ads",
             "created_by": "user_1"},
        )
        p2 = rows[f"settle:{MONTH}:{self.ads['p2']}"]
        self.assertEqual(p2["learning_text"], "「桌面質感」本期每筆成本超過宣告上限；僅表示相關")
        self.assertEqual(base_learning_scope(p2["applicability_scope"]),
                         f"ads;campaign={self.daily};group=none;settle_fate=ineffective;settle_basis=absolute")
        i3 = rows[f"settle:{MONTH}:{self.ads['i3']}"]
        source = ads_learnings.stored_evidence(i3)
        self.assertEqual(source["source_kind"], "settle")
        self.assertEqual(source["source_ref"]["entity_id"], self.ads["i3"])
        self.assertEqual(source["scope"]["claim_key"], "message_text:多種用法")
        self.assertEqual(source["direction"], "contrary")
        self.assertEqual(i3["learning_text"],
                         "「多種用法」本期無法計算每筆成本與上限的差距；成效原因未知")
        self.assertEqual(base_learning_scope(i3["applicability_scope"]),
                         f"ads;campaign={self.imp};group=none;settle_fate=ineffective;settle_basis=absolute")
        self.assertEqual(i3["sample_size"], "0")
        # no numbers in any text (identical conclusions promote confidence)
        self.assertFalse(any(ch.isdigit() for row in rows.values()
                             for ch in row["learning_text"]))
        self.assertEqual(result["status"], "written")
        self.assertEqual({k: result["written"][k] for k in ("count", "effective", "ineffective",
                                                            "by")},
                         {"count": 7, "effective": 2, "ineffective": 5, "by": "user_1"})
        self.assertEqual(result["notebook"], {"count": 7})
        view_rows = self.rows(result)
        self.assertEqual(view_rows[self.ads["i3"]]["written_angle"], "多種用法")
        self.assertIsNone(view_rows[self.ads["g1"]]["written_angle"])
        self.assertTrue(all(row["angles"]["status"] == "not_needed" for row in result["rows"]))

        again = self.write(picks)  # a repeated POST writes nothing twice
        self.assertEqual(len(self.learnings()), 7)
        self.assertEqual(again["written"]["count"], 7)

    def test_each_row_carries_its_campaigns_sell_way(self):
        """F48 Contract W: entity -> its campaign -> that campaign's sell-way; the imported
        campaign has none, so its rows are brand level."""
        product = brands.create_product(self.conn, self.brand, name="隨行杯單入", actor="test")
        self.conn.execute(
            "UPDATE ads_campaign SET context_json = context_json"
            " || jsonb_build_object('product_ids', jsonb_build_array(%s::text)) WHERE id = %s",
            (product["id"], self.daily),
        )
        self.conn.commit()
        self.write(self.picks(*LEARNABLE, angle="保溫到公司"))
        by_entity = {row["source_cycle_id"].rsplit(":", 1)[1]: row["product_id"]
                     for row in self.learnings()}
        self.assertEqual(
            by_entity,
            {self.ads[k]: (product["id"] if k.startswith("p") else None) for k in LEARNABLE},
        )

    def test_identical_text_and_overlapping_periods_do_not_promote_unknown_conditions(self):
        brands.record_learning(
            self.conn, self.brand, actor="system", learning_text="「保冷」對這群受眾無效",
            applicability_scope="ads;campaign=x", confidence="observed", sample_size="1",
            source_cycle_id="act_old", source_track="ads",
        )
        replaced = ("p2", "p3", "p4", "i2", "i3")
        picks = [*self.picks("p1", "i1", angle="保溫"), *self.picks(*replaced, angle="保冷")]
        self.write(picks)
        by_entity = {row["source_cycle_id"].rsplit(":", 1)[1]: row for row in self.learnings()}
        effective = sorted(by_entity[self.ads[k]]["confidence"] for k in ("p1", "i1"))
        self.assertEqual(effective, ["observed", "observed"])
        ineffective = sorted(by_entity[self.ads[k]]["confidence"] for k in replaced)
        self.assertEqual(ineffective, ["observed"] * 5)

    def test_missing_or_too_long_pick_writes_nothing(self):
        with self.assertRaises(settle.SettleError) as caught:
            self.write(self.picks(*LEARNABLE[:-1]))  # i3 has no pick
        self.assertEqual(caught.exception.code, "settle_angle_missing")
        with self.assertRaises(settle.SettleError) as caught:
            self.write([*self.picks(*LEARNABLE[:-1]),
                        *self.picks("i3", angle="十三個字的主打一定太長了啦")])
        self.assertEqual((caught.exception.status, caught.exception.code),
                         (400, "settle_angle_invalid"))
        self.assertEqual(self.learnings(), [])

    def test_strategy_reads_the_written_learnings(self):
        self.write(self.picks(*LEARNABLE, angle="保溫到公司"))
        text, basis = strategy._learnings_section(self.conn, self.brand)
        self.assertIn("「保溫到公司」本期每筆成本未超過宣告上限；僅表示相關", text)
        self.assertIn("「保溫到公司」本期每筆成本超過宣告上限；僅表示相關", text)
        self.assertEqual(len(basis), len(LEARNABLE))


class SettleTimezoneTest(SettleFixture):
    """The month ends at midnight in the ORG timezone, not the server's."""

    def at(self, local):
        zone = coresettings.org_timezone(self.conn, org_id=self.org)
        instant = local.replace(tzinfo=zone).astimezone(UTC)
        # F50 Contract K: `today_for_org` reads its instant from `db.now_utc()` (the drill
        # clock's seam too), so freezing that one function freezes the org's calendar.
        return patch.object(db, "now_utc", return_value=instant)

    def test_month_edge_follows_the_org_timezone(self):
        self.today_patch.stop()
        with self.at(datetime(2026, 8, 31, 23, 30)):
            self.assertEqual(settle.previous_month(self.conn, self.org), "2026-07")
            self.assertEqual(self.view()["status"], "not_ended")
            with self.assertRaises(settle.SettleError):
                settle.write(self.conn, self.org, self.brand, MONTH, [], "user_1")
        with self.at(datetime(2026, 9, 1, 0, 30)):
            self.assertEqual(settle.previous_month(self.conn, self.org), MONTH)
            self.assertEqual(self.view()["status"], "open")


class SettleQueueTest(SettleFixture):
    def setUp(self):
        super().setUp()
        # Only the settle row is under test: the per-ad kinds read today's real windows.
        patch.object(triage, "_classify_brand", return_value=[]).start()

    def settle_rows(self, queue):
        return [row for row in queue["items"] if row["kind_key"] == "settle"]

    def test_raised_from_the_second_day_after_the_month_with_its_payload(self):
        self.today.return_value = date(2026, 9, 1)
        self.assertEqual(self.settle_rows(triage.refresh_queue(self.conn, self.org, self.brand)),
                         [])
        self.today.return_value = date(2026, 9, 2)
        rows = self.settle_rows(triage.refresh_queue(self.conn, self.org, self.brand))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["category"], "ads_triage_settle")
        self.assertEqual(row["severity"], "informational")
        self.assertEqual(row["dedupe_key"], f"ads-triage:settle:{self.brand}:2026-08-31")
        self.assertEqual(row["action_url"], f"/brands/{self.brand}/ads/settle/{MONTH}/result")
        self.assertIsNone(row["triage"])
        self.assertIsNone(row["proposal"])
        payload = row["settle"]
        self.assertEqual(
            {k: payload[k] for k in ("month", "start", "end", "campaign_count", "imported_count",
                                     "learnable_count")},
            {"month": MONTH, "start": "2026-08-01", "end": "2026-08-31", "campaign_count": 2,
             "imported_count": 1, "learnable_count": len(LEARNABLE)},
        )
        self.assertEqual(len(payload["buckets"]), 6)
        self.enqueue.assert_not_called()  # the queue never asks the model

    def test_written_settle_resolves_the_row_and_is_not_raised_again(self):
        triage.refresh_queue(self.conn, self.org, self.brand)
        settle.write(self.conn, self.org, self.brand, MONTH,
                     self.picks(*LEARNABLE), "user_1")
        open_rows = interrupts.list_open(self.conn, org_id=self.org, brand_id=self.brand,
                                         category="ads_triage_settle", archive_stale=False)
        self.assertEqual(open_rows, [])
        queue = triage.refresh_queue(self.conn, self.org, self.brand)
        self.assertEqual(self.settle_rows(queue), [])

    def test_no_cap_anywhere_still_ranks_against_the_best(self):
        # F48-I02: the ranking needs no cap (learning_rank keeps the best and those within
        # NEAR_BEST of it, flagged 相對最好). Absolute success remains unknown without a cap.
        for campaign in (self.daily, self.imp):
            self.conn.execute(
                "UPDATE ads_campaign SET target_cost=NULL, target_basis=NULL WHERE id=%s",
                (campaign,),
            )
        self.conn.commit()
        rows = self.settle_rows(triage.refresh_queue(self.conn, self.org, self.brand))
        # F48-I13: with no cap a known zero is not judged -- only the five sold ads are ranked.
        self.assertEqual(rows, [])
        view_rows = self.rows()
        for key in ("p4", "p5", "i3"):
            self.assertEqual((view_rows[self.ads[key]]["fate"], view_rows[self.ads[key]]["rank"]),
                             ("skip", None))
        p1 = view_rows[self.ads["p1"]]
        self.assertEqual((p1["grade"], p1["verdict"], p1["flags"], p1["fate"]),
                         ("no_target", "keep_relative", ["相對最好"], "skip"))

    def test_only_the_latest_ended_month_is_raised(self):
        self.today.return_value = date(2026, 10, 5)  # September has no rows at all
        self.assertEqual(self.settle_rows(triage.refresh_queue(self.conn, self.org, self.brand)),
                         [])


class SettleRouteTest(SettleFixture):
    def test_get_defaults_to_the_previous_month_and_post_writes(self):
        from fastapi.testclient import TestClient

        from app import main

        client = TestClient(main.app)
        response = client.get(f"/api/ads/brands/{self.brand}/settle")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["month"], MONTH)

        missing = client.post(f"/api/ads/brands/{self.brand}/settle",
                              json={"month": MONTH, "picks": self.picks("p1")})
        self.assertEqual(missing.status_code, 400, missing.text)
        self.assertEqual(missing.json()["error"]["code"], "settle_angle_missing")

        body = {"month": MONTH, "picks": self.picks(*LEARNABLE)}
        written = client.post(f"/api/ads/brands/{self.brand}/settle", json=body)
        self.assertEqual(written.status_code, 200, written.text)
        self.assertEqual(written.json()["status"], "written")

        self.today.return_value = END
        early = client.post(f"/api/ads/brands/{self.brand}/settle", json=body)
        self.assertEqual(early.status_code, 409, early.text)
        self.assertEqual(early.json()["error"]["code"], "settle_not_ended")


if __name__ == "__main__":
    unittest.main()
