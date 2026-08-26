# -*- coding: utf-8 -*-
"""app/tests/test_angle_rename.py — 票 04-angle-rename：切角改名。

決議（`.scratch/e2e-adflow/issues/04-angle-rename-todo.md`）：只做改名，不動 schema
（就地改 `experiment_cell.creative_angle`）；交接包（`publishing_package`）產出後鎖住。

FakeProvider 出一個方案、選定它，落地成 `experiment_cell`（`app/ads/plan.py` `_persist()`）
後才有格子可以改名，流程沿用 `test_ads_plan.py` 既有的兩步生成／選定寫法。
"""

import json
import time
import unittest

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.ads import plan as ads_plan
from app.brand_intelligence import repository as bi_repo
from app.core.db import DEV_ORG_ID, new_id, now_iso
from app.llm.providers import FakeProvider, ProviderResponse, Usage
from app.shared.web import OPERATOR

ACTOR = "測試員"

# BUG app/ads/routes_progress.py:96 — _progress_run() 跑在一個新開的 threading.Thread
# 裡，closure 捕捉的 main_mod.conn 靠 contextvar 找目前連線，contextvar 不會帶進手動開
# 的執行緒，一律「RuntimeError: no connection bound」，JSON 端點把它翻成
# status=failed——setUp() 靠 _run_plan()（走 plan/generate 這個背景引擎）先湊出一個
# 已選定的 experiment_cell 才能測改名，所以整個檔案的每個測試都中（同一個 BUG，
# 其他群組已標過）。
_BUG_PROGRESS_THREAD_NO_CONNECTION = pytest.mark.xfail(
    strict=True,
    reason="BUG app/ads/routes_progress.py:96 — _progress_run() 在新執行緒呼叫"
           " work()，closure 捕捉的 main_mod.conn 靠 contextvar 找目前連線，"
           "contextvar 不會帶進手動開的執行緒，一律「RuntimeError: no connection"
           " bound」，JSON 端點把它翻成 status=failed",
)

def _option(summary: str, angle_title: str, is_recommended: bool) -> dict:
    return {
        "is_recommended": is_recommended,
        "summary": summary,
        "difference": None,
        "audience": {
            "cold": {"description": "對價格敏感的新客。"},
            "warm": {"description": ""},
            "hot": {"description": ""},
            "exclusions": [],
        },
        "angles": [
            {"title": angle_title, "message": "一天不到十塊", "why": "價格敏感",
             "product_id": None},
        ],
        "hypotheses": [],
        "grounding": {"facts": [], "inferences": [], "to_verify": []},
    }


# _normalize_options() 不足 2 個有效方案算失敗（app/ads/plan.py 255 行註解），這裡給 2 個，
# 只有推薦的那個角度是測試要用的，另一個純粹湊數。
_ONE_ANGLE_OPTION = {
    "options": [
        _option("先打省錢角度看能不能帶下單。", "省錢角度", True),
        _option("改打風味角度看看。", "風味角度", False),
    ]
}


def _fake(text: str) -> ProviderResponse:
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=200, output_tokens=100),
                            stop_reason="end_turn")


def _run_plan(client, brand_id, cycle_id, timeout=5.0):
    started = client.post(f"/api/campaigns/{brand_id}/{cycle_id}/plan/generate", json={})
    assert started.status_code == 204, started.text
    status_url = f"/api/campaigns/{brand_id}/{cycle_id}/plan/status"
    deadline = time.time() + timeout
    state = client.get(status_url).json()["data"]
    while state["status"] == "running" and time.time() < deadline:
        time.sleep(0.02)
        state = client.get(status_url).json()["data"]
    return state


@_BUG_PROGRESS_THREAD_NO_CONNECTION
class AngleRenameTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]
        self.product = bi_repo.create_product(main.conn, self.bid, name="虛構濾掛組",
                                              actor=ACTOR)["id"]
        bi_repo.create_brand_fact(main.conn, self.bid, actor=ACTOR, fact_type="positioning",
                                  label="定位", value="單一產區濾掛咖啡。",
                                  status="confirmed", confirmed_by=ACTOR)
        resp = self.client.post(f"/api/campaigns/{self.bid}",
                                json={"product_ids": [self.product], "budget": 10000,
                                      "objective": "sales"})
        self.cycle_id = resp.json()["cycle_id"]

        self._orig_provider = ads_plan.PROVIDER
        ads_plan.PROVIDER = FakeProvider(
            response=_fake(json.dumps(_ONE_ANGLE_OPTION, ensure_ascii=False)))
        _run_plan(self.client, self.bid, self.cycle_id)
        select = self.client.post(f"/api/campaigns/{self.bid}/{self.cycle_id}/plan/select")
        assert select.status_code == 204, select.text

        self.cell_id = main.conn.execute(
            "SELECT id FROM experiment_cell WHERE brand_id = %s AND campaign_cycle_id = %s",
            (self.bid, self.cycle_id),
        ).fetchone()["id"]

    def tearDown(self):
        ads_plan.PROVIDER = self._orig_provider

    def _rename(self, creative_angle, cell_id=None):
        return self.client.patch(
            f"/api/campaigns/{self.bid}/{self.cycle_id}/cells/{cell_id or self.cell_id}/angle",
            json={"creative_angle": creative_angle},
        )

    def test_rename_success_writes_audit(self):
        resp = self._rename("省錢角度改版")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json(), {"ok": True, "creative_angle": "省錢角度改版"})

        cell = ads_plan.get_cell(main.conn, self.bid, self.cycle_id, self.cell_id)
        self.assertEqual(cell["creative_angle"], "省錢角度改版")

        audit = main.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'experiment_cell'"
            " AND entity_id = %s AND action = 'rename_angle'", (self.cell_id,),
        ).fetchone()
        self.assertIsNotNone(audit)
        self.assertEqual(json.loads(audit["before_json"])["creative_angle"], "省錢角度")
        self.assertEqual(json.loads(audit["after_json"])["creative_angle"], "省錢角度改版")
        self.assertEqual(audit["actor"], OPERATOR)

    def test_blank_name_rejected(self):
        resp = self._rename("   ")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("detail", resp.json())

    def test_too_long_name_rejected(self):
        resp = self._rename("字" * 31)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("detail", resp.json())

    def test_locked_after_publishing_package_exists(self):
        main.conn.execute(
            "INSERT INTO publishing_package (id, org_id, brand_id, campaign_cycle_id,"
            " experiment_cell_id, product_id, hook_id, copy_variant_id, campaign_name,"
            " adset_name, ad_name, destination_url, utm_json, objective, daily_budget,"
            " status, created_at) VALUES (%s, %s, %s, %s, %s, NULL, NULL, NULL, 'c', 'a', 'ad', '',"
            " '{}', 'sales', 100, 'ready', %s)",
            (new_id("pkg"), DEV_ORG_ID, self.bid, self.cycle_id, self.cell_id, now_iso()),
        )
        main.conn.commit()

        resp = self._rename("再改一次")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("detail", resp.json())
        cell = ads_plan.get_cell(main.conn, self.bid, self.cycle_id, self.cell_id)
        self.assertEqual(cell["creative_angle"], "省錢角度")  # 沒被改動

    def test_cell_not_found(self):
        resp = self._rename("隨便", cell_id="exc_not_a_real_one")
        self.assertEqual(resp.status_code, 404)

    def test_list_cell_angles_keeps_insertion_order_not_id_order(self):
        """同一毫秒產的 ULID 尾碼隨機，不能拿 id 排序；提案頁是用「第幾個」對齊 plan.angles。"""
        ts = now_iso()
        for cell_id, angle in ((new_id("exc"), "第二格"), (new_id("exc"), "第三格")):
            main.conn.execute(
                "INSERT INTO experiment_cell (id, org_id, brand_id, campaign_cycle_id,"
                " creative_angle, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
                (cell_id, DEV_ORG_ID, self.bid, self.cycle_id, angle, ts))
        main.conn.commit()
        names = [c["creative_angle"] for c in ads_plan.list_cell_angles(main.conn, self.bid, self.cycle_id)]
        self.assertEqual(names[-2:], ["第二格", "第三格"])

