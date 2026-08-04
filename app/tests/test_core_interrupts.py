# -*- coding: utf-8 -*-
"""app/tests/test_core_interrupts.py — 全站打斷佇列（GitHub issue #32，決策 0025／0026）。

驗收重點：
1. 同去重鍵二次 enqueue 只留一筆（assert 自檢）。
2. 嚴重度中央分級，排序＝嚴重度為主、同級按登記順序（行動價值）。
3. 卡片內文超過 30 全形字直接擋下（DESIGN.md §20 規則 4）。
4. 待辦／已結分流；resolve 會留一筆 audit_log。
5. 資訊性項目逾期自動降級封存，不再佔待辦清單。

測試一律用虛構品牌 id，不碰真實品牌資料。
"""

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from app.core import db
from app.core import interrupts as core_interrupts


class InterruptQueueTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self._tmpdir.name) / "test.db")
        # 測試借用既有登記的 "cycle_reminder" 類別（severity=informational）即可，
        # 不需要為了測試另外登記一個假類別。

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def _enqueue(self, dedupe_key="dedupe-1", message="測試訊息，一句話。", **extra):
        return core_interrupts.enqueue(
            self.conn, category="cycle_reminder", dedupe_key=dedupe_key,
            message=message, brand_id="brn_FAKE", **extra,
        )

    def test_unknown_category_is_rejected(self):
        """模組不得自報嚴重度——類別沒登記過就直接擋下。"""
        with self.assertRaises(ValueError):
            core_interrupts.enqueue(
                self.conn, category="made_up_category", dedupe_key="x",
                message="測試", brand_id="brn_FAKE",
            )

    def test_same_dedupe_key_enqueued_twice_leaves_one_row(self):
        """同去重鍵連塞兩次只留一筆（驗收條件的 assert 自檢）。"""
        first = self._enqueue()
        self.conn.commit()
        second = self._enqueue(message="換一句話也一樣被擋。")
        self.conn.commit()

        self.assertIsNotNone(first)
        self.assertIsNone(second)  # 第二次是 no-op
        rows = self.conn.execute(
            "SELECT COUNT(*) c FROM interrupt WHERE dedupe_key = 'dedupe-1'"
        ).fetchone()
        assert rows["c"] == 1, f"同去重鍵應只留一筆，實際 {rows['c']} 筆"
        self.assertEqual(rows["c"], 1)

    def test_same_dedupe_key_different_brands_both_kept(self):
        """票 M6：兩個品牌用同一把 dedupe_key，兩則提醒都要各自留存，不能被對方吞掉
        （修憲落地體檢 19 第三節找到的品牌隔離缺陷：唯一索引原本只建在 dedupe_key 上）。"""
        first = core_interrupts.enqueue(
            self.conn, category="cycle_reminder", dedupe_key="shared-key",
            message="品牌一的提醒。", brand_id="brn_FAKE_A",
        )
        self.conn.commit()
        second = core_interrupts.enqueue(
            self.conn, category="cycle_reminder", dedupe_key="shared-key",
            message="品牌二的提醒。", brand_id="brn_FAKE_B",
        )
        self.conn.commit()

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertNotEqual(first, second)
        rows = self.conn.execute(
            "SELECT COUNT(*) c FROM interrupt WHERE dedupe_key = 'shared-key'"
        ).fetchone()
        self.assertEqual(rows["c"], 2)

    def test_message_over_limit_is_rejected(self):
        with self.assertRaises(ValueError):
            self._enqueue(message="這句話刻意寫得非常非常非常非常非常非常非常長超過三十個全形字上限")

    def test_severity_is_looked_up_not_self_reported(self):
        """enqueue() 沒有 severity 參數：值只能由 category 反查 CATEGORIES 表得出。"""
        interrupt_id = self._enqueue()
        self.conn.commit()
        row = self.conn.execute(
            "SELECT severity FROM interrupt WHERE id = ?", (interrupt_id,)
        ).fetchone()
        self.assertEqual(row["severity"], core_interrupts.CATEGORIES["cycle_reminder"]["severity"])
        self.assertEqual(row["severity"], "informational")

    def test_list_open_sorted_by_severity_then_created_at(self):
        # cycle_reminder 目前是唯一登記的類別（severity=informational），這裡至少驗證
        # 同嚴重度內按建立順序排序（同級按行動價值的退化情況：無其他類別可比較時退回時間序）。
        first = self._enqueue(dedupe_key="a", message="第一筆。")
        self.conn.commit()
        second = self._enqueue(dedupe_key="b", message="第二筆。")
        self.conn.commit()
        open_items = core_interrupts.list_open(self.conn, brand_id="brn_FAKE")
        self.assertEqual([i["id"] for i in open_items], [first, second])

    def test_resolve_moves_item_to_done_and_writes_audit(self):
        interrupt_id = self._enqueue()
        self.conn.commit()
        core_interrupts.resolve(self.conn, interrupt_id, actor="測試員")

        self.assertEqual(core_interrupts.list_open(self.conn, brand_id="brn_FAKE"), [])
        done = core_interrupts.list_done(self.conn, brand_id="brn_FAKE")
        self.assertEqual([d["id"] for d in done], [interrupt_id])
        self.assertEqual(done[0]["status"], "resolved")

        audit_row = self.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'interrupt' AND entity_id = ?",
            (interrupt_id,),
        ).fetchone()
        self.assertIsNotNone(audit_row)
        self.assertEqual(audit_row["actor"], "測試員")
        self.assertEqual(audit_row["action"], "resolve")

    def test_resolve_requires_actor(self):
        interrupt_id = self._enqueue()
        self.conn.commit()
        with self.assertRaises(ValueError):
            core_interrupts.resolve(self.conn, interrupt_id, actor="")

    def test_visible_from_hides_item_until_due(self):
        future = (date.today() + timedelta(days=5)).isoformat()
        interrupt_id = self._enqueue(visible_from=future)
        self.conn.commit()
        self.assertEqual(core_interrupts.list_open(self.conn, brand_id="brn_FAKE"), [])

        due_today = self._enqueue(dedupe_key="dedupe-2",
                                  visible_from=date.today().isoformat())
        self.conn.commit()
        open_ids = [i["id"] for i in core_interrupts.list_open(self.conn, brand_id="brn_FAKE")]
        self.assertNotIn(interrupt_id, open_ids)
        self.assertIn(due_today, open_ids)

    def test_stale_informational_item_auto_archives(self):
        """資訊性項目逾期自動降級封存，不再佔待辦清單（驗收條件）。"""
        interrupt_id = self._enqueue()
        self.conn.commit()
        stale_today = (date.today()
                       + timedelta(days=core_interrupts.STALE_AFTER_DAYS + 1)).isoformat()

        open_items = core_interrupts.list_open(self.conn, brand_id="brn_FAKE", today=stale_today)
        self.assertEqual(open_items, [])

        done = core_interrupts.list_done(self.conn, brand_id="brn_FAKE")
        self.assertEqual([d["id"] for d in done], [interrupt_id])
        self.assertEqual(done[0]["status"], "archived")

    def test_current_card_is_the_first_open_item_or_none(self):
        self.assertIsNone(core_interrupts.current_card(self.conn, brand_id="brn_FAKE"))
        interrupt_id = self._enqueue()
        self.conn.commit()
        card = core_interrupts.current_card(self.conn, brand_id="brn_FAKE")
        self.assertEqual(card["id"], interrupt_id)


if __name__ == "__main__":
    unittest.main()
