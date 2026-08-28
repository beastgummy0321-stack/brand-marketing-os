"""app/tests/test_inbox_api.py — 收件匣 JSON API（票 B1-inbox，契約
`.scratch/grill/GRILL-B1-inbox.md` S2）。

`GET /api/inbox`、`GET /api/system/prototype-phase`：真實暫存 SQLite，不 mock，直接打路由
驗證形狀齊全＋既有資料函式（`app.core.interrupts`／`app.core.prototype_phase`）真的接上。
"""

import atexit
import shutil
import tempfile
import unittest
from uuid import uuid4

_tmpdir = tempfile.mkdtemp(prefix="brand_os_inbox_api_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import interrupts as core_interrupts  # noqa: E402
from app.core import prototype_phase as core_prototype_phase  # noqa: E402
from app.core import settings as core_settings  # noqa: E402
from app.core.db import DEV_ORG_ID  # noqa: E402

from .identity_test_helpers import mint_hs256  # noqa: E402


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
        main.conn.execute("DELETE FROM app_setting WHERE key = %s", (core_prototype_phase.FLAG_SETTING,))
        main.conn.commit()
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構貓山咖啡", client_name=None, actor=ACTOR, org_id=DEV_ORG_ID)
        self.bid = self.brand["id"]

    def test_shape_matches_contract_type(self):
        """契約 InboxItem 型別：id／brand_id／brand_name／category／category_label／severity／
        message／action_url／resolved_at 九個欄位，逐一比對，契約沒寫的欄位不得混進來。"""
        core_interrupts.enqueue(
            main.conn, category="pacing_overspend", dedupe_key="k1", message="燒太快",
            brand_id=self.bid, action_url="/brands/x/ads/cycle-1", org_id=DEV_ORG_ID,
        )
        core_interrupts.enqueue(
            main.conn, category="cycle_reminder", dedupe_key="k2", message="全站事項", brand_id=None, org_id=DEV_ORG_ID,
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
            main.conn, category="auto_sync_failed", dedupe_key="k3", message="同步失敗", brand_id=self.bid, org_id=DEV_ORG_ID,
        )
        main.conn.commit()
        core_interrupts.resolve(main.conn, interrupt_id, actor=ACTOR, org_id=DEV_ORG_ID)

        body = self.client.get("/api/inbox").json()
        self.assertEqual(len(body["data"]["done"]), 1)
        self.assertIsNotNone(body["data"]["done"][0]["resolved_at"])

    def test_empty_state_returns_empty_lists_not_error(self):
        body = self.client.get("/api/inbox").json()
        self.assertEqual(body["data"], {"open": [], "done": []})

    def test_resolve_via_api_endpoint_moves_item_to_done(self):
        """S2.8：「知道了」呼叫 `POST /api/interrupts/{id}/resolve`
        （T4 步驟 1 刪除舊版 `POST /interrupts/{id}/resolve` HTML 端點，前端已改打這支）。"""
        interrupt_id = core_interrupts.enqueue(
            main.conn, category="cycle_reminder", dedupe_key="k4", message="測試", brand_id=self.bid, org_id=DEV_ORG_ID,
        )
        main.conn.commit()
        resp = self.client.post(f"/api/interrupts/{interrupt_id}/resolve")
        self.assertEqual(resp.status_code, 200)
        body = self.client.get("/api/inbox").json()
        self.assertEqual(len(body["data"]["done"]), 1)
        self.assertEqual(len(body["data"]["open"]), 0)


class InterruptResolveApiTest(unittest.TestCase):
    def setUp(self):
        main.conn.execute("DELETE FROM interrupt")
        main.conn.commit()
        self.client = TestClient(main.app)

    def test_resolve_api_returns_json(self):
        interrupt_id = core_interrupts.enqueue(
            main.conn, category="cycle_reminder", dedupe_key="api-resolve", message="test", org_id=DEV_ORG_ID,
        )
        main.conn.commit()
        response = self.client.post(f"/api/interrupts/{interrupt_id}/resolve")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})


class InterruptResolveTenantIsolationTest(unittest.TestCase):
    """票 03-1 r1 defect 1：org A 的 token 不能結掉 org B 的中斷提醒——404，且資料庫裡
    那筆維持 open（一個「已經動手改資料」的 404 不算修好）。"""

    def setUp(self):
        self.client = TestClient(main.app)
        a_user = uuid4()
        self.a_token = mint_hs256(
            sub=str(a_user), email=f"inbox-orga-{a_user.hex[:8]}@example.com"
        )
        me_a = self.client.get(
            "/api/identity/me", headers={"Authorization": f"Bearer {self.a_token}"}
        )
        self.org_a = me_a.json()["org"]["id"]

        b_user = uuid4()
        b_token = mint_hs256(
            sub=str(b_user), email=f"inbox-orgb-{b_user.hex[:8]}@example.com"
        )
        me_b = self.client.get(
            "/api/identity/me", headers={"Authorization": f"Bearer {b_token}"}
        )
        self.org_b = me_b.json()["org"]["id"]

        self.brand_b = bi_repo.create_brand(
            main.conn, org_id=self.org_b, name="組織B的品牌", client_name=None, actor="測試"
        )["id"]
        main.conn.commit()
        self.interrupt_id = core_interrupts.enqueue(
            main.conn, org_id=self.org_b, category="cycle_reminder",
            dedupe_key="cross-org-resolve", message="B組織的提醒", brand_id=self.brand_b,
        )
        main.conn.commit()

    def test_org_a_cannot_resolve_org_b_interrupt(self):
        resp = self.client.post(
            f"/api/interrupts/{self.interrupt_id}/resolve",
            headers={"Authorization": f"Bearer {self.a_token}"},
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(
            resp.json(),
            {"error": {"code": "not_found", "message": "找不到中斷提醒。", "details": None}},
        )
        row = main.conn.execute(
            "SELECT status FROM interrupt WHERE id = %s", (self.interrupt_id,)
        ).fetchone()
        self.assertEqual(row["status"], "open", "404 不該連帶把資料改掉")


class PrototypePhaseApiTest(unittest.TestCase):
    def setUp(self):
        main.conn.execute("DELETE FROM app_setting WHERE key = %s", (core_prototype_phase.FLAG_SETTING,))
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
        core_settings.set_setting(main.conn, core_prototype_phase.FLAG_SETTING, "2026-08-01T00:00:00", org_id=DEV_ORG_ID)
        resp = self.client.get("/api/system/prototype-phase")
        self.assertTrue(resp.json()["data"]["ended"])


if __name__ == "__main__":
    unittest.main()
