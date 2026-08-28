"""app/tests/test_ads_history.py — D線票3（GitHub issue #45）：廣告 hub 五卡＋歷期戰績頁。

品牌與產品名一律虛構，絕不使用真實客戶品牌。
"""

import unittest

from fastapi.testclient import TestClient

import app.main as main
from app.ads import performance as ads_perf
from app.ads import reading as ads_reading
from app.ads import repository as ads_repo
from app.ads import routes_common
from app.ads import sync as ads_sync
from app.brand_intelligence import repository as bi_repo
from app.llm.providers import FakeProvider, ProviderResponse, Usage


def _fake(text: str) -> ProviderResponse:
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=200, output_tokens=100),
                            stop_reason="end_turn")

ACTOR = "測試員"


class _BaseHubTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        main.conn.execute("DELETE FROM discovered_campaign")
        main.conn.execute("DELETE FROM app_setting WHERE key IN (%s, %s)",
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

    def _api_cycles(self) -> list:
        """檔期清單 JSON API：`bucket` 就是歷期戰績頁三段（進行中／已結案／已封存）的同一份
        歸段依據，`stage_label`／`days_left` 就是 hub 進行中卡的同一份 `_hub_stage_info`。"""
        resp = self.client.get(f"/api/campaigns/brands/{self.bid}")
        self.assertEqual(resp.status_code, 200)
        return resp.json()["data"]

    def _bucket_of(self, cycle_id: str):
        for item in self._api_cycles():
            if item["id"] == cycle_id:
                return item["bucket"]
        return None

    def _trend_rows(self) -> list:
        """歷期戰績頁跨期趨勢表的同一份資料來源（模板 `{% if trend_rows %}` 才渲染整張表，
        每一格直接印這裡的欄位），沒有對應的 /api 端點，直接呼叫業務函式。"""
        cycles = ads_repo.list_cycles(main.conn, self.bid)
        closed = [c for c in cycles if c["status"] == "CLOSED"]
        return routes_common._history_trend_rows(main.conn, self.bid, closed)


class HubInProgressCardTest(_BaseHubTest):
    def test_single_active_cycle_shows_stage_and_days_left(self):
        cycle_id = self._open_cycle()
        in_progress = [c for c in self._api_cycles() if c["bucket"] == "in_progress"]
        # 剛開的檔期還在 PLANNING，落在五格的第一格「計畫」
        self.assertEqual(in_progress[0]["stage_label"], "計畫")
        # 「剩 N 天」的 N
        self.assertIsNotNone(in_progress[0]["days_left"])
        # 只有這一期進行中，所以沒有第二期可以算進「另有 N 期進行中」
        self.assertEqual([c["id"] for c in in_progress], [cycle_id])

    def test_multiple_active_cycles_show_most_recent_and_link_to_history(self):
        """真正要保住的是 ads_repo.list_cycles 的排序（start_date DESC，最新一期在前）。"""
        self._open_cycle(start_date="2026-06-01")
        newest_id = self._open_cycle(start_date="2026-07-01")
        cycles = self._api_cycles()
        self.assertEqual(cycles[0]["id"], newest_id)

    def test_only_closed_cycle_falls_back_to_empty_state(self):
        """進行中＝非封存且非已結束；只剩已結案檔期時，卡片仍當作沒有進行中處理。"""
        cycle_id = self._open_cycle()
        ads_repo.update_cycle_status(main.conn, self.bid, cycle_id, status="CLOSED", actor=ACTOR)
        items = self._api_cycles()
        # 沒有任何進行中檔期＝hub 回到空狀態（只剩「開新檔期」那顆）
        self.assertEqual([c["id"] for c in items if c["bucket"] == "in_progress"], [])
        self.assertEqual(self._bucket_of(cycle_id), "closed")


class HistoryPageTest(_BaseHubTest):
    def test_three_segments_bucket_cycles_correctly(self):
        in_progress_id = self._open_cycle(start_date="2026-06-01")
        closed_id = self._open_cycle(start_date="2026-05-01")
        ads_repo.update_cycle_status(main.conn, self.bid, closed_id, status="CLOSED", actor=ACTOR)
        archived_id = self._open_cycle(start_date="2026-04-01")
        ads_repo.set_cycle_archived(main.conn, self.bid, archived_id, archived=True, actor=ACTOR)

        buckets = {c["id"]: c["bucket"] for c in self._api_cycles()}
        self.assertEqual(buckets, {in_progress_id: "in_progress", closed_id: "closed",
                                   archived_id: "archived"})

    def test_restore_and_permanent_delete_from_history_page(self):
        """行為與原本首頁封存收合區完全一致——恢復切換 archived、永久刪除需先封存＋確認名稱。"""
        cycle_id = self._open_cycle()
        label = ads_repo.get_cycle(main.conn, self.bid, cycle_id)
        label = f"{label['start_date']} ～ {label['end_date']}"

        self.client.post(f"/api/campaigns/brands/{self.bid}/{cycle_id}/archive")
        self.assertEqual(ads_repo.get_cycle(main.conn, self.bid, cycle_id)["archived"], 1)
        self.assertEqual(self._bucket_of(cycle_id), "archived")

        self.client.post(f"/api/campaigns/brands/{self.bid}/{cycle_id}/archive")
        self.assertEqual(ads_repo.get_cycle(main.conn, self.bid, cycle_id)["archived"], 0)
        self.assertEqual(self._bucket_of(cycle_id), "in_progress")

        self.client.post(f"/api/campaigns/brands/{self.bid}/{cycle_id}/archive")
        resp = self.client.post(f"/api/campaigns/brands/{self.bid}/{cycle_id}/delete",
                                json={"confirm_name": label})
        self.assertEqual(resp.status_code, 204)
        self.assertIsNone(ads_repo.get_cycle(main.conn, self.bid, cycle_id))




class HistoryTrendTableTest(_BaseHubTest):
    """跨期趨勢表（GitHub issue #63，決策 0039 第 12 點）：只列已結案檔期，複用 hub 既有
    判讀摘要邏輯，算不出的顯示「算不出」不補 0（鐵則 16）。"""

    def test_zero_closed_cycles_does_not_render_table(self):
        self._open_cycle()  # 只有進行中檔期，沒有任何已結案期
        self.assertEqual(self._trend_rows(), [])  # 空清單＝整張跨期趨勢表不渲染

    def test_unjudged_closed_cycle_does_not_render_table(self):
        """已結案但沒判讀過（原則 16：拿不到就不要放，不放假資料或 0 佔位）。"""
        cycle_id = self._open_cycle()
        ads_repo.update_cycle_status(main.conn, self.bid, cycle_id, status="CLOSED", actor=ACTOR)
        self.assertEqual(self._trend_rows(), [])  # 空清單＝整張跨期趨勢表不渲染

    def test_single_closed_period_shows_data_but_no_vs_previous_arrow(self):
        cycle_id = self._open_cycle(start_date="2026-01-01")
        self._judge_closed(cycle_id, revenue=20000)  # roas = 20000/10000 = 2.0
        rows = self._trend_rows()
        self.assertEqual(len(rows), 1)  # 非空清單＝跨期趨勢表有渲染
        self.assertEqual("{:.2f} 倍".format(rows[0]["roas"]), "2.00 倍")
        # 只有一期，沒有相鄰上一期可比，不該出現任何漲跌箭頭
        self.assertIsNone(rows[0]["vs_previous"])

    def test_no_revenue_period_shows_roas_cannot_compute(self):
        cycle_id = self._open_cycle()
        self._judge_closed(cycle_id, revenue=None)
        # 模板：roas is none 的那一格印「算不出」
        self.assertIsNone(self._trend_rows()[0]["roas"])

    def test_three_periods_compare_against_adjacent_closed_period(self):
        oldest = self._open_cycle(start_date="2026-01-01")
        middle = self._open_cycle(start_date="2026-02-01")
        newest = self._open_cycle(start_date="2026-03-01")
        self._judge_closed(oldest, revenue=20000)  # roas 2.0
        self._judge_closed(middle, revenue=40000)  # roas 4.0 → 比上一期（oldest）漲
        self._judge_closed(newest, revenue=10000)  # roas 1.0 → 比上一期（middle）跌

        rows = {row["id"]: row for row in self._trend_rows()}

        def _row(cycle_id):
            self.assertIn(cycle_id, rows, f"trend row for {cycle_id} not found")
            return rows[cycle_id]["vs_previous"]

        self.assertEqual(_row(newest), "▼")
        self.assertEqual(_row(middle), "▲")
        self.assertNotIn(_row(oldest), ("▲", "▼"))


if __name__ == "__main__":
    unittest.main()
