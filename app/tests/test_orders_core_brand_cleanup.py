"""app/tests/test_orders_core_brand_cleanup.py — 訂單＋核心模組接上清理登記處（第 5 刀）。

驗四件事：
  (a) orders 9 張表 + interrupt，刪品牌後全部歸零。
  (b) llm_task 刻意不刪——使用者定案的行為，用測試釘住，以後有人手滑把它加進哪個模組的
      brand_tables 也會被抓到。
  (c) 品牌隔離：刪一個品牌，不會動到另一個品牌掛在同一批表底下的資料。
  (d) 跨模組 id 沒有外鍵、且模組登記順序不影響刪除完整性：cycle_shopee_code.campaign_cycle_id
      指向廣告模組的 campaign_cycle，但集裝箱憲章禁止跨模組外鍵（02-2 決策 6），這欄
      刻意沒有 REFERENCES（見 orders_baseline migration 該欄位註解）。02-4 前身（SQLite）
      靠 `PRAGMA defer_foreign_keys = ON` 讓「不管哪個模組先登記」都刪得掉；Postgres 版
      壓根沒有這條外鍵可違反，這裡改成直接證明：(1) 真的沒有外鍵存在，(2) 刻意喬成地雷
      順序（廣告先於訂單登記）刪除品牌，兩張表照樣清空、不留孤兒列。

不依賴 app.main，直接用這個測試模組自己的 schema（conftest.py 的 `_module_schema`
fixture 已經灌好 baseline migrations）。塞資料用本檔自己的 `_seed_table`（依
information_schema 自動推導必填欄位；原本 SQLite 版靠 `test_ads_brand_cleanup.py`
的同名工具，該檔在 02-4 被整個刪除——SQLite `PRAGMA table_info` 內部斷言測試,
所以這裡改成獨立的 Postgres 版，不依賴那個檔案）。
"""

import unittest

from app.brand_intelligence import repository as bi_repo
from app.core import cleanup as core_cleanup
from app.core import db
from app.core import interrupts as interrupts_repo  # noqa: F401  # import 觸發它的自我登記
from app.core.db import new_id
from app.orders import repository as orders_repo

_TEST_PRODUCT_ID = "prd_測試用固定產品id"


def _seed_table(conn, table: str, brand_id: str, fk_ids: dict, product_id: str = _TEST_PRODUCT_ID):
    """依 information_schema 自動塞一列，只填「必填又沒有預設值」的欄位；外鍵欄位接上
    fk_ids 裡對應表已經塞好的那一列 id。回傳這一列的 id（表沒有單一 id 欄位就回傳 None）。

    org_id 特別處理：每張表都有、一律指向 organisation(id)，測試固定用
    `coredb.DEV_ORG_ID`（conftest.py 的 baseline seed.sql 已經塞好那一列 org_dev）。
    """
    cols = conn.execute(
        "SELECT column_name, data_type, is_nullable, column_default"
        " FROM information_schema.columns"
        " WHERE table_schema = current_schema() AND table_name = %s"
        " ORDER BY ordinal_position", (table,)
    ).fetchall()
    fk_targets = {
        row["column_name"]: row["target_table"] for row in conn.execute(
            "SELECT kcu.column_name, ccu.table_name AS target_table"
            " FROM information_schema.table_constraints tc"
            " JOIN information_schema.key_column_usage kcu"
            "   ON kcu.constraint_name = tc.constraint_name"
            "  AND kcu.table_schema = tc.table_schema"
            " JOIN information_schema.constraint_column_usage ccu"
            "   ON ccu.constraint_name = tc.constraint_name"
            "  AND ccu.table_schema = tc.table_schema"
            " WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = current_schema()"
            "   AND tc.table_name = %s", (table,)
        ).fetchall()
    }
    names, values = [], []
    row_id = None
    for col in cols:
        name, coltype, nullable, dflt = (
            col["column_name"], col["data_type"], col["is_nullable"], col["column_default"])
        if dflt is not None:
            continue  # 有預設值就讓 DB 自己填，不必湊值
        notnull = nullable == "NO"
        if name == "id":
            row_id = new_id("t")
            value = row_id
        elif name == "org_id":
            value = db.DEV_ORG_ID
        elif name == "brand_id":
            value = brand_id
        elif name == "product_id":
            value = product_id
        elif name in fk_targets:
            target = fk_targets[name]
            if target in fk_ids:
                value = fk_ids[target]
            elif notnull:
                raise AssertionError(
                    f"{table}.{name} 參照 {target}，但 {target} 還沒塞過資料——"
                    "呼叫端的塞資料順序要調整，父表要排在子表前面")
            else:
                continue
        elif name.endswith("_id") and name[:-3] in fk_ids:
            # 跨模組 id：沒有正式外鍵（集裝箱憲章禁止跨模組外鍵，見本檔檔頭），但呼叫端
            # 已經在 fk_ids 塞好同名父列——沿用同一個值，不要落到下面的通用文字分支
            # （通用分支對每個欄位都塞同一個固定字串，這欄若剛好帶 UNIQUE 索引就會撞號）。
            value = fk_ids[name[:-3]]
        elif not notnull:
            continue
        elif "int" in coltype or "numeric" in coltype:
            value = 0
        elif coltype == "boolean":
            value = False
        elif coltype == "date":
            value = db.now_utc().date()
        elif "timestamp" in coltype:
            value = db.now_utc()
        elif coltype == "jsonb":
            value = db.jsonb({})
        else:
            value = f"test_{name}"
        names.append(name)
        values.append(value)
    placeholders = ", ".join("%s" for _ in names)
    conn.execute(f"INSERT INTO {table} ({', '.join(names)}) VALUES ({placeholders})", values)
    return row_id


# 這 10 張表（orders 9 張 + interrupt 1 張）是本刀的清理範圍。
_ALL_TABLES = list(orders_repo.BRAND_CASCADE_TABLES) + list(interrupts_repo.BRAND_CASCADE_TABLES)


class OrdersCoreBrandCleanupTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()

    def _make_archived_brand(self, name: str) -> str:
        bid = bi_repo.create_brand(self.conn, name=name, client_name=None, actor="測試員", org_id=db.DEV_ORG_ID)["id"]
        bi_repo.update_brand(self.conn, bid, name=name, client_name=None,
                              status="archived", actor="測試員")
        return bid

    def _seed_orders_and_interrupt(self, brand_id: str) -> None:
        """訂單 9 張表 + interrupt 各塞一列。cycle_shopee_code 帶了個跨模組 id
        （campaign_cycle_id，沒有外鍵，見檔頭說明），得先塞一列 campaign_cycle 讓
        fk_ids 有值可接，即使資料庫層面不強制。"""
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
                f"SELECT COUNT(*) AS c FROM {table} WHERE brand_id = %s", (bid,)).fetchone()["c"]
            self.assertEqual(n, 1, f"塞資料失敗：{table}（{label}）沒有塞進任何一列")

        bi_repo.delete_brand(self.conn, bid, actor="測試員")

        for table, label in _ALL_TABLES:
            n = self.conn.execute(
                f"SELECT COUNT(*) AS c FROM {table} WHERE brand_id = %s", (bid,)).fetchone()["c"]
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
                "SELECT COUNT(*) AS c FROM llm_task WHERE id = %s", (task_id,)).fetchone()["c"],
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
                f"SELECT COUNT(*) AS c FROM {table} WHERE brand_id = %s", (survivor,)).fetchone()["c"]
            self.assertEqual(n, 1, f"{table}（{label}）誤刪了別的品牌的資料，品牌隔離失敗")

    # (d) 跨模組 id 沒有外鍵、登記順序不影響刪除完整性 -------------------------------

    def test_cross_module_column_has_no_foreign_key_and_cleanup_order_is_irrelevant(self):
        fk_row = self.conn.execute(
            "SELECT 1 AS hit FROM information_schema.table_constraints tc"
            " JOIN information_schema.key_column_usage kcu"
            "   ON kcu.constraint_name = tc.constraint_name AND kcu.table_schema = tc.table_schema"
            " WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = current_schema()"
            "   AND tc.table_name = 'cycle_shopee_code' AND kcu.column_name = 'campaign_cycle_id'"
        ).fetchone()
        self.assertIsNone(fk_row, "cycle_shopee_code.campaign_cycle_id 冒出了外鍵——"
                           "跨模組外鍵違反集裝箱憲章（02-2 決策 6），這欄故意留白")

        import app.ads.repository  # noqa: F401  # 確保「廣告」已登記

        bid = self._make_archived_brand("虛構寵物品牌（跨模組刪除順序測試）")
        fk_ids: dict = {}
        cycle_id = _seed_table(self.conn, "campaign_cycle", bid, fk_ids)
        fk_ids["campaign_cycle"] = cycle_id
        _seed_table(self.conn, "cycle_shopee_code", bid, fk_ids)
        self.conn.commit()

        # 刻意把登記表順序喬成「廣告」排到「訂單」前面（測試專用手法，直接操作
        # cleanup._REGISTRY；正式程式碼不會這樣做，也不該這樣做）。
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

        bi_repo.delete_brand(self.conn, bid, actor="測試員")

        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) AS c FROM campaign_cycle WHERE id = %s", (cycle_id,)).fetchone()["c"],
            0, "campaign_cycle 應該被刪光")
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) AS c FROM cycle_shopee_code WHERE campaign_cycle_id = %s",
                (cycle_id,)).fetchone()["c"],
            0, "cycle_shopee_code 應該被刪光")


if __name__ == "__main__":
    unittest.main()
