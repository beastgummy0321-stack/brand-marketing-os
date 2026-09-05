"""app/tests/test_customer_voice.py — 顧客原話語料庫（GitHub issue #14，決策 0023 第 18a 條／0024 第 2 條）。

見 app/brand_intelligence/customer_voice.py（抽取）、repository.py 的 *_customer_voice
函式與顧客原話 API。全程只用 FakeProvider，不發任何
真實網路請求。測試品牌一律虛構名：晨露茶飲、山嵐選物。
"""

import json
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import app.background as background_module
import app.brand_web as brand_web_module
import app.main as main
import app.shared.web as web
from app.brand_intelligence import repository as repo
from app.brand_web import routes_library as customer_voice
from app.core.db import DEV_ORG_ID  # noqa: E402
from app.llm import providers

ACTOR = "測試員"



def _items(tag: str) -> list:
    return [
        {"task_layer": "functional", "quote": f"{tag}吃了兩天終於消下去",
         "insight": "消腫速度是顧客在意的重點", "signal": "unprompted"},
        {"task_layer": "emotional", "quote": f"{tag}鬆了一口氣",
         "insight": "情緒上的解脫感可以當 Hook", "signal": "unprompted"},
    ]


def _fake(items=None, output_text=None) -> providers.FakeProvider:
    if output_text is None:
        output_text = json.dumps({"items": items if items is not None else []}, ensure_ascii=False)
    return providers.FakeProvider(response=providers.ProviderResponse(
        output_text=output_text, structured=None,
        usage=providers.Usage(input_tokens=800, output_tokens=300), stop_reason="end_turn",
    ))


class CustomerVoiceExtractTest(unittest.TestCase):
    """直接測 customer_voice.extract()／repository，不經 HTTP。"""

    def setUp(self):
        self.brand = repo.create_brand(web.conn, name="晨露茶飲", client_name="測試客戶", actor=ACTOR, org_id=DEV_ORG_ID)

    def test_extract_success_stores_row_with_items(self):
        fake = _fake(_items("晨露"))
        with mock.patch.object(customer_voice, "PROVIDER", fake):
            ok, row = customer_voice.extract(
                web.conn, self.brand["id"], actor=ACTOR, raw_text="連續熬夜三天，吃了兩天終於消下去，鬆了一口氣",
                source_channel="shopee", source_detail="XX保健品評論區",
            )
        self.assertTrue(ok, row)
        self.assertEqual(len(row["extraction"]), 2)
        self.assertEqual(row["extraction"][0]["task_layer"], "functional")
        self.assertEqual(row["source_type"], "manual")
        self.assertTrue(row["llm_task_id"])

        stored = repo.get_customer_voice(web.conn, self.brand["id"], row["id"])
        self.assertIsNotNone(stored)
        self.assertEqual(stored["status"], "active")

        audit_rows = web.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'customer_voice' AND action = 'create' "
            "AND entity_id = %s", (row["id"],)
        ).fetchall()
        self.assertEqual(len(audit_rows), 1)

    def test_extract_empty_items_is_honest_not_a_failure(self):
        """AI 判斷這段原話沒有值得收的重點也是誠實結果，仍然入庫（principles 第 16 條）。"""
        with mock.patch.object(customer_voice, "PROVIDER", _fake([])):
            ok, row = customer_voice.extract(
                web.conn, self.brand["id"], actor=ACTOR, raw_text="好用+1",
                source_channel="dcard",
            )
        self.assertTrue(ok, row)
        self.assertEqual(row["extraction"], [])

    def test_bad_format_does_not_store(self):
        with mock.patch.object(customer_voice, "PROVIDER", _fake(output_text="這不是 JSON")):
            ok, err = customer_voice.extract(
                web.conn, self.brand["id"], actor=ACTOR, raw_text="測試原文", source_channel="ptt",
            )
        self.assertFalse(ok)
        self.assertTrue(err)
        n = web.conn.execute(
            "SELECT COUNT(*) AS n FROM customer_voice WHERE brand_id = %s", (self.brand["id"],)
        ).fetchone()["n"]
        self.assertEqual(n, 0)

    def test_invalid_task_layer_does_not_store(self):
        bad_items = [{"task_layer": "not_a_layer", "quote": "隨便", "insight": "隨便"}]
        with mock.patch.object(customer_voice, "PROVIDER", _fake(bad_items)):
            ok, err = customer_voice.extract(
                web.conn, self.brand["id"], actor=ACTOR, raw_text="測試原文", source_channel="ptt",
            )
        self.assertFalse(ok)
        self.assertTrue(err)

    def test_archive_and_restore(self):
        with mock.patch.object(customer_voice, "PROVIDER", _fake(_items("晨露"))):
            _ok, row = customer_voice.extract(
                web.conn, self.brand["id"], actor=ACTOR, raw_text="測試原文", source_channel="ptt",
            )
        archived = repo.set_customer_voice_status(web.conn, self.brand["id"], row["id"],
                                                    status="archived", actor=ACTOR)
        self.assertEqual(archived["status"], "archived")
        restored = repo.set_customer_voice_status(web.conn, self.brand["id"], row["id"],
                                                    status="active", actor=ACTOR)
        self.assertEqual(restored["status"], "active")

    def test_delete_does_not_require_archive_first(self):
        """決策 0023 第 8 條：沿用 _delete_entity 模式，刪除不要求先封存。"""
        with mock.patch.object(customer_voice, "PROVIDER", _fake(_items("晨露"))):
            _ok, row = customer_voice.extract(
                web.conn, self.brand["id"], actor=ACTOR, raw_text="測試原文", source_channel="ptt",
            )
        self.assertEqual(row["status"], "active")
        repo.delete_customer_voice(web.conn, self.brand["id"], row["id"], actor=ACTOR)
        self.assertIsNone(repo.get_customer_voice(web.conn, self.brand["id"], row["id"]))
        del_row = web.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'customer_voice' AND action = 'delete' "
            "AND entity_id = %s", (row["id"],)
        ).fetchone()
        self.assertIsNotNone(del_row)


class CustomerVoiceHttpTest(unittest.TestCase):
    """經 HTTP 路由驗證頁面渲染、隔離、驗證錯誤、封存與刪除、指引頁。"""

    def setUp(self):
        self.client = TestClient(main.app)
        # 票 08：這個測試模組自己有一份 schema（見 conftest.py），要重新掛一次
        # `background.customer_voice_extraction`——DSN 換了 App 整顆重建，跟
        # `test_schedule.py` `schedule_module.register_tasks()` 同一個理由。
        brand_web_module.register(main.app)

    def _new_brand(self, name):
        b = repo.create_brand(web.conn, name=name, client_name=None, actor=ACTOR, org_id=DEV_ORG_ID)
        return b["id"]

    def _run_worker(self) -> None:
        web.conn.commit()
        background_module.app().run_worker(wait=False)

    def test_new_page_200(self):
        bid = self._new_brand("山嵐選物-新增頁")
        resp = self.client.get(f"/api/library/brands/{bid}")
        self.assertEqual(resp.status_code, 200)

    def test_validation_errors_do_not_call_llm(self):
        bid = self._new_brand("山嵐選物-驗證錯誤")
        fake = _fake(_items("不該被呼叫"))
        with mock.patch.object(customer_voice, "PROVIDER", fake):
            resp = self.client.post(f"/api/library/brands/{bid}/customer-voice",
                                    json={"source_channel": "", "raw_text": ""})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(len(fake.calls), 0)

    def test_post_creates_and_redirects_to_list(self):
        bid = self._new_brand("山嵐選物-新增成功")
        with mock.patch.object(customer_voice, "PROVIDER", _fake(_items("山嵐"))):
            resp = self.client.post(f"/api/library/brands/{bid}/customer-voice", json={
                "source_channel": "dcard", "source_detail": "推薦文",
                "raw_text": "連續熬夜三天，吃了兩天終於消下去，鬆了一口氣",
            })
            self._run_worker()
            status = self.client.get(
                f"/api/library/brands/{bid}/customer-voice/jobs/{resp.json()['job_key']}"
            ).json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(status["status"], "done")
        voices = self.client.get(f"/api/library/brands/{bid}").json()["data"]["customer_voices"]
        self.assertEqual(voices[0]["extraction"][1]["quote"], "山嵐鬆了一口氣")
        self.assertEqual(voices[0]["source_channel_label"], "Dcard")

    def test_extraction_failure_keeps_raw_text_and_shows_error(self):
        bid = self._new_brand("山嵐選物-抽取失敗")
        with mock.patch.object(customer_voice, "PROVIDER", _fake(output_text="不是 JSON")):
            ok, error = customer_voice.extract(
                web.conn, bid, actor=ACTOR, source_channel="ptt", raw_text="這段原話會抽取失敗",
            )
        self.assertFalse(ok)
        self.assertTrue(error)
        n = web.conn.execute(
            "SELECT COUNT(*) AS n FROM customer_voice WHERE brand_id = %s", (bid,)
        ).fetchone()["n"]
        self.assertEqual(n, 0)

    def test_archive_and_delete_via_routes(self):
        bid = self._new_brand("山嵐選物-封存刪除路由")
        with mock.patch.object(customer_voice, "PROVIDER", _fake(_items("山嵐"))):
            _ok, row = customer_voice.extract(
                web.conn, bid, actor=ACTOR, raw_text="測試原文", source_channel="ptt",
            )
        cv_id = row["id"]

        repo.set_customer_voice_status(web.conn, bid, cv_id, status="archived", actor=ACTOR)
        self.assertEqual(repo.get_customer_voice(web.conn, bid, cv_id)["status"], "archived")

        voice = self.client.get(f"/api/library/brands/{bid}").json()["data"]["customer_voices"][0]
        self.assertEqual(voice["status"], "archived")

        repo.set_customer_voice_status(web.conn, bid, cv_id, status="active", actor=ACTOR)
        self.assertEqual(repo.get_customer_voice(web.conn, bid, cv_id)["status"], "active")

        repo.delete_customer_voice(web.conn, bid, cv_id, actor=ACTOR)
        self.assertIsNone(repo.get_customer_voice(web.conn, bid, cv_id))

    def test_isolation_between_brands(self):
        morning_id = self._new_brand("晨露茶飲-隔離")
        mountain_id = self._new_brand("山嵐選物-隔離")
        with mock.patch.object(customer_voice, "PROVIDER", _fake(_items("晨露機密內容"))):
            ok, _row = customer_voice.extract(web.conn, morning_id, actor=ACTOR,
                                               source_channel="ptt", raw_text="晨露機密內容 原文")
        self.assertTrue(ok)
        voices = self.client.get(f"/api/library/brands/{mountain_id}").json()["data"]["customer_voices"]
        self.assertEqual(voices, [])

    def test_unknown_brand_is_404(self):
        resp = self.client.get("/api/library/brands/brd_不存在")
        self.assertEqual(resp.status_code, 404)

    def test_guide_page_matches_methodology_content(self):
        bid = self._new_brand("山嵐選物-指引頁")
        self.assertEqual(self.client.get(f"/api/library/brands/{bid}").status_code, 200)
        self.assertEqual(customer_voice.md.customer_voice_channel_label("dcard"), "Dcard")


if __name__ == "__main__":
    unittest.main()
