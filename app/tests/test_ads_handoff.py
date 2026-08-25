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
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_handoff_")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import handoff as ads_handoff  # noqa: E402
from app.ads import plan as ads_plan  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.ads import theme_repository as theme_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import db as coredb  # noqa: E402
from app.core.db import new_id, now_iso  # noqa: E402
from app.llm.providers import FakeProvider, ProviderResponse, Usage  # noqa: E402
from app.shared.web import OPERATOR  # noqa: E402



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


class _BaseHandoffTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]
        resp = self.client.post(f"/api/campaigns/{self.bid}",
                                json={"product_ids": [], "budget": 10000, "objective": "sales"})
        self.cycle_id = resp.json()["cycle_id"]

        self._orig_plan = ads_plan.PROVIDER
        ads_plan.PROVIDER = FakeProvider(
            response=_fake(json.dumps(_PLAN_OPTIONS, ensure_ascii=False)))
        ok, err = ads_plan.generate_options(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)
        self.client.post(f"/api/campaigns/{self.bid}/{self.cycle_id}/plan/select", json={})
        self.client.post(f"/api/campaigns/{self.bid}/{self.cycle_id}/plan/approve")
        cell_id = self.cell_id = main.conn.execute(
            "SELECT id FROM experiment_cell WHERE campaign_cycle_id = %s",
            (self.cycle_id,)).fetchone()["id"]

        # 票 02-repoint-creative-readers：素材資料源改主題表，不再經 LLM 生成管線
        # （generate() 仍寫 creative_variant，但已沒有任何讀取路徑會看它），直接建一顆
        # 已採用主題，內容比照原本假回覆的三則。
        theme = theme_repo.create_theme(
            main.conn, self.bid, campaign_cycle_id=self.cycle_id, experiment_cell_id=cell_id,
            format_key="single_image", name="早上第一杯主題", folder_code="H1N0", actor=ACTOR,
            components=[
                {"component_type": "title", "content": "每天第一杯，別再將就",
                 "fingerprint_json": {"angle": "pain", "tone": "blunt",
                                      "format": "text_focus", "selling_point": "quality"}},
                {"component_type": "body", "content": "三分鐘沖一杯好咖啡。",
                 "fingerprint_json": {"angle": "benefit", "tone": "warm",
                                      "format": "text_focus", "selling_point": "convenience"}},
                {"component_type": "image_prompt",
                 "content": "A warm morning desk with a pour-over set",
                 "fingerprint_json": {"angle": "scene", "tone": "warm",
                                      "format": "single_image", "selling_point": "quality"}},
            ],
        )
        theme_repo.adopt_theme(main.conn, self.bid, theme["id"], actor=ACTOR)

    def tearDown(self):
        ads_plan.PROVIDER = self._orig_plan

    def _build(self):
        return self.client.post(
            f"/api/campaigns/{self.bid}/{self.cycle_id}/handoff/build")

    def _packages(self):
        return ads_handoff.list_packages(main.conn, self.bid, self.cycle_id)

    def _activate(self, package_id, **overrides):
        data = {"meta_campaign_id": "23851234567890123"}
        data.update(overrides)
        return self.client.post(
            f"/api/campaigns/{self.bid}/{self.cycle_id}/handoff/{package_id}/activate",
            json=data)


# BUG app/core/settings.py:143 — brand_llm_spent() 回傳 row["n"] or 0.0，SUM(numeric)
# 有值時是 Decimal，宣告回傳型別是 float 但沒轉型；budget_exceeded_message() 接著
# `spent + cost`（Decimal + float）一律 TypeError。plan/approve 會觸發
# theme_batch.generate_preselected_batch() -> _budget_blocked() -> 這裡，
# _BaseHandoffTest.setUp() 呼叫 plan/approve，所以繼承它的整個測試類別都中
# （同一個 BUG，brand_intelligence 群組已標過）。
_BUG_DECIMAL_PLUS_FLOAT = pytest.mark.xfail(
    strict=True,
    reason='BUG app/core/settings.py:143 — brand_llm_spent() 回傳 Decimal，'
           "budget_exceeded_message() 的 spent + cost 一律 TypeError",
)


@_BUG_DECIMAL_PLUS_FLOAT
class PackageBuildTest(_BaseHandoffTest):
    def test_builds_one_package_per_cell_with_program_generated_names(self):
        self._build()
        packages = self._packages()
        self.assertEqual(len(packages), 1)
        package = packages[0]
        self.assertIn("虛構晨光咖啡", package["campaign_name"])
        self.assertIn("sales", package["campaign_name"])
        self.assertTrue(package["adset_name"].startswith("早上第一杯"))

    def test_campaign_name_ends_with_cycle_short_code(self):
        """票 22：建議活動名稱尾巴帶檔期短碼，跟主題資料夾短碼同一種風格（尾 4 碼）——
        投手照抄這個名字，Meta 動態變數代回來的名字裡就找得回是哪一期。"""
        self._build()
        package = self._packages()[0]
        self.assertTrue(package["campaign_name"].endswith(self.cycle_id[-4:]))
        self.assertEqual(len(self.cycle_id[-4:]), 4)

    def test_utm_campaign_is_meta_dynamic_variable_not_hardcoded_cycle_id(self):
        """票 22：utm_campaign 改用 Meta 動態變數 {{campaign.name}} 的字面值——寫死
        cycle id 在投手手動調整過 Meta 活動結構後會跟實際脫鉤，動態變數才能自動跟著走。
        utm_content 維持 cell id：那是系統內部的切角格，不是 Meta 的廣告物件。"""
        self._build()
        utm = json.loads(self._packages()[0]["utm_json"])
        self.assertEqual(utm["utm_campaign"], "{{campaign.name}}")
        self.assertEqual(utm["utm_content"], self.cell_id)
        self.assertEqual(utm["utm_source"], "facebook")

    def test_full_url_leaves_meta_dynamic_variable_unencoded(self):
        """{{campaign.name}} 要原封不動留在網址裡，quote() 把大括號編碼成 %7B%7D 的話
        Meta 就認不出這是動態變數了（票 22 UTM 值改動連帶要顧到的編碼細節）。"""
        bi_repo.create_channel(main.conn, self.bid, channel_type="website",
                               name="官網", identifier="https://example.test",
                               actor=ACTOR)
        self._build()
        full_url = self._packages()[0]["full_url"]
        self.assertIn("utm_campaign={{campaign.name}}", full_url)
        self.assertNotIn("%7B", full_url)

    def test_daily_budget_is_computed_not_asked_from_llm(self):
        self._build()
        package = self._packages()[0]
        cycle = ads_repo.get_cycle(main.conn, self.bid, self.cycle_id)
        expected = cycle["budget"] / ads_repo.derived_plan(cycle)["duration_days"]
        self.assertAlmostEqual(package["daily_budget"], round(expected, 2), places=1)

    def test_missing_website_says_so_instead_of_silently_blank(self):
        """沒登記官網 → full_url 落空，API 誠實回 null，不是拼一段沒有網域的網址。"""
        self._build()
        resp = self.client.get(f"/api/campaigns/{self.bid}/{self.cycle_id}/handoff")
        self.assertEqual(resp.status_code, 200)
        packages = resp.json()["data"]["packages"]
        self.assertTrue(packages)
        for package in packages:
            self.assertIsNone(package["full_url"])

    def test_website_channel_becomes_destination_url(self):
        bi_repo.create_channel(main.conn, self.bid, channel_type="website",
                               name="官網", identifier="https://example.test",
                               actor=ACTOR)
        self._build()
        package = self._packages()[0]
        self.assertTrue(package["full_url"].startswith("https://example.test?utm_source"))

    def test_build_without_adopted_creatives_is_refused_politely(self):
        resp = self.client.post(f"/api/campaigns/{self.bid}",
                                json={"product_ids": [], "budget": 5000, "objective": "awareness"})
        other = resp.json()["cycle_id"]
        built = ads_handoff.build_packages(main.conn, self.bid, other, ACTOR)
        self.assertEqual(built, 0)
        self.assertEqual(ads_handoff.list_packages(main.conn, self.bid, other), [])


@_BUG_DECIMAL_PLUS_FLOAT
class MissingFieldReportTest(_BaseHandoffTest):
    def test_report_is_recorded_and_acknowledged(self):
        self._build()
        ads_handoff.report_missing_field(
            main.conn, self.bid, self.cycle_id, "daily_budget", OPERATOR)
        row = main.conn.execute(
            "SELECT * FROM audit_log WHERE action = 'field_not_found'"
            " ORDER BY created_at DESC LIMIT 1").fetchone()
        self.assertIsNotNone(row)
        self.assertIn("每日預算", row["after_json"])


@_BUG_DECIMAL_PLUS_FLOAT
class ActivationGateTest(_BaseHandoffTest):
    def test_activation_creates_named_authorization_and_mapping(self):
        self._build()
        package = self._packages()[0]
        resp = self._activate(package["id"])
        self.assertEqual(resp.status_code, 204)

        auth = main.conn.execute(
            "SELECT * FROM activation_authorization WHERE scope_ref = %s",
            (package["id"],)).fetchone()
        self.assertEqual(auth["authorized_by"], OPERATOR)

        activation = main.conn.execute(
            "SELECT * FROM campaign_activation WHERE campaign_cycle_id = %s",
            (self.cycle_id,)).fetchone()
        self.assertEqual(activation["authorization_id"], auth["id"])
        self.assertEqual(activation["activated_by"], OPERATOR)

        mapping = main.conn.execute(
            "SELECT * FROM external_ad_mapping WHERE publishing_package_id = %s",
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
        self.assertEqual(resp.status_code, 400)
        self.assertIsNone(main.conn.execute(
            "SELECT 1 FROM campaign_activation WHERE campaign_cycle_id = %s",
            (self.cycle_id,)).fetchone())

    def test_activation_works_without_operator_cookie(self):
        """ADR 0004：投放授權關卡本身仍要人按一次確認，但不再要求先設定操作人。"""
        self._build()
        package_id = self._packages()[0]["id"]
        self.client.cookies.clear()
        resp = self._activate(package_id)
        self.assertEqual(resp.status_code, 204)
        auth = main.conn.execute(
            "SELECT * FROM activation_authorization WHERE scope_ref = %s",
            (package_id,)).fetchone()
        self.assertIsNotNone(auth)
        self.assertEqual(auth["authorized_by"], OPERATOR)

    def test_ad_account_is_created_without_a_brand_binding(self):
        """廣告帳號不綁品牌——一個帳號可服務多個品牌（決策 0022 第 6 點）。"""
        self._build()
        ads_handoff.authorize_and_map(
            main.conn, self.bid, self.cycle_id, self._packages()[0]["id"],
            meta_ids={"meta_campaign_id": "23851234567890123",
                      "meta_account_id": "act_9876543210"},
            actor=OPERATOR)
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
        """直接建一個切角＋一顆已採用主題（標題／文案），不經 LLM 生成管線
        （票 02-repoint-creative-readers：資料源改主題表）。"""
        cell_id = new_id("exc")
        main.conn.execute(
            "INSERT INTO experiment_cell (id, org_id, campaign_cycle_id, brand_id, product_id,"
            " audience, creative_angle, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (cell_id, coredb.DEV_ORG_ID, cycle_id, self.bid, product_id, "測試受眾", angle, now_iso()),
        )
        main.conn.commit()
        theme = theme_repo.create_theme(
            main.conn, self.bid, campaign_cycle_id=cycle_id, experiment_cell_id=cell_id,
            format_key="single_image", name=f"{angle}主題", folder_code="D1V0", actor=ACTOR,
            components=[
                {"component_type": "title", "content": f"{angle}主打句"},
                {"component_type": "body", "content": f"{angle}內文"},
            ],
        )
        theme_repo.adopt_theme(main.conn, self.bid, theme["id"], actor=ACTOR)
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


class NamingCheckTest(unittest.TestCase):
    """B4R 收尾包項目 1：naming_check 只在「同品牌跨檔期」撞名時才算撞名——同檔期多份
    交接包共用同一個活動名稱是設計如此（build_names() 一檔期一活動名，多切角共用）。"""

    def setUp(self):
        self.bid = bi_repo.create_brand(
            main.conn, name="虛構晨露茶行", client_name="測試客戶", actor=ACTOR)["id"]

    def _cell(self, cycle_id: str, angle: str) -> str:
        """直接建一個切角＋一顆已採用主題（標題／文案），不經 LLM 生成管線（比照
        DailyBudgetInvariantTest._cell()，這裡不綁產品；票 02-repoint-creative-readers）。"""
        cell_id = new_id("exc")
        main.conn.execute(
            "INSERT INTO experiment_cell (id, org_id, campaign_cycle_id, brand_id, product_id,"
            " audience, creative_angle, created_at) VALUES (%s, %s, %s, %s, NULL, %s, %s, %s)",
            (cell_id, coredb.DEV_ORG_ID, cycle_id, self.bid, "測試受眾", angle, now_iso()),
        )
        main.conn.commit()
        theme = theme_repo.create_theme(
            main.conn, self.bid, campaign_cycle_id=cycle_id, experiment_cell_id=cell_id,
            format_key="single_image", name=f"{angle}主題", folder_code="D1V0", actor=ACTOR,
            components=[
                {"component_type": "title", "content": f"{angle}主打句"},
                {"component_type": "body", "content": f"{angle}內文"},
            ],
        )
        theme_repo.adopt_theme(main.conn, self.bid, theme["id"], actor=ACTOR)
        return cell_id

    def _cycle(self, start_date: str) -> dict:
        return ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[], pain_value=4000, objective="sales",
            actor=ACTOR, start_date=start_date, duration_days=10)

    def _built_packages(self, cycle_id: str) -> list:
        ads_handoff.build_packages(main.conn, self.bid, cycle_id, ACTOR)
        return ads_handoff.list_packages(main.conn, self.bid, cycle_id)

    def test_same_cycle_shared_campaign_name_passes(self):
        cycle = self._cycle("2026-08-01")
        for i in range(4):
            self._cell(cycle["id"], f"切角{i}")
        packages = self._built_packages(cycle["id"])
        self.assertEqual(len(packages), 4)
        self.assertEqual(len({p["campaign_name"] for p in packages}), 1)  # 同檔期共用一個活動名

        result = ads_handoff.naming_check(main.conn, self.bid, cycle["id"], packages)
        self.assertEqual(result, {"duplicates": [], "missing": [], "passed": True})

    def test_cross_cycle_campaign_name_collision_fails(self):
        """短碼撞名機率極低，直接改資料庫模擬「萬一撞到」的情境。"""
        cycle_a = self._cycle("2026-08-01")
        self._cell(cycle_a["id"], "切角A")
        packages_a = self._built_packages(cycle_a["id"])

        cycle_b = self._cycle("2026-09-01")
        self._cell(cycle_b["id"], "切角B")
        packages_b = self._built_packages(cycle_b["id"])

        collided_name = "撞名測試活動"
        main.conn.execute("UPDATE publishing_package SET campaign_name = %s WHERE id = %s",
                          (collided_name, packages_a[0]["id"]))
        main.conn.execute("UPDATE publishing_package SET campaign_name = %s WHERE id = %s",
                          (collided_name, packages_b[0]["id"]))
        main.conn.commit()

        packages_a = ads_handoff.list_packages(main.conn, self.bid, cycle_a["id"])
        result = ads_handoff.naming_check(main.conn, self.bid, cycle_a["id"], packages_a)
        self.assertFalse(result["passed"])
        self.assertEqual(len(result["duplicates"]), 1)
        dup = result["duplicates"][0]
        self.assertEqual(dup["field"], "campaign_name")
        self.assertEqual(dup["value"], collided_name)
        self.assertEqual(set(dup["package_ids"]), {packages_a[0]["id"], packages_b[0]["id"]})


if __name__ == "__main__":
    unittest.main()
