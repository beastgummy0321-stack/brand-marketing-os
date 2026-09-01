"""app/tests/test_meta_daily_spend.py — 票 05／S1：每日拉 Meta 花費並顯示，三層都拉。

只寫 docs/workflow-diet.md 第 4 條允許的四類（金額、租戶隔離、API 契約、資料正確性；
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
        with self.assertRaises(graph.GraphError) as caught:
            daily_pull.run_daily_pull(org_id)
        self.assertIn(BP_ACCOUNT_ID, str(caught.exception), "錯誤訊息要指名是哪個帳號失敗")

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
            return {"data": [{"campaign_id": "c1"}], "paging": {"next": "https://example/next"}}

        graph.fetch_page = always_one_more_page
        with self.assertRaises(graph.GraphError):
            graph._fetch_all_pages("https://example/first", None, {})

    def test_a_walk_that_ends_normally_still_returns_every_page(self):
        pages = [
            {"data": [{"campaign_id": "c1"}], "paging": {"next": "https://example/2"}},
            {"data": [{"campaign_id": "c2"}], "paging": {"next": "https://example/3"}},
            {"data": [{"campaign_id": "c3"}], "paging": {}},
        ]
        calls = iter(pages)

        def walk(url, *, params, headers):
            return next(calls)

        graph.fetch_page = walk
        items = graph._fetch_all_pages("https://example/1", None, {})
        self.assertEqual([i["campaign_id"] for i in items], ["c1", "c2", "c3"])


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
