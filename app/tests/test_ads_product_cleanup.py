"""app/tests/test_ads_product_cleanup.py — 廣告模組接上刪產品清理登記處（第 6 刀）。

驗三件事（比照品牌層那套清理測試，這裡換成產品層）：
  (a) PRODUCT_CASCADE_TABLES 列出的 10 張表，刪產品後都歸零。
  (b) 產品隔離：刪一個產品，不會動到同品牌底下另一個產品的資料。
  (c) 品牌層資料（product_id 為 NULL 的列）不會被刪產品波及。

共用連線上有人在用時刪產品要被擋下，那條測試在 test_product_delete.py，本檔不重複。

不依賴 app.main，直接用這個測試模組自己的 schema（conftest.py 的 `_module_schema`
fixture 已經灌好 baseline migrations）。塞資料用本檔自己的 `_seed_table`（依
information_schema 自動推導必填欄位；原本 SQLite 版靠 `test_ads_brand_cleanup.py`
的同名工具，該檔在 02-4 被整個刪除——SQLite `PRAGMA table_info` 內部斷言測試，所以這裡
改成獨立的 Postgres 版，不依賴那個檔案；跟 test_orders_core_brand_cleanup.py 的同名
工具是同一套邏輯的重複實作，兩邊都是各自模組的清理測試自帶塞資料工具，不共用）。
"""

import unittest

from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db
from app.core.db import new_id

_TEST_PRODUCT_ID = "prd_測試用固定產品id"

# 修過：app/ads/repository.py 的 _product_cascade_scope()／_pk_columns()／_pk_where()
# 原本用 _require_id_column() 假設每張表都有單一 id 欄位，走到 campaign_cycle_goal
# （marketing_goal 的子表，複合主鍵 (campaign_cycle_id, goal_id)，沒有單一 id 欄位）
# 就一律 RuntimeError。改成 _pk_columns() 讀該表真正的主鍵（單欄位或複合皆可）當
# row handle，count/delete product data 就不再受目標關聯表拖累（route=C 02-3c）。


def _seed_table(conn, table: str, brand_id: str, fk_ids: dict, product_id: str = _TEST_PRODUCT_ID):
    """依 information_schema 自動塞一列，只填「必填又沒有預設值」的欄位；外鍵欄位接上
    fk_ids 裡對應表已經塞好的那一列 id。回傳這一列的 id（表沒有單一 id 欄位就回傳 None）。
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
        elif not notnull:
            continue
        elif "int" in coltype or "numeric" in coltype or "double" in coltype or coltype == "real":
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


class AdsProductCleanupTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()

    def _make_archived_product(self, brand_name: str, product_name: str):
        bid = bi_repo.create_brand(self.conn, name=brand_name, client_name=None,
                                    actor="測試員", org_id=db.DEV_ORG_ID)["id"]
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
        # PRODUCT_CASCADE_TABLES 是「先子後父」的刪除順序（比照品牌層那套的註解），
        # 倒著塞才會是外鍵合法的建立順序。
        for table, _label in reversed(ads_repo.PRODUCT_CASCADE_TABLES):
            row_id = _seed_table(self.conn, table, brand_id, fk_ids, product_id=product_id)
            if row_id is not None:
                fk_ids[table] = row_id

    # (a) 10 張表刪產品後都歸零 -----------------------------------------------

    def test_delete_product_clears_every_ads_table(self):
        bid, pid = self._make_archived_product("虛構茶飲品牌（第6刀刪產品測試）", "虛構茶包")
        self._seed_ads_product_tables(bid, pid)
        self.conn.commit()

        # 塞資料前先自我檢查：10 張表真的都塞進去了，不然刪完全是 0 也測不出東西。
        for table, label in ads_repo.PRODUCT_CASCADE_TABLES:
            n = self.conn.execute(
                f"SELECT COUNT(*) AS c FROM {table} WHERE product_id = %s", (pid,)).fetchone()["c"]
            self.assertEqual(n, 1, f"塞資料失敗：{table}（{label}）沒有塞進任何一列")

        bi_repo.delete_product(self.conn, bid, pid, actor="測試員")

        for table, label in ads_repo.PRODUCT_CASCADE_TABLES:
            n = self.conn.execute(
                f"SELECT COUNT(*) AS c FROM {table} WHERE product_id = %s", (pid,)).fetchone()["c"]
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
            "SELECT id FROM experiment_cell WHERE product_id = %s", (pid,)).fetchone()["id"]
        pkg = self.conn.execute(
            "SELECT id FROM publishing_package WHERE product_id = %s", (pid,)).fetchone()["id"]
        fk_ids = {"experiment_cell": cell, "publishing_package": pkg,
                  "campaign_cycle": self.conn.execute(
                      "SELECT id FROM campaign_cycle WHERE brand_id = %s", (bid,)).fetchone()["id"]}
        # 這三張都沒有 product_id 欄位，只能靠外鍵連到產品層的列。塞資料時 _seed_table
        # 已經回傳新生的 id——就是這一列的識別（SQLite 版原本繞去查 rowid 消歧義，
        # Postgres 沒有 rowid 這個系統欄位；每張表都有自己的 id 主鍵，直接用不用繞）。
        planted = {}
        for table in ("creative_brief", "external_ad_mapping", "activation_authorization"):
            row_id = _seed_table(self.conn, table, bid, fk_ids)
            if row_id is not None:
                fk_ids[table] = row_id
                planted[table] = row_id
        planted["campaign_activation"] = _seed_table(self.conn, "campaign_activation", bid, fk_ids)
        self.conn.commit()

        chain = ("creative_brief", "external_ad_mapping", "campaign_activation")
        for t in chain:
            self.assertIn(t, planted, f"塞資料失敗：{t} 沒有塞進任何一列")

        bi_repo.delete_product(self.conn, bid, pid, actor="測試員")

        for t in chain:
            self.assertIsNone(
                self.conn.execute(f"SELECT 1 FROM {t} WHERE id = %s", (planted[t],)).fetchone(),
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
                f"SELECT COUNT(*) AS c FROM {table} WHERE product_id = %s",
                (survivor,)).fetchone()["c"]
            self.assertEqual(n, 1, f"{table}（{label}）誤刪了同品牌另一個產品的資料")

    # (c) 品牌層資料（product_id 為 NULL）不受產品刪除波及 --------------------------

    def test_delete_product_keeps_brand_level_rows(self):
        bid, pid = self._make_archived_product("虛構寢具品牌（第6刀品牌層保留測試）",
                                                 "虛構枕頭")
        # marketing_goal.product_id 可為 NULL（品牌整體的行銷目標，不屬於任何單一產品）。
        ts = db.now_utc()
        self.conn.execute(
            "INSERT INTO marketing_goal (id, org_id, brand_id, product_id, objective_summary,"
            " status, created_at, updated_at) VALUES (%s, %s, %s, NULL, %s, 'active', %s, %s)",
            (new_id("gol"), db.DEV_ORG_ID, bid, "測試品牌層目標", ts, ts),
        )
        self.conn.commit()

        bi_repo.delete_product(self.conn, bid, pid, actor="測試員")

        n = self.conn.execute(
            "SELECT COUNT(*) AS c FROM marketing_goal WHERE brand_id = %s AND product_id IS NULL",
            (bid,),
        ).fetchone()["c"]
        self.assertEqual(n, 1, "品牌層資料（product_id 為 NULL）不該被刪產品波及")


if __name__ == "__main__":
    unittest.main()
