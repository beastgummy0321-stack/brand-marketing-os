"""app/tests/test_dashboard_pinned_views.py — 駕駛艙成效釘選區（B4R 收尾包項目 3）：
目錄預設 5 筆全選、存讀來回、無效鍵被濾掉、沒開過檔期時視圖回 None、
post_placeholder 恆定顯示。品牌一律虛構。
"""

import atexit
import shutil
import tempfile
import unittest

_tmpdir = tempfile.mkdtemp(prefix="brand_os_pinned_views_")

import app.main as main  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core.db import DEV_ORG_ID  # noqa: E402
from app.dashboard import pinned_views  # noqa: E402


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"


class PinnedViewsStorageTest(unittest.TestCase):
    def setUp(self):
        self.bid = bi_repo.create_brand(
            main.conn, name="虛構晨露茶行", client_name="測試客戶", actor=ACTOR, org_id=DEV_ORG_ID)["id"]

    def test_defaults_to_full_catalog_before_first_save(self):
        self.assertEqual(pinned_views.get_pinned_views(main.conn, self.bid),
                         [c["key"] for c in pinned_views.PINNED_VIEW_CATALOG])

    def test_set_then_get_round_trips(self):
        pinned_views.set_pinned_views(main.conn, self.bid, ["health_lights", "attribution"])
        self.assertEqual(pinned_views.get_pinned_views(main.conn, self.bid),
                         ["health_lights", "attribution"])

    def test_invalid_keys_are_filtered_out_on_read(self):
        pinned_views.set_pinned_views(main.conn, self.bid, ["health_lights", "沒這個視圖"])
        self.assertEqual(pinned_views.get_pinned_views(main.conn, self.bid), ["health_lights"])

    def test_different_brands_do_not_share_pins(self):
        other_bid = bi_repo.create_brand(
            main.conn, name="虛構霧語咖啡", client_name="測試客戶", actor=ACTOR, org_id=DEV_ORG_ID)["id"]
        pinned_views.set_pinned_views(main.conn, self.bid, ["health_lights"])
        self.assertEqual(pinned_views.get_pinned_views(main.conn, other_bid),
                         [c["key"] for c in pinned_views.PINNED_VIEW_CATALOG])


class BuildPerformanceViewTest(unittest.TestCase):
    def setUp(self):
        self.bid = bi_repo.create_brand(
            main.conn, name="虛構晨露茶行二號店", client_name="測試客戶", actor=ACTOR, org_id=DEV_ORG_ID)["id"]

    def test_post_placeholder_is_constant_even_without_any_cycle(self):
        self.assertEqual(pinned_views.build_performance_view(main.conn, self.bid, "post_placeholder"),
                         {"kind": "post_placeholder"})

    def test_unknown_view_key_returns_none(self):
        self.assertIsNone(pinned_views.build_performance_view(main.conn, self.bid, "沒這個視圖"))

    def test_real_view_returns_none_without_any_cycle(self):
        self.assertIsNone(pinned_views.build_performance_view(main.conn, self.bid, "health_lights"))

    def test_health_lights_view_builds_once_a_cycle_exists(self):
        cycle = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[], pain_value=4000, objective="sales",
            actor=ACTOR, start_date="2026-08-01", duration_days=10)
        view = pinned_views.build_performance_view(main.conn, self.bid, "health_lights")
        self.assertEqual(view["kind"], "health_lights")
        self.assertEqual(view["cycle_id"], cycle["id"])
        self.assertEqual(set(view) - {"kind", "cycle_id"}, {"spend_rate", "cpa", "roas", "fatigue"})


if __name__ == "__main__":
    unittest.main()
