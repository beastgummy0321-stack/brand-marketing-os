# -*- coding: utf-8 -*-
"""app/tests/test_architecture_boundaries.py — A1 三層地界的機器檢查（修憲落地 A2）。

見 docs/architecture-rules.md A1。地界靠讀文件、沒有機器檢查是體檢（19-constitution-audit.md
第七節）點名的致命發現，這裡補上兩道掃描：

1. **import 掃描**：除排除清單外，任何模組不得 import 分支專屬層（`app.ads` 等）。
2. **跨層原生 SQL 掃描**：任何模組不得直接對「品牌永久層」（`app.brand_intelligence`）
   或「分支專屬層」（`app.ads`）的資料表下原生 SQL，必須走該層的公開函式（A1、鐵則 7）。
   實測原有三處偷讀（見 docs/design/19-constitution-audit.md 第七節），先列進
   KNOWN_SQL_VIOLATIONS 讓測試通過——這是明文記錄的欠帳（見 docs/rule-checks.md）。
   修憲落地 A3（`learning_ledger` 遷出 `app/ads` 進品牌永久層）已修好其中一處
   （`app/llm/context_compiler.py`，改走 `repo.list_learnings_for_prompt()`），
   從清單劃掉；`app/ads/interview.py`／`app/intake/ai.py`／`app/intake/state.py`
   三處讀 `strategy_hypothesis`／`brand` 仍是欠帳，留待後續票。

兩道掃描都是靜態文字掃描，不是完整的 SQL parser：只認得出現在原始碼字面裡、緊接在
FROM／INTO／UPDATE／JOIN 後面的表名。用 f-string 動態拼表名可以繞過去——這是刻意
接受的天花板（ponytail: 靜態字面掃描，非 AST-level SQL 解析；真的需要更嚴謹時再升級）。
"""

import ast
import re
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent  # .../app
REPO_ROOT = APP_DIR.parent

# ---- 分支專屬層（A1 表格；未來新分支加進來即可，目前只有 app.ads）----
BRANCH_PACKAGES = ("app.ads",)

# 分支專屬層的資料表清單（來自 app/ads/migrations 的 CREATE TABLE，供跨層 SQL 掃描比對）
BRANCH_TABLES = {
    "activation_authorization", "ad_account", "ad_revenue_coefficient",
    "ad_revenue_coefficient_error_log", "adoption_decision", "brand_checklist_item",
    "campaign_activation", "campaign_cycle", "campaign_cycle_goal", "campaign_cycle_hypothesis",
    "campaign_cycle_product", "campaign_plan", "campaign_plan_option", "creative_brief",
    "creative_rule_card", "creative_variant", "cycle_checklist_item", "cycle_checkpoint",
    "cycle_code_verification", "cycle_voucher_code", "derived_metric", "discovered_campaign",
    "experiment_cell", "external_ad_mapping", "final_asset", "finding", "ga4_summary",
    "ga4_sync_status", "marketing_goal", "offer", "performance_reading",
    "performance_snapshot", "publishing_package", "reading_snapshot", "reading_snapshot_input",
    "recommendation", "rule_dissent", "settlement_version", "success_criterion",
}

# 品牌永久層的資料表清單（來自 app/brand_intelligence/migrations 的 CREATE TABLE）。
# learning_ledger 修憲落地 A3（決策 0037）從 app/ads 遷入——它是品牌長期資產，不是廣告
# 分支專屬的東西，見 architecture-rules.md A1。
BRAND_PERMANENT_TABLES = {
    "brand", "brand_fact", "brand_performance_baseline", "brand_report", "claim",
    "customer_voice", "learning_ledger", "official_asset", "owned_channel", "product",
    "product_economics", "product_fact", "rule", "source_reference", "strategy_hypothesis",
}

_SQL_TABLE_REF = re.compile(r"(?:FROM|INTO|UPDATE|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.IGNORECASE)

# 已知違例（三處偷讀，體檢 19-constitution-audit.md 第七節；狀態見 docs/rule-checks.md）。
# 這份清單本身有 test_known_violations_list_is_not_stale 把關，修好了要記得同步刪除兩邊。
KNOWN_SQL_VIOLATIONS = {
    "app/ads/interview.py": {"strategy_hypothesis"},
    "app/intake/ai.py": {"brand"},
    "app/intake/state.py": {"brand"},
}


# ---- A1 檢查③：套件之間不得形成 import 環 ----
# 環在執行期不一定炸（Python 只在兩個「模組」直接互 import 才會），但它讓「這層依賴那層」
# 這句話失去意義：任一邊都無法單獨抽換或單獨測試，重構時無從下手。
# 既有的環先列進 KNOWN_IMPORT_CYCLES 凍住現況，新增的環當場擋下——比照
# KNOWN_SQL_VIOLATIONS 的欠帳寫法，欠帳明文記錄，但不准再多欠。
# 每一項是「參與環的兩個套件」排序後的 tuple；三個以上的環會拆成多組相鄰對出現。
# 五組全部由同一個成因造成：app.brand_intelligence（品牌永久層）反過來 import 了
# 上層的三個套件。把這三條邊拆掉，五組環會一起消失——解法與代價見 docs/tech-debt.md 第二節。
KNOWN_IMPORT_CYCLES = {
    ("app.brand_intelligence", "app.intake"),   # brand_intelligence/routes.py:40
    ("app.brand_intelligence", "app.llm"),      # report.py:17／customer_voice.py:21／product_ai.py:19
    ("app.brand_intelligence", "app.shared"),   # brand_intelligence/routes.py:41-42
    ("app.intake", "app.llm"),                  # 上面三條的連帶效應，非獨立成因
    ("app.intake", "app.shared"),               # 同上
}

# 只有 app/<套件>/ 底下的檔案算「層」；app/*.py（main.py 組裝根、mock_data.py 共用選項清單）
# 不是層，兩邊都不計入。app/tests 不計入（測試本來就要 import 各層）。
_NON_LAYER_DIRS = {"tests", "templates", "static", "methodology", "__pycache__"}


def _layer_of(dotted_or_rel: str) -> "str | None":
    """'app/llm/methodology.py' 或 'app.llm.methodology' → 'app.llm'；不是層就回 None。"""
    parts = dotted_or_rel.replace("/", ".").split(".")
    if len(parts) < 2 or parts[0] != "app" or parts[1] in _NON_LAYER_DIRS:
        return None
    # 是不是層，看檔案系統上它是不是目錄——不能用名稱長度判斷：
    # `app.llm`（層）與 `app.mock_data`（頂層模組）都只有兩段。
    if not (APP_DIR / parts[1]).is_dir():
        return None
    return f"app.{parts[1]}"


def _import_time_modules(node) -> list:
    """這個節點底下、**import 期真的會執行**的 import 目標模組名。

    只有 import 期執行的 import 會形成硬環——函式／方法內的延遲 import 正是解環的標準手法
    （例：`app/core/settings.py:108` 就刻意這樣寫並留了註解），把它算成硬邊是誤判。
    class 主體會在 import 期執行，所以要進去看；def／async def 不進去。
    """
    found = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(child, ast.Import):
            found.extend(alias.name for alias in child.names)
        elif isinstance(child, ast.ImportFrom) and child.module:
            found.append(child.module)
        else:
            found.extend(_import_time_modules(child))  # if／try／with／class 主體照樣執行
    return found


def _layer_import_graph() -> dict:
    graph: dict = {}
    for path in _iter_py_files():
        src = _layer_of(_rel(path))
        if src is None:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=_rel(path))
        for name in _import_time_modules(tree):
            dst = _layer_of(name)
            if dst is not None and dst != src:
                graph.setdefault(src, set()).add(dst)
    return graph


def _reaches(graph: dict, start: str, target: str) -> bool:
    seen, stack = set(), [start]
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(graph.get(node, ()))
    return False


def _cyclic_pairs(graph: dict) -> set:
    """所有「a import b，而 b 又繞得回 a」的套件對（排序後去重）。"""
    return {
        tuple(sorted((src, dst)))
        for src, dsts in graph.items()
        for dst in dsts
        if _reaches(graph, dst, src)
    }


def _iter_py_files():
    for path in APP_DIR.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        yield path


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()  # 例如 "app/ads/interview.py"


def _owner_module(rel: str) -> str:
    parts = rel.split("/")
    return f"{parts[0]}/{parts[1]}" if len(parts) > 2 else parts[0]


def _is_allowed_branch_importer(rel: str) -> bool:
    """A1 排除清單（永久豁免）：app/main.py 組裝根部分、app/tests/*、app/orders/*、
    app/dashboard/*（票 02：跨品牌總覽要讀檔期狀態，資料只活在 app.ads 層，只能靠
    呼叫該層公開函式取數——見 docs/specs/0001-cockpit-stage0-1.md 接口鐵則）。"""
    if rel == "app/main.py":
        return True
    if rel.startswith("app/tests/"):
        return True
    if rel.startswith("app/orders/"):
        return True
    if rel.startswith("app/dashboard/"):
        return True
    return False


class ImportBoundaryScanTest(unittest.TestCase):
    """A1 檢查①：除排除清單外，任何模組不得 import 分支專屬層。"""

    def test_no_module_imports_branch_exclusive_layer_outside_allowlist(self):
        violations = []
        for path in _iter_py_files():
            rel = _rel(path)
            if rel.startswith("app/ads/"):
                continue  # 分支自己 import 自己不算跨界
            if _is_allowed_branch_importer(rel):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                else:
                    names = []
                for name in names:
                    if any(name == pkg or name.startswith(pkg + ".") for pkg in BRANCH_PACKAGES):
                        violations.append(f"{rel} 竟然 import 了 {name}")
        self.assertEqual(
            violations, [],
            "以下模組 import 了分支專屬層，違反 A1 三層地界（排除清單見 architecture-rules.md）：\n"
            + "\n".join(violations),
        )


class AdsMustNotImportOrdersTest(unittest.TestCase):
    """第 7 刀：app/ads → app/orders 那 9 處呼叫已經拆光，這裡補一條機器閘門把圈鎖死成
    單行道——app/orders 允許 import app.ads（見 `_is_allowed_branch_importer`），反過來
    app/ads import app.orders 一律禁止，不設排除清單，跟上面 `BRANCH_PACKAGES` 的
    import 掃描同一個風格（靜態 AST，只認 import／from...import 語句本身）。"""

    def test_no_ads_module_imports_orders(self):
        violations = []
        for path in _iter_py_files():
            rel = _rel(path)
            if not rel.startswith("app/ads/"):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                else:
                    names = []
                for name in names:
                    if name == "app.orders" or name.startswith("app.orders."):
                        violations.append(f"{rel} 竟然 import 了 {name}")
        self.assertEqual(
            violations, [],
            "以下 app/ads 模組 import 了 app.orders，違反第 7 刀單向依賴（app/orders 允許"
            " import app.ads，反向不行，不設例外——需要訂單資料一律改由呼叫端傳入或由"
            " app/main.py 這個組裝根注入）：\n" + "\n".join(violations),
        )


class CrossLayerRawSqlScanTest(unittest.TestCase):
    """A1 檢查②：跨層一律走公開函式，不得直接對別層的資料表下原生 SQL（鐵則 7）。

    已知三處偷讀在 KNOWN_SQL_VIOLATIONS 裡被明文豁免——這是欠帳，不是允許新增。
    """

    def test_no_undocumented_cross_layer_raw_sql(self):
        violations = []
        for path in _iter_py_files():
            rel = _rel(path)
            if rel.startswith("app/tests/") or rel == "app/main.py":
                continue  # 排除清單同 A1：組裝根部分、測試檔
            owner = _owner_module(rel)
            text = path.read_text(encoding="utf-8")
            tables_hit = {t.lower() for t in _SQL_TABLE_REF.findall(text)}
            known = KNOWN_SQL_VIOLATIONS.get(rel, set())

            if owner != "app/brand_intelligence":
                for table in tables_hit & BRAND_PERMANENT_TABLES - known:
                    violations.append(f"{rel} 直接對品牌永久層資料表 {table} 下 SQL")

            if owner != "app/ads" and not rel.startswith("app/orders/"):
                for table in tables_hit & BRANCH_TABLES - known:
                    violations.append(f"{rel} 直接對分支專屬層資料表 {table} 下 SQL")

        self.assertEqual(
            violations, [],
            "以下模組偷讀了別層的資料表，違反 A1／鐵則 7"
            "（若是刻意的新豁免，先確認過再加進 KNOWN_SQL_VIOLATIONS 並同步 docs/rule-checks.md）：\n"
            + "\n".join(violations),
        )

    def test_known_violations_list_is_not_stale(self):
        """已知違例清單本身要保持真實：清單裡的每一項，檔案裡真的還踩得到那個表。

        避免「以後修好了卻忘記把清單項目刪掉」讓清單變成掩護新違例的死名單。
        """
        for rel, tables in KNOWN_SQL_VIOLATIONS.items():
            path = REPO_ROOT / rel
            self.assertTrue(path.exists(), f"{rel} 已不存在，KNOWN_SQL_VIOLATIONS 該清掉這項了")
            text = path.read_text(encoding="utf-8")
            tables_hit = {t.lower() for t in _SQL_TABLE_REF.findall(text)}
            for table in tables:
                self.assertIn(
                    table, tables_hit,
                    f"{rel} 已經不再對 {table} 下 SQL，KNOWN_SQL_VIOLATIONS 該清掉這項了"
                    "（順手修好了記得同步更新 docs/rule-checks.md）",
                )


_WRITE_SQL_VERB = re.compile(r"\b(INSERT|UPDATE|DELETE)\b", re.IGNORECASE)


class DashboardReadOnlyTest(unittest.TestCase):
    """票 02-overview-cards 驗收條件：dashboard 模組不寫入任何資料表。只讀 JSON API，
    只能靠呼叫別層公開函式取數，本身不得出現任何寫入 SQL 字面。"""

    def test_dashboard_module_has_no_write_sql(self):
        dashboard_dir = APP_DIR / "dashboard"
        self.assertTrue(dashboard_dir.is_dir(), "app/dashboard 尚未建立")
        violations = []
        for path in dashboard_dir.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            if _WRITE_SQL_VERB.search(text):
                violations.append(_rel(path))
        self.assertEqual(
            violations, [],
            "以下 dashboard 模組檔案疑似含寫入 SQL，違反票 02「只讀」鐵則：\n"
            + "\n".join(violations),
        )


class ImportCycleScanTest(unittest.TestCase):
    """A1 檢查③：套件之間不得形成新的 import 環（既有的先凍在 KNOWN_IMPORT_CYCLES）。

    這道掃描補的是 2026-08-07 發現的盲點：`app.llm` 與 `app.brand_intelligence` 互相
    import 已經存在很久，但上面兩道掃描都不看環，所以「測試全綠」在這件事上不代表任何東西。
    """

    def test_no_new_import_cycles_between_layers(self):
        found = _cyclic_pairs(_layer_import_graph())
        new = sorted(found - KNOWN_IMPORT_CYCLES)
        self.assertEqual(
            new, [],
            "以下套件之間新形成了 import 環（a 依賴 b、b 又繞得回 a）。\n"
            "不得自行改依賴方向解環——停下回報（~/.claude/code-rules.md 第三節）：\n"
            + "\n".join(f"  {a} ⇄ {b}" for a, b in new),
        )

    def test_known_import_cycles_list_is_not_stale(self):
        """欠帳清單本身要保持真實：解掉的環要從清單劃掉，否則清單會變成謊言。"""
        found = _cyclic_pairs(_layer_import_graph())
        stale = sorted(KNOWN_IMPORT_CYCLES - found)
        self.assertEqual(
            stale, [],
            "以下環已經不存在，請從 KNOWN_IMPORT_CYCLES 劃掉（並更新 docs/tech-debt.md）：\n"
            + "\n".join(f"  {a} ⇄ {b}" for a, b in stale),
        )


if __name__ == "__main__":
    unittest.main()
