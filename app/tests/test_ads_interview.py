"""app/tests/test_ads_interview.py — 前朝教訓訪談（點選式三分流，GitHub issue #55）。

驗收條件（票 #55）：
- 選項用票 #52 定版的四軸值（app.ads.fingerprint.AXES）。
- 「試過不行」→ creative_rule_card（reject_count=0、evidence 標自述、status=pending）。
- 「這個有效」→ strategy_hypothesis（status=proposed、created_by=使用者、source_cycle_id 留空）。
- 自由補充文字只存不用：不進 prompt、不升級任何東西。
- 整個訪談流程對 learning_ledger 的寫入筆數為 0。
- 自述假設在下一期開期時自動掛進 campaign_cycle_hypothesis。
- 全程選填、跳過不擋流程。
"""

import atexit
import shutil
import tempfile
import unittest

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_interview_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import fingerprint as fp  # noqa: E402
from app.ads import interview  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"


def _ledger_count(brand_id):
    return main.conn.execute(
        "SELECT COUNT(*) c FROM learning_ledger WHERE brand_id = %s", (brand_id,)
    ).fetchone()["c"]


class InterviewSubmitTest(unittest.TestCase):
    def setUp(self):
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]

    def test_bad_selection_becomes_pending_rule_card_with_self_report_evidence(self):
        result = interview.submit(main.conn, self.bid,
                                  bad={"tone": ["urgent"]}, good={}, note=None, actor=ACTOR)
        self.assertEqual(len(result["rule_cards"]), 1)
        card = result["rule_cards"][0]
        self.assertEqual(card["reject_count"], 0)
        self.assertEqual(card["status"], "pending")
        self.assertEqual(card["fingerprint_axis"], "tone")
        self.assertEqual(card["fingerprint_value"], "urgent")
        evidence = card["evidence_json"]  # jsonb 欄位，psycopg 讀回已經是 dict
        self.assertEqual(evidence["source"], "self_report")

        row = main.conn.execute(
            "SELECT * FROM creative_rule_card WHERE id = %s", (card["id"],)
        ).fetchone()
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["reject_count"], 0)

    def test_good_selection_becomes_proposed_hypothesis_by_user(self):
        result = interview.submit(main.conn, self.bid,
                                  bad={}, good={"angle": ["testimonial"]},
                                  note=None, actor=ACTOR)
        self.assertEqual(len(result["hypotheses"]), 1)
        hyp = result["hypotheses"][0]
        self.assertEqual(hyp["status"], "proposed")
        self.assertEqual(hyp["created_by"], ACTOR)
        self.assertIsNone(hyp["source_cycle_id"])

        row = bi_repo.get_strategy_hypothesis(main.conn, self.bid, hyp["id"])
        self.assertEqual(row["status"], "proposed")
        self.assertIsNone(row["source_cycle_id"])

    def test_free_text_only_stored_in_audit_not_upgraded_anywhere(self):
        note_text = "曾經找網紅業配效果不好"
        interview.submit(main.conn, self.bid, bad={}, good={}, note=note_text, actor=ACTOR)

        audit_rows = main.conn.execute(
            "SELECT * FROM audit_log WHERE brand_id = %s AND entity_type = 'lesson_interview'",
            (self.bid,),
        ).fetchall()
        self.assertEqual(len(audit_rows), 1)
        after = audit_rows[0]["after_json"]  # jsonb 欄位，psycopg 讀回已經是 dict
        self.assertEqual(after["note"], note_text)

        # 不升級成規則卡或假設
        self.assertEqual(
            main.conn.execute("SELECT COUNT(*) c FROM creative_rule_card WHERE brand_id = %s",
                              (self.bid,)).fetchone()["c"], 0)
        self.assertEqual(len(bi_repo.list_strategy_hypotheses(main.conn, self.bid)), 0)

    def test_zero_writes_to_learning_ledger(self):
        """驗收條件明文要求的斷言：整個訪談流程對 learning_ledger 的寫入筆數為 0。"""
        before = _ledger_count(self.bid)
        interview.submit(
            main.conn, self.bid,
            bad={"angle": ["pain"], "tone": ["urgent"]},
            good={"selling_point": ["efficacy"], "format": ["short_video"]},
            note="補充備註", actor=ACTOR,
        )
        after = _ledger_count(self.bid)
        self.assertEqual(before, 0)
        self.assertEqual(after, 0)

    def test_skip_everything_creates_nothing_and_does_not_block(self):
        result = interview.submit(main.conn, self.bid, bad={}, good={}, note="", actor=ACTOR)
        self.assertEqual(result["rule_cards"], [])
        self.assertEqual(result["hypotheses"], [])
        self.assertEqual(
            main.conn.execute("SELECT COUNT(*) c FROM audit_log WHERE brand_id = %s"
                              " AND entity_type = 'lesson_interview'",
                              (self.bid,)).fetchone()["c"], 0)

    def test_invalid_axis_and_value_are_dropped_not_stored(self):
        result = interview.submit(
            main.conn, self.bid,
            bad={"not_an_axis": ["x"], "tone": ["not_a_real_value"]},
            good={}, note=None, actor=ACTOR,
        )
        self.assertEqual(result["rule_cards"], [])

    def test_duplicate_axis_value_does_not_create_second_card(self):
        interview.submit(main.conn, self.bid, bad={"tone": ["urgent"]}, good={},
                         note=None, actor=ACTOR)
        result = interview.submit(main.conn, self.bid, bad={"tone": ["urgent"]}, good={},
                                  note=None, actor=ACTOR)
        self.assertEqual(result["rule_cards"], [])
        count = main.conn.execute(
            "SELECT COUNT(*) c FROM creative_rule_card WHERE brand_id = %s AND fingerprint_axis = %s"
            " AND fingerprint_value = %s", (self.bid, "tone", "urgent"),
        ).fetchone()["c"]
        self.assertEqual(count, 1)

    def test_options_are_the_defined_axes(self):
        """選項直接用票 #52 定版的四軸值，不另寫一份清單。"""
        result = interview.submit(main.conn, self.bid,
                                  bad={axis: list(spec["values"].keys())
                                       for axis, spec in fp.AXES.items()},
                                  good={}, note=None, actor=ACTOR)
        total_values = sum(len(spec["values"]) for spec in fp.AXES.values())
        self.assertEqual(len(result["rule_cards"]), total_values)


class AttachPendingHypothesesTest(unittest.TestCase):
    def setUp(self):
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡二號",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]
        self.product = bi_repo.create_product(main.conn, self.bid, name="虛構濾掛組",
                                              actor=ACTOR)["id"]

    def test_self_report_hypothesis_auto_links_to_next_opened_cycle(self):
        result = interview.submit(main.conn, self.bid, bad={},
                                  good={"angle": ["testimonial"]}, note=None, actor=ACTOR)
        hyp_id = result["hypotheses"][0]["id"]

        cycle = ads_repo.create_cycle(main.conn, self.bid, product_ids=[self.product],
                                      pain_value=10000, objective="sales", actor=ACTOR)
        links = main.conn.execute(
            "SELECT * FROM campaign_cycle_hypothesis WHERE campaign_cycle_id = %s",
            (cycle["id"],),
        ).fetchall()
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["strategy_hypothesis_id"], hyp_id)
        self.assertEqual(links[0]["role"], "message")

    def test_already_linked_hypothesis_is_not_reattached_to_a_later_cycle(self):
        interview.submit(main.conn, self.bid, bad={}, good={"tone": ["blunt"]},
                         note=None, actor=ACTOR)
        first = ads_repo.create_cycle(main.conn, self.bid, product_ids=[self.product],
                                      pain_value=10000, objective="sales", actor=ACTOR)
        second = ads_repo.create_cycle(main.conn, self.bid, product_ids=[self.product],
                                       pain_value=10000, objective="sales", actor=ACTOR)
        first_links = main.conn.execute(
            "SELECT * FROM campaign_cycle_hypothesis WHERE campaign_cycle_id = %s",
            (first["id"],)).fetchall()
        second_links = main.conn.execute(
            "SELECT * FROM campaign_cycle_hypothesis WHERE campaign_cycle_id = %s",
            (second["id"],)).fetchall()
        self.assertEqual(len(first_links), 1)
        self.assertEqual(len(second_links), 0)

    def test_no_self_report_hypothesis_means_no_op(self):
        cycle = ads_repo.create_cycle(main.conn, self.bid, product_ids=[self.product],
                                      pain_value=10000, objective="sales", actor=ACTOR)
        links = main.conn.execute(
            "SELECT * FROM campaign_cycle_hypothesis WHERE campaign_cycle_id = %s",
            (cycle["id"],)).fetchall()
        self.assertEqual(len(links), 0)


class InterviewRouteTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡三號",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]

    def test_post_with_nothing_selected_does_not_block(self):
        resp = self.client.post(f"/api/campaigns/brands/{self.bid}/interview", json={})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["rule_card_count"], 0)
        self.assertEqual(resp.json()["hypothesis_count"], 0)

    def test_post_creates_card_and_hypothesis_via_form(self):
        resp = self.client.post(
            f"/api/campaigns/brands/{self.bid}/interview",
            json={"bad": {"tone": ["urgent"]}, "good": {"angle": ["testimonial"]},
                  "note": "備註文字"},
        )
        self.assertEqual(resp.status_code, 200)
        cards = main.conn.execute(
            "SELECT * FROM creative_rule_card WHERE brand_id = %s", (self.bid,)
        ).fetchall()
        hyps = bi_repo.list_strategy_hypotheses(main.conn, self.bid)
        self.assertEqual(len(cards), 1)
        self.assertEqual(len(hyps), 1)


class InterviewConflictTest(unittest.TestCase):
    """同一軸值兩邊都勾＝矛盾，兩邊都不採納，也不擋送出（審查發現，2026-08-02）。"""

    def setUp(self):
        self.brand = bi_repo.create_brand(main.conn, name="虛構湖畔燕麥",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]

    def test_same_axis_value_on_both_sides_creates_nothing(self):
        result = interview.submit(
            main.conn, self.bid,
            bad={"tone": ["blunt", "urgent"]}, good={"tone": ["blunt"]},
            note=None, actor=ACTOR,
        )
        # blunt 兩邊都勾 → 不產卡也不產假設；urgent 只勾一邊 → 照常產卡
        cards = main.conn.execute(
            "SELECT fingerprint_value FROM creative_rule_card WHERE brand_id = %s", (self.bid,)
        ).fetchall()
        self.assertEqual([r["fingerprint_value"] for r in cards], ["urgent"])
        self.assertEqual(bi_repo.list_strategy_hypotheses(main.conn, self.bid), [])
        self.assertEqual(len(result["conflicts"]), 1)
        self.assertIn("直白不修飾", result["conflicts"][0])

    def test_conflict_does_not_block_submit(self):
        """全部都衝突時仍正常回傳、不丟例外（不擋路）。"""
        result = interview.submit(
            main.conn, self.bid,
            bad={"angle": ["pain"]}, good={"angle": ["pain"]}, note=None, actor=ACTOR,
        )
        self.assertEqual(result["rule_cards"], [])
        self.assertEqual(result["hypotheses"], [])
        self.assertEqual(len(result["conflicts"]), 1)


if __name__ == "__main__":
    unittest.main()
