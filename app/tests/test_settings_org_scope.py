"""app/tests/test_settings_org_scope.py — 票 04-0：`app_setting` 讀值一定要照 org_id
篩選，不能讓一個組織讀到另一個組織存的值（Meta 權杖、GA4 服務帳戶、AI 金鑰都走這條路）。

修復前 `app/core/settings.py::_get_setting()` 的查詢是
`SELECT value FROM app_setting WHERE key = %s`——沒有 org_id，而且函式簽章根本不收
org_id 這個參數。本檔的測試因此在修復前是「呼叫就炸」（TypeError: 缺參數／多餘參數），
不是「有時對有時錯」的巧合——比起靠 Postgres 沒有 ORDER BY 時不保證的列序去賭運氣，
這是更可靠的紅：呼叫端當時連「請求某個組織的值」這件事本身都做不到。

`test_unscoped_query_replays_the_pre_fix_leak_mechanism` 額外用逐字重放修復前那句 SQL
（不經過已經修好的 `get_setting()`）示範根因：只要另一個組織曾經寫過同一把鍵，任何人的
讀取都會拿到那個值——用「只有一個組織寫過值」的情境讓這件事可重現，不必仰賴列序。
"""

import unittest

from app.core import db
from app.core import settings as coresettings

ORG_A = "org_04_0_test_a"
ORG_B = "org_04_0_test_b"


class SettingsOrgScopeTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        for org_id in (ORG_A, ORG_B):
            self.conn.execute(
                "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
                " ON CONFLICT (id) DO NOTHING",
                (org_id, org_id),
            )
        self.conn.commit()

    def tearDown(self):
        self.conn.execute("DELETE FROM app_setting WHERE org_id IN (%s, %s)", (ORG_A, ORG_B))
        self.conn.execute("DELETE FROM organisation WHERE id IN (%s, %s)", (ORG_A, ORG_B))
        self.conn.commit()

    # -- 驗收 3：兩個組織寫同一把鍵、不同值，各自讀回自己的值 -----------------------

    def test_two_orgs_same_key_different_values_each_org_reads_its_own(self):
        coresettings.set_setting(self.conn, "shared_key_04_0", "A-value", org_id=ORG_A)
        coresettings.set_setting(self.conn, "shared_key_04_0", "B-value", org_id=ORG_B)
        self.assertEqual(
            coresettings.get_setting(self.conn, "shared_key_04_0", org_id=ORG_A), "A-value")
        self.assertEqual(
            coresettings.get_setting(self.conn, "shared_key_04_0", org_id=ORG_B), "B-value")

    def test_org_with_no_value_never_sees_the_other_orgs_value(self):
        """單列可重現版：只有 org A 設過值，org B 從沒設過——修復前的查詢沒有 org_id
        篩選，資料表裡這把鍵只有一列，B 的讀取 100% 會拿到 A 的值，不是巧合。"""
        coresettings.set_setting(self.conn, "only_a_key_04_0", "A-secret", org_id=ORG_A)
        self.assertIsNone(coresettings.get_setting(self.conn, "only_a_key_04_0", org_id=ORG_B))

    # -- 根因重放：不經過修好的 get_setting()，直接示範舊查詢字面上為什麼會洩漏 ---------

    def test_unscoped_query_replays_the_pre_fix_leak_mechanism(self):
        coresettings.set_setting(self.conn, "mechanism_key_04_0", "A-secret", org_id=ORG_A)
        # 這句就是修復前 _get_setting() 的原始查詢，逐字重放（不呼叫已經修好的
        # get_setting()）：org B 從沒寫過這把鍵，這句查詢仍然把 org A 的值端出來。
        row = self.conn.execute(
            "SELECT value FROM app_setting WHERE key = %s", ("mechanism_key_04_0",)
        ).fetchone()
        self.assertEqual(row["value"], "A-secret")


if __name__ == "__main__":
    unittest.main()
