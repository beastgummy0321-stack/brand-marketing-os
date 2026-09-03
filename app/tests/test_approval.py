"""app/tests/test_approval.py — 票 01
（`.scratch/approval-slice/issues/01-approval-is-the-money-brake.md`，ADR 0040）：核准＝花錢煞車。

只寫這些事（全域 CLAUDE.md 測試四類）：金額伺服器算、`content_hash` 排除清單、
租戶隔離、API 契約、超支比對兩個時間窗必須對齊。只用 FakeProvider，不發真實網路請求。

票 05-1：`_succeed_plan_and_tree()` 用到的 POST .../plans、.../tree 兩支現在只 enqueue，
真正打代理搬進 worker——助手方法自己 `self._run_worker()`，見那裡的說明；核准／撤回／綁定
三支端點沒有移動，仍是同步的。
"""

import json
import unittest
import uuid
from datetime import UTC, date, datetime
from unittest import mock

from fastapi.testclient import TestClient

import app.background as background_module
import app.main as main
import app.schedule as schedule_module
import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core import approval as approval_mod
from app.core import db as coredb
from app.core import rule_cards
from app.core import settings as coresettings
from app.llm import providers
from app.meta import graph as meta_graph
from app.meta import repository as meta_repo
from app.schedule import jobs as schedule_jobs
from app.schedule import routes as schedule_routes
from app.schedule import state as schedule_state

ACTOR = "測試員"

_DATA = schedule_state._load_platform_data()  # 平台／目標照資料檔取，不重寫平行資料
VALID_PLATFORM = next(p["id"] for p in _DATA["platforms"] if p["enabled"])
VALID_OBJECTIVE = next(o["value"] for o in _DATA["objectives"] if o["platform"] == VALID_PLATFORM)

_PLAN_FENCED = (
    '文字。\n\n```json\n{"plans": [{"summary": "主打驗證過的受眾。", "reasoning": "穩定。",'
    ' "splits": [{"label": "主力方向", "share": 1.0, "why": "先守住"}]}]}\n```'
)


def _tree_fenced(name: str) -> str:
    """單層扛預算（budget_level=1）、三層深——approval 只在乎「一個扛預算節點」跟名字。"""
    leaf = {"name": "單元1", "fields": [], "share": None, "warnings": [], "children": []}
    mid = {"name": "組合1", "fields": [], "share": None, "warnings": [], "children": [leaf]}
    root = {"name": name, "fields": [], "share": 1.0, "warnings": [], "children": [mid]}
    payload = {"levels": ["行銷活動", "廣告組合", "廣告"], "budget_level": 1, "nodes": [root]}
    return f"文字。\n\n```json\n{json.dumps(payload, ensure_ascii=False)}\n```"


def _tree_fenced_two(name_a: str, name_b: str, share_a: float, share_b: float) -> str:
    """票 M2（ADR 0059 done-check 2）：兩個扛預算節點的版本——`_tree_fenced` 只有一個
    root，share 永遠是 1.0，測不出「share 在節點之間搬動」，得要至少兩個 root 才行。"""
    def _campaign(name: str, share: float) -> dict:
        leaf = {"name": "單元1", "fields": [], "share": None, "warnings": [], "children": []}
        mid = {"name": "組合1", "fields": [], "share": None, "warnings": [], "children": [leaf]}
        return {"name": name, "fields": [], "share": share, "warnings": [], "children": [mid]}
    payload = {
        "levels": ["行銷活動", "廣告組合", "廣告"], "budget_level": 1,
        "nodes": [_campaign(name_a, share_a), _campaign(name_b, share_b)],
    }
    return f"文字。\n\n```json\n{json.dumps(payload, ensure_ascii=False)}\n```"


def _fake(rendered_output: str) -> providers.FakeProvider:
    return providers.FakeProvider(response=providers.ProviderResponse(
        output_text=rendered_output, structured=None,
        usage=providers.Usage(input_tokens=500, output_tokens=200), stop_reason="end_turn",
        search_sources=None,
    ))


class ApprovalApiContractTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        # 票 05-1：這個測試模組自己有一份 schema，這個模組自己那份 `background.app()` 要
        # 重新掛一次三個生成 task（見 app/schedule/__init__.py register_tasks() 檔頭）。
        schedule_module.register_tasks()
        self.brand = bi_repo.create_brand(
            web.conn, org_id=coredb.DEV_ORG_ID, name="測試品牌：核准",
            client_name=None, actor=ACTOR,
        )
        self.product = bi_repo.create_product(
            web.conn, self.brand["id"], name="測試產品：核准用", actor=ACTOR,
        )
        rule_cards.set_value(
            web.conn, self.brand["id"], "schedule_budget", "daily_budget", 1000.0,
            ACTOR, org_id=coredb.DEV_ORG_ID,
        )
        self._orig_provider = schedule_jobs.PROVIDER

    def tearDown(self):
        schedule_jobs.PROVIDER = self._orig_provider

    def _run_worker(self) -> None:
        """票 05-1：POST 只 enqueue，見 test_schedule.py 同名助手方法的說明。"""
        web.conn.commit()
        background_module.app().run_worker(wait=False)

    def _succeed_plan_and_tree(self, node_name: str = "活動一") -> None:
        schedule_jobs.PROVIDER = _fake(_PLAN_FENCED)
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/plans",
            json={"product_ids": [self.product["id"]], "platform": VALID_PLATFORM,
                  "objective": VALID_OBJECTIVE, "promotion_note": "", "plan_count": 1,
                  # 票 T2b（ADR 0053）：開始日／結束日現在是必填——這裡不測檔期本身，
                  # 隨便給一段合法區間讓既有的核准流程走得下去。
                  "start_date": "2026-09-10", "end_date": "2026-09-24"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        schedule_jobs.PROVIDER = _fake(_tree_fenced(node_name))
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

    def _approve(self):
        return self.client.post(f"/api/schedule/brands/{self.brand['id']}/tree/approve")

    def _get(self):
        return self.client.get(f"/api/schedule/brands/{self.brand['id']}")

    def _bind_one_campaign(self, node_name: str, campaign_id: str = "camp-1") -> str:
        """真的打一次 POST .../tree/bind，不是憑空假造 bound_external_id。"""
        meta_repo.save_token(web.conn, coredb.DEV_ORG_ID, "tok")
        external_id = f"act_{uuid.uuid4().hex[:10]}"
        meta_repo.upsert_accounts(web.conn, coredb.DEV_ORG_ID, [
            {"account_id": external_id, "name": "測試帳號", "currency": "TWD"},
        ])
        account_id = web.conn.execute(
            "SELECT id FROM meta_ad_account WHERE account_id = %s", (external_id,)
        ).fetchone()["id"]
        meta_repo.bind(web.conn, coredb.DEV_ORG_ID, self.brand["id"], account_id)
        web.conn.commit()

        def fake_list_campaigns(_token: str, acc_id: str) -> list[dict]:
            hit = [{"campaign_id": campaign_id, "name": node_name, "effective_status": "ACTIVE"}]
            return hit if acc_id == external_id else []

        # 票 T3c：綁定現在也會往下比對第二層（廣告組合）——這支測試守的是核准／花費／
        # content_hash 那條路，不是第二層配對，平台上沒有任何廣告組合（`list_ad_sets`
        # 一律回空清單）本來就會讓第二層配不到，`bind_failure` 因此非 null，不影響這裡
        # 只在乎的第一層（root）綁定結果。
        with mock.patch.object(meta_graph, "list_campaigns", fake_list_campaigns), \
                mock.patch.object(meta_graph, "list_ad_sets", lambda _token, _cid: []):
            resp = self.client.post(f"/api/schedule/brands/{self.brand['id']}/tree/bind")
        self.assertEqual(
            (resp.status_code, resp.json()["tree"]["nodes"][0]["bound_external_id"]),
            (200, campaign_id), resp.text,
        )
        return account_id

    def _seed_spend(self, account_id: str, campaign_id: str, day, *, spend: float) -> None:
        meta_repo.upsert_entity_spend(web.conn, coredb.DEV_ORG_ID, account_id, [
            {"level": "campaign", "entity_id": campaign_id, "entity_name": "活動一",
             "campaign_id": campaign_id, "adset_id": None, "ad_id": None, "spend_date": day,
             "spend": spend, "impressions": 10, "clicks": 1, "roas": None,
             "actions": None, "action_values": None,
             "attribution_window": "7d_click,1d_view"},
        ])
        web.conn.commit()

    def _set_tree_daily_budget(self, amount: float) -> None:
        """票 M2（ADR 0059）：今天系統自己還沒有任何一條路會改動 `daily_amount`（ADR 0059
        「why now」段落親口承認），這是唯一能在不重新展開（不換 content_hash 結構）的
        前提下，模擬「系統自己把總額縮小／放大」這件事的槓桿——跟 ADR 0058 那支測試直接
        改 `approved_at` 是同一招：`tree_from_task_row()` 每次都從 `rendered_output` 加
        `context_scope_json.daily_budget` 重算（同輸入同輸出，不落地快取），改這一欄、
        不重新展開，node 名字／`share`／結構都不變，只有 `daily_amount` 跟著新總額重算。"""
        web.conn.execute(
            "UPDATE llm_task SET context_scope_json ="
            " jsonb_set(context_scope_json, '{daily_budget}', %s::jsonb)"
            " WHERE id = (SELECT id FROM llm_task WHERE brand_id = %s AND task_type = %s"
            " ORDER BY started_at DESC LIMIT 1)",
            (json.dumps(amount), self.brand["id"], schedule_state.TREE_TASK_TYPE),
        )
        web.conn.commit()

    def test_scaling_the_whole_tree_down_keeps_the_approval_valid(self):
        """done-check 1／4（ADR 0059）：只把總額縮小、`share`（唯一節點吃滿 1.0）不動——
        `matches_current_tree` 仍是 true，`within_approved_ceiling` 仍是 true，
        `expected_to_date` 跟著現在的總額走、比用核准當時的總額算出來的數字小（這是煞車
        往「更嚴格」錯，不是往「更寬鬆」錯，ADR 0058／0040 那個方向）。"""
        self._succeed_plan_and_tree()
        approved = self._approve().json()["tree"]["approval"]
        self.assertEqual(approved["approved_amount"], 1000)
        self.assertEqual(approved["max_daily_amount"], 1000)

        self._set_tree_daily_budget(850)  # 總額縮 15%
        after = self._get().json()["tree"]["approval"]
        self.assertTrue(after["matches_current_tree"])
        self.assertEqual(after["current_daily_amount"], 850)
        self.assertTrue(after["within_approved_ceiling"])
        self.assertEqual(
            after["expected_to_date"], after["current_daily_amount"] * after["days_elapsed"]
        )
        self.assertLess(
            after["expected_to_date"], approved["approved_amount"] * after["days_elapsed"]
        )

    def test_moving_budget_between_nodes_still_voids_it(self):
        """done-check 2：把 share 在兩個節點之間搬動——即使總額沒變，`matches_current_tree`
        要變 false。這是擋住 check 1 被誤讀成「整份雜湊都不用管金額」的底線：如果連
        `share` 都被拿掉，這支測試會失敗而上一支會過；如果一個都沒拿掉，上一支會失敗而
        這一支會過——兩支都要綠，才代表只拿掉了 `daily_amount` 一個鍵（ticket 矛盾檢查表）。
        """
        schedule_jobs.PROVIDER = _fake(_PLAN_FENCED)
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/plans",
            json={"product_ids": [self.product["id"]], "platform": VALID_PLATFORM,
                  "objective": VALID_OBJECTIVE, "promotion_note": "", "plan_count": 1,
                  "start_date": "2026-09-10", "end_date": "2026-09-24"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        schedule_jobs.PROVIDER = _fake(_tree_fenced_two("活動A", "活動B", 0.6, 0.4))
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        approved = self._approve().json()["tree"]["approval"]
        self.assertEqual(approved["approved_amount"], 1000)  # 600 + 400

        schedule_jobs.PROVIDER = _fake(_tree_fenced_two("活動A", "活動B", 0.5, 0.5))
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        after = self._get().json()["tree"]["approval"]
        self.assertFalse(after["matches_current_tree"])  # 名字沒變，share 搬動了

    def test_above_the_ceiling_is_caught(self):
        """done-check 3：把總額拉到核准當時的每日上限之上，`within_approved_ceiling` 要
        變 false。"""
        self._succeed_plan_and_tree()
        approved = self._approve().json()["tree"]["approval"]
        self.assertEqual(approved["max_daily_amount"], 1000)

        self._set_tree_daily_budget(1200)
        after = self._get().json()["tree"]["approval"]
        self.assertEqual(after["current_daily_amount"], 1200)
        self.assertFalse(after["within_approved_ceiling"])

    def test_approve_refuses_without_a_tree_then_writes_correct_amount_audit_and_overspend(self):
        resp = self._approve()  # item 2：沒有成功展開的樹，先擋，不寫任何東西
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.json()["error"]["message"], schedule_routes.NO_TREE_TO_APPROVE_MESSAGE
        )
        self.assertEqual(list(web.conn.execute(
            "SELECT * FROM approval WHERE brand_id = %s", (self.brand["id"],)
        )), [])
        self._succeed_plan_and_tree()  # items 1/3/8：核准之後，一次核准的完整字面契約
        resp = self._approve()
        self.assertEqual(resp.status_code, 200, resp.text)
        approval = resp.json()["tree"]["approval"]
        self.assertEqual(approval["approved_amount"], 1000)  # 唯一節點吃下整個日預算
        self.assertTrue(approval["matches_current_tree"])
        self.assertEqual(approval["days_elapsed"], 1)  # 核准當天，窗口只有今天
        self.assertEqual(
            approval["expected_to_date"], approval["approved_amount"] * approval["days_elapsed"]
        )
        self.assertIsNone(approval["spend_to_date"])  # 沒綁定，未追蹤，不是 0
        self.assertEqual(len(list(web.conn.execute(
            "SELECT * FROM approval WHERE brand_id = %s", (self.brand["id"],)
        ))), 1)  # 落地一列
        self.assertEqual([r["action"] for r in web.conn.execute(
            "SELECT action FROM audit_log WHERE entity_type = 'approval' AND brand_id = %s",
            (self.brand["id"],),
        )], ["approve"])
        self.assertEqual(self._get().json()["tree"]["approval"], approval)  # 讀回同一列
        row = next(iter(web.conn.execute(
            "SELECT scope_ref FROM approval WHERE brand_id = %s", (self.brand["id"],))))
        # scope_ref 記的是「簽的是哪一棵」，不是品牌自己——事後查得回去的那一欄
        self.assertEqual(row["scope_ref"], self._get().json()["tree"]["task_id"])

    def test_overspend_window_counts_days_on_the_orgs_calendar_not_utc(self):
        """票 M1（ADR 0058）：approved_at 存 UTC，org 的今天要問組織時區——兩者不是同一個
        日曆。這裡不等時鐘走到 UTC 跨日前的那八小時才會紅（ADR 0058「how this can be
        seen red again」），把兩個日期都釘死：approved_at 是 UTC 17:00（台北隔天
        01:00），today_for_org 釘成台北那一天，兩者同一天，days_elapsed 該是 1。"""
        self._succeed_plan_and_tree()
        approval = self._approve().json()["tree"]["approval"]
        web.conn.execute(
            "UPDATE approval SET approved_at = %s WHERE id = %s",
            (datetime(2026, 1, 15, 17, 0, 0, tzinfo=UTC), approval["id"]),
        )
        web.conn.commit()
        with mock.patch.object(coresettings, "today_for_org", return_value=date(2026, 1, 16)):
            approval = self._get().json()["tree"]["approval"]
        self.assertEqual(approval["days_elapsed"], 1)
        self.assertEqual(approval["expected_to_date"], 1000.0)
        self.assertIsNone(approval["spend_to_date"])

    def test_binding_and_spend_survive_hash_but_reexpanding_does_not(self):
        """item 4/5/9：核准之後綁定活動、花費進來都不翻臉（`content_hash` 排除清單真的
        擋住這兩件事），超支只算核准日之後；同一個方案重展開才真的翻臉——不同的第一層
        節點名字，是真的不同的 content_hash，舊列不被改寫。"""
        # 票 M1：核准超支現在問組織時區的今天（ADR 0058），這裡跟著用同一個來源，不再用
        # datetime.now(UTC).date()——兩者在台北每天有 8 小時不是同一天，UTC 版本會把
        # 下面種的「核准當天」那筆花費種到 org 的窗口之外，spend_to_date 平白少算。
        today = coresettings.today_for_org(web.conn, org_id=coredb.DEV_ORG_ID)
        if today.day == 1:
            self.skipTest("今天是每月 1 號，核准日跟月初重疊，測不出時間窗切齊")
        month_start = today.replace(day=1)
        self._succeed_plan_and_tree()
        approval_before = self._approve().json()["tree"]["approval"]

        account_id = self._bind_one_campaign("活動一")  # 核准之後才綁定、才有花費
        self._seed_spend(account_id, "camp-1", month_start, spend=99999.0)  # 核准前（月初）
        self._seed_spend(account_id, "camp-1", today, spend=500.0)  # 核准當天
        approval_now = self._get().json()["tree"]["approval"]
        self.assertTrue(approval_now["matches_current_tree"])  # 綁定／花費不翻臉
        self.assertEqual(approval_now["spend_to_date"], 500.0)  # 月初那筆被排除

        schedule_jobs.PROVIDER = _fake(_tree_fenced("活動一（改過）"))
        resp = self.client.post(
            f"/api/schedule/brands/{self.brand['id']}/tree", json={"plan_index": 0}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()
        approval_after = self._get().json()["tree"]["approval"]
        self.assertFalse(approval_after["matches_current_tree"])
        self.assertEqual(approval_after["approved_at"], approval_before["approved_at"])
        self.assertEqual(approval_after["approved_amount"], approval_before["approved_amount"])

    def test_revoke_survives_and_respects_the_tenant_boundary(self):
        """item 6/7：撤回之後 null、列留著（`revoked_at`），另一個組織不能撤回這一列。"""
        self._succeed_plan_and_tree()
        approval_id = self._approve().json()["tree"]["approval"]["id"]
        resp = self.client.post(f"/api/schedule/brands/{self.brand['id']}/tree/approve/revoke")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIsNone(resp.json()["tree"]["approval"])
        self.assertIsNone(self._get().json()["tree"]["approval"])
        row = web.conn.execute("SELECT * FROM approval WHERE id = %s", (approval_id,)).fetchone()
        self.assertIsNotNone(row)  # nothing is deleted
        self.assertIsNotNone(row["revoked_at"])
        self.assertTrue(row["revoked_by"])
        second_id = self._approve().json()["tree"]["approval"]["id"]
        with self.assertRaises(ValueError):  # 找不到／不是你的同一個錯誤，比照 interrupts.resolve
            approval_mod.revoke(
                web.conn, approval_id=second_id, org_id="org_not_this_one", actor=ACTOR
            )
