# -*- coding: utf-8 -*-
"""app/tests/test_ads_creative_buttons.py — 素材頁上的按鈕：逐則複製鈕（T-G2-2）與直接生圖空殼鈕。

setUp 沿用 test_ads_creative 的 _BaseCreativeTest——該檔已達行數上限（只准變小），
新測試依 A1 檢查⑤「要加就先拆」另立本檔。全程 FakeProvider，不發任何真實網路請求。
"""

import json
import re
import unittest

from app.tests.test_ads_creative import _BaseCreativeTest


class CreativeButtonsTest(_BaseCreativeTest):
    def test_每則文案有純圖示複製鈕_圖片提示詞不重複給(self):
        """票 T-G2-2：文案／開場白各一顆純圖示複製鈕，複製的是該則純文字。

        圖片提示詞底下已經有 copy_block 的「複製全部」，不再疊第二顆。
        """
        variants = [
            {"cell_id": self.cell_ids[0], "variant_type": "copy", "content": "這則文案的純文字",
             "creative_angle_number": 7, "on_camera": False, "cut_type": "pain_visualized",
             "quote_source": None,
             "fingerprint": {"angle": "pain", "tone": "warm", "format": "text_focus",
                             "selling_point": "quality"}},
            {"cell_id": self.cell_ids[0], "variant_type": "image_prompt", "content": "一張情境圖",
             "creative_angle_number": 7, "on_camera": False, "cut_type": None,
             "quote_source": None,
             "fingerprint": {"angle": "pain", "tone": "warm", "format": "single_image",
                             "selling_point": "quality"}},
        ]
        self._generate(reply=json.dumps({"variants": variants}, ensure_ascii=False))
        rows = {v["variant_type"]: v for v in self._variants()}
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives").text

        # 文案：按鈕存在、有無障礙名稱、抓的 id 就是承載該則文字的元素
        self.assertIn('aria-label="複製這則廣告文案"', page)
        self.assertIn(f"creative-text-{rows['copy']['id']}", page)
        self.assertIn(f'id="creative-text-{rows["copy"]["id"]}"', page)
        self.assertIn("navigator.clipboard.writeText", page)
        # ✓ 必須掛在 writeText 的成功分支上；同步蓋掉就會「沒複製到也報成功」
        handler = re.search(r'aria-label="複製這則廣告文案"\s+onclick="([^"]+)"', page).group(1)
        self.assertIn(".then(", handler)
        self.assertNotRegex(handler, r"writeText\([^)]*\)[^.]*;\s*b?\.?textContent\s*=")
        # 圖片提示詞：沒有第二顆圖示鈕
        self.assertNotIn(f'creative-text-{rows["image_prompt"]["id"]}', page)
        self.assertNotIn('aria-label="複製這則圖片提示詞"', page)

    def test_直接生圖是按不下去的空殼鈕(self):
        """ADR 0008：刻意留下的空殼按鈕，必須存在且必須按不下去。"""
        self._generate()
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives").text
        self.assertIn("直接生圖（建置中）", page)
        self.assertIn('class="btn btn-secondary" disabled', page)


if __name__ == "__main__":
    unittest.main()
