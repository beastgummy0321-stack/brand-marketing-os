# -*- coding: utf-8 -*-
"""app/tools/wording_check.py — 「暫時／本階段／原型階段」用詞檢查（修憲落地 A6，決策 0037 第一節第3點）。

規範文件出現這三個詞時，必須附「結束條件」，否則所有臨時簡化會悄悄變成正式架構
——而且是在沒有人做過那個決定的情況下（決策 0037 的核心發現）。

判定方式（grep 類，不是語意分析器，見 docs/decisions/0037 第 3 條「檢查＝可 grep」）：
一行出現目標詞，且該詞未被「」引號包住（引號內視為引用／定義該詞本身，不是新的豁免宣告），
就檢查它前後一行（含自身，共三行）之內有沒有下列任一「結束條件標記」：
- 「結束」「為止」「才成立」「直到」等字面
- 「決策 0037」等決策編號引用（決策文件被視為結束條件的權威出處）
都沒有就是違例。

掃描範圍限「規範文件」（AGENTS.md／principles／domain／architecture-rules／DESIGN 及其拆出的
`docs/design-spec/*`／rule-checks／decisions/*；UI.md 與 build.md 已於 2026-08-04 歸檔至
`docs/archive/`，不再是規範），不含 `docs/design/`（工作用設計文件，非規範，見 governance.md
對「設計文件目錄」的定性——那份的體檢報告與實作計畫書本身就會大量引用／討論這三個詞，
掃了只會全部誤判成違例）。
"""

import re
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

TARGET_WORDS = re.compile(r"暫時|本階段|原型階段")
END_CONDITION_MARKER = re.compile(r"結束|為止|才成立|直到|決策\s*0\d{3}")
QUOTE_SPAN = re.compile(r"「[^」]*」")

REGULATION_FILES = [
    "AGENTS.md",
    "DESIGN.md",
    "docs/principles.md",
    "docs/domain.md",
    "docs/architecture-rules.md",
    "docs/rule-checks.md",
]


def _decision_files() -> list:
    return sorted(str(p.relative_to(REPO_ROOT)).replace("\\", "/")
                  for p in (REPO_ROOT / "docs" / "decisions").glob("*.md"))


def _design_spec_files() -> list:
    # DESIGN.md 拆出的規格子檔（2026-08-04 文件節食），條文效力同 DESIGN.md，一併掃描。
    return sorted(str(p.relative_to(REPO_ROOT)).replace("\\", "/")
                  for p in (REPO_ROOT / "docs" / "design-spec").glob("*.md"))


def scanned_files() -> list:
    return REGULATION_FILES + _design_spec_files() + _decision_files()


class Violation(NamedTuple):
    file: str
    line: int
    snippet: str


def _quoted(line: str, start: int, end: int) -> bool:
    """match 是否整段落在某個「」引號範圍內（引用該詞本身，不算新的豁免宣告）。"""
    return any(span.start() <= start and end <= span.end()
              for span in QUOTE_SPAN.finditer(line))


def check_file(rel_path: str) -> list:
    """rel_path 可以是相對 REPO_ROOT 的路徑，也可以是絕對路徑（測試用暫存檔）。"""
    path = Path(rel_path)
    if not path.is_absolute():
        path = REPO_ROOT / path
    lines = path.read_text(encoding="utf-8").splitlines()
    violations = []
    for i, line in enumerate(lines):
        for m in TARGET_WORDS.finditer(line):
            if _quoted(line, m.start(), m.end()):
                continue
            window = "\n".join(lines[max(0, i - 1):i + 2])
            if END_CONDITION_MARKER.search(window):
                continue
            violations.append(Violation(rel_path, i + 1, line.strip()[:80]))
            break  # 同一行多次命中只回報一次，行本身就是修正單位
    return violations


def check_all() -> list:
    violations = []
    for rel_path in scanned_files():
        if (REPO_ROOT / rel_path).exists():
            violations.extend(check_file(rel_path))
    return violations


def demo() -> None:
    """python -m app.tools.wording_check — 印出目前全部違例，供人工複查／debt 清單比對。"""
    violations = check_all()
    if not violations:
        print("用詞檢查通過：沒有違例。")
        return
    print(f"共 {len(violations)} 處違例：")
    for v in violations:
        print(f"  {v.file}:{v.line}  {v.snippet}")


if __name__ == "__main__":
    demo()
