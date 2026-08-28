"""app/tools/capacity_check.py — 版面守恆憲法容量驗收腳本（決策 0026、DESIGN.md §20.2、
GitHub issue #43；修憲落地 V2 依 §20.1 規則 1 加入 kind 分流）。

腳本只掃「本次票改動涉及的頁面」——呼叫端自己列頁面清單餵進來，不是全站掃描（§20.2：
「未動到的舊頁不報違憲，增量收斂的可執行定義」）。輸出四項數字，任一超標就非 0 退出碼：

1. 卡片數（依 `_components/card.html` 的 `kind` 分流）——§20.1 規則 1，主欄容量 ≤ 5。
   只有明講 `kind=content`（class 含 "card-content"）才不計入——2026-08-03 依決策 0033，
   內容卡／清單卡不受這條上限約束（DESIGN.md §20.1 規則 1）。`kind=entry`（class 含
   "menu-card"）、`kind=notice`（class 含 "card-notice"）與沒有指定 kind 的裸 "card"
   （既有呼叫端與尚未經 macro 的手寫卡片，例如 ads_home.html「進行中檔期」）一律計入——
   分流只對明講 kind 的呼叫端生效，避免既有頁面已驗收過的卡片數無聲跳動（見 `_card_kind`
   docstring）。**只掃 <main>…</main> 範圍**（找不到 <main> 才退回掃全文）：打斷佇列卡
   渲染在 `_layouts/base.html` 的 `<main>` 之外、屬全站 chrome，決策 0029／§20.1 規則 1
   明文不計入主欄。
2. 導覽連結數（class 含 "menu-card" 的 <a> 個數）——§20.1 規則 2「頂層導覽入口 ≤ 4」。
   這條只約束**品牌功能選單頁**四張分類卡，不是任何頁面的 menu-card 連結數，因此
   **預設不檢查**；呼叫端要對哪一頁套用這條規則，`violations()`／`check_file()` 傳
   `check_nav_limit=True`，CLI 用 `--check-nav-limit <頁面路徑>` 指定。
3. 非法展開元件數（<details> 的 class 不在既有登記清單內）——§20.1 規則 3，全站唯一展開
   元件；既有登記清單＝目前 app.css 已有樣式的 6 個 <details> 變體（field-details 是
   本批新詳情 macro 的輸出，其餘 5 個是既有元件，見 DESIGN.md §10.8）。
4. 單卡內文字數（每張卡片內的全形字數，不含卡片裡巢狀 <details> 展開後才看得到的內文——
   §20.1 規則 4 明文「詳情展開後的內文不受 30 字限」——也不含 <select> 裡的 <option>
   文字，修憲落地 V7 全站容量掃描發現：模型／思考等級下拉選單的選項文字會被算進卡片字數，
   但下拉選單是操作介面本身，不是規則 4 要管的說明句，比照 <details> 排除）——每張卡片
   ≤ 30 全形字。

用 html.parser.HTMLParser（跟 app/core/net.py 的 _TextExtractor 同一套 stdlib 寫法，
不加任何新依賴）；不要求標籤完美平衡——遇到未預期的收合順序一律以「往回找同名標籤」的
寬鬆方式處理，不因為原始碼裡有自我封閉標籤（如 <img>）不平衡而誤判。
"""

import html.parser
import sys
import unicodedata
from pathlib import Path

CARD_LIMIT = 5
NAV_LINK_LIMIT = 4
CARD_TEXT_LIMIT = 30

# 既有已登記、有專屬樣式的 <details> 變體（DESIGN.md §10.8）。field-details 是本批
# 新增的「詳情」macro 輸出；其餘 5 個是這批之前就存在、各自有專屬 CSS 的既有元件。
# 不在這份清單內的 <details> class＝新造的第二套展開元件，判定違憲。
LEGAL_DETAIL_CLASSES = {
    "field-details", "fact-detail", "archived-box",
    "cost-meter-detail", "settings-reveal", "brand-switcher",
}


def _classes(attrs) -> list:
    for key, value in attrs:
        if key == "class":
            return (value or "").split()
    return []


def _wide_char_count(text: str) -> int:
    """全形字數：只算 East Asian Width 為 W（wide）或 F（fullwidth）的字元。"""
    return sum(1 for ch in text if unicodedata.east_asian_width(ch) in ("W", "F"))


def _card_kind(classes: list) -> str | None:
    """回傳這個元素的卡片種類：None＝不是卡片。是卡片時回傳 'entry'／'notice'／'content'
    三擇一，依 `_components/card.html` 的 kind 參數輸出的 class 信號判斷（修憲落地 V2，
    DESIGN.md §20.1 規則 1）：
    - 'menu-card' → entry（功能入口卡）
    - 'card-notice' → notice（頁面自建的提醒卡）
    - 'card-content' → content（內容卡／清單卡，明講 kind='content' 才會掛這個信號）
    - 都沒有（只有裸的 "card"）→ 沿用舊版無分流時代的認定，一律當 entry 計入主欄 ≤5。
      這條刻意保守：既有頁面有未經 card.html macro 的手寫 <div class="card">
      （例如 ads_home.html「進行中檔期」）與尚未指定 kind 的既有 card_block() 呼叫
      （例如 ads_learnings.html），這批已經是 DESIGN.md §20.1 驗收過的既有頁面容量
      數字（首次紙上驗收，issue #50），本票不改頁面模板，沒有機會幫它們補 kind——
      分流只對「明講 kind」的呼叫端生效，沒講就維持舊行為，不會讓既有頁面的卡片數
      無聲跳動。
    """
    if "card" not in classes:
        return None
    if "menu-card" in classes:
        return "entry"
    if "card-notice" in classes:
        return "notice"
    if "card-content" in classes:
        return "content"
    return "entry"


def _main_scope(text: str) -> str:
    """只回傳 <main>…</main> 之間的內容——主欄容量規則只約束頁面內容，不含 header／
    打斷佇列列／footer 這些渲染在 <main> 之外的全站 chrome（決策 0029）。找不到 <main>
    就退回整份文字（例如測試直接餵片段 HTML，沒有完整版型）。"""
    start = text.find("<main")
    if start == -1:
        return text
    start = text.find(">", start)
    if start == -1:
        return text
    start += 1
    end = text.find("</main>", start)
    return text[start:end] if end != -1 else text[start:]


class _CapacityParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.card_count = 0
        self.nav_link_count = 0
        self.illegal_detail_count = 0
        self.card_text_counts: list = []  # 每張已關閉卡片各自的全形字數
        self._stack: list = []  # [(tag, is_card, is_detail, is_select)]
        self._detail_depth = 0  # 目前巢狀在幾層 <details> 裡（其內文不算進外層卡片字數）
        self._select_depth = 0  # 目前巢狀在幾層 <select> 裡（修憲落地 V7：下拉選單的
        # <option> 文字是操作介面，不是規則 4 要管的說明句，同 <details> 的排除邏輯）
        self._card_chars: list = []  # 與目前開著的每張卡片一一對應的字數累加器

    def _open(self, tag: str, attrs) -> None:
        classes = _classes(attrs)
        kind = _card_kind(classes)
        is_card = kind is not None
        is_detail = tag == "details"
        is_select = tag == "select"
        if is_detail:
            self._detail_depth += 1
            if not (set(classes) & LEGAL_DETAIL_CLASSES):
                self.illegal_detail_count += 1
        if is_select:
            self._select_depth += 1
        if is_card:
            # 規則 1 的 ≤5 上限只管 entry／notice；content（內容卡／清單卡）依決策 0033
            # 不計入，但文字量測（規則 4）沿用既有邏輯，對三種卡片一視同仁。
            if kind != "content":
                self.card_count += 1
            self._card_chars.append(0)
        if tag == "a" and "menu-card" in classes:
            self.nav_link_count += 1
        self._stack.append((tag, is_card, is_detail, is_select))

    def _close_frame(self, frame) -> None:
        _tag, was_card, was_detail, was_select = frame
        if was_card:
            self.card_text_counts.append(self._card_chars.pop())
        if was_detail and self._detail_depth:
            self._detail_depth -= 1
        if was_select and self._select_depth:
            self._select_depth -= 1

    def handle_starttag(self, tag, attrs):
        self._open(tag, attrs)

    def handle_startendtag(self, tag, attrs):
        # 自我封閉標籤（例如 <img/>）：開了就算數，沒有對應的 end tag，讓它留在堆疊裡
        # 等外層真正的收合標籤觸發時被一併清掉（見 handle_endtag 的往回找同名邏輯）。
        self._open(tag, attrs)

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                closing = self._stack[i:]
                del self._stack[i:]
                for frame in closing:
                    self._close_frame(frame)
                break

    def handle_data(self, data):
        if self._detail_depth or self._select_depth or not self._card_chars:
            return
        count = _wide_char_count(data)
        if count:
            self._card_chars[-1] += count


def check_html(text: str) -> dict:
    """回傳這頁的四項計數：card_count／nav_link_count／illegal_detail_count／
    card_text_counts（每張卡片各自的全形字數清單）。只計 <main> 範圍內的內容。"""
    parser = _CapacityParser()
    parser.feed(_main_scope(text))
    parser.close()
    return {
        "card_count": parser.card_count,
        "nav_link_count": parser.nav_link_count,
        "illegal_detail_count": parser.illegal_detail_count,
        "card_text_counts": parser.card_text_counts,
    }


def violations(page_name: str, counts: dict, check_nav_limit: bool = False) -> list:
    """回傳這頁超標的違規訊息（人話一句一項）；沒有超標就是空清單。

    check_nav_limit：「頂層導覽入口 ≤4」只約束品牌功能選單頁，預設 False（不檢查），
    呼叫端要對這頁套用這條規則才傳 True（§20.1 規則 2）。
    """
    problems = []
    if counts["card_count"] > CARD_LIMIT:
        problems.append(
            f"{page_name}：卡片數 {counts['card_count']} 超過上限 {CARD_LIMIT}")
    if check_nav_limit and counts["nav_link_count"] > NAV_LINK_LIMIT:
        problems.append(
            f"{page_name}：導覽連結數 {counts['nav_link_count']} 超過上限 {NAV_LINK_LIMIT}")
    if counts["illegal_detail_count"] > 0:
        problems.append(
            f"{page_name}：有 {counts['illegal_detail_count']} 個非法展開元件"
            "（未使用登記過的 details 樣式）")
    over = [c for c in counts["card_text_counts"] if c > CARD_TEXT_LIMIT]
    if over:
        problems.append(
            f"{page_name}：{len(over)} 張卡片內文字數超過 {CARD_TEXT_LIMIT} 全形字"
            f"（實際：{over}）")
    return problems


def check_file(path, check_nav_limit: bool = False) -> tuple:
    text = Path(path).read_text(encoding="utf-8")
    counts = check_html(text)
    return counts, violations(str(path), counts, check_nav_limit=check_nav_limit)


def main(argv: list | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("用法：python -m app.tools.capacity_check "
              "[--check-nav-limit <頁面路徑>]... <頁面路徑...>")
        return 2

    pages = []
    nav_limit_pages = set()
    i = 0
    while i < len(argv):
        if argv[i] == "--check-nav-limit":
            i += 1
            if i >= len(argv):
                print("用法：--check-nav-limit 後面要接一個頁面路徑")
                return 2
            nav_limit_pages.add(argv[i])
        else:
            pages.append(argv[i])
        i += 1
    if not pages:
        print("用法：python -m app.tools.capacity_check "
              "[--check-nav-limit <頁面路徑>]... <頁面路徑...>")
        return 2

    all_problems = []
    for page in pages:
        counts, problems = check_file(page, check_nav_limit=page in nav_limit_pages)
        print(f"{page}：卡片 {counts['card_count']}／導覽連結 {counts['nav_link_count']}／"
              f"非法展開 {counts['illegal_detail_count']}／單卡文字數 {counts['card_text_counts']}")
        all_problems.extend(problems)
    if all_problems:
        print("違憲（超出 DESIGN.md §20.1 容量上限）：")
        for msg in all_problems:
            print(f"  - {msg}")
        return 1
    print("全部合規。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
