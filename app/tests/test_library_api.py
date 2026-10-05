"""app/tests/test_library_api.py — 品牌智庫 JSON API（票 B2-library 第二段）。

見 app/brand_intelligence/routes_library.py、repository_channels.py、customer_voice.py
的 COST_CUSTOMER_VOICE_EXTRACTION 超預算檢查。全程只用 FakeProvider，不發任何真實網路
請求。測試品牌一律虛構名。
"""

import json
import os
import time
import unittest
from unittest import mock
from uuid import uuid4

from fastapi.testclient import TestClient

import app.background as background_module
import app.brand_web as brand_web_module
import app.main as main
import app.shared.web as web
from app.brand_intelligence import repository as repo
from app.brand_web import routes_library as customer_voice
from app.core import db as coredb
from app.core import interrupts as core_interrupts
from app.core import settings as core_settings
from app.core.db import new_id, now_iso
from app.identity import repository as identity_repo
from app.llm import providers

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-fake-library-api-test")

ACTOR = "測試員"




def _fake(items=None, output_text=None) -> providers.FakeProvider:
    if output_text is None:
        output_text = json.dumps({"items": items if items is not None else []}, ensure_ascii=False)
    return providers.FakeProvider(response=providers.ProviderResponse(
        output_text=output_text, structured=None,
        usage=providers.Usage(input_tokens=10, output_tokens=10), stop_reason="end_turn",
    ))


def _spend(conn, brand_id: str, cost: float) -> None:
    conn.execute(
        "INSERT INTO llm_task (id, org_id, brand_id, task_type, context_scope_json,"
        " input_context_ids_json, input_context_hash, knowledge_item_ids_json,"
        " brand_version, prompt_template_id, prompt_template_version, provider, model,"
        " status, attempt_no, cost, started_at, finished_at)"
        " VALUES (%s, %s, %s, 't', '{}', '[]', '', '[]', 1, 'p', 'v1', 'seed', 'seed',"
        " 'succeeded', 1, %s, %s, %s)",
        (new_id("llm"), coredb.DEV_ORG_ID, brand_id, cost, now_iso(), now_iso()),
    )
    conn.commit()


class LibraryBundleTest(unittest.TestCase):
    """GET /api/library/brands/{brand_id} 整包形狀（契約 LibraryData TS type）。"""

    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = repo.create_brand(web.conn, name="晨露茶飲－智庫整包", client_name="測試客戶",
                                        actor=ACTOR, org_id=coredb.DEV_ORG_ID)
        self.bid = self.brand["id"]

    def test_envelope_and_empty_shape(self):
        resp = self.client.get(f"/api/library/brands/{self.bid}")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("data", body)
        self.assertIn("generated_at", body)
        data = body["data"]
        for key in ("brand", "products", "facts", "rules", "claims", "assets",
                    "channels", "customer_voices"):
            self.assertIn(key, data)
        self.assertEqual(data["facts"], [])
        self.assertEqual(data["brand"]["name"], "晨露茶飲－智庫整包")
        self.assertEqual(data["brand"]["delete_impact"], [])

    def test_brand_regulatory_regime_in_bundle(self):
        """F34-I01（Contract R）：新品牌是 None；facade 設了之後整包帶 "food_tw"。"""
        resp = self.client.get(f"/api/library/brands/{self.bid}")
        self.assertIsNone(resp.json()["data"]["brand"]["regulatory_regime"])
        repo.set_regulatory_regime(web.conn, self.bid, "food_tw", actor=ACTOR)
        resp = self.client.get(f"/api/library/brands/{self.bid}")
        self.assertEqual(resp.json()["data"]["brand"]["regulatory_regime"], "food_tw")

    def test_unknown_brand_is_404(self):
        resp = self.client.get("/api/library/brands/brd_不存在")
        self.assertEqual(resp.status_code, 404)

    def test_fact_shape_fields_match_contract(self):
        repo.create_brand_fact(web.conn, self.bid, actor=ACTOR, fact_type="positioning",
                                label="定位", value="精品茶飲", status="confirmed",
                                confirmed_by=ACTOR)
        data = self.client.get(f"/api/library/brands/{self.bid}").json()["data"]
        self.assertEqual(len(data["facts"]), 1)
        fact = data["facts"][0]
        self.assertEqual(
            set(fact.keys()),
            {"id", "fact_type", "fact_type_label", "fact_key", "fact_key_label", "label", "value", "status",
             "confirmed_by", "confirmed_at", "stale_label", "source_reference"},
        )
        self.assertEqual(fact["fact_type_label"], "定位")
        self.assertIsNone(fact["fact_key"])  # F38-I01: only proof facts carry a kind
        self.assertIsNone(fact["fact_key_label"])
        self.assertIsInstance(fact["confirmed_at"], str)  # ISO 字串，不是 datetime 物件

    def test_fact_confirmer_user_id_reads_as_the_members_email(self):
        """F47-I03 (drill-10 外觀 #11): 「確認人」 in the bundle and in a write response is the member's
        e-mail, never the stored user id; a typed name stays as typed."""
        member = uuid4()
        email = f"lib-confirmer-{member.hex[:8]}@example.com"
        identity_repo.create_user(web.conn, member, email)
        identity_repo.create_membership(web.conn, coredb.DEV_ORG_ID, member, "member")
        repo.create_brand_fact(web.conn, self.bid, actor=ACTOR, fact_type="positioning", label="成員確認",
                               value="v", status="confirmed", confirmed_by=str(member))
        repo.create_brand_fact(web.conn, self.bid, actor=ACTOR, fact_type="positioning", label="打字確認",
                               value="v", status="confirmed", confirmed_by="小陳")
        facts = self.client.get(f"/api/library/brands/{self.bid}").json()["data"]["facts"]
        self.assertEqual({f["label"]: f["confirmed_by"] for f in facts}, {"成員確認": email, "打字確認": "小陳"})
        row = next(f for f in repo.list_brand_facts(web.conn, self.bid) if f["label"] == "成員確認")
        self.assertEqual(customer_voice._fact_shape(self.bid, row)["confirmed_by"], email)

    def test_policy_fact_in_bundle(self):
        """F42-I01: a store policy saved by onboarding shows in the library's facts with its
        type label 「全店政策」, its registry label and the composed sentence."""
        repo.save_brand_policies(web.conn, self.bid,
                                 [{"key": "ship_threshold", "params": {"threshold": "999"}}], actor=ACTOR)
        data = self.client.get(f"/api/library/brands/{self.bid}").json()["data"]
        [fact] = data["facts"]
        self.assertEqual(fact["fact_type"], "policy")
        self.assertEqual(fact["fact_type_label"], "全店政策")
        self.assertEqual(fact["fact_key"], "ship_threshold")
        self.assertEqual(fact["label"], "滿額免運")
        self.assertEqual(fact["value"], "滿 NT$999 免運")
        self.assertEqual(fact["status"], "confirmed")

    def test_rule_claim_asset_channel_shape_fields_match_contract(self):
        rule = repo.create_rule(web.conn, self.bid, actor=ACTOR, rule_type="tone",
                                 content="不能用「最」字", severity="hard")
        repo.create_claim(web.conn, self.bid, actor=ACTOR, claim_text="無添加防腐劑",
                           claim_type="high_risk")
        repo.create_channel(web.conn, self.bid, actor=ACTOR, channel_type="website",
                             name="官網", identifier="https://example.com", org_id=coredb.DEV_ORG_ID)
        data = self.client.get(f"/api/library/brands/{self.bid}").json()["data"]

        self.assertEqual(
            set(data["rules"][0].keys()),
            {"id", "rule_type", "rule_type_label", "content", "severity", "product_id",
             "scope_label", "source_reference"},
        )
        self.assertEqual(data["rules"][0]["severity"], "hard")
        self.assertEqual(data["rules"][0]["id"], rule["id"])

        claim = data["claims"][0]
        self.assertEqual(
            set(claim.keys()),
            {"id", "claim_text", "claim_type", "product_id", "scope_label",
             "evidence_source_reference"},
        )
        # 高風險缺佐證：evidence_source_reference 應為 None，前端才會畫警示（S5.20）
        self.assertIsNone(claim["evidence_source_reference"])

        channel = data["channels"][0]
        self.assertEqual(
            set(channel.keys()),
            {"id", "channel_type", "channel_type_label", "name", "identifier", "status"},
        )
        self.assertEqual(channel["channel_type_label"], "官方網站")


class ChannelEditDeleteTest(unittest.TestCase):
    """自有渠道編輯／刪除（S5.31，本票新補）。"""

    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = repo.create_brand(web.conn, name="山嵐選物－渠道", client_name=None, actor=ACTOR, org_id=coredb.DEV_ORG_ID)
        self.bid = self.brand["id"]
        self.channel = repo.create_channel(web.conn, self.bid, actor=ACTOR, channel_type="website",
                                            name="官網", identifier="https://old.example.com", org_id=coredb.DEV_ORG_ID)

    def test_edit_updates_fields_and_audit(self):
        repo.update_channel(
            web.conn, self.bid, self.channel["id"], actor=ACTOR, channel_type="fb_page",
            name="粉專", identifier="https://fb.com/x", status="inactive",
        )
        after = repo.get_channel(web.conn, self.bid, self.channel["id"])
        self.assertEqual(after["channel_type"], "fb_page")
        self.assertEqual(after["name"], "粉專")
        self.assertEqual(after["status"], "inactive")
        audit = web.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'owned_channel' AND action = 'update' "
            "AND entity_id = %s", (self.channel["id"],)
        ).fetchone()
        self.assertIsNotNone(audit)

    def test_edit_validation_error_returns_400(self):
        with self.assertRaisesRegex(ValueError, "channel_type"):
            repo.update_channel(web.conn, self.bid, self.channel["id"], actor=ACTOR,
                                channel_type="", name="", identifier="", status="active")
        unchanged = repo.get_channel(web.conn, self.bid, self.channel["id"])
        self.assertEqual(unchanged["name"], "官網")

    def test_edit_unknown_channel_is_404(self):
        with self.assertRaisesRegex(ValueError, "找不到"):
            repo.update_channel(web.conn, self.bid, "ch_不存在", actor=ACTOR,
                                channel_type="website", name="x", identifier="y", status="active")

    def test_delete_removes_row_and_writes_audit(self):
        repo.delete_channel(web.conn, self.bid, self.channel["id"], actor=ACTOR)
        self.assertIsNone(repo.get_channel(web.conn, self.bid, self.channel["id"]))
        audit = web.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'owned_channel' AND action = 'delete' "
            "AND entity_id = %s", (self.channel["id"],)
        ).fetchone()
        self.assertIsNotNone(audit)

    def test_delete_unknown_channel_is_404(self):
        with self.assertRaisesRegex(ValueError, "找不到"):
            repo.delete_channel(web.conn, self.bid, "ch_不存在", actor=ACTOR)


class CustomerVoiceBackgroundTest(unittest.TestCase):
    """顧客原話貼入＋AI 抽取（S5.40–S5.42；票 08：從行程內執行緒搬上
    `app.background` 佇列）。"""

    def setUp(self):
        self.client = TestClient(main.app)
        # 票 08：這個測試模組自己有一份 schema（見 conftest.py），要重新掛一次
        # `background.customer_voice_extraction` 這三個 task——DSN 換了 App 整顆重建，
        # 跟 `test_schedule.py` `schedule_module.register_tasks()` 同一個理由。
        brand_web_module.register(main.app)
        self.brand = repo.create_brand(web.conn, name="晨露茶飲－背景抽取", client_name=None,
                                        actor=ACTOR, org_id=coredb.DEV_ORG_ID)
        self.bid = self.brand["id"]

    def _run_worker(self) -> None:
        """票 08：POST 現在只 enqueue，真正打代理在 worker 裡——先 commit 這個 request
        留下的異動，worker 自己開一條新連線，看不到還沒 commit 的交易（比照
        `test_schedule.py` `_run_worker()`）。"""
        web.conn.commit()
        background_module.app().run_worker(wait=False)

    def test_submit_returns_immediately_with_job_key(self):
        """不能同步擋住 request：POST 本身要在很短時間內回應（不等 AI 跑完）。

        worker 讀 customer_voice.PROVIDER 是模組層即時查值，`mock.patch.object` 一還原
        它就會改回真的 AnthropicProvider——所以這裡要等 worker 真的跑完才能離開 `with`
        區塊，不然 worker 可能讀到還原後的真 PROVIDER，變成一次真實網路請求
        （安全規則：測試禁止真實網路請求）。"""
        fake = _fake([{"task_layer": "functional", "quote": "測試引言",
                        "insight": "測試重點", "signal": "unprompted"}])
        with mock.patch.object(customer_voice, "PROVIDER", fake):
            started = time.time()
            resp = self.client.post(f"/api/library/brands/{self.bid}/customer-voice", json={
                "source_channel": "ptt", "source_detail": "", "raw_text": "測試原文",
            })
            elapsed = time.time() - started
            self.assertEqual(resp.status_code, 200)
            self.assertIn("job_key", resp.json())
            self.assertLess(elapsed, 1.0, "POST 不該等 AI 抽取跑完才回應")
            self._run_worker()  # worker 真的跑完才放行 mock 還原

    def test_job_completes_stores_row_and_enqueues_notification(self):
        fake = _fake([{"task_layer": "functional", "quote": "喝了三天真的有感",
                        "insight": "見效時間是重點", "signal": "unprompted"}])
        with mock.patch.object(customer_voice, "PROVIDER", fake):
            job_key = self.client.post(
                f"/api/library/brands/{self.bid}/customer-voice",
                json={"source_channel": "dcard", "raw_text": "喝了三天真的有感"},
            ).json()["job_key"]
            self._run_worker()
            status = self.client.get(
                f"/api/library/brands/{self.bid}/customer-voice/jobs/{job_key}"
            ).json()

        self.assertEqual(status["status"], "done")
        self.assertEqual(len(status["result"]["extraction"]), 1)

        # 落庫（下次組簡報要讀得到）
        stored = repo.list_customer_voices(web.conn, self.bid)
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["raw_text"], "喝了三天真的有感")

        # 收件匣通知（五鐵則③）
        open_items = core_interrupts.list_open(web.conn, org_id=coredb.DEV_ORG_ID, brand_id=self.bid)
        matches = [r for r in open_items if r["category"] == "customer_voice_extraction_done"]
        self.assertEqual(len(matches), 1)
        self.assertLessEqual(len(matches[0]["message"]), core_interrupts.MAX_MESSAGE_LEN)

    def test_job_failure_does_not_store_and_still_notifies(self):
        fake_bad = _fake(output_text="這不是 JSON")
        with mock.patch.object(customer_voice, "PROVIDER", fake_bad):
            job_key = self.client.post(
                f"/api/library/brands/{self.bid}/customer-voice",
                json={"source_channel": "ptt", "raw_text": "會抽取失敗的原文"},
            ).json()["job_key"]
            self._run_worker()
            status = self.client.get(
                f"/api/library/brands/{self.bid}/customer-voice/jobs/{job_key}"
            ).json()

        self.assertEqual(status["status"], "failed")
        self.assertTrue(status["message"])
        self.assertEqual(repo.list_customer_voices(web.conn, self.bid), [])
        open_items = core_interrupts.list_open(web.conn, org_id=coredb.DEV_ORG_ID, brand_id=self.bid)
        self.assertEqual(
            len([r for r in open_items if r["category"] == "customer_voice_extraction_done"]), 1)

    def test_missing_raw_text_is_rejected_before_any_llm_call(self):
        fake = _fake([{"task_layer": "functional", "quote": "不該被呼叫",
                        "insight": "不該被呼叫", "signal": "unprompted"}])
        with mock.patch.object(customer_voice, "PROVIDER", fake):
            resp = self.client.post(f"/api/library/brands/{self.bid}/customer-voice", json={
                "source_channel": "ptt", "raw_text": "",
            })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(len(fake.calls), 0)

    def test_over_budget_blocks_before_any_llm_call(self):
        """票要求：extract() 前補預算檢查，比照 product_ai._scan_budget_error 模式。"""
        core_settings.set_setting(web.conn, "intake_budget_limit", "1", org_id=coredb.DEV_ORG_ID)
        _spend(web.conn, self.bid, 5.0)
        fake = _fake([{"task_layer": "functional", "quote": "不該被呼叫",
                        "insight": "不該被呼叫", "signal": "unprompted"}])
        with mock.patch.object(customer_voice, "PROVIDER", fake):
            resp = self.client.post(f"/api/library/brands/{self.bid}/customer-voice", json={
                "source_channel": "ptt", "raw_text": "這筆會被擋在花費上限外",
            })
        self.assertEqual(resp.status_code, 422)
        self.assertIn("US$", resp.json()["error"])
        self.assertEqual(len(fake.calls), 0)
        self.assertEqual(repo.list_customer_voices(web.conn, self.bid), [])

    def test_job_status_unknown_key_reports_unknown_not_error(self):
        """F50-I07（Contract J，intake #10）：沒有 job 也沒有 AI 呼叫的 job_key 回
        `unknown`，不是 404，也不再猜「還在跑」。剛送出、worker 還沒撿走的那一刻佇列裡已經
        有 job，讀得到 running，所以不會被誤判成錯誤。"""
        resp = self.client.get(f"/api/library/brands/{self.bid}/customer-voice/jobs/job_不存在")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "unknown"})


if __name__ == "__main__":
    unittest.main()
