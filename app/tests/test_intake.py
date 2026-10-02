"""app/tests/test_intake.py — 品牌建檔草稿：持久化與花費上限預設值。

欄位權威見 supabase/migrations/ 本身。全程不發任何真實網路請求。F42-I14 拆掉舊階段（初掃印象、
照片產品卡、AI 問答、交接包操作卡）後，這裡只留草稿本身的測試；預填與七步各有自己的測試檔
（test_intake_prefill.py、test_intake_onboarding_api.py…）。
"""

import io
import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import app.intake as intake_module
import app.main as main
import app.shared.web as web
from app import storage
from app.core import db as coredb
from app.intake import ai as intake_ai
from app.intake import repository as ir
from app.intake import script, state

_BRAND_SEQ = [0]


class IntakeWizardTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        web.conn.execute("DELETE FROM app_setting")
        web.conn.commit()
        intake_module.register(main.app)  # 這個模組自己有一份 schema，要重新掛一次背景 task
        # 隔離環境變數：金鑰／模型只看 DB 設定（沒設＝沒金鑰、預設模型 opus）
        self._envpatch = mock.patch.dict(os.environ, {}, clear=False)
        self._envpatch.start()
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("BRAND_OS_LLM_MODEL", None)
        self._orig_provider = intake_ai.PROVIDER
        self._orig_fetch = intake_ai.fetch_url
        intake_ai.fetch_url = lambda url: (False, "")

    def tearDown(self):
        intake_ai.PROVIDER = self._orig_provider
        intake_ai.fetch_url = self._orig_fetch
        self._envpatch.stop()

    # -- helpers ------------------------------------------------------------

    def _new_wizard_brand(self) -> str:
        _BRAND_SEQ[0] += 1
        name = f"精靈測試品牌{_BRAND_SEQ[0]}"
        photo = self.client.post(
            "/api/intake/photos", files={"photo": ("t.jpg", io.BytesIO(bytes.fromhex("ffd8ff") + b"x" * 97), "image/jpeg")})
        assert photo.status_code == 200
        token = photo.json()["token"]
        storage_key = state.get_pending_photos(token)[0]["storage_key"]
        self.addCleanup(storage.delete, org_id=coredb.DEV_ORG_ID, key=storage_key)
        resp = self.client.post("/api/intake/brands", data={
            "brand_name": name, "description": "測試品牌的描述文字，超過十個字。",
            "photo_tokens": token,
        })
        assert resp.status_code == 200
        return resp.json()["brand_id"]

    # -- 草稿持久化 ----------------------------------------------------------

    def test_draft_persisted_and_survives_restart(self):
        brand_id = self._new_wizard_brand()
        row = ir.get_active_draft(web.conn, brand_id)
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "draft")
        self.assertEqual(row["cost_limit"], script.DEFAULT_BUDGET)

        # 等同重啟伺服器：跟連線池借一條全新連線讀回，證明草稿是真的落了 DB，
        # 不是只活在某一條連線的交易裡（ADR 0027：沒有「reopen」這回事，每個
        # request／背景工作各自跟池子借一條，見 app/core/db.py connection()）。
        with coredb.connection() as fresh:
            draft = state.get_draft(brand_id, conn=fresh)
        self.assertIsNotNone(draft)
        self.assertEqual(draft["step"], 2)
        self.assertEqual(draft["resume_path"], f"/app/brands/{brand_id}/intake")

    def test_budget_limit_default_reads_setting(self):
        from app.core import settings as coresettings
        coresettings.set_setting(web.conn, "intake_budget_limit", "55", org_id=coredb.DEV_ORG_ID)
        brand_id = self._new_wizard_brand()
        self.assertEqual(ir.get_active_draft(web.conn, brand_id)["cost_limit"], 55.0)


if __name__ == "__main__":
    unittest.main()
