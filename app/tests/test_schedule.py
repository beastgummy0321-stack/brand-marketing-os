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
from datetime import UTC, date, datetime, timedelta
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
from app.core import settings as coresettings
from app.identity import repository as identity_repo
from app.llm import providers
from app.meta import graph as meta_graph
from app.meta import repository as meta_repo
from app.schedule import binding as binding_mod
from app.schedule import creative as creative_mod
from app.schedule import jobs as schedule_jobs
from app.schedule import period as period_mod
from app.schedule import period_repository as period_repo
from app.schedule import plan as plan_mod
from app.schedule import repository as schedule_repo
from app.schedule import state as schedule_state
from app.schedule import tree as tree_mod
from app.workbench import repository as workbench_repo

from .identity_test_helpers import mint_hs256

ACTOR = "測試員"

# 有效的平台／目標——照 app/schedule/channel_catalogue.json 的內容取，測試不重寫一份
# 平行的資料（改資料檔不用跟著改這裡）。
_DATA = schedule_state._load_platform_data()
VALID_PLATFORM = next(p["id"] for p in _DATA["platforms"] if p["enabled"])
VALID_OBJECTIVE = next(o["value"] for o in _DATA["objectives"] if o["platform"] == VALID_PLATFORM)
VALID_PLATFORM_LABEL = next(p["label"] for p in _DATA["platforms"] if p["id"] == VALID_PLATFORM)
VALID_OBJECTIVE_LABEL = next(
    o["label"] for o in _DATA["objectives"]
    if o["platform"] == VALID_PLATFORM and o["value"] == VALID_OBJECTIVE
)
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
    child_names: tuple = ("組合1", "組合2"), coordinates: dict | None = None,
) -> list:
    """三層節點，扛預算的是第二層（比照 Meta：行銷活動／廣告組合／廣告，預算在第 2 層）。
    `name`：票 T3b 的重綁測試需要重新展開之後第一層節點換一個名字。`child_names`：票
    T3c 的第二層測試需要換第二層節點的名字（改名顯示未綁定、兩個同名手足）——預設值跟
    原本的 f"組合{i+1}" 一樣，既有呼叫端不用改。`coordinates`：票 05——`None`（預設）不帶
    這個欄位，跟這支 fixture 原本的形狀一模一樣（`CreativeCandidateSyncTest` 的既有測試
    靠這一點維持綠燈，見票面「§6 vs. 既有 idempotent 測試」矛盾檢查）；帶了就套用到兩個
    第三層節點（`單元1`／`單元2`）身上，同一份。"""
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
                            **({"coordinates": coordinates} if coordinates is not None else {}),
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


# -- 1a. 票 past-ads/05（ADR 0067 §1.10）：_history_text——純函數，桌面案例，不碰資料庫 ---

def _history_item(**overrides) -> dict:
    """`docs/contracts/schedule.md`「One coordinate has two ROAS values」那組實測數字
    （spend 3,570／revenue 2,737.8／coverage 75% → 保守 0.767／樂觀 1.029），座標七個
    維度只填三個，其餘留 `None` 印 `—`。"""
    item = {
        "name": "BP｜夏季｜輪播A", "first_seen_date": date(2026, 5, 3),
        "last_seen_date": date(2026, 8, 31), "currency": "TWD",
        "spend": 3570.0, "impressions": 10000, "clicks": 500, "revenue": 2737.8,
        "roas": 1.029, "roas_conservative": 0.767, "roas_coverage": 0.75, "ad_count": 1,
        "coordinates": {
            "audience": "new_parents", "pain": None, "angle": "convenience", "hook": None,
            "proof": None, "offer": "first_purchase_discount", "format": "carousel",
        },
        "owner_note": "媽媽群組轉貼最多，週末單量翻倍",
    }
    item.update(overrides)
    return item


_HISTORY_LABELS = {
    ("audience", "new_parents"): "新手爸媽", ("angle", "convenience"): "省時方便",
    ("offer", "first_purchase_discount"): "首購折扣", ("format", "carousel"): "輪播",
}


class HistoryTextTest(unittest.TestCase):
    def test_empty_items_is_empty_string(self):
        self.assertEqual(schedule_jobs._history_text([], {}, (None, "還沒有毛利率")), "")

    def test_one_item_prints_the_contract_pages_numbers_and_a_verbatim_note(self):
        text = schedule_jobs._history_text([_history_item()], _HISTORY_LABELS, (1.0, "測試打平線"))
        self.assertIn("【投放史】", text)
        self.assertIn("2026-05-03", text)
        self.assertIn("2026-08-31", text)
        self.assertIn("BP｜夏季｜輪播A", text)
        self.assertIn("0.77x", text)  # 保守 ROAS
        self.assertIn("1.03x", text)  # 樂觀 ROAS
        self.assertIn("75%", text)  # 追蹤覆蓋率
        # 座標七個維度順序固定，沒填的印 —，不是印 None 或 key 本身。
        self.assertIn("新手爸媽／—／省時方便／—／—／首購折扣／輪播", text)
        self.assertIn("媽媽群組轉貼最多，週末單量翻倍", text)  # owner_note 逐字附上
        self.assertIn("打平線 1.00x，來自測試打平線", text)
        self.assertIn(schedule_jobs.diagnosis_mod.DIRECTIONAL_ONLY_NOTE, text)
        self.assertIn(schedule_jobs._HISTORY_CLOSING_LINE, text)

    def test_pipe_in_owner_note_is_replaced_with_fullwidth_and_nothing_else_touched(self):
        item = _history_item(owner_note="這句話 | 有一條直線")
        text = schedule_jobs._history_text([item], _HISTORY_LABELS, (None, "還沒有毛利率"))
        self.assertIn("這句話 ｜ 有一條直線", text)
        self.assertNotIn("這句話 | 有一條直線", text)


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

    # -- 票 05（ADR 0069 §2）：第三層節點的 coordinates ------------------------------------

    def test_third_layer_coordinates_unknown_dropped_non_string_none(self):
        """done-check 1：未知維度丟棄、非字串值變 None、代理給的 null 原樣留 None、
        完全沒給的維度補 None——四種輸入落在同一個第三層節點上，各自的處理不能混。"""
        nodes = _one_tree_nodes()
        nodes[0]["children"][0]["children"][0]["coordinates"] = {
            "audience": "陌生・知道問題", "pain": 123, "angle": None,
            "unknown_dim": "亂寫的維度",
            # hook／proof／offer／format 完全沒給。
        }
        body, failure = tree_mod.build_tree(_tree_fenced(nodes), daily_budget=1000)
        self.assertIsNone(failure)
        leaf = body["nodes"][0]["children"][0]["children"][0]
        self.assertEqual(leaf["coordinates"], {
            "audience": "陌生・知道問題", "pain": None, "angle": None, "hook": None,
            "proof": None, "offer": None, "format": None,
        })

    def test_tree_without_coordinates_field_gets_all_seven_none_and_still_succeeds(self):
        """done-check 1：舊樹（代理沒回 `coordinates`）不是拒絕條件——第三層補七個
        `None`，第一、二層一律 `None`，`build_tree` 照樣成功。Red proof：把 tree.py 對
        缺 `coordinates` 的處理改成跟 `fields`／`share` 一樣的 `return None`（拒絕），
        這支測試先紅。"""
        body, failure = tree_mod.build_tree(_tree_fenced(_one_tree_nodes()), daily_budget=1000)
        self.assertIsNone(failure)
        top = body["nodes"][0]
        self.assertIsNone(top["coordinates"])  # 第一層
        combo = top["children"][0]
        self.assertIsNone(combo["coordinates"])  # 第二層
        leaf = combo["children"][0]
        self.assertEqual(leaf["coordinates"], dict.fromkeys(creative_mod.COORDINATE_KEYS))


# -- 2d. 票 09 settled 段第 8 點：活動樹元件不得寫死通路詞彙 ---------------------------

class CampaignTreeVocabularyGateTest(unittest.TestCase):
    """票 01 done-check 最後一條：「不要寫死」延伸到 Python 那一側。這裡只掃創意詞彙
    （切角／主題／素材檔／創意簡報／一條學習），不套用平台詞彙清單——`routes.py` 的註解
    本來就會提到 Meta／Google／TikTok 這類平台名稱解釋歷史決定（例如 46 行「campaign_plan」
    改名的由來），那從來不是這道閘門要抓的東西；但這五個創意詞彙沒有任何理由出現在後端
    程式碼的任何角落，包含註解——它們的定義只准活在素材工作檯自己的部門任務檔裡。"""

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
        # 票 smart-loop 05：還沒結算過任何一期，下一期建議是 null。
        self.assertIsNone(body["next_period_suggestion"])
        # 方案數上下限來自規則卡 schedule_plan_count，預設 1～5（票 08）。
        self.assertEqual(body["plan_count_min"], 1)
        self.assertEqual(body["plan_count_max"], 5)
        # 平台／目標來自資料檔，不是外殼寫死——Meta 開放，Google／TikTok 列出但停用。
        platform_ids = {p["id"]: p["enabled"] for p in body["platforms"]}
        self.assertEqual(platform_ids, {"meta": True, "google": False, "tiktok": False})
        self.assertTrue(all(o["source_url"] for o in body["objectives"]))

    # -- 票 plan-quality/03：品牌檔案缺口要在排程表單露出來 --------------------------

    def test_knowledge_gaps_lists_every_empty_category_in_order(self):
        """red proof（票面 done-check 1a）：`setUp` 的測試品牌沒有事實／人物誌／宣稱，
        回 `[]` 會讓這條紅。"""
        resp = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["knowledge_gaps"], ["品牌事實", "典型客人", "宣稱"])

    def test_knowledge_gaps_drops_category_once_a_confirmed_fact_exists(self):
        """red proof（票面 done-check 1b）：不分狀態就數 `brand_fact`，或永遠回三個名字
        不分現況，都會讓這條紅。"""
        bi_repo.create_brand_fact(
            web.conn, self.brand["id"], actor=ACTOR, fact_type="positioning", label="定位",
            value="平價日常茶飲", status="confirmed", confirmed_by=ACTOR,
        )
        web.conn.commit()
        resp = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["knowledge_gaps"], ["典型客人", "宣稱"])

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

    def test_tree_success_submits_one_brief_per_leaf_and_stays_queued(self):
        """票 05（ADR 0068 §2）：`schedule_tree()` 成功後，每個最深層節點各提交一份工作檯
        工單，讀出來是 `status='queued'`。

        契約：這個測試模組（`conftest.py` 每個測試模組自己一份 schema／`background.app()`）
        故意不呼叫 `workbench` 的 `register_tasks()`——`background.workbench_generate`
        在這裡的 `background.app()` 上沒有註冊，worker 真的撿到那個 job 時是 procrastinate
        自己的 `TaskNotFound`（在呼叫任務本體之前發生），本體第一行
        `mark_brief_status(..., "running")` 完全沒機會跑，`workbench_brief.status` 因此停在
        `submit_brief()` 寫入當下的 `'queued'`——一次 worker pass（展開活動樹那一次）就看得到
        這個狀態，不必刻意分兩次呼叫，也不會真的打到任何供應商（不管是 FakeProvider 還是
        真的 `AnthropicProvider`）。真正跑完文案生成、驗證輸出形狀是
        test_workbench.py／test_workbench_api.py 的事，這裡不重測一次。"""
        schedule_jobs.PROVIDER = _fake(_fenced_plans([_one_plan()]))
        resp = self._post(plan_count=1)
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        # 票 05（ADR 0069 §3）：兩個最深層節點都帶座標——angle／format 兩個維度沒填，
        # 交棒時要被濾掉，不是整批落成 None。
        leaf_coordinates = {
            "audience": "陌生・知道問題", "pain": "太麻煩", "angle": None, "hook": None,
            "proof": None, "offer": None, "format": None,
        }
        schedule_jobs.PROVIDER = _fake(
            _tree_fenced(_one_tree_nodes(coordinates=leaf_coordinates))
        )
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        tree_row = schedule_state._latest_task_row(
            web.conn, self.brand["id"], schedule_state.TREE_TASK_TYPE
        )
        self.assertEqual(tree_row["status"], "succeeded")

        rows = web.conn.execute(
            "SELECT source_ref, status, coordinates_snapshot_json FROM workbench_brief"
            " WHERE brand_id = %s ORDER BY created_at", (self.brand["id"],),
        ).fetchall()
        # `_one_tree_nodes()`（預設引數）固定兩個最深層節點：「單元1」node_key "1.1.1"，
        # 「單元2」node_key "1.2.1"（跟既有其他測試同一個固定映射）。
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["status"] == "queued" for r in rows))
        self.assertEqual({r["source_ref"]["node_key"] for r in rows}, {"1.1.1", "1.2.1"})
        self.assertTrue(all(
            r["source_ref"]["source_tree_task_id"] == tree_row["id"] for r in rows
        ))
        # done-check 3：每份工單的 coordinates_snapshot_json 等於它那個節點的非空座標——
        # 空維度（angle／hook／proof／offer／format）被濾掉，不是整批落成 None。
        # Red proof：把 jobs.py 那行改回 `"coordinates": None`，這裡先紅。
        self.assertTrue(all(
            r["coordinates_snapshot_json"] == {"audience": "陌生・知道問題", "pain": "太麻煩"}
            for r in rows
        ))

        get_resp = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(get_resp.status_code, 200, get_resp.text)
        briefs = get_resp.json()["briefs"]
        self.assertEqual({b["node_key"] for b in briefs}, {"1.1.1", "1.2.1"})
        self.assertTrue(all(b["status"] == "queued" for b in briefs))
        self.assertTrue(all(b["copy"] is None and b["image_prompts"] is None for b in briefs))


class TreeDispatchRequestTest(_ScheduleApiTestBase):
    """票 F01-T02-I04（F02-I02 更新）：`schedule_tree()` 展開成功後交給工作檯的
    `request_json`，每個最深層節點自己的 `copy_length`（沒填就落成 `"short"`）跟這一期的
    `promotion_note` 都要原樣帶到。F02-I02：`parts` 現在從 `required_outputs.keys()`
    衍生（ARCHITECTURE.md §5.4）——一個節點一次交棒 copy 跟 image_prompt 兩個 part，不再
    只有 copy，`required_outputs_json` 也要能看到 `{"copy": 1, "image_prompt": 1}`。"""

    def test_dispatched_brief_request_carries_node_copy_length_and_promotion_note(self):
        schedule_jobs.PROVIDER = _fake(_fenced_plans([_one_plan()]))
        resp = self._post(plan_count=1, promotion_note="滿799免運\n新品九折")
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        nodes = _one_tree_nodes()
        nodes[0]["children"][0]["children"][0]["copy_length"] = "long"
        schedule_jobs.PROVIDER = _fake(_tree_fenced(nodes))
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        rows = web.conn.execute(
            "SELECT source_ref, request_json, required_outputs_json FROM workbench_brief"
            " WHERE brand_id = %s", (self.brand["id"],),
        ).fetchall()
        self.assertEqual(len(rows), 2)
        by_node_key = {r["source_ref"]["node_key"]: r["request_json"] for r in rows}
        required_by_node_key = {
            r["source_ref"]["node_key"]: r["required_outputs_json"] for r in rows
        }
        self.assertEqual(by_node_key.keys(), {"1.1.1", "1.2.1"})
        self.assertEqual(by_node_key["1.1.1"]["copy_length"], "long")
        self.assertEqual(by_node_key["1.2.1"]["copy_length"], "short")
        for request in by_node_key.values():
            self.assertEqual(set(request["parts"]), {"copy", "image_prompt"})
            self.assertEqual(request["promotion_note"], "滿799免運\n新品九折")
        for required_outputs in required_by_node_key.values():
            self.assertEqual(required_outputs, {"copy": 1, "image_prompt": 1})

        pack_row = web.conn.execute(
            "SELECT context_json FROM workbench_pack WHERE brand_id = %s", (self.brand["id"],),
        ).fetchone()
        # F02-I19：`context` 是 §5.4 契約欄位，`schedule_tree()` 過去只填 `product_ids`，
        # 平台／目標的標籤（不是 id／value）要一起帶到，否則 §5.13 的「平台」列跟
        # `PackDetail.meta.platform`／`goal` 永遠是「—」／null。
        self.assertEqual(pack_row["context_json"]["platform"], VALID_PLATFORM_LABEL)
        self.assertEqual(pack_row["context_json"]["goal"], VALID_OBJECTIVE_LABEL)


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

    # -- 沒有綁定帳戶 -> 擋在節點迴圈之前，原文回傳，不叫 Meta --------------------------

    def test_no_bound_account_returns_the_guard_message_and_calls_nothing(self):
        """票 workbench-2/03，drill 2（2026-09-09）：沒綁帳戶就配對，舊行為是每個節點都
        跑完名稱比對、各自讀回「在 Meta 上找不到」——零次 Graph 呼叫也照樣顯示成名稱問題。
        這裡驗證新的擋法：`bind_tree` 在進節點迴圈之前就回傳 `NO_ACCOUNT_BOUND` 原文，不寫
        `channel_entity_map`、不呼叫 `list_campaigns`。"""
        meta_repo.unbind(web.conn, coredb.DEV_ORG_ID, self.brand["id"], self.account_id)
        web.conn.commit()
        self._succeed_plan_and_tree()

        calls: list = []

        def fake_list_campaigns(_token: str, account_id: str) -> list[dict]:
            calls.append(account_id)
            return []

        with mock.patch.object(meta_graph, "list_campaigns", fake_list_campaigns):
            resp = self._bind()

        self.assertEqual(resp.status_code, 200, resp.text)
        tree = resp.json()["tree"]
        self.assertEqual(tree["bind_failure"], binding_mod.NO_ACCOUNT_BOUND)
        self.assertEqual(self._channel_entity_map_rows(), [])
        self.assertEqual(calls, [])

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

    def test_two_top_level_siblings_rebind_independently_after_re_expansion(self):
        """票 T3b（ADR 0055 §1）：舊版拿節點名稱當 dict key，兩個節點會撞成同一格；新版
        鍵是 node_key，各自綁到各自的活動——這是舊版表達不出來的狀態。

        票 10（ADR 0064 §3）修正這支測試原本的手法：`bind_tree()` 以前問「畫面現在顯示
        成綁定了嗎」，這支測試利用「已顯示綁定的節點不會重新查詢」讓兩個**同名**節點各自
        對到 Meta 上不同時間點才看得到的活動；現在 `bind_tree()` 問的是「這一棵樹自己有
        沒有這個節點的列」，同一棵樹裡兩個同名節點會問出一模一樣的 Meta 查詢結果，兩者
        無法用名稱互相分辨——這正是 ADR 0064 關掉的洞的另一面：不能再假裝「兩個同名位置
        查得出兩個不同答案」。這裡改用兩個**不同名**的頂層節點，改用它們驗證同一件更基本
        的事：`channel_entity_map` 用 `node_key` 分格，兩個位置的列各自獨立、互不覆寫，
        重新展開後舊位置也要拿到屬於這一棵新樹自己的列（不是繼續沿用舊樹的列）。"""
        self._succeed_plan_and_tree()  # 第一次展開：第一層只有一個「活動一」（node_key "1"）
        # 平台上這一輪還沒有任何廣告組合（票 T3c：第二層配不到，不影響這裡要看的第一層
        # 結果，`_platform_ad_sets({})` 對任何活動都回空清單）。
        with self._platform_campaigns({self.account_id: [("camp-1", "活動一")]}), \
                self._platform_ad_sets({}):
            resp = self._bind()
        self.assertEqual(resp.json()["tree"]["nodes"][0]["bound_external_id"], "camp-1")
        first_tree_id = resp.json()["tree"]["task_id"]

        # 重新展開：這次代理回了兩個第一層節點——"1" 名字沒變（活動一），"2" 是新位置
        # （活動二）。ADR 0064 之後，這一棵新樹自己還沒有任何一列，兩個節點都要重新比對。
        schedule_jobs.PROVIDER = _fake(_tree_fenced(_two_top_nodes("活動一", "活動二")))
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        # 平台上「活動一」還是原來那個 camp-1（使用者沒動它），「活動二」是照新樹手動建的
        # camp-2；底下各自也建好了一個廣告組合「組合」（票 T3c：第二層也要各自綁到各自
        # 活動內部）。
        with self._platform_campaigns(
            {self.account_id: [("camp-1", "活動一"), ("camp-2", "活動二")]}
        ), self._platform_ad_sets(
            {"camp-1": [("as-1x", "組合")], "camp-2": [("as-2x", "組合")]}
        ), self._platform_ads(
            {"as-1x": [("ad-1x", "單元")], "as-2x": [("ad-2x", "單元")]}
        ):
            resp = self._bind()
        self.assertEqual(resp.status_code, 200, resp.text)
        tree = resp.json()["tree"]
        self.assertIsNone(tree["bind_failure"])
        second_tree_id = tree["task_id"]
        self.assertNotEqual(first_tree_id, second_tree_id)
        self.assertEqual(tree["nodes"][0]["bound_external_id"], "camp-1")
        self.assertEqual(tree["nodes"][1]["bound_external_id"], "camp-2")  # 各自綁到不同活動
        self.assertEqual(tree["nodes"][0]["children"][0]["bound_external_id"], "as-1x")
        self.assertEqual(tree["nodes"][1]["children"][0]["bound_external_id"], "as-2x")
        # 票 T5：第三層現在也綁——同一支測試守的「兩個位置各自綁到不同活動」延伸一層。
        self.assertEqual(
            tree["nodes"][0]["children"][0]["children"][0]["bound_external_id"], "ad-1x"
        )
        self.assertEqual(
            tree["nodes"][1]["children"][0]["children"][0]["bound_external_id"], "ad-2x"
        )
        # 票 10（ADR 0064 §1）：node_key "1" 現在有兩列——tree1 綁的那一列，跟這次重新
        # 展開後、這一棵新樹自己重新查詢寫下的那一列（外部 id 剛好還是同一個 camp-1，
        # 但物理上是不同的兩列）；node_key "2" 是全新的位置，只有一列。兩個 node_key
        # 各自的列互不干擾，正是這支測試原本要證的事。
        self.assertEqual(
            sorted(
                (r["node_key"], r["external_id"]) for r in self._channel_entity_map_rows()
            ),
            sorted([
                ("1", "camp-1"), ("1", "camp-1"),
                ("1.1", "as-1x"), ("1.1.1", "ad-1x"),
                ("2", "camp-2"), ("2.1", "as-2x"), ("2.1.1", "ad-2x"),
            ]),
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

    # -- 資料正確性：改名後第二次 bind 是新樹自己的一列，不是撞唯一鍵、也不是覆寫 --------

    def test_second_bind_after_rename_inserts_a_new_row_for_the_new_tree(self):
        """票 10（ADR 0064 §1）：這支測試原本叫 `..._updates_the_row_not_a_unique_
        violation`，證的是「改名後重綁是覆寫同一列」——那正是 ADR 0064 要關掉的洞（換一棵
        樹綁同一個位置，蓋掉上一棵樹的列，上一期的廣告從資料庫裡永久消失）。改名逼出的
        重新查詢現在寫進**一列新的**，第一棵樹自己的那一列（`external_id`／
        `source_tree_task_id` 都是）原封不動留著——這才是這支測試現在該證的事。"""
        self._succeed_plan_and_tree()
        # 這支測試守的是第一層 upsert 鍵的行為，第二層有沒有配到不影響——兩次都給空的
        # 廣告組合清單（`_platform_ad_sets({})`），兩層各自的失敗互不牽連。
        with self._platform_campaigns({self.account_id: [("camp-1", "活動一")]}), \
                self._platform_ad_sets({}):
            resp = self._bind()
        self.assertEqual(resp.json()["tree"]["nodes"][0]["bound_external_id"], "camp-1")
        first_tree_id = resp.json()["tree"]["task_id"]

        schedule_jobs.PROVIDER = _fake(_tree_fenced(_one_tree_nodes(name="活動一（新版）")))
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        # 第二次 bind：平台上是新名字的活動——這一棵新樹自己還沒有任何一列，所以照樣
        # 重新查詢、寫下屬於自己的一列，不是撞 `(org_id, brand_id, channel_id, node_key,
        # source_tree_task_id)` 唯一鍵報錯（兩邊的 `source_tree_task_id` 本來就不同，
        # 不會撞）。平台上一樣沒有廣告組合，所以第二層兩個子節點都配不到——`bind_failure`
        # 因此非 null，這是第二層自己的失敗，不影響這支測試要證的事。
        with self._platform_campaigns({self.account_id: [("camp-2", "活動一（新版）")]}), \
                self._platform_ad_sets({}):
            resp = self._bind()
        self.assertEqual(resp.status_code, 200, resp.text)
        tree = resp.json()["tree"]
        second_tree_id = tree["task_id"]
        self.assertNotEqual(first_tree_id, second_tree_id)
        self.assertIn("「組合1」在 Meta 上找不到", tree["bind_failure"])
        self.assertEqual(tree["nodes"][0]["bound_external_id"], "camp-2")
        self.assertEqual(  # 新樹自己一列，舊樹的列還在——兩列，不是覆寫成一列
            sorted(
                (r["node_key"], r["external_id"]) for r in self._channel_entity_map_rows()
            ),
            [("1", "camp-1"), ("1", "camp-2")],
        )
        first_tree_row = web.conn.execute(
            "SELECT external_id, source_tree_task_id FROM channel_entity_map"
            " WHERE org_id = %s AND brand_id = %s AND node_key = '1' AND external_id = 'camp-1'",
            (coredb.DEV_ORG_ID, self.brand["id"]),
        ).fetchone()
        self.assertEqual(  # done-check 3：第一棵樹的列原封不動——external_id 跟
                           # source_tree_task_id 都還是它自己的
            dict(first_tree_row),
            {"external_id": "camp-1", "source_tree_task_id": first_tree_id},
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
        變成 `ON CONFLICT DO UPDATE`（票 10，ADR 0064 §4：改綁到新樹時 `source_tree_task_id`
        要跟著換），不是應用層自己記得寫過。"""
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
        # ticket done-check 3（money）：第二棵樹綁完之後，channel_entity_map 對每個
        # node_key 都有兩棵樹各自的一列，但 period_node_memberships_for_brand() 的 JOIN
        # 多帶了 source_tree_task_id 才不會 fan-out——回傳列數要跟 membership 本身的列數
        # 一樣多，不是列數乘上樹的數量。
        memberships = schedule_repo.period_node_memberships_for_brand(
            web.conn, coredb.DEV_ORG_ID, self.brand["id"]
        )
        self.assertEqual(len(memberships), len(rows))

    # -- 票 01（docs/issues/plan-quality/）：出方案的 prompt 要看得到這個帳戶的成效 --------

    def test_account_performance_is_the_last_prompt_section(self):
        """red proof（票面 done-check 1）：`schedule_plan()` prompt tuple 拿掉
        `performance_text` 那個元素就會紅——`assertGreater` 的兩個 index 斷言拿不到值。"""
        meta_repo.upsert_entity_spend(web.conn, coredb.DEV_ORG_ID, self.account_id, [
            {"level": "ad", "entity_id": "ad-1", "entity_name": "測試廣告A",
             "campaign_id": "camp-1", "adset_id": "as-1", "ad_id": "ad-1",
             "spend_date": self.today, "spend": 100.0, "impressions": 100, "clicks": 10,
             "roas": 3.0, "actions": None, "action_values": None,
             "attribution_window": "7d_click,1d_view"},
            {"level": "ad", "entity_id": "ad-1", "entity_name": "測試廣告A",
             "campaign_id": "camp-1", "adset_id": "as-1", "ad_id": "ad-1",
             "spend_date": self.today + timedelta(days=1), "spend": 100.0,
             "impressions": 100, "clicks": 10, "roas": None, "actions": None,
             "action_values": None, "attribution_window": "7d_click,1d_view"},
        ])
        web.conn.commit()
        # 品牌事實非空，`brand_context` 才會印出 `【事實】品牌事實` 那一段，才有東西可以
        # 拿來跟 `【這個帳戶目前的成效】` 比 index 先後。
        bi_repo.create_brand_fact(
            web.conn, self.brand["id"], actor=ACTOR, fact_type="positioning", label="定位",
            value="平價日常茶飲", status="confirmed", confirmed_by=ACTOR,
        )
        web.conn.commit()

        fake = _fake(_fenced_plans([_one_plan()]))
        schedule_jobs.PROVIDER = fake
        resp = self._post(plan_count=1)
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        self.assertEqual(len(fake.calls), 1)
        prompt_text = fake.calls[0]["messages"][0]["content"]
        self.assertIn("【這個帳戶目前的成效】", prompt_text)
        self.assertIn("測試廣告A", prompt_text)
        self.assertIn("保守 ROAS 1.50x", prompt_text)
        self.assertIn("樂觀 ROAS 3.00x", prompt_text)
        self.assertIn("50%", prompt_text)
        self.assertIn("未設定轉換目標", prompt_text)  # 測試品牌沒設定 conversion_goal
        performance_index = prompt_text.index("【這個帳戶目前的成效】")
        self.assertGreater(performance_index, prompt_text.index("SCHEDULE-PLAN-TASK-V1"))
        self.assertGreater(performance_index, prompt_text.index("【事實】品牌事實"))

    def test_no_spend_in_window_shows_the_literal_inclusive_window(self):
        """done-check 2：沒有任何花費列 → 印「還沒有任何 Meta 花費資料」＋這一期真正的
        起訖日（含首尾，不是 `_current_month_window()` 半開區間那個下月初）。"""
        today = coresettings.today_for_org(web.conn, org_id=coredb.DEV_ORG_ID)
        month_start = today.replace(day=1)
        month_end = (month_start + timedelta(days=32)).replace(day=1)
        inclusive_end = month_end - timedelta(days=1)

        fake = _fake(_fenced_plans([_one_plan()]))
        schedule_jobs.PROVIDER = fake
        resp = self._post(plan_count=1)
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        prompt_text = fake.calls[0]["messages"][0]["content"]
        self.assertIn("還沒有任何 Meta 花費資料", prompt_text)
        self.assertIn(
            f"（{month_start.isoformat()} ~ {inclusive_end.isoformat()}）", prompt_text
        )
        self.assertNotIn(month_end.isoformat(), prompt_text)  # 半開區間的下月初不准漏出來

    # -- 票 smart-loop 03：plan／tree prompt 帶上一期的判決 -------------------------------

    def _write_scored_period(self, *, start: date, end: date, daily_budget: float,
                              settled_spend: float, settled_revenue: float,
                              node_rows: list[dict]) -> str:
        """直接寫表造一個已結算檔期＋它的節點記分列——不走真的「規劃→展開→綁定→結算」
        整條鏈（那條鏈已經在 test_schedule_period.py／本檔別的測試測過），這裡只測
        `jobs._last_period_text()` 讀出來、印出來的樣子。"""
        org_id, brand_id = coredb.DEV_ORG_ID, self.brand["id"]
        period_id = period_repo.upsert_draft_period(
            web.conn, org_id, brand_id, name=f"上一期 {start.isoformat()}",
            start_date=start, end_date=end, daily_budget=daily_budget, currency="TWD",
        )
        period_repo.write_settlement(
            web.conn, org_id=org_id, period_id=period_id, spend=settled_spend,
            revenue=settled_revenue, settled_at=datetime.now(UTC), force_early=False,
        )
        period_repo.replace_period_node_results(web.conn, org_id, brand_id, period_id, node_rows)
        web.conn.commit()
        return period_id

    def test_last_period_section_is_the_last_element_in_both_prompts(self):
        """done-check 1／3：red proof——拿掉 jobs.py 兩個 prompt tuple 裡的
        `last_period_text` 元素，兩組 index 斷言（各自比對 `【上一期】` 跟前一段的先後）就會
        變紅；`_coordinate_cell` 若印 key 不印 label，`陌生・不知有問題` 那個 assertIn 會紅；
        `實花佔比` 若跨深度合計而不是各自的深度，`100%` 那個子字串斷言會紅（done-check 3）。
        `self._post()` 用預設 `start_date`／`end_date`（2026-09-10 ~ 2026-09-24）另開一個
        `planning` 草稿檔期，created_at 比這裡先造的已結算檔期新——藉此順便關住矛盾檢查段
        「check 1 vs. check 2」點名的那個陷阱：拿 `get_latest_period()` 配 `status=='settled'`
        判斷的錯誤實作，會被這個更新的草稿檔期擋下，讀不到已結算的那個。"""
        start, end = date(2026, 8, 1), date(2026, 8, 14)
        channel_id = schedule_repo.ensure_meta_channel(web.conn, coredb.DEV_ORG_ID)
        node_rows = [
            {
                "source_tree_task_id": "tsk_fake_last_period", "channel_id": channel_id,
                "node_key": "1.1", "depth": 2, "node_name": "上一期組合節點",
                "external_id": "as-scored", "approved_share": 0.55,
                "approved_daily_amount": 1100.0, "actual_spend": 600.0,
                "revenue_tracked": 900.0, "roas_conservative": 1.5, "roas_optimistic": 3.0,
                "roas_coverage": 0.5, "breakeven_roas": 1.0, "breakeven_source": "測試打平線",
                "verdict": "win", "coordinates_json": None, "settled_at": datetime.now(UTC),
            },
            {
                "source_tree_task_id": "tsk_fake_last_period", "channel_id": channel_id,
                "node_key": "1.1.1", "depth": 3, "node_name": "上一期廣告節點",
                "external_id": "ad-scored", "approved_share": None,
                "approved_daily_amount": None, "actual_spend": 500.0,
                "revenue_tracked": 150.0, "roas_conservative": 0.3, "roas_optimistic": 0.6,
                "roas_coverage": 1.0, "breakeven_roas": 1.0, "breakeven_source": "測試打平線",
                "verdict": "lose",
                # 只填 audience 一個維度：拿現有 brand_coordinate 種子的一個 key（見
                # `app/schedule/repository.py` `_SEED_COORDINATES["audience"][0]`），其餘六個
                # 留 None——順便驗證「沒填的維度印 —，不是印 None／key」這條沒有明講的規則。
                "coordinates_json": {
                    "audience_key": "cold_unaware", "pain_key": None, "angle_key": None,
                    "hook_key": None, "proof_key": None, "offer_key": None, "format_key": None,
                },
                "settled_at": datetime.now(UTC),
            },
        ]
        self._write_scored_period(
            start=start, end=end, daily_budget=2000.0, settled_spend=1068.0,
            settled_revenue=0.0, node_rows=node_rows,
        )

        fake = _fake(_fenced_plans([_one_plan()]))
        schedule_jobs.PROVIDER = fake
        resp = self._post(plan_count=1)
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        self.assertEqual(len(fake.calls), 1)
        plan_prompt = fake.calls[0]["messages"][0]["content"]
        self.assertIn("【上一期】", plan_prompt)
        self.assertIn(f"{start.isoformat()} ~ {end.isoformat()}", plan_prompt)
        self.assertIn("上一期組合節點", plan_prompt)
        self.assertIn("賺", plan_prompt)
        self.assertIn("賠", plan_prompt)
        self.assertIn("55%", plan_prompt)
        self.assertIn("1.50x", plan_prompt)
        self.assertIn("陌生・不知有問題", plan_prompt)  # label，不是 key `cold_unaware`
        self.assertNotIn("cold_unaware", plan_prompt)
        # done-check 3：兩列各自是自己那個深度唯一的一列，實花佔比各自 100%，不是合併成 50%
        # （只在 `【上一期】` 這一段裡找 `50%`——`50%` 這個子字串本身在方法論文字裡另有
        # 不相干的出現，例如 `ads-commerce.md` 的毛利率例子，不能拿整份 prompt 當範圍）。
        last_period_text = plan_prompt[plan_prompt.index("【上一期】"):]
        self.assertIn("| 55% | 600 | 100% | 1.50x | 3.00x | 賺 |", last_period_text)
        self.assertNotIn("50%", last_period_text)
        self.assertGreater(
            plan_prompt.index("【上一期】"), plan_prompt.index("【這個帳戶目前的成效】")
        )

        tree_fake = _fake(_tree_fenced(_one_tree_nodes()))
        schedule_jobs.PROVIDER = tree_fake
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        self.assertEqual(len(tree_fake.calls), 1)
        tree_prompt = tree_fake.calls[0]["messages"][0]["content"]
        self.assertIn("【上一期】", tree_prompt)
        self.assertIn("上一期組合節點", tree_prompt)
        self.assertGreater(
            tree_prompt.index("【上一期】"), tree_prompt.index("CAMPAIGN-TREE-TASK-V1")
        )

    def test_no_last_period_section_when_nothing_settled_or_no_scored_nodes(self):
        """done-check 2：兩個子案都要「兩個 prompt 都沒有」。"""
        def _assert_no_section():
            fake = _fake(_fenced_plans([_one_plan()]))
            schedule_jobs.PROVIDER = fake
            resp = self._post(plan_count=1)
            self.assertEqual(resp.status_code, 200, resp.text)
            self._run_worker()
            self.assertNotIn("【上一期】", fake.calls[0]["messages"][0]["content"])

            tree_fake = _fake(_tree_fenced(_one_tree_nodes()))
            schedule_jobs.PROVIDER = tree_fake
            resp = self.client.post(
                f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
            )
            self.assertEqual(resp.status_code, 200, resp.text)
            self._run_worker()
            self.assertNotIn("【上一期】", tree_fake.calls[0]["messages"][0]["content"])

        _assert_no_section()  # 子案一：這個品牌從沒結算過任何檔期

        self._write_scored_period(
            start=date(2026, 7, 1), end=date(2026, 7, 14), daily_budget=2000.0,
            settled_spend=1000.0, settled_revenue=500.0, node_rows=[],
        )
        _assert_no_section()  # 子案二：結算過，但那個檔期零個節點被記分

    # -- 票 04：winners keep their names ---------------------------------------------------

    def test_continuity_section_lists_keep_and_replace_blocks_separately(self):
        """done-check 1／3：tree prompt 的最後一段是【延續】，緊接在【上一期】後面——
        `win`（A）／`unclear`（C）進沿用區，`lose`（B）進換掉區，兩區不能混。不只斷言
        子字串出現，要斷言在正確的標題底下（ticket「Cheapest wrong implementation」(c)：
        把 `lose` 節點塞進沿用區，只斷言子字串出現的測試逮不到）。
        Red proof：把 `schedule_tree()` 的 tree tuple裡 `continuity_text` 拿掉 →
        `【延續】` 那個 assertIn 先紅（本檔紅過一次，見票面 done-check 1）。

        Amendment 2026-09-08（第一輪驗收撞牆）：depth 1（活動）從沒被記分，`node_rows`
        裡沒有它——第一層的沿用名字要從**這一棵樹自己**的綁定列（K，`node_key` 不含
        `.`，同一個 `source_tree_task_id`）找。Red proof：拿掉 `_continuity_text()` 的
        `campaign_names` 引數（改傳 `[]`）→ `- 活動：K` 那個 assertIn 先紅。"""
        channel_id = schedule_repo.ensure_meta_channel(web.conn, coredb.DEV_ORG_ID)
        node_rows = [
            {
                "source_tree_task_id": "tsk_continuity_seed", "channel_id": channel_id,
                "node_key": "1.1", "depth": 2, "node_name": "A",
                "external_id": "as-a", "approved_share": 0.5, "approved_daily_amount": 500.0,
                "actual_spend": 500.0, "revenue_tracked": 1000.0, "roas_conservative": 1.5,
                "roas_optimistic": 2.0, "roas_coverage": 1.0, "breakeven_roas": 1.0,
                "breakeven_source": "測試打平線", "verdict": "win", "coordinates_json": None,
                "settled_at": datetime.now(UTC),
            },
            {
                "source_tree_task_id": "tsk_continuity_seed", "channel_id": channel_id,
                "node_key": "1.2", "depth": 2, "node_name": "C",
                "external_id": "as-c", "approved_share": 0.5, "approved_daily_amount": 500.0,
                "actual_spend": 10.0, "revenue_tracked": 0.0, "roas_conservative": 0.0,
                "roas_optimistic": 0.0, "roas_coverage": 0.02, "breakeven_roas": 1.0,
                "breakeven_source": "測試打平線", "verdict": "unclear", "coordinates_json": None,
                "settled_at": datetime.now(UTC),
            },
            {
                "source_tree_task_id": "tsk_continuity_seed", "channel_id": channel_id,
                "node_key": "1.1.1", "depth": 3, "node_name": "B",
                "external_id": "ad-b", "approved_share": None, "approved_daily_amount": None,
                "actual_spend": 400.0, "revenue_tracked": 100.0, "roas_conservative": 0.2,
                "roas_optimistic": 0.3, "roas_coverage": 1.0, "breakeven_roas": 1.0,
                "breakeven_source": "測試打平線", "verdict": "lose", "coordinates_json": None,
                "settled_at": datetime.now(UTC),
            },
        ]
        self._write_scored_period(
            start=date(2026, 7, 1), end=date(2026, 7, 14), daily_budget=2000.0,
            settled_spend=910.0, settled_revenue=1100.0, node_rows=node_rows,
        )
        schedule_repo.upsert_binding(
            web.conn, org_id=coredb.DEV_ORG_ID, brand_id=self.brand["id"],
            channel_id=channel_id, node_key="1", node_name_at_bind="K",
            external_id="camp-k", external_status=None,
            source_tree_task_id="tsk_continuity_seed",
        )
        web.conn.commit()

        schedule_jobs.PROVIDER = _fake(_fenced_plans([_one_plan()]))
        resp = self._post(plan_count=1)
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        tree_fake = _fake(_tree_fenced(_one_tree_nodes()))
        schedule_jobs.PROVIDER = tree_fake
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        tree_prompt = tree_fake.calls[0]["messages"][0]["content"]
        self.assertIn("【延續】", tree_prompt)
        self.assertGreater(tree_prompt.index("【延續】"), tree_prompt.index("【上一期】"))

        continuity_text = tree_prompt[tree_prompt.index("【延續】"):]
        keep_idx = continuity_text.index(schedule_jobs._CONTINUITY_KEEP_HEADER)
        replace_idx = continuity_text.index(schedule_jobs._CONTINUITY_REPLACE_HEADER)
        self.assertLess(keep_idx, replace_idx)
        keep_section = continuity_text[keep_idx:replace_idx]
        replace_section = continuity_text[replace_idx:]
        self.assertIn("- 活動：K", keep_section)
        self.assertIn("- 組合：A", keep_section)
        self.assertIn("- 組合：C", keep_section)
        self.assertNotIn("- 廣告：B", keep_section)
        self.assertIn("- 廣告：B", replace_section)
        self.assertNotIn("- 活動：K", replace_section)
        self.assertNotIn("- 組合：A", replace_section)
        self.assertNotIn("- 組合：C", replace_section)

        # 票 05（ADR 0069 §1）：座標詞彙表是這份 prompt 的最後一段，緊接在【延續】之後
        # （ADR 0068 §6「vocabulary last」同一條規則）。Red proof：把 `schedule_tree()`
        # 的 prompt tuple 裡 `coordinate_vocabulary_text` 拿掉，這個 assertIn 先紅。
        self.assertIn("## 座標詞彙表", tree_prompt)
        self.assertGreater(tree_prompt.index("## 座標詞彙表"), tree_prompt.index("【延續】"))
        # 新版 `_CONTINUITY_CLOSING_LINE`——red proof：把它改回舊文字（只有 name 不能動），
        # 這個 assertIn 先紅。
        self.assertIn("name 與 coordinates 都不能動", tree_prompt)

    def test_continuity_overlay_matches_by_depth_and_name_not_position(self):
        """done-check 2：overlay 只認 `(depth, name)`，不認 `node_key`——沿用節點在新樹裡
        的 node_key（"1.1"）跟上一期記分列的 node_key（刻意設成不同的 "9.9"）不一樣，照樣
        要接上（矛盾檢查 check 2：延續認名字，綁定才認位置）。名字多一個尾端空白、或名字
        對但層不對，都要是 None（「Cheapest wrong implementation」(a)：只認名字不認深度，
        會被這裡深度 3 的 "A" 逮到）。"""
        channel_id = schedule_repo.ensure_meta_channel(web.conn, coredb.DEV_ORG_ID)
        node_rows = [{
            "source_tree_task_id": "tsk_continuity_overlay", "channel_id": channel_id,
            "node_key": "9.9", "depth": 2, "node_name": "A",
            "external_id": "as-a", "approved_share": 0.5, "approved_daily_amount": 500.0,
            "actual_spend": 500.0, "revenue_tracked": 1000.0, "roas_conservative": 1.5,
            "roas_optimistic": 2.0, "roas_coverage": 1.0, "breakeven_roas": 1.0,
            "breakeven_source": "測試打平線", "verdict": "win", "coordinates_json": None,
            "settled_at": datetime.now(UTC),
        }]
        self._write_scored_period(
            start=date(2026, 7, 1), end=date(2026, 7, 14), daily_budget=2000.0,
            settled_spend=500.0, settled_revenue=1000.0, node_rows=node_rows,
        )

        schedule_jobs.PROVIDER = _fake(_fenced_plans([_one_plan()]))
        resp = self._post(plan_count=1)
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        custom_nodes = [{
            "name": "根", "fields": [], "share": None, "warnings": [],
            "children": [
                {"name": "A", "fields": [], "share": 0.5, "warnings": [],
                 "children": [{"name": "Z1", "fields": [], "share": None, "warnings": [],
                               "children": []}]},
                {"name": "A ", "fields": [], "share": 0.5, "warnings": [],
                 "children": [{"name": "A", "fields": [], "share": None, "warnings": [],
                               "children": []}]},
            ],
        }]
        schedule_jobs.PROVIDER = _fake(_tree_fenced(custom_nodes))
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        get_resp = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(get_resp.status_code, 200, get_resp.text)
        root = get_resp.json()["tree"]["nodes"][0]
        self.assertIsNone(root["continued_from_node_key"])  # 第一層一律 None

        node_a, node_a_space = root["children"]
        self.assertEqual(node_a["name"], "A")
        self.assertEqual(node_a["continued_from_node_key"], "9.9")  # 上一期那一列的 node_key
        self.assertEqual(node_a_space["name"], "A ")
        self.assertIsNone(node_a_space["continued_from_node_key"])  # 尾端空白，名字不算相符

        depth3_a = node_a_space["children"][0]
        self.assertEqual(depth3_a["name"], "A")
        self.assertIsNone(depth3_a["continued_from_node_key"])  # 名字對，深度不對

    def test_continuity_overlay_overwrites_coordinates_with_last_periods_labels(self):
        """done-check 2（ADR 0069 §2／§3）：深度 3 沿用節點的座標由程式蓋成上一期
        `period_node_result.coordinates_json` 轉出來的 label，不管代理這次寫了什麼——
        矛盾檢查 check 1 點名的正是這個案例（本地模型抄錯座標，一個字都不該讓它蒙混過關，
        故意讓代理的 hook 跟上一期不一樣）。沒配對到的第三層節點維持模型自己寫的座標。"""
        channel_id = schedule_repo.ensure_meta_channel(web.conn, coredb.DEV_ORG_ID)
        node_rows = [{
            "source_tree_task_id": "tsk_coord_overlay", "channel_id": channel_id,
            "node_key": "9.9.9", "depth": 3, "node_name": "01A",
            "external_id": "ad-01a", "approved_share": None, "approved_daily_amount": None,
            "actual_spend": 500.0, "revenue_tracked": 1000.0, "roas_conservative": 1.5,
            "roas_optimistic": 2.0, "roas_coverage": 1.0, "breakeven_roas": 1.0,
            "breakeven_source": "測試打平線", "verdict": "win",
            "coordinates_json": {
                "audience_key": None, "pain_key": "effort", "angle_key": None,
                "hook_key": "outcome_led", "proof_key": None, "offer_key": None,
                "format_key": None,
            },
            "settled_at": datetime.now(UTC),
        }]
        self._write_scored_period(
            start=date(2026, 7, 1), end=date(2026, 7, 14), daily_budget=2000.0,
            settled_spend=500.0, settled_revenue=1000.0, node_rows=node_rows,
        )

        schedule_jobs.PROVIDER = _fake(_fenced_plans([_one_plan()]))
        resp = self._post(plan_count=1)
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        custom_nodes = [{
            "name": "根", "fields": [], "share": None, "warnings": [],
            "children": [
                {"name": "組合", "fields": [], "share": 1.0, "warnings": [],
                 "children": [
                     {"name": "01A", "fields": [], "share": None, "warnings": [],
                      "children": [],
                      # 模型抄錯：hook 打成別的字，證明程式蓋掉它、不是照抄它。
                      "coordinates": {
                          "audience": None, "pain": "用起來不舒服", "angle": None,
                          "hook": "痛點提問", "proof": None, "offer": None, "format": None,
                      }},
                     {"name": "沒配對到的節點", "fields": [], "share": None, "warnings": [],
                      "children": [],
                      "coordinates": {
                          "audience": None, "pain": None, "angle": "UGC 偽裝", "hook": None,
                          "proof": None, "offer": None, "format": None,
                      }},
                 ]},
            ],
        }]
        schedule_jobs.PROVIDER = _fake(_tree_fenced(custom_nodes))
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        get_resp = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(get_resp.status_code, 200, get_resp.text)
        combo = get_resp.json()["tree"]["nodes"][0]["children"][0]
        node_01a, node_unmatched = combo["children"]

        self.assertEqual(node_01a["name"], "01A")
        self.assertEqual(node_01a["continued_from_node_key"], "9.9.9")
        # Red proof：拿掉 binding._apply_continuity() 對深度 3 的 coordinates 覆蓋，
        # 這兩個 assertEqual 先紅（回到模型寫的「用起來不舒服」／「痛點提問」）。
        self.assertEqual(node_01a["coordinates"]["pain"], "太麻煩")
        self.assertEqual(node_01a["coordinates"]["hook"], "結果導向")
        # 模型寫的其他維度沒被上一期記過分（None），程式不會用 key 本身頂替，維持 None。
        self.assertIsNone(node_01a["coordinates"]["audience"])

        self.assertIsNone(node_unmatched["continued_from_node_key"])
        self.assertEqual(node_unmatched["name"], "沒配對到的節點")
        self.assertEqual(node_unmatched["coordinates"]["angle"], "UGC 偽裝")

    def test_continuity_overlay_is_none_for_every_node_when_nothing_settled(self):
        """done-check 2 子案：這個品牌從沒結算過任何檔期 → 每個節點都是 None，但鍵要在
        （ticket §2：不管有沒有疊圖，形狀都一樣）。"""
        self._succeed_plan_and_tree()
        get_resp = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(get_resp.status_code, 200, get_resp.text)
        nodes = get_resp.json()["tree"]["nodes"]

        def _walk(entries: list) -> None:
            for entry in entries:
                self.assertIn("continued_from_node_key", entry)
                self.assertIsNone(entry["continued_from_node_key"])
                _walk(entry["children"])

        _walk(nodes)

    # -- 票 05：預算層級跟樹以為的不一樣，binding.py 讀 Meta 判斷、回應補一句話 -------------

    def _platform_budgets(self, by_id: dict):
        """換掉 Meta 回的預算欄位（不打網路，票 05）：`by_id` 是
        {external_id: {"daily_budget": str | None, "lifetime_budget": str | None}}——跟
        `_platform_ad_sets` 同一個替換風格；`budgets_for_bound_ids` 問哪些 id 由呼叫端
        （`channel_entity_map` 篩過的租戶界線）決定，這裡只負責照樣回傳。"""

        def fake_fetch_budgets(_token: str, external_ids: list) -> dict:
            return {eid: by_id[eid] for eid in external_ids if eid in by_id}

        return mock.patch.object(meta_graph, "fetch_budgets", fake_fetch_budgets)

    def test_budget_note_shows_when_campaign_has_budget_but_tree_expects_adset_level(self):
        """(a)：預算掛在第一層（行銷活動），樹照第二層（廣告組合，`_one_tree_nodes()`
        預設扛預算的那一層）分配——兩層不吻合，回應補一句話。紅色證明：把
        `binding.budget_placement_note()` 改成無條件回 `None`，這支測試就會紅。"""
        self._succeed_plan_and_tree()
        with self._platform_campaigns({self.account_id: [("camp-1", "活動一")]}), \
                self._platform_ad_sets({"camp-1": [("as-1", "組合1"), ("as-2", "組合2")]}), \
                self._platform_ads(
                    {"as-1": [("ad-1", "單元1")], "as-2": [("ad-2", "單元2")]}
                ), \
                self._platform_budgets({
                    "camp-1": {"daily_budget": "500", "lifetime_budget": None},
                    "as-1": {"daily_budget": None, "lifetime_budget": None},
                    "as-2": {"daily_budget": None, "lifetime_budget": None},
                }):
            resp = self._bind()
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(
            resp.json()["tree"]["budget_note"],
            binding_mod.BUDGET_LEVEL_NOTE.format(actual="行銷活動", expected="廣告組合"),
        )

    def test_budget_note_is_none_when_adset_level_budget_matches_the_tree(self):
        """(b)：預算掛在第二層（廣告組合）——跟樹的 `budget_level` 吻合，不講話。"""
        self._succeed_plan_and_tree()
        with self._platform_campaigns({self.account_id: [("camp-1", "活動一")]}), \
                self._platform_ad_sets({"camp-1": [("as-1", "組合1"), ("as-2", "組合2")]}), \
                self._platform_ads(
                    {"as-1": [("ad-1", "單元1")], "as-2": [("ad-2", "單元2")]}
                ), \
                self._platform_budgets({
                    "camp-1": {"daily_budget": None, "lifetime_budget": None},
                    "as-1": {"daily_budget": "100", "lifetime_budget": None},
                    "as-2": {"daily_budget": None, "lifetime_budget": None},
                }):
            resp = self._bind()
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIsNone(resp.json()["tree"]["budget_note"])

    def test_budget_note_is_none_when_meta_is_unreachable_but_bind_stands(self):
        """(c)：讀預算連不上 Meta——這則提示是錦上添花，不該讓剛成功的綁定被撤銷；回應
        仍是 200，`budget_note` 是 `None`，`channel_entity_map` 這次綁定寫下的列還在。"""
        self._succeed_plan_and_tree()

        def fail(_token: str, _external_ids: list) -> dict:
            raise meta_graph.GraphError("連不上")

        with self._platform_campaigns({self.account_id: [("camp-1", "活動一")]}), \
                self._platform_ad_sets({"camp-1": [("as-1", "組合1"), ("as-2", "組合2")]}), \
                self._platform_ads(
                    {"as-1": [("ad-1", "單元1")], "as-2": [("ad-2", "單元2")]}
                ), \
                mock.patch.object(meta_graph, "fetch_budgets", fail):
            resp = self._bind()
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIsNone(resp.json()["tree"]["budget_note"])
        rows = self._channel_entity_map_rows()
        node_keys = {r["node_key"] for r in rows}
        self.assertEqual(node_keys, {"1", "1.1", "1.2", "1.1.1", "1.2.1"})  # 綁定沒有被撤銷

    def test_diagnosis_budget_section_appears_before_role_text_when_placement_mismatches(self):
        """票 05 done-check 3：判讀讀的是綁定已經讀過的同一棵樹，(a) 的預算不吻合時，
        prompt 多一段【預算層級】，且擺在 `reminders` 之後、`role_text(lens)`（那句
        「只准對上面表格裡已經出現過的座標值」必須墊底，`docs/contracts/schedule.md`
        「Position in the prompt decides」）之前。用 (b) 的組合驗證吻合時完全不加這段。"""
        self._succeed_plan_and_tree()
        with self._platform_campaigns({self.account_id: [("camp-1", "活動一")]}), \
                self._platform_ad_sets({"camp-1": [("as-1", "組合1"), ("as-2", "組合2")]}), \
                self._platform_ads(
                    {"as-1": [("ad-1", "單元1")], "as-2": [("ad-2", "單元2")]}
                ), \
                self._platform_budgets({
                    "camp-1": {"daily_budget": "500", "lifetime_budget": None},
                    "as-1": {"daily_budget": None, "lifetime_budget": None},
                    "as-2": {"daily_budget": None, "lifetime_budget": None},
                }):
            resp = self._bind()
        self.assertEqual(resp.status_code, 200, resp.text)

        fake = _fake("這是一段判讀說明。\n\n```json\n{\"suggestions\": []}\n```")
        schedule_jobs.PROVIDER = fake
        with self._platform_budgets({
            "camp-1": {"daily_budget": "500", "lifetime_budget": None},
            "as-1": {"daily_budget": None, "lifetime_budget": None},
            "as-2": {"daily_budget": None, "lifetime_budget": None},
        }):
            web.conn.commit()  # job 開自己的連線，先把 bind 交易送出去（比照 _run_worker）
            schedule_jobs.schedule_diagnosis(coredb.DEV_ORG_ID, self.brand["id"])

        self.assertEqual(len(fake.calls), 3)  # 三個 lens 各打一次
        prompt = fake.calls[0]["messages"][0]["content"]
        self.assertIn("【預算層級】", prompt)
        self.assertIn(
            binding_mod.BUDGET_LEVEL_NOTE.format(actual="行銷活動", expected="廣告組合"),
            prompt,
        )
        self.assertLess(
            prompt.index("【預算層級】"),
            prompt.index("只准對上面表格裡已經出現過的座標值"),
        )

    def test_diagnosis_budget_section_absent_when_placement_matches(self):
        """(b) 的組合：預算層級吻合，`budget_placement_note()` 回 `None`，prompt 不該多
        這段。"""
        self._succeed_plan_and_tree()
        with self._platform_campaigns({self.account_id: [("camp-1", "活動一")]}), \
                self._platform_ad_sets({"camp-1": [("as-1", "組合1"), ("as-2", "組合2")]}), \
                self._platform_ads(
                    {"as-1": [("ad-1", "單元1")], "as-2": [("ad-2", "單元2")]}
                ), \
                self._platform_budgets({
                    "camp-1": {"daily_budget": None, "lifetime_budget": None},
                    "as-1": {"daily_budget": "100", "lifetime_budget": None},
                    "as-2": {"daily_budget": None, "lifetime_budget": None},
                }):
            resp = self._bind()
        self.assertEqual(resp.status_code, 200, resp.text)

        fake = _fake("這是一段判讀說明。\n\n```json\n{\"suggestions\": []}\n```")
        schedule_jobs.PROVIDER = fake
        with self._platform_budgets({
            "camp-1": {"daily_budget": None, "lifetime_budget": None},
            "as-1": {"daily_budget": "100", "lifetime_budget": None},
            "as-2": {"daily_budget": None, "lifetime_budget": None},
        }):
            web.conn.commit()
            schedule_jobs.schedule_diagnosis(coredb.DEV_ORG_ID, self.brand["id"])

        self.assertEqual(len(fake.calls), 3)
        prompt = fake.calls[0]["messages"][0]["content"]
        self.assertNotIn("【預算層級】", prompt)

    # -- 票 past-ads/05（ADR 0067 §1.10）：plan prompt 帶投放史 -----------------------------

    def _tag_imported_ad(self, external_id: str, day: date, *, keys: dict,
                          owner_note: str) -> None:
        channel_id = schedule_repo.ensure_meta_channel(web.conn, coredb.DEV_ORG_ID)
        schedule_repo.upsert_imported_ad(
            web.conn, org_id=coredb.DEV_ORG_ID, brand_id=self.brand["id"],
            ad_channel_id=channel_id, external_id=external_id, external_name="老廣告",
            first_seen_date=day, last_seen_date=day, creative_body=None, creative_title=None,
            creative_image_url=None, creative_fetched_at=None, coordinates_status="pending",
        )
        full = {"audience": None, "pain": None, "angle": None, "hook": None,
                "proof": None, "offer": None, "format": None}
        full.update(keys)
        schedule_repo.update_imported_ad_tags(
            web.conn, coredb.DEV_ORG_ID, self.brand["id"], external_id, keys=full,
            owner_note=owner_note, status="tagged", actor=ACTOR,
        )
        web.conn.commit()

    def test_history_section_is_the_last_plan_section_and_absent_from_the_tree_prompt(self):
        """票 past-ads/05 done-check 2／3：一則老廣告被標了座標之後，`schedule_plan()`
        prompt 最後一段是【投放史】；`schedule_tree()` 的 prompt 完全不含這一段——那支從沒
        呼叫 `_history_text()`（ADR 0067 §1.10：這一期還沒有節點名字可以對照老廣告）。

        矛盾檢查段點名的陷阱：花費特意種在**這個月之外**，逼出 `tagged_history()` 用的是
        廣告自己的視窗，不是 `state._current_month_window()`——用錯視窗這支廣告會印成
        全零，下面對花費日期的斷言會紅，「有沒有印出這一段」本身逮不到這個陷阱。"""
        old_day = self.today.replace(day=1) - timedelta(days=45)
        meta_repo.upsert_entity_spend(web.conn, coredb.DEV_ORG_ID, self.account_id, [{
            "level": "ad", "entity_id": "ad-old-1", "entity_name": "老廣告",
            "campaign_id": "camp-old", "adset_id": "as-old", "ad_id": "ad-old-1",
            "spend_date": old_day, "spend": 3570.0, "impressions": 1000, "clicks": 50,
            "roas": 2.0, "actions": None, "action_values": None,
            "attribution_window": "7d_click,1d_view",
        }])
        web.conn.commit()
        self._tag_imported_ad(
            "ad-old-1", old_day, keys={"angle": "convenience"}, owner_note="測試備註",
        )

        fake = _fake(_fenced_plans([_one_plan()]))
        schedule_jobs.PROVIDER = fake
        resp = self._post(plan_count=1)
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        plan_prompt = fake.calls[0]["messages"][0]["content"]
        self.assertIn("【投放史】", plan_prompt)
        self.assertIn("老廣告", plan_prompt)
        self.assertIn(old_day.isoformat(), plan_prompt)
        # 數字必須來自花費列自己的視窗，不是本月：3,570 只存在於 45 天前那一列（review 05
        # 抓到的漏洞——名字與日期都來自 imported_ad 那一列，沒有這一句，錯的視窗也能綠）。
        self.assertIn("3,570", plan_prompt)
        self.assertTrue(plan_prompt.rstrip().endswith(schedule_jobs._HISTORY_CLOSING_LINE))

        tree_fake = _fake(_tree_fenced(_one_tree_nodes()))
        schedule_jobs.PROVIDER = tree_fake
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        self.assertNotIn("投放史", tree_fake.calls[0]["messages"][0]["content"])

    def test_history_section_absent_when_nothing_is_tagged(self):
        fake = _fake(_fenced_plans([_one_plan()]))
        schedule_jobs.PROVIDER = fake
        resp = self._post(plan_count=1)
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        self.assertNotIn("投放史", fake.calls[0]["messages"][0]["content"])


class CoordinateSeedTest(_ScheduleApiTestBase):
    """票 T1b done-check：一個品牌的座標第一次被讀出時，剛好 35 個 `dimension='angle'`；
    讀第二次不會多出 70 個（`ensure_coordinates_seeded` 冪等）。票 T8a 擴充：另外六個維度
    也要種進去（35＋33＝68），讀第二次一樣不會變成 136 個。票 workbench/06：`format`
    維度多一個 `flexible` 種子（彈性格式），六個維度的種子總數 33→34，35＋34＝69。"""

    def test_first_read_seeds_35_angles_second_read_does_not_duplicate(self):
        resp1 = self.client.get(f"/api/schedule/brands/{self.brand['id']}/coordinates")
        self.assertEqual(resp1.status_code, 200, resp1.text)
        coordinates1 = resp1.json()["coordinates"]
        angles1 = [c for c in coordinates1 if c["dimension"] == "angle"]
        self.assertEqual(len(angles1), 35)

        # 票 T8a done-check 1：七個維度都有座標，六個新維度加總 34 個（票 workbench/06 之前
        # 是 33，`format` 多了 `flexible` 一筆）。
        seven_dims = creative_mod.COORDINATE_KEYS
        self.assertEqual(
            {c["dimension"] for c in coordinates1}, set(seven_dims),
            "第一次讀完應該七個維度都有座標",
        )
        other_six = [c for c in coordinates1 if c["dimension"] != "angle"]
        self.assertEqual(len(other_six), 34)

        resp2 = self.client.get(f"/api/schedule/brands/{self.brand['id']}/coordinates")
        self.assertEqual(resp2.status_code, 200, resp2.text)
        coordinates2 = resp2.json()["coordinates"]
        angles2 = [c for c in coordinates2 if c["dimension"] == "angle"]
        self.assertEqual(len(angles2), 35)
        other_six2 = [c for c in coordinates2 if c["dimension"] != "angle"]
        self.assertEqual(len(other_six2), 34)


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


class CreativeCandidateSyncTest(_ScheduleApiTestBase):
    """票 05（ADR 0068 §3）：排程讀自己這棵樹時，把「已採用」的文案同步進
    `creative_candidate`——排程自己的記憶（座標種子、成效分組讀這張表），跟 workbench 完全
    分開，讀時同步、不是 workbench 回呼。這裡直接用 `workbench` 的寫入函式組出「一個
    brief 已經有兩輪、採用第一輪」的狀態，不必真的跑 LLM——這條路徑要驗的是同步邏輯本身
    （用哪一輪、擋不擋重複寫入），不是文案生成本身（那是 test_workbench.py／
    test_workbench_api.py 的事）。"""

    def _tree_leaf_brief(self, coordinates: dict | None = None) -> dict:
        """展開一棵最小的活動樹，回傳最深層節點「單元1」（node_key 固定 "1.1.1"，跟既有
        其他測試同一個固定映射）自動提交的那份 workbench_brief。`coordinates`：`None`
        （預設）不帶這個欄位——`test_adopted_round_not_latest_syncs_to_creative_candidate_
        idempotently` 靠這一點維持綠燈（票面矛盾檢查 §6：那支測試斷言模型的答案落地，
        前提是這裡的快照是空的）；帶了就是這個節點的 `coordinates_snapshot_json`（票 05，
        ADR 0069 §4）。"""
        schedule_jobs.PROVIDER = _fake(_fenced_plans([_one_plan()]))
        resp = self._post(plan_count=1)
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        schedule_jobs.PROVIDER = _fake(
            _tree_fenced(_one_tree_nodes(coordinates=coordinates))
        )
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        row = web.conn.execute(
            "SELECT id FROM workbench_brief WHERE brand_id = %s"
            " AND source_ref ->> 'node_key' = '1.1.1'", (self.brand["id"],),
        ).fetchone()
        return dict(row)

    def _write_copy_round(self, brief_id: str, round_no: int, angle_label: str,
                           visual_tone: str = "暖調生活", warnings: list | None = None,
                           hook_label: str | None = None) -> str:
        """直接寫一輪 `workbench_output`（含它自己的 `llm_task` 列）——回傳這一輪的
        `llm_task_id`，供斷言「同步用的是哪一輪」。`visual_tone` 可覆寫，供壞值測試用
        （票 05 fix round：`body_json` 裡不是兩個合法值之一的情況）。`warnings` 可覆寫，
        預設 `[]`（票 workbench-2/02 ablation §4：`_copy_summary()` 的過濾測試用）。
        `hook_label` 可覆寫（票 05，ADR 0069 §4：快照贏過模型逐維度合併測試需要模型自己
        也填一個 `hook`）。"""
        llm_task_id = coredb.new_id("llm")
        web.conn.execute(
            "INSERT INTO llm_task (id, org_id, brand_id, task_type, context_scope_json,"
            " input_context_ids_json, input_context_hash, knowledge_item_ids_json,"
            " brand_version, prompt_template_id, prompt_template_version, provider, model,"
            " status, attempt_no, started_at)"
            " VALUES (%s, %s, %s, 'workbench_copy', '{}', '[]', '', '[]', 1, 'p', 'v1',"
            " 'seed', 'seed', 'succeeded', 1, %s)",
            (llm_task_id, coredb.DEV_ORG_ID, self.brand["id"], coredb.now_iso()),
        )
        coordinates = {
            "audience": None, "pain": None, "angle": angle_label, "hook": hook_label,
            "proof": None, "offer": None, "format": None,
        }
        body = {
            "coordinates": coordinates, "copy_length": "short",
            "sets": [{"body": "短版", "headline": "標題", "description": "說明"}],
            "visual_tone": visual_tone, "visual_concept": f"第 {round_no} 輪的畫面概念",
            "warnings": warnings if warnings is not None else [], "validation": [],
        }
        workbench_repo.write_output(
            web.conn, org_id=coredb.DEV_ORG_ID, brand_id=self.brand["id"], brief_id=brief_id,
            part="copy", generation_round=round_no, body_json=body,
            coordinates_json=coordinates, llm_task_id=llm_task_id,
        )
        return llm_task_id

    def test_adopted_round_not_latest_syncs_to_creative_candidate_idempotently(self):
        # 票 05（ADR 0069 §4）矛盾檢查：`_tree_leaf_brief()` 不帶 `coordinates`，這個
        # brief 的 `coordinates_snapshot_json` 因此是 `{}`——底下 `angle_key ==
        # "scarcity_marketing"` 這條斷言的綠燈靠的正是「快照空，模型的答案沒被蓋掉」；
        # 這支測試不能改成帶座標的 fixture，那是 `test_snapshot_wins_per_dimension_
        # over_model_coordinates` 的事。
        brief = self._tree_leaf_brief()
        round1_task_id = self._write_copy_round(brief["id"], 1, "稀缺性行銷")
        output_1 = web.conn.execute(
            "SELECT id FROM workbench_output WHERE brief_id = %s AND generation_round = 1",
            (brief["id"],),
        ).fetchone()
        workbench_repo.adopt_output(web.conn, coredb.DEV_ORG_ID, self.brand["id"], output_1["id"])
        # 第二輪：真的存在，但沒被採用——同步邏輯要挑第一輪，不是「最新一輪」。
        self._write_copy_round(brief["id"], 2, "限時福利")

        get_resp = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(get_resp.status_code, 200, get_resp.text)

        candidates = web.conn.execute(
            "SELECT * FROM creative_candidate WHERE brand_id = %s", (self.brand["id"],),
        ).fetchall()
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        # 用的是採用的那一輪（第一輪的 llm_task_id），不是最新一輪。
        self.assertEqual(candidate["llm_task_id"], round1_task_id)
        self.assertEqual(candidate["angle_key"], "scarcity_marketing")
        self.assertEqual(candidate["coordinates_status"], "tagged")
        self.assertEqual(candidate["visual_tone"], "暖調生活")
        self.assertEqual(candidate["visual_concept"], "第 1 輪的畫面概念")

        item = web.conn.execute(
            "SELECT fields_json FROM creative_candidate_item WHERE candidate_id = %s",
            (candidate["id"],),
        ).fetchone()
        self.assertEqual(
            {f["label"] for f in item["fields_json"]},
            {"主要文字（短）", "標題", "說明"},
        )

        # 讀第二次不多寫一份（llm_task_id 擋掉重複落地）。
        self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        count = web.conn.execute(
            "SELECT COUNT(*) AS n FROM creative_candidate WHERE brand_id = %s",
            (self.brand["id"],),
        ).fetchone()["n"]
        self.assertEqual(count, 1)

    def test_snapshot_wins_per_dimension_over_model_coordinates(self):
        """done-check 4（ADR 0069 §4）：`angle` 這個維度快照有值，蓋過模型的答案；
        `hook` 快照沒填，模型的答案補上——逐維度合併，不是整份二選一。Red proof：把
        `_sync_creative_candidate()` 的合併改回只用 `copy_output.get("coordinates_json")`
        （拿掉快照），`angle_key` 那個 assertEqual 先紅。"""
        brief = self._tree_leaf_brief(coordinates={
            "audience": None, "pain": None, "angle": "UGC 偽裝", "hook": None,
            "proof": None, "offer": None, "format": None,
        })
        self._write_copy_round(brief["id"], 1, "稀缺行銷", hook_label="痛點提問")
        output_1 = web.conn.execute(
            "SELECT id FROM workbench_output WHERE brief_id = %s AND generation_round = 1",
            (brief["id"],),
        ).fetchone()
        workbench_repo.adopt_output(web.conn, coredb.DEV_ORG_ID, self.brand["id"], output_1["id"])

        get_resp = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(get_resp.status_code, 200, get_resp.text)

        candidate = web.conn.execute(
            "SELECT angle_key, hook_key FROM creative_candidate WHERE brand_id = %s",
            (self.brand["id"],),
        ).fetchone()
        self.assertEqual(candidate["angle_key"], "ugc_disguise")  # 快照贏過模型的「稀缺行銷」
        self.assertEqual(candidate["hook_key"], "pain_question")  # 快照沒填，模型的答案補上

    def test_unadopted_round_still_syncs_to_creative_candidate(self):
        """票 workbench-2/01（ADR 0068 §3 amended，drill 2）：同步跟 `adopted_output()`
        本身的「已採用，否則最新一輪」語意走，不再只挑已採用的——drill 2 量到 33 份輸出
        只有 2 份被採用，只同步已採用會讓大半花費永遠讀不到座標。"""
        brief = self._tree_leaf_brief()
        round1_task_id = self._write_copy_round(brief["id"], 1, "稀缺性行銷")

        get_resp = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(get_resp.status_code, 200, get_resp.text)

        candidates = web.conn.execute(
            "SELECT * FROM creative_candidate WHERE brand_id = %s", (self.brand["id"],),
        ).fetchall()
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["llm_task_id"], round1_task_id)

        # 讀第二次不多寫一份。
        get_resp_2 = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(get_resp_2.status_code, 200, get_resp_2.text)
        count = web.conn.execute(
            "SELECT COUNT(*) AS n FROM creative_candidate WHERE brand_id = %s",
            (self.brand["id"],),
        ).fetchone()["n"]
        self.assertEqual(count, 1)

        # 之後採用同一輪——仍然冪等，不多寫一份。
        output_1 = web.conn.execute(
            "SELECT id FROM workbench_output WHERE brief_id = %s AND generation_round = 1",
            (brief["id"],),
        ).fetchone()
        workbench_repo.adopt_output(web.conn, coredb.DEV_ORG_ID, self.brand["id"], output_1["id"])
        get_resp_3 = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(get_resp_3.status_code, 200, get_resp_3.text)
        count = web.conn.execute(
            "SELECT COUNT(*) AS n FROM creative_candidate WHERE brand_id = %s",
            (self.brand["id"],),
        ).fetchone()["n"]
        self.assertEqual(count, 1)

    def test_bad_visual_tone_in_body_json_does_not_crash_the_sync(self):
        """票 05 fix round（2026-09-09 reject）：`body_json.visual_tone` 不是兩個合法值
        之一（這裡直接寫壞值，模擬 workbench 修好之前留下的舊資料，或任何繞過 sanitise
        的寫入路徑）——同步要退回 `None`，不能讓 `creative_candidate` 的 CHECK 炸掉整支
        排程 GET。"""
        brief = self._tree_leaf_brief()
        self._write_copy_round(brief["id"], 1, "稀缺性行銷", visual_tone="紫色")
        output_1 = web.conn.execute(
            "SELECT id FROM workbench_output WHERE brief_id = %s AND generation_round = 1",
            (brief["id"],),
        ).fetchone()
        workbench_repo.adopt_output(web.conn, coredb.DEV_ORG_ID, self.brand["id"], output_1["id"])

        get_resp = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(get_resp.status_code, 200, get_resp.text)

        candidate = web.conn.execute(
            "SELECT visual_tone FROM creative_candidate WHERE brand_id = %s",
            (self.brand["id"],),
        ).fetchone()
        self.assertIsNone(candidate["visual_tone"])

        # 讀第二次不多寫一份，也不再次撞到同一個壞值。
        get_resp_2 = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(get_resp_2.status_code, 200, get_resp_2.text)
        count = web.conn.execute(
            "SELECT COUNT(*) AS n FROM creative_candidate WHERE brand_id = %s",
            (self.brand["id"],),
        ).fetchone()["n"]
        self.assertEqual(count, 1)

    def test_copy_warnings_reach_the_brand_response(self):
        """票 workbench-2/02（ablation §4）：`_copy_summary()` 過濾出來的 `warnings` 一路
        帶到排程頁 `briefs[].copy.warnings`（純函式那一段在 test_workbench.py 驗，這裡驗
        端到端的那一段——經 GET /api/schedule/brands/{brand_id} 真的讀得到）。混一個非字串
        元素，確認被濾掉、不是整批丟棄。"""
        brief = self._tree_leaf_brief()
        self._write_copy_round(
            brief["id"], 1, "稀缺性行銷",
            warnings=["3 顆體驗包的價格是佔位，投放前請核對。", "另一句提醒。", 123],
        )

        get_resp = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(get_resp.status_code, 200, get_resp.text)
        target = next(b for b in get_resp.json()["briefs"] if b["node_key"] == "1.1.1")
        self.assertEqual(
            target["copy"]["warnings"],
            ["3 顆體驗包的價格是佔位，投放前請核對。", "另一句提醒。"],
        )


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
