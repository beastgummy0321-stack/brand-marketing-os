# -*- coding: utf-8 -*-
"""app/tests/test_capacity_check.py — D線票1（GitHub issue #43）容量驗收腳本自檢。

票面硬性要求「腳本自檢：餵一份故意超標的 HTML 必須失敗、餵合規的必須通過（沒有自檢
等於沒有刑度）」——本檔就是那份自檢，另外也覆蓋四項計數本身的邊界情況。
"""

import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from app.tools import capacity_check as cc

_tmpdir = tempfile.mkdtemp(prefix="brand_os_capacity_check_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import interrupts as core_interrupts  # noqa: E402

main.reopen_connection()

ACTOR = "測試員"


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)


def _cards(n: int, text: str = "一句話說明。") -> str:
    return "".join(f'<a class="card menu-card" href="/x{i}"><h3>卡{i}</h3><p>{text}</p></a>'
                    for i in range(n))


class CountingTest(unittest.TestCase):
    def test_card_count_matches_card_class_token(self):
        html = '<div class="menu-grid">' + _cards(3) + "</div>"
        counts = cc.check_html(html)
        self.assertEqual(counts["card_count"], 3)

    def test_menu_card_stats_paragraph_is_not_itself_a_card(self):
        html = ('<a class="card menu-card" href="/x">'
                '<h3>卡</h3><p>說明。</p><p class="menu-card-stats">共 3 筆</p></a>')
        counts = cc.check_html(html)
        self.assertEqual(counts["card_count"], 1)  # 不會把 stats 段落也算成一張卡

    def test_nav_link_count_only_counts_a_tags_with_menu_card(self):
        html = ('<div class="menu-grid">'
                '<a class="card menu-card" href="/a">A</a>'
                '<a class="card menu-card" href="/b">B</a>'
                '<a class="link" href="/c">純文字連結</a>'  # 不算導覽入口
                '<div class="card menu-card menu-card-soon">C</div>'  # 沒連結，不算
                "</div>")
        counts = cc.check_html(html)
        self.assertEqual(counts["nav_link_count"], 2)
        self.assertEqual(counts["card_count"], 3)

    def test_illegal_detail_flagged_legal_detail_not(self):
        html = ('<details class="field-details"><summary>詳情</summary>x</details>'
                '<details class="my-own-thing"><summary>自製收合</summary>y</details>')
        counts = cc.check_html(html)
        self.assertEqual(counts["illegal_detail_count"], 1)

    def test_all_six_registered_detail_classes_are_legal(self):
        for cls in sorted(cc.LEGAL_DETAIL_CLASSES):
            html = f'<details class="{cls}"><summary>x</summary>y</details>'
            self.assertEqual(cc.check_html(html)["illegal_detail_count"], 0, cls)

    def test_card_text_excludes_nested_detail_content(self):
        # §20.1 規則 4：「詳情展開後的內文不受 30 字限」——巢狀 details 的字不算進外層卡片
        long_text = "字" * 50
        html = (f'<div class="card menu-card"><h3>卡</h3><p>短說明。</p>'
                f'<details class="field-details"><summary>詳情</summary>'
                f'<div class="details-body">{long_text}</div></details></div>')
        counts = cc.check_html(html)
        self.assertEqual(len(counts["card_text_counts"]), 1)
        self.assertLess(counts["card_text_counts"][0], 30)  # 只有卡面本文，不含展開內容

    def test_wide_char_count_ignores_ascii(self):
        html = '<div class="card menu-card"><h3>ABC123</h3></div>'
        counts = cc.check_html(html)
        self.assertEqual(counts["card_text_counts"][0], 0)  # 半形英數不算全形字

    def test_explicit_content_kind_card_not_counted_toward_card_limit(self):
        """修憲落地 V2：明講 kind='content' 才會掛 .card-content，才不計入主欄 ≤5
        上限，但仍會被量測文字數（規則 4 沿用既有邏輯，本票不擴大修改）。"""
        html = '<div class="card card-content"><p>一段內容摘要。</p></div>'
        counts = cc.check_html(html)
        self.assertEqual(counts["card_count"], 0)
        self.assertEqual(len(counts["card_text_counts"]), 1)

    def test_unmarked_card_still_counts_like_before_kind_existed(self):
        """沒有指定 kind 的裸 class="card"（既有頁面手寫卡片、尚未遷移的 card_block()
        呼叫）維持舊行為照樣計入，避免既有頁面已驗收過的卡片數無聲跳動。"""
        html = '<div class="card"><p>沒有 kind 標記。</p></div>'
        counts = cc.check_html(html)
        self.assertEqual(counts["card_count"], 1)

    def test_notice_kind_card_is_counted_toward_card_limit(self):
        """kind='notice'（頁面自建的提醒卡）掛 .card-notice，依決策 0033 仍計入。"""
        html = '<div class="card card-notice"><p>提醒訊息。</p></div>'
        counts = cc.check_html(html)
        self.assertEqual(counts["card_count"], 1)

    def test_select_option_text_excluded_from_card_char_count(self):
        """修憲落地 V7：<select> 的 <option> 文字是操作介面（模型／思考等級下拉選單），
        不是規則 4 要管的說明句，比照 <details> 排除，不計入卡片字數。"""
        long_option_text = "字" * 40  # 單一 option 就超過 30 字上限
        html = (f'<div class="card menu-card"><h3>卡</h3><p>短說明。</p>'
                f'<select><option>{long_option_text}</option></select></div>')
        counts = cc.check_html(html)
        self.assertLess(counts["card_text_counts"][0], 30)  # 只算卡面本文，不含選單選項

    def test_mixed_kinds_only_explicit_content_is_excluded(self):
        html = (
            '<div class="menu-grid">' + _cards(2) +  # 2 張 entry
            '<div class="card card-content"><p>內容卡一。</p></div>'  # 明講 content，不計
            '<div class="card"><p>沒標記，照舊計入。</p></div>'  # 沒 kind，照舊計入
            '<div class="card card-notice"><p>提醒卡。</p></div>'  # notice，計入
            "</div>"
        )
        counts = cc.check_html(html)
        self.assertEqual(counts["card_count"], 4)  # 2 entry + 1 未標記 + 1 notice


class SelfCheckTest(unittest.TestCase):
    """票面要求的腳本自檢本體：餵超標必失敗、餵合規必通過。"""

    def test_over_limit_html_fails(self):
        over_cards = '<div class="menu-grid">' + _cards(6) + "</div>"  # 6 張卡 > 上限 5
        counts = cc.check_html(over_cards)
        problems = cc.violations("over.html", counts)
        self.assertTrue(problems)
        self.assertTrue(any("卡片數" in p for p in problems))

    def test_compliant_html_passes(self):
        ok_html = '<div class="menu-grid">' + _cards(3) + "</div>"
        counts = cc.check_html(ok_html)
        problems = cc.violations("ok.html", counts)
        self.assertEqual(problems, [])

    def test_nav_link_limit_not_checked_by_default(self):
        """§20.1 規則 2「頂層導覽入口 ≤4」只約束品牌功能選單頁，不是任何頁面的
        menu-card 連結數——預設不檢查，超過也不報違規（缺陷 2 修正）。"""
        html = '<div class="menu-grid">' + _cards(5) + "</div>"  # 5 個 menu-card 連結
        problems = cc.violations("nav.html", cc.check_html(html))
        self.assertEqual(problems, [])

    def test_nav_link_limit_checked_when_opted_in(self):
        """呼叫端明確指定這頁要套用「頂層導覽入口 ≤4」才檢查（品牌功能選單頁）。"""
        html = '<div class="menu-grid">' + _cards(5) + "</div>"  # 5 個 menu-card 連結 > 上限 4
        problems = cc.violations("nav.html", cc.check_html(html), check_nav_limit=True)
        self.assertTrue(any("導覽連結數" in p for p in problems))

    def test_over_limit_card_text_fails(self):
        long_text = "說" * 40  # 40 個全形字 > 上限 30
        html = f'<div class="card menu-card"><h3>卡</h3><p>{long_text}</p></div>'
        problems = cc.violations("text.html", cc.check_html(html))
        self.assertTrue(any("單卡文字數" in p or "全形字" in p for p in problems))

    def test_cli_main_exit_code_nonzero_on_violation_zero_when_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad_path = Path(tmp) / "bad.html"
            ok_path = Path(tmp) / "ok.html"
            bad_path.write_text('<div class="menu-grid">' + _cards(6) + "</div>", encoding="utf-8")
            ok_path.write_text('<div class="menu-grid">' + _cards(2) + "</div>", encoding="utf-8")

            self.assertEqual(cc.main([str(bad_path)]), 1)
            self.assertEqual(cc.main([str(ok_path)]), 0)

    def test_cli_main_no_args_returns_usage_exit_code(self):
        self.assertEqual(cc.main([]), 2)

    def test_cli_check_nav_limit_flag_applies_only_to_specified_page(self):
        """CLI 能指定哪些頁面套用「頂層導覽入口 ≤4」（缺陷 2 修正）。"""
        with tempfile.TemporaryDirectory() as tmp:
            page_a = Path(tmp) / "menu.html"
            page_b = Path(tmp) / "other.html"
            five_links = '<div class="menu-grid">' + _cards(5) + "</div>"  # 5 個 menu-card 連結
            page_a.write_text(five_links, encoding="utf-8")
            page_b.write_text(five_links, encoding="utf-8")

            # 沒指定 --check-nav-limit：兩頁都不檢查這條規則，全部通過
            self.assertEqual(cc.main([str(page_a), str(page_b)]), 0)

            # 只對 page_a 指定套用：page_a 違規，退出碼非 0
            exit_code = cc.main(["--check-nav-limit", str(page_a), str(page_a), str(page_b)])
            self.assertEqual(exit_code, 1)


class MainScopeExcludesInterruptQueueTest(unittest.TestCase):
    """缺陷 1 修正：打斷佇列卡渲染在 <main> 之外（決策 0029、DESIGN.md §20.1 規則 1），
    不計入主欄卡片數。用 app.core.interrupts.enqueue() 造一筆真實佇列項，打 HTTP 取得
    實際渲染的 HTML 來驗（只讀 app.core.interrupts，不修改它）。"""

    def setUp(self):
        self.client = TestClient(main.app)
        self.client.post("/settings/operator", data={"name": ACTOR, "next": "/"},
                         follow_redirects=False)
        self.brand = bi_repo.create_brand(main.conn, name=f"虛構容量驗收{self.id()[-6:]}",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]

    def test_interrupt_queue_card_not_counted_in_main_card_count(self):
        resp_before = self.client.get(f"/brands/{self.bid}")
        counts_before = cc.check_html(resp_before.text)
        self.assertNotIn("current-interrupt-bar", resp_before.text)  # 這時還沒有佇列項

        core_interrupts.enqueue(
            main.conn, category="cycle_reminder", dedupe_key=f"capacity-check-{self.bid}",
            message="測試用打斷佇列訊息。", brand_id=self.bid,
        )
        main.conn.commit()

        resp_after = self.client.get(f"/brands/{self.bid}")
        self.assertIn("current-interrupt-bar", resp_after.text)  # 打斷佇列卡確實有渲染
        counts_after = cc.check_html(resp_after.text)
        # 主欄卡片數在打斷佇列卡出現前後不變——它渲染在 <main> 之外，不算進來
        self.assertEqual(counts_after["card_count"], counts_before["card_count"])


if __name__ == "__main__":
    unittest.main()
