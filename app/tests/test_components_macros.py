# -*- coding: utf-8 -*-
"""app/tests/test_components_macros.py — D線票1（GitHub issue #43）共用元件套件：
卡片／進度軌／詳情三個 Jinja macro。

不需要資料庫或 FastAPI app：三個 macro 都是純樣板渲染，直接用獨立的 Jinja Environment
指到 app/templates/_components/ 測試即可（跟 app/tests 既有的『能不碰資料庫就不碰』
精神一致）。

進度軌 macro 的「不收合／收合」兩種呼叫端各有專屬測試（票 #43 驗收條件）：
- IntakeCallerTest 模擬建檔精靈呼叫端（wizard_steps，全展開，不收合）。
- CollapsedCallerTest 模擬廣告檔期呼叫端（progress_rail(..., collapsed=True)，
  只亮當前格與下一格，其餘收合為序號）。
"""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"

env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)


def _draft(brand_id="brd_x", **overrides):
    base = {"brand_id": brand_id, "scan_done": False, "answers": [], "question_index": 0,
            "handoff_generated": False, "paste_raw": None}
    base.update(overrides)
    return base


class ProgressRailUncollapsedTest(unittest.TestCase):
    """建檔精靈呼叫端：wizard_steps(draft, current)，全展開、不收合。"""

    def setUp(self):
        tmpl = env.get_template("_components/wizard_steps.html")
        self.module = tmpl.make_module()

    def test_step2_scan_current_matches_old_three_state_semantics(self):
        # 對齊泛化前的邏輯：num==current -> current；num<current 且有 url -> done（可點）；
        # 其餘（含 num<current 但沒有 url）一律當 future（渲染成 rail-next，不可點）。
        draft = _draft(scan_done=False)  # 第 2 步 url 條件未成立
        out = str(self.module.wizard_steps(draft, 2))
        self.assertIn('aria-label="精靈步驟"', out)
        self.assertIn('<span class="rail-current" aria-current="step">初步印象</span>', out)
        # 第 1 步永遠沒有 url，num(1) < current(2) 但沒有 url -> 不是 done，是 rail-next
        self.assertIn('<span class="rail-next">起始輸入</span>', out)
        self.assertNotIn("rail-done", out)
        self.assertNotIn("rail-collapsed", out)  # 不收合模式沒有 rail-collapsed

    def test_step3_question_shows_done_link_for_completed_scan(self):
        draft = _draft(scan_done=True)
        out = str(self.module.wizard_steps(draft, 3))
        self.assertIn('<a class="rail-done" href="/brands/brd_x/intake/scan">初步印象</a>', out)
        self.assertIn('<span class="rail-current" aria-current="step">引導問答</span>', out)
        self.assertIn('<span class="rail-next">交接包</span>', out)
        self.assertIn('<span class="rail-next">貼回</span>', out)

    def test_dot_separator_between_every_item_not_before_first(self):
        draft = _draft()
        out = str(self.module.wizard_steps(draft, 1))
        self.assertEqual(out.count('<span class="dot-sep" aria-hidden="true">・</span>'), 4)  # 5 步驟 = 4 個分隔
        self.assertFalse(out.lstrip().startswith('<span class="dot-sep"'))


class ProgressRailCollapsedTest(unittest.TestCase):
    """廣告檔期一類的收合呼叫端：progress_rail(items, collapsed=True)。
    只亮當前格與下一格，其餘（不論在前在後）一律收合成序號。"""

    def setUp(self):
        tmpl = env.get_template("_components/wizard_steps.html")
        self.module = tmpl.make_module()

    def _items(self, current: int):
        labels = ["計畫", "素材", "交接包", "投放前檢查", "成效"]
        items = []
        for num, name in enumerate(labels, start=1):
            status = "current" if num == current else ("done" if num < current else "future")
            items.append((num, name, None, status))
        return items

    def test_middle_stage_only_current_and_next_expanded(self):
        out = str(self.module.progress_rail(self._items(3), collapsed=True))
        self.assertIn('<span class="rail-current" aria-current="step">交接包</span>', out)
        self.assertIn('<span class="rail-next">投放前檢查</span>', out)  # 緊接在後的下一格
        # 其餘（前面兩個已完成的、最後一個更遠的 future）一律收合成序號
        self.assertIn('<span class="rail-collapsed">1</span>', out)
        self.assertIn('<span class="rail-collapsed">2</span>', out)
        self.assertIn('<span class="rail-collapsed">5</span>', out)
        self.assertNotIn("計畫</span>", out)
        self.assertNotIn("素材</span>", out)
        self.assertNotIn("成效</span>", out)

    def test_first_stage_has_no_done_cells_to_collapse(self):
        out = str(self.module.progress_rail(self._items(1), collapsed=True))
        self.assertIn('<span class="rail-current" aria-current="step">計畫</span>', out)
        self.assertIn('<span class="rail-next">素材</span>', out)
        self.assertIn('<span class="rail-collapsed">3</span>', out)
        self.assertIn('<span class="rail-collapsed">4</span>', out)
        self.assertIn('<span class="rail-collapsed">5</span>', out)

    def test_last_stage_no_next_cell_exists(self):
        out = str(self.module.progress_rail(self._items(5), collapsed=True))
        self.assertIn('<span class="rail-current" aria-current="step">成效</span>', out)
        self.assertNotIn("rail-next", out)  # 沒有下一格可亮
        for n in (1, 2, 3, 4):
            self.assertIn(f'<span class="rail-collapsed">{n}</span>', out)

    def test_done_cell_with_url_is_collapsed_but_still_clickable(self):
        # 收合模式下，done 格有連結時收合成序號、但仍渲染成可點的 <a>（可點回顧，
        # GitHub issue #46）——收合只收掉完整名稱，不收掉可點性。
        items = [(1, "計畫", "/somewhere", "done"), (2, "素材", None, "current"),
                 (3, "交接包", None, "future")]
        out = str(self.module.progress_rail(items, collapsed=True))
        self.assertIn('<a class="rail-collapsed rail-done" href="/somewhere">1</a>', out)
        self.assertNotIn(">計畫<", out)  # 不展開完整名稱

    def test_done_cell_without_url_is_collapsed_and_not_a_link(self):
        # done 格沒有連結（呼叫端沒給）時，維持原本收合、不可點
        items = [(1, "計畫", None, "done"), (2, "素材", None, "current"),
                 (3, "交接包", None, "future")]
        out = str(self.module.progress_rail(items, collapsed=True))
        self.assertIn('<span class="rail-collapsed">1</span>', out)
        self.assertNotIn("<a ", out)


class CardMacroTest(unittest.TestCase):
    def setUp(self):
        tmpl = env.get_template("_components/card.html")
        self.module = tmpl.make_module()

    def test_linked_card_reuses_existing_classes_only(self):
        out = str(self.module.card("標題", "說明文字。", url="/x"))
        self.assertIn('<a class="card menu-card" href="/x">', out)
        self.assertIn("<h3>標題</h3>", out)
        self.assertIn("<p>說明文字。</p>", out)
        self.assertNotIn("menu-card-stats", out)

    def test_no_url_renders_div_not_link(self):
        out = str(self.module.card("標題", "說明。"))
        self.assertIn('<div class="card menu-card">', out)
        self.assertNotIn("<a ", out)

    def test_soon_adds_existing_soon_class_only(self):
        out = str(self.module.card("標題", "說明。", soon=True))
        self.assertIn('class="card menu-card menu-card-soon"', out)

    def test_stats_line_uses_existing_stats_class(self):
        out = str(self.module.card("標題", "說明。", url="/x", stats="共 3 筆"))
        self.assertIn('<p class="menu-card-stats">共 3 筆</p>', out)

    def test_kind_content_adds_card_content_class(self):
        """修憲落地 V2：kind='content' 掛 .card-content（不掛 menu-card），
        capacity_check 才能分流、不計入主欄 ≤5 上限。"""
        out = str(self.module.card("標題", "說明。", url="/x", kind="content"))
        self.assertIn('<a class="card card-content" href="/x">', out)
        self.assertNotIn("menu-card", out)

    def test_kind_notice_adds_card_notice_class(self):
        out = str(self.module.card("標題", "說明。", kind="notice"))
        self.assertIn('<div class="card card-notice">', out)


class CardBlockMacroTest(unittest.TestCase):
    """card_block：接 {% call %} 內容的卡片變體（GitHub issue #43 缺陷 3），與現行
    手寫卡片（ads_home.html 的 <div class="card">、ads_connections.html 的
    <section class="card">）等價比對，class 一致。"""

    def setUp(self):
        self.tmpl_src = (
            '{% from "_components/card.html" import card_block %}'
            '{% call card_block("進行中檔期") %}<p>內容</p>{% endcall %}'
        )

    def test_div_variant_matches_existing_hand_written_div_card(self):
        # 比照 ads_home.html:24 現行手寫的 <div class="card"><h3>進行中檔期</h3>...</div>
        out = env.from_string(self.tmpl_src).render()
        self.assertIn('<div class="card">', out)
        self.assertIn('<h3>進行中檔期</h3>', out)
        self.assertIn('<p>內容</p>', out)
        self.assertIn('</div>', out)
        self.assertNotIn('menu-card', out)  # 不是選單入口卡，class 跟手寫版一致

    def test_section_tag_matches_existing_hand_written_section_card(self):
        # 比照 ads_connections.html:29 現行手寫的 <section class="card"><h3>...</h3>...</section>
        src = ('{% from "_components/card.html" import card_block %}'
               '{% call card_block("訂單與成效資料", tag="section") %}<p>內容</p>{% endcall %}')
        out = env.from_string(src).render()
        self.assertIn('<section class="card">', out)
        self.assertIn('</section>', out)

    def test_url_renders_link_not_container_tag(self):
        src = ('{% from "_components/card.html" import card_block %}'
               '{% call card_block("標題", url="/x") %}<p>內容</p>{% endcall %}')
        out = env.from_string(src).render()
        self.assertIn('<a class="card" href="/x">', out)
        self.assertNotIn('<div', out)

    def test_no_title_omits_h3(self):
        src = ('{% from "_components/card.html" import card_block %}'
               '{% call card_block() %}<p>內容</p>{% endcall %}')
        out = env.from_string(src).render()
        self.assertNotIn('<h3>', out)
        self.assertIn('<p>內容</p>', out)

    def test_kind_entry_adds_menu_card_class(self):
        """修憲落地 V2：card_block() 也能明確指定 kind='entry'，掛上 menu-card 讓
        capacity_check 計入主欄 ≤5 上限。"""
        src = ('{% from "_components/card.html" import card_block %}'
               '{% call card_block("標題", kind="entry") %}<p>內容</p>{% endcall %}')
        out = env.from_string(src).render()
        self.assertIn('<div class="card menu-card">', out)

    def test_kind_notice_adds_card_notice_class(self):
        src = ('{% from "_components/card.html" import card_block %}'
               '{% call card_block("標題", kind="notice") %}<p>內容</p>{% endcall %}')
        out = env.from_string(src).render()
        self.assertIn('<div class="card card-notice">', out)


class DetailMacroTest(unittest.TestCase):
    def setUp(self):
        self.tmpl_src = (
            '{% from "_components/detail.html" import detail %}'
            '{% call detail() %}<p>內容文字</p>{% endcall %}'
        )

    def test_fixed_trigger_word_and_existing_classes(self):
        out = env.from_string(self.tmpl_src).render()
        self.assertIn('<details class="field-details">', out)
        self.assertIn("詳情", out)
        self.assertIn('<div class="details-body"><p>內容文字</p></div>', out)

    def test_open_param_adds_open_attribute(self):
        src = ('{% from "_components/detail.html" import detail %}'
               '{% call detail(open=True) %}<p>x</p>{% endcall %}')
        out = env.from_string(src).render()
        self.assertIn('<details class="field-details" open>', out)


if __name__ == "__main__":
    unittest.main()
