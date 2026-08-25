# -*- coding: utf-8 -*-
"""app/tests/test_core_orchestrator.py — 票 O1-01：調度台本體 decide()＋派工員＋決策留痕。

`OrchestratorMechanicsTest` 測 decide()／run() 本身的機制（純函數性質、去重、錯誤邊界、
連三次失敗升級、模組缺席、未知 op）：全部用臨時登記的假模組／假規則測，不叫真正的
診斷／創意／優化三個模組的 handle()（避免測試跑真的 AI 生成／耗時操作）——setUp／
tearDown 各自存還 `orchestrator.MODULES`／`RULES`，真正模組在 import 期就已經登記過，
不受影響。

`RealRuleWiringTest` 只驗證真正規則 1、2（登記在 `app/ads/diagnosis.py`／
`app/ads/theme_batch.py`）餵進 `decide()` 的 facts 會不會產出正確形狀的 Action——
`decide()` 本身不碰資料庫、不呼叫 handle()，所以這裡不需要任何資料庫或品牌 fixture。

`ModuleHandleUnknownOpTest` 驗證三個模組的 handle() 對不認得的 op 一律丟 ValueError
（ADR 0024 決議 6）。

票 O1-02 新增：`NewModuleStatusShapeTest`（開戶／同步／提案／上架／監測五個模組的
status() 在全新空品牌上照樣回傳全部 key）、`NoOpModuleHandleTest`（開戶／同步／提案／
上架四個模組沒有任何 op，收到任何 op 一律 ValueError）、`MonitorCheckPacingHandleTest`
（監測模組唯一的 op：check_pacing 會呼叫到既有 pacing.check_cycle）。
"""

import inspect
import unittest
from unittest import mock

import pytest

# BUG app/core/interrupts.py:99 — enqueue() 的去重查詢用 "brand_id IS %s"，這是 SQLite
# `IS` 運算子的寫法（可綁參數）；Postgres 的 IS 只接受 NULL/TRUE/FALSE/UNKNOWN 字面值，
# 不接受綁參數，一律 psycopg.errors.SyntaxError。凡是會走到出卡（core_interrupts.enqueue）
# 的路徑都會炸在這裡。02-4 是測試轉移票，不改 app/core/*.py，這裡標 xfail，等後續票修正
# production code（正確寫法應是 "brand_id IS NOT DISTINCT FROM %s"）。
_BUG_INTERRUPT_IS_PARAM = pytest.mark.xfail(
    strict=True,
    reason='BUG app/core/interrupts.py:99 — enqueue() dedup 查詢用 "brand_id IS %s"，'
           "Postgres 的 IS 不接受綁參數，一律 psycopg.errors.SyntaxError",
)

from app.ads import auto_sync
from app.ads import diagnosis as ads_diagnosis
from app.ads import health_lights
from app.ads import meta_mcp
from app.ads import proposal as ads_proposal
from app.ads import theme_batch
from app.ads import weekly_proposals
from app.core import db
from app.core import interrupts as core_interrupts
from app.core import orchestrator
from app.core import rule_cards
from app.intake import dispatch as intake_dispatch

ACTOR = "測試員"


class OrchestratorMechanicsTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        # 真正的診斷／創意／優化模組在 import 期已經登記過，這裡存一份快照，測試裡
        # 臨時登記的假模組／假規則在 tearDown 還原時一起清掉，不留給下一個測試。
        self._modules_snapshot = dict(orchestrator.MODULES)
        self._rules_snapshot = dict(orchestrator.RULES)
        # 專屬品牌 id（不是共用字面值）：conftest.py 的 schema 是整個模組共用一份，
        # 不是逐測試重建，共用字面值會讓不同測試方法在 decision／interrupt 表裡
        # 互相看到對方留下的列（例如某測試出了一張卡沒解掉，下一個測試斷言
        # list_open() 是空的就會被那張卡污染）。
        self.brand_id = f"brn_orch_mechanics_{db.new_id('t')}"

    def tearDown(self):
        orchestrator.MODULES.clear()
        orchestrator.MODULES.update(self._modules_snapshot)
        orchestrator.RULES.clear()
        orchestrator.RULES.update(self._rules_snapshot)

    def _register_fake_module(self, name, *, status, handle):
        orchestrator.register_module(name, status=status, handle=handle)

    def _set_autonomy(self, mode: float):
        rule_cards.set_value(self.conn, self.brand_id, "autonomy", "mode", mode, ACTOR)

    # ---- 驗收 1：decide() 是純函數 ----

    def test_decide_is_pure_and_takes_only_facts(self):
        self.assertEqual(list(inspect.signature(orchestrator.decide).parameters), ["facts"])

        def _rule(facts):
            if facts.get("fake.ready"):
                return {"module": "fake", "op": "do_it", "brand_id": facts["brand_id"],
                        "params": {}, "risk": None, "dedupe_key": "fake:purity"}
            return None

        orchestrator.register_rule("fake_rule_purity", _rule)
        facts = {"brand_id": self.brand_id, "fake.ready": True}
        first = orchestrator.decide(facts)
        second = orchestrator.decide(facts)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["module"], "fake")
        self.assertEqual(first[0]["rule_id"], "fake_rule_purity")

    # ---- 驗收 3／4：自動度閘門 ----

    @_BUG_INTERRUPT_IS_PARAM
    def test_conservative_gate_cards_instead_of_calling_handle(self):
        handle_calls = []
        self._register_fake_module(
            "fake", status=lambda conn, brand_id: {"fake.ready": True},
            handle=lambda conn, action: handle_calls.append(action) or {"ok": True})
        orchestrator.register_rule("fake_rule_conservative", lambda facts: (
            {"module": "fake", "op": "do_it", "brand_id": facts["brand_id"], "params": {},
             "risk": "asset", "dedupe_key": "fake:conservative"}
            if facts.get("fake.ready") else None))
        self._set_autonomy(1.0)

        result = orchestrator.run(self.conn, self.brand_id, actor=ACTOR)

        self.assertEqual(handle_calls, [])
        outcome = next(o for o in result["outcomes"] if o["dedupe_key"] == "fake:conservative")
        self.assertEqual(outcome["outcome"], "carded")
        row = self.conn.execute(
            "SELECT outcome FROM decision WHERE brand_id = %s AND dedupe_key = %s",
            (self.brand_id, "fake:conservative")).fetchone()
        self.assertEqual(row["outcome"], "carded")
        open_cards = core_interrupts.list_open(self.conn, brand_id=self.brand_id)
        self.assertTrue(any(c["category"] == "orchestrator_pending" for c in open_cards))

    def test_handsoff_gate_calls_handle_and_writes_auto_done(self):
        handle_calls = []
        self._register_fake_module(
            "fake", status=lambda conn, brand_id: {"fake.ready": True},
            handle=lambda conn, action: handle_calls.append(action) or {"ok": True})
        orchestrator.register_rule("fake_rule_handsoff", lambda facts: (
            {"module": "fake", "op": "do_it", "brand_id": facts["brand_id"], "params": {},
             "risk": "asset", "dedupe_key": "fake:handsoff"}
            if facts.get("fake.ready") else None))
        self._set_autonomy(2.0)

        result = orchestrator.run(self.conn, self.brand_id, actor=ACTOR)

        self.assertEqual(len(handle_calls), 1)
        outcome = next(o for o in result["outcomes"] if o["dedupe_key"] == "fake:handsoff")
        self.assertEqual(outcome["outcome"], "auto_done")

    def test_risk_none_action_always_auto_regardless_of_autonomy(self):
        """規則 1 的形狀（risk 無）：即使保守檔也一律自動做，不出卡。"""
        handle_calls = []
        self._register_fake_module(
            "fake", status=lambda conn, brand_id: {"fake.ready": True},
            handle=lambda conn, action: handle_calls.append(action) or {"ok": True})
        orchestrator.register_rule("fake_rule_riskless", lambda facts: (
            {"module": "fake", "op": "do_it", "brand_id": facts["brand_id"], "params": {},
             "risk": None, "dedupe_key": "fake:riskless"}
            if facts.get("fake.ready") else None))
        self._set_autonomy(1.0)  # 保守檔

        result = orchestrator.run(self.conn, self.brand_id, actor=ACTOR)

        self.assertEqual(len(handle_calls), 1)
        outcome = next(o for o in result["outcomes"] if o["dedupe_key"] == "fake:riskless")
        self.assertEqual(outcome["outcome"], "auto_done")

    # ---- 驗收 5：去重 ----

    def test_dedupe_skips_second_run_for_same_key(self):
        handle_calls = []
        self._register_fake_module(
            "fake", status=lambda conn, brand_id: {"fake.ready": True},
            handle=lambda conn, action: handle_calls.append(action) or {"ok": True})
        orchestrator.register_rule("fake_rule_dedupe", lambda facts: (
            {"module": "fake", "op": "do_it", "brand_id": facts["brand_id"], "params": {},
             "risk": None, "dedupe_key": "fake:dedupe"}
            if facts.get("fake.ready") else None))

        orchestrator.run(self.conn, self.brand_id, actor=ACTOR)
        orchestrator.run(self.conn, self.brand_id, actor=ACTOR)

        self.assertEqual(len(handle_calls), 1)
        row = self.conn.execute(
            "SELECT COUNT(*) c FROM decision WHERE brand_id = %s AND dedupe_key = %s",
            (self.brand_id, "fake:dedupe")).fetchone()
        self.assertEqual(row["c"], 1)

    # ---- 驗收 6：錯誤邊界 ----

    def test_one_action_failing_does_not_block_the_other(self):
        good_calls = []

        def _bad_handle(conn, action):
            raise RuntimeError("炸掉了")

        self._register_fake_module(
            "fake_bad", status=lambda conn, brand_id: {"bad.ready": True}, handle=_bad_handle)
        self._register_fake_module(
            "fake_good", status=lambda conn, brand_id: {"good.ready": True},
            handle=lambda conn, action: good_calls.append(action) or {"ok": True})
        orchestrator.register_rule("fake_rule_bad", lambda facts: (
            {"module": "fake_bad", "op": "do_it", "brand_id": facts["brand_id"], "params": {},
             "risk": None, "dedupe_key": "fake:bad"} if facts.get("bad.ready") else None))
        orchestrator.register_rule("fake_rule_good", lambda facts: (
            {"module": "fake_good", "op": "do_it", "brand_id": facts["brand_id"], "params": {},
             "risk": None, "dedupe_key": "fake:good"} if facts.get("good.ready") else None))

        result = orchestrator.run(self.conn, self.brand_id, actor=ACTOR)

        self.assertEqual(len(good_calls), 1)
        bad_outcome = next(o for o in result["outcomes"] if o["dedupe_key"] == "fake:bad")
        self.assertEqual(bad_outcome["outcome"], "failed")
        row = self.conn.execute(
            "SELECT error_text FROM decision WHERE brand_id = %s AND dedupe_key = %s",
            (self.brand_id, "fake:bad")).fetchone()
        self.assertIn("炸掉了", row["error_text"])
        good_outcome = next(o for o in result["outcomes"] if o["dedupe_key"] == "fake:good")
        self.assertEqual(good_outcome["outcome"], "auto_done")

    # ---- 驗收 7：連三次失敗升級出卡 ----

    @_BUG_INTERRUPT_IS_PARAM
    def test_third_consecutive_failure_escalates_to_inbox(self):
        def _always_fails(conn, action):
            raise RuntimeError("still broken")

        self._register_fake_module(
            "fake", status=lambda conn, brand_id: {"fake.ready": True}, handle=_always_fails)
        orchestrator.register_rule("fake_rule_escalate", lambda facts: (
            {"module": "fake", "op": "do_it", "brand_id": facts["brand_id"], "params": {},
             "risk": None, "dedupe_key": "fake:escalate"} if facts.get("fake.ready") else None))

        for _ in range(3):
            orchestrator.run(self.conn, self.brand_id, actor=ACTOR)

        row = self.conn.execute(
            "SELECT attempt_count, outcome FROM decision WHERE brand_id = %s AND dedupe_key = %s",
            (self.brand_id, "fake:escalate")).fetchone()
        self.assertEqual(row["attempt_count"], 3)
        self.assertEqual(row["outcome"], "failed")
        open_cards = core_interrupts.list_open(self.conn, brand_id=self.brand_id)
        self.assertTrue(any(c["category"] == "orchestrator_pending" for c in open_cards))

    def test_first_and_second_failure_do_not_escalate_yet(self):
        def _always_fails(conn, action):
            raise RuntimeError("still broken")

        self._register_fake_module(
            "fake", status=lambda conn, brand_id: {"fake.ready": True}, handle=_always_fails)
        orchestrator.register_rule("fake_rule_no_escalate_yet", lambda facts: (
            {"module": "fake", "op": "do_it", "brand_id": facts["brand_id"], "params": {},
             "risk": None, "dedupe_key": "fake:not_yet"} if facts.get("fake.ready") else None))

        orchestrator.run(self.conn, self.brand_id, actor=ACTOR)
        orchestrator.run(self.conn, self.brand_id, actor=ACTOR)

        open_cards = core_interrupts.list_open(self.conn, brand_id=self.brand_id)
        self.assertEqual(open_cards, [])

    # ---- 驗收 8：模組缺席（拔根測試的程式版） ----

    def test_missing_module_does_not_crash_run_other_rules_still_fire(self):
        good_calls = []
        self._register_fake_module(
            "fake_missing", status=lambda conn, brand_id: {}, handle=lambda conn, action: {"ok": True})
        self._register_fake_module(
            "fake_present", status=lambda conn, brand_id: {"present.ready": True},
            handle=lambda conn, action: good_calls.append(action) or {"ok": True})
        # 故意不讀 facts，永遠對 fake_missing 產生一個 Action——模擬「模組已經被拔掉，
        # 但還有殘留規則會叫到它」的情境。
        orchestrator.register_rule("fake_rule_targets_missing_module", lambda facts: {
            "module": "fake_missing", "op": "do_it", "brand_id": facts["brand_id"], "params": {},
            "risk": None, "dedupe_key": "fake:missing"})
        orchestrator.register_rule("fake_rule_present", lambda facts: (
            {"module": "fake_present", "op": "do_it", "brand_id": facts["brand_id"],
             "params": {}, "risk": None, "dedupe_key": "fake:present"}
            if facts.get("present.ready") else None))

        del orchestrator.MODULES["fake_missing"]

        result = orchestrator.run(self.conn, self.brand_id, actor=ACTOR)  # 不炸

        self.assertEqual(len(good_calls), 1)
        missing_outcome = next(o for o in result["outcomes"] if o["dedupe_key"] == "fake:missing")
        self.assertEqual(missing_outcome["outcome"], "failed")
        present_outcome = next(o for o in result["outcomes"] if o["dedupe_key"] == "fake:present")
        self.assertEqual(present_outcome["outcome"], "auto_done")

    # ---- 驗收 9：未知 op ----

    def test_unknown_op_raises_value_error_caught_by_error_boundary(self):
        def _handle(conn, action):
            if action["op"] != "known_op":
                raise ValueError(f"不認得的 op：{action['op']}")
            return {"ok": True}

        self._register_fake_module(
            "fake", status=lambda conn, brand_id: {"fake.ready": True}, handle=_handle)
        orchestrator.register_rule("fake_rule_unknown_op", lambda facts: (
            {"module": "fake", "op": "unknown_op", "brand_id": facts["brand_id"], "params": {},
             "risk": None, "dedupe_key": "fake:unknown_op"} if facts.get("fake.ready") else None))

        result = orchestrator.run(self.conn, self.brand_id, actor=ACTOR)

        outcome = next(o for o in result["outcomes"] if o["dedupe_key"] == "fake:unknown_op")
        self.assertEqual(outcome["outcome"], "failed")
        self.assertIn("不認得", outcome["error"])


class RealRuleWiringTest(unittest.TestCase):
    """規則 1、2（登記在 app/ads/diagnosis.py／app/ads/theme_batch.py）餵進
    decide() 的形狀驗證——decide() 不碰資料庫、不呼叫 handle()，不需要任何 DB fixture。"""

    def test_rule1_fires_when_synced_and_unread(self):
        facts = {
            "brand_id": "brn_x", "data.synced": True,
            "diagnosis.cycle_id": "ccy_1", "diagnosis.reading_ready": False,
            "diagnosis.bottleneck_primary": None,
            "optimize.cards_open": 0, "optimize.cycle_id": None,
        }
        actions = orchestrator.decide(facts)
        diagnosis_actions = [a for a in actions if a["module"] == "diagnosis"]
        self.assertEqual(len(diagnosis_actions), 1)
        action = diagnosis_actions[0]
        self.assertEqual(action["op"], "run_reading")
        self.assertIsNone(action["risk"])
        self.assertEqual(action["params"]["cycle_id"], "ccy_1")
        self.assertEqual(action["dedupe_key"], "run_reading:ccy_1")

    def test_rule1_does_not_fire_when_already_read_or_not_synced(self):
        already_read = {"brand_id": "brn_x", "data.synced": True,
                        "diagnosis.cycle_id": "ccy_1", "diagnosis.reading_ready": True}
        not_synced = {"brand_id": "brn_x", "data.synced": False,
                     "diagnosis.cycle_id": "ccy_1", "diagnosis.reading_ready": False}
        for facts in (already_read, not_synced):
            actions = orchestrator.decide(facts)
            self.assertFalse(any(a["module"] == "diagnosis" for a in actions))

    def test_rule2_fires_on_ctr_bottleneck_and_targets_creative_module(self):
        """票 O1-01 回報重點：add_theme 實際登記在『創意』模組
        （app/ads/theme_batch.py），不是票面原本猜的『優化』（weekly_proposals.py）。"""
        facts = {"brand_id": "brn_x", "diagnosis.bottleneck_primary": "ctr",
                "optimize.cycle_id": "ccy_2"}
        actions = orchestrator.decide(facts)
        creative_actions = [a for a in actions if a["module"] == "creative"]
        self.assertEqual(len(creative_actions), 1)
        action = creative_actions[0]
        self.assertEqual(action["op"], "add_theme")
        self.assertEqual(action["risk"], "asset")
        self.assertEqual(action["params"]["cycle_id"], "ccy_2")
        self.assertFalse(any(a["module"] == "optimize" for a in actions))

    def test_rule2_does_not_fire_when_bottleneck_is_not_ctr(self):
        facts = {"brand_id": "brn_x", "diagnosis.bottleneck_primary": "cpm",
                "optimize.cycle_id": "ccy_2"}
        actions = orchestrator.decide(facts)
        self.assertFalse(any(a["module"] == "creative" for a in actions))


class ModuleHandleUnknownOpTest(unittest.TestCase):
    """兩個模組（＋『優化』的沒有 op 版）收到不認得的 op 一律丟 ValueError
    （ADR 0024 決議 6）。三個 handle() 都在檢查 op 之後才碰資料庫，conn 傳 None 安全。"""

    def test_diagnosis_handle_rejects_unknown_op(self):
        with self.assertRaises(ValueError):
            ads_diagnosis.handle(None, {"op": "nope", "brand_id": "x", "params": {}})

    def test_creative_handle_rejects_unknown_op(self):
        with self.assertRaises(ValueError):
            theme_batch.handle(None, {"op": "nope", "brand_id": "x", "params": {}})

    def test_optimize_handle_rejects_any_op(self):
        with self.assertRaises(ValueError):
            weekly_proposals.handle(None, {"op": "add_theme", "brand_id": "x", "params": {}})


class NewModuleStatusShapeTest(unittest.TestCase):
    """票 O1-02：五個新模組的 status(conn, brand_id) 在『全新空品牌』上要照樣回傳全部
    key（值可為 None／0／False），不得少 key、不得丟例外。"""

    def setUp(self):
        self.conn = db.current()
        self.brand_id = "brn_o1_02_empty"  # 全新空品牌：資料庫裡沒有任何一列屬於它

    def test_intake_status_returns_all_keys(self):
        self.assertEqual(
            intake_dispatch.status(self.conn, self.brand_id),
            {"intake.draft_open": False, "intake.completed": False,
             "intake.pending_items": 0, "intake.products_count": 0},
        )

    def test_sync_status_returns_all_keys(self):
        self.assertEqual(
            auto_sync.status(self.conn, self.brand_id),
            {"sync.meta_configured": False, "sync.ga4_configured": False},
        )

    def test_proposal_status_returns_all_keys(self):
        self.assertEqual(
            ads_proposal.status(self.conn, self.brand_id),
            {"proposal.cycle_id": None, "proposal.plan_ready": False,
             "proposal.approved": False},
        )

    def test_publish_status_returns_all_keys(self):
        self.assertEqual(
            meta_mcp.status(self.conn, self.brand_id),
            {"publish.cycle_id": None, "publish.packages_total": 0,
             "publish.packages_mapped": 0, "publish.live": False},
        )

    def test_monitor_status_returns_all_keys(self):
        self.assertEqual(
            health_lights.status(self.conn, self.brand_id),
            {"monitor.cycle_id": None, "monitor.spend_rate_light": None,
             "monitor.red_lights": 0},
        )


class NoOpModuleHandleTest(unittest.TestCase):
    """intake／sync／proposal／publish 四個模組的 handle() 沒有任何 op，收到任何 op
    一律丟 ValueError（ADR 0024 決議 6，票 O1-02 使用者裁決）。"""

    def test_intake_handle_rejects_any_op(self):
        with self.assertRaises(ValueError):
            intake_dispatch.handle(None, {"op": "沒這個op", "brand_id": "x", "params": {}})

    def test_sync_handle_rejects_any_op(self):
        with self.assertRaises(ValueError):
            auto_sync.handle(None, {"op": "沒這個op", "brand_id": "x", "params": {}})

    def test_proposal_handle_rejects_any_op(self):
        with self.assertRaises(ValueError):
            ads_proposal.handle(None, {"op": "沒這個op", "brand_id": "x", "params": {}})

    def test_publish_handle_rejects_any_op(self):
        with self.assertRaises(ValueError):
            meta_mcp.handle(None, {"op": "沒這個op", "brand_id": "x", "params": {}})

    def test_monitor_handle_rejects_unknown_op(self):
        with self.assertRaises(ValueError):
            health_lights.handle(None, {"op": "沒這個op", "brand_id": "x", "params": {}})


class MonitorCheckPacingHandleTest(unittest.TestCase):
    """monitor.handle() 收 check_pacing 會呼叫到既有 pacing.check_cycle（不重寫第二套
    步調判定）；沒有檔期時回 {"interrupt_id": None} 不炸。"""

    def setUp(self):
        self.conn = db.current()
        self.brand_id = "brn_o1_02_pacing"

    def test_check_pacing_calls_pacing_check_cycle(self):
        with mock.patch.object(health_lights.ads_pacing, "check_cycle",
                               return_value="int_fake") as fake_check:
            result = health_lights.handle(
                self.conn, {"op": "check_pacing", "brand_id": self.brand_id,
                           "params": {"cycle_id": "ccy_x"}})
        fake_check.assert_called_once_with(self.conn, self.brand_id, "ccy_x")
        self.assertEqual(result, {"interrupt_id": "int_fake"})

    def test_check_pacing_no_cycle_returns_none_without_raising(self):
        result = health_lights.handle(
            self.conn, {"op": "check_pacing", "brand_id": self.brand_id,
                       "params": {"cycle_id": "ccy_missing"}})
        self.assertEqual(result, {"interrupt_id": None})


if __name__ == "__main__":
    unittest.main()
