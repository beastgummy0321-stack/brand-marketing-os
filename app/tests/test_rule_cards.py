"""app/tests/test_rule_cards.py — 規則卡通用機制（issue #12；分品牌：設定中心票 01）。

驗：門檻值有預設種子、改值落庫後讀值立即用新值、重設回預設值、
分品牌覆寫互不干擾（A 品牌改值不影響 B 品牌、沒覆寫時繼續拿系統預設值）。
"""

import os
import unittest

import psycopg
from psycopg.rows import dict_row

from app.core import db, rule_cards

BID_A = "brand_a"
BID_B = "brand_b"


class RuleCardValueTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        # ADR 0027：conftest.py 逐「模組」一個 schema，不是逐「測試」——BID_A／BID_B 是整檔
        # 共用的固定字面值，任何一個測試對它們的 set_value() 不清乾淨，就會滲漏進其他測試
        # 方法。每個測試開始前把這兩個品牌的規則卡覆寫值全部清空，回到「沒有任何覆寫，
        # 全部拿系統預設值」的乾淨起點。
        self.conn.execute("DELETE FROM rule_card_value WHERE brand_id IN (%s, %s)", (BID_A, BID_B))
        self.conn.execute(
            "DELETE FROM audit_log WHERE entity_type = 'rule_card_value' AND brand_id IN (%s, %s)",
            (BID_A, BID_B),
        )
        self.conn.commit()

    def _audit_rows(self):
        return [dict(r) for r in
                self.conn.execute("SELECT * FROM audit_log ORDER BY created_at, id").fetchall()]

    # -- 種子與預設值 -------------------------------------------------------

    def test_get_value_falls_back_to_default_without_db(self):
        """conn=None 或表還沒建起來時（例如全新 schema 還沒跑 migrations），優雅回程式
        常數預設值，不噴錯（principles 16）。「表還沒建起來」在 Postgres 世界模擬成一個
        全新、沒跑過任何 migration 的 schema（跟 conftest.py 逐模組建的正常 schema不同）。"""
        self.assertEqual(rule_cards.get_value(None, BID_A, "rule_prompt_cap", "max_active_rules"), 20.0)

        bare_schema = f"t_bare_rule_cards_{os.getpid()}"
        base_dsn = db.dsn().split("?", 1)[0]
        admin = psycopg.connect(base_dsn, autocommit=True, row_factory=dict_row)
        admin.execute(f'DROP SCHEMA IF EXISTS "{bare_schema}" CASCADE')
        admin.execute(f'CREATE SCHEMA "{bare_schema}"')
        admin.execute(f'SET search_path TO "{bare_schema}"')
        bare = db.Conn(admin)
        try:
            self.assertEqual(
                rule_cards.get_value(bare, BID_A, "rule_prompt_cap", "max_active_rules"), 20.0)
        finally:
            admin.execute(f'DROP SCHEMA IF EXISTS "{bare_schema}" CASCADE')
            admin.close()

    def test_unknown_card_or_field_raises(self):
        with self.assertRaises(ValueError):
            rule_cards.get_value(self.conn, BID_A, "沒這張卡", "x")
        with self.assertRaises(ValueError):
            rule_cards.get_value(self.conn, BID_A, "rule_prompt_cap", "沒這個欄位")

    def test_list_cards_includes_human_readable_metadata(self):
        cards = rule_cards.list_cards(self.conn, BID_A)
        # 2026-08-29 刪掉六張沒有消費端的卡剩四張；dead-code-sweep 票 04（2026-08-30）
        # 再刪 rule_expiry（規則不再過期），剩三張。票 01（T6c 成效判讀）加回第四張
        # `gross_margin`（打平線用的毛利率，決定 1b）。F03-I17（使用者裁決 4：預算搬進
        # 投放中心）把 `schedule_budget` 從設定頁清單藏起來，`list_cards` 回到 3 張——
        # 卡片定義沒刪，`get_value` 照常可用（舊 schedule 程式碼還在讀）。
        self.assertEqual(len(cards), 3)
        by_key = {c["key"]: c for c in cards}
        self.assertNotIn("schedule_budget", by_key)
        self.assertIn("規則", by_key["rule_prompt_cap"]["title"])
        for c in cards:
            self.assertTrue(c["description"])  # 「這個門檻管什麼」說明不可空
            for f in c["fields"]:
                self.assertTrue(f["label"])
                self.assertTrue(f["help"])
        # 藏起來 ≠ 刪掉：get_value 仍能讀 schedule_budget 的預設值。
        self.assertEqual(
            rule_cards.get_value(self.conn, BID_A, "schedule_budget", "daily_budget"),
            rule_cards.CARDS["schedule_budget"]["fields"]["daily_budget"]["default"],
        )

    def test_user_facing_text_carries_no_internal_notes(self):
        """F31-I10 (drill wording item 1): description and help are shown to the user as-is,
        so they must not carry ticket numbers, internal role words or doc paths. Checks every
        card, including ones hidden from the settings page."""
        banned = ("票", "代理", "外殼", "docs/", "prompt", "token")
        for card_key, card in rule_cards.CARDS.items():
            texts = [("description", card["description"])] + [
                (f"{field_key}.help", field["help"]) for field_key, field in card["fields"].items()
            ]
            for where, text in texts:
                for word in banned:
                    self.assertNotIn(word, text, f"{card_key}.{where} contains {word!r}")

    def test_rule_prompt_cap_default_matches_adr_0012(self):
        """票 02-prompt-cap-and-overflow-list：進生成提示詞的規則上限，系統預設 20 條
        （ADR 0012 第二節），沒有種子 migration，靠 CARDS default 落地就夠。"""
        self.assertEqual(
            rule_cards.get_value(self.conn, BID_A, "rule_prompt_cap", "max_active_rules"), 20.0)

    # -- 改值即時生效 ---------------------------------------------------------

    def test_set_value_persists_and_is_read_back_immediately(self):
        """改值落庫後，讀卡立即拿到新值——不用重開程式、不用清快取。"""
        self.assertEqual(
            rule_cards.get_value(self.conn, BID_A, "rule_prompt_cap", "max_active_rules"), 20.0)

        rule_cards.set_value(self.conn, BID_A, "rule_prompt_cap", "max_active_rules", 35.0, actor="測試員", org_id=db.DEV_ORG_ID)
        self.assertEqual(
            rule_cards.get_value(self.conn, BID_A, "rule_prompt_cap", "max_active_rules"), 35.0)

        rows = self._audit_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entity_type"], "rule_card_value")
        self.assertEqual(rows[0]["entity_id"], "rule_prompt_cap.max_active_rules")
        self.assertEqual(rows[0]["action"], "update")
        self.assertEqual(rows[0]["actor"], "測試員")
        self.assertEqual(rows[0]["brand_id"], BID_A)  # 分品牌後是真正的品牌事件（不再是 None）

    def test_set_value_upserts_without_duplicating_row(self):
        rule_cards.set_value(self.conn, BID_A, "rule_prompt_cap", "max_active_rules", 30.0, actor="A", org_id=db.DEV_ORG_ID)
        rule_cards.set_value(self.conn, BID_A, "rule_prompt_cap", "max_active_rules", 33.0, actor="B", org_id=db.DEV_ORG_ID)
        count = self.conn.execute(
            "SELECT COUNT(*) AS n FROM rule_card_value WHERE brand_id = %s AND card_key = 'rule_prompt_cap'"
            " AND field_key = 'max_active_rules'", (BID_A,)
        ).fetchone()["n"]
        self.assertEqual(count, 1)
        self.assertEqual(
            rule_cards.get_value(self.conn, BID_A, "rule_prompt_cap", "max_active_rules"), 33.0)

    # -- 分品牌隔離（設定中心票 01） -------------------------------------------

    def test_brand_override_does_not_leak_into_other_brand(self):
        """A 品牌改規則卡值，B 品牌完全不受影響——各自一份覆寫值。"""
        rule_cards.set_value(self.conn, BID_A, "rule_prompt_cap", "max_active_rules", 99.0, actor="測試員", org_id=db.DEV_ORG_ID)
        self.assertEqual(
            rule_cards.get_value(self.conn, BID_A, "rule_prompt_cap", "max_active_rules"), 99.0)
        self.assertEqual(
            rule_cards.get_value(self.conn, BID_B, "rule_prompt_cap", "max_active_rules"), 20.0)

    def test_brand_without_override_falls_back_to_system_default(self):
        """B 品牌從沒改過這個欄位——就算 A 品牌已經改過，B 品牌繼續拿系統預設值。"""
        rule_cards.set_value(self.conn, BID_A, "schedule_plan_count", "plan_count_max", 3.0,
                             actor="測試員", org_id=db.DEV_ORG_ID)
        self.assertEqual(
            rule_cards.get_value(self.conn, BID_B, "schedule_plan_count", "plan_count_max"), 5.0)

    # -- 重設 -----------------------------------------------------------------

    def test_reset_card_restores_defaults(self):
        rule_cards.set_value(self.conn, BID_A, "schedule_plan_count", "plan_count_min", 2.0, actor="測試員", org_id=db.DEV_ORG_ID)
        rule_cards.set_value(self.conn, BID_A, "schedule_plan_count", "plan_count_max", 9.0, actor="測試員", org_id=db.DEV_ORG_ID)
        rule_cards.reset_card(self.conn, BID_A, "schedule_plan_count", actor="測試員", org_id=db.DEV_ORG_ID)

        self.assertEqual(rule_cards.get_value(self.conn, BID_A, "schedule_plan_count", "plan_count_min"), 1.0)
        self.assertEqual(rule_cards.get_value(self.conn, BID_A, "schedule_plan_count", "plan_count_max"), 5.0)

    def test_reset_skips_fields_already_at_default_no_noise_audit(self):
        rule_cards.set_value(self.conn, BID_A, "schedule_plan_count", "plan_count_max", 9.0, actor="測試員", org_id=db.DEV_ORG_ID)
        before = len(self._audit_rows())
        rule_cards.reset_card(self.conn, BID_A, "schedule_plan_count", actor="測試員", org_id=db.DEV_ORG_ID)
        after_rows = self._audit_rows()
        # 只有 plan_count_max 被測試改過；plan_count_min 本來就是 CARDS 現在的 default，
        # reset 不該產生額外稽核噪音。
        self.assertEqual(len(after_rows) - before, 1)
        touched = {r["entity_id"] for r in after_rows[-1:]}
        self.assertEqual(touched, {"schedule_plan_count.plan_count_max"})

    def test_reset_unknown_card_raises(self):
        with self.assertRaises(ValueError):
            rule_cards.reset_card(self.conn, BID_A, "沒這張卡", actor="測試員", org_id=db.DEV_ORG_ID)


class RuleCardCopyTest(unittest.TestCase):
    def test_card_texts_name_rules_in_chinese(self):
        """F47: the card texts say 必守規則／參考規則, not the internal hard / soft."""
        for card in rule_cards.CARDS.values():
            texts = [card["description"], *(f["help"] for f in card["fields"].values())]
            for text in texts:
                self.assertNotRegex(text, r"\b(hard|soft)\b")


if __name__ == "__main__":
    unittest.main()
