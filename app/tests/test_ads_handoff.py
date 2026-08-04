# -*- coding: utf-8 -*-
"""app/tests/test_ads_handoff.py — 廣告分支票 8：投放交接包、具名授權、回填 Meta ID。

重點在安全邊界（鐵則 4）：授權必須具名、投放啟動必須引用授權、
不由「交接包產好了」或「素材確認了」自動推導。品牌名一律虛構。
"""

import atexit
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_handoff_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import creative as ads_creative  # noqa: E402
from app.ads import handoff as ads_handoff  # noqa: E402
from app.ads import plan as ads_plan  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core.db import new_id, now_iso  # noqa: E402
from app.llm.providers import FakeProvider, ProviderResponse, Usage  # noqa: E402

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

# 票 4：計畫生成一次出多個方案，測試只挑第一個（AI 推薦、預設選定的那個）。
_PLAN_OPTIONS = {
    "options": [
        {
            "is_recommended": True,
            "summary": "測試打法", "audience": _AUDIENCE,
            "angles": [{"title": "早上第一杯", "message": "訊息", "why": "", "product_id": None}],
            "hypotheses": [], "grounding": {"facts": [], "inferences": [], "to_verify": []},
        },
        {
            "is_recommended": False,
            "summary": "備用方案", "audience": _AUDIENCE,
            "angles": [{"title": "備用切角", "message": "備用訊息", "why": "", "product_id": None}],
            "hypotheses": [], "grounding": {"facts": [], "inferences": [], "to_verify": []},
        },
    ]
}


def _fake(text: str) -> ProviderResponse:
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=400, output_tokens=200),
                            stop_reason="end_turn")


def _wait_progress(client, url, timeout=5.0):
    """票 M3：進度頁改背景執行緒後，?run=1 不再同步等完；短輪詢模擬瀏覽器 meta refresh，
    等到真的轉址（303）或逾時為止（FakeProvider 幾乎瞬間完成，正常情況幾毫秒內就會轉址）。"""
    deadline = time.time() + timeout
    resp = client.get(url, follow_redirects=False)
    while resp.status_code != 303 and time.time() < deadline:
        time.sleep(0.02)
        resp = client.get(url, follow_redirects=False)
    return resp


class _BaseHandoffTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.client.post("/settings/operator", data={"name": ACTOR, "next": "/"},
                         follow_redirects=False)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]
        resp = self.client.post(f"/brands/{self.bid}/ads/new",
                                data={"slider_index": "5", "objective": "sales"},
                                follow_redirects=False)
        self.cycle_id = resp.headers["location"].split("/ads/")[1].split("?")[0]

        self._orig_plan, self._orig_creative = ads_plan.PROVIDER, ads_creative.PROVIDER
        ads_plan.PROVIDER = FakeProvider(
            response=_fake(json.dumps(_PLAN_OPTIONS, ensure_ascii=False)))
        _wait_progress(self.client, f"/brands/{self.bid}/ads/{self.cycle_id}/plan/progress?run=1")
        self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/plan/select",
                         data={}, follow_redirects=False)
        self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/plan/approve",
                         follow_redirects=False)
        cell_id = main.conn.execute(
            "SELECT id FROM experiment_cell WHERE campaign_cycle_id = ?",
            (self.cycle_id,)).fetchone()["id"]
        reply = json.dumps({"variants": [
            {"cell_id": cell_id, "variant_type": "hook", "content": "每天第一杯，別再將就",
             "rationale": "", "creative_angle_number": 16, "on_camera": False,
             "cut_type": "pain_visualized", "quote_source": None,
             "fingerprint": {"angle": "pain", "tone": "blunt",
                                              "format": "text_focus", "selling_point": "quality"}},
            {"cell_id": cell_id, "variant_type": "copy", "content": "三分鐘沖一杯好咖啡。",
             "rationale": "", "creative_angle_number": 9, "on_camera": False,
             "cut_type": "value_reframe", "quote_source": None,
             "fingerprint": {"angle": "benefit", "tone": "warm",
                                              "format": "text_focus",
                                              "selling_point": "convenience"}},
            {"cell_id": cell_id, "variant_type": "image_prompt",
             "content": "A warm morning desk with a pour-over set",
             "rationale": "", "creative_angle_number": 9, "on_camera": False,
             "cut_type": None, "quote_source": None,
             "fingerprint": {"angle": "scene", "tone": "warm",
                                              "format": "single_image",
                                              "selling_point": "quality"}},
        ]}, ensure_ascii=False)
        ads_creative.PROVIDER = FakeProvider(response=_fake(reply))
        _wait_progress(self.client,
                       f"/brands/{self.bid}/ads/{self.cycle_id}/creatives/progress?run=1")
        self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives/approve",
                         follow_redirects=False)

    def tearDown(self):
        ads_plan.PROVIDER, ads_creative.PROVIDER = self._orig_plan, self._orig_creative

    def _build(self):
        return self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/handoff/build",
                                follow_redirects=False)

    def _packages(self):
        return ads_handoff.list_packages(main.conn, self.bid, self.cycle_id)

    def _activate(self, package_id, **overrides):
        data = {"meta_campaign_id": "23851234567890123",
                "meta_account_id": "act_9876543210"}
        data.update(overrides)
        return self.client.post(
            f"/brands/{self.bid}/ads/{self.cycle_id}/handoff/{package_id}/activate",
            data=data, follow_redirects=False)


class PackageBuildTest(_BaseHandoffTest):
    def test_builds_one_package_per_cell_with_program_generated_names(self):
        self._build()
        packages = self._packages()
        self.assertEqual(len(packages), 1)
        package = packages[0]
        self.assertIn("虛構晨光咖啡", package["campaign_name"])
        self.assertIn("sales", package["campaign_name"])
        self.assertTrue(package["adset_name"].startswith("早上第一杯"))

    def test_utm_carries_cycle_and_cell_ids(self):
        """UTM 帶內部 id，成效回來時才對得回是哪一期哪一個切角。"""
        self._build()
        utm = json.loads(self._packages()[0]["utm_json"])
        self.assertEqual(utm["utm_campaign"], self.cycle_id)
        self.assertEqual(utm["utm_source"], "facebook")

    def test_daily_budget_is_computed_not_asked_from_llm(self):
        self._build()
        package = self._packages()[0]
        cycle = ads_repo.get_cycle(main.conn, self.bid, self.cycle_id)
        expected = cycle["budget"] / ads_repo.derived_plan(cycle)["duration_days"]
        self.assertAlmostEqual(package["daily_budget"], round(expected, 2), places=1)

    def test_page_uses_meta_field_labels(self):
        self._build()
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/handoff")
        for label in ("行銷活動名稱", "廣告組合名稱", "每日預算", "主要文字"):
            self.assertIn(label, page.text)

    def test_missing_website_says_so_instead_of_silently_blank(self):
        self._build()
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/handoff")
        self.assertIn("還沒有登記官網網址", page.text)

    def test_website_channel_becomes_destination_url(self):
        bi_repo.create_channel(main.conn, self.bid, channel_type="website",
                               name="官網", identifier="https://example.test",
                               actor=ACTOR)
        self._build()
        package = self._packages()[0]
        self.assertTrue(package["full_url"].startswith("https://example.test?utm_source"))

    def test_build_without_adopted_creatives_is_refused_politely(self):
        resp = self.client.post(f"/brands/{self.bid}/ads/new",
                                data={"slider_index": "3", "objective": "awareness"},
                                follow_redirects=False)
        other = resp.headers["location"].split("/ads/")[1].split("?")[0]
        resp = self.client.post(f"/brands/{self.bid}/ads/{other}/handoff/build",
                                follow_redirects=False)
        self.assertIn("kind=warn", resp.headers["location"])


class WildcardVariantExcludedFromOfficialPickTest(_BaseHandoffTest):
    """C線票6a 修正（#57）：野路子實驗組不得蓋過交接包裡正式選中的 Hook。

    實驗組 recommendation_rank 固定寫 0（見 creative.py），若交接包選 hook 時沒排除它，
    `next()` 會優先選到刻意違反禁令的內容，讓交接包顯示的不是真正要貼進 Meta 的正常素材。
    """

    def _insert_experiment_hook(self):
        real_hook = main.conn.execute(
            "SELECT * FROM creative_variant WHERE campaign_cycle_id = ? AND variant_type = 'hook'"
            " ORDER BY recommendation_rank LIMIT 1", (self.cycle_id,)).fetchone()
        main.conn.execute(
            "INSERT INTO creative_variant (id, variant_type, creative_brief_id,"
            " campaign_cycle_id, experiment_cell_id, brand_id, product_id, attributes_json,"
            " fingerprint_json, rationale, recommendation_rank, status, created_at)"
            " VALUES ('cvr_wildcard_test', 'hook', ?, ?, ?, ?, ?, ?, '{}', '', 0, 'DRAFT',"
            " '2026-08-02T00:00:00')",
            (real_hook["creative_brief_id"], self.cycle_id, real_hook["experiment_cell_id"],
             self.bid, real_hook["product_id"],
             json.dumps({"content": "刻意違反禁令的野路子內容", "experiment_variant": True,
                        "experiment_rule_text": "測試禁令", "creative_angle_number": None,
                        "on_camera": False, "cut_type": None, "quote_source": None},
                       ensure_ascii=False)))
        main.conn.commit()

    def test_build_packages_picks_real_hook_not_experiment_variant(self):
        self._insert_experiment_hook()
        self._build()
        package = self._packages()[0]
        self.assertEqual(package["hook_text"], "每天第一杯，別再將就")
        self.assertNotIn("野路子", package["hook_text"])


class MissingFieldReportTest(_BaseHandoffTest):
    def test_report_is_recorded_and_acknowledged(self):
        self._build()
        resp = self.client.post(
            f"/brands/{self.bid}/ads/{self.cycle_id}/handoff/missing-field",
            data={"field_key": "daily_budget"}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        row = main.conn.execute(
            "SELECT * FROM audit_log WHERE action = 'field_not_found'"
            " ORDER BY created_at DESC LIMIT 1").fetchone()
        self.assertIsNotNone(row)
        self.assertIn("每日預算", row["after_json"])


class ActivationGateTest(_BaseHandoffTest):
    def test_activation_creates_named_authorization_and_mapping(self):
        self._build()
        package = self._packages()[0]
        resp = self._activate(package["id"])
        self.assertEqual(resp.status_code, 303)

        auth = main.conn.execute(
            "SELECT * FROM activation_authorization WHERE scope_ref = ?",
            (package["id"],)).fetchone()
        self.assertEqual(auth["authorized_by"], ACTOR)

        activation = main.conn.execute(
            "SELECT * FROM campaign_activation WHERE campaign_cycle_id = ?",
            (self.cycle_id,)).fetchone()
        self.assertEqual(activation["authorization_id"], auth["id"])
        self.assertEqual(activation["activated_by"], ACTOR)

        mapping = main.conn.execute(
            "SELECT * FROM external_ad_mapping WHERE publishing_package_id = ?",
            (package["id"],)).fetchone()
        self.assertEqual(mapping["meta_campaign_id"], "23851234567890123")
        self.assertEqual(mapping["claim_status"], "confirmed")

    def test_cycle_only_goes_live_after_the_human_confirms(self):
        """關卡三的重點：交接包產好、素材確認完，狀態都還不是投放中。"""
        self._build()
        self.assertEqual(
            ads_repo.get_cycle(main.conn, self.bid, self.cycle_id)["status"], "PRODUCTION")
        self._activate(self._packages()[0]["id"])
        self.assertEqual(
            ads_repo.get_cycle(main.conn, self.bid, self.cycle_id)["status"], "LIVE")

    def test_campaign_id_is_required(self):
        self._build()
        resp = self._activate(self._packages()[0]["id"], meta_campaign_id="")
        self.assertIn("kind=warn", resp.headers["location"])
        self.assertIsNone(main.conn.execute(
            "SELECT 1 FROM campaign_activation WHERE campaign_cycle_id = ?",
            (self.cycle_id,)).fetchone())

    def test_activation_requires_named_operator(self):
        self._build()
        package_id = self._packages()[0]["id"]
        self.client.cookies.clear()
        resp = self._activate(package_id)
        self.assertIn("/settings/operator", resp.headers["location"])
        self.assertIsNone(main.conn.execute(
            "SELECT 1 FROM activation_authorization WHERE scope_ref = ?",
            (package_id,)).fetchone())

    def test_ad_account_is_created_without_a_brand_binding(self):
        """廣告帳號不綁品牌——一個帳號可服務多個品牌（決策 0022 第 6 點）。"""
        self._build()
        self._activate(self._packages()[0]["id"])
        account = main.conn.execute(
            "SELECT * FROM ad_account WHERE external_account_id = 'act_9876543210'"
        ).fetchone()
        self.assertIsNotNone(account)
        self.assertNotIn("brand_id", account.keys())

    def test_rebuild_keeps_packages_that_are_already_live(self):
        """已回報投放的交接包不能被重出洗掉，否則對應關係就斷了。"""
        self._build()
        package_id = self._packages()[0]["id"]
        self._activate(package_id)
        self._build()
        ids = [p["id"] for p in self._packages()]
        self.assertIn(package_id, ids)

    def test_page_shows_who_confirmed(self):
        self._build()
        self._activate(self._packages()[0]["id"])
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/handoff")
        self.assertIn("已回報開始投放", page.text)
        self.assertIn(ACTOR, page.text)


class DailyBudgetInvariantTest(unittest.TestCase):
    """修憲落地 M1：build_packages() 的每日預算加總不能超過計畫總額。

    原本 bug：一個產品配多個切角時，`allocations[product_id]["allocated_budget"] / days`
    沒再除以切角數，每個切角組合各自拿到整個產品的日預算——貼進 Meta 後實際日花費
    是計畫的切角數倍。這裡直接呼叫 build_packages()（不經 LLM 規劃管線），
    用可控的整數預算組出多產品、多切角、切角未綁產品三種情境驗證加總不變式：
    所有 package 的 daily_budget 加總 × 天數 = 計畫總額。
    """

    def setUp(self):
        self.bid = bi_repo.create_brand(
            main.conn, name="虛構晨光咖啡二號店", client_name="測試客戶", actor=ACTOR)["id"]

    def _product(self, name: str) -> str:
        return bi_repo.create_product(main.conn, self.bid, name=name, actor=ACTOR)["id"]

    def _cell(self, cycle_id: str, product_id, angle: str) -> str:
        """直接建一個切角＋一組已採用的 hook／copy 素材，不經 LLM 生成管線。"""
        cell_id = new_id("exc")
        main.conn.execute(
            "INSERT INTO experiment_cell (id, campaign_cycle_id, brand_id, product_id,"
            " audience, creative_angle, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (cell_id, cycle_id, self.bid, product_id, "測試受眾", angle, now_iso()),
        )
        brief_id = ads_creative._brief_for_cell(
            main.conn, self.bid, cycle_id, {"id": cell_id, "creative_angle": angle}, now_iso())
        for variant_type, content in (("hook", f"{angle}主打句"), ("copy", f"{angle}內文")):
            main.conn.execute(
                "INSERT INTO creative_variant (id, variant_type, creative_brief_id,"
                " campaign_cycle_id, experiment_cell_id, brand_id, product_id, attributes_json,"
                " fingerprint_json, rationale, recommendation_rank, status, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', '', 1, 'DRAFT', ?)",
                (new_id("cvr"), variant_type, brief_id, cycle_id, cell_id, self.bid, product_id,
                 json.dumps({"content": content}, ensure_ascii=False), now_iso()),
            )
        main.conn.commit()
        return cell_id

    def _built_packages(self, cycle_id: str) -> list:
        ads_handoff.build_packages(main.conn, self.bid, cycle_id, ACTOR)
        return ads_handoff.list_packages(main.conn, self.bid, cycle_id)

    def _plan_total(self, cycle_id: str) -> float:
        cycle = ads_repo.get_cycle(main.conn, self.bid, cycle_id)
        return cycle["budget"]

    def test_single_product_four_angles_daily_budget_is_not_quadrupled(self):
        """直接重現票上描述的 bug 情境：一個產品配 DEFAULT_ANGLE_COUNT=4 個切角。"""
        product_id = self._product("虛構濾掛咖啡")
        cycle = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[product_id], pain_value=4000, objective="sales",
            actor=ACTOR, start_date="2026-08-01", duration_days=10)
        for i in range(4):
            self._cell(cycle["id"], product_id, f"切角{i}")

        packages = self._built_packages(cycle["id"])
        self.assertEqual(len(packages), 4)
        # 修好之前：每份都是 400（整個產品的日預算），4 份加總會變成計畫的 4 倍。
        for package in packages:
            self.assertEqual(package["daily_budget"], 100.0)

        total = sum(p["daily_budget"] for p in packages) * 10
        self.assertAlmostEqual(total, self._plan_total(cycle["id"]), places=2)

    def test_multi_product_multi_angle_budget_sums_to_plan_total(self):
        """多產品、且各產品切角數不同時，加總仍要等於計畫總額。"""
        product_a = self._product("虛構濾掛咖啡")
        product_b = self._product("虛構冷萃咖啡")
        cycle = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[product_a, product_b], pain_value=12000,
            objective="sales", actor=ACTOR, start_date="2026-08-01", duration_days=10)
        for i in range(2):
            self._cell(cycle["id"], product_a, f"A切角{i}")
        for i in range(3):
            self._cell(cycle["id"], product_b, f"B切角{i}")

        packages = self._built_packages(cycle["id"])
        self.assertEqual(len(packages), 5)
        by_product = {"A": [], "B": []}
        for package in packages:
            key = "A" if package["product_id"] == product_a else "B"
            by_product[key].append(package["daily_budget"])

        # 兩產品沒有毛利資料，均分預算：各 6000，A 兩個切角、B 三個切角。
        for daily in by_product["A"]:
            self.assertEqual(daily, 300.0)
        for daily in by_product["B"]:
            self.assertEqual(daily, 200.0)

        total = sum(p["daily_budget"] for p in packages) * 10
        self.assertAlmostEqual(total, self._plan_total(cycle["id"]), places=2)

    def test_angles_without_product_binding_still_sum_to_plan_total(self):
        """切角沒綁產品：走整期日預算除以切角數的既有分支，加總不變式一樣要守住。"""
        cycle = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[], pain_value=9000, objective="sales",
            actor=ACTOR, start_date="2026-08-01", duration_days=10)
        for i in range(3):
            self._cell(cycle["id"], None, f"切角{i}")

        packages = self._built_packages(cycle["id"])
        self.assertEqual(len(packages), 3)
        for package in packages:
            self.assertEqual(package["daily_budget"], 300.0)

        total = sum(p["daily_budget"] for p in packages) * 10
        self.assertAlmostEqual(total, self._plan_total(cycle["id"]), places=2)


if __name__ == "__main__":
    unittest.main()
