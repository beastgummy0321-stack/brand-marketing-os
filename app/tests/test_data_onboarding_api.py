# -*- coding: utf-8 -*-
"""資料上線新殼 API：形狀、連線檢查與背景工作完成狀態。"""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as main
from app.ads import routes_onboarding_api as onboarding_api
from app.ads import sync as ads_sync
from app.brand_intelligence import repository as bi_repo


ACTOR = "測試員"


class DataOnboardingApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name=f"虛構資料上線茶行{self.id()[-8:]}",
                                          client_name=None, actor=ACTOR)
        self.brand_id = self.brand["id"]
        onboarding_api._jobs.clear()

    def _url(self, suffix: str = "") -> str:
        return f"/api/campaigns/brands/{self.brand_id}{suffix}"

    def test_get_returns_four_items_progress_and_spa_action_urls(self):
        response = self.client.get(self._url("/data-onboarding"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            [item["key"] for item in body["data"]["checklist"]],
            ["meta_claim", "order_backfill", "ga4_backfill", "interview"],
        )
        self.assertEqual(body["data"]["progress"]["total"], 3)
        self.assertEqual(body["data"]["progress"]["done"], 0)
        self.assertTrue(all(item["action_url"].startswith("/app/")
                            for item in body["data"]["checklist"]))
        self.assertEqual(body["data"]["jobs"]["meta_backfill"]["status"], "idle")

    def test_meta_backfill_requires_connection_with_existing_message(self):
        with patch.object(onboarding_api.ads_sync, "is_configured", return_value=False):
            response = self.client.post(self._url("/backfill/meta"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "還沒連上 Meta，先去設定頁連線。"})

    def test_meta_backfill_records_done_after_background_work(self):
        def start_immediately(key, running_state, target, args, **_kwargs):
            onboarding_api._jobs.set(key, running_state)
            target(*args)

        with patch.object(onboarding_api.ads_sync, "is_configured", return_value=True), \
             patch.object(onboarding_api.ads_sync, "sync_account", return_value=ads_sync.SyncResult()), \
             patch.object(onboarding_api, "_notify"), \
             patch.object(onboarding_api._jobs, "start", side_effect=start_immediately):
            response = self.client.post(self._url("/backfill/meta"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "ok": True,
            "message": "開始回填近 12 個月的 Meta 成效，好了會通知你。",
        })
        status = self.client.get(self._url("/data-onboarding")).json()
        self.assertEqual(status["data"]["jobs"]["meta_backfill"]["status"], "done")


if __name__ == "__main__":
    unittest.main()
