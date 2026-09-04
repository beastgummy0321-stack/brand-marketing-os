"""app/tests/test_schedule.py — 票 07：檔期規劃最薄路徑；票 08：表單擴成 N 個方案；
票 09：選定一個方案展開成三層活動樹。

只寫這些事（全域 CLAUDE.md 測試四類；票 07／08／09 settled 段都明講畫面行為不寫
單元測試）：金額算法（最大餘數法）、比例不合法／方案（樹）格式不合法的拒絕、租戶隔離、
API 契約（含 ADR 0029「原樣貼進 prompt」的可驗證證據、票 08 的平台／目標／方案數驗證、
票 09 的方案編號驗證）、「查詢不是排程的先決條件」這條資料正確性規則、票 09 的活動樹元件
不得寫死通路詞彙這道機器閘門。全程只用 FakeProvider，不發任何真實網路請求；網路搜尋工具
本身怎麼解析 SDK 回應（成功／出錯兩種形狀）不在這裡測，那是 `AnthropicProvider.complete()`
的責任，見 test_llm_web_search.py。

票 05-1：三支 POST（.../plans、.../tree、.../creative）不再在 request 裡打代理，改
`background.enqueue()` 排進佇列——POST 回來的當下代理還沒被打過，`plan`／`tree`／`creative`
可能還是上一次的內容或 null。凡是要看「代理真的跑完之後」那個結果的測試，都得先
`self._run_worker()`（POST → commit → `background.app().run_worker(wait=False)` → 再
GET），跟 `app/tests/test_meta_daily_spend.py:351-363` 已經在用的 QueueWiringTest 同一個
寫法；只驗證同步驗證行為（400、404）的測試不受影響，那些仍在 enqueue 之前擋下。
"""

import json
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

import app.background as background_module
import app.main as main
import app.schedule as schedule_module
import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.core import rule_cards
from app.identity import repository as identity_repo
from app.llm import providers
from app.meta import graph as meta_graph
from app.meta import repository as meta_repo
from app.schedule import creative as creative_mod
from app.schedule import jobs as schedule_jobs
from app.schedule import period as period_mod
from app.schedule import plan as plan_mod
from app.schedule import state as schedule_state
from app.schedule import tree as tree_mod

from .identity_test_helpers import mint_hs256

ACTOR = "測試員"

# 有效的平台／目標——照 app/schedule/channel_catalogue.json 的內容取，測試不重寫一份
# 平行的資料（改資料檔不用跟著改這裡）。
_DATA = schedule_state._load_platform_data()
VALID_PLATFORM = next(p["id"] for p in _DATA["platforms"] if p["enabled"])
VALID_OBJECTIVE = next(o["value"] for o in _DATA["objectives"] if o["platform"] == VALID_PLATFORM)
DISABLED_PLATFORM = next(p["id"] for p in _DATA["platforms"] if not p["enabled"])


def _fenced(splits: list) -> str:
    body = json.dumps({"splits": splits}, ensure_ascii=False)
    return f"這是一段給老闆看的說明文字。\n\n```json\n{body}\n```"


def _fenced_plans(plans: list) -> str:
    body = json.dumps({"plans": plans}, ensure_ascii=False)
    return f"這是一段給老闆看的說明文字。\n\n```json\n{body}\n```"


def _one_plan(**overrides) -> dict:
    plan = {
        "summary": "主打驗證過的受眾，小額測試新概念。",
        "reasoning": "過去表現穩定，先守住再小額試新的。",
        "splits": [
            {"label": "主力方向", "share": 0.7, "why": "已驗證的受眾，先守住"},
            {"label": "測試方向", "share": 0.3, "why": "新概念，小額試"},
        ],
    }
    plan.update(overrides)
    return plan


def _tree_fenced(nodes: list, levels: list | None = None, budget_level: int = 2) -> str:
    payload = {
        "levels": levels or ["行銷活動", "廣告組合", "廣告"],
        "budget_level": budget_level,
        "nodes": nodes,
    }
    body = json.dumps(payload, ensure_ascii=False)
    return f"這是一段給老闆看的說明文字。\n\n```json\n{body}\n```"


def _one_tree_nodes(
    shares: tuple = (0.7, 0.3), name: str = "活動一",
    child_names: tuple = ("組合1", "組合2"),
) -> list:
    """三層節點，扛預算的是第二層（比照 Meta：行銷活動／廣告組合／廣告，預算在第 2 層）。
    `name`：票 T3b 的重綁測試需要重新展開之後第一層節點換一個名字。`child_names`：票
    T3c 的第二層測試需要換第二層節點的名字（改名顯示未綁定、兩個同名手足）——預設值跟
    原本的 f"組合{i+1}" 一樣，既有呼叫端不用改。"""
    return [
        {
            "name": name,
            "fields": [{"label": "目標", "value": "業績"}],
            "share": None,
            "warnings": [],
            "children": [
                {
                    "name": child_names[i],
                    "fields": [{"label": "受眾", "value": "既有客"}],
                    "share": share,
                    "warnings": [] if i == 0 else ["只投一個版位，沒有勾其他版位"],
                    "children": [
                        {
                            "name": f"單元{i + 1}",
                            "fields": [{"label": "素材", "value": "影片"}],
                            "share": None,
                            "warnings": [],
                            "children": [],
                        }
                    ],
                }
                for i, share in enumerate(shares)
            ],
        }
    ]


def _two_top_nodes(name_a: str, name_b: str, shares: tuple = (0.5, 0.5)) -> list:
    """兩個第一層節點（可以同名也可以不同名）——票 T3b：證明綁定鍵是 node_key，不是
    節點名稱（舊版拿名稱當 dict key，兩個同名節點會撞成一格）。"""
    def branch(name: str, share: float) -> dict:
        return {
            "name": name, "fields": [{"label": "目標", "value": "業績"}],
            "share": None, "warnings": [],
            "children": [{"name": "組合", "fields": [], "share": share, "warnings": [],
                          "children": [{"name": "單元", "fields": [], "share": None,
                                        "warnings": [], "children": []}]}],
        }
    return [branch(name_a, shares[0]), branch(name_b, shares[1])]


def _creative_fenced(creatives: list) -> str:
    body = json.dumps({"creatives": creatives}, ensure_ascii=False)
    return f"這是一段給老闆看的說明文字。\n\n```json\n{body}\n```"


def _nodes(*names: str) -> list[dict]:
    """票 T3d：`build_creative()` 的 `ad_nodes` 參數——`BuildCreativeTest` 只測名稱比對，
    不看 `node_key` 內容，序號頂著即可。"""
    return [{"node_key": str(i + 1), "name": name} for i, name in enumerate(names)]


def _one_creative(node: str, **overrides) -> dict:
    creative = {
        "node": node,
        # 票 T1 站③收尾：預設帶上座標，讓 CreativeApiContractTest 對座標不是零斷言——
        # 之前這裡沒有這個鍵，API 契約測試全走「沒有這個鍵 → 補七個 null」那條路。
        "coordinates": {
            "angle": "測試角度", "audience": None, "pain": None, "hook": None,
            "proof": None, "offer": None, "format": None,
        },
        "fields": [
            {"label": "主要文字", "value": "測試內容"},
            {"label": "圖片提示詞", "value": "測試提示詞"},
        ],
        "warnings": [],
    }
    creative.update(overrides)
    return creative


def _fake(rendered_output: str, search_sources: list | None = None) -> providers.FakeProvider:
    return providers.FakeProvider(response=providers.ProviderResponse(
        output_text=rendered_output, structured=None,
        usage=providers.Usage(input_tokens=500, output_tokens=200), stop_reason="end_turn",
        search_sources=search_sources,
    ))


def _post_body(**overrides) -> dict:
    body = {
        "product_ids": [],  # 呼叫端自己補
        "platform": VALID_PLATFORM,
        "objective": VALID_OBJECTIVE,
        "promotion_note": "",
        "plan_count": 2,
        # 票 T2b（ADR 0053）：開始日／結束日現在是必填——這裡的兩個既有測試檔不測檔期
        # 本身，隨便給一段合法區間讓既有流程走得下去；真的要測檔期日期驗證的測試自己
        # 用 overrides 蓋掉。
        "start_date": "2026-09-10",
        "end_date": "2026-09-24",
    }
    body.update(overrides)
    return body


# -- 1. 最大餘數法：整數金額，加總精確等於預算 ----------------------------------------

class LargestRemainderAllocationTest(unittest.TestCase):
    def test_amounts_are_integers_and_sum_exactly_to_budget(self):
        amounts = plan_mod.largest_remainder_allocation(3000, [0.7, 0.3])
        self.assertTrue(all(isinstance(a, int) for a in amounts))
        self.assertEqual(sum(amounts), 3000)

    def test_three_way_split_still_sums_exactly(self):
        amounts = plan_mod.largest_remainder_allocation(1000, [1 / 3, 1 / 3, 1 / 3])
        self.assertTrue(all(isinstance(a, int) for a in amounts))
        self.assertEqual(sum(amounts), 1000)


# -- 1b. 票 T3e（ADR 0055 §11）：node_level_spend——純函數，桌面案例，不碰資料庫 ---------

def _period(period_id: str, start: date, end: date) -> dict:
    return {"id": period_id, "start_date": start, "end_date": end}


def _membership(entity_id: str, period_id: str, start: date, end: date | None,
                 weight: float = 1.0) -> dict:
    return {"entity_id": entity_id, "campaign_period_id": period_id,
            "from_date": start, "to_date": end, "allocation_weight": weight}


def _spend_row(day: date, entity_id: str, spend: float) -> dict:
    return {"spend_date": day, "entity_id": entity_id, "spend": spend}


class NodeLevelSpendTest(unittest.TestCase):
    """ticket done-check 2：每一支對應 ticket 明講的一條規則，一條一支，不多不少。"""

    D = date(2026, 9, 10)

    def test_invariant_every_periods_take_sums_to_the_days_total(self):
        a = _period("cpd_a", date(2026, 9, 8), date(2026, 9, 12))   # 4 天
        b = _period("cpd_b", date(2026, 9, 1), date(2026, 9, 20))   # 19 天，較長
        competitors = [a, b]
        memberships = [
            _membership("ent-1", "cpd_a", a["start_date"], a["end_date"]),  # 只登記給 a
            _membership("ent-2", "cpd_b", b["start_date"], b["end_date"]),  # 只登記給 b
        ]
        daily_rows = [
            _spend_row(self.D, "ent-1", 100.0),
            _spend_row(self.D, "ent-2", 50.0),
            _spend_row(self.D, "ent-3", 30.0),  # 沒登記
        ]
        spend_a = period_mod.node_level_spend(a, competitors, memberships, daily_rows)
        spend_b = period_mod.node_level_spend(b, competitors, memberships, daily_rows)
        self.assertAlmostEqual(spend_a + spend_b, 180.0, places=2)

    def test_registered_entity_goes_to_its_registered_period_not_the_day_owner(self):
        """`ent-1` 只登記給 `p2`（3 天）；`p1`（1 天，較短）雖然是這天的品牌層擁有者，
        但它沒有 `ent-1` 的 membership——「among those memberships' periods」只看
        `ent-1` 自己登記過的那些期，不是全部競爭者。"""
        p1 = _period("cpd_p1", date(2026, 9, 9), date(2026, 9, 10))   # 1 天
        p2 = _period("cpd_p2", date(2026, 9, 8), date(2026, 9, 11))   # 3 天
        competitors = [p1, p2]
        memberships = [_membership("ent-1", "cpd_p2", p2["start_date"], p2["end_date"])]
        daily_rows = [_spend_row(self.D, "ent-1", 200.0)]
        self.assertEqual(
            period_mod.node_level_spend(p2, competitors, memberships, daily_rows), 200.0,
        )
        self.assertEqual(
            period_mod.node_level_spend(p1, competitors, memberships, daily_rows), 0.0,
        )

    def test_one_entity_registered_to_two_periods_goes_to_the_shorter_one(self):
        """ADR 0053 §4 的規則本體，套在節點上：同一個廣告組合同時登記在兩個**不等長**的
        檔期底下時，短的整天全拿、長的拿 0。

        T3e 審查發現的覆蓋缺口補的就是這一支——把 `period.py` 的 `shortest = min(...)`
        改成 `max(...)`（讓長的贏），原本九支測試**全部照樣綠燈**：沒有任何一支餵過
        「同一實體、兩個不等長的已登記期互相競爭」這個輸入。既有的
        `test_registered_entity_goes_to_its_registered_period_not_the_day_owner` 比的是
        「已登記的期」對「這天的品牌層擁有者」，不是兩個已登記期彼此比。守的是金額。"""
        short = _period("cpd_short", date(2026, 9, 8), date(2026, 9, 12))   # 4 天
        long_ = _period("cpd_long", date(2026, 9, 1), date(2026, 9, 20))    # 19 天
        competitors = [short, long_]
        memberships = [
            _membership("ent-1", "cpd_short", short["start_date"], short["end_date"]),
            _membership("ent-1", "cpd_long", long_["start_date"], long_["end_date"]),
        ]
        daily_rows = [_spend_row(self.D, "ent-1", 120.0)]
        self.assertEqual(
            period_mod.node_level_spend(short, competitors, memberships, daily_rows), 120.0,
        )
        self.assertEqual(
            period_mod.node_level_spend(long_, competitors, memberships, daily_rows), 0.0,
        )

    def test_unregistered_entity_goes_to_the_days_brand_level_owner(self):
        short = _period("cpd_short", date(2026, 9, 9), date(2026, 9, 10))  # 1 天
        long_ = _period("cpd_long", date(2026, 9, 1), date(2026, 9, 20))
        competitors = [short, long_]
        daily_rows = [_spend_row(self.D, "ent-x", 77.0)]
        self.assertEqual(
            period_mod.node_level_spend(short, competitors, [], daily_rows), 77.0,
        )
        self.assertEqual(
            period_mod.node_level_spend(long_, competitors, [], daily_rows), 0.0,
        )

    def test_equal_length_periods_split_a_registered_entity_by_allocation_weight(self):
        p1 = _period("cpd_p1", date(2026, 9, 8), date(2026, 9, 12))  # 4 天
        p2 = _period("cpd_p2", date(2026, 9, 6), date(2026, 9, 10))  # 4 天，一樣長
        competitors = [p1, p2]
        daily_rows = [_spend_row(self.D, "ent-1", 100.0)]

        even = [
            _membership("ent-1", "cpd_p1", p1["start_date"], p1["end_date"], weight=1.0),
            _membership("ent-1", "cpd_p2", p2["start_date"], p2["end_date"], weight=1.0),
        ]
        self.assertEqual(
            (period_mod.node_level_spend(p1, competitors, even, daily_rows),
             period_mod.node_level_spend(p2, competitors, even, daily_rows)),
            (50.0, 50.0),
        )

        two_to_one = [
            _membership("ent-1", "cpd_p1", p1["start_date"], p1["end_date"], weight=2.0),
            _membership("ent-1", "cpd_p2", p2["start_date"], p2["end_date"], weight=1.0),
        ]
        s1 = period_mod.node_level_spend(p1, competitors, two_to_one, daily_rows)
        s2 = period_mod.node_level_spend(p2, competitors, two_to_one, daily_rows)
        self.assertAlmostEqual(s1, 66.67, places=2)
        self.assertAlmostEqual(s2, 33.33, places=2)
        self.assertEqual(round(s1 + s2, 2), 100.0)

    def test_membership_reaching_past_its_periods_end_date_contributes_nothing_outside_it(self):
        """ticket 矛盾檢查段：membership 自己宣稱蓋到 9/10，但它掛的檔期 `stale` 自己的
        `end_date` 只到 9/5——兩邊都要夾，夾不住這筆錢在這天當沒登記，落給這天真正的品牌層
        擁有者 `owner`。"""
        stale = _period("cpd_stale", date(2026, 9, 1), date(2026, 9, 5))
        owner = _period("cpd_owner", date(2026, 9, 1), date(2026, 9, 20))
        competitors = [stale, owner]
        memberships = [_membership("ent-1", "cpd_stale", date(2026, 9, 1), date(2026, 9, 10))]
        daily_rows = [_spend_row(self.D, "ent-1", 40.0)]
        self.assertEqual(
            period_mod.node_level_spend(owner, competitors, memberships, daily_rows), 40.0,
        )
        self.assertEqual(
            period_mod.node_level_spend(stale, competitors, memberships, daily_rows), 0.0,
        )

    def test_day_covered_by_no_period_is_taken_by_nobody(self):
        lonely = _period("cpd_lonely", date(2026, 9, 8), date(2026, 9, 12))
        daily_rows = [_spend_row(self.D, "ent-1", 15.0)]
        self.assertEqual(period_mod.node_level_spend(lonely, [], [], daily_rows), 0.0)


# -- 2b. 票 08：N 個方案，任何一個壞掉整批失敗 -----------------------------------------

class BuildPlansTest(unittest.TestCase):
    def test_n_plans_all_succeed(self):
        plans, failure = plan_mod.build_plans(
            _fenced_plans([_one_plan(), _one_plan(summary="第二個方案")]), daily_budget=1000,
        )
        self.assertIsNone(failure)
        self.assertEqual(len(plans), 2)
        self.assertEqual(sum(s["daily_amount"] for s in plans[0]["splits"]), 1000)
        self.assertEqual(plans[1]["summary"], "第二個方案")

    def test_one_bad_plan_fails_the_whole_batch(self):
        good = _one_plan()
        bad = _one_plan(splits=[{"label": "x", "share": 0.5, "why": "y"}])  # 只有 0.5，加總不是 1
        plans, failure = plan_mod.build_plans(_fenced_plans([good, bad]), daily_budget=1000)
        self.assertEqual(plans, [])
        self.assertTrue(failure)

    def test_missing_plans_key_is_a_failure(self):
        plans, failure = plan_mod.build_plans(_fenced([{"label": "x", "share": 1.0, "why": "y"}]),
                                              daily_budget=1000)
        self.assertEqual(plans, [])
        self.assertTrue(failure)


# -- 2c. 票 09：選定方案展開成活動樹，錢照文件順序算、比例不合法整棵樹失敗 --------------

class BuildTreeTest(unittest.TestCase):
    def test_success_shape_and_daily_amounts_sum_to_budget(self):
        body, failure = tree_mod.build_tree(_tree_fenced(_one_tree_nodes()), daily_budget=1000)
        self.assertIsNone(failure)
        self.assertEqual(body["levels"], ["行銷活動", "廣告組合", "廣告"])
        self.assertEqual(body["budget_level"], 2)
        top = body["nodes"][0]
        self.assertIsNone(top["share"])  # 第一層不扛預算
        share_nodes = top["children"]
        self.assertEqual(sum(n["daily_amount"] for n in share_nodes), 1000)
        self.assertEqual(share_nodes[1]["warnings"], ["只投一個版位，沒有勾其他版位"])
        self.assertEqual(share_nodes[0]["children"][0]["daily_amount"], None)  # 第三層不扛預算

    def test_shares_not_summing_to_one_is_bad_shares_failure(self):
        body, failure = tree_mod.build_tree(
            _tree_fenced(_one_tree_nodes(shares=(0.5, 0.2))), daily_budget=1000
        )
        self.assertEqual(body, {})
        # tree.py 有自己的訊息（票 10-feedback-entries 帶著票 09 review 的小修正）：
        # 失敗時使用者該重新展開，不是重新排程一整批方案，不沿用 plan.py 的那句。
        self.assertEqual(failure, tree_mod.BAD_SHARES_MESSAGE)
        self.assertNotEqual(tree_mod.BAD_SHARES_MESSAGE, plan_mod.BAD_SHARES_MESSAGE)

    def test_missing_json_block_is_a_failure(self):
        body, failure = tree_mod.build_tree("這裡面沒有任何 fenced json 區塊。", daily_budget=1000)
        self.assertEqual(body, {})
        self.assertTrue(failure)

    def test_fourth_level_is_a_failure(self):
        # 第三層節點不該再有子節點——樹一定剛好三層深。
        nodes = _one_tree_nodes()
        nodes[0]["children"][0]["children"][0]["children"] = [
            {"name": "第四層", "fields": [], "share": None, "warnings": [], "children": []}
        ]
        body, failure = tree_mod.build_tree(_tree_fenced(nodes), daily_budget=1000)
        self.assertEqual(body, {})
        self.assertTrue(failure)

    def test_share_on_non_budget_level_is_a_failure(self):
        nodes = _one_tree_nodes()
        nodes[0]["share"] = 0.5  # budget_level=2，第一層不該有 share
        body, failure = tree_mod.build_tree(_tree_fenced(nodes), daily_budget=1000)
        self.assertEqual(body, {})
        self.assertTrue(failure)


# -- 2c. 票 T1（docs/issues/T1-creative-fingerprint/ticket.md）：build_creative() 純函數 ---

class BuildCreativeTest(unittest.TestCase):
    """decision 3 收窄（多認得一個手足鍵 `coordinates`）、decision 4 不動（node 逐一對上
    樹）、`fields.value` 收 `string | string[]`——直接測 `creative.build_creative()`，
    不必經過 API／worker。"""

    def test_coordinates_survive_the_shell(self):
        """票 T1 唯一要問的問題：代理回覆裡的 `coordinates.angle` 撐得過外殼，原封不動地
        出現在回傳值裡。"""
        creative = _one_creative("單元1", coordinates={
            "angle": "疑慮 Q&A 連發", "audience": None, "pain": None, "hook": None,
            "proof": None, "offer": None, "format": None,
        })
        ads, failure = creative_mod.build_creative(_creative_fenced([creative]), _nodes("單元1"))
        self.assertIsNone(failure)
        self.assertEqual(ads[0]["coordinates"]["angle"], "疑慮 Q&A 連發")

    def test_bad_coordinate_values_fall_back_to_null_and_copy_still_ships(self):
        """票 T1 站③收尾第 2 條：座標是診斷用中繼資料不是交付物。個別維度給 `""`／數字，
        或整個 `coordinates` 給錯形狀，都退回 null，文案照樣交付——不整批失敗（那次生成
        的錢已經花掉了，整批作廢等於白燒）。"""
        creative = _one_creative(
            "單元1", coordinates={"angle": "", "pain": 3, "hook": "真的鉤子"}
        )
        ads, failure = creative_mod.build_creative(_creative_fenced([creative]), _nodes("單元1"))
        self.assertIsNone(failure)
        self.assertIsNone(ads[0]["coordinates"]["angle"])
        self.assertIsNone(ads[0]["coordinates"]["pain"])
        self.assertEqual(ads[0]["coordinates"]["hook"], "真的鉤子")
        self.assertEqual(ads[0]["fields"][0]["value"], ["測試內容"])

        # 整個 coordinates 給錯形狀（list）也一樣：七維全 null，文案照交。
        creative = _one_creative("單元1", coordinates=["不是 dict"])
        ads, failure = creative_mod.build_creative(_creative_fenced([creative]), _nodes("單元1"))
        self.assertIsNone(failure)
        self.assertEqual(
            ads[0]["coordinates"], {key: None for key in creative_mod.COORDINATE_KEYS}
        )
        self.assertEqual(ads[0]["fields"][0]["value"], ["測試內容"])

    def test_decision_4_still_holds(self):
        # node 對不上樹裡任何一個最深層節點，整批失敗——加 coordinates 沒有放寬這一條。
        ads, failure = creative_mod.build_creative(
            _creative_fenced([_one_creative("不存在的節點")]), _nodes("單元1")
        )
        self.assertEqual(ads, [])
        self.assertEqual(failure, creative_mod.NODE_MISMATCH_MESSAGE)

    def test_field_value_accepts_list_and_string(self):
        creative = _one_creative("單元1", fields=[
            {"label": "主要文字", "value": "單一字串"},
            {"label": "標題", "value": ["變體一", "變體二"]},
        ])
        ads, failure = creative_mod.build_creative(_creative_fenced([creative]), _nodes("單元1"))
        self.assertIsNone(failure)
        self.assertEqual(ads[0]["fields"], [
            {"label": "主要文字", "value": ["單一字串"]},
            {"label": "標題", "value": ["變體一", "變體二"]},
        ])

    def test_unknown_coordinate_key_is_dropped(self):
        creative = _one_creative(
            "單元1", coordinates={"angle": "測試角度", "not_a_real_key": "不該出現"}
        )
        ads, failure = creative_mod.build_creative(_creative_fenced([creative]), _nodes("單元1"))
        self.assertIsNone(failure)
        self.assertNotIn("not_a_real_key", ads[0]["coordinates"])
        self.assertEqual(set(ads[0]["coordinates"]), set(creative_mod.COORDINATE_KEYS))

    def test_node_key_decides_which_same_name_node_gets_which_copy(self):
        """資料正確性，`docs/issues/ad-loop/issue-same-name-leaf-node-key.md`（2026-09-04
        根治）：兩個最深層節點同名時名稱帶不出任何資訊，`node_key` 是唯一分得出來的依據。
        代理倒著答（先 "2" 後 "1"）→ 照編號配（舊版照回覆順序排隊會拿到「第一段」，所以
        這支分得出兩種行為）；漏答、或答了樹上沒有的編號 → 退回既有的名稱排隊，不整批重產
        （那一次呼叫已經花過錢）。"""
        def first_node_copy(*keys: str | None) -> list:
            creatives = [
                _one_creative("單元", fields=[{"label": "主要文字", "value": marker}])
                | ({"node_key": key} if key else {})
                for marker, key in zip(("第一段", "第二段"), keys, strict=True)
            ]
            ads, failure = creative_mod.build_creative(
                _creative_fenced(creatives), _nodes("單元", "單元")
            )
            self.assertIsNone(failure)
            self.assertEqual([a["node_key"] for a in ads], ["1", "2"])
            return ads[0]["fields"][0]["value"]

        self.assertEqual(first_node_copy("2", "1"), ["第二段"])      # 照編號配
        self.assertEqual(first_node_copy(None, None), ["第一段"])    # 漏答 → 名稱排隊
        self.assertEqual(first_node_copy("9.9.9", "1"), ["第一段"])  # 答錯 → 名稱排隊


# -- 2d. 票 09 settled 段第 8 點：活動樹元件不得寫死通路詞彙 ---------------------------

class CampaignTreeVocabularyGateTest(unittest.TestCase):
    """加一個通路＝加一個部門任務檔（`app/departments/ads/campaign_tree.md`），不是改這支
    前端元件——這道閘門逐字掃過去確保沒人偷懶寫死。字面比對區分大小寫：元件本身叫
    `CampaignTree`（大寫 C），跟清單裡小寫的 `campaign` 不是同一個字串，不誤判。

    票 01：這個元件延伸到 CONTEXT.md「外殼認得的業務詞只有三個」那條界線——切角／主題／
    素材檔／創意簡報／一條學習全部下放給 `app/departments/creative/ad_creative.md`，一併
    加進這裡的清單（這支元件現在也渲染最深層節點的內容）。"""

    _BANNED_WORDS = [
        "Meta", "Facebook", "Instagram", "Google", "TikTok",
        "campaign", "adset", "ad set", "行銷活動", "廣告組合", "廣告",
        "切角", "主題", "素材檔", "創意簡報", "一條學習",
    ]

    def test_component_has_no_platform_or_creative_vocabulary(self):
        path = (
            Path(__file__).resolve().parents[2]
            / "frontend" / "src" / "components" / "schedule" / "CampaignTree.tsx"
        )
        text = path.read_text(encoding="utf-8")
        hits = [word for word in self._BANNED_WORDS if word in text]
        self.assertEqual(hits, [], f"CampaignTree.tsx 含通路或創意詞彙：{hits}")

    # 票 01 done-check 最後一條：「不要寫死」延伸到 Python 那一側。這裡只掃創意詞彙
    # （切角／主題／素材檔／創意簡報／一條學習），不套用平台詞彙清單——`routes.py` 的註解
    # 本來就會提到 Meta／Google／TikTok 這類平台名稱解釋歷史決定（例如 46 行「campaign_plan」
    # 改名的由來），那從來不是這道閘門要抓的東西；但這五個創意詞彙沒有任何理由出現在後端
    # 程式碼的任何角落，包含註解——它們的定義只准活在 `ad_creative.md` 這份任務檔裡。
    _CREATIVE_WORDS = ["切角", "主題", "素材檔", "創意簡報", "一條學習"]
    _BACKEND_SCANNED_PATHS = [
        ("app", "schedule", "routes.py"),
        ("app", "schedule", "creative.py"),
    ]

    def test_new_backend_files_have_no_creative_vocabulary(self):
        repo_root = Path(__file__).resolve().parents[2]
        problems = []
        for parts in self._BACKEND_SCANNED_PATHS:
            path = repo_root.joinpath(*parts)
            text = path.read_text(encoding="utf-8")
            hits = [word for word in self._CREATIVE_WORDS if word in text]
            if hits:
                problems.append(f"{'/'.join(parts)}：{hits}")
        self.assertEqual(problems, [], "後端程式碼含創意詞彙：\n" + "\n".join(problems))


# -- 3／4／5：API 契約、租戶隔離、prompt 原樣貼入（ADR 0029）、票 08 表單驗證 -----------

class _ScheduleApiTestBase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        # 票 05-1：這個測試模組自己有一份 schema（見 conftest.py），這個模組自己那份
        # `background.app()` 要重新掛一次三個生成 task——DSN 換了 App 整顆重建，跟
        # test_meta_daily_spend.py `daily_pull.register_task()` 同一個理由（見
        # app/schedule/__init__.py 的 register_tasks() 檔頭）。
        schedule_module.register_tasks()
        self.brand = bi_repo.create_brand(
            web.conn, org_id=coredb.DEV_ORG_ID, name="測試品牌：晨露茶飲",
            client_name=None, actor=ACTOR,
        )
        self.product = bi_repo.create_product(
            web.conn, self.brand["id"], name="測試產品：蜂蜜柚子茶", actor=ACTOR,
        )
        rule_cards.set_value(
            web.conn, self.brand["id"], "schedule_budget", "daily_budget", 3000.0,
            ACTOR, org_id=coredb.DEV_ORG_ID,
        )
        self._orig_provider = schedule_jobs.PROVIDER

    def tearDown(self):
        schedule_jobs.PROVIDER = self._orig_provider

    def _run_worker(self) -> None:
        """票 05-1：POST 現在只 enqueue，真正打代理在 worker 裡——`web.conn.commit()` 先把
        這個 request 留下的異動送出去，job 自己開一條新連線，看不到還沒 commit 的交易
        （test_meta_daily_spend.py:351-363 QueueWiringTest 已經在用同一個寫法）。"""
        web.conn.commit()
        background_module.app().run_worker(wait=False)

    def _make_org(self, suffix: str) -> tuple:
        org_id = f"org_schedule_test_{suffix}"
        web.conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
            " ON CONFLICT (id) DO NOTHING",
            (org_id, org_id),
        )
        import uuid

        user_id = uuid.uuid4()
        email = f"schedule-test-{suffix}-{user_id.hex[:8]}@example.com"
        identity_repo.create_user(web.conn, user_id, email)
        identity_repo.create_membership(web.conn, org_id, user_id, "owner")
        web.conn.commit()
        token = mint_hs256(sub=str(user_id), email=email)
        return org_id, token

    @staticmethod
    def _headers(token: str, org_id: str) -> dict:
        return {"Authorization": f"Bearer {token}", "X-Org-Id": org_id}

    def _post(self, **overrides):
        body = _post_body(product_ids=[self.product["id"]], **overrides)
        return self.client.post(f"/api/schedule/brands/{self.brand['id']}/plans", json=body)


class PlanApiContractTest(_ScheduleApiTestBase):
    def test_get_before_any_run_returns_null_plan_and_form_data(self):
        resp = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["daily_budget"], 3000.0)
        self.assertIsNone(body["plan"])
        self.assertIsNone(body["tree"])  # 票 09：還沒展開過，tree 是 null
        # 方案數上下限來自規則卡 schedule_plan_count，預設 1～5（票 08）。
        self.assertEqual(body["plan_count_min"], 1)
        self.assertEqual(body["plan_count_max"], 5)
        # 平台／目標來自資料檔，不是外殼寫死——Meta 開放，Google／TikTok 列出但停用。
        platform_ids = {p["id"]: p["enabled"] for p in body["platforms"]}
        self.assertEqual(platform_ids, {"meta": True, "google": False, "tiktok": False})
        self.assertTrue(all(o["source_url"] for o in body["objectives"]))

    def test_post_returns_n_plan_cards_and_prompt_carries_department_file(self):
        fake = _fake(_fenced_plans([_one_plan(), _one_plan(summary="第二個方案")]))
        schedule_jobs.PROVIDER = fake

        resp = self._post(plan_count=2)
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        body = self.client.get(f"/api/schedule/brands/{self.brand['id']}").json()
        plan = body["plan"]
        self.assertIsNone(plan["failure"])
        self.assertEqual(plan["product_ids"], [self.product["id"]])
        self.assertEqual(plan["platform"], VALID_PLATFORM)
        self.assertEqual(plan["objective"], VALID_OBJECTIVE)
        self.assertEqual(len(plan["plans"]), 2)  # 要求 2 個，回 2 張卡
        self.assertEqual(sum(s["daily_amount"] for s in plan["plans"][0]["splits"]), 3000)

        # ADR 0029：部門任務檔原樣貼進 prompt，不解讀——用檔案裡的識別行證明真的貼進去了。
        self.assertEqual(len(fake.calls), 1)
        prompt_text = fake.calls[0]["messages"][0]["content"]
        self.assertIn("SCHEDULE-PLAN-TASK-V1", prompt_text)

    def test_get_after_post_returns_identical_plans(self):
        schedule_jobs.PROVIDER = _fake(_fenced_plans([_one_plan()]))
        resp = self._post(plan_count=1)
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        get_resp_1 = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        get_resp_2 = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(get_resp_1.json()["plan"], get_resp_2.json()["plan"])

    def test_budget_not_set_refuses_before_calling_agent(self):
        rule_cards.set_value(
            web.conn, self.brand["id"], "schedule_budget", "daily_budget", 0.0,
            ACTOR, org_id=coredb.DEV_ORG_ID,
        )
        fake = _fake(_fenced_plans([_one_plan()]))
        schedule_jobs.PROVIDER = fake
        resp = self._post()
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["message"], plan_mod.BUDGET_NOT_SET_MESSAGE)
        self.assertEqual(fake.calls, [])  # 沒打到代理

    def test_disabled_platform_is_rejected_before_calling_agent(self):
        fake = _fake(_fenced_plans([_one_plan()]))
        schedule_jobs.PROVIDER = fake
        resp = self._post(platform=DISABLED_PLATFORM)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(fake.calls, [])

    def test_objective_not_belonging_to_platform_is_rejected(self):
        fake = _fake(_fenced_plans([_one_plan()]))
        schedule_jobs.PROVIDER = fake
        resp = self._post(objective="這不是有效的目標值")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(fake.calls, [])

    def test_plan_count_out_of_rule_card_range_is_rejected(self):
        fake = _fake(_fenced_plans([_one_plan()]))
        schedule_jobs.PROVIDER = fake
        resp = self._post(plan_count=6)  # 規則卡預設上限 5
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(fake.calls, [])

    def test_another_orgs_brand_is_404(self):
        _org_b, token_b = self._make_org("b")
        resp = self.client.get(
            f"/api/schedule/brands/{self.brand['id']}", headers=self._headers(token_b, _org_b)
        )
        self.assertEqual(resp.status_code, 404)

        post_resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/plans",
            json=_post_body(product_ids=[self.product["id"]]),
            headers=self._headers(token_b, _org_b),
        )
        self.assertEqual(post_resp.status_code, 404)

        tree_resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree",
            json={"plan_index": 0},
            headers=self._headers(token_b, _org_b),
        )
        self.assertEqual(tree_resp.status_code, 404)

        reject_resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/reject",
            json={"entries": [{"severity": "hard", "content": "紅線"}]},
            headers=self._headers(token_b, _org_b),
        )
        self.assertEqual(reject_resp.status_code, 404)

        creative_resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/creative",
            json={},
            headers=self._headers(token_b, _org_b),
        )
        self.assertEqual(creative_resp.status_code, 404)

        # 票 01（ADR 0040）：核准／撤回一樣經 require_brand。
        for path in ("tree/approve", "tree/approve/revoke"):
            resp = self.client.post(
                f"/api/schedule/brands/{self.brand['id']}/{path}",
                headers=self._headers(token_b, _org_b),
            )
            self.assertEqual(resp.status_code, 404)


class QueuedGenerationTest(_ScheduleApiTestBase):
    """票 05-1：三個生成端點不再在 request 裡打代理，改進 procrastinate 佇列——這裡守兩件事
    （ticket「How we know it's done」點名的兩條，只寫這兩條）：

    money：同一個品牌／task_type 已經有一列 `llm_task` 在跑的時候，第二次 POST 一律 409，
    且不會多排一個工作（多排＝多花一次代理的錢）。

    API contract：POST 回來的時候代理還沒被打過（`run_task()` 在 worker 裡才會呼叫），只有
    真的跑過一次 worker 之後代理才被打到。
    """

    def _insert_running_row(self, task_type: str, context_scope: dict | None = None) -> None:
        web.conn.execute(
            "INSERT INTO llm_task (id, org_id, brand_id, task_type, context_scope_json,"
            " input_context_ids_json, input_context_hash, knowledge_item_ids_json,"
            " brand_version, prompt_template_id, prompt_template_version, provider, model,"
            " status, attempt_no, started_at)"
            " VALUES (%s, %s, %s, %s, %s, '[]', '', '[]', 1, 'p', 'v1', 'seed', 'seed',"
            " 'running', 1, %s)",
            (coredb.new_id("llm"), coredb.DEV_ORG_ID, self.brand["id"], task_type,
             coredb.jsonb(context_scope or {}), coredb.now_iso()),
        )
        web.conn.commit()

    def test_second_post_while_one_is_running_is_refused_and_defers_no_second_job(self):
        self._insert_running_row(schedule_state.TASK_TYPE)
        fake = _fake(_fenced_plans([_one_plan()]))
        schedule_jobs.PROVIDER = fake

        resp = self._post(plan_count=1)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["error"]["code"], "already_running")

        self._run_worker()
        self.assertEqual(fake.calls, [], "409 沒有多排一個工作，代理一次都不該被打到")

    def test_post_returns_before_the_provider_is_called_worker_calls_it_once(self):
        fake = _fake(_fenced_plans([_one_plan()]))
        schedule_jobs.PROVIDER = fake

        resp = self._post(plan_count=1)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(fake.calls, [], "POST 回來的時候，代理還不該被打過")

        self._run_worker()
        self.assertEqual(len(fake.calls), 1, "worker 真的跑過一次，代理才被打")

    def test_creative_job_uses_the_tree_pinned_at_enqueue_not_a_later_running_row(self):
        """fix round 1（money）：`schedule_creative` 過去在 job 執行時用
        `_latest_task_row()` 重讀「這個品牌最新一次 schedule_tree」——frozen decision 3
        的「一次一個」是按 task type 算的，擋不住這段情境：使用者按了「產素材」（排進
        佇列，還沒跑）之後又按了一次「展開活動樹」，插進一列新的 running schedule_tree。
        job 真的跑的時候重讀「最新」會撿到那一列還在跑的——`tree_from_task_row()` 對
        running 列回空樹（`levels: []`／`nodes: []`），不拋例外，job 照著空樹組 prompt、
        照樣打代理，花錢的結果卻對不上任何廣告節點。修法：enqueue 當下把
        `tree_row["id"]` 釘進 job 參數，job 只認這個 id，不重讀「最新」。"""
        schedule_jobs.PROVIDER = _fake(_fenced_plans([_one_plan()]))
        resp = self._post(plan_count=1)
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        succeeded_plan_id = schedule_state._latest_task_row(
            web.conn, self.brand["id"], schedule_state.TASK_TYPE
        )["id"]

        schedule_jobs.PROVIDER = _fake(_tree_fenced(_one_tree_nodes()))
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        succeeded_tree_id = schedule_state._latest_task_row(
            web.conn, self.brand["id"], schedule_state.TREE_TASK_TYPE
        )["id"]

        fake = _fake(_creative_fenced([_one_creative("單元1"), _one_creative("單元2")]))
        schedule_jobs.PROVIDER = fake
        resp = self.client.post(f"/api/schedule/brands/{self.brand['id']}/creative", json={})
        self.assertEqual(resp.status_code, 200, resp.text)

        # 產素材已經排進佇列（釘住上面那棵成功的樹），使用者這時又按了一次展開活動樹，
        # 插進一列「更新」的 running schedule_tree——worker 還沒跑到 creative job。這一列
        # 帶著真的 source_plan_task_id（跟真正的 schedule_tree job 會寫的一樣），才會真的
        # 讓舊版重讀「最新」的 bug 打到代理、燒錢產出空樹的內容，不是隨便崩潰在別的地方。
        self._insert_running_row(
            schedule_state.TREE_TASK_TYPE,
            context_scope={
                "brand_id": self.brand["id"], "plan_index": 0, "daily_budget": 3000.0,
                "source_plan_task_id": succeeded_plan_id,
            },
        )

        self._run_worker()

        creative_row = schedule_state._latest_task_row(
            web.conn, self.brand["id"], schedule_state.CREATIVE_TASK_TYPE
        )
        self.assertEqual(
            creative_row["context_scope_json"]["source_tree_task_id"], succeeded_tree_id,
            "creative job 必須用 enqueue 當下釘住的那棵樹，不是後來插隊、還在跑的那一列",
        )
        self.assertEqual(len(fake.calls), 1)
        prompt_text = fake.calls[0]["messages"][0]["content"]
        self.assertIn("單元1", prompt_text)
        self.assertIn("單元2", prompt_text)


class RejectApiContractTest(_ScheduleApiTestBase):
    """票 10-feedback-entries（ADR 0037）：POST .../reject——每條意見變一列 rule，
    再用凍結參數重新排程。"""

    def _succeed_plan(self, plan_count: int = 2, promotion_note: str = "這期主打新品") -> None:
        schedule_jobs.PROVIDER = _fake(
            _fenced_plans([_one_plan(), _one_plan(summary="第二個方案")][:plan_count])
        )
        resp = self._post(plan_count=plan_count, promotion_note=promotion_note)
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

    def _reject(self, entries: list):
        return self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/reject", json={"entries": entries}
        )

    def test_empty_entries_is_rejected_before_creating_rules_or_calling_agent(self):
        self._succeed_plan()
        fake = _fake(_fenced_plans([_one_plan()]))
        schedule_jobs.PROVIDER = fake
        resp = self._reject([])
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(fake.calls, [])
        self.assertEqual(bi_repo.list_rules_for_brand(web.conn, self.brand["id"]), [])

    def test_content_too_long_is_rejected(self):
        self._succeed_plan()
        resp = self._reject([{"severity": "hard", "content": "太" * 101}])
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(bi_repo.list_rules_for_brand(web.conn, self.brand["id"]), [])

    def test_blank_content_is_rejected(self):
        self._succeed_plan()
        resp = self._reject([{"severity": "hard", "content": "   "}])
        self.assertEqual(resp.status_code, 400)

    def test_invalid_severity_is_rejected(self):
        self._succeed_plan()
        resp = self._reject([{"severity": "medium", "content": "不上不下"}])
        self.assertEqual(resp.status_code, 400)

    def test_soft_entry_with_invalid_category_is_rejected(self):
        self._succeed_plan()
        resp = self._reject([{"severity": "soft", "rule_type": "policy", "content": "受眾不對"}])
        self.assertEqual(resp.status_code, 400)  # policy 是既有分類，不在新增的四個偏好類別內

    def test_hard_entry_forces_forbidden_word_regardless_of_supplied_rule_type(self):
        self._succeed_plan()
        resp = self._reject(
            [{"severity": "hard", "rule_type": "policy", "content": "絕不可宣稱醫療效果"}]
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        rules = bi_repo.list_rules_for_brand(web.conn, self.brand["id"])
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["rule_type"], "forbidden_word")
        self.assertEqual(rules[0]["severity"], "hard")

    def test_creates_one_rule_per_entry_and_reruns_plan_with_frozen_params(self):
        self._succeed_plan(plan_count=2, promotion_note="這期主打新品")
        first_task_id = self.client.get(
            f"/api/schedule/brands/{self.brand['id']}"
        ).json()["plan"]["task_id"]  # 讀目前的 task_id，不能再 POST 一次（會覆蓋掉凍結參數）

        fake = _fake(_fenced_plans([_one_plan()]))  # 重排只回 1 個方案，證明真的重打了代理
        schedule_jobs.PROVIDER = fake
        resp = self._reject([
            {"severity": "hard", "content": "絕不可宣稱醫療效果"},
            {"severity": "soft", "rule_type": "audience", "content": "受眾偏了，不該對到長輩"},
        ])
        self.assertEqual(resp.status_code, 200, resp.text)

        rules = bi_repo.list_rules_for_brand(web.conn, self.brand["id"])
        self.assertEqual(len(rules), 2)  # 兩條意見各自一列——寫規則是同步的，不必等 worker

        self._run_worker()  # 票 05-1：重跑的排程現在排進佇列，跑一次 worker 才會真的重打代理
        self.assertEqual(len(fake.calls), 1)  # 真的重跑了一次排程
        body = self.client.get(f"/api/schedule/brands/{self.brand['id']}").json()

        # 重跑用的是舊方案凍結的參數：一樣的產品／平台／目標／促銷重點／方案數。
        self.assertEqual(body["plan"]["product_ids"], [self.product["id"]])
        self.assertEqual(body["plan"]["platform"], VALID_PLATFORM)
        self.assertEqual(body["plan"]["objective"], VALID_OBJECTIVE)
        self.assertEqual(body["plan"]["promotion_note"], "這期主打新品")
        self.assertEqual(len(body["plan"]["plans"]), 1)  # plan_count 凍結值＝2 沒被亂用，這裡
        # 只是確認新的一次任務確實跑完（回傳這次 fake 回覆的 1 個方案），task_id 也不同。
        self.assertNotEqual(body["plan"]["task_id"], first_task_id)

    def test_no_succeeded_plan_is_rejected_before_creating_rules(self):
        resp = self._reject([{"severity": "hard", "content": "還沒排過程"}])
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(bi_repo.list_rules_for_brand(web.conn, self.brand["id"]), [])


class TreeApiContractTest(_ScheduleApiTestBase):
    """票 09：POST .../tree、GET 回應多帶的 tree 欄位。"""

    def _succeed_plan(self, plan_count: int = 2) -> None:
        schedule_jobs.PROVIDER = _fake(
            _fenced_plans([_one_plan(), _one_plan(summary="第二個方案")][:plan_count])
        )
        resp = self._post(plan_count=plan_count)
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

    def test_post_tree_returns_tree_and_prompt_carries_department_file(self):
        self._succeed_plan()
        fake = _fake(_tree_fenced(_one_tree_nodes()))
        schedule_jobs.PROVIDER = fake

        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        tree = self.client.get(f"/api/schedule/brands/{self.brand['id']}").json()["tree"]
        self.assertIsNone(tree["failure"])
        self.assertEqual(tree["plan_index"], 0)
        self.assertEqual(tree["levels"], ["行銷活動", "廣告組合", "廣告"])
        self.assertEqual(tree["budget_level"], 2)
        share_nodes = tree["nodes"][0]["children"]
        # daily_budget 凍結自選定方案的來源列（setUp 設的 3000），不是重讀規則卡。
        self.assertEqual(sum(n["daily_amount"] for n in share_nodes), 3000)

        # ADR 0029：部門任務檔原樣貼進 prompt——用檔案裡的識別行證明真的貼進去了。
        self.assertEqual(len(fake.calls), 1)
        prompt_text = fake.calls[0]["messages"][0]["content"]
        self.assertIn("CAMPAIGN-TREE-TASK-V1", prompt_text)

    def test_get_after_post_tree_returns_identical_tree(self):
        self._succeed_plan()
        schedule_jobs.PROVIDER = _fake(_tree_fenced(_one_tree_nodes()))
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        get_resp_1 = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        get_resp_2 = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(get_resp_1.json()["tree"], get_resp_2.json()["tree"])

    def test_plan_index_out_of_range_is_rejected_before_calling_agent(self):
        self._succeed_plan(plan_count=2)
        fake = _fake(_tree_fenced(_one_tree_nodes()))
        schedule_jobs.PROVIDER = fake
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 5}
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(fake.calls, [])

    def test_no_succeeded_plan_is_rejected_before_calling_agent(self):
        fake = _fake(_tree_fenced(_one_tree_nodes()))
        schedule_jobs.PROVIDER = fake
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(fake.calls, [])


class BindTreeApiContractTest(_ScheduleApiTestBase):
    """票 11：手動在平台上發布的活動，用名稱精準比對回這棵樹的第一層節點——SQL '=' 比對
    （settled 段第 2 點），名稱只用一次、之後改用存下來的 campaign_id（settled 段第 3
    點），零筆或兩筆以上都是失敗，不猜（settled 段第 4 點）。"""

    def setUp(self):
        super().setUp()
        self.today = datetime.now(UTC).date()
        self._external_account_ids: dict = {}
        self.account_id = self._connect_account(coredb.DEV_ORG_ID, "測試廣告帳號")
        meta_repo.bind(web.conn, coredb.DEV_ORG_ID, self.brand["id"], self.account_id)
        web.conn.commit()

    def _connect_account(self, org_id: str, name: str) -> str:
        import uuid

        meta_repo.save_token(web.conn, org_id, "tok")
        external_id = f"act_{uuid.uuid4().hex[:10]}"
        meta_repo.upsert_accounts(web.conn, org_id, [
            {"account_id": external_id, "name": name, "currency": "TWD"},
        ])
        web.conn.commit()
        row = next(a for a in meta_repo.list_accounts(web.conn, org_id)
                   if a["account_id"] == external_id)
        self._external_account_ids[row["id"]] = external_id
        return row["id"]

    def _platform_campaigns(self, by_account: dict):
        """換掉平台上的活動清單（不打網路）：`by_account` 是
        {本地 meta_ad_account.id: [(campaign_id, 活動名稱), …]}。

        名稱比對問的是平台上有沒有這個活動，不是 `meta_entity_spend`——手動建好、維持
        關閉的活動沒有任何 insights 列（見 app/meta/graph.py `list_campaigns`），所以這裡
        換掉的是 `graph.list_campaigns`，不是塞花費列進去。"""
        wanted = {
            self._external_account_ids[row_id]: entries
            for row_id, entries in by_account.items()
        }

        def fake_list_campaigns(_token: str, account_id: str) -> list[dict]:
            return [
                {"campaign_id": campaign_id, "name": name, "effective_status": "ACTIVE"}
                for campaign_id, name in wanted.get(account_id, [])
            ]

        return mock.patch.object(meta_graph, "list_campaigns", fake_list_campaigns)

    def _platform_ad_sets(self, by_campaign: dict):
        """換掉平台上的廣告組合清單（不打網路，票 T3c）：`by_campaign` 是
        {campaign_id: [(adset_id, 廣告組合名稱), …]}——比對只在傳進來的那一個活動
        內部找，不是這個帳號全部（`app/meta/graph.py` `list_ad_sets` 的簽名本身就只收
        一個 `campaign_id`，不是帳號清單）。"""

        def fake_list_ad_sets(_token: str, campaign_id: str) -> list[dict]:
            return [
                {"adset_id": adset_id, "name": name, "external_status": "ACTIVE"}
                for adset_id, name in by_campaign.get(campaign_id, [])
            ]

        return mock.patch.object(meta_graph, "list_ad_sets", fake_list_ad_sets)

    def _platform_ads(self, by_adset: dict):
        """換掉平台上的廣告清單（不打網路，票 T5）：`by_adset` 是
        {adset_id: [(ad_id, 廣告名稱), …]}——比對只在傳進來的那一個廣告組合內部找，跟
        `_platform_ad_sets` 同一個理由，只是深一層（`app/meta/graph.py` `list_ads` 的
        簽名本身就只收一個 `adset_id`，不是帳號或活動清單）。既有的深度二測試沒有掛過
        這支——現在深度二綁定成功會順手觸發深度三比對，不掛就是打真的網路，所以每個會
        走到深度三的既有測試都要跟著掛一次（掛空字典＝故意不比對，讓那個節點留在
        `bind_failure` 裡，不代表沒被呼叫）。"""

        def fake_list_ads(_token: str, adset_id: str) -> list[dict]:
            return [
                {"ad_id": ad_id, "name": name, "external_status": "ACTIVE"}
                for ad_id, name in by_adset.get(adset_id, [])
            ]

        return mock.patch.object(meta_graph, "list_ads", fake_list_ads)

    def _seed_campaign(self, org_id: str, account_id: str, campaign_id: str, campaign_name: str,
                        *, spend: float = 1000.0, roas: float | None = 2.0) -> None:
        meta_repo.upsert_entity_spend(web.conn, org_id, account_id, [
            {"level": "campaign", "entity_id": campaign_id, "entity_name": campaign_name,
             "campaign_id": campaign_id, "adset_id": None, "ad_id": None,
             "spend_date": self.today, "spend": spend, "impressions": 100, "clicks": 10,
             "roas": roas, "actions": None, "action_values": None,
             "attribution_window": "7d_click,1d_view"},
        ])
        web.conn.commit()

    def _succeed_plan_and_tree(self) -> None:
        schedule_jobs.PROVIDER = _fake(_fenced_plans([_one_plan()]))
        resp = self._post(plan_count=1)
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        schedule_jobs.PROVIDER = _fake(_tree_fenced(_one_tree_nodes()))
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

    def _bind(self):
        return self.client.post(f"/api/schedule/brands/{self.brand['id']}/tree/bind")

    def _channel_entity_map_rows(self, brand_id: str | None = None) -> list:
        """票 T3b：綁定現在落在 `channel_entity_map`，不是 `llm_task.context_scope_json`
        （grep `bound_external_ids` 找不到這支——settled 段第 5 點的舊機制已經整段刪掉）。"""
        rows = web.conn.execute(
            "SELECT node_key, external_id FROM channel_entity_map"
            " WHERE org_id = %s AND brand_id = %s ORDER BY node_key",
            (coredb.DEV_ORG_ID, brand_id or self.brand["id"]),
        ).fetchall()
        return [dict(r) for r in rows]

    def _period_node_membership_rows(self, brand_id: str | None = None) -> list:
        """票 T3e：深度 2 綁定時記進 `period_node_membership` 的那一列——欄位比照
        `_channel_entity_map_rows()`，只挑跟斷言相關的幾欄。"""
        rows = web.conn.execute(
            "SELECT node_key, campaign_period_id, from_date, to_date"
            " FROM period_node_membership WHERE org_id = %s AND brand_id = %s"
            " ORDER BY node_key",
            (coredb.DEV_ORG_ID, brand_id or self.brand["id"]),
        ).fetchall()
        return [dict(r) for r in rows]

    # -- 資料正確性：綁一次之後，平台端改名不斷線，花費／ROAS 照樣讀得到 -----------------

    def test_exact_match_binds_once_and_survives_a_rename(self):
        self._succeed_plan_and_tree()
        self._seed_campaign(coredb.DEV_ORG_ID, self.account_id, "camp-1", "活動一")

        with self._platform_campaigns({self.account_id: [("camp-1", "活動一")]}), \
                self._platform_ad_sets({"camp-1": [("as-1", "組合1"), ("as-2", "組合2")]}), \
                self._platform_ads(
                    {"as-1": [("ad-1", "單元1")], "as-2": [("ad-2", "單元2")]}
                ):
            resp = self._bind()
        self.assertEqual(resp.status_code, 200, resp.text)
        tree = resp.json()["tree"]
        self.assertIsNone(tree["bind_failure"])
        node = tree["nodes"][0]
        self.assertEqual(node["bound_external_id"], "camp-1")
        self.assertEqual(node["spend"], 1000.0)
        self.assertEqual(node["roas"], 2.0)

        # 平台端把活動改名——同一個 campaign_id，換了 campaign_name／花費／ROAS。
        self._seed_campaign(
            coredb.DEV_ORG_ID, self.account_id, "camp-1", "活動一（已改名）",
            spend=1500.0, roas=3.0,
        )
        get_resp = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        node = get_resp.json()["tree"]["nodes"][0]
        self.assertEqual(node["bound_external_id"], "camp-1")  # 連結沒斷
        self.assertEqual(node["spend"], 1500.0)
        self.assertEqual(node["roas"], 3.0)

    # -- 資料正確性：關閉中、還沒花過錢的活動照樣配得到 ----------------------------------

    def test_a_paused_campaign_with_no_spend_still_binds(self):
        """手動路徑的順序是「照樹建成關閉 → 配對確認 → 才開跑」，所以配對時活動一定還沒
        花過錢，一列 insights 都沒有。名稱比對若建在 `meta_entity_spend` 上，這一步永遠
        是「在 Meta 上找不到」——名字明明一字不差（2026-08-29 對真帳號實測：
        建了一個 PAUSED 活動，拉完當天花費，那個活動不在花費表裡）。"""
        self._succeed_plan_and_tree()

        with self._platform_campaigns({self.account_id: [("camp-paused", "活動一")]}), \
                self._platform_ad_sets({"camp-paused": [("as-1", "組合1"), ("as-2", "組合2")]}), \
                self._platform_ads(
                    {"as-1": [("ad-1", "單元1")], "as-2": [("ad-2", "單元2")]}
                ):
            resp = self._bind()

        self.assertEqual(resp.status_code, 200, resp.text)
        tree = resp.json()["tree"]
        self.assertIsNone(tree["bind_failure"])
        node = tree["nodes"][0]
        self.assertEqual(node["bound_external_id"], "camp-paused")
        self.assertIsNone(node["spend"])  # 還沒跑過就是沒有數字，不是 0
        self.assertIsNone(node["roas"])

    # -- 零筆比對 -> 唯一的失敗訊息，不綁定、不落地 --------------------------------------

    def test_no_match_shows_failure_message_and_binds_nothing(self):
        self._succeed_plan_and_tree()  # 帳號裡沒有任何叫「活動一」的活動

        with self._platform_campaigns({self.account_id: []}):
            resp = self._bind()
        self.assertEqual(resp.status_code, 200, resp.text)
        tree = resp.json()["tree"]
        # 2026-09-04 實機驗收：訊息要指名是哪一個節點、以及哪一種失敗（找不到 vs 有兩個
        # 同名的）——兩者要做的事相反。整批仍然只講一句（ADR 0055 §4）。
        self.assertIn("「活動一」在 Meta 上找不到", tree["bind_failure"])
        self.assertIsNone(tree["nodes"][0]["bound_external_id"])
        self.assertEqual(self._channel_entity_map_rows(), [])

    # -- 兩筆比對 -> 同一句失敗訊息，不猜一個出來 ----------------------------------------

    def test_two_matches_is_a_failure_not_a_guess(self):
        self._succeed_plan_and_tree()

        with self._platform_campaigns(
            {self.account_id: [("camp-1", "活動一"), ("camp-2", "活動一")]}
        ):
            resp = self._bind()
        self.assertEqual(resp.status_code, 200, resp.text)
        tree = resp.json()["tree"]
        self.assertIn("「活動一」在 Meta 上有 2 個同名的", tree["bind_failure"])
        self.assertIsNone(tree["nodes"][0]["bound_external_id"])
        self.assertEqual(self._channel_entity_map_rows(), [])

    # -- 租戶隔離：另一個組織帳號裡的同名活動不算數 --------------------------------------

    def test_same_name_in_another_orgs_account_is_not_matched(self):
        self._succeed_plan_and_tree()
        org_b, _token_b = self._make_org("bind-isolation")
        account_b = self._connect_account(org_b, "另一個組織的帳號")

        # 只有 org B 的帳號上有這個名稱的活動；org A 的品牌配對時根本不該去讀那個帳號。
        with self._platform_campaigns({account_b: [("camp-b", "活動一")]}):
            resp = self._bind()
        self.assertEqual(resp.status_code, 200, resp.text)
        tree = resp.json()["tree"]
        # 另一個組織的帳號裡有同名活動，但這個組織讀不到 → 對這裡就是「找不到」。
        self.assertIn("「活動一」在 Meta 上找不到", tree["bind_failure"])
        self.assertIsNone(tree["nodes"][0]["bound_external_id"])
        self.assertEqual(self._channel_entity_map_rows(), [])

    # -- 資料正確性：綁定鍵是 node_key，兩個同名節點各自綁到不同活動、互不干擾 -----------

    def test_two_same_name_siblings_bind_to_different_campaigns_and_stay_distinct(self):
        """票 T3b（ADR 0055 §1）：舊版拿節點名稱當 dict key，兩個「活動一」會撞成同一格；
        新版鍵是 node_key，各自綁到不同的活動——這是舊版表達不出來的狀態。"""
        self._succeed_plan_and_tree()  # 第一次展開：第一層只有一個「活動一」（node_key "1"）
        # 平台上這一輪還沒有任何廣告組合（票 T3c：第二層配不到，不影響這裡要看的第一層
        # 結果，`_platform_ad_sets({})` 對任何活動都回空清單）。
        with self._platform_campaigns({self.account_id: [("camp-1", "活動一")]}), \
                self._platform_ad_sets({}):
            resp = self._bind()
        self.assertEqual(resp.json()["tree"]["nodes"][0]["bound_external_id"], "camp-1")

        # 重新展開：這次代理回了兩個第一層節點，都叫「活動一」——node_key "1" 名字沒變，
        # 綁定跟著位置留下來；"2" 是新位置，還沒綁。
        schedule_jobs.PROVIDER = _fake(_tree_fenced(_two_top_nodes("活動一", "活動一")))
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        # 平台上這時只有另一個叫「活動一」的活動（使用者照樹又手動建了第二個），底下
        # 各自也建好了一個廣告組合「組合」（票 T3c：第二層也要各自綁到各自活動內部）。
        with self._platform_campaigns({self.account_id: [("camp-2", "活動一")]}), \
                self._platform_ad_sets(
                    {"camp-1": [("as-1x", "組合")], "camp-2": [("as-2x", "組合")]}
                ), \
                self._platform_ads(
                    {"as-1x": [("ad-1x", "單元")], "as-2x": [("ad-2x", "單元")]}
                ):
            resp = self._bind()
        self.assertEqual(resp.status_code, 200, resp.text)
        tree = resp.json()["tree"]
        self.assertIsNone(tree["bind_failure"])
        self.assertEqual(tree["nodes"][0]["bound_external_id"], "camp-1")  # 沒被動過
        self.assertEqual(tree["nodes"][1]["bound_external_id"], "camp-2")  # 各自綁到不同活動
        self.assertEqual(tree["nodes"][0]["children"][0]["bound_external_id"], "as-1x")
        self.assertEqual(tree["nodes"][1]["children"][0]["bound_external_id"], "as-2x")
        # 票 T5：第三層現在也綁——同一支測試守的「同名手足各自綁到不同活動」延伸一層。
        self.assertEqual(
            tree["nodes"][0]["children"][0]["children"][0]["bound_external_id"], "ad-1x"
        )
        self.assertEqual(
            tree["nodes"][1]["children"][0]["children"][0]["bound_external_id"], "ad-2x"
        )
        self.assertEqual(
            self._channel_entity_map_rows(),
            [{"node_key": "1", "external_id": "camp-1"},
             {"node_key": "1.1", "external_id": "as-1x"},
             {"node_key": "1.1.1", "external_id": "ad-1x"},
             {"node_key": "2", "external_id": "camp-2"},
             {"node_key": "2.1", "external_id": "as-2x"},
             {"node_key": "2.1.1", "external_id": "ad-2x"}],
        )

    # -- 資料正確性：位置配對，名字只當否決票 --------------------------------------------

    def test_re_expand_keeps_binding_when_name_unchanged_shows_unbound_when_renamed(self):
        """ADR 0055 §4：同位置、同名字——綁定留著；同位置、換了名字——顯示未綁定。"""
        self._succeed_plan_and_tree()
        # 這支測試只看第一層，第二層有沒有配到不影響這裡的斷言。
        with self._platform_campaigns({self.account_id: [("camp-1", "活動一")]}), \
                self._platform_ad_sets({}):
            resp = self._bind()
        self.assertEqual(resp.json()["tree"]["nodes"][0]["bound_external_id"], "camp-1")

        schedule_jobs.PROVIDER = _fake(_tree_fenced(_one_tree_nodes()))  # 同名重展開
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        get_resp = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(get_resp.json()["tree"]["nodes"][0]["bound_external_id"], "camp-1")

        schedule_jobs.PROVIDER = _fake(  # 同位置、換了名字
            _tree_fenced(_one_tree_nodes(name="活動一（改版）"))
        )
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        get_resp = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertIsNone(get_resp.json()["tree"]["nodes"][0]["bound_external_id"])

    # -- ticket 矛盾檢查段：兩個鄰居互換名字，位置優先，都不繼承對方的綁定 ---------------

    def test_rename_swap_between_siblings_leaves_both_unbound(self):
        """node "1" 從 A 改名成 B、node "2" 從 B 改名成 A——位置先配對、名字只當否決票，
        兩邊都要顯示未綁定，不是被「幫」著互換活動。"""
        schedule_jobs.PROVIDER = _fake(_fenced_plans([_one_plan()]))
        resp = self._post(plan_count=1)
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        schedule_jobs.PROVIDER = _fake(_tree_fenced(_two_top_nodes("活動A", "活動B")))
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        # 這支測試只看第一層互換名字的行為，第二層有沒有配到不影響這裡的斷言。
        with self._platform_campaigns(
            {self.account_id: [("camp-a", "活動A"), ("camp-b", "活動B")]}
        ), self._platform_ad_sets({}):
            resp = self._bind()
        self.assertEqual(resp.status_code, 200, resp.text)
        tree = resp.json()["tree"]
        self.assertEqual(tree["nodes"][0]["bound_external_id"], "camp-a")
        self.assertEqual(tree["nodes"][1]["bound_external_id"], "camp-b")

        # 重新展開：同樣兩個位置，名字互換了。
        schedule_jobs.PROVIDER = _fake(_tree_fenced(_two_top_nodes("活動B", "活動A")))
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        get_resp = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        tree = get_resp.json()["tree"]
        self.assertIsNone(tree["nodes"][0]["bound_external_id"])
        self.assertIsNone(tree["nodes"][1]["bound_external_id"])

    # -- 資料正確性：改名後第二次 bind 是覆寫同一列，不是撞唯一鍵 -----------------------

    def test_second_bind_after_rename_updates_the_row_not_a_unique_violation(self):
        self._succeed_plan_and_tree()
        # 這支測試守的是第一層 upsert 鍵的行為，第二層有沒有配到不影響——兩次都給空的
        # 廣告組合清單（`_platform_ad_sets({})`），兩層各自的失敗互不牽連。
        with self._platform_campaigns({self.account_id: [("camp-1", "活動一")]}), \
                self._platform_ad_sets({}):
            resp = self._bind()
        self.assertEqual(resp.json()["tree"]["nodes"][0]["bound_external_id"], "camp-1")

        schedule_jobs.PROVIDER = _fake(_tree_fenced(_one_tree_nodes(name="活動一（新版）")))
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        # 第二次 bind：平台上是新名字的活動——upsert 蓋掉同一個 node_key 的舊列，不是
        # 撞 `(org_id, brand_id, channel_id, node_key)` 唯一鍵報錯。平台上一樣沒有廣告
        # 組合，所以第二層兩個子節點都配不到——`bind_failure` 因此非 null，這是第二層
        # 自己的失敗，不影響這支測試要證的事：第一層同一個 node_key 只有一列。
        with self._platform_campaigns({self.account_id: [("camp-2", "活動一（新版）")]}), \
                self._platform_ad_sets({}):
            resp = self._bind()
        self.assertEqual(resp.status_code, 200, resp.text)
        tree = resp.json()["tree"]
        self.assertIn("「組合1」在 Meta 上找不到", tree["bind_failure"])
        self.assertEqual(tree["nodes"][0]["bound_external_id"], "camp-2")
        self.assertEqual(  # 同一個 node_key 只有一列，覆寫不是新增
            self._channel_entity_map_rows(), [{"node_key": "1", "external_id": "camp-2"}]
        )

    # -- 租戶隔離：疊圖的 SQL 用 org_id／brand_id 篩，另一個組織的綁定看不到 --------------

    def test_another_orgs_binding_is_not_visible_through_the_tree_endpoint(self):
        self._succeed_plan_and_tree()
        # 這支測試只看第一層的租戶隔離，第二層有沒有配到不影響這裡的斷言。
        with self._platform_campaigns({self.account_id: [("camp-1", "活動一")]}), \
                self._platform_ad_sets({}):
            resp = self._bind()
        self.assertEqual(resp.json()["tree"]["nodes"][0]["bound_external_id"], "camp-1")

        org_b, token_b = self._make_org("bind-tree-isolation")
        brand_b = bi_repo.create_brand(
            web.conn, org_id=org_b, name="另一個組織的品牌", client_name=None, actor=ACTOR,
        )
        product_b = bi_repo.create_product(
            web.conn, brand_b["id"], name="另一個組織的產品", actor=ACTOR,
        )
        rule_cards.set_value(
            web.conn, brand_b["id"], "schedule_budget", "daily_budget", 3000.0,
            ACTOR, org_id=org_b,
        )
        headers = self._headers(token_b, org_b)

        schedule_jobs.PROVIDER = _fake(_fenced_plans([_one_plan()]))
        resp = self.client.post(
            f"/api/schedule/brands/{brand_b['id']}/plans",
            json=_post_body(product_ids=[product_b["id"]], plan_count=1),
            headers=headers,
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        # org B 自己的樹，同一個 node_key "1"，名字也叫「活動一」——這是最容易撞到的情境。
        schedule_jobs.PROVIDER = _fake(_tree_fenced(_one_tree_nodes()))
        resp = self.client.post(
            f"/api/schedule/brands/{brand_b['id']}/tree", json={"plan_index": 0},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        get_resp = self.client.get(f"/api/schedule/brands/{brand_b['id']}", headers=headers)
        self.assertIsNone(get_resp.json()["tree"]["nodes"][0]["bound_external_id"])

    # -- 票 T3c（ADR 0055 §7）：第二層（扛預算的廣告組合）也綁 --------------------------

    def test_depth_two_and_three_nodes_bind_inside_their_parents_and_show_on_the_tree(self):
        """票 T5（ADR 0057 §1／§2）：第一層綁定成功之後，第二層在它底下的活動範圍內
        比對；第二層綁定成功之後，同一條規則再套一次——第三層（廣告）在它底下的廣告組合
        範圍內比對。綁到的 id 要出現在 API 回的樹上（不是只寫進 `channel_entity_map`）。
        三層都綁了之後：depth-3 的列要帶著這次 bind 的 `source_tree_task_id`（凍結是哪棵
        樹綁的，ADR 0057 §2）；`period_node_membership` 仍然只在深度 2 各一列，不會因為
        深度 3 多出一列（done-check 4：不是一張表變成一個 ad 一列）。"""
        self._succeed_plan_and_tree()  # 活動一 -> 組合1（share .7）／組合2（share .3）
        with self._platform_campaigns({self.account_id: [("camp-1", "活動一")]}), \
                self._platform_ad_sets({"camp-1": [("as-1", "組合1"), ("as-2", "組合2")]}), \
                self._platform_ads(
                    {"as-1": [("ad-1", "單元1")], "as-2": [("ad-2", "單元2")]}
                ):
            resp = self._bind()
        self.assertEqual(resp.status_code, 200, resp.text)
        tree = resp.json()["tree"]
        self.assertIsNone(tree["bind_failure"])
        parent = tree["nodes"][0]
        self.assertEqual(parent["bound_external_id"], "camp-1")
        self.assertEqual(parent["children"][0]["bound_external_id"], "as-1")
        self.assertEqual(parent["children"][1]["bound_external_id"], "as-2")
        self.assertEqual(parent["children"][0]["children"][0]["bound_external_id"], "ad-1")
        self.assertEqual(parent["children"][1]["children"][0]["bound_external_id"], "ad-2")
        self.assertEqual(
            {(r["node_key"], r["external_id"]) for r in self._channel_entity_map_rows()},
            {("1", "camp-1"), ("1.1", "as-1"), ("1.1.1", "ad-1"),
             ("1.2", "as-2"), ("1.2.1", "ad-2")},
        )
        source_tree_task_id = tree["task_id"]
        depth_three_rows = web.conn.execute(
            "SELECT node_key, source_tree_task_id FROM channel_entity_map"
            " WHERE org_id = %s AND brand_id = %s AND depth = 3 ORDER BY node_key",
            (coredb.DEV_ORG_ID, self.brand["id"]),
        ).fetchall()
        self.assertEqual(
            [dict(r) for r in depth_three_rows],
            [{"node_key": "1.1.1", "source_tree_task_id": source_tree_task_id},
             {"node_key": "1.2.1", "source_tree_task_id": source_tree_task_id}],
        )
        # done-check 4：深度 3 綁了兩個 ad，membership 仍然只在深度 2 各一列——不是一個
        # ad 一列（ADR 0055 §6：membership 只認扛預算的那一層）。
        self.assertEqual(
            {r["node_key"] for r in self._period_node_membership_rows()}, {"1.1", "1.2"},
        )

    def test_depth_two_match_in_another_campaign_does_not_bind_it(self):
        """ticket 矛盾檢查段第一點：兩個活動都綁定了，各自底下有一個同名的廣告組合
        「組合」——比對只在各自的活動範圍內找，讀全帳號會看到兩筆、兩邊都綁不了；
        讀各自活動內部各只有一筆，兩邊都該綁上。"""
        schedule_jobs.PROVIDER = _fake(_fenced_plans([_one_plan()]))
        resp = self._post(plan_count=1)
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        schedule_jobs.PROVIDER = _fake(_tree_fenced(_two_top_nodes("活動A", "活動B")))
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        with self._platform_campaigns(
            {self.account_id: [("camp-a", "活動A"), ("camp-b", "活動B")]}
        ), self._platform_ad_sets(
            {"camp-a": [("as-a", "組合")], "camp-b": [("as-b", "組合")]}
        ), self._platform_ads(
            {"as-a": [("ad-a", "單元")], "as-b": [("ad-b", "單元")]}
        ):
            resp = self._bind()
        self.assertEqual(resp.status_code, 200, resp.text)
        tree = resp.json()["tree"]
        self.assertIsNone(tree["bind_failure"])
        self.assertEqual(tree["nodes"][0]["children"][0]["bound_external_id"], "as-a")
        self.assertEqual(tree["nodes"][1]["children"][0]["bound_external_id"], "as-b")

    def test_depth_two_node_under_unbound_parent_is_not_attempted(self):
        """第一層沒配對到活動，底下的第二層完全不查——猜整個帳號等於綁到陌生人的
        廣告組合（ticket 說明第 3 點）。用呼叫紀錄證明真的沒打這支查詢，不只是結果
        剛好是 None。"""
        self._succeed_plan_and_tree()  # 帳號裡沒有叫「活動一」的活動
        calls: list = []

        def fake_list_ad_sets(_token: str, campaign_id: str) -> list[dict]:
            calls.append(campaign_id)
            return []

        with self._platform_campaigns({self.account_id: []}), \
                mock.patch.object(meta_graph, "list_ad_sets", fake_list_ad_sets):
            resp = self._bind()
        self.assertEqual(resp.status_code, 200, resp.text)
        tree = resp.json()["tree"]
        # 只講第一層那個節點——第二層根本沒去比對，訊息不該假裝它也失敗了；
        # 「上一層沒配對成功時底下不會比對」那句話由 `bind_failure_message()` 固定附上。
        self.assertIn("「活動一」在 Meta 上找不到", tree["bind_failure"])
        self.assertNotIn("組合", tree["bind_failure"])
        self.assertIsNone(tree["nodes"][0]["bound_external_id"])
        self.assertIsNone(tree["nodes"][0]["children"][0]["bound_external_id"])
        self.assertEqual(calls, [])

    def test_two_depth_two_siblings_same_name_both_stay_unbound(self):
        """ticket 矛盾檢查段第二點：跟第一層「兩個同名手足各自綁到不同活動」不是同一件
        事——這裡的歧義在平台端（同一個活動底下兩個廣告組合剛好同名），沒有任何資訊能
        分辨誰是誰，兩邊都不猜；第一層照樣維持綁定。"""
        schedule_jobs.PROVIDER = _fake(_fenced_plans([_one_plan()]))
        resp = self._post(plan_count=1)
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        schedule_jobs.PROVIDER = _fake(
            _tree_fenced(_one_tree_nodes(child_names=("組合", "組合")))
        )
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        with self._platform_campaigns({self.account_id: [("camp-1", "活動一")]}), \
                self._platform_ad_sets({"camp-1": [("as-1", "組合"), ("as-2", "組合")]}):
            resp = self._bind()
        self.assertEqual(resp.status_code, 200, resp.text)
        tree = resp.json()["tree"]
        # 兩個同名手足產生兩句一模一樣的原因，訊息去重只講一次（兩邊都沒綁上不變）。
        self.assertEqual(
            tree["bind_failure"].count("「組合」在 Meta 上有 2 個同名的"), 1
        )
        self.assertEqual(tree["nodes"][0]["bound_external_id"], "camp-1")  # 第一層照樣綁定
        self.assertIsNone(tree["nodes"][0]["children"][0]["bound_external_id"])
        self.assertIsNone(tree["nodes"][0]["children"][1]["bound_external_id"])
        self.assertEqual(
            self._channel_entity_map_rows(), [{"node_key": "1", "external_id": "camp-1"}]
        )

    def test_depth_two_node_renamed_after_binding_shows_unbound(self):
        """ADR 0055 §4：位置配對、名字只當否決票——第二層跟第一層適用同一條規則
        （比照 test_re_expand_keeps_binding_when_name_unchanged_shows_unbound_when_renamed）。
        重新展開只換第二層第一個子節點的名字，第一層與第二層第二個子節點都沒動。"""
        self._succeed_plan_and_tree()
        with self._platform_campaigns({self.account_id: [("camp-1", "活動一")]}), \
                self._platform_ad_sets({"camp-1": [("as-1", "組合1"), ("as-2", "組合2")]}), \
                self._platform_ads({}):
            resp = self._bind()
        tree = resp.json()["tree"]
        self.assertEqual(tree["nodes"][0]["children"][0]["bound_external_id"], "as-1")
        self.assertEqual(tree["nodes"][0]["children"][1]["bound_external_id"], "as-2")

        schedule_jobs.PROVIDER = _fake(
            _tree_fenced(_one_tree_nodes(child_names=("組合1（改版）", "組合2")))
        )
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        get_resp = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        tree = get_resp.json()["tree"]
        self.assertEqual(tree["nodes"][0]["bound_external_id"], "camp-1")  # 第一層沒動過
        self.assertIsNone(tree["nodes"][0]["children"][0]["bound_external_id"])  # 改名了
        self.assertEqual(tree["nodes"][0]["children"][1]["bound_external_id"], "as-2")  # 沒改名

    # -- 票 T3e（ADR 0055 §11）：深度 2 綁定時記 period_node_membership --------------------

    def test_depth_two_binding_writes_period_node_membership_for_the_current_period(self):
        """ticket §1：`from_date`／`to_date` 是檔期自己的 `start_date`／`end_date`，深度 1
        （`node_key` "1"）不寫——membership 只在扛預算那一層（ADR 0055 §6）。"""
        self._succeed_plan_and_tree()
        period = web.conn.execute(
            "SELECT id, start_date, end_date FROM campaign_period"
            " WHERE org_id = %s AND brand_id = %s",
            (coredb.DEV_ORG_ID, self.brand["id"]),
        ).fetchone()
        with self._platform_campaigns({self.account_id: [("camp-1", "活動一")]}), \
                self._platform_ad_sets({"camp-1": [("as-1", "組合1"), ("as-2", "組合2")]}), \
                self._platform_ads({}):
            resp = self._bind()
        self.assertEqual(resp.status_code, 200, resp.text)
        rows = self._period_node_membership_rows()
        self.assertEqual({r["node_key"] for r in rows}, {"1.1", "1.2"})
        for row in rows:
            self.assertEqual(row["campaign_period_id"], period["id"])
            self.assertEqual(row["from_date"], period["start_date"])
            self.assertEqual(row["to_date"], period["end_date"])

    def test_binding_with_no_period_writes_no_membership_and_still_succeeds(self):
        """ticket §1：「沒有檔期 → 不寫 membership、也不是錯誤」。今天的畫面一定先出方案
        才綁得到樹，方案一出檔期就在了，所以這是防禦性分支——直接把檔期刪掉，逼出這條
        今天走不到、但寫在 ticket 上要求釘住的路。"""
        self._succeed_plan_and_tree()
        # llm_task.campaign_period_id 是 nullable 外鍵（票 T2 留的：「LLM 花費有主人」），
        # 刪檔期之前先解開這棵樹的參照，不然刪檔期會撞外鍵——這裡要刪的是檔期，不是樹。
        web.conn.execute(
            "UPDATE llm_task SET campaign_period_id = NULL"
            " WHERE org_id = %s AND brand_id = %s",
            (coredb.DEV_ORG_ID, self.brand["id"]),
        )
        web.conn.execute(
            "DELETE FROM campaign_period WHERE org_id = %s AND brand_id = %s",
            (coredb.DEV_ORG_ID, self.brand["id"]),
        )
        web.conn.commit()
        with self._platform_campaigns({self.account_id: [("camp-1", "活動一")]}), \
                self._platform_ad_sets({"camp-1": [("as-1", "組合1"), ("as-2", "組合2")]}), \
                self._platform_ads(
                    {"as-1": [("ad-1", "單元1")], "as-2": [("ad-2", "單元2")]}
                ):
            resp = self._bind()
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIsNone(resp.json()["tree"]["bind_failure"])
        self.assertEqual(self._period_node_membership_rows(), [])

    def test_depth_two_rebind_in_the_same_period_does_not_duplicate_membership(self):
        """ticket done-check 3：雙寫在結構上不可能。改名逼出真的第二次 `upsert_binding`
        （跟上面第一層 `test_second_bind_after_rename_updates_the_row_not_a_unique_violation`
        同一個手法）——同一期、同一個 `node_key`，migration 那把唯一鍵讓第二次 INSERT
        變成 `ON CONFLICT DO NOTHING`，不是應用層自己記得寫過。"""
        self._succeed_plan_and_tree()
        with self._platform_campaigns({self.account_id: [("camp-1", "活動一")]}), \
                self._platform_ad_sets({"camp-1": [("as-1", "組合1"), ("as-2", "組合2")]}), \
                self._platform_ads({}):
            self._bind()
        self.assertEqual(
            {r["node_key"] for r in self._period_node_membership_rows()}, {"1.1", "1.2"},
        )

        schedule_jobs.PROVIDER = _fake(
            _tree_fenced(_one_tree_nodes(child_names=("組合1（新版）", "組合2")))
        )
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        with self._platform_campaigns({self.account_id: [("camp-1", "活動一")]}), \
                self._platform_ad_sets(
                    {"camp-1": [("as-1x", "組合1（新版）"), ("as-2", "組合2")]}
                ), \
                self._platform_ads({}):
            resp = self._bind()
        self.assertEqual(resp.status_code, 200, resp.text)
        rows = self._period_node_membership_rows()
        self.assertEqual(sorted(r["node_key"] for r in rows), ["1.1", "1.2"])


class CreativeApiContractTest(_ScheduleApiTestBase):
    """票 01（`.scratch/creative-slice/issues/01-ad-creative-per-ad-node.md`）：POST
    .../creative——活動樹每個最深層節點各配一份內容。這裡的最深層節點固定是 `_one_tree_nodes()`
    產生的「單元1」「單元2」（見本檔頂部），照文件順序。"""

    _LEAF_NODE_NAMES = ["單元1", "單元2"]

    def _succeed_plan_and_tree(self) -> None:
        schedule_jobs.PROVIDER = _fake(_fenced_plans([_one_plan()]))
        resp = self._post(plan_count=1)
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        schedule_jobs.PROVIDER = _fake(_tree_fenced(_one_tree_nodes()))
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

    def _generate(self):
        return self.client.post(f"/api/schedule/brands/{self.brand['id']}/creative", json={})

    def test_post_creative_returns_one_ad_per_leaf_node_and_prompt_carries_department_file(self):
        self._succeed_plan_and_tree()
        # 代理故意回覆「反過來」的順序——用來證明回應真的是照樹的文件順序重排，不是原樣
        # 照抄代理回覆的順序（代理不保證照樹的順序回覆）。
        reversed_names = list(reversed(self._LEAF_NODE_NAMES))
        fake = _fake(_creative_fenced([_one_creative(name) for name in reversed_names]))
        schedule_jobs.PROVIDER = fake

        resp = self._generate()
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        creative = self.client.get(f"/api/schedule/brands/{self.brand['id']}").json()["creative"]
        self.assertIsNone(creative["failure"])
        # 樹的文件順序（單元1、單元2），不是代理回覆的順序（單元2、單元1）。
        self.assertEqual([ad["node"] for ad in creative["ads"]], self._LEAF_NODE_NAMES)
        # 票 T1：`value` 一律正規化成陣列——`_one_creative()` 給的是單一字串，撐過外殼之後
        # 變成單元素陣列（既有的單字串回覆照樣能用，只是形狀換了）。
        self.assertEqual(
            creative["ads"][0]["fields"],
            [
                {"label": "主要文字", "value": ["測試內容"]},
                {"label": "圖片提示詞", "value": ["測試提示詞"]},
            ],
        )
        # 票 T1 站③收尾：座標撐得過 API 層，不只撐得過 build_creative() 這支純函式。
        self.assertEqual(creative["ads"][0]["coordinates"]["angle"], "測試角度")

        # ADR 0029：部門任務檔原樣貼進 prompt——用檔案裡的識別行證明真的貼進去了。
        self.assertEqual(len(fake.calls), 1)
        prompt_text = fake.calls[0]["messages"][0]["content"]
        self.assertIn("AD-CREATIVE-TASK-V1", prompt_text)

    def test_creative_task_gets_methodology(self):
        """票 T1 第 4 節：`jobs.schedule_creative()` 過去沒有接方法論，代理看不到 35 個
        創意角度、也看不到 Meta 版位字數規格。紅法：把 `app/methodology/README.md` 的
        「廣告內容生成」那一列拿掉，`methodology.compile()` 就找不到這兩份檔案，prompt
        裡不會再出現這兩句斷言字串。"""
        self._succeed_plan_and_tree()
        fake = _fake(_creative_fenced([_one_creative(name) for name in self._LEAF_NODE_NAMES]))
        schedule_jobs.PROVIDER = fake

        resp = self._generate()
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        self.assertEqual(len(fake.calls), 1)
        prompt_text = fake.calls[0]["messages"][0]["content"]
        self.assertIn("【方法論：creative-matrix.md】", prompt_text)
        self.assertIn("【方法論：meta-format-specs.md】", prompt_text)

    def test_creative_prompt_carries_the_brand_coordinate_vocabulary(self):
        """票 T8b：七維座標的詞彙表要真的進 prompt。落地時
        `repository._resolve_coordinates()` 拿代理回的字串比對 `brand_coordinate.label`，
        比對不到就寫 NULL——所以少了這一節，代理只會造詞，六維照樣全空，而且外面看起來像
        功能已經動了。停用掉的詞不給代理挑（使用者在畫面上劃掉的值不該再被填回來）。
        紅法：把 `jobs.schedule_creative()` 那行 `coordinate_text` 從 prompt 的 join 裡拿掉。"""
        self._succeed_plan_and_tree()
        brand_id = self.brand["id"]
        listed = self.client.get(f"/api/schedule/brands/{brand_id}/coordinates")
        self.assertEqual(listed.status_code, 200, listed.text)
        disabled = next(
            c for c in listed.json()["coordinates"] if c["dimension"] == "offer"
        )
        off = self.client.post(
            f"/api/schedule/brands/{brand_id}/coordinates/{disabled['id']}/disable",
            json={"disabled": True},
        )
        self.assertEqual(off.status_code, 200, off.text)
        fake = _fake(_creative_fenced([_one_creative(name) for name in self._LEAF_NODE_NAMES]))
        schedule_jobs.PROVIDER = fake

        resp = self._generate()
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        self.assertEqual(len(fake.calls), 1)
        prompt_text = fake.calls[0]["messages"][0]["content"]
        self.assertIn("## 這個品牌的座標詞彙表", prompt_text)
        # 七個維度各自一段，順序照 COORDINATE_KEYS。
        for dimension in creative_mod.COORDINATE_KEYS:
            self.assertIn(f"### {dimension}", prompt_text)
        # 「無證明」是 proof 維度真的有的值（票 T8a 裁決③：沒放證明也要有 key）。
        self.assertIn("無證明", prompt_text)
        # 停用掉的那個值不出現——代理挑不到使用者已經劃掉的詞。
        self.assertNotIn(disabled["label"], prompt_text)

    def test_get_after_post_returns_identical_creative(self):
        self._succeed_plan_and_tree()
        schedule_jobs.PROVIDER = _fake(_creative_fenced(
            [_one_creative(name) for name in self._LEAF_NODE_NAMES]
        ))
        resp = self._generate()
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        get_resp_1 = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        get_resp_2 = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(get_resp_1.json()["creative"], get_resp_2.json()["creative"])

    def test_no_succeeded_tree_is_rejected_before_calling_agent(self):
        fake = _fake(_creative_fenced([_one_creative("單元1")]))
        schedule_jobs.PROVIDER = fake
        resp = self._generate()
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(fake.calls, [])

    def test_missing_node_fails_the_whole_run(self):
        self._succeed_plan_and_tree()
        # 少一份：「單元2」沒有配到內容。
        schedule_jobs.PROVIDER = _fake(_creative_fenced([_one_creative("單元1")]))
        resp = self._generate()
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        creative = self.client.get(f"/api/schedule/brands/{self.brand['id']}").json()["creative"]
        self.assertTrue(creative["failure"])
        self.assertEqual(creative["ads"], [])

    def test_duplicate_node_fails_the_whole_run(self):
        self._succeed_plan_and_tree()
        schedule_jobs.PROVIDER = _fake(_creative_fenced(
            [_one_creative("單元1"), _one_creative("單元1"), _one_creative("單元2")]
        ))
        resp = self._generate()
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        creative = self.client.get(f"/api/schedule/brands/{self.brand['id']}").json()["creative"]
        self.assertTrue(creative["failure"])
        self.assertEqual(creative["ads"], [])

    def test_unknown_node_fails_the_whole_run(self):
        self._succeed_plan_and_tree()
        schedule_jobs.PROVIDER = _fake(_creative_fenced(
            [_one_creative("單元1"), _one_creative("不存在的節點")]
        ))
        resp = self._generate()
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        creative = self.client.get(f"/api/schedule/brands/{self.brand['id']}").json()["creative"]
        self.assertTrue(creative["failure"])
        self.assertEqual(creative["ads"], [])

    def test_running_creative_renders_as_running_not_failure(self):
        self._succeed_plan_and_tree()
        tree_row = schedule_state._latest_task_row(
            web.conn, self.brand["id"], schedule_state.TREE_TASK_TYPE
        )
        web.conn.execute(
            "INSERT INTO llm_task (id, org_id, brand_id, task_type, context_scope_json,"
            " input_context_ids_json, input_context_hash, knowledge_item_ids_json,"
            " brand_version, prompt_template_id, prompt_template_version, provider, model,"
            " status, attempt_no, started_at)"
            " VALUES (%s, %s, %s, %s, %s, '[]', '', '[]', 1, 'p', 'v1', 'seed', 'seed',"
            " 'running', 1, %s)",
            (
                coredb.new_id("llm"), coredb.DEV_ORG_ID, self.brand["id"],
                schedule_state.CREATIVE_TASK_TYPE,
                coredb.jsonb({
                    "brand_id": self.brand["id"], "source_tree_task_id": tree_row["id"],
                    "plan_index": 0,
                }),
                coredb.now_iso(),
            ),
        )
        web.conn.commit()

        resp = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(resp.status_code, 200, resp.text)
        creative = resp.json()["creative"]
        self.assertTrue(creative["running"])
        self.assertIsNone(creative["failure"])


class CoordinateSeedTest(_ScheduleApiTestBase):
    """票 T1b done-check：一個品牌的座標第一次被讀出時，剛好 35 個 `dimension='angle'`；
    讀第二次不會多出 70 個（`ensure_coordinates_seeded` 冪等）。票 T8a 擴充：另外六個維度
    也要種進去（35＋33＝68），讀第二次一樣不會變成 136 個。"""

    def test_first_read_seeds_35_angles_second_read_does_not_duplicate(self):
        resp1 = self.client.get(f"/api/schedule/brands/{self.brand['id']}/coordinates")
        self.assertEqual(resp1.status_code, 200, resp1.text)
        coordinates1 = resp1.json()["coordinates"]
        angles1 = [c for c in coordinates1 if c["dimension"] == "angle"]
        self.assertEqual(len(angles1), 35)

        # 票 T8a done-check 1：七個維度都有座標，六個新維度加總 33 個。
        seven_dims = creative_mod.COORDINATE_KEYS
        self.assertEqual(
            {c["dimension"] for c in coordinates1}, set(seven_dims),
            "第一次讀完應該七個維度都有座標",
        )
        other_six = [c for c in coordinates1 if c["dimension"] != "angle"]
        self.assertEqual(len(other_six), 33)

        resp2 = self.client.get(f"/api/schedule/brands/{self.brand['id']}/coordinates")
        self.assertEqual(resp2.status_code, 200, resp2.text)
        coordinates2 = resp2.json()["coordinates"]
        angles2 = [c for c in coordinates2 if c["dimension"] == "angle"]
        self.assertEqual(len(angles2), 35)
        other_six2 = [c for c in coordinates2 if c["dimension"] != "angle"]
        self.assertEqual(len(other_six2), 33)


class CoordinateTenantIsolationTest(_ScheduleApiTestBase):
    """票 T1b done-check：品牌 A 的座標對品牌 B 不可見；停用 A 的角度不影響 B。"""

    def test_brand_a_coordinates_invisible_to_brand_b_and_disable_does_not_cross(self):
        brand_b = bi_repo.create_brand(
            web.conn, org_id=coredb.DEV_ORG_ID, name="測試品牌：另一個品牌座標",
            client_name=None, actor=ACTOR,
        )

        coords_a = self.client.get(
            f"/api/schedule/brands/{self.brand['id']}/coordinates"
        ).json()["coordinates"]
        target = next(c for c in coords_a if c["label"] == "稀缺性行銷")

        disable_resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/coordinates/{target['id']}/disable",
            json={"disabled": True},
        )
        self.assertEqual(disable_resp.status_code, 200, disable_resp.text)
        self.assertIsNotNone(disable_resp.json()["disabled_at"])

        coords_b = self.client.get(
            f"/api/schedule/brands/{brand_b['id']}/coordinates"
        ).json()["coordinates"]
        self.assertNotIn(target["id"], [c["id"] for c in coords_b])
        b_target = next(c for c in coords_b if c["label"] == "稀缺性行銷")
        self.assertIsNone(b_target["disabled_at"])  # 品牌 A 停用不影響品牌 B 自己那一列


class CreativePersistenceTest(_ScheduleApiTestBase):
    """票 T1b done-check：`schedule_creative` 任務成功後落地
    `creative_slot`／`creative_candidate`／`creative_candidate_item`，候選的七個 `*_key`
    撐得住代理回覆，查無此字的座標退回 `*_key = NULL`／`coordinates_status = 'pending'`，
    文案照樣回傳；讀第二次不會多寫一份（同一支 `llm_task_id` 擋掉）。"""

    _LEAF_NODE_NAMES = ["單元1", "單元2"]

    def _succeed_plan_and_tree(self) -> None:
        schedule_jobs.PROVIDER = _fake(_fenced_plans([_one_plan()]))
        resp = self._post(plan_count=1)
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        schedule_jobs.PROVIDER = _fake(_tree_fenced(_one_tree_nodes()))
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

    def test_success_persists_resolved_and_unresolved_coordinates_copy_still_returned(self):
        self._succeed_plan_and_tree()
        matched = _one_creative("單元1", coordinates={
            "angle": "稀缺性行銷", "audience": None, "pain": None, "hook": None,
            "proof": None, "offer": None, "format": None,
        })
        # 「單元2」沿用 _one_creative() 預設座標「測試角度」——查無此字，35 個種子裡沒有它。
        unmatched = _one_creative("單元2")
        schedule_jobs.PROVIDER = _fake(_creative_fenced([matched, unmatched]))
        resp = self.client.post(f"/api/schedule/brands/{self.brand['id']}/creative", json={})
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        get_resp = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(get_resp.status_code, 200, get_resp.text)
        creative = get_resp.json()["creative"]
        self.assertIsNone(creative["failure"])
        self.assertEqual(len(creative["ads"]), 2)  # 查無此字的座標不讓文案跟著作廢

        slots = web.conn.execute(
            "SELECT * FROM creative_slot WHERE brand_id = %s", (self.brand["id"],),
        ).fetchall()
        candidates = web.conn.execute(
            "SELECT * FROM creative_candidate WHERE brand_id = %s", (self.brand["id"],),
        ).fetchall()
        items = web.conn.execute(
            "SELECT * FROM creative_candidate_item WHERE brand_id = %s", (self.brand["id"],),
        ).fetchall()
        self.assertEqual(len(slots), 2)      # 一個廣告節點一個 slot
        self.assertEqual(len(candidates), 2)  # 一個 slot 一個候選
        self.assertEqual(len(items), 2)       # 一個候選一個 item（v1）

        # 票 T3d：鍵是 node_key，不是名稱——「單元1」在 _one_tree_nodes() 固定是 "1.1.1"，
        # 「單元2」固定是 "1.2.1"。
        by_node = {
            next(s for s in slots if s["id"] == c["slot_id"])["node_key"]: c
            for c in candidates
        }
        self.assertEqual(by_node["1.1.1"]["angle_key"], "scarcity_marketing")
        self.assertEqual(by_node["1.1.1"]["coordinates_status"], "tagged")
        self.assertIsNone(by_node["1.1.1"]["pain_key"])

        self.assertIsNone(by_node["1.2.1"]["angle_key"])
        self.assertEqual(by_node["1.2.1"]["coordinates_status"], "pending")

        # 讀第二次不會多寫一份（llm_task_id 擋掉重複落地）。
        self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        count = web.conn.execute(
            "SELECT COUNT(*) AS n FROM creative_candidate WHERE brand_id = %s",
            (self.brand["id"],),
        ).fetchone()["n"]
        self.assertEqual(count, 2)

    def test_visual_tone_round_trips_and_bad_value_degrades_to_null_without_failing_the_batch(self):
        """票 T1b wave 3 done-check：`visual_tone` 兩個合法值之一原樣落地；不合法值（DB
        `CHECK` 只收兩個字串）退回 NULL——跟座標同一條規則，壞值不讓這批文案跟著整批作廢，
        也不能讓 INSERT 整批失敗。"""
        self._succeed_plan_and_tree()
        good = _one_creative("單元1", visual_tone="暖調生活", visual_concept="測試視覺概念")
        bad = _one_creative("單元2", visual_tone="螢光粉", visual_concept="測試視覺概念")
        schedule_jobs.PROVIDER = _fake(_creative_fenced([good, bad]))
        resp = self.client.post(f"/api/schedule/brands/{self.brand['id']}/creative", json={})
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        get_resp = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(get_resp.status_code, 200, get_resp.text)
        creative = get_resp.json()["creative"]
        self.assertIsNone(creative["failure"])  # 壞值不讓整批作廢
        self.assertEqual(len(creative["ads"]), 2)

        slots = web.conn.execute(
            "SELECT * FROM creative_slot WHERE brand_id = %s", (self.brand["id"],),
        ).fetchall()
        candidates = web.conn.execute(
            "SELECT * FROM creative_candidate WHERE brand_id = %s", (self.brand["id"],),
        ).fetchall()
        # 票 T3d：鍵是 node_key，不是名稱——同上一個測試的固定映射。
        by_node = {
            next(s for s in slots if s["id"] == c["slot_id"])["node_key"]: c
            for c in candidates
        }
        self.assertEqual(by_node["1.1.1"]["visual_tone"], "暖調生活")
        self.assertIsNone(by_node["1.2.1"]["visual_tone"])  # 不合法值退回 NULL，不炸整批 INSERT

    def test_two_same_name_leaves_under_different_parents_produce_two_slots_and_two_candidates(
        self,
    ):
        """票 T3d done-check 2（ADR 0055 §1）：舊版拿 `ad_node_name` 當鍵，兩個同名的最深層
        節點會撞成一個 slot；新版鍵是 `node_key`，各自成為獨立的 slot 跟候選——`_two_top_nodes`
        兩個分支底下的最深層節點固定都叫「單元」，node_key 各自是 "1.1.1"／"2.1.1"，這是舊版
        （`set()`／單一名稱 dict）表達不出來的狀態。"""
        schedule_jobs.PROVIDER = _fake(_fenced_plans([_one_plan()]))
        resp = self._post(plan_count=1)
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        schedule_jobs.PROVIDER = _fake(_tree_fenced(_two_top_nodes("活動A", "活動B")))
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        schedule_jobs.PROVIDER = _fake(_creative_fenced(
            [_one_creative("單元"), _one_creative("單元")]
        ))
        resp = self.client.post(f"/api/schedule/brands/{self.brand['id']}/creative", json={})
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        get_resp = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(get_resp.status_code, 200, get_resp.text)
        creative = get_resp.json()["creative"]
        self.assertIsNone(creative["failure"])
        self.assertEqual(len(creative["ads"]), 2)

        slots = web.conn.execute(
            "SELECT * FROM creative_slot WHERE brand_id = %s", (self.brand["id"],),
        ).fetchall()
        candidates = web.conn.execute(
            "SELECT * FROM creative_candidate WHERE brand_id = %s", (self.brand["id"],),
        ).fetchall()
        self.assertEqual(len(slots), 2)  # 同名的兩個節點，不是撞成一個
        self.assertEqual({s["node_key"] for s in slots}, {"1.1.1", "2.1.1"})
        self.assertEqual(len(candidates), 2)  # 每個 slot 各自一個候選，不是同一份重複算兩次
        self.assertEqual({c["slot_id"] for c in candidates}, {s["id"] for s in slots})


class SearchSourcesReadbackTest(_ScheduleApiTestBase):
    """票 08 兩條不可妥協規則之一：查詢不是排程的先決條件——這裡只驗證 gateway →
    usage_json → plan_from_task_row 這段管線本身接得起來；SDK 回應怎麼解析成
    search_sources（成功／出錯兩種形狀）在 test_llm_web_search.py 測，不在這裡重測。
    """

    def test_search_sources_are_stored_and_read_back(self):
        sources = [{"title": "雙十一活動頁", "url": "https://example.com/1111"}]
        schedule_jobs.PROVIDER = _fake(_fenced_plans([_one_plan()]), search_sources=sources)
        resp = self._post(plan_count=1)
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        body = self.client.get(f"/api/schedule/brands/{self.brand['id']}").json()
        self.assertEqual(body["plan"]["sources"], sources)

    def test_no_search_sources_still_returns_plans(self):
        # FakeProvider 預設 search_sources=None（沒開搜尋、或搜尋沒找到東西）：排程照樣成功，
        # 不會因為沒有搜尋結果就整個排程失敗。
        schedule_jobs.PROVIDER = _fake(_fenced_plans([_one_plan()]))
        resp = self._post(plan_count=1)
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        body = self.client.get(f"/api/schedule/brands/{self.brand['id']}").json()
        self.assertIsNone(body["plan"]["failure"])
        self.assertEqual(body["plan"]["sources"], [])


if __name__ == "__main__":
    unittest.main()
