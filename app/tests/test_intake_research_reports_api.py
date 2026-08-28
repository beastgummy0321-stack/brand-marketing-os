"""調研報告回顯 API。全程使用隔離資料庫與虛構品牌，不發真實網路請求。"""

import os
import unittest
from datetime import datetime

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-fake-research-reports-api-test")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
import app.shared.web as web  # noqa: E402
from app.brand_intelligence import repository as brand_repo  # noqa: E402
from app.core import db as coredb  # noqa: E402
from app.core.db import new_id, now_utc  # noqa: E402
from app.intake import repository as intake_repo  # noqa: E402
from app.intake import routes_api as api  # noqa: E402


class ResearchReportApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        brand = brand_repo.create_brand(
            web.conn, name=f"虛構調研回顯品牌{new_id('test')}", client_name=None, actor="測試員", org_id=coredb.DEV_ORG_ID,
        )
        self.brand_id = brand["id"]

    def _report(self, raw_text: str, created_at: str) -> str:
        draft = intake_repo.create_draft(
            web.conn, self.brand_id, "測試用描述", [], [], actor="測試員",
        )
        intake_repo.update_draft(
            web.conn, self.brand_id, draft["id"], handoff_depth="deep", paste_raw=raw_text,
        )
        intake_repo.complete_draft(web.conn, self.brand_id, draft["id"])
        web.conn.execute(
            "UPDATE intake_draft SET created_at = %s WHERE id = %s",
            (datetime.fromisoformat(created_at), draft["id"]),
        )
        web.conn.commit()
        return draft["id"]

    def _confirmed_item(self, draft_id: str) -> None:
        web.conn.execute(
            """INSERT INTO intake_item (
                id, org_id, intake_draft_id, brand_id, row_no, raw_row, kind, category, title,
                content, scope_raw, outcome, created_at
            ) VALUES (%s, %s, %s, %s, 1, '測試原文', 'brand_fact', 'positioning', '測試標題',
                      '測試內容', '整個品牌', 'confirmed', %s)""",
            (new_id("iit"), coredb.DEV_ORG_ID, draft_id, self.brand_id, now_utc()),
        )
        web.conn.commit()

    def test_list_returns_newest_first_with_confirmed_counts(self):
        older = self._report("1. 市場與品類\n較早內容", "2026-07-01T10:00:00+00:00")
        self._confirmed_item(older)
        self._confirmed_item(older)
        newer = self._report("1. 市場與品類\n較新內容", "2026-08-15T10:00:00+00:00")

        response = self.client.get(f"/api/intake/brands/{self.brand_id}/research-reports")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIn("generated_at", body)
        self.assertEqual(
            body["data"],
            [
                {"id": newer, "created_at": "2026-08-15T10:00:00+00:00", "confirmed_count": 0},
                {"id": older, "created_at": "2026-07-01T10:00:00+00:00", "confirmed_count": 2},
            ],
        )

    def test_detail_returns_original_text_and_detected_sections(self):
        raw_text = (
            "調研前言，原樣保留。\n"
            "# 一、市場與品類\n市場內容\n"
            "## 二、競品拆解\n競品內容\n"
        )
        draft_id = self._report(raw_text, "2026-08-15T10:00:00+00:00")

        response = self.client.get(
            f"/api/intake/brands/{self.brand_id}/research-reports/{draft_id}",
        )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["id"], draft_id)
        self.assertEqual(data["paste_raw"], raw_text)
        self.assertEqual(data["leading_text"], "調研前言，原樣保留。\n")
        self.assertEqual(
            data["sections"],
            [
                {"title": "市場與品類", "raw_text": "# 一、市場與品類\n市場內容\n"},
                {"title": "競品拆解", "raw_text": "## 二、競品拆解\n競品內容\n"},
            ],
        )

    def test_empty_brand_returns_an_empty_list(self):
        response = self.client.get(f"/api/intake/brands/{self.brand_id}/research-reports")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["data"], [])


class ReportSectionDetectionTest(unittest.TestCase):
    def test_deep_scope_headings_keep_every_original_character(self):
        raw_text = "調研前言\n" + "".join(
            f"{index}. {title}\n第 {index} 章原文\n"
            for index, title in enumerate(api.REPORT_SECTION_TITLES, start=1)
        )

        leading_text, sections = api.detect_report_sections(raw_text)

        self.assertEqual(leading_text + "".join(section["raw_text"] for section in sections), raw_text)
        self.assertEqual([section["title"] for section in sections], list(api.REPORT_SECTION_TITLES))


if __name__ == "__main__":
    unittest.main()
