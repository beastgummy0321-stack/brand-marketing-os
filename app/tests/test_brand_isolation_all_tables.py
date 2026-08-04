# -*- coding: utf-8 -*-
"""app/tests/test_brand_isolation_all_tables.py — 品牌隔離全站測試（修憲落地 A2）。

見 docs/architecture-rules.md A1、鐵則 5（使用者紅線）、決策 0037 第四節第 17 點。

體檢（19-constitution-audit.md 第七節）發現：`03-data-model.md` 宣稱的「共用 repository
基底」不存在，71 處手寫 SELECT，唯一防線是住在廣告專屬測試檔（test_ads_schema.py）裡
一份手寫 38 表白名單——只涵蓋廣告模組，其他 33 張表完全沒被這份白名單看過一眼。

本檔把它升格為全站測試：
- 表清單改由 `sqlite_master` 反推，不是手寫列舉——新增資料表自動被本測試看到。
- 白名單改成「刻意不綁品牌」的**例外清單**：新表預設有罪，直到被明文列進
  BRAND_AGNOSTIC_EXCEPTIONS 並寫清楚理由，否則就必須有 NOT NULL 的 brand_id。
"""

import tempfile
import unittest
from pathlib import Path

from app.core import db

# 系統表／非資料表，不在「品牌資料表」的討論範圍內。
_NON_DATA_TABLES = {"schema_migrations"}

# 刻意不綁單一品牌的表——新表要進這份清單前，先確認是不是真的該有 brand_id 卻漏寫。
# 理由逐項寫清楚，供下一個人稽核；不是「懶得填 brand_id」的藉口清單。
BRAND_AGNOSTIC_EXCEPTIONS = {
    "brand": "品牌表本身，主鍵 id 就是 brand_id，不適用「有沒有 brand_id 欄位」這個檢查",
    "app_setting": "整台機器的全站設定（AI 金鑰、模型選擇等），不是品牌資料"
        "（migration 0002_app_setting.sql 註解）",
    "rule_card_value": "平台層級的判定門檻（例如素材疲勞頻率），不分品牌"
        "（migration 0003_rule_card.sql 註解）",
    "ad_account": "一個廣告帳號可服務多個品牌，歸屬不由帳號推導（決策 0022 第 6 點）",
    "discovered_campaign": "未認領的東西不屬於任何品牌，認領後才寫 external_ad_mapping"
        "（決策 0022 第 7 點）",
    "audit_log": "跨全部分支的稽核紀錄，brand_id 可為 NULL 表示系統級動作"
        "（migration 0001_core.sql 註解，brand_id 欄位存在但刻意不設 NOT NULL）",
    "interrupt": "全站打斷佇列，brand_id 可為 NULL 表示跨品牌系統級提醒"
        "（migration 0006_interrupts.sql 註解：「NULL＝跨品牌系統級」）",
}


class SiteWideBrandIsolationSchemaTest(unittest.TestCase):
    """新表預設有罪：除非明文列在 BRAND_AGNOSTIC_EXCEPTIONS，否則必須有 NOT NULL brand_id。"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self._tmpdir.name) / "test.db")

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def _all_tables(self):
        rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
        return sorted(r["name"] for r in rows if r["name"] not in _NON_DATA_TABLES)

    def _columns(self, table):
        return {row["name"]: row for row in self.conn.execute(f"PRAGMA table_info({table})")}

    def test_every_table_is_brand_scoped_or_an_explicit_exception(self):
        tables = self._all_tables()
        self.assertGreater(len(tables), 0, "sqlite_master 反推不到任何表，migration 可能沒跑")

        offenders = []
        for table in tables:
            if table in BRAND_AGNOSTIC_EXCEPTIONS:
                continue
            cols = self._columns(table)
            if "brand_id" not in cols:
                offenders.append(
                    f"{table}：沒有 brand_id 欄位，也不在例外清單裡——"
                    "若刻意不綁品牌，請加進 BRAND_AGNOSTIC_EXCEPTIONS 並寫明理由"
                )
            elif cols["brand_id"]["notnull"] != 1:
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
                    cols["brand_id"]["notnull"], 1,
                    f"{table} 的 brand_id 已經是 NOT NULL 了，該把它從 BRAND_AGNOSTIC_EXCEPTIONS 移除"
                    "（表示它其實已經補上品牌隔離，不再需要例外）",
                )


if __name__ == "__main__":
    unittest.main()
