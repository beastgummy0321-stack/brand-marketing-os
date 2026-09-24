"""app/tests/test_ads_one_cap.py — F28-I01 falsifiers for R1 storage: every campaign has ONE
cost-per-result cap, stored once in `ads_campaign.target_cost` with `target_basis='own'`
(docs/architecture/ads.md §6.32).

- No non-test file under `app/ads` (or its prompt parts) names the retired goal columns, so no
  reader can drift back to the second store.
- Drill 5: typing 450 in the cap input with nothing else touched stores a 450 cost cap -- the
  old metric dropdown (defaulting to ROAS) can no longer turn it into a ROAS target.
- Without a product cost the cap resolves to null, never this campaign's own past actual.
- The migration back-fills a cost-per-purchase target into the one store and never converts a
  ROAS; `trailing_30` is no longer a storable basis; a system-built campaign no longer needs the
  retired metric column.
"""

import re
import unittest
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

import psycopg
from fastapi.testclient import TestClient

from app import main
from app.ads import channels, repository, targets
from app.ads import external_repository as external
from app.brand_intelligence import repository as brands
from app.core import db
from app.core import settings as coresettings

_ROOT = Path(__file__).resolve().parents[2]
_RETIRED = re.compile(r"success_(metric|target|basis)")
_MIGRATION = _ROOT / "supabase" / "migrations" / "20260925000001_ads_one_cap.sql"


@contextmanager
def transaction(conn):
    try:
        yield
        conn.commit()
    except Exception:
        conn.rollback()
        raise


class NoReaderNamesTheRetiredColumnsTest(unittest.TestCase):
    def test_no_non_test_file_under_app_ads_names_them(self):
        offenders = []
        for folder in (_ROOT / "app" / "ads", _ROOT / "app" / "departments" / "ads"):
            for path in folder.rglob("*"):
                if not path.is_file() or path.suffix not in {".py", ".md"}:
                    continue
                for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    if _RETIRED.search(line):
                        offenders.append(f"{path.relative_to(_ROOT)}:{number}: {line.strip()}")
        self.assertEqual(offenders, [], "\n".join(offenders))


class _CapTestBase(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        self.org = db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="一個上限", actor="test", client_name=None,
        )["id"]
        self.conn.commit()
        self.client = TestClient(main.app)

    def _internal_campaign(self, **fields) -> str:
        campaign = repository.create_campaign(self.conn, self.org, self.brand, {
            "name": "內部活動", "goal_text": "衝購買", "objective": "購買", **fields,
        }, created_by="test")
        self.conn.commit()
        return campaign["id"]

    def _url(self, campaign_id: str, suffix: str = "") -> str:
        return f"/api/ads/brands/{self.brand}/campaigns/{campaign_id}{suffix}"


class DrillFiveCapTest(_CapTestBase):
    def test_typing_450_with_nothing_else_touched_stores_a_450_cost_cap(self):
        campaign_id = self._internal_campaign()
        before = self.client.get(self._url(campaign_id)).json()["campaign"]
        self.assertIsNone(before["cap"]["own_value"])

        saved = self.client.put(self._url(campaign_id, "/target"), json={
            "basis": "own", "value": 450, "expected_revision": before["cap"]["revision"],
        })
        self.assertEqual(saved.status_code, 200, saved.text)

        campaign = self.client.get(self._url(campaign_id)).json()["campaign"]
        self.assertEqual(campaign["cap"]["value"], 450)
        self.assertEqual(campaign["cap"]["basis"], "own")
        self.assertEqual(campaign["cap"]["result_kind"], "purchase")
        self.assertFalse([key for key in campaign if key.startswith("success_")])
        row = self.conn.execute(
            "SELECT target_cost, target_basis FROM ads_campaign WHERE id=%s", (campaign_id,),
        ).fetchone()
        self.assertEqual(float(row["target_cost"]), 450.0)
        self.assertEqual(row["target_basis"], "own")

    def test_cap_must_be_a_positive_number(self):
        campaign_id = self._internal_campaign()
        for bad in (0, -1):
            response = self.client.put(self._url(campaign_id, "/target"), json={
                "basis": "own", "value": bad, "expected_revision": 0,
            })
            self.assertEqual(response.status_code, 400, response.text)
            self.assertEqual(response.json()["error"]["code"], "target_value_unknown")

    def test_trailing_30_is_no_longer_a_basis(self):
        campaign_id = self._internal_campaign()
        response = self.client.put(self._url(campaign_id, "/target"), json={
            "basis": "trailing_30", "expected_revision": 0,
        })
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["error"]["code"], "target_basis_unknown")

    def test_patch_with_a_retired_goal_key_is_400_and_writes_nothing(self):
        campaign_id = self._internal_campaign(target_cost=300)
        for body in ({"success_target": 450}, {"success_metric": "cpa"},
                     {"goal_text": "改", "success_basis": "說明"}):
            response = self.client.patch(self._url(campaign_id), json=body)
            self.assertEqual(response.status_code, 400, response.text)
            self.assertEqual(response.json()["error"]["code"], "goal_fields_retired")
        campaign = repository.get_campaign(self.conn, self.org, self.brand, campaign_id)
        self.assertEqual(campaign["goal_text"], "衝購買")
        self.assertEqual(float(campaign["target_cost"]), 300.0)

    def test_patch_with_another_unknown_key_is_still_422(self):
        campaign_id = self._internal_campaign()
        response = self.client.patch(self._url(campaign_id), json={"status": "live"})
        self.assertEqual(response.status_code, 422, response.text)


class NoTrailingActualTest(_CapTestBase):
    def test_purchase_campaign_without_product_cost_resolves_null_despite_results(self):
        product_id = brands.create_product(self.conn, self.brand, name="沒成本", actor="test")["id"]
        brands.save_product_economics(
            self.conn, self.brand, product_id, selling_price=500, currency="TWD",
            confirmed_by="test", actor="test", unit_variable_cost=None, shipping_cost=50,
        )
        campaign_id = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="有成效的既有活動",
        )["id"]
        entity = external.upsert_entity(self.conn, self.org, self.brand, campaign_id, {
            "platform": "meta", "source_account": "act_1", "native_kind": "campaign",
            "native_id": "c1", "objective": "OUTCOME_SALES",
        })
        yesterday = coresettings.today_for_org(self.conn, org_id=self.org) - timedelta(days=1)
        for offset in range(5):
            external.upsert_observation(
                self.conn, self.org, self.brand, campaign_id,
                {
                    "entity_id": entity["id"], "day": yesterday - timedelta(days=offset),
                    "metric_scope": "campaign", "attribution_key": "unused", "currency": "TWD",
                    "source": "meta", "spend": 1000,
                },
                result_kind="purchase", result_count=4, result_action="omni_purchase",
                result_attribution="7d_click+1d_view",
            )
        self.conn.commit()
        repository.save_campaign_target(
            self.conn, self.org, self.brand, campaign_id,
            result_kind=channels.external_reader("meta").result_kind(entity),
            product_id=product_id, expected_revision=0, actor="test",
        )
        campaign = repository.get_campaign(self.conn, self.org, self.brand, campaign_id)

        result = targets.resolve(self.conn, self.org, self.brand, campaign)

        self.assertIsNone(result["value"])  # never 250 (5000 / 20), the trailing actual
        self.assertIsNone(result["basis"])
        self.assertEqual(result["missing"], ["product_cost"])
        self.assertEqual(result["price"], 500)  # the price is known, only the cost is not
        self.assertEqual(
            self.client.get(self._url(campaign_id, "/target")).json()["target"]["value"], None,
        )


class MigrationTest(_CapTestBase):
    def _insert_legacy(self, *, metric, target) -> str:
        campaign_id = db.new_id("adc")
        self.conn.execute(
            "INSERT INTO ads_campaign(id,org_id,brand_id,name,goal_text,objective,origin,"
            "success_metric,success_target) VALUES (%s,%s,%s,'舊活動','目標','購買','internal',"
            "%s,%s)",
            (campaign_id, self.org, self.brand, metric, target),
        )
        self.conn.commit()
        return campaign_id

    def _row(self, campaign_id):
        return self.conn.execute(
            "SELECT target_cost, target_basis FROM ads_campaign WHERE id=%s", (campaign_id,),
        ).fetchone()

    def test_back_fill_copies_a_cost_target_and_never_converts_a_roas(self):
        cost = self._insert_legacy(metric="cpa", target=450)
        roas = self._insert_legacy(metric="roas", target=3)
        zero = self._insert_legacy(metric="cpa", target=0)
        with transaction(self.conn):
            # Re-running is safe: the updates only touch rows still in the old shape and the
            # constraints are dropped and re-added.
            self.conn.execute(_MIGRATION.read_text(encoding="utf-8"))

        self.assertEqual(float(self._row(cost)["target_cost"]), 450.0)
        self.assertEqual(self._row(cost)["target_basis"], "own")
        for untouched in (roas, zero):
            self.assertIsNone(self._row(untouched)["target_cost"])
            self.assertIsNone(self._row(untouched)["target_basis"])

    def test_trailing_30_basis_is_rejected(self):
        campaign_id = self._internal_campaign()
        with self.assertRaises(psycopg.errors.CheckViolation):
            with transaction(self.conn):
                self.conn.execute(
                    "UPDATE ads_campaign SET target_basis='trailing_30' WHERE id=%s",
                    (campaign_id,),
                )

    def test_internal_campaign_no_longer_needs_the_retired_metric(self):
        campaign_id = self._internal_campaign(target_cost=300)
        self.assertEqual(float(self._row(campaign_id)["target_cost"]), 300.0)


if __name__ == "__main__":
    unittest.main()
