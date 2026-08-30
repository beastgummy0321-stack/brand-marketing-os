"""app/tests/test_meta_daily_spend.py — 票 05：每日拉 Meta 花費並顯示。

四件事，只寫這四件（docs/workflow-diet.md 第 4 條：金額、租戶隔離、API 契約、資料
正確性；畫面行為不寫單元測試，只留 frontend/e2e/smoke.spec.ts 一支端到端煙霧測試）：

1. 金額正確：拿票面點名的真實數字當 fixture（BP AD 三檔活動共 NT$172,081，ROAS
   3.22／2.21；上等生技四檔活動共 NT$22,256，ROAS 0.54，三檔未追蹤），驗證存進
   `meta_campaign_spend` 的加總與逐檔金額對得上，且「未追蹤」（purchase_roas 缺 key、
   空陣列、顯式 null 三種可能形狀都要驗）永遠存成 NULL，不是 0。
2. 重跑同一天不重複、不 double count：同一份 fixture 跑兩次，列數與金額不變
   （meta_campaign_spend 的 (ad_account_id, campaign_id, spend_date) 唯一索引撐住的
   upsert，見 migration／repository.upsert_campaign_spend）。
3. 一次拉取失敗（GraphError）留舊資料、不動 last_pull_at；同一輪跑裡另一個帳號成功
   互不牽連（部分成功優於全部放棄）。
4. 租戶隔離：對一個組織跑 `run_daily_pull` 完全不寫另一個組織的列——即使兩個組織都
   有綁定的帳號、都能被拉。

外加 API 契約：GET /api/meta/brands/{brand_id}/spend 的加總邏輯（ROAS 是比率，花費
加權平均；任一列未追蹤，該活動或總計就整組回 None，不能悄悄假裝把那筆花費的營收
算進去了）與跨組織 404。

procrastinate 的實際排程／worker 機制（defer → run_worker → 真的跑）已經是票 01 的
測試範圍（test_background.py）；這裡只補一支證明 `register_task()` 掛的名字
（"background.meta_daily_pull"，滿足 ADR 0038 TaskSignatureOrgIdGateTest 的
"background." 前綴掃描）真的能被 defer／跑，不重複整套機制的測試。
"""

import unittest
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

import app.background as background_module
import app.main as main
import app.meta.daily_pull as daily_pull
import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.core import settings as coresettings
from app.identity import repository as identity_repo
from app.meta import graph
from app.meta import repository as meta_repo

from .identity_test_helpers import mint_hs256

TOKEN = "EAAtest-fake-meta-token-abcd1234"

# ---- fixtures：票面點名的真實數字（HANDOFF-schedule-module.md §2）------------------

BP_ACCOUNT_ID = "300100000001001"
SD_ACCOUNT_ID = "300100000002002"

# BP AD：3 檔活動共 NT$172,081，ROAS 3.22／2.21 兩檔有追蹤，第三檔沒有 purchase_roas
# 這個 key（未追蹤的第一種形狀：整個 key 缺席）。
BP_INSIGHTS_PAGE = {
    "data": [
        {"campaign_id": "bp-c1", "campaign_name": "BP AD 業配 A", "spend": "100000.00",
         "impressions": "500000", "clicks": "8000",
         "purchase_roas": [{"action_type": "omni_purchase", "value": "3.22"}]},
        {"campaign_id": "bp-c2", "campaign_name": "BP AD 業配 B", "spend": "50000.00",
         "impressions": "250000", "clicks": "4000",
         "purchase_roas": [{"action_type": "onsite_web_purchase", "value": "2.21"}]},
        {"campaign_id": "bp-c3", "campaign_name": "BP AD 觸及 C", "spend": "22081.00",
         "impressions": "90000", "clicks": "1200"},
    ],
    "paging": {},
}

# 上等生技：4 檔活動共 NT$22,256，全部 NT$500 日預算，ROAS 0.54 一檔有追蹤，
# 三檔未追蹤——分別用「缺 key」「空陣列」「顯式 null」三種可能形狀各驗一次
# （Graph API 文件沒說死是哪一種，見 app/meta/graph.py 檔頭說明）。
SD_INSIGHTS_PAGE = {
    "data": [
        {"campaign_id": "sd-c1", "campaign_name": "上等 A", "spend": "6000.00",
         "impressions": "40000", "clicks": "600",
         "purchase_roas": [{"action_type": "purchase", "value": "0.54"}]},
        {"campaign_id": "sd-c2", "campaign_name": "上等 B（空陣列）", "spend": "6000.00",
         "impressions": "35000", "clicks": "500", "purchase_roas": []},
        {"campaign_id": "sd-c3", "campaign_name": "上等 C（缺 key）", "spend": "6000.00",
         "impressions": "30000", "clicks": "400"},
        {"campaign_id": "sd-c4", "campaign_name": "上等 D（顯式 null）", "spend": "4256.00",
         "impressions": "20000", "clicks": "300", "purchase_roas": None},
    ],
    "paging": {},
}


def _dispatch_insights(pages_by_account: dict):
    """回傳一個 fetch_page 替身：依 URL 裡的 act_<account_id> 決定回哪一頁。"""

    def fake(url, *, params, headers):
        for account_id, page in pages_by_account.items():
            if f"act_{account_id}/insights" in url:
                return page
        raise AssertionError(f"沒有對應的 fixture：{url}")

    return fake


def _fail_for(account_id: str, otherwise):
    """回傳一個 fetch_page 替身：這個帳號一律連不上，其他帳號照 `otherwise` 那支跑。"""
    import httpx

    def fake(url, *, params, headers):
        if f"act_{account_id}/insights" in url:
            raise httpx.ConnectError("boom")
        return otherwise(url, params=params, headers=headers)

    return fake


class _MetaDailySpendTestBase(unittest.TestCase):
    """共用：換掉 graph.fetch_page（不打真正網路）、掛好本測試模組自己那份
    `background.app()` 上的 task（DSN 每個測試模組都不同，見 daily_pull.py 檔頭
    「為什麼不能只做一次」）、建帳號／綁定的小工具。"""

    def setUp(self):
        self._orig_fetch_page = graph.fetch_page
        daily_pull.register_task()
        self.client = TestClient(main.app)

    def tearDown(self):
        graph.fetch_page = self._orig_fetch_page

    def _make_org(self, suffix: str) -> tuple:
        """每次呼叫都是一個全新的組織（org_id 帶隨機尾碼）——即使同一個 suffix
        字串在同一支測試檔裡被叫很多次（每個測試方法各自的 setUp），也不會撞到
        同一個 (org_id, account_id) 組合，才不會讓某個測試方法的資料悄悄成為
        下一個測試方法的『舊資料』（upsert 語意本身沒有辦法分辨『真的是舊資料』
        跟『其實是別的測試留下來的』）。"""
        org_id = f"org_spend_test_{suffix}_{uuid4().hex[:10]}"
        web.conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
            " ON CONFLICT (id) DO NOTHING",
            (org_id, org_id),
        )
        user_id = uuid4()
        email = f"spend-test-{suffix}-{user_id.hex[:8]}@example.com"
        identity_repo.create_user(web.conn, user_id, email)
        identity_repo.create_membership(web.conn, org_id, user_id, "owner")
        web.conn.commit()
        return org_id, mint_hs256(sub=str(user_id), email=email)

    @staticmethod
    def _headers(token: str, org_id: str) -> dict:
        return {"Authorization": f"Bearer {token}", "X-Org-Id": org_id}

    def _connect_account(self, org_id: str, account_id: str, name: str) -> str:
        """接權杖＋落地一個帳號，回傳它的內部 id（"mad_..."）。直接呼叫 repository，
        不經過 /api/meta/token——這批測試要驗的是 daily_pull／spend 讀取，不是
        票 04 已經驗過的連接流程。"""
        meta_repo.save_token(web.conn, org_id, TOKEN)
        meta_repo.upsert_accounts(web.conn, org_id, [
            {"account_id": account_id, "name": name, "currency": "TWD"},
        ])
        web.conn.commit()
        row = next(a for a in meta_repo.list_accounts(web.conn, org_id)
                   if a["account_id"] == account_id)
        return row["id"]

    def _bind(self, org_id: str, brand_id: str, ad_account_id: str) -> None:
        meta_repo.bind(web.conn, org_id, brand_id, ad_account_id)
        web.conn.commit()

    def _spend_rows(self, ad_account_id: str) -> list:
        return list(web.conn.execute(
            "SELECT campaign_id, spend, roas FROM meta_campaign_spend"
            " WHERE ad_account_id = %s ORDER BY campaign_id",
            (ad_account_id,),
        ))


# -- 1. 金額正確：票面真實數字，null 永遠是 null 不是 0 ------------------------------

class MoneyMathTest(_MetaDailySpendTestBase):
    def setUp(self):
        super().setUp()
        self.org_id, _ = self._make_org("money")
        self.bp_id = self._connect_account(self.org_id, BP_ACCOUNT_ID, "BP AD")
        self.sd_id = self._connect_account(self.org_id, SD_ACCOUNT_ID, "上等生技廣告帳號")
        brand_id = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="花費測試品牌", client_name=None, actor="test",
        )["id"]
        self._bind(self.org_id, brand_id, self.bp_id)
        self._bind(self.org_id, brand_id, self.sd_id)
        graph.fetch_page = _dispatch_insights(
            {BP_ACCOUNT_ID: BP_INSIGHTS_PAGE, SD_ACCOUNT_ID: SD_INSIGHTS_PAGE})

    def test_bp_ad_totals_and_roas_match_the_real_figures(self):
        daily_pull.run_daily_pull(self.org_id)
        rows = self._spend_rows(self.bp_id)
        self.assertEqual(len(rows), 3)
        self.assertAlmostEqual(sum(float(r["spend"]) for r in rows), 172081.00, places=2)
        by_id = {r["campaign_id"]: r for r in rows}
        self.assertAlmostEqual(float(by_id["bp-c1"]["roas"]), 3.22, places=2)
        self.assertAlmostEqual(float(by_id["bp-c2"]["roas"]), 2.21, places=2)
        self.assertIsNone(by_id["bp-c3"]["roas"], "缺 purchase_roas key 必須存成 NULL，不是 0")

    def test_shangdeng_totals_and_three_untracked_campaigns(self):
        daily_pull.run_daily_pull(self.org_id)
        rows = self._spend_rows(self.sd_id)
        self.assertEqual(len(rows), 4)
        self.assertAlmostEqual(sum(float(r["spend"]) for r in rows), 22256.00, places=2)
        by_id = {r["campaign_id"]: r for r in rows}
        self.assertAlmostEqual(float(by_id["sd-c1"]["roas"]), 0.54, places=2)
        # 空陣列、缺 key、顯式 null 三種形狀，一律是 NULL（未追蹤），不是 0。
        self.assertIsNone(by_id["sd-c2"]["roas"])
        self.assertIsNone(by_id["sd-c3"]["roas"])
        self.assertIsNone(by_id["sd-c4"]["roas"])

    def test_successful_pull_sets_last_pull_at(self):
        before = web.conn.execute(
            "SELECT last_pull_at FROM meta_ad_account WHERE id = %s", (self.bp_id,)
        ).fetchone()["last_pull_at"]
        self.assertIsNone(before)
        daily_pull.run_daily_pull(self.org_id)
        after = web.conn.execute(
            "SELECT last_pull_at FROM meta_ad_account WHERE id = %s", (self.bp_id,)
        ).fetchone()["last_pull_at"]
        self.assertIsNotNone(after)


# -- 2. 重跑同一天不重複、不 double count ---------------------------------------------

class RerunIsIdempotentTest(_MetaDailySpendTestBase):
    def test_running_twice_does_not_duplicate_or_double_count(self):
        org_id, _ = self._make_org("rerun")
        bp_id = self._connect_account(org_id, BP_ACCOUNT_ID, "BP AD")
        brand_id = bi_repo.create_brand(
            web.conn, org_id=org_id, name="重跑測試品牌", client_name=None, actor="test",
        )["id"]
        self._bind(org_id, brand_id, bp_id)
        graph.fetch_page = _dispatch_insights({BP_ACCOUNT_ID: BP_INSIGHTS_PAGE})

        daily_pull.run_daily_pull(org_id)
        daily_pull.run_daily_pull(org_id)

        rows = self._spend_rows(bp_id)
        self.assertEqual(len(rows), 3, "同一天重跑不該多出列")
        self.assertAlmostEqual(sum(float(r["spend"]) for r in rows), 172081.00, places=2)


# -- 3. 失敗留舊資料、不動 last_pull_at；同輪別的帳號互不牽連 -------------------------

class FailedPullLeavesOldDataTest(_MetaDailySpendTestBase):
    def test_one_account_failing_does_not_touch_its_old_data_or_last_pull_at(self):
        org_id, _ = self._make_org("failed")
        bp_id = self._connect_account(org_id, BP_ACCOUNT_ID, "BP AD")
        sd_id = self._connect_account(org_id, SD_ACCOUNT_ID, "上等生技廣告帳號")
        brand_id = bi_repo.create_brand(
            web.conn, org_id=org_id, name="失敗測試品牌", client_name=None, actor="test",
        )["id"]
        self._bind(org_id, brand_id, bp_id)
        self._bind(org_id, brand_id, sd_id)

        # 第一輪：兩個帳號都成功，留下一組「舊資料」與各自的 last_pull_at。
        graph.fetch_page = _dispatch_insights(
            {BP_ACCOUNT_ID: BP_INSIGHTS_PAGE, SD_ACCOUNT_ID: SD_INSIGHTS_PAGE})
        daily_pull.run_daily_pull(org_id)
        bp_rows_before = self._spend_rows(bp_id)
        bp_last_pull_before = web.conn.execute(
            "SELECT last_pull_at FROM meta_ad_account WHERE id = %s", (bp_id,)
        ).fetchone()["last_pull_at"]

        # 第二輪：BP AD 連不上 Meta，上等生技照常成功。
        graph.fetch_page = _fail_for(
            BP_ACCOUNT_ID,
            otherwise=_dispatch_insights({SD_ACCOUNT_ID: SD_INSIGHTS_PAGE}),
        )
        daily_pull.run_daily_pull(org_id)

        bp_rows_after = self._spend_rows(bp_id)
        bp_last_pull_after = web.conn.execute(
            "SELECT last_pull_at FROM meta_ad_account WHERE id = %s", (bp_id,)
        ).fetchone()["last_pull_at"]
        self.assertEqual(
            [(r["campaign_id"], r["spend"]) for r in bp_rows_before],
            [(r["campaign_id"], r["spend"]) for r in bp_rows_after],
            "失敗的帳號，舊的花費數字必須原封不動",
        )
        self.assertEqual(bp_last_pull_before, bp_last_pull_after, "失敗不該更新上次成功時間")

        sd_after = web.conn.execute(
            "SELECT last_pull_at FROM meta_ad_account WHERE id = %s", (sd_id,)
        ).fetchone()["last_pull_at"]
        self.assertIsNotNone(sd_after, "同一輪裡，成功的帳號不該被失敗的帳號拖累")


# -- 4. 租戶隔離：一個組織的 run 不寫另一個組織的列 -----------------------------------

class OrgIsolationTest(_MetaDailySpendTestBase):
    def test_running_for_org_a_writes_nothing_for_org_b(self):
        org_a, _ = self._make_org("a")
        org_b, _ = self._make_org("b")
        account_a = self._connect_account(org_a, BP_ACCOUNT_ID, "A 的帳號")
        account_b = self._connect_account(org_b, SD_ACCOUNT_ID, "B 的帳號")
        brand_a = bi_repo.create_brand(
            web.conn, org_id=org_a, name="A 的品牌", client_name=None, actor="test")["id"]
        brand_b = bi_repo.create_brand(
            web.conn, org_id=org_b, name="B 的品牌", client_name=None, actor="test")["id"]
        self._bind(org_a, brand_a, account_a)
        self._bind(org_b, brand_b, account_b)
        graph.fetch_page = _dispatch_insights(
            {BP_ACCOUNT_ID: BP_INSIGHTS_PAGE, SD_ACCOUNT_ID: SD_INSIGHTS_PAGE})

        daily_pull.run_daily_pull(org_a)

        self.assertGreater(len(self._spend_rows(account_a)), 0, "org A 自己應該有拉到資料")
        self.assertEqual(self._spend_rows(account_b), [], "org A 的 run 不該寫 org B 的列")
        b_last_pull = web.conn.execute(
            "SELECT last_pull_at FROM meta_ad_account WHERE id = %s", (account_b,)
        ).fetchone()["last_pull_at"]
        self.assertIsNone(b_last_pull, "org B 的帳號沒被拉過，last_pull_at 該還是 NULL")


# -- 4b. 花費記在哪一天＝組織自己的時區的今天（票 04-1b）-------------------------------

class SpendDateFollowsOrgTimezoneTest(_MetaDailySpendTestBase):
    """`spend_date` 是這筆錢算在哪一天。修復前它是 `datetime.now(UTC).date()`——伺服器
    搬到 UTC 機房，台北的整個上午拉到的花費就會掛在前一天。兩個相差 26 小時的組織在
    同一個瞬間跑，日期必須不同（修復前必然相同）。"""

    def _pull_one_org(self, suffix: str, timezone: str, account_id: str, page: dict) -> str:
        org_id, _ = self._make_org(suffix)
        coresettings.set_setting(
            web.conn, coresettings.ORG_TIMEZONE_SETTING, timezone, org_id=org_id)
        internal_id = self._connect_account(org_id, account_id, f"{suffix} 的帳號")
        brand_id = bi_repo.create_brand(
            web.conn, org_id=org_id, name=f"{suffix} 的品牌", client_name=None, actor="test")["id"]
        self._bind(org_id, brand_id, internal_id)
        graph.fetch_page = _dispatch_insights({account_id: page})
        daily_pull.run_daily_pull(org_id)
        return web.conn.execute(
            "SELECT DISTINCT spend_date FROM meta_campaign_spend WHERE ad_account_id = %s",
            (internal_id,),
        ).fetchone()["spend_date"]

    def test_two_orgs_a_day_apart_file_the_same_pull_under_different_dates(self):
        east = self._pull_one_org("tz_east", "Pacific/Kiritimati", BP_ACCOUNT_ID, BP_INSIGHTS_PAGE)
        west = self._pull_one_org("tz_west", "Etc/GMT+12", SD_ACCOUNT_ID, SD_INSIGHTS_PAGE)
        self.assertEqual(east, datetime.now(ZoneInfo("Pacific/Kiritimati")).date())
        self.assertEqual(west, datetime.now(ZoneInfo("Etc/GMT+12")).date())
        self.assertNotEqual(east, west, "相差 26 小時的兩個組織不可能把同一次拉取記在同一天")


# -- 5. 真的透過 procrastinate 排程跑一次（證明 register_task() 掛對名字、defer 得到）--

class QueueWiringTest(_MetaDailySpendTestBase):
    def test_deferred_and_run_through_the_real_queue(self):
        org_id, _ = self._make_org("queue")
        bp_id = self._connect_account(org_id, BP_ACCOUNT_ID, "BP AD")
        brand_id = bi_repo.create_brand(
            web.conn, org_id=org_id, name="排程測試品牌", client_name=None, actor="test",
        )["id"]
        self._bind(org_id, brand_id, bp_id)
        graph.fetch_page = _dispatch_insights({BP_ACCOUNT_ID: BP_INSIGHTS_PAGE})

        a = background_module.app()
        with a.open():
            job_id = a.configure_task("background.meta_daily_pull").defer(org_id=org_id)
        a.run_worker(wait=False)

        schema = coredb.current().execute("SELECT current_schema() AS s").fetchone()["s"]
        row = coredb.current().execute(
            f'SELECT status FROM "{schema}__queue".procrastinate_jobs WHERE id = %s', (job_id,)
        ).fetchone()
        self.assertEqual(row["status"], "succeeded")
        self.assertEqual(len(self._spend_rows(bp_id)), 3)


# -- 5b. 排程本身：不用人手動跑（票 05 fix round，review 打回的 done-check）-------------
#
# 「defer → worker → 落地」已經被上面 QueueWiringTest 證過；這裡只補「誰按下開始鍵」的
# 那一段——periodic dispatch task 真的掛上了、觸發時真的對每個有綁帳號的組織各 defer 一個
# job。worker 是否真的常駐、lifespan 收不收得乾淨，是 app/background 自己的事，見
# app/tests/test_background.py WorkerLifespanTest。

class ScheduledDispatchTest(_MetaDailySpendTestBase):
    def test_register_task_wires_the_periodic_cron(self):
        a = background_module.app()
        self.assertIn(daily_pull._DISPATCH_TASK_NAME, a.tasks,
                       "register_task() 必須連 periodic dispatch task 一起掛")
        key = (daily_pull._DISPATCH_TASK_NAME, daily_pull._DISPATCH_PERIODIC_ID)
        self.assertIn(key, a.periodic_registry.periodic_tasks,
                       "dispatch task 必須真的用 periodic() 註冊，不能只是掛了普通 task")
        self.assertEqual(
            a.periodic_registry.periodic_tasks[key].cron, daily_pull._DAILY_PULL_CRON)

    def test_dispatch_defers_and_lands_rows_for_every_bound_account(self):
        """periodic 觸發時實際會跑的路徑：dispatch → defer → worker → 落地——跟
        QueueWiringTest 同一條鏈路，差別只在 defer 這一步由 `_dispatch_daily_pull`（一天
        觸發一次的排程本身）做，不是測試手動 configure_task().defer()。"""
        org_id, _ = self._make_org("dispatch")
        bp_id = self._connect_account(org_id, BP_ACCOUNT_ID, "BP AD")
        brand_id = bi_repo.create_brand(
            web.conn, org_id=org_id, name="排程 dispatch 測試品牌", client_name=None, actor="test",
        )["id"]
        self._bind(org_id, brand_id, bp_id)
        web.conn.commit()
        graph.fetch_page = _dispatch_insights({BP_ACCOUNT_ID: BP_INSIGHTS_PAGE})

        a = background_module.app()
        with a.open():
            daily_pull._dispatch_daily_pull(0)
        a.run_worker(wait=False)

        self.assertEqual(len(self._spend_rows(bp_id)), 3,
                          "periodic dispatch 觸發後，綁定的帳號也要真的落地資料")


# -- 6. API 契約：GET /api/meta/brands/{brand_id}/spend -----------------------------

class BrandSpendRouteTest(_MetaDailySpendTestBase):
    def setUp(self):
        super().setUp()
        self.org_id, self.token = self._make_org("route")
        self.account_id = self._connect_account(self.org_id, BP_ACCOUNT_ID, "BP AD")
        self.brand_id = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="路由測試品牌", client_name=None, actor="test",
        )["id"]
        self._bind(self.org_id, self.brand_id, self.account_id)
        self.auth = self._headers(self.token, self.org_id)

    def _insert_row(self, campaign_id, day, spend, roas, impressions=1000, clicks=10, name=None):
        meta_repo.upsert_campaign_spend(
            web.conn, self.org_id, self.account_id, day,
            [{"campaign_id": campaign_id, "campaign_name": name or campaign_id, "spend": spend,
              "impressions": impressions, "clicks": clicks, "roas": roas}],
        )
        web.conn.commit()

    def test_a_campaign_renamed_mid_month_stays_one_row_with_its_latest_name(self):
        """錢的正確性（票 11 審查發現）：改名前後的日列各自留著當天的名稱，若照
        (campaign_id, campaign_name) 分組，同一個活動會裂成兩列、各拿半個月的花費——
        畫面上就少算一半，而且沒有任何錯誤訊息提醒。"""
        from datetime import UTC, datetime, timedelta
        month_start = datetime.now(UTC).date().replace(day=1)
        self._insert_row("c1", month_start, 1000, 2.0, name="活動一")
        self._insert_row("c1", month_start + timedelta(days=1), 3000, 4.0, name="活動一（改名後）")

        resp = self.client.get(f"/api/meta/brands/{self.brand_id}/spend", headers=self.auth)
        body = resp.json()
        self.assertEqual(len(body["campaigns"]), 1, "同一個活動改名不該裂成兩列")
        row = body["campaigns"][0]
        self.assertAlmostEqual(row["spend"], 4000.0, places=2)
        self.assertEqual(row["campaign_name"], "活動一（改名後）", "顯示最後一天用的名稱")
        self.assertAlmostEqual(row["roas"], 3.5, places=2)  # 花費加權：(1000*2+3000*4)/4000

    def test_weighted_total_roas_and_null_propagation(self):
        from datetime import UTC, datetime
        today = datetime.now(UTC).date()
        self._insert_row("c1", today, 1000, 2.0)
        self._insert_row("c2", today, 3000, 4.0)

        resp = self.client.get(f"/api/meta/brands/{self.brand_id}/spend", headers=self.auth)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body["campaigns"]), 2)
        self.assertAlmostEqual(body["total"]["spend"], 4000.0, places=2)
        # 花費加權：(1000*2 + 3000*4) / 4000 = 3.5，不是天真平均 (2+4)/2=3。
        self.assertAlmostEqual(body["total"]["roas"], 3.5, places=2)

        # 加一檔未追蹤的活動：任何一列 roas 是 None，總計就整組回 None——不能假裝
        # 那筆花費的營收被算進去了。
        self._insert_row("c3", today, 500, None)
        resp = self.client.get(f"/api/meta/brands/{self.brand_id}/spend", headers=self.auth)
        body = resp.json()
        self.assertAlmostEqual(body["total"]["spend"], 4500.0, places=2)
        self.assertIsNone(body["total"]["roas"])
        # 但個別已追蹤的活動小計還是各自的真實數字，不會被拖成 None。
        by_id = {c["campaign_id"]: c for c in body["campaigns"]}
        self.assertAlmostEqual(by_id["c1"]["roas"], 2.0, places=2)
        self.assertIsNone(by_id["c3"]["roas"])

    def test_rows_outside_this_month_are_excluded(self):
        from datetime import UTC, datetime, timedelta
        today = datetime.now(UTC).date()
        last_month = today.replace(day=1) - timedelta(days=1)
        self._insert_row("old", last_month, 999, 1.0)
        resp = self.client.get(f"/api/meta/brands/{self.brand_id}/spend", headers=self.auth)
        body = resp.json()
        self.assertEqual(body["campaigns"], [], "上個月的花費不該算進本月總計")
        self.assertEqual(body["total"]["spend"], 0.0)

    def test_brand_with_no_bound_account_has_empty_summary(self):
        empty_brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="沒綁帳號的品牌", client_name=None, actor="test",
        )["id"]
        resp = self.client.get(f"/api/meta/brands/{empty_brand}/spend", headers=self.auth)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["campaigns"], [])
        self.assertIsNone(body["last_pull_at"])

    def test_other_org_cannot_read_this_brand_spend(self):
        org_b, token_b = self._make_org("route")
        resp = self.client.get(
            f"/api/meta/brands/{self.brand_id}/spend",
            headers=self._headers(token_b, org_b),
        )
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
