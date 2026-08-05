# -*- coding: utf-8 -*-
"""app/tests/test_ads_performance_split.py — D線票5（GitHub issue #47）：成效頁拆層＋資料操作子頁。

驗收重點：
1. 成效頁上層剛好五塊（判讀結論／算出來的數字／分開看每個產品／下一期就這樣開／本期判讀可信度），
   容量腳本通過（卡片數、非法展開元件數、單卡文字數）。
2. 通路對照與判讀可信度的詳情內只有唯讀摘要／燈號；蝦皮碼與對帳自答的輸入表單只存在於
   資料操作子頁，不得兩處都放。
3. 資料操作子頁含 CSV／手動填／蝦皮碼／對帳／營收校準，麵包屑可點回成效頁。
4. 舊網址 `/revenue-reconcile` 302 轉址到資料操作子頁。
5. 拆層前後：同一組 fixture 的判讀結論／成色標籤／可信度數值必須完全相同（本票不改判讀邏輯，
   只驗證版面搬動沒有連帶改到這些數字）。
6. 模擬檔期的「產生模擬成效」按鈕維持原位；資料操作子頁不重複提供匯入表單。
7. 對帳、蝦皮碼、CSV 匯入、手動填數字四個表單送出後留在資料操作子頁，不被踢回成效頁
   （獨立驗證抓到的缺陷修正）。

品牌與產品名一律虛構，全程 FakeProvider，不發任何真實網路請求。
"""

import atexit
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_perf_split_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import performance as perf  # noqa: E402
from app.ads import reading  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.llm.providers import FakeProvider, ProviderResponse, Usage  # noqa: E402
from app.orders import channel as orders_channel  # noqa: E402
from app.tools import capacity_check as cc  # noqa: E402

main.reopen_connection()


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"


def _fake(text: str) -> ProviderResponse:
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=200, output_tokens=100),
                            stop_reason="end_turn")


class _JudgedCycleTest(unittest.TestCase):
    """一個已判讀、有下一期草案、非模擬的真實檔期——五塊在這個狀態下應該同時全部出現。"""

    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨露茶行",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]
        self.product = bi_repo.create_product(main.conn, self.bid, name="虛構烏龍茶包",
                                              actor=ACTOR)["id"]
        bi_repo.save_product_economics(main.conn, self.bid, self.product, selling_price=1000,
                                       unit_variable_cost=400, currency="TWD",
                                       confirmed_by=ACTOR, actor=ACTOR)
        resp = self.client.post(f"/brands/{self.bid}/ads/new",
                                data={"product_ids": [self.product],
                                      "custom_amount": "10000", "objective": "sales"},
                                follow_redirects=False)
        self.cycle_id = resp.headers["location"].split("/ads/")[1].split("?")[0]
        self._orig = reading.PROVIDER
        # 判讀說明刻意用極短字串：AI 自然語言長度不受本票的版面容量規則管（決策 0026
        # §20.1 規則 4 修訂後僅約束主動推播訊息），但容量腳本目前不分卡片種類、一律計數，
        # 這裡用短字串讓「判讀結論」卡的卡面文字可驗證地落在單卡上限內，不代表正式產品
        # 會限制 AI 說明的長度。
        reading.PROVIDER = FakeProvider(response=_fake('{"text": "加碼"}'))
        perf.import_manual(main.conn, self.bid, self.cycle_id,
                           {"spend": 10000, "impressions": 20000, "clicks": 400,
                            "conversions": 10, "revenue": 40000}, actor=ACTOR)
        # 現有匯入路徑（CSV／手動／模擬）都不分產品寫回 performance_snapshot.product_id
        # （這欄位早就存在 schema，只是還沒有任何呼叫端填它——見 test_ads_reading.py
        # 的 test_says_it_cannot_split_by_product_when_data_is_aggregate）。這裡直接補一筆
        # 更新，模擬「這筆成效資料查得出是哪個產品」的情境，才能驗到「③分開看每個產品」
        # 這塊——零 migration，只是測試資料層面補一個既有欄位的值。
        snapshot_id = perf.list_snapshots(main.conn, self.bid, self.cycle_id)[0]["id"]
        main.conn.execute("UPDATE performance_snapshot SET product_id = ? WHERE id = ?",
                          (self.product, snapshot_id))
        main.conn.commit()
        ok, err = reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        assert ok, err

    def tearDown(self):
        reading.PROVIDER = self._orig

    def _perf(self):
        return self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/performance")

    def _data(self):
        return self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/performance/data")


class CapacityTest(_JudgedCycleTest):
    """驗收條件：成效頁上層剛好五塊，容量腳本通過。"""

    def test_performance_page_has_exactly_five_cards_and_passes_capacity(self):
        page = self._perf()
        self.assertEqual(page.status_code, 200)
        counts = cc.check_html(page.text)
        self.assertEqual(counts["card_count"], 5)
        self.assertEqual(counts["illegal_detail_count"], 0)
        self.assertEqual(cc.violations("ads_performance", counts), [])

    def test_data_subpage_stays_within_card_limit_and_uses_legal_details(self):
        page = self._data()
        self.assertEqual(page.status_code, 200)
        counts = cc.check_html(page.text)
        self.assertLessEqual(counts["card_count"], cc.CARD_LIMIT)
        self.assertEqual(counts["illegal_detail_count"], 0)


class FormsOnlyOnDataSubpageTest(_JudgedCycleTest):
    """驗收條件：蝦皮碼與對帳的輸入表單只存在於資料操作子頁；通路對照與判讀可信度的
    詳情內只有唯讀摘要／燈號。兩邊各有斷言。"""

    def test_shopee_code_form_absent_from_performance_page(self):
        page = self._perf().text
        self.assertNotIn('name="code"', page)
        self.assertNotIn('id="shopee_code_input"', page)

    def test_shopee_code_form_present_on_data_subpage(self):
        page = self._data().text
        self.assertIn('id="shopee_code_input"', page)
        self.assertIn(f'/brands/{self.bid}/ads/{self.cycle_id}/performance/shopee-code', page)

    def test_reconcile_self_answer_form_absent_from_performance_page(self):
        page = self._perf().text
        self.assertNotIn('name="budget_same"', page)
        self.assertNotIn('name="other_campaign_running"', page)

    def test_reconcile_self_answer_form_present_on_data_subpage(self):
        page = self._data().text
        self.assertIn('name="budget_same"', page)
        self.assertIn(f'/brands/{self.bid}/ads/{self.cycle_id}/performance/reconcile', page)

    def test_csv_and_manual_forms_absent_from_performance_page(self):
        page = self._perf().text
        self.assertNotIn("匯入 Meta 匯出的報表", page)
        self.assertNotIn('id="csv_file"', page)
        self.assertNotIn('id="spend"', page)

    def test_csv_and_manual_forms_present_on_data_subpage(self):
        page = self._data().text
        self.assertIn('id="csv_file"', page)
        self.assertIn('id="spend"', page)

    def test_channel_detail_on_performance_page_is_readonly(self):
        """通路對照詳情：只留唯讀摘要／燈號，沒有表單。"""
        page = self._perf().text
        self.assertIn("通路對照（蝦皮／藥局）", page)
        self.assertNotIn("<form", page[page.index("通路對照（蝦皮／藥局）"):
                                        page.index("通路對照（蝦皮／藥局）") + 2000])

    def test_confidence_detail_on_performance_page_is_readonly(self):
        """判讀可信度詳情：只留唯讀摘要，沒有自答表單。"""
        page = self._perf().text
        self.assertIn("本期判讀可信度", page)
        tail = page[page.index("本期判讀可信度"):]
        self.assertNotIn("<form", tail)


class RevenueReconcileRedirectTest(_JudgedCycleTest):
    def test_old_url_redirects_302_to_data_subpage(self):
        resp = self.client.get(
            f"/brands/{self.bid}/ads/{self.cycle_id}/revenue-reconcile",
            follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers["location"].startswith(
            f"/brands/{self.bid}/ads/{self.cycle_id}/performance/data"))

    def test_calibrate_action_still_works_and_data_subpage_shows_it(self):
        resp = self.client.post(
            f"/brands/{self.bid}/ads/{self.cycle_id}/revenue-reconcile/calibrate",
            follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertTrue(resp.headers["location"].startswith(
            f"/brands/{self.bid}/ads/{self.cycle_id}/performance/data"))


class DataOpsFormRedirectTest(unittest.TestCase):
    """獨立驗證抓到的缺陷（#47 缺陷 2）：對帳、蝦皮碼、CSV 匯入、手動填數字四個表單送出後
    要留在資料操作子頁（/performance/data），不能被 back 參數踢回成效頁。"""

    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨露烘焙",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]
        resp = self.client.post(f"/brands/{self.bid}/ads/new",
                                data={"custom_amount": "10000", "objective": "sales"},
                                follow_redirects=False)
        self.cycle_id = resp.headers["location"].split("/ads/")[1].split("?")[0]

    def _data_path(self):
        return f"/brands/{self.bid}/ads/{self.cycle_id}/performance/data"

    def _assert_redirects_to_data_subpage(self, resp):
        self.assertTrue(300 <= resp.status_code < 400, resp.status_code)
        self.assertTrue(resp.headers["location"].startswith(self._data_path()),
                        resp.headers["location"])

    def test_reconcile_redirects_to_data_subpage(self):
        resp = self.client.post(
            f"/brands/{self.bid}/ads/{self.cycle_id}/performance/reconcile",
            data={}, follow_redirects=False)
        self._assert_redirects_to_data_subpage(resp)

    def test_shopee_code_redirects_to_data_subpage(self):
        resp = self.client.post(
            f"/brands/{self.bid}/ads/{self.cycle_id}/performance/shopee-code",
            data={"code": "SHOP0802"}, follow_redirects=False)
        self._assert_redirects_to_data_subpage(resp)

    def test_csv_import_redirects_to_data_subpage(self):
        resp = self.client.post(
            f"/brands/{self.bid}/ads/{self.cycle_id}/performance/csv",
            data={"csv_text": ""}, follow_redirects=False)
        self._assert_redirects_to_data_subpage(resp)

    def test_manual_entry_redirects_to_data_subpage(self):
        resp = self.client.post(
            f"/brands/{self.bid}/ads/{self.cycle_id}/performance/manual",
            data={"spend": "5000"}, follow_redirects=False)
        self._assert_redirects_to_data_subpage(resp)


class DataSubpageBreadcrumbTest(_JudgedCycleTest):
    def test_breadcrumb_links_back_to_performance_page(self):
        page = self._data().text
        self.assertIn(f'href="/brands/{self.bid}/ads/{self.cycle_id}/performance"', page)

    def test_calibration_badge_is_a_short_label_not_a_sentence(self):
        """瀏覽器驗收實測：badge 是 nowrap 標籤，塞整句話會在 375 視口撐爆版面（+26px）。

        badge 只放短標籤，長說明另起一行（人話說明本身仍要出現在頁面上，不能為了版面把資訊吃掉）。
        """
        page = self._data().text
        badge_texts = re.findall(r'<span class="badge badge-\w+">([^<]*)</span>', page)
        self.assertTrue(badge_texts, "頁面上應該有成色 badge")
        for text in badge_texts:
            self.assertLessEqual(len(text.strip()), 8, f"badge 文字過長會撐爆 375 視口：{text}")
        self.assertIn("暫用保守預設", page)  # 說明句仍在，只是不在 badge 裡

    def test_data_subpage_covers_all_five_operations(self):
        """驗收條件：資料操作子頁含匯入 CSV、手動填數字、對帳、蝦皮碼、營收校準。"""
        page = self._data().text
        self.assertIn('id="csv_file"', page)          # 匯入 CSV
        self.assertIn('id="spend"', page)              # 手動填數字
        self.assertIn('name="budget_same"', page)      # 對帳
        self.assertIn('id="shopee_code_input"', page)  # 蝦皮碼
        self.assertIn("營收校準", page)                  # 營收校準（併入，見決策 0029 第 10 點）


class FixtureParityTest(_JudgedCycleTest):
    """本票只搬版面：同一組 fixture 的判讀結論、成色標籤、可信度數值要跟拆層前完全一致。"""

    def test_reading_verdict_and_grade_unchanged(self):
        page = self._perf().text
        self.assertIn("這期該怎麼看", page)
        self.assertIn("可以考慮加碼", page)  # scale_candidate 的人話標籤（reading.STATUS_LABELS）
        self.assertIn("Meta 視角判讀", page)  # 懶人模式資料成色（決策 0025 第 6 點）

    def test_confidence_defaults_to_trustworthy_without_reconcile_findings(self):
        page = self._perf().text
        self.assertIn("本期判讀可信度", page)
        self.assertIn("可信", page)

    def test_next_cycle_draft_numbers_unchanged(self):
        page = self._perf().text
        self.assertIn("下一期就這樣開", page)
        self.assertIn("10,000", page)  # 這期預算
        self.assertIn("12,000", page)  # 建議下期預算（scale_candidate 上限 20%）


class SimulationUnaffectedTest(unittest.TestCase):
    """驗收條件：模擬檔期的「產生模擬成效」按鈕維持現狀不動，資料操作子頁不重複提供匯入表單。"""

    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨露咖啡",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]
        resp = self.client.post(f"/brands/{self.bid}/ads/new",
                                data={"custom_amount": "10000", "objective": "sales",
                                      "mode": "simulation"}, follow_redirects=False)
        self.cycle_id = resp.headers["location"].split("/ads/")[1].split("?")[0]

    def test_simulate_button_stays_on_performance_page(self):
        page = self.client.get(
            f"/brands/{self.bid}/ads/{self.cycle_id}/performance").text
        self.assertIn("產生模擬成效", page)
        self.assertIn(f'/brands/{self.bid}/ads/{self.cycle_id}/performance/simulate', page)

    def test_data_subpage_does_not_duplicate_the_simulate_button(self):
        """子頁可以用一句話提示按鈕在成效頁，但不得重複放出那個表單／按鈕本體。"""
        page = self.client.get(
            f"/brands/{self.bid}/ads/{self.cycle_id}/performance/data").text
        self.assertNotIn(f'action="/brands/{self.bid}/ads/{self.cycle_id}/performance/simulate"',
                         page)
        self.assertNotIn("匯入 Meta 匯出的報表", page)


class InsufficientDataStillGradesTest(unittest.TestCase):
    """驗收條件：資料不足時仍給結論並標成色，不擋路、不顯示假數字。"""

    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨露花藝",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]
        resp = self.client.post(f"/brands/{self.bid}/ads/new",
                                data={"custom_amount": "10000", "objective": "sales"},
                                follow_redirects=False)
        self.cycle_id = resp.headers["location"].split("/ads/")[1].split("?")[0]
        perf.import_manual(main.conn, self.bid, self.cycle_id, {"spend": 3000}, actor=ACTOR)

    def test_performance_page_says_insufficient_not_zero(self):
        page = self.client.get(
            f"/brands/{self.bid}/ads/{self.cycle_id}/performance").text
        self.assertIn("資料不足", page)

    def test_data_subpage_shows_accumulated_raw_number(self):
        page = self.client.get(
            f"/brands/{self.bid}/ads/{self.cycle_id}/performance/data").text
        self.assertIn("目前累積的原始數字", page)


class ShopeeCodeReadonlyGlanceTest(_JudgedCycleTest):
    """已記錄的蝦皮碼要在成效頁的通路對照詳情內看得到唯讀摘要（不是表單）。"""

    def test_recorded_code_shows_up_readonly_on_performance_page(self):
        orders_channel.set_shopee_code(main.conn, self.bid, self.cycle_id, code="SHOP0801",
                                       redemption_count=3, actor=ACTOR)
        # 蝦皮碼是判讀當下讀的訊號，記錄後要重判讀一次才會反映進通路對照卡（既有行為，票 #40）。
        ok, err = reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        assert ok, err
        page = self._perf().text
        self.assertIn("SHOP0801", page)


if __name__ == "__main__":
    unittest.main()
