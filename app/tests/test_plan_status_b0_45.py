"""app/tests/test_plan_status_b0_45.py — B0-45 紅燈檢查（先紅後綠，尚未修）。

兩個症狀、兩條斷言，都不打真 LLM、不碰 data/app.db：

A. `_PROGRESS_TIMEOUT_SECONDS = 90`（routes_progress.py:42）比「一次合法的出方案」被
   允許花的時間還短：plan.py:543 的 `gateway.run_task()` 用 `TaskOptions` 預設值
   timeout_s=120、max_retries=1，也就是後端自己願意等到 240 秒。90 秒就判失敗，等於
   對一個自己還在正常等待的工作宣告「AI 沒有在時間內回應」——使用者實測 107 秒成功、
   畫面卻在 90 秒翻成失敗卡，就是這個落差。proposal 那條路已經有
   `_proposal_generate_ceiling_seconds()` 把天花板算出來（同檔 336 行），plan 沒有。

B. 真失敗（業務失敗／例外，非逾時）那條路 `plan_status` 讀一次就
   `_progress_clear(key)`（routes_campaigns_open_api.py:537），第二次再問就落回
   「entry 不存在＝done」。前端只要重掛載一次（WarroomPage.refresh() 會把整棵樹換成
   讀取中…），那句攔下訊息就永遠拿不回來，畫面靜靜跳回初始按鈕。B0-28 只修了逾時
   那條路（`_progress_fail` 留著 entry），真失敗這條沒修。
"""

import atexit
import shutil
import tempfile
import time
import unittest

_tmpdir = tempfile.mkdtemp(prefix="brand_os_b0_45_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import plan as ads_plan  # noqa: E402
from app.ads import routes as ads_routes  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.llm import gateway  # noqa: E402
from app.llm.providers import ProviderResponse, Usage  # noqa: E402

ACTOR = "測試員"


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)


class _StubProvider:
    """假 Provider：回一段固定文字，不發任何真實網路請求、不扣任何額度。"""

    name = "fake-b0-45"

    def __init__(self, text: str):
        self.text = text
        self.calls: list = []

    def complete(self, *, model, system, messages, max_tokens, timeout_s=120.0,
                 effort=None, tools=None):
        self.calls.append({"model": model})
        return ProviderResponse(output_text=self.text, structured=None,
                                usage=Usage(input_tokens=10, output_tokens=10),
                                stop_reason="end_turn")


class PlanStatusB045Test(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name=f"虛構晨光豆行{abs(hash(self.id())) % 99999}",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]
        resp = self.client.post(f"/api/campaigns/{self.bid}",
                                json={"product_ids": [], "budget": 10000, "objective": "sales"})
        self.cycle_id = resp.json()["cycle_id"]
        self.status_url = f"/api/campaigns/{self.bid}/{self.cycle_id}/plan/status"
        self.generate_url = f"/api/campaigns/{self.bid}/{self.cycle_id}/plan/generate"
        self._orig_provider = ads_plan.PROVIDER

    def tearDown(self):
        ads_plan.PROVIDER = self._orig_provider
        ads_routes._progress_clear(ads_routes._progress_key("plan", self.bid, self.cycle_id))

    def test_a_still_running_inside_the_legitimate_window_is_not_reported_as_failed(self):
        """症狀 A：出方案還在跑、而且花的時間仍在後端自己允許的範圍內時，狀態不得回 failed。

        斷言的是行為不是常數：`_PROGRESS_TIMEOUT_SECONDS` 是 tracking（routes_tracking_api.py:89）
        與 weekly（routes_weekly_proposals_api.py:230）共用的，出方案要的是自己的天花板
        （比照同檔 `_proposal_generate_ceiling_seconds()`），不是把共用常數整顆調大。
        """
        opts = gateway.TaskOptions()
        allowed_seconds = opts.timeout_s * (1 + max(opts.max_retries, 0))
        key = ads_routes._progress_key("plan", self.bid, self.cycle_id)

        # 使用者實測那次：107 秒後成功、扣了 US$0.072、三個方案有存進 campaign_plan_option，
        # 畫面卻早就翻成「AI 這次沒有在時間內回應」。107 秒遠在 240 秒的合法範圍內。
        ads_routes._progress_state[key] = {
            "stage": "ask_ai", "started_at": time.time() - 107,
            "status": "running", "result": None, "thread": None}
        data = self.client.get(self.status_url).json()["data"]
        self.assertNotEqual(
            data["status"], "failed",
            f"跑了 107 秒就被判失敗，但後端自己允許一次生成花到 {allowed_seconds} 秒"
            f"（gateway timeout_s={opts.timeout_s}×{1 + opts.max_retries} 次嘗試）",
        )

        # 另一端也要釘住：真的超過合法範圍還是要失敗，不能把天花板改成無限大。
        ads_routes._progress_state[key]["started_at"] = time.time() - (allowed_seconds + 60)
        late = self.client.get(self.status_url).json()["data"]
        self.assertEqual(late["status"], "failed", "超過合法範圍仍必須判失敗，不得永遠等下去")

    def test_b_genuine_failure_survives_a_second_status_read(self):
        """症狀 B：真失敗的攔下訊息不得被第一次讀取消化掉——前端重掛載後再問一次，
        還是要拿到同一句失敗訊息，而不是看似正常的 done。"""
        ads_plan.PROVIDER = _StubProvider("這不是 JSON，解析一定失敗")
        self.assertEqual(self.client.post(self.generate_url, json={}).status_code, 204)

        deadline = time.time() + 10
        first = self.client.get(self.status_url).json()["data"]
        while first["status"] == "running" and time.time() < deadline:
            time.sleep(0.02)
            first = self.client.get(self.status_url).json()["data"]
        self.assertEqual(first["status"], "failed", "前置條件：這次生成本來就該是失敗的")

        second = self.client.get(self.status_url).json()["data"]
        self.assertEqual(
            second["status"], "failed",
            "第二次問狀態變成 done：使用者重整／元件重掛載後，那句攔下訊息就消失了",
        )
        self.assertEqual(second.get("message"), first.get("message"))


if __name__ == "__main__":
    unittest.main()
