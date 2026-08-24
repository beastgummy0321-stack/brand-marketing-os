# -*- coding: utf-8 -*-
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
from app.ads import carry_forward  # noqa: E402
from app.ads import opening_suggestion  # noqa: E402
from app.ads import plan as ads_plan  # noqa: E402
from app.ads import reading as ads_reading  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core.db import new_id, now_iso  # noqa: E402
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
        "INSERT INTO experiment_cell (id, campaign_cycle_id, brand_id, creative_angle,"
        " product_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (cell_id, cycle_id, brand_id, creative_angle, product_id, ts))
    conn.execute(
        "INSERT INTO publishing_package (id, brand_id, campaign_cycle_id, experiment_cell_id,"
        " campaign_name, adset_name, ad_name, destination_url, utm_json, status, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', 'ready', ?)",
        (pkg_id, brand_id, cycle_id, cell_id, "測試活動", "測試組合", f"{creative_angle}_ad",
         "https://example.test", ts))
    conn.execute(
        "INSERT INTO external_ad_mapping (id, brand_id, publishing_package_id,"
        " campaign_cycle_id, platform, claim_status, confirmed_by, confirmed_at, created_at)"
        " VALUES (?, ?, ?, ?, 'meta', 'confirmed', ?, ?, ?)",
        (mapping_id, brand_id, pkg_id, cycle_id, ACTOR, ts, ts))
    conn.execute(
        "INSERT INTO performance_snapshot (id, brand_id, campaign_cycle_id, product_id,"
        " external_ad_mapping_id, platform, date_range_start, date_range_end, as_of_date,"
        " snapshot_taken_at, currency, spend, conversions, revenue, source, created_at)"
        " VALUES (?, ?, ?, ?, ?, 'meta', '2026-01-01', '2026-01-07', '2026-01-07', ?, 'TWD',"
        " ?, ?, ?, 'manual', ?)",
        (new_id("psn"), brand_id, cycle_id, product_id, mapping_id, ts, spend, conversions,
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

        ok, err = self._generate(self.carry_forward_cycle_id)
        self.assertTrue(ok, err)
        sent = ads_plan.PROVIDER.calls[0]["messages"][0]["content"]
        self.assertIn("實證成分", sent)
        self.assertIn("ROAS 4.31", sent)
        self.assertIn("節慶檔期用禮盒／組合切角能拉高客單價，投報率會比平常好", sent)
        self.assertIn("上期此方向賠錢，已避開", sent)

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
            "INSERT INTO campaign_cycle_hypothesis (campaign_cycle_id, strategy_hypothesis_id,"
            " brand_id, role) VALUES (?, ?, ?, 'message')",
            (self.prior_cycle_id, hyp["id"], self.bid))
        main.conn.commit()

        updated = ads_reading.resolve_hypotheses(
            main.conn, self.bid, self.prior_cycle_id, {hyp["id"]: "supported"}, actor=ACTOR)
        self.assertEqual(updated, 1)
        resolved = bi_repo.get_strategy_hypothesis(main.conn, self.bid, hyp["id"])
        self.assertEqual(resolved["status"], "inconclusive")  # guard 擋下，不是「成立」
        self.assertEqual(ads_repo.list_learning_ledger(main.conn, self.bid), [])  # 沒入帳

        ok, err = self._generate(self.carry_forward_cycle_id)
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
        ok, err = self._generate(self.carry_forward_cycle_id)
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


if __name__ == "__main__":
    unittest.main()
