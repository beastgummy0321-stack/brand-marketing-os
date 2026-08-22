# -*- coding: utf-8 -*-
"""app/tests/test_ads_compliance.py — 廣告分支票 7：交接包／素材輸出前的法務掃描。

這是廣告分支第一次真正引用品牌智庫的限制層（宣稱與規則），
也是品牌智庫「待觀察」簽核的驗收點之一。品牌名一律虛構。
"""

import atexit
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_compliance_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import compliance  # noqa: E402
from app.ads import compliance_wordlist  # noqa: E402
from app.ads import creative as ads_creative  # noqa: E402
from app.ads import plan as ads_plan  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.ads import theme_repository as theme_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.llm.providers import FakeProvider, ProviderResponse, Usage  # noqa: E402
from app.shared.web import OPERATOR  # noqa: E402



def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"

_AUDIENCE = {"cold": {"description": "測試受眾"}, "warm": {"description": ""},
            "hot": {"description": ""}, "exclusions": []}

# 票 4：計畫生成一次出多個方案，測試只挑第一個（AI 推薦、預設選定的那個）。
_PLAN_OPTIONS = {
    "options": [
        {
            "is_recommended": True,
            "summary": "測試打法", "audience": _AUDIENCE,
            "angles": [{"title": "切角一", "message": "訊息一", "why": "", "product_id": None}],
            "hypotheses": [], "grounding": {"facts": [], "inferences": [], "to_verify": []},
        },
        {
            "is_recommended": False,
            "summary": "備用方案", "audience": _AUDIENCE,
            "angles": [{"title": "備用切角", "message": "備用訊息", "why": "", "product_id": None}],
            "hypotheses": [], "grounding": {"facts": [], "inferences": [], "to_verify": []},
        },
    ]
}


def _fake(text: str) -> ProviderResponse:
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=400, output_tokens=200),
                            stop_reason="end_turn")


class TermExtractionTest(unittest.TestCase):
    def test_pulls_quoted_terms_from_a_rule(self):
        terms = compliance.extract_terms("文案禁止出現「療效」「治療」等字樣，圖片上的文字也算。")
        self.assertEqual(terms, ["療效", "治療"])

    def test_short_claim_is_used_whole(self):
        self.assertEqual(compliance.extract_terms("有助於增強免疫力"), ["有助於增強免疫力"])

    def test_long_rule_without_quotes_is_skipped(self):
        """整段長規則逐字比對只會製造誤判，寧可抽不出來也不亂比。"""
        long_rule = "所有素材都必須符合品牌一貫的溫暖調性，並且在視覺上維持一致的色彩使用方式。"
        self.assertEqual(compliance.extract_terms(long_rule), [])

    def test_single_character_terms_are_ignored(self):
        """一個字的詞誤判率太高（「藥」會打到「藥妝」），不列入比對。"""
        self.assertEqual(compliance.extract_terms("禁止出現「藥」字"), [])

    def test_scan_text_reports_each_source_once(self):
        sources = [{"terms": ["療效", "治療"], "severity": "warn", "kind": "規則",
                    "detail": "禁用醫療字眼", "source_id": "rul_1", "source_type": "rule"}]
        hits = compliance.scan_text("有療效也能治療", sources)
        self.assertEqual(len(hits), 1)


class BuiltinWordlistTest(unittest.TestCase):
    def test_covers_both_statutory_groups_labeled_as_law(self):
        sources = compliance_wordlist.builtin_sources()
        self.assertTrue(all(s["source_category"] == "law" for s in sources))
        terms = {t for s in sources for t in s["terms"]}
        self.assertIn("治療", terms)          # 食安法 §28 II 醫療效能字群
        self.assertIn("調節血脂", terms)      # 健管法法定保健功效用語

    def test_has_a_review_due_date(self):
        self.assertRegex(compliance_wordlist.REVIEW_DUE_DATE, r"^\d{4}-\d{2}-\d{2}$")


class SellingPointLawNoteTest(unittest.TestCase):
    """修憲落地 L4（決策 0034 第 9 點）：efficacy／safety 是食安法 §28 最常見的入罪與
    易生誤解用語，不管有沒有命中字詞比對都要一律附一則提醒——純函數層級，不需要資料庫。"""

    def test_efficacy_gets_a_law_reminder(self):
        finding = compliance.selling_point_law_finding(
            {"id": "cvr_x", "fingerprint": {"selling_point": "efficacy"}})
        self.assertIsNotNone(finding)
        self.assertEqual(finding.severity, "info")
        # 故意不是 "law"：那個分類專屬於 L1 字詞命中，會被 L2 apply_default_holds()
        # 自動翻成「已挑掉」。這則是「選了這個賣點就一律附上」的提醒，不是命中，
        # 標成 "law" 會讓完全乾淨的素材被系統自動預設打掉（修憲落地 L4 修正）。
        self.assertEqual(finding.evidence["source_category"], "law_advisory")
        self.assertIn("食安法", finding.message)

    def test_safety_gets_a_law_reminder(self):
        finding = compliance.selling_point_law_finding(
            {"id": "cvr_y", "fingerprint": {"selling_point": "safety"}})
        self.assertIsNotNone(finding)

    def test_other_selling_points_get_nothing(self):
        finding = compliance.selling_point_law_finding(
            {"id": "cvr_z", "fingerprint": {"selling_point": "quality"}})
        self.assertIsNone(finding)

    def test_missing_fingerprint_gets_nothing(self):
        self.assertIsNone(compliance.selling_point_law_finding({"id": "cvr_w"}))


class CoverageGapsTest(unittest.TestCase):
    """修憲落地 L5（決策 0034 第 12 點）：`MIN_TERM_LENGTH` 讓單字規則永遠不觸發、
    無引號且超過 20 字的規則直接回空——這兩條路徑原本收下規則、靜默忽略、畫面不說。
    這裡驗證 `compliance.coverage_gaps()` 真的把這兩種情況抓出來，不是靜默消失。"""

    def setUp(self):
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨露茶飲",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]

    def test_single_character_forbidden_claim_is_reported_as_a_gap(self):
        bi_repo.create_claim(main.conn, self.bid, claim_text="藥",
                             claim_type="forbidden", actor=ACTOR)
        gaps = compliance.coverage_gaps(main.conn, self.bid)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["detail"], "藥")
        self.assertEqual(gaps[0]["source_type"], "claim")

    def test_long_unquoted_rule_is_reported_as_a_gap(self):
        long_rule = "所有素材都必須符合品牌一貫的溫暖調性，並且在視覺上維持一致的色彩使用方式。"
        bi_repo.create_rule(main.conn, self.bid, rule_type="tone", content=long_rule,
                            severity="soft", actor=ACTOR)
        gaps = compliance.coverage_gaps(main.conn, self.bid)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["detail"], long_rule)
        self.assertEqual(gaps[0]["source_type"], "rule")

    def test_normal_claim_is_not_reported_as_a_gap(self):
        bi_repo.create_claim(main.conn, self.bid, claim_text="能治療失眠",
                             claim_type="forbidden", actor=ACTOR)
        self.assertEqual(compliance.coverage_gaps(main.conn, self.bid), [])

    def test_no_claims_or_rules_means_no_gaps(self):
        self.assertEqual(compliance.coverage_gaps(main.conn, self.bid), [])


class ComplianceScanTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構草本工坊",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]
        resp = self.client.post(f"/api/campaigns/{self.bid}",
                                json={"product_ids": [], "budget": 10000, "objective": "sales"})
        self.cycle_id = resp.json()["cycle_id"]

        self._orig_plan = ads_plan.PROVIDER
        ads_plan.PROVIDER = FakeProvider(
            response=_fake(json.dumps(_PLAN_OPTIONS, ensure_ascii=False)))
        ads_plan.generate_options(main.conn, self.bid, self.cycle_id, ACTOR)
        self.client.post(f"/api/campaigns/{self.bid}/{self.cycle_id}/plan/select", json={})
        self.client.post(f"/api/campaigns/{self.bid}/{self.cycle_id}/plan/approve")
        self.cell_id = main.conn.execute(
            "SELECT id FROM experiment_cell WHERE campaign_cycle_id = ?",
            (self.cycle_id,)).fetchone()["id"]
        self._theme_seq = 0

    def tearDown(self):
        ads_plan.PROVIDER = self._orig_plan

    def _make_creative(self, content, selling_point="quality"):
        """開一顆已採用主題，底下一個標題元件（票 02-repoint-creative-readers：資料源改
        主題表，不再經 LLM 生成管線——舊碼用假回覆餵 generate()，這裡直接建主題）。"""
        self._theme_seq += 1
        theme = theme_repo.create_theme(
            main.conn, self.bid, campaign_cycle_id=self.cycle_id,
            experiment_cell_id=self.cell_id, format_key="single_image",
            name=f"掃描測試主題{self._theme_seq}", folder_code=f"C{self._theme_seq:03d}",
            actor=ACTOR,
            components=[{"component_type": "title", "content": content,
                        "fingerprint_json": {"angle": "benefit", "tone": "warm",
                                             "format": "text_focus",
                                             "selling_point": selling_point}}],
        )
        theme_repo.adopt_theme(main.conn, self.bid, theme["id"], actor=ACTOR)

    def _make_creatives(self, contents):
        """一批多顆已採用主題，各一個標題元件（主題模型沒有 cut_type 多樣性驗形，
        那是舊生成管線 creative_matrix.py 的規則，跟讀取層無關）。"""
        for content in contents:
            self._make_creative(content)

    def _scan_like_page(self):
        """舊素材頁 GET 的法務副作用，逐行對應 app/ads/routes_creative.py:ads_creatives()：
        重掃並整批換掉舊結論 → 讀回 flags → 命中內建法規詞庫的預設值翻成「已挑掉」。
        素材頁沒有對應的 /api 端點，改為直接呼叫路由本來就在呼叫的同一批業務函式。"""
        ads_repo.replace_findings(main.conn, self.bid, self.cycle_id, "compliance",
                                  compliance.scan_cycle(main.conn, self.bid, self.cycle_id))
        flags = compliance.load_findings(main.conn, self.bid, self.cycle_id)
        if flags:
            compliance.apply_default_holds(main.conn, self.bid, self.cycle_id, flags,
                                           compliance.AUTO_HOLD_ACTOR)

    def test_forbidden_claim_hit_is_flagged(self):
        bi_repo.create_claim(main.conn, self.bid, claim_text="能治療失眠",
                             claim_type="forbidden", actor=ACTOR)
        self._make_creative("我們的配方能治療失眠，晚上一覺到天亮")
        findings = compliance.scan_cycle(main.conn, self.bid, self.cycle_id)
        # 修憲落地 L1 之後，同一句文字也會命中內建法定詞庫的「治療」，
        # 所以這裡只挑品牌自訂那一條出來驗證，不再斷言總數剛好 1（見 BuiltinWordlistTest）。
        brand_findings = [f for f in findings if f.evidence.get("source_category") == "brand"]
        self.assertEqual(len(brand_findings), 1)
        self.assertEqual(brand_findings[0].severity, "warn")
        self.assertIn("能治療失眠", brand_findings[0].message)
        self.assertEqual(brand_findings[0].finding_type, "compliance")

    def test_hard_rule_quoted_term_is_flagged(self):
        bi_repo.create_rule(main.conn, self.bid, rule_type="wording",
                            content="文案禁止出現「療效」「治療」等字樣。",
                            severity="hard", actor=ACTOR)
        self._make_creative("實測療效驚人")
        findings = compliance.scan_cycle(main.conn, self.bid, self.cycle_id)
        # 「療效」同時是內建法定詞庫的字詞，這句話現在會命中兩種來源，都是 warn。
        brand_findings = [f for f in findings if f.evidence.get("source_category") == "brand"]
        self.assertEqual([f.severity for f in brand_findings], ["warn"])
        self.assertIn("療效", brand_findings[0].message)

    def test_soft_rule_is_only_an_info(self):
        bi_repo.create_rule(main.conn, self.bid, rule_type="tone",
                            content="盡量避免使用「限時」這種催促字眼。",
                            severity="soft", actor=ACTOR)
        self._make_creative("限時優惠，把握機會")
        findings = compliance.scan_cycle(main.conn, self.bid, self.cycle_id)
        self.assertEqual([f.severity for f in findings], ["info"])

    def test_clean_creative_produces_nothing(self):
        bi_repo.create_claim(main.conn, self.bid, claim_text="能治療失眠",
                             claim_type="forbidden", actor=ACTOR)
        self._make_creative("每天早晨的一杯好茶")
        self.assertEqual(compliance.scan_cycle(main.conn, self.bid, self.cycle_id), [])

    def test_approved_claims_are_not_flagged(self):
        """已核准的宣稱本來就能講，不該被自己的掃描擋。"""
        bi_repo.create_claim(main.conn, self.bid, claim_text="使用天然原料",
                             claim_type="approved", actor=ACTOR)
        self._make_creative("使用天然原料，喝得安心")
        self.assertEqual(compliance.scan_cycle(main.conn, self.bid, self.cycle_id), [])

    def test_rejected_variants_are_not_scanned(self):
        bi_repo.create_claim(main.conn, self.bid, claim_text="能治療失眠",
                             claim_type="forbidden", actor=ACTOR)
        self._make_creative("能治療失眠喔")
        variant = ads_creative.list_variants(main.conn, self.bid, self.cycle_id)[0]
        ads_creative.reject(main.conn, self.bid, variant["id"],
                            reason_code="overclaim", actor=ACTOR)
        self.assertEqual(compliance.scan_cycle(main.conn, self.bid, self.cycle_id), [])

    def test_rescan_replaces_old_findings(self):
        bi_repo.create_claim(main.conn, self.bid, claim_text="能治療失眠",
                             claim_type="forbidden", actor=ACTOR)
        self._make_creative("能治療失眠喔")
        self._scan_like_page()
        first = len(ads_repo.list_findings(main.conn, self.bid, self.cycle_id, "compliance"))
        self._scan_like_page()
        second = len(ads_repo.list_findings(main.conn, self.bid, self.cycle_id, "compliance"))
        self.assertEqual(first, second)
        self.assertGreater(first, 0)

    def test_new_brand_with_no_claims_still_flags_statutory_terms(self):
        """修憲落地 L1（決策 0034 第4條）：新品牌宣稱表是空的，掃描不該回空——
        內建法定紅線詞庫要能獨立命中，不依賴使用者自己登錄任何 claim／rule。"""
        self.assertEqual(bi_repo.list_claims_for_brand(main.conn, self.bid), [])
        self.assertEqual(bi_repo.list_rules_for_brand(main.conn, self.bid), [])
        self._make_creative("喝了之後能治療失眠，還能調節血脂")
        findings = compliance.scan_cycle(main.conn, self.bid, self.cycle_id)
        self.assertGreaterEqual(len(findings), 1)
        self.assertTrue(all(f.evidence.get("source_category") == "law" for f in findings))

    def test_builtin_hit_message_names_the_law_and_penalty(self):
        """三種來源後果不同（罰鍰 vs 拒登 vs 自訂偏好）——法規命中要講清楚是哪條法、罰多少。"""
        self._make_creative("這款能治療失眠")
        findings = compliance.scan_cycle(main.conn, self.bid, self.cycle_id)
        self.assertEqual(len(findings), 1)
        self.assertIn("食品安全衛生管理法", findings[0].message)
        self.assertIn("罰鍰", findings[0].message)

    def test_brand_custom_sources_are_labeled_differently_from_law(self):
        """品牌自訂規則與法規來源並列但標示不同（決策 0034 第4條）。"""
        bi_repo.create_claim(main.conn, self.bid, claim_text="能治療失眠",
                             claim_type="forbidden", actor=ACTOR)
        self._make_creative("能治療失眠喔")
        findings = compliance.scan_cycle(main.conn, self.bid, self.cycle_id)
        categories = {f.evidence.get("source_category") for f in findings}
        self.assertIn("brand", categories)

    def test_findings_share_the_guardrail_structure(self):
        """法務掃描與對帳護欄產出同一種 Finding，落在同一張表。"""
        bi_repo.create_claim(main.conn, self.bid, claim_text="能治療失眠",
                             claim_type="forbidden", actor=ACTOR)
        self._make_creative("能治療失眠喔")
        ads_repo.replace_findings(main.conn, self.bid, self.cycle_id, "compliance",
                                  compliance.scan_cycle(main.conn, self.bid, self.cycle_id))
        row = ads_repo.list_findings(main.conn, self.bid, self.cycle_id, "compliance")[0]
        self.assertEqual(row["source"], "rule_scan")
        self.assertEqual(row["target_type"], "variant")
        self.assertIn("variant_id", json.loads(row["evidence_json"]))

    def test_efficacy_selling_point_gets_a_reminder_even_with_clean_content(self):
        """修憲落地 L4（決策 0034 第 9 點）：即使一個字都沒命中詞庫，主打 efficacy／safety
        的素材也要一律附提醒——字詞比對之外不能讓系統對這兩個賣點免疫。"""
        self._make_creative("每天早晨的一杯好茶", selling_point="efficacy")
        findings = compliance.scan_cycle(main.conn, self.bid, self.cycle_id)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].code, "selling_point_law_note")
        self.assertEqual(findings[0].severity, "info")

    def test_quality_selling_point_gets_no_reminder(self):
        self._make_creative("每天早晨的一杯好茶", selling_point="quality")
        self.assertEqual(compliance.scan_cycle(main.conn, self.bid, self.cycle_id), [])


class DefaultHoldTest(ComplianceScanTest):
    """修憲落地 L2（決策 0034 第 25 條）：命中內建法規詞庫的素材，預設值從「已採用」翻成
    「已挑掉」，一鍵勾回即可使用；品牌自訂命中（含 high_risk）維持原樣、只標黃不動預設值。
    setUp／_make_creative(s) 沿用 ComplianceScanTest（品牌、檔期、計畫、切角都已備好）。
    """

    def _first_variant(self):
        return ads_creative.list_variants(main.conn, self.bid, self.cycle_id)[0]

    def test_law_hit_defaults_to_rejected(self):
        self._make_creative("每天喝一杯，改善你的生活品質")
        self._scan_like_page()
        variant = self._first_variant()
        self.assertTrue(variant["rejected"])
        self.assertTrue(variant["auto_held"])

    def test_brand_only_hit_does_not_default_reject(self):
        """只命中品牌自訂宣稱（非內建法規詞庫），不受這票影響，維持原本「預設採用」。"""
        bi_repo.create_claim(main.conn, self.bid, claim_text="全台銷量第一",
                             claim_type="forbidden", actor=ACTOR)
        self._make_creative("我們是全台銷量第一的品牌")
        self._scan_like_page()
        variant = self._first_variant()
        self.assertFalse(variant["rejected"])
        self.assertFalse(variant["auto_held"])

    def test_high_risk_claim_hit_does_not_default_reject(self):
        """決策 0034 第 25 條：high_risk 維持標黃不動，只有法規類命中才翻預設值。"""
        bi_repo.create_claim(main.conn, self.bid, claim_text="長期穩定回購保證",
                             claim_type="high_risk", actor=ACTOR)
        self._make_creative("我們主打長期穩定回購保證")
        self._scan_like_page()
        variant = self._first_variant()
        self.assertFalse(variant["rejected"])

    def test_efficacy_selling_point_with_clean_content_does_not_default_reject(self):
        """修憲落地 L4 修正：efficacy／safety 的法規提醒（`source_category="law_advisory"`）
        不是字詞命中，不該被 L2 apply_default_holds() 誤判成命中內建法定詞庫而自動翻成
        「已挑掉」——內容完全乾淨、一個字都沒踩線，就不該有任何自動判定列。要走完整條
        掃描路徑（scan → load_findings → apply_default_holds，不是只呼叫 scan_cycle），
        才會踩到 L2 那段用 evidence.source_category 判斷的邏輯。"""
        self._make_creative("每天早晨的一杯好茶", selling_point="efficacy")
        self._scan_like_page()
        variant = self._first_variant()
        self.assertFalse(variant["rejected"])
        self.assertFalse(variant["auto_held"])
        decision = main.conn.execute(
            "SELECT * FROM adoption_decision WHERE target_id = ?", (variant["id"],)).fetchone()
        self.assertIsNone(decision)

    def test_safety_selling_point_with_clean_content_does_not_default_reject(self):
        self._make_creative("每天早晨的一杯好茶", selling_point="safety")
        self._scan_like_page()
        variant = self._first_variant()
        self.assertFalse(variant["rejected"])
        self.assertFalse(variant["auto_held"])

    def test_restore_flips_back_to_adopted_and_logs_audit(self):
        self._make_creative("每天喝一杯，改善你的生活品質")
        self._scan_like_page()
        variant_id = self._first_variant()["id"]
        # 前提：真的先被系統自動挑掉，勾回才有意義可驗（不然 restore() 後面的斷言
        # 不論挑沒挑掉都會成立，等於沒測到東西）。
        self.assertTrue(self._first_variant()["rejected"])
        self.assertTrue(self._first_variant()["auto_held"])

        ads_creative.restore(main.conn, self.bid, variant_id, actor=OPERATOR)

        variant = self._first_variant()
        self.assertFalse(variant["rejected"])

        audit_row = main.conn.execute(
            "SELECT * FROM audit_log WHERE entity_id = ? AND action = 'compliance_restore'",
            (variant_id,)).fetchone()
        self.assertIsNotNone(audit_row)
        self.assertEqual(audit_row["actor"], OPERATOR)  # ADR 0004：操作人固定帶入

    def test_reload_after_restore_does_not_re_hold(self):
        """冪等性：勾回之後重新整理，不會把預設挑掉又蓋回去。"""
        self._make_creative("每天喝一杯，改善你的生活品質")
        self._scan_like_page()
        variant_id = self._first_variant()["id"]
        ads_creative.restore(main.conn, self.bid, variant_id, actor=ACTOR)

        self._scan_like_page()
        self.assertFalse(self._first_variant()["rejected"])

    def test_batch_restore_button_shown_and_works_at_threshold(self):
        self.assertEqual(ads_creative.BATCH_RESTORE_THRESHOLD, 3)
        self._make_creatives([
            "每天喝一杯，改善你的生活品質",
            "長期使用，預防身體出狀況",
            "見效快，根治你的困擾",
        ])
        self._scan_like_page()
        variants = ads_creative.list_variants(main.conn, self.bid, self.cycle_id)
        self.assertEqual(sum(1 for v in variants if v["auto_held"]), 3)

        restored = ads_creative.restore_all_auto_held(main.conn, self.bid, self.cycle_id,
                                                      actor=OPERATOR)
        self.assertEqual(restored, 3)

        variants = ads_creative.list_variants(main.conn, self.bid, self.cycle_id)
        self.assertEqual(sum(1 for v in variants if v["rejected"]), 0)
        self.assertEqual(sum(1 for v in variants if v["auto_held"]), 0)


if __name__ == "__main__":
    unittest.main()
