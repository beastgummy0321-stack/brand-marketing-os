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

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import nextcycle  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import rule_cards  # noqa: E402
from app.core.db import new_id  # noqa: E402
from app.llm import context_compiler  # noqa: E402
from app.shared.web import OPERATOR  # noqa: E402

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

    def _sections(self):
        resp = self.client.get(f"/api/campaigns/brands/{self.bid}/learnings")
        self.assertEqual(resp.status_code, 200)
        return resp.json()["data"]

    def test_ledger_entry_shown_and_deactivate_removes_it(self):
        entry = ads_repo.create_learning_ledger_entry(
            main.conn, self.bid, learning_text="描繪使用情境的素材成交率比較好",
            applicability_scope="brand", created_by=ACTOR, actor=ACTOR,
            sample_size="80", confidence="Meta 視角判讀",
        )
        texts = [e["learning_text"] for e in self._sections()["learnings"]]
        self.assertIn("描繪使用情境的素材成交率比較好", texts)

        resp2 = self.client.post(
            f"/api/campaigns/brands/{self.bid}/learnings/ledger/{entry['id']}/deactivate",
        )
        self.assertEqual(resp2.status_code, 200)
        texts_after = [e["learning_text"] for e in self._sections()["learnings"]]
        self.assertNotIn("描繪使用情境的素材成交率比較好", texts_after)

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

        bans = [b["proposed_rule_text"] for b in self._sections()["active_bans"]]
        self.assertIn("以後不要再出現畫面感覺怪的素材", bans)
        self.assertEqual(len(nextcycle.list_active_bans(main.conn, self.bid)), 1)

        resp2 = self.client.post(
            f"/api/campaigns/brands/{self.bid}/learnings/rules/{rule['id']}/deactivate",
        )
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(nextcycle.list_active_bans(main.conn, self.bid), [])
        bans_after = [b["proposed_rule_text"] for b in self._sections()["active_bans"]]
        self.assertNotIn("以後不要再出現畫面感覺怪的素材", bans_after)

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
        data = self._sections()
        self.assertTrue(any("痛點" in card["proposed_rule_text"] for card in data["pending_cards"]))
        self.assertIn("親切溫暖的語氣過去有效",
                      [h["statement"] for h in data["pending_hypotheses"]])

    def test_overflow_rules_shown_with_count_and_confirmed_date(self):
        """票 02-prompt-cap-and-overflow-list（決策 0012 第三節）：超過上限未生效的規則不
        悄悄消失，累積智慧頁列出清單附最近確認時間；上限用該品牌自己的 rule_cards 覆寫值，
        不用真的建 20 幾條規則才能測到。

        confirmed_at 刻意選最近幾天內的日期（不是任意舊日期）：這個頁面同時會跑票
        01-rule-expiry-reconfirm 的逾期未確認掃描（系統預設 6 期＝84 天沒確認就退回
        pending_reconfirm），confirmed_at 太舊會先被那條掃描收走，測不到「未生效清單」
        這個獨立的行為——兩個機制刻意保持互不依賴，這裡的日期只是避開兩者疊加的巧合。"""
        rule_cards.set_value(main.conn, self.bid, "rule_prompt_cap", "max_active_rules",
                             1.0, actor=ACTOR)
        kept = bi_repo.create_rule(main.conn, self.bid, actor=ACTOR, rule_type="tone",
                                   content="留在提示詞裡的規則", severity="soft")
        main.conn.execute("UPDATE rule SET confirmed_at = '2026-08-06T00:00:00+00:00' WHERE id = ?",
                          (kept["id"],))
        overflowed = bi_repo.create_rule(main.conn, self.bid, actor=ACTOR, rule_type="tone",
                                         content="超過上限未生效的規則", severity="soft")
        main.conn.execute("UPDATE rule SET confirmed_at = '2026-08-05T00:00:00+00:00' WHERE id = ?",
                          (overflowed["id"],))
        main.conn.commit()

        overflow = self._sections()["overflow_rules"]
        self.assertEqual(len(overflow), 1)
        self.assertIn("超過上限未生效的規則", [r["content"] for r in overflow])
        self.assertTrue(overflow[0]["confirmed_at"].startswith("2026-08-05"))
        # 沒被下架、狀態仍是 active——只是這次沒排進生成提示詞。
        self.assertEqual(bi_repo.get_rule(main.conn, self.bid, overflowed["id"])["status"], "active")

    def test_no_overflow_section_when_within_cap(self):
        bi_repo.create_rule(main.conn, self.bid, actor=ACTOR, rule_type="tone",
                            content="唯一一條規則，沒超過上限", severity="soft")
        self.assertEqual(self._sections()["overflow_rules"], [])

    def test_pending_reconfirm_rule_shown_and_reconfirm_restores_it(self):
        """票 01-rule-expiry-reconfirm（ADR 0012 第一節）：太久沒重新確認的規則自動退回
        待確認、顯示在累積智慧頁，按「延續」恢復生效且不必重新輸入內容。"""
        rule = bi_repo.create_rule(main.conn, self.bid, actor=ACTOR, rule_type="tone",
                                   content="太久沒人確認的規則需要延續", severity="soft")
        main.conn.execute(
            "UPDATE rule SET confirmed_at = '2020-01-01T00:00:00+00:00' WHERE id = ?",
            (rule["id"],))
        main.conn.commit()

        pending = self._sections()["pending_reconfirm_rules"]
        self.assertEqual(len(pending), 1)
        self.assertIn("太久沒人確認的規則需要延續", [r["content"] for r in pending])
        self.assertEqual(
            bi_repo.get_rule(main.conn, self.bid, rule["id"])["status"], "pending_reconfirm")

        resp2 = self.client.post(
            f"/api/campaigns/brands/{self.bid}/learnings/rules/{rule['id']}/reconfirm",
        )
        self.assertEqual(resp2.status_code, 200)
        after = bi_repo.get_rule(main.conn, self.bid, rule["id"])
        self.assertEqual(after["status"], "active")
        self.assertEqual(after["content"], "太久沒人確認的規則需要延續")  # 不必重新輸入內容

        self.assertEqual(self._sections()["pending_reconfirm_rules"], [])  # 延續後從待確認清單消失

    def test_no_pending_reconfirm_section_when_none_stale(self):
        bi_repo.create_rule(main.conn, self.bid, actor=ACTOR, rule_type="tone",
                            content="剛接受的規則不該出現在待確認清單", severity="soft")
        self.assertEqual(self._sections()["pending_reconfirm_rules"], [])

    def test_reconfirm_unknown_rule_shows_error_not_500(self):
        resp = self.client.post(
            f"/api/campaigns/brands/{self.bid}/learnings/rules/rul_nope/reconfirm",
        )
        self.assertEqual(resp.status_code, 400)

    def test_expired_active_ban_disappears_from_active_bans_section(self):
        """票 01-rule-expiry-reconfirm 與既有「生效中的禁令」機制的交集：升級成長期規則的
        禁令一旦逾期未確認，`nextcycle.list_active_bans` 既有的 `status != 'active'` 過濾
        （原本只給人工下架用）自然把它排除，不需要另外改 nextcycle.py。"""
        rule = bi_repo.create_rule(main.conn, self.bid, actor=ACTOR, rule_type="tone",
                                   content="逾期未確認的禁令", severity="soft")
        main.conn.execute(
            "INSERT INTO creative_rule_card (id, brand_id, fingerprint_axis, fingerprint_value,"
            " proposed_rule_text, evidence_json, reject_count, status, promoted_rule_id,"
            " created_at, updated_at) VALUES ('rcd_test_expired', ?, 'tone', 'urgent', ?, '{}', 3,"
            " 'accepted', ?, '2026-01-01T00:00:00', '2026-01-01T00:00:00')",
            (self.bid, rule["content"], rule["id"]),
        )
        main.conn.execute(
            "UPDATE rule SET confirmed_at = '2020-01-01T00:00:00+00:00' WHERE id = ?",
            (rule["id"],))
        main.conn.commit()

        data = self._sections()
        self.assertEqual(len(data["pending_reconfirm_rules"]), 1)
        self.assertEqual(data["active_bans"], [])  # 「生效中的禁令」段回到空狀態
        self.assertEqual(nextcycle.list_active_bans(main.conn, self.bid), [])


class RuleCardDecisionApiTest(unittest.TestCase):
    """規則卡採納／不採納（票 T5-04）：戰情室企劃步驟的「同意」「不用」兩顆按鈕接的就是
    這支 API——跟累積智慧頁的候選卡同一批資料、同一支底層函式 `nextcycle.decide_rule_card`。"""

    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡四號", client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]

    def _insert_card(self, card_id=None, axis="tone", value="urgent",
                     text="不要再出現太急迫催促的語氣"):
        card_id = card_id or new_id("rcd")
        main.conn.execute(
            "INSERT INTO creative_rule_card (id, brand_id, fingerprint_axis, fingerprint_value,"
            " proposed_rule_text, evidence_json, reject_count, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, '{}', 2, 'pending', '2026-01-01T00:00:00', '2026-01-01T00:00:00')",
            (card_id, self.bid, axis, value, text),
        )
        main.conn.commit()
        return card_id

    def _decide(self, card_id, accepted):
        return self.client.post(
            f"/api/campaigns/brands/{self.bid}/learnings/rule-cards/{card_id}/decide",
            json={"accepted": accepted},
        )

    def test_accepting_promotes_it_to_a_brand_rule(self):
        card_id = self._insert_card()
        resp = self._decide(card_id, True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["message"], "記住了，以後產素材會避開這個方向。")

        row = dict(main.conn.execute(
            "SELECT * FROM creative_rule_card WHERE id = ?", (card_id,)).fetchone())
        self.assertEqual(row["status"], "accepted")
        self.assertIsNotNone(row["promoted_rule_id"])
        self.assertEqual(row["decided_by"], OPERATOR)
        rules = bi_repo.list_rules_for_brand(main.conn, self.bid)
        self.assertTrue(any(r["id"] == row["promoted_rule_id"] for r in rules))

    def test_declining_creates_no_rule(self):
        card_id = self._insert_card()
        resp = self._decide(card_id, False)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["message"], "好，這條不記成長期規則。")

        row = dict(main.conn.execute(
            "SELECT * FROM creative_rule_card WHERE id = ?", (card_id,)).fetchone())
        self.assertEqual(row["status"], "declined")
        self.assertIsNone(row["promoted_rule_id"])
        self.assertEqual(nextcycle.list_pending_rule_cards(main.conn, self.bid), [])

    def test_overclaim_card_uses_claim_wording_not_rule_wording(self):
        """overclaim 候選卡（票 T1／決策 0034 第 8 點）接受後走 claim 分支，訊息文案不同——
        沿用舊頁 `routes_interview.py` 兩組文案。"""
        card_id = self._insert_card(card_id="rcd_decide_overclaim",
                                     axis=nextcycle.OVERCLAIM_CLAIM_AXIS, value="v1",
                                     text="保證三天見效")
        resp = self._decide(card_id, True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["message"], "已經登記為禁用宣稱，之後掃描與生成都會避開這句話。")
        row = dict(main.conn.execute(
            "SELECT * FROM creative_rule_card WHERE id = ?", (card_id,)).fetchone())
        self.assertIsNone(row["promoted_rule_id"])  # 這條走 claim，不是 rule（見 nextcycle 註記）

    def test_audit_log_records_the_decision(self):
        card_id = self._insert_card()
        self._decide(card_id, True)
        rows = main.conn.execute(
            "SELECT * FROM audit_log WHERE brand_id = ? AND entity_type = 'creative_rule_card'"
            " AND entity_id = ? AND action = 'accept_rule_card'", (self.bid, card_id),
        ).fetchall()
        self.assertEqual(len(rows), 1)

    def test_decide_unknown_card_shows_error_not_500(self):
        resp = self._decide("rcd_not_real", True)
        self.assertEqual(resp.status_code, 400)

    def test_decide_works_without_operator_cookie(self):
        """ADR 0004：規則卡採納不再要求先設定操作人。"""
        card_id = self._insert_card()
        self.client.cookies.clear()
        resp = self._decide(card_id, True)
        self.assertEqual(resp.status_code, 200)
        row = main.conn.execute(
            "SELECT decided_by FROM creative_rule_card WHERE id = ?", (card_id,)).fetchone()
        self.assertEqual(row["decided_by"], OPERATOR)

