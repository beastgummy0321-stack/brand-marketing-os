# -*- coding: utf-8 -*-
"""卡片元件的 CSS 回歸檢查（2026-08-03，修使用者回報的廣告首頁「白色殘影」）。

背景：`card_block(url=...)` 會渲染成 `<a class="card">`，而 `<a>` 預設是 inline。
inline 元素包住 `<h3>`／`<p>` 這種區塊子元素時，瀏覽器會把 inline 盒切成多個片段，
**每一片各自畫一次背景、外框與內距**——畫面上就是幾塊漂浮的白色矩形。

當時 `.card` 沒有 `display` 屬性、`.menu-card` 才有 `display:block`，
而 V2 新增的 `kind='content'`／`'notice'` 對應的信號 class 在 `app.css` 裡根本沒有定義，
所以 `kind='content'` 的可點卡就是裸的 inline `<a>`。

這支測試守兩件事（決策 0031 第 1 條：無檢查不成規則）：
1. `.card` 一定要有 `display: block`——不然任何 `<a class="card">` 都會碎掉。
2. `card.html` macro 會掛的每一個 kind class，要嘛在 `app.css` 有定義，
   要嘛明文列進下方「純信號、不需樣式」的清單。
   當初就是因為沒有這道檢查，`.card-content` 憑空消失沒人發現。
"""

import re
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_CSS = _ROOT / "app" / "static" / "app.css"
_CARD_MACRO = _ROOT / "app" / "templates" / "_components" / "card.html"

# 純信號用、給 capacity_check.py 分流計數，不需要任何視覺樣式。
# 要新增請連同理由一起寫在這裡，不要默默放行。
SIGNAL_ONLY_CLASSES = {
    "card-content",  # 順序閱讀的內容卡：計數時不計入主欄 ≤5，視覺與一般 .card 相同
    "card-notice",   # 頁面自建的提醒卡：照計（決策 0029 例外），視覺與一般 .card 相同
}


def _css_text() -> str:
    """讀 app.css 並**去掉註解**。

    去註解不是潔癖：本檔第一版沒去，而 `.card` 的註解裡剛好寫著「`.menu-card` 一直有
    display:block」這句話，正則在註解裡就命中了——把 `display: block` 整條刪掉測試還是綠的。
    紅燈驗證（故意弄壞看測試會不會紅）才抓到這件事。
    """
    css = _CSS.read_text(encoding="utf-8")
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


class CardDisplayBlockTest(unittest.TestCase):
    def test_card_rule_declares_display_block(self):
        """`.card` 必須明寫 display:block，否則 <a class="card"> 會碎成多個片段。"""
        css = _css_text()
        match = re.search(r"^\.card\s*\{(.*?)\}", css, re.S | re.M)
        self.assertIsNotNone(match, "app.css 找不到 .card 規則")
        body = match.group(1)
        self.assertRegex(
            body, r"display\s*:\s*block",
            "`.card` 少了 display:block。<a class=\"card\"> 會變成 inline，"
            "包住 <h3>/<p> 時瀏覽器會把它切成多段，每段各畫一次白底＋外框＝畫面白色殘影。",
        )

    def test_clickable_card_has_interaction_feedback(self):
        """可點的卡要有 hover 與 :active（DESIGN.md §15 鬆綁後的必要互動回饋）。"""
        css = _css_text()
        self.assertRegex(css, r"a\.card:hover", "缺 a.card:hover")
        self.assertRegex(css, r"a\.card:active", "缺 a.card:active")


class CardKindClassesDefinedTest(unittest.TestCase):
    def test_every_kind_class_is_defined_or_declared_signal_only(self):
        """macro 會掛的 kind class，不能既沒有 CSS 定義、也沒列進純信號清單。"""
        macro = _CARD_MACRO.read_text(encoding="utf-8")
        # macro 內以 'menu-card' / 'card-notice' / 'card-content' 這種字面字串指定 class
        kind_classes = set(re.findall(r"'(menu-card|card-notice|card-content)'", macro))
        self.assertTrue(kind_classes, "card.html 抓不到任何 kind class，測試本身失效了")

        css = _css_text()
        for cls in sorted(kind_classes):
            defined = re.search(rf"^\.{re.escape(cls)}[\s,{{:]", css, re.M) is not None
            self.assertTrue(
                defined or cls in SIGNAL_ONLY_CLASSES,
                f"`.{cls}` 在 app.css 沒有定義，也沒列進 SIGNAL_ONLY_CLASSES。"
                f"要嘛補樣式，要嘛明文承認它只是計數用的信號 class。",
            )

    def test_signal_only_list_has_no_stale_entries(self):
        """清單不得變成死名單：列在裡面的 class 必須真的還被 macro 使用。"""
        macro = _CARD_MACRO.read_text(encoding="utf-8")
        for cls in sorted(SIGNAL_ONLY_CLASSES):
            self.assertIn(
                f"'{cls}'", macro,
                f"SIGNAL_ONLY_CLASSES 裡的 `{cls}` 已經沒有人用了，請從清單移除。",
            )


if __name__ == "__main__":
    unittest.main()
