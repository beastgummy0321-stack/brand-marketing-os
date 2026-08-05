# -*- coding: utf-8 -*-
"""app/tests/test_ads_product_cleanup.py — 廣告模組接上刪產品清理登記處（第 6 刀）。

驗三件事（比照 test_ads_brand_cleanup.py 品牌層那套，這裡換成產品層）：
  (a) PRODUCT_CASCADE_TABLES 列出的 10 張表，刪產品後都歸零。
  (b) 產品隔離：刪一個產品，不會動到同品牌底下另一個產品的資料。
  (c) 品牌層資料（product_id 為 NULL 的列）不會被刪產品波及。

共用連線上有人在用時刪產品要被擋下，那條測試在 test_product_delete.py（跟品牌層
test_brand_delete.py 的 test_refuses_when_connection_is_mid_transaction 對應），本檔不重複。

不依賴 app.main，直接用 db.connect_and_migrate 開一個乾淨的暫存 DB（比照
test_ads_brand_cleanup.py）。塞資料沿用該檔已經寫好的 _seed_table 通用工具（依 schema
自動推導必填欄位），不重寫一份。
"""

import tempfile
import unittest
from pathlib import Path

from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db
from app.core.db import new_id, now_iso
from app.tests.test_ads_brand_cleanup import _seed_table


class AdsProductCleanupTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self._tmpdir.name) / "test.db")

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def _make_archived_product(self, brand_name: str, product_name: str):
        bid = bi_repo.create_brand(self.conn, name=brand_name, client_name=None,
                                    actor="測試員")["id"]
        pid = bi_repo.create_product(self.conn, bid, name=product_name, actor="測試員")["id"]
        bi_repo.update_product(self.conn, bid, pid, name=product_name, status="archived",
                                actor="測試員")
        return bid, pid

    def _seed_ads_product_tables(self, brand_id: str, product_id: str) -> None:
        """PRODUCT_CASCADE_TABLES 這 10 張表本身之外，creative_variant 帶 NOT NULL 外鍵
        指向 campaign_cycle／creative_brief，這兩張不在清理範圍內（不屬於產品層、屬於
        檔期／品牌層），但得先塞一列父列，子表才插得進去。"""
        fk_ids: dict = {}
        fk_ids["campaign_cycle"] = _seed_table(self.conn, "campaign_cycle", brand_id, fk_ids,
                                                product_id=product_id)
        fk_ids["creative_brief"] = _seed_table(self.conn, "creative_brief", brand_id, fk_ids,
                                                product_id=product_id)
        # PRODUCT_CASCADE_TABLES 是「先子後父」的刪除順序（比照 _seed_all_brand_tables 的
        # 註解），倒著塞才會是外鍵合法的建立順序。
        for table, _label in reversed(ads_repo.PRODUCT_CASCADE_TABLES):
            row_id = _seed_table(self.conn, table, brand_id, fk_ids, product_id=product_id)
            if row_id is not None:
                fk_ids[table] = row_id

    def _row_counts(self, product_id: str) -> dict:
        return {t: self.conn.execute(
            f"SELECT COUNT(*) FROM {t} WHERE product_id = ?", (product_id,)).fetchone()[0]
            for t, _label in ads_repo.PRODUCT_CASCADE_TABLES}

    # (a) 10 張表刪產品後都歸零 -----------------------------------------------

    def test_delete_product_clears_every_ads_table(self):
        bid, pid = self._make_archived_product("虛構茶飲品牌（第6刀刪產品測試）", "虛構茶包")
        self._seed_ads_product_tables(bid, pid)
        self.conn.commit()

        # 塞資料前先自我檢查：10 張表真的都塞進去了，不然刪完全是 0 也測不出東西。
        for table, label in ads_repo.PRODUCT_CASCADE_TABLES:
            n = self.conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE product_id = ?", (pid,)).fetchone()[0]
            self.assertEqual(n, 1, f"塞資料失敗：{table}（{label}）沒有塞進任何一列")

        bi_repo.delete_product(self.conn, bid, pid, actor="測試員")

        for table, label in ads_repo.PRODUCT_CASCADE_TABLES:
            n = self.conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE product_id = ?", (pid,)).fetchone()[0]
            self.assertEqual(n, 0, f"{table}（{label}）刪產品後還留著資料，沒被清乾淨")

    def test_delete_product_also_clears_second_order_children(self):
        """自己沒有 product_id、卻指著產品層列的表，也要跟著清掉。

        這一類原本漏掉，因為漏表警報器只看「有 product_id 的表有沒有人清」，
        看不到「被刪的表有沒有人還指著它」。實測是拿真實資料庫複本刪產品時被
        creative_brief -> experiment_cell 與 external_ad_mapping -> publishing_package
        擋下來才發現的；而且有傳遞性——納入 external_ad_mapping 之後，指著它的
        campaign_activation 又變成新的懸空來源。這條測試釘住整條鏈。
        """
        bid, pid = self._make_archived_product("虛構茶飲品牌（第二層清理）", "虛構茶包")
        self._seed_ads_product_tables(bid, pid)

        cell = self.conn.execute(
            "SELECT id FROM experiment_cell WHERE product_id = ?", (pid,)).fetchone()[0]
        pkg = self.conn.execute(
            "SELECT id FROM publishing_package WHERE product_id = ?", (pid,)).fetchone()[0]
        fk_ids = {"experiment_cell": cell, "publishing_package": pkg,
                  "campaign_cycle": self.conn.execute(
                      "SELECT id FROM campaign_cycle WHERE brand_id = ?", (bid,)).fetchone()[0]}
        # 這三張都沒有 product_id 欄位，只能靠外鍵連到產品層的列
        # 記下自己塞的那幾列的 rowid：同一張表可能還有別的列（例如當外鍵父列先塞的
        # creative_brief），那些不指向這顆產品，本來就不該被刪，不能一起算進來。
        planted = {}
        for table in ("creative_brief", "external_ad_mapping", "activation_authorization"):
            row_id = _seed_table(self.conn, table, bid, fk_ids)
            if row_id is not None:
                fk_ids[table] = row_id
                planted[table] = self.conn.execute(
                    f"SELECT rowid FROM {table} WHERE id = ?", (row_id,)).fetchone()[0]
        _seed_table(self.conn, "campaign_activation", bid, fk_ids)
        planted["campaign_activation"] = self.conn.execute(
            "SELECT rowid FROM campaign_activation ORDER BY rowid DESC LIMIT 1").fetchone()[0]
        self.conn.commit()

        chain = ("creative_brief", "external_ad_mapping", "campaign_activation")
        for t in chain:
            self.assertIn(t, planted, f"塞資料失敗：{t} 沒有塞進任何一列")

        bi_repo.delete_product(self.conn, bid, pid, actor="測試員")

        for t in chain:
            self.assertIsNone(
                self.conn.execute(f"SELECT 1 FROM {t} WHERE rowid = ?", (planted[t],)).fetchone(),
                f"{t} 指著被刪掉的產品層列，卻沒跟著清掉——刪除會在 COMMIT 被外鍵擋下")

    # (b) 產品隔離：刪一個產品不動到同品牌另一個產品 ------------------------------

    def test_delete_product_does_not_touch_other_product(self):
        bid, victim = self._make_archived_product("虛構文具品牌（第6刀隔離測試）",
                                                    "被刪的虛構產品")
        survivor = bi_repo.create_product(self.conn, bid, name="留著的虛構產品",
                                           actor="測試員")["id"]
        self._seed_ads_product_tables(bid, victim)
        self._seed_ads_product_tables(bid, survivor)
        self.conn.commit()

        bi_repo.delete_product(self.conn, bid, victim, actor="測試員")

        for table, label in ads_repo.PRODUCT_CASCADE_TABLES:
            n = self.conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE product_id = ?",
                (survivor,)).fetchone()[0]
            self.assertEqual(n, 1, f"{table}（{label}）誤刪了同品牌另一個產品的資料")

    # (c) 品牌層資料（product_id 為 NULL）不受產品刪除波及 --------------------------

    def test_delete_product_keeps_brand_level_rows(self):
        bid, pid = self._make_archived_product("虛構寢具品牌（第6刀品牌層保留測試）",
                                                 "虛構枕頭")
        # marketing_goal.product_id 可為 NULL（品牌整體的行銷目標，不屬於任何單一產品）。
        ts = now_iso()
        self.conn.execute(
            "INSERT INTO marketing_goal (id, brand_id, product_id, objective_summary, status,"
            " created_at, updated_at) VALUES (?, ?, NULL, ?, 'active', ?, ?)",
            (new_id("gol"), bid, "測試品牌層目標", ts, ts),
        )
        self.conn.commit()

        bi_repo.delete_product(self.conn, bid, pid, actor="測試員")

        n = self.conn.execute(
            "SELECT COUNT(*) FROM marketing_goal WHERE brand_id = ? AND product_id IS NULL",
            (bid,),
        ).fetchone()[0]
        self.assertEqual(n, 1, "品牌層資料（product_id 為 NULL）不該被刪產品波及")


if __name__ == "__main__":
    unittest.main()
