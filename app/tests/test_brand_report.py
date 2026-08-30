"""app/tests/test_brand_report.py — 顧問分析報告（決策 0017、GitHub issue #4）。

見 app/brand_intelligence/report.py、repository.py 的 create_brand_report／get_latest_brand_report、
顧問分析報告 API。全程只用 FakeProvider，不發任何真實網路請求。
測試品牌一律虛構名：晨露茶飲、山嵐選物。
"""

import json
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.brand_intelligence import repository as repo
from app.brand_web import report_service
from app.brand_web import routes as report
from app.brand_web import routes_report_api as report_api
from app.core.db import DEV_ORG_ID  # noqa: E402
from app.llm import providers

ACTOR = "測試員"


def _sections(tag: str) -> dict:
    return {
        "positioning": {"summary": f"{tag}的品牌定位摘要，主打天然成分與透明溝通。",
                         "points": [f"{tag}主打成分透明", "鎖定注重健康的消費者"]},
        "market": {"summary": f"{tag}目前的市場與競爭觀察是電商通路持續成長。",
                   "points": ["電商通路增長", "社群口碑影響力大"]},
        "audience": {"summary": f"{tag}的主要受眾多為25至40歲重視健康的消費者。",
                     "points": ["重視成分安全", "偏好小包裝試用"]},
        "claims": {"summary": f"{tag}目前登錄的可用宣稱整理如下。",
                   "points": ["可以講天然萃取", "不得宣稱療效"]},
        "rhythm": {"summary": f"{tag}建議內容主軸以衛教與產品故事為主。",
                   "points": ["衛教內容為主", "產品故事為輔"]},
    }


def _fake(sections_dict=None, output_text=None) -> providers.FakeProvider:
    text = output_text if output_text is not None else json.dumps(sections_dict, ensure_ascii=False)
    return providers.FakeProvider(response=providers.ProviderResponse(
        output_text=text, structured=None,
        usage=providers.Usage(input_tokens=2000, output_tokens=1500), stop_reason="end_turn",
    ))


class BrandReportGenerateTest(unittest.TestCase):
    """直接測 report.generate()／repository，不經 HTTP。"""

    def setUp(self):
        self.brand = repo.create_brand(web.conn, name="晨露茶飲", client_name="測試客戶", actor=ACTOR, org_id=DEV_ORG_ID)

    def test_generate_success_stores_full_report(self):
        repo.create_brand_fact(web.conn, self.brand["id"], fact_type="positioning", label="定位",
                                value="主打冷萃茶飲、天然無糖", status="confirmed",
                                confirmed_by=ACTOR, actor=ACTOR)
        repo.create_brand_fact(web.conn, self.brand["id"], fact_type="tone", label="語調",
                                value="輕鬆親切", status="confirmed", confirmed_by=ACTOR, actor=ACTOR)

        fake = _fake(_sections("晨露茶飲"))
        with mock.patch.object(report, "PROVIDER", fake):
            ok, err = report.generate(web.conn, self.brand["id"], ACTOR)

        self.assertTrue(ok, err)
        self.assertIsNone(err)

        stored = repo.get_latest_brand_report(web.conn, self.brand["id"])
        self.assertIsNotNone(stored)
        for key in report.SECTION_KEYS:
            self.assertIn(key, stored["sections"])
            self.assertTrue(stored["sections"][key]["summary"].strip())

        self.assertTrue(stored["model"])
        self.assertTrue(stored["generated_at"])
        self.assertTrue(stored["llm_task_id"])
        self.assertEqual(stored["generated_by"], ACTOR)
        self.assertEqual(stored["brand_version"],
                         repo.get_brand(web.conn, self.brand["id"])["knowledge_version"])

        audit_rows = web.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'brand_report' AND action = 'create' "
            "AND brand_id = %s", (self.brand["id"],)
        ).fetchall()
        self.assertEqual(len(audit_rows), 1)

        task = web.conn.execute(
            "SELECT * FROM llm_task WHERE id = %s", (stored["llm_task_id"],)
        ).fetchone()
        self.assertEqual(task["status"], "succeeded")
        self.assertGreater(task["cost"], 0)

    def test_bad_format_does_not_store(self):
        with mock.patch.object(report, "PROVIDER", _fake(output_text="這不是 JSON")):
            ok, err = report.generate(web.conn, self.brand["id"], ACTOR)
        self.assertFalse(ok)
        self.assertTrue(err)
        n = web.conn.execute(
            "SELECT COUNT(*) AS n FROM brand_report WHERE brand_id = %s", (self.brand["id"],)
        ).fetchone()["n"]
        self.assertEqual(n, 0)

    def test_missing_section_key_does_not_store(self):
        broken = _sections("晨露茶飲")
        del broken["rhythm"]
        with mock.patch.object(report, "PROVIDER", _fake(broken)):
            ok, err = report.generate(web.conn, self.brand["id"], ACTOR)
        self.assertFalse(ok)
        self.assertTrue(err)
        n = web.conn.execute(
            "SELECT COUNT(*) AS n FROM brand_report WHERE brand_id = %s", (self.brand["id"],)
        ).fetchone()["n"]
        self.assertEqual(n, 0)

    def test_thin_data_still_generates(self):
        """決策 0013：0 條已確認事實也照樣生成。"""
        with mock.patch.object(report, "PROVIDER", _fake(_sections("晨露茶飲"))):
            ok, err = report.generate(web.conn, self.brand["id"], ACTOR)
        self.assertTrue(ok, err)
        stored = repo.get_latest_brand_report(web.conn, self.brand["id"])
        self.assertEqual(stored["source_fact_count"], 0)


class BrandReportHttpTest(unittest.TestCase):
    """經 HTTP 路由驗證頁面渲染、隔離、空狀態、過期標示、重複觸發守門。"""

    def setUp(self):
        self.client = TestClient(main.app)

    def _new_brand(self, name):
        b = repo.create_brand(web.conn, name=name, client_name=None, actor=ACTOR, org_id=DEV_ORG_ID)
        return b["id"]

    def test_empty_state(self):
        bid = self._new_brand("山嵐選物-空狀態")
        resp = self.client.get(f"/api/brands/{bid}/report")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()["report"])
        self.assertEqual(resp.json()["job"]["status"], "idle")

    def test_unknown_brand_is_404(self):
        resp = self.client.get("/api/brands/brd_不存在/report")
        self.assertEqual(resp.status_code, 404)

    def test_isolation_between_brands(self):
        morning_id = self._new_brand("晨露茶飲-隔離")
        mountain_id = self._new_brand("山嵐選物-隔離")

        with mock.patch.object(report, "PROVIDER", _fake(_sections("晨露機密內容"))):
            ok, err = report.generate(web.conn, morning_id, ACTOR)
        self.assertTrue(ok, err)
        with mock.patch.object(report, "PROVIDER", _fake(_sections("山嵐專屬內容"))):
            ok, err = report.generate(web.conn, mountain_id, ACTOR)
        self.assertTrue(ok, err)

        mountain_report = repo.get_latest_brand_report(web.conn, mountain_id)
        mountain_text = json.dumps(mountain_report["sections"], ensure_ascii=False)
        self.assertNotIn("晨露機密內容", mountain_text)

        body = self.client.get(f"/api/brands/{mountain_id}/report").json()
        page = json.dumps(body["report"]["sections"], ensure_ascii=False)
        self.assertNotIn("晨露機密內容", page)
        self.assertIn("山嵐專屬內容", page)

    def test_staleness_banner_on_page(self):
        bid = self._new_brand("晨露茶飲-過期")
        with mock.patch.object(report, "PROVIDER", _fake(_sections("晨露茶飲"))):
            ok, err = report.generate(web.conn, bid, ACTOR)
        self.assertTrue(ok, err)
        stored = repo.get_latest_brand_report(web.conn, bid)

        repo.create_brand_fact(web.conn, bid, actor=ACTOR, fact_type="positioning",
                               label="新事實", value="報告生成後新增", status="confirmed",
                               confirmed_by=ACTOR)
        body = self.client.get(f"/api/brands/{bid}/report").json()
        self.assertIsNotNone(body["report"]["staleness"])

        web.conn.execute("UPDATE brand_report SET brand_version = %s WHERE id = %s",
                          (repo.get_brand(web.conn, bid)["knowledge_version"], stored["id"]))
        web.conn.commit()
        body = self.client.get(f"/api/brands/{bid}/report").json()
        self.assertIsNone(body["report"]["staleness"])

    def test_progress_guards_against_duplicate_run(self):
        bid = self._new_brand("山嵐選物-防重複")
        fake = _fake(_sections("山嵐選物"))
        with mock.patch.object(report, "PROVIDER", fake):
            ok, error = report.generate(web.conn, bid, ACTOR)
        self.assertTrue(ok, error)
        self.assertTrue(report_service.recent(bid))
        self.assertEqual(len(fake.calls), 1)


class ReportBackgroundJobTest(unittest.TestCase):
    """票 dead-code-sweep 02：`brand_report_done` 沒登記在 CATEGORIES 時，`_notify()` 會在
    try 區塊外炸 ValueError，執行緒死掉、job 狀態永遠卡在 running（GET 一直顯示「正在整理
    五章」、POST 一直擋 400）。這裡直接呼叫 `_run_report`（不經執行緒，同步跑，斷言才不會
    flaky），驗證成功／失敗都能把 job 狀態帶出 running。"""

    def setUp(self):
        self.brand = repo.create_brand(web.conn, name="晨露茶飲-背景工作", client_name=None,
                                        actor=ACTOR, org_id=DEV_ORG_ID)
        report_api._report_jobs.clear()

    def tearDown(self):
        report_api._report_jobs.clear()

    def test_success_reaches_done(self):
        with mock.patch.object(report_service, "generate", return_value=(True, None)):
            report_api._run_report(self.brand["id"], ACTOR)
        state = report_api._report_jobs.get(self.brand["id"], {})
        self.assertEqual(state.get("status"), "done")

    def test_failure_reaches_failed_with_message(self):
        with mock.patch.object(report_service, "generate", return_value=(False, "provider 逾時")):
            report_api._run_report(self.brand["id"], ACTOR)
        state = report_api._report_jobs.get(self.brand["id"], {})
        self.assertEqual(state.get("status"), "failed")
        self.assertIn("provider 逾時", state.get("message", ""))

    def test_long_failure_message_does_not_raise_on_notify(self):
        """background_job.notify 截斷到 MAX_MESSAGE_LEN，長失敗訊息不該讓 enqueue 的長度檢查炸開。"""
        long_message = "發生錯誤" * 30
        with mock.patch.object(report_service, "generate", return_value=(False, long_message)):
            report_api._run_report(self.brand["id"], ACTOR)  # 不該 raise
        state = report_api._report_jobs.get(self.brand["id"], {})
        self.assertEqual(state.get("status"), "failed")


if __name__ == "__main__":
    unittest.main()
