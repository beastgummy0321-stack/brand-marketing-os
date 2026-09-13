"""app/tests/test_intake_tools_api.py — 精靈第 4 步「接工具」JSON API（F05-I08）。

不重測 Meta 權杖／綁定本身（那是 `test_meta_credentials.py` 的範圍，這支路由直接沿用
既有端點，一個字都沒改）。這裡只驗證這一步自己的兩支新端點：GET /tools 的形狀、
POST /conversion-goal 寫得進去、`market_region` 不會被連帶洗掉、不合法值擋下來、
租戶隔離。
"""

import os
import unittest
from uuid import uuid4

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-fake-intake-tools-test")

from fastapi.testclient import TestClient  # noqa: E402

import app.intake as intake_module  # noqa: E402
import app.main as main  # noqa: E402
import app.shared.web as web  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.identity import repository as identity_repo  # noqa: E402
from app.intake import state as intake_state  # noqa: E402

from .identity_test_helpers import mint_hs256  # noqa: E402

_SEQ = [0]


class _Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        web.conn.execute("DELETE FROM app_setting")
        web.conn.commit()
        intake_module.register(main.app)

    def _brand_name(self) -> str:
        _SEQ[0] += 1
        return f"虛構建檔tools測試品牌{_SEQ[0]}"

    def _create_full(self) -> str:
        resp = self.client.post("/api/intake/brands", data={
            "brand_name": self._brand_name(), "description": "一句測試用的品牌描述文字。",
        })
        self.assertEqual(resp.status_code, 200)
        return resp.json()["brand_id"]

    def _make_org(self, suffix: str) -> tuple:
        org_id = f"org_intake_tools_test_{suffix}"
        web.conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
            " ON CONFLICT (id) DO NOTHING",
            (org_id, org_id),
        )
        user_id = uuid4()
        email = f"intake-tools-test-{suffix}-{user_id.hex[:8]}@example.com"
        identity_repo.create_user(web.conn, user_id, email)
        identity_repo.create_membership(web.conn, org_id, user_id, "owner")
        web.conn.commit()
        token = mint_hs256(sub=str(user_id), email=email)
        return org_id, token

    @staticmethod
    def _headers(token: str, org_id: str) -> dict:
        return {"Authorization": f"Bearer {token}", "X-Org-Id": org_id}


class ToolsGetTest(_Base):
    def test_empty_shape_and_four_goal_options(self):
        bid = self._create_full()
        resp = self.client.get(f"/api/intake/brands/{bid}/tools")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertIsNone(data["conversion_goal"])
        self.assertEqual(data["bound_account_ids"], [])
        self.assertEqual(
            {o["key"] for o in data["conversion_goal_options"]},
            {"purchase", "lead", "booking", "awareness"},
        )
        for option in data["conversion_goal_options"]:
            self.assertTrue(option["label"])


class ConversionGoalPostTest(_Base):
    def test_saves_and_preserves_existing_market_region(self):
        bid = self._create_full()
        bi_repo.set_brand_switches(
            web.conn, bid, market_region="TW", conversion_goal=None, actor="test",
        )
        resp = self.client.post(
            f"/api/intake/brands/{bid}/conversion-goal", json={"conversion_goal": "lead"},
        )
        self.assertEqual(resp.status_code, 204)
        brand = bi_repo.get_brand(web.conn, bid)
        self.assertEqual(brand["conversion_goal"], "lead")
        self.assertEqual(brand["market_region"], "TW")

    def test_invalid_value_returns_400(self):
        bid = self._create_full()
        resp = self.client.post(
            f"/api/intake/brands/{bid}/conversion-goal", json={"conversion_goal": "not_a_goal"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("成效目標", resp.json()["error"])

    def test_does_not_rewind_step_past_five(self):
        bid = self._create_full()
        draft = intake_state.require_draft(bid, conn=web.conn)
        intake_state.touch(draft, f"/brands/{bid}/intake/knowledge", 5, conn=web.conn)
        resp = self.client.post(
            f"/api/intake/brands/{bid}/conversion-goal", json={"conversion_goal": "lead"},
        )
        self.assertEqual(resp.status_code, 204)
        draft = intake_state.require_draft(bid, conn=web.conn)
        self.assertEqual(draft["step"], 5)

    def test_other_org_brand_returns_404(self):
        bid = self._create_full()
        _org_b, token_b = self._make_org("b")
        headers = self._headers(token_b, "org_intake_tools_test_b")
        resp = self.client.get(f"/api/intake/brands/{bid}/tools", headers=headers)
        self.assertEqual(resp.status_code, 404)
        resp = self.client.post(
            f"/api/intake/brands/{bid}/conversion-goal",
            json={"conversion_goal": "lead"},
            headers=self._headers(token_b, "org_intake_tools_test_b"),
        )
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
