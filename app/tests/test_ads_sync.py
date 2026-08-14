# -*- coding: utf-8 -*-
"""app/tests/test_ads_sync.py — 廣告分支票 9：Meta 唯讀同步與品牌歸屬認領。

全程 FakeMetaClient，不發任何真實網路請求。
重點在「一個帳號多品牌」的隔離保證：沒認領歸屬的活動，成效一律不進任何品牌。
"""

import atexit
import calendar
import os
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_sync_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import meta_api  # noqa: E402
from app.ads import performance as ads_performance  # noqa: E402
from app.ads import reading  # noqa: E402
from app.ads import sync as ads_sync  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import settings as coresettings  # noqa: E402
from app.core.db import new_id, now_iso  # noqa: E402
from app.shared.web import OPERATOR  # noqa: E402



def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"
ACCOUNT = "act_1234567890"


def _campaign(cid, name, status="ACTIVE"):
    return meta_api.Campaign(campaign_id=cid, name=name, objective="OUTCOME_SALES",
                             effective_status=status)


def _insight(cid, **overrides):
    data = dict(campaign_id=cid, adset_id="adset1", ad_id="ad1",
                date_start="2026-07-01", date_stop="2026-07-14",
                impressions=10000, clicks=250, spend=5000.0, conversions=12.0,
                revenue=18000.0)
    data.update(overrides)
    return meta_api.Insight(**data)


class InsightParsingTest(unittest.TestCase):
    def test_only_purchase_actions_count_as_conversions(self):
        """Meta 的 actions 陣列什麼都有。認不得的類型不能算成成交。"""
        row = {
            "campaign_id": "1", "date_start": "2026-07-01", "date_stop": "2026-07-14",
            "impressions": "1000", "clicks": "40", "spend": "800.5",
            "actions": [{"action_type": "like", "value": "30"},
                        {"action_type": "purchase", "value": "3"}],
            "action_values": [{"action_type": "purchase", "value": "2400"}],
        }
        insight = meta_api.parse_insight_row(row)
        self.assertEqual(insight.conversions, 3.0)
        self.assertEqual(insight.revenue, 2400.0)
        self.assertEqual(insight.clicks, 40)
        self.assertEqual(insight.spend, 800.5)

    def test_missing_numbers_become_zero_not_none(self):
        insight = meta_api.parse_insight_row({"campaign_id": "1"})
        self.assertEqual((insight.impressions, insight.clicks, insight.spend), (0, 0, 0.0))

    def test_reach_and_frequency_are_parsed(self):
        row = {"campaign_id": "1", "date_start": "2026-07-01", "date_stop": "2026-07-14",
               "impressions": "1000", "reach": "800", "frequency": "1.25"}
        insight = meta_api.parse_insight_row(row)
        self.assertEqual(insight.reach, 800)
        self.assertEqual(insight.frequency, 1.25)

    def test_missing_reach_and_frequency_stay_none_not_zero(self):
        """跟 impressions/clicks 不同：Meta 沒回這兩個欄位時要誠實回 None，不能當 0
        （鐵則 16——「沒收到」跟「確實是 0」是兩件事，checkpoint 的疲勞判定靠這個分辨）。"""
        insight = meta_api.parse_insight_row({"campaign_id": "1"})
        self.assertIsNone(insight.reach)
        self.assertIsNone(insight.frequency)

    def test_list_insights_requests_reach_and_frequency_fields(self):
        """根因修正：原本的 fields 清單連 frequency 都沒拉，自動同步進來的資料永遠沒有
        素材疲勞判定的依據（票 03-add-reach-metric）。"""
        client = meta_api.MetaClient("fake-token")
        captured = {}

        def _fake_get(path, params):
            captured.update(params)
            return {"data": []}

        client._get = _fake_get
        client.list_insights("act_1", "2026-07-01", "2026-07-14")
        self.assertIn("reach", captured["fields"])
        self.assertIn("frequency", captured["fields"])

    def test_list_insights_requests_daily_rows_from_now_on(self):
        client = meta_api.MetaClient("fake-token")
        captured = {}

        def _fake_get(path, params):
            captured.update(params)
            return {"data": []}

        client._get = _fake_get
        client.list_insights("act_1", "2026-08-01", "2026-08-14")
        self.assertEqual(captured["time_increment"], 1)

    def test_list_insights_without_breakdowns_omits_the_param(self):
        """I2：純新增能力，沒指定 breakdowns 時參數維持原樣，不影響既有同步行為。"""
        client = meta_api.MetaClient("fake-token")
        captured = {}

        def _fake_get(path, params):
            captured.update(params)
            return {"data": []}

        client._get = _fake_get
        client.list_insights("act_1", "2026-07-01", "2026-07-14")
        self.assertNotIn("breakdowns", captured)

    def test_list_insights_passes_through_asset_breakdowns(self):
        """I2：D 段成效歸因要用的素材元件層 breakdowns，能原樣傳給 Meta。"""
        client = meta_api.MetaClient("fake-token")
        captured = {}

        def _fake_get(path, params):
            captured.update(params)
            return {"data": []}

        client._get = _fake_get
        client.list_insights("act_1", "2026-07-01", "2026-07-14",
                             breakdowns=("body_asset", "title_asset"))
        self.assertEqual(captured["breakdowns"], "body_asset,title_asset")

    def test_asset_breakdowns_constant_matches_meta_docs(self):
        """已查證：Meta Marketing API Insights breakdowns 官方文件，素材元件層只有這八種。"""
        self.assertEqual(set(meta_api.ASSET_BREAKDOWNS), {
            "ad_format_asset", "body_asset", "call_to_action_asset", "description_asset",
            "image_asset", "link_url_asset", "title_asset", "video_asset",
        })

    def test_account_id_prefix_is_normalised(self):
        self.assertEqual(meta_api._normalise_account_id("1234"), "act_1234")
        self.assertEqual(meta_api._normalise_account_id("act_1234"), "act_1234")

    def test_no_token_gives_a_plain_message(self):
        with self.assertRaises(meta_api.MetaApiError) as ctx:
            meta_api.MetaClient(None)._get("act_1/campaigns", {})
        self.assertIn("還沒有設定", str(ctx.exception))


class _BaseSyncTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        # 先子後父：derived_metric 有外鍵指向 performance_snapshot，順序倒過來會被外鍵擋下
        main.conn.execute("DELETE FROM discovered_campaign")
        main.conn.execute("DELETE FROM derived_metric")
        main.conn.execute("DELETE FROM performance_snapshot")
        main.conn.commit()
        # 每個測試用不同的品牌名：同名品牌會讓命名猜測猜到先建的那一個
        # （這正是「猜測只能是預選、必須人確認」的原因，見 test_suggested_is_still_not_enough）
        # 用 uuid4 不用 hash(self.id())：hash() 受 PYTHONHASHSEED 隨機化，跨進程／跟
        # test_ads_ga4.py 同前綴同 mod 可能撞名（B4R 收尾包踢出的 flaky 根因）。不用 new_id()：
        # 它回傳的字串含底線，會被 _guess_brand() 的 campaign_name.split("_")[0] 切壞。
        # 只取 8 碼十六進位（32 位元亂數，測試規模下撞名機率可忽略）：品牌名要留在
        # ads_handoff._slug() 的 20 字元截斷門檻內，這裡本來就靠猜品牌測試比對整段名稱。
        self.brand_name = f"虛構晨光咖啡{uuid.uuid4().hex[:8]}"
        self.brand = bi_repo.create_brand(main.conn, name=self.brand_name,
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]
        coresettings.set_setting(main.conn, ads_sync.ACCOUNT_SETTING, ACCOUNT)
        coresettings.set_setting(main.conn, ads_sync.TOKEN_SETTING, "fake-token")

    def _sync(self, campaigns=None, insights=None, error=None):
        client = meta_api.FakeMetaClient(campaigns=campaigns, insights=insights, error=error)
        return ads_sync.sync_account(main.conn, ACTOR, client=client, today="2026-07-31")


class DiscoveryTest(_BaseSyncTest):
    def test_campaigns_land_in_the_unclaimed_pile(self):
        result = self._sync(campaigns=[_campaign("111", "某人的活動")])
        self.assertEqual(result.discovered, 1)
        row = main.conn.execute("SELECT * FROM discovered_campaign").fetchone()
        self.assertEqual(row["claim_status"], "unclaimed")
        self.assertIsNone(row["claimed_brand_id"])

    def test_discovered_table_has_no_brand_column(self):
        """還沒認領的東西不屬於任何品牌——這是結構性保證，不是流程約定。"""
        self._sync(campaigns=[_campaign("111", "某人的活動")])
        row = main.conn.execute("SELECT * FROM discovered_campaign").fetchone()
        self.assertNotIn("brand_id", row.keys())

    def test_our_own_naming_is_recognised_as_a_suggestion_only(self):
        result = self._sync(campaigns=[_campaign("222", f"{self.brand_name}_20260801_sales")])
        self.assertEqual(result.discovered, 1)
        row = main.conn.execute("SELECT * FROM discovered_campaign").fetchone()
        self.assertEqual(row["suggested_brand_id"], self.bid)
        self.assertEqual(row["claim_status"], "suggested")   # 猜到了也還沒生效
        self.assertIsNone(row["claimed_brand_id"])
        self.assertIn("命名", row["suggested_reason"])

    def test_resync_does_not_duplicate(self):
        self._sync(campaigns=[_campaign("111", "某人的活動")])
        second = self._sync(campaigns=[_campaign("111", "改了名字的活動")])
        self.assertEqual(second.discovered, 0)
        rows = main.conn.execute("SELECT * FROM discovered_campaign").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["campaign_name"], "改了名字的活動")


class ClaimGateTest(_BaseSyncTest):
    def test_unclaimed_insights_are_not_collected(self):
        """最重要的一條：沒認領的活動，成效一筆都不進資料庫。"""
        result = self._sync(campaigns=[_campaign("111", "某人的活動")],
                            insights=[_insight("111")])
        self.assertEqual(result.snapshots, 0)
        self.assertEqual(result.skipped_unclaimed, 1)
        self.assertEqual(main.conn.execute(
            "SELECT COUNT(*) c FROM performance_snapshot").fetchone()["c"], 0)

    def test_suggested_is_still_not_enough(self):
        """系統猜到了也不算數——預選不是確認。"""
        result = self._sync(campaigns=[_campaign("222", f"{self.brand_name}_20260801_sales")],
                            insights=[_insight("222")])
        self.assertEqual(result.snapshots, 0)
        self.assertEqual(result.skipped_unclaimed, 1)

    def test_after_claiming_the_numbers_come_in(self):
        self._sync(campaigns=[_campaign("222", f"{self.brand_name}_20260801_sales")])
        discovered_id = main.conn.execute("SELECT id FROM discovered_campaign").fetchone()["id"]
        ads_sync.claim(main.conn, self.bid, discovered_id, ACTOR)

        result = self._sync(campaigns=[_campaign("222", f"{self.brand_name}_20260801_sales")],
                            insights=[_insight("222")])
        self.assertEqual(result.snapshots, 1)
        row = main.conn.execute("SELECT * FROM performance_snapshot").fetchone()
        self.assertEqual(row["brand_id"], self.bid)
        self.assertEqual(row["source"], "meta_api")
        self.assertEqual(row["clicks"], 250)
        self.assertEqual(row["spend"], 5000.0)

    def test_reach_and_frequency_land_in_the_normalised_columns(self):
        """自動同步會拉回觸及與頻率，不再只有手動匯 CSV 才有（票 03-add-reach-metric）。"""
        self._sync(campaigns=[_campaign("223", f"{self.brand_name}_20260801_sales")])
        discovered_id = main.conn.execute("SELECT id FROM discovered_campaign").fetchone()["id"]
        ads_sync.claim(main.conn, self.bid, discovered_id, ACTOR)

        result = self._sync(campaigns=[_campaign("223", f"{self.brand_name}_20260801_sales")],
                            insights=[_insight("223", reach=7200, frequency=1.4)])
        self.assertEqual(result.snapshots, 1)
        row = main.conn.execute("SELECT * FROM performance_snapshot").fetchone()
        self.assertEqual(row["reach"], 7200)
        self.assertEqual(row["frequency"], 1.4)

    def test_claim_list_never_shows_another_brands_campaign(self):
        """品牌隔離（鐵則 13）：A 品牌的頁面不得出現已認領給 B 的活動。"""
        other = bi_repo.create_brand(main.conn, name="虛構隔壁烘焙", client_name=None,
                                     actor=ACTOR)["id"]
        self._sync(campaigns=[_campaign("333", "隔壁的活動")])
        discovered_id = main.conn.execute("SELECT id FROM discovered_campaign").fetchone()["id"]
        ads_sync.claim(main.conn, other, discovered_id, ACTOR)

        self.assertEqual(ads_sync.list_pending_claims(main.conn, self.bid), [])
        page = self.client.get(f"/brands/{self.bid}/ads/claims")
        self.assertNotIn("隔壁的活動", page.text)

    def test_cannot_steal_another_brands_claim(self):
        other = bi_repo.create_brand(main.conn, name="虛構隔壁烘焙2", client_name=None,
                                     actor=ACTOR)["id"]
        self._sync(campaigns=[_campaign("444", "某活動")])
        discovered_id = main.conn.execute("SELECT id FROM discovered_campaign").fetchone()["id"]
        ads_sync.claim(main.conn, other, discovered_id, ACTOR)
        with self.assertRaises(ValueError):
            ads_sync.claim(main.conn, self.bid, discovered_id, ACTOR)

    def test_ignore_removes_it_from_the_list(self):
        self._sync(campaigns=[_campaign("555", f"{self.brand_name}_20260801_sales")])
        discovered_id = main.conn.execute("SELECT id FROM discovered_campaign").fetchone()["id"]
        resp = self.client.post(f"/brands/{self.bid}/ads/claims/{discovered_id}/ignore",
                                follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(ads_sync.list_pending_claims(main.conn, self.bid), [])

    def test_claim_works_without_operator_cookie(self):
        """ADR 0004：認領歸屬不再要求先設定操作人。"""
        self._sync(campaigns=[_campaign("666", "某活動")])
        discovered_id = main.conn.execute("SELECT id FROM discovered_campaign").fetchone()["id"]
        self.client.cookies.clear()
        resp = self.client.post(f"/brands/{self.bid}/ads/claims/{discovered_id}/claim",
                                follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertNotIn("/settings/operator", resp.headers["location"])
        row = main.conn.execute(
            "SELECT claimed_by FROM discovered_campaign WHERE id = ?", (discovered_id,)).fetchone()
        self.assertEqual(row["claimed_by"], OPERATOR)


class SanityAndErrorTest(_BaseSyncTest):
    def _claim_campaign(self, cid, name):
        self._sync(campaigns=[_campaign(cid, name)])
        discovered_id = main.conn.execute(
            "SELECT id FROM discovered_campaign WHERE meta_campaign_id = ?", (cid,)
        ).fetchone()["id"]
        ads_sync.claim(main.conn, self.bid, discovered_id, ACTOR)

    def test_impossible_numbers_are_quarantined_not_dropped(self):
        """壞資料要留下來看得到，但不能進判讀。"""
        self._claim_campaign("777", f"{self.brand_name}_20260801_sales")
        result = self._sync(campaigns=[_campaign("777", f"{self.brand_name}_20260801_sales")],
                            insights=[_insight("777", impressions=100, clicks=500)])
        self.assertEqual(result.quarantined, 1)
        row = main.conn.execute(
            "SELECT * FROM performance_snapshot WHERE meta_campaign_id = '777'").fetchone()
        self.assertEqual(row["quarantined"], 1)
        self.assertIn("不合理", row["quarantine_reason"])

    def test_api_error_returns_plain_message_and_writes_nothing(self):
        result = self._sync(error=meta_api.MetaApiError("Meta 拒絕了這次連線"))
        self.assertIn("Meta 拒絕", result.error)
        self.assertEqual(main.conn.execute(
            "SELECT COUNT(*) c FROM discovered_campaign").fetchone()["c"], 0)

    def test_sync_without_configuration_is_refused_politely(self):
        main.conn.execute("DELETE FROM app_setting WHERE key IN (?, ?)",
                          (ads_sync.TOKEN_SETTING, ads_sync.ACCOUNT_SETTING))
        main.conn.commit()
        resp = self.client.post(f"/brands/{self.bid}/ads/sync", follow_redirects=False)
        self.assertIn("kind=warn", resp.headers["location"])
        self.assertFalse(ads_sync.is_configured(main.conn))

    def test_settings_page_offers_readonly_meta_connection(self):
        page = self.client.get("/settings")
        self.assertIn("Meta 廣告帳號", page.text)
        self.assertIn("讀得到你的廣告數字，但改不了", page.text)


class BrandLevelBaselineTest(_BaseSyncTest):
    """票 F2（決策 0039 第 7 條）：認領觸發品牌層（無檔期）成效重算基準。"""

    def _insert_brand_level_snapshot(self, as_of_date, *, clicks, impressions, spend,
                                     conversions):
        sid = new_id("psn")
        ts = now_iso()
        main.conn.execute(
            "INSERT INTO performance_snapshot (id, brand_id, campaign_cycle_id, platform,"
            " date_range_start, date_range_end, as_of_date, snapshot_taken_at, currency,"
            " impressions, clicks, spend, conversions, reconciled, source, quarantined,"
            " created_at)"
            " VALUES (?, ?, NULL, 'meta', ?, ?, ?, ?, 'TWD', ?, ?, ?, ?, 1, 'meta_api', 0, ?)",
            (sid, self.bid, as_of_date, as_of_date, as_of_date, ts,
             impressions, clicks, spend, conversions, ts),
        )
        main.conn.commit()

    def test_claiming_recomputes_baseline_from_twelve_months_of_history(self):
        """①認領後 brand_baseline() 回傳含舊資料的 cpc/ctr/cvr 中位數（測試造 12 個月假資料）。"""
        for i in range(1, 13):
            self._insert_brand_level_snapshot(
                f"2025-{i:02d}-15", clicks=100 + i, impressions=10000,
                spend=1000 + i * 10, conversions=5 + (i % 3))
        self.assertEqual(reading.brand_baseline(main.conn, self.bid), {})  # 認領前還沒重算過

        self._sync(campaigns=[_campaign("900", "某個舊廣告")])
        discovered_id = main.conn.execute(
            "SELECT id FROM discovered_campaign WHERE meta_campaign_id = '900'"
        ).fetchone()["id"]
        ads_sync.claim(main.conn, self.bid, discovered_id, ACTOR)

        baseline = reading.brand_baseline(main.conn, self.bid)
        self.assertIn("cpc", baseline)
        self.assertIn("ctr", baseline)
        self.assertIn("cvr", baseline)

    def test_a_normal_sync_after_claiming_keeps_the_baseline_fresh(self):
        """認領後，後續一般同步若對不到檔期也自動併入品牌層基準，不必每次都重新認領。"""
        self._sync(campaigns=[_campaign("901", f"{self.brand_name}_20260801_sales")])
        discovered_id = main.conn.execute(
            "SELECT id FROM discovered_campaign WHERE meta_campaign_id = '901'"
        ).fetchone()["id"]
        ads_sync.claim(main.conn, self.bid, discovered_id, ACTOR)

        result = self._sync(campaigns=[_campaign("901", f"{self.brand_name}_20260801_sales")],
                            insights=[_insight("901", clicks=300, impressions=20000,
                                               spend=6000.0, conversions=15.0)])
        self.assertEqual(result.snapshots, 1)
        baseline = reading.brand_baseline(main.conn, self.bid)
        self.assertIn("cpc", baseline)


class BrandLevelDuplicateBackfillTest(_BaseSyncTest):
    """票 F10（GitHub #69，父票 #59）：認領過但沒有檔期對應的舊廣告落在品牌層
    （campaign_cycle_id NULL），一鍵回填重跑兩次不該把同一批成效算兩遍——比照
    F9（#68）CSV 匯入的內容簽章去重思路，這裡換成 API 同步路徑。"""

    def _claim(self, cid, name):
        self._sync(campaigns=[_campaign(cid, name)])
        discovered_id = main.conn.execute(
            "SELECT id FROM discovered_campaign WHERE meta_campaign_id = ?", (cid,)
        ).fetchone()["id"]
        ads_sync.claim(main.conn, self.bid, discovered_id, ACTOR)

    def test_rerunning_the_same_backfill_adds_nothing_the_second_time(self):
        """①同一回填連跑兩次→第二次 0 新增＋訊息含略過數。"""
        self._claim("950", f"{self.brand_name}_20260801_sales")
        insights = [_insight("950")]

        first = self._sync(campaigns=[_campaign("950", f"{self.brand_name}_20260801_sales")],
                           insights=insights)
        self.assertEqual(first.snapshots, 1)
        self.assertEqual(first.skipped_duplicate, 0)

        second = self._sync(campaigns=[_campaign("950", f"{self.brand_name}_20260801_sales")],
                            insights=insights)
        self.assertEqual(second.snapshots, 0)
        self.assertEqual(second.skipped_duplicate, 1)  # 誠實列出略過幾列，不是靜默吞掉
        rows = main.conn.execute(
            "SELECT COUNT(*) c FROM performance_snapshot WHERE brand_id = ?"
            " AND campaign_cycle_id IS NULL", (self.bid,)).fetchone()
        self.assertEqual(rows["c"], 1)  # 資料庫裡只有一筆，不是兩筆

    def test_different_ads_with_identical_numbers_are_not_mistaken_for_duplicates(self):
        """②內容不同的列不誤擋——這裡故意讓兩個不同廣告的量測數字長得一模一樣，
        真正的區別在 meta_ad_id，不能被誤判成重複。"""
        self._claim("951", f"{self.brand_name}_20260802_sales")
        result = self._sync(
            campaigns=[_campaign("951", f"{self.brand_name}_20260802_sales")],
            insights=[_insight("951", ad_id="adA"), _insight("951", ad_id="adB")])
        self.assertEqual(result.snapshots, 2)
        self.assertEqual(result.skipped_duplicate, 0)

    def test_cycle_scoped_snapshots_still_accumulate_every_sync(self):
        """③檔期層 snapshot 照舊累加行為不變（test_snapshots_accumulate_never_overwrite
        既有行為不動）——認領到有檔期對應的活動，去重不介入。"""
        self._sync(campaigns=[_campaign("952", f"{self.brand_name}_20260803_sales")])
        discovered_id = main.conn.execute(
            "SELECT id FROM discovered_campaign WHERE meta_campaign_id = '952'"
        ).fetchone()["id"]
        ads_sync.claim(main.conn, self.bid, discovered_id, ACTOR)

        resp = self.client.post(f"/brands/{self.bid}/ads/new",
                                data={"slider_index": "5", "objective": "sales"},
                                follow_redirects=False)
        cycle_id = resp.headers["location"].split("/ads/")[1].split("?")[0]
        main.conn.execute(
            "INSERT INTO external_ad_mapping (id, brand_id, campaign_cycle_id,"
            " platform, meta_campaign_id, claim_status, confirmed_by, confirmed_at,"
            " created_at) VALUES (?, ?, ?, 'meta', '952', 'confirmed', ?, ?, ?)",
            (new_id("eam"), self.bid, cycle_id, ACTOR, now_iso(), now_iso()),
        )
        main.conn.commit()

        insights = [_insight("952")]
        first = self._sync(campaigns=[_campaign("952", f"{self.brand_name}_20260803_sales")],
                           insights=insights)
        second = self._sync(campaigns=[_campaign("952", f"{self.brand_name}_20260803_sales")],
                            insights=insights)
        self.assertEqual(first.snapshots, 1)
        self.assertEqual(second.snapshots, 1)  # 檔期層每次同步都照樣累加，不受品牌層去重影響
        self.assertEqual(second.skipped_duplicate, 0)
        rows = main.conn.execute(
            "SELECT COUNT(*) c FROM performance_snapshot WHERE brand_id = ?"
            " AND campaign_cycle_id = ?", (self.bid, cycle_id)).fetchone()
        self.assertEqual(rows["c"], 2)

    def test_two_ads_under_one_campaign_map_to_their_own_cycle(self):
        """I1（GRILL 第三部分）：同一活動底下兩支廣告分屬不同檔期，各自的成效要對到
        各自的 external_ad_mapping，不能因為查詢只認 meta_campaign_id 而全部黏到
        最後建立的那一筆（程式碼自己標的既有缺口，見 sync.py `_cycle_for`）。"""
        self._sync(campaigns=[_campaign("960", f"{self.brand_name}_20260804_sales")])
        discovered_id = main.conn.execute(
            "SELECT id FROM discovered_campaign WHERE meta_campaign_id = '960'"
        ).fetchone()["id"]
        ads_sync.claim(main.conn, self.bid, discovered_id, ACTOR)

        def _new_cycle():
            resp = self.client.post(f"/brands/{self.bid}/ads/new",
                                    data={"slider_index": "5", "objective": "sales"},
                                    follow_redirects=False)
            return resp.headers["location"].split("/ads/")[1].split("?")[0]

        cycle_a, cycle_b = _new_cycle(), _new_cycle()
        ts = now_iso()
        for cycle_id, ad_id in ((cycle_a, "adA"), (cycle_b, "adB")):
            main.conn.execute(
                "INSERT INTO external_ad_mapping (id, brand_id, campaign_cycle_id, platform,"
                " meta_campaign_id, meta_ad_id, claim_status, confirmed_by, confirmed_at,"
                " created_at) VALUES (?, ?, ?, 'meta', '960', ?, 'confirmed', ?, ?, ?)",
                (new_id("eam"), self.bid, cycle_id, ad_id, ACTOR, ts, ts),
            )
        main.conn.commit()

        self._sync(campaigns=[_campaign("960", f"{self.brand_name}_20260804_sales")],
                   insights=[_insight("960", ad_id="adA"), _insight("960", ad_id="adB")])

        row_a = main.conn.execute(
            "SELECT campaign_cycle_id FROM performance_snapshot WHERE meta_ad_id = 'adA'"
        ).fetchone()
        row_b = main.conn.execute(
            "SELECT campaign_cycle_id FROM performance_snapshot WHERE meta_ad_id = 'adB'"
        ).fetchone()
        self.assertEqual(row_a["campaign_cycle_id"], cycle_a)
        self.assertEqual(row_b["campaign_cycle_id"], cycle_b)


class BrandLevelMultiMonthBackfillTest(_BaseSyncTest):
    """票 F11（GitHub #70）：一次回填橫跨多個月，品牌層月度分組要逐月拆開，不能全部倒進
    資料期間最後一天所在的那個月——根因是 Meta `/insights` 沒指定 time_increment 時，
    整段時間範圍一次問完只回一列聚合資料，改成逐月分開打 API（`ads_sync._month_windows()`）。"""

    class _MonthlyFakeClient:
        """本地測試替身：依呼叫的 since 回傳對應月份的洞察，用來驗證 sync_account 真的
        逐月分開打 API，不是把整段時間範圍一次丟給 Meta。不動 `meta_api.FakeMetaClient`——
        那個是共用替身，回放固定清單，不支援按月給不同資料。"""

        def __init__(self, campaigns, insights_by_month):
            self._campaigns = campaigns
            self._insights_by_month = insights_by_month
            self.calls = []

        def list_campaigns(self, account_id):
            return list(self._campaigns)

        def list_insights(self, account_id, since, until):
            self.calls.append((since, until))
            return list(self._insights_by_month.get(since[:7], []))

        def list_component_breakdowns(self, account_id, since, until):
            """票 12：sync_account 每次同步都會呼叫這支，本測試不驗元件層歸因，回空即可。"""
            return []

    def test_multi_month_backfill_produces_one_group_per_data_month(self):
        cid, name = "970", f"{self.brand_name}_20250801_sales"
        self._sync(campaigns=[_campaign(cid, name)])
        discovered_id = main.conn.execute(
            "SELECT id FROM discovered_campaign WHERE meta_campaign_id = ?", (cid,)
        ).fetchone()["id"]
        ads_sync.claim(main.conn, self.bid, discovered_id, ACTOR)

        months = []
        y, m = 2025, 8
        for _ in range(12):
            months.append((y, m))
            m += 1
            if m == 13:
                y, m = y + 1, 1

        insights_by_month = {}
        for y, m in months:
            last_day = calendar.monthrange(y, m)[1]
            key = f"{y:04d}-{m:02d}"
            insights_by_month[key] = [_insight(
                cid, date_start=f"{key}-01", date_stop=f"{key}-{last_day:02d}",
                clicks=50, impressions=5000, spend=500.0, conversions=2.0, revenue=1000.0)]

        client = self._MonthlyFakeClient([_campaign(cid, name)], insights_by_month)
        result = ads_sync.sync_account(main.conn, ACTOR, client=client,
                                       since="2025-08-01", until="2026-07-31",
                                       today="2026-07-31")

        self.assertEqual(result.snapshots, 12)
        self.assertEqual(len(client.calls), 12)  # 逐月各打一次，不是整段一次問完

        rows = main.conn.execute(
            "SELECT calc_basis FROM derived_metric WHERE brand_id = ?"
            " AND campaign_cycle_id IS NULL", (self.bid,)).fetchall()
        months_seen = {r["calc_basis"][6:13] for r in rows}
        expected = {f"{y:04d}-{m:02d}" for y, m in months}
        self.assertEqual(months_seen, expected)  # 12 個資料月各自成組
        self.assertNotIn("2026-08", months_seen)  # 不再全部倒進「匯入當下」那個月

    def test_pre_existing_full_year_mixed_row_is_superseded_by_monthly_backfill(self):
        """票 F13（GitHub #72）：#70 之前整段一次回填留下的跨全年混合列還在資料庫裡
        （append-only 不刪舊資料），使用者用 #70 修好的逐月回填重跑同一支廣告——新月列
        與舊混合列並存不能重複計算，也不能讓 F10（issue #69）的回填冪等退化。"""
        cid, name = "971", f"{self.brand_name}_20250801_sales"
        self._sync(campaigns=[_campaign(cid, name)])
        discovered_id = main.conn.execute(
            "SELECT id FROM discovered_campaign WHERE meta_campaign_id = ?", (cid,)
        ).fetchone()["id"]
        ads_sync.claim(main.conn, self.bid, discovered_id, ACTOR)

        # 模擬 #70 之前的舊回填：整段 12 個月只回一列聚合資料
        sid = new_id("psn")
        ts = now_iso()
        main.conn.execute(
            "INSERT INTO performance_snapshot (id, brand_id, campaign_cycle_id, platform,"
            " account_id, meta_campaign_id, meta_adset_id, meta_ad_id, date_range_start,"
            " date_range_end, as_of_date, snapshot_taken_at, currency, impressions, clicks,"
            " spend, conversions, revenue, reconciled, source, quarantined, created_at)"
            " VALUES (?, ?, NULL, 'meta', ?, ?, 'adset1', 'ad1', ?, ?, ?, ?, 'TWD', ?, ?, ?, ?,"
            " ?, 1, 'meta_api', 0, ?)",
            (sid, self.bid, ACCOUNT, cid, "2025-08-01", "2026-07-31", "2026-07-31", ts,
             60000, 600, 6000.0, 24.0, 12000.0, ts),
        )
        main.conn.commit()
        ads_performance.save_brand_level_derived_metrics(main.conn, self.bid)  # 舊資料先重算過一次

        months = []
        y, m = 2025, 8
        for _ in range(12):
            months.append((y, m))
            m += 1
            if m == 13:
                y, m = y + 1, 1
        insights_by_month = {}
        for y, m in months:
            last_day = calendar.monthrange(y, m)[1]
            key = f"{y:04d}-{m:02d}"
            insights_by_month[key] = [_insight(
                cid, date_start=f"{key}-01", date_stop=f"{key}-{last_day:02d}",
                clicks=50, impressions=5000, spend=500.0, conversions=2.0, revenue=1000.0)]

        client = self._MonthlyFakeClient([_campaign(cid, name)], insights_by_month)
        result = ads_sync.sync_account(main.conn, ACTOR, client=client,
                                       since="2025-08-01", until="2026-07-31",
                                       today="2026-07-31")
        self.assertEqual(result.snapshots, 12)  # 新月列跟舊混合列日期範圍不同，簽章不會擋

        rows = main.conn.execute(
            "SELECT calc_basis, metric, value FROM derived_metric WHERE brand_id = ?"
            " AND campaign_cycle_id IS NULL", (self.bid,)).fetchall()
        months_seen = {r["calc_basis"][6:13] for r in rows}
        expected = {f"{y:04d}-{m:02d}" for y, m in months}
        self.assertEqual(months_seen, expected)  # 剛好 12 組，舊混合列沒有另外多出一組
        self.assertFalse(any("跨月" in r["calc_basis"] for r in rows))  # 已被逐月資料覆蓋、整列排除
        cpcs = {r["value"] for r in rows if r["metric"] == "cpc"}
        self.assertEqual(cpcs, {10.0})  # 500/50，不是混進舊列後的另一個數字

        totals = ads_performance.brand_level_totals(main.conn, self.bid)
        self.assertEqual(totals["spend"], 6000.0)  # 12 個月各 500，不是舊列 6000＋新列 6000

        # F10 冪等：同一批回填再跑一次，不再新增，先前算出的數字也不會被再放大
        second = ads_sync.sync_account(main.conn, ACTOR, client=client,
                                       since="2025-08-01", until="2026-07-31",
                                       today="2026-07-31")
        self.assertEqual(second.snapshots, 0)
        self.assertEqual(second.skipped_duplicate, 12)
        totals_after_resync = ads_performance.brand_level_totals(main.conn, self.bid)
        self.assertEqual(totals_after_resync["spend"], 6000.0)


class HistoricalCampaignFromInsightsTest(_BaseSyncTest):
    """票 F14（GitHub #73，父票 #59）：已刪除／已封存的活動不會出現在 list_campaigns，
    但 insights 歷史成效裡還有它的 campaign_id——同步時要照樣補進待認領清單，
    不然它的成效永遠卡在「查無歸屬」進不了任何品牌。"""

    def test_insight_only_campaign_lands_in_pending_claims_marked_historical(self):
        """①清單沒有、insights 有的活動，出現在待認領清單且標示歷史來源。"""
        result = self._sync(
            campaigns=[],
            insights=[_insight("999", campaign_name=f"{self.brand_name}_20260101_sales")])
        self.assertEqual(result.discovered, 1)

        row = main.conn.execute(
            "SELECT * FROM discovered_campaign WHERE meta_campaign_id = '999'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["effective_status"], ads_sync.HISTORICAL_STATUS)
        self.assertIn("歷史", row["effective_status"])

        pending = ads_sync.list_pending_claims(main.conn, self.bid)
        self.assertEqual(len(pending), 1)
        self.assertIn("歷史", pending[0]["effective_status"])

        page = self.client.get(f"/brands/{self.bid}/ads/claims")
        self.assertIn("歷史", page.text)

    def test_guess_brand_still_runs_off_the_insight_campaign_name(self):
        """④猜品牌邏輯對這類活動照常運作：insight 帶的 campaign_name 跟品牌命名一樣時能猜到。"""
        self._sync(campaigns=[],
                   insights=[_insight("998", campaign_name=f"{self.brand_name}_20260101_sales")])
        row = main.conn.execute(
            "SELECT * FROM discovered_campaign WHERE meta_campaign_id = '998'").fetchone()
        self.assertEqual(row["suggested_brand_id"], self.bid)
        self.assertEqual(row["claim_status"], "suggested")
        self.assertIn("命名", row["suggested_reason"])

    def test_guess_brand_leaves_it_blank_when_it_cannot_tell(self):
        """④猜不到就留空，不亂猜。"""
        self._sync(campaigns=[], insights=[_insight("997", campaign_name="隨便取的名字")])
        row = main.conn.execute(
            "SELECT * FROM discovered_campaign WHERE meta_campaign_id = '997'").fetchone()
        self.assertIsNone(row["suggested_brand_id"])
        self.assertEqual(row["claim_status"], "unclaimed")
        self.assertIsNone(row["suggested_reason"])

    def test_unclaimed_historical_insight_is_still_skipped(self):
        """②未認領時其成效仍被略過——原則不變。"""
        result = self._sync(campaigns=[], insights=[_insight("996")])
        self.assertEqual(result.snapshots, 0)
        self.assertEqual(result.skipped_unclaimed, 1)
        self.assertEqual(main.conn.execute(
            "SELECT COUNT(*) c FROM performance_snapshot").fetchone()["c"], 0)

    def test_claiming_then_resyncing_brings_its_numbers_into_the_brand(self):
        """③認領後再次回填→其成效入品牌層、月彙總正確。"""
        self._sync(campaigns=[], insights=[_insight("995")])
        discovered_id = main.conn.execute(
            "SELECT id FROM discovered_campaign WHERE meta_campaign_id = '995'"
        ).fetchone()["id"]
        ads_sync.claim(main.conn, self.bid, discovered_id, ACTOR)

        result = self._sync(campaigns=[], insights=[_insight("995")])
        self.assertEqual(result.snapshots, 1)
        row = main.conn.execute(
            "SELECT * FROM performance_snapshot WHERE meta_campaign_id = '995'").fetchone()
        self.assertEqual(row["brand_id"], self.bid)
        self.assertIsNone(row["campaign_cycle_id"])  # 沒有檔期對應，落在品牌層

        totals = ads_performance.brand_level_totals(main.conn, self.bid)
        self.assertEqual(totals["spend"], 5000.0)

    def test_resync_does_not_duplicate_the_historical_discovery_row(self):
        self._sync(campaigns=[], insights=[_insight("994")])
        second = self._sync(campaigns=[], insights=[_insight("994")])
        self.assertEqual(second.discovered, 0)
        rows = main.conn.execute(
            "SELECT COUNT(*) c FROM discovered_campaign WHERE meta_campaign_id = '994'"
        ).fetchone()
        self.assertEqual(rows["c"], 1)

    def test_still_active_campaign_is_not_downgraded_to_historical(self):
        """活動清單裡還在的活動，狀態要用清單回來的真實狀態，不能被 insights 的補登蓋掉。"""
        result = self._sync(campaigns=[_campaign("993", "某人的活動", status="ACTIVE")],
                            insights=[_insight("993")])
        self.assertEqual(result.discovered, 1)  # 只算一次，不是清單＋insights 各算一次
        rows = main.conn.execute(
            "SELECT * FROM discovered_campaign WHERE meta_campaign_id = '993'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["effective_status"], "ACTIVE")


if __name__ == "__main__":
    unittest.main()
