"""app/tests/test_dashboard_guide_cards_wiring.py — 票 04-guide-card-engine：
儀表板 API 接上指南卡引擎真貨源（app/dashboard/guide_cards.py 的純函數邏輯已在
test_dashboard_guide_cards.py 測過，這裡只驗證 API 有把真實資料組成 facts 餵給引擎，
以及跨品牌總覽卡／單品牌駕駛艙分別拿到「第一筆」與「完整清單」）。

TestClient 模式。測試品牌一律虛構。
"""

import os
import unittest

os.environ["BRAND_OS_TODAY"] = "2026-08-05"  # 凍結時鐘：與其他儀表板測試檔一致

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import pacing as ads_pacing  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import db as coredb  # noqa: E402
from app.core.db import new_id, now_iso  # noqa: E402

ACTOR = "測試員"



def _insert_cycle(conn, brand_id: str, *, status: str, start_date: str = "2026-07-20") -> str:
    """比照 test_dashboard_overview.py：檔期用公開的 create_cycle 對本票情境過重，
    直接塞一列（測試檔豁免跨層 SQL 掃描）。"""
    cycle_id = new_id("ccy")
    ts = now_iso()
    conn.execute(
        "INSERT INTO campaign_cycle (id, org_id, brand_id, product_scope_json, objective,"
        " budget, currency, start_date, end_date, channels_json, status, archived,"
        " plan_version, phase, created_at, updated_at) VALUES (%s, %s, %s, '[]', 'sales',"
        " 5000, 'TWD', %s, %s, '[\"meta\"]', %s, false, 0, 'normal', %s, %s)",
        (cycle_id, coredb.DEV_ORG_ID, brand_id, start_date, start_date, status, ts, ts),
    )
    conn.commit()
    return cycle_id


def _insert_reading(conn, brand_id: str, cycle_id: str) -> None:
    conn.execute(
        "INSERT INTO performance_reading (id, org_id, brand_id, campaign_cycle_id, status,"
        " rule_result_json, created_at) VALUES (%s, %s, %s, %s, 'maintain', '{}', %s)",
        (new_id("prd"), coredb.DEV_ORG_ID, brand_id, cycle_id, now_iso()),
    )
    conn.commit()


def _insert_next_cycle_recommendation(conn, brand_id: str, cycle_id: str) -> None:
    ts = now_iso()
    conn.execute(
        "INSERT INTO recommendation (id, org_id, brand_id, campaign_cycle_id,"
        " recommendation_type, content_json, status, created_at, updated_at)"
        " VALUES (%s, %s, %s, %s, 'next_cycle', '{}', 'GENERATED', %s, %s)",
        (new_id("rec"), coredb.DEV_ORG_ID, brand_id, cycle_id, ts, ts),
    )
    conn.commit()


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
            client_name=None, actor=ACTOR)
        bi_repo.set_brand_switches(main.conn, brand["id"], market_region=None,
                                   conversion_goal="purchase", actor=ACTOR)
        bi_repo.create_brand_fact(
            main.conn, brand["id"], actor=ACTOR, fact_type="other",
            label="測試事實", value="測試值", status="pending")

        card = self._card(brand["id"])
        self.assertIsNotNone(card["next_step"])
        self.assertIn("1", card["next_step"]["title"])
        self.assertEqual(card["next_step"]["action_url"], f"/app/brands/{brand['id']}/library?tab=facts")

    def test_cycle_stuck_before_launch_surfaces_stage_as_next_step(self):
        brand = bi_repo.create_brand(
            main.conn, name=f"虛構卡關雜貨店{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)
        bi_repo.set_brand_switches(main.conn, brand["id"], market_region=None,
                                   conversion_goal="purchase", actor=ACTOR)
        cycle_id = _insert_cycle(main.conn, brand["id"], status="PLANNING")

        card = self._card(brand["id"])
        self.assertIsNotNone(card["next_step"])
        self.assertIn("計畫", card["next_step"]["title"])
        self.assertEqual(card["next_step"]["action_url"],
                         f"/app/brands/{brand['id']}/campaigns/{cycle_id}")

    def test_reading_unread_beats_pending_facts_in_priority(self):
        """判讀出爐未讀（reading_unread）比待確認事實（pending_facts）先登記，
        兩條規則同時觸發時 next_step 該是 reading_unread。"""
        brand = bi_repo.create_brand(
            main.conn, name=f"虛構判讀待看茶行{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)
        bi_repo.set_brand_switches(main.conn, brand["id"], market_region=None,
                                   conversion_goal="purchase", actor=ACTOR)
        cycle_id = _insert_cycle(main.conn, brand["id"], status="EVALUATING")
        _insert_reading(main.conn, brand["id"], cycle_id)
        bi_repo.create_brand_fact(
            main.conn, brand["id"], actor=ACTOR, fact_type="other",
            label="測試事實", value="測試值", status="pending")

        card = self._card(brand["id"])
        self.assertIsNotNone(card["next_step"])
        self.assertIn("判讀", card["next_step"]["title"])
        self.assertEqual(card["next_step"]["action_url"],
                         f"/app/brands/{brand['id']}/campaigns/{cycle_id}")

    def test_next_cycle_draft_ready_surfaces_once_reading_is_used(self):
        brand = bi_repo.create_brand(
            main.conn, name=f"虛構下期已備妥雜貨店{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)
        bi_repo.set_brand_switches(main.conn, brand["id"], market_region=None,
                                   conversion_goal="purchase", actor=ACTOR)
        cycle_id = _insert_cycle(main.conn, brand["id"], status="CLOSED")
        _insert_reading(main.conn, brand["id"], cycle_id)
        _insert_next_cycle_recommendation(main.conn, brand["id"], cycle_id)

        card = self._card(brand["id"])
        self.assertIsNotNone(card["next_step"])
        self.assertIn("下期草案", card["next_step"]["title"])
        self.assertEqual(card["next_step"]["action_url"],
                         f"/app/brands/{brand['id']}/campaigns/{cycle_id}")


class CockpitGuideCardsWiringTest(unittest.TestCase):
    """單品牌駕駛艙拿到完整清單（最多 3 件），沒有待辦是空清單。"""

    def setUp(self):
        self.client = TestClient(main.app)

    def _guide_cards(self, brand_id):
        body = self.client.get(f"/api/dashboard/brands/{brand_id}/cockpit").json()
        return body["data"]["guide_cards"]

    def test_empty_list_when_nothing_to_do(self):
        brand = bi_repo.create_brand(
            main.conn, name=f"虛構一切正常茶行{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)
        bi_repo.set_brand_switches(main.conn, brand["id"], market_region=None,
                                   conversion_goal="purchase", actor=ACTOR)
        self.assertEqual(self._guide_cards(brand["id"]), [])

    def test_conversion_goal_missing_surfaces_as_guide_card(self):
        """票 C：conversion_goal 沒設定本身就是待辦，駕駛艙要看得到。"""
        brand = bi_repo.create_brand(
            main.conn, name=f"虛構沒設定目標茶行{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)
        cards = self._guide_cards(brand["id"])
        self.assertEqual(len(cards), 1)
        self.assertIn("廣告目標", cards[0]["title"])
        self.assertEqual(cards[0]["action_url"], f"/app/brands/{brand['id']}/library")

    def test_stuck_cycle_and_pending_facts_both_surface_up_to_three(self):
        brand = bi_repo.create_brand(
            main.conn, name=f"虛構雙待辦雜貨店{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)
        bi_repo.set_brand_switches(main.conn, brand["id"], market_region=None,
                                   conversion_goal="purchase", actor=ACTOR)
        _insert_cycle(main.conn, brand["id"], status="PRODUCTION")
        bi_repo.create_brand_fact(
            main.conn, brand["id"], actor=ACTOR, fact_type="other",
            label="測試事實", value="測試值", status="pending")

        cards = self._guide_cards(brand["id"])
        self.assertEqual(len(cards), 2)
        titles = " ".join(c["title"] for c in cards)
        self.assertIn("素材", titles)
        self.assertIn("事實", titles)

    def test_intake_draft_in_progress_surfaces_as_guide_card(self):
        """票 B3-intake：品牌有進行中的建檔精靈草稿，駕駛艙要看得到「繼續建檔」的入口
        （GRILL-B3-intake.md「拿不準的點」第 3 條裁決：併進本票）。"""
        resp = self.client.post("/api/intake/brands", data={
            "brand_name": f"虛構建檔中茶行{abs(hash(self.id())) % 100000}",
            "description": "一句測試用的品牌描述文字。",
        })
        brand_id = resp.json()["brand_id"]
        bi_repo.set_brand_switches(main.conn, brand_id, market_region=None,
                                   conversion_goal="purchase", actor=ACTOR)
        cards = self._guide_cards(brand_id)
        self.assertEqual(len(cards), 1)
        self.assertIn("建檔進行中（第 2 步，共 5 步）", cards[0]["title"])
        self.assertIn("繼續建檔", cards[0]["title"])
        self.assertEqual(cards[0]["action_url"], f"/app/brands/{brand_id}/intake")

    def test_pacing_alert_card_names_which_cycle(self):
        """B0-15：品牌同時有好幾期進行中時，「下一步指南」的 pacing 警示卡要寫出是哪一期
        （跟「看這期完整作戰室」指到不同檔期時，兩處都得標日期區間）。"""
        brand = bi_repo.create_brand(
            main.conn, name=f"虛構步調警示茶行{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)
        bi_repo.set_brand_switches(main.conn, brand["id"], market_region=None,
                                   conversion_goal="purchase", actor=ACTOR)
        cycle = ads_repo.create_cycle(
            main.conn, brand["id"], product_ids=[], pain_value=10000, objective="sales",
            actor=ACTOR, start_date="2026-07-14", duration_days=7)
        ads_repo.update_cycle_status(main.conn, brand["id"], cycle["id"], status="LIVE", actor=ACTOR)
        # 花費遠遠落後時間進度 → underspend，真的走 check_cycle() 排進打斷佇列
        # （不直接塞 interrupt 列，這樣才驗到 campaign_cycle_id 真的被帶上去）。
        ads_pacing.check_cycle(main.conn, brand["id"], cycle["id"], today="2026-07-20")

        cards = self._guide_cards(brand["id"])
        self.assertEqual(len(cards), 1)
        self.assertIn("2026-07-14", cards[0]["title"])
        self.assertIn("2026-07-20", cards[0]["title"])

    def test_cockpit_endpoint_does_not_write_any_row(self):
        """接口鐵則：只讀。指南卡的資料源多讀了 campaign_cycle／performance_reading／
        recommendation／brand_fact 幾張表，補進只讀防線的快照清單裡一起驗。"""
        brand = bi_repo.create_brand(
            main.conn, name=f"虛構只讀驗證茶行{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)
        cycle_id = _insert_cycle(main.conn, brand["id"], status="EVALUATING")
        _insert_reading(main.conn, brand["id"], cycle_id)
        bi_repo.create_brand_fact(
            main.conn, brand["id"], actor=ACTOR, fact_type="other",
            label="測試事實", value="測試值", status="pending")

        tables = ["brand", "campaign_cycle", "performance_reading", "recommendation",
                 "brand_fact"]

        def _snapshot():
            return {t: [dict(r) for r in main.conn.execute(f"SELECT * FROM {t} ORDER BY id")]
                    for t in tables}

        before = _snapshot()
        self.client.get(f"/api/dashboard/brands/{brand['id']}/cockpit")
        self.client.get(f"/api/dashboard/brands/{brand['id']}/cockpit")
        after = _snapshot()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
