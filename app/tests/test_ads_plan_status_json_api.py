# -*- coding: utf-8 -*-
"""app/tests/test_ads_plan_status_json_api.py — 修「投放與成效」企劃階段卡住 BUG：
JSON `/api/campaigns/{brand_id}/{cycle_id}/plan/status` 過去只看 `entry is None or
status == "done"` 就無條件回 `{"status": "done"}`，背景生成失敗（例外或業務失敗）或
逾時時，前端輪詢永遠讀到「done」但 `plan/options` 其實是空的——因為根本沒生成出來，
或乾脆一路停在「running」轉指到天荒地老。

本檔驗證新版端點把 `_progress_state` 既有的 error／逾時語意翻成 JSON「failed + 人話
訊息」，沿用舊 Jinja `ads_plan_progress`（routes_plan.py:420-437）同一套判斷、同一份
`_progress_state` 底層，不是另一套邏輯——直接操作 `_progress_state`（同
test_ads_progress_background.py 的 ProgressRunResultShapeTest 單元測法），不依賴真的
LLM 呼叫、不發任何真實網路請求。全程假品牌（虛構晨光豆行），不碰真 DB。
"""

import atexit
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_plan_status_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import routes as ads_routes  # noqa: E402
from app.ads import routes_campaigns_open_api  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import db as coredb  # noqa: E402
from app.core.db import new_id, now_utc  # noqa: E402



def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)
ACTOR = "測試員"


class PlanStatusApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(
            main.conn, name=f"虛構晨光豆行{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]
        self.cycle_id = new_id("ccy")
        ts = now_utc()
        main.conn.execute(
            "INSERT INTO campaign_cycle (id, org_id, brand_id, product_scope_json, objective,"
            " currency, start_date, end_date, channels_json, status, archived, plan_version,"
            " phase, created_at, updated_at) VALUES (%s, %s, %s, '[]', 'sales', 'TWD',"
            " '2026-08-01', '2026-08-31', '[]', 'PLANNING', false, 0, 'normal', %s, %s)",
            (self.cycle_id, coredb.DEV_ORG_ID, self.bid, ts, ts),
        )
        main.conn.commit()
        self.status_url = f"/api/campaigns/{self.bid}/{self.cycle_id}/plan/status"
        self.key = ads_routes._progress_key("plan", self.bid, self.cycle_id)

    def tearDown(self):
        ads_routes._progress_clear(self.key)

    def test_no_entry_reads_as_done(self):
        """從沒生成過（或已經被消化過一次）：這是「有結果可看」的意思，不是失敗。"""
        resp = self.client.get(self.status_url)
        self.assertEqual(resp.json()["data"], {"status": "done"})

    def test_still_running_reports_running(self):
        ads_routes._progress_state[self.key] = {
            "stage": "only", "started_at": time.time(), "status": "running", "result": None}
        resp = self.client.get(self.status_url)
        self.assertEqual(resp.json()["data"], {"status": "running"})

    def test_background_exception_reports_failed_with_human_message(self):
        """修這張票之前：entry status 是 done 但 result 是 ("error", ...)，舊端點只看
        status=="done" 就無條件回 {"status": "done"}——前端把失敗當成功處理，去讀
        `plan/options` 只會拿到空清單，畫面卡在「讀取中…」。這條測試證明現在會誠實回
        failed＋人話訊息。"""
        ads_routes._progress_state[self.key] = {
            "stage": "only", "started_at": time.time(), "status": "done",
            "result": ("error", "背景執行發生未預期錯誤：測試用錯誤")}
        resp = self.client.get(self.status_url)
        body = resp.json()["data"]
        self.assertEqual(body["status"], "failed")
        self.assertIn("測試用錯誤", body["message"])
        # B0-45 修復 B：失敗是使用者唯一拿得到的紀錄，沒有別的地方存這份訊息——entry
        # 留著，第二次 GET 還是讀到同一句 failed，不會被第一次讀取消化掉、變成看似
        # 正常的「entry 不存在＝done」。
        resp2 = self.client.get(self.status_url)
        body2 = resp2.json()["data"]
        self.assertEqual(body2["status"], "failed")
        self.assertIn("測試用錯誤", body2["message"])

    def test_business_failure_tuple_reports_failed_with_human_message(self):
        """work() 沒爆例外，但回傳 (False, 人話錯誤)——同樣要被視為失敗，不是「done」。"""
        ads_routes._progress_state[self.key] = {
            "stage": "only", "started_at": time.time(), "status": "done",
            "result": ("ok", (False, "AI 回傳的格式兜不起來，請再試一次。"))}
        resp = self.client.get(self.status_url)
        body = resp.json()["data"]
        self.assertEqual(body["status"], "failed")
        self.assertEqual(body["message"], "AI 回傳的格式兜不起來，請再試一次。")

    def test_success_tuple_reports_done(self):
        ads_routes._progress_state[self.key] = {
            "stage": "only", "started_at": time.time(), "status": "done",
            "result": ("ok", (True, None))}
        resp = self.client.get(self.status_url)
        self.assertEqual(resp.json()["data"], {"status": "done"})

    def test_stalled_entry_past_timeout_reports_failed(self):
        """背景執行緒真的還在跑但已經超過逾時門檻：不能讓前端永遠停在 running 輪詢到天荒
        地老（票的根因就是這個症狀）。plan_status 逾時判定讀的是
        `_plan_generate_ceiling_seconds()`（自己算出來的天花板），不是 tracking／weekly
        共用的 `_PROGRESS_TIMEOUT_SECONDS`（B45-1），要壓低的是前者。"""
        original_ceiling = routes_campaigns_open_api._plan_generate_ceiling_seconds
        routes_campaigns_open_api._plan_generate_ceiling_seconds = lambda: 0.05
        try:
            ads_routes._progress_state[self.key] = {
                "stage": "only", "started_at": time.time() - 1, "status": "running", "result": None}
            resp = self.client.get(self.status_url)
        finally:
            routes_campaigns_open_api._plan_generate_ceiling_seconds = original_ceiling
        body = resp.json()["data"]
        self.assertEqual(body["status"], "failed")
        self.assertIn("沒有在時間內回應", body["message"])


if __name__ == "__main__":
    unittest.main()
