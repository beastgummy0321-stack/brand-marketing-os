# -*- coding: utf-8 -*-
"""app/tests/test_inbox_api.py — 收件匣 JSON API（票 B1-inbox，契約
`.scratch/grill/GRILL-B1-inbox.md` S2）。

`GET /api/inbox`、`GET /api/system/prototype-phase`：真實暫存 SQLite，不 mock，直接打路由
驗證形狀齊全＋既有資料函式（`app.core.interrupts`／`app.core.prototype_phase`）真的接上。
"""

import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_inbox_api_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import interrupts as core_interrupts  # noqa: E402
from app.core import prototype_phase as core_prototype_phase  # noqa: E402
from app.core import settings as core_settings  # noqa: E402

main.reopen_connection()


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"


class InboxApiTest(unittest.TestCase):
    def setUp(self):
        main.conn.execute("DELETE FROM interrupt")
        main.conn.execute("DELETE FROM app_setting WHERE key = ?", (core_prototype_phase.FLAG_SETTING,))
        main.conn.commit()
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構貓山咖啡", client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]

    def test_shape_matches_contract_type(self):
        """契約 InboxItem 型別：id／brand_id／brand_name／category／category_label／severity／
        message／action_url／resolved_at 九個欄位，逐一比對，契約沒寫的欄位不得混進來。"""
        core_interrupts.enqueue(
            main.conn, category="pacing_overspend", dedupe_key="k1", message="燒太快",
            brand_id=self.bid, action_url="/brands/x/ads/cycle-1",
        )
        core_interrupts.enqueue(
            main.conn, category="cycle_reminder", dedupe_key="k2", message="全站事項", brand_id=None,
        )
        main.conn.commit()

        resp = self.client.get("/api/inbox")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("data", body)
        self.assertIn("generated_at", body)
        self.assertEqual(set(body["data"].keys()), {"open", "done"})
        self.assertEqual(len(body["data"]["open"]), 2)

        item = next(i for i in body["data"]["open"] if i["category"] == "pacing_overspend")
        self.assertEqual(
            set(item.keys()),
            {"id", "brand_id", "brand_name", "category", "category_label", "severity",
             "message", "action_url", "resolved_at"},
        )
        self.assertEqual(item["brand_id"], self.bid)
        self.assertEqual(item["brand_name"], "虛構貓山咖啡")
        self.assertEqual(item["category_label"], "檔期步調－燒太快")
        self.assertEqual(item["severity"], "rule_warning")
        self.assertEqual(item["message"], "燒太快")
        self.assertEqual(item["action_url"], "/brands/x/ads/cycle-1")
        self.assertIsNone(item["resolved_at"])

        # 全站事項：brand_id／brand_name 皆為 null（S2.3）
        site_item = next(i for i in body["data"]["open"] if i["category"] == "cycle_reminder")
        self.assertIsNone(site_item["brand_id"])
        self.assertIsNone(site_item["brand_name"])

    def test_done_list_has_resolved_at(self):
        interrupt_id = core_interrupts.enqueue(
            main.conn, category="auto_sync_failed", dedupe_key="k3", message="同步失敗", brand_id=self.bid,
        )
        main.conn.commit()
        core_interrupts.resolve(main.conn, interrupt_id, actor=ACTOR)

        body = self.client.get("/api/inbox").json()
        self.assertEqual(len(body["data"]["done"]), 1)
        self.assertIsNotNone(body["data"]["done"][0]["resolved_at"])

    def test_empty_state_returns_empty_lists_not_error(self):
        body = self.client.get("/api/inbox").json()
        self.assertEqual(body["data"], {"open": [], "done": []})

    def test_resolve_still_uses_existing_html_endpoint(self):
        """S2.8：「知道了」沿用既有 `POST /interrupts/{id}/resolve`，本票不重造第二份。"""
        interrupt_id = core_interrupts.enqueue(
            main.conn, category="cycle_reminder", dedupe_key="k4", message="測試", brand_id=self.bid,
        )
        main.conn.commit()
        resp = self.client.post(f"/interrupts/{interrupt_id}/resolve", follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        body = self.client.get("/api/inbox").json()
        self.assertEqual(len(body["data"]["done"]), 1)
        self.assertEqual(len(body["data"]["open"]), 0)


class PrototypePhaseApiTest(unittest.TestCase):
    def setUp(self):
        main.conn.execute("DELETE FROM app_setting WHERE key = ?", (core_prototype_phase.FLAG_SETTING,))
        main.conn.commit()
        self.client = TestClient(main.app)

    def test_not_ended_shape(self):
        resp = self.client.get("/api/system/prototype-phase")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(set(body["data"].keys()), {"ended", "exemptions"})
        self.assertFalse(body["data"]["ended"])
        self.assertEqual(len(body["data"]["exemptions"]), 4)
        for exemption in body["data"]["exemptions"]:
            self.assertEqual(set(exemption.keys()), {"item", "status"})

    def test_ended_reflects_flag(self):
        core_settings.set_setting(main.conn, core_prototype_phase.FLAG_SETTING, "2026-08-01T00:00:00")
        resp = self.client.get("/api/system/prototype-phase")
        self.assertTrue(resp.json()["data"]["ended"])


if __name__ == "__main__":
    unittest.main()
