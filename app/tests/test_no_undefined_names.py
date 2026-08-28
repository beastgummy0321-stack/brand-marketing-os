"""靜態掃描：`app/` 底下不得有用到卻沒定義也沒 import 的名字。

由來（2026-08-03）：票 A4 把 `app/main.py` 拆成三份時，`brand_intelligence/routes.py`
用了 `get_operator_name` 與 `_with_brand_names` 兩個函式，卻沒把它們寫進
`from app.shared.web import (...)` 清單。結果四條路由一打開就 500（NameError），
其中 `GET /settings/operator` 是使用者每次設定操作人都會走的路。

Python 是執行到那一行才報 NameError，所以：
- 匯入模組不會爆（`import app.main` 完全正常）
- 967→1167 條測試全綠也照樣漏掉——那四條路由沒有測試覆蓋
- 只有真的用瀏覽器打開那一頁才會發現

這支測試補的就是這個空隙：不執行程式碼，直接讀 AST 比對「用到的名字」與「拿得到的名字」。
它是在拆分後第 3 天由一次瀏覽器實測意外撞出來的，補成自動檢查後就不必再靠運氣
（決策 0031 第 1 條：無檢查不成規則）。
"""

import ast
import builtins
import unittest
from pathlib import Path

_APP = Path(__file__).resolve().parents[1]

# 直譯器在模組層自動提供、AST 裡看不到定義的名字。
_MODULE_DUNDERS = {"__file__", "__name__", "__doc__", "__package__", "__spec__", "__loader__"}


def _undefined_names(tree: ast.AST) -> set:
    """用到（Load）但整份檔案裡從未定義、也沒 import 的名字。

    刻意不做 scope 分析：只要名字在檔案裡任何地方被綁定過就算數。
    這會漏掉「在錯的 scope 用」這種細節，但零誤報——而我們要擋的是
    「整份檔案根本沒有這個名字」這一類，那才是拆檔會犯的錯。
    """
    defined = set(dir(builtins)) | _MODULE_DUNDERS
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                defined.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            defined.add(node.id)
        elif isinstance(node, ast.arg):
            defined.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            defined.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            defined.update(node.names)

    used = {
        node.id for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    return used - defined


class NoUndefinedNamesTest(unittest.TestCase):
    def test_app_modules_have_no_undefined_names(self):
        offenders = {}
        for path in sorted(_APP.rglob("*.py")):
            if "tests" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            missing = _undefined_names(tree)
            if missing:
                offenders[path.relative_to(_APP.parent).as_posix()] = sorted(missing)

        self.assertEqual(
            offenders, {},
            "以下檔案用到了沒有定義也沒有 import 的名字，該路徑一執行就會 NameError：\n"
            + "\n".join(f"  {f} -> {names}" for f, names in offenders.items())
            + "\n（多半是拆檔／搬函式時漏了 import 清單。）",
        )

    def test_detector_actually_detects(self):
        """測試本身要有牙齒：塞一段明顯壞掉的程式碼，掃描器必須抓到。"""
        tree = ast.parse("def f():\n    return helper(1)\n")
        self.assertIn("helper", _undefined_names(tree))


if __name__ == "__main__":
    unittest.main()
