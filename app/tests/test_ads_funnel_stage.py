# -*- coding: utf-8 -*-
"""app/tests/test_ads_funnel_stage.py — 票 04：漏斗階段接上的最小自檢。

品牌名一律虛構，絕不使用真實客戶品牌。

涵蓋：
1. 五個本期目標各自推導到哪一層（純函數，對照 app/ads/plan.py OBJECTIVE_TO_FUNNEL_STAGE）。
2. 開新檔期（app/ads/repository.create_cycle）真的把推導結果寫進 funnel_stage 欄位，不再是 None。
3. 既有檔期回填 migration（0014_funnel_stage_backfill.sql）把舊資料的空值補上、不動已有值。
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from app.ads import plan as ads_plan
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db

ACTOR = "測試員"

_MIN_CYCLE_COLUMNS = (
    "id, brand_id, product_scope_json, objective, funnel_stage, currency, "
    "start_date, end_date, channels_json, status, created_at, updated_at"
)


def _insert_bare_cycle(conn, *, cycle_id: str, objective: str, funnel_stage) -> None:
    """繞過 create_cycle，直接寫一列「本票上線前開的舊檔期」——funnel_stage 還沒被接上，
    或（第二個情境）已經有人工訂正過的值，用來驗證回填 migration 不吃已有值。"""
    conn.execute(
        f"INSERT INTO campaign_cycle ({_MIN_CYCLE_COLUMNS}) VALUES "
        "(:id, 'brand_x', '[]', :objective, :funnel_stage, 'TWD', '2026-01-01', '2026-01-14', "
        "'[\"meta\"]', 'PLANNING', '2026-01-01T00:00:00', '2026-01-01T00:00:00')",
        {"id": cycle_id, "objective": objective, "funnel_stage": funnel_stage},
    )


class DeriveFunnelStageTest(unittest.TestCase):
    """五個目標值各自推導到哪一層——這是本票的核心對照表，改錯了畫面會顯示錯的漏斗層。"""

    def test_awareness_maps_to_exposure(self):
        self.assertEqual(ads_plan.derive_funnel_stage("awareness"), "exposure")

    def test_traffic_maps_to_consideration(self):
        self.assertEqual(ads_plan.derive_funnel_stage("traffic"), "consideration")

    def test_engagement_maps_to_consideration(self):
        self.assertEqual(ads_plan.derive_funnel_stage("engagement"), "consideration")

    def test_leads_maps_to_conversion(self):
        self.assertEqual(ads_plan.derive_funnel_stage("leads"), "conversion")

    def test_sales_maps_to_conversion(self):
        self.assertEqual(ads_plan.derive_funnel_stage("sales"), "conversion")

    def test_unknown_objective_returns_none_not_a_guess(self):
        self.assertIsNone(ads_plan.derive_funnel_stage("不存在的目標"))

    def test_every_objective_text_key_has_a_mapping(self):
        """OBJECTIVE_TEXT 是開期表單能選的五個值——每一個都必須推導得出漏斗層，不留漏網之魚。"""
        for objective in ads_plan.OBJECTIVE_TEXT:
            self.assertIsNotNone(ads_plan.derive_funnel_stage(objective),
                                  f"{objective} 沒有對應的漏斗層")

    def test_all_mapped_stages_have_a_human_label(self):
        for stage in ads_plan.OBJECTIVE_TO_FUNNEL_STAGE.values():
            self.assertIn(stage, ads_plan.FUNNEL_STAGE_LABELS)


class CreateCycleWritesFunnelStageTest(unittest.TestCase):
    """開新檔期時，funnel_stage 欄位要真的有值——這是本票要接上的行為，之前永遠寫 None。"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self._tmpdir.name) / "test.db")
        self.brand = bi_repo.create_brand(self.conn, name="虛構晨光咖啡",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def test_new_cycle_gets_funnel_stage_from_objective(self):
        cases = [
            ("awareness", "exposure"),
            ("traffic", "consideration"),
            ("engagement", "consideration"),
            ("leads", "conversion"),
            ("sales", "conversion"),
        ]
        for objective, expected_stage in cases:
            with self.subTest(objective=objective):
                cycle = ads_repo.create_cycle(
                    self.conn, self.bid, product_ids=[], pain_value=5000,
                    objective=objective, actor=ACTOR)
                self.assertEqual(cycle["funnel_stage"], expected_stage)
                stored = ads_repo.get_cycle(self.conn, self.bid, cycle["id"])
                self.assertEqual(stored["funnel_stage"], expected_stage,
                                  "回傳值跟寫進資料庫的值必須一致")


class FunnelStageBackfillMigrationTest(unittest.TestCase):
    """既有檔期（funnel_stage 還是 NULL 的舊資料）跑過回填 migration 後要補上值，不留空值；
    已經有值的列不能被覆蓋。

    做法：先套用到 0013（模擬本票上線前的舊 db），手動塞兩列舊資料，
    再補跑真正的 ads/migrations 目錄（含 0014），驗證回填結果。
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test.db"
        self.real_ads_dir = db.APP_DIR / "ads" / "migrations"
        self.pre14_dir = Path(self._tmpdir.name) / "ads_pre14"
        self.pre14_dir.mkdir()
        for path in sorted(self.real_ads_dir.glob("*.sql")):
            if int(path.name.split("_", 1)[0]) < 14:
                shutil.copy(path, self.pre14_dir / path.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_backfill_fills_null_rows_and_leaves_existing_values_alone(self):
        conn = db.connect(self.db_path)
        for module, migrations_dir in db.MODULE_MIGRATIONS:
            db.run_migrations(conn, module, self.pre14_dir if module == "ads" else migrations_dir)

        _insert_bare_cycle(conn, cycle_id="ccy_old", objective="sales", funnel_stage=None)
        _insert_bare_cycle(conn, cycle_id="ccy_already_set", objective="awareness",
                            funnel_stage="conversion")  # 模擬人工訂正過的值
        conn.commit()

        db.run_migrations(conn, "ads", self.real_ads_dir)  # 補跑到 0014

        old_row = conn.execute(
            "SELECT funnel_stage FROM campaign_cycle WHERE id = 'ccy_old'").fetchone()
        self.assertEqual(old_row["funnel_stage"], "conversion",
                          "sales → conversion，舊資料回填後不該再是 NULL")

        untouched_row = conn.execute(
            "SELECT funnel_stage FROM campaign_cycle WHERE id = 'ccy_already_set'").fetchone()
        self.assertEqual(untouched_row["funnel_stage"], "conversion",
                          "已經有值的列不該被 migration 覆蓋")
        conn.close()


if __name__ == "__main__":
    unittest.main()
