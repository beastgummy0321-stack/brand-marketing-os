"""app/tests/test_brand_proof_facts.py — F38-I01: 「證據」 brand facts and `available_proof_keys`.

A proof fact names one of six kinds (= the six `proof` coordinate keys); the facade answers
"which proof kinds does this brand really have evidence for?" for the prompt builders.
Module-style like `test_library_write_api.py`.
"""

import unittest

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.brand_intelligence import repository as repo
from app.core.db import DEV_ORG_ID

_SEQ = [0]
ACTOR = "本人"


class BrandProofFactsTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def _new_brand(self) -> str:
        _SEQ[0] += 1
        return repo.create_brand(web.conn, name=f"證據品牌{_SEQ[0]}", client_name=None,
                                 actor=ACTOR, org_id=DEV_ORG_ID)["id"]

    def _proof(self, brand_id: str, key: str, status: str) -> dict:
        return repo.create_brand_fact(
            web.conn, brand_id, actor=ACTOR, fact_type="proof", fact_key=key, label=f"{key} 證據",
            value="SGS 檢驗報告 2026-05", status=status,
            confirmed_by=ACTOR if status == "confirmed" else None,
        )

    # ---- routes ----

    def test_proof_without_key_is_400(self):
        brand_id = self._new_brand()
        resp = self.client.post(
            f"/api/library/brands/{brand_id}/facts",
            json={"fact_type": "proof", "label": "PChome 4.8 星", "value": "1,200 則評論",
                  "status": "pending"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json(), {"errors": {"fact_key": "請選擇哪一種證據。"}})
        self.assertEqual(repo.list_brand_facts(web.conn, brand_id), [])

    def test_proof_with_unknown_key_is_400(self):
        brand_id = self._new_brand()
        resp = self.client.post(
            f"/api/library/brands/{brand_id}/facts",
            json={"fact_type": "proof", "fact_key": "none", "label": "x", "value": "y",
                  "status": "pending"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("fact_key", resp.json()["errors"])

    def test_proof_with_key_is_stored_and_shaped(self):
        brand_id = self._new_brand()
        resp = self.client.post(
            f"/api/library/brands/{brand_id}/facts",
            json={"fact_type": "proof", "fact_key": "customer_review", "label": "PChome 4.8 星",
                  "value": "1,200 則評論", "status": "confirmed"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["fact_type_label"], "證據")
        self.assertEqual(data["fact_key"], "customer_review")
        self.assertEqual(data["fact_key_label"], "顧客評論原話")
        stored = repo.get_brand_fact(web.conn, brand_id, data["id"])
        assert stored is not None
        self.assertEqual(stored["fact_key"], "customer_review")

    def test_non_proof_with_key_stores_null(self):
        brand_id = self._new_brand()
        resp = self.client.post(
            f"/api/library/brands/{brand_id}/facts",
            json={"fact_type": "positioning", "fact_key": "lab_report", "label": "定位",
                  "value": "平價家用", "status": "pending"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertIsNone(data["fact_key"])
        self.assertIsNone(data["fact_key_label"])
        stored = repo.get_brand_fact(web.conn, brand_id, data["id"])
        assert stored is not None
        self.assertIsNone(stored["fact_key"])

    def test_edit_to_proof_requires_key_and_away_from_proof_clears_it(self):
        brand_id = self._new_brand()
        fact = self._proof(brand_id, "lab_report", "pending")
        url = f"/api/library/brands/{brand_id}/facts/{fact['id']}/edit"
        resp = self.client.post(url, json={"fact_type": "proof", "label": "x", "value": "y"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["errors"]["fact_key"], "請選擇哪一種證據。")
        resp = self.client.post(url, json={"fact_type": "proof", "fact_key": "media_coverage",
                                           "label": "x", "value": "y"})
        self.assertEqual(resp.json()["data"]["fact_key"], "media_coverage")
        resp = self.client.post(url, json={"fact_type": "tone", "fact_key": "media_coverage",
                                           "label": "x", "value": "y"})
        self.assertIsNone(resp.json()["data"]["fact_key"])

    def test_repository_rejects_proof_without_key(self):
        brand_id = self._new_brand()
        with self.assertRaisesRegex(ValueError, "六種證據"):
            repo.create_brand_fact(web.conn, brand_id, actor=ACTOR, fact_type="proof",
                                   label="x", value="y", status="pending")

    # ---- available_proof_keys ----

    def test_empty_brand_has_no_proof(self):
        self.assertEqual(repo.available_proof_keys(web.conn, self._new_brand()), set())

    def test_only_confirmed_proof_counts(self):
        brand_id = self._new_brand()
        self._proof(brand_id, "lab_report", "confirmed")
        self._proof(brand_id, "sales_numbers", "pending")
        repo.create_brand_fact(web.conn, brand_id, actor=ACTOR, fact_type="tone", label="語調",
                               value="活潑", status="confirmed", confirmed_by=ACTOR)
        self.assertEqual(repo.available_proof_keys(web.conn, brand_id), {"lab_report"})

    def test_active_customer_voice_adds_customer_review_archived_does_not(self):
        brand_id = self._new_brand()
        cv = repo.create_customer_voice(
            web.conn, brand_id, actor=ACTOR, raw_text="吃了一個月睡得比較好",
            source_channel="shopee",
            source_type="manual", extraction=[],
        )
        self.assertEqual(repo.available_proof_keys(web.conn, brand_id), {"customer_review"})
        repo.set_customer_voice_status(web.conn, brand_id, cv["id"], status="archived", actor=ACTOR)
        self.assertEqual(repo.available_proof_keys(web.conn, brand_id), set())


if __name__ == "__main__":
    unittest.main()
