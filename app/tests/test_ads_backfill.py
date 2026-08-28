"""app/tests/test_ads_backfill.py — 票 F3（GitHub #62）：回填日期參數（Meta＋GA4 一鍵 12 個月）。

驗收 rubric（決策 0039 第 3 條）：
①日常同步行為不變（既有測試不動全綠，本檔不改任何既有測試）
②回填 route 傳 12 個月範圍，假金鑰隔離 DB 下走完流程
③縮短情境誠實顯示 N 個月
④F5 重整不重複觸發
⑤Meta 歷史上限已向官方文件查證且程式碼註明出處 URL（見 app/ads/sync.py 常數區註解）

全程 FakeMetaClient／FakeGA4Client，不發任何真實網路請求；比照
test_ads_progress_background.py 的做法，用模組層級 monkeypatch（`ads_sync.make_client`／
`ga4_sync.make_client`）注入假用戶端——sync_account／sync_brand 本身就支援 `client=` 覆寫，
但路由沒有為此開一個新參數（正式流程一律用真用戶端），所以測試改用同一招換掉
`make_client`，不改任何正式程式碼。品牌名一律虛構。
"""

import time
import unittest
from datetime import date, timedelta

from fastapi.testclient import TestClient

import app.main as main
from app.ads import ga4_api, ga4_sync, meta_api
from app.ads import routes as ads_routes
from app.ads import sync as ads_sync
from app.brand_intelligence import repository as bi_repo
from app.core import settings as coresettings

ACTOR = "測試員"
ACCOUNT = "act_1234567890"
PROPERTY_ID = "123456789"
FAKE_KEY_JSON = '{"client_email": "svc@example.iam.gserviceaccount.com"}'




class MonthMathTest(unittest.TestCase):
    """`ads_sync.months_before` 純函數：日曆月往回推，不是 30N 天近似值。"""

    def test_simple_case_same_day_of_month(self):
        self.assertEqual(ads_sync.months_before("2026-08-15", 1), "2026-07-15")

    def test_crosses_year_boundary(self):
        self.assertEqual(ads_sync.months_before("2026-01-10", 2), "2025-11-10")

    def test_clamps_to_shorter_target_month(self):
        """3/31 往回推一個月落在 2 月——2026 不是閏年，2 月只有 28 天。"""
        self.assertEqual(ads_sync.months_before("2026-03-31", 1), "2026-02-28")

    def test_twelve_months_back(self):
        self.assertEqual(ads_sync.months_before("2026-08-04", 12), "2025-08-04")


class BackfillRangeTest(unittest.TestCase):
    """`ads_sync.backfill_range`：夾住 Meta 歷史上限，回傳 (since, until, actual_months)。"""

    def test_requested_within_cap_is_used_as_is(self):
        since, until, actual_months = ads_sync.backfill_range(12, today="2026-08-04")
        self.assertEqual(until, "2026-08-04")
        self.assertEqual(since, "2025-08-04")
        self.assertEqual(actual_months, 12)

    def test_requested_beyond_cap_is_clamped(self):
        """驗收 rubric ③ 的底層邏輯：要求超過官方上限就誠實夾住，不假裝拿得到那麼多。"""
        original = ads_sync.META_MAX_HISTORY_MONTHS
        ads_sync.META_MAX_HISTORY_MONTHS = 3
        try:
            since, until, actual_months = ads_sync.backfill_range(12, today="2026-08-04")
        finally:
            ads_sync.META_MAX_HISTORY_MONTHS = original
        self.assertEqual(actual_months, 3)
        self.assertEqual(since, "2026-05-04")


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


class _BaseMetaBackfillTest(unittest.TestCase):
    """T4 大清倉第 2 刀：回填精靈 Jinja 路由（`/brands/{b}/ads/connections/meta/backfill`）
    已隨 `_render_wait_page`（app/ads/routes_progress.py）一併刪除——已被
    `/api/campaigns/brands/{brand_id}/backfill/meta`（app/ads/routes_onboarding_api.py，
    資料上線 React 頁在用）取代。但新端點的完成通知只回「Meta 成效已完成」這種泛用訊息，
    不像舊路由那樣把「實際拿到幾個月」「發現幾個新活動」組成一句話回傳——這批 rubric 驗證
    改直呼舊路由本來就是呼叫的兩個業務函式（`ads_sync.backfill_range`／`sync_account`），
    斷言意義不變（真正做事的邏輯在這兩個函式裡，路由只是把回傳值組句子），不依賴訊息組字。
    """

    def setUp(self):
        self.client = TestClient(main.app)
        main.conn.execute("DELETE FROM discovered_campaign")
        main.conn.execute("DELETE FROM derived_metric")
        main.conn.execute("DELETE FROM performance_snapshot")
        main.conn.commit()
        self.brand = bi_repo.create_brand(
            main.conn, name=f"虛構回填晨光咖啡{abs(hash(self.id())) % 10000}",
            client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]
        coresettings.set_setting(main.conn, ads_sync.ACCOUNT_SETTING, ACCOUNT)
        coresettings.set_setting(main.conn, ads_sync.TOKEN_SETTING, "fake-token")
        self._orig_make_client = ads_sync.make_client

    def tearDown(self):
        ads_sync.make_client = self._orig_make_client

    def _patch_client(self, campaigns=None, insights=None, delay=0.0):
        fake = meta_api.FakeMetaClient(campaigns=campaigns, insights=insights)
        if delay:
            real_list_campaigns = fake.list_campaigns

            def _slow_list_campaigns(account_id):
                time.sleep(delay)
                return real_list_campaigns(account_id)

            fake.list_campaigns = _slow_list_campaigns
        ads_sync.make_client = lambda conn: fake
        return fake


class MetaBackfillConfigurationTest(_BaseMetaBackfillTest):
    def test_not_configured_shows_a_plain_warning(self):
        """原本打 HTTP 等待頁看轉址警告；頁面已刪，直測路由本來就是靠它把關的
        `ads_sync.is_configured`。"""
        main.conn.execute("DELETE FROM app_setting WHERE key IN (%s, %s)",
                          (ads_sync.TOKEN_SETTING, ads_sync.ACCOUNT_SETTING))
        main.conn.commit()
        self.assertFalse(ads_sync.is_configured(main.conn))

    def test_progress_touch_alone_does_not_trigger_any_sync(self):
        """安全底線：只是「看過」進度狀態（`_progress_touch`，等待頁 run!=1 那個分支
        唯一會做的事）不能觸發任何呼叫——同一套背景引擎的通用行為，另見
        test_ads_progress_background.py IdempotencyTest。"""
        fake = self._patch_client(campaigns=[_campaign("1", "某活動")])
        key = ads_routes._progress_key("meta_backfill", self.bid, "_brand_")
        for _ in range(3):
            ads_routes._progress_touch(key, [("run", "回填 Meta 廣告成效中")])
        self.assertEqual(fake.calls, [])
        ads_routes._progress_clear(key)


class MetaBackfillFlowTest(_BaseMetaBackfillTest):
    def test_full_flow_reports_actual_months_and_requests_twelve_month_range(self):
        """驗收 rubric ②：回填傳 12 個月範圍，假金鑰隔離 DB 下走完流程。

        issue #70 根因修正：Meta `/insights` 沒指定 time_increment 時整段時間範圍只回
        一列聚合資料，回填 12 個月會讓資料全部塌成「最後一天所在的那個月」一組。改成
        逐月分開打 API 之後，這裡驗證的重點從「只打一次」改成「逐月各打一次，總覆蓋範圍
        精準對上請求的 12 個月，段與段之間不重疊、不留縫」。"""
        fake = self._patch_client(campaigns=[_campaign("1", "某活動")])

        since, until, actual_months = ads_sync.backfill_range(12)
        result = ads_sync.sync_account(main.conn, ACTOR, since=since, until=until)

        self.assertEqual(actual_months, 12)
        self.assertEqual(result.discovered, 1)

        insight_calls = [c for c in fake.calls if c[0] == "insights"]
        self.assertGreater(len(insight_calls), 1)  # 逐月分開打，不是一次整段問完（issue #70）
        for c in insight_calls:
            self.assertEqual(c[1], ACCOUNT)

        windows = [(c[2], c[3]) for c in insight_calls]
        self.assertEqual(windows[0][0], since)   # 第一段從請求的起點開始
        self.assertEqual(windows[-1][1], until)  # 最後一段在請求的終點結束
        for w_since, w_until in windows:
            self.assertEqual(w_since[:7], w_until[:7])  # 每一段都落在單一日曆月內
        for (_, w_until), (next_since, _) in zip(windows, windows[1:]):
            # 前一段結束隔天正好是下一段開始：不重疊、不留縫
            self.assertEqual(date.fromisoformat(w_until) + timedelta(days=1),
                             date.fromisoformat(next_since))

    def test_shortened_history_is_displayed_honestly(self):
        """驗收 rubric ③：夾到比 12 個月短時，`backfill_range` 誠實回報實際拿到的月數。"""
        original = ads_sync.META_MAX_HISTORY_MONTHS
        ads_sync.META_MAX_HISTORY_MONTHS = 2
        try:
            _since, _until, actual_months = ads_sync.backfill_range(12)
        finally:
            ads_sync.META_MAX_HISTORY_MONTHS = original
        self.assertEqual(actual_months, 2)

    def test_repeated_trigger_does_not_call_client_twice(self):
        """驗收 rubric ④：F5／多分頁重整（同一個 key 重複觸發）不會讓背景任務被多打一次
        ——直測進度引擎本身的冪等閘，接上真正的 sync_account 當 work，不只是通用假函式
        （通用機制另見 test_ads_progress_background.py ProgressRunResultShapeTest）。"""
        fake = self._patch_client(campaigns=[_campaign("1", "某活動")], delay=0.2)
        key = ads_routes._progress_key("meta_backfill", self.bid, "_test_")

        def work(on_stage):
            since, until, _months = ads_sync.backfill_range(12)
            return ads_sync.sync_account(main.conn, ACTOR, since=since, until=until)

        ads_routes._progress_start(key, [("run", "回填 Meta 廣告成效中")], work)
        ads_routes._progress_start(key, [("run", "回填 Meta 廣告成效中")], work)  # 模擬 F5

        deadline = time.time() + 5
        while (ads_routes._progress_state.get(key, {}).get("status") != "done"
               and time.time() < deadline):
            time.sleep(0.02)

        campaign_calls = [c for c in fake.calls if c[0] == "campaigns"]
        self.assertEqual(len(campaign_calls), 1, "F5 不得重複觸發：list_campaigns 只該被打一次")
        ads_routes._progress_clear(key)


class GA4BackfillConfigurationTest(unittest.TestCase):
    """同 _BaseMetaBackfillTest 檔頭說明：GA4 回填精靈 Jinja 路由已刪，改直測業務層。"""

    def setUp(self):
        self.client = TestClient(main.app)
        main.conn.execute("DELETE FROM ga4_summary")
        main.conn.execute("DELETE FROM ga4_sync_status")
        main.conn.commit()
        self.brand = bi_repo.create_brand(
            main.conn, name=f"虛構回填晨光咖啡GA{abs(hash(self.id())) % 10000}",
            client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]
        self._orig_make_client = ga4_sync.make_client

    def tearDown(self):
        ga4_sync.make_client = self._orig_make_client

    def test_not_configured_shows_a_plain_warning(self):
        main.conn.execute("DELETE FROM app_setting WHERE key IN (%s, %s)",
                          (ga4_sync.PROPERTY_SETTING, ga4_sync.SERVICE_ACCOUNT_SETTING))
        main.conn.commit()
        self.assertFalse(ga4_sync.is_configured(main.conn))

    def test_progress_touch_alone_does_not_trigger_any_sync(self):
        coresettings.set_setting(main.conn, ga4_sync.PROPERTY_SETTING, PROPERTY_ID)
        coresettings.set_setting(main.conn, ga4_sync.SERVICE_ACCOUNT_SETTING, FAKE_KEY_JSON)
        fake = ga4_api.FakeGA4Client(rows=[])
        ga4_sync.make_client = lambda conn: fake
        key = ads_routes._progress_key("ga4_backfill", self.bid, "_brand_")
        for _ in range(3):
            ads_routes._progress_touch(key, [("connect", "連線 GA4 服務帳戶")])
        self.assertEqual(fake.calls, [])
        ads_routes._progress_clear(key)


class GA4BackfillFlowTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        main.conn.execute("DELETE FROM ga4_summary")
        main.conn.execute("DELETE FROM ga4_sync_status")
        main.conn.commit()
        self.brand = bi_repo.create_brand(
            main.conn, name=f"虛構回填晨光咖啡GA2{abs(hash(self.id())) % 10000}",
            client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]
        coresettings.set_setting(main.conn, ga4_sync.PROPERTY_SETTING, PROPERTY_ID)
        coresettings.set_setting(main.conn, ga4_sync.SERVICE_ACCOUNT_SETTING, FAKE_KEY_JSON)
        self._orig_make_client = ga4_sync.make_client

    def tearDown(self):
        ga4_sync.make_client = self._orig_make_client

    def _patch_client(self, rows=None, purchase_seen=True, delay=0.0):
        fake = ga4_api.FakeGA4Client(rows=rows, purchase_seen=purchase_seen)
        if delay:
            real_fetch = fake.fetch_source_medium

            def _slow_fetch(since, until):
                time.sleep(delay)
                return real_fetch(since, until)

            fake.fetch_source_medium = _slow_fetch
        ga4_sync.make_client = lambda conn: fake
        return fake

    def test_full_flow_reports_requested_months_and_requests_twelve_month_range(self):
        """驗收 rubric ②：GA4 回填傳 12 個月範圍，假金鑰隔離 DB 下走完流程。"""
        row = ga4_api.SourceMediumRow(source="google", medium="cpc", sessions=100,
                                      conversions=5.0, revenue=8000.0)
        fake = self._patch_client(rows=[row], purchase_seen=True)

        until = date.today().isoformat()
        since = ads_sync.months_before(until, 12)
        result = ga4_sync.sync_brand(main.conn, self.bid, ACTOR, since=since, until=until)

        self.assertIsNone(result.error)
        self.assertEqual(result.rows, 1)

        source_medium_calls = [c for c in fake.calls if c[0] == "source_medium"]
        self.assertEqual(len(source_medium_calls), 1)
        _, call_since, call_until = source_medium_calls[0]
        self.assertEqual(call_until, until)
        self.assertEqual(call_since, since)

    def test_repeated_trigger_does_not_call_client_twice(self):
        """驗收 rubric ④：F5／多分頁重整（同一個 key 重複觸發）不會讓背景任務被多打一次。"""
        fake = self._patch_client(rows=[], delay=0.2)
        key = ads_routes._progress_key("ga4_backfill", self.bid, "_test_")

        def work(on_stage):
            until = date.today().isoformat()
            since = ads_sync.months_before(until, 12)
            return ga4_sync.sync_brand(main.conn, self.bid, ACTOR, since=since, until=until)

        stages = [("connect", "連線 GA4 服務帳戶"), ("fetch", "抓取來源／媒介成效與 purchase 事件"),
                  ("save", "寫入彙總表")]
        ads_routes._progress_start(key, stages, work)
        ads_routes._progress_start(key, stages, work)  # 模擬 F5

        deadline = time.time() + 5
        while (ads_routes._progress_state.get(key, {}).get("status") != "done"
               and time.time() < deadline):
            time.sleep(0.02)

        source_medium_calls = [c for c in fake.calls if c[0] == "source_medium"]
        self.assertEqual(len(source_medium_calls), 1,
                         "F5 不得重複觸發：fetch_source_medium 只該被打一次")
        ads_routes._progress_clear(key)


class DailySyncUnaffectedTest(unittest.TestCase):
    """驗收 rubric ①：日常同步（30 天視窗）行為完全不受回填功能影響。"""

    def test_default_lookback_constant_unchanged(self):
        self.assertEqual(ads_sync.DEFAULT_LOOKBACK_DAYS, 30)
        self.assertEqual(ga4_sync.DEFAULT_LOOKBACK_DAYS, 30)

    def test_sync_account_without_since_until_keeps_default_thirty_day_window(self):
        fake = meta_api.FakeMetaClient(campaigns=[], insights=[])
        ads_sync.sync_account(main.conn, ACTOR, client=fake, today="2026-07-31")
        insight_calls = [c for c in fake.calls if c[0] == "insights"]
        _, _, since, until = insight_calls[0]
        self.assertEqual(until, "2026-07-31")
        self.assertEqual(since, "2026-07-01")  # 30 天前，不是回填的日曆月算法


if __name__ == "__main__":
    unittest.main()
