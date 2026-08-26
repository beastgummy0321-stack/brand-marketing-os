# -*- coding: utf-8 -*-
"""app/tests/test_carousel_theme.py — 輪播主題端到端（票 07-carousel-theme）。

接縫一（引擎門口，app/ads/theme_engine.py generate_carousel_theme）：假簡報進 → 驗
骨架標記＋有序卡片＋5 則廣告層文案，數量與字數對規格表；接縫二（路由層）：走 HTTP 驗
JSON 回應與存檔路徑跟單圖共用。全程 FakeProvider，不發任何真實網路請求。品牌與產品名
一律虛構。setUp／_ready_cell 等寫法照抄 app/tests/test_theme_engine.py（票 04），
不共用 import——本專案測試檔一律自帶獨立 tmp DB。
"""

import atexit
import inspect
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import pytest

_tmpdir = tempfile.mkdtemp(prefix="brand_os_carousel_theme_")

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


ROOT = Path(_tmpdir) / "creative"


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"

# BUG app/core/settings.py:143 — brand_llm_spent() 回傳 Decimal，budget_exceeded_message()
# 的 spent + cost 一律 TypeError（同一個 BUG，其他群組已標過）。
_BUG_DECIMAL_PLUS_FLOAT = pytest.mark.xfail(
    strict=True,
    reason='BUG app/core/settings.py:143 — brand_llm_spent() 回傳 Decimal，'
           "budget_exceeded_message() 的 spent + cost 一律 TypeError",
)
# 同一個 BUG，但這個測試對同一個品牌連呼兩次 generate_carousel_theme()（count=2 再
# count=10）：第一次呼叫時 llm_task 還沒有任何列，SUM(cost) 回傳 NULL、brand_llm_spent()
# 走 `or 0.0` 分支（float），不中這個 BUG；第二次呼叫時第一次的花費已經入帳，
# SUM(cost) 有值變成 Decimal，才中。strict=True 在這裡不適用——不是「這個測試一律失敗」，
# 是「同一個 BUG 在同一個測試裡视呼叫順序決定中不中」，用 strict=False 誠實描述這件事。
_BUG_DECIMAL_PLUS_FLOAT_ORDER_DEPENDENT = pytest.mark.xfail(
    strict=False,
    reason='BUG app/core/settings.py:143 — brand_llm_spent() 回傳 Decimal，'
           "budget_exceeded_message() 的 spent + cost 一律 TypeError；這個測試連呼兩次，"
           "只有第二次（此時已有花費入帳）會中，第一次（花費是 0.0）不會中",
)
_FIELDS = FORMAT_SPECS["carousel"]["fields"]
_AXES_VALUES = {"angle": "benefit", "tone": "warm", "format": "carousel",
                "selling_point": "quality"}


def _fake(text: str) -> ProviderResponse:
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=400, output_tokens=250),
                            stop_reason="end_turn")


def _card(i: int, *, extra: dict = None) -> dict:
    card = {"image_prompt": f"第 {i} 卡：暖金色茶席場景特寫", "title": f"卡標題{i}",
           "description": f"卡說明{i}：把卡標題講的事再說一次"}
    if extra:
        card.update(extra)
    return card


def _carousel_reply(*, narrative_type: str, card_count: int, name: str = "虛構主題：開盒四步驟",
                    extra_top: dict = None, card_extra: dict = None) -> str:
    text_item = lambda label, i: {"content": f"{label}{i}", "fingerprint": _AXES_VALUES}
    payload = {
        "name": name,
        "narrative_type": narrative_type,
        "cards": [_card(i, extra=card_extra) for i in range(card_count)],
        "body": [text_item("文案", i) for i in range(5)],
    }
    if extra_top:
        payload.update(extra_top)
    return json.dumps(payload, ensure_ascii=False)


class _Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        coresettings.set_setting(main.conn, creative_assets.SETTING_KEY, str(ROOT))
        coresettings.set_setting(main.conn, "intake_budget_limit", "1000")
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡（輪播票）",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]
        self.product_id = bi_repo.create_product(main.conn, self.bid, name="虛構濾掛組",
                                                  actor=ACTOR)["id"]
        self._orig_provider = theme_engine.PROVIDER

    def tearDown(self):
        theme_engine.PROVIDER = self._orig_provider
        coresettings.set_setting(main.conn, "intake_budget_limit", "30")

    def _ready_cell(self, *, objective: str = "sales") -> tuple:
        cycle = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[self.product_id],
            pain_value=5, objective=objective, actor=ACTOR,
        )
        cycle_id = cycle["id"]
        cell_id = db.new_id("exc")
        main.conn.execute(
            "INSERT INTO experiment_cell (id, org_id, campaign_cycle_id, brand_id, product_id,"
            " creative_angle, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (cell_id, db.DEV_ORG_ID, cycle_id, self.bid, self.product_id, "價格敏感：第一杯 39 元",
             db.now_iso()),
        )
        main.conn.execute(
            "INSERT INTO campaign_plan (id, org_id, campaign_cycle_id, brand_id, plan_version,"
            " plan_json, status, approved_by, approved_at, created_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, 'approved', %s, %s, %s)",
            (db.new_id("cpl"), db.DEV_ORG_ID, cycle_id, self.bid, 1,
             db.jsonb({"summary": "測試打法：主打省錢誘因"}),
             ACTOR, db.now_iso(), db.now_iso()),
        )
        main.conn.commit()
        return cycle_id, cell_id

    def _assemble(self, cycle_id: str, cell_id: str):
        brief, err = brief_assembler.assemble_brief(
            main.conn, self.bid, cycle_id, cell_id, "carousel", theme_count=1, actor=ACTOR)
        self.assertIsNone(err, err)
        return brief

    def _swap(self, reply: str) -> FakeProvider:
        provider = FakeProvider(response=_fake(reply))
        theme_engine.PROVIDER = provider
        return provider


class ShapeMatchesSpecTest(_Base):
    """票 07 驗收 1：假簡報進 → 骨架標記＋2–10 張有序卡片＋5 文案，數量與字數對規格表。"""

    def test_steps_narrative_produces_marker_ordered_cards_and_five_body(self):
        cycle_id, cell_id = self._ready_cell()
        brief = self._assemble(cycle_id, cell_id)
        self._swap(_carousel_reply(narrative_type="steps", card_count=4))

        generated, err = theme_engine.generate_carousel_theme(main.conn, brief, actor=ACTOR)
        self.assertIsNone(err, err)
        components = generated["components"]

        markers = [c for c in components if c["component_type"] == "narrative_type"]
        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0]["content"], "steps")

        for field in ("card_image_prompt", "card_title", "card_description"):
            self.assertEqual(
                len([c for c in components if c["component_type"] == field]), 4)
        body = [c for c in components if c["component_type"] == "body"]
        self.assertEqual(len(body), _FIELDS["body"]["count"])

    @_BUG_DECIMAL_PLUS_FLOAT_ORDER_DEPENDENT
    def test_card_count_within_two_to_ten(self):
        cycle_id, cell_id = self._ready_cell()
        for count in (2, 10):
            with self.subTest(count=count):
                brief = self._assemble(cycle_id, cell_id)
                self._swap(_carousel_reply(narrative_type="steps", card_count=count))
                generated, err = theme_engine.generate_carousel_theme(
                    main.conn, brief, actor=ACTOR)
                self.assertIsNone(err, err)
                titles = [c for c in generated["components"]
                         if c["component_type"] == "card_title"]
                self.assertEqual(len(titles), count)

    def test_before_after_must_be_exactly_two_cards(self):
        cycle_id, cell_id = self._ready_cell()
        brief = self._assemble(cycle_id, cell_id)
        self._swap(_carousel_reply(narrative_type="before_after", card_count=4))  # 骨架違規

        generated, err = theme_engine.generate_carousel_theme(main.conn, brief, actor=ACTOR)
        self.assertIsNone(generated)
        self.assertEqual(err, theme_engine.PARSE_FAIL_MESSAGE)

    def test_prompt_forbids_cta_and_link(self):
        cycle_id, cell_id = self._ready_cell()
        brief = self._assemble(cycle_id, cell_id)
        provider = self._swap(_carousel_reply(narrative_type="steps", card_count=3))
        theme_engine.generate_carousel_theme(main.conn, brief, actor=ACTOR)
        prompt_text = provider.calls[0]["messages"][0]["content"]
        self.assertIn("不要生成任何 CTA", prompt_text)
        self.assertIn("商品連結也不是你的工作", prompt_text)

    def test_no_narrative_type_parameter_anywhere_on_the_generation_path(self):
        """票 07 驗收 3：骨架由引擎選，簡報與路由都沒有骨架參數。"""
        assemble_params = inspect.signature(brief_assembler.assemble_brief).parameters
        self.assertNotIn("narrative_type", assemble_params)
        generate_params = inspect.signature(theme_engine.generate_carousel_theme).parameters
        self.assertNotIn("narrative_type", generate_params)
        self.assertNotIn("narrative_type", brief_assembler.CreativeBrief._fields)


class CardSequencePersistenceTest(_Base):
    """票 07 驗收 2：卡片序號落庫、讀回順序不變。"""

    def test_saved_cards_read_back_in_original_order(self):
        cycle_id, cell_id = self._ready_cell()
        brief = self._assemble(cycle_id, cell_id)
        self._swap(_carousel_reply(narrative_type="steps", card_count=5))

        generated, err = theme_engine.generate_carousel_theme(main.conn, brief, actor=ACTOR)
        self.assertIsNone(err, err)
        theme = theme_engine.save_generated_theme(main.conn, brief, generated, actor=ACTOR)

        fetched = theme_repo.get_theme(main.conn, self.bid, theme["id"])
        titles = [c for c in fetched["components"] if c["component_type"] == "card_title"]
        self.assertEqual([t["sequence"] for t in titles], [1, 2, 3, 4, 5])
        self.assertEqual([t["content"] for t in titles],
                         [f"卡標題{i}" for i in range(5)])

        descriptions = [c for c in fetched["components"]
                        if c["component_type"] == "card_description"]
        self.assertEqual([d["sequence"] for d in descriptions], [1, 2, 3, 4, 5])

    def test_route_json_preserves_card_order(self):
        cycle_id, cell_id = self._ready_cell()
        self._swap(_carousel_reply(narrative_type="steps", card_count=3))

        resp = self.client.post(
            f"/api/ads/brands/{self.bid}/ads/{cycle_id}/cells/{cell_id}"
            f"/formats/carousel/themes")
        self.assertEqual(resp.status_code, 200)
        components = resp.json()["theme"]["components"]
        titles = [c for c in components if c["component_type"] == "card_title"]
        self.assertEqual([t["content"] for t in titles], ["卡標題0", "卡標題1", "卡標題2"])
        self.assertEqual([t["sequence"] for t in titles], [1, 2, 3])


class MultiProductLinkNotGeneratedTest(_Base):
    """票 07 驗收 4：多商品型每卡連結不生成，欄位在 JSON 裡預留佔位。"""

    def test_multi_product_reserves_placeholder_link_component_per_card(self):
        cycle_id, cell_id = self._ready_cell()
        brief = self._assemble(cycle_id, cell_id)
        # 模型夾帶一個連結欄位，驗證它完全不會流進存檔內容。
        self._swap(_carousel_reply(
            narrative_type="multi_product", card_count=3,
            card_extra={"link": "https://example.com/smuggled-product"}))

        generated, err = theme_engine.generate_carousel_theme(main.conn, brief, actor=ACTOR)
        self.assertIsNone(err, err)
        links = [c for c in generated["components"] if c["component_type"] == "card_product_link"]
        self.assertEqual(len(links), 3)
        self.assertEqual([l["sequence"] for l in links], [1, 2, 3])
        for link in links:
            self.assertEqual(link["content"], theme_engine.CARD_PRODUCT_LINK_PLACEHOLDER)

        contents = [c["content"] for c in generated["components"]]
        self.assertFalse(any("example.com" in text for text in contents))

    def test_non_multi_product_has_no_link_component(self):
        cycle_id, cell_id = self._ready_cell()
        brief = self._assemble(cycle_id, cell_id)
        self._swap(_carousel_reply(narrative_type="steps", card_count=4))

        generated, err = theme_engine.generate_carousel_theme(main.conn, brief, actor=ACTOR)
        self.assertIsNone(err, err)
        links = [c for c in generated["components"] if c["component_type"] == "card_product_link"]
        self.assertEqual(links, [])


class CharGuardAndSimilarityReuseTest(_Base):
    """票 07 驗收 1（字數對規格表）＋沿用既有兩道守門，不得另寫。"""

    def test_over_budget_card_title_gets_flagged_after_shared_char_guard(self):
        cycle_id, cell_id = self._ready_cell()
        brief = self._assemble(cycle_id, cell_id)
        long_title = "超長卡標題" * 20  # 遠超 45 字預算
        provider = self._swap(_carousel_reply(
            narrative_type="steps", card_count=2,
            card_extra={"title": long_title}))
        # 重寫呼叫會再打一次 provider；FakeProvider 固定回同一個 reply，重寫格式讀不到
        # rewrites 陣列 → fallback 保留原文、標 over_budget（跟票 05 的失敗保底路徑一致）。

        generated, err = theme_engine.generate_carousel_theme(main.conn, brief, actor=ACTOR)
        self.assertIsNone(err, err)
        titles = [c for c in generated["components"] if c["component_type"] == "card_title"]
        self.assertTrue(all(t["content"] == long_title for t in titles))
        self.assertTrue(all(t.get("over_budget") for t in titles))
        self.assertGreaterEqual(len(provider.calls), 2)  # 主生成＋至少一次重寫呼叫

    def test_similarity_flag_applies_to_body_and_not_to_cards(self):
        cycle_id, cell_id = self._ready_cell()
        brief = self._assemble(cycle_id, cell_id)
        text_item = lambda i: {"content": f"文案{i}", "fingerprint": _AXES_VALUES}
        self._swap(_carousel_reply(
            narrative_type="steps", card_count=2,
            extra_top={"body": [text_item(i) for i in range(5)]}))  # 全部同指紋 → 一定標黃

        generated, err = theme_engine.generate_carousel_theme(main.conn, brief, actor=ACTOR)
        self.assertIsNone(err, err)
        body = [c for c in generated["components"] if c["component_type"] == "body"]
        self.assertTrue(any(c.get("similarity_flag") for c in body))
        cards = [c for c in generated["components"]
                if c["component_type"] in ("card_title", "card_description")]
        self.assertFalse(any(c.get("similarity_flag") for c in cards))


class InvalidNarrativeTypeRejectedTest(_Base):
    def test_unknown_narrative_type_key_fails_parse(self):
        cycle_id, cell_id = self._ready_cell()
        brief = self._assemble(cycle_id, cell_id)
        self._swap(_carousel_reply(narrative_type="不存在的骨架", card_count=3))

        generated, err = theme_engine.generate_carousel_theme(main.conn, brief, actor=ACTOR)
        self.assertIsNone(generated)
        self.assertEqual(err, theme_engine.PARSE_FAIL_MESSAGE)

    def test_wrong_format_key_on_brief_raises(self):
        cycle_id, cell_id = self._ready_cell()
        brief, err = brief_assembler.assemble_brief(
            main.conn, self.bid, cycle_id, cell_id, "single_image", theme_count=1, actor=ACTOR)
        self.assertIsNone(err, err)
        with self.assertRaises(ValueError):
            theme_engine.generate_carousel_theme(main.conn, brief, actor=ACTOR)


class RouteGenerateCarouselThemeTest(_Base):
    """接縫二（路由層）：走 04 的同一條路徑，只換 format_key。"""

    def test_post_returns_json_theme_with_carousel_shape(self):
        cycle_id, cell_id = self._ready_cell()
        self._swap(_carousel_reply(narrative_type="multi_product", card_count=3,
                                   name="虛構主題：三款任選"))

        resp = self.client.post(
            f"/api/ads/brands/{self.bid}/ads/{cycle_id}/cells/{cell_id}"
            f"/formats/carousel/themes")
        self.assertEqual(resp.status_code, 200)
        theme = resp.json()["theme"]
        self.assertEqual(theme["name"], "虛構主題：三款任選")
        self.assertEqual(theme["format_key"], "carousel")
        self.assertEqual(theme["status"], "draft")
        # 1 骨架標記 ＋ 3 卡 ×（圖＋標題＋說明＋商品連結）＋ 5 文案 ＝ 1 + 12 + 5 = 18
        self.assertEqual(len(theme["components"]), 18)
        self.assertTrue(Path(theme["folder_path"]).is_dir())

    def test_unsupported_format_key_returns_400_without_calling_provider(self):
        cycle_id, cell_id = self._ready_cell()
        provider = self._swap(_carousel_reply(narrative_type="steps", card_count=3))

        # "video" 從票 08 起也是支援格式了（見 app/tests/test_video_theme.py），這裡改用
        # 一個規格表真的沒有的格式 key 當「不支援」的例子——蝦皮插槽照 spec Out of Scope
        # 明文還沒查證落地，是個站得住腳、不會意外變成「支援」的反例。
        resp = self.client.post(
            f"/api/ads/brands/{self.bid}/ads/{cycle_id}/cells/{cell_id}"
            f"/formats/shopee/themes")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(provider.calls, [])


if __name__ == "__main__":
    unittest.main()
