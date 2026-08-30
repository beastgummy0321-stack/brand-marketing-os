"""app/tests/test_schedule.py — 票 07：檔期規劃最薄路徑；票 08：表單擴成 N 個方案；
票 09：選定一個方案展開成三層活動樹。

只寫這些事（docs/workflow-diet.md 第 4 條；票 07／08／09 settled 段都明講畫面行為不寫
單元測試）：金額算法（最大餘數法）、比例不合法／方案（樹）格式不合法的拒絕、租戶隔離、
API 契約（含 ADR 0029「原樣貼進 prompt」的可驗證證據、票 08 的平台／目標／方案數驗證、
票 09 的方案編號驗證）、「查詢不是排程的先決條件」這條資料正確性規則、票 09 的活動樹元件
不得寫死通路詞彙這道機器閘門。全程只用 FakeProvider，不發任何真實網路請求；網路搜尋工具
本身怎麼解析 SDK 回應（成功／出錯兩種形狀）不在這裡測，那是 `AnthropicProvider.complete()`
的責任，見 test_llm_web_search.py。
"""

import json
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.core import rule_cards
from app.identity import repository as identity_repo
from app.llm import providers
from app.meta import graph as meta_graph
from app.meta import repository as meta_repo
from app.schedule import plan as plan_mod
from app.schedule import routes as schedule_routes
from app.schedule import tree as tree_mod

from .identity_test_helpers import mint_hs256

ACTOR = "測試員"

# 有效的平台／目標——照 app/schedule/platform_objectives.json 的內容取，測試不重寫一份
# 平行的資料（改資料檔不用跟著改這裡）。
_DATA = schedule_routes._load_platform_data()
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


def _one_tree_nodes(shares: tuple = (0.7, 0.3)) -> list:
    """三層節點，扛預算的是第二層（比照 Meta：行銷活動／廣告組合／廣告，預算在第 2 層）。"""
    return [
        {
            "name": "活動一",
            "fields": [{"label": "目標", "value": "業績"}],
            "share": None,
            "warnings": [],
            "children": [
                {
                    "name": f"組合{i + 1}",
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


def _creative_fenced(creatives: list) -> str:
    body = json.dumps({"creatives": creatives}, ensure_ascii=False)
    return f"這是一段給老闆看的說明文字。\n\n```json\n{body}\n```"


def _one_creative(node: str, **overrides) -> dict:
    creative = {
        "node": node,
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
        self._orig_provider = schedule_routes.PROVIDER

    def tearDown(self):
        schedule_routes.PROVIDER = self._orig_provider

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
        schedule_routes.PROVIDER = fake

        resp = self._post(plan_count=2)
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
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
        schedule_routes.PROVIDER = _fake(_fenced_plans([_one_plan()]))
        post_resp = self._post(plan_count=1)
        get_resp = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(post_resp.json()["plan"], get_resp.json()["plan"])

    def test_budget_not_set_refuses_before_calling_agent(self):
        rule_cards.set_value(
            web.conn, self.brand["id"], "schedule_budget", "daily_budget", 0.0,
            ACTOR, org_id=coredb.DEV_ORG_ID,
        )
        fake = _fake(_fenced_plans([_one_plan()]))
        schedule_routes.PROVIDER = fake
        resp = self._post()
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["message"], plan_mod.BUDGET_NOT_SET_MESSAGE)
        self.assertEqual(fake.calls, [])  # 沒打到代理

    def test_disabled_platform_is_rejected_before_calling_agent(self):
        fake = _fake(_fenced_plans([_one_plan()]))
        schedule_routes.PROVIDER = fake
        resp = self._post(platform=DISABLED_PLATFORM)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(fake.calls, [])

    def test_objective_not_belonging_to_platform_is_rejected(self):
        fake = _fake(_fenced_plans([_one_plan()]))
        schedule_routes.PROVIDER = fake
        resp = self._post(objective="這不是有效的目標值")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(fake.calls, [])

    def test_plan_count_out_of_rule_card_range_is_rejected(self):
        fake = _fake(_fenced_plans([_one_plan()]))
        schedule_routes.PROVIDER = fake
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


class RejectApiContractTest(_ScheduleApiTestBase):
    """票 10-feedback-entries（ADR 0037）：POST .../reject——每條意見變一列 rule，
    再用凍結參數重新排程。"""

    def _succeed_plan(self, plan_count: int = 2, promotion_note: str = "這期主打新品") -> None:
        schedule_routes.PROVIDER = _fake(
            _fenced_plans([_one_plan(), _one_plan(summary="第二個方案")][:plan_count])
        )
        resp = self._post(plan_count=plan_count, promotion_note=promotion_note)
        self.assertEqual(resp.status_code, 200, resp.text)

    def _reject(self, entries: list):
        return self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/reject", json={"entries": entries}
        )

    def test_empty_entries_is_rejected_before_creating_rules_or_calling_agent(self):
        self._succeed_plan()
        fake = _fake(_fenced_plans([_one_plan()]))
        schedule_routes.PROVIDER = fake
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
        schedule_routes.PROVIDER = fake
        resp = self._reject([
            {"severity": "hard", "content": "絕不可宣稱醫療效果"},
            {"severity": "soft", "rule_type": "audience", "content": "受眾偏了，不該對到長輩"},
        ])
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()

        rules = bi_repo.list_rules_for_brand(web.conn, self.brand["id"])
        self.assertEqual(len(rules), 2)  # 兩條意見各自一列
        self.assertEqual(len(fake.calls), 1)  # 真的重跑了一次排程

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
        schedule_routes.PROVIDER = _fake(
            _fenced_plans([_one_plan(), _one_plan(summary="第二個方案")][:plan_count])
        )
        resp = self._post(plan_count=plan_count)
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_post_tree_returns_tree_and_prompt_carries_department_file(self):
        self._succeed_plan()
        fake = _fake(_tree_fenced(_one_tree_nodes()))
        schedule_routes.PROVIDER = fake

        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        tree = resp.json()["tree"]
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
        schedule_routes.PROVIDER = _fake(_tree_fenced(_one_tree_nodes()))
        post_resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        get_resp = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(post_resp.json()["tree"], get_resp.json()["tree"])

    def test_plan_index_out_of_range_is_rejected_before_calling_agent(self):
        self._succeed_plan(plan_count=2)
        fake = _fake(_tree_fenced(_one_tree_nodes()))
        schedule_routes.PROVIDER = fake
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 5}
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(fake.calls, [])

    def test_no_succeeded_plan_is_rejected_before_calling_agent(self):
        fake = _fake(_tree_fenced(_one_tree_nodes()))
        schedule_routes.PROVIDER = fake
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

        名稱比對問的是平台上有沒有這個活動，不是 `meta_campaign_spend`——手動建好、維持
        關閉的活動沒有任何 insights 列（見 app/meta/graph.py `list_campaigns`），所以這裡
        換掉的是 `graph.list_campaigns`，不是塞花費列進去。"""
        wanted = {
            self._external_account_ids[row_id]: entries
            for row_id, entries in by_account.items()
        }

        def fake_list_campaigns(_token: str, account_id: str) -> list[dict]:
            return [
                {"campaign_id": campaign_id, "name": name}
                for campaign_id, name in wanted.get(account_id, [])
            ]

        return mock.patch.object(meta_graph, "list_campaigns", fake_list_campaigns)

    def _seed_campaign(self, org_id: str, account_id: str, campaign_id: str, campaign_name: str,
                        *, spend: float = 1000.0, roas: float | None = 2.0) -> None:
        meta_repo.upsert_campaign_spend(web.conn, org_id, account_id, self.today, [
            {"campaign_id": campaign_id, "campaign_name": campaign_name,
             "spend": spend, "impressions": 100, "clicks": 10, "roas": roas},
        ])
        web.conn.commit()

    def _succeed_plan_and_tree(self) -> None:
        schedule_routes.PROVIDER = _fake(_fenced_plans([_one_plan()]))
        resp = self._post(plan_count=1)
        self.assertEqual(resp.status_code, 200, resp.text)
        schedule_routes.PROVIDER = _fake(_tree_fenced(_one_tree_nodes()))
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)

    def _bind(self):
        return self.client.post(f"/api/schedule/brands/{self.brand['id']}/tree/bind")

    def _stored_bound_external_ids(self) -> dict:
        row = web.conn.execute(
            "SELECT context_scope_json FROM llm_task WHERE brand_id = %s AND task_type = %s"
            " ORDER BY started_at DESC LIMIT 1",
            (self.brand["id"], schedule_routes.TREE_TASK_TYPE),
        ).fetchone()
        return (row["context_scope_json"] or {}).get("bound_external_ids", {})

    # -- 資料正確性：綁一次之後，平台端改名不斷線，花費／ROAS 照樣讀得到 -----------------

    def test_exact_match_binds_once_and_survives_a_rename(self):
        self._succeed_plan_and_tree()
        self._seed_campaign(coredb.DEV_ORG_ID, self.account_id, "camp-1", "活動一")

        with self._platform_campaigns({self.account_id: [("camp-1", "活動一")]}):
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
        花過錢，一列 insights 都沒有。名稱比對若建在 `meta_campaign_spend` 上，這一步永遠
        是「配對失敗，請檢查名稱是否完全相符」——名字明明一字不差（2026-08-29 對真帳號實測：
        建了一個 PAUSED 活動，拉完當天花費，那個活動不在花費表裡）。"""
        self._succeed_plan_and_tree()

        with self._platform_campaigns({self.account_id: [("camp-paused", "活動一")]}):
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
        self.assertEqual(tree["bind_failure"], "配對失敗，請檢查名稱是否完全相符")
        self.assertIsNone(tree["nodes"][0]["bound_external_id"])
        self.assertEqual(self._stored_bound_external_ids(), {})

    # -- 兩筆比對 -> 同一句失敗訊息，不猜一個出來 ----------------------------------------

    def test_two_matches_is_a_failure_not_a_guess(self):
        self._succeed_plan_and_tree()

        with self._platform_campaigns(
            {self.account_id: [("camp-1", "活動一"), ("camp-2", "活動一")]}
        ):
            resp = self._bind()
        self.assertEqual(resp.status_code, 200, resp.text)
        tree = resp.json()["tree"]
        self.assertEqual(tree["bind_failure"], "配對失敗，請檢查名稱是否完全相符")
        self.assertIsNone(tree["nodes"][0]["bound_external_id"])
        self.assertEqual(self._stored_bound_external_ids(), {})

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
        self.assertEqual(tree["bind_failure"], "配對失敗，請檢查名稱是否完全相符")
        self.assertIsNone(tree["nodes"][0]["bound_external_id"])
        self.assertEqual(self._stored_bound_external_ids(), {})


class CreativeApiContractTest(_ScheduleApiTestBase):
    """票 01（`.scratch/creative-slice/issues/01-ad-creative-per-ad-node.md`）：POST
    .../creative——活動樹每個最深層節點各配一份內容。這裡的最深層節點固定是 `_one_tree_nodes()`
    產生的「單元1」「單元2」（見本檔頂部），照文件順序。"""

    _LEAF_NODE_NAMES = ["單元1", "單元2"]

    def _succeed_plan_and_tree(self) -> None:
        schedule_routes.PROVIDER = _fake(_fenced_plans([_one_plan()]))
        resp = self._post(plan_count=1)
        self.assertEqual(resp.status_code, 200, resp.text)
        schedule_routes.PROVIDER = _fake(_tree_fenced(_one_tree_nodes()))
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)

    def _generate(self):
        return self.client.post(f"/api/schedule/brands/{self.brand['id']}/creative", json={})

    def test_post_creative_returns_one_ad_per_leaf_node_and_prompt_carries_department_file(self):
        self._succeed_plan_and_tree()
        # 代理故意回覆「反過來」的順序——用來證明回應真的是照樹的文件順序重排，不是原樣
        # 照抄代理回覆的順序（代理不保證照樹的順序回覆）。
        reversed_names = list(reversed(self._LEAF_NODE_NAMES))
        fake = _fake(_creative_fenced([_one_creative(name) for name in reversed_names]))
        schedule_routes.PROVIDER = fake

        resp = self._generate()
        self.assertEqual(resp.status_code, 200, resp.text)
        creative = resp.json()["creative"]
        self.assertIsNone(creative["failure"])
        # 樹的文件順序（單元1、單元2），不是代理回覆的順序（單元2、單元1）。
        self.assertEqual([ad["node"] for ad in creative["ads"]], self._LEAF_NODE_NAMES)
        self.assertEqual(
            creative["ads"][0]["fields"],
            [
                {"label": "主要文字", "value": "測試內容"},
                {"label": "圖片提示詞", "value": "測試提示詞"},
            ],
        )

        # ADR 0029：部門任務檔原樣貼進 prompt——用檔案裡的識別行證明真的貼進去了。
        self.assertEqual(len(fake.calls), 1)
        prompt_text = fake.calls[0]["messages"][0]["content"]
        self.assertIn("AD-CREATIVE-TASK-V1", prompt_text)

    def test_get_after_post_returns_identical_creative(self):
        self._succeed_plan_and_tree()
        schedule_routes.PROVIDER = _fake(_creative_fenced(
            [_one_creative(name) for name in self._LEAF_NODE_NAMES]
        ))
        post_resp = self._generate()
        get_resp = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(post_resp.json()["creative"], get_resp.json()["creative"])

    def test_no_succeeded_tree_is_rejected_before_calling_agent(self):
        fake = _fake(_creative_fenced([_one_creative("單元1")]))
        schedule_routes.PROVIDER = fake
        resp = self._generate()
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(fake.calls, [])

    def test_missing_node_fails_the_whole_run(self):
        self._succeed_plan_and_tree()
        # 少一份：「單元2」沒有配到內容。
        schedule_routes.PROVIDER = _fake(_creative_fenced([_one_creative("單元1")]))
        resp = self._generate()
        self.assertEqual(resp.status_code, 200, resp.text)
        creative = resp.json()["creative"]
        self.assertTrue(creative["failure"])
        self.assertEqual(creative["ads"], [])

    def test_duplicate_node_fails_the_whole_run(self):
        self._succeed_plan_and_tree()
        schedule_routes.PROVIDER = _fake(_creative_fenced(
            [_one_creative("單元1"), _one_creative("單元1"), _one_creative("單元2")]
        ))
        resp = self._generate()
        self.assertEqual(resp.status_code, 200, resp.text)
        creative = resp.json()["creative"]
        self.assertTrue(creative["failure"])
        self.assertEqual(creative["ads"], [])

    def test_unknown_node_fails_the_whole_run(self):
        self._succeed_plan_and_tree()
        schedule_routes.PROVIDER = _fake(_creative_fenced(
            [_one_creative("單元1"), _one_creative("不存在的節點")]
        ))
        resp = self._generate()
        self.assertEqual(resp.status_code, 200, resp.text)
        creative = resp.json()["creative"]
        self.assertTrue(creative["failure"])
        self.assertEqual(creative["ads"], [])

    def test_running_creative_renders_as_running_not_failure(self):
        self._succeed_plan_and_tree()
        tree_row = schedule_routes._latest_task_row(
            web.conn, self.brand["id"], schedule_routes.TREE_TASK_TYPE
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
                schedule_routes.CREATIVE_TASK_TYPE,
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


class SearchSourcesReadbackTest(_ScheduleApiTestBase):
    """票 08 兩條不可妥協規則之一：查詢不是排程的先決條件——這裡只驗證 gateway →
    usage_json → plan_from_task_row 這段管線本身接得起來；SDK 回應怎麼解析成
    search_sources（成功／出錯兩種形狀）在 test_llm_web_search.py 測，不在這裡重測。
    """

    def test_search_sources_are_stored_and_read_back(self):
        sources = [{"title": "雙十一活動頁", "url": "https://example.com/1111"}]
        schedule_routes.PROVIDER = _fake(_fenced_plans([_one_plan()]), search_sources=sources)
        resp = self._post(plan_count=1)
        self.assertEqual(resp.json()["plan"]["sources"], sources)

    def test_no_search_sources_still_returns_plans(self):
        # FakeProvider 預設 search_sources=None（沒開搜尋、或搜尋沒找到東西）：排程照樣成功，
        # 不會因為沒有搜尋結果就整個排程失敗。
        schedule_routes.PROVIDER = _fake(_fenced_plans([_one_plan()]))
        resp = self._post(plan_count=1)
        body = resp.json()
        self.assertIsNone(body["plan"]["failure"])
        self.assertEqual(body["plan"]["sources"], [])


if __name__ == "__main__":
    unittest.main()
