"""app/tests/test_core_interrupts.py — 全站打斷佇列（GitHub issue #32，決策 0025／0026）。

驗收重點：
1. 同去重鍵二次 enqueue 只留一筆（assert 自檢）。
2. 嚴重度中央分級，排序＝嚴重度為主、同級按登記順序（行動價值）。
3. 卡片內文超過 30 全形字直接擋下（原設計文件規則 4，已刪；見 `MAX_MESSAGE_LEN`）。
4. 待辦／已結分流；resolve 會留一筆 audit_log。
5. 資訊性項目逾期自動降級封存，不再佔待辦清單。

測試一律用虛構品牌 id，不碰真實品牌資料。
"""

import unittest
from datetime import UTC, date, datetime, timedelta
from unittest import mock

from app.core import db
from app.core import interrupts as core_interrupts
from app.core import settings as coresettings


class InterruptQueueTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        # 測試借用既有登記的 "customer_voice_extraction_done" 類別（severity=informational）
        # 即可，不需要為了測試另外登記一個假類別。conftest.py 是逐模組一個 schema（不是逐測
        # 試），這個類別本身的品牌 id／預設 dedupe_key 每個測試方法各自唯一，
        # 避免不同測試方法在同一個 schema 裡互相看到對方 enqueue 的列
        # （list_open() 沒有篩選 dedupe_key，共用品牌 id 會讓斷言看到別的測試留下的殘留）。
        self.brand_id = f"brn_FAKE_{db.new_id('t')}"
        self._default_dedupe_key = f"dedupe-{db.new_id('t')}"

    def _open(self, **kwargs):
        return core_interrupts.list_open(self.conn, org_id=db.DEV_ORG_ID, brand_id=self.brand_id,
                                         **kwargs)

    def _enqueue(self, dedupe_key=None, message="測試訊息，一句話。", **extra):
        return core_interrupts.enqueue(
            self.conn, category="customer_voice_extraction_done",
            dedupe_key=dedupe_key or self._default_dedupe_key,
            message=message, brand_id=self.brand_id, **extra, org_id=db.DEV_ORG_ID,
        )

    def test_unknown_category_is_rejected(self):
        """模組不得自報嚴重度——類別沒登記過就直接擋下。"""
        with self.assertRaises(ValueError):
            core_interrupts.enqueue(
                self.conn, category="made_up_category", dedupe_key="x",
                message="測試", brand_id=self.brand_id, org_id=db.DEV_ORG_ID,
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
            "SELECT COUNT(*) c FROM interrupt WHERE dedupe_key = %s", (self._default_dedupe_key,)
        ).fetchone()
        assert rows["c"] == 1, f"同去重鍵應只留一筆，實際 {rows['c']} 筆"
        self.assertEqual(rows["c"], 1)

    def test_same_dedupe_key_different_brands_both_kept(self):
        """票 M6：兩個品牌用同一把 dedupe_key，兩則提醒都要各自留存，不能被對方吞掉
        （修憲落地體檢 19 第三節找到的品牌隔離缺陷：唯一索引原本只建在 dedupe_key 上）。"""
        first = core_interrupts.enqueue(
            self.conn, category="customer_voice_extraction_done", dedupe_key="shared-key",
            message="品牌一的提醒。", brand_id="brn_FAKE_A", org_id=db.DEV_ORG_ID,
        )
        self.conn.commit()
        second = core_interrupts.enqueue(
            self.conn, category="customer_voice_extraction_done", dedupe_key="shared-key",
            message="品牌二的提醒。", brand_id="brn_FAKE_B", org_id=db.DEV_ORG_ID,
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
            "SELECT severity FROM interrupt WHERE id = %s", (interrupt_id,)
        ).fetchone()
        self.assertEqual(row["severity"],
                        core_interrupts.CATEGORIES["customer_voice_extraction_done"]["severity"])
        self.assertEqual(row["severity"], "informational")

    def test_list_open_sorted_by_severity_then_created_at(self):
        # 這裡固定用同一個類別，至少驗證同嚴重度內按建立順序排序
        # （同級按行動價值的退化情況：無其他類別可比較時退回時間序）。
        first = self._enqueue(dedupe_key="a", message="第一筆。")
        self.conn.commit()
        second = self._enqueue(dedupe_key="b", message="第二筆。")
        self.conn.commit()
        open_items = self._open()
        self.assertEqual([i["id"] for i in open_items], [first, second])

    def test_resolve_moves_item_to_done_and_writes_audit(self):
        interrupt_id = self._enqueue()
        self.conn.commit()
        core_interrupts.resolve(self.conn, interrupt_id, actor="測試員", org_id=db.DEV_ORG_ID)

        self.assertEqual(self._open(), [])
        done = core_interrupts.list_done(self.conn, brand_id=self.brand_id)
        self.assertEqual([d["id"] for d in done], [interrupt_id])
        self.assertEqual(done[0]["status"], "resolved")

        audit_row = self.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'interrupt' AND entity_id = %s",
            (interrupt_id,),
        ).fetchone()
        self.assertIsNotNone(audit_row)
        self.assertEqual(audit_row["actor"], "測試員")
        self.assertEqual(audit_row["action"], "resolve")

    def test_resolve_requires_actor(self):
        interrupt_id = self._enqueue()
        self.conn.commit()
        with self.assertRaises(ValueError):
            core_interrupts.resolve(self.conn, interrupt_id, actor="", org_id=db.DEV_ORG_ID)

    def _org_today(self) -> date:
        return coresettings.today_for_org(self.conn, org_id=db.DEV_ORG_ID)

    def test_visible_from_hides_item_until_due(self):
        future = (self._org_today() + timedelta(days=5)).isoformat()
        interrupt_id = self._enqueue(visible_from=future)
        self.conn.commit()
        self.assertEqual(self._open(), [])

        due_today = self._enqueue(dedupe_key="dedupe-2",
                                  visible_from=self._org_today().isoformat())
        self.conn.commit()
        open_ids = [i["id"] for i in self._open()]
        self.assertNotIn(interrupt_id, open_ids)
        self.assertIn(due_today, open_ids)

    def test_stale_informational_item_auto_archives(self):
        """資訊性項目逾期自動降級封存，不再佔待辦清單（驗收條件）。"""
        interrupt_id = self._enqueue()
        self.conn.commit()
        stale_today = (self._org_today()
                       + timedelta(days=core_interrupts.STALE_AFTER_DAYS + 1)).isoformat()

        open_items = self._open(today=stale_today)
        self.assertEqual(open_items, [])

        done = core_interrupts.list_done(self.conn, brand_id=self.brand_id)
        self.assertEqual([d["id"] for d in done], [interrupt_id])
        self.assertEqual(done[0]["status"], "archived")

    def test_settle_category_is_informational_and_never_auto_archived(self):
        """F29-I03: an unwritten period settle stays open however long it waits -- archiving it
        would silently drop that month's learnings. Other informational rows still archive."""
        self.assertEqual(
            core_interrupts.CATEGORIES["ads_triage_settle"],
            {"severity": "informational", "label": "上一期待結算"},
        )
        settle_id = core_interrupts.enqueue(
            self.conn, org_id=db.DEV_ORG_ID, brand_id=self.brand_id,
            category="ads_triage_settle", dedupe_key=f"settle-{db.new_id('t')}",
message="結算上一期，待寫進筆記本",
        )
        other_id = self._enqueue()
        self.conn.commit()
        stale_today = (self._org_today()
                       + timedelta(days=core_interrupts.STALE_AFTER_DAYS + 30)).isoformat()
        open_ids = [i["id"] for i in core_interrupts.list_open(
            self.conn, org_id=db.DEV_ORG_ID, brand_id=self.brand_id, today=stale_today)]
        self.assertEqual(open_ids, [settle_id])
        done = core_interrupts.list_done(self.conn, brand_id=self.brand_id)
        self.assertEqual([d["id"] for d in done], [other_id])

    def test_ads_triage_scale_and_refresh_categories_registered(self):
        """F25-I01: the two remaining queue kinds -- both informational (agent proposals, not
        yet losses or warnings), registered right after the F18 stop_loss/worse entries."""
        self.assertEqual(
            core_interrupts.CATEGORIES["ads_triage_scale_budget"],
            {"severity": "informational", "label": "可加預算待決定"},
        )
        self.assertEqual(
            core_interrupts.CATEGORIES["ads_triage_refresh_creative"],
            {"severity": "informational", "label": "素材待補待決定"},
        )

    def test_ads_triage_insufficient_data_category_registered(self):
        """F26-I01: the campaign-level 「資料不足」 row -- rule_warning (a rule about the data
        itself, not yet a loss), registered after the other rule_warning entries."""
        self.assertEqual(
            core_interrupts.CATEGORIES["ads_triage_insufficient_data"],
            {"severity": "rule_warning", "label": "活動資料不足待處理"},
        )

    def test_ads_triage_closeout_category_registered(self):
        """F49 Contract Q: an ended campaign's closeout row -- never done until the campaign
        closes, so never auto-archived (rule_warning, not informational), ranked right after
        `worse` (board order cleanup > worse > closeout)."""
        self.assertEqual(
            core_interrupts.CATEGORIES["ads_triage_closeout"],
            {"severity": "rule_warning", "label": "活動已結束待結案"},
        )
        order = list(core_interrupts.CATEGORIES)
        self.assertEqual(order.index("ads_triage_closeout"), order.index("ads_triage_worse") + 1)

    def test_ads_triage_cleanup_category_registered(self):
        """F28-I06: the cleanup row carries the 白花 ads that used to raise `stop_loss`, so its
        weight never drops below it -- money_loss, ranked right after stop_loss."""
        self.assertEqual(
            core_interrupts.CATEGORIES["ads_triage_cleanup"],
            {"severity": "money_loss", "label": "花錢沒效的廣告待決定"},
        )
        order = list(core_interrupts.CATEGORIES)
        self.assertEqual(order.index("ads_triage_cleanup"), order.index("ads_triage_stop_loss") + 1)

    def test_row_with_deregistered_category_still_lists_and_sorts(self):
        """票 dead-code-sweep 05：CATEGORIES 清掉了一批沒有生產呼叫端的類別，但舊 DB 列
        可能還留著已刪掉的類別字串（本測試直接寫欄位繞過 enqueue() 的登記檢查，模擬那種
        列）。_sort_key／_CATEGORY_RANK 用 .get() 給預設值，這種列不該讓 list_open() 整批
        炸掉——找不到就排最後，不是報錯（優雅缺席，同本模組其他「找不到就誠實回應」的慣例）。"""
        interrupt_id = db.new_id("itr")
        self.conn.execute(
            "INSERT INTO interrupt (id, org_id, brand_id, dedupe_key, category, severity, message,"
            " status, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, 'open', %s)",
            (interrupt_id, db.DEV_ORG_ID, self.brand_id, self._default_dedupe_key,
             "a_category_removed_from_categories", "informational", "測試訊息。", db.now_utc()),
        )
        self.conn.commit()
        open_items = self._open()
        self.assertEqual([i["id"] for i in open_items], [interrupt_id])


    def test_list_open_for_one_org_never_archives_another_orgs_rows(self):
        """F50 Contract K: the informational archive runs only for the org being listed -- one
        org's "today" is not a global UPDATE over every tenant's rows."""
        other_org = f"org_itr_{db.new_id('t')}"
        self.conn.execute("INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')",
                          (other_org, other_org))
        other_brand = f"brn_FAKE_{db.new_id('t')}"
        other_id = core_interrupts.enqueue(
            self.conn, org_id=other_org, brand_id=other_brand,
            category="customer_voice_extraction_done", dedupe_key=f"other-{db.new_id('t')}",
            message="別的組織的提醒。",
        )
        mine = self._enqueue()
        self.conn.commit()
        try:
            stale_today = (self._org_today()
                           + timedelta(days=core_interrupts.STALE_AFTER_DAYS + 1)).isoformat()
            core_interrupts.list_open(self.conn, org_id=db.DEV_ORG_ID, today=stale_today)
            status = {r["id"]: r["status"] for r in self.conn.execute(
                "SELECT id, status FROM interrupt WHERE id IN (%s, %s)", (other_id, mine))}
            self.assertEqual(status, {other_id: "open", mine: "archived"})
            self.assertNotIn(other_id, [
                r["id"] for r in core_interrupts.list_open(self.conn, org_id=db.DEV_ORG_ID)])
        finally:
            self.conn.execute("DELETE FROM interrupt WHERE org_id = %s", (other_org,))
            self.conn.execute("DELETE FROM organisation WHERE id = %s", (other_org,))
            self.conn.commit()

    def test_today_is_the_org_calendar_day(self):
        """F50 Contract K: a row visible from the org's tomorrow-in-UTC is already due at
        07:30 Taipei (23:30 UTC the day before) -- `today` is the org's, not the machine's."""
        taipei_first = date(2026, 11, 1)
        row_id = self._enqueue(visible_from=taipei_first.isoformat())
        self.conn.commit()
        with mock.patch.object(db, "now_utc",
                               return_value=datetime(2026, 10, 31, 23, 30, tzinfo=UTC)):
            open_ids = [r["id"] for r in core_interrupts.list_open(
                self.conn, org_id=db.DEV_ORG_ID, brand_id=self.brand_id, archive_stale=False)]
        self.assertIn(row_id, open_ids)


if __name__ == "__main__":
    unittest.main()
