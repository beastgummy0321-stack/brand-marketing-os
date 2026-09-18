"""Expired imported source dates must never dispatch a legacy closeout."""

import unittest
from datetime import date
from unittest.mock import patch

from app.ads import external_repository as external
from app.ads import jobs, repository
from app.brand_intelligence import repository as brands
from app.core import db


class JobsOriginTest(unittest.TestCase):
    def test_only_internal_campaign_is_selected(self):
        conn = db.current()
        org = db.DEV_ORG_ID
        brand = brands.create_brand(
            conn, org_id=org, name="排程隔離", actor="test", client_name=None
        )["id"]
        imported = external.create_imported_campaign(conn, org, brand, name="來源已結束")
        internal = repository.create_campaign(
            conn,
            org,
            brand,
            {
                "name": "內部",
                "goal_text": "目標",
                "objective": "購買",
                "success_metric": "cpa",
                "status": "ended",
                "start_date": date(2000, 1, 1),
                "end_date": date(2000, 1, 2),
            },
        )
        conn.execute(
            "UPDATE ads_campaign SET status='ended',end_date='2000-01-02' WHERE id=%s",
            (imported["id"],),
        )
        conn.commit()
        with patch.object(jobs.closeout, "close") as close:
            jobs.close_expired_campaigns(org)
        ids = [call.args[3] for call in close.call_args_list]
        self.assertIn(internal["id"], ids)
        self.assertNotIn(imported["id"], ids)
        self.assertEqual(
            repository.get_campaign(conn, org, brand, imported["id"])["status"], "ended"
        )
