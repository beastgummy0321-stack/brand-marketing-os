# -*- coding: utf-8 -*-
"""app/tests/test_ads_history.py — D線票3（GitHub issue #45）：廣告 hub 五卡＋歷期戰績頁。

容量腳本（票 1）對這頁的用法跟 #44 不同：hub 五卡有 3 張是 `_components/card.html` 的
macro 呼叫，capacity_check 靜態讀原始模板檔看不到巨集展開後的 <a class="card menu-card">
（macro 定義在別的檔案），對這種頁面要吃 check_file() 會直接漏算成 1 張卡。這裡改用
capacity_check.check_html() 餵「實際渲染後」的回應文字，才是這頁真正的卡片／導覽連結數。

品牌與產品名一律虛構，絕不使用真實客戶品牌。
"""

import atexit
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_history_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import meta_api  # noqa: E402
from app.ads import performance as ads_perf  # noqa: E402
from app.ads import reading as ads_reading  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.ads import sync as ads_sync  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import settings as coresettings  # noqa: E402
from app.llm.providers import FakeProvider, ProviderResponse, Usage  # noqa: E402
from app.tools import capacity_check as cc  # noqa: E402



def _fake(text: str) -> ProviderResponse:
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=200, output_tokens=100),
                            stop_reason="end_turn")

ACTOR = "測試員"


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)


class _BaseHubTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        main.conn.execute("DELETE FROM discovered_campaign")
        main.conn.execute("DELETE FROM app_setting WHERE key IN (?, ?)",
                          (ads_sync.ACCOUNT_SETTING, ads_sync.TOKEN_SETTING))
        main.conn.commit()
        self.brand = bi_repo.create_brand(main.conn, name=f"虛構晨光咖啡{self.id()[-6:]}",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]

    def _open_cycle(self, **overrides):
        start_date = overrides.get("start_date")
        if start_date:
            cycle = ads_repo.create_cycle(
                main.conn, self.bid, product_ids=[], pain_value=10000,
                objective=overrides.get("objective", "sales"), actor=ACTOR,
                start_date=start_date,
            )
            return cycle["id"]
        resp = self.client.post(
            f"/api/campaigns/{self.bid}",
            json={"product_ids": [], "budget": 10000,
                  "objective": overrides.get("objective", "sales")},
        )
        self.assertEqual(resp.status_code, 200)
        return resp.json()["cycle_id"]

    def _judge_closed(self, cycle_id, *, spend=10000, impressions=20000, clicks=400,
                      conversions=5, revenue=None):
        """把一期灌進成效資料、跑一次判讀、直接標成已結案（票 F4：跨期趨勢表要吃到判讀
        快照才會有 ROAS／賺賠／成色可顯示，比照 test_ads_home_console.py 既有寫法）。
        revenue 省略時代表這期完全沒收到營收資料，ROAS 應算不出。"""
        orig = ads_reading.PROVIDER
        ads_reading.PROVIDER = FakeProvider(response=_fake('{"text": "判讀說明"}'))
        try:
            values = {"spend": spend, "impressions": impressions, "clicks": clicks,
                     "conversions": conversions}
            if revenue is not None:
                values["revenue"] = revenue
            ads_perf.import_manual(main.conn, self.bid, cycle_id, values, actor=ACTOR)
            ok, err = ads_reading.run(main.conn, self.bid, cycle_id, ACTOR)
            self.assertTrue(ok, err)
        finally:
            ads_reading.PROVIDER = orig
        ads_repo.update_cycle_status(main.conn, self.bid, cycle_id, status="CLOSED", actor=ACTOR)


class HubCapacityTest(_BaseHubTest):
    """驗收條件：廣告首頁容量腳本通過（決策 0029／0033）。修憲落地 V3 把 hub 遷成 B｜工作台式
    單欄清單後，原本的五張固定卡片牆拿掉：「進行中檔期」「最近結案的檔期」兩塊摘要改用
    `kind=content`（順序閱讀的內容卡，決策 0033 §20.1 規則 1 不計入主欄 ≤5 上限），所以卡片數
    不再固定是 5，而是 0（沒有任何 kind=entry 功能入口卡）。"""

    def test_hub_has_zero_entry_cards_within_capacity(self):
        resp = self.client.get(f"/brands/{self.bid}/ads")
        counts = cc.check_html(resp.text)
        self.assertEqual(counts["card_count"], 0)
        self.assertLessEqual(counts["nav_link_count"], cc.NAV_LINK_LIMIT)
        self.assertEqual(counts["illegal_detail_count"], 0)
        self.assertEqual(cc.violations("ads_home", counts), [])

    def test_hub_stays_within_capacity_with_an_active_cycle(self):
        """有進行中檔期時多一張「進行中檔期」內容卡（kind=content），仍不計入主欄 ≤5 上限。"""
        self._open_cycle()
        resp = self.client.get(f"/brands/{self.bid}/ads")
        counts = cc.check_html(resp.text)
        self.assertEqual(counts["card_count"], 0)
        self.assertEqual(cc.violations("ads_home", counts), [])


class HubInProgressCardTest(_BaseHubTest):
    def test_empty_state_offers_new_cycle_as_primary_action(self):
        resp = self.client.get(f"/brands/{self.bid}/ads")
        self.assertIn("還沒有跑過任何一期廣告", resp.text)
        self.assertIn(f'href="/brands/{self.bid}/ads/new"', resp.text)

    def test_single_active_cycle_shows_stage_and_days_left(self):
        cycle_id = self._open_cycle()
        resp = self.client.get(f"/brands/{self.bid}/ads")
        # 剛開的檔期還在 PLANNING，落在五格的第一格「計畫」
        self.assertIn("計畫", resp.text)
        self.assertIn("剩", resp.text)
        self.assertIn(f'href="/brands/{self.bid}/ads/{cycle_id}"', resp.text)
        # 只有一期進行中，不該出現「另有」這行
        self.assertNotIn("另有", resp.text)

    def test_multiple_active_cycles_show_most_recent_and_link_to_history(self):
        self._open_cycle(start_date="2026-06-01")
        newest_id = self._open_cycle(start_date="2026-07-01")
        resp = self.client.get(f"/brands/{self.bid}/ads")
        self.assertIn(f'href="/brands/{self.bid}/ads/{newest_id}"', resp.text)
        self.assertIn("另有 1 期進行中", resp.text)
        self.assertIn(f'href="/brands/{self.bid}/ads/history"', resp.text)

    def test_only_closed_cycle_falls_back_to_empty_state(self):
        """進行中＝非封存且非已結束；只剩已結案檔期時，卡片仍當作沒有進行中處理。"""
        cycle_id = self._open_cycle()
        ads_repo.update_cycle_status(main.conn, self.bid, cycle_id, status="CLOSED", actor=ACTOR)
        resp = self.client.get(f"/brands/{self.bid}/ads")
        self.assertIn(f'href="/brands/{self.bid}/ads/new"', resp.text)
        self.assertNotIn(f'href="/brands/{self.bid}/ads/{cycle_id}"', resp.text)


class HubSyncAndClaimsMovedTest(_BaseHubTest):
    """Meta 同步按鈕與待認領提醒遷入 /ads/connections（#44），hub 不留操作列。"""

    def test_meta_sync_button_not_on_hub(self):
        coresettings.set_setting(main.conn, ads_sync.ACCOUNT_SETTING, "act_1234567890")
        coresettings.set_setting(main.conn, ads_sync.TOKEN_SETTING, "fake-token")
        resp = self.client.get(f"/brands/{self.bid}/ads")
        self.assertNotIn(f'action="/brands/{self.bid}/ads/sync"', resp.text)

    def test_pending_claims_banner_not_on_hub_but_present_on_connections(self):
        coresettings.set_setting(main.conn, ads_sync.ACCOUNT_SETTING, "act_1234567890")
        coresettings.set_setting(main.conn, ads_sync.TOKEN_SETTING, "fake-token")
        client = meta_api.FakeMetaClient(campaigns=[
            meta_api.Campaign(campaign_id="999", name="某個沒歸屬的活動",
                              objective="OUTCOME_SALES", effective_status="ACTIVE")])
        ads_sync.sync_account(main.conn, ACTOR, client=client, today="2026-07-31")

        hub = self.client.get(f"/brands/{self.bid}/ads")
        self.assertNotIn("還沒確認是不是這個品牌的", hub.text)

        connections = self.client.get(f"/brands/{self.bid}/ads/connections")
        self.assertIn("還沒確認是不是這個品牌的", connections.text)


class HistoryPageTest(_BaseHubTest):
    def test_empty_state_when_no_cycles_at_all(self):
        resp = self.client.get(f"/brands/{self.bid}/ads/history")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("還沒有跑過任何一期廣告", resp.text)
        self.assertIn(f'href="/brands/{self.bid}/ads/new"', resp.text)

    def test_breadcrumb_reaches_history_from_hub(self):
        resp = self.client.get(f"/brands/{self.bid}/ads/history")
        self.assertIn("歷期戰績", resp.text)
        self.assertIn(f'href="/brands/{self.bid}/ads"', resp.text)

    def test_three_segments_bucket_cycles_correctly(self):
        in_progress_id = self._open_cycle(start_date="2026-06-01")
        closed_id = self._open_cycle(start_date="2026-05-01")
        ads_repo.update_cycle_status(main.conn, self.bid, closed_id, status="CLOSED", actor=ACTOR)
        archived_id = self._open_cycle(start_date="2026-04-01")
        ads_repo.set_cycle_archived(main.conn, self.bid, archived_id, archived=True, actor=ACTOR)

        resp = self.client.get(f"/brands/{self.bid}/ads/history")
        self.assertIn("進行中（1）", resp.text)
        self.assertIn("已結案（1）", resp.text)
        self.assertIn("已封存檔期（1）", resp.text)
        for cid in (in_progress_id, closed_id, archived_id):
            self.assertIn(f'href="/brands/{self.bid}/ads/{cid}"', resp.text)

    def test_restore_and_permanent_delete_from_history_page(self):
        """行為與原本首頁封存收合區完全一致——恢復切換 archived、永久刪除需先封存＋確認名稱。"""
        cycle_id = self._open_cycle()
        label = ads_repo.get_cycle(main.conn, self.bid, cycle_id)
        label = f"{label['start_date']} ～ {label['end_date']}"

        self.client.post(f"/api/campaigns/brands/{self.bid}/{cycle_id}/archive")
        self.assertEqual(ads_repo.get_cycle(main.conn, self.bid, cycle_id)["archived"], 1)
        history = self.client.get(f"/brands/{self.bid}/ads/history")
        self.assertIn("已封存檔期（1）", history.text)

        self.client.post(f"/api/campaigns/brands/{self.bid}/{cycle_id}/archive")
        self.assertEqual(ads_repo.get_cycle(main.conn, self.bid, cycle_id)["archived"], 0)
        history = self.client.get(f"/brands/{self.bid}/ads/history")
        self.assertIn("進行中（1）", history.text)

        self.client.post(f"/api/campaigns/brands/{self.bid}/{cycle_id}/archive")
        resp = self.client.post(f"/api/campaigns/brands/{self.bid}/{cycle_id}/delete",
                                json={"confirm_name": label})
        self.assertEqual(resp.status_code, 204)
        self.assertIsNone(ads_repo.get_cycle(main.conn, self.bid, cycle_id))

    def test_capacity_script_passes_on_history_page(self):
        resp = self.client.get(f"/brands/{self.bid}/ads/history")
        counts = cc.check_html(resp.text)
        self.assertEqual(cc.violations("ads_history", counts), [])


class HistoryTrendTableTest(_BaseHubTest):
    """跨期趨勢表（GitHub issue #63，決策 0039 第 12 點）：只列已結案檔期，複用 hub 既有
    判讀摘要邏輯，算不出的顯示「算不出」不補 0（鐵則 16）。"""

    def test_zero_closed_cycles_does_not_render_table(self):
        self._open_cycle()  # 只有進行中檔期，沒有任何已結案期
        resp = self.client.get(f"/brands/{self.bid}/ads/history")
        self.assertNotIn("跨期趨勢", resp.text)

    def test_unjudged_closed_cycle_does_not_render_table(self):
        """已結案但沒判讀過（原則 16：拿不到就不要放，不放假資料或 0 佔位）。"""
        cycle_id = self._open_cycle()
        ads_repo.update_cycle_status(main.conn, self.bid, cycle_id, status="CLOSED", actor=ACTOR)
        resp = self.client.get(f"/brands/{self.bid}/ads/history")
        self.assertNotIn("跨期趨勢", resp.text)

    def test_single_closed_period_shows_data_but_no_vs_previous_arrow(self):
        cycle_id = self._open_cycle(start_date="2026-01-01")
        self._judge_closed(cycle_id, revenue=20000)  # roas = 20000/10000 = 2.0
        resp = self.client.get(f"/brands/{self.bid}/ads/history")
        self.assertIn("跨期趨勢", resp.text)
        self.assertIn("2.00 倍", resp.text)
        # 只有一期，沒有相鄰上一期可比，不該出現任何漲跌箭頭
        self.assertNotIn("▲", resp.text)
        self.assertNotIn("▼", resp.text)

    def test_no_revenue_period_shows_roas_cannot_compute(self):
        cycle_id = self._open_cycle()
        self._judge_closed(cycle_id, revenue=None)
        resp = self.client.get(f"/brands/{self.bid}/ads/history")
        self.assertIn("算不出", resp.text)

    def test_three_periods_compare_against_adjacent_closed_period(self):
        oldest = self._open_cycle(start_date="2026-01-01")
        middle = self._open_cycle(start_date="2026-02-01")
        newest = self._open_cycle(start_date="2026-03-01")
        self._judge_closed(oldest, revenue=20000)  # roas 2.0
        self._judge_closed(middle, revenue=40000)  # roas 4.0 → 比上一期（oldest）漲
        self._judge_closed(newest, revenue=10000)  # roas 1.0 → 比上一期（middle）跌

        resp = self.client.get(f"/brands/{self.bid}/ads/history")
        trend_section = resp.text[resp.text.index("跨期趨勢"):resp.text.index("進行中（")]

        def _row(cycle_id):
            match = re.search(
                rf'<a class="link" href="/brands/{self.bid}/ads/{cycle_id}">.*?</tr>',
                trend_section, re.S)
            self.assertIsNotNone(match, f"trend row for {cycle_id} not found")
            return match.group(0)

        self.assertIn("▼", _row(newest))
        self.assertIn("▲", _row(middle))
        self.assertNotIn("▲", _row(oldest))
        self.assertNotIn("▼", _row(oldest))

    def test_capacity_script_passes_with_judged_history(self):
        cycle_id = self._open_cycle()
        self._judge_closed(cycle_id, revenue=20000)
        resp = self.client.get(f"/brands/{self.bid}/ads/history")
        counts = cc.check_html(resp.text)
        self.assertEqual(cc.violations("ads_history", counts), [])


if __name__ == "__main__":
    unittest.main()
