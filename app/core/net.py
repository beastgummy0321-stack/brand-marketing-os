"""app/core/net.py — 讀一個網址、抽出純文字節錄。

原本住在 `app/intake/ai.py`，只有建檔精靈在用；產品調研搬去 `brand_intelligence`
之後變成兩邊共用，放在最底層的 core（core 不 import 任何其他 app 模組），
兩邊都拿得到，也不會生出模組間的回頭依賴。

呼叫端一律 `fetch_url = net.fetch_url` 綁成自己模組的名字，測試才能各自換掉
（見 app/tests/test_intake.py、test_product_scan.py）。
"""

import html.parser
import urllib.request

URL_FETCH_TIMEOUT_S = 10
URL_EXCERPT_CHARS = 3000


class _TextExtractor(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.chunks = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.chunks.append(data.strip())


def fetch_url(url: str) -> tuple:
    """讀一個網址，回 (ok, 純文字節錄)。讀不到只回 (False, "")——不存狀態碼、
    不存例外訊息（§19.2(b) 優雅缺席）。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (BrandOS intake)"})
        with urllib.request.urlopen(req, timeout=URL_FETCH_TIMEOUT_S) as resp:
            raw = resp.read(500_000).decode("utf-8", errors="replace")
    except Exception:
        return False, ""
    extractor = _TextExtractor()
    try:
        extractor.feed(raw)
        text = " ".join(extractor.chunks)
    except Exception:
        text = raw
    return True, text[:URL_EXCERPT_CHARS]


def fetch_raw_html(url: str) -> tuple:
    """讀一個網址，回 (ok, 原始 HTML)——不濾 script／style。追蹤碼健檢（app/ads/tracking.py）
    要在原始碼裡找 <script src="..."> 這類特徵字串，fetch_url() 的純文字節錄會把 script
    內容整段濾掉，兩支用途不同、不能共用一支。讀不到只回 (False, "")，同 fetch_url 的
    優雅缺席寫法（不存狀態碼、不存例外訊息）。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (BrandOS intake)"})
        with urllib.request.urlopen(req, timeout=URL_FETCH_TIMEOUT_S) as resp:
            return True, resp.read(500_000).decode("utf-8", errors="replace")
    except Exception:
        return False, ""
