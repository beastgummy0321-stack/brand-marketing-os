# -*- coding: utf-8 -*-
"""app/tests/test_ads_brand_cleanup.py — 廣告模組接上清理登記處（第 4 刀）。

驗三件事：
  (a) BRAND_CASCADE_TABLES 列出的每一張表，刪品牌後都歸零。
  (b) 品牌隔離：刪一個品牌，不會動到另一個品牌掛在同一批表底下的資料。
  (c) 帳號層資料（ad_account／discovered_campaign）不屬於任何品牌，刪品牌時不能被清掉。

不依賴 app.main，直接用 db.connect_and_migrate 開一個乾淨的暫存 DB（比照
test_cleanup_registry.py）。
"""

import tempfile
import unittest
from pathlib import Path

from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import cleanup
from app.core import db
from app.core.db import new_id

_TEST_PRODUCT_ID = "prd_測試用固定產品id"


def _seed_table(conn, table: str, brand_id: str, fk_ids: dict, product_id: str = _TEST_PRODUCT_ID):
    """依 schema（PRAGMA table_info／foreign_key_list）自動塞一列，只填「必填又沒有
    預設值」的欄位；外鍵欄位接上 fk_ids 裡對應表已經塞好的那一列 id。

    37 張表手刻塞資料太容易漏，而且以後 app/ads 新增表也能自動涵蓋，不用回頭補寫
    塞資料的程式碼。回傳這一列的 id（表沒有單一 id 欄位——例如複合主鍵的連結表——
    就回傳 None）。

    product_id 預設用固定假值 _TEST_PRODUCT_ID（品牌層測試不在乎產品層是否存在真實
    product 列）；第 6 刀的產品層清理測試需要塞進真實 product id，才傳這個參數覆寫。
    """
    columns = conn.execute(f"PRAGMA table_info({table})").fetchall()
    fk_targets = {row[3]: row[2] for row in conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()}
    names, values = [], []
    row_id = None
    for _cid, name, coltype, notnull, dflt, _pk in columns:
        if dflt is not None:
            continue  # 有預設值就讓 DB 自己填，不必湊值
        if name == "id":
            row_id = new_id("t")
            value = row_id
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
                    "BRAND_CASCADE_TABLES／呼叫端的塞資料順序要調整，父表要排在子表前面")
            else:
                continue
        elif not notnull:
            continue
        elif "INT" in coltype.upper():
            value = 0
        elif "REAL" in coltype.upper() or "FLOA" in coltype.upper():
            value = 0.0
        else:
            value = f"test_{name}"
        names.append(name)
        values.append(value)
    conn.execute(
        f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})",
        values,
    )
    return row_id


def _seed_all_brand_tables(conn, brand_id: str) -> None:
    """把 BRAND_CASCADE_TABLES 每一張表都塞一列。倒著塞（父表先塞）：這份清單是
    「先子後父」的刪除順序，刪除順序反過來剛好就是外鍵合法的建立順序（父表一定要
    在子表引用它之前就存在）。"""
    fk_ids: dict = {}
    for table, _label in reversed(ads_repo.BRAND_CASCADE_TABLES):
        row_id = _seed_table(conn, table, brand_id, fk_ids)
        if row_id is not None:
            fk_ids[table] = row_id


class AdsBrandCleanupTest(unittest.TestCase):
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

    # (a) 每一張表刪品牌後都歸零 ------------------------------------------------

    def test_delete_brand_clears_every_ads_table(self):
        bid = self._make_archived_brand("虛構玩具品牌（第4刀刪品牌測試）")
        _seed_all_brand_tables(self.conn, bid)
        self.conn.commit()

        # 塞資料前先自我檢查：37 張表真的都塞進去了，不然刪完全是 0 也測不出東西。
        for table, label in ads_repo.BRAND_CASCADE_TABLES:
            n = self.conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE brand_id = ?", (bid,)).fetchone()[0]
            self.assertEqual(n, 1, f"塞資料失敗：{table}（{label}）沒有塞進任何一列")

        bi_repo.delete_brand(self.conn, bid, actor="測試員")

        for table, label in ads_repo.BRAND_CASCADE_TABLES:
            n = self.conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE brand_id = ?", (bid,)).fetchone()[0]
            self.assertEqual(n, 0, f"{table}（{label}）刪品牌後還留著資料，沒被清乾淨")

    # (b) 品牌隔離：刪一個品牌不動到另一個品牌 ------------------------------------

    def test_delete_brand_does_not_touch_other_brand(self):
        victim = self._make_archived_brand("被刪的虛構品牌（第4刀隔離測試）")
        survivor = self._make_archived_brand("倖存的虛構品牌（第4刀隔離測試）")
        _seed_all_brand_tables(self.conn, victim)
        _seed_all_brand_tables(self.conn, survivor)
        self.conn.commit()

        bi_repo.delete_brand(self.conn, victim, actor="測試員")

        for table, label in ads_repo.BRAND_CASCADE_TABLES:
            n = self.conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE brand_id = ?", (survivor,)).fetchone()[0]
            self.assertEqual(n, 1, f"{table}（{label}）誤刪了別的品牌的資料，品牌隔離失敗")

    # (c) 帳號層資料不屬於任何品牌，不可以被刪掉 ----------------------------------

    def test_delete_brand_keeps_account_layer_data(self):
        bid = self._make_archived_brand("測試帳號層資料保留（第4刀）")
        fk_ids: dict = {}
        acct_id = _seed_table(self.conn, "ad_account", bid, fk_ids)
        fk_ids["ad_account"] = acct_id
        campaign_id = _seed_table(self.conn, "discovered_campaign", bid, fk_ids)
        self.conn.commit()

        bi_repo.delete_brand(self.conn, bid, actor="測試員")

        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM ad_account WHERE id = ?", (acct_id,)).fetchone()[0],
            1, "ad_account 是帳號層資料，不該被刪品牌清掉")
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM discovered_campaign WHERE id = ?", (campaign_id,)).fetchone()[0],
            1, "discovered_campaign 是帳號層資料，不該被刪品牌清掉")

    # (d) 跨模組刪除順序：品牌智庫一定比廣告先登記，learning_ledger 才能在
    # campaign_cycle 之前解除／清掉，不被 FK 擋下來（見 app/ads/repository.py 檔尾說明）。

    def test_brand_intelligence_registers_before_ads(self):
        names = cleanup.registered_names()
        self.assertIn("品牌智庫", names)
        self.assertIn("廣告", names)
        self.assertLess(names.index("品牌智庫"), names.index("廣告"),
                         "「品牌智庫」要比「廣告」先登記，不然舊資料庫的 learning_ledger"
                         " REFERENCES campaign_cycle(id) 外鍵會擋下刪除順序")


if __name__ == "__main__":
    unittest.main()
