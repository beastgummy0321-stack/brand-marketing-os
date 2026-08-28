"""顧問分析報告 React API：資料形狀、兩分鐘守門與背景工作狀態。"""

import json
import unittest

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.brand_intelligence import repository as repo
from app.brand_web import report_service
from app.brand_web import routes_report_api as report_api
from app.core.db import DEV_ORG_ID  # noqa: E402
from app.llm import providers

ACTOR = "測試員"


def _sections(tag: str) -> dict:
    return {
        "positioning": {"summary": f"{tag}定位摘要", "points": ["定位重點"]},
        "market": {"summary": f"{tag}市場摘要", "points": ["市場重點"]},
        "audience": {"summary": f"{tag}受眾摘要", "points": ["受眾重點"]},
        "claims": {"summary": f"{tag}宣稱摘要", "points": ["宣稱重點"]},
        "rhythm": {"summary": f"{tag}節奏摘要", "points": ["節奏重點"]},
    }


def _provider(tag: str) -> providers.FakeProvider:
    return providers.FakeProvider(response=providers.ProviderResponse(
        output_text=json.dumps(_sections(tag), ensure_ascii=False), structured=None,
        usage=providers.Usage(input_tokens=10, output_tokens=10), stop_reason="end_turn",
    ))


class BrandReportApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        report_api._report_jobs.clear()

    def tearDown(self):
        report_api._report_jobs.clear()

    def _brand_with_report(self, fact_count: int):
        brand = repo.create_brand(web.conn, name=f"報告 API 測試 {fact_count}", client_name=None, actor=ACTOR, org_id=DEV_ORG_ID)
        for index in range(fact_count):
            repo.create_brand_fact(
                web.conn, brand["id"], fact_type="positioning", label=f"事實 {index}",
                value=f"內容 {index}", status="confirmed", confirmed_by=ACTOR, actor=ACTOR,
            )
        ok, error = report_service.generate(
            web.conn, brand["id"], ACTOR, provider=_provider(brand["name"])
        )
        self.assertTrue(ok, error)
        return brand

    def test_generate_with_provider_keeps_default_provider_unchanged(self):
        brand = repo.create_brand(web.conn, name="注入 Provider 報告", client_name=None, actor=ACTOR, org_id=DEV_ORG_ID)
        default_provider = report_service.PROVIDER

        ok, error = report_service.generate(
            web.conn, brand["id"], ACTOR, provider=_provider(brand["name"])
        )

        self.assertTrue(ok, error)
        self.assertIs(report_service.PROVIDER, default_provider)

    def test_get_returns_fixed_five_sections_and_thin_data_boundary(self):
        four = self._brand_with_report(4)
        five = self._brand_with_report(5)

        four_data = self.client.get(f"/api/brands/{four['id']}/report").json()
        five_data = self.client.get(f"/api/brands/{five['id']}/report").json()

        self.assertEqual(
            [item["label"] for item in four_data["report"]["sections"]],
            ["品牌定位", "市場與競爭觀察", "受眾洞察", "可用宣稱與紅線", "建議節奏方向"],
        )
        self.assertTrue(four_data["report"]["thin_data"])
        self.assertFalse(five_data["report"]["thin_data"])
        self.assertEqual(four_data["job"], {"status": "idle"})

    def test_recent_post_is_rejected_with_exact_message(self):
        brand = self._brand_with_report(0)

        response = self.client.post(f"/api/brands/{brand['id']}/report/generate")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.json()), {"detail"})

    def test_get_exposes_running_job(self):
        brand = repo.create_brand(web.conn, name="執行中報告", client_name=None, actor=ACTOR, org_id=DEV_ORG_ID)
        report_api._report_jobs.set(brand["id"], {
            "status": "running", "stage": "正在整理五章",
            "started_at": "2026-08-20T04:11:02+00:00", "brand_id": brand["id"],
        })

        response = self.client.get(f"/api/brands/{brand['id']}/report")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["report"], None)
        self.assertEqual(response.json()["job"]["status"], "running")

    def test_missing_brand_returns_json_404_for_get_and_post(self):
        brand_id = "missing-brand"

        get_response = self.client.get(f"/api/brands/{brand_id}/report")
        post_response = self.client.post(f"/api/brands/{brand_id}/report/generate")

        self.assertEqual(get_response.status_code, 404)
        self.assertEqual(set(get_response.json()), {"detail"})
        self.assertEqual(post_response.status_code, 404)
        self.assertEqual(set(post_response.json()), {"detail"})
