"""app/tests/test_workbench_tasks.py — 素材工作檯任務卡衍生查詢（票 13-workbench-cards）。

接縫二（路由層，app/ads/routes_workbench.py）：GET /api/ads/brands/{b}/workbench/tasks
走真正的 HTTP。不需要任何 AI 呼叫——主題直接用 theme_repository.create_theme() 灌資料
（照抄 app/tests/test_ads_theme_adopt_reject.py 的做法），只驗「計畫已核准＋素材未完成」
判準與卡片數字對不對得上 creative_theme／adoption_decision 的實況（驗收 1）。

驗收 2（零新資料表）不是行為測試，是靜態事實：app/ads/migrations/ 本票沒新增檔案，
用 `git status` 核對即可，不在這裡重複斷言。

setUp 寫法照抄既有先例——本專案測試檔一律自帶獨立 tmp DB，不共用 import。
"""

import unittest

from fastapi.testclient import TestClient

import app.main as main
from app.ads import repository as ads_repo
from app.ads import theme_repository as theme_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db

ACTOR = "測試員"


class _Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡（工作檯票）",
                                          client_name="測試客戶", actor=ACTOR, org_id=db.DEV_ORG_ID)
        self.bid = self.brand["id"]
        self.product_id = bi_repo.create_product(main.conn, self.bid, name="虛構濾掛組",
                                                  actor=ACTOR)["id"]

    def _open_cycle(self) -> dict:
        return ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[self.product_id],
            pain_value=5, objective="sales", actor=ACTOR,
        )

    def _insert_cell(self, cycle_id: str, *, angle: str = "價格敏感：第一杯 39 元") -> str:
        cell_id = db.new_id("exc")
        main.conn.execute(
            "INSERT INTO experiment_cell (id, org_id, campaign_cycle_id, brand_id, creative_angle,"
            " created_at) VALUES (%s, %s, %s, %s, %s, %s)",
            (cell_id, db.DEV_ORG_ID, cycle_id, self.bid, angle, db.now_iso()),
        )
        main.conn.commit()
        return cell_id

    def _insert_plan(self, cycle_id: str, *, status: str) -> None:
        main.conn.execute(
            "INSERT INTO campaign_plan (id, org_id, campaign_cycle_id, brand_id, plan_version,"
            " plan_json, status, approved_by, approved_at, created_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (db.new_id("cpl"), db.DEV_ORG_ID, cycle_id, self.bid, 1,
             db.jsonb({"summary": "測試打法"}), status,
             ACTOR if status == "approved" else None,
             db.now_iso() if status == "approved" else None, db.now_iso()),
        )
        main.conn.commit()

    def _create_theme(self, cycle_id: str, cell_id: str, *, format_key: str, name: str) -> dict:
        return theme_repo.create_theme(
            main.conn, self.bid, campaign_cycle_id=cycle_id, experiment_cell_id=cell_id,
            format_key=format_key, name=name, folder_code="A1B2", actor=ACTOR,
            components=[{"component_type": "body", "content": "測試文案內容"}],
        )

    def _tasks(self) -> list:
        resp = self.client.get(f"/api/ads/brands/{self.bid}/workbench/tasks")
        self.assertEqual(resp.status_code, 200)
        return resp.json()["tasks"]


class NoTaskCasesTest(_Base):
    """驗收 1 後半——不符合條件的不出卡。"""

    def test_empty_list_for_brand_with_no_cycles(self):
        self.assertEqual(self._tasks(), [])

    def test_plan_not_approved_yields_no_task(self):
        cycle = self._open_cycle()
        self._insert_cell(cycle["id"])
        self._insert_plan(cycle["id"], status="draft")
        self.assertEqual(self._tasks(), [])

    def test_no_plan_at_all_yields_no_task(self):
        cycle = self._open_cycle()
        self._insert_cell(cycle["id"])
        self.assertEqual(self._tasks(), [])

    def test_fully_generated_matrix_yields_no_task(self):
        """計畫核准了，但矩陣（1 格 × 3 格式）全部生過——素材已完成，不再出卡。"""
        cycle = self._open_cycle()
        cell_id = self._insert_cell(cycle["id"])
        self._insert_plan(cycle["id"], status="approved")
        for format_key in ("single_image", "carousel", "video"):
            self._create_theme(cycle["id"], cell_id, format_key=format_key, name=f"主題-{format_key}")
        self.assertEqual(self._tasks(), [])

    def test_no_cells_yields_no_task(self):
        cycle = self._open_cycle()
        self._insert_plan(cycle["id"], status="approved")
        self.assertEqual(self._tasks(), [])

    def test_archived_cycle_excluded_even_if_otherwise_qualifies(self):
        cycle = self._open_cycle()
        self._insert_cell(cycle["id"])
        self._insert_plan(cycle["id"], status="approved")
        ads_repo.set_cycle_archived(main.conn, self.bid, cycle["id"], archived=True, actor=ACTOR)
        self.assertEqual(self._tasks(), [])


class TaskAppearsWithCorrectCountsTest(_Base):
    """驗收 1 前半＋驗收 3——出卡時數字對得上主題表與決策實況，欄位足以畫任務卡。"""

    def test_partial_generation_counts_and_shape(self):
        cycle = self._open_cycle()
        cell_id = self._insert_cell(cycle["id"])
        self._insert_plan(cycle["id"], status="approved")
        theme = self._create_theme(cycle["id"], cell_id, format_key="single_image",
                                   name="虛構主題：暖金茶席")
        theme_repo.adopt_theme(main.conn, self.bid, theme["id"], actor=ACTOR)

        tasks = self._tasks()
        self.assertEqual(len(tasks), 1)
        task = tasks[0]
        self.assertEqual(task["source"], "廣告檔期")
        self.assertEqual(task["cycle_id"], cycle["id"])
        self.assertEqual(task["cycle_label"], f"{cycle['start_date']} ～ {cycle['end_date']}")
        self.assertEqual(task["total_cells"], 3)   # 1 格 × 3 格式（single_image/carousel/video）
        self.assertEqual(task["generated_cells"], 1)
        self.assertEqual(task["adopted_count"], 1)

    def test_two_themes_same_cell_same_format_count_as_one_generated_cell(self):
        """同一格同一格式生兩個主題（預選格常態）——已生成格數看「有沒有」不是「有幾個」。"""
        cycle = self._open_cycle()
        cell_id = self._insert_cell(cycle["id"])
        self._insert_plan(cycle["id"], status="approved")
        self._create_theme(cycle["id"], cell_id, format_key="single_image", name="主題一")
        self._create_theme(cycle["id"], cell_id, format_key="single_image", name="主題二")

        tasks = self._tasks()
        self.assertEqual(tasks[0]["generated_cells"], 1)
        self.assertEqual(tasks[0]["adopted_count"], 0)  # 都還沒被採用

    def test_multiple_cells_counted_independently(self):
        cycle = self._open_cycle()
        cell_a = self._insert_cell(cycle["id"], angle="價格敏感：第一杯 39 元")
        cell_b = self._insert_cell(cycle["id"], angle="便利：辦公室手沖")
        self._insert_plan(cycle["id"], status="approved")
        self._create_theme(cycle["id"], cell_a, format_key="single_image", name="A-主題")
        self._create_theme(cycle["id"], cell_a, format_key="carousel", name="A-輪播主題")
        # cell_b 全空

        tasks = self._tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["total_cells"], 6)     # 2 格 × 3 格式
        self.assertEqual(tasks[0]["generated_cells"], 2)  # 只有 cell_a 的兩種格式生過

    def test_multiple_qualifying_cycles_each_get_a_card(self):
        cycle1 = self._open_cycle()
        cell1 = self._insert_cell(cycle1["id"])
        self._insert_plan(cycle1["id"], status="approved")

        cycle2 = self._open_cycle()
        cell2 = self._insert_cell(cycle2["id"])
        self._insert_plan(cycle2["id"], status="approved")
        self._create_theme(cycle2["id"], cell2, format_key="single_image", name="第二期主題")

        tasks = self._tasks()
        self.assertEqual({t["cycle_id"] for t in tasks}, {cycle1["id"], cycle2["id"]})


if __name__ == "__main__":
    unittest.main()
