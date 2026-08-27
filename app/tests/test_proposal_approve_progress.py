# -*- coding: utf-8 -*-
"""app/tests/test_proposal_approve_progress.py — 票 13：核可提案書不能凍住、不能不告知
花費（`.scratch/adloop/tickets/13-approve-must-not-block-or-surprise.md`）。

- 驗收 1／2：`proposal/approve` 把 `theme_batch.generate_preselected_batch(...)` 挪到
  跟 `plan/generate`＋`plan/status`（`routes_campaigns_open_api.py`）同一套
  `app.ads.routes_progress` 背景引擎——approve 這次請求不等生成跑完就回應，新的
  `proposal/approve-status` 輪詢端點回報 running → done。
- 驗收 3：生成本身炸掉，狀態回 failed，但核可（`proposal.approve()`）已經同步生效，
  不因為背景生成失敗而被撤銷（D2）。同一條驗收下第三審查抓到的 blocker：
  `generate_preselected_batch()` 沒丟例外時，回傳 dict 裡的 `budget_stopped`／`errors`
  被整批丟掉，八次生成可能一次都沒跑（AI 花費一開始就頂到上限）卻回一句沒事的
  「done」——核可前才說了「這一步會用 AI 產素材，預估花費 US$X」，核可後卻無聲
  收場，正是這張票要殺的「花錢不告知」，只是晚一步發生。`BudgetStoppedWithZeroThemesTest`
  ／`BudgetStoppedWithSomeThemesTest`／`PartialErrorsReportSuccessAndFailureCountsTest`
  三個測試分別鎖住三種語意都要老實回報（新狀態 "partial"），且核可依然生效。
- 驗收 4：核可前看得到的預估花費，跟矩陣頁 `estimated_cost` 同一個
  `pricing.cost_ceiling(model, theme_engine.THEME_MAX_TOKENS)` 天花板來源，只是乘上這次
  核准實際會跑的生成次數（`theme_batch.preselected_cells`＋`theme_feedback.theme_quota`），
  不是另外編一個數字。

全程 monkeypatch `theme_batch.generate_preselected_batch`，不呼叫任何真實 provider／
付費 API；核可前的花費估算改讀 `theme_engine.THEME_MAX_TOKENS`／`pricing.cost_ceiling`，
兩者都是純算式，不打真實網路。
"""

import atexit
import json
import shutil
import tempfile
import threading
import time
import unittest

import pytest

_tmpdir = tempfile.mkdtemp(prefix="brand_os_proposal_approve_progress_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import nextcycle  # noqa: E402
from app.ads import proposal  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.ads import routes as ads_routes  # noqa: E402
from app.ads import theme_batch  # noqa: E402
from app.ads import theme_engine  # noqa: E402
from app.ads import theme_feedback  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core.db import DEV_ORG_ID, new_id, now_iso  # noqa: E402
from app.llm import pricing, providers  # noqa: E402


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"



def _poll(client, url, timeout=3.0):
    """短輪詢直到不再是 running（照抄 test_ads_progress_background.py 的 `_poll_plan_status`
    寫法，換成本票的 approve-status 端點）。"""
    deadline = time.time() + timeout
    data = client.get(url).json()["data"]
    while data["status"] == "running" and time.time() < deadline:
        time.sleep(0.02)
        data = client.get(url).json()["data"]
    return data


class _Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(
            main.conn, name=f"提案核可背景票測試品牌{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]
        product = bi_repo.create_product(main.conn, self.bid, name="測試商品", actor=ACTOR)
        bi_repo.save_product_economics(
            main.conn, self.bid, product["id"], actor=ACTOR, selling_price=1000,
            unit_variable_cost=400, currency="TWD", confirmed_by=ACTOR)
        self.cycle = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[product["id"]], pain_value=5000,
            objective="sales", actor=ACTOR)
        self.cycle_id = self.cycle["id"]
        proposal.seed_channel_plans(main.conn, self.bid, self.cycle_id)
        self._insert_plan()
        self._insert_cell()
        self._orig_batch = theme_batch.generate_preselected_batch
        self.approve_url = f"/api/campaigns/brands/{self.bid}/cycles/{self.cycle_id}/proposal/approve"
        self.status_url = f"/api/campaigns/brands/{self.bid}/cycles/{self.cycle_id}/proposal/approve-status"
        self.proposal_url = f"/api/campaigns/brands/{self.bid}/cycles/{self.cycle_id}/proposal"

    def tearDown(self):
        theme_batch.generate_preselected_batch = self._orig_batch

    def _insert_plan(self):
        plan = {
            "summary": "先用一個清楚方向開始", "difference": "",
            "audience": {"tiers": {}, "exclusions": []},
            "angles": [{"title": "商品亮點", "message": "說明商品能帶來的改變",
                       "why": "先做基本測試", "product_id": None}],
            "hypotheses": [], "grounding": {"facts": [], "inferences": [], "to_verify": []},
        }
        main.conn.execute(
            "INSERT INTO campaign_plan (id, org_id, campaign_cycle_id, brand_id, plan_version,"
            " plan_json, status, created_at) VALUES (%s, %s, %s, %s, 1, %s, 'draft', %s)",
            (new_id("cpl"), DEV_ORG_ID, self.cycle_id, self.bid, json.dumps(plan, ensure_ascii=False),
             now_iso()),
        )
        main.conn.execute(
            "UPDATE campaign_cycle SET plan_version = 1, status = 'REVIEW' WHERE id = %s",
            (self.cycle_id,))
        main.conn.commit()

    def _insert_cell(self) -> str:
        cell_id = new_id("exc")
        main.conn.execute(
            "INSERT INTO experiment_cell (id, org_id, campaign_cycle_id, brand_id, creative_angle,"
            " created_at) VALUES (%s, %s, %s, %s, '測試切角', %s)",
            (cell_id, DEV_ORG_ID, self.cycle_id, self.bid, now_iso()),
        )
        main.conn.commit()
        return cell_id


class ApproveReturnsPromptlyTest(_Base):
    def test_approve_returns_before_generation_finishes(self):
        """驗收 1：approve 這次請求不等生成跑完——不是靠量時間，而是直接證明生成被丟到
        `_progress_state` 背景引擎：回應當下該 key 已經是 running，且假批次函式此刻仍卡在
        `release.wait()`，還沒真的跑完。"""
        release = threading.Event()

        def _blocked_batch(conn, brand_id, cycle_id, *, actor):
            release.wait(timeout=5)
            return {"themes": [], "budget_stopped": False, "errors": []}

        theme_batch.generate_preselected_batch = _blocked_batch
        try:
            resp = self.client.post(self.approve_url)
            self.assertEqual(resp.status_code, 204)

            key = ads_routes._progress_key("proposal_generate", self.bid, self.cycle_id)
            entry = ads_routes._progress_state.get(key)
            self.assertIsNotNone(entry, "approve 應該把生成交給 _progress_state 背景引擎")
            self.assertEqual(entry["status"], "running",
                             "回應當下生成應該還在跑，不是已經同步跑完")
        finally:
            release.set()
        _poll(self.client, self.status_url)  # 收尾：讓背景執行緒真的跑完，不留尾巴給下一測試


class StatusPollingTest(_Base):
    def test_status_reports_running_then_done_without_manual_reload(self):
        """驗收 2：輪詢端點 running → done。"""
        release = threading.Event()

        def _blocked_then_ok(conn, brand_id, cycle_id, *, actor):
            release.wait(timeout=5)
            return {"themes": [{"id": "thm_x"}], "budget_stopped": False, "errors": []}

        theme_batch.generate_preselected_batch = _blocked_then_ok
        resp = self.client.post(self.approve_url)
        self.assertEqual(resp.status_code, 204)

        running = self.client.get(self.status_url).json()["data"]
        self.assertEqual(running["status"], "running")

        release.set()
        done = _poll(self.client, self.status_url)
        self.assertEqual(done["status"], "done")


class GenerationFailureDoesNotRetractApprovalTest(_Base):
    def test_generation_exception_reports_failed_but_approval_still_stands(self):
        """驗收 3：生成炸掉回報 failed，但核可本身（D2）不受影響。"""
        def _boom(conn, brand_id, cycle_id, *, actor):
            raise RuntimeError("測試用生成炸裂")

        theme_batch.generate_preselected_batch = _boom
        resp = self.client.post(self.approve_url)
        self.assertEqual(resp.status_code, 204)

        status = _poll(self.client, self.status_url)
        self.assertEqual(status["status"], "failed")
        self.assertIn("測試用生成炸裂", status["message"])

        approval = proposal.proposal(main.conn, self.bid, self.cycle_id)["approval"]
        self.assertTrue(approval["approved"], "生成失敗不該撤銷已經生效的核可")


class BudgetStoppedWithZeroThemesTest(_Base):
    def test_budget_stopped_with_no_themes_reports_ceiling_plainly(self):
        """票 13 第三審查的 blocker：`budget_stopped=True` 且一個主題都沒生出來——AI 花費
        已經頂到上限，八次生成一次都沒跑。狀態路由不能因為 work() 沒丟例外就回一句沒事的
        「done」；要老實說花費撞到上限、做出了 0 份，且核可依然生效（D2）。"""
        def _budget_capped_from_the_start(conn, brand_id, cycle_id, *, actor):
            return {"themes": [], "budget_stopped": True, "errors": []}

        theme_batch.generate_preselected_batch = _budget_capped_from_the_start
        resp = self.client.post(self.approve_url)
        self.assertEqual(resp.status_code, 204)

        status = _poll(self.client, self.status_url)
        self.assertNotEqual(status["status"], "done",
                            "撞到花費上限、0 份生成不是靜默成功，不能回 done")
        self.assertIn("上限", status["message"])
        self.assertIn("0", status["message"])

        approval = proposal.proposal(main.conn, self.bid, self.cycle_id)["approval"]
        self.assertTrue(approval["approved"], "撞到花費上限不該撤銷已經生效的核可")


class BudgetStoppedWithSomeThemesTest(_Base):
    def test_budget_stopped_with_some_themes_reports_how_many_were_made(self):
        """`budget_stopped=True` 但部分主題已經做出來——訊息要講出做了幾份，不是只講
        「撞到上限」四個字就交差，使用者才知道這次核可換到多少東西。"""
        def _budget_capped_after_two(conn, brand_id, cycle_id, *, actor):
            return {"themes": [{"id": "thm_a"}, {"id": "thm_b"}],
                    "budget_stopped": True, "errors": []}

        theme_batch.generate_preselected_batch = _budget_capped_after_two
        resp = self.client.post(self.approve_url)
        self.assertEqual(resp.status_code, 204)

        status = _poll(self.client, self.status_url)
        self.assertNotEqual(status["status"], "done")
        self.assertIn("上限", status["message"])
        self.assertIn("2", status["message"])

        approval = proposal.proposal(main.conn, self.bid, self.cycle_id)["approval"]
        self.assertTrue(approval["approved"])


class PartialErrorsReportSuccessAndFailureCountsTest(_Base):
    def test_some_generations_failed_reports_counts_without_raw_error_text(self):
        """`errors` 非空、`budget_stopped=False`——不是費用問題，是個別生成本身出狀況。
        訊息要講「幾份成功、幾份沒成功」，不能把底層例外原文丟給非技術使用者看。"""
        def _mixed_result(conn, brand_id, cycle_id, *, actor):
            return {"themes": [{"id": "thm_ok"}], "budget_stopped": False,
                    "errors": [{"experiment_cell_id": "ec1", "format_key": "single_image",
                                "error": "psycopg.errors.UndefinedTable: no such table 底層例外XYZ"}]}

        theme_batch.generate_preselected_batch = _mixed_result
        resp = self.client.post(self.approve_url)
        self.assertEqual(resp.status_code, 204)

        status = _poll(self.client, self.status_url)
        self.assertNotEqual(status["status"], "done",
                            "部分生成失敗不是靜默成功，不能回 done")
        self.assertIn("1", status["message"])
        self.assertNotIn("底層例外XYZ", status["message"],
                         "不能把原始例外文字丟給非技術使用者看")
        self.assertNotIn("OperationalError", status["message"])

        approval = proposal.proposal(main.conn, self.bid, self.cycle_id)["approval"]
        self.assertTrue(approval["approved"])


class ProgressCeilingScalesWithGenerationCountTest(_Base):
    """線上付費手測抓到的第一個真實缺陷（不是被造假 provider 蓋過去的那種）：8 次生成
    序列跑，`llm_task` 實測每次 23～31 秒，全批約 215 秒；`_PROGRESS_TIMEOUT_SECONDS`
    是給「一次生成」用的 90 秒常數，套在整批八次生成上一定比實際跑完還快逾時——正常
    成功的批次永遠回報「failed」，且逾時分支會 `_progress_clear()`，把剛做好的
    partial／budget_stopped 資訊一起丟掉。天花板要跟著這次核准實際會跑幾次生成走
    （`theme_batch.generation_count()`，跟花費預估同一個計數），不能是單次生成的常數。"""

    def _add_cells(self, n):
        for _ in range(n):
            self._insert_cell()

    def test_ceiling_covers_a_batch_still_within_the_derived_bound(self):
        # 4 個切角格（setUp 既有 1 格 + 這裡加 3 格）、每格基準配額 2 份（無歷史成效
        # 資料）＝ 8 次生成，跟報告裡的真實批次一致。derived ceiling = 8 * 90 = 720 秒，
        # 200 秒（模擬報告裡實測的 ~215 秒整批耗時）還在裡面，不該被判定逾時。
        self._add_cells(3)
        release = threading.Event()

        def _blocked_batch(conn, brand_id, cycle_id, *, actor):
            release.wait(timeout=5)
            return {"themes": [], "budget_stopped": False, "errors": []}

        theme_batch.generate_preselected_batch = _blocked_batch
        try:
            resp = self.client.post(self.approve_url)
            self.assertEqual(resp.status_code, 204)

            count = theme_batch.generation_count(main.conn, self.bid, self.cycle_id)
            self.assertEqual(count, 8, "測試前提：4 格 x 基準配額 2 = 8 次生成")

            key = ads_routes._progress_key("proposal_generate", self.bid, self.cycle_id)
            entry = ads_routes._progress_state[key]
            entry["started_at"] = time.time() - 200  # 模擬已經跑了 200 秒

            status = self.client.get(self.status_url).json()["data"]
            self.assertEqual(status["status"], "running",
                             "8 次生成、200 秒還在合理範圍內，不該被判定逾時失敗")
        finally:
            release.set()
        _poll(self.client, self.status_url)  # 收尾：讓背景執行緒真的跑完

    def test_genuinely_hung_job_still_eventually_reported_as_failed(self):
        """逾時判斷沒有被拿掉，只是天花板跟著生成次數走：真的卡住超過 derived ceiling
        還是要回報失敗，不能無限輪詢下去。"""
        self._add_cells(3)  # 共 4 格、8 次生成，derived ceiling = 8 * 90 = 720 秒
        release = threading.Event()

        def _blocked_forever(conn, brand_id, cycle_id, *, actor):
            release.wait(timeout=10)
            return {"themes": [], "budget_stopped": False, "errors": []}

        theme_batch.generate_preselected_batch = _blocked_forever
        try:
            resp = self.client.post(self.approve_url)
            self.assertEqual(resp.status_code, 204)

            key = ads_routes._progress_key("proposal_generate", self.bid, self.cycle_id)
            entry = ads_routes._progress_state[key]
            entry["started_at"] = time.time() - 800  # 超過 720 秒的 derived ceiling

            status = self.client.get(self.status_url).json()["data"]
            self.assertEqual(status["status"], "failed")
            self.assertIn("核可已經生效", status["message"])
        finally:
            release.set()


class GenerationCountInApprovalPayloadTest(_Base):
    def test_approval_payload_carries_generation_count(self):
        """獨立審查抓到的最後一個 blocker：畫面上「AI 正在生成素材」的等待文案，寫死抄
        單次生成慣例的「40 到 90 秒」，但這條路線一次跑 N 次序列生成，實測每次
        23～31 秒、8 次生成整批約 215 秒，字面上差了三倍。批次會跑幾次生成，
        `theme_batch.generation_count()` 早就算好（花費預估、逾時天花板都共用這個計數），
        這裡驗證 approval payload 也帶出同一個數字，不是另外編第三個計數器，也不是
        寫死 8。"""
        body = self.client.get(self.proposal_url).json()
        self.assertEqual(body["status"], "ready")
        expected = theme_batch.generation_count(main.conn, self.bid, self.cycle_id)
        self.assertGreater(expected, 0)
        self.assertEqual(body["approval"]["generation_count"], expected)


class EstimatedCostMatchesMatrixTest(_Base):
    def test_proposal_estimated_cost_equals_matrix_ceiling_times_generation_count(self):
        """驗收 4：核可前看得到的預估花費＝矩陣頁同一個 cost_ceiling 天花板 × 這次核准
        實際會跑的生成次數，不是另外編一個數字。"""
        body = self.client.get(self.proposal_url).json()
        self.assertEqual(body["status"], "ready")
        estimated = body["approval"]["estimated_generation_cost"]

        model = providers.resolve_model(task_type="creative_theme", conn=main.conn)
        per_generation_ceiling = pricing.cost_ceiling(model, theme_engine.THEME_MAX_TOKENS)
        historical_cells = nextcycle.historical_cell_performance(
            main.conn, self.bid, exclude_cycle_id=self.cycle_id)
        generation_count = sum(
            theme_feedback.theme_quota(cell, historical_cells)
            for cell in theme_batch.preselected_cells(main.conn, self.bid, self.cycle_id)
        )

        self.assertGreater(generation_count, 0)
        self.assertEqual(estimated, per_generation_ceiling * generation_count)


if __name__ == "__main__":
    unittest.main()
