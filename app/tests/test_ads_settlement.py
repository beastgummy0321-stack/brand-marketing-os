# -*- coding: utf-8 -*-
"""app/tests/test_ads_settlement.py — 結算版次＋判讀快照基建（GitHub issue #37）。

驗收條件逐條對應：
1. 三組新表存在、掛檔期外鍵者進 CYCLE_CASCADE_TABLES（見 test_ads_schema.py／
   test_ads_cycle_delete.py，本檔不重複驗）。
2. 同一期重跑判讀必產生新版次，且快照逐位可比對（SettlementFreezeTest）。
3. 判讀只引用「當時生效」的係數與 SKU 成本版本；成本回改不改寫歷史（SkuCostVersionTest、
   SettlementFreezeTest.test_cost_change_after_freeze_does_not_rewrite_history）。

品牌與產品名一律虛構，絕不使用真實客戶品牌。
"""

import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_settlement_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import performance as perf  # noqa: E402
from app.ads import reading  # noqa: E402
from app.ads import settlement as ads_settlement  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import db  # noqa: E402
from app.llm.providers import FakeProvider, ProviderResponse, Usage  # noqa: E402
from app.orders import repository as orders_repo  # noqa: E402

main.reopen_connection()


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"


def _fake(text):
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=300, output_tokens=150),
                            stop_reason="end_turn")


class SkuCostVersionTest(unittest.TestCase):
    """成本版本表：登記即長版本，成本沒變不長版，valid_to 封頂舊版但值不被覆寫。"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self._tmpdir.name) / "test.db")
        self.bid = bi_repo.create_brand(self.conn, name="虛構晨光咖啡（成本版本）",
                                        client_name=None, actor=ACTOR)["id"]

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def test_first_set_creates_version_1(self):
        orders_repo.set_sku_cost(self.conn, self.bid, "SKU-A", 10, actor=ACTOR, today="2026-01-01")
        versions = orders_repo.list_effective_sku_costs(self.conn, self.bid)
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0]["version"], 1)
        self.assertEqual(versions[0]["unit_cost"], 10)
        self.assertIsNone(versions[0]["valid_to"])

    def test_cost_change_creates_new_version_and_closes_old(self):
        orders_repo.set_sku_cost(self.conn, self.bid, "SKU-A", 10, actor=ACTOR, today="2026-01-01")
        orders_repo.set_sku_cost(self.conn, self.bid, "SKU-A", 15, actor=ACTOR, today="2026-02-01")

        rows = self.conn.execute(
            "SELECT * FROM sku_cost_version WHERE brand_id = ? AND sku = ? ORDER BY version",
            (self.bid, "SKU-A"),
        ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["unit_cost"], 10)
        self.assertEqual(rows[0]["valid_to"], "2026-02-01")  # 舊版封頂，值不變
        self.assertIsNone(rows[1]["valid_to"])
        self.assertEqual(rows[1]["unit_cost"], 15)

        effective = orders_repo.list_effective_sku_costs(self.conn, self.bid)
        self.assertEqual(len(effective), 1)
        self.assertEqual(effective[0]["unit_cost"], 15)

    def test_setting_same_cost_again_does_not_grow_a_new_version(self):
        orders_repo.set_sku_cost(self.conn, self.bid, "SKU-A", 10, actor=ACTOR, today="2026-01-01")
        orders_repo.set_sku_cost(self.conn, self.bid, "SKU-A", 10, actor=ACTOR, today="2026-02-01")
        rows = self.conn.execute(
            "SELECT COUNT(*) c FROM sku_cost_version WHERE brand_id = ? AND sku = ?",
            (self.bid, "SKU-A"),
        ).fetchone()
        self.assertEqual(rows["c"], 1)


class SettlementFreezeTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡（結算快照）",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]
        self.product = bi_repo.create_product(main.conn, self.bid, name="虛構濾掛組",
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
        reading.PROVIDER = FakeProvider(response=_fake('{"text": "測試判讀說明"}'))

    def tearDown(self):
        reading.PROVIDER = self._orig

    def _spend(self, **values):
        perf.import_manual(main.conn, self.bid, self.cycle_id, values, actor=ACTOR)

    def test_rerun_produces_new_version_each_time(self):
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)

        versions = main.conn.execute(
            "SELECT version, trigger_reason FROM settlement_version"
            " WHERE campaign_cycle_id = ? ORDER BY version", (self.cycle_id,),
        ).fetchall()
        self.assertEqual([v["version"] for v in versions], [1, 2, 3])
        self.assertEqual(versions[0]["trigger_reason"], "initial")
        self.assertEqual(versions[1]["trigger_reason"], "manual_rerun")

        # performance_reading 仍是「目前這版」的單一快取列，不受版次數量影響
        # （既有 test_ads_reading.py::test_rerun_replaces_previous_reading 的既定行為）。
        current = main.conn.execute(
            "SELECT COUNT(*) c FROM performance_reading WHERE campaign_cycle_id = ?",
            (self.cycle_id,)).fetchone()["c"]
        self.assertEqual(current, 1)

        snapshots = main.conn.execute(
            "SELECT COUNT(*) c FROM reading_snapshot WHERE campaign_cycle_id = ?",
            (self.cycle_id,)).fetchone()["c"]
        self.assertEqual(snapshots, 3)

    def test_snapshot_captures_arrival_and_summary(self):
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)

        snap = ads_settlement.load_snapshot(main.conn, self.bid, self.cycle_id)
        self.assertEqual(snap["settlement_version"], 1)
        self.assertIn("meta", snap["data_arrival"])
        self.assertIsNotNone(snap["data_arrival"]["meta"])  # 剛匯入過，一定有到達時間
        self.assertIn("orders", snap["missing_sources"])  # 沒訂單資料，誠實列進缺席清單
        self.assertEqual(snap["summary"]["cycle"]["spend"], 10000)

    def test_snapshots_across_versions_are_comparable_field_by_field(self):
        """跨版差異必須對得上：花費從 10000 改成 20000，diff 要精準抓到 cycle.spend 這一鍵。"""
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)  # 累加後 spend=20000

        diffs = ads_settlement.diff_versions(main.conn, self.bid, self.cycle_id, 1, 2)
        changed_keys = {(scope, key) for scope, key, _before, _after in diffs}
        self.assertIn(("cycle", "spend"), changed_keys)
        spend_diff = next(d for d in diffs if d[:2] == ("cycle", "spend"))
        self.assertEqual(spend_diff[2], "10000.0")
        self.assertEqual(spend_diff[3], "20000.0")

    def test_cost_change_after_freeze_does_not_rewrite_history(self):
        """判讀只引用當時生效的成本版本：先凍結一版（成本 10），事後把成本改成 15，
        舊版快照的明細仍要顯示 10，不能被回改的成本悄悄改掉（決策 0025 審查補遺 C）。"""
        orders_repo.set_sku_cost(main.conn, self.bid, "SKU-A", 10, actor=ACTOR, today="2026-01-01")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)

        old_row = main.conn.execute(
            "SELECT rsin.value FROM reading_snapshot_input rsin"
            " JOIN reading_snapshot rs ON rs.id = rsin.reading_snapshot_id"
            " JOIN settlement_version sv ON sv.id = rs.settlement_version_id"
            " WHERE rs.campaign_cycle_id = ? AND sv.version = 1"
            " AND rsin.scope = 'sku_cost:SKU-A' AND rsin.key = 'unit_cost'",
            (self.cycle_id,),
        ).fetchone()
        self.assertEqual(old_row["value"], "10.0")

        # 成本回改：SKU-A 漲價到 15
        orders_repo.set_sku_cost(main.conn, self.bid, "SKU-A", 15, actor=ACTOR, today="2026-02-01")

        # 舊版快照的明細值必須紋風不動——它指向的是版本 id，不是現行值
        old_row_after = main.conn.execute(
            "SELECT rsin.value FROM reading_snapshot_input rsin"
            " JOIN reading_snapshot rs ON rs.id = rsin.reading_snapshot_id"
            " JOIN settlement_version sv ON sv.id = rs.settlement_version_id"
            " WHERE rs.campaign_cycle_id = ? AND sv.version = 1"
            " AND rsin.scope = 'sku_cost:SKU-A' AND rsin.key = 'unit_cost'",
            (self.cycle_id,),
        ).fetchone()
        self.assertEqual(old_row_after["value"], "10.0")

        # 重新判讀（第 2 版）才會看到新成本
        self._spend(spend=0, impressions=0, clicks=0, conversions=0, revenue=0)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        new_row = main.conn.execute(
            "SELECT rsin.value FROM reading_snapshot_input rsin"
            " JOIN reading_snapshot rs ON rs.id = rsin.reading_snapshot_id"
            " JOIN settlement_version sv ON sv.id = rs.settlement_version_id"
            " WHERE rs.campaign_cycle_id = ? AND sv.version = 2"
            " AND rsin.scope = 'sku_cost:SKU-A' AND rsin.key = 'unit_cost'",
            (self.cycle_id,),
        ).fetchone()
        self.assertEqual(new_row["value"], "15.0")

    def test_is_post_close_flag_reflects_cycle_status_at_freeze_time(self):
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        v1 = main.conn.execute(
            "SELECT is_post_close FROM settlement_version WHERE campaign_cycle_id = ? AND version = 1",
            (self.cycle_id,)).fetchone()
        self.assertEqual(v1["is_post_close"], 0)

        main.conn.execute("UPDATE campaign_cycle SET status = 'CLOSED' WHERE id = ?",
                          (self.cycle_id,))
        main.conn.commit()
        self._spend(spend=0, impressions=0, clicks=0, conversions=0, revenue=0)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        v2 = main.conn.execute(
            "SELECT is_post_close FROM settlement_version WHERE campaign_cycle_id = ? AND version = 2",
            (self.cycle_id,)).fetchone()
        self.assertEqual(v2["is_post_close"], 1)


if __name__ == "__main__":
    unittest.main()
