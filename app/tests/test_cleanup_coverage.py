# -*- coding: utf-8 -*-
"""app/tests/test_cleanup_coverage.py — 漏表警報器（第 3 刀）。

刪品牌／刪產品時，資料表沒人清就會變成孤兒列（指向不存在的品牌）。這種錯不會當場
報錯，只會讓資料悄悄髒掉——除非有東西盯著。本檔就是那個東西。

做法：從真實 migrations 建出來的資料庫直接讀 schema，列出所有帶 brand_id／
product_id 的表，跟「有人宣告會清掉的表」比對。差集必須完全落在下面的已知缺口清單裡。

兩邊都會叫，這是重點：
  1. 冒出新的沒人認領的表 -> 測試紅（防止未來新增表時又漏掉）。
  2. 清單裡有某條其實已經被清掉了 -> 測試也紅（防止清單變成掩護新缺口的死名單，
     借用 test_architecture_boundaries.py 的 KNOWN_SQL_VIOLATIONS 同一招）。

補完一個模組的清理，就從清單裡把對應的表刪掉，測試會告訴你有沒有補乾淨。
"""

import tempfile
import unittest
from pathlib import Path

from app.ads import repository as ads_repo  # noqa: F401  # import 才會觸發它的自我登記
from app.brand_intelligence import repository as repo  # noqa: F401  # 同上，觸發它的自我登記
from app.core import calendar_dismiss as core_calendar_dismiss  # noqa: F401  # 同上，觸發它的自我登記
from app.core import campaign_skip as core_campaign_skip  # noqa: F401  # 同上，觸發它的自我登記
from app.core import cleanup, db
from app.core import interrupts as core_interrupts  # noqa: F401  # 同上，觸發它的自我登記
from app.core import rule_cards as core_rule_cards  # noqa: F401  # 同上，觸發它的自我登記
from app.intake import repository as intake_repo  # noqa: F401  # import 才會觸發它的自我登記
from app.orders import repository as orders_repo  # noqa: F401  # 同上，觸發它的自我登記

# 刻意保留、不隨品牌一起刪的表，附理由。加東西進這裡要想清楚。
DELIBERATELY_KEPT = {
    "audit_log": "稽核軌跡。刪除品牌那筆紀錄本身就存在這裡，清掉就沒有證據可查（決策 0015）。",
    "llm_task": "AI 花費紀錄（每次呼叫花多少錢）。品牌刪掉不代表那筆支出沒發生，錢已經花了；"
                "留著才答得出「這個帳號總共花多少錢」（app/core/settings.py 會 SUM 它）。",
    "channel_tracking_check": "追蹤健檢結果快取（票 T0）。app/ads/repository.py 已頂到"
                "docs/tech-debt.md 凍結行數上限，本票邊界定案明列不得再往裡面加 BRAND_CASCADE_"
                "TABLES；留著無害——只是品牌×通路一列的健檢燈號快取，沒有外鍵、不會擋刪除，"
                "之後有票動到 repository.py 時再補登記進正式清理流程。",
}

# 品牌本身那一列不是「子資料」，由 delete_brand() 在所有登記模組清完之後才刪。
_ROOT_TABLES = {"brand"}
_PRODUCT_ROOT_TABLES = {"product"}

# ---------------------------------------------------------------------------
# 已知缺口：帶 brand_id 但刪品牌時沒人清的表。每一條都標明歸哪一刀處理。
# 補完就從這裡刪掉——刪了測試才會綠，這是進度可見的來源。
# ---------------------------------------------------------------------------

# 第 5 刀把訂單模組（9 張）、核心模組（interrupt）接上登記處，llm_task 改列進
# DELIBERATELY_KEPT（刻意保留），品牌層缺口歸零。第 6 刀把廣告模組的產品層清理
# （10 張表）也接上登記處，產品層缺口跟著歸零。空集合本身要保留、連同這段註解——
# 之後有新表帶 brand_id／product_id 卻沒人認領，這裡會再長出東西，到時候依樣畫葫蘆
# 補上模組登記或 DELIBERATELY_KEPT，不要圖方便直接把表名塞回這裡了事。
KNOWN_BRAND_GAPS = set()

KNOWN_PRODUCT_GAPS = set()


def _tables_with_column(conn, column: str) -> set:
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    return {t for t in names
            if column in {r[1] for r in conn.execute(f"PRAGMA table_info({t})")}}


class CleanupCoverageTest(unittest.TestCase):
    """比對真實 schema 與登記處宣告的涵蓋範圍。"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self._tmpdir.name) / "test.db")

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def _brand_uncovered(self) -> set:
        declared = set().union(*cleanup.declared_brand_tables().values())
        return (_tables_with_column(self.conn, "brand_id")
                - declared - _ROOT_TABLES - set(DELIBERATELY_KEPT))

    def _product_uncovered(self) -> set:
        declared = set().union(*cleanup.declared_product_tables().values())
        return (_tables_with_column(self.conn, "product_id")
                - declared - _PRODUCT_ROOT_TABLES - set(DELIBERATELY_KEPT))

    def test_no_unlisted_table_is_left_behind_on_brand_delete(self):
        """新增了帶 brand_id 的表卻沒人認領 -> 這裡會叫。"""
        unlisted = self._brand_uncovered() - KNOWN_BRAND_GAPS
        self.assertEqual(
            unlisted, set(),
            "以下資料表帶 brand_id，但刪品牌時沒有任何模組會清掉它，也不在已知缺口清單裡。\n"
            "要嘛讓擁有它的模組向 app.core.cleanup 登記（並把表名放進 brand_tables），\n"
            "要嘛確認是刻意保留、加進 DELIBERATELY_KEPT 並寫明理由：\n"
            + "\n".join(f"  - {t}" for t in sorted(unlisted)))

    def test_no_unlisted_table_is_left_behind_on_product_delete(self):
        unlisted = self._product_uncovered() - KNOWN_PRODUCT_GAPS
        self.assertEqual(
            unlisted, set(),
            "以下資料表帶 product_id，但刪產品時沒人清，也不在已知缺口清單裡：\n"
            + "\n".join(f"  - {t}" for t in sorted(unlisted)))

    def test_nothing_outside_the_delete_set_still_points_at_it(self):
        """被刪的表有沒有人還指著它？上面兩條看不到這一類破口。

        上面兩條只問「有 brand_id／product_id 的表有沒有人清」。但還有一類表自己沒有
        那兩個欄位、卻用外鍵指著會被刪掉的列——父列刪了、子列留著就是懸空外鍵，整個
        刪除會在 COMMIT 被擋下（實測：刪產品時 creative_brief -> experiment_cell 與
        external_ad_mapping -> publishing_package 就是這樣把刪除整個擋死的）。
        這條檢查的是 schema 層的封閉性：刪除集合之外的表，不得指向刪除集合之內的表。
        """
        from app.ads import repository as ads_repo

        product_set = ({t for t, _ in repo.PRODUCT_CHILD_TABLES}
                       | {t for t, _ in ads_repo.PRODUCT_CASCADE_TABLES}
                       | set(ads_repo._PRODUCT_CASCADE_LABELS)
                       | _PRODUCT_ROOT_TABLES)
        dangling = []
        for (table,) in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            if table in product_set:
                continue
            for fk in self.conn.execute(f"PRAGMA foreign_key_list({table})"):
                if fk[2] in product_set:
                    dangling.append(f"{table}.{fk[3]} -> {fk[2]}")
        self.assertEqual(
            dangling, [],
            "以下資料表不會被刪產品清掉，卻用外鍵指著會被清掉的表——刪產品會在 COMMIT\n"
            "被外鍵擋下、整筆失敗。自己有 product_id 就加進 PRODUCT_CASCADE_TABLES；\n"
            "沒有的話，_product_cascade_scope() 沿外鍵走本來就會撿到它，只要在\n"
            "_PRODUCT_CASCADE_LABELS 補一個中文標籤即可：\n"
            + "\n".join(f"  - {d}" for d in sorted(dangling)))

    def test_known_gap_lists_are_not_stale(self):
        """清單裡的每一條都必須真的還是缺口。補好了忘記刪 -> 這裡會叫。

        沒有這一條，清單會慢慢變成一份掩護新缺口的死名單。
        """
        for label, known, actual in (
            ("KNOWN_BRAND_GAPS", KNOWN_BRAND_GAPS, self._brand_uncovered()),
            ("KNOWN_PRODUCT_GAPS", KNOWN_PRODUCT_GAPS, self._product_uncovered()),
        ):
            fixed = known - actual
            self.assertEqual(
                fixed, set(),
                f"{label} 裡的這幾張表已經有人清了，把它們從清單刪掉：\n"
                + "\n".join(f"  - {t}" for t in sorted(fixed)))

    def test_deliberately_kept_tables_really_exist_and_have_a_reason(self):
        """刻意保留清單也要保持真實：表要還在，理由不能是空的。"""
        all_tables = {r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for table, reason in DELIBERATELY_KEPT.items():
            self.assertIn(table, all_tables, f"{table} 已不存在，DELIBERATELY_KEPT 該清掉這項")
            self.assertTrue(reason.strip(), f"{table} 沒有寫保留理由")


if __name__ == "__main__":
    unittest.main()
