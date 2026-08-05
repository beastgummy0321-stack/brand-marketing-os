# -*- coding: utf-8 -*-
"""app/tests/test_customer_voice.py — 顧客原話語料庫（GitHub issue #14，決策 0023 第 18a 條／0024 第 2 條）。

見 app/brand_intelligence/customer_voice.py（抽取）、repository.py 的 *_customer_voice
函式、main.py 的 /brands/{id}/hub/customer-voice* 路由。全程只用 FakeProvider，不發任何
真實網路請求。測試品牌一律虛構名：晨露茶飲、山嵐選物。
"""

import atexit
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# 先備好暫存 DB 的環境變數，才能 import app.main（它在 import 當下就會連線＋跑 migrations）。
_tmpdir = tempfile.mkdtemp(prefix="brand_os_customer_voice_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.brand_intelligence import customer_voice  # noqa: E402
from app.brand_intelligence import repository as repo  # noqa: E402
from app.llm import providers  # noqa: E402

main.reopen_connection()


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"


def _items(tag: str) -> list:
    return [
        {"task_layer": "functional", "quote": f"{tag}吃了兩天終於消下去",
         "insight": "消腫速度是顧客在意的重點", "signal": "unprompted"},
        {"task_layer": "emotional", "quote": f"{tag}鬆了一口氣",
         "insight": "情緒上的解脫感可以當 Hook", "signal": "unprompted"},
    ]


def _fake(items=None, output_text=None) -> providers.FakeProvider:
    if output_text is None:
        output_text = json.dumps({"items": items if items is not None else []}, ensure_ascii=False)
    return providers.FakeProvider(response=providers.ProviderResponse(
        output_text=output_text, structured=None,
        usage=providers.Usage(input_tokens=800, output_tokens=300), stop_reason="end_turn",
    ))


class CustomerVoiceExtractTest(unittest.TestCase):
    """直接測 customer_voice.extract()／repository，不經 HTTP。"""

    def setUp(self):
        self.brand = repo.create_brand(main.conn, name="晨露茶飲", client_name="測試客戶", actor=ACTOR)

    def test_extract_success_stores_row_with_items(self):
        fake = _fake(_items("晨露"))
        with mock.patch.object(customer_voice, "PROVIDER", fake):
            ok, row = customer_voice.extract(
                main.conn, self.brand["id"], actor=ACTOR, raw_text="連續熬夜三天，吃了兩天終於消下去，鬆了一口氣",
                source_channel="shopee", source_detail="XX保健品評論區",
            )
        self.assertTrue(ok, row)
        self.assertEqual(len(row["extraction"]), 2)
        self.assertEqual(row["extraction"][0]["task_layer"], "functional")
        self.assertEqual(row["source_type"], "manual")
        self.assertTrue(row["llm_task_id"])

        stored = repo.get_customer_voice(main.conn, self.brand["id"], row["id"])
        self.assertIsNotNone(stored)
        self.assertEqual(stored["status"], "active")

        audit_rows = main.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'customer_voice' AND action = 'create' "
            "AND entity_id = ?", (row["id"],)
        ).fetchall()
        self.assertEqual(len(audit_rows), 1)

    def test_extract_empty_items_is_honest_not_a_failure(self):
        """AI 判斷這段原話沒有值得收的重點也是誠實結果，仍然入庫（principles 第 16 條）。"""
        with mock.patch.object(customer_voice, "PROVIDER", _fake([])):
            ok, row = customer_voice.extract(
                main.conn, self.brand["id"], actor=ACTOR, raw_text="好用+1",
                source_channel="dcard",
            )
        self.assertTrue(ok, row)
        self.assertEqual(row["extraction"], [])

    def test_bad_format_does_not_store(self):
        with mock.patch.object(customer_voice, "PROVIDER", _fake(output_text="這不是 JSON")):
            ok, err = customer_voice.extract(
                main.conn, self.brand["id"], actor=ACTOR, raw_text="測試原文", source_channel="ptt",
            )
        self.assertFalse(ok)
        self.assertTrue(err)
        n = main.conn.execute(
            "SELECT COUNT(*) AS n FROM customer_voice WHERE brand_id = ?", (self.brand["id"],)
        ).fetchone()["n"]
        self.assertEqual(n, 0)

    def test_invalid_task_layer_does_not_store(self):
        bad_items = [{"task_layer": "not_a_layer", "quote": "隨便", "insight": "隨便"}]
        with mock.patch.object(customer_voice, "PROVIDER", _fake(bad_items)):
            ok, err = customer_voice.extract(
                main.conn, self.brand["id"], actor=ACTOR, raw_text="測試原文", source_channel="ptt",
            )
        self.assertFalse(ok)
        self.assertTrue(err)

    def test_archive_and_restore(self):
        with mock.patch.object(customer_voice, "PROVIDER", _fake(_items("晨露"))):
            _ok, row = customer_voice.extract(
                main.conn, self.brand["id"], actor=ACTOR, raw_text="測試原文", source_channel="ptt",
            )
        archived = repo.set_customer_voice_status(main.conn, self.brand["id"], row["id"],
                                                    status="archived", actor=ACTOR)
        self.assertEqual(archived["status"], "archived")
        restored = repo.set_customer_voice_status(main.conn, self.brand["id"], row["id"],
                                                    status="active", actor=ACTOR)
        self.assertEqual(restored["status"], "active")

    def test_delete_does_not_require_archive_first(self):
        """決策 0023 第 8 條：沿用 _delete_entity 模式，刪除不要求先封存。"""
        with mock.patch.object(customer_voice, "PROVIDER", _fake(_items("晨露"))):
            _ok, row = customer_voice.extract(
                main.conn, self.brand["id"], actor=ACTOR, raw_text="測試原文", source_channel="ptt",
            )
        self.assertEqual(row["status"], "active")
        repo.delete_customer_voice(main.conn, self.brand["id"], row["id"], actor=ACTOR)
        self.assertIsNone(repo.get_customer_voice(main.conn, self.brand["id"], row["id"]))
        del_row = main.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'customer_voice' AND action = 'delete' "
            "AND entity_id = ?", (row["id"],)
        ).fetchone()
        self.assertIsNotNone(del_row)


class CustomerVoiceHttpTest(unittest.TestCase):
    """經 HTTP 路由驗證頁面渲染、隔離、驗證錯誤、封存與刪除、指引頁。"""

    def setUp(self):
        self.client = TestClient(main.app)

    def _new_brand(self, name):
        b = repo.create_brand(main.conn, name=name, client_name=None, actor=ACTOR)
        return b["id"]

    def test_new_page_200(self):
        bid = self._new_brand("山嵐選物-新增頁")
        resp = self.client.get(f"/brands/{bid}/customer-voice/new")
        self.assertEqual(resp.status_code, 200)

    def test_validation_errors_do_not_call_llm(self):
        bid = self._new_brand("山嵐選物-驗證錯誤")
        fake = _fake(_items("不該被呼叫"))
        with mock.patch.object(customer_voice, "PROVIDER", fake):
            resp = self.client.post(f"/brands/{bid}/customer-voice/new",
                                     data={"source_channel": "", "raw_text": ""})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(len(fake.calls), 0)

    def test_post_creates_and_redirects_to_list(self):
        bid = self._new_brand("山嵐選物-新增成功")
        with mock.patch.object(customer_voice, "PROVIDER", _fake(_items("山嵐"))):
            resp = self.client.post(f"/brands/{bid}/customer-voice/new", data={
                "source_channel": "dcard", "source_detail": "推薦文",
                "raw_text": "連續熬夜三天，吃了兩天終於消下去，鬆了一口氣",
            }, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertIn("/hub/customer-voice", resp.headers["location"])

        page = self.client.get(f"/brands/{bid}/hub/customer-voice")
        self.assertEqual(page.status_code, 200)
        self.assertIn("鬆了一口氣", page.text)
        self.assertIn("Dcard", page.text)

    def test_extraction_failure_keeps_raw_text_and_shows_error(self):
        bid = self._new_brand("山嵐選物-抽取失敗")
        with mock.patch.object(customer_voice, "PROVIDER", _fake(output_text="不是 JSON")):
            resp = self.client.post(f"/brands/{bid}/customer-voice/new", data={
                "source_channel": "ptt", "raw_text": "這段原話會抽取失敗",
            })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("這段原話會抽取失敗", resp.text)  # 沒吃掉使用者貼的內容
        n = main.conn.execute(
            "SELECT COUNT(*) AS n FROM customer_voice WHERE brand_id = ?", (bid,)
        ).fetchone()["n"]
        self.assertEqual(n, 0)

    def test_archive_and_delete_via_routes(self):
        bid = self._new_brand("山嵐選物-封存刪除路由")
        with mock.patch.object(customer_voice, "PROVIDER", _fake(_items("山嵐"))):
            _ok, row = customer_voice.extract(
                main.conn, bid, actor=ACTOR, raw_text="測試原文", source_channel="ptt",
            )
        cv_id = row["id"]

        self.client.post(f"/brands/{bid}/customer-voice/{cv_id}/archive", follow_redirects=False)
        self.assertEqual(repo.get_customer_voice(main.conn, bid, cv_id)["status"], "archived")

        page = self.client.get(f"/brands/{bid}/hub/customer-voice")
        self.assertIn("已封存", page.text)

        self.client.post(f"/brands/{bid}/customer-voice/{cv_id}/archive", follow_redirects=False)
        self.assertEqual(repo.get_customer_voice(main.conn, bid, cv_id)["status"], "active")

        self.client.post(f"/brands/{bid}/customer-voice/{cv_id}/delete", follow_redirects=False)
        self.assertIsNone(repo.get_customer_voice(main.conn, bid, cv_id))

    def test_isolation_between_brands(self):
        morning_id = self._new_brand("晨露茶飲-隔離")
        mountain_id = self._new_brand("山嵐選物-隔離")
        with mock.patch.object(customer_voice, "PROVIDER", _fake(_items("晨露機密內容"))):
            self.client.post(f"/brands/{morning_id}/customer-voice/new", data={
                "source_channel": "ptt", "raw_text": "晨露機密內容 原文",
            })
        page = self.client.get(f"/brands/{mountain_id}/hub/customer-voice")
        self.assertNotIn("晨露機密內容", page.text)

    def test_unknown_brand_is_404(self):
        resp = self.client.get("/brands/brd_不存在/hub/customer-voice")
        self.assertEqual(resp.status_code, 404)

    def test_guide_page_matches_methodology_content(self):
        bid = self._new_brand("山嵐選物-指引頁")
        resp = self.client.get(f"/brands/{bid}/customer-voice/guide")
        self.assertEqual(resp.status_code, 200)
        for phrase in ("蝦皮商品評論", "momo", "Dcard", "PTT", "客服對話紀錄",
                       "具體情境", "顧客自己的用詞", "好用+1"):
            self.assertIn(phrase, resp.text)


if __name__ == "__main__":
    unittest.main()
