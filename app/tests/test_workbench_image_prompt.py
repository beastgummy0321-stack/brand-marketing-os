"""app/tests/test_workbench_image_prompt.py — ticket F01-T03-I02: the three image-prompt
renderers (`prompts.py`), their validation (`validate.py`) and the fix-round path addressing
(`jobs.py`). Only `ProductLineTest` touches the DB (seeded through `bi_repo`, the conftest
autouse fixtures give it a schema); every other test here is a pure-function assertion — the
renderers take every line as an argument, so no DB and no coordinate rows are needed.

This file is workbench code (ARCHITECTURE.md §2: `module_of()` matches by path glob, no test
special case), so it obeys `workbench.may_depend_on == []`: no `app.schedule` import in any
form, no reach into `test_workbench.py` internals.
"""

import unittest

import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.workbench import jobs as workbench_jobs
from app.workbench import prompts, validate

ACTOR = "測試員"

NO_PHOTO = "無參考商品照，畫面以情境與人物為主，不畫商品特寫。"


# -- 渲染：① 主圖提示詞（變體模式） -----------------------------------------------------

class RenderHeroPromptTest(unittest.TestCase):
    def test_line_order_and_dropped_lines(self):
        text = prompts.render_hero_prompt(
            {
                "scene": "廚房晨光", "person": "一位女性，居家便服",
                "subject_position": "置中，中景", "headline": "早晨也能好好吃",
                "subhead": None,
            },
            style_block="UGC 手機直式實拍", product_line="見參考商品照：晨光咖啡豆。不重述外觀。",
            audience_line="上班族；痛點：沒時間做早餐", appeal_line="切角：省時——早上時間寶貴",
            quotable_lines=["滿799免運"], output_line="4:5｜Meta 動態消息，一張",
        )
        lines = text.split("\n")
        self.assertEqual(lines[0], "【風格】UGC 手機直式實拍")
        self.assertEqual(lines[1], "【商品】見參考商品照：晨光咖啡豆。不重述外觀。")
        self.assertEqual(lines[2], "【受眾】上班族；痛點：沒時間做早餐")
        self.assertEqual(lines[3], "【這則的訴求】切角：省時——早上時間寶貴")
        self.assertEqual(lines[4], "【可用字句（逐字，不得改）】滿799免運")
        self.assertEqual(lines[5], "【畫面】廚房晨光／一位女性，居家便服／置中，中景")
        self.assertEqual(
            lines[6], "【圖上文字】大標：「早晨也能好好吃」；文字純色填滿，數字獨立成行",
        )
        self.assertEqual(lines[7], "【輸出】4:5｜Meta 動態消息，一張")
        self.assertNotIn("副標", lines[6])
        self.assertNotIn("禁止", text)

    def test_subhead_and_dropped_audience_appeal_quotable(self):
        text = prompts.render_hero_prompt(
            {
                "scene": "s", "person": "p", "subject_position": "sp",
                "headline": "大標", "subhead": "副標一句",
            },
            style_block="風格", product_line=NO_PHOTO, audience_line="", appeal_line="",
            quotable_lines=[], output_line="一張",
        )
        self.assertIn("大標：「大標」；副標：「副標一句」；文字純色填滿，數字獨立成行", text)
        self.assertNotIn("【受眾】", text)
        self.assertNotIn("【這則的訴求】", text)
        self.assertNotIn("【可用字句", text)
        self.assertNotIn("禁止", text)


# -- 渲染：② 變體提示詞（兩模式共用） ---------------------------------------------------

class RenderVariantPromptTest(unittest.TestCase):
    def test_full_shape(self):
        text = prompts.render_variant_prompt(
            count=3, appeal_sentence="省時", quotable_lines=["滿799免運"],
            output_line="4:5｜Meta 動態消息，一張", style_block="UGC 手機直式實拍",
        )
        self.assertEqual(text.split("\n"), [
            "以附上的這張圖為基底，分別生成 3 個完全不同風格排版與人物的圖片，"
            "主要訴求保持不變。一次一張。",
            "不變：訴求「省時」、可用字句「滿799免運」（數字逐字）、商品外型與 Logo、"
            "4:5｜Meta 動態消息，一張。",
            "可變：場景、人物、構圖、文字排版位置、配色。",
            "【風格】UGC 手機直式實拍",
        ])
        self.assertNotIn("禁止", text)

    def test_no_quotable_and_no_output_line(self):
        text = prompts.render_variant_prompt(
            count=2, appeal_sentence="以這張圖原本的主訴求為準", quotable_lines=[],
            output_line="", style_block="探索風格",
        )
        self.assertIn("不變：訴求「以這張圖原本的主訴求為準」、商品外型與 Logo。", text)
        self.assertNotIn("可用字句", text)


# -- 渲染：③ 探索提示詞（探索模式） -----------------------------------------------------

class RenderExplorationPromptTest(unittest.TestCase):
    def test_line_order_and_numbered_angles(self):
        angles = [
            {"name": "省時", "brief": "廚房場景", "on_image_line": "早晨也能好好吃"},
            {"name": "健康", "brief": "戶外場景", "on_image_line": "喝一杯，元氣一整天"},
        ]
        text = prompts.render_exploration_prompt(
            angles, style_block="風格區塊", product_line=NO_PHOTO, purpose_line="未指定",
            quotable_lines=["滿799免運"], count=2,
        )
        lines = text.split("\n")
        self.assertEqual(lines[0], "【風格】風格區塊")
        self.assertEqual(lines[1], f"【商品】{NO_PHOTO}")
        self.assertEqual(lines[2], "【目的與對象】未指定")
        self.assertEqual(lines[3], "【可用字句（逐字，不得改）】滿799免運")
        self.assertEqual(
            lines[4], "【任務】分別給我 2 張圖，每張一個不同的說服切角，排版與風格彼此差異要大：",
        )
        self.assertEqual(lines[5], "1. 省時｜廚房場景｜圖上文字：「早晨也能好好吃」")
        self.assertEqual(lines[6], "2. 健康｜戶外場景｜圖上文字：「喝一杯，元氣一整天」")
        self.assertEqual(
            lines[7], "【圖上文字】每張圖只出現它自己那一行字；文字純色填滿，數字獨立成行",
        )
        self.assertNotIn("【輸出】", text)
        self.assertNotIn("禁止", text)

    def test_no_quotable_line_dropped(self):
        text = prompts.render_exploration_prompt(
            [{"name": "n", "brief": "b", "on_image_line": "o"}],
            style_block="風格", product_line=NO_PHOTO, purpose_line="未指定",
            quotable_lines=[], count=1,
        )
        self.assertNotIn("【可用字句", text)


# -- image_prompt_prompt：模式行／可用字句行／可用的大標行 ------------------------------

class ImagePromptPromptWorksheetTest(unittest.TestCase):
    def test_exploration_worksheet_with_no_note_and_no_hint(self):
        text = prompts.image_prompt_prompt(
            "部門任務", "方法論", "## 這張工單\n產品：（無）", "品牌上下文",
            mode="exploration", count=3, quotable_lines=[], headline_hint=None,
        )
        self.assertIn("模式：探索模式；角度數：3", text)
        self.assertNotIn("可用字句", text)
        self.assertNotIn("可用的大標", text)

    def test_variant_worksheet_with_note_and_hint(self):
        text = prompts.image_prompt_prompt(
            "部門任務", "方法論", "## 這張工單\n產品：（無）", "品牌上下文",
            mode="variant", count=1, quotable_lines=["滿799免運"], headline_hint="早晨也能好好吃",
        )
        self.assertIn("模式：變體模式", text)
        self.assertIn("可用字句（逐字，不得改）：滿799免運", text)
        self.assertIn("可用的大標（可用可不用）：「早晨也能好好吃」", text)


# -- 驗證：check_image_prompt 數字規則（綠／紅） -----------------------------------------

class NumberRuleTest(unittest.TestCase):
    def _hero_data(self, headline: str) -> dict:
        return {
            "hero": {
                "scene": "s", "person": "p", "subject_position": "sp",
                "headline": headline, "subhead": None,
            },
        }

    def test_number_in_quotable_text_passes(self):
        results = validate.check_image_prompt(
            self._hero_data("滿799免運，即刻選購"), mode="variant", count=1,
            quotable_text="滿799免運",
        )
        item = next(r for r in results if r["path"] == "hero.headline")
        self.assertTrue(item["ok"], item)

    def test_number_not_in_quotable_text_fails_with_exact_message(self):
        results = validate.check_image_prompt(
            self._hero_data("滿899免運，即刻選購"), mode="variant", count=1,
            quotable_text="滿799免運",
        )
        item = next(r for r in results if r["path"] == "hero.headline")
        self.assertFalse(item["ok"])
        self.assertEqual(item["message"], "數字「899」未出現在可用字句或品牌資料")


class CheckImagePromptShapeTest(unittest.TestCase):
    def test_variant_mode_all_green(self):
        results = validate.check_image_prompt(
            {"hero": {
                "scene": "s", "person": "p", "subject_position": "sp",
                "headline": "早晨也能好好吃", "subhead": None,
            }},
            mode="variant", count=1, quotable_text="",
        )
        self.assertTrue(all(r["ok"] for r in results), results)

    def test_exploration_mode_wrong_count(self):
        results = validate.check_image_prompt(
            {"angles": [{"name": "n", "brief": "b", "on_image_line": "o"}]},
            mode="exploration", count=2, quotable_text="",
        )
        self.assertEqual(results, [{"path": "angles", "ok": False, "message": "要 2 個，實際 1"}])


# -- 修正輪：angles[2].on_image_line 這種索引後接子鍵的 path 真的被套用 -------------------

class FixRoundAnglePathTest(unittest.TestCase):
    def test_angles_index_subkey_replacement_applied(self):
        data = {
            "angles": [
                {"name": "省時", "brief": "b1", "on_image_line": "壞掉的字"},
                {"name": "健康", "brief": "b2", "on_image_line": "another bad"},
                {"name": "划算", "brief": "b3", "on_image_line": "壞掉的字三"},
            ],
        }
        workbench_jobs._apply_replacements(
            data, [{"path": "angles[2].on_image_line", "value": "喝一杯，元氣一整天"}]
        )
        self.assertEqual(data["angles"][1]["on_image_line"], "喝一杯，元氣一整天")
        # 沒被點名的項目原封不動。
        self.assertEqual(data["angles"][0]["on_image_line"], "壞掉的字")
        self.assertEqual(data["angles"][2]["on_image_line"], "壞掉的字三")

    def test_original_value_reads_index_subkey_path(self):
        data = {"angles": [{"on_image_line": "第一則"}, {"on_image_line": "第二則"}]}
        self.assertEqual(
            workbench_jobs._original_value(data, "angles[2].on_image_line"), "第二則"
        )


# -- ProductLineTest：唯一碰 DB 的測試，走 bi_repo 種子 ---------------------------------

class ProductLineTest(unittest.TestCase):
    def setUp(self):
        self.brand = bi_repo.create_brand(
            web.conn, org_id=coredb.DEV_ORG_ID, name="測試品牌：商品照", client_name=None,
            actor=ACTOR,
        )
        self.product = bi_repo.create_product(
            web.conn, self.brand["id"], name="測試產品：晨光咖啡豆", actor=ACTOR,
        )

    def test_product_line_with_matching_product_photo(self):
        bi_repo.create_official_asset(
            web.conn, self.brand["id"], actor=ACTOR, asset_kind="product_photo",
            storage_key="test/asset.jpg", product_id=self.product["id"],
        )
        line = workbench_jobs._product_line(
            web.conn, self.brand["id"], self.product["id"], self.product
        )
        self.assertEqual(line, "見參考商品照：測試產品：晨光咖啡豆。不重述外觀。")

    def test_product_line_without_matching_product_photo(self):
        # (a) 完全沒有素材列。
        self.assertEqual(
            workbench_jobs._product_line(
                web.conn, self.brand["id"], self.product["id"], self.product
            ),
            NO_PHOTO,
        )

        # (b) logo（同一個產品）＋ 品牌層級的 product_photo（product_id=None）。
        bi_repo.create_official_asset(
            web.conn, self.brand["id"], actor=ACTOR, asset_kind="logo",
            storage_key="test/logo.jpg", product_id=self.product["id"],
        )
        bi_repo.create_official_asset(
            web.conn, self.brand["id"], actor=ACTOR, asset_kind="product_photo",
            storage_key="test/brand-level.jpg", product_id=None,
        )
        self.assertEqual(
            workbench_jobs._product_line(
                web.conn, self.brand["id"], self.product["id"], self.product
            ),
            NO_PHOTO,
        )

        # (c) 另一個產品的 product_photo，不算數。
        other_product = bi_repo.create_product(
            web.conn, self.brand["id"], name="測試產品：另一款", actor=ACTOR,
        )
        bi_repo.create_official_asset(
            web.conn, self.brand["id"], actor=ACTOR, asset_kind="product_photo",
            storage_key="test/other.jpg", product_id=other_product["id"],
        )
        self.assertEqual(
            workbench_jobs._product_line(
                web.conn, self.brand["id"], self.product["id"], self.product
            ),
            NO_PHOTO,
        )

        # (d) 這個產品有 product_photo，但呼叫時沒帶 product_id/product（工單沒有商品）。
        bi_repo.create_official_asset(
            web.conn, self.brand["id"], actor=ACTOR, asset_kind="product_photo",
            storage_key="test/has-photo.jpg", product_id=self.product["id"],
        )
        self.assertEqual(
            workbench_jobs._product_line(web.conn, self.brand["id"], None, None),
            NO_PHOTO,
        )
