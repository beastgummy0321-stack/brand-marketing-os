# -*- coding: utf-8 -*-
"""app/tests/test_ads_progress_background.py — 修憲落地票 M3：等待頁改背景執行＋冪等閘。

體檢原文（docs/design/19-constitution-audit.md §3.1）：「?run=1 那一次請求同步跑完整個
LLM 呼叫」，瀏覽器凍住 20–90 秒，且按 F5 會再打一次付費 API。本檔驗證三件事：

1. 背景執行：?run=1 那次請求要「立刻回應」（不等生成跑完），畫面之後靠既有的
   meta-refresh 機制每次重整讀真實進度，直到跑完才轉址。
2. 冪等閘：同一個 key 已經在跑，F5／多分頁重整不會讓 provider 被多打一次。
3. 90 秒逾時：等待頁不會無限等下去，即使背景那次呼叫還在跑。

全程 FakeProvider／自訂的慢速假 Provider，不發任何真實網路請求；品牌與產品名一律虛構。
"""

import atexit
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import unquote

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_progress_bg_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import plan as ads_plan  # noqa: E402
from app.ads import routes as ads_routes  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.llm.providers import ProviderResponse, Usage  # noqa: E402

main.reopen_connection()


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"

_AUDIENCE = {"cold": {"description": "測試受眾"}, "warm": {"description": ""},
            "hot": {"description": ""}, "exclusions": []}
_GOOD_OPTIONS = {"options": [
    {"is_recommended": True, "summary": "測試打法", "audience": _AUDIENCE,
     "angles": [{"title": "早上第一杯", "message": "訊息", "why": "", "product_id": None}],
     "hypotheses": [], "grounding": {"facts": [], "inferences": [], "to_verify": []}},
    {"is_recommended": False, "summary": "備用方案", "audience": _AUDIENCE,
     "angles": [{"title": "備用切角", "message": "備用訊息", "why": "", "product_id": None}],
     "hypotheses": [], "grounding": {"facts": [], "inferences": [], "to_verify": []}},
]}


def _fake(text: str) -> ProviderResponse:
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=400, output_tokens=200),
                            stop_reason="end_turn")


class _SlowProvider:
    """假 Provider：等 delay 秒才回覆，用來讓「背景執行不擋住 HTTP 回應」這件事量得出來
    ——FakeProvider 幾乎瞬間完成，量不出「有沒有真的等」的差異。不發任何真實網路請求。"""

    name = "fake-slow"

    def __init__(self, response: ProviderResponse, delay: float = 0.3):
        self.response = response
        self.delay = delay
        self.calls: list = []

    def complete(self, *, model, system, messages, max_tokens, timeout_s=120.0, effort=None):
        self.calls.append({"model": model})
        time.sleep(self.delay)
        return self.response


def _wait_progress(client, url, timeout=5.0):
    """短輪詢模擬瀏覽器 meta refresh，等到真的轉址（303）或逾時為止。"""
    deadline = time.time() + timeout
    resp = client.get(url, follow_redirects=False)
    while resp.status_code != 303 and time.time() < deadline:
        time.sleep(0.02)
        resp = client.get(url, follow_redirects=False)
    return resp


class _BaseProgressTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]
        resp = self.client.post(f"/brands/{self.bid}/ads/new",
                                data={"slider_index": "5", "objective": "sales"},
                                follow_redirects=False)
        self.cycle_id = resp.headers["location"].split("/ads/")[1].split("?")[0]
        self._orig_provider = ads_plan.PROVIDER
        self.url = f"/brands/{self.bid}/ads/{self.cycle_id}/plan/progress?run=1"

    def tearDown(self):
        ads_plan.PROVIDER = self._orig_provider


class BackgroundExecutionTest(_BaseProgressTest):
    def test_run_call_returns_before_generation_finishes(self):
        """驗收核心：?run=1 那次請求不再同步等完整個生成，遠低於 provider 的等待時間就回應。"""
        provider = _SlowProvider(_fake(json.dumps(_GOOD_OPTIONS, ensure_ascii=False)), delay=0.4)
        ads_plan.PROVIDER = provider

        start = time.time()
        first = self.client.get(self.url, follow_redirects=False)
        elapsed = time.time() - start

        self.assertLess(elapsed, 0.3, "?run=1 不該同步等生成跑完——這正是本票要修的凍結問題")
        self.assertEqual(first.status_code, 200)  # 還在跑，不是轉址

        final = _wait_progress(self.client, self.url)
        self.assertEqual(final.status_code, 303)
        self.assertIn("/plan/select", final.headers["location"])
        self.assertEqual(len(provider.calls), 1)


class IdempotencyTest(_BaseProgressTest):
    def test_pressing_f5_while_running_does_not_call_provider_twice(self):
        """驗收核心：同一個 key 已經在跑，F5／多分頁重整不會讓付費 API 被多打一次。"""
        provider = _SlowProvider(_fake(json.dumps(_GOOD_OPTIONS, ensure_ascii=False)), delay=0.3)
        ads_plan.PROVIDER = provider

        first = self.client.get(self.url, follow_redirects=False)
        second = self.client.get(self.url, follow_redirects=False)  # 模擬使用者按 F5
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)

        final = _wait_progress(self.client, self.url)
        self.assertEqual(final.status_code, 303)
        self.assertEqual(len(provider.calls), 1, "F5 不得重複扣款：provider 只該被打一次")

    def test_bare_entry_page_does_not_trigger_generation(self):
        """安全底線：還沒按下去生成前（沒有 run=1）的等待頁本身絕對不能觸發任何呼叫
        ——否則測試環境裡預設的（非 Fake）provider 有被誤觸發真實 API 呼叫的風險。"""
        provider = _SlowProvider(_fake(json.dumps(_GOOD_OPTIONS, ensure_ascii=False)), delay=0.05)
        ads_plan.PROVIDER = provider
        bare_url = f"/brands/{self.bid}/ads/{self.cycle_id}/plan/progress"
        for _ in range(3):
            resp = self.client.get(bare_url)
            self.assertEqual(resp.status_code, 200)
        self.assertEqual(provider.calls, [])


class TimeoutTest(_BaseProgressTest):
    def test_gives_up_after_patched_timeout_without_waiting_full_backend_duration(self):
        """驗收核心：逾時不無限等，且不必真的等 90 秒——用可覆寫的模組常數把門檻壓低
        （生產值仍是 90 秒，與 DESIGN.md §19.4 規則 6 對齊），確認邏輯而非真的等一分半。"""
        delay = 0.3
        provider = _SlowProvider(_fake(json.dumps(_GOOD_OPTIONS, ensure_ascii=False)), delay=delay)
        ads_plan.PROVIDER = provider

        original_timeout = ads_routes._PROGRESS_TIMEOUT_SECONDS
        ads_routes._PROGRESS_TIMEOUT_SECONDS = 0.05
        try:
            self.client.get(self.url, follow_redirects=False)  # 觸發背景執行緒開始跑
            time.sleep(0.1)  # 超過壓低後的逾時門檻，但還沒到 provider 的 0.3 秒
            resp = self.client.get(self.url, follow_redirects=False)
        finally:
            ads_routes._PROGRESS_TIMEOUT_SECONDS = original_timeout
            time.sleep(delay)  # 讓背景那條「已經被放棄」的執行緒把 sleep 跑完，不留尾巴給下一個測試

        self.assertEqual(resp.status_code, 303)
        self.assertIn("kind=warn", resp.headers["location"])
        self.assertIn("沒有在時間內回應", unquote(resp.headers["location"]))


class ProgressRunResultShapeTest(unittest.TestCase):
    """單元層級：_progress_run／_progress_start 不假設 work() 回傳值的形狀（plan/creative
    回 (ok, err) 二元組；ga4_sync.sync_brand 回一個 dataclass 物件），一律包成
    ("ok", 原始值) 或 ("error", 人話訊息)，供各路由自行拆——這裡直接測這個共用機制本身。
    """

    def setUp(self):
        self.key = f"unit-test:{time.time_ns()}"
        self.stages = [("only", "唯一階段")]

    def tearDown(self):
        ads_routes._progress_clear(self.key)

    def _wait_done(self, timeout=2.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            entry = ads_routes._progress_state.get(self.key)
            if entry and entry["status"] == "done":
                return entry
            time.sleep(0.01)
        self.fail("背景執行緒沒有在時限內完成")

    def test_non_tuple_return_value_is_stored_as_ok(self):
        """比照 ga4_sync.sync_brand 回傳一個物件（不是 (ok, err) 二元組）的情況。"""
        sentinel = object()
        ads_routes._progress_start(self.key, self.stages, lambda on_stage: sentinel)
        entry = self._wait_done()
        outcome_kind, payload = entry["result"]
        self.assertEqual(outcome_kind, "ok")
        self.assertIs(payload, sentinel)

    def test_unexpected_exception_is_captured_not_raised(self):
        """work() 本身爆例外（真的非預期的 bug）：不能讓背景執行緒把例外吞掉憑空消失，
        也不能讓它未被捕捉地炸掉整個執行緒——要轉成人話錯誤存進 entry。"""
        def _boom(on_stage):
            raise RuntimeError("測試用的非預期錯誤")

        ads_routes._progress_start(self.key, self.stages, _boom)
        entry = self._wait_done()
        outcome_kind, payload = entry["result"]
        self.assertEqual(outcome_kind, "error")
        self.assertIn("測試用的非預期錯誤", payload)

    def test_idempotent_start_does_not_run_work_twice(self):
        calls = []

        def _work(on_stage):
            calls.append(1)
            time.sleep(0.05)
            return "done"

        ads_routes._progress_start(self.key, self.stages, _work)
        ads_routes._progress_start(self.key, self.stages, _work)  # 模擬 F5：同一個 key 再打一次
        self._wait_done()
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
