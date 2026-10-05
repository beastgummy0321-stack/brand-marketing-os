"""app/tests/test_dashboard_guide_cards_wiring.py — 票 04-guide-card-engine：
儀表板 API 接上指南卡引擎真貨源（app/dashboard/guide_cards.py 的純函數邏輯已在
test_dashboard_guide_cards.py 測過，這裡只驗證 API 有把真實資料組成 facts 餵給引擎，
跨品牌總覽卡拿到排序後的「第一筆」）。

外殼切片（2026-08-28）：檔期相關的案例（卡關關卡、判讀未讀、下期草案、pacing 警示）
與整個 `CockpitGuideCardsWiringTest` 隨 `app/ads/` 一起刪掉——那四條規則與
`/api/dashboard/brands/{id}/cockpit` 端點都不存在了。

TestClient 模式。測試品牌一律虛構。
"""

import os
import unittest

os.environ["BRAND_OS_TODAY"] = "2026-08-05"  # 凍結時鐘：與其他儀表板測試檔一致

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import db as coredb  # noqa: E402

ACTOR = "測試員"


class OverviewNextStepWiringTest(unittest.TestCase):
    """跨品牌總覽卡「最重要一件下一步」＝指南卡引擎排序後的第一筆。"""

    def setUp(self):
        self.client = TestClient(main.app)

    def _card(self, brand_id):
        body = self.client.get("/api/dashboard/overview").json()
        return next(c for c in body["data"] if c["brand_id"] == brand_id)

    def test_pending_facts_surface_as_next_step(self):
        brand = bi_repo.create_brand(
            main.conn, name=f"虛構待確認茶行{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR, org_id=coredb.DEV_ORG_ID)
        bi_repo.set_brand_switches(main.conn, brand["id"], market_region=None,
                                   conversion_goal="purchase", actor=ACTOR)
        bi_repo.create_brand_fact(
            main.conn, brand["id"], actor=ACTOR, fact_type="positioning",
            label="測試事實", value="測試值", status="pending")

        card = self._card(brand["id"])
        self.assertIsNotNone(card["next_step"])
        self.assertIn("1", card["next_step"]["title"])
        self.assertEqual(card["next_step"]["action_url"],
                         f"/brands/{brand['id']}/library?tab=facts")

    def test_conversion_goal_missing_outranks_pending_facts(self):
        """票 C：conversion_goal 沒設定本身就是待辦，而且排在所有規則之前。"""
        brand = bi_repo.create_brand(
            main.conn, name=f"虛構沒設定目標茶行{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR, org_id=coredb.DEV_ORG_ID)
        bi_repo.create_brand_fact(
            main.conn, brand["id"], actor=ACTOR, fact_type="positioning",
            label="測試事實", value="測試值", status="pending")

        card = self._card(brand["id"])
        self.assertIn("廣告目標", card["next_step"]["title"])
        self.assertEqual(card["next_step"]["action_url"], f"/brands/{brand['id']}/library")

    def test_intake_draft_in_progress_surfaces_as_next_step(self):
        """票 B3-intake：品牌有進行中的建檔精靈草稿，總覽卡要看得到「繼續建檔」的入口。"""
        resp = self.client.post("/api/intake/brands", data={
            "brand_name": f"虛構建檔中茶行{abs(hash(self.id())) % 100000}",
            "description": "一句測試用的品牌描述文字。",
        })
        brand_id = resp.json()["brand_id"]
        bi_repo.set_brand_switches(main.conn, brand_id, market_region=None,
                                   conversion_goal="purchase", actor=ACTOR)

        card = self._card(brand_id)
        # F42-I04: seven brand-onboarding steps; a description-only brand skips the scan (step 2).
        self.assertIn("建檔進行中（第 3 步，共 7 步）", card["next_step"]["title"])
        self.assertEqual(card["next_step"]["action_url"], f"/brands/{brand_id}/intake")


if __name__ == "__main__":
    unittest.main()
