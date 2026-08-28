"""app/tests/test_cleanup_registry.py — 品牌刪除的清理登記處（app/core/cleanup.py，
第 2 刀「清理登記處」）。

這裡守三件事：
1. 登記進去的模組，刪品牌時清除函式都會被呼叫到。
2. 其中一個模組清除時出錯，整批要回捲（Q4 單一交易、全有全無）：delete_all()
   只下 DELETE、不 commit，commit 與 rollback 都是呼叫端的事——這裡直接驗這件事。
3. register() 缺參數、或同名重複註冊，都要當場報錯。

不依賴 app.main（不 import app.main，直接用 conftest.py 逐模組建的 Postgres schema）。
cleanup._REGISTRY 是模組層全域狀態，import app.brand_intelligence.repository／
app.intake.repository 時就會自我登記「品牌智庫」「建檔精靈」——這裡用到的假模組
一律另外取名，並在 tearDown 主動移除，不污染同一個 pytest 行程裡的其他測試。
"""

import unittest

from app.brand_intelligence import repository as bi_repo
from app.core import cleanup, db


def _fake_count_fixed(label, n):
    """回傳固定筆數的假清點函式：不碰真的資料表，只用來驗證登記處有沒有把它串進來
    ——真正驗證資料表真的被清空、且沒 commit 的是靠 (b) 案的 `_fake_delete_ok`。"""
    def count(conn, brand_id):
        return [(label, n)]
    return count


def _fake_delete_fixed(label, n, call_log):
    """回傳固定筆數的假清除函式，順便把自己的名字記進 call_log，證明真的被叫到。"""
    def delete(conn, brand_id):
        call_log.append(label)
        return {label: n}
    return delete


def _fake_count(table, label):
    def count(conn, brand_id):
        n = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE brand_id = %s", (brand_id,)
        ).fetchone()["count"]
        return [(label, n)]
    return count


def _fake_delete_ok(table, label):
    """正常清除：真的下 DELETE，但不 commit（比照介面規定）。"""
    def delete(conn, brand_id):
        n = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE brand_id = %s", (brand_id,)
        ).fetchone()["count"]
        conn.execute(f"DELETE FROM {table} WHERE brand_id = %s", (brand_id,))
        return {label: n}
    return delete


def _fake_delete_boom(conn, brand_id):
    raise RuntimeError("假模組故意壞掉，測整批回捲")


def _delete_brand_like(conn, brand_id):
    """模擬 app/brand_intelligence/repository.py delete_brand() 的交易協定：
    cleanup.delete_all() 清完 -> 刪 brand 那一列 -> commit；中途出錯就 rollback
    （Q4 單一交易、全有全無）。"""
    try:
        counts = cleanup.delete_all(conn, brand_id)
        conn.execute("DELETE FROM brand WHERE id = %s", (brand_id,))
        conn.commit()
        return counts
    except Exception:
        conn.rollback()
        raise


class CleanupRegistryTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        self._registered_names = []

    def tearDown(self):
        # 假模組用完就從登記表移除，不污染其他測試（登記表是模組層全域狀態）。
        for name in self._registered_names:
            cleanup._REGISTRY.pop(name, None)

    def _register(self, name, *, count_brand, delete_brand, brand_tables=frozenset(),
                  count_product=None, delete_product=None, product_tables=frozenset()):
        # 假模組沒有真的資料表，brand_tables／product_tables 預設空集合——涵蓋率警報器
        # （機器閘門見 ticket 02-5）比對的是真實 schema，空集合不會影響它。product 三件套
        # 預設「沒有產品層資料」（count_product=None、delete_product=None、空集合），
        # 個別測試需要驗產品層行為時再覆寫。
        cleanup.register(name, count_brand=count_brand, delete_brand=delete_brand,
                         brand_tables=brand_tables, count_product=count_product,
                         delete_product=delete_product, product_tables=product_tables)
        self._registered_names.append(name)

    def _make_brand(self, name):
        return bi_repo.create_brand(self.conn, name=name, client_name=None, actor="測試員")["id"]

    # (a) 兩個假模組都登記，刪品牌時兩個的清除函式都要被呼叫到 -------------------

    def test_delete_all_calls_every_registered_module(self):
        # 注意：import bi_repo／intake_repo 時它們已經自我登記「品牌智庫」「建檔精靈」，
        # delete_all 一定也會叫到它們——所以這裡只斷言我們自己這兩個假模組真的被叫到、
        # 回傳值真的被彙整進 counts，不去斷言整個 counts 字典的完整內容（那要看當時還有
        # 哪些真的模組登記著，不是本測試該管的）。
        bid = self._make_brand("假模組雙登記品牌（清理登記處測試）")
        call_log = []
        self._register("假模組A（清理登記處測試）",
                        count_brand=_fake_count_fixed("假模組A", 1),
                        delete_brand=_fake_delete_fixed("假模組A", 1, call_log))
        self._register("假模組B（清理登記處測試）",
                        count_brand=_fake_count_fixed("假模組B", 1),
                        delete_brand=_fake_delete_fixed("假模組B", 1, call_log))

        counts = cleanup.delete_all(self.conn, bid)

        self.assertEqual(set(call_log), {"假模組A", "假模組B"})
        self.assertEqual(counts["假模組A"], 1)
        self.assertEqual(counts["假模組B"], 1)

    # (b) 其中一個模組出錯，整批回捲：品牌還在、另一個模組的資料也還在 -----------

    def test_one_module_failing_rolls_back_everything(self):
        bid = self._make_brand("假模組回捲品牌（清理登記處測試）")
        bi_repo.create_channel(self.conn, bid, actor="測試員", channel_type="website", name="測試官網")

        # 登記順序：先一個會真的下 DELETE 的正常模組，再一個故意壞掉的模組——
        # 這樣壞掉之前，正常模組的 DELETE 已經下過但還沒 commit，才驗得出回捲有效。
        self._register("假模組OK（清理登記處測試）",
                        count_brand=_fake_count("owned_channel", "假模組OK"),
                        delete_brand=_fake_delete_ok("owned_channel", "假模組OK"))
        self._register("假模組炸裂（清理登記處測試）",
                        count_brand=lambda conn, brand_id: [("假模組炸裂", 0)],
                        delete_brand=_fake_delete_boom)

        with self.assertRaises(RuntimeError):
            _delete_brand_like(self.conn, bid)

        self.assertIsNotNone(bi_repo.get_brand(self.conn, bid))
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM owned_channel WHERE brand_id = %s", (bid,)).fetchone()["count"], 1)

    # (c) register() 缺參數、或重複註冊同名，都要拋錯 --------------------------

    def test_register_requires_all_brand_args(self):
        noop_count = lambda conn, brand_id: []  # noqa: E731
        noop_delete = lambda conn, brand_id: {}  # noqa: E731
        # 這裡測的是品牌維度四參數，產品維度統一給「沒有產品層資料」的合法空值，
        # 不干擾本測試要驗的東西。
        p = dict(count_product=None, delete_product=None, product_tables=set())

        with self.assertRaises(ValueError):
            cleanup.register(None, count_brand=noop_count, delete_brand=noop_delete,
                             brand_tables=set(), **p)
        with self.assertRaises(ValueError):
            cleanup.register("", count_brand=noop_count, delete_brand=noop_delete,
                             brand_tables=set(), **p)
        with self.assertRaises(ValueError):
            cleanup.register("缺清點函式（清理登記處測試）", count_brand=None,
                             delete_brand=noop_delete, brand_tables=set(), **p)
        with self.assertRaises(ValueError):
            cleanup.register("缺清除函式（清理登記處測試）", count_brand=noop_count,
                             delete_brand=None, brand_tables=set(), **p)
        with self.assertRaises(ValueError):
            cleanup.register("缺表名宣告（清理登記處測試）", count_brand=noop_count,
                             delete_brand=noop_delete, brand_tables=None, **p)

        # 上面五次都該失敗、都沒真的登記進去，registered_names 不該多出東西。
        self.assertNotIn("缺清點函式（清理登記處測試）", cleanup.registered_names())
        self.assertNotIn("缺清除函式（清理登記處測試）", cleanup.registered_names())
        self.assertNotIn("缺表名宣告（清理登記處測試）", cleanup.registered_names())

    # (c') register() 的產品維度：宣告了表就必須給函式、給了函式就必須宣告表，
    # 兩邊對不上要當場報錯；明確傳「沒有」（空值三件套）要能成功登記 -----------------

    def test_register_requires_product_tables_param(self):
        """product_tables 本身不能整個省略——沒有產品層資料也要明確傳空集合表態。"""
        noop_count = lambda conn, brand_id: []  # noqa: E731
        noop_delete = lambda conn, brand_id: {}  # noqa: E731
        with self.assertRaises(ValueError):
            cleanup.register("缺產品層表宣告（清理登記處測試）", count_brand=noop_count,
                             delete_brand=noop_delete, brand_tables=set(),
                             count_product=None, delete_product=None, product_tables=None)
        self.assertNotIn("缺產品層表宣告（清理登記處測試）", cleanup.registered_names())

    def test_register_rejects_lopsided_product_functions(self):
        """count_product／delete_product 只給一個、沒給另一個：當場報錯。"""
        noop_count = lambda conn, brand_id: []  # noqa: E731
        noop_delete = lambda conn, brand_id: {}  # noqa: E731
        noop_count_p = lambda conn, brand_id, product_id: []  # noqa: E731
        noop_delete_p = lambda conn, brand_id, product_id: {}  # noqa: E731

        with self.assertRaises(ValueError):
            cleanup.register("只給產品清點函式（清理登記處測試）", count_brand=noop_count,
                             delete_brand=noop_delete, brand_tables=set(),
                             count_product=noop_count_p, delete_product=None,
                             product_tables=set())
        with self.assertRaises(ValueError):
            cleanup.register("只給產品清除函式（清理登記處測試）", count_brand=noop_count,
                             delete_brand=noop_delete, brand_tables=set(),
                             count_product=None, delete_product=noop_delete_p,
                             product_tables=set())
        self.assertNotIn("只給產品清點函式（清理登記處測試）", cleanup.registered_names())
        self.assertNotIn("只給產品清除函式（清理登記處測試）", cleanup.registered_names())

    def test_register_rejects_product_tables_and_functions_mismatch(self):
        """宣告了 product_tables 卻沒給函式、或給了函式卻不宣告表：兩邊對不上就報錯。"""
        noop_count = lambda conn, brand_id: []  # noqa: E731
        noop_delete = lambda conn, brand_id: {}  # noqa: E731
        noop_count_p = lambda conn, brand_id, product_id: []  # noqa: E731
        noop_delete_p = lambda conn, brand_id, product_id: {}  # noqa: E731

        with self.assertRaises(ValueError):
            cleanup.register("宣告表卻沒給函式（清理登記處測試）", count_brand=noop_count,
                             delete_brand=noop_delete, brand_tables=set(),
                             count_product=None, delete_product=None,
                             product_tables={"某張假表"})
        with self.assertRaises(ValueError):
            cleanup.register("給函式卻沒宣告表（清理登記處測試）", count_brand=noop_count,
                             delete_brand=noop_delete, brand_tables=set(),
                             count_product=noop_count_p, delete_product=noop_delete_p,
                             product_tables=set())
        self.assertNotIn("宣告表卻沒給函式（清理登記處測試）", cleanup.registered_names())
        self.assertNotIn("給函式卻沒宣告表（清理登記處測試）", cleanup.registered_names())

    def test_register_accepts_explicit_empty_product_dimension(self):
        """沒有產品層資料的模組，明確傳空值三件套要能成功登記——這是「明確表示沒有」，
        不是被免除必填。"""
        noop_count = lambda conn, brand_id: []  # noqa: E731
        noop_delete = lambda conn, brand_id: {}  # noqa: E731
        self._register("沒有產品層資料（清理登記處測試）", count_brand=noop_count,
                       delete_brand=noop_delete)
        self.assertIn("沒有產品層資料（清理登記處測試）", cleanup.registered_names())

    def test_register_accepts_matching_product_dimension(self):
        """有產品層資料的模組，表跟函式都給、也對得上，要能成功登記，且
        declared_product_tables() 讀得到宣告的表名。"""
        noop_count = lambda conn, brand_id: []  # noqa: E731
        noop_delete = lambda conn, brand_id: {}  # noqa: E731
        noop_count_p = lambda conn, brand_id, product_id: []  # noqa: E731
        noop_delete_p = lambda conn, brand_id, product_id: {}  # noqa: E731
        self._register("有產品層資料（清理登記處測試）", count_brand=noop_count,
                       delete_brand=noop_delete, count_product=noop_count_p,
                       delete_product=noop_delete_p, product_tables={"假產品表"})
        self.assertIn("有產品層資料（清理登記處測試）", cleanup.registered_names())
        self.assertEqual(
            cleanup.declared_product_tables()["有產品層資料（清理登記處測試）"],
            frozenset({"假產品表"}))

    def test_register_rejects_duplicate_name(self):
        noop_count = lambda conn, brand_id: []  # noqa: E731
        noop_delete = lambda conn, brand_id: {}  # noqa: E731
        self._register("重複命名（清理登記處測試）", count_brand=noop_count, delete_brand=noop_delete)

        with self.assertRaises(ValueError):
            cleanup.register("重複命名（清理登記處測試）", count_brand=noop_count,
                             delete_brand=noop_delete, brand_tables=set(),
                             count_product=None, delete_product=None, product_tables=set())

    # (d) 真正的 bi_repo.delete_brand()（不是上面 (b) 案自己寫的 _delete_brand_like
    # 模擬版）出錯時也要整批回捲：品牌還在、audit_log 沒有半筆刪除紀錄 ---------------

    def test_real_delete_brand_rolls_back_on_module_failure(self):
        bid = self._make_brand("真實刪除回捲品牌（清理登記處測試）")
        bi_repo.create_channel(self.conn, bid, actor="測試員", channel_type="website", name="測試官網")
        bi_repo.update_brand(self.conn, bid, name="真實刪除回捲品牌（清理登記處測試）",
                              client_name=None, status="archived", actor="測試員")

        self._register("假模組炸裂（真實刪除測試）",
                        count_brand=lambda conn, brand_id: [("假模組炸裂", 0)],
                        delete_brand=_fake_delete_boom)

        with self.assertRaises(RuntimeError):
            bi_repo.delete_brand(self.conn, bid, actor="測試員")

        # 品牌本身還在（沒被刪掉）
        self.assertIsNotNone(bi_repo.get_brand(self.conn, bid))
        # 品牌自己的子表資料（owned_channel 屬於「品牌智庫」登記模組）也還在，
        # 不是「有些模組清掉了、有些沒清掉」的半殘狀態
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM owned_channel WHERE brand_id = %s", (bid,)).fetchone()["count"], 1)
        # 沒有留下任何刪除紀錄——不能一邊資料還在、一邊卻假裝寫了稽核
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE brand_id = %s AND action = 'delete'",
                (bid,)).fetchone()["count"], 0)


if __name__ == "__main__":
    unittest.main()
