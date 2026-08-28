"""app/tests/test_ads_theme_detail.py — 單一主題完整內容路由（票 17-panel-single-image）。

接縫二（路由層，app/ads/routes_creative_theme.py get_theme_detail()）：矩陣資料端點只回
id／name／status 摘要，側板骨架要另外抓一次完整資料（含全部元件）。setUp 寫法照抄
app/tests/test_ads_theme_adopt_reject.py（票 10）。品牌與產品名一律虛構。
"""

import atexit
import shutil
import tempfile
import unittest

_tmpdir = tempfile.mkdtemp(prefix="brand_os_theme_detail_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
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
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡（側板票）",
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
            "INSERT INTO experiment_cell (id, org_id, campaign_cycle_id, brand_id, created_at)"
            " VALUES (%s, %s, %s, %s, %s)",
            (self.cell_id, db.DEV_ORG_ID, self.cycle_id, self.bid, db.now_iso()),
        )
        main.conn.commit()

    def _create_theme(self, **overrides):
        kwargs = dict(
            campaign_cycle_id=self.cycle_id, experiment_cell_id=self.cell_id,
            format_key="single_image", name="虛構主題：晨光第一杯", folder_code="A1B2",
            actor=ACTOR,
            components=[
                {"component_type": "image_prompt", "content": "暖金色茶席上的三入禮盒"},
                {"component_type": "body", "content": "三分鐘沖一杯好咖啡", "over_budget": True},
                {"component_type": "title", "content": "早晨從一杯開始",
                 "similarity_flag": True},
            ],
        )
        kwargs.update(overrides)
        return theme_repo.create_theme(main.conn, self.bid, **kwargs)


class ThemeDetailRouteTest(_Base):
    def test_returns_full_theme_with_components_and_flags(self):
        theme = self._create_theme()
        resp = self.client.get(
            f"/api/ads/brands/{self.bid}/ads/{self.cycle_id}/themes/{theme['id']}")
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()["theme"]
        self.assertEqual(payload["id"], theme["id"])
        self.assertEqual(payload["name"], "虛構主題：晨光第一杯")
        self.assertEqual(payload["format_key"], "single_image")
        self.assertEqual(len(payload["components"]), 3)

        body = next(c for c in payload["components"] if c["component_type"] == "body")
        self.assertEqual(body["over_budget"], 1)
        title = next(c for c in payload["components"] if c["component_type"] == "title")
        self.assertEqual(title["similarity_flag"], 1)

    def test_404_on_unknown_theme(self):
        resp = self.client.get(
            f"/api/ads/brands/{self.bid}/ads/{self.cycle_id}/themes/cth_not_real")
        self.assertEqual(resp.status_code, 404)

    def test_404_on_theme_from_a_different_cycle(self):
        other_cycle_id = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[self.product_id],
            pain_value=5, objective="sales", actor=ACTOR,
        )["id"]
        theme = self._create_theme()
        resp = self.client.get(
            f"/api/ads/brands/{self.bid}/ads/{other_cycle_id}/themes/{theme['id']}")
        self.assertEqual(resp.status_code, 404)

    def test_404_on_unknown_brand(self):
        theme = self._create_theme()
        resp = self.client.get(
            f"/api/ads/brands/brand_not_real/ads/{self.cycle_id}/themes/{theme['id']}")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
