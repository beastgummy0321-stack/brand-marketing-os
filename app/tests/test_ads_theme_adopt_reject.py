# -*- coding: utf-8 -*-
"""app/tests/test_ads_theme_adopt_reject.py — 主題採用與元件退件路由（票 10-adopt-reject）。

接縫二（路由層，app/ads/routes_creative_theme.py）：一鍵採用整包主題、單元件退件＋理由，
走真正的 HTTP POST。不需要任何 AI 呼叫——主題與元件直接用 theme_repository 灌資料，
只驗路由層的查無此物、輸入驗證、回應形狀，以及退件理由續餵拒絕記憶這條全鏈路
（reject 路由 → adoption_decision → app/ads/brief_assembler.py 既有的
`_rejection_constraints()` 讀法）。品牌與產品名一律虛構。

setUp 寫法照抄 app/tests/test_ads_creative_theme.py（票 02）、
app/tests/test_brief_assembler.py（票 03）——本專案測試檔一律自帶獨立 tmp DB，不共用 import。
"""

import atexit
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_theme_adopt_reject_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import brief_assembler as ba  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.ads import theme_repository as theme_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import db  # noqa: E402


ACTOR = "測試員"


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)


class _Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡（採退票）",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]
        self.product_id = bi_repo.create_product(main.conn, self.bid, name="虛構濾掛組",
                                                  actor=ACTOR)["id"]
        self.cycle_id = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[self.product_id],
            pain_value=5, objective="sales", actor=ACTOR,
        )["id"]
        self.cell_id = db.new_id("exc")
        main.conn.execute(
            "INSERT INTO experiment_cell (id, campaign_cycle_id, brand_id, created_at)"
            " VALUES (?, ?, ?, ?)",
            (self.cell_id, self.cycle_id, self.bid, db.now_iso()),
        )
        main.conn.commit()

    def _create_theme(self, **overrides):
        kwargs = dict(
            campaign_cycle_id=self.cycle_id, experiment_cell_id=self.cell_id,
            format_key="single_image", name="虛構主題：晨光第一杯", folder_code="A1B2",
            actor=ACTOR,
            components=[
                {"component_type": "body", "content": "三分鐘沖一杯好咖啡",
                 "fingerprint_json": {"angle": "benefit", "tone": "warm",
                                      "format": "single_image", "selling_point": "quality"}},
                {"component_type": "title", "content": "早晨從一杯開始"},
            ],
        )
        kwargs.update(overrides)
        return theme_repo.create_theme(main.conn, self.bid, **kwargs)

    def _insert_approved_plan(self):
        main.conn.execute(
            "INSERT INTO campaign_plan (id, campaign_cycle_id, brand_id, plan_version,"
            " plan_json, status, approved_by, approved_at, created_at)"
            " VALUES (?, ?, ?, ?, ?, 'approved', ?, ?, ?)",
            (db.new_id("cpl"), self.cycle_id, self.bid, 1,
             json.dumps({"summary": "測試打法"}, ensure_ascii=False),
             ACTOR, db.now_iso(), db.now_iso()),
        )
        main.conn.commit()


class AdoptThemeRouteTest(_Base):
    def test_adopt_route_marks_theme_adopted(self):
        theme = self._create_theme()
        resp = self.client.post(
            f"/api/ads/brands/{self.bid}/ads/{self.cycle_id}/themes/{theme['id']}/adopt")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["theme"]["status"], "adopted")

        refetched = theme_repo.get_theme(main.conn, self.bid, theme["id"])
        self.assertEqual(refetched["status"], "adopted")

    def test_adopt_route_404s_on_theme_from_a_different_cycle(self):
        other_cycle_id = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[self.product_id],
            pain_value=5, objective="sales", actor=ACTOR,
        )["id"]
        theme = self._create_theme()
        resp = self.client.post(
            f"/api/ads/brands/{self.bid}/ads/{other_cycle_id}/themes/{theme['id']}/adopt")
        self.assertEqual(resp.status_code, 404)

    def test_adopt_route_404s_on_unknown_theme(self):
        resp = self.client.post(
            f"/api/ads/brands/{self.bid}/ads/{self.cycle_id}/themes/cth_not_real/adopt")
        self.assertEqual(resp.status_code, 404)


class RejectComponentRouteTest(_Base):
    def test_reject_route_marks_component_rejected_with_reason(self):
        theme = self._create_theme()
        body_component = theme["components"][0]
        resp = self.client.post(
            f"/api/ads/brands/{self.bid}/ads/{self.cycle_id}"
            f"/components/{body_component['id']}/reject",
            json={"reason_code": "off_brand"},
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()["component"]
        self.assertTrue(payload["rejected"])
        self.assertEqual(payload["reject_reason_label"], "不是我們品牌的調性")

        # AC3：另一則（title）不受影響，主題狀態也不因單一元件退件而改變。
        refetched = theme_repo.get_theme(main.conn, self.bid, theme["id"])
        title_component = next(c for c in refetched["components"]
                               if c["component_type"] == "title")
        self.assertFalse(title_component["rejected"])
        self.assertEqual(refetched["status"], "draft")

    def test_reject_route_rejects_invalid_reason_code(self):
        theme = self._create_theme()
        body_component = theme["components"][0]
        resp = self.client.post(
            f"/api/ads/brands/{self.bid}/ads/{self.cycle_id}"
            f"/components/{body_component['id']}/reject",
            json={"reason_code": "not_a_real_reason"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_reject_route_rejects_malformed_json_body(self):
        theme = self._create_theme()
        body_component = theme["components"][0]
        resp = self.client.post(
            f"/api/ads/brands/{self.bid}/ads/{self.cycle_id}"
            f"/components/{body_component['id']}/reject",
            content=b"not json at all", headers={"content-type": "application/json"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_reject_route_rejects_non_object_json_body(self):
        theme = self._create_theme()
        body_component = theme["components"][0]
        resp = self.client.post(
            f"/api/ads/brands/{self.bid}/ads/{self.cycle_id}"
            f"/components/{body_component['id']}/reject",
            json=["off_brand"],
        )
        self.assertEqual(resp.status_code, 400)

    def test_reject_route_404s_on_unknown_component(self):
        resp = self.client.post(
            f"/api/ads/brands/{self.bid}/ads/{self.cycle_id}"
            f"/components/cthc_not_real/reject",
            json={"reason_code": "off_brand"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_reject_route_404s_on_component_from_a_different_cycle(self):
        other_cycle_id = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[self.product_id],
            pain_value=5, objective="sales", actor=ACTOR,
        )["id"]
        theme = self._create_theme()
        body_component = theme["components"][0]
        resp = self.client.post(
            f"/api/ads/brands/{self.bid}/ads/{other_cycle_id}"
            f"/components/{body_component['id']}/reject",
            json={"reason_code": "off_brand"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_reject_feeds_next_briefs_rejection_constraints(self):
        """AC2：退件理由續餵拒絕記憶，下次簡報的拒絕約束帶得到它——走
        app/ads/brief_assembler.py 既有的 `_rejection_constraints()` 讀法，本票不必另接線。
        """
        self._insert_approved_plan()
        theme = self._create_theme()
        body_component = theme["components"][0]  # fingerprint tone=warm

        resp = self.client.post(
            f"/api/ads/brands/{self.bid}/ads/{self.cycle_id}"
            f"/components/{body_component['id']}/reject",
            json={"reason_code": "off_brand"},  # off_brand → tone 軸
        )
        self.assertEqual(resp.status_code, 200)

        brief, err = ba.assemble_brief(
            main.conn, self.bid, self.cycle_id, self.cell_id, "single_image",
            theme_count=1, actor=ACTOR)
        self.assertIsNone(err)
        self.assertTrue(any("親切溫暖" in c for c in brief.rejection_constraints),
                        brief.rejection_constraints)


if __name__ == "__main__":
    unittest.main()
