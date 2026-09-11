"""app/tests/test_workbench_pack.py — F02-I02: 任務包 → 素材組 → 產物 → 版本, the physical
model (ARCHITECTURE.md §5.1-§5.4) and the upstream handoff contract (`submit_pack`). Covers
the two pure state-derivation rules (§5.3: product/set/pack state, the set-table cell text)
and the write path (`submit_pack`, a version-aware `write_output`, `select_version`/
`adopted_output`), plus tenant isolation for `pack_for_source`. FakeProvider/LLM calls are out
of scope here — those are `test_workbench.py`'s job (ARCHITECTURE.md §5.2's version-count-per-
part rule is exercised end to end there via `jobs.py`).
"""

import unittest

import app.shared.web as web
import app.workbench as workbench_module
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.workbench import repository as workbench_repo

ACTOR = "測試員"


class _WorkbenchPackTestBase(unittest.TestCase):
    def setUp(self):
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：任務包", client_name=None,
            actor=ACTOR,
        )
        self.brand_id = self.brand["id"]

    def _submit_pack(self, sets: list, **overrides) -> str:
        pack = {
            "source_kind": "schedule_node", "source_ref": {"source_tree_task_id": "tree_1"},
            "name": "測試任務包", "summary": {"情境": "測試"}, "sets": sets,
        }
        pack.update(overrides)
        return workbench_repo.submit_pack(web.conn, self.org_id, self.brand_id, pack)

    def _one_set(self, node_key: str, required_outputs: dict) -> dict:
        return {
            "name": f"單元 {node_key}", "source_ref": {"node_key": node_key},
            "coordinates": {}, "style_key": "ugc", "required_outputs": required_outputs,
            "request": {"copy_length": "short", "image_prompt_count": 3},
        }

    def _briefs(self, pack_id: str) -> list:
        rows = web.conn.execute(
            "SELECT * FROM workbench_brief WHERE org_id = %s AND brand_id = %s"
            " AND pack_id = %s ORDER BY created_at",
            (self.org_id, self.brand_id, pack_id),
        ).fetchall()
        return [dict(r) for r in rows]


# -- 案例 1：純函式——product_state／set_state／pack_state／set_table_cell 一次到位 --------

class StateDerivationTest(unittest.TestCase):
    def test_product_state_未生成_待選定_已選定(self):
        self.assertEqual(workbench_repo.product_state(1, []), "未生成")
        self.assertEqual(workbench_repo.product_state(2, [False]), "待選定")
        self.assertEqual(workbench_repo.product_state(2, [True, False]), "待選定")
        self.assertEqual(workbench_repo.product_state(2, [True, True]), "已選定")
        # required_outputs["image_prompt"] = 5 跟 4 版已選定：還沒到 5，不能算已選定
        # （票面明講的矛盾檢查：required_outputs 不是產出數量）。
        self.assertEqual(
            workbench_repo.product_state(5, [True, True, True, True]), "待選定",
        )
        self.assertEqual(
            workbench_repo.product_state(5, [True, True, True, True, True]), "已選定",
        )

    def test_set_table_cell_未生成_已選定需要_破折號(self):
        required_outputs = {"copy": 5}
        self.assertEqual(
            workbench_repo.set_table_cell(required_outputs, {}, "copy"),
            {"state": "未生成", "text": "未生成"},
        )
        self.assertEqual(
            workbench_repo.set_table_cell(
                required_outputs, {"copy": [True, True, False, False, False]}, "copy",
            ),
            {"state": "待選定", "text": "2／5"},
        )
        self.assertEqual(
            workbench_repo.set_table_cell(
                required_outputs, {"copy": [True] * 5}, "copy",
            ),
            {"state": "已選定", "text": "5／5"},
        )
        # 這個 set 不需要 image_prompt -> 「—」，一個規則、一個拼字。
        self.assertEqual(
            workbench_repo.set_table_cell(required_outputs, {}, "image_prompt"),
            {"state": "not_required", "text": "—"},
        )

    def test_set_state_待開始_等待決定_已完成(self):
        required_outputs = {"copy": 1, "image_prompt": 1}
        self.assertEqual(workbench_repo.set_state(required_outputs, {}), "待開始")
        self.assertEqual(
            workbench_repo.set_state(required_outputs, {"copy": [True]}), "等待決定",
        )
        self.assertEqual(
            workbench_repo.set_state(
                required_outputs, {"copy": [True], "image_prompt": [True]},
            ),
            "已完成",
        )

    def test_pack_state_待處理_進行中_待核准_已完成(self):
        self.assertEqual(workbench_repo.pack_state(None, []), "待處理")
        self.assertEqual(workbench_repo.pack_state(None, ["待開始", "待開始"]), "待處理")
        self.assertEqual(workbench_repo.pack_state(None, ["已完成", "待開始"]), "進行中")
        self.assertEqual(workbench_repo.pack_state(None, ["已完成", "已完成"]), "待核准")
        self.assertEqual(workbench_repo.pack_state("2026-09-12", ["已完成", "已完成"]), "已完成")


# -- 案例 2：submit_pack 落三組不同 required_outputs，讀回三種 cell --------------------------

class SubmitPackCellsTest(_WorkbenchPackTestBase):
    def test_three_sets_mixed_required_outputs_give_expected_cells(self):
        pack_id = self._submit_pack([
            self._one_set("1", {"copy": 5}),
            self._one_set("2", {"copy": 5, "image_prompt": 1}),
            self._one_set("3", {"image_prompt": 1}),
        ])
        briefs = self._briefs(pack_id)
        self.assertEqual(len(briefs), 3)
        by_node = {b["source_ref"]["node_key"]: b for b in briefs}

        # set "2" 選定 2 個 copy 版本（需要 5），image_prompt 沒生成過。
        set2 = by_node["2"]
        copy_outputs = workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=set2["id"],
            part="copy", generation_round=1,
            body_json=[{"sets": []} for _ in range(5)],
            coordinates_json=None, llm_task_id=None,
        )
        workbench_repo.select_version(web.conn, self.org_id, self.brand_id, copy_outputs[0]["id"])
        workbench_repo.select_version(web.conn, self.org_id, self.brand_id, copy_outputs[1]["id"])

        set1_versions = workbench_repo._versions_by_part(
            web.conn, self.org_id, self.brand_id, by_node["1"]["id"],
        )
        cell_copy_set1 = workbench_repo.set_table_cell(
            by_node["1"]["required_outputs_json"], set1_versions, "copy",
        )
        self.assertEqual(cell_copy_set1, {"state": "未生成", "text": "未生成"})

        cell_copy_set2 = workbench_repo.set_table_cell(
            by_node["2"]["required_outputs_json"],
            workbench_repo._versions_by_part(web.conn, self.org_id, self.brand_id, set2["id"]),
            "copy",
        )
        self.assertEqual(cell_copy_set2, {"state": "待選定", "text": "2／5"})

        cell_image_set3 = workbench_repo.set_table_cell(
            by_node["3"]["required_outputs_json"], {}, "image_prompt",
        )
        self.assertEqual(cell_image_set3, {"state": "未生成", "text": "未生成"})

        cell_image_set1 = workbench_repo.set_table_cell(
            by_node["1"]["required_outputs_json"], {}, "image_prompt",
        )
        self.assertEqual(cell_image_set1, {"state": "not_required", "text": "—"})


# -- 案例 3：pack_state 隨版本選定推進——待處理 -> 進行中 -> 待核准 ---------------------------

class PackStateTransitionsViaSourceTest(_WorkbenchPackTestBase):
    def test_pack_state_advances_as_versions_are_selected(self):
        source_ref = {"source_tree_task_id": "tree_transitions"}
        pack_id = self._submit_pack(
            [self._one_set("1", {"copy": 1}), self._one_set("2", {"copy": 1})],
            source_ref=source_ref,
        )
        found = workbench_module.pack_for_source(
            web.conn, self.org_id, self.brand_id, "schedule_node", source_ref
        )
        assert found is not None
        self.assertEqual(found["id"], pack_id)
        self.assertEqual(found["state"], "待處理")

        briefs = self._briefs(pack_id)
        first_outputs = workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=briefs[0]["id"],
            part="copy", generation_round=1, body_json=[{"sets": []}],
            coordinates_json=None, llm_task_id=None,
        )
        workbench_repo.select_version(
            web.conn, self.org_id, self.brand_id, first_outputs[0]["id"]
        )

        found = workbench_module.pack_for_source(
            web.conn, self.org_id, self.brand_id, "schedule_node", source_ref
        )
        assert found is not None
        self.assertEqual(found["state"], "進行中")
        self.assertEqual(found["sets_done"], 1)
        self.assertEqual(found["sets_total"], 2)

        second_outputs = workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=briefs[1]["id"],
            part="copy", generation_round=1, body_json=[{"sets": []}],
            coordinates_json=None, llm_task_id=None,
        )
        workbench_repo.select_version(
            web.conn, self.org_id, self.brand_id, second_outputs[0]["id"]
        )

        found = workbench_module.pack_for_source(
            web.conn, self.org_id, self.brand_id, "schedule_node", source_ref
        )
        assert found is not None
        self.assertEqual(found["state"], "待核准")
        self.assertEqual(found["sets_done"], 2)


# -- 案例 4：一輪 copy 寫 5 列不同 version_index；選兩版，adopted_output 回最早那個 --------

class CopyRoundVersionsTest(_WorkbenchPackTestBase):
    def test_copy_round_writes_five_versions_and_adopted_output_returns_earliest_selected(self):
        pack_id = self._submit_pack([self._one_set("1", {"copy": 5})])
        brief = self._briefs(pack_id)[0]

        rows = workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief["id"],
            part="copy", generation_round=1,
            body_json=[{"sets": [], "marker": i} for i in range(5)],
            coordinates_json=None, llm_task_id=None,
        )
        self.assertEqual(len(rows), 5)
        self.assertEqual([r["version_index"] for r in rows], [1, 2, 3, 4, 5])

        # rows[2] 先選，rows[0] 後選——「最早選定」讀的是 `adopted_at` 這個時間戳本身，
        # 不是 `version_index` 的順序，所以先選的 rows[2] 才是 `adopted_output()` 要回的
        # 那一列，即使它在清單裡排在後面。
        workbench_repo.select_version(web.conn, self.org_id, self.brand_id, rows[2]["id"])
        workbench_repo.select_version(web.conn, self.org_id, self.brand_id, rows[0]["id"])

        adopted = workbench_module.adopted_output(
            web.conn, self.org_id, self.brand_id, brief["id"], "copy"
        )
        assert adopted is not None
        self.assertEqual(adopted["id"], rows[2]["id"])
        self.assertTrue(adopted["is_adopted"])


# -- 案例 5：submit_pack 的四個拒絕情境——不落任何一列 --------------------------------------

class SubmitPackRejectionsTest(_WorkbenchPackTestBase):
    def test_empty_sets_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            self._submit_pack([])
        self.assertEqual(str(ctx.exception), "sets_unknown")

    def test_unknown_part_in_required_outputs_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            self._submit_pack([self._one_set("1", {"not_a_part": 1})])
        self.assertEqual(str(ctx.exception), "parts_unknown")

    def test_free_in_required_outputs_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            self._submit_pack([self._one_set("1", {"free": 1})])
        self.assertEqual(str(ctx.exception), "part_retired")

    def test_count_zero_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            self._submit_pack([self._one_set("1", {"copy": 0})])
        self.assertEqual(str(ctx.exception), "count_out_of_range")

    def test_rejected_pack_writes_nothing(self):
        with self.assertRaises(ValueError):
            self._submit_pack([self._one_set("1", {"copy": 5}), self._one_set("2", {"free": 1})])
        count = web.conn.execute(
            "SELECT count(*) AS n FROM workbench_pack WHERE brand_id = %s", (self.brand_id,)
        ).fetchone()["n"]
        self.assertEqual(count, 0)


# -- 案例 6：required_outputs 不是產出數量——4/5 還沒完成，第 5 個選定才完成 -----------------

class RequiredOutputsIsNotGenerationCountTest(_WorkbenchPackTestBase):
    def test_four_of_five_selected_stays_進行中_fifth_completes(self):
        source_ref = {"source_tree_task_id": "tree_five"}
        pack_id = self._submit_pack(
            [self._one_set("1", {"image_prompt": 5})], source_ref=source_ref,
        )
        brief = self._briefs(pack_id)[0]
        rows = workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief["id"],
            part="image_prompt", generation_round=1,
            body_json=[{"rendered": {}} for _ in range(5)],
            coordinates_json=None, llm_task_id=None,
        )
        for row in rows[:4]:
            workbench_repo.select_version(web.conn, self.org_id, self.brand_id, row["id"])

        found = workbench_module.pack_for_source(
            web.conn, self.org_id, self.brand_id, "schedule_node", source_ref
        )
        assert found is not None
        self.assertEqual(found["state"], "進行中")
        self.assertEqual(found["sets_done"], 0)

        workbench_repo.select_version(web.conn, self.org_id, self.brand_id, rows[4]["id"])
        found = workbench_module.pack_for_source(
            web.conn, self.org_id, self.brand_id, "schedule_node", source_ref
        )
        assert found is not None
        self.assertEqual(found["state"], "待核准")
        self.assertEqual(found["sets_done"], 1)


# -- 案例 7：租戶隔離——另一個組織的 pack id 讀不到 ------------------------------------------

class PackTenantIsolationTest(_WorkbenchPackTestBase):
    def test_pack_for_source_never_crosses_org(self):
        org_b = "org_workbench_pack_isolation"
        web.conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
            " ON CONFLICT (id) DO NOTHING",
            (org_b, org_b),
        )
        brand_b = bi_repo.create_brand(
            web.conn, org_id=org_b, name="測試品牌 B：任務包隔離", client_name=None,
            actor=ACTOR,
        )
        web.conn.commit()

        source_ref = {"source_tree_task_id": "tree_shared_id"}
        self._submit_pack([self._one_set("1", {"copy": 1})], source_ref=source_ref)

        found_a = workbench_module.pack_for_source(
            web.conn, self.org_id, self.brand_id, "schedule_node", source_ref
        )
        self.assertIsNotNone(found_a)

        found_b = workbench_module.pack_for_source(
            web.conn, org_b, brand_b["id"], "schedule_node", source_ref
        )
        self.assertIsNone(found_b)


if __name__ == "__main__":
    unittest.main()
