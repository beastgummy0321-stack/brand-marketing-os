# -*- coding: utf-8 -*-
"""app/tests/test_ads_nextcycle.py — 廣告分支票 13：下期草案、規則卡、反回音室。

三件事都由程式決定（加多少、學不學、像不像），LLM 不參與判斷。
"""

import atexit
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_next_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import creative as ads_creative  # noqa: E402
from app.ads import fingerprint as fp  # noqa: E402
from app.ads import nextcycle  # noqa: E402
from app.ads import performance as perf  # noqa: E402
from app.ads import reading  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core.db import new_id, now_iso  # noqa: E402
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


def _fake(text):
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=200, output_tokens=100),
                            stop_reason="end_turn")


def _print(angle="pain", tone="blunt", fmt="text_focus", selling="quality"):
    return {"angle": angle, "tone": tone, "format": fmt, "selling_point": selling}


class FingerprintDistanceTest(unittest.TestCase):
    def test_identical_prints_have_no_distance(self):
        self.assertEqual(fp.distance(_print(), _print()), 0.0)

    def test_completely_different_is_one(self):
        other = _print(angle="curiosity", tone="warm", fmt="carousel", selling="safety")
        self.assertEqual(fp.distance(_print(), other), 1.0)

    def test_missing_axes_are_not_counted_as_different(self):
        """指紋殘缺不該被誤判成很有創意。"""
        self.assertEqual(fp.distance({"angle": "pain"}, {"angle": "pain"}), 0.0)
        self.assertEqual(fp.distance({}, _print()), 1.0)  # 沒得比就當作不同，不誤報「太像」

    def test_novelty_uses_the_closest_neighbour(self):
        """只要跟其中任何一則幾乎一樣，它就是舊東西——不能被不相干的歷史稀釋。"""
        history = [_print(angle="curiosity", tone="warm", fmt="carousel", selling="safety"),
                   _print()]
        self.assertEqual(fp.novelty(_print(), history), 0.0)

    def test_echo_ratio_counts_stale_candidates(self):
        history = [_print()]
        candidates = [_print(), _print(angle="curiosity", tone="warm", fmt="carousel",
                                       selling="safety")]
        self.assertEqual(fp.echo_chamber_ratio(candidates, history), 0.5)

    def test_echo_threshold_catches_three_of_four_axes_matching(self):
        """修憲落地 G3（決策 0035 第9點）：四軸 distance 只有離散值 0／0.25／0.5／0.75／1.0，
        舊門檻 0.25 搭配「novelty < 門檻」等於要求四軸全部相同（novelty=0）才算重複；
        新門檻放寬到只要有 3 軸相同（novelty=0.25）也算在原地打轉。"""
        history = [_print()]
        near_dupe = _print(selling="price")  # 只有賣點不同，novelty=0.25
        self.assertEqual(fp.novelty(near_dupe, history), 0.25)
        self.assertLess(fp.novelty(near_dupe, history), fp.ECHO_THRESHOLD)
        self.assertEqual(fp.echo_chamber_ratio([near_dupe], history), 1.0)


class PromptVocabularyLawNoteTest(unittest.TestCase):
    """修憲落地 L4（決策 0034 第 9 點）：efficacy／safety 給模型看的枚舉清單要附法規註記，
    別的軸值不受影響。"""

    def test_efficacy_and_safety_carry_a_law_note(self):
        vocab = fp.prompt_vocabulary()
        self.assertIn("efficacy（有感有效，", vocab)
        self.assertIn("safety（安全無添加，", vocab)
        self.assertIn("食安法", vocab)

    def test_other_values_are_unchanged(self):
        vocab = fp.prompt_vocabulary()
        self.assertIn("quality（品質好）", vocab)
        self.assertIn("pain（點出痛點）", vocab)


class _BaseNextCycleTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]
        self.product = bi_repo.create_product(main.conn, self.bid, name="虛構濾掛組",
                                              actor=ACTOR)["id"]
        bi_repo.save_product_economics(main.conn, self.bid, self.product, selling_price=1000,
                                       unit_variable_cost=400, currency="TWD",
                                       confirmed_by=ACTOR, actor=ACTOR)
        resp = self.client.post(f"/brands/{self.bid}/ads/new",
                                data={"product_ids": [self.product],
                                      "custom_amount": "10000", "objective": "sales"},
                                follow_redirects=False)
        self.cycle_id = resp.headers["location"].split("/ads/")[1].split("?")[0]
        self._orig = reading.PROVIDER
        reading.PROVIDER = FakeProvider(response=_fake(
            json.dumps({"text": "說明文字"}, ensure_ascii=False)))

    def tearDown(self):
        reading.PROVIDER = self._orig

    def _run_cycle(self, **values):
        perf.import_manual(main.conn, self.bid, self.cycle_id, values, actor=ACTOR)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)

    def _insert_variant(self, variant_id, cycle_id, fingerprint):
        """真的插一列 creative_variant——規則卡相對判準（修憲落地 G3）的分母來自這張表，
        不是只看 adoption_decision（反對制下預設全採用，未被拒的變體本來就沒有 decision 列）。
        """
        cell_id = new_id("exc")
        brief_id = new_id("cbf")
        ts = now_iso()
        main.conn.execute(
            "INSERT INTO experiment_cell (id, campaign_cycle_id, brand_id, created_at)"
            " VALUES (?, ?, ?, ?)", (cell_id, cycle_id, self.bid, ts))
        main.conn.execute(
            "INSERT INTO creative_brief (id, campaign_cycle_id, experiment_cell_id, brand_id,"
            " brief_type, purpose, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, 'copy', '測試', 'dispatched', ?, ?)",
            (brief_id, cycle_id, cell_id, self.bid, ts, ts))
        main.conn.execute(
            "INSERT INTO creative_variant (id, variant_type, creative_brief_id,"
            " campaign_cycle_id, experiment_cell_id, brand_id, attributes_json,"
            " fingerprint_json, status, created_at)"
            " VALUES (?, 'hook', ?, ?, ?, ?, ?, ?, 'DRAFT', ?)",
            (variant_id, brief_id, cycle_id, cell_id, self.bid,
             json.dumps({"content": "測試"}, ensure_ascii=False),
             json.dumps(fingerprint, ensure_ascii=False), ts))

    def _generate(self, fingerprint, cycle_id=None):
        """純出現、沒被拒——用來補分母，證明相對判準看得到「這個值本來就常出現」。"""
        cycle_id = cycle_id or self.cycle_id
        self._insert_variant(new_id("cvr"), cycle_id, fingerprint)
        main.conn.commit()

    def _reject(self, fingerprint, reason_code="off_brand", cycle_id=None):
        cycle_id = cycle_id or self.cycle_id
        variant_id = new_id("cvr")
        self._insert_variant(variant_id, cycle_id, fingerprint)
        main.conn.execute(
            "INSERT INTO adoption_decision (id, brand_id, campaign_cycle_id, target_type,"
            " target_id, decision, reason_code, fingerprint_json, decided_by, decided_at)"
            " VALUES (?, ?, ?, 'variant', ?, 'rejected', ?, ?, ?, ?)",
            (new_id("adp"), self.bid, cycle_id, variant_id, reason_code,
             json.dumps(fingerprint, ensure_ascii=False), ACTOR, now_iso()),
        )
        main.conn.commit()

    def _make_cycle(self, created_at):
        """直接插一期最小可用的 campaign_cycle——只給時間窗測試量身訂做的分期用，
        不必真的跑完整條開期流程。"""
        cid = new_id("ccy")
        ts = now_iso()
        main.conn.execute(
            "INSERT INTO campaign_cycle (id, brand_id, product_scope_json, objective, currency,"
            " start_date, end_date, channels_json, status, created_at, updated_at)"
            " VALUES (?, ?, ?, 'sales', 'TWD', '2026-01-01', '2026-01-31', '[]', 'EVALUATING', ?, ?)",
            (cid, self.bid, json.dumps([self.product]), created_at, ts),
        )
        main.conn.commit()
        return cid


class BudgetProposalTest(_BaseNextCycleTest):
    def test_good_cycle_proposes_a_capped_increase(self):
        self._run_cycle(spend=10000, impressions=20000, clicks=400, conversions=10,
                        revenue=40000)
        draft = nextcycle.load(main.conn, self.bid, self.cycle_id)["content"]
        self.assertEqual(draft["budget"]["status"], "scale_candidate")
        # 10 筆成交 → 只准加 20%
        self.assertEqual(draft["budget"]["proposed_budget"], 12000.0)
        self.assertEqual(draft["budget"]["cap_ratio"], 0.2)

    def test_more_conversions_unlock_a_bigger_step(self):
        self._run_cycle(spend=10000, impressions=200000, clicks=4000, conversions=150,
                        revenue=600000)
        draft = nextcycle.load(main.conn, self.bid, self.cycle_id)["content"]
        self.assertEqual(draft["budget"]["cap_ratio"], 1.5)
        self.assertEqual(draft["budget"]["proposed_budget"], 25000.0)

    def test_losing_cycle_proposes_cutting_in_half(self):
        self._run_cycle(spend=10000, impressions=20000, clicks=400, conversions=10,
                        revenue=10000)
        draft = nextcycle.load(main.conn, self.bid, self.cycle_id)["content"]
        self.assertEqual(draft["budget"]["status"], "pause_candidate")
        self.assertEqual(draft["budget"]["proposed_budget"], 5000.0)
        self.assertIn("收一半", draft["budget"]["advice"])

    def test_draft_is_built_together_with_the_reading(self):
        """判讀完成的同時就備好下期，不必再點一次。"""
        self._run_cycle(spend=10000, impressions=20000, clicks=400, conversions=10,
                        revenue=40000)
        self.assertIsNotNone(nextcycle.load(main.conn, self.bid, self.cycle_id))

    def test_page_shows_why_the_increase_is_capped(self):
        self._run_cycle(spend=10000, impressions=20000, clicks=400, conversions=10,
                        revenue=40000)
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/performance")
        self.assertIn("下一期就這樣開", page.text)
        self.assertIn("加碼幅度上限", page.text)


class RuleCardTest(_BaseNextCycleTest):
    def test_one_rejection_is_not_enough(self):
        """一次可能只是那則寫得爛，兩次才看得出方向不對。"""
        self._reject(_print(tone="blunt"))
        self.assertEqual(nextcycle.build_rule_cards(main.conn, self.bid, ACTOR), 0)

    def test_two_rejections_of_the_same_tag_make_a_card(self):
        self._reject(_print(tone="blunt"))
        self._reject(_print(tone="blunt"))
        self.assertEqual(nextcycle.build_rule_cards(main.conn, self.bid, ACTOR), 1)
        cards = nextcycle.list_pending_rule_cards(main.conn, self.bid)
        self.assertEqual(cards[0]["fingerprint_axis"], "tone")
        self.assertEqual(cards[0]["reject_count"], 2)

    def test_data_error_rejections_never_become_cards(self):
        self._reject(_print(), reason_code="wrong_product")
        self._reject(_print(), reason_code="wrong_product")
        self.assertEqual(nextcycle.build_rule_cards(main.conn, self.bid, ACTOR), 0)

    def test_accepting_promotes_it_to_a_brand_rule(self):
        self._reject(_print(tone="blunt"))
        self._reject(_print(tone="blunt"))
        nextcycle.build_rule_cards(main.conn, self.bid, ACTOR)
        card = nextcycle.list_pending_rule_cards(main.conn, self.bid)[0]
        result = nextcycle.decide_rule_card(main.conn, self.bid, card["id"], accept=True,
                                            actor=ACTOR)
        self.assertEqual(result["status"], "accepted")
        self.assertIsNotNone(result["promoted_rule_id"])
        rules = bi_repo.list_rules_for_brand(main.conn, self.bid)
        self.assertTrue(any(r["id"] == result["promoted_rule_id"] for r in rules))

    def test_declining_creates_no_rule_and_stops_asking(self):
        self._reject(_print(tone="blunt"))
        self._reject(_print(tone="blunt"))
        nextcycle.build_rule_cards(main.conn, self.bid, ACTOR)
        card = nextcycle.list_pending_rule_cards(main.conn, self.bid)[0]
        nextcycle.decide_rule_card(main.conn, self.bid, card["id"], accept=False, actor=ACTOR)
        self.assertEqual(nextcycle.list_pending_rule_cards(main.conn, self.bid), [])
        self._reject(_print(tone="blunt"))
        nextcycle.build_rule_cards(main.conn, self.bid, ACTOR)
        self.assertEqual(nextcycle.list_pending_rule_cards(main.conn, self.bid), [])

    def test_rule_card_accept_works_without_operator_cookie(self):
        """ADR 0004：規則卡採納不再要求先設定操作人。"""
        self._reject(_print(tone="blunt"))
        self._reject(_print(tone="blunt"))
        nextcycle.build_rule_cards(main.conn, self.bid, ACTOR)
        card = nextcycle.list_pending_rule_cards(main.conn, self.bid)[0]
        self.client.cookies.clear()
        resp = self.client.post(f"/brands/{self.bid}/ads/rule-cards/{card['id']}/accept",
                                follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertNotIn("/settings/operator", resp.headers["location"])
        row = main.conn.execute(
            "SELECT decided_by FROM creative_rule_card WHERE id = ?", (card["id"],)).fetchone()
        self.assertEqual(row["decided_by"], OPERATOR)


class RuleCardRelativeThresholdTest(_BaseNextCycleTest):
    """修憲落地 G3（決策 0035 第5點）：舊門檻只數分子（被拒次數）不數分母（這個軸值總共
    出現過幾次），一期隨機退幾則素材就有相當機率巧合撞到絕對次數、鑄成永久禁令。
    新門檻改看拒絕比例是否明顯高於同軸其他值——這裡用模擬的拒絕分布重現並證明修好了。
    """

    def _bulk(self, value, appear, reject_n, axis="tone"):
        """製造 `appear` 次同一軸值的出現，其中 `reject_n` 次被拒——appear 含被拒的那幾次。"""
        for _ in range(appear - reject_n):
            self._generate(_print(**{axis: value}))
        for _ in range(reject_n):
            self._reject(_print(**{axis: value}))

    def test_old_threshold_would_fire_on_noise_but_new_one_does_not(self):
        """blunt／warm 都剛好被拒 2 次——舊的絕對次數門檻（RULE_CARD_THRESHOLD=2）看到這裡
        就會各鑄成一張候選卡。但兩者出現次數都很多（各20次），拒絕比例只有10%，跟同軸
        其他值比起來並不突出，只是巧合被拒到 2 次——新門檻不該把這種雜訊鑄成禁令。"""
        self._bulk("blunt", appear=20, reject_n=2)
        self._bulk("warm", appear=20, reject_n=2)
        # urgent 拒絕比例遠高於其他值（62.5% vs 同軸其他值合計10%），是真的方向有問題，
        # 新門檻該抓到——同一批資料裡放進去，證明新邏輯不是「乾脆都不產卡」交差了事。
        self._bulk("urgent", appear=8, reject_n=5)

        self.assertEqual(nextcycle.build_rule_cards(main.conn, self.bid, ACTOR), 1)
        cards = nextcycle.list_pending_rule_cards(main.conn, self.bid)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["fingerprint_value"], "urgent")
        values_with_cards = {c["fingerprint_value"] for c in cards}
        self.assertNotIn("blunt", values_with_cards)
        self.assertNotIn("warm", values_with_cards)

    def test_noise_shows_up_as_observing_not_silence(self):
        """沒鑄成禁令不等於什麼都不顯示——沒過門檻的先降級為「觀察中」，只顯示不進 prompt。"""
        self._bulk("blunt", appear=20, reject_n=2)
        self._bulk("warm", appear=20, reject_n=2)
        self._bulk("urgent", appear=8, reject_n=5)
        nextcycle.build_rule_cards(main.conn, self.bid, ACTOR)

        signals = nextcycle.list_observing_signals(main.conn, self.bid)
        observed_values = {(s["axis_label"], s["value_label"]) for s in signals}
        self.assertIn((fp.AXES["tone"]["label"], fp.axis_value_label("tone", "blunt")),
                      observed_values)
        self.assertIn((fp.AXES["tone"]["label"], fp.axis_value_label("tone", "warm")),
                      observed_values)
        # urgent 已經達門檻升級成候選卡，不該同時留在「觀察中」
        self.assertNotIn((fp.AXES["tone"]["label"], fp.axis_value_label("tone", "urgent")),
                         observed_values)

    def test_no_baseline_data_falls_back_to_the_floor(self):
        """新品牌剛開始、同一軸只出現過這一個值時沒有基準可比——退回絕對次數門檻，
        不會因為找不到比較對象就永遠卡在「觀察中」。"""
        self._bulk("blunt", appear=2, reject_n=2)
        self.assertEqual(nextcycle.build_rule_cards(main.conn, self.bid, ACTOR), 1)

    def test_window_ignores_cycles_older_than_the_lookback(self):
        """時間窗只算最近 RULE_CARD_WINDOW_CYCLES 期——舊期的拒絕紀錄被擠出窗口後不再累加。"""
        old_cycle = self._make_cycle("2020-01-01T00:00:00")
        self._reject(_print(tone="blunt"), cycle_id=old_cycle)
        self._reject(_print(tone="blunt"), cycle_id=old_cycle)
        # 補滿窗口：3 期比舊期更新的，把舊期擠出「最近3期」
        self._make_cycle("2030-01-01T00:00:00")
        self._make_cycle("2030-01-02T00:00:00")
        self._make_cycle("2030-01-03T00:00:00")

        self.assertEqual(nextcycle.build_rule_cards(main.conn, self.bid, ACTOR), 0)
        self.assertEqual(nextcycle.list_pending_rule_cards(main.conn, self.bid), [])


class OverclaimClaimCardTest(_BaseNextCycleTest):
    """修憲落地 L4（決策 0034 第 8 點）：`overclaim` 被拒累積到門檻 → 每則還沒處理過的
    踩線素材各產一張候選卡，AI 已經寫出來的那句直接當草稿，接受就直接寫進 claim（禁用宣稱）。
    維持決策 0030 第 6 點的切分：overclaim 不升級成風格禁令（不進 build_rule_cards）。
    """

    def _make_variant(self, content, product_id=None):
        cell_id = new_id("exc")
        brief_id = new_id("cbf")
        variant_id = new_id("cvr")
        ts = now_iso()
        main.conn.execute(
            "INSERT INTO experiment_cell (id, campaign_cycle_id, brand_id, created_at)"
            " VALUES (?, ?, ?, ?)", (cell_id, self.cycle_id, self.bid, ts))
        main.conn.execute(
            "INSERT INTO creative_brief (id, campaign_cycle_id, experiment_cell_id, brand_id,"
            " brief_type, purpose, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, 'copy', '測試', 'dispatched', ?, ?)",
            (brief_id, self.cycle_id, cell_id, self.bid, ts, ts))
        main.conn.execute(
            "INSERT INTO creative_variant (id, variant_type, creative_brief_id,"
            " campaign_cycle_id, experiment_cell_id, brand_id, product_id, attributes_json,"
            " fingerprint_json, status, created_at)"
            " VALUES (?, 'hook', ?, ?, ?, ?, ?, ?, ?, 'DRAFT', ?)",
            (variant_id, brief_id, self.cycle_id, cell_id, self.bid, product_id,
             json.dumps({"content": content}, ensure_ascii=False),
             json.dumps(_print(), ensure_ascii=False), ts))
        main.conn.commit()
        return variant_id

    def _reject_overclaim(self, content, product_id=None):
        variant_id = self._make_variant(content, product_id=product_id)
        ads_creative.reject(main.conn, self.bid, variant_id, reason_code="overclaim", actor=ACTOR)
        return variant_id

    def test_one_overclaim_rejection_is_not_enough(self):
        self._reject_overclaim("這是全世界最有效的配方")
        self.assertEqual(nextcycle.build_overclaim_claim_cards(main.conn, self.bid, ACTOR), 0)

    def test_two_overclaim_rejections_each_get_their_own_card(self):
        self._reject_overclaim("這是全世界最有效的配方")
        self._reject_overclaim("吃三天就有感")
        self.assertEqual(nextcycle.build_overclaim_claim_cards(main.conn, self.bid, ACTOR), 2)
        cards = nextcycle.list_pending_rule_cards(main.conn, self.bid)
        self.assertEqual(len(cards), 2)
        self.assertTrue(all(c["is_overclaim_claim"] for c in cards))
        texts = {c["proposed_rule_text"] for c in cards}
        self.assertEqual(texts, {"這是全世界最有效的配方", "吃三天就有感"})

    def test_does_not_duplicate_cards_on_rebuild(self):
        self._reject_overclaim("這是全世界最有效的配方")
        self._reject_overclaim("吃三天就有感")
        nextcycle.build_overclaim_claim_cards(main.conn, self.bid, ACTOR)
        self.assertEqual(nextcycle.build_overclaim_claim_cards(main.conn, self.bid, ACTOR), 0)
        self.assertEqual(len(nextcycle.list_pending_rule_cards(main.conn, self.bid)), 2)

    def test_accepting_registers_a_forbidden_claim(self):
        self._reject_overclaim("這是全世界最有效的配方", product_id=self.product)
        self._reject_overclaim("吃三天就有感")
        nextcycle.build_overclaim_claim_cards(main.conn, self.bid, ACTOR)
        card = next(c for c in nextcycle.list_pending_rule_cards(main.conn, self.bid)
                    if c["proposed_rule_text"] == "這是全世界最有效的配方")
        result = nextcycle.decide_rule_card(main.conn, self.bid, card["id"], accept=True,
                                            actor=ACTOR)
        self.assertEqual(result["status"], "accepted")
        claims = bi_repo.list_claims_for_brand(main.conn, self.bid)
        self.assertTrue(any(c["claim_text"] == "這是全世界最有效的配方"
                            and c["claim_type"] == "forbidden" for c in claims))

    def test_declining_creates_no_claim(self):
        self._reject_overclaim("這是全世界最有效的配方")
        self._reject_overclaim("吃三天就有感")
        nextcycle.build_overclaim_claim_cards(main.conn, self.bid, ACTOR)
        card = nextcycle.list_pending_rule_cards(main.conn, self.bid)[0]
        nextcycle.decide_rule_card(main.conn, self.bid, card["id"], accept=False, actor=ACTOR)
        self.assertEqual(bi_repo.list_claims_for_brand(main.conn, self.bid), [])

    def test_overclaim_does_not_leak_into_style_rule_cards(self):
        """維持決策 0030 第 6 點的切分：overclaim 不升級成風格禁令。"""
        self._reject_overclaim("這是全世界最有效的配方")
        self._reject_overclaim("吃三天就有感")
        self.assertEqual(nextcycle.build_rule_cards(main.conn, self.bid, ACTOR), 0)

    def test_build_wires_it_into_the_next_cycle_draft(self):
        self._reject_overclaim("這是全世界最有效的配方")
        self._reject_overclaim("吃三天就有感")
        self._run_cycle(spend=10000, impressions=20000, clicks=400, conversions=10,
                        revenue=40000)
        draft = nextcycle.load(main.conn, self.bid, self.cycle_id)["content"]
        self.assertEqual(draft["overclaim_claim_cards_created"], 2)


class ActiveBanTest(_BaseNextCycleTest):
    """票 6a／#57 的地基：「現行生效中的禁令」＝規則卡已接受、升級後的規則仍是 active。"""

    def test_no_rule_cards_means_no_active_bans(self):
        self.assertEqual(nextcycle.list_active_bans(main.conn, self.bid), [])

    def test_accepted_card_appears_as_an_active_ban(self):
        self._reject(_print(tone="blunt"))
        self._reject(_print(tone="blunt"))
        nextcycle.build_rule_cards(main.conn, self.bid, ACTOR)
        card = nextcycle.list_pending_rule_cards(main.conn, self.bid)[0]
        nextcycle.decide_rule_card(main.conn, self.bid, card["id"], accept=True, actor=ACTOR)
        bans = nextcycle.list_active_bans(main.conn, self.bid)
        self.assertEqual(len(bans), 1)
        self.assertEqual(bans[0]["fingerprint_axis"], "tone")
        self.assertEqual(bans[0]["fingerprint_value"], "blunt")

    def test_pending_card_is_not_yet_an_active_ban(self):
        self._reject(_print(tone="blunt"))
        self._reject(_print(tone="blunt"))
        nextcycle.build_rule_cards(main.conn, self.bid, ACTOR)
        self.assertEqual(nextcycle.list_active_bans(main.conn, self.bid), [])

    def test_declined_card_is_not_an_active_ban(self):
        self._reject(_print(tone="blunt"))
        self._reject(_print(tone="blunt"))
        nextcycle.build_rule_cards(main.conn, self.bid, ACTOR)
        card = nextcycle.list_pending_rule_cards(main.conn, self.bid)[0]
        nextcycle.decide_rule_card(main.conn, self.bid, card["id"], accept=False, actor=ACTOR)
        self.assertEqual(nextcycle.list_active_bans(main.conn, self.bid), [])


class EchoChamberTest(_BaseNextCycleTest):
    def _adopt(self, fingerprint, cycle_id=None):
        main.conn.execute(
            "INSERT INTO adoption_decision (id, brand_id, campaign_cycle_id, target_type,"
            " target_id, decision, fingerprint_json, decided_by, decided_at)"
            " VALUES (?, ?, ?, 'variant', ?, 'adopted', ?, ?, ?)",
            (new_id("adp"), self.bid, cycle_id, new_id("cvr"),
             json.dumps(fingerprint, ensure_ascii=False), ACTOR, now_iso()),
        )
        main.conn.commit()

    def _make_variant(self, fingerprint):
        cell_id = new_id("exc")
        brief_id = new_id("cbf")
        ts = now_iso()
        main.conn.execute(
            "INSERT INTO experiment_cell (id, campaign_cycle_id, brand_id, created_at)"
            " VALUES (?, ?, ?, ?)", (cell_id, self.cycle_id, self.bid, ts))
        main.conn.execute(
            "INSERT INTO creative_brief (id, campaign_cycle_id, experiment_cell_id, brand_id,"
            " brief_type, purpose, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, 'copy', '測試', 'dispatched', ?, ?)",
            (brief_id, self.cycle_id, cell_id, self.bid, ts, ts))
        main.conn.execute(
            "INSERT INTO creative_variant (id, variant_type, creative_brief_id,"
            " campaign_cycle_id, experiment_cell_id, brand_id, attributes_json,"
            " fingerprint_json, status, created_at)"
            " VALUES (?, 'hook', ?, ?, ?, ?, ?, ?, 'DRAFT', ?)",
            (new_id("cvr"), brief_id, self.cycle_id, cell_id, self.bid,
             json.dumps({"content": "測試"}, ensure_ascii=False),
             json.dumps(fingerprint, ensure_ascii=False), ts))
        main.conn.commit()

    def test_no_history_means_no_complaint(self):
        self._make_variant(_print())
        self.assertIsNone(nextcycle.check_echo_chamber(main.conn, self.bid, self.cycle_id))

    def test_repeating_the_past_is_flagged(self):
        self._adopt(_print(), cycle_id=None)
        self._make_variant(_print())
        finding = nextcycle.check_echo_chamber(main.conn, self.bid, self.cycle_id)
        self.assertIsNotNone(finding)
        self.assertEqual(finding.code, "creatives_too_similar")
        self.assertEqual(finding.severity, "info")  # 提示，不擋路

    def test_genuinely_different_creatives_pass(self):
        self._adopt(_print(), cycle_id=None)
        self._make_variant(_print(angle="curiosity", tone="warm", fmt="carousel",
                                  selling="safety"))
        self.assertIsNone(nextcycle.check_echo_chamber(main.conn, self.bid, self.cycle_id))

    def test_near_duplicates_are_flagged_not_just_exact_repeats(self):
        """修憲落地 G3（決策 0035 第9點）：舊門檻要求四軸「全部」相同才算重複，前十幾期
        幾乎不可能觸發。這裡只有一軸（賣點）不一樣，其餘三軸都跟歷史一致，也該算在原地
        打轉——不必要求完全一模一樣。"""
        self._adopt(_print(), cycle_id=None)
        self._make_variant(_print(selling="price"))
        finding = nextcycle.check_echo_chamber(main.conn, self.bid, self.cycle_id)
        self.assertIsNotNone(finding)
        self.assertEqual(finding.code, "creatives_too_similar")


class TasteRejectionFreezeTest(_BaseNextCycleTest):
    """票 T1（使用者 2026-08-06 拍板）：猜消費者反應的三條理由（too_stiff、too_ad_like、
    hook_weak）永遠停在「觀察中」，不論被拒幾次都不會鑄成永久禁令；仍可升級的只剩
    off_brand、discount_too_deep 這兩條使用者自己的政策（`fp.RULE_UPGRADABLE_REASONS`）。
    """

    def test_frozen_taste_reason_never_produces_a_card_even_at_high_counts(self):
        """就算被拒到 5 次（遠超過門檻），凍結理由也不該被鑄成候選卡。"""
        for _ in range(5):
            self._reject(_print(tone="blunt"), reason_code="too_stiff")
        self.assertEqual(nextcycle.build_rule_cards(main.conn, self.bid, ACTOR), 0)
        self.assertEqual(nextcycle.list_pending_rule_cards(main.conn, self.bid), [])

    def test_frozen_taste_reason_shows_up_as_observing_forever(self):
        """沒鑄成禁令不等於從畫面上消失——凍結理由永遠停在「觀察中」提醒使用者。"""
        self._reject(_print(tone="blunt"), reason_code="too_stiff")
        self._reject(_print(tone="blunt"), reason_code="too_stiff")
        nextcycle.build_rule_cards(main.conn, self.bid, ACTOR)
        signals = nextcycle.list_observing_signals(main.conn, self.bid)
        observed = {(s["axis_label"], s["value_label"]) for s in signals}
        self.assertIn((fp.AXES["tone"]["label"], fp.axis_value_label("tone", "blunt")), observed)
        self.assertEqual(nextcycle.list_pending_rule_cards(main.conn, self.bid), [])

    def test_mixed_policy_and_taste_rejections_still_promote_on_policy_count(self):
        """同一個 (軸, 值) 混到品味理由也不該被拖死——政策次數單獨算，足夠就照樣升級。"""
        self._reject(_print(tone="blunt"), reason_code="off_brand")
        self._reject(_print(tone="blunt"), reason_code="off_brand")
        self._reject(_print(tone="blunt"), reason_code="too_stiff")
        self._reject(_print(tone="blunt"), reason_code="too_stiff")
        self.assertEqual(nextcycle.build_rule_cards(main.conn, self.bid, ACTOR), 1)
        cards = nextcycle.list_pending_rule_cards(main.conn, self.bid)
        self.assertEqual(cards[0]["fingerprint_value"], "blunt")


if __name__ == "__main__":
    unittest.main()
