# -*- coding: utf-8 -*-
"""app/tests/test_ads_theme_copy.py — 整組複製與逐則複製內容路由（票 11-copy-flows）。

接縫二（路由層，app/ads/routes_creative_theme.py）：不需要任何 AI 呼叫——主題與元件直接用
theme_repository 灌資料，只驗路由層的內容組裝形狀、查無此物、輸入驗證。setUp 寫法照抄
app/tests/test_ads_theme_adopt_reject.py（票 10）。品牌與產品名一律虛構。
"""

import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_theme_copy_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.ads import theme_repository as theme_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import settings as coresettings  # noqa: E402
from app.creative.format_specs import FORMAT_SPECS  # noqa: E402


ACTOR = "測試員"


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)


class _Base(unittest.TestCase):
    def setUp(self):
        main.conn.execute("DELETE FROM app_setting")
        main.conn.commit()
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡（複製票）",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]
        self.product_id = bi_repo.create_product(main.conn, self.bid, name="虛構濾掛組",
                                                  actor=ACTOR)["id"]
        self.cycle_id = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[self.product_id],
            pain_value=5, objective="sales", actor=ACTOR,
        )["id"]
        self.cell_id = main.coredb.new_id("exc")
        main.conn.execute(
            "INSERT INTO experiment_cell (id, org_id, campaign_cycle_id, brand_id, created_at)"
            " VALUES (%s, %s, %s, %s, %s)",
            (self.cell_id, main.coredb.DEV_ORG_ID, self.cycle_id, self.bid, main.coredb.now_iso()),
        )
        main.conn.commit()

    def _create_theme(self, **overrides):
        kwargs = dict(
            campaign_cycle_id=self.cycle_id, experiment_cell_id=self.cell_id,
            format_key="single_image", name="虛構主題：晨光第一杯", folder_code="A1B2",
            actor=ACTOR,
        )
        kwargs.update(overrides)
        return theme_repo.create_theme(main.conn, self.bid, **kwargs)


class ImagePromptBatchCopyTest(_Base):
    def test_batch_content_is_header_plus_size_line_plus_prompts(self):
        coresettings.set_setting(
            main.conn, coresettings.IMAGE_PROMPT_HEADER_SETTING,
            "圖上文字一律平面實填，不要浮雕字")
        theme = self._create_theme(components=[
            {"component_type": "image_prompt", "content": "第一則提示詞"},
            {"component_type": "image_prompt", "content": "第二則提示詞"},
        ])
        resp = self.client.get(
            f"/api/ads/brands/{self.bid}/ads/{self.cycle_id}"
            f"/themes/{theme['id']}/image-prompts/copy")
        self.assertEqual(resp.status_code, 200)
        groups = resp.json()["groups"]
        self.assertEqual(len(groups), 1)
        content = groups[0]["content"]
        self.assertEqual(groups[0]["count"], 2)
        # 開頭在最前面
        self.assertTrue(content.startswith("圖上文字一律平面實填，不要浮雕字"))
        # 尺寸張數行照規格表帶，不是寫死的字串（AC3）
        ratio = FORMAT_SPECS["single_image"]["ratio"]
        width, height = FORMAT_SPECS["single_image"]["pixels"]
        self.assertIn(f"{width}×{height}", content)
        self.assertIn(ratio, content)
        self.assertIn("本組共 2 張", content)
        # 兩則提示詞都在，且都在尺寸行之後
        self.assertIn("第一則提示詞", content)
        self.assertIn("第二則提示詞", content)
        self.assertLess(content.index(f"{width}×{height}"), content.index("第一則提示詞"))

    def test_no_header_set_omits_header_line(self):
        theme = self._create_theme(components=[
            {"component_type": "image_prompt", "content": "唯一一則提示詞"},
        ])
        resp = self.client.get(
            f"/api/ads/brands/{self.bid}/ads/{self.cycle_id}"
            f"/themes/{theme['id']}/image-prompts/copy")
        self.assertEqual(resp.status_code, 200)
        content = resp.json()["groups"][0]["content"]
        width, height = FORMAT_SPECS["single_image"]["pixels"]
        # 沒設開頭時，內容第一行就是尺寸張數行，不是空白或占位字串
        self.assertTrue(content.startswith(f"尺寸 {width}×{height}"))

    def test_twelve_prompts_split_into_ten_plus_two(self):
        """AC2：12 則提示詞時拆 10＋2 兩組。"""
        components = [{"component_type": "image_prompt", "content": f"提示詞{i}"}
                     for i in range(12)]
        theme = self._create_theme(components=components)
        resp = self.client.get(
            f"/api/ads/brands/{self.bid}/ads/{self.cycle_id}"
            f"/themes/{theme['id']}/image-prompts/copy")
        self.assertEqual(resp.status_code, 200)
        groups = resp.json()["groups"]
        self.assertEqual(len(groups), 2)
        self.assertEqual([g["count"] for g in groups], [10, 2])
        # 第一組出現前 10 則、不出現第 11、12 則；第二組反過來
        self.assertIn("提示詞0", groups[0]["content"])
        self.assertIn("提示詞9", groups[0]["content"])
        self.assertNotIn("提示詞10", groups[0]["content"])
        self.assertIn("提示詞10", groups[1]["content"])
        self.assertIn("提示詞11", groups[1]["content"])

    def test_carousel_uses_carousel_format_spec_for_size_line(self):
        """AC3：尺寸行照該主題格式從規格表帶，輪播（1:1 1080×1080）跟單圖不一樣。"""
        theme = self._create_theme(format_key="carousel", components=[
            {"component_type": "card_image_prompt", "sequence": 1, "content": "第一卡圖"},
            {"component_type": "card_title", "sequence": 1, "content": "第一卡標題"},
            {"component_type": "card_description", "sequence": 1, "content": "第一卡說明"},
        ])
        resp = self.client.get(
            f"/api/ads/brands/{self.bid}/ads/{self.cycle_id}"
            f"/themes/{theme['id']}/image-prompts/copy")
        self.assertEqual(resp.status_code, 200)
        content = resp.json()["groups"][0]["content"]
        ratio = FORMAT_SPECS["carousel"]["ratio"]
        width, height = FORMAT_SPECS["carousel"]["pixels"]
        self.assertIn(f"{width}×{height}", content)
        self.assertIn(ratio, content)
        self.assertIn("第一卡圖", content)
        # 卡標題／卡說明是文字元件，不進整組複製（AC4）
        self.assertNotIn("第一卡標題", content)
        self.assertNotIn("第一卡說明", content)

    def test_video_theme_has_no_image_prompts_to_copy(self):
        """影片格式沒有圖片提示詞元件（腳本＋Hook 池），整組複製回人話錯誤，不回空陣列。"""
        theme = self._create_theme(format_key="video", components=[
            {"component_type": "script", "content": '{"framework":"PAS","segments":[]}'},
        ])
        resp = self.client.get(
            f"/api/ads/brands/{self.bid}/ads/{self.cycle_id}"
            f"/themes/{theme['id']}/image-prompts/copy")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("沒有圖片提示詞", resp.json()["error"])

    def test_404_on_unknown_theme(self):
        resp = self.client.get(
            f"/api/ads/brands/{self.bid}/ads/{self.cycle_id}"
            f"/themes/cth_not_real/image-prompts/copy")
        self.assertEqual(resp.status_code, 404)

    def test_404_on_theme_from_a_different_cycle(self):
        other_cycle_id = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[self.product_id],
            pain_value=5, objective="sales", actor=ACTOR,
        )["id"]
        theme = self._create_theme(components=[
            {"component_type": "image_prompt", "content": "提示詞"},
        ])
        resp = self.client.get(
            f"/api/ads/brands/{self.bid}/ads/{other_cycle_id}"
            f"/themes/{theme['id']}/image-prompts/copy")
        self.assertEqual(resp.status_code, 404)


class ComponentCopyTest(_Base):
    def test_returns_pure_content_for_text_component(self):
        theme = self._create_theme(components=[
            {"component_type": "body", "content": "三分鐘沖一杯好咖啡"},
        ])
        component_id = theme["components"][0]["id"]
        resp = self.client.get(
            f"/api/ads/brands/{self.bid}/ads/{self.cycle_id}"
            f"/components/{component_id}/copy")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"content": "三分鐘沖一杯好咖啡"})

    def test_404_on_unknown_component(self):
        resp = self.client.get(
            f"/api/ads/brands/{self.bid}/ads/{self.cycle_id}/components/cthc_not_real/copy")
        self.assertEqual(resp.status_code, 404)

    def test_404_on_component_from_a_different_cycle(self):
        other_cycle_id = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[self.product_id],
            pain_value=5, objective="sales", actor=ACTOR,
        )["id"]
        theme = self._create_theme(components=[
            {"component_type": "title", "content": "早晨從一杯開始"},
        ])
        component_id = theme["components"][0]["id"]
        resp = self.client.get(
            f"/api/ads/brands/{self.bid}/ads/{other_cycle_id}"
            f"/components/{component_id}/copy")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
