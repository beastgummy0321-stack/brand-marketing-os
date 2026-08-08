# -*- coding: utf-8 -*-
"""app/tests/test_theme_engine.py — 單圖主題端到端（票 04-single-image-e2e）。

接縫一（引擎門口，app/ads/theme_engine.py）：假簡報進 → 驗產出形狀，全程 FakeProvider，
不發任何真實網路請求。接縫二（路由層，app/ads/routes_creative_theme.py）：走 HTTP 驗
JSON 回應、費用攔截、開資料夾（os.startfile 一律 patch 掉，不讓 pytest 開檔案總管）。
品牌與產品名一律虛構。
"""

import atexit
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_tmpdir = tempfile.mkdtemp(prefix="brand_os_theme_engine_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import brief_assembler  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.ads import theme_engine  # noqa: E402
from app.ads import theme_repository as theme_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import creative_assets  # noqa: E402
from app.core import db  # noqa: E402
from app.core import settings as coresettings  # noqa: E402
from app.creative.format_specs import FORMAT_SPECS  # noqa: E402
from app.llm.providers import FakeProvider, ProviderResponse, Usage  # noqa: E402

main.reopen_connection()

ROOT = Path(_tmpdir) / "creative"


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"
_FIELDS = FORMAT_SPECS["single_image"]["fields"]
_AXES_VALUES = {"angle": "benefit", "tone": "warm", "format": "single_image",
                "selling_point": "quality"}


def _fake(text: str) -> ProviderResponse:
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=400, output_tokens=250),
                            stop_reason="end_turn")


def _theme_reply(*, image_count: int, text_count: int, name: str = "虛構主題：晨光第一杯",
                 extra_fields: dict = None) -> str:
    text_item = lambda label, i: {"content": f"{label}{i}", "fingerprint": _AXES_VALUES}
    payload = {
        "name": name,
        "image_prompt": [f"暖金色茶席場景，特寫第 {i} 張" for i in range(image_count)],
        "body": [text_item("文案", i) for i in range(text_count)],
        "title": [text_item("標題", i) for i in range(text_count)],
        "description": [text_item("說明", i) for i in range(text_count)],
    }
    if extra_fields:
        payload.update(extra_fields)
    return json.dumps(payload, ensure_ascii=False)


class _Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        coresettings.set_setting(main.conn, creative_assets.SETTING_KEY, str(ROOT))
        coresettings.set_setting(main.conn, "intake_budget_limit", "1000")
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡（主題引擎票）",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]
        self.product_id = bi_repo.create_product(main.conn, self.bid, name="虛構濾掛組",
                                                  actor=ACTOR)["id"]
        self._orig_provider = theme_engine.PROVIDER

    def tearDown(self):
        theme_engine.PROVIDER = self._orig_provider
        coresettings.set_setting(main.conn, "intake_budget_limit", "30")

    def _open_cycle(self, *, objective: str = "sales") -> str:
        cycle = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[self.product_id],
            pain_value=5, objective=objective, actor=ACTOR,
        )
        return cycle["id"]

    def _insert_cell(self, cycle_id: str) -> str:
        cell_id = db.new_id("exc")
        main.conn.execute(
            "INSERT INTO experiment_cell (id, campaign_cycle_id, brand_id, product_id,"
            " creative_angle, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (cell_id, cycle_id, self.bid, self.product_id, "價格敏感：第一杯 39 元",
             db.now_iso()),
        )
        main.conn.commit()
        return cell_id

    def _approve_plan(self, cycle_id: str) -> None:
        main.conn.execute(
            "INSERT INTO campaign_plan (id, campaign_cycle_id, brand_id, plan_version,"
            " plan_json, status, approved_by, approved_at, created_at)"
            " VALUES (?, ?, ?, ?, ?, 'approved', ?, ?, ?)",
            (db.new_id("cpl"), cycle_id, self.bid, 1,
             json.dumps({"summary": "測試打法：主打省錢誘因"}, ensure_ascii=False),
             ACTOR, db.now_iso(), db.now_iso()),
        )
        main.conn.commit()

    def _ready_cell(self, *, objective: str = "sales") -> tuple:
        """開檔期＋切角格＋核准計畫的最短路徑，回傳 (cycle_id, cell_id)。"""
        cycle_id = self._open_cycle(objective=objective)
        cell_id = self._insert_cell(cycle_id)
        self._approve_plan(cycle_id)
        return cycle_id, cell_id

    def _assemble(self, cycle_id: str, cell_id: str, *, format_key: str = "single_image"):
        brief, err = brief_assembler.assemble_brief(
            main.conn, self.bid, cycle_id, cell_id, format_key, theme_count=1, actor=ACTOR)
        self.assertIsNone(err, err)
        return brief

    def _swap(self, reply: str) -> FakeProvider:
        provider = FakeProvider(response=_fake(reply))
        theme_engine.PROVIDER = provider
        return provider


class ComponentCountsMatchSpecTest(_Base):
    """票 04 驗收 1：假簡報進 → 產出數量對規格表（10/5/5/5）、CTA 與連結不出現。"""

    def test_sales_objective_full_shape_10_5_5_5(self):
        cycle_id, cell_id = self._ready_cell(objective="sales")
        brief = self._assemble(cycle_id, cell_id)
        self._swap(_theme_reply(image_count=10, text_count=5))

        generated, err = theme_engine.generate_single_image_theme(main.conn, brief, actor=ACTOR)
        self.assertIsNone(err, err)

        counts = {}
        for c in generated["components"]:
            counts[c["component_type"]] = counts.get(c["component_type"], 0) + 1
        self.assertEqual(counts, {
            "image_prompt": _FIELDS["image_prompt"]["count"],
            "body": _FIELDS["body"]["count"],
            "title": _FIELDS["title"]["count"],
            "description": _FIELDS["description"]["count"],
        })
        self.assertEqual(sum(counts.values()), 25)

    def test_cta_and_link_fields_are_ignored_even_if_model_smuggles_them_in(self):
        cycle_id, cell_id = self._ready_cell(objective="sales")
        brief = self._assemble(cycle_id, cell_id)
        self._swap(_theme_reply(
            image_count=10, text_count=5,
            extra_fields={"cta": "立即購買", "link": "https://example.com"}))

        generated, err = theme_engine.generate_single_image_theme(main.conn, brief, actor=ACTOR)
        self.assertIsNone(err, err)
        component_types = {c["component_type"] for c in generated["components"]}
        self.assertNotIn("cta", component_types)
        self.assertNotIn("link", component_types)
        contents = [c["content"] for c in generated["components"]]
        self.assertFalse(any("example.com" in text for text in contents))

    def test_prompt_forbids_cta_and_link(self):
        cycle_id, cell_id = self._ready_cell(objective="sales")
        brief = self._assemble(cycle_id, cell_id)
        provider = self._swap(_theme_reply(image_count=10, text_count=5))
        theme_engine.generate_single_image_theme(main.conn, brief, actor=ACTOR)
        prompt_text = provider.calls[0]["messages"][0]["content"]
        self.assertIn("不要生成任何 CTA", prompt_text)
        self.assertIn("連結", prompt_text)


class NonSalesObjectiveCollapseTest(_Base):
    """票 04 驗收 2：非 sales 目標媒體塌成 1、文字仍 5；同一段程式碼跑五種目標，
    沒有 if objective == "sales" 分支——用資料驅動的規格表比對，不是特判某一個目標。"""

    def test_media_cap_follows_format_specs_for_every_objective(self):
        for objective, objective_spec in FORMAT_SPECS["single_image"]["objectives"].items():
            with self.subTest(objective=objective):
                plan = theme_engine._single_image_fields_plan(objective)
                self.assertEqual(plan["image_prompt"]["count"],
                                 objective_spec["media_cap_per_theme"])
                self.assertEqual(plan["body"]["count"], _FIELDS["body"]["count"])
                self.assertEqual(plan["title"]["count"], _FIELDS["title"]["count"])
                self.assertEqual(plan["description"]["count"], _FIELDS["description"]["count"])

    def test_awareness_objective_collapses_media_to_one_text_stays_five(self):
        cycle_id, cell_id = self._ready_cell(objective="awareness")
        brief = self._assemble(cycle_id, cell_id)
        self._swap(_theme_reply(image_count=1, text_count=5))

        generated, err = theme_engine.generate_single_image_theme(main.conn, brief, actor=ACTOR)
        self.assertIsNone(err, err)
        counts = {}
        for c in generated["components"]:
            counts[c["component_type"]] = counts.get(c["component_type"], 0) + 1
        self.assertEqual(counts["image_prompt"], 1)
        self.assertEqual(counts["body"], 5)
        self.assertEqual(counts["title"], 5)
        self.assertEqual(counts["description"], 5)


class PromptRulesTest(_Base):
    """票 04 驗收 3：三條 prompt 規則入 prompt 且各標適用層級。"""

    def test_three_rules_present_with_layer_labels(self):
        cycle_id, cell_id = self._ready_cell(objective="sales")
        brief = self._assemble(cycle_id, cell_id)
        provider = self._swap(_theme_reply(image_count=10, text_count=5))
        theme_engine.generate_single_image_theme(main.conn, brief, actor=ACTOR)

        prompt_text = provider.calls[0]["messages"][0]["content"]
        self.assertEqual(prompt_text.count("〔切角層〕"), 1)
        self.assertEqual(prompt_text.count("〔主題層〕"), 2)
        self.assertIn("要真的不一樣", prompt_text)
        self.assertIn("圖上文字一律相同", prompt_text)
        self.assertIn("只准在「說法」", prompt_text)


class ExistingThemeAntiDuplicateTest(_Base):
    """票 04 驗收 4：簡報裡的同格既有主題摘要有進 prompt（防撞衫指令）。"""

    def test_existing_theme_name_reaches_the_prompt(self):
        cycle_id, cell_id = self._ready_cell(objective="sales")
        theme_repo.create_theme(
            main.conn, self.bid, campaign_cycle_id=cycle_id, experiment_cell_id=cell_id,
            format_key="single_image", name="虛構主題：暖金茶席", folder_code="A1B2",
            actor=ACTOR,
            components=[{"component_type": "body", "content": "第一杯只要 39 元",
                        "fingerprint_json": {"angle": "benefit", "tone": "warm"}}],
        )
        brief = self._assemble(cycle_id, cell_id)
        self.assertEqual(len(brief.existing_themes_summary), 1)

        provider = self._swap(_theme_reply(image_count=10, text_count=5))
        theme_engine.generate_single_image_theme(main.conn, brief, actor=ACTOR)
        prompt_text = provider.calls[0]["messages"][0]["content"]
        self.assertIn("虛構主題：暖金茶席", prompt_text)
        self.assertIn("不要撞衫", prompt_text)

    def test_no_existing_theme_no_anti_duplicate_block(self):
        cycle_id, cell_id = self._ready_cell(objective="sales")
        brief = self._assemble(cycle_id, cell_id)
        provider = self._swap(_theme_reply(image_count=10, text_count=5))
        theme_engine.generate_single_image_theme(main.conn, brief, actor=ACTOR)
        prompt_text = provider.calls[0]["messages"][0]["content"]
        self.assertNotIn("不要撞衫", prompt_text)


class PersistAndFolderTest(_Base):
    """票 04 驗收 5、6：主題與 25 個元件落庫、指紋經 normalize 才寫入；主題資料夾建立。"""

    def test_theme_and_25_components_persisted_with_normalized_fingerprint(self):
        cycle_id, cell_id = self._ready_cell(objective="sales")
        brief = self._assemble(cycle_id, cell_id)
        self._swap(_theme_reply(
            image_count=10, text_count=5,
            extra_fields={"body": [
                {"content": f"文案{i}",
                 # 第一則故意夾帶一個不合法的 tone 值，驗證 normalize() 真的有跑
                 # （不是原封不動存進去）——這是「當場證明會紅」的那道檢查。
                 "fingerprint": {"angle": "benefit", "tone": "沒這個值" if i == 0 else "warm",
                                "format": "single_image", "selling_point": "quality"}}
                for i in range(5)
            ]}))

        generated, err = theme_engine.generate_single_image_theme(main.conn, brief, actor=ACTOR)
        self.assertIsNone(err, err)
        theme = theme_engine.save_generated_theme(main.conn, brief, generated, actor=ACTOR)

        fetched = theme_repo.get_theme(main.conn, self.bid, theme["id"])
        self.assertEqual(len(fetched["components"]), 25)

        first_body = next(c for c in fetched["components"]
                          if c["component_type"] == "body" and c["content"] == "文案0")
        self.assertNotIn("tone", first_body["fingerprint_json"])  # 非法值被 normalize 丟掉
        self.assertEqual(first_body["fingerprint_json"]["angle"], "benefit")  # 合法值留著

        image_component = next(c for c in fetched["components"]
                               if c["component_type"] == "image_prompt")
        self.assertIsNone(image_component["fingerprint_json"])

    def test_folder_created_with_name_and_short_code(self):
        cycle_id, cell_id = self._ready_cell(objective="sales")
        brief = self._assemble(cycle_id, cell_id)
        self._swap(_theme_reply(image_count=10, text_count=5, name="虛構主題：暖金茶席"))
        generated, err = theme_engine.generate_single_image_theme(main.conn, brief, actor=ACTOR)
        self.assertIsNone(err, err)
        theme = theme_engine.save_generated_theme(main.conn, brief, generated, actor=ACTOR)

        folder_path = Path(theme["folder_path"])
        self.assertTrue(folder_path.is_dir())
        self.assertEqual(folder_path, ROOT / self.bid / cycle_id
                         / f"虛構主題：暖金茶席_{theme['folder_code']}")
        self.assertEqual(len(theme["folder_code"]), 4)


class BudgetCapTest(_Base):
    """票 04 驗收 7（前半）：費用上限攔截沿用既有機制。"""

    def test_over_limit_blocks_before_calling_provider(self):
        coresettings.set_setting(main.conn, "intake_budget_limit", "0.0001")
        cycle_id, cell_id = self._ready_cell(objective="sales")
        brief = self._assemble(cycle_id, cell_id)
        provider = self._swap(_theme_reply(image_count=10, text_count=5))

        generated, err = theme_engine.generate_single_image_theme(main.conn, brief, actor=ACTOR)
        self.assertIsNone(generated)
        self.assertIn("花費上限", err)
        self.assertEqual(provider.calls, [])  # 真的沒送出呼叫，沒花到錢


class UnsupportedFormatTest(_Base):
    def test_non_single_image_format_key_raises(self):
        cycle_id, cell_id = self._ready_cell(objective="sales")
        brief, err = brief_assembler.assemble_brief(
            main.conn, self.bid, cycle_id, cell_id, "carousel", theme_count=1, actor=ACTOR)
        self.assertIsNone(err, err)
        with self.assertRaises(ValueError):
            theme_engine.generate_single_image_theme(main.conn, brief, actor=ACTOR)


class RouteGenerateThemeTest(_Base):
    """接縫二（路由層）：POST 這支端點打通整條 route → brief → engine → 存檔 → JSON。"""

    def test_post_returns_json_theme_sufficient_for_card_and_panel(self):
        cycle_id, cell_id = self._ready_cell(objective="sales")
        self._swap(_theme_reply(image_count=10, text_count=5, name="虛構主題：暖金茶席"))

        resp = self.client.post(
            f"/api/ads/brands/{self.bid}/ads/{cycle_id}/cells/{cell_id}"
            f"/formats/single_image/themes")
        self.assertEqual(resp.status_code, 200)
        theme = resp.json()["theme"]
        self.assertEqual(theme["name"], "虛構主題：暖金茶席")
        self.assertEqual(theme["format_key"], "single_image")
        self.assertEqual(theme["status"], "draft")
        self.assertEqual(len(theme["components"]), 25)
        self.assertTrue(Path(theme["folder_path"]).is_dir())

    def test_plan_not_approved_returns_409(self):
        cycle_id = self._open_cycle(objective="sales")
        cell_id = self._insert_cell(cycle_id)  # 沒呼叫 _approve_plan()

        resp = self.client.post(
            f"/api/ads/brands/{self.bid}/ads/{cycle_id}/cells/{cell_id}"
            f"/formats/single_image/themes")
        self.assertEqual(resp.status_code, 409)
        self.assertIn("計畫", resp.json()["error"])

    def test_unknown_cell_returns_400(self):
        cycle_id, _ = self._ready_cell(objective="sales")
        resp = self.client.post(
            f"/api/ads/brands/{self.bid}/ads/{cycle_id}/cells/exc_not_real"
            f"/formats/single_image/themes")
        self.assertEqual(resp.status_code, 400)

    def test_unknown_cycle_is_404(self):
        resp = self.client.post(
            f"/api/ads/brands/{self.bid}/ads/ccy_not_real/cells/exc_x"
            f"/formats/single_image/themes")
        self.assertEqual(resp.status_code, 404)


class RouteOpenFolderTest(_Base):
    """票 04 驗收 6（開資料夾入口）：沿用既有 os.startfile 先例。"""

    def test_open_folder_creates_and_launches_explorer(self):
        cycle_id, cell_id = self._ready_cell(objective="sales")
        brief = self._assemble(cycle_id, cell_id)
        self._swap(_theme_reply(image_count=10, text_count=5, name="虛構主題：暖金茶席"))
        generated, _ = theme_engine.generate_single_image_theme(main.conn, brief, actor=ACTOR)
        theme = theme_engine.save_generated_theme(main.conn, brief, generated, actor=ACTOR)
        expected_path = Path(theme["folder_path"])

        with mock.patch("os.startfile", create=True) as startfile:
            resp = self.client.post(
                f"/api/ads/brands/{self.bid}/ads/{cycle_id}/themes/{theme['id']}/folder")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["folder_path"], str(expected_path))
        startfile.assert_called_once_with(expected_path)

    def test_unknown_theme_is_404(self):
        cycle_id, _ = self._ready_cell(objective="sales")
        with mock.patch("os.startfile", create=True):
            resp = self.client.post(
                f"/api/ads/brands/{self.bid}/ads/{cycle_id}/themes/cth_not_real/folder")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
