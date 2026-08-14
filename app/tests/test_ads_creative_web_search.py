# -*- coding: utf-8 -*-
"""app/tests/test_ads_creative_web_search.py — ADR 0005：素材生成這個呼叫點有沒有帶網路搜尋工具。

setUp 沿用 test_ads_creative 的 _BaseCreativeTest——該檔已達行數上限（870 行，
`test_architecture_boundaries.KNOWN_OVERSIZED_FILES` 凍住、只准變小），新測試不得往裡面加，
比照 test_ads_creative_buttons.py 的既有做法另立本檔。跨檔 import 只沿用測試基底；
資料庫由 app/tests/conftest.py 在本模組執行前另開暫存庫，不依賴檔名或收集順序。

打法（campaign_plan）那個呼叫點的同款測試在 test_ads_plan.py；工具定義本身與成本計算
在 test_llm_web_search.py。全程 FakeProvider，不發任何真實網路請求。
"""

import unittest

import app.main as main
from app.ads import creative as ads_creative
from app.llm import providers as llm_providers
from app.llm.providers import FakeProvider
from app.tests.test_ads_creative import _BaseCreativeTest, _fake, _variants_reply


class CreativeCallSiteWebSearchTest(_BaseCreativeTest):
    def test_generation_asks_ai_with_web_search_tool(self):
        """ADR 0005 首波開通的呼叫點之一：素材生成。工具定義引用同一個常數，不各寫一份。"""
        provider = FakeProvider(response=_fake(_variants_reply(self.cell_ids)))
        ads_creative.PROVIDER = provider
        ok, err = ads_creative.generate(main.conn, self.bid, self.cycle_id, "測試員")
        self.assertTrue(ok, err)
        self.assertEqual(provider.calls[0]["tools"], [llm_providers.WEB_SEARCH_TOOL])


if __name__ == "__main__":
    unittest.main()
