# -*- coding: utf-8 -*-
"""app/tools/dead_css_check.py — 死碼掃描：抓 `app/static/app.css` 定義了、但全庫模板
（`app/templates/**/*.html`）與 Python 原始碼（`app/**/*.py`）都沒有引用的 class
（修憲落地 V7，決策 0031 第 1 條「無檢查不成規則」：這條規則要留下可執行檢查）。

判法：
1. 從 app.css 逐行選取器抓出所有 `.class-name` 定義（忽略註解、`:hover` 這類虛擬類別
   不當成 class）。
2. 把全部模板與 Python 檔案內容併成一份大字串當「有沒有用到」的依據——只要 class 名稱
   整串字面出現在任何模板或 Python 原始碼裡（不管是不是在 `class="..."` 屬性裡），
   就算有用到。
3. **動態組名排除**：像 `class="badge badge-{{ kind }}"` 這種前綴＋Jinja 變數組出來的
   class，原始碼裡不會出現完整字面（例如 `badge-warn`）。掃描階段先從所有 `class="..."`
   屬性值裡，抓出「前綴後面接 `{{` 或 `~` 字串串接」的寫法，取前綴當白名單——任何 CSS
   class 只要以「白名單前綴 + `-`」開頭，一律視為有用到，不列入死碼候選。

只掃出候選清單，**不自動刪除**——動態前綴偵測是啟發式，可能有漏網或誤判，最終要不要刪
由人審過再動手（票面規則：列出來、逐一確認後刪除）。
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CSS_PATH = REPO_ROOT / "app" / "static" / "app.css"
TEMPLATE_DIR = REPO_ROOT / "app" / "templates"
APP_DIR = REPO_ROOT / "app"

_CLASS_SELECTOR_RE = re.compile(r"\.([a-zA-Z][a-zA-Z0-9_-]*)")
_CLASS_ATTR_RE = re.compile(r'class\s*=\s*["\']([^"\']*)["\']', re.S)
_DYNAMIC_PREFIX_RE = re.compile(
    r"([a-zA-Z][a-zA-Z0-9_-]*?)-(?:\{\{|['\"]\s*[~+])"
)


def defined_classes() -> set:
    """回傳 app.css 裡所有選取器出現過的 class 名稱（不含虛擬類別／虛擬元素）。"""
    text = CSS_PATH.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)  # 去註解，避免註解裡的範例名混入
    classes = set()
    for line in text.splitlines():
        selector_part = line.split("{", 1)[0]
        if "@media" in selector_part or "@keyframes" in selector_part:
            continue
        for m in _CLASS_SELECTOR_RE.finditer(selector_part):
            classes.add(m.group(1))
    return classes


def _source_files():
    """模板全掃；Python 只掃正式程式碼，排除 `app/tests/`——測試裡常見
    `assertNotIn('class="xxx"', ...)` 這種斷言「不該出現」的寫法，字面上會包含
    class 名稱，若也算進「有用到」，會把真正死掉的 class 誤判成還活著。"""
    yield from TEMPLATE_DIR.rglob("*.html")
    for p in APP_DIR.rglob("*.py"):
        if "tests" not in p.relative_to(APP_DIR).parts:
            yield p


def _read_all() -> str:
    parts = []
    for p in _source_files():
        parts.append(p.read_text(encoding="utf-8"))
    return "\n".join(parts)


def dynamic_prefixes(haystack: str) -> set:
    """從所有 class 屬性值裡抓出「前綴 + 動態片段」的前綴集合（見模組說明第 3 點）。"""
    prefixes = set()
    for attr_val in _CLASS_ATTR_RE.findall(haystack):
        for m in _DYNAMIC_PREFIX_RE.finditer(attr_val):
            prefixes.add(m.group(1))
    return prefixes


def find_dead_classes() -> list:
    """回傳排序後的死碼候選 class 名稱清單。"""
    defined = defined_classes()
    haystack = _read_all()
    prefixes = dynamic_prefixes(haystack)
    dead = []
    for cls in sorted(defined):
        if any(cls == p or cls.startswith(p + "-") for p in prefixes):
            continue
        if re.search(r"(?<![\w-])" + re.escape(cls) + r"(?![\w-])", haystack):
            continue
        dead.append(cls)
    return dead


def main() -> int:
    dead = find_dead_classes()
    if not dead:
        print("沒有找到死碼 class。")
        return 0
    print(f"候選死碼 class（共 {len(dead)} 個，動態組名前綴已排除，人工確認後再刪）：")
    for cls in dead:
        print(f"  - .{cls}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
