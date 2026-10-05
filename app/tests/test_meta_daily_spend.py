"""app/tests/test_meta_daily_spend.py — 票 05／S1：每日拉 Meta 花費並顯示，三層都拉。

只寫 全域 CLAUDE.md 測試四類允許的四類（金額、租戶隔離、API 契約、資料正確性；
畫面行為不寫單元測試，只留 frontend/e2e/smoke.spec.ts 一支端到端煙霧測試）：

1. 金額正確：拿票面點名的真實數字當 fixture（BP AD 三檔活動共 NT$172,081，ROAS
   3.22／2.21；上等生技四檔活動共 NT$22,256，ROAS 0.54，三檔未追蹤），驗證存進
   `meta_entity_spend` 的加總與逐檔金額對得上，且「未追蹤」（purchase_roas 缺 key、
   空陣列、顯式 null 三種可能形狀都要驗）永遠存成 NULL，不是 0。
2. 重跑同一天不重複、不 double count：同一份 fixture 跑兩次，列數與金額不變；同一個
   (account, level, entity, date) upsert 兩次、數字不同，只留第二次的值（
   meta_entity_spend 的 (ad_account_id, level, entity_id, spend_date) 唯一索引撐住的
   upsert，見 migration／repository.upsert_entity_spend）。
3. 一次拉取失敗（GraphError）留舊資料、不動 last_pull_at；同一輪跑裡另一個帳號成功
   互不牽連（部分成功優於全部放棄）；某一層某一天 Meta 沒回任何列，就是零列，不補一列
   spend=0（票 S1 D8：沒投遞跟投了沒成效是兩件事）。
4. 租戶隔離：對一個組織跑 `run_daily_pull` 完全不寫另一個組織的列——即使兩個組織都
   有綁定的帳號、都能被拉。

外加：
- API 契約：GET /api/meta/brands/{brand_id}/spend 的加總邏輯（ROAS 是比率，花費加權
  平均；任一列未追蹤，該活動或總計就整組回 None，不能悄悄假裝把那筆花費的營收算進去
  了）與跨組織 404；`attribution_window` 存的是這次請求真的送出的值（票 S1 D6）；
  `backfill` 按日曆月切段，三個月該送三次請求，不是一次也不是九十次（票 S1 D4）。
- 金額：三層共用一張表，`spend_summary(level="campaign")` 不能把 adset／ad 層的花費
  疊進來變三倍（票 S1 done-check 1）；CPA 沒設定轉換目標就是 NULL，設定了就照對應的
  action_type 算（票 S1 D4）；backfill 的 37 個月保護要在任何 HTTP 呼叫之前就擋下
  （票 S1 D10）。

procrastinate 的實際排程／worker 機制（defer → run_worker → 真的跑）已經是票 01 的
測試範圍（test_background.py）；這裡只補一支證明 `register_task()` 掛的名字
（"background.meta_daily_pull"，滿足 ADR 0038 TaskSignatureOrgIdGateTest 的
"background." 前綴掃描）真的能被 defer／跑，不重複整套機制的測試。
"""

import json
import unittest
from datetime import datetime, timedelta
from unittest import mock
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
from app.schedule import repository as schedule_repo

from .identity_test_helpers import mint_hs256
from .org_clock import org_today

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


def _with_date_start(page: dict, params: dict) -> dict:
    """幫 fixture 每一列補上 `date_start`——`_to_entity_row`（票 S1 D7）要求每一列自己帶
    日期，不能從呼叫端的迴圈變數來；夾具本身不用管日期，這裡從送出的 `time_range` 讀
    `until` 補上去。

    2026-09-01 從 `since` 改成 `until`：拉取範圍不再是單日（歸因窗 7d_click，見
    `daily_pull._ATTRIBUTION_LOOKBACK_DAYS`），`since` 現在是七天前。夾具只回一列，
    那一列代表的是「今天」——所以要蓋上範圍的**最後一天**。用 `since` 會讓每一個
    「這次拉取落在哪一天」的斷言都指向七天前。"""
    until = json.loads(params["time_range"])["until"]
    return {**page, "data": [dict(item, date_start=until) for item in page.get("data", [])]}


def _dispatch_insights(pages_by_account: dict):
    """回傳一個 fetch_page 替身：依 URL 裡的 act_<account_id> 決定回哪一頁（不分層級——
    這批既有測試只餵 campaign 形狀的資料，adset／ad 層請求會因為缺 adset_id／ad_id
    被 `_to_entity_row` 跳過，落地列數不受影響，見 `AbsenceIsNotZeroTest` 對這個行為的
    正面驗證）。"""

    def fake(url, *, params, headers):
        for account_id, page in pages_by_account.items():
            if f"act_{account_id}/insights" in url:
                return _with_date_start(page, params)
        raise AssertionError(f"沒有對應的 fixture：{url}")

    return fake


def _dispatch_by_level(account_id: str, pages_by_level: dict):
    """回傳一個 fetch_page 替身：依 URL 裡的 act_<account_id> **與** `params["level"]`
    決定回哪一頁——比 `_dispatch_insights` 精細，用在需要驗證「這一層真的什麼都沒有」
    （票 S1 D8：絕不能補一列 0）的測試。沒對到的層級回一頁空資料，不是憑空造錯。"""

    def fake(url, *, params, headers):
        if f"act_{account_id}/insights" not in url:
            raise AssertionError(f"沒有對應的 fixture：{url}")
        page = pages_by_level.get(params["level"], {"data": [], "paging": {}})
        return _with_date_start(page, params)

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
        """只看 campaign 層——這批既有測試的 fixture 本來就只餵得出 campaign 層的列
        （見 `_dispatch_insights` 的說明），這裡明講篩 level 而不是巧合地只有一層。"""
        return list(web.conn.execute(
            "SELECT entity_id, spend, roas FROM meta_entity_spend"
            " WHERE ad_account_id = %s AND level = 'campaign' ORDER BY entity_id",
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
        by_id = {r["entity_id"]: r for r in rows}
        self.assertAlmostEqual(float(by_id["bp-c1"]["roas"]), 3.22, places=2)
        self.assertAlmostEqual(float(by_id["bp-c2"]["roas"]), 2.21, places=2)
        self.assertIsNone(by_id["bp-c3"]["roas"], "缺 purchase_roas key 必須存成 NULL，不是 0")

    def test_shangdeng_totals_and_three_untracked_campaigns(self):
        daily_pull.run_daily_pull(self.org_id)
        rows = self._spend_rows(self.sd_id)
        self.assertEqual(len(rows), 4)
        self.assertAlmostEqual(sum(float(r["spend"]) for r in rows), 22256.00, places=2)
        by_id = {r["entity_id"]: r for r in rows}
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

    def test_upserting_same_entity_twice_with_different_numbers_keeps_only_the_second(self):
        """資料正確性（票 S1 done-check 2）：同一個 (account, level, entity, date) upsert
        兩次、數字不同，只留一列、值是第二次的——這是 (ad_account_id, level, entity_id,
        spend_date) 唯一索引撐住的重跑安全機制，不是程式碼自己防呆。"""
        from datetime import UTC, datetime

        org_id, _ = self._make_org("upsert_twice")
        bp_id = self._connect_account(org_id, BP_ACCOUNT_ID, "BP AD")
        day = datetime.now(UTC).date()

        def row(spend):
            return {"level": "campaign", "entity_id": "c1", "entity_name": "活動一",
                    "campaign_id": "c1", "adset_id": None, "ad_id": None, "spend_date": day,
                    "spend": spend, "impressions": 100, "clicks": 10, "roas": None,
                    "actions": None, "action_values": None,
                    "attribution_window": "7d_click,1d_view"}

        meta_repo.upsert_entity_spend(web.conn, org_id, bp_id, [row(1000)])
        web.conn.commit()
        meta_repo.upsert_entity_spend(web.conn, org_id, bp_id, [row(2000)])
        web.conn.commit()

        rows = self._spend_rows(bp_id)
        self.assertEqual(len(rows), 1, "同一個實體同一天，不該留下兩列")
        self.assertAlmostEqual(float(rows[0]["spend"]), 2000.0, places=2,
                                msg="留下的該是第二次寫進去的數字")


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
        # 2026-09-01：失敗不再靜默。以前這一支照樣算成功，於是「Meta 限流」跟「今天真的
        # 沒有花費」在系統裡長得一模一樣。現在跑完所有帳號才拋，所以下面「成功的帳號沒被
        # 拖累」那條斷言仍然成立。
        # F50 Contract J：拋的是 `background.JobFailed("account_failed")`，句子指名帳號。
        with self.assertRaises(background_module.JobFailed) as caught:
            daily_pull.run_daily_pull(org_id)
        self.assertEqual(caught.exception.code, "account_failed")
        self.assertIn(BP_ACCOUNT_ID, caught.exception.text or "", "錯誤訊息要指名是哪個帳號失敗")
        self.assertNotIn(SD_ACCOUNT_ID, caught.exception.text or "", "成功的帳號不該被點名")

        bp_rows_after = self._spend_rows(bp_id)
        bp_last_pull_after = web.conn.execute(
            "SELECT last_pull_at FROM meta_ad_account WHERE id = %s", (bp_id,)
        ).fetchone()["last_pull_at"]
        self.assertEqual(
            [(r["entity_id"], r["spend"]) for r in bp_rows_before],
            [(r["entity_id"], r["spend"]) for r in bp_rows_after],
            "失敗的帳號，舊的花費數字必須原封不動",
        )
        self.assertEqual(bp_last_pull_before, bp_last_pull_after, "失敗不該更新上次成功時間")

        sd_after = web.conn.execute(
            "SELECT last_pull_at FROM meta_ad_account WHERE id = %s", (sd_id,)
        ).fetchone()["last_pull_at"]
        self.assertIsNotNone(sd_after, "同一輪裡，成功的帳號不該被失敗的帳號拖累")


# -- 3a-2. 拉取範圍要蓋住歸因窗 -------------------------------------------------------

class PullCoversTheAttributionWindowTest(_MetaDailySpendTestBase):
    """歸因窗是 `7d_click`：一天的 roas 在那天之後還會被改變七天。只拉當天等於把每一天
    的數字凍在第 0 天，最近一週系統性偏低，而且看起來像「新廣告都在賠」。"""

    def test_time_range_spans_the_attribution_window_not_just_today(self):
        org_id, _ = self._make_org("window")
        bp_id = self._connect_account(org_id, BP_ACCOUNT_ID, "BP AD")
        brand_id = bi_repo.create_brand(
            web.conn, org_id=org_id, name="歸因窗測試品牌", client_name=None, actor="test",
        )["id"]
        self._bind(org_id, brand_id, bp_id)

        seen: list = []
        inner = _dispatch_insights({BP_ACCOUNT_ID: BP_INSIGHTS_PAGE})

        def recording(url, *, params, headers):
            seen.append(json.loads(params["time_range"]) if params else None)
            return inner(url, params=params, headers=headers)

        graph.fetch_page = recording
        daily_pull.run_daily_pull(org_id)

        self.assertTrue(seen, "沒有任何一次 insights 請求")
        today = coresettings.today_for_org(web.conn, org_id=org_id)
        # 天數從 `graph._ATTRIBUTION_WINDOWS`（"7d_click"）推，**不是**從被測的
        # `daily_pull._ATTRIBUTION_LOOKBACK_DAYS` 推——第一版就是拿後者當期望值，
        # 結果把回補天數改成 0 照樣綠（同義反覆）。歸因窗多長，拉取就得回頭蓋多長。
        window_days = max(int(w.split("d_")[0]) for w in graph._ATTRIBUTION_WINDOWS)
        expected_since = (today - timedelta(days=window_days)).isoformat()
        for rng in seen:
            self.assertEqual(rng["until"], today.isoformat())
            self.assertEqual(
                rng["since"], expected_since,
                "拉取起點要往回蓋住歸因窗，不是今天",
            )


# -- 3b. 缺席不是零：Meta 對某一層某一天沒回任何列，就是零列，不是一列 spend=0 ----------

class AbsenceIsNotZeroTest(_MetaDailySpendTestBase):
    def test_a_level_with_no_data_produces_no_rows_not_a_zero_row(self):
        """資料正確性（票 S1 done-check 3、D8）：ad 層這次完全沒回任何資料，
        meta_entity_spend 就該是零列——補一列 spend=0 會把「沒投遞」偽造成「投了沒
        成效」，兩者是完全不同的事實。"""
        org_id, _ = self._make_org("absence")
        bp_id = self._connect_account(org_id, BP_ACCOUNT_ID, "BP AD")
        brand_id = bi_repo.create_brand(
            web.conn, org_id=org_id, name="缺席測試品牌", client_name=None, actor="test")["id"]
        self._bind(org_id, brand_id, bp_id)
        # 只給 campaign 層資料；adset／ad 層明講回空資料，不是巧合地缺欄位被跳過。
        graph.fetch_page = _dispatch_by_level(BP_ACCOUNT_ID, {"campaign": BP_INSIGHTS_PAGE})

        daily_pull.run_daily_pull(org_id)

        ad_rows = web.conn.execute(
            "SELECT * FROM meta_entity_spend WHERE ad_account_id = %s AND level = 'ad'",
            (bp_id,),
        ).fetchall()
        self.assertEqual(ad_rows, [], "ad 層沒有回任何資料，就該是零列，不是一列 spend=0")
        # campaign 層照樣落地，證明「缺席」只影響沒資料的那一層，不是整個帳號都不寫。
        self.assertEqual(len(self._spend_rows(bp_id)), 3)


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

    def test_running_backfill_for_org_a_writes_nothing_for_org_b(self):
        """票 past-ads/02 done-check 3：`run_backfill` 重用既有 `backfill()`，同一條租戶
        界線適用——跟上面 `run_daily_pull` 那支同一個斷言。"""
        org_a, _ = self._make_org("backfill_a")
        org_b, _ = self._make_org("backfill_b")
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

        daily_pull.run_backfill(org_a)

        self.assertGreater(len(self._spend_rows(account_a)), 0, "org A 自己應該有拉到資料")
        self.assertEqual(self._spend_rows(account_b), [], "org A 的補拉不該寫 org B 的列")


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
            "SELECT DISTINCT spend_date FROM meta_entity_spend"
            " WHERE ad_account_id = %s AND level = 'campaign'",
            (internal_id,),
        ).fetchone()["spend_date"]

    def test_two_orgs_a_day_apart_file_the_same_pull_under_different_dates(self):
        east = self._pull_one_org("tz_east", "Pacific/Kiritimati", BP_ACCOUNT_ID, BP_INSIGHTS_PAGE)
        west = self._pull_one_org("tz_west", "Etc/GMT+12", SD_ACCOUNT_ID, SD_INSIGHTS_PAGE)
        self.assertEqual(east, datetime.now(ZoneInfo("Pacific/Kiritimati")).date())
        self.assertEqual(west, datetime.now(ZoneInfo("Etc/GMT+12")).date())
        self.assertNotEqual(east, west, "相差 26 小時的兩個組織不可能把同一次拉取記在同一天")


class SpendDateFollowsTheAdAccountTimezoneTest(_MetaDailySpendTestBase):
    """票 T4：`spend_date` 改跟廣告帳戶自己的時區，不是組織的——同一個組織可能同時連著
    美國西岸的帳號，組織自己在台北，兩者的「今天」常常不一樣。`timezone_name` 是 NULL
    的帳號（T4 之前接的舊帳號）退回組織時區，不是另一套規則，是同一套規則的預設值
    （上面的 `SpendDateFollowsOrgTimezoneTest` 驗的正是這條退回路徑——那批帳號從沒填過
    `timezone_name`）。

    時區選 `Pacific/Kiritimati`／`Etc/GMT+12`——跟上面 `SpendDateFollowsOrgTimezoneTest`
    同一組，相差 26 小時：兩地的日期在任何時刻都不可能相同（`Asia/Taipei`／
    `America/Los_Angeles` 只差 15～16 小時，一天裡有大半時間兩邊日期剛好一樣，斷言會
    看時間點碰運氣過，不是真的證明帳戶時區真的生效）。"""

    def test_account_with_its_own_timezone_overrides_the_orgs(self):
        org_id, _ = self._make_org("acct_tz")
        coresettings.set_setting(
            web.conn, coresettings.ORG_TIMEZONE_SETTING, "Pacific/Kiritimati", org_id=org_id)
        brand_id = bi_repo.create_brand(
            web.conn, org_id=org_id, name="帳戶時區測試品牌", client_name=None, actor="test"
        )["id"]

        overridden_id = self._connect_account(org_id, BP_ACCOUNT_ID, "自己有時區的帳號")
        web.conn.execute(
            "UPDATE meta_ad_account SET timezone_name = %s WHERE id = %s",
            ("Etc/GMT+12", overridden_id),
        )
        legacy_id = self._connect_account(org_id, SD_ACCOUNT_ID, "沒填時區的舊帳號")
        web.conn.commit()
        self._bind(org_id, brand_id, overridden_id)
        self._bind(org_id, brand_id, legacy_id)

        graph.fetch_page = _dispatch_insights(
            {BP_ACCOUNT_ID: BP_INSIGHTS_PAGE, SD_ACCOUNT_ID: SD_INSIGHTS_PAGE})
        daily_pull.run_daily_pull(org_id)

        overridden_date = web.conn.execute(
            "SELECT DISTINCT spend_date FROM meta_entity_spend"
            " WHERE ad_account_id = %s AND level = 'campaign'", (overridden_id,)
        ).fetchone()["spend_date"]
        legacy_date = web.conn.execute(
            "SELECT DISTINCT spend_date FROM meta_entity_spend"
            " WHERE ad_account_id = %s AND level = 'campaign'", (legacy_id,)
        ).fetchone()["spend_date"]

        self.assertEqual(
            overridden_date, datetime.now(ZoneInfo("Etc/GMT+12")).date(),
            "填了 timezone_name 的帳號要用它自己的今天，不是組織的",
        )
        self.assertEqual(
            legacy_date, datetime.now(ZoneInfo("Pacific/Kiritimati")).date(),
            "timezone_name 是 NULL 的帳號要退回組織時區",
        )
        self.assertNotEqual(
            overridden_date, legacy_date,
            "相差 26 小時的兩個時區不可能在同一瞬間算出同一個日期",
        )


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


# -- 5c. 票 past-ads/02：37 個月補拉是一個背景工作，真的透過 procrastinate 跑一次 ----------

class BackfillQueueWiringTest(_MetaDailySpendTestBase):
    def test_deferred_and_run_through_the_real_queue_over_the_full_37_months(self):
        """done-check 1：task 掛好名字、真的透過 procrastinate defer／跑；第一個 insights
        請求的 `time_range.since` 等於 `_earliest_pullable(today)`，最後一個請求的 `until`
        等於今天（組織時區）——證明 `run_backfill` 真的呼叫既有 `backfill(org_id, since,
        today)`，不是另一條拉取路徑（票面「Nothing else」）。"""
        from datetime import date

        self.assertIn(daily_pull._BACKFILL_TASK_NAME, background_module.app().tasks)

        org_id, _ = self._make_org("backfill_queue")
        bp_id = self._connect_account(org_id, BP_ACCOUNT_ID, "BP AD")
        brand_id = bi_repo.create_brand(
            web.conn, org_id=org_id, name="補拉排程測試品牌", client_name=None, actor="test",
        )["id"]
        self._bind(org_id, brand_id, bp_id)
        today = coresettings.today_for_org(web.conn, org_id=org_id)
        calls: list[dict] = []

        def fake(url, *, params, headers):
            calls.append(dict(params))
            return {"data": [], "paging": {}}

        graph.fetch_page = fake

        a = background_module.app()
        with a.open():
            job_id = a.configure_task(daily_pull._BACKFILL_TASK_NAME).defer(org_id=org_id)
        a.run_worker(wait=False)

        schema = coredb.current().execute("SELECT current_schema() AS s").fetchone()["s"]
        row = coredb.current().execute(
            f'SELECT status FROM "{schema}__queue".procrastinate_jobs WHERE id = %s', (job_id,)
        ).fetchone()
        self.assertEqual(row["status"], "succeeded")

        self.assertGreater(len(calls), 0, "至少要打過一次 insights")
        first_since = date.fromisoformat(json.loads(calls[0]["time_range"])["since"])
        last_until = date.fromisoformat(json.loads(calls[-1]["time_range"])["until"])
        self.assertEqual(first_since, daily_pull._earliest_pullable(today))
        self.assertEqual(last_until, today)


# -- 5d. 一個組織一個補拉：第二次按下只回「還在跑」，佇列不長出第二筆 ----------------------

class BackfillOneRunningPerOrgTest(_MetaDailySpendTestBase):
    def test_second_start_while_one_is_queued_reports_running_not_started(self):
        """done-check 2：`backfill()` 是組織＋廣告帳戶層，所以鎖也是組織層——同一個組織
        兩次按下補拉，第二次不該再排一筆 job，佇列裡帶這個 lock 的 job 永遠只有一筆。"""
        org_id, token = self._make_org("backfill_lock")
        bp_id = self._connect_account(org_id, BP_ACCOUNT_ID, "BP AD")
        brand_id = bi_repo.create_brand(
            web.conn, org_id=org_id, name="補拉鎖測試品牌", client_name=None, actor="test",
        )["id"]
        self._bind(org_id, brand_id, bp_id)
        auth = self._headers(token, org_id)
        lock = daily_pull.backfill_lock(org_id)

        # 先手動排一筆 job、不跑 worker（停在 todo），模擬「已經有一個補拉在跑」。
        self.assertTrue(background_module.enqueue(
            daily_pull._BACKFILL_TASK_NAME, org_id=org_id, lock=lock))
        self.assertTrue(background_module.is_active(lock))

        resp = self.client.post(f"/api/meta/brands/{brand_id}/backfill", headers=auth)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"started": False, "running": True})

        schema = coredb.current().execute("SELECT current_schema() AS s").fetchone()["s"]
        rows = coredb.current().execute(
            f'SELECT count(*) AS n FROM "{schema}__queue".procrastinate_jobs'
            " WHERE queueing_lock = %s", (lock,),
        ).fetchone()
        self.assertEqual(rows["n"], 1, "同一個 lock 名下只該有一筆 job，不是兩筆")


# -- 5e. 補拉路由：跨組織 404、沒綁帳號 409 --------------------------------------------

class BackfillTenantBoundaryTest(_MetaDailySpendTestBase):
    def setUp(self):
        super().setUp()
        self.org_id, self.token = self._make_org("backfill_tenant")
        self.account_id = self._connect_account(self.org_id, BP_ACCOUNT_ID, "BP AD")
        self.brand_id = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="補拉租戶測試品牌", client_name=None, actor="test",
        )["id"]
        self._bind(self.org_id, self.brand_id, self.account_id)
        self.auth = self._headers(self.token, self.org_id)

    def test_other_org_cannot_start_or_read_this_brand_backfill(self):
        """done-check 3：另一個組織的 brand_id → 404，POST／GET 都一樣。"""
        org_b, token_b = self._make_org("backfill_tenant_b")
        auth_b = self._headers(token_b, org_b)
        self.assertEqual(
            self.client.post(
                f"/api/meta/brands/{self.brand_id}/backfill", headers=auth_b
            ).status_code, 404,
        )
        self.assertEqual(
            self.client.get(
                f"/api/meta/brands/{self.brand_id}/backfill", headers=auth_b
            ).status_code, 404,
        )

    def test_brand_with_no_bound_account_gets_409(self):
        """done-check 3：沒綁帳號的品牌 → 409 no_bound_account，POST／GET 都一樣。"""
        empty_brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="沒綁帳號的品牌", client_name=None, actor="test",
        )["id"]
        resp_post = self.client.post(
            f"/api/meta/brands/{empty_brand}/backfill", headers=self.auth)
        self.assertEqual(resp_post.status_code, 409)
        self.assertEqual(resp_post.json()["error"]["code"], "no_bound_account")
        resp_get = self.client.get(
            f"/api/meta/brands/{empty_brand}/backfill", headers=self.auth)
        self.assertEqual(resp_get.status_code, 409)
        self.assertEqual(resp_get.json()["error"]["code"], "no_bound_account")


# -- 5f. backfill_status：只讀呼叫端給的那幾個帳號 --------------------------------------

class BackfillStatusTest(_MetaDailySpendTestBase):
    def test_status_reads_only_the_given_accounts(self):
        """done-check 4：兩個帳號各有列，只問其中一個帳號拿到的 min／max／count 只算那個
        帳號的。"""
        from datetime import date

        org_id, _ = self._make_org("backfill_status")
        account_1 = self._connect_account(org_id, BP_ACCOUNT_ID, "帳號一")
        account_2 = self._connect_account(org_id, SD_ACCOUNT_ID, "帳號二")

        def _row(entity_id, day, spend):
            return {"level": "ad", "entity_id": entity_id, "entity_name": entity_id,
                    "campaign_id": "c1", "adset_id": "as1", "ad_id": entity_id,
                    "spend_date": day, "spend": spend, "impressions": 10, "clicks": 1,
                    "roas": None, "actions": None, "action_values": None,
                    "attribution_window": "7d_click,1d_view"}

        meta_repo.upsert_entity_spend(web.conn, org_id, account_1, [
            _row("ad-1a", date(2026, 6, 1), 100), _row("ad-1b", date(2026, 6, 5), 200),
        ])
        meta_repo.upsert_entity_spend(web.conn, org_id, account_2, [
            _row("ad-2a", date(2026, 7, 15), 300),
        ])
        web.conn.commit()

        status = daily_pull.backfill_status(web.conn, org_id, [account_1])
        self.assertEqual(status["earliest_spend_date"], date(2026, 6, 1))
        self.assertEqual(status["latest_spend_date"], date(2026, 6, 5))
        self.assertEqual(status["ad_rows"], 2)


# -- 5g. F50 Contract J：補拉與每日拉取一定留下結果，GET …/backfill 讀得到 -------------

class PullOutcomeTest(_MetaDailySpendTestBase):
    """F50-I10（R7 A12、controls a-66）：以前補拉跑完一列都沒有、或某個帳號失敗，畫面看到的
    都是 `running: false, ad_rows: 0`——沒跑過、跑完沒資料、失敗長得一模一樣。現在每一次
    跑完都存一個結果，`GET …/backfill` 的 `outcome` 照實給。"""

    def setUp(self):
        super().setUp()
        self.org_id, token = self._make_org("pull_outcome")
        self.auth = self._headers(token, self.org_id)
        self.bp_id = self._connect_account(self.org_id, BP_ACCOUNT_ID, "BP AD")
        self.brand_id = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="結果測試品牌", client_name=None, actor="test",
        )["id"]
        self._bind(self.org_id, self.brand_id, self.bp_id)

    def _run_backfill_job(self) -> str:
        """真的透過佇列跑一次補拉（跟路由同一個 lock），回傳 procrastinate 的 job status。"""
        lock = daily_pull.backfill_lock(self.org_id)
        self.assertTrue(background_module.enqueue(
            daily_pull._BACKFILL_TASK_NAME, org_id=self.org_id, lock=lock))
        web.conn.commit()
        background_module.app().run_worker(wait=False)
        schema = coredb.current().execute("SELECT current_schema() AS s").fetchone()["s"]
        return coredb.current().execute(
            f'SELECT status::text AS status FROM "{schema}__queue".procrastinate_jobs'
            " WHERE queueing_lock = %s ORDER BY id DESC LIMIT 1", (lock,),
        ).fetchone()["status"]

    def _backfill_status(self) -> dict:
        resp = self.client.get(f"/api/meta/brands/{self.brand_id}/backfill", headers=self.auth)
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()

    def test_never_ran_serves_a_null_outcome(self):
        self.assertIsNone(self._backfill_status()["outcome"])

    def test_backfill_with_zero_rows_is_empty_and_the_route_says_so(self):
        graph.fetch_page = lambda url, *, params, headers: {"data": [], "paging": {}}

        self.assertEqual(self._run_backfill_job(), "succeeded", "沒資料不是失敗")

        body = self._backfill_status()
        self.assertFalse(body["running"])
        self.assertEqual(body["ad_rows"], 0)
        self.assertEqual(body["outcome"]["state"], "empty")
        self.assertEqual(body["outcome"]["code"], "no_rows")
        self.assertTrue(body["outcome"]["text"])
        self.assertIsNotNone(body["outcome"]["finished_at"])

    def test_backfill_with_rows_is_done(self):
        def fake(url, *, params, headers):
            level = params["level"]
            since = json.loads(params["time_range"])["since"]
            item = {"campaign_id": "camp-1", f"{level}_id": f"{level}-1", "spend": "100",
                    "impressions": "1000", "clicks": "10", "date_start": since}
            return {"data": [item], "paging": {}}

        graph.fetch_page = fake

        self.assertEqual(self._run_backfill_job(), "succeeded")
        body = self._backfill_status()
        self.assertEqual(body["outcome"]["state"], "done")
        self.assertGreater(body["ad_rows"], 0)

    def test_backfill_with_a_failing_account_fails_with_the_classified_code(self):
        """一個帳號 Meta 回 190（權杖失效）→ 這次補拉失敗，code 是 `graph.classify_error`
        的分類 `auth`，句子指名帳號；另一個帳號照補，寫進去的列留著。"""
        sd_id = self._connect_account(self.org_id, SD_ACCOUNT_ID, "上等生技廣告帳號")
        self._bind(self.org_id, self.brand_id, sd_id)

        def fake(url, *, params, headers):
            if f"act_{BP_ACCOUNT_ID}/" in url:
                return {"error": {"code": 190, "message": "Error validating access token"}}
            level = params["level"]
            since = json.loads(params["time_range"])["since"]
            item = {"campaign_id": "camp-1", f"{level}_id": f"{level}-1", "spend": "100",
                    "impressions": "1000", "clicks": "10", "date_start": since}
            return {"data": [item], "paging": {}}

        graph.fetch_page = fake

        self.assertEqual(self._run_backfill_job(), "failed", "帳號失敗要讓這次 job 記成失敗")
        body = self._backfill_status()
        self.assertEqual(body["outcome"]["state"], "failed")
        self.assertEqual(body["outcome"]["code"], graph.ERROR_AUTH)
        self.assertIn(BP_ACCOUNT_ID, body["outcome"]["text"])
        self.assertNotIn(SD_ACCOUNT_ID, body["outcome"]["text"])
        self.assertGreater(body["ad_rows"], 0, "沒失敗的帳號照補，寫進去的列留著")

    def test_daily_pull_with_one_failed_account_fails_its_job_with_account_failed(self):
        sd_id = self._connect_account(self.org_id, SD_ACCOUNT_ID, "上等生技廣告帳號")
        self._bind(self.org_id, self.brand_id, sd_id)
        graph.fetch_page = _fail_for(
            BP_ACCOUNT_ID, otherwise=_dispatch_insights({SD_ACCOUNT_ID: SD_INSIGHTS_PAGE}))
        lock = f"meta_daily_pull_test:{self.org_id}"

        a = background_module.app()
        with a.open():
            a.configure_task(daily_pull._TASK_NAME, queueing_lock=lock).defer(org_id=self.org_id)
        a.run_worker(wait=False)

        found = background_module.outcome(lock)
        self.assertIsNotNone(found)
        self.assertEqual(found["state"], "failed")
        self.assertEqual(found["code"], "account_failed")
        self.assertIn(BP_ACCOUNT_ID, found["text"])
        self.assertNotIn(SD_ACCOUNT_ID, found["text"])


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
        meta_repo.upsert_entity_spend(
            web.conn, self.org_id, self.account_id,
            [{"level": "campaign", "entity_id": campaign_id, "entity_name": name or campaign_id,
              "campaign_id": campaign_id, "adset_id": None, "ad_id": None, "spend_date": day,
              "spend": spend, "impressions": impressions, "clicks": clicks, "roas": roas,
              "actions": None, "action_values": None,
              "attribution_window": "7d_click,1d_view"}],
        )
        web.conn.commit()

    def test_a_campaign_renamed_mid_month_stays_one_row_with_its_latest_name(self):
        """錢的正確性（票 11 審查發現）：改名前後的日列各自留著當天的名稱，若照
        (campaign_id, campaign_name) 分組，同一個活動會裂成兩列、各拿半個月的花費——
        畫面上就少算一半，而且沒有任何錯誤訊息提醒。"""
        month_start = org_today(web.conn, self.org_id).replace(day=1)
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
        today = org_today(web.conn, self.org_id)
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
        today = org_today(web.conn, self.org_id)
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


# -- 7. 金額：三層共用一張表，spend_summary(level=) 不能把別層的花費疊進來 --------------

class LevelNeverSumsTest(unittest.TestCase):
    """money（票 S1 done-check 1）：meta_entity_spend 三層共用一張表，`level` 是 NOT NULL
    沒有預設值就是為了擋住這件事——spend_summary 沒篩 level，campaign／adset／ad 三層的
    花費會被疊在一起，同一筆錢算三遍。"""

    def setUp(self):
        self.org_id = f"org_level_test_{uuid4().hex[:10]}"
        web.conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
            " ON CONFLICT (id) DO NOTHING",
            (self.org_id, self.org_id),
        )
        meta_repo.upsert_accounts(web.conn, self.org_id, [
            {"account_id": BP_ACCOUNT_ID, "name": "BP AD", "currency": "TWD"},
        ])
        web.conn.commit()
        self.account_id = next(
            a["id"] for a in meta_repo.list_accounts(web.conn, self.org_id)
            if a["account_id"] == BP_ACCOUNT_ID
        )
        from datetime import UTC, datetime
        self.today = datetime.now(UTC).date()
        self._seed("campaign", "camp-1", "camp-1", None, spend=1000)
        self._seed("adset", "adset-1", "camp-1", None, spend=2000)
        self._seed("ad", "ad-1", "camp-1", "adset-1", spend=4000)

    def _seed(self, level, entity_id, campaign_id, adset_id, *, spend):
        meta_repo.upsert_entity_spend(web.conn, self.org_id, self.account_id, [{
            "level": level, "entity_id": entity_id, "entity_name": entity_id,
            "campaign_id": campaign_id, "adset_id": adset_id, "ad_id": None,
            "spend_date": self.today, "spend": spend, "impressions": 100, "clicks": 10,
            "roas": None, "actions": None, "action_values": None,
            "attribution_window": "7d_click,1d_view",
        }])
        web.conn.commit()

    def test_campaign_level_summary_excludes_adset_and_ad_rows(self):
        from datetime import timedelta
        month_start = self.today.replace(day=1)
        month_end = (month_start + timedelta(days=32)).replace(day=1)
        summary = meta_repo.spend_summary(
            web.conn, self.org_id, [self.account_id], month_start, month_end, level="campaign",
        )
        self.assertEqual(len(summary["entities"]), 1, "只有一個 campaign 層實體")
        self.assertAlmostEqual(
            summary["total"]["spend"], 1000.0, places=2,
            msg="level='campaign' 混進了 adset（2000）／ad（4000）層的花費",
        )


# -- 8. attribution_window 存的是這次請求真的送出的值 -----------------------------------

class AttributionWindowStoredAsSentTest(unittest.TestCase):
    def setUp(self):
        self._orig_fetch_page = graph.fetch_page

    def tearDown(self):
        graph.fetch_page = self._orig_fetch_page

    def test_stored_attribution_window_matches_the_request_not_a_hardcoded_string(self):
        """資料正確性（票 S1 done-check 4、D6）：存進去的 attribution_window 是這次請求
        真的送出的 action_attribution_windows，不是測試自己寫死的一個字串——比對的對象是
        `graph._ATTRIBUTION_WINDOWS` 這個模組常數，不是複製一份字面值。"""
        from datetime import UTC, datetime

        sent = list(graph._ATTRIBUTION_WINDOWS)

        def fake(url, *, params, headers):
            self.assertEqual(json.loads(params["action_attribution_windows"]), sent,
                              "送出的 action_attribution_windows 跟模組常數對不上")
            since = json.loads(params["time_range"])["since"]
            return {"data": [{**BP_INSIGHTS_PAGE["data"][0], "date_start": since}], "paging": {}}

        graph.fetch_page = fake
        today = datetime.now(UTC).date()
        rows = graph.list_entity_insights("tok", BP_ACCOUNT_ID, "campaign", today, today)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["attribution_window"], ",".join(sent))


# -- 9. CPA：沒設定轉換目標是 NULL，設定了就照對應的 action_type 算 ---------------------

class CpaMappingTest(unittest.TestCase):
    """money（票 S1 done-check 6、D4）：CPA 該用哪個 action_type 由 conversion_goal 決定，
    沒設定就是 NULL，不是 0；設定了就用 README 對照表 map 出來的那個 action_type。"""

    def setUp(self):
        self.org_id = f"org_cpa_test_{uuid4().hex[:10]}"
        web.conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
            " ON CONFLICT (id) DO NOTHING",
            (self.org_id, self.org_id),
        )
        meta_repo.upsert_accounts(web.conn, self.org_id, [
            {"account_id": BP_ACCOUNT_ID, "name": "BP AD", "currency": "TWD"},
        ])
        web.conn.commit()
        self.account_id = next(
            a["id"] for a in meta_repo.list_accounts(web.conn, self.org_id)
            if a["account_id"] == BP_ACCOUNT_ID
        )
        from datetime import UTC, datetime
        self.today = datetime.now(UTC).date()
        meta_repo.upsert_entity_spend(web.conn, self.org_id, self.account_id, [{
            "level": "campaign", "entity_id": "c1", "entity_name": "活動一",
            "campaign_id": "c1", "adset_id": None, "ad_id": None, "spend_date": self.today,
            "spend": 1000, "impressions": 1000, "clicks": 50, "roas": None,
            "actions": [{"action_type": "lead", "value": "5"}], "action_values": None,
            "attribution_window": "7d_click,1d_view",
        }])
        web.conn.commit()

    def _summary(self, conversion_goal):
        from datetime import timedelta
        month_start = self.today.replace(day=1)
        month_end = (month_start + timedelta(days=32)).replace(day=1)
        return meta_repo.spend_summary(
            web.conn, self.org_id, [self.account_id], month_start, month_end,
            level="campaign", conversion_goal=conversion_goal,
        )

    def test_cpa_is_null_when_conversion_goal_is_unset(self):
        summary = self._summary(None)
        self.assertIsNone(summary["total"]["cpa"], "沒設定轉換目標，CPA 不該算出任何數字")

    def test_cpa_uses_the_mapped_action_type_when_goal_is_set(self):
        summary = self._summary("lead")
        # spend 1000 / lead 5 次 = 200；"lead" 目標映射到 ("lead", "complete_registration")，
        # 這一列的 actions 剛好有 lead=5。
        self.assertAlmostEqual(summary["total"]["cpa"], 200.0, places=2)

    def test_cpa_is_null_when_any_day_in_range_has_no_tracked_conversions(self):
        """money：同一個實體，一天有對得上的 action、另一天 actions 是 NULL（未追蹤，不是
        零轉換）——那天的花費照樣算進分子，NULL 卻不會被 SUM() 算進分母，沒有 bool_and
        保護就會印出一個過度樂觀的假 CPA。這裡驗證加了保護之後，整組正確地回 None。"""
        other_day = self.today.replace(day=1 if self.today.day != 1 else 2)
        meta_repo.upsert_entity_spend(web.conn, self.org_id, self.account_id, [{
            "level": "campaign", "entity_id": "c1", "entity_name": "活動一",
            "campaign_id": "c1", "adset_id": None, "ad_id": None, "spend_date": other_day,
            "spend": 1000, "impressions": 1000, "clicks": 50, "roas": None,
            "actions": None, "action_values": None, "attribution_window": "7d_click,1d_view",
        }])
        web.conn.commit()
        summary = self._summary("lead")
        self.assertIsNone(
            summary["total"]["cpa"], "有一天未追蹤到轉換，CPA 該回 None，不是灌水數字")
        self.assertIsNone(summary["entities"][0]["cpa"], "同一個實體小計也要一樣回 None")


# -- 9b. F16-I05：daily_entity_spend 多回 purchases／revenue／action_type／attribution_window --

# 2026-09-20 從 `meta_entity_spend` 撈的真實形狀（見票 F16-I05 環境說明），不是憑空造的購買
# 定義域：同一次交易被好幾個同義字各回報一次（`omni_purchase`／`purchase`），優先序只認
# `graph._ROAS_ACTION_PRIORITY` 第一個對得上的——這裡刻意兩個都放，用來驗證優先序真的生效。
_REAL_ACTIONS_WITH_PURCHASE = [
    {"value": "6", "1d_view": "4", "7d_click": "2", "action_type": "omni_purchase"},
    {"value": "6", "1d_view": "4", "7d_click": "2", "action_type": "purchase"},
    {"value": "31", "7d_click": "31", "action_type": "link_click"},
]
_REAL_ACTION_VALUES_WITH_PURCHASE = [
    {"value": "6000", "1d_view": "3000", "7d_click": "3000", "action_type": "purchase"},
    {"value": "6000", "1d_view": "3000", "7d_click": "3000", "action_type": "omni_purchase"},
]
# 同一份真實資料裡「有 actions 卻沒有任何購買同義字」的一列（帳號那天只回報互動事件）。
_REAL_ACTIONS_NO_PURCHASE = [
    {"value": "2", "7d_click": "2", "action_type": "link_click"},
    {"value": "91", "1d_view": "88", "7d_click": "3", "action_type": "page_engagement"},
    {"value": "1", "action_type": "post_interaction_gross"},
]


class DailyEntitySpendPurchasesTest(unittest.TestCase):
    """F16-I05：`daily_entity_spend` 不再回不了購買數——同義字判定整段沿用
    `external_purchase_values()`（`purchase` 目標的唯一定義是 `graph._ROAS_ACTION_PRIORITY`），
    這裡只驗證 SQL 端把對的欄位接出來，不是另外挑一次同義字。"""

    def setUp(self):
        from datetime import UTC, datetime

        self.org_id = f"org_purchases_test_{uuid4().hex[:10]}"
        web.conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
            " ON CONFLICT (id) DO NOTHING",
            (self.org_id, self.org_id),
        )
        meta_repo.upsert_accounts(web.conn, self.org_id, [
            {"account_id": BP_ACCOUNT_ID, "name": "BP AD", "currency": "TWD"},
            {"account_id": SD_ACCOUNT_ID, "name": "上等生技廣告帳號", "currency": "TWD"},
        ])
        web.conn.commit()
        self.account_id = next(
            a["id"] for a in meta_repo.list_accounts(web.conn, self.org_id)
            if a["account_id"] == BP_ACCOUNT_ID
        )
        # 兩個帳號用來組「同一個 (spend_date, entity_id, currency) group 裡有不只一個 physical
        # row」的情境——唯一索引 `(ad_account_id, level, entity_id, spend_date)` 讓同一個帳號
        # 沒辦法讓同一天同一個實體長出兩列，換一個帳號才擠得出這個 near-impossible 的分支。
        self.account_id_2 = next(
            a["id"] for a in meta_repo.list_accounts(web.conn, self.org_id)
            if a["account_id"] == SD_ACCOUNT_ID
        )
        self.today = datetime.now(UTC).date()

    def _row(self, entity_id: str, *, actions, action_values,
              attribution_window: str = "7d_click,1d_view") -> dict:
        return {
            "level": "campaign", "entity_id": entity_id, "entity_name": entity_id,
            "campaign_id": entity_id, "adset_id": None, "ad_id": None,
            "spend_date": self.today, "spend": 1000, "impressions": 1000, "clicks": 50,
            "roas": None, "actions": actions, "action_values": action_values,
            "attribution_window": attribution_window,
        }

    def _daily(self, account_ids: list | None = None) -> dict:
        rows = meta_repo.daily_entity_spend(
            web.conn, self.org_id, account_ids or [self.account_id], self.today,
            self.today + timedelta(days=1), level="campaign",
        )
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_real_purchase_action_reports_count_revenue_and_attribution(self):
        meta_repo.upsert_entity_spend(web.conn, self.org_id, self.account_id, [
            self._row("c1", actions=_REAL_ACTIONS_WITH_PURCHASE,
                      action_values=_REAL_ACTION_VALUES_WITH_PURCHASE),
        ])
        web.conn.commit()
        row = self._daily()
        self.assertEqual(row["purchases"], 6)
        self.assertAlmostEqual(row["revenue"], 6000.0, places=2)
        # 優先序第一個對得上的是 omni_purchase，不是同一列裡也存在的 purchase。
        self.assertEqual(row["action_type"], "omni_purchase")
        self.assertEqual(row["attribution_window"], "7d_click,1d_view")

    def test_no_purchase_action_present_is_untracked_not_zero(self):
        meta_repo.upsert_entity_spend(web.conn, self.org_id, self.account_id, [
            self._row("c2", actions=_REAL_ACTIONS_NO_PURCHASE, action_values=None),
        ])
        web.conn.commit()
        row = self._daily()
        self.assertIsNone(row["purchases"], "沒有任何購買同義字，未追蹤永遠不是 0")
        self.assertIsNone(row["revenue"])
        self.assertIsNone(row["action_type"])

    def test_purchase_action_present_with_tracked_zero_value_is_zero_not_none(self):
        meta_repo.upsert_entity_spend(web.conn, self.org_id, self.account_id, [
            self._row("c3",
                      actions=[{"action_type": "omni_purchase", "value": "0"}],
                      action_values=[{"action_type": "omni_purchase", "value": "0"}]),
        ])
        web.conn.commit()
        row = self._daily()
        self.assertEqual(row["purchases"], 0, "追蹤到真的零，不該回 None")
        self.assertEqual(row["revenue"], 0.0)
        self.assertEqual(row["action_type"], "omni_purchase")

    def test_no_actions_at_all_stays_untracked(self):
        """既有形狀（`actions`／`action_values` 都是 SQL NULL）不能被新欄位動到——這是
        F16-I05 之前所有既有呼叫端（`app/schedule/*`）已經在用的形狀。"""
        meta_repo.upsert_entity_spend(web.conn, self.org_id, self.account_id, [
            self._row("c4", actions=None, action_values=None),
        ])
        web.conn.commit()
        row = self._daily()
        self.assertIsNone(row["purchases"])
        self.assertIsNone(row["revenue"])
        self.assertIsNone(row["action_type"])
        self.assertEqual(row["spend"], 1000.0)
        self.assertEqual(row["impressions"], 1000)

    def test_two_rows_disagreeing_on_action_type_are_unknown_not_summed(self):
        """F16-I05 review repair：同一個 group 裡兩個 physical row（用兩個帳號硬湊，唯一索引
        讓同一個帳號辦不到）各自對到不同的購買同義字——加起來印一個數字、只掛其中一個
        action_type，等於講一個算對了、標籤卻是亂猜的故事。必須整組回未知，不是加總。"""
        meta_repo.upsert_entity_spend(web.conn, self.org_id, self.account_id, [
            self._row("c5", actions=[{"action_type": "omni_purchase", "value": "3"}],
                      action_values=[{"action_type": "omni_purchase", "value": "3000"}]),
        ])
        meta_repo.upsert_entity_spend(web.conn, self.org_id, self.account_id_2, [
            self._row("c5", actions=[{"action_type": "purchase", "value": "5"}],
                      action_values=[{"action_type": "purchase", "value": "5000"}]),
        ])
        web.conn.commit()
        row = self._daily([self.account_id, self.account_id_2])
        self.assertIsNone(row["purchases"], "兩個 row 對到不同 action_type，不能加總成 8")
        self.assertIsNone(row["revenue"])
        self.assertIsNone(row["action_type"])
        self.assertIsNone(row["attribution_window"])
        self.assertEqual(row["spend"], 2000.0, "花費本身照樣誠實加總，不受這條規則影響")

    def test_two_rows_disagreeing_on_attribution_window_are_unknown(self):
        """同一個購買同義字，但兩個 physical row 的歸因窗不一樣——同一條規則，不同觸發條件。"""
        meta_repo.upsert_entity_spend(web.conn, self.org_id, self.account_id, [
            self._row("c6", actions=[{"action_type": "omni_purchase", "value": "3"}],
                      action_values=[{"action_type": "omni_purchase", "value": "3000"}],
                      attribution_window="7d_click,1d_view"),
        ])
        meta_repo.upsert_entity_spend(web.conn, self.org_id, self.account_id_2, [
            self._row("c6", actions=[{"action_type": "omni_purchase", "value": "5"}],
                      action_values=[{"action_type": "omni_purchase", "value": "5000"}],
                      attribution_window="1d_click"),
        ])
        web.conn.commit()
        row = self._daily([self.account_id, self.account_id_2])
        self.assertIsNone(row["purchases"], "兩個 row 的歸因窗不一樣，不能假裝是同一件事")
        self.assertIsNone(row["revenue"])
        self.assertIsNone(row["action_type"])
        self.assertIsNone(row["attribution_window"])


# -- 10. backfill：37 個月保護在任何 HTTP 呼叫之前就擋下 --------------------------------

class RetentionGuardTest(_MetaDailySpendTestBase):
    def test_since_far_in_the_past_raises_before_any_http_call(self):
        """money（票 S1 done-check 7、D10）：backfill 的 `since` 超過 37 個月要在任何
        HTTP 呼叫之前就拒絕——不然一次補拉會打一串注定被 Meta 拒絕、或安靜少給資料的
        API 呼叫。"""
        from datetime import UTC, date, datetime

        org_id, _ = self._make_org("retention")
        called = []

        def fake(url, *, params, headers):
            called.append(url)
            return {"data": [], "paging": {}}

        graph.fetch_page = fake
        with self.assertRaises(ValueError):
            daily_pull.backfill(org_id, date(2000, 1, 1), datetime.now(UTC).date())
        self.assertEqual(called, [], "37 個月保護要在任何 HTTP 呼叫之前擋下")


# -- 11. backfill：按日曆月切段，三個月該送三次請求，不是一次也不是九十次 ----------------

class MonthlyChunkingTest(_MetaDailySpendTestBase):
    def test_three_month_backfill_issues_three_requests_per_level_not_one_and_not_ninety(self):
        """API 契約（票 S1 done-check 8）：官方對「查詢太大」的處方是把日期範圍切小
        （SPEC §7.4(b)），不是一次全要，也不是逐日發送——三個月的補拉，三層各自該是
        3 次請求（一段一個日曆月），不是 1 次（塞進單一呼叫）也不是 90 次（逐日）。"""
        from datetime import date

        org_id, _ = self._make_org("chunking")
        bp_id = self._connect_account(org_id, BP_ACCOUNT_ID, "BP AD")
        brand_id = bi_repo.create_brand(
            web.conn, org_id=org_id, name="切段測試品牌", client_name=None, actor="test")["id"]
        self._bind(org_id, brand_id, bp_id)
        calls: list[dict] = []

        def fake(url, *, params, headers):
            calls.append(dict(params))
            level = params["level"]
            since = json.loads(params["time_range"])["since"]
            # 每一層造一筆自己那層形狀的資料（帶對的 {level}_id），這樣三層都真的落地，
            # 才驗證得出「9 次請求 → 9 列」，不是巧合地因為 fixture 缺欄位被跳過。
            item = {"campaign_id": "camp-1", f"{level}_id": f"{level}-1", "spend": "100",
                    "impressions": "1000", "clicks": "10", "date_start": since}
            return {"data": [item], "paging": {}}

        graph.fetch_page = fake
        since = date(2026, 6, 1)
        until = date(2026, 8, 30)  # 剛好橫跨六、七、八三個日曆月

        written = daily_pull.backfill(org_id, since, until)

        self.assertEqual(len(calls), 9, "三個月 x 三層，該是 9 次請求")
        for level in ("campaign", "adset", "ad"):
            level_calls = [c for c in calls if c["level"] == level]
            self.assertEqual(len(level_calls), 3, f"{level} 層三個月該是 3 次請求")
        self.assertEqual(written, 9, "9 次請求各回一列，backfill 回傳值該是總共寫入的列數")
        rows = web.conn.execute(
            "SELECT count(*) AS n FROM meta_entity_spend WHERE ad_account_id = %s", (bp_id,)
        ).fetchone()
        self.assertEqual(rows["n"], 9, "三層 x 三個月，各自不同的 (level, entity_id, date)")


class PagingNeverTruncatesSilentlyTest(unittest.TestCase):
    """守的是資料正確性（票 S0）：撞到頁數上限時回一份殘缺的清單、不出聲，少掉的那幾天
    會讓一則正在贏的廣告看起來像是停止投遞了。"""

    def setUp(self):
        self._orig_fetch_page = graph.fetch_page

    def tearDown(self):
        graph.fetch_page = self._orig_fetch_page

    def test_hitting_the_page_ceiling_raises_instead_of_returning_a_short_list(self):
        def always_one_more_page(url, *, params, headers):
            cursor = int((params or {}).get("after", 0)) + 1
            return {"data": [{"campaign_id": "c1"}], "paging": {
                "next": f"{graph.GRAPH_BASE_URL}/act_1/campaigns?after={cursor}"}}

        graph.fetch_page = always_one_more_page
        with self.assertRaises(graph.GraphError):
            graph._fetch_all_pages(graph.GRAPH_BASE_URL + "/act_1/campaigns", None,
                                   {"Authorization": "Bearer tok"})

    def test_a_walk_that_ends_normally_still_returns_every_page(self):
        pages = [
            {"data": [{"campaign_id": "c1"}], "paging": {
                "next": graph.GRAPH_BASE_URL + "/act_1/campaigns?after=2"}},
            {"data": [{"campaign_id": "c2"}], "paging": {
                "next": graph.GRAPH_BASE_URL + "/act_1/campaigns?after=3"}},
            {"data": [{"campaign_id": "c3"}], "paging": {}},
        ]
        calls = iter(pages)

        def walk(url, *, params, headers):
            return next(calls)

        graph.fetch_page = walk
        items = graph._fetch_all_pages(graph.GRAPH_BASE_URL + "/act_1/campaigns", None,
                                      {"Authorization": "Bearer tok"})
        self.assertEqual([i["campaign_id"] for i in items], ["c1", "c2", "c3"])


# -- 11b. 票 past-ads/02（ADR 0067 §1.9）：fetch_ad_creatives 讀不到的 id 留著，不丟掉 -----

class FetchAdCreativesTest(unittest.TestCase):
    """讀不到的 id 是狀態（None），不是被丟掉的資料；頁面貼文廣告的文字／圖片從
    `object_story_spec.link_data` 退回，不在 `creative.body`/`creative.image_url` 頂層。"""

    def setUp(self):
        self._orig_fetch_page = graph.fetch_page

    def tearDown(self):
        graph.fetch_page = self._orig_fetch_page

    def test_top_level_body_link_data_fallback_and_unreadable_id_in_one_call(self):
        """done-check 5：id A 從頂層取 body／image_url，id B 從 link_data 退回，id C 是
        `{"error": …}` → None，三個 key 都要在。"""

        def fake(url, *, params, headers):
            if url.endswith("/ad-a"):
                return {
                    "name": "廣告 A", "created_time": "2026-05-01T00:00:00+0000",
                    "effective_status": "ACTIVE",
                    "creative": {"body": "頂層文案", "title": "頂層標題",
                                 "image_url": "https://example/a.jpg"},
                }
            if url.endswith("/ad-b"):
                return {
                    "name": "廣告 B", "created_time": "2026-05-02T00:00:00+0000",
                    "effective_status": "PAUSED",
                    "creative": {"object_story_spec": {"link_data": {
                        "message": "連結貼文文案", "name": "連結標題",
                        "picture": "https://example/b.jpg",
                    }}},
                }
            if url.endswith("/ad-c"):
                return {"error": {"message": "Unsupported get request", "code": 100}}
            raise AssertionError(f"沒有對應的 fixture：{url}")

        graph.fetch_page = fake
        result = graph.fetch_ad_creatives("token", ["ad-a", "ad-b", "ad-c"])

        self.assertEqual(set(result), {"ad-a", "ad-b", "ad-c"}, "三個 id 都要留在字典裡")
        self.assertEqual(result["ad-a"]["body"], "頂層文案")
        self.assertEqual(result["ad-a"]["title"], "頂層標題")
        self.assertEqual(result["ad-a"]["image_url"], "https://example/a.jpg")
        self.assertEqual(result["ad-b"]["body"], "連結貼文文案")
        self.assertEqual(result["ad-b"]["title"], "連結標題")
        self.assertEqual(result["ad-b"]["image_url"], "https://example/b.jpg")
        self.assertIsNone(result["ad-c"], "讀不到的 id 是 None，不是被丟掉")

    def test_transport_error_on_any_id_raises_for_the_whole_call(self):
        import httpx

        def fake(url, *, params, headers):
            raise httpx.ConnectError("boom")

        graph.fetch_page = fake
        with self.assertRaises(graph.GraphError):
            graph.fetch_ad_creatives("token", ["ad-a"])


# -- 12. 票 T3c（ADR 0055 §7）：第二層綁定要的兩支新讀取 -------------------------------

class ListAdSetsTest(unittest.TestCase):
    """`list_ad_sets` 比照 `list_campaigns` 走同一套翻頁骨架（`_fetch_all_pages`，
    `PagingNeverTruncatesSilentlyTest` 已經測過那一層，這裡不重測），只驗 `_to_ad_set`
    自己的轉型規則：翻頁真的跟到下一頁、缺 id 的項目整筆跳過、缺名稱補空字串。"""

    def setUp(self):
        self._orig_fetch_page = graph.fetch_page

    def tearDown(self):
        graph.fetch_page = self._orig_fetch_page

    def test_pagination_followed_no_id_dropped_missing_name_blank(self):
        pages = [
            {"data": [
                {"id": "as-1", "name": "組合1", "effective_status": "ACTIVE"},
                {"name": "沒有 id，應該整筆被丟掉"},
            ], "paging": {"next": graph.GRAPH_BASE_URL + "/1/adsets?after=2"}},
            {"data": [{"id": "as-2", "effective_status": "PAUSED"}], "paging": {}},
        ]
        calls = iter(pages)
        graph.fetch_page = lambda url, *, params, headers: next(calls)

        result = graph.list_ad_sets("tok", "1")
        self.assertEqual(result, [
            {"adset_id": "as-1", "name": "組合1", "external_status": "ACTIVE"},
            {"adset_id": "as-2", "name": "", "external_status": "PAUSED"},
        ])


class AdSetMatchUnreachableTest(_MetaDailySpendTestBase):
    """`ad_set_ids_by_exact_name` 連不上 Meta 時的錯誤形狀，比照
    `campaign_ids_by_exact_name`（app/meta/repository.py 該函式的 docstring）：
    `graph.GraphError` 轉成人話 `web.ApiError(502, "meta_unreachable", …)`。"""

    def test_graph_error_surfaces_as_meta_unreachable(self):
        import httpx

        org_id, _ = self._make_org("adset_unreachable")
        meta_repo.save_token(web.conn, org_id, TOKEN)
        web.conn.commit()

        def fail(url, *, params, headers):
            raise httpx.ConnectError("boom")

        graph.fetch_page = fail

        with self.assertRaises(web.ApiError) as caught:
            meta_repo.ad_set_ids_by_exact_name(web.conn, org_id, "camp-1", "組合1")
        self.assertEqual(caught.exception.code, "meta_unreachable")


# -- 13. 票 T5（ADR 0057 §1）：第三層（廣告）綁定要的兩支新讀取 -------------------------

class ListAdsTest(unittest.TestCase):
    """`list_ads` 比照 `list_campaigns`／`list_ad_sets` 走同一套翻頁骨架
    （`_fetch_all_pages`，`PagingNeverTruncatesSilentlyTest` 已經測過那一層，這裡不
    重測），只驗 `_to_ad` 自己的轉型規則：翻頁真的跟到下一頁、缺 id 的項目整筆跳過、
    缺名稱補空字串——跟 `ListAdSetsTest` 逐字同一套斷言，僅深一層。"""

    def setUp(self):
        self._orig_fetch_page = graph.fetch_page

    def tearDown(self):
        graph.fetch_page = self._orig_fetch_page

    def test_pagination_followed_no_id_dropped_missing_name_blank(self):
        pages = [
            {"data": [
                {"id": "ad-1", "name": "單元1", "effective_status": "ACTIVE"},
                {"name": "沒有 id，應該整筆被丟掉"},
            ], "paging": {"next": graph.GRAPH_BASE_URL + "/1/ads?after=2"}},
            {"data": [{"id": "ad-2", "effective_status": "PENDING_REVIEW"}], "paging": {}},
        ]
        calls = iter(pages)
        graph.fetch_page = lambda url, *, params, headers: next(calls)

        result = graph.list_ads("tok", "1")
        self.assertEqual(result, [
            {"ad_id": "ad-1", "name": "單元1", "external_status": "ACTIVE"},
            {"ad_id": "ad-2", "name": "", "external_status": "PENDING_REVIEW"},
        ])


class AdMatchUnreachableTest(_MetaDailySpendTestBase):
    """`ad_ids_by_exact_name` 連不上 Meta 時的錯誤形狀，比照 `AdSetMatchUnreachableTest`：
    `graph.GraphError` 轉成人話 `web.ApiError(502, "meta_unreachable", …)`。"""

    def test_graph_error_surfaces_as_meta_unreachable(self):
        import httpx

        org_id, _ = self._make_org("ad_unreachable")
        meta_repo.save_token(web.conn, org_id, TOKEN)
        web.conn.commit()

        def fail(url, *, params, headers):
            raise httpx.ConnectError("boom")

        graph.fetch_page = fail

        with self.assertRaises(web.ApiError) as caught:
            meta_repo.ad_ids_by_exact_name(web.conn, org_id, "as-1", "單元1")
        self.assertEqual(caught.exception.code, "meta_unreachable")


# -- 14. 票 06：這兩支函式現在自己驗 parent id 的租戶界線，不是只靠呼叫端自律 -------------

class _CrossOrgBindingFixture(_MetaDailySpendTestBase):
    """兩個組織：org_a 有權杖但沒有任何綁定；org_b 有一個真的綁定紀錄（`channel_entity_map`
    一列），external_id 是 org_a 接下來會拿去呼叫的那個 id——org_a 從沒見過它、也沒有任何
    ad_account 曾經配對出它，唯一「知道」它的地方是別的組織的綁定紀錄。"""

    def _bind_for_other_org(self, org_id: str, node_key: str, external_id: str) -> None:
        brand_id = f"brd_{uuid4().hex[:10]}"
        web.conn.execute(
            "INSERT INTO brand (id, org_id, name, status) VALUES (%s, %s, %s, 'active')",
            (brand_id, org_id, "別的組織的品牌"),
        )
        channel_id = schedule_repo.ensure_meta_channel(web.conn, org_id)
        schedule_repo.upsert_binding(
            web.conn, org_id=org_id, brand_id=brand_id, channel_id=channel_id,
            node_key=node_key, node_name_at_bind="別的組織的節點",
            external_id=external_id, external_status="ACTIVE", source_tree_task_id=None,
        )
        web.conn.commit()


class AdSetParentCrossOrgRefusedTest(_CrossOrgBindingFixture):
    """org_b 綁過的活動 id，org_a 直接拿去呼叫 `ad_set_ids_by_exact_name`——refused 在任何
    Meta 呼叫之前：`graph.list_ad_sets` 完全沒被呼叫，不是讓請求出去、指望 Meta 那邊回權限
    錯誤（那樣等於這支函式仍然沒有第二行防線，`docs/contracts/meta.md` 收這張票之前記錄
    的正是這個洞）。"""

    def test_refused_before_any_meta_call(self):
        org_a, _ = self._make_org("cross_org_adset_a")
        org_b, _ = self._make_org("cross_org_adset_b")
        meta_repo.save_token(web.conn, org_a, TOKEN)
        web.conn.commit()
        self._bind_for_other_org(org_b, "1", "camp-owned-by-org-b")

        with mock.patch.object(graph, "list_ad_sets") as fake_list_ad_sets:
            with self.assertRaises(web.ApiError) as caught:
                meta_repo.ad_set_ids_by_exact_name(
                    web.conn, org_a, "camp-owned-by-org-b", "隨便什麼名字"
                )
            self.assertEqual(fake_list_ad_sets.call_count, 0)
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(caught.exception.code, "campaign_not_owned")


class AdParentCrossOrgRefusedTest(_CrossOrgBindingFixture):
    """跟 `AdSetParentCrossOrgRefusedTest` 同一套規矩，深一層：org_b 綁過的廣告組合 id，
    org_a 直接拿去呼叫 `ad_ids_by_exact_name`，一樣要在任何 Meta 呼叫之前被拒絕。"""

    def test_refused_before_any_meta_call(self):
        org_a, _ = self._make_org("cross_org_ad_a")
        org_b, _ = self._make_org("cross_org_ad_b")
        meta_repo.save_token(web.conn, org_a, TOKEN)
        web.conn.commit()
        self._bind_for_other_org(org_b, "1.1", "adset-owned-by-org-b")

        with mock.patch.object(graph, "list_ads") as fake_list_ads:
            with self.assertRaises(web.ApiError) as caught:
                meta_repo.ad_ids_by_exact_name(
                    web.conn, org_a, "adset-owned-by-org-b", "隨便什麼名字"
                )
            self.assertEqual(fake_list_ads.call_count, 0)
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(caught.exception.code, "adset_not_owned")


# -- 15. 票 05（budget-level-mismatch）：`budgets_for_bound_ids` 的租戶界線是正面表列 ----

class BudgetsForBoundIdsTenantBoundaryTest(_CrossOrgBindingFixture):
    """跟前面兩支（`AdSetParentCrossOrgRefusedTest`／`AdParentCrossOrgRefusedTest`）不是
    同一套規則：那兩支是**負面表列**（只擋「記錄成別的組織」，沒人綁過的 id 照樣放行，
    `docs/contracts/meta.md` 明文的已知殘留缺口）。這裡的 `budgets_for_bound_ids` 是**正面
    表列**——只有 `channel_entity_map` 記過是這個組織自己綁的 id 才問 Meta，org_a 從沒
    見過、也沒有任何 ad_account 曾經配對出的 id，即使它完全沒有任何綁定紀錄也不放行
    （比前兩支更嚴的那一半）。"""

    def test_budgets_for_bound_ids_refuses_an_id_owned_by_another_org(self):
        org_a, _ = self._make_org("budgets_cross_a")
        org_b, _ = self._make_org("budgets_cross_b")
        meta_repo.save_token(web.conn, org_a, TOKEN)
        web.conn.commit()
        self._bind_for_other_org(org_b, "1", "camp-owned-by-org-b")

        with mock.patch.object(graph, "fetch_budgets") as fake_fetch_budgets:
            result = meta_repo.budgets_for_bound_ids(web.conn, org_a, ["camp-owned-by-org-b"])
            self.assertEqual(fake_fetch_budgets.call_count, 0)
        self.assertEqual(result, {})

    def test_budgets_for_bound_ids_calls_meta_with_exactly_this_orgs_bound_id(self):
        org_a, _ = self._make_org("budgets_owned_a")
        meta_repo.save_token(web.conn, org_a, TOKEN)
        web.conn.commit()
        self._bind_for_other_org(org_a, "1", "camp-owned-by-org-a")

        with mock.patch.object(graph, "fetch_budgets") as fake_fetch_budgets:
            fake_fetch_budgets.return_value = {
                "camp-owned-by-org-a": {"daily_budget": "500", "lifetime_budget": None}
            }
            result = meta_repo.budgets_for_bound_ids(web.conn, org_a, ["camp-owned-by-org-a"])
        fake_fetch_budgets.assert_called_once_with(TOKEN, ["camp-owned-by-org-a"])
        self.assertEqual(
            result, {"camp-owned-by-org-a": {"daily_budget": "500", "lifetime_budget": None}}
        )


# -- 4. FK 保護：有花費紀錄的帳號不能被刪（T-fk） -------------------------------------

class SpendHistoryOutlivesTheAccountTest(_MetaDailySpendTestBase):
    """`meta_entity_spend` 是花費唯一存在的地方，沒有第二份副本。刪掉一個還有花費列的
    `meta_ad_account`，那些列必須連帶消失不了——見 docs/issues/T-fk-spend-history。"""

    def test_deleting_an_account_with_spend_is_refused(self):
        import psycopg  # module import, not `from ... import`

        org_id, _ = self._make_org("delete_guard")
        bp_id = self._connect_account(org_id, BP_ACCOUNT_ID, "BP AD")
        brand_id = bi_repo.create_brand(
            web.conn, org_id=org_id, name="刪除保護測試品牌", client_name=None, actor="test",
        )["id"]
        self._bind(org_id, brand_id, bp_id)
        graph.fetch_page = _dispatch_insights({BP_ACCOUNT_ID: BP_INSIGHTS_PAGE})
        daily_pull.run_daily_pull(org_id)

        rows_before = self._spend_rows(bp_id)
        self.assertEqual(len(rows_before), 3, "前置：這個帳號要真的有花費紀錄")

        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            web.conn.execute("DELETE FROM meta_ad_account WHERE id = %s", (bp_id,))
        web.conn.rollback()  # required — psycopg leaves the transaction aborted, every later
                             # statement raises InFailedSqlTransaction without this

        rows_after = self._spend_rows(bp_id)
        self.assertEqual(
            [(r["entity_id"], r["spend"]) for r in rows_before],
            [(r["entity_id"], r["spend"]) for r in rows_after],
            "被拒絕的 DELETE 不該動到任何一列花費紀錄",
        )


if __name__ == "__main__":
    unittest.main()
