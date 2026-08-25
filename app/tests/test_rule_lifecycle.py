# -*- coding: utf-8 -*-
"""app/tests/test_rule_lifecycle.py — 規則有效期與重新確認（票 01-rule-expiry-reconfirm，
ADR 0012 第一節）。

驗收條件：
- 規則剛接受時仍生效（confirmed_at 就是建立時間，未超過門檻期數）。
- 超過門檻期數未重新確認的生效中規則，狀態自動退回 pending_reconfirm；不刪除、不變 inactive。
- 按「延續」後恢復生效，且確認時間更新為現在（不必重新輸入規則內容）。
- 逾期規則不再進 context_compiler 組出的生成 prompt。
- 分品牌：A 品牌調過的門檻期數不影響 B 品牌的逾期判定。

沿用 app/tests/test_rule_cards.py 的暫存 DB 慣例：真實 SQLite，不 mock。
"""

import unittest
from datetime import datetime, timedelta, timezone

from app.brand_intelligence import repository as bi_repo
from app.brand_intelligence import rule_lifecycle
from app.core import db, rule_cards
from app.llm import context_compiler

ACTOR = "測試員"


def _ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


class RuleLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        self.brand = bi_repo.create_brand(self.conn, name="虛構晨光咖啡規則有效期",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]

    def _age_rule(self, rule_id: str, days: int) -> None:
        """把 confirmed_at 直接改到過去，模擬「太久沒人重新確認」——不經任何公開函式，
        因為現有公開函式（create_rule／reconfirm_rule）本來就只會寫「現在」。"""
        self.conn.execute(
            "UPDATE rule SET confirmed_at = %s WHERE id = %s", (_ago(days), rule_id))
        self.conn.commit()

    # -- 驗收條件 1：剛接受時仍生效 -------------------------------------------

    def test_freshly_created_rule_stays_active(self):
        rule = bi_repo.create_rule(self.conn, self.bid, actor=ACTOR, rule_type="tone",
                                   content="剛接受的規則", severity="soft")
        self.assertEqual(rule["status"], "active")
        self.assertIsNotNone(rule["confirmed_at"])
        rules = bi_repo.list_rules_for_brand(self.conn, self.bid)
        self.assertIn(rule["id"], [r["id"] for r in rules])

    # -- 驗收條件 2：超過門檻期數未確認變待確認 ---------------------------------

    def test_stale_rule_flips_to_pending_reconfirm_on_list(self):
        rule = bi_repo.create_rule(self.conn, self.bid, actor=ACTOR, rule_type="tone",
                                   content="太久沒人確認的規則", severity="soft")
        self._age_rule(rule["id"], days=200)  # 6 期 × 14 天 = 84 天，200 天遠超過門檻

        rules = bi_repo.list_rules_for_brand(self.conn, self.bid)
        self.assertNotIn(rule["id"], [r["id"] for r in rules])  # 不再進生效清單

        row = self.conn.execute("SELECT * FROM rule WHERE id = %s", (rule["id"],)).fetchone()
        self.assertEqual(row["status"], "pending_reconfirm")  # 狀態變化
        self.assertIsNotNone(row)  # 沒有被刪除，該列還在

    def test_rule_just_under_threshold_stays_active(self):
        """83 天（略少於 6 期 × 14 天 = 84 天）不該被判定逾期，避免差一點就誤觸發。"""
        rule = bi_repo.create_rule(self.conn, self.bid, actor=ACTOR, rule_type="tone",
                                   content="還沒到門檻的規則", severity="soft")
        self._age_rule(rule["id"], days=83)
        rules = bi_repo.list_rules_for_brand(self.conn, self.bid)
        self.assertIn(rule["id"], [r["id"] for r in rules])

    def test_sweep_is_idempotent(self):
        rule = bi_repo.create_rule(self.conn, self.bid, actor=ACTOR, rule_type="tone",
                                   content="太久沒人確認的規則", severity="soft")
        self._age_rule(rule["id"], days=200)
        first = rule_lifecycle.sweep_expired_rules(self.conn, self.bid)
        second = rule_lifecycle.sweep_expired_rules(self.conn, self.bid)
        self.assertEqual(first, 1)
        self.assertEqual(second, 0)  # 已經翻過的列不會重複計入

    def test_pending_reconfirm_rule_disappears_from_generation_prompt(self):
        """驗收清單明文要求：逾期規則不再進生成 prompt。"""
        rule = bi_repo.create_rule(self.conn, self.bid, actor=ACTOR, rule_type="tone",
                                   content="逾期規則不該出現在提示詞裡", severity="soft")
        text_before, _, _, _ = context_compiler.compile(self.conn, self.bid)
        self.assertIn("逾期規則不該出現在提示詞裡", text_before)

        self._age_rule(rule["id"], days=200)
        text_after, _, _, _ = context_compiler.compile(self.conn, self.bid)
        self.assertNotIn("逾期規則不該出現在提示詞裡", text_after)

    def test_deactivated_rule_is_not_swept_into_pending_reconfirm(self):
        """已被人工下架（inactive）的規則不受這條自動掃描影響——只掃 status='active' 的列。"""
        rule = bi_repo.create_rule(self.conn, self.bid, actor=ACTOR, rule_type="tone",
                                   content="已下架的規則", severity="soft")
        bi_repo.deactivate_rule(self.conn, self.bid, rule["id"], actor=ACTOR)
        self._age_rule(rule["id"], days=200)
        rule_lifecycle.sweep_expired_rules(self.conn, self.bid)
        row = self.conn.execute("SELECT status FROM rule WHERE id = %s", (rule["id"],)).fetchone()
        self.assertEqual(row["status"], "inactive")  # 沒有被誤翻成 pending_reconfirm

    # -- 驗收條件 3：按延續後恢復生效 -------------------------------------------

    def test_reconfirm_restores_active_and_updates_confirmed_at_without_reentering_content(self):
        rule = bi_repo.create_rule(self.conn, self.bid, actor=ACTOR, rule_type="tone",
                                   content="待確認後延續的規則", severity="soft")
        self._age_rule(rule["id"], days=200)
        bi_repo.list_rules_for_brand(self.conn, self.bid)  # 觸發掃描，變成 pending_reconfirm
        before = self.conn.execute("SELECT * FROM rule WHERE id = %s", (rule["id"],)).fetchone()
        self.assertEqual(before["status"], "pending_reconfirm")

        after = bi_repo.reconfirm_rule(self.conn, self.bid, rule["id"], actor=ACTOR)

        self.assertEqual(after["status"], "active")
        self.assertEqual(after["content"], "待確認後延續的規則")  # 內容不必重新輸入
        self.assertGreater(after["confirmed_at"], before["confirmed_at"])  # 確認時間更新
        rules = bi_repo.list_rules_for_brand(self.conn, self.bid)
        self.assertIn(rule["id"], [r["id"] for r in rules])

    def test_reconfirm_unknown_rule_raises(self):
        with self.assertRaises(ValueError):
            bi_repo.reconfirm_rule(self.conn, self.bid, "rul_nope", actor=ACTOR)

    def test_reconfirm_writes_audit(self):
        rule = bi_repo.create_rule(self.conn, self.bid, actor=ACTOR, rule_type="tone",
                                   content="待確認後延續的規則二", severity="soft")
        bi_repo.reconfirm_rule(self.conn, self.bid, rule["id"], actor=ACTOR)
        rows = self.conn.execute(
            "SELECT * FROM audit_log WHERE brand_id = %s AND entity_type = 'rule'"
            " AND action = 'reconfirm'", (self.bid,),
        ).fetchall()
        self.assertEqual(len(rows), 1)

    def test_list_pending_reconfirm_rules(self):
        fresh = bi_repo.create_rule(self.conn, self.bid, actor=ACTOR, rule_type="tone",
                                    content="仍生效的規則", severity="soft")
        stale = bi_repo.create_rule(self.conn, self.bid, actor=ACTOR, rule_type="tone",
                                    content="待確認的規則", severity="soft")
        self._age_rule(stale["id"], days=200)

        pending = bi_repo.list_pending_reconfirm_rules(self.conn, self.bid)
        ids = [r["id"] for r in pending]
        self.assertIn(stale["id"], ids)
        self.assertNotIn(fresh["id"], ids)

    # -- 分品牌：門檻期數各自覆寫 ------------------------------------------------

    def test_brand_override_of_reconfirm_cycles_does_not_leak(self):
        other_brand = bi_repo.create_brand(self.conn, name="虛構晨光咖啡規則有效期二號",
                                           client_name=None, actor=ACTOR)
        other_bid = other_brand["id"]
        # A 品牌把門檻拉長到 100 期（1400 天），200 天不該逾期
        rule_cards.set_value(self.conn, self.bid, "rule_expiry", "reconfirm_cycles", 100.0,
                             actor=ACTOR)
        rule = bi_repo.create_rule(self.conn, self.bid, actor=ACTOR, rule_type="tone",
                                   content="A 品牌拉長門檻的規則", severity="soft")
        self._age_rule(rule["id"], days=200)
        rules = bi_repo.list_rules_for_brand(self.conn, self.bid)
        self.assertIn(rule["id"], [r["id"] for r in rules])  # A 品牌用自己拉長的門檻，還沒逾期

        # B 品牌沒改過，繼續用系統預設 6 期（84 天），200 天早該逾期
        other_rule = bi_repo.create_rule(self.conn, other_bid, actor=ACTOR, rule_type="tone",
                                         content="B 品牌沒改過門檻的規則", severity="soft")
        self.conn.execute(
            "UPDATE rule SET confirmed_at = %s WHERE id = %s", (_ago(200), other_rule["id"]))
        self.conn.commit()
        other_rules = bi_repo.list_rules_for_brand(self.conn, other_bid)
        self.assertNotIn(other_rule["id"], [r["id"] for r in other_rules])


if __name__ == "__main__":
    unittest.main()
