"""AUD-03 manual handoff persistence, containment and honest readiness."""

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.ads import manual_settings
from app.ads import repository as repo
from app.ads.adapters import manual
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
