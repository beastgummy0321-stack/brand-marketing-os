# -*- coding: utf-8 -*-
"""app/tests/test_real_db_schema_drift.py — 真實資料庫的 schema 跟全新安裝差在哪。

其他所有測試都跑在「全新 migrate 出來的暫存資料庫」上。但正式環境那顆是一路
migration 疊上來的，兩者不保證一樣——不一樣的地方，就是所有測試都看不到的死角。

這個死角害過兩次：
  1. 真實庫的 learning_ledger 帶著 REFERENCES campaign_cycle 外鍵，全新庫沒有，
     所以「跨模組刪除順序」的正確性在測試裡驗不到。
  2. 刪產品時 creative_brief -> experiment_cell 懸空、刪除整個失敗。五路獨立查驗
     全在全新庫上跑，一致得出「產品層沒有跨模組外鍵」——在他們的環境是對的。

所以把差異釘住：冒出新的差異就變紅，逼人當場看一眼那是什麼、會不會又是個死角。
補上或確認無害之後，同步更新 KNOWN_SCHEMA_DRIFT。

data/app.db 不進版控，別台機器上沒有這個檔——沒有就跳過，不擋別人跑測試。
"""

import unittest

from app.tools.real_db_probe import REAL_DB, schema_diffs

# 已知且已確認過的差異。每一條都要寫明「為什麼可以留著」。
KNOWN_SCHEMA_DRIFT = {
    # learning_ledger 原本建在 app/ads/migrations/0001（帶跨模組外鍵），修憲落地 A3 遷入
    # 品牌永久層時，新版建表刻意拿掉那兩條外鍵（跨模組外鍵原則禁止）。舊資料庫的表已經
    # 存在，CREATE TABLE IF NOT EXISTS 是 no-op，所以外鍵留著。
    # 留著無害：那兩條外鍵讓「先刪子後刪父」變成硬性要求，而 delete_brand／delete_product
    # 已經用 PRAGMA defer_foreign_keys 讓順序無關。
    "learning_ledger.source_cycle_id -> campaign_cycle.id：**只有真實庫有這條外鍵**"
    "（全新庫上的測試驗不到它）",
    "learning_ledger.source_reading_id -> performance_reading.id：**只有真實庫有這條外鍵**"
    "（全新庫上的測試驗不到它）",
}


@unittest.skipUnless(REAL_DB.exists(), f"沒有 {REAL_DB}，跳過（這個檔不進版控）")
class RealDbSchemaDriftTest(unittest.TestCase):
    def setUp(self):
        self.diffs = set(schema_diffs())

    def test_no_undocumented_drift(self):
        """冒出沒被記錄過的 schema 差異 -> 這裡會叫。"""
        new = self.diffs - KNOWN_SCHEMA_DRIFT
        self.assertEqual(
            new, set(),
            "真實資料庫的 schema 出現沒被記錄過的差異。每一條都是所有測試都看不到的死角，\n"
            "先確認它會不會影響刪除流程或外鍵順序，再加進 KNOWN_SCHEMA_DRIFT 並寫明理由：\n"
            + "\n".join(f"  - {d}" for d in sorted(new)))

    def test_known_drift_is_not_stale(self):
        """記錄過的差異其實已經消失了（例如 migration 補齊了）-> 也要叫，免得清單腐化。"""
        gone = KNOWN_SCHEMA_DRIFT - self.diffs
        self.assertEqual(
            gone, set(),
            "以下差異已經不存在了，把它們從 KNOWN_SCHEMA_DRIFT 刪掉：\n"
            + "\n".join(f"  - {d}" for d in sorted(gone)))


if __name__ == "__main__":
    unittest.main()
