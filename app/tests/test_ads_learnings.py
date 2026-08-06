# -*- coding: utf-8 -*-
"""app/tests/test_ads_learnings.py — 累積智慧頁（三段＋停用規則函式，GitHub issue #56）。

驗收條件（票 #56）：
- 新 route `/brands/{brand_id}/ads/learnings`，註冊位置早於 `/ads/{cycle_id}` 萬用路由。
- 三段內容正確：ledger 條目（expired=0）／生效中的 rule／pending 規則卡與未結案假設。
- `brand_intelligence.repository.deactivate_rule`：把 rule.status 改為非 active 但保留該列。
- 學習與禁令都可手動下架；下架後確實從 context_compiler 組出的 prompt 消失。
- 空狀態誠實：沒有內容就說「還沒有」。
- hub「累積智慧」卡改為可點；前朝教訓訪談入口只出現一處。
"""

import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_learnings_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import nextcycle  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.llm import context_compiler  # noqa: E402

main.reopen_connection()


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"


class LearningLedgerRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡", client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]

    def _make_entry(self):
        return ads_repo.create_learning_ledger_entry(
            main.conn, self.bid, learning_text="真人見證的角度轉換率比較好",
            applicability_scope="brand", created_by=ACTOR, actor=ACTOR,
            sample_size="120", confidence="已校準判讀",
        )

    def test_list_only_returns_non_expired_by_default(self):
        entry = self._make_entry()
        ads_repo.deactivate_learning_ledger_entry(main.conn, self.bid, entry["id"], actor=ACTOR)
        self.assertEqual(ads_repo.list_learning_ledger(main.conn, self.bid), [])
        all_rows = ads_repo.list_learning_ledger(main.conn, self.bid, include_expired=True)
        self.assertEqual(len(all_rows), 1)
        self.assertEqual(all_rows[0]["expired"], 1)

    def test_deactivate_keeps_row_and_content_unchanged(self):
        entry = self._make_entry()
        after = ads_repo.deactivate_learning_ledger_entry(main.conn, self.bid, entry["id"], actor=ACTOR)
        self.assertEqual(after["id"], entry["id"])
        self.assertEqual(after["learning_text"], entry["learning_text"])
        self.assertEqual(after["expired"], 1)
        row = main.conn.execute("SELECT * FROM learning_ledger WHERE id = ?", (entry["id"],)).fetchone()
        self.assertIsNotNone(row)

    def test_deactivate_unknown_entry_raises(self):
        with self.assertRaises(ValueError):
            ads_repo.deactivate_learning_ledger_entry(main.conn, self.bid, "lrn_nope", actor=ACTOR)

    def test_deactivate_writes_audit(self):
        entry = self._make_entry()
        ads_repo.deactivate_learning_ledger_entry(main.conn, self.bid, entry["id"], actor=ACTOR)
        rows = main.conn.execute(
            "SELECT * FROM audit_log WHERE brand_id = ? AND entity_type = 'learning_ledger'"
            " AND action = 'deactivate'", (self.bid,),
        ).fetchall()
        self.assertEqual(len(rows), 1)


class DeactivateRuleTest(unittest.TestCase):
    def setUp(self):
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡二號", client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]
        self.rule = bi_repo.create_rule(main.conn, self.bid, actor=ACTOR, rule_type="tone",
                                        content="以後不要再出現太急迫催促的語氣", severity="soft")

    def test_status_becomes_non_active_row_kept(self):
        after = bi_repo.deactivate_rule(main.conn, self.bid, self.rule["id"], actor=ACTOR)
        self.assertNotEqual(after["status"], "active")
        row = main.conn.execute("SELECT * FROM rule WHERE id = ?", (self.rule["id"],)).fetchone()
        self.assertIsNotNone(row)
        self.assertNotEqual(row["status"], "active")

    def test_excluded_from_list_rules_for_brand(self):
        bi_repo.deactivate_rule(main.conn, self.bid, self.rule["id"], actor=ACTOR)
        ids = [r["id"] for r in bi_repo.list_rules_for_brand(main.conn, self.bid)]
        self.assertNotIn(self.rule["id"], ids)

    def test_unknown_rule_raises(self):
        with self.assertRaises(ValueError):
            bi_repo.deactivate_rule(main.conn, self.bid, "rul_nope", actor=ACTOR)

    def test_disappears_from_context_compiler_prompt(self):
        """驗收條件明文要求的實測：規則停用後確實從 context_compiler 組出的 prompt 消失。"""
        text_before, _, _, _ = context_compiler.compile(main.conn, self.bid)
        self.assertIn("太急迫催促", text_before)
        bi_repo.deactivate_rule(main.conn, self.bid, self.rule["id"], actor=ACTOR)
        text_after, _, _, _ = context_compiler.compile(main.conn, self.bid)
        self.assertNotIn("太急迫催促", text_after)

    def test_writes_audit(self):
        bi_repo.deactivate_rule(main.conn, self.bid, self.rule["id"], actor=ACTOR)
        rows = main.conn.execute(
            "SELECT * FROM audit_log WHERE brand_id = ? AND entity_type = 'rule'"
            " AND action = 'deactivate'", (self.bid,),
        ).fetchall()
        self.assertEqual(len(rows), 1)


class LearningsPageRouteTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡三號", client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]

    def test_route_registered_before_cycle_wildcard(self):
        resp = self.client.get(f"/brands/{self.bid}/ads/learnings")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("找不到廣告檔期", resp.text)

    def test_empty_state_is_honest(self):
        resp = self.client.get(f"/brands/{self.bid}/ads/learnings")
        self.assertIn("還沒有已確認的學習", resp.text)
        self.assertIn("目前沒有生效中的禁令", resp.text)
        self.assertIn("目前沒有待處理的候選", resp.text)

    def test_page_shows_the_taste_freeze_notice_not_a_rebuild_notice(self):
        """票 T1：猜消費者反應的理由永遠停在觀察中、不會鑄成永久禁令，這是刻意的設計決定，
        不是還沒修好的機制（鐵則 16 狀態誠實）。頁面不得再說「重建中」——機制是永久拿掉，
        不是暫停等重建（修憲 6）。"""
        resp = self.client.get(f"/brands/{self.bid}/ads/learnings")
        self.assertNotIn("重建中", resp.text)
        self.assertIn("不會自動變成長期禁令", resp.text)

    def test_ledger_entry_shown_and_deactivate_removes_it(self):
        entry = ads_repo.create_learning_ledger_entry(
            main.conn, self.bid, learning_text="描繪使用情境的素材成交率比較好",
            applicability_scope="brand", created_by=ACTOR, actor=ACTOR,
            sample_size="80", confidence="Meta 視角判讀",
        )
        resp = self.client.get(f"/brands/{self.bid}/ads/learnings")
        self.assertIn("描繪使用情境的素材成交率比較好", resp.text)

        resp2 = self.client.post(
            f"/brands/{self.bid}/ads/learnings/ledger/{entry['id']}/deactivate",
            follow_redirects=False,
        )
        self.assertEqual(resp2.status_code, 303)
        resp3 = self.client.get(f"/brands/{self.bid}/ads/learnings")
        self.assertNotIn("描繪使用情境的素材成交率比較好", resp3.text)

    def test_active_ban_shown_and_deactivate_removes_it(self):
        rule = bi_repo.create_rule(main.conn, self.bid, actor=ACTOR, rule_type="tone",
                                   content="以後不要再出現畫面感覺怪的素材", severity="soft")
        main.conn.execute(
            "INSERT INTO creative_rule_card (id, brand_id, fingerprint_axis, fingerprint_value,"
            " proposed_rule_text, evidence_json, reject_count, status, promoted_rule_id,"
            " created_at, updated_at) VALUES ('rcd_test1', ?, 'tone', 'urgent', ?, '{}', 3,"
            " 'accepted', ?, '2026-01-01T00:00:00', '2026-01-01T00:00:00')",
            (self.bid, rule["content"], rule["id"]),
        )
        main.conn.commit()

        resp = self.client.get(f"/brands/{self.bid}/ads/learnings")
        self.assertIn("以後不要再出現畫面感覺怪的素材", resp.text)
        self.assertEqual(len(nextcycle.list_active_bans(main.conn, self.bid)), 1)

        resp2 = self.client.post(
            f"/brands/{self.bid}/ads/learnings/rules/{rule['id']}/deactivate",
            follow_redirects=False,
        )
        self.assertEqual(resp2.status_code, 303)
        self.assertEqual(nextcycle.list_active_bans(main.conn, self.bid), [])
        resp3 = self.client.get(f"/brands/{self.bid}/ads/learnings")
        self.assertNotIn("以後不要再出現畫面感覺怪的素材", resp3.text)

    def test_pending_rule_card_and_hypothesis_shown_as_candidates(self):
        main.conn.execute(
            "INSERT INTO creative_rule_card (id, brand_id, fingerprint_axis, fingerprint_value,"
            " proposed_rule_text, evidence_json, reject_count, status, created_at, updated_at)"
            " VALUES ('rcd_test2', ?, 'angle', 'pain', '候選：不要再點出痛點', '{}', 2, 'pending',"
            " '2026-01-01T00:00:00', '2026-01-01T00:00:00')",
            (self.bid,),
        )
        main.conn.commit()
        bi_repo.create_strategy_hypothesis(
            main.conn, self.bid, actor=ACTOR, hypothesis_type="message",
            statement="親切溫暖的語氣過去有效", created_by=ACTOR,
        )
        resp = self.client.get(f"/brands/{self.bid}/ads/learnings")
        self.assertIn("痛點", resp.text)
        self.assertIn("親切溫暖的語氣過去有效", resp.text)

    def test_hub_card_is_clickable(self):
        resp = self.client.get(f"/brands/{self.bid}/ads")
        self.assertIn(f'/brands/{self.bid}/ads/learnings', resp.text)
        self.assertNotIn("menu-card-soon", resp.text)

    def test_interview_entry_appears_exactly_once_across_hub_and_learnings(self):
        hub = self.client.get(f"/brands/{self.bid}/ads").text
        learnings = self.client.get(f"/brands/{self.bid}/ads/learnings").text
        interview_url = f"/brands/{self.bid}/ads/interview"
        count = hub.count(interview_url) + learnings.count(interview_url)
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
