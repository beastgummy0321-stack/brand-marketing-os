"""app/tests/test_architecture_boundaries.py — A1 三層地界的機器檢查（修憲落地 A2）。

A1 三層地界：原文件 docs/architecture-rules.md 已被 5eca0db 清除，權威現在是這支檔案本身
（見下方 LAYER_ORDER）。地界靠讀文件、沒有機器檢查曾是致命發現，這裡補上兩道掃描：

1. **import 掃描**：除排除清單外，任何模組不得 import 分支專屬層。
2. **跨層原生 SQL 掃描**：任何模組不得直接對「品牌永久層」（`app.brand_intelligence`）
   或「分支專屬層」的資料表下原生 SQL，必須走該層的公開函式（A1、鐵則 7）。
   實測原有三處偷讀（合憲審查發現，原文件已被 5eca0db 清除），先列進
   KNOWN_SQL_VIOLATIONS 讓測試通過——這是明文記錄的欠帳（狀態就寫在這份清單旁邊）。
   修憲落地 A3（`learning_ledger` 遷出 `app/ads` 進品牌永久層）已修好其中一處
   （`app/llm/context_compiler.py`，改走 `repo.list_learnings_for_prompt()`），
   從清單劃掉；`app/ads/interview.py`／`app/intake/ai.py`／`app/intake/state.py`
   三處讀 `strategy_hypothesis`／`brand` 仍是欠帳，留待後續票。

2026-09-10: the skeleton-slice ratchets (file line cap, module size, test line
ceiling, contract page) were removed with that workflow; the harness plugin's
ARCHITECTURE.md checker owns module boundaries now. What stays here is what the
checker cannot see: raw-SQL layer crossings, tenant-scoped reads, key-source.

兩道 SQL／import 掃描都是靜態文字掃描，不是完整的 SQL parser：只認得出現在原始碼字面裡、緊接在
FROM／INTO／UPDATE／JOIN 後面的表名。用 f-string 動態拼表名可以繞過去——這是刻意
接受的天花板（ponytail: 靜態字面掃描，非 AST-level SQL 解析；真的需要更嚴謹時再升級）。
"""

import ast
import re
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent  # .../app
REPO_ROOT = APP_DIR.parent

# ---- 分支專屬層（A1 表格；未來新分支加進來即可）----
# 外殼切片（2026-08-28）：唯一的分支專屬層（廣告模組）已刪除，這個 tuple 因此是空的，
# 下面的 ImportBoundaryScanTest 現在掃不到任何東西。留著機器與規則，等下一個分支層
# （例如新的部門模組）出現時把套件名填回來即可，不必重寫掃描本身。
BRANCH_PACKAGES: tuple = ()

# 分支專屬層的資料表清單（供跨層 SQL 掃描比對）。外殼切片（2026-08-28）票 3 的 migration
# 已經 DROP 掉這 44 張表（20260828000003_ads_drop_module_tables.sql），沒有表可以偷讀了，
# 所以這個集合是空的。下一個分支層出現時把它的表名填回來即可。
BRANCH_TABLES: set = set()

# 品牌永久層的資料表清單（來自 app/brand_intelligence/migrations 的 CREATE TABLE）。
# learning_ledger 修憲落地 A3（決策 0037）從 app/ads 遷入——它是品牌長期資產，不是廣告
# 分支專屬的東西（原文件 architecture-rules.md A1 已被 5eca0db 清除）。
BRAND_PERMANENT_TABLES = {
    "brand", "brand_fact", "brand_performance_baseline", "brand_report", "claim",
    "customer_voice", "learning_ledger", "official_asset", "owned_channel", "persona", "product",
    "product_economics", "product_fact", "rule", "source_reference", "strategy_hypothesis",
}

_SQL_TABLE_REF = re.compile(r"(?:FROM|INTO|UPDATE|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.IGNORECASE)

# 已知違例（三處偷讀，合憲審查發現，原體檢文件已被 5eca0db 清除；狀態見下方清單）。
# 這份清單本身有 test_known_violations_list_is_not_stale 把關，修好了要記得同步刪除兩邊。
KNOWN_SQL_VIOLATIONS = {
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
KNOWN_IMPORT_CYCLES = set()

# 只有 app/<套件>/ 底下的檔案算「層」；app/*.py（main.py 組裝根等頂層檔案）
# 不是層，兩邊都不計入。app/tests 不計入（測試本來就要 import 各層）。
_NON_LAYER_DIRS = {"tests", "templates", "static", "methodology", "__pycache__"}


def _layer_of(dotted_or_rel: str) -> "str | None":
    """'app/llm/methodology.py' 或 'app.llm.methodology' → 'app.llm'；不是層就回 None。"""
    parts = dotted_or_rel.replace("/", ".").split(".")
    if len(parts) < 2 or parts[0] != "app" or parts[1] in _NON_LAYER_DIRS:
        return None
    # 是不是層，看檔案系統上它是不是目錄——不能用名稱長度判斷：
    # `app.llm`（層）與 `app.main`（頂層模組）都只有兩段。
    if not (APP_DIR / parts[1]).is_dir():
        return None
    return f"app.{parts[1]}"


def _import_time_modules(node) -> list:
    """這個節點底下、**import 期真的會執行**的 import 目標模組名。

    只有 import 期執行的 import 會形成硬環——函式／方法內的延遲 import 正是解環的標準手法
    （例：`app/core/settings.py:108` 就刻意這樣寫並留了註解），把它算成硬邊是誤判。
    class 主體會在 import 期執行，所以要進去看；def／async def 不進去。

    `from X import Y` 回傳 `X.Y` 而不是 `X`，由 `_module_of()` 切。2026-09-04 量到：只回 `X`
    會讓 `from app import storage` 整條邊消失（`X`＝`app`，`_layer_of()` 判 None），
    `app/intake/` 三個檔對 `app.storage` 的依賴在依賴方向與環兩道掃描裡因此都是隱形的。
    """
    found = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(child, ast.Import):
            found.extend(alias.name for alias in child.names)
        elif isinstance(child, ast.ImportFrom) and child.module and child.level == 0:
            found.extend(f"{child.module}.{alias.name}" for alias in child.names)
        else:
            found.extend(_import_time_modules(child))  # if／try／with／class 主體照樣執行
    return found


def _app_modules() -> dict:
    """{'app.llm.gateway': 'app/llm/gateway.py'}。只收層底下的檔，範圍與 `_layer_of()` 一致。"""
    modules = {}
    for path in _iter_py_files():
        rel = _rel(path)
        if _layer_of(rel) is None:
            continue
        dotted = rel[: -len(".py")].replace("/", ".")
        if dotted.endswith(".__init__"):
            dotted = dotted[: -len(".__init__")]
        modules[dotted] = rel
    return modules


def _module_of(name: str, modules: dict) -> "str | None":
    """import 目標名 → 它實際落在哪一個檔＝檔案系統上真的存在的最長前綴。
    `app.core.db.conn` 的 `conn` 是函式，`app.storage` 的 `storage` 是模組，靜態上分不出來，
    只能這樣切。都不存在（第三方套件、stdlib）就回 None。"""
    while name:
        if name in modules:
            return name
        name = name.rpartition(".")[0]
    return None


def _file_import_graph() -> dict:
    """檔案層 import 圖：節點是單一 .py 檔，不是套件。"""
    modules = _app_modules()
    graph: dict = {}
    for dotted, rel in modules.items():
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"), filename=rel)
        for name in _import_time_modules(tree):
            dst = _module_of(name, modules)
            if dst is not None and dst != dotted:
                graph.setdefault(dotted, set()).add(dst)
    return graph


def _layer_import_graph() -> dict:
    """套件層 import 圖＝把檔案層那張圖收合到套件。收合而不是各掃一次：同一份解析結果，
    兩張圖必然一致，不會出現「檔案層看得到、套件層看不到」的漂移。"""
    graph: dict = {}
    for src, dsts in _file_import_graph().items():
        src_layer = _layer_of(src)
        for dst in dsts:
            dst_layer = _layer_of(dst)
            if src_layer is not None and dst_layer is not None and dst_layer != src_layer:
                graph.setdefault(src_layer, set()).add(dst_layer)
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
    """所有「a import b，而 b 又繞得回 a」的節點對（排序後去重）。套件層與檔案層共用。"""
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
    app/dashboard/*（跨層取數只能走該層公開函式——見 docs/specs/0001-cockpit-stage0-1.md
    接口鐵則）。"""
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
            "以下模組 import 了分支專屬層，違反 A1 三層地界（排除清單見 _is_allowed_branch_importer）：\n"
            + "\n".join(violations),
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

            # 分支專屬層的表在外殼切片後沒有擁有者了（`app/ads/` 已刪），這些表本身
            # 在票 3 的 migration 裡 DROP；在那之前仍守著「別的模組不准偷讀」。
            if not rel.startswith("app/orders/"):
                for table in tables_hit & BRANCH_TABLES - known:
                    violations.append(f"{rel} 直接對分支專屬層資料表 {table} 下 SQL")

        self.assertEqual(
            violations, [],
            "以下模組偷讀了別層的資料表，違反 A1／鐵則 7"
            "（若是刻意的新豁免，先確認過再加進 KNOWN_SQL_VIOLATIONS，這份清單就是唯一權威）：\n"
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
                    "（這份清單就是唯一權威，不必再同步別的文件）",
                )


# ---- A1 檢查⑤：讀租戶資料表的函式，函式裡要出現租戶欄位（org_id 或 brand_id）----
# 為什麼是這一條：`test_org_isolation_all_tables.py` 守的是「每張表有沒有 org_id 這個欄位」，
# 那是 schema 層。欄位存在不代表查詢有用它——`SELECT ... FROM x WHERE id = %s` 照樣過那道閘門，
# 而它就是跨租戶讀取的標準長相。這一條補的是查詢層。
#
# 天花板（刻意接受，同本檔開頭那段）：靜態掃描，不是 SQL parser。
# - 粒度是「函式」不是「字串」：SQL 常常先寫基底字串、再依參數 `sql += " AND org_id = %s"`
#   接起來（`app/core/interrupts.py:148` 就是），只看單一字面會把它誤判成違規。
# - 反過來，一個函式裡兩句 SQL、只有一句帶租戶欄位，這道掃描看不出來。它是絆索，不是證明。
_TENANT_CREATE_TABLE = re.compile(
    r"create\s+table\s+(?:if\s+not\s+exists\s+)?([a-zA-Z_][\w]*)\s*\((.*?)\n\s*\)\s*;",
    re.IGNORECASE | re.DOTALL,
)
_TENANT_ORG_COLUMN = re.compile(r"\borg_id\b", re.IGNORECASE)
_TENANT_READ_VERB = re.compile(r"^\s*(SELECT|UPDATE|DELETE)\b", re.IGNORECASE)
_TENANT_READ_TABLE = re.compile(r"\b(?:FROM|JOIN)\s+([a-zA-Z_][\w]*)", re.IGNORECASE)
_TENANT_SCOPE_COLUMN = re.compile(r"\b(org_id|brand_id)\b", re.IGNORECASE)

# 已知違例：函式拿原始 id 取租戶資料，整個函式沒有任何租戶欄位。凍結現況、只准減不准加，
# 寫法比照 KNOWN_SQL_VIOLATIONS。都是「id 由呼叫端給」的形狀——呼叫端若沒先驗過那個 id
# 屬於誰，就是跨租戶讀取。要清掉是去看呼叫端有沒有驗，不是把它們從清單刪掉。
#
# 2026-09-02（票 R4）把每一條的呼叫鏈追到了 HTTP／背景工作進入點，結論寫在這裡而不是票裡，
# 因為票會被刪掉。三條全部「呼叫端有先驗」，所以留在清單裡是正確的——它們不是漏洞，是
# 「這道靜態掃描看不到驗證發生在上一層」。第四條 `intake/repository.py::get_draft_spend`
# 是死碼（零呼叫端），同一次一併刪掉，所以清單少了一項：
#
# - `brand_web/routes_report_api.py::_report_shape`：唯一呼叫端在 routes_report_api.py:116，
#   先過 `require_brand`；讀的 `llm_task_id` 本來就是同一個 brand_id 寫進去的
#   （`report_service.py:47`）。
# - `intake/repository.py::list_llm_cost_items`：約 30 個入口，每一個要嘛帶著已經過
#   `app/shared/web.py:236` `require_brand` 的 brand_id，要嘛帶著剛用 `actor.org_id` 建出來的。
# - `llm/gateway.py::get_task`：`run_task` 內部自己讀自己剛寫的列（id 由 `gateway.py:118`
#   `db.new_id()` 產生，外人換不掉）；`schedule/jobs.py` 那條的 id 凍結自
#   `schedule/routes.py:665` `require_brand` 之後的查詢。
KNOWN_UNSCOPED_TENANT_READS = {
    ("app/brand_web/routes_report_api.py", "_report_shape"),
    ("app/intake/repository.py", "list_llm_cost_items"),
    ("app/llm/gateway.py", "get_task"),
}


def _tenant_tables() -> set:
    """租戶資料表＝migration 的 CREATE TABLE 內文出現 org_id 的那些表。

    從 migration 檔靜態反推，不連資料庫：這道掃描掃的是原始碼，要能在沒有 Postgres 時跑。
    連 DB 的那道是 `test_org_isolation_all_tables.py`，兩者守的不是同一件事。
    """
    tables = set()
    for path in sorted((REPO_ROOT / "supabase" / "migrations").glob("*.sql")):
        for name, body in _TENANT_CREATE_TABLE.findall(path.read_text(encoding="utf-8")):
            if _TENANT_ORG_COLUMN.search(body):
                tables.add(name.lower())
    return tables


def _unscoped_tenant_read_functions() -> set:
    """回傳 {(檔案相對路徑, 函式名)}：函式讀了租戶表，但整個函式沒提到租戶欄位。"""
    tenant = _tenant_tables()
    found = set()
    for path in _iter_py_files():
        rel = _rel(path)
        if rel.startswith("app/tests/"):
            continue
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            reads_tenant = any(
                isinstance(child, ast.Constant)
                and isinstance(child.value, str)
                and _TENANT_READ_VERB.match(child.value)
                and ({t.lower() for t in _TENANT_READ_TABLE.findall(child.value)} & tenant)
                for child in ast.walk(node)
            )
            if not reads_tenant:
                continue
            body = ast.get_source_segment(source, node) or ""
            if not _TENANT_SCOPE_COLUMN.search(body):
                found.add((rel, node.name))
    return found


class UnscopedTenantReadScanTest(unittest.TestCase):
    """讀租戶表的函式必須在函式內出現 org_id 或 brand_id；既有四處凍在清單裡。"""

    def test_no_new_unscoped_tenant_reads(self):
        new = _unscoped_tenant_read_functions() - KNOWN_UNSCOPED_TENANT_READS
        self.assertEqual(
            set(), new,
            "以下函式讀了帶 org_id 的資料表，卻整個函式都沒有租戶欄位——跨租戶讀取的標準長相。"
            "修好它，不要加進 KNOWN_UNSCOPED_TENANT_READS：\n"
            + "\n".join(f"  {rel}::{fn}()" for rel, fn in sorted(new)),
        )

    def test_known_unscoped_list_is_not_stale(self):
        """清單本身要保持真實：修好了要記得刪那一項，否則清單會變成掩護新違例的死名單。"""
        fixed = KNOWN_UNSCOPED_TENANT_READS - _unscoped_tenant_read_functions()
        self.assertEqual(
            set(), fixed,
            "以下項目已經不再違規，KNOWN_UNSCOPED_TENANT_READS 該清掉它們了：\n"
            + "\n".join(f"  {rel}::{fn}()" for rel, fn in sorted(fixed)),
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


class FileImportCycleScanTest(unittest.TestCase):
    """同一件事降到檔案層：`app/x/a.py` 與 `app/x/b.py` 互相 import 是環，但兩個檔在同一個
    套件裡，收合成套件之後那條環會消失——上面那道掃描永遠看不到它。

    2026-09-04 量過：整個 `app/` 檔案層違規數是 0（T5 拆 `routes.py` 時連帶解掉了），
    所以這裡不開欠帳清單——沒有債要凍，先開一個空 set 只會變成下次有人偷渡的入口。
    """

    def test_no_import_cycles_between_files(self):
        found = sorted(_cyclic_pairs(_file_import_graph()))
        self.assertEqual(
            found, [],
            "以下檔案之間形成了 import 環（a 依賴 b、b 又繞得回 a）。\n"
            "不得自行改依賴方向解環——停下回報：\n"
            + "\n".join(f"  {a} ⇄ {b}" for a, b in found),
        )


# ---- A1 檢查④：依賴方向（誰可以 import 誰）----
# 層級定義原本在 docs/architecture-rules.md，該檔已被 5eca0db「乾淨重啟」清除。
# 重建成這張表而不是重寫一份文件：文件會腐爛、沒人讀，這張表每次跑測試都會執行。
# 規則：只准依賴排在自己前面的層。順序由現況推導——這是唯一一種讓違規數收斂到
# 「只剩 brand_intelligence 那三條」的排法，其餘七個套件零違規。
LAYER_ORDER = [
    "app.core",                # 基礎設施：DB、migration、audit、interrupts
    "app.background",          # 票 schedule-01：procrastinate App，只依賴 app.core（db.dsn()）
    "app.storage",             # 票 storage-01：Supabase Storage 四函式，只依賴 stdlib／httpx／
                                # 環境變數，不依賴任何租戶模組（比照 app.background，ADR 0038
                                # 先例）
    "app.brand_intelligence",  # 品牌永久層
    "app.llm",                 # AI gateway 與 prompt 組裝
    "app.shared",              # web 骨架（app、templates、共用 ctx）
    "app.identity",            # 票 03-1：身分／租戶（JWT、org 解析），依賴 app.shared 的
                                # ApiError／conn；app.shared 對它的依賴是函式內延遲 import
                                # （見 require_actor()），這裡的靜態掃描看不到，不算環
    "app.meta",                # 票 04：Meta 廣告帳戶連接（Graph API、Vault 權杖），依賴
                                # app.core 與 app.shared；票 11 起 app.schedule 依賴它讀
                                # meta_entity_spend（比照既有的 app.dashboard 依賴方向）
    "app.orders",              # 訂單，只依賴 app.brand_intelligence／app.core／app.shared
                                # （docs/contracts/schedule.md）——挪到這裡，讓它排在
                                # app.schedule 前面
    "app.workbench",           # 票 workbench/02（ADR 0068 §2）：只依賴上面幾層，排在
                                # app.schedule 前面——契約單向 schedule -> workbench。
    "app.ads",                 # 投放中心，只依賴 app.core／app.shared，其餘走 legacy facade
                                # （app.meta／app.brand_intelligence）；排在 app.schedule 前面
                                # 是因為 ARCHITECTURE.md §2 規定 ads 不得 import app.schedule，
                                # 這個順位讓那條規則被測試守住（manifest 的 may_depend_on 只有
                                # workbench，而 workbench 已排在前面）
    "app.schedule",            # 票 07：檔期規劃最薄路徑，依賴 app.core／app.llm／app.shared／
                                # app.brand_intelligence／app.meta；票 T2b（ADR 0053，
                                # docs/contracts/schedule.md 2026-09-02）起也依賴
                                # app.orders.repository（結算讀全通路營收）——contract 只多
                                # 授權這一個依賴，所以只把 app.orders 挪到它前面，不整段挪到
                                # app.intake／app.brand_web 後面：這個順位不准 app.schedule
                                # 依賴 app.intake 或 app.brand_web，contract 沒授權的依賴，
                                # 這張表也不授權
    "app.intake",              # 建檔精靈
    "app.brand_web",           # 品牌智庫 web 路由
    "app.dashboard",           # 駕駛艙（只讀，跨分支彙總）
    "app.tools",               # 一次性工具
]

# 既有的反向依賴（欠帳，不准再多欠）。三條全部出自品牌永久層反過來依賴上層，
# 也正是 KNOWN_IMPORT_CYCLES 五組環的根源——解掉這三條，兩張清單一起清空。
KNOWN_LAYER_VIOLATIONS = set()


class LayerDirectionTest(unittest.TestCase):
    """A1 檢查④：只准依賴排在 LAYER_ORDER 前面的層。

    與 ImportCycleScanTest 的分工：環是客觀事實（不管誰怎麼排都是環），這張表是
    我們選的方向。兩者都留——有人日後改了 LAYER_ORDER 的排法，環那道仍然守得住底線。
    """

    def _violations(self) -> set:
        rank = {layer: i for i, layer in enumerate(LAYER_ORDER)}
        graph = _layer_import_graph()
        unknown = (set(graph) | {d for ds in graph.values() for d in ds}) - set(rank)
        self.assertEqual(unknown, set(), f"這些套件不在 LAYER_ORDER 裡，請先決定它的位置：{unknown}")
        return {(src, dst) for src, dsts in graph.items() for dst in dsts
                if rank[dst] > rank[src]}

    def test_no_new_upward_dependency(self):
        new = sorted(self._violations() - KNOWN_LAYER_VIOLATIONS)
        self.assertEqual(
            new, [],
            "以下依賴方向反了（只准依賴 LAYER_ORDER 排在自己前面的層）。\n"
            "不得自行改依賴方向或調整 LAYER_ORDER 來讓測試變綠——停下回報：\n"
            + "\n".join(f"  {a} → {b}" for a, b in new),
        )

    def test_known_layer_violations_list_is_not_stale(self):
        stale = sorted(KNOWN_LAYER_VIOLATIONS - self._violations())
        self.assertEqual(
            stale, [],
            "以下反向依賴已經解掉，請從 KNOWN_LAYER_VIOLATIONS 劃掉並更新 docs/tech-debt.md：\n"
            + "\n".join(f"  {a} → {b}" for a, b in stale),
        )


# ---- 票 04-1a（D4-3）：誰的金鑰付錢，只准 app/core/settings.py 一個檔案知道 ----
# 日後開放第三個 key source（付費層自帶端點等）時，只改這一個檔案就要能做到——這兩道
# 掃描把「不准」的部分機器化，不靠人工複查 code review。

_AI_KEY_SOURCE_ENV_VAR_PATTERN = re.compile(r"ANTHROPIC_API_KEY")
_AI_KEY_SOURCE_ONLY_FILE = "app/core/settings.py"

# source 變數（或 .source 屬性）直接跟 'platform'／'own' 字面值比較——這是「呼叫端自己
# 判斷該用哪個分支」的訊號。單純出現 "platform"／"own" 這兩個英文字不算（app/ads 等模組
# 拿它們當廣告平台、法規來源分類用，見既有 app/ads/compliance.py、routes_claims_api.py），
# 只掃「跟 source 做字面比較」這個精確樣式，不是任何出現這兩個字的地方。
_SOURCE_BRANCH_PATTERN = re.compile(
    r"""source\s*==\s*['"](?:platform|own)['"]|['"](?:platform|own)['"]\s*==\s*source"""
)


class AiKeySourceSingleSourceOfTruthTest(unittest.TestCase):
    """票 04-1a：`resolve_ai_credentials()` 是唯一知道「誰的金鑰付錢」的地方。

    兩道掃描對齊 ticket 04-1a-ai-money-gate.md 驗收條件 8：
    1. `ANTHROPIC_API_KEY`（環境變數名）只准出現在 app/core/settings.py——別的模組
       一律問 resolve_ai_credentials()／get_api_key()，不准自己讀環境變數。
    2. 對 `source`（AiCredentials.source）的值做 'platform'／'own' 字面比較，只准出現在
       app/core/settings.py——加第三個 tier 時只改這一個檔案，呼叫端不必跟著改。
    """

    def test_only_settings_module_reads_the_anthropic_env_var_name(self):
        violations = []
        for path in _iter_py_files():
            rel = _rel(path)
            if rel == _AI_KEY_SOURCE_ONLY_FILE or rel.startswith("app/tests/"):
                continue
            text = path.read_text(encoding="utf-8")
            if _AI_KEY_SOURCE_ENV_VAR_PATTERN.search(text):
                violations.append(rel)
        self.assertEqual(
            violations, [],
            "以下檔案直接出現 ANTHROPIC_API_KEY 這個環境變數名，違反票 04-1a「只有一個地方"
            "知道操作者的金鑰放哪裡」——一律改問 app.core.settings.get_api_key()／"
            "resolve_ai_credentials()：\n" + "\n".join(violations),
        )

    def test_only_settings_module_branches_on_ai_key_source(self):
        violations = []
        for path in _iter_py_files():
            rel = _rel(path)
            if rel == _AI_KEY_SOURCE_ONLY_FILE or rel.startswith("app/tests/"):
                continue
            text = path.read_text(encoding="utf-8")
            if _SOURCE_BRANCH_PATTERN.search(text):
                violations.append(rel)
        self.assertEqual(
            violations, [],
            "以下檔案對 source 的值做 'platform'／'own' 字面比較，違反票 04-1a「誰付錢的"
            "分流只准在 resolve_ai_credentials() 一個地方」——呼叫端只能問 resolver 拿"
            "AiCredentials，不准自己判斷 source 的字面值：\n" + "\n".join(violations),
        )


# ---- 票 T8a：七維座標詞彙同步閘門 ----
# 七個維度名稱（CONSTITUTION.md 規則 5）活在三個地方——`app/schedule/creative.py` 的
# `COORDINATE_KEYS`（唯一權威）、`frontend/src/lib/coordinatesApi.ts` 的
# `COORDINATE_DIMENSIONS`、`frontend/src/components/schedule/CampaignTree.tsx` 的
# `COORDINATE_LABELS`——過去沒有任何機器比對過三邊是否一致。跟 `_tenant_tables()`／
# `AiKeySourceSingleSourceOfTruthTest` 同一種既有天花板：純文字 regex 掃描，不接 TS
# parser（`app/tests` 不能 import 前端，repo 裡也沒有能解析 TypeScript 的依賴——
# ponytail：正則字面比對，真的需要更嚴謹時再升級）。

_PY_COORDINATE_KEYS = re.compile(r"COORDINATE_KEYS\s*=\s*\(([^)]*)\)")
_TS_COORDINATE_DIMENSIONS_BLOCK = re.compile(
    r"COORDINATE_DIMENSIONS\s*:[^=]*=\s*\[(.*?)\n\];", re.DOTALL
)
_TS_COORDINATE_LABELS_BLOCK = re.compile(
    r"COORDINATE_LABELS\s*:[^=]*=\s*\[(.*?)\n\];", re.DOTALL
)
_TS_TUPLE_FIRST_KEY = re.compile(r'\["([a-z_]+)",')

# 憲法規則 5 逐字抄下來的那七個，順序照抄。這是權威，不是「其中一份原始碼」——
# 2026-09-04 補：原本三份只互相比對，於是三份同時清空也會全綠（空清單彼此相等）。
# 拿一份文件當基準才有底線可言，而這七個字在 CONSTITUTION.md 有明文出處，不是這裡編的。
CONSTITUTION_COORDINATE_KEYS = [
    "audience", "pain", "angle", "hook", "proof", "offer", "format",
]


class CoordinateDimensionSyncTest(unittest.TestCase):
    """票 T8a：三邊的七個維度鍵名跟順序要一致，而且都等於憲法規則 5 那七個。
    全部當純文字讀，不執行、不 import（TS 那兩份是前端程式碼，這支測試檔跑在 Python 這邊）。

    2026-09-04 補強：本測試原本只找「第一個同名宣告」，T8a 的審查因此騙過它——在真正的
    `export const COORDINATE_DIMENSIONS` 前面插一個同名、七鍵正確的假宣告（合法 TS，不同
    作用域），再把真的那份弄壞，閘門全綠。現在改成「同名宣告只准有一個」，那一招當場紅。
    這仍然不是 TS parser（票面禁裝，也沒有這個依賴），但它擋掉的不再只是手滑。
    """

    def _one_declaration(self, text: str, pattern: re.Pattern, rel: str, const_name: str):
        """整份檔案裡這個名字只准宣告一次。多一個＝有人放了誘餌，少一個＝名字被改掉了。"""
        matches = list(pattern.finditer(text))
        self.assertEqual(
            len(matches), 1,
            f"{rel} 裡 {const_name} 的宣告有 {len(matches)} 份，只准有 1 份。\n"
            "兩份以上：純文字掃描只會讀到第一份，第二份改壞了也不會紅——這正是 2026-09-04 "
            "審查騙過這道閘門的手法。零份：名字被改掉或刪掉了。",
        )
        return matches[0]

    def _python_keys(self) -> list:
        rel = "app/schedule/creative.py"
        text = (APP_DIR / "schedule" / "creative.py").read_text(encoding="utf-8")
        match = self._one_declaration(text, _PY_COORDINATE_KEYS, rel, "COORDINATE_KEYS")
        return re.findall(r'"([a-z_]+)"', match.group(1))

    def _ts_keys(self, rel: str, block_pattern: re.Pattern, const_name: str) -> list:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        match = self._one_declaration(text, block_pattern, rel, const_name)
        return _TS_TUPLE_FIRST_KEY.findall(match.group(1))

    def test_all_three_equal_the_constitution(self):
        """三份都要等於憲法那七個。少了這條，三份同時被清空或同時被改錯也會全綠。"""
        for label, keys in (
            ("app/schedule/creative.py COORDINATE_KEYS", self._python_keys()),
            ("frontend/src/lib/coordinatesApi.ts COORDINATE_DIMENSIONS", self._ts_keys(
                "frontend/src/lib/coordinatesApi.ts",
                _TS_COORDINATE_DIMENSIONS_BLOCK, "COORDINATE_DIMENSIONS")),
        ):
            self.assertEqual(
                keys, CONSTITUTION_COORDINATE_KEYS,
                f"{label} 跟 CONSTITUTION.md 規則 5 的七維對不上（鍵名或順序）：\n"
                f"  這裡: {keys}\n  憲法: {CONSTITUTION_COORDINATE_KEYS}",
            )

    def test_seven_dimension_keys_agree_python_and_typescript(self):
        python_keys = self._python_keys()
        coordinates_api_keys = self._ts_keys(
            "frontend/src/lib/coordinatesApi.ts",
            _TS_COORDINATE_DIMENSIONS_BLOCK, "COORDINATE_DIMENSIONS",
        )
        self.assertEqual(
            python_keys, coordinates_api_keys,
            "COORDINATE_KEYS（app/schedule/creative.py）跟 COORDINATE_DIMENSIONS"
            "（frontend/src/lib/coordinatesApi.ts）的七個鍵名或順序對不上：\n"
            f"  python: {python_keys}\n  coordinatesApi.ts: {coordinates_api_keys}",
        )
        # 票 past-ads/08（2026-09-09，主對話台裁決）：CampaignTree.tsx 不再有自己那份
        # COORDINATE_LABELS——七維標籤只准有一個前端來源（coordinatesApi.ts 的
        # COORDINATE_DIMENSIONS）。這條檢查仍然有效：檔案不准再長出自己的座標標籤字典。
        #
        # 票 05（ADR 0068，2026-09-09）amendment：per-ad 座標畫面（曾經讀 `COORDINATE_
        # DIMENSIONS` 逐格印出）搬去素材工作檯——`ScheduleBrief.copy` 這個新形狀本來就不帶
        # 座標值（app/schedule/state.py `_copy_summary`），CampaignTree.tsx 因此不再需要、
        # 也不再 import 那個常數；留著會是一個沒有使用者的 import（tsc/eslint 會紅）。原本
        # 「必須 import COORDINATE_DIMENSIONS」那條斷言跟著這個畫面一起退休，上面「不准自己
        # 定義 COORDINATE_LABELS」那條閘門原樣保留（不管座標畫在哪裡，都不准另開一份詞彙）。
        tree_text = (REPO_ROOT / "frontend/src/components/schedule/CampaignTree.tsx").read_text(
            encoding="utf-8")
        self.assertEqual(
            len(list(_TS_COORDINATE_LABELS_BLOCK.finditer(tree_text))), 0,
            "CampaignTree.tsx 又長出自己的 COORDINATE_LABELS——七維標籤只准有一個前端來源"
            "（coordinatesApi.ts 的 COORDINATE_DIMENSIONS，票 past-ads/08）。",
        )
