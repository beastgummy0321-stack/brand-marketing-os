"""app/tests/test_ads_carry_forward.py — R3-carry-forward-winners（B0-29／B0-36）。

「沿用有效方向」要真的讀贏家：企劃 prompt 具名帶上期真正打贏的切角（ROAS／花費／轉換數，
`carry_forward.prior_winners()`）與已驗證賠錢的方向（`carry_forward.rejected_directions()`），
不是丟一句抽象的 learning_ledger 文字讓模型自己猜「有效方向」是什麼（B0-29）；已判讀
「不成立」的方向要明講「上期此方向賠錢，已避開」，不是悄悄避開不說明理由（B0-36）。

反向檢查：R2 的 `guard_supported_verdict()` 把沒有真對照的假設降級成「看不出來」——降級後
的假設不得回頭冒充成方案依據出現在下一期企劃 prompt 裡（B0-32／B0-36 污染鏈）。

全程 FakeProvider，不發任何真實網路請求；品牌與產品名一律虛構。
"""

import atexit
import json
import shutil
import tempfile
import unittest

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_carry_forward_")

import app.main as main  # noqa: E402
from app.ads import (
    carry_forward,  # noqa: E402
    opening_suggestion,  # noqa: E402
    plan_citation,  # noqa: E402
)
from app.ads import plan as ads_plan  # noqa: E402
from app.ads import reading as ads_reading  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core.db import DEV_ORG_ID, new_id, now_iso  # noqa: E402
from app.llm.providers import FakeProvider, ProviderResponse, Usage  # noqa: E402


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"


# 兩個方案的最小合法形狀（見 plan.py::_normalize_option）：summary、冷受眾描述、至少一個
# 有 title／message 的切角。跟 test_ads_plan.py 的 _GOOD_OPTIONS 不共用一份——這裡只是
# 拿來讓 generate_options() 跑得完，不驗方案內容本身，各測試檔各自維護一份比互相耦合乾淨。
_GOOD_OPTIONS = {
    "options": [
        {
            "is_recommended": True,
            "summary": "延續上期贏家切角，主力放大。",
            "audience": {"cold": {"description": "對這個品類已經有興趣的陌生受眾。"}},
            "angles": [{"title": "延續切角", "message": "延續上期打贏的方向", "why": "已驗證"}],
        },
        {
            "is_recommended": False,
            "summary": "備案方案，測另一個角度。",
            "audience": {"cold": {"description": "同一批陌生受眾，換個訊息角度。"}},
            "angles": [{"title": "備案切角", "message": "另一種說法", "why": "分散風險"}],
        },
    ]
}


def _options_citing(winner_angle: str, roas: float = 4.31) -> dict:
    """跟 `_GOOD_OPTIONS` 一樣的最小合法形狀，但第一個（推薦）選項的 message 具名提到
    `winner_angle` 並帶出它的 ROAS 數字——票 F12 契約：推薦方案要點名贏家、還要原樣寫出
    它的成績，這裡是「有引用」的合格回覆，給本來就該通過驗證的測試情境用（不是驗證本身
    要測的東西）。`roas` 預設 4.31，對齊本檔既有 `_seed_cell(spend=21000,
    revenue=21000 * 4.31)` 這個常見寫法，呼叫端只要贏家的實際 ROAS 不是 4.31 才需要覆寫。"""
    return {
        "options": [
            {
                "is_recommended": True,
                "summary": "延續上期贏家切角，主力放大。",
                "audience": {"cold": {"description": "對這個品類已經有興趣的陌生受眾。"}},
                "angles": [{"title": "延續切角",
                           "message": f"延續上期打贏的「{winner_angle}」方向，ROAS {roas:.2f}",
                           "why": "已驗證"}],
            },
            {
                "is_recommended": False,
                "summary": "備案方案，測另一個角度。",
                "audience": {"cold": {"description": "同一批陌生受眾，換個訊息角度。"}},
                "angles": [{"title": "備案切角", "message": "另一種說法", "why": "分散風險"}],
            },
        ]
    }


def _fake(text: str) -> ProviderResponse:
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=200, output_tokens=100),
                            stop_reason="end_turn")


def _seed_cell(conn, brand_id: str, cycle_id: str, *, creative_angle: str, product_id,
              spend: float, conversions: float, revenue: float) -> str:
    """建一條完整的 performance_snapshot → external_ad_mapping → publishing_package →
    experiment_cell 鏈（比照 test_ads_nextcycle.py::HistoricalCellPerformanceTest._cell_with_ad
    既有寫法，多帶 performance_snapshot.product_id 讓 comparison_cells() 的 `ps.product_id`
    篩選也吃得到）。回傳 experiment_cell id。"""
    cell_id, pkg_id, mapping_id, ts = new_id("exc"), new_id("pkg"), new_id("xam"), now_iso()
    conn.execute(
        "INSERT INTO experiment_cell (id, org_id, campaign_cycle_id, brand_id, creative_angle,"
        " product_id, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (cell_id, DEV_ORG_ID, cycle_id, brand_id, creative_angle, product_id, ts))
    conn.execute(
        "INSERT INTO publishing_package (id, org_id, brand_id, campaign_cycle_id, experiment_cell_id,"
        " campaign_name, adset_name, ad_name, destination_url, utm_json, status, created_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '{}', 'ready', %s)",
        (pkg_id, DEV_ORG_ID, brand_id, cycle_id, cell_id, "測試活動", "測試組合", f"{creative_angle}_ad",
         "https://example.test", ts))
    conn.execute(
        "INSERT INTO external_ad_mapping (id, org_id, brand_id, publishing_package_id,"
        " campaign_cycle_id, platform, claim_status, confirmed_by, confirmed_at, created_at)"
        " VALUES (%s, %s, %s, %s, %s, 'meta', 'confirmed', %s, %s, %s)",
        (mapping_id, DEV_ORG_ID, brand_id, pkg_id, cycle_id, ACTOR, ts, ts))
    conn.execute(
        "INSERT INTO performance_snapshot (id, org_id, brand_id, campaign_cycle_id, product_id,"
        " external_ad_mapping_id, platform, date_range_start, date_range_end, as_of_date,"
        " snapshot_taken_at, currency, spend, conversions, revenue, source, created_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, 'meta', '2026-01-01', '2026-01-07', '2026-01-07', %s, 'TWD',"
        " %s, %s, %s, 'manual', %s)",
        (new_id("psn"), DEV_ORG_ID, brand_id, cycle_id, product_id, mapping_id, ts, spend, conversions,
         revenue, ts))
    conn.commit()
    return cell_id


class _BaseCarryForwardTest(unittest.TestCase):
    def setUp(self):
        self.brand = bi_repo.create_brand(main.conn, name="虛構贏家品牌",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]
        self.product = bi_repo.create_product(main.conn, self.bid, name="虛構主打品",
                                              actor=ACTOR)["id"]
        self.prior_cycle_id = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[self.product], pain_value=10000,
            objective="sales", actor=ACTOR)["id"]
        # 預設「推新品／換方向」形狀：background 空（比照前端 chosen == "" → None）。
        self.new_cycle_id = self._open_cycle()
        # 使用者真的按了「沿用有效方向」：background 是
        # f"{CARRY_FORWARD_DIRECTION}：{direction}"（比照 NewCycleDirectionChoice.tsx）。
        self.carry_forward_cycle_id = self._open_cycle(
            background=f"{opening_suggestion.CARRY_FORWARD_DIRECTION}：實證成分")
        self._orig_provider = ads_plan.PROVIDER

    def tearDown(self):
        ads_plan.PROVIDER = self._orig_provider

    def _open_cycle(self, background=None) -> str:
        return ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[self.product], pain_value=10000,
            objective="sales", actor=ACTOR, background=background)["id"]

    def _seed_cell(self, cycle_id: str, **kwargs) -> str:
        return _seed_cell(main.conn, self.bid, cycle_id, **kwargs)

    def _generate(self, cycle_id: str, reply=None):
        ads_plan.PROVIDER = FakeProvider(
            response=_fake(reply if reply is not None
                           else json.dumps(_GOOD_OPTIONS, ensure_ascii=False)))
        return ads_plan.generate_options(main.conn, self.bid, cycle_id, ACTOR)

    def _sign_off_learning(self, cycle_id: str, *, product_id, cells: list,
                           statement: str = "簽核學習測試假設") -> dict:
        """票 F7：比照 `UnvalidatedHypothesisNeverBecomesPlanGroundingTest` 既有寫法，走真的
        簽核鏈——建假設、掛進檔期、餵夠 `MIN_COMPARISON_CELLS` 個切角讓
        `guard_supported_verdict()` 真的放行「成立」，再走 `resolve_hypotheses()` 入帳
        `learning_ledger`。`cells` 是 (creative_angle, conversions, spend, revenue) 的列表。
        """
        hyp = bi_repo.create_strategy_hypothesis(
            main.conn, self.bid, actor=ACTOR, hypothesis_type="message", statement=statement,
            created_by=ACTOR, product_id=product_id, source_cycle_id=cycle_id)
        main.conn.execute(
            "INSERT INTO campaign_cycle_hypothesis (org_id, campaign_cycle_id,"
            " strategy_hypothesis_id, brand_id, role) VALUES (%s, %s, %s, %s, 'message')",
            (DEV_ORG_ID, cycle_id, hyp["id"], self.bid))
        main.conn.commit()
        for angle, conversions, spend, revenue in cells:
            self._seed_cell(cycle_id, creative_angle=angle, product_id=product_id,
                            spend=spend, conversions=conversions, revenue=revenue)
        updated = ads_reading.resolve_hypotheses(
            main.conn, self.bid, cycle_id, {hyp["id"]: "supported"}, actor=ACTOR)
        self.assertEqual(updated, 1)
        resolved = bi_repo.get_strategy_hypothesis(main.conn, self.bid, hyp["id"])
        self.assertEqual(resolved["status"], "supported")
        return hyp


class PriorWinnersRetrievalTest(_BaseCarryForwardTest):
    """直接測 `carry_forward.prior_winners()`：不經過 LLM，純粹是「贏家」定義與誠實門檻。"""

    def test_profitable_and_well_evidenced_cell_is_a_winner(self):
        self._seed_cell(self.prior_cycle_id, creative_angle="實證成分", product_id=self.product,
                        spend=21000, conversions=60, revenue=21000 * 4.31)
        winners = carry_forward.prior_winners(main.conn, self.bid)
        self.assertEqual(len(winners), 1)
        self.assertEqual(winners[0]["angle"], "實證成分")
        self.assertEqual(winners[0]["roas"], 4.31)
        self.assertEqual(winners[0]["spend"], 21000)
        self.assertEqual(winners[0]["source_cycle_id"], self.prior_cycle_id)

    def test_insufficient_evidence_is_not_a_winner_even_with_a_great_roas(self):
        """R2 同一種誠實門檻（鐵則 16）：轉換數不到可信門檻，數字再漂亮也不算贏家——
        跟 `guard_supported_verdict()` 擋「沒對照就不准喊成立」同一個道理。"""
        self._seed_cell(self.prior_cycle_id, creative_angle="太少樣本的假贏家",
                        product_id=self.product, spend=1000, conversions=3, revenue=10000)
        self.assertEqual(carry_forward.prior_winners(main.conn, self.bid), [])

    def test_underperforming_cell_is_not_a_winner(self):
        self._seed_cell(self.prior_cycle_id, creative_angle="零轉換", product_id=self.product,
                        spend=5000, conversions=0, revenue=0)
        self.assertEqual(carry_forward.prior_winners(main.conn, self.bid), [])

    def test_sorted_by_roas_desc_and_limited(self):
        self._seed_cell(self.prior_cycle_id, creative_angle="成分對比", product_id=self.product,
                        spend=18000, conversions=55, revenue=18000 * 4.28)
        self._seed_cell(self.prior_cycle_id, creative_angle="實證成分", product_id=self.product,
                        spend=21000, conversions=60, revenue=21000 * 4.31)
        winners = carry_forward.prior_winners(main.conn, self.bid, limit=1)
        self.assertEqual(len(winners), 1)
        self.assertEqual(winners[0]["angle"], "實證成分")  # 4.31 > 4.28

    def test_product_filter_excludes_other_products(self):
        other_product = bi_repo.create_product(main.conn, self.bid, name="別的產品",
                                               actor=ACTOR)["id"]
        self._seed_cell(self.prior_cycle_id, creative_angle="別產品的贏家",
                        product_id=other_product, spend=1000, conversions=60, revenue=5000)
        winners = carry_forward.prior_winners(main.conn, self.bid, product_ids={self.product})
        self.assertEqual(winners, [])


class RejectedDirectionsRetrievalTest(_BaseCarryForwardTest):
    """直接測 `carry_forward.rejected_directions()`。"""

    def test_only_rejected_status_is_returned(self):
        proposed = bi_repo.create_strategy_hypothesis(
            main.conn, self.bid, actor=ACTOR, hypothesis_type="message",
            statement="待驗證的猜想", created_by=ACTOR, product_id=self.product,
            source_cycle_id=self.prior_cycle_id)
        rejected = bi_repo.create_strategy_hypothesis(
            main.conn, self.bid, actor=ACTOR, hypothesis_type="message",
            statement="節慶檔期用禮盒／組合切角能拉高客單價，投報率會比平常好",
            created_by=ACTOR, product_id=self.product, source_cycle_id=self.prior_cycle_id)
        bi_repo.update_hypothesis_status(main.conn, self.bid, rejected["id"],
                                         status="rejected", actor=ACTOR)
        directions = carry_forward.rejected_directions(main.conn, self.bid)
        self.assertEqual([d["statement"] for d in directions],
                         ["節慶檔期用禮盒／組合切角能拉高客單價，投報率會比平常好"])
        self.assertEqual(directions[0]["source_cycle_id"], self.prior_cycle_id)
        self.assertNotIn(proposed["id"], [d["id"] for d in directions])

    def test_product_filter_keeps_brand_level_entries_and_drops_other_products(self):
        brand_level = bi_repo.create_strategy_hypothesis(
            main.conn, self.bid, actor=ACTOR, hypothesis_type="audience",
            statement="品牌層賠錢方向", created_by=ACTOR, product_id=None,
            source_cycle_id=self.prior_cycle_id)
        bi_repo.update_hypothesis_status(main.conn, self.bid, brand_level["id"],
                                         status="rejected", actor=ACTOR)
        other_product = bi_repo.create_product(main.conn, self.bid, name="別的產品",
                                               actor=ACTOR)["id"]
        other = bi_repo.create_strategy_hypothesis(
            main.conn, self.bid, actor=ACTOR, hypothesis_type="audience",
            statement="別產品的賠錢方向", created_by=ACTOR, product_id=other_product,
            source_cycle_id=self.prior_cycle_id)
        bi_repo.update_hypothesis_status(main.conn, self.bid, other["id"],
                                         status="rejected", actor=ACTOR)
        directions = carry_forward.rejected_directions(main.conn, self.bid,
                                                    product_ids={self.product})
        self.assertEqual([d["statement"] for d in directions], ["品牌層賠錢方向"])


class SignedOffLearningWinnerTest(_BaseCarryForwardTest):
    """票 F7（2026-08-25 使用者裁決 option 1）：人親自簽核「成立」的學習，就算樣本數沒到
    `WEEKLY_CONVERSIONS_PER_GROUP` 統計門檻也算贏家——低門檻給人簽的、高門檻給機器自動
    加碼／停損卡用，兩件事分開（B2 F2 ❌ 重現的正是同一個問題兩套不同的門檻）。"""

    def test_signed_off_learning_below_statistical_threshold_is_still_a_winner(self):
        """票 F11：贏家是學習句子點名的切角，不是那期 ROAS 最高的切角——這裡刻意讓
        「使用者見證」的 ROAS 比句子點名的「實證成分」還高，若橋接還是舊的 argmax
        （F7 原本的寫法），這裡會錯拿「使用者見證」。"""
        self._sign_off_learning(
            self.prior_cycle_id, product_id=self.product,
            statement="拿證據說話的實證成分比純促銷更能拉高轉換率",
            cells=[("實證成分", 22, 12000, 12000 * 3.0), ("使用者見證", 20, 11000, 11000 * 4.30)])
        winners = carry_forward.prior_winners(main.conn, self.bid)
        self.assertEqual(len(winners), 1)
        self.assertEqual(winners[0]["angle"], "實證成分")
        self.assertEqual(winners[0]["roas"], 3.0)
        self.assertEqual(winners[0]["source_cycle_id"], self.prior_cycle_id)
        self.assertLess(winners[0]["conversions"], 50)  # 統計門檻在這條來源不適用，但轉換數仍如實回報

    def test_no_signed_learning_and_insufficient_statistical_evidence_still_returns_no_winners(self):
        """契約 done-check 3：兩邊來源都沒東西，`prior_winners()` 仍回空——加了新來源不能
        變得比原本寬鬆。"""
        self._seed_cell(self.prior_cycle_id, creative_angle="太少樣本的假贏家",
                        product_id=self.product, spend=1000, conversions=3, revenue=10000)
        self.assertEqual(carry_forward.prior_winners(main.conn, self.bid), [])

    def test_plan_ignoring_signed_off_winner_is_rejected_not_stored(self):
        """契約 done-check 2：`FakeProvider` 回的方案沒引用這條簽核贏家，
        `citation_violations()` 要擋下、錯誤訊息具名點出切角，不能悄悄存進去。"""
        self._sign_off_learning(
            self.prior_cycle_id, product_id=self.product,
            statement="拿證據說話的實證成分比純促銷更能拉高轉換率",
            cells=[("實證成分", 22, 12000, 12000 * 4.30), ("使用者見證", 20, 11000, 11000 * 3.0)])
        ok, err = self._generate(self.carry_forward_cycle_id)  # 預設 _GOOD_OPTIONS 沒提到「實證成分」
        self.assertFalse(ok)
        self.assertIn("實證成分", err)
        self.assertEqual(
            ads_plan.get_pending_options(main.conn, self.bid, self.carry_forward_cycle_id), [])

    def test_plan_citing_only_one_of_two_signed_off_winners_is_rejected_naming_the_missing_one(self):
        """票 F12 done-check 6：兩個具名贏家，推薦方案只交代其中一個（連數字都寫對）——
        另一個完全沒被沿用，錯誤訊息要點名那個沒被交代的贏家，方案整批不落地。RED first：
        F2 舊的 `any()` 只要有任何一個贏家在任何選項出現過就放行，這裡「實證成分」有被
        引用，舊碼會誤判整批通過。"""
        self._sign_off_learning(
            self.prior_cycle_id, product_id=self.product,
            statement="拿證據說話的切角（實證成分／成分對比）比純促銷更能拉高轉換率",
            cells=[("實證成分", 22, 12000, 12000 * 4.30), ("成分對比", 18, 9000, 9000 * 3.50),
                   ("使用者見證", 20, 11000, 11000 * 5.0)])
        reply = _options_citing("實證成分", roas=4.30)  # 只交代兩個贏家的其中一個
        ok, err = self._generate(self.carry_forward_cycle_id,
                                 reply=json.dumps(reply, ensure_ascii=False))
        self.assertFalse(ok)
        self.assertIn("成分對比", err)
        self.assertEqual(
            ads_plan.get_pending_options(main.conn, self.bid, self.carry_forward_cycle_id), [])

    def test_learning_naming_no_cell_of_its_cycle_contributes_no_winner(self):
        """票 F11 done-check 2：學習句子沒點名這期任何一個切角（都是代號形狀）——不准
        落回「那期 ROAS 最高的」當贏家，這條 entry 就是沒有贏家。RED first：F7 原本的
        argmax 橋接會在這裡選出 `fatigue`（真實資料重現的正是這個案例）。"""
        self._sign_off_learning(
            self.prior_cycle_id, product_id=self.product,
            statement="拿證據說話的切角比純促銷更能拉高轉換率",
            cells=[("normal_1", 30, 4500, 4500 * 6.60), ("fatigue", 30, 4500, 4500 * 6.60),
                   ("bad_cvr", 30, 4500, 4500 * 0.99)])
        self.assertEqual(carry_forward.prior_winners(main.conn, self.bid), [])

    def test_learning_naming_two_cells_returns_both_with_their_own_roas(self):
        """票 F11 done-check 3：一句學習點名兩個切角，兩個都要回來，各自帶自己的 ROAS
        ——沒被點名的第三個切角（使用者見證，ROAS 更高）不算數。"""
        self._sign_off_learning(
            self.prior_cycle_id, product_id=self.product,
            statement="拿證據說話的切角（實證成分／成分對比）比純促銷更能拉高轉換率",
            cells=[("實證成分", 22, 12000, 12000 * 4.30), ("成分對比", 18, 9000, 9000 * 3.50),
                   ("使用者見證", 20, 11000, 11000 * 5.0)])
        winners = carry_forward.prior_winners(main.conn, self.bid)
        self.assertEqual({w["angle"] for w in winners}, {"實證成分", "成分對比"})
        by_angle = {w["angle"]: w for w in winners}
        self.assertEqual(by_angle["實證成分"]["roas"], 4.30)
        self.assertEqual(by_angle["成分對比"]["roas"], 3.50)


class PromptIncludesCarryForwardDataTest(_BaseCarryForwardTest):
    """整合測：組進 `generate_options()` 實際送給模型的 prompt 文字（契約第 2、3 點）。"""

    def test_prior_winner_and_avoid_direction_are_named_with_roas_and_reason(self):
        """契約例：從 C2 重開下一期要看到「實證成分」與其 ROAS；從 C4 重開下一期要看到
        「上期此方向賠錢，已避開」——兩件事這裡一次驗，因為都是同一支 prompt 組裝函式。"""
        self._seed_cell(self.prior_cycle_id, creative_angle="實證成分", product_id=self.product,
                        spend=21000, conversions=60, revenue=21000 * 4.31)
        rejected = bi_repo.create_strategy_hypothesis(
            main.conn, self.bid, actor=ACTOR, hypothesis_type="message",
            statement="節慶檔期用禮盒／組合切角能拉高客單價，投報率會比平常好",
            created_by=ACTOR, product_id=self.product, source_cycle_id=self.prior_cycle_id)
        bi_repo.update_hypothesis_status(main.conn, self.bid, rejected["id"],
                                         status="rejected", actor=ACTOR)

        ok, err = self._generate(self.carry_forward_cycle_id,
                                 reply=json.dumps(_options_citing("實證成分"), ensure_ascii=False))
        self.assertTrue(ok, err)
        sent = ads_plan.PROVIDER.calls[0]["messages"][0]["content"]
        self.assertIn("實證成分", sent)
        self.assertIn("ROAS 4.31", sent)
        self.assertIn("節慶檔期用禮盒／組合切角能拉高客單價，投報率會比平常好", sent)
        self.assertIn("上期此方向賠錢，已避開", sent)

    def test_prompt_tells_the_model_recommended_option_must_name_each_winner_with_roas(self):
        """票 F12 done-check 7：prompt 要明講「推薦方案」必須逐一點名每個贏家、原樣寫出
        ROAS 數字——不是只帶贏家清單讓模型自己猜。斷言新指示文字本身，不是贏家名字
        （那段 :346-360 已經驗過）。"""
        self._seed_cell(self.prior_cycle_id, creative_angle="實證成分", product_id=self.product,
                        spend=21000, conversions=60, revenue=21000 * 4.31)
        ok, err = self._generate(self.carry_forward_cycle_id,
                                 reply=json.dumps(_options_citing("實證成分"), ensure_ascii=False))
        self.assertTrue(ok, err)
        sent = ads_plan.PROVIDER.calls[0]["messages"][0]["content"]
        self.assertIn("逐一點名", sent)
        self.assertIn("ROAS 數字", sent)

    def test_per_winner_demand_moves_into_numbered_hard_rules_and_winner_lines_get_a_reminder(self):
        """票 F15 done-check 6：逐一點名／原樣寫出 ROAS 數字的規定要搬進編號硬規則清單，
        規則數要跟著改；贏家清單裡每一行也要各自帶一句簡短提醒。RED first：今天這句指示
        還在贏家段落下面的段落文字裡，不在「N條硬規則」清單編號裡，規則數還是「六」。"""
        self._seed_cell(self.prior_cycle_id, creative_angle="實證成分", product_id=self.product,
                        spend=21000, conversions=60, revenue=21000 * 4.31)
        ok, err = self._generate(self.carry_forward_cycle_id,
                                 reply=json.dumps(_options_citing("實證成分"), ensure_ascii=False))
        self.assertTrue(ok, err)
        sent = ads_plan.PROVIDER.calls[0]["messages"][0]["content"]
        self.assertIn("七條硬規則：", sent)
        before, rules_block = sent.split("七條硬規則：", 1)
        self.assertIn("7. ", rules_block)
        self.assertIn("逐一點名", rules_block)
        self.assertIn("ROAS 數字", rules_block)
        self.assertNotIn("逐一點名", before)  # 不再留在贏家段落文字裡
        winner_line = next(line for line in sent.splitlines() if line.startswith("- 實證成分"))
        self.assertIn("也要在推薦案裡出現，並寫出這個數字", winner_line)

    def test_low_evidence_winner_does_not_leak_into_the_prompt(self):
        """反向檢查：樣本不足的切角就算 ROAS 好看，也不准當「贏家」引用進 prompt。"""
        self._seed_cell(self.prior_cycle_id, creative_angle="太少樣本的假贏家",
                        product_id=self.product, spend=1000, conversions=3, revenue=10000)
        ok, err = self._generate(self.carry_forward_cycle_id)  # 就算走沿用模式也不准冒充
        self.assertTrue(ok, err)
        sent = ads_plan.PROVIDER.calls[0]["messages"][0]["content"]
        self.assertNotIn("太少樣本的假贏家", sent)

    def test_no_history_means_no_new_sections(self):
        """就算走沿用模式，沒有任何歷史贏家／賠錢方向時（例如真的第一次開檔），
        不新增空段落——照舊行為（回歸鐵條）。"""
        ok, err = self._generate(self.carry_forward_cycle_id)
        self.assertTrue(ok, err)
        sent = ads_plan.PROVIDER.calls[0]["messages"][0]["content"]
        self.assertNotIn("上期以來真正打出成績的切角", sent)
        self.assertNotIn("已驗證賠錢、這期不要再選的方向", sent)
        # 票 F15：沒有贏家可點名時，硬規則清單不該多出第 7 條，規則數詞要照樣是「六」。
        self.assertIn("六條硬規則：", sent)
        self.assertNotIn("七條硬規則", sent)


class UnvalidatedHypothesisNeverBecomesPlanGroundingTest(_BaseCarryForwardTest):
    """B0-32／B0-36 反向檢查：C3 只投了 1 個切角（沒有真的 A/B 對照）卻把假設結成「成立」，
    R2 的 `guard_supported_verdict()` 會把它降級成「看不出來」、擋在 learning_ledger 門外。
    這裡驗證降級後的假設真的不會回頭冒充成方案依據出現在下一期企劃 prompt 裡（契約第 3 點）。
    """

    def test_downgraded_hypothesis_never_reaches_the_next_plan_prompt(self):
        # 只投了 1 個切角，沒有 B 邊可比——跟 B0-32 重現步驟一樣的形狀。
        self._seed_cell(self.prior_cycle_id, creative_angle="情感痛點開場",
                        product_id=self.product, spend=5000, conversions=60, revenue=25000)
        hyp = bi_repo.create_strategy_hypothesis(
            main.conn, self.bid, actor=ACTOR, hypothesis_type="message",
            statement="情感痛點開場優於功能宣稱開場", created_by=ACTOR,
            product_id=self.product, source_cycle_id=self.prior_cycle_id)
        main.conn.execute(
            "INSERT INTO campaign_cycle_hypothesis (org_id, campaign_cycle_id,"
            " strategy_hypothesis_id, brand_id, role) VALUES (%s, %s, %s, %s, 'message')",
            (DEV_ORG_ID, self.prior_cycle_id, hyp["id"], self.bid))
        main.conn.commit()

        updated = ads_reading.resolve_hypotheses(
            main.conn, self.bid, self.prior_cycle_id, {hyp["id"]: "supported"}, actor=ACTOR)
        self.assertEqual(updated, 1)
        resolved = bi_repo.get_strategy_hypothesis(main.conn, self.bid, hyp["id"])
        self.assertEqual(resolved["status"], "inconclusive")  # guard 擋下，不是「成立」
        self.assertEqual(ads_repo.list_learning_ledger(main.conn, self.bid), [])  # 沒入帳

        ok, err = self._generate(
            self.carry_forward_cycle_id,
            # 這顆切角是真的統計贏家（revenue 25000 / spend 5000 = ROAS 5.00），跟被
            # guard 擋下的假設無關——票 F12 新增數字驗證後，要對齊它真正的 ROAS。
            reply=json.dumps(_options_citing("情感痛點開場", roas=5.00), ensure_ascii=False))
        self.assertTrue(ok, err)
        sent = ads_plan.PROVIDER.calls[0]["messages"][0]["content"]
        self.assertNotIn("情感痛點開場優於功能宣稱開場", sent)


class CarryForwardModeGateTest(_BaseCarryForwardTest):
    """鎖兩條分支（reviewer 抓到的原始缺陷）：`plan.py` 曾經不管使用者按哪一顆按鈕，
    一律把上期贏家／避開清單塞進 prompt——「沿用有效方向」與「推新品／換方向」兩個
    cycle 的 prompt 逐字元相同，還帶著一句「不要整批換成沒出現過的新切角」，直接跟
    選了換方向的使用者的意思對著幹。這裡用同一份歷史資料，鎖住兩條分支長得不一樣。"""

    def setUp(self):
        super().setUp()
        self._seed_cell(self.prior_cycle_id, creative_angle="實證成分", product_id=self.product,
                        spend=21000, conversions=60, revenue=21000 * 4.31)
        rejected = bi_repo.create_strategy_hypothesis(
            main.conn, self.bid, actor=ACTOR, hypothesis_type="message",
            statement="節慶檔期用禮盒／組合切角能拉高客單價，投報率會比平常好",
            created_by=ACTOR, product_id=self.product, source_cycle_id=self.prior_cycle_id)
        bi_repo.update_hypothesis_status(main.conn, self.bid, rejected["id"],
                                         status="rejected", actor=ACTOR)

    def test_carry_forward_gets_the_block_fresh_direction_does_not(self):
        ok, err = self._generate(self.carry_forward_cycle_id,
                                 reply=json.dumps(_options_citing("實證成分"), ensure_ascii=False))
        self.assertTrue(ok, err)
        carry_forward_prompt = ads_plan.PROVIDER.calls[0]["messages"][0]["content"]

        ok, err = self._generate(self.new_cycle_id)  # background="" → None，「推新品／換方向」
        self.assertTrue(ok, err)
        fresh_direction_prompt = ads_plan.PROVIDER.calls[0]["messages"][0]["content"]

        self.assertIn("實證成分：ROAS 4.31", carry_forward_prompt)
        self.assertIn("上期此方向賠錢，已避開", carry_forward_prompt)

        self.assertNotIn("實證成分：ROAS", fresh_direction_prompt)
        self.assertNotIn("上期此方向賠錢，已避開", fresh_direction_prompt)
        self.assertNotIn("不要整批換成沒出現過的新切角", fresh_direction_prompt)
        self.assertNotEqual(carry_forward_prompt, fresh_direction_prompt)

    def test_custom_free_text_direction_also_does_not_get_the_block(self):
        """使用者自己打字選方向（`NewCycleDirectionChoice.tsx` 第三個選項）也不是沿用——
        跟「推新品／換方向」一樣不該塞上期歷史，使用者已經自己講了要打什麼。"""
        custom_cycle = self._open_cycle(background="這期主打中秋禮盒，別的都先不用管")
        ok, err = self._generate(custom_cycle)
        self.assertTrue(ok, err)
        sent = ads_plan.PROVIDER.calls[0]["messages"][0]["content"]
        self.assertNotIn("實證成分：ROAS", sent)
        self.assertNotIn("上期此方向賠錢，已避開", sent)


class CarryForwardTextareaEditKeepsThePrefixTest(_BaseCarryForwardTest):
    """使用者按「沿用有效方向」，但落到 `OpeningSuggestionCard.tsx` 的後備表單（建議卡
    讀取失敗／沒有可主打商品，122-131／133-142 行）——`IntakeStep.tsx` 把 `initialBackground`
    塞進一個可編輯 `<textarea>`。修法前這欄直接綁 `initialBackground`，使用者一改，整段
    （含「沿用有效方向：」前綴）就被換成使用者自己打的字，沿用信號悄悄消失、退回 R3 前的
    行為（安全失敗：不會反過來汙染「換方向」分支，但也不該悄悄發生）。

    修法（`IntakeStep.tsx`）：前綴釘死成不可編輯的一行，`<textarea>` 只收補充文字，送出時
    用 `pinned + "\\n" + 補充文字` 原樣接在後面（`carryForwardPinned` 那段邏輯）。這裡驗證
    那個「使用者編輯過」的 background 字串送進後端，plan prompt 仍然帶上贏家清單——不是
    測 TSX 本身（repo 沒有前端測試工具鏈），是鎖住 `IntakeStep.tsx` 送出的字串形狀跟後端
    `_is_carry_forward_cycle()` 之間的契約：只要前綴保留在開頭，訊號就不會丟。
    """

    def setUp(self):
        super().setUp()
        self._seed_cell(self.prior_cycle_id, creative_angle="實證成分", product_id=self.product,
                        spend=21000, conversions=60, revenue=21000 * 4.31)

    def test_edited_textarea_with_pinned_prefix_still_gets_the_block(self):
        pinned = f"{opening_suggestion.CARRY_FORWARD_DIRECTION}：實證成分"
        edited_background = pinned + "\n使用者自己多補的一句話"  # IntakeStep.tsx 修法後的送出形狀
        cycle_id = self._open_cycle(background=edited_background)

        ok, err = self._generate(cycle_id,
                                 reply=json.dumps(_options_citing("實證成分"), ensure_ascii=False))
        self.assertTrue(ok, err)
        sent = ads_plan.PROVIDER.calls[0]["messages"][0]["content"]
        self.assertIn("實證成分：ROAS 4.31", sent)


class WinnerCitationGuardTest(_BaseCarryForwardTest):
    """票 F2 契約 (b)：具名贏家沒被任何切角引用、或已避開的方向原封不動又冒出來，都要讓
    生成可見地失敗（回 False + 錯誤訊息），不能形狀合法就悄悄存進 campaign_plan_option。"""

    def setUp(self):
        super().setUp()
        self._seed_cell(self.prior_cycle_id, creative_angle="實證成分對比", product_id=self.product,
                        spend=21000, conversions=60, revenue=21000 * 4.31)
        rejected = bi_repo.create_strategy_hypothesis(
            main.conn, self.bid, actor=ACTOR, hypothesis_type="message",
            statement="純促銷折扣", created_by=ACTOR,
            product_id=self.product, source_cycle_id=self.prior_cycle_id)
        bi_repo.update_hypothesis_status(main.conn, self.bid, rejected["id"],
                                         status="rejected", actor=ACTOR)

    def test_options_ignoring_named_winner_are_rejected_not_stored(self):
        """預設 `_GOOD_OPTIONS` 的切角完全沒提到「實證成分對比」——模型當贏家不存在。"""
        ok, err = self._generate(self.carry_forward_cycle_id)
        self.assertFalse(ok)
        self.assertIn("實證成分對比", err)
        self.assertEqual(
            ads_plan.get_pending_options(main.conn, self.bid, self.carry_forward_cycle_id), [])

    def test_avoid_direction_reused_verbatim_is_rejected(self):
        """有引用贏家，但另一個切角把已避開的方向原封不動端回來。"""
        reply = _options_citing("實證成分對比")
        reply["options"][1]["angles"][0]["title"] = "純促銷折扣"
        reply["options"][1]["angles"][0]["message"] = "純促銷折扣"
        ok, err = self._generate(self.carry_forward_cycle_id,
                                 reply=json.dumps(reply, ensure_ascii=False))
        self.assertFalse(ok)
        self.assertIn("純促銷折扣", err)
        self.assertEqual(
            ads_plan.get_pending_options(main.conn, self.bid, self.carry_forward_cycle_id), [])

    def test_options_citing_winner_and_avoiding_avoided_direction_are_accepted(self):
        """正面對照：真的沿用贏家、沒有重提避開方向，一樣照常通過並存進去。"""
        ok, err = self._generate(self.carry_forward_cycle_id,
                                 reply=json.dumps(_options_citing("實證成分對比"), ensure_ascii=False))
        self.assertTrue(ok, err)
        self.assertEqual(
            len(ads_plan.get_pending_options(main.conn, self.bid, self.carry_forward_cycle_id)), 2)


def _option(is_recommended: bool, *, summary: str = "", difference: str = "",
           angles: list = None) -> dict:
    """票 F12 單元測試用的最小合法方案形狀，跳過 `_normalize_option()`——直接手動對齊它
    的輸出契約（`summary`／`difference`／`angles`／`is_recommended`）就好。"""
    return {
        "is_recommended": is_recommended,
        "summary": summary,
        "difference": difference,
        "angles": angles or [{"title": "", "message": ""}],
    }


class CitationViolationsUnitTest(unittest.TestCase):
    """票 F12 契約：`citation_violations()` 只看推薦方案，贏家不只要被點名，還要被原樣
    寫出 ROAS 數字。純函式測試，不碰 DB——`prior_winners` 手動對齊
    `carry_forward.prior_winners()` 的輸出形狀即可。"""

    _WINNER_A = {"angle": "成分對比", "roas": 4.30, "spend": 9000, "conversions": 18,
                "source_cycle_id": "cyc_a"}
    _WINNER_B = {"angle": "實證成分", "roas": 4.30, "spend": 12000, "conversions": 22,
                "source_cycle_id": "cyc_b"}

    def test_recommended_cites_only_one_of_two_winners_names_the_missing_one(self):
        """done-check 1：推薦方案交代了一個贏家（含數字），另一個完全沒提——訊息要點名
        缺的那個，不是點名已經交代好的那個。"""
        recommended = _option(True, angles=[{"title": "延續切角",
                                              "message": "延續「成分對比」方向，ROAS 4.30"}])
        alt = _option(False, angles=[{"title": "備案", "message": "另一種說法"}])
        violations = plan_citation.citation_violations(
            [recommended, alt], [self._WINNER_A, self._WINNER_B], [])
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["winner_angle"], "實證成分")
        message = plan_citation.citation_error_message(violations)
        self.assertIn("實證成分", message)
        self.assertIn("ROAS 4.30", message)
        self.assertNotIn("成分對比", message)  # 已經交代好的那個不該被點名

    def test_recommended_names_both_winners_but_no_roas_number_names_both_as_missing_number(self):
        """done-check 2：兩個贏家的名字都寫了，但完全沒有數字——兩個都要被點名缺數字，
        不是缺點名。"""
        recommended = _option(True, angles=[{"title": "延續切角",
                                              "message": "延續「成分對比」與「實證成分」方向"}])
        violations = plan_citation.citation_violations(
            [recommended], [self._WINNER_A, self._WINNER_B], [])
        self.assertEqual(len(violations), 2)
        self.assertEqual({v["winner_angle"] for v in violations}, {"成分對比", "實證成分"})
        self.assertTrue(all(not v["angle_missing"] for v in violations))
        message = plan_citation.citation_error_message(violations)
        self.assertIn("成分對比", message)
        self.assertIn("實證成分", message)
        self.assertIn("但沒寫出它的成績", message)

    def test_both_winners_named_with_numbers_in_recommended_passes_even_if_alt_says_nothing(self):
        """done-check 3 正面：推薦方案兩個贏家都交代好（含數字），備案方案完全沒提——
        照樣通過，備案不影響判定。"""
        recommended = _option(True, angles=[{
            "title": "延續切角",
            "message": "延續「成分對比」（ROAS 4.30）與「實證成分」（ROAS 4.30）方向"}])
        alt = _option(False, angles=[{"title": "備案", "message": "另一種說法"}])
        violations = plan_citation.citation_violations(
            [recommended, alt], [self._WINNER_A, self._WINNER_B], [])
        self.assertEqual(violations, [])

    def test_winners_cited_only_in_an_alternative_option_is_still_a_violation(self):
        """done-check 3 鏡像（原始 bug 本身）：客戶讀到的是推薦方案，贏家只出現在備案裡
        不算數——這正是舊碼 `any()` 誤判放行的情境。"""
        recommended = _option(True, angles=[{"title": "延續切角", "message": "全新方向"}])
        alt = _option(False, angles=[{
            "title": "備案", "message": "「成分對比」（ROAS 4.30）「實證成分」（ROAS 4.30）"}])
        violations = plan_citation.citation_violations(
            [recommended, alt], [self._WINNER_A, self._WINNER_B], [])
        self.assertEqual(len(violations), 2)

    def test_no_prior_winners_means_no_winner_violation_regardless_of_option_text(self):
        """done-check 4：既有行為（沒有贏家就無從比對），可能一開始就是綠的——如實說明，
        不是新行為。"""
        recommended = _option(True, angles=[{"title": "隨便", "message": "隨便寫，不提任何贏家"}])
        self.assertEqual(plan_citation.citation_violations([recommended], [], []), [])

    def test_roas_number_formats_stripped_and_full_both_accepted_wrong_number_is_not(self):
        """done-check 5：`4.3`／`4.30` 對 4.30 的贏家都算數；`4.31` 不算——尤其要擋住
        「4.31 開頭三碼長得像 4.3」這種子字串矇混。"""
        base_message = "延續「成分對比」方向"

        stripped = _option(True, angles=[{"title": "延續切角",
                                          "message": base_message + "，ROAS 4.3"}])
        self.assertEqual(
            plan_citation.citation_violations([stripped], [self._WINNER_A], []), [])

        full = _option(True, angles=[{"title": "延續切角",
                                      "message": base_message + "，ROAS 4.30"}])
        self.assertEqual(
            plan_citation.citation_violations([full], [self._WINNER_A], []), [])

        wrong = _option(True, angles=[{"title": "延續切角",
                                       "message": base_message + "，ROAS 4.31"}])
        violations = plan_citation.citation_violations([wrong], [self._WINNER_A], [])
        self.assertEqual(len(violations), 1)
        self.assertFalse(violations[0]["angle_missing"])  # 角度有交代，缺的是正確數字

    def test_real_b4_recommended_option_only_flags_the_winner_truly_absent(self):
        """票 F15 done-check 1：B4 真機跑出來的推薦方案原文（`llm_task`
        `llm_01M0W5RVQ8BV8FHG4A00SXWZ5E`）——「實證成分」只出現在 summary／difference，
        ROAS 藏在 angle 0 的引用句裡；「成分對比」整個方案（含全部切角）都沒提到。
        RED first：今天的舊碼只掃切角文字（`rec_angle_texts`），「實證成分」不在任何一個
        切角的 title/message 裡，會被誤判成「沒有交代」——兩個贏家都跳違規（假陽性），
        今天這裡會回傳 2 個 violation，不是 1 個。"""
        winner_evidenced = {"angle": "實證成分", "roas": 4.3, "spend": 12000, "conversions": 22,
                            "source_cycle_id": "cyc_prior"}
        winner_missing = {"angle": "成分對比", "roas": 4.3, "spend": 9000, "conversions": 18,
                          "source_cycle_id": "cyc_prior"}
        recommended = _option(
            True,
            summary="以『實證成分』與『身分關鍵字』雙軸擴量，驗證靜態圖素材在前 7 天的派發優勢…",
            difference="強化前一期驗證過的『實證成分』方向…放大期集中投『實證成分』贏家，"
                       "測試期用異議破解與身分鏡像測新假設。",
            angles=[
                {"title": "下午卡關上班族的實證時刻",
                 "message": "…用『實證咖啡因』（引用上期 ROAS 4.3 驗證成績）快速恢復專注…"},
                {"title": "健身訓練後的補給儀式", "message": "訓練後快速補給，不提歷史成績。"},
                {"title": "長夜備考的清醒夥伴", "message": "熬夜備考也要清醒，不提歷史成績。"},
                {"title": "長途駕駛的安全提神", "message": "長途駕駛保持專注，不提歷史成績。"},
            ],
        )
        violations = plan_citation.citation_violations(
            [recommended], [winner_evidenced, winner_missing], [])
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["winner_angle"], "成分對比")
        self.assertTrue(violations[0]["angle_missing"])
        message = plan_citation.citation_error_message(violations)
        self.assertIn("方案沒有交代上期贏家「成分對比」", message)
        self.assertNotIn("實證成分", message)

    def test_winner_absent_from_entire_recommended_option_is_still_a_violation(self):
        """票 F15 done-check 2（迴歸守門）：贏家不在推薦方案的 summary、difference，也不在
        任何切角——F15 沒有動這一半，維持原本「沒有交代」的判定。"""
        recommended = _option(True, summary="完全沒提到任何贏家。", difference="也沒有提到。",
                              angles=[{"title": "全新切角", "message": "全新方向，沒有引用歷史。"}])
        violations = plan_citation.citation_violations([recommended], [self._WINNER_A], [])
        self.assertEqual(len(violations), 1)
        self.assertTrue(violations[0]["angle_missing"])
        message = plan_citation.citation_error_message(violations)
        self.assertIn("方案沒有交代上期贏家「成分對比」", message)

    def test_winner_named_only_in_alternative_option_summary_is_still_a_violation(self):
        """票 F15 done-check 3（迴歸守門）：F12 的鏡像檢查不能因為 F15 把「推薦方案全文」
        的範圍擴大就跟著鬆綁——贏家只出現在備案方案的 summary，不是推薦方案，一樣算
        沒交代。"""
        recommended = _option(True, angles=[{"title": "延續切角", "message": "全新方向"}])
        alt = _option(False, summary="這裡有提到「成分對比」（ROAS 4.30）。",
                     angles=[{"title": "備案", "message": "另一種說法"}])
        violations = plan_citation.citation_violations([recommended, alt], [self._WINNER_A], [])
        self.assertEqual(len(violations), 1)
        self.assertTrue(violations[0]["angle_missing"])

    def test_winner_named_in_summary_but_roas_nowhere_is_missing_number_not_missing_name(self):
        """票 F15 done-check 4：贏家名字只出現在推薦方案的 summary（不是切角），但整個方案
        沒有任何地方寫出 ROAS 數字。RED first：今天的舊碼只掃切角文字判斷點名與否，
        summary 裡的名字看不到，今天這裡 `angle_missing` 會是 True（「沒有交代」），
        訊息會是「沒有交代」而不是「提到…但沒寫出成績」。"""
        recommended = _option(True, summary="延續「成分對比」方向，主力放大。",
                              angles=[{"title": "延續切角", "message": "沒有寫任何數字"}])
        violations = plan_citation.citation_violations([recommended], [self._WINNER_A], [])
        self.assertEqual(len(violations), 1)
        self.assertFalse(violations[0]["angle_missing"])
        message = plan_citation.citation_error_message(violations)
        self.assertIn("方案提到上期贏家「成分對比」但沒寫出它的成績", message)


if __name__ == "__main__":
    unittest.main()
