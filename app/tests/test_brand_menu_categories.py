# -*- coding: utf-8 -*-
"""app/tests/test_brand_menu_categories.py — D線票7（GitHub issue #49）：
品牌功能選單頁四分類＋品牌智庫首頁收斂（限制規則＋宣稱→規則與宣稱、
官方素材＋自有渠道→素材與渠道）。

品牌與資料一律虛構，嚴禁真實品牌名稱。
"""

import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_menu_categories_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.tools import capacity_check as cc  # noqa: E402


ACTOR = "測試員"


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)


class _Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]


class BrandMenuFourCategoriesTest(_Base):
    """品牌功能選單頁：主欄 = 4 張分類卡，容量腳本通過。"""

    def test_main_grid_has_exactly_four_category_cards(self):
        resp = self.client.get(f"/brands/{self.bid}")
        for title in ("品牌智庫", "投放與成效", "內容與曝光", "顧客與口碑"):
            self.assertIn(title, resp.text)
        counts = cc.check_html(resp.text)
        self.assertLessEqual(counts["nav_link_count"], cc.NAV_LINK_LIMIT)
        self.assertLessEqual(counts["card_count"], cc.CARD_LIMIT)
        self.assertEqual(cc.violations(f"/brands/{self.bid}", counts), [])

    def test_six_soon_branches_visible_but_not_links(self):
        """六個未上線分支（成效中樞併入投放與成效、其餘五個併入內容與曝光／顧客與口碑）
        仍看得到、但不是可點連結（不佔主欄，各分類詳情裡呈現）。"""
        resp = self.client.get(f"/brands/{self.bid}")
        for branch in ("成效中樞", "內容經營", "視覺資產", "搜尋曝光", "顧客關係", "口碑擴散"):
            self.assertIn(branch, resp.text)
            self.assertNotIn(f'href="{branch}"', resp.text)

    def test_advisor_report_and_reintake_links_reachable_from_hub_category_detail(self):
        resp = self.client.get(f"/brands/{self.bid}")
        self.assertIn(f'href="/brands/{self.bid}/report"', resp.text)
        self.assertIn(f'href="/brands/{self.bid}/intake/restart"', resp.text)
        # 兩者的目的頁行為不變、仍可達
        self.assertEqual(self.client.get(f"/brands/{self.bid}/report").status_code, 200)

    def test_reintake_link_hidden_when_brand_archived(self):
        bi_repo.update_brand(main.conn, self.bid, name=self.brand["name"],
                             client_name="測試客戶", status="archived", actor=ACTOR)
        resp = self.client.get(f"/brands/{self.bid}")
        self.assertNotIn(f'href="/brands/{self.bid}/intake/restart"', resp.text)

    def test_pending_alert_card_hidden_when_zero(self):
        resp = self.client.get(f"/brands/{self.bid}")
        self.assertNotIn("pending-alert-card", resp.text)

    def test_pending_alert_card_shown_when_facts_pending(self):
        bi_repo.create_brand_fact(main.conn, self.bid, fact_type="定位", label="虛構事實",
                                  value="示範內容", status="pending", actor=ACTOR)
        resp = self.client.get(f"/brands/{self.bid}")
        self.assertIn("pending-alert-card", resp.text)
        self.assertIn("品牌事實待確認 1 項", resp.text)

    def test_ads_still_a_real_link_not_soon(self):
        """既有測試（test_ads_cycle）已驗證此點；這裡只補驗四分類改版沒有讓它退回即將推出。"""
        resp = self.client.get(f"/brands/{self.bid}")
        self.assertIn(f'href="/brands/{self.bid}/ads"', resp.text)


class HubHomeRulesClaimsMergeTest(_Base):
    """品牌智庫首頁：「限制規則」＋「宣稱」合併為一張「規則與宣稱」，卡上分別顯示兩類筆數。"""

    def _add_rule_and_claim(self):
        bi_repo.create_rule(main.conn, self.bid, rule_type="hard", content="虛構限制規則",
                            severity="hard", actor=ACTOR)
        bi_repo.create_claim(main.conn, self.bid, claim_text="虛構宣稱",
                             claim_type="approved", actor=ACTOR)

    def test_merged_card_shows_both_counts_and_no_separate_rules_or_claims_cards(self):
        self._add_rule_and_claim()
        resp = self.client.get(f"/brands/{self.bid}/hub")
        self.assertIn("規則與宣稱", resp.text)
        self.assertIn("限制規則 1 筆", resp.text)
        self.assertIn("宣稱 1 筆", resp.text)
        # 舊的「限制規則」「宣稱」不再各自是一張獨立入口卡標題
        self.assertNotIn('<h3>限制規則</h3>', resp.text)
        self.assertNotIn('<h3>宣稱</h3>', resp.text)

    def test_existing_rules_and_claims_urls_unchanged_and_reachable(self):
        self._add_rule_and_claim()
        resp = self.client.get(f"/brands/{self.bid}/hub")
        self.assertIn(f'href="/brands/{self.bid}/hub/rules"', resp.text)
        self.assertIn(f'href="/brands/{self.bid}/hub/claims"', resp.text)
        self.assertEqual(self.client.get(f"/brands/{self.bid}/hub/rules").status_code, 200)
        self.assertEqual(self.client.get(f"/brands/{self.bid}/hub/claims").status_code, 200)

    def test_rules_and_claims_pages_content_and_behavior_unchanged(self):
        """既有子頁（新增／修改／確認／刪除）沿用既有測試，這裡只確認內容還在，
        沒有因為這次改版被搬動或清空。"""
        self._add_rule_and_claim()
        rules_page = self.client.get(f"/brands/{self.bid}/hub/rules").text
        claims_page = self.client.get(f"/brands/{self.bid}/hub/claims").text
        self.assertIn("虛構限制規則", rules_page)
        self.assertIn("虛構宣稱", claims_page)

    def test_hub_home_uses_capacity_registered_detail_component_only(self):
        self._add_rule_and_claim()
        resp = self.client.get(f"/brands/{self.bid}/hub")
        counts = cc.check_html(resp.text)
        self.assertEqual(counts["illegal_detail_count"], 0)
        for n in counts["card_text_counts"]:
            self.assertLessEqual(n, cc.CARD_TEXT_LIMIT)

    def test_hub_home_card_count_down_to_five(self):
        """品牌智庫首頁 = 5 張卡（品牌事實／規則與宣稱／產品／素材與渠道／顧客原話），
        兩次合併（限制規則＋宣稱、官方素材＋自有渠道）都到位後完全合規。"""
        resp = self.client.get(f"/brands/{self.bid}/hub")
        counts = cc.check_html(resp.text)
        self.assertEqual(counts["card_count"], 5)
        self.assertEqual(cc.violations(f"/brands/{self.bid}/hub", counts), [])


class HubHomeAssetsChannelsMergeTest(_Base):
    """品牌智庫首頁：「官方素材」＋「自有渠道」合併為一張「素材與渠道」卡，
    卡上分別顯示兩類筆數，比照規則與宣稱既有的合併寫法。"""

    def _add_asset_and_channel(self):
        bi_repo.create_official_asset(main.conn, self.bid, actor=ACTOR, asset_kind="logo",
                                      file_path="uploads/fake-logo.png")
        bi_repo.create_channel(main.conn, self.bid, actor=ACTOR, channel_type="website",
                               name="虛構晨光咖啡官網", identifier="https://example.test/fake")

    def test_merged_card_shows_both_counts_and_no_separate_assets_or_channels_cards(self):
        self._add_asset_and_channel()
        resp = self.client.get(f"/brands/{self.bid}/hub")
        self.assertIn("素材與渠道", resp.text)
        self.assertIn("官方素材 1 筆", resp.text)
        self.assertIn("自有渠道 1 筆", resp.text)
        self.assertNotIn('<h3>官方素材</h3>', resp.text)
        self.assertNotIn('<h3>自有渠道</h3>', resp.text)

    def test_existing_assets_and_channels_urls_unchanged_and_reachable(self):
        self._add_asset_and_channel()
        resp = self.client.get(f"/brands/{self.bid}/hub")
        self.assertIn(f'href="/brands/{self.bid}/hub/assets"', resp.text)
        self.assertIn(f'href="/brands/{self.bid}/hub/channels"', resp.text)
        assets_page = self.client.get(f"/brands/{self.bid}/hub/assets")
        channels_page = self.client.get(f"/brands/{self.bid}/hub/channels")
        self.assertEqual(assets_page.status_code, 200)
        self.assertEqual(channels_page.status_code, 200)
        self.assertIn("虛構晨光咖啡官網", channels_page.text)

    def test_hub_home_uses_capacity_registered_detail_component_only(self):
        self._add_asset_and_channel()
        resp = self.client.get(f"/brands/{self.bid}/hub")
        counts = cc.check_html(resp.text)
        self.assertEqual(counts["illegal_detail_count"], 0)
        for n in counts["card_text_counts"]:
            self.assertLessEqual(n, cc.CARD_TEXT_LIMIT)


if __name__ == "__main__":
    unittest.main()
