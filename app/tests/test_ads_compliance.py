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
import time
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_compliance_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import compliance  # noqa: E402
from app.ads import compliance_wordlist  # noqa: E402
from app.ads import creative as ads_creative  # noqa: E402
from app.ads import plan as ads_plan  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.llm.providers import FakeProvider, ProviderResponse, Usage  # noqa: E402
from app.shared.web import OPERATOR  # noqa: E402

main.reopen_connection()


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


def _wait_progress(client, url, timeout=5.0):
    """票 M3：進度頁改背景執行緒後，?run=1 不再同步等完；短輪詢模擬瀏覽器 meta refresh，
    等到真的轉址（303）或逾時為止（FakeProvider 幾乎瞬間完成，正常情況幾毫秒內就會轉址）。"""
    deadline = time.time() + timeout
    resp = client.get(url, follow_redirects=False)
    while resp.status_code != 303 and time.time() < deadline:
        time.sleep(0.02)
        resp = client.get(url, follow_redirects=False)
    return resp


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
        resp = self.client.post(f"/brands/{self.bid}/ads/new",
                                data={"slider_index": "5", "objective": "sales"},
                                follow_redirects=False)
        self.cycle_id = resp.headers["location"].split("/ads/")[1].split("?")[0]

        self._orig_plan, self._orig_creative = ads_plan.PROVIDER, ads_creative.PROVIDER
        ads_plan.PROVIDER = FakeProvider(
            response=_fake(json.dumps(_PLAN_OPTIONS, ensure_ascii=False)))
        _wait_progress(self.client, f"/brands/{self.bid}/ads/{self.cycle_id}/plan/progress?run=1")
        self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/plan/select",
                         data={}, follow_redirects=False)
        self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/plan/approve",
                         follow_redirects=False)
        self.cell_id = main.conn.execute(
            "SELECT id FROM experiment_cell WHERE campaign_cycle_id = ?",
            (self.cycle_id,)).fetchone()["id"]

    def tearDown(self):
        ads_plan.PROVIDER, ads_creative.PROVIDER = self._orig_plan, self._orig_creative

    def _make_creative(self, content, selling_point="quality"):
        reply = json.dumps({"variants": [
            {"cell_id": self.cell_id, "variant_type": "hook", "content": content,
             "rationale": "", "creative_angle_number": 16, "on_camera": False,
             "cut_type": "pain_visualized", "quote_source": None,
             "fingerprint": {"angle": "benefit", "tone": "warm",
                                              "format": "text_focus",
                                              "selling_point": selling_point}},
        ]}, ensure_ascii=False)
        ads_creative.PROVIDER = FakeProvider(response=_fake(reply))
        _wait_progress(self.client,
                       f"/brands/{self.bid}/ads/{self.cycle_id}/creatives/progress?run=1")

    def _make_creatives(self, contents):
        """一批多則 hook，各給不同 cut_type 以通過多樣性驗形（見 creative_matrix.py）。"""
        cut_types = ["pain_visualized", "counterintuitive", "identity_callout",
                    "precise_dissuasion", "contrast_pairing"]
        variants = [
            {"cell_id": self.cell_id, "variant_type": "hook", "content": content,
             "rationale": "", "creative_angle_number": 16 + i, "on_camera": False,
             "cut_type": cut_types[i % len(cut_types)], "quote_source": None,
             "fingerprint": {"angle": "benefit", "tone": "warm",
                            "format": "text_focus", "selling_point": "quality"}}
            for i, content in enumerate(contents)
        ]
        reply = json.dumps({"variants": variants}, ensure_ascii=False)
        ads_creative.PROVIDER = FakeProvider(response=_fake(reply))
        _wait_progress(self.client,
                       f"/brands/{self.bid}/ads/{self.cycle_id}/creatives/progress?run=1")

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

    def test_page_flags_but_does_not_block(self):
        """決策 0013：命中只標黃，關卡照樣可以按下去。

        用品牌自訂宣稱（非內建法規詞庫字詞）測，避免跟修憲落地 L2 的法規類自動預設挑掉混在一起——
        那個行為由 test_law_hit_defaults_to_rejected 等測試另外驗證。
        """
        bi_repo.create_claim(main.conn, self.bid, claim_text="全台銷量第一",
                             claim_type="forbidden", actor=ACTOR)
        self._make_creative("我們是全台銷量第一的品牌")
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives")
        self.assertIn("命中", page.text)
        self.assertIn("這不會擋住你", page.text)
        self.assertIn("這些都好，繼續", page.text)

        resp = self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives/approve",
                                follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertNotIn("kind=warn", resp.headers["location"])

    def test_page_is_honest_about_scan_limits(self):
        """不能讓使用者以為沒被標記就等於法務過關（鐵則 16）。"""
        self._make_creative("每天早晨的一杯好茶")
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives")
        self.assertIn("抓不到語氣或語意層面的問題", page.text)

    def test_page_states_the_responsibility_boundary(self):
        """修憲落地 L5（決策 0034 第 11 點）：頁面要老實講清楚這三句，並校正罰則認知。"""
        self._make_creative("每天早晨的一杯好茶")
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives")
        self.assertIn("系統會比對你登錄的字詞", page.text)
        self.assertIn("系統不會判斷你的宣稱合不合法", page.text)
        self.assertIn("食品廣告的法律責任在刊登者，也就是你", page.text)
        self.assertIn("60 萬元", page.text)
        self.assertIn("刑事責任", page.text)

    def test_page_discloses_scan_coverage_gap(self):
        """修憲落地 L5（決策 0034 第 12 點）：規則抽不出可比對字詞時，畫面要誠實列出來，
        不能靜靜跳過讓使用者以為沒事。"""
        bi_repo.create_claim(main.conn, self.bid, claim_text="藥",
                             claim_type="forbidden", actor=ACTOR)
        self._make_creative("每天早晨的一杯好茶")
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives")
        self.assertIn("這幾條規則抽不出可比對字詞，沒有被本次掃描涵蓋", page.text)

    def test_page_has_no_coverage_gap_banner_when_everything_is_covered(self):
        self._make_creative("每天早晨的一杯好茶")
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives")
        self.assertNotIn("沒有被本次掃描涵蓋", page.text)

    def test_rescan_replaces_old_findings(self):
        bi_repo.create_claim(main.conn, self.bid, claim_text="能治療失眠",
                             claim_type="forbidden", actor=ACTOR)
        self._make_creative("能治療失眠喔")
        self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives")
        first = len(ads_repo.list_findings(main.conn, self.bid, self.cycle_id, "compliance"))
        self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives")
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
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives")
        variant = self._first_variant()
        self.assertTrue(variant["rejected"])
        self.assertTrue(variant["auto_held"])
        self.assertIn("命中法規禁用字詞", page.text)
        self.assertIn("勾回，我要用這則", page.text)

    def test_brand_only_hit_does_not_default_reject(self):
        """只命中品牌自訂宣稱（非內建法規詞庫），不受這票影響，維持原本「預設採用」。"""
        bi_repo.create_claim(main.conn, self.bid, claim_text="全台銷量第一",
                             claim_type="forbidden", actor=ACTOR)
        self._make_creative("我們是全台銷量第一的品牌")
        self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives")
        variant = self._first_variant()
        self.assertFalse(variant["rejected"])
        self.assertFalse(variant["auto_held"])

    def test_high_risk_claim_hit_does_not_default_reject(self):
        """決策 0034 第 25 條：high_risk 維持標黃不動，只有法規類命中才翻預設值。"""
        bi_repo.create_claim(main.conn, self.bid, claim_text="長期穩定回購保證",
                             claim_type="high_risk", actor=ACTOR)
        self._make_creative("我們主打長期穩定回購保證")
        self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives")
        variant = self._first_variant()
        self.assertFalse(variant["rejected"])

    def test_efficacy_selling_point_with_clean_content_does_not_default_reject(self):
        """修憲落地 L4 修正：efficacy／safety 的法規提醒（`source_category="law_advisory"`）
        不是字詞命中，不該被 L2 apply_default_holds() 誤判成命中內建法定詞庫而自動翻成
        「已挑掉」——內容完全乾淨、一個字都沒踩線，就不該有任何自動判定列。實際走真實路由
        （不是直接呼叫 scan_cycle），才會踩到 L2 那段用 evidence.source_category 判斷的邏輯。"""
        self._make_creative("每天早晨的一杯好茶", selling_point="efficacy")
        self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives")
        variant = self._first_variant()
        self.assertFalse(variant["rejected"])
        self.assertFalse(variant["auto_held"])
        decision = main.conn.execute(
            "SELECT * FROM adoption_decision WHERE target_id = ?", (variant["id"],)).fetchone()
        self.assertIsNone(decision)

    def test_safety_selling_point_with_clean_content_does_not_default_reject(self):
        self._make_creative("每天早晨的一杯好茶", selling_point="safety")
        self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives")
        variant = self._first_variant()
        self.assertFalse(variant["rejected"])
        self.assertFalse(variant["auto_held"])

    def test_restore_flips_back_to_adopted_and_logs_audit(self):
        self._make_creative("每天喝一杯，改善你的生活品質")
        self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives")
        variant_id = self._first_variant()["id"]

        resp = self.client.post(
            f"/brands/{self.bid}/ads/{self.cycle_id}/creatives/{variant_id}/restore",
            follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertNotIn("kind=warn", resp.headers["location"])

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
        self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives")
        variant_id = self._first_variant()["id"]
        ads_creative.restore(main.conn, self.bid, variant_id, actor=ACTOR)

        self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives")
        self.assertFalse(self._first_variant()["rejected"])

    def test_reload_keeps_the_compliance_explanation_visible(self):
        """自動預設挑掉的素材不是「被改寫掉的舊版本」，重新整理後說明文字要還在
        （不能只剩一個看不出理由的黃標）。"""
        self._make_creative("每天喝一杯，改善你的生活品質")
        self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives")
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives")
        self.assertIn("改善", page.text)
        self.assertIn("食品安全衛生管理法", page.text)

    def test_creatives_page_renders_without_operator_cookie(self):
        """修憲落地 L2 修正：法規自動預設挑掉是系統判定，GET 這個檢視頁不該因為操作人 cookie
        還沒設定就整頁進不去（不能 303 轉址去 /settings/operator）——使用者自己按下
        『勾回』的 POST 才需要他自己的操作人身份。"""
        self._make_creative("每天喝一杯，改善你的生活品質")
        anon_client = TestClient(main.app)  # 全新 client，沒帶 operator_name cookie
        page = anon_client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives",
                               follow_redirects=False)
        self.assertEqual(page.status_code, 200)
        self.assertIn("命中法規禁用字詞", page.text)

    def test_batch_restore_button_hidden_below_threshold(self):
        self._make_creative("每天喝一杯，改善你的生活品質")
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives")
        self.assertNotIn("一次全部勾回", page.text)

    def test_batch_restore_button_shown_and_works_at_threshold(self):
        self.assertEqual(ads_creative.BATCH_RESTORE_THRESHOLD, 3)
        self._make_creatives([
            "每天喝一杯，改善你的生活品質",
            "長期使用，預防身體出狀況",
            "見效快，根治你的困擾",
        ])
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives")
        self.assertIn("一次全部勾回", page.text)
        self.assertIn("3", page.text)
        variants = ads_creative.list_variants(main.conn, self.bid, self.cycle_id)
        self.assertEqual(sum(1 for v in variants if v["auto_held"]), 3)

        resp = self.client.post(
            f"/brands/{self.bid}/ads/{self.cycle_id}/creatives/restore-batch",
            follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertNotIn("kind=warn", resp.headers["location"])

        variants = ads_creative.list_variants(main.conn, self.bid, self.cycle_id)
        self.assertEqual(sum(1 for v in variants if v["rejected"]), 0)
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives")
        self.assertNotIn("一次全部勾回", page.text)


if __name__ == "__main__":
    unittest.main()
