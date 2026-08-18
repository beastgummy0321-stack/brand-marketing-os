# -*- coding: utf-8 -*-
"""app/tests/test_dashboard_overview.py — 票 02-overview-cards：儀表板跨品牌總覽 API。

隔離測試資料庫（BRAND_OS_DB 指向 tmp 檔），TestClient 模式（比照
app/tests/test_orders_routes.py）。測試品牌一律虛構。
"""

import atexit
import os
import shutil
import tempfile
import unittest
from datetime import date

_tmpdir = tempfile.mkdtemp(prefix="brand_os_dashboard_")
os.environ["BRAND_OS_TODAY"] = "2026-08-05"  # 凍結時鐘：本檔所有日期斷言都以這天為「今天」

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import interrupts as core_interrupts  # noqa: E402
from app.core.db import new_id, now_iso  # noqa: E402
from app.orders import repository as orders_repo  # noqa: E402



def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"
TODAY = "2026-08-05"


def _insert_cycle(conn, brand_id: str, *, status: str, start_date: str) -> str:
    """檔期建立走公開函式（create_cycle）需要先備妥產品與單位經濟資料，對本票的
    「有一期進行中檔期」情境過重；改直接塞一列 campaign_cycle（測試檔豁免跨層 SQL
    掃描，見 test_architecture_boundaries.py 的 app/tests/ 排除清單）。"""
    cycle_id = new_id("ccy")
    ts = now_iso()
    conn.execute(
        "INSERT INTO campaign_cycle (id, brand_id, product_scope_json, objective, budget,"
        " currency, start_date, end_date, channels_json, status, archived, plan_version,"
        " phase, created_at, updated_at) VALUES (?, ?, '[]', 'sales', 5000, 'TWD', ?, ?,"
        " '[\"meta\"]', ?, 0, 0, 'normal', ?, ?)",
        (cycle_id, brand_id, start_date, start_date, status, ts, ts),
    )
    conn.commit()
    return cycle_id


class DashboardOverviewApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand_red = bi_repo.create_brand(
            main.conn, name=f"虛構燒錢茶行{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)
        self.brand_green = bi_repo.create_brand(
            main.conn, name=f"虛構安穩雜貨店{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)
        # 票 C：conversion_goal 沒設定會冒出提醒卡，蓋掉本檔要測的「四條規則都不觸發
        # →next_step 為 None」情境；先設定好維持本檔原本要測的東西。
        bi_repo.set_brand_switches(main.conn, self.brand_green["id"], market_region=None,
                                   conversion_goal="purchase", actor=ACTOR)

        # 紅燈品牌：一筆未結 money_loss 警報。core_interrupts.enqueue() 的 severity 由
        # CATEGORIES 登記表反查，目前尚無任何類別登記 money_loss（08-pacing-alert 之類
        # 未來票才會登記）；測試直接塞一列，繞過 enqueue（測試檔豁免跨層寫入掃描）。
        main.conn.execute(
            "INSERT INTO interrupt (id, brand_id, dedupe_key, category, severity, message,"
            " status, created_at) VALUES (?, ?, 'dup-1', 'code_surge_alert', 'money_loss',"
            " '測試用金額損失警報', 'open', ?)",
            (new_id("itr"), self.brand_red["id"], now_iso()),
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
        self.cycle_id = _insert_cycle(main.conn, self.brand_green["id"],
                                      status="LIVE", start_date="2026-07-20")

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

    def test_active_cycle_status_surfaced(self):
        body = self.client.get("/api/dashboard/overview").json()
        card = self._card(body["data"], self.brand_green["id"])
        self.assertIsNotNone(card["active_cycle"])
        self.assertEqual(card["active_cycle"]["id"], self.cycle_id)
        self.assertEqual(card["active_cycle"]["status"], "LIVE")
        self.assertEqual(card["active_cycle"]["status_label"], "投放中")

    def test_brand_with_no_cycle_has_null_active_cycle(self):
        body = self.client.get("/api/dashboard/overview").json()
        card = self._card(body["data"], self.brand_red["id"])
        self.assertIsNone(card["active_cycle"])

    def test_next_step_is_none_when_no_guide_card_rule_triggers(self):
        """票 04-guide-card-engine：next_step 接上指南卡引擎的真貨源。brand_green 這裡
        的 LIVE 檔期已經在成效格（stage_label 為 None）、沒有判讀、沒有待確認事實，
        四條規則都不觸發，next_step 該是 None，不是佔位字串。"""
        body = self.client.get("/api/dashboard/overview").json()
        card = self._card(body["data"], self.brand_green["id"])
        self.assertIn("next_step", card)
        self.assertIsNone(card["next_step"])

    def test_dashboard_endpoint_does_not_write_any_row(self):
        """接口鐵則：只讀，不寫任何資料。呼叫兩次前後各資料表『整列內容』不變（不能只比
        COUNT——第 2 輪驗證退回的正是 UPDATE 不增減列數、COUNT 抓不到的死角，見票 02
        second-round review）。"""
        tables = ["brand", "interrupt", "order_record", "campaign_cycle"]

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
            "INSERT INTO interrupt (id, brand_id, dedupe_key, category, severity, message,"
            " status, visible_from, created_at) VALUES (?, ?, 'dup-stale', 'cycle_reminder',"
            " 'informational', '測試用逾期提醒', 'open', '2026-07-16', ?)",
            (stale_id, self.brand_green["id"], now_iso()),
        )
        main.conn.commit()

        self.client.get("/api/dashboard/overview")

        row = main.conn.execute("SELECT status FROM interrupt WHERE id = ?",
                                (stale_id,)).fetchone()
        self.assertEqual(row["status"], "open")


if __name__ == "__main__":
    unittest.main()
