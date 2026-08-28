"""app/tests/test_brand_isolation_all_tables.py — 品牌隔離全站測試（修憲落地 A2）。

見 docs/architecture-rules.md A1、鐵則 5（使用者紅線）、決策 0037 第四節第 17 點。

體檢（19-constitution-audit.md 第七節）發現：`03-data-model.md` 宣稱的「共用 repository
基底」不存在，71 處手寫 SELECT，唯一防線是住在廣告專屬測試檔（test_ads_schema.py）裡
一份手寫 38 表白名單——只涵蓋廣告模組，其他 33 張表完全沒被這份白名單看過一眼。

本檔把它升格為全站測試：
- 表清單改由 `information_schema` 反推（02-4：原本是 SQLite `sqlite_master`），不是手寫
  列舉——新增資料表自動被本測試看到。查的是這個測試模組自己的 schema
  （conftest.py 逐模組建的 Postgres schema，`current_schema()` 就是它）。
- 白名單改成「刻意不綁品牌」的**例外清單**：新表預設有罪，直到被明文列進
  BRAND_AGNOSTIC_EXCEPTIONS 並寫清楚理由，否則就必須有 NOT NULL 的 brand_id。

ADR 0027（多租戶 SaaS）：`org_id` 是更上層的租戶邊界，每張表都有——那條由 02-5 的
機器閘門守（見 ticket 02-5-gates.md）。本檔守的是既有、更細的 brand_id 邊界，
兩者不是同一件事，02-4 只做「換一套 introspection 手法」的搬遷，不重新設計檢查範圍。
"""

import unittest

from app.core import db

# 系統表／非資料表，不在「品牌資料表」的討論範圍內。Supabase CLI 自己的 migration
# 履歷表活在別的 schema（不是這個測試模組的 schema），這裡不會看到，留空集合即可。
_NON_DATA_TABLES = set()

# 刻意不綁單一品牌的表——新表要進這份清單前，先確認是不是真的該有 brand_id 卻漏寫。
# 理由逐項寫清楚，供下一個人稽核；不是「懶得填 brand_id」的藉口清單。
BRAND_AGNOSTIC_EXCEPTIONS = {
    "brand": "品牌表本身，主鍵 id 就是 brand_id，不適用「有沒有 brand_id 欄位」這個檢查",
    "organisation": "組織表本身（ADR 0027 新增的租戶根），brand 掛在 organisation 底下，"
        "不是 organisation 掛在 brand 底下，不適用這個檢查",
    "app_setting": "整台機器的全站設定（AI 金鑰、模型選擇等），不是品牌資料"
        "（core_baseline migration 註解）",
    "ad_account": "一個廣告帳號可服務多個品牌，歸屬不由帳號推導（決策 0022 第 6 點）",
    "discovered_campaign": "未認領的東西不屬於任何品牌，認領後才寫 external_ad_mapping"
        "（決策 0022 第 7 點）",
    "audit_log": "跨全部分支的稽核紀錄，brand_id 可為 NULL 表示系統級動作"
        "（core_baseline migration 註解，brand_id 欄位存在但刻意不設 NOT NULL）",
    "interrupt": "全站打斷佇列，brand_id 可為 NULL 表示跨品牌系統級提醒"
        "（core_baseline migration 註解：NULL＝跨品牌系統級）",
    "app_user": "身分表（票 03-1）：組織→使用者→品牌三層，使用者活在品牌之上、可橫跨"
        "多個組織／品牌，不適用「有沒有 brand_id」這個檢查",
    "membership": "使用者與組織的關係表（票 03-1）：綁的是 org_id，不是 brand_id——"
        "同一個道理，membership 活在品牌之上",
    "org_invite": "組織邀請（票 03-1）：綁的是 org_id，邀請的是加入組織、不是加入品牌",
}


class SiteWideBrandIsolationSchemaTest(unittest.TestCase):
    """新表預設有罪：除非明文列在 BRAND_AGNOSTIC_EXCEPTIONS，否則必須有 NOT NULL brand_id。"""

    def setUp(self):
        self.conn = db.current()

    def _all_tables(self):
        rows = self.conn.execute(
            "SELECT table_name FROM information_schema.tables"
            " WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'"
        )
        return sorted(r["table_name"] for r in rows if r["table_name"] not in _NON_DATA_TABLES)

    def _columns(self, table):
        rows = self.conn.execute(
            "SELECT column_name, is_nullable FROM information_schema.columns"
            " WHERE table_schema = current_schema() AND table_name = %s", (table,)
        )
        return {row["column_name"]: row for row in rows}

    def test_every_table_is_brand_scoped_or_an_explicit_exception(self):
        tables = self._all_tables()
        self.assertGreater(len(tables), 0, "information_schema 反推不到任何表，migration 可能沒跑")

        offenders = []
        for table in tables:
            if table in BRAND_AGNOSTIC_EXCEPTIONS:
                continue
            cols = self._columns(table)
            if "brand_id" not in cols:
                offenders.append(
                    f"{table}：沒有 brand_id 欄位，也不在例外清單裡——"
                    "若刻意不綁品牌，請加進 BRAND_AGNOSTIC_EXCEPTIONS 並寫明理由")
            elif cols["brand_id"]["is_nullable"] != "NO":
                offenders.append(f"{table}：有 brand_id 但可為 NULL，且不在例外清單裡，品牌隔離會有破口")

        self.assertEqual(
            offenders, [],
            "以下資料表未通過品牌隔離的結構檢查（鐵則 5，使用者紅線）：\n" + "\n".join(offenders),
        )

    def test_exceptions_are_still_real_not_a_dead_list(self):
        """例外清單不能變成死名單：清單裡每一項現在真的還「沒有 NOT NULL brand_id」。

        避免「哪天有人補上 brand_id 卻忘記把表從例外清單刪掉」，讓例外清單掩護真違例。
        """
        tables = set(self._all_tables())
        for table, reason in BRAND_AGNOSTIC_EXCEPTIONS.items():
            self.assertTrue(reason.strip(), f"{table} 例外清單缺理由")
            self.assertIn(table, tables, f"{table} 已不存在於資料庫，該把它從例外清單刪掉了")
            cols = self._columns(table)
            if "brand_id" in cols:
                self.assertNotEqual(
                    cols["brand_id"]["is_nullable"], "NO",
                    f"{table} 的 brand_id 已經是 NOT NULL 了，該把它從 BRAND_AGNOSTIC_EXCEPTIONS 移除"
                    "（表示它其實已經補上品牌隔離，不再需要例外）",
                )


if __name__ == "__main__":
    unittest.main()
