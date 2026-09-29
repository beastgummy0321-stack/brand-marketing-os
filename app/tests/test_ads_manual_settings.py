"""AUD-03 manual handoff persistence, containment and honest readiness."""

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.ads import manual_settings
from app.ads import repository as repo
from app.ads.adapters import manual
from app.core.db import jsonb
from app.tests.test_ads_plan import PlanTestBase


class TestManualSettings(PlanTestBase):
    def setUp(self):
        super().setUp()
        self.campaign = self._create_adopted_campaign()
        self.cid = self.campaign["id"]
        self.group = repo.create_group(
            web.conn,
            self.org_id,
            self.brand_id,
            self.cid,
            channel_key="meta",
            name="再行銷",
            role="retarget",
            daily_budget=200,
        )
        web.conn.commit()
        self.client = TestClient(main.app)
        self.url = (
            f"/api/ads/brands/{self.brand_id}/campaigns/{self.cid}"
            f"/groups/{self.group['id']}/manual-settings"
        )

    def test_same_second_ads_have_a_stable_order(self):
        # Drill 5: a plan's ads share created_at, so ordering by it alone flipped between reads
        # and the launch snapshot looked changed, sending a half-done handoff stale.
        created = [
            repo.create_ad(
                web.conn, self.org_id, self.brand_id, self.cid, self.group["id"],
                name=f"廣告{i}", coordinates={}, coordinates_snapshot={},
            )["id"]
            for i in range(4)
        ]
        # Ties on created_at, and ids deliberately the reverse of the insertion order: only an
        # ordering that names a tie-breaker can answer the same way twice.
        made = sorted(created, reverse=True)
        for old, new in zip(created, made, strict=True):
            web.conn.execute("UPDATE ads_ad SET id = %s WHERE id = %s", (new + "_t", old))
        made = [ad + "_t" for ad in made]
        web.conn.execute(
            "UPDATE ads_ad SET created_at = now() WHERE campaign_id = %s", (self.cid,)
        )
        web.conn.commit()
        listed = [
            [ad["id"] for group in repo.campaign_detail(
                web.conn, self.org_id, self.brand_id, self.cid)["groups"] for ad in group["ads"]]
            for _ in range(3)
        ]
        self.assertEqual(listed[0], listed[1])
        self.assertEqual(listed[1], listed[2])
        self.assertEqual([i for i in listed[0] if i in made], sorted(made))

    def test_save_reload_checklist_and_unverified_id(self):
        values = {f["key"]: "已確認設定" for f in manual_settings.FIELDS if f["required"]}
        values.update(
            landing_url="https://example.test/coffee",
            audience_id="aud_123",
            group_platform_id="group_456",
        )
        response = self.client.put(self.url, json={"values": values})
        assert response.status_code == 200, response.text
        detail = repo.campaign_detail(web.conn, self.org_id, self.brand_id, self.cid)
        assert detail is not None
        record = detail["manual_handoff"]["groups"][0]
        assert record["values"] == values
        assert record["missing"] == []
        assert record["status"] == "資料已填齊，待平台核對"
        assert detail["groups"][0]["local_state"] == "unbound"
        assert detail["groups"][0]["external_id"] is None
        checklist = manual.describe(detail)["checklist"][1]["fields"]
        assert any(f["value"] == "aud_123" for f in checklist)
        assert any(f["label"] == "開始日期" for f in checklist)
        assert any(f["value"] == "group_456" and "不代表已配對" in f["reason"] for f in checklist)
        assert detail["budget_planned"] == self.campaign["budget_planned"]

    def test_group_without_landing_url_reads_the_campaign_default(self):
        # F40-I04: the landing URL given at create time (`context_json.landing_url`) fills every
        # group that has none of its own, marked `sources.landing_url = "campaign"`, and counts
        # as filled; the group's own saved value keeps winning.
        web.conn.execute(
            "UPDATE ads_campaign SET context_json = context_json || %s WHERE id = %s",
            (jsonb({"landing_url": "https://example.test/campaign"}), self.cid),
        )
        detail = repo.campaign_detail(web.conn, self.org_id, self.brand_id, self.cid)
        assert detail is not None
        record = detail["manual_handoff"]["groups"][0]
        assert record["values"]["landing_url"] == "https://example.test/campaign"
        assert record["sources"] == {"landing_url": "campaign"}
        assert "落地頁網址" not in record["missing"]
        assert record["saved_at"] is None  # nothing was saved on the group itself
        # The saved document is untouched: the default is read, never written into the group.
        assert "manual_delivery" not in (detail["context_json"] or {})

        detail = manual_settings.save(
            web.conn, self.org_id, self.brand_id, self.cid, self.group["id"],
            {"landing_url": "https://example.test/own"}, actor="tester",
        )
        record = detail["manual_handoff"]["groups"][0]
        assert record["values"]["landing_url"] == "https://example.test/own"
        assert record["sources"] == {}

    def test_retarget_missing_pool_never_reports_ready(self):
        response = self.client.put(self.url, json={"values": {"audience_source": "網站訪客"}})
        assert response.status_code == 200
        detail = repo.campaign_detail(web.conn, self.org_id, self.brand_id, self.cid)
        assert detail is not None
        assert detail["manual_handoff"]["pending_count"] == 1
        assert "再行銷受眾 ID" in detail["manual_handoff"]["groups"][0]["missing"]

    def test_wrong_campaign_unknown_field_and_unsafe_url_rejected(self):
        other = self._create_adopted_campaign()
        web.conn.commit()
        wrong = self.url.replace(self.cid, other["id"])
        assert self.client.put(wrong, json={"values": {}}).status_code == 404
        assert (
            self.client.put(self.url, json={"values": {"external_id": "fake"}}).status_code == 400
        )
        assert (
            self.client.put(
                self.url, json={"values": {"landing_url": "javascript:alert(1)"}}
            ).status_code
            == 400
        )
        assert (
            self.client.put(
                self.url, json={"values": {"ad_platform_ids": "other = 123"}}
            ).status_code
            == 400
        )

    def test_org_and_brand_isolation_before_write(self):
        import pytest

        for org_id, brand_id in [("org_other", self.brand_id), (self.org_id, "brd_other")]:
            with pytest.raises(ValueError, match="campaign_unknown"):
                manual_settings.save(
                    web.conn, org_id, brand_id, self.cid, self.group["id"], {}, actor="tester"
                )

    def test_saving_another_group_preserves_existing_record(self):
        second = repo.create_group(
            web.conn,
            self.org_id,
            self.brand_id,
            self.cid,
            channel_key="meta",
            name="新客",
            role="new",
            daily_budget=100,
        )
        manual_settings.save(
            web.conn,
            self.org_id,
            self.brand_id,
            self.cid,
            self.group["id"],
            {"audience_source": "網站訪客"},
            actor="tester",
        )
        detail = manual_settings.save(
            web.conn,
            self.org_id,
            self.brand_id,
            self.cid,
            second["id"],
            {"audience_source": "25–44歲"},
            actor="tester",
        )
        records = detail["context_json"]["manual_delivery"]
        assert records[self.group["id"]]["values"]["audience_source"] == "網站訪客"
        assert records[second["id"]]["values"]["audience_source"] == "25–44歲"
