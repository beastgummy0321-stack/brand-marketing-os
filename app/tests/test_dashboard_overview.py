"""app/tests/test_dashboard_overview.py — 票 02-overview-cards：儀表板跨品牌總覽 API。

每個測試模組一個 Postgres schema（conftest.py 的 `_module_schema` fixture），
TestClient 模式。測試品牌一律虛構。
"""

import os
import unittest

os.environ["BRAND_OS_TODAY"] = "2026-08-05"  # 凍結時鐘：本檔所有日期斷言都以這天為「今天」

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import db as coredb  # noqa: E402
from app.core.db import new_id, now_iso  # noqa: E402
from app.orders import repository as orders_repo  # noqa: E402

ACTOR = "測試員"
TODAY = "2026-08-05"


class DashboardOverviewApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand_red = bi_repo.create_brand(
            main.conn, name=f"虛構燒錢茶行{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR, org_id=coredb.DEV_ORG_ID)
        self.brand_green = bi_repo.create_brand(
            main.conn, name=f"虛構安穩雜貨店{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR, org_id=coredb.DEV_ORG_ID)
        # 票 C：conversion_goal 沒設定會冒出提醒卡，蓋掉本檔要測的「四條規則都不觸發
        # →next_step 為 None」情境；先設定好維持本檔原本要測的東西。
        bi_repo.set_brand_switches(main.conn, self.brand_green["id"], market_region=None,
                                   conversion_goal="purchase", actor=ACTOR)

        # 紅燈品牌：一筆未結 money_loss 警報。core_interrupts.enqueue() 的 severity 由
        # CATEGORIES 登記表反查，目前尚無任何類別登記 money_loss（08-pacing-alert 之類
        # 未來票才會登記）；測試直接塞一列，繞過 enqueue（測試檔豁免跨層寫入掃描）。
        main.conn.execute(
            "INSERT INTO interrupt (id, org_id, brand_id, dedupe_key, category, severity,"
            " message, status, created_at) VALUES (%s, %s, %s, 'dup-1', 'code_surge_alert',"
            " 'money_loss', '測試用金額損失警報', 'open', %s)",
            (new_id("itr"), coredb.DEV_ORG_ID, self.brand_red["id"], now_iso()),
        )
        main.conn.commit()

        # 本月／上月訂單：本月 1200、上月 1000 → 環比 +20%
        orders_repo.save_orders(
            main.conn, self.brand_green["id"],
            [{"order_number": "ORD-THIS", "order_date": "2026-08-01",
              "total_amount": 1200, "refunded_amount": 0}],
            source="test", actor=ACTOR)
        orders_repo.save_orders(
            main.conn, self.brand_green["id"],
            [{"order_number": "ORD-LAST", "order_date": "2026-07-01",
              "total_amount": 1000, "refunded_amount": 0}],
            source="test", actor=ACTOR)

        # 綠燈品牌有一期投放中的檔期

    def _card(self, resp_data, brand_id):
        return next(c for c in resp_data if c["brand_id"] == brand_id)

    def test_envelope_has_data_and_generated_at(self):
        resp = self.client.get("/api/dashboard/overview")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("data", body)
        self.assertIn("generated_at", body)
        self.assertIsInstance(body["data"], list)

    def test_brand_with_open_money_loss_interrupt_is_red(self):
        body = self.client.get("/api/dashboard/overview").json()
        card = self._card(body["data"], self.brand_red["id"])
        self.assertEqual(card["health"], "red")

    def test_brand_with_no_open_interrupts_is_green(self):
        body = self.client.get("/api/dashboard/overview").json()
        card = self._card(body["data"], self.brand_green["id"])
        self.assertEqual(card["health"], "green")

    def test_revenue_this_month_and_mom_pct(self):
        body = self.client.get("/api/dashboard/overview").json()
        card = self._card(body["data"], self.brand_green["id"])
        self.assertEqual(card["revenue_this_month"], 1200)
        self.assertEqual(card["revenue_mom_pct"], 20.0)

    def test_card_no_longer_carries_a_cycle(self):
        """外殼切片（2026-08-28）：`active_cycle` 隨 `app/ads/` 一起從卡片契約移除——
        檔期概念不存在了（票 3 的 migration 也 DROP 掉了 campaign_cycle 表），
        欄位留著會是永遠 null 的假欄位。"""
        body = self.client.get("/api/dashboard/overview").json()
        card = self._card(body["data"], self.brand_green["id"])
        self.assertNotIn("active_cycle", card)

    def test_next_step_is_none_when_no_guide_card_rule_triggers(self):
        """票 04-guide-card-engine：next_step 接上指南卡引擎的真貨源。brand_green 這裡
        的 LIVE 檔期已經在成效格（stage_label 為 None）、沒有判讀、沒有待確認事實，
        沒有判讀、沒有待確認事實，規則都不觸發，next_step 該是 None，不是佔位字串。"""
        body = self.client.get("/api/dashboard/overview").json()
        card = self._card(body["data"], self.brand_green["id"])
        self.assertIn("next_step", card)
        self.assertIsNone(card["next_step"])

    def test_dashboard_endpoint_does_not_write_any_row(self):
        """接口鐵則：只讀，不寫任何資料。呼叫兩次前後各資料表『整列內容』不變（不能只比
        COUNT——第 2 輪驗證退回的正是 UPDATE 不增減列數、COUNT 抓不到的死角，見票 02
        second-round review）。"""
        tables = ["brand", "interrupt", "order_record"]

        def _snapshot():
            return {t: [dict(r) for r in main.conn.execute(f"SELECT * FROM {t} ORDER BY id")]
                    for t in tables}

        before = _snapshot()
        self.client.get("/api/dashboard/overview")
        self.client.get("/api/dashboard/overview")
        after = _snapshot()
        self.assertEqual(before, after)

    def test_dashboard_endpoint_does_not_archive_stale_informational_interrupt(self):
        """第 2 輪驗證退回的重現案例：list_open() 內部的 _archive_stale_informational
        會把逾期 14 天以上的 informational 提醒悄悄 UPDATE 成 archived。dashboard 打
        這支只讀 API 不該觸發這個副作用。"""
        stale_id = new_id("itr")
        main.conn.execute(
            "INSERT INTO interrupt (id, org_id, brand_id, dedupe_key, category, severity,"
            " message, status, visible_from, created_at) VALUES (%s, %s, %s, 'dup-stale',"
            " 'cycle_reminder', 'informational', '測試用逾期提醒', 'open', '2026-07-16', %s)",
            (stale_id, coredb.DEV_ORG_ID, self.brand_green["id"], now_iso()),
        )
        main.conn.commit()

        self.client.get("/api/dashboard/overview")

        row = main.conn.execute("SELECT status FROM interrupt WHERE id = %s",
                                (stale_id,)).fetchone()
        self.assertEqual(row["status"], "open")


class ArchivedBrandsApiTest(unittest.TestCase):
    """F50-I17: `GET /api/dashboard/archived-brands` = the org's archived brands, nothing else."""

    def setUp(self):
        self.client = TestClient(main.app)
        suffix = abs(hash(self.id())) % 100000
        self.active = bi_repo.create_brand(main.conn, name=f"虛構營業中{suffix}", client_name=None,
                                           actor=ACTOR, org_id=coredb.DEV_ORG_ID)
        self.archived = bi_repo.create_brand(main.conn, name=f"虛構收起來{suffix}",
                                             client_name="客戶", actor=ACTOR,
                                             org_id=coredb.DEV_ORG_ID)
        bi_repo.update_brand(main.conn, self.archived["id"], name=self.archived["name"],
                             client_name="客戶", status="archived", actor=ACTOR)
        other_org = f"org_archived_test_{suffix}"
        main.conn.execute("INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
                          " ON CONFLICT (id) DO NOTHING", (other_org, other_org))
        main.conn.commit()
        self.foreign = bi_repo.create_brand(main.conn, name=f"虛構別家{suffix}", client_name=None,
                                            actor=ACTOR, org_id=other_org)
        bi_repo.update_brand(main.conn, self.foreign["id"], name=self.foreign["name"],
                             client_name=None, status="archived", actor=ACTOR)

    def test_lists_only_this_orgs_archived_brands(self):
        resp = self.client.get("/api/dashboard/archived-brands")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertIn({"brand_id": self.archived["id"], "name": self.archived["name"]}, data)
        ids = {item["brand_id"] for item in data}
        self.assertNotIn(self.active["id"], ids)
        self.assertNotIn(self.foreign["id"], ids)
        overview = self.client.get("/api/dashboard/overview").json()["data"]
        overview_ids = {c["brand_id"] for c in overview}
        self.assertNotIn(self.archived["id"], overview_ids)


if __name__ == "__main__":
    unittest.main()
