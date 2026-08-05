# -*- coding: utf-8 -*-
"""app/tests/test_orders_core_brand_cleanup.py — 訂單＋核心模組接上清理登記處（第 5 刀）。

驗四件事：
  (a) orders 9 張表 + interrupt，刪品牌後全部歸零。
  (b) llm_task 刻意不刪——使用者定案的行為，用測試釘住，以後有人手滑把它加進哪個模組的
      brand_tables 也會被抓到。
  (c) 品牌隔離：刪一個品牌，不會動到另一個品牌掛在同一批表底下的資料。
  (d) PRAGMA defer_foreign_keys = ON 真的讓外鍵檢查延到 COMMIT：刻意把刪除順序排錯
      （先刪父表 campaign_cycle 再刪子表 cycle_shopee_code），沒開 PRAGMA 會被外鍵當場
      擋下，開了才刪得掉。這條釘住本刀最核心的機制，其餘三條都只是清單有沒有補對。

不依賴 app.main，直接用 db.connect_and_migrate 開一個乾淨的暫存 DB（比照
test_ads_brand_cleanup.py）。塞資料沿用該檔已經寫好的 _seed_table 通用工具
（依 schema 自動推導必填欄位），不重寫一份。
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.brand_intelligence import repository as bi_repo
from app.core import db
from app.core import interrupts as interrupts_repo
from app.orders import repository as orders_repo
from app.tests.test_ads_brand_cleanup import _seed_table

# 這 10 張表（orders 9 張 + interrupt 1 張）是本刀的清理範圍。
_ALL_TABLES = list(orders_repo.BRAND_CASCADE_TABLES) + list(interrupts_repo.BRAND_CASCADE_TABLES)


class OrdersCoreBrandCleanupTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self._tmpdir.name) / "test.db")

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def _make_archived_brand(self, name: str) -> str:
        bid = bi_repo.create_brand(self.conn, name=name, client_name=None, actor="測試員")["id"]
        bi_repo.update_brand(self.conn, bid, name=name, client_name=None,
                              status="archived", actor="測試員")
        return bid

    def _seed_orders_and_interrupt(self, brand_id: str) -> None:
        """訂單 9 張表 + interrupt 各塞一列。cycle_shopee_code 是這批表裡唯一帶真外鍵
        的（REFERENCES campaign_cycle(id)），得先塞一列 campaign_cycle 當父列。"""
        fk_ids: dict = {}
        fk_ids["campaign_cycle"] = _seed_table(self.conn, "campaign_cycle", brand_id, fk_ids)
        for table, _label in orders_repo.BRAND_CASCADE_TABLES:
            _seed_table(self.conn, table, brand_id, fk_ids)
        _seed_table(self.conn, "interrupt", brand_id, {})

    # (a) orders 9 張 + interrupt 刪品牌後全部歸零 --------------------------------

    def test_delete_brand_clears_orders_and_interrupt_tables(self):
        bid = self._make_archived_brand("虛構寵物品牌（第5刀刪品牌測試）")
        self._seed_orders_and_interrupt(bid)
        self.conn.commit()

        for table, label in _ALL_TABLES:
            n = self.conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE brand_id = ?", (bid,)).fetchone()[0]
            self.assertEqual(n, 1, f"塞資料失敗：{table}（{label}）沒有塞進任何一列")

        bi_repo.delete_brand(self.conn, bid, actor="測試員")

        for table, label in _ALL_TABLES:
            n = self.conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE brand_id = ?", (bid,)).fetchone()[0]
            self.assertEqual(n, 0, f"{table}（{label}）刪品牌後還留著資料，沒被清乾淨")

    # (b) llm_task 刻意保留 --------------------------------------------------------

    def test_delete_brand_keeps_llm_task(self):
        """llm_task 是 AI 花費紀錄，刪品牌不刪它（使用者定案：錢已經花掉了，
        品牌刪掉不代表那筆支出沒發生，留著才答得出總花費）。這條測試釘住這個刻意行為——
        以後有人手滑把 llm_task 加進任何模組的 brand_tables，這裡會紅。"""
        bid = self._make_archived_brand("虛構寵物品牌（llm_task 保留測試）")
        task_id = _seed_table(self.conn, "llm_task", bid, {})
        self.conn.commit()

        bi_repo.delete_brand(self.conn, bid, actor="測試員")

        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM llm_task WHERE id = ?", (task_id,)).fetchone()[0],
            1, "llm_task 應該保留（AI 花費紀錄，刪品牌不代表那筆支出沒發生），卻被清掉了")

    # (c) 品牌隔離 ------------------------------------------------------------------

    def test_delete_brand_does_not_touch_other_brand(self):
        victim = self._make_archived_brand("被刪的虛構寵物品牌（第5刀隔離測試）")
        survivor = self._make_archived_brand("倖存的虛構寵物品牌（第5刀隔離測試）")
        self._seed_orders_and_interrupt(victim)
        self._seed_orders_and_interrupt(survivor)
        self.conn.commit()

        bi_repo.delete_brand(self.conn, victim, actor="測試員")

        for table, label in _ALL_TABLES:
            n = self.conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE brand_id = ?", (survivor,)).fetchone()[0]
            self.assertEqual(n, 1, f"{table}（{label}）誤刪了別的品牌的資料，品牌隔離失敗")

    # (d) PRAGMA defer_foreign_keys = ON 真的生效——本刀最重要的釘子 -------------------

    def test_delete_brand_survives_forced_wrong_module_registration_order(self):
        """cycle_shopee_code.campaign_cycle_id -> campaign_cycle(id) 是這一刀唯一一條
        真外鍵：父表 campaign_cycle 歸「廣告」清，子表 cycle_shopee_code 歸「訂單」清。
        兩個模組平常誰先登記不保證，但只要哪天「廣告」先於「訂單」登記，delete_all()
        就會先刪父表、子表還在參照它——這是本刀要防的地雷順序。

        分兩步證明：
          1. 基線——不經過 delete_brand()，用原始 DELETE 直接證明這個順序真的是地雷：
             沒有 PRAGMA 時父表先刪會被外鍵當場擋下（sqlite3.IntegrityError）。
          2. 刻意把登記表順序喬成這個地雷順序，再改叫真正的 bi_repo.delete_brand()——
             它能全身而退，靠的正是函式開頭那行 `PRAGMA defer_foreign_keys = ON`。
             拿掉那一行，這條測試會紅（驗收要求：親自證明過，不是假設）。
        """
        import app.ads.repository  # noqa: F401  # 確保「廣告」已登記
        from app.core import cleanup as core_cleanup

        bid = self._make_archived_brand("虛構寵物品牌（defer FK 順序測試）")
        fk_ids: dict = {}
        cycle_id = _seed_table(self.conn, "campaign_cycle", bid, fk_ids)
        fk_ids["campaign_cycle"] = cycle_id
        _seed_table(self.conn, "cycle_shopee_code", bid, fk_ids)
        self.conn.commit()

        # 步驟 1（基線）：沒有 PRAGMA，父表先刪、子表還在參照它 -> 立刻被外鍵擋下。
        # 這一步證明「地雷順序」是真的地雷，不是憑空想像的風險。
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("DELETE FROM campaign_cycle WHERE id = ?", (cycle_id,))
        self.conn.rollback()
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM campaign_cycle WHERE id = ?", (cycle_id,)).fetchone()[0],
            1, "被擋下的 DELETE 不該有任何效果，campaign_cycle 這一列應該還在")

        # 步驟 2：刻意把登記表順序喬成地雷順序（「廣告」排到「訂單」前面）。這是測試
        # 專用手法，直接操作 cleanup._REGISTRY——正式程式碼不會這樣做，也不該這樣做。
        registry = core_cleanup._REGISTRY
        self.assertIn("廣告", registry)
        self.assertIn("訂單", registry)
        original_items = list(registry.items())
        self.addCleanup(lambda: (registry.clear(), registry.update(original_items)))
        ads_entry = registry.pop("廣告")
        reordered = []
        for name, entry in registry.items():
            if name == "訂單":
                reordered.append(("廣告", ads_entry))
            reordered.append((name, entry))
        registry.clear()
        registry.update(reordered)
        names = core_cleanup.registered_names()
        self.assertLess(names.index("廣告"), names.index("訂單"),
                         "測試前置作業沒喬成功：「廣告」要排在「訂單」前面才逼得出地雷順序")

        # 逼出地雷順序後改叫真正的 delete_brand()：靠 PRAGMA defer_foreign_keys = ON
        # 把外鍵檢查延到 COMMIT，中途誰先誰後不重要，順利刪完整個品牌。
        bi_repo.delete_brand(self.conn, bid, actor="測試員")

        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM campaign_cycle WHERE id = ?", (cycle_id,)).fetchone()[0],
            0, "campaign_cycle 應該被刪光")
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM cycle_shopee_code WHERE campaign_cycle_id = ?",
                (cycle_id,)).fetchone()[0],
            0, "cycle_shopee_code 應該被刪光")


if __name__ == "__main__":
    unittest.main()
