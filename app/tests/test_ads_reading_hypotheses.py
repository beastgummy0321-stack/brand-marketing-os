"""app/tests/test_ads_reading_hypotheses.py — 票 10-split-reading-py：假設結案週邊測試。

從 app/tests/test_ads_reading.py 搬過來，原樣不改——鏡射 app/ads/reading_hypotheses.py
的拆檔（見該檔開頭說明：`resolve_hypotheses`／`_ledger_confidence` 本身留在 reading.py，
但這裡的測試照樣經 `reading.resolve_hypotheses(...)` 呼叫，搬檔不影響呼叫端）。
"""

import json
import unittest

from fastapi.testclient import TestClient

import app.main as main
from app.ads import performance as perf
from app.ads import reading
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db
from app.core import interrupts as core_interrupts
from app.llm import context_compiler
from app.llm.providers import FakeProvider, ProviderError, ProviderResponse, Usage
from app.shared.web import OPERATOR

ACTOR = "測試員"





def _fake(text):
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=300, output_tokens=150),
                            stop_reason="end_turn")


class LearningTextNormalizationTest(unittest.TestCase):
    """票 F3-signoff-residue：`_normalize_learning_text()` 拓寬括號家族／收斂內部空白／
    清孤兒標點——近似重複要能對上，但真的不同的結論不能被拓寬順手洗成同一句話。"""

    def test_parenthetical_family_asides_strip_to_the_bare_sentence(self):
        """票 F3 R5 orchestrator ruling：夾註刪空只適用括號家族（全形／半形小括號、龜殼括號）
        ——這是原始 B0-23 案例，內容是舉例性補充，刪掉不影響結論。"""
        base = "情感訴求角度轉換率比功能訴求高"
        for aside in ("（第二輪驗證）", "(second pass)", "〔第二輪驗證〕"):
            with self.subTest(aside=aside):
                self.assertEqual(bi_repo._normalize_learning_text(base + aside), base)

    def test_quote_family_delimiters_canonicalize_but_never_empty_the_content(self):
        """票 F3 R5（b2）：「」『』【】是中文的引號／標籤，框住的是結論本身不是補充夾註，
        絕對不能被刪空——只統一分隔符寫法讓「換了引號但內容一樣」的兩句話對得上，同時
        內容不同的兩句話仍然要能分得開（round 3/4 把三種引號都當夾註刪空、只驗證了對得上
        那一半，這裡把「內容仍會參與比較」也一起驗證，才不會證明了錯的機制）。"""
        base = "情感訴求角度轉換率比功能訴求高"
        canonical = bi_repo._normalize_learning_text(f"{base}「第二輪驗證」")
        self.assertIn("第二輪驗證", canonical)
        for aside in ("『第二輪驗證』", "【第二輪驗證】"):
            with self.subTest(aside=aside):
                self.assertEqual(bi_repo._normalize_learning_text(base + aside), canonical)
        different_note = bi_repo._normalize_learning_text(f"{base}『第三輪再測』")
        self.assertNotEqual(different_note, canonical)

    def test_internal_whitespace_is_collapsed(self):
        base = "情感訴求角度轉換率比功能訴求高"
        spaced = "情感 訴求角度轉換率\t比功能訴求　高"
        self.assertEqual(bi_repo._normalize_learning_text(spaced), base)

    def test_stray_punctuation_left_by_a_stripped_aside_is_cleaned_up(self):
        """夾註前後各自帶一個逗號，拿掉夾註後兩個逗號黏在一起、句尾也多一個懸空逗號——
        清乾淨後應該跟完全沒有夾註的版本比對相同。"""
        base = "情感訴求角度轉換率比功能訴求高"
        text = f"{base}，（第二輪驗證），"
        self.assertEqual(bi_repo._normalize_learning_text(text), base)

    def test_genuinely_different_conclusions_do_not_normalize_the_same(self):
        """核心結論字詞不同（高 vs 低）就是真的不同，括號／空白拓寬不能把它們洗成一樣——
        這是本票要求的反向證明。"""
        higher = bi_repo._normalize_learning_text("情感訴求角度轉換率比功能訴求高（第二輪驗證）")
        lower = bi_repo._normalize_learning_text("情感訴求角度轉換率比功能訴求低（第二輪驗證）")
        self.assertNotEqual(higher, lower)

    def test_parenthetical_wrapping_the_whole_sentence_is_unwrapped_not_stripped(self):
        """R3（reject 覆核）：若整句結論剛好整段被同一組括號包住（中文常見的整句加括號
        強調寫法，不是舉例性夾註），括號家族的「整段刪夾註」規則刪完會是空字串，退回
        fallback：只拆括號、留內容（rule 4：非空輸入不准正規化成空字串）。"""
        for opener, closer in (("(", ")"), ("（", "）"), ("〔", "〕")):
            with self.subTest(bracket=opener + closer):
                higher = bi_repo._normalize_learning_text(
                    f"{opener}情感訴求角度轉換率比功能訴求高{closer}")
                lower = bi_repo._normalize_learning_text(
                    f"{opener}情感訴求角度轉換率比功能訴求低{closer}")
                self.assertNotEqual(higher, lower)
                self.assertEqual(higher, "情感訴求角度轉換率比功能訴求高")
                self.assertEqual(lower, "情感訴求角度轉換率比功能訴求低")

    def test_quote_wrapping_the_whole_sentence_keeps_canonical_delimiters(self):
        """票 F3 R5 orchestrator ruling：「」『』是引號不是夾註，整句被引號包住時不套用
        括號家族的「拆掉留內容」fallback——引號本來就不會被刪空，分隔符統一之後內容原封
        不動留在結果裡（不會退化成跟括號家族一樣的裸句）。"""
        for opener, closer in (("「", "」"), ("『", "』")):
            with self.subTest(bracket=opener + closer):
                higher = bi_repo._normalize_learning_text(
                    f"{opener}情感訴求角度轉換率比功能訴求高{closer}")
                lower = bi_repo._normalize_learning_text(
                    f"{opener}情感訴求角度轉換率比功能訴求低{closer}")
                self.assertNotEqual(higher, lower)
                self.assertEqual(higher, "「情感訴求角度轉換率比功能訴求高」")
                self.assertEqual(lower, "「情感訴求角度轉換率比功能訴求低」")

    def test_never_normalizes_a_non_empty_input_to_the_empty_string(self):
        """票 F3 R4（sign-off residue 覆核）：R3 的「整段包住才拆括號」判斷是拿『這個括號以
        外還剩什麼』來看，兩個以上括號區段時每一段都看到「別段還在」，於是每段都判自己該刪
        ——全部段落都刪光，結論相反的兩句話一起洗成空字串，變成假重複。任何非空輸入正規化
        後都不准是空字串，不然凡是這種形狀的學習就永遠被當成第一句以外全部視為重複，真正
        新學習被靜靜吞掉。"""
        whole_quote_plus_aside_high = "「情感訴求角度轉換率比功能訴求高」（第二輪驗證）"
        whole_quote_plus_aside_low = "「情感訴求角度轉換率比功能訴求低」（第二輪驗證）"
        two_spans_high_then_low = "「情感訴求角度轉換率比功能訴求高」『情感訴求角度轉換率比功能訴求低』"
        two_spans_low_then_high = "「情感訴求角度轉換率比功能訴求低」『情感訴求角度轉換率比功能訴求高』"
        for text in (whole_quote_plus_aside_high, whole_quote_plus_aside_low,
                     two_spans_high_then_low, two_spans_low_then_high):
            with self.subTest(text=text):
                self.assertNotEqual(bi_repo._normalize_learning_text(text), "")

    def test_multi_span_opposite_conclusions_do_not_collide(self):
        """票 F3 R4：上一個測試證明「不是空字串」還不夠——四句話裡有兩句講「高」、兩句講
        「低」，正規化後絕不能把講「高」的和講「低」的洗成同一個字串（否則兩句結論相反的
        學習照樣會互相判定成重複）。"""
        whole_quote_plus_aside_high = "「情感訴求角度轉換率比功能訴求高」（第二輪驗證）"
        whole_quote_plus_aside_low = "「情感訴求角度轉換率比功能訴求低」（第二輪驗證）"
        two_spans_high_then_low = "「情感訴求角度轉換率比功能訴求高」『情感訴求角度轉換率比功能訴求低』"
        two_spans_low_then_high = "「情感訴求角度轉換率比功能訴求低」『情感訴求角度轉換率比功能訴求高』"
        normalized = {
            "A1": bi_repo._normalize_learning_text(whole_quote_plus_aside_high),
            "A2": bi_repo._normalize_learning_text(whole_quote_plus_aside_low),
            "B1": bi_repo._normalize_learning_text(two_spans_high_then_low),
            "B2": bi_repo._normalize_learning_text(two_spans_low_then_high),
        }
        keys = list(normalized)
        for i, ka in enumerate(keys):
            for kb in keys[i + 1:]:
                with self.subTest(pair=(ka, kb)):
                    self.assertNotEqual(normalized[ka], normalized[kb])

    def test_b1_quote_wrapped_claim_followed_by_aside_does_not_collide(self):
        """票 F3 R5 orchestrator ruling done-check b1（原字面案例）：引號框住的是結論本身，
        句尾另外掛一個括號夾註，「高」「低」兩句正規化後不准變成同一個字串。"""
        high = bi_repo._normalize_learning_text(
            "本次學習：「情感訴求角度轉換率比功能訴求高」，樣本充足（第二輪驗證）")
        low = bi_repo._normalize_learning_text(
            "本次學習：「情感訴求角度轉換率比功能訴求低」，樣本充足（第二輪驗證）")
        self.assertNotEqual(high, low)

    def test_b2_corner_and_white_corner_quote_dedupe_on_delimiter_only(self):
        """done-check b2（原字面案例）：同一句結論只是換了引號寫法（「」↔『』），要對得上。"""
        corner = bi_repo._normalize_learning_text("拿證據說話的切角「實證成分」比純促銷高")
        white = bi_repo._normalize_learning_text("拿證據說話的切角『實證成分』比純促銷高")
        self.assertEqual(corner, white)

    def test_b3_b0_23_aside_with_slash_still_strips(self):
        """done-check b3：B0-23 原案不變——括號夾註（含頓號／斜線）刪掉後跟無夾註版本相同。"""
        with_aside = bi_repo._normalize_learning_text(
            "這個切角（實證成分／成分對比）比純促銷更能拉高轉換率")
        bare = bi_repo._normalize_learning_text("這個切角比純促銷更能拉高轉換率")
        self.assertEqual(with_aside, bare)

    def test_b4_parenthetical_and_tortoise_shell_aside_family_swap_dedupes(self):
        """done-check b4：小括號和龜殼括號同屬括號家族，只是換了寫法，要對得上。"""
        paren = bi_repo._normalize_learning_text("這個切角（實證成分）比純促銷更能拉高轉換率")
        tortoise = bi_repo._normalize_learning_text("這個切角〔實證成分〕比純促銷更能拉高轉換率")
        self.assertEqual(paren, tortoise)

    def test_b5_never_normalizes_a_non_empty_input_to_the_empty_string_property(self):
        """done-check b5（property check）：不手選三個樣本，改成用括號家族 × 引號家族 ×
        區段數量 × 排列方式組出一整批形狀（巢狀夾註、三段以上、家族交錯、括號裡只有標點、
        整句都是標點），任何一個非空輸入正規化後都不准變成空字串（票 F3 R6：巢狀形狀原本
        只驗非空，這裡加「內容仍分得開」，對著同一批形狀一起驗）。"""
        aside_families = ["（", "）"], ["(", ")"], ["〔", "〕"]
        quote_families = ["「", "」"], ["『", "』"], ["【", "】"]
        core_texts = ["情感訴求角度轉換率比功能訴求高", "，、", "。！？", ""]
        shapes = []
        nested_pairs = []
        # 巢狀：括號裡包引號，引號裡包括號
        for (ao, ac) in aside_families:
            for (qo, qc) in quote_families:
                shapes.append(f"{ao}{qo}實證成分{qc}{ac}")
                shapes.append(f"{qo}{ao}實證成分{ac}{qc}")
                # 「括號裡包引號」換「高」／「低」——票 F3 R6 缺陷方向。反方向不擴大範圍。
                nested_pairs.append((f"{ao}{qo}高{qc}{ac}", f"{ao}{qo}低{qc}{ac}"))
        # 三段以上、家族交錯排列
        for core in core_texts:
            for (ao, ac) in aside_families:
                for (qo, qc) in quote_families:
                    shapes.append(f"{core}{ao}第一段{ac}{qo}第二段{qc}{ao}第三段{ac}")
                    shapes.append(f"{qo}第一段{qc}{ao}第二段{ac}{qo}第三段{qc}")
        # 括號／引號裡只有標點、整句都是標點
        for (ao, ac) in aside_families:
            shapes.append(f"{ao}，。！{ac}")
        for (qo, qc) in quote_families:
            shapes.append(f"{qo}，。！{qc}")
        shapes.append("，、；：。.")
        shapes.append("（）〔〕「」『』【】")
        for text in shapes:
            with self.subTest(text=text):
                self.assertNotEqual(bi_repo._normalize_learning_text(text), "")
        for high, low in nested_pairs:
            with self.subTest(pair=(high, low)):
                self.assertNotEqual(bi_repo._normalize_learning_text(high),
                                     bi_repo._normalize_learning_text(low))

    def test_b6_quote_nested_inside_aside_no_longer_collides_across_delimiter_families(self):
        """票 F3 R6（最後一輪，orchestrator reject 案例）：`（「高」）`——舊 content class
        吃穿引號跨到右括號整段刪空，「高」「低」崩成同一句。寧可漏抓重複也不誤刪新學習
        （accepted regression）。三種括號家族都要驗，因為兩個 alternation 分支都改了。"""
        for ao, ac in (("（", "）"), ("(", ")"), ("〔", "〕")):
            with self.subTest(aside=ao + ac):
                high = bi_repo._normalize_learning_text(f"本次學習，{ao}「高」{ac}樣本充足")
                low = bi_repo._normalize_learning_text(f"本次學習，{ao}「低」{ac}樣本充足")
                self.assertNotEqual(high, low)


class LearningLedgerDedupeWidenedNormalizationTest(unittest.TestCase):
    """票 F3-signoff-residue：`learning_ledger_entry_exists()` 走真的查表路徑，正／反兩個
    方向都要證明——近似重複要擋下（標「已加強」而不是「第一次看到」），真的不同的結論
    不能被誤擋。"""

    def setUp(self):
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨露茶行去重測試",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]
        bi_repo.create_learning_ledger_entry(
            main.conn, self.bid, learning_text="情感訴求角度轉換率比功能訴求高（第二輪驗證）",
            applicability_scope="brand", created_by=ACTOR, actor=ACTOR, source_track="ads")

    def test_near_duplicate_across_bracket_family_and_whitespace_dedupes(self):
        near_dup = "情感訴求角度轉換率 比功能訴求高〔第三輪再測〕"
        self.assertTrue(bi_repo.learning_ledger_entry_exists(
            main.conn, self.bid, product_id=None, learning_text=near_dup))

    def test_genuinely_different_conclusion_does_not_dedupe(self):
        different = "情感訴求角度轉換率比功能訴求低（第二輪驗證）"
        self.assertFalse(bi_repo.learning_ledger_entry_exists(
            main.conn, self.bid, product_id=None, learning_text=different))

    def test_multi_span_learning_is_not_silently_treated_as_duplicate(self):
        """票 F3 R4：帳上先有一句多括號區段的學習（round 3 缺陷下會被正規化成空字串）。
        另一句結論相反、一樣是多括號區段的新學習拿來比對——round 3 的缺陷會讓兩句話都被
        正規化成空字串，空字串跟空字串相等，於是新學習被誤判成「已經記過了」而不會真的
        入帳。這裡直接查真的查表路徑，不能只看正規化函式本身。"""
        already_recorded = "「情感訴求角度轉換率比功能訴求高」『情感訴求角度轉換率比功能訴求低』"
        bi_repo.create_learning_ledger_entry(
            main.conn, self.bid, learning_text=already_recorded,
            applicability_scope="brand", created_by=ACTOR, actor=ACTOR, source_track="ads")
        genuinely_new = "「情感訴求角度轉換率比功能訴求低」『情感訴求角度轉換率比功能訴求高』"
        self.assertFalse(bi_repo.learning_ledger_entry_exists(
            main.conn, self.bid, product_id=None, learning_text=genuinely_new))

    def test_b6_quote_nested_inside_aside_is_recorded_separately_via_real_ledger_path(self):
        """票 F3 R6：走真的 `learning_ledger_entry_exists()` 查表路徑，不只測正規化函式。"""
        high = "本次學習，（「情感訴求角度轉換率比功能訴求高」）樣本充足"
        low = "本次學習，（「情感訴求角度轉換率比功能訴求低」）樣本充足"
        bi_repo.create_learning_ledger_entry(
            main.conn, self.bid, learning_text=high,
            applicability_scope="brand", created_by=ACTOR, actor=ACTOR, source_track="ads")
        self.assertFalse(bi_repo.learning_ledger_entry_exists(
            main.conn, self.bid, product_id=None, learning_text=low))


class _HypothesisReviewBase(unittest.TestCase):
    """票 #53 判讀頁假設結案共用的建置。"""

    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨露茶行",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]
        self.product = bi_repo.create_product(main.conn, self.bid, name="虛構烏龍茶包",
                                              actor=ACTOR)["id"]
        bi_repo.save_product_economics(main.conn, self.bid, self.product, selling_price=1000,
                                       unit_variable_cost=400, currency="TWD",
                                       confirmed_by=ACTOR, actor=ACTOR)
        resp = self.client.post(f"/api/campaigns/{self.bid}",
                                json={"product_ids": [self.product], "budget": 10000,
                                      "objective": "sales"})
        self.cycle_id = resp.json()["cycle_id"]
        self._orig = reading.PROVIDER
        reading.PROVIDER = FakeProvider(response=_fake(
            json.dumps({"reasons": {}}, ensure_ascii=False)))

    def tearDown(self):
        reading.PROVIDER = self._orig

    def _link_hypothesis(self, statement, hypothesis_type="audience", product_id=None):
        hyp = bi_repo.create_strategy_hypothesis(
            main.conn, self.bid, hypothesis_type=hypothesis_type, statement=statement,
            created_by=ACTOR, actor=ACTOR, product_id=product_id, source_cycle_id=self.cycle_id)
        main.conn.execute(
            "INSERT INTO campaign_cycle_hypothesis (org_id, campaign_cycle_id,"
            " strategy_hypothesis_id, brand_id, role) VALUES (%s, %s, %s, %s, %s)"
            " ON CONFLICT (campaign_cycle_id, strategy_hypothesis_id) DO NOTHING",
            (db.DEV_ORG_ID, self.cycle_id, hyp["id"], self.bid, hypothesis_type),
        )
        main.conn.commit()
        return hyp

    def _spend(self, **values):
        perf.import_manual(main.conn, self.bid, self.cycle_id, values, actor=ACTOR)

    def _cell_with_ad(self, ad_name, *, cycle_id=None, creative_angle="pain"):
        """R2-learning-honesty：一個真的投放過的切角（experiment_cell → publishing_package →
        external_ad_mapping），比照 `test_ads_nextcycle.py::HistoricalCellPerformanceTest`
        既有寫法——CSV 匯入靠廣告名稱對回這裡建好的交接包，才算「真的做過對照」。"""
        cycle_id = cycle_id or self.cycle_id
        cell_id, pkg_id, ts = db.new_id("exc"), db.new_id("pkg"), db.now_utc()
        main.conn.execute(
            "INSERT INTO experiment_cell (id, org_id, campaign_cycle_id, brand_id, creative_angle,"
            " created_at) VALUES (%s, %s, %s, %s, %s, %s)",
            (cell_id, db.DEV_ORG_ID, cycle_id, self.bid, creative_angle, ts))
        main.conn.execute(
            "INSERT INTO publishing_package (id, org_id, brand_id, campaign_cycle_id,"
            " experiment_cell_id, campaign_name, adset_name, ad_name, destination_url, utm_json,"
            " status, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '{}', 'ready', %s)",
            (pkg_id, db.DEV_ORG_ID, self.bid, cycle_id, cell_id, "測試活動", "測試組合", ad_name,
             "https://example.test", ts))
        main.conn.execute(
            "INSERT INTO external_ad_mapping (id, org_id, brand_id, publishing_package_id,"
            " campaign_cycle_id, platform, claim_status, confirmed_by, confirmed_at,"
            " created_at) VALUES (%s, %s, %s, %s, %s, 'meta', 'confirmed', %s, %s, %s)",
            (db.new_id("xam"), db.DEV_ORG_ID, self.bid, pkg_id, cycle_id, ACTOR, ts, ts))
        main.conn.commit()
        return cell_id

    def _ab_spend(self, *, spend, conversions, revenue, impressions=20000, clicks=400,
                  cycle_id=None, ad_names=("角度A_ad", "角度B_ad")):
        """兩個真的投放過的切角、成效加總等於給定的整期數字（切一半，餘數給第一支）——
        `judge()` 只看聚合總數，兩支怎麼分不影響整體判讀方向，但滿足了「這期真的做過
        對照」的門檻（`MIN_COMPARISON_CELLS = 2`）。曝光／點擊預設值跟既有 `_spend()`
        呼叫端一致（20000／400），避免曝光量不足被判成 `insufficient_data`。回傳這兩個
        切角的 `experiment_cell.id`。"""
        cycle_id = cycle_id or self.cycle_id
        angles = ("情感痛點開場", "功能宣稱開場")
        cells = [self._cell_with_ad(name, cycle_id=cycle_id, creative_angle=angle)
                for name, angle in zip(ad_names, angles)]
        def _half(total):
            h = total // 2
            return total - h, h
        (spend_a, spend_b), (conv_a, conv_b) = _half(spend), _half(conversions)
        (rev_a, rev_b), (imp_a, imp_b) = _half(revenue), _half(impressions)
        (click_a, click_b) = _half(clicks)
        csv_text = (
            "行銷活動名稱,廣告名稱,曝光次數,連結點擊次數,花費金額,購買次數,購買轉換價值\n"
            f"測試活動,{ad_names[0]},{imp_a},{click_a},{spend_a},{conv_a},{rev_a}\n"
            f"測試活動,{ad_names[1]},{imp_b},{click_b},{spend_b},{conv_b},{rev_b}\n"
        )
        result = perf.import_csv(main.conn, self.bid, cycle_id, csv_text, actor=ACTOR)
        assert result.matched_assets == 2, result.errors
        return cells


class HypothesisReviewTest(_HypothesisReviewBase):
    """票 #53：判讀頁假設結案（三選一，AI 預選）＋入帳 learning_ledger＋打斷佇列補網。"""

    def test_scale_candidate_with_real_comparison_still_preselects_inconclusive(self):
        """票 F3-signoff-residue：判讀結論偏正向、且這期真的做過對照，畫面預選也不再猜
        「成立」——聚合判讀方向不等於這條假設自己的對照數字撐得住這個結論，使用者要主動
        選才算數（同精神：B0-21）。AI 理由照樣附上、對照證據照樣並排出示，只是不預選。"""
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._ab_spend(spend=10000, conversions=10, revenue=40000)
        ok, err = reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)
        reviews = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["hypothesis_reviews"]
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0]["id"], hyp["id"])
        self.assertEqual(reviews[0]["preselect"], "inconclusive")
        self.assertTrue(reviews[0]["ai_reason"])
        self.assertEqual(len(reviews[0]["comparison_cells"]), 2, "契約第2點：要出示兩邊的並排證據")

    def test_pause_candidate_with_real_comparison_still_preselects_inconclusive(self):
        """票 F3-signoff-residue：同一條理由套在停損方向——聚合結論偏負向也不代表這條假設
        自己被否證了，一樣不預選「不成立」。"""
        self._link_hypothesis("這群受眾在意價格")
        self._ab_spend(spend=10000, conversions=0, revenue=0)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reviews = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["hypothesis_reviews"]
        self.assertEqual(reviews[0]["preselect"], "inconclusive")

    def test_ai_preselects_inconclusive_when_maintain(self):
        """修憲落地 G4（決策 0035 第三節第 6 點）：`maintain`（只是打平）不算「程式算出
        方向」，預選改看不出來，不是成立——橡皮圖章的產物不該被貼上「已驗證」標籤。"""
        self._link_hypothesis("通勤族比在家工作者更會下單")
        # 這個品牌的產品毛利率固定（售價1000／變動成本400 → 打平線約1.667），
        # ROAS=1.8 落在 [打平線, 打平線*1.3) → maintain。
        self._ab_spend(spend=10000, conversions=10, revenue=18000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reviews = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["hypothesis_reviews"]
        self.assertEqual(reviews[0]["preselect"], "inconclusive")

    def test_llm_failure_falls_back_to_program_generated_reason(self):
        """AI 講不出話不擋清單顯示——理由退回程式產生的版本，選項本身不受影響。"""
        self._link_hypothesis("通勤族比在家工作者更會下單")
        reading.PROVIDER = FakeProvider(exception=ProviderError("暫時無法回應"))
        self._ab_spend(spend=10000, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        review = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["hypothesis_reviews"][0]
        self.assertIn("這期判讀結論是", review["ai_reason"])

    def test_zero_operation_submit_uses_ai_preselect(self):
        """使用者零操作也能過：直接照 AI 預選送出，status 隨之更新。"""
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._ab_spend(spend=10000, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        preselect = reading.load(main.conn, self.bid,
                                 self.cycle_id)["cycle"]["hypothesis_reviews"][0]["preselect"]
        updated_count = reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id, {hyp["id"]: preselect}, actor=OPERATOR)
        self.assertEqual(updated_count, 1)
        updated = bi_repo.get_strategy_hypothesis(main.conn, self.bid, hyp["id"])
        self.assertEqual(updated["status"], preselect)

    def test_supported_confirmation_writes_learning_ledger(self):
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._ab_spend(spend=10000, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id, {hyp["id"]: "supported"}, actor=OPERATOR)
        rows = [dict(r) for r in main.conn.execute(
            "SELECT * FROM learning_ledger WHERE brand_id = %s", (self.bid,))]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["learning_text"], "通勤族比在家工作者更會下單")
        self.assertEqual(rows[0]["source_cycle_id"], self.cycle_id)
        self.assertEqual(rows[0]["source_hypothesis_id"], hyp["id"])
        self.assertEqual(rows[0]["created_by"], OPERATOR)
        self.assertIsNone(rows[0]["sample_size"])  # ADR 0026 決定 7b：句子沒點名切角，樣本留白
        self.assertIsNotNone(rows[0]["confidence"])
        self.assertIsNotNone(rows[0]["source_reading_id"])

    def test_ledger_confidence_is_its_own_scale_not_the_data_grade_label(self):
        """修憲落地 G4（決策 0035 第三節第 8 點）：ledger 的 confidence 是「樣本數＋是否
        重測過」自己一套，不是資料成色標籤（那個標籤講的是資料有沒有對過帳，不是這條
        學習可不可信）——這裡的品牌沒有接 GA4／Meta 對帳，成色標籤會是「Meta 視角判讀」，
        跟 confidence 欄位的值必須不同。"""
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._ab_spend(spend=10000, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id, {hyp["id"]: "supported"}, actor=OPERATOR)
        row = main.conn.execute(
            "SELECT confidence FROM learning_ledger WHERE brand_id = %s", (self.bid,)).fetchone()
        self.assertNotEqual(row["confidence"], "Meta 視角判讀")
        self.assertEqual(row["confidence"], "preliminary")  # ADR 0026 決定 7b：句子沒點名切角

    def test_small_sample_manual_override_gets_preliminary_confidence(self):
        """使用者手動把還在學習期的假設硬結案「成立」，系統不擋（決策 0013）；
        樣本只有 5 筆、不是重測，confidence 該誠實標「初步」。"""
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._ab_spend(spend=10000, conversions=5, revenue=9000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id, {hyp["id"]: "supported"}, actor=OPERATOR)
        row = main.conn.execute(
            "SELECT confidence FROM learning_ledger WHERE brand_id = %s", (self.bid,)).fetchone()
        self.assertEqual(row["confidence"], "preliminary")

    def test_repeated_learning_text_gets_reinforced_confidence(self):
        """同一個品牌、同一個範圍、同一句學習文字，不同期別各自被判定「成立」——不是同一次
        判讀的巧合，是獨立重測，第二次入帳的 confidence 要標「已加強」。"""
        statement = "通勤族比在家工作者更會下單"
        hyp1 = self._link_hypothesis(statement)
        self._ab_spend(spend=10000, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id, {hyp1["id"]: "supported"}, actor=OPERATOR)

        cycle2_id = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[self.product], pain_value=10000,
            objective="sales", actor=ACTOR)["id"]
        hyp2 = bi_repo.create_strategy_hypothesis(
            main.conn, self.bid, hypothesis_type="audience", statement=statement,
            created_by=ACTOR, actor=ACTOR, product_id=None, source_cycle_id=cycle2_id)
        main.conn.execute(
            "INSERT INTO campaign_cycle_hypothesis (org_id, campaign_cycle_id,"
            " strategy_hypothesis_id, brand_id, role) VALUES (%s, %s, %s, %s, 'audience')"
            " ON CONFLICT (campaign_cycle_id, strategy_hypothesis_id) DO NOTHING",
            (db.DEV_ORG_ID, cycle2_id, hyp2["id"], self.bid))
        main.conn.commit()
        self._ab_spend(spend=10000, conversions=10, revenue=40000, cycle_id=cycle2_id,
                       ad_names=("cycle2_角度A_ad", "cycle2_角度B_ad"))
        reading.run(main.conn, self.bid, cycle2_id, ACTOR)
        reading.resolve_hypotheses(
            main.conn, self.bid, cycle2_id, {hyp2["id"]: "supported"}, actor=OPERATOR)

        rows = [dict(r) for r in main.conn.execute(
            "SELECT * FROM learning_ledger WHERE brand_id = %s ORDER BY created_at", (self.bid,))]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["confidence"], "preliminary")  # ADR 0026 決定 7b：句子沒點名切角
        self.assertEqual(rows[1]["confidence"], "reinforced")

    def test_near_duplicate_learning_text_with_bracket_aside_still_gets_reinforced(self):
        """R2-learning-honesty 契約第 5 點（重現 B0-23）：LLM 每期生成的假設措辭有微幅
        出入，第二句多了一段舉例性括號夾註，逐字比對會誤判成「不同結論」、錯標「這是
        第一次看到這個結論」——拿掉括號後其實是同一句話，第二次入帳該標「已加強」。"""
        hyp1 = self._link_hypothesis("拿證據說話的切角（實證成分／成分對比）比純促銷更能拉高轉換率")
        self._ab_spend(spend=10000, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id, {hyp1["id"]: "supported"}, actor=OPERATOR)

        cycle2_id = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[self.product], pain_value=10000,
            objective="sales", actor=ACTOR)["id"]
        hyp2 = bi_repo.create_strategy_hypothesis(
            main.conn, self.bid, hypothesis_type="audience",
            statement="拿證據說話的切角比純促銷更能拉高轉換率",
            created_by=ACTOR, actor=ACTOR, product_id=None, source_cycle_id=cycle2_id)
        main.conn.execute(
            "INSERT INTO campaign_cycle_hypothesis (org_id, campaign_cycle_id,"
            " strategy_hypothesis_id, brand_id, role) VALUES (%s, %s, %s, %s, 'audience')"
            " ON CONFLICT (campaign_cycle_id, strategy_hypothesis_id) DO NOTHING",
            (db.DEV_ORG_ID, cycle2_id, hyp2["id"], self.bid))
        main.conn.commit()
        self._ab_spend(spend=10000, conversions=10, revenue=40000, cycle_id=cycle2_id,
                       ad_names=("cycle2_角度A_ad", "cycle2_角度B_ad"))
        reading.run(main.conn, self.bid, cycle2_id, ACTOR)
        reading.resolve_hypotheses(
            main.conn, self.bid, cycle2_id, {hyp2["id"]: "supported"}, actor=OPERATOR)

        rows = [dict(r) for r in main.conn.execute(
            "SELECT * FROM learning_ledger WHERE brand_id = %s ORDER BY created_at", (self.bid,))]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["confidence"], "reinforced",
                         "拿掉括號夾註後跟第一條逐字相同，不該被當成「第一次看到」")

    def _later_cycle(self):
        """比照 DualBaselineTest 直接用 repository 開一期，只用來造「後面又開過幾期」的
        時間序（`mark_stale_learnings_for_revalidation` 依 `campaign_cycle.created_at`
        排序，不必真的填成效資料）。"""
        return ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[self.product], pain_value=10000,
            objective="sales", actor=ACTOR)["id"]

    def test_ledger_entry_flagged_for_revalidation_after_window_of_later_cycles(self):
        """修憲落地 G4（決策 0035 第三節第 5 點）：`needs_revalidation` 欄位在表上但全庫
        沒有任何一行寫入過。「第 N 期再驗一次」＝這個品牌又開過幾期（依建立順序），
        超過門檻期數還沒被下架，就標記需要複查——只提醒，不擋路、不自動下架。"""
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._ab_spend(spend=10000, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id, {hyp["id"]: "supported"}, actor=OPERATOR)
        entry_id = main.conn.execute(
            "SELECT id FROM learning_ledger WHERE brand_id = %s", (self.bid,)).fetchone()["id"]

        for _ in range(reading.LEDGER_REVALIDATION_WINDOW_CYCLES - 1):
            self._later_cycle()
        reading.mark_stale_learnings_for_revalidation(main.conn, self.bid)
        row = main.conn.execute(
            "SELECT needs_revalidation FROM learning_ledger WHERE id = %s", (entry_id,)).fetchone()
        self.assertEqual(row["needs_revalidation"], 0, "還沒滿門檻期數，不該標記")

        self._later_cycle()
        reading.mark_stale_learnings_for_revalidation(main.conn, self.bid)
        row = main.conn.execute(
            "SELECT needs_revalidation FROM learning_ledger WHERE id = %s", (entry_id,)).fetchone()
        self.assertEqual(row["needs_revalidation"], 1)

    def test_revalidation_check_is_wired_into_next_cycle_build(self):
        """驗證真的掛進判讀後的下期準備流程（nextcycle.build()），不是孤兒函式沒人呼叫。"""
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._ab_spend(spend=10000, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id, {hyp["id"]: "supported"}, actor=OPERATOR)

        for _ in range(reading.LEDGER_REVALIDATION_WINDOW_CYCLES):
            self._later_cycle()

        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)  # 重判同一期，順手觸發 nextcycle.build()
        row = main.conn.execute(
            "SELECT needs_revalidation FROM learning_ledger WHERE brand_id = %s",
            (self.bid,)).fetchone()
        self.assertEqual(row["needs_revalidation"], 1)

    def test_learning_flows_into_next_cycle_prompt_via_context_compiler(self):
        """端到端實測（GitHub issue #54 驗收條件）：建虛構品牌 → 開期產假設 → 判讀 → 結案入帳
        → 下一期生成的 prompt（context_compiler.compile）內確實出現該學習。"""
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._ab_spend(spend=10000, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id, {hyp["id"]: "supported"}, actor=OPERATOR)

        # 模擬下一期生成計畫時 plan.py／creative.py 呼叫 compile() 的方式（brand-level）
        text, knowledge_item_ids, _brand_version, _product_version = context_compiler.compile(
            main.conn, self.bid)

        self.assertIn("【已驗證的學習】", text)
        self.assertIn("通勤族比在家工作者更會下單", text)
        self.assertIn(f"來源期別 {self.cycle_id}", text)
        learning_row = main.conn.execute(
            "SELECT id FROM learning_ledger WHERE brand_id = %s", (self.bid,)).fetchone()
        self.assertIn(learning_row["id"], knowledge_item_ids)

    def test_rejected_confirmation_does_not_write_ledger(self):
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=0, revenue=0)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id, {hyp["id"]: "rejected"}, actor=OPERATOR)
        rows = main.conn.execute(
            "SELECT COUNT(*) c FROM learning_ledger WHERE brand_id = %s", (self.bid,)).fetchone()
        self.assertEqual(rows["c"], 0)
        updated = bi_repo.get_strategy_hypothesis(main.conn, self.bid, hyp["id"])
        self.assertEqual(updated["status"], "rejected")

    def test_resolved_hypothesis_disappears_from_page_after_confirm(self):
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id, {hyp["id"]: "supported"}, actor=OPERATOR)
        reviews = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["hypothesis_reviews"]
        self.assertEqual(reviews, [])

    def test_unresolved_hypothesis_flagged_at_finalize(self):
        self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.finalize(main.conn, self.bid, self.cycle_id, ACTOR)
        open_items = core_interrupts.list_open(main.conn, brand_id=self.bid)
        self.assertTrue(any(i["category"] == "hypothesis_unresolved" for i in open_items))

    def test_resolved_before_finalize_does_not_flag(self):
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id, {hyp["id"]: "supported"}, actor=OPERATOR)
        reading.finalize(main.conn, self.bid, self.cycle_id, ACTOR)
        open_items = core_interrupts.list_open(main.conn, brand_id=self.bid)
        self.assertFalse(any(i["category"] == "hypothesis_unresolved" for i in open_items))

    def test_ignores_unknown_hypothesis_id_and_invalid_verdict_value(self):
        """防偽造 id、防非法 verdict 值：忽略不處理，不拋例外。"""
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        updated = reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id,
            {"hyp_not_real": "supported", hyp["id"]: "not_a_real_verdict"}, actor=ACTOR)
        self.assertEqual(updated, 0)


class HypothesisComparisonHonestyTest(_HypothesisReviewBase):
    """R2-learning-honesty：契約第 1／2／3／4 點——沒真的做過 A/B 對照時，預選不能是
    「成立」，簽核畫面要出示對照的切角證據，入帳前程式端要再擋一次、樣本數只算真的
    對照過的切角。對照票面的 C3 契約例：整期只投 1 個切角，覆盤③不列預設「成立」。"""

    def test_single_angle_cycle_preselects_none_even_when_scale_candidate(self):
        """契約例：C3 型檔期（整期只投 1 個切角）結算，覆盤③不再列「成立」預選——即使
        整體判讀結論是加碼方向（scale_candidate）。`_spend()` 是純手動彙總輸入，
        不對回任何切角，等同「0 個切角」，比契約例的「1 個切角」更嚴格，一樣不能預選。"""
        self._link_hypothesis("情感痛點開場優於功能宣稱開場")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reviews = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["hypothesis_reviews"]
        self.assertIsNone(reviews[0]["preselect"])
        self.assertEqual(reviews[0]["comparison_cells"], [])
        self.assertIn("沒有對得回切角的成效資料", reviews[0]["ai_reason"])

    def test_single_real_cell_still_not_enough_to_preselect(self):
        """1 個切角有真的成效資料（比 0 個更像真實情境）——仍然不到 `MIN_COMPARISON_CELLS`
        （2），一樣不能預選，證明門檻是「筆數」而不是「有沒有任何資料」。"""
        self._link_hypothesis("情感痛點開場優於功能宣稱開場")
        self._cell_with_ad("角度A_ad")
        perf.import_csv(
            main.conn, self.bid, self.cycle_id,
            "行銷活動名稱,廣告名稱,花費金額,購買次數,購買轉換價值\n測試活動,角度A_ad,10000,10,40000\n",
            actor=ACTOR)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reviews = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["hypothesis_reviews"]
        self.assertIsNone(reviews[0]["preselect"])
        self.assertEqual(len(reviews[0]["comparison_cells"]), 1)
        self.assertIn("只投了 1 個切角", reviews[0]["ai_reason"])

    def test_two_angle_cycle_shows_side_by_side_evidence(self):
        """契約第 2 點：真的做過對照時，簽核畫面拿得到兩邊各自的切角名／樣本數／花費／
        CPA／ROAS，不是只有程式的結論一句話。"""
        self._link_hypothesis("情感痛點開場優於功能宣稱開場")
        self._ab_spend(spend=10000, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        cells = reading.load(
            main.conn, self.bid, self.cycle_id)["cycle"]["hypothesis_reviews"][0]["comparison_cells"]
        self.assertEqual({c["creative_angle"] for c in cells}, {"情感痛點開場", "功能宣稱開場"})
        self.assertEqual(sum(c["conversions"] for c in cells), 10)
        self.assertEqual(sum(c["spend"] for c in cells), 10000)
        for c in cells:
            self.assertIn("cpa", c["kpis"])
            self.assertIn("roas", c["kpis"])

    def test_supported_verdict_without_real_comparison_is_downgraded_and_not_booked(self):
        """Done-check 5（紅→綠）：無對照資料的「成立」不准入帳。這裡直接餵
        `resolve_hypotheses(..., "supported")`——模擬繞過前端（前端本來就不會預選這個
        選項）直接打 API 的情況，程式端在寫入口必須自己再擋一次，不能只靠前端不給選。"""
        hyp = self._link_hypothesis("情感痛點開場優於功能宣稱開場")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        updated = reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id, {hyp["id"]: "supported"}, actor=OPERATOR)
        self.assertEqual(updated, 1)
        rows = main.conn.execute(
            "SELECT COUNT(*) c FROM learning_ledger WHERE brand_id = %s", (self.bid,)).fetchone()
        self.assertEqual(rows["c"], 0, "沒對照資料的「成立」不准寫進 learning_ledger")
        updated_hyp = bi_repo.get_strategy_hypothesis(main.conn, self.bid, hyp["id"])
        self.assertEqual(updated_hyp["status"], "inconclusive", "程式端要把它降級，不是照單全收")

    def test_two_angle_cycle_sample_size_is_the_compared_cells_total_not_the_whole_product(self):
        """契約第 4 點：入帳的樣本數＝這次真的拿來對照的切角自己的轉換數加總，不是
        「花費÷CPA」反推、也不是這個產品整期的全部轉換數——這裡額外灌一筆對不回任何
        切角的手動彙總資料，讓「整期總轉換數」跟「對照切角轉換數加總」出現落差，
        證明程式真的只算了後者。"""
        hyp = self._link_hypothesis("情感痛點開場優於功能宣稱開場")
        self._ab_spend(spend=10000, conversions=10, revenue=40000)
        # 額外一筆對不回任何切角的手動彙總（例如線下核銷），不該被算進這條假設的樣本數。
        self._spend(spend=5000, impressions=1000, clicks=50, conversions=90, revenue=9000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id, {hyp["id"]: "supported"}, actor=OPERATOR)
        row = main.conn.execute(
            "SELECT sample_size FROM learning_ledger WHERE brand_id = %s", (self.bid,)).fetchone()
        self.assertEqual(row["sample_size"], "10", "樣本數只能是兩個切角自己的 10 筆，不含額外灌的 90 筆")


class HypothesisLedgerHaltTest(_HypothesisReviewBase):
    """修憲落地 G4（決策 0035 第三節第 6 點）：假設結案入帳原本是確認偏誤幫浦——AI 預選加
    一路下一步等於橡皮圖章，只有「成立」單向累積、產物貼「已驗證的學習」標籤永久寫進
    prompt。統計缺陷（橡皮圖章式的預選、`maintain` 誤算正面、小樣本喊加碼停損）修好後，
    選「成立」照樣入帳，這裡驗證使用者實際會遇到的預設狀態。"""

    def test_supported_confirmation_writes_ledger_even_though_the_flag_is_on(self):
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._ab_spend(spend=10000, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id, {hyp["id"]: "supported"}, actor=OPERATOR)
        rows = main.conn.execute(
            "SELECT COUNT(*) c FROM learning_ledger WHERE brand_id = %s", (self.bid,)).fetchone()
        self.assertEqual(rows["c"], 1)
        updated = bi_repo.get_strategy_hypothesis(main.conn, self.bid, hyp["id"])
        self.assertEqual(updated["status"], "supported")


class HypothesisStaleNoteTest(_HypothesisReviewBase):
    """票 R4-late-data-downstream（B0-34）：已簽核假設補件後判讀翻盤要提示「結論依據已變，
    建議重看」，但簽核的 verdict 本身不能被自動改動。"""

    def test_no_note_before_any_rerun_after_signing(self):
        hyp = self._link_hypothesis("節慶檔期禮盒切角投報率比平常好")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=8000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id, {hyp["id"]: "rejected"}, actor=ACTOR)
        resolved = bi_repo.get_strategy_hypothesis(main.conn, self.bid, hyp["id"])
        self.assertIsNone(reading.stale_note(main.conn, self.bid, self.cycle_id, resolved))

    def test_note_appears_after_late_data_rerun_actually_changes_numbers(self):
        hyp = self._link_hypothesis("節慶檔期禮盒切角投報率比平常好")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=8000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id, {hyp["id"]: "rejected"}, actor=ACTOR)

        # 補一筆晚到營收，逼判讀真的重跑且數字真的變（不是空氣重判）。
        self._spend(spend=0, impressions=0, clicks=0, conversions=0, revenue=12000)
        ok, err = reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)

        resolved = bi_repo.get_strategy_hypothesis(main.conn, self.bid, hyp["id"])
        self.assertEqual(resolved["status"], "rejected")  # 已簽核結論本身沒被自動改動
        self.assertEqual(reading.stale_note(main.conn, self.bid, self.cycle_id, resolved),
                         reading.STALE_HYPOTHESIS_NOTE)

    def test_pending_hypothesis_never_gets_a_stale_note(self):
        hyp = self._link_hypothesis("節慶檔期禮盒切角投報率比平常好")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=8000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        still_pending = bi_repo.get_strategy_hypothesis(main.conn, self.bid, hyp["id"])
        self.assertEqual(still_pending["status"], "proposed")
        self.assertIsNone(reading.stale_note(main.conn, self.bid, self.cycle_id, still_pending))


if __name__ == "__main__":
    unittest.main()
