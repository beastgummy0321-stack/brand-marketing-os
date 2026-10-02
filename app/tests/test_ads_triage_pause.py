"""app/tests/test_ads_triage_pause.py — F45-I05 falsifiers for Contract P (ads.md §6.49): the pause
page reads the ad itself. Real rows in the sync tables, read through the route: an active ad's
`triage` equals the item `GET …/triage` returns for it; a paused ad is `closed` with its own item;
a deleted or unknown ad is `gone`; an unknown status is active; `change_set_id` names only an open
PLAIN pause set on this ad.
"""

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.ads import channels, repository
from app.ads import external_repository as external
from app.brand_intelligence import repository as bi_repo
from app.core import db

from .identity_test_helpers import mint_hs256

ACCOUNT_TZ = "Asia/Taipei"
MONTH = "2026-10"


class _Reader:
    """Stand-in source capability (same pattern as `test_ads_triage.py`): one account with a known
    timezone, so the cutoff is deterministic."""

    def accounts(self, conn, org, brand):
        return [{"account_id": "act_1", "currency": "TWD", "name": "來源",
                 "timezone_name": ACCOUNT_TZ}]


class PauseViewTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        user = uuid4()
        token = mint_hs256(sub=str(user), email=f"pause-{user.hex[:8]}@example.com")
        self.headers = {"Authorization": f"Bearer {token}"}
        me = self.client.get("/api/identity/me", headers=self.headers)
        self.org = me.json()["org"]["id"]
        self.conn = web.conn
        self.brand = bi_repo.create_brand(
            self.conn, org_id=self.org, name="暫停頁讀廣告", client_name=None, actor="test",
        )["id"]
        patcher = patch.object(channels, "external_reader", return_value=_Reader())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="既有活動",
        )["id"]
        external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "campaign",
             "native_id": "c1"},
        )
        self.cutoff = (
            db.now_utc().astimezone(ZoneInfo(ACCOUNT_TZ)) - timedelta(days=1)
        ).date()
        external.record_sync(
            self.conn, self.org, self.brand, self.campaign, section="observations",
            state={
                "last_success_at": db.now_utc().isoformat(),
                "coverage": {"start": (self.cutoff - timedelta(days=90)).isoformat(),
                             "end": self.cutoff.isoformat()},
            },
        )
        repository.save_campaign_target(
            self.conn, self.org, self.brand, self.campaign,
            result_kind="purchase", basis="own", value=100, expected_revision=0, actor="測試員",
        )
        self.conn.commit()

    # -- fixtures ---------------------------------------------------------------------------------

    def ad(self, native_id, name, *, status="ACTIVE", **extra):
        entity = external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "ad",
             "native_id": native_id, "name": name, "parent_native_kind": "campaign",
             "parent_native_id": "c1", "native_status": status, **extra},
        )
        self.conn.commit()
        return entity["id"]

    def purchases(self, entity_id, *, days=7, spend=100, count=2):
        for offset in range(days):
            day = self.cutoff - timedelta(days=offset)
            external.upsert_observation(
                self.conn, self.org, self.brand, self.campaign,
                {"entity_id": entity_id, "day": day, "metric_scope": "ad",
                 "attribution_key": f"{entity_id}-{day}", "currency": "TWD", "source": "meta",
                 "spend": spend, "impressions": 1000, "purchases": count},
                result_kind="purchase", result_count=count, result_action="omni_purchase",
                result_attribution="7d_click+1d_view",
            )
        self.conn.commit()

    def change_set(self, items, *, status="draft", source=None, minutes=0, action_states=None):
        set_id = db.new_id("acs")
        plan = {"items": items, **({"source": source} if source else {})}
        self.conn.execute(
            "INSERT INTO ads_change_set(id,org_id,brand_id,campaign_id,operation_id,request_hash,"
            "content_hash,title,month,plan_json,created_by,status,approved_at,created_at) "
            "VALUES(%s,%s,%s,%s,%s,'h','h','t',%s,%s,'test',%s,%s,%s)",
            (set_id, self.org, self.brand, self.campaign, db.new_id("op"), MONTH,
             db.jsonb(plan), status,
             datetime(2026, 9, 20, tzinfo=UTC) if status == "approved" else None,
             datetime(2026, 9, 20, tzinfo=UTC) + timedelta(minutes=minutes)),
        )
        for item_id, state in (action_states or {}).items():
            target = next(i["target_id"] for i in items if i["id"] == item_id)
            self.conn.execute(
                "INSERT INTO ads_action(id,org_id,brand_id,campaign_id,target_kind,target_id,"
                "kind,change_set_id,verification_state) VALUES(%s,%s,%s,%s,'ad',%s,'pause',%s,%s)",
                (item_id, self.org, self.brand, self.campaign, target, set_id, state),
            )
        self.conn.commit()
        return set_id

    def pause(self, entity_id, *, campaign_id=None):
        response = self.client.get(
            f"/api/ads/brands/{self.brand}/campaigns/{campaign_id or self.campaign}"
            f"/triage/{entity_id}/pause",
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["pause"]

    def triage_items(self):
        response = self.client.get(
            f"/api/ads/brands/{self.brand}/campaigns/{self.campaign}/triage", headers=self.headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["triage"]

    # -- states -----------------------------------------------------------------------------------

    def test_active_ad_with_purchases_equals_its_triage_item(self):
        ad = self.ad("ad1", "廣告一")
        self.ad("ad2", "廣告二")
        self.purchases(ad)
        view = self.pause(ad)
        expected = next(i for i in self.triage_items()["items"] if i["entity_id"] == ad)
        self.assertEqual(view["state"], "active")
        self.assertEqual((view["entity_id"], view["name"]), (ad, "廣告一"))
        self.assertEqual(view["triage"], expected)
        self.assertEqual((view["triage"]["grade"], view["triage"]["grade_label"]),
                         ("on_target", "划算"))
        self.assertEqual(view["triage"]["current"]["spend"], 700)
        self.assertEqual(view["triage"]["current"]["result_count"], 14)
        self.assertEqual(view["triage"]["current"]["cost_per_result"], 50)
        self.assertIn("ladder", view["triage"])
        self.assertIsNone(view["change_set_id"])

    def test_unknown_status_is_active(self):
        ad = self.ad("ad1", "沒狀態", status=None)
        view = self.pause(ad)
        self.assertEqual(view["state"], "active")
        self.assertIsNotNone(view["triage"])

    def test_paused_ad_is_closed_with_its_own_item(self):
        ad = self.ad("ad1", "停掉的")
        self.purchases(ad)
        self.ad("ad1", "停掉的", status="PAUSED", last_success_at="2026-09-30T02:00:00+00:00")
        changed_at = datetime(2026, 9, 29, 3, 0, tzinfo=UTC)
        self.conn.execute(
            "UPDATE ads_external_entity SET status_changed_at=%s WHERE id=%s", (changed_at, ad),
        )
        self.conn.commit()
        view = self.pause(ad)
        self.assertEqual(view["state"], "closed")
        self.assertEqual(datetime.fromisoformat(view["closed_at"]), changed_at)
        self.assertEqual(
            datetime.fromisoformat(view["last_read_at"]),
            datetime(2026, 9, 30, 2, 0, tzinfo=UTC),
        )
        self.assertEqual(view["triage"]["entity_id"], ad)
        self.assertEqual(view["triage"]["grade"], "on_target")
        self.assertEqual(view["triage"]["current"]["cost_per_result"], 50)
        # The closed ad is not in GET …/triage's judged items; the pause page still has numbers.
        self.assertNotIn(ad, [i["entity_id"] for i in self.triage_items()["items"]])

    def test_deleted_ad_is_gone(self):
        ad = self.ad("ad1", "刪掉的", status="DELETED")
        view = self.pause(ad)
        self.assertEqual(view["state"], "gone")
        self.assertIsNone(view["triage"])

    def test_unknown_id_is_gone(self):
        view = self.pause("aee_missing")
        self.assertEqual(view, {
            "state": "gone", "entity_id": "aee_missing", "name": None, "triage": None,
            "closed_at": None, "last_read_at": None, "change_set_id": None,
        })

    def test_non_ad_entity_and_other_campaign_are_gone(self):
        root = self.conn.execute(
            "SELECT id FROM ads_external_entity WHERE campaign_id=%s AND native_kind='campaign'",
            (self.campaign,),
        ).fetchone()["id"]
        self.assertEqual(self.pause(root)["state"], "gone")
        ad = self.ad("ad1", "廣告一")
        other = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="別的活動",
        )["id"]
        self.conn.commit()
        self.assertEqual(self.pause(ad, campaign_id=other)["state"], "gone")

    def test_unknown_campaign_is_404(self):
        response = self.client.get(
            f"/api/ads/brands/{self.brand}/campaigns/adc_missing/triage/x/pause",
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(response.json()["error"]["code"], "campaign_unknown")

    # -- change_set_id ----------------------------------------------------------------------------

    def test_open_draft_pause_set_is_returned(self):
        ad = self.ad("ad1", "廣告一")
        set_id = self.change_set([{"id": db.new_id("aci"), "kind": "pause", "target_id": ad}])
        self.assertEqual(self.pause(ad)["change_set_id"], set_id)

    def test_approved_set_with_unconfirmed_item_is_returned(self):
        ad = self.ad("ad1", "廣告一")
        item_id = db.new_id("aci")
        set_id = self.change_set(
            [{"id": item_id, "kind": "pause", "target_id": ad}], status="approved",
            action_states={item_id: "pending"},
        )
        self.assertEqual(self.pause(ad)["change_set_id"], set_id)

    def test_approved_set_with_confirmed_item_is_null(self):
        ad = self.ad("ad1", "廣告一")
        item_id = db.new_id("aci")
        self.change_set(
            [{"id": item_id, "kind": "pause", "target_id": ad}], status="approved",
            action_states={item_id: "confirmed"},
        )
        self.assertIsNone(self.pause(ad)["change_set_id"])

    def test_cleanup_and_ab_sets_listing_the_ad_are_null(self):
        ad = self.ad("ad1", "廣告一")
        self.change_set([{"id": db.new_id("aci"), "kind": "pause", "target_id": ad}],
                        source="cleanup")
        self.change_set([{"id": db.new_id("aci"), "kind": "pause", "target_id": ad}],
                        source="ab", minutes=1)
        self.assertIsNone(self.pause(ad)["change_set_id"])

    def test_other_ad_or_other_kind_is_null_and_newest_open_set_wins(self):
        ad = self.ad("ad1", "廣告一")
        other = self.ad("ad2", "廣告二")
        self.change_set([{"id": db.new_id("aci"), "kind": "pause", "target_id": other}])
        self.change_set([{"id": db.new_id("aci"), "kind": "copy", "target_id": ad}], minutes=1)
        self.assertIsNone(self.pause(ad)["change_set_id"])
        older = self.change_set(
            [{"id": db.new_id("aci"), "kind": "pause", "target_id": ad}], minutes=2,
        )
        newer = self.change_set(
            [{"id": db.new_id("aci"), "kind": "pause", "target_id": ad}], minutes=3,
        )
        self.assertNotEqual(older, newer)
        self.assertEqual(self.pause(ad)["change_set_id"], newer)


if __name__ == "__main__":
    unittest.main()
