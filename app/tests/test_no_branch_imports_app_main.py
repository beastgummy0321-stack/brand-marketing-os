# -*- coding: utf-8 -*-
"""app/tests/test_no_branch_imports_app_main.py — 修憲落地 A4 的機器檢查。

見票 A4：`app/main.py` 原本頂著「組裝根永久豁免」的身分塞了 87 條業務路由，
卻被 `app/ads/routes.py`、`app/orders/routes.py`、`app/intake/routes.py`、
`app/intake/state.py` 反向 import（存在 main → ads.routes → main 的循環）。

拆成 app/main.py（組裝根）／app/shared/web.py（共用 web 工具）／
app/brand_intelligence/routes.py（業務路由）之後，分支專屬層一律只單向依賴
app.shared.web，不再 import app.main——這裡把「無反向 import」釘成機器檢查，
之後有人手滑加回去，這個測試會抓到。

靜態 AST 掃描（跟 test_architecture_boundaries.py 同一套手法）：不只看
module-level import，也看函式內的延遲 import（`ast.walk` 會走到巢狀節點），
因為 app/intake/state.py 原本就是在函式內動態 import app.main 繞開循環——
這正是本檢查要防的手法本身，不能只查檔頭。
"""

import ast
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent  # .../app
REPO_ROOT = APP_DIR.parent

# 分支專屬層＋建檔精靈（issue #A4：這四個模組是體檢點名的反向 import 現行犯）。
CHECKED_PACKAGES = ("app/ads", "app/orders", "app/intake")


def _iter_py_files_under(rel_prefix: str):
    for path in (REPO_ROOT / rel_prefix).rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        yield path


class NoBranchImportsAppMainTest(unittest.TestCase):
    """驗收條件：app/ads、app/orders、app/intake 底下的模組不得 import app.main。"""

    def test_no_module_under_branches_imports_app_main(self):
        violations = []
        for prefix in CHECKED_PACKAGES:
            for path in _iter_py_files_under(prefix):
                rel = path.relative_to(REPO_ROOT).as_posix()
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        names = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        names = [node.module]
                    else:
                        names = []
                    for name in names:
                        if name == "app.main" or name.startswith("app.main."):
                            violations.append(f"{rel} 竟然 import 了 {name}")
        self.assertEqual(
            violations, [],
            "以下模組 import 了 app.main，違反修憲落地 A4（分支只能單向依賴 "
            "app.shared.web，不得反向依賴組裝根，見 docs/decisions/0037）：\n"
            + "\n".join(violations),
        )


if __name__ == "__main__":
    unittest.main()
