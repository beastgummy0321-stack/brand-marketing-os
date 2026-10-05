"""app/tests/test_product_economics_version.py — 票 T2c（ADR 0053 §5）：成本只能從今天生效、
絕不回溯。用 mock.patch.object 假 today_for_org()，不真的跨日等待。"""

import unittest
from datetime import date
from unittest import mock

from app.brand_intelligence import repository as repo
from app.core import db


class ProductEconomicsVersionTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        self.bid = repo.create_brand(self.conn, name="測試茶行（成本版本）", client_name="測試客戶",
                                      actor="測試員", org_id=db.DEV_ORG_ID)["id"]
        self.pid = repo.create_product(self.conn, self.bid, name="測試茶包", actor="測試員")["id"]

    def _save(self, price, today):
        with mock.patch.object(repo.coresettings, "today_for_org", return_value=today):
            repo.save_product_economics(self.conn, self.bid, self.pid, selling_price=price,
                                         currency="TWD", confirmed_by="測試員", actor="測試員")

    def _open_count(self):
        return self.conn.execute(
            "SELECT COUNT(*) AS n FROM product_economics_version"
            " WHERE product_id = %s AND effective_to IS NULL", (self.pid,)).fetchone()["n"]

    def test_cost_change_applies_from_today_never_backwards(self):
        d1, d2 = date(2026, 9, 1), date(2026, 9, 2)
        self._save(300, d1)
        self._save(350, d2)
        self.assertEqual(repo.economics_at(self.conn, self.bid, self.pid, d1)["selling_price"], 300)
        self.assertEqual(repo.economics_at(self.conn, self.bid, self.pid, d2)["selling_price"], 350)
        self.assertEqual(self._open_count(), 1)

    def test_two_saves_same_day_leave_one_open_one_zero_length_closed(self):
        today = date(2026, 9, 3)
        self._save(300, today)
        self._save(350, today)  # 不該炸在 partial unique index 上
        rows = self.conn.execute(
            "SELECT effective_from, effective_to FROM product_economics_version"
            " WHERE product_id = %s ORDER BY version", (self.pid,)).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["effective_to"], today)  # 零長度：[today, today)
        self.assertIsNone(rows[1]["effective_to"])
        self.assertEqual(self._open_count(), 1)

    def test_list_price_and_cap_are_versioned_and_kept(self):
        """F43-I01: list_price / cap_per_sale travel with each version; a save that does not pass
        them (an editor from before F43) keeps the stored values."""
        d1, d2 = date(2026, 9, 1), date(2026, 9, 2)
        with mock.patch.object(repo.coresettings, "today_for_org", return_value=d1):
            repo.save_product_economics(self.conn, self.bid, self.pid, selling_price=359,
                                         currency="TWD", confirmed_by="測試員", actor="測試員",
                                         list_price=399, cap_per_sale=150)
        self._save(349, d2)
        self.assertEqual((repo.economics_at(self.conn, self.bid, self.pid, d1)["list_price"],
                          repo.economics_at(self.conn, self.bid, self.pid, d2)["list_price"],
                          repo.economics_at(self.conn, self.bid, self.pid, d2)["cap_per_sale"]),
                         (399, 399, 150))

    def test_campaign_price_edit_keeps_a_bundle_cost_derived(self):
        """F43-I01: the campaign target's price edit (`PUT .../target`) merges onto the stored
        economics (`raw=True`) and writes them back -- a bundle's NULL cost must stay NULL (still
        derived from its components), never frozen to the effective sum display readers see.
        Driven over HTTP: the ads repository is private to `app.ads`."""
        from fastapi.testclient import TestClient

        import app.main as main

        other = repo.create_product(self.conn, self.bid, name="測試濾掛", actor="測試員")["id"]
        for product_id in (self.pid, other):  # F50 Contract R: a bundle takes ready products
            repo.save_customer_groups(self.conn, self.bid, product_id,
                                      [{"who": "測試客群", "pain_keys": ["cost"]}], actor="測試員")
        bases = [
            repo.save_sell_way(self.conn, self.bid, name=name, actor="測試員",
                               product_id=product_id,
                               economics={"selling_price": price, "unit_variable_cost": cost})["id"]
            for product_id, name, price, cost in ((self.pid, "單盒", 300, 90),
                                                  (other, "單包", 200, 50))
        ]
        bundle = repo.save_sell_way(self.conn, self.bid, name="茶點組", actor="測試員",
                                    components=[{"sell_way_id": bases[0], "qty": 1},
                                                {"sell_way_id": bases[1], "qty": 2}],
                                    economics={"selling_price": 599, "shipping_cost": 60})
        self.assertEqual(bundle["economics"]["unit_variable_cost"], 190)  # 90 + 2 × 50
        self.conn.commit()

        client = TestClient(main.app)
        campaigns = f"/api/ads/brands/{self.bid}/campaigns"
        created = client.post(campaigns, json={
            "goal_text": "茶點組衝一波", "start_date": "2026-10-01", "end_date": "2026-10-31",
            "product_ids": [bundle["id"]], "objective": "購買", "budget": 3000,
        })
        self.assertEqual(created.status_code, 200, created.text)
        resp = client.put(f"{campaigns}/{created.json()['campaign']['id']}/target",
                          json={"price": 579, "expected_revision": 0})
        self.assertEqual(resp.status_code, 200, resp.text)
        raw = repo.get_product_economics(self.conn, self.bid, bundle["id"], raw=True)
        self.assertEqual((raw["selling_price"], raw["unit_variable_cost"], raw["list_price"],
                          raw["shipping_cost"]), (579, None, None, 60))
        effective = repo.get_product_economics(self.conn, self.bid, bundle["id"])
        self.assertEqual((effective["unit_variable_cost"], effective["list_price"]), (190, 700))
        self.assertEqual(effective["derived_fields"], ["list_price", "unit_variable_cost"])
