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

外殼切片（2026-08-29）票 shell-06 再補兩道**量**的閘門（`TestRatioTest`、
`ModuleSizeRatchetTest`，見檔案後段）：既有三道全都在看耦合與單檔大小，沒有一道在看
「一個模組總共長到幾行」——`app/ads/` 長到 21,595 行的過程中它們一次都沒紅過。

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


# ---- A1 檢查⑤：單檔行數只准變小 ----
# CLAUDE.md：單檔超過 800 行即為待拆，不得再往裡面加新功能。原本只是一句話沒有閘門，
# 2026-08-07 票 C 就在 routes.py 加了 48 行淨成長。凍住現況：超標檔只准變小。
# ponytail: 只鎖「不得超過歷史最大值」，縮小後不強制回來調低數字（每次縮都要改常數是白工）。
# 真的需要單向棘輪時再升級。
FILE_LINE_CAP = 800
KNOWN_OVERSIZED_FILES = {
    "app/brand_intelligence/repository.py": 1667,
}


class FileLineCapTest(unittest.TestCase):
    """A1 檢查⑤：沒有新的超標檔，既有超標檔不得再變大。

    CLAUDE.md「Tests」節：「800 行上限不適用於 `app/tests/`」——這條原本只是一句話沒有
    閘門守，`_iter_py_files()` 掃到的又是全 app/ 樹（含 app/tests/），02-4 逐一碰過
    174 個測試檔後第一次真的撞到這個落差（先前從沒有任何測試檔超過 800 行，這條路徑
    沒被走過）。這裡把已經寫死在 CLAUDE.md 的決定接到閘門上，不是本票另開的新決定。"""

    def _line_counts(self) -> dict:
        return {_rel(p): len(p.read_text(encoding="utf-8").splitlines())
                for p in _iter_py_files() if "app/tests/" not in _rel(p)}

    def test_no_file_grows_past_its_frozen_size(self):
        problems = []
        for rel, count in sorted(self._line_counts().items()):
            if count <= FILE_LINE_CAP:
                continue
            frozen = KNOWN_OVERSIZED_FILES.get(rel)
            if frozen is None:
                problems.append(f"  {rel}：{count} 行，超過 {FILE_LINE_CAP} 行上限——這是警報不是命令：先問這個檔該裝什麼、每個函式去哪、哪些碰錢，答案是一張模組邊界票，不是搬走最小的那個函式")
            elif count > frozen:
                problems.append(f"  {rel}：{count} 行，比凍結值 {frozen} 大——只准變小")
        self.assertEqual(problems, [], "單檔行數違規：\n" + "\n".join(problems))

    def test_known_oversized_list_is_not_stale(self):
        counts = self._line_counts()
        stale = sorted(rel for rel in KNOWN_OVERSIZED_FILES
                       if counts.get(rel, 0) <= FILE_LINE_CAP)
        self.assertEqual(
            stale, [],
            "以下檔案已經拆到上限以下，請從 KNOWN_OVERSIZED_FILES 劃掉並更新 docs/tech-debt.md：\n"
            + "\n".join(f"  {rel}" for rel in stale),
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
            ("frontend/src/components/schedule/CampaignTree.tsx COORDINATE_LABELS",
             self._ts_keys("frontend/src/components/schedule/CampaignTree.tsx",
                           _TS_COORDINATE_LABELS_BLOCK, "COORDINATE_LABELS")),
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
        campaign_tree_keys = self._ts_keys(
            "frontend/src/components/schedule/CampaignTree.tsx",
            _TS_COORDINATE_LABELS_BLOCK, "COORDINATE_LABELS",
        )
        self.assertEqual(
            python_keys, coordinates_api_keys,
            "COORDINATE_KEYS（app/schedule/creative.py）跟 COORDINATE_DIMENSIONS"
            "（frontend/src/lib/coordinatesApi.ts）的七個鍵名或順序對不上：\n"
            f"  python: {python_keys}\n  coordinatesApi.ts: {coordinates_api_keys}",
        )
        self.assertEqual(
            python_keys, campaign_tree_keys,
            "COORDINATE_KEYS（app/schedule/creative.py）跟 COORDINATE_LABELS"
            "（frontend/src/components/schedule/CampaignTree.tsx）的七個鍵名或順序對不上：\n"
            f"  python: {python_keys}\n  CampaignTree.tsx: {campaign_tree_keys}",
        )


# ---------------------------------------------------------------------------
# A1 檢查⑥⑦：量。票 shell-06（HANDOFF-shell-slice.md §4）。
#
# 為什麼要有這兩道：`app/ads/` 長到 21,595 行的過程中，既有三道閘門**一次都沒有紅過**——
# `FileLineCapTest` 管單檔 800 行（那些行攤在幾十個檔裡，每個都在 800 以下），
# `LayerDirectionTest`／`ImportCycleScanTest` 管耦合不管體積（廣告的耦合一直很乾淨）。
# 三道都沒錯，只是都沒在看「量」。下面兩道補這一格。
#
# **誠實的天花板**：這兩道抓不到真正的病因（為沒人跑過的系統寫猜出來的門檻），買到的是
# 早 10 倍的警報，不是解藥。完整說明見 `docs/tech-debt.md` 開頭。
# ---------------------------------------------------------------------------

# 2026-08-30 使用者裁決（ADR 0041）：這道閘門從「比值」改成「測試絕對行數」。
#
# 原本量的是 tests/production 的比值，凍結在 0.858，只准往下。它在同一天被迫往上調了
# 兩次（0.858 → 0.862 → 0.865），兩次都不是因為有人多寫測試，而是因為**刪掉了死程式碼**
# ——分母變小，比值就漲。也就是說：這道閘門在懲罰「刪碼」這件我們最想做的事，而唯一能讓
# 它變綠的動作就是調高它自己。一道只能靠調鬆自己來通過的閘門，不是閘門。
#
# 改成量測試的絕對行數之後，因果就對了：刪 production 不影響這個數字（本來就不該紅），
# 加測試才會紅。要加測試就改這一行、寫理由，reviewer 在 diff 裡看得到——完全比照下面
# KNOWN_MODULE_SIZES 已經在用的機制（「允許調高，但必須改這張表」）。
#
# 比值本身沒有消失，只是降級成參考值：失敗訊息裡照印，目標仍是 0.7×
# （全域 CLAUDE.md）。它現在是北極星，不是煞車。
#
# 凍結於 2026-08-30 核准票（fdf619a）落地後的實測值 14,300，**加上改寫這道閘門自己花掉的
# 5 行**（比值版 14,300 → 絕對行數版 14,305；本檔自己的行數也算進去，所以改閘門就會動到它
# 守的數字——這裡照實記，不藏）。
#
# 2026-08-30 核准票 scope_ref 修正：14,305 → 14,317（含本段註解與 KNOWN_MODULE_SIZES 那筆理由自己佔掉的行）。這次是**真的多寫了 4 行測試**，不是
# 刪碼造成的被動漲——`test_approval.py` 加了一條斷言，釘住「`scope_ref` 存的是被核准那棵樹
# 的 id，不是品牌 id」。它守的是資料正確性（事後查得回去「當初簽的是哪一棵」），屬於
# 全域 CLAUDE.md 測試四類允許的四類之一。先證過紅：把 scope_ref 改回 brand_id，
# 這條斷言就抓到（`'brd_…' != 'llm_…'`）。這正是 ADR 0041 說的「該漲就改這一行、寫理由」。
#
# 2026-08-30 票 04-1b 組織時區：14,317 → 14,410（含本段註解自己佔掉的行）。新增兩支：
# `test_meta_daily_spend.py::SpendDateFollowsOrgTimezoneTest`（相差 26 小時的兩個組織，
# 同一次拉取必須記在不同的 `spend_date`）與 `test_org_timezone.py`（時區設定壞掉或從沒設過
# 一律退回預設，不拋例外）。兩者守的都是資料正確性——一筆花費算在哪一天、以及設定壞一格
# 不會讓那天完全沒有數字——屬 全域 CLAUDE.md 測試四類允許的四類之一。
# 先證過紅：把 `today_for_org()` 改回 `datetime.now(UTC).date()`，兩支同時抓到。
# 初稿寫了四支（+104 行），刪掉跟端到端那支重複的兩支之後才是這個數字：同一件事驗兩遍
# 不是更安全，是多一份要維護的東西。
# 2026-08-30 票 04-2 AI 金鑰進 Vault：14,410 → 14,480（含本段註解自己佔掉的行；審查回饋後
# 修正過一次算法，這是修正後的實測值，不是估的）。test_settings_api.py 新增四支，守的是
# 資料正確性／租戶隔離（全域 CLAUDE.md 測試四類）：存金鑰後 app_setting 不留明文、
# 舊明文列被清掉；第二次存 secret_id 指標不變（同一個 secret 就地覆寫——不比對
# vault.secrets 全域列數，那張表全組織共用一個 schema，`-n auto --dist loadfile` 下別的
# 模組同時 save_token／save_api_key 會讓總數跳動）；清除同時砍掉指標與 secret；兩個組織
# 各存各的讀不到對方的，用完清乾淨（vault secret／app_setting／organisation 都刪，比照
# test_settings_org_scope.py 的 tearDown 形狀）。先證過紅：把 save_api_key() 改回呼叫
# set_setting() 直寫明文，這幾支立刻抓到。
#
# 票 05-1（三個檔期生成改走佇列）：14,480 → 14,662（含本段註解自己佔掉的行，實測值）。
# test_schedule.py：新增 QueuedGenerationTest（money：同一個品牌／task_type 已經在跑，第
# 二次 POST 409 且不多排一個工作；API contract：POST 回來時代理還沒被打過，worker 跑過
# 一次才打），既有成功路徑的測試（PlanApiContractTest／RejectApiContractTest／
# TreeApiContractTest／BindTreeApiContractTest／CreativeApiContractTest／
# SearchSourcesReadbackTest）從「POST 直接讀結果」改成「POST → commit → run_worker(wait=
# False) → GET 讀結果」（POST 不再在 request 裡打代理，見 app/schedule/routes.py 檔頭）。
# test_llm_gateway.py：新增 FailInterruptedTasksTest（資料正確性：process 重啟時，中斷的
# running 列標記失敗，succeeded 列原封不動）。test_approval.py 的 `_succeed_plan_and_tree()`
# 助手方法同一個改法，不算新測試（既有斷言原封不動，只是等 worker 跑過一次）。三支新斷言
# 都屬 全域 CLAUDE.md 測試四類允許的類別（money／API 契約／資料正確性），先證過紅：
# 分別把 _display_task_row() 的 running 檢查、enqueue() 之前的順序、
# fail_interrupted_tasks() 的 WHERE 條件改壞，三支各自單獨抓到。
# 票 05-1 fix round 1（money）：14,662 → 14,740（含本段註解自己佔掉的行，實測值）。
# test_schedule.py 新增一支：`QueuedGenerationTest::test_creative_job_uses_the_tree_pinned_at_enqueue_not_a_later_running_row`
# ——`schedule_creative` 過去在 job 執行時重讀「這個品牌最新一次 schedule_tree」而不是
# enqueue 當下驗證過的那一列；frozen decision 3「一次一個」是按 task type 算的，擋不住
# 使用者先按產素材（排進佇列）又按展開活動樹（插進一列新的 running）這段交錯窗口——job
# 真的跑到時撿到那列還在跑的、對著錯的（甚至空的）樹打代理，花錢的結果對不上任何廣告
# 節點。這支測試守的就是這個：enqueue 一個 creative job、在它被 worker 撿走之前插一列
# 更新的 running schedule_tree，斷言 job 用的還是 enqueue 當下釘住的那棵樹（
# `context_scope_json["source_tree_task_id"]` 對得上、prompt 裡看得到真的葉節點名稱），
# 不是後來插隊的那一列。屬 全域 CLAUDE.md 測試四類「money」——先證過紅：把
# `schedule_creative()` 改回用 `_latest_task_row()` 重讀最新的 schedule_tree，這支立刻
# 抓到（斷言接住的是 `source_tree_task_id` 對不上，不是隨便崩潰在別的地方）。
# 票 storage-01：14,740 → 14,861。新檔 app/tests/test_storage.py（對真的本機 Storage
# 跑）：put/get 位元組與 content-type 原樣往返（data correctness）、get 對缺物件丟
# NotFound（同上，錯誤模型不能是死碼）、delete_prefix 真的刪掉兩層深的物件而不是回報
# 成功卻什麼都沒刪（data correctness，就是 SPEC D3 點名的那個坑）、四個函式各一支
# key/prefix 首段必須等於 org_id 的測試，不寫迴圈（tenant isolation）。
# 票 storage-03：14,861 → 14,955。建檔精靈照片搬進 Storage：
# `POST /api/intake/photos` 存進去的 key 第一段必須是呼叫者的 org_id（tenant isolation，
# proven red once：暫時斷言錯的 org 前綴，看它真的紅，再改回來）；新增
# `GET /brands/{id}/intake/photos/{filename}` 回真的位元組、沒登記在草稿上的檔名仍 404
# （API contract，這條路由先前完全沒有測試）；既有的
# `test_scan_success_stores_impressions_and_real_cost`（cost_items 長度斷言）現在順帶
# 證明照片掃描真的經 `storage.get` 讀回位元組——沒改斷言，只是背後的路徑換了。
# 票 storage-04：14,955 → 14,772。素材資料夾設定退役，整支測試檔（160 行）隨模組一起
# 刪；test_relocation_paths.py 收斂成只剩一條還站得住腳的斷言（官方素材／建檔精靈照片
# 的本機上傳目錄測試隨 storage-02／03 一起失去測試對象）、test_settings_api.py 少幾行
# 不再測的斷言與 import。
# 票 S0：14,772 → 14,813。`PagingNeverTruncatesSilentlyTest` 兩條：擞到翻頁上限要拋例外、
# 以及正常翻完三頁仍然全部回得來（後者守的是這次把 `break` 改成 `return` 的那行）。
# 守的是**資料正確性**：殘缺的拉取比拉不到更危險，因為它看起來像資料——少掉的那幾天
# 會讓一則正在贏的廣告看起來像是停止投遞了。沒有第三條，畫面行為不寫單元測試。
# 票 S1（三層成效）：14,813 → 15,144（實測值，含本段註解與 KNOWN_MODULE_SIZES 兩筆理由
# 自己佔掉的行）。`test_meta_daily_spend.py` 新增七支，
# 每一支的 docstring 都點名守的是四類之一：`LevelNeverSumsTest`（**money**——
# `meta_entity_spend` 三層共用一張表，`spend_summary` 沒篩 `level` 就把三層的花費疊在一起，
# 同一筆錢算三遍；先證過紅——暫時把 `_SPEND_WHERE` 的 `level` 條件拿掉，這支從斷言
# 「只有一個實體」變成「3 != 1」，見票 S1 報告的 RED 輸出）、
# `RerunIsIdempotentTest::test_upserting_same_entity_twice_...`（**資料正確性**：同一個
# (account, level, entity, date) upsert 兩次，只留第二次的數字）、`AbsenceIsNotZeroTest`
# （**資料正確性**：某一層某一天 Meta 沒回任何列，就是零列，不是補一列 spend=0）、
# `AttributionWindowStoredAsSentTest`（**資料正確性**：存進去的 attribution_window 是這次
# 請求真的送出的值，不是測試自己寫死的字串）、`CpaMappingTest`（**money**：CPA 沒設定
# 轉換目標是 NULL，設定了就照 README 對照表 map 出來的 action_type 算）、
# `RetentionGuardTest`（**money**：backfill 的 37 個月保護要在任何 HTTP 呼叫之前擋下）、
# `MonthlyChunkingTest`（**API 契約**：3 個月的補拉每層該送 3 次請求，不是 1 次也不是
# 90 次）。沒有重複驗證同一件事的兩支，也沒有畫面行為的單元測試。
# 票 S1 審查缺陷修正：15,144 → 15,178。`CpaMappingTest` 新增一支
# `test_cpa_is_null_when_any_day_in_range_has_no_tracked_conversions`（**money**：同一個
# 實體、同一個月，一天有對得上的 action、另一天 actions 是 SQL NULL——沒有 bool_and 保護
# 的話那天的花費照樣進分子、卻不進分母，印出一個過度樂觀的假 CPA；這支證明加了保護之後
# 總計跟實體小計都正確回 None）。沒有第二支重複驗證同一件事，也沒有畫面行為的單元測試。
# 多出來的行數還含這段理由註解本身與 KNOWN_MODULE_SIZES 那筆理由。
# 票 S2（開帳讀歷史）：15178 → 15714（實測值，含本段註解與四筆 KNOWN_MODULE_SIZES 理由
# 自己佔掉的行）。新檔 `test_onboarding_read.py`（482 行）六支，每一支的 docstring 都點名
# 守的是四類之一：`GenerationWritesNothingToLedgerTest`（**資料正確性**：跑完一次讀取、
# 不勾選任何結論，`learning_ledger` 一列都不該多出來——先證過紅：暫時讓
# `onboarding_read()` 生成當下就寫帳本，這支從綠翻紅（`1 != 0`），改回來才又綠）、
# `AcceptPerConclusionTest`（**資料正確性**：勾一條只多一列且是被勾的那條、全選補齊其餘、
# 讀取剛完成時沒有任何一條預先打勾、寫進去的列 `source_track` 標成 imported——四件事一支
# 測完，不拆成四支各自重建一次 fixture）、`ParallelCampaignsBothSucceedTest`（**money**：
# ADR 0042 修正版明講的那支——鎖字面值是 `onboarding_read:{account}:{campaign}`，兩個活動
# 平行各自成功一次，沒有任何一個被鎖拒收，鎖抓太寬會白花錢又查不到帳，抓太窄會同一份工作
# 算兩次錢）、`FanInCountsTest`（**資料正確性**：一個活動故意失敗，「全部完成」該是
# False；只重跑那一個活動之後變 True，另一個活動不會跟著多跑一次）、
# `UnreadableAdIsReportedTest`（**資料正確性**：Meta 回不出素材的廣告要出現在
# `unreadable_ads`，斷言「被靜悄悄丟掉」必須失敗）、`PromptCarriesMethodologyTableTest`
# （**資料正確性**：組出來的 prompt 真的貼進 `ab-testing.md` 第 3 節樣本數速查表逐字內容
# 跟部門任務檔識別行——這是模型真正需要的判斷依據有沒有到位，取代已刪掉的「grep diff 找
# 常數」檢查）。沒有第七支重複驗證同一件事，也沒有畫面行為的單元測試（那支留給
# `frontend/e2e/smoke.spec.ts`，S2-DESIGN.md D0-b）。
# 票 S2 審查回應：15714 → 15725。沒有多寫任何一支測試——多的 6 行全是上面
# `KNOWN_MODULE_SIZES` 裡 `app/schedule` 那筆新增的理由註解（accept 的冪等只是先查再寫，
# 那個上限現在寫在 `accept_conclusions()` 的 `ponytail:` 段落裡）。審查抓到的是一個
# 沒有測試守得住的上限：要守它得先有唯一索引，而 ADR 0044 不准這張票動 schema，所以
# 這裡不新增一支「會通過但什麼都沒證明」的測試來假裝守住了。
# 票 S2 實機驗收（第三件）：15793 → 15842。新增第八支
# `DailyCsvFlattensActionsWithoutInventingZeroTest`（**資料正確性**：`actions` 攤平成欄位
# 只准改形狀，回報過的數字原樣留著、沒回報的那天留空白絕不填 0——後者正是
# `meta_entity_spend` 的 null≠0 規矩在 CSV 這一層的樣子）。先證過紅：把留空白改成填 0，
# 這支立刻紅在 `'0' != ''`，改回來才綠。純函式測試，不跑 worker、不進資料庫。
# 前一次是 15793——
# 票 S2 實機驗收（第二件）：15740 → 15793。新增第七支
# `CampaignWithoutNumbersIsReportedTest`（**資料正確性**：Meta 列得出來、但這段期間手上
# 一列數字都沒有的活動不派分析師，卻一定要被點名——真帳號 58 個活動裡 34 個屬於這類，
# 靜靜跳過等於謊報這次讀了整個帳號），另外兩支多活動的測試各補一列 c2 的花費（不補的話
# 它們的第二個活動會被正確跳過，那兩支要驗的「兩個活動」就只剩一個）。
# 這一條是假的 Graph 替身量不到、只有真的打一次 Meta 才看得見的東西。
# 前一次是 15740——
# 票 S2 實機驗收：15725 → 15740。一樣沒有多寫測試——多的 11 行是上面 `app/meta` 與
# `app/schedule` 兩筆新增的理由註解（Meta 實際拒收 `DELETED`，跟報告表頭那句話因此要
# 講得更精確）。這是第一次真的打 Meta 才量得到的事，不是漏測：測試裡的 Graph 是假的，
# 假的那支不會替我們拒絕一個官方文件明明列出來的枚舉值。
# 票 S2b 步驟 0（純搬移）：15842 → 15854（含本段註解自己佔掉的 5 行）。**一支測試都沒有多寫**——多的 12 行全部是本段與上面
# `KNOWN_MODULE_SIZES` 裡 `app/schedule` 那筆新增的理由註解。測試檔本身只改了兩行：
# `DailyCsvFlattensActionsWithoutInventingZeroTest` 呼叫的 `onboarding._daily_csv` 改成
# `onboarding_slice.daily_csv`，import 那行跟著加一個名字（淨增 0 行）。它守的那件事
# （**資料正確性**：沒回報的那天留空白絕不填 0）一個字都沒放寬，只是換了個 import 路徑。
# 票 S2b A1：15854 → 15919（含本段註解自己佔掉的行數）。新增一支
# `DailyCsvOmitsAllZeroColumnsTest`（**資料正確性**：整個窗口加總是 0 的欄位不送，且
# `totals_text()` 要把「送了幾種、省了哪幾種」點名出來，presence 跟 absence 都是事實，
# 沉默才是說謊），`DailyCsvFlattensActionsWithoutInventingZeroTest` 跟著新的
# `daily_csv()` 回傳形狀多接兩個變數、多兩行斷言確認這次的兩種欄位都沒被誤砍——它守的
# 「blank≠0」那條規矩一個字沒放寬，只是多驗一件事：A1 新加的「加總是 0 才砍」不會把
# blank 誤判成 0 一起砍掉。多的行數同時也是上面 `KNOWN_MODULE_SIZES["app/schedule"]`
# 那筆新增理由註解自己佔的行。
# 票 S2b A3：15919 → 15962（含本段註解、上面 `KNOWN_MODULE_SIZES["app/schedule"]` 那筆
# 新增理由註解，以及測試檔本身的改動自己佔的行）。**沒有新增測試類別**：
# `DailyCsvOmitsAllZeroColumnsTest` 本來就是 A1 的資料正確性閘門，這裡只是多驗同一支
# 測試就該驗的另一件事——長的 `entity_name` 不該重複出現在逐日資料列裡，應該只在
# `daily_csv()` 新回傳的實體對照表出現一次（六行新斷言＋長名字測試資料）；
# `DailyCsvFlattensActionsWithoutInventingZeroTest` 只是函式簽名從三元組變四元組，多接
# 一個變數，它守的「blank≠0」規矩一個字沒動。都不是「新測試」，是既有測試跟著新形狀
# 補斷言，兩支測試守的事一個沒變。
# 票 S2b A2：15962 → 16048（含本段註解、上面 `KNOWN_MODULE_SIZES["app/schedule"]` 那筆
# 新增理由註解自己佔的行，兩邊都會被這支測試算進 `tests`）。新增一支
# `CoverageTextComputesLongestGapTest`（**資料正確性**：餵一個已知的缺口分布，斷言算
# 出來的最長缺口起訖日剛好對得上，同時涵蓋票 S2b 明講的三個邊界——一列資料都沒有的
# 實體、缺口只落在窗口最前面、窗口裡天天都有資料所以沒有缺口）——這是貨真價實的新測試，
# 不是既有測試補斷言，守的是「涵蓋範圍全部外殼算好、絕不問模型」這件事，第一次有機器
# 檢查。
# 票 S2b A4：16048 → 16119（含本段註解、上面 `KNOWN_MODULE_SIZES["app/schedule"]` 那筆
# 新增理由註解自己佔的行，兩邊都會被這支測試算進 `tests`）。新增一支
# `CreativeFuseSendsRawJsonOnUnexpectedShapeTest`（**資料正確性**：文案藏在
# `_creative_variants()` 認不得的鍵名裡，斷言保險絲點火——這則素材的原始 JSON 原封不動
# 送出去，且不算進 `unreadable`——先證過紅：暫時拿掉 `_ad_fact_card()` 的保險絲分支，
# 這支從綠翻紅，訊息是 `AssertionError: '保險絲觸發' not found in '...'`，改回來才又綠）。
# `FanInCountsTest` 的 `_FailByMarkerProvider` 標記字串跟著 `structure_text()` 的新形狀
# 換了一次（`"id": "c2"` → `campaign：[c2]`），不是新測試，是既有測試補上新格式下同一份
# 判斷依據，多出的幾行是這支測試自己 docstring 的更新說明。
# 票 S2b A4 審查回應（四位獨立審查者對同一份 diff）：16119 → 16245（含本段註解、上面
# `KNOWN_MODULE_SIZES["app/schedule"]` 那筆新增理由註解自己佔的行）。新增三支，三支都
# 是既有測試守不住、審查真的抓到程式在跑的資料正確性缺陷：
# `VideoCreativeTitleFieldIsNotDroppedTest`（**資料正確性**：`video_data` 的標題鍵是
# `title`，`_creative_variants()` 原本三種形狀共用 `link_data` 的 `name`，video 廣告的
# 標題整個消失且保險絲不會點火——先證過紅：把 `_STORY_SHAPES` 的 video_data 那一列
# 標題鍵改回 `name`，這支從綠翻紅，`AssertionError: None != '限時五折｜補水面膜'`，
# 改回來才又綠）、`ZeroSumSplitDoesNotProveZeroFromMissingValueTest`（**資料正確性**：
# 一個種類有回報但沒給數字，`_zero_sum_split()` 原本先 `setdefault` 成 0 才看
# `raw is None`，把「無法證明」偷渡成「證明是 0」——先證過紅：拿掉 `raw is None` 分支
# 裡的 `unprovable.add()`，這支從綠翻紅，`AssertionError: 'lead' not found in
# ['link_click']`，改回來才又綠）、`AdsetFactCardCarriesBudgetModeFieldsTest`
# （**資料正確性**：`effective_status`／`optimization_goal`／`billing_event` 是
# ADR 0045 點名的「budget mode（結構性事實）」，`app/meta/graph.py` 本來就打這三個
# 欄位回來，`_adset_fact_card()` 原本漏接——先證過紅：拿掉卡片那三個欄位的輸出行，
# 這支從綠翻紅，`AssertionError: 'PAUSED' not found in '...'`，改回來才又綠）。
# `app/schedule` 那邊其餘的修法（video_data 以外的欄位對應、輪播、`asset_feed_spec`
# 沒有 `asset_customization_rules` 時的抽法、興趣去重、實體對照表改名、CPM／CPC 精度）
# 已經被 `DailyCsvOmitsAllZeroColumnsTest`／`DailyCsvFlattensActionsWithoutInventingZeroTest`／
# `CreativeFuseSendsRawJsonOnUnexpectedShapeTest` 這幾支既有測試間接守住（跑過，全
# 綠），沒有為了同一類邏輯重複開測試。
# 票 S2b（拆檔，二次）：16245 → 16257。零新測試——這 12 行是 `KNOWN_MODULE_SIZES`
# ["app/schedule"] 那筆新增理由註解，跟本段自己這兩行理由註解，合起來佔的行。
# 票 S2b A4 完整性審查（2026-08-31，真帳號 368741390835357）：16257 → 16358。新增兩支，
# 兩支都守**資料正確性**，且都先證過紅：
# `LabelledAssetResolvesAdAssetLabelObjectTest`（真帳號驗證過 `asset_customization_rules`
# 的 `body_label`／`title_label` 是 AdAssetLabel 物件不是字串——先證過紅：把
# `_resolve_labelled_asset()` 改回只比 `adlabel.get("name") == label`（label 還是物件），
# 這支從綠翻紅，`AssertionError: 0 != 1`，改回來才又綠）、
# `AssetFeedSpecCtaAndDescriptionsAreNotDroppedTest`（真帳號驗證過 `asset_feed_spec` 回
# `call_to_action_types`（純字串陣列）不是原本讀的 `call_to_actions`，且完全沒讀
# `descriptions`——先證過紅：改回 `call_to_actions`，`AssertionError: None != 'SHOP_NOW'`；
# 另外把 `descriptions` 讀取改回 `None`，`AssertionError: [] is not true`；兩處分別改回來
# 才又綠）。這兩支不是既有測試補斷言，是舊測試（`CreativeFuseSendsRawJsonOnUnexpectedShapeTest`
# 等）從沒餵過這兩種真帳號形狀，才會綠燈放過這兩個 bug。多出的 101 行含這段理由本身跟上面
# `KNOWN_MODULE_SIZES["app/schedule"]` 那筆新增理由註解自己佔的行。
# 票 S2b A4 完整性審查回應第二輪（2026-08-31，真帳號 368741390835357）：16358 → 16448。
# 新增兩支，兩支都守**資料正確性**，且都先證過紅：
# `AssetFeedSpecUnpairedBodiesAndTitlesAreHonestTest`（`asset_feed_spec` 沒有
# `asset_customization_rules` 時，上一輪把每個 body／title 各自印成一則帶
# `placement_count：1` 的假變體，這裡讀不出配對就不該印一個看似有意義的數字——先證過紅：
# 把這個分支改回舊邏輯（body／title 各自造一個假變體），這支從綠翻紅，
# `AssertionError: 4 != 1`，改回來才又綠）、`RoundSigFigsDoesNotEmitScientificNotationTest`
# （`_round_sig_figs()` 磨一個 ≥ 1000 的大數字，結果印成科學記號跟這支函式自己 docstring
# 講的相反——先證過紅：拿掉 `format(rounded, "f")` 那行重建，這支從綠翻紅，
# `AssertionError: '1.23E+3' != '1230'`，改回來才又綠）。多出的 90 行含這段理由本身跟上面
# `KNOWN_MODULE_SIZES["app/schedule"]` 那筆新增理由註解自己佔的行。
# 票 S2b A4 完整性審查回應第三輪（2026-08-31，真帳號 368741390835357，三個獨立審查者
# realdata／fuse／gate 逐一量到、上一輪綠燈閘門守不住的資料正確性缺陷）：16448 → 16706。
# 新增八支，全部守**資料正確性**，全部先證過紅：
# `TemplateDataShapeAndChildOnlyAttachmentsAreNotDroppedTest`（兩支，`object_story_spec.
# template_data` 是 `_STORY_SHAPES` 原本不認得的第四種真實形狀，25/158 則素材是這個形狀；
# 另一支是 `link_data` 沒有 `message`／`name`、文案全在 `child_attachments` 裡卻被
# `continue` 跳過——先證過紅：分別拿掉新加的 `_STORY_SHAPES` 那筆、把 continue 判斷式
# 改回不看 `child_attachments`，兩支都從綠翻紅 `AssertionError: 0 != 3` 與
# `AssertionError: 0 != 2`，改回來才又綠）、`CallToActionFallsBackToTopLevelFieldTest`
# （CTA 只在素材最外層有、`object_story_spec`／`asset_feed_spec` 兩邊都沒有時原本印
# None——先證過紅：拿掉兩處 `or creative.get("call_to_action_type")` 退回層，
# `AssertionError: None != 'SHOP_NOW'`，改回來才又綠）、
# `AssetCustomizationRulesUnreferencedAssetTriggersFuseTest`（真帳號驗證過同一份 body／
# title 資產的 `adlabels` 常帶著全部規則的 label，first-match-wins 因此把全部規則收斂成
# 一組、其他資產悄悄消失——改成分組後斷言涵蓋率，讀不懂真配對就回空清單讓保險絲接手；先
# 證過紅：拿掉這段涵蓋率檢查，回傳 2 個不完整的變體而非空清單，改回來才又綠）、
# `UnpairedVariantSeedsFromTopLevelTitleWhenFeedHasNoneTest`（`asset_feed_spec` 只有
# bodies 沒有 titles 時，素材最外層 `title` 原本被丟掉，印出「titles（0）」這句假話——
# 先證過紅：拿掉新加的補值那兩行，`AssertionError: [] != ['留言...']`，改回來才又綠）、
# `ExtraListFieldsPrintVerbatimNotAsPythonReprTest`（`extra` 的清單值——`descriptions`
# 這類——原本塞進 f-string 印成 Python `repr()`，帶換行的文案因此不是逐字；改成共用的
# `_extra_lines()` 印成一行標頭＋逐則清單，兩處呼叫端一次修好——先證過紅：把
# `_extra_lines()` 改回單行版本，帶換行那句真話不再逐字出現，改回來才又通過）、
# `AdsetFactCardCarriesAgeRangeAdvantageAudienceAndAllDetailedTargetingKindsTest`（真帳號
# 30/50 個廣告組開了 `advantage_audience`，`age_min`／`age_max` 因此被灌成平台上限，
# 廣告主真正選的範圍留在 `age_range`；`behaviors`／`industries`／`work_positions` 原本
# 完全沒收集；`excluded_product_audience_specs` 原本沒算進 exclusion_count——先證過紅：
# 拿掉 `age_range`／`advantage_audience` 那行跟 `*flexible_lines`，`age_range=[18, 40]`
# 不再出現，改回來才又綠）、`TotalsTextRendersMissingMetricAsBlankNotNoneLiteralTest`
# （`totals_text()` 沒套 `_ad_fact_card()` 那族已經在用的 `_blank_or()`，一個活動沒有
# 轉換事件時 ROAS／CPA 印出裸的 Python `None`——先證過紅：拿掉三個 `_blank_or(...)`，
# `AssertionError: 'None' unexpectedly found in`，改回來才又通過）。八支都是拿真帳號
# 368741390835357 逐欄位驗證過的形狀剪下來當 fixture，不是重複既有測試的斷言：既有測試
# 從沒餵過「兩邊都沒 CTA」「同一份文案被全部規則的 label 都認得」「feed 只有一邊」
# 「清單值 extra」「age_range 跟 age_min／age_max 不一致」「總計裡的 None」這幾種形狀，
# 才會綠燈放過這幾個 bug。多出的 328 行含這段理由本身跟上面
# `KNOWN_MODULE_SIZES["app/schedule"]` 那筆新增理由註解自己佔的行。
# 票 S2b B1＋完整性審查三件 major（2026-08-31）：16776 → 16964。四支新測試，每一支都
# 指名它守的是**資料正確性**（ADR 0041 要求的四選一），而且都先證過紅、看它失敗、再改回來：
#   1. `BucketSumsEqualTheDailyValuesTheyReplaceTest`——B1 閘門 1：一個桶的 spend／
#      impressions／clicks 等於它取代的那幾天加總（ADR 0045：分桶可以改形狀，不准改總和）。
#      順便守「先加總再四捨五入」：三天各 0.005 元，先捨入再加是 0.03，正確是 0.02。
#   2. `EmptyBucketIsNamedNotSilentlyDroppedTest`——B1 閘門 2：空桶不進表格但要在涵蓋範圍
#      那節被逐個點名（缺席不准變沉默），而且有資料卻沒 ROAS 的桶那一格是空白不是 0。
#   3. `OutlierDaysSurviveBucketingTest`——分桶最容易磨掉「某一天爆單」，所以每個桶額外
#      原封送出花費最高日與轉換最高日；「轉換」用品牌自己的目標，不是所有 actions 加總
#      （fixture 就是那個差別：800 次點擊 0 筆成交那天 vs 9 筆成交花費最低那天）。
#   4. `CreativeFuseSendsRawJsonOnUnexpectedShapeTest` 新增的第二支——保險絲理由要講出
#      真正觸發的那一條路。真帳號 34 次觸發裡 27 次原本那句「抽不出 body 也抽不出 title」
#      被緊接著印出的 JSON 當場推翻，系統在對分析員說謊。
# 沒有一支重複既有斷言：既有測試從沒餵過「同一個實體跨兩個桶」「先捨入 vs 先加總」
# 「有資料但零 ROAS 的桶」「兩種編碼都帶文案」這四種形狀，才會綠燈放過。
# 同一批改動也刪掉了 `DailyCsv*` 兩支的舊粒度斷言（改寫成桶粒度，不是多留一份）。
# 16964 → 17010：多出的 46 行就是上面這段理由註解自己佔的行（比照前幾次的記法）。
#
# 真瀏覽器驗收兩個 bug（2026-08-31）：17010 → 17074（多的 15 行含這段理由本身）。一支新測試，守的是 **API 契約**
# （ADR 0041 四選一）：`StartReportsTheReadItJustStartedTest`——POST 建立讀取之後回的必須是
# 這一次剛派出去的讀取，不是上一次那份已完成的。先證過紅（把結尾改回 `brand_response(...)`，
# 第二次 POST 回的 read_id 跟第一次一模一樣）。不重複既有斷言：既有測試從沒對 POST 自己的
# 回應斷言過任何東西，只驗過之後 GET 回來的內容，所以綠燈一路放過這個 bug。
# 另一個 bug（畫面每 2 秒閃一次）在 `frontend/`，那一層照 CLAUDE.md 只收 e2e smoke，不寫單元測試。
#
# 票 T3b（ADR 0055）：綁定改鍵 node_key，不再落在 llm_task.context_scope_json。守的是
# **資料正確性**——舊版拿節點名稱當 dict key，兩個同名節點會撞成一格；新測試證明新版不會：
# 兩個同名第一層節點各自綁到不同活動且保持獨立（舊版表達不出來的狀態）、重新展開後同名同
# 位置留住綁定、換了名字顯示未綁定、ticket 矛盾檢查段那個「兩個鄰居互換名字」的第三案例
# （位置優先、名字只當否決票，兩邊都不繼承對方）、改名後第二次 bind 是覆寫同一列
# （`(org_id, brand_id, channel_id, node_key)` 這把 upsert 鍵本來要防的事）、以及讀這條疊圖
# 的 SQL 本身也要過租戶隔離。17074 → 17263（含本段理由註解自己佔的行）。
#
# 票 T3c（ADR 0055 §7）：第二層（扛預算的廣告組合）也綁。守的是**資料正確性**：
# `app/meta/graph.py` 的 `list_ad_sets`／`_to_ad_set`（翻頁跟到下一頁、缺 id 整筆跳過、
# 缺名稱補空字串——比照既有 `list_campaigns` 那組規則，`test_meta_daily_spend.py`
# `ListAdSetsTest`）；`app/meta/repository.py` 的 `ad_set_ids_by_exact_name` 連不上 Meta
# 時把 `GraphError` 轉成人話 `meta_unreachable`（同檔 `AdSetMatchUnreachableTest`，比照
# 既有 `campaign_ids_by_exact_name` 的錯誤形狀）；`app/schedule/binding.py` 的
# `bind_tree`／`tree_with_bindings` 遞迴到第二層（`test_schedule.py`
# `BindTreeApiContractTest` 五支新測試：第二層在父層活動範圍內配對且出現在 API 回的樹
# 上、同名廣告組合出現在別的活動底下不算數、父層沒綁成子節點整批不比對、平台端兩個廣告
# 組合剛好同名兩邊都不猜、改名後跟第一層一樣顯示未綁定）。多出來的行數也含既有六支
# 測試补上 `_platform_ad_sets` 這道新配對步驟必要的 mock（第二層現在一定會被嘗試，不
# mock 就真的打網路），以及本段理由註解自己佔的行。17263 → 17504。
#
# 票 T3e（ADR 0055 §11）：檔期分帳細到節點。守的是**金額**與**資料正確性**：
# `test_schedule.py` 新增 `NodeLevelSpendTest`（`node_level_spend()` 純函數、桌面案例、
# 不碰資料庫）六支，逐條對應 ticket done-check 2 明講的六條規則——並列日全部期加總對到
# 分（金額）、已登記的實體去它自己登記的那期而不是品牌層擁有者、沒登記的照舊落給品牌層
# 擁有者、天數並列時照 `allocation_weight` 分（1:1 與 2:1 兩案）、membership 蓋到的天數
# 夾不進它自己那期的真實範圍就不算登記、沒有任何檔期的一天誰都拿不到（皆資料正確性）；
# `BindTreeApiContractTest` 新增三支：深度 2 綁定時 `period_node_membership` 落地一列且
# 深度 1 不落地（資料正確性）、沒有檔期時不寫也不報錯（資料正確性）、改名逼出真的第二次
# `upsert_binding` 時 migration 的唯一鍵讓 `period_node_membership` 仍只有一列（金額——
# 這是雙寫算兩次錢的防線）。`test_schedule_period.py` 的 `_seed_spend()` 從
# `level="campaign"` 改成 `level="adset"`（ticket §5 的 level 換層逼的，這支測試本身
# 守的規則一個字沒變，見檔頭新增那段說明）。多出來的行數也含本段理由註解自己佔的行。
# 17504 → 17733。
# T3e 審查補洞（2026-09-03 主對話台，+28 行，含這段理由自己佔的行）：`node_level_spend()` 的「短檔期優先」
# 是 ADR 0053 §4 的規則本體，卻**沒有任何測試在守**——把 `period.py` 的 `min()` 改成
# `max()`，原本九支測試全部照樣綠燈。補的那一支餵「同一個廣告組合同時登記在兩個不等長
# 檔期底下」這個輸入，已證過紅（同樣的變異現在只殺它一支）。守的是金額。
#
# 票 T3d（ADR 0055 §1）：`creative_slot` 改用 `node_key` 識別，不再用節點名稱。守的是
# **資料正確性**：舊版兩個同名的最深層節點會撞成同一個 slot、兩份文案分不出彼此；新測試
# 證明新版不會——`_two_top_nodes` 兩個分支底下的最深層節點固定同名，各自綁到不同的
# `node_key`，各自落地成獨立的 slot 跟候選
# （`CreativePersistenceTest.test_two_same_name_leaves_under_different_parents_produce_two_slots_and_two_candidates`，
# 紅法：讓兩個節點共用同一個 `node_key` 落地，兩個 slot 撞成一個，已證過紅、已還原）。
# 多出來的行數也含 `CreativePersistenceTest` 既有兩支測試把斷言鍵從 `ad_node_name` 換成
# `node_key`、`BuildCreativeTest` 五支既有純函數測試改吃新版 `ad_nodes`
# （`{"node_key", "name"}`）形狀必要的 fixture 更新（`_nodes()` 小工具，簽章換了、不是新
# 斷言），以及本段理由註解自己佔的行。17761 → 17823。
#
# 票 identity-hs256-startup-guard：17823 → 17867（含本段理由註解自己佔的行）。新增一支
# `Hs256StartupGuardTest`（**租戶隔離**：`.env.example` 原樣複製到雲端時，`IDENTITY_ALLOW_HS256`
# 這道開發後門會跟著打開，任何知道 Supabase 本機示範密鑰的人都能簽出帶任意 `org_id` 的
# token、讀到別人的租戶——這支同時證兩件事：`register()` 在非本機＋
# `IDENTITY_ALLOW_HS256=1` 時會 `RuntimeError` 拒絕啟動（守執行期），`.env.example` 出廠
# 沒有打開這個變數也沒有帶那把示範密鑰（守模板，擋回歸）。沒有第二支重複驗證同一件事，
# 這是 ticket 本身明講的測試預算。
#
# 票 schedule-extract-state：17867 → 17877（含本段理由註解自己佔的行）。**一支新測試都沒有**
# ——這 +1 行是一句 import：`_load_platform_data()` 從 `routes.py` 搬進 `state.py`，
# `test_approval.py` 必須跟著多一行 `from app.schedule import state as schedule_state`，
# 否則整個測試檔在 collect 當下就 `AttributeError`。`test_schedule.py` 那邊先加後刪抵銷成淨零，
# 只有這個檔少不掉。實作者拒絕自己調這個數字、回報 blocked-upstream，是對的：本票第 5 項
# 只授權他在 `KNOWN_MODULE_SIZES` 真的變紅時調那一個尺，沒有延伸到這裡。裁決在主對話台，
# 判準用 `docs/tech-debt.md` §六那一句——「新增的行數是那張票的交付物本身，還是為了繞過閘門
# 塞進來的？」搬家要求的 import 是前者。
#
# 票 T4（ADR 0056）：17877 → 18058（含本段理由註解自己佔的行）。三支新測試，**每一支都由
# 票上一條 done-check 逐字指名，每一支都證過紅**，沒有第四支：
#   1. `test_meta_credentials.AccountScopeUniquenessTest`（租戶隔離／API 契約）——證明
#      `channel_credential` 的 `unique(org_id, channel_id, account_scope)` 真的擋得住重複，
#      也真的允許同組織第二組 token。這是 T4 換掉 `meta_credential`（主鍵 org_id＝一個組織
#      只能一個 token）的**唯一**證據；紅法：拿掉那道 unique，第二次 INSERT 不再拋
#      `UniqueViolation`。
#   2. `test_meta_daily_spend.SpendDateFollowsTheAdAccountTimezoneTest`（資料正確性）——
#      `spend_date` 跟廣告帳戶自己的時區，NULL 退回組織時區。守的是**錢記在哪一天**。
#      紅法：`daily_pull._pull_one_account` 改回只用 `today_for_org`，日期差一天。
#      實作者把票上舉例的 Asia/Taipei／America/Los_Angeles 換成相差 26 小時的
#      Pacific/Kiritimati／Etc/GMT+12，理由寫在測試 docstring 裡：前者一天裡有大半時間
#      兩邊日期剛好相同，紅法會碰運氣過——那不是證據。
#   3. `test_rls_tenant_policy.VaultOrgScopedAccessTest.test_read_secret_through_channel_
#      credential_is_scoped_to_the_claimed_org`（租戶隔離）——Vault 那三支 SECURITY DEFINER
#      門的擁有權檢查改認 `channel_credential` 之後，組織 B 仍然開不了組織 A 的鑰匙。
#      **這條分支在 T4 之前從來沒有測試**：既有的 vault 測試全部走 `app_setting` 那一支
#      （`test_rls_tenant_policy.py:209`）。紅法：把 `channel_credential` 那個 EXISTS 註解掉，
#      組織 A 讀自己的也被擋。
#
# 為什麼調高而不是退件：`docs/tech-debt.md` §六（2026-09-02 使用者裁決）的判準是
# **「新增的行數是那張票的交付物本身，還是為了繞過閘門塞進來的？」** T4 是 route C 的
# schema／權限票，三條 done-check 各自要一支測試，這 156 行測試＋25 行本註解就是交付物。調到量到的數字，
# 不留餘裕——這正是那次裁決的原話。實作者拒絕自己調、把它送回主對話台，是對的。
#
# 票 T5（ADR 0057）：18058 → 18504（2026-09-03 實測，含本段理由註解自己佔的行）。授權寫在
# 票面「Line-budget authorisations」段——票上明講 TEST_LINES_CEILING 在票開出當天是 18058、
# 零餘裕，實作者被授權「調到量出來的後值，理由寫進這裡，不准為了留餘裕多調」。新增測試
# 全部對應票面 done-check，每一支都證過紅（不是「湊數」）：
#   1. `test_schedule_performance.py`（NEW，四支）——這張票存在的理由，money：
#      `MoneyInvariantTest`（done-check 1／2）證明 `untagged.spend + Σvalues[].spend ==
#      total_spend` 逐維度逐幣別都成立、兩個幣別互不相加；`RoasHonestyTest`
#      （done-check 3）證明 15 列裡只追蹤到 2 列時，`revenue`／`roas` 只用那 2 列、
#      `roas_coverage` 誠實回 2/15；`RenamedNodeUntaggedTest`（done-check 5）證明改名後
#      舊候選的座標不再悄悄接走這筆錢。done-check 1 的「證過紅」不是說說——`_currency_view`
#      裡 `dim_untagged_rows = buckets.pop(None, [])` 暫時改成 `= []`，
#      `MoneyInvariantTest` 立刻紅在 `untagged + values == total_spend` 那一行（0 != 1000），
#      改回來又綠，證據見本票 T5 實作報告。
#   2. `test_schedule.py`（`BindTreeApiContractTest`，擴充既有測試，不是新開）——深度 3
#      綁定本身（done-check 4）：既有的
#      `test_depth_two_node_binds_inside_its_parent_campaign_and_shows_on_the_tree` 擴成
#      `test_depth_two_and_three_nodes_bind_inside_their_parents_and_show_on_the_tree`，
#      多驗深度 3 綁定、`source_tree_task_id` 落地、`period_node_membership` 仍然只在深度 2
#      各一列（不是一個 ad 一列）；另外七支既有的深度二測試因為深度二綁定成功會連動觸發
#      深度三比對，多掛一次 `_platform_ads()`（新增的 mock helper）才不會在測試裡打真的
#      Meta 網路——這部分是既有測試因為深度三開通而必須跟著改的行數，不是新查核點。
#   3. `test_meta_daily_spend.py`（`ListAdsTest`／`AdMatchUnreachableTest`，兩支）—— API
#      contract：`graph.list_ads` 的翻頁／轉型規則逐字比照既有 `ListAdSetsTest`；
#      `ad_ids_by_exact_name` 連不上 Meta 時的錯誤形狀逐字比照既有 `AdSetMatchUnreachableTest`
#      （票面「這是同一套規矩，只深一層」——沒有第三種行為需要驗）。
#
# 掃障礙清單②（2026-09-04）：18504 → 18568（含本段理由註解自己佔的行）。新增
# `ContractPageRatchetTest`（MODULES_WITHOUT_CONTRACT 棘輪，跟 `FileLineCapTest`／
# `ModuleSizeRatchetTest` 同一種架構閘門，不是業務邏輯測試，全域 CLAUDE.md
# 「限制要有機器閘門」直接對應這一條）。先弄紅一次才算數：加一個假模組資料夾
# （無契約頁、不在豁免清單）驗證兩支斷言都紅，刪掉假資料夾後復原成綠。
#
# 小債清空（2026-09-04）：18568 → 18598（含本段理由註解自己佔的行）。新增
# `app/tests/test_schedule_creative.py`（`_valid_creative_fields` 對 `value: []`／
# `value: ["", ""]` 兩種空值誤放行——T1 收尾時記下、不擋合併的舊債，這裡收掉，
# 守的是資料正確性）。先證過紅：兩支斷言在改 creative.py 之前先跑過一次紅。
#
# 票 M1（ADR 0058）：18598 → 18635（含本段理由註解自己佔的行）。`test_approval.py` 新增
# `test_overspend_window_counts_days_on_the_orgs_calendar_not_utc`（money：approved_at
# 存 UTC、today 問組織時區，兩者要落在同一個時區才能相減，否則台北每天有 8 小時
# `days_elapsed`／`expected_to_date` 會多算一天——ADR 0058）——`astimezone(...)` 拿掉時
# 這支測試斷言 `2 != 1` 紅，補回去綠，證據見本票完成報告。順手把
# `test_binding_and_spend_survive_hash_but_reexpanding_does_not` 原本用
# `datetime.now(UTC).date()` 算「今天」改成跟生產碼同一個 `today_for_org()`——這張票
# 修好之後兩者不再是同一天，2026-09-04 台北 01 時這個時段親眼撞到它紅在
# `spend_to_date` 0.0 != 500.0（同一個 bug 的第二個現場，不是新查核點，是讓既有測試
# 繼續量對它原本要量的東西）。
#
# 小債清空（2026-09-04，使用者裁決刪除死碼）：18635 → 18467。這次是**往下**調，不需要授權——
# 棘輪本來就只准往下。刪掉 `app/tools/capacity_check.py`（260 行）與
# `app/tests/test_capacity_check.py`（176 行）：全 repo 找不到任何 `card.html`／`base.html`
# 模板或呼叫端（`git grep` 四個命中全是它自己、它自己的測試、`BOARD.md`、`docs/tech-debt.md`），
# 這支「版面守恆」腳本服務的是已刪除的 Jinja／`app/ads/` 舊 UI 世代，React 前端接手後
# 零呼叫端。`KNOWN_MODULE_SIZES["app/tools"]` 同步 318 → 58。
#
# 票 T7（channel_revenue 去重）：18467 → 18515（含本段理由註解自己佔的行）。使用者已在票面
# 「Line-budget authorisations」段授權調高，終值照票上的規矩——量到的數字，不留餘裕。新增
# `app/tests/test_orders_channel.py::ManualChannelEntryDedupeTest`（兩支）＋既有
# `SaveShopeeRowsTest` 一支新斷言：
#   1. `test_identical_resubmit_updates_not_duplicates`——**money**：手動通路營收表單按兩次要
#      更新同一列，不是翻倍。證過紅：`record_channel_entry()` 的去重分支暫時改回單純
#      INSERT（拿掉 SELECT-then-UPDATE-or-INSERT），這支立刻紅在 `2 != 1`；改回去綠。
#   2. `test_a_genuinely_different_second_entry_still_lands`——**data correctness**：只有
#      `note` 不同的第二筆手動登記，不能被雜湊誤判成同一筆而漏記（鐵則 8 手動路徑優先）。
#   3. `SaveShopeeRowsTest` 新斷言（同一個測試方法內，不是新開測試）——**data correctness**：
#      蝦皮匯入寫的列，新欄位 `source_row_hash` 要是 NULL，不然兩筆金額剛好相同的不同蝦皮
#      訂單會被新的 partial unique index 誤判成重複，去重修好反而變成漏記營收。
#
# 票 T8a（七維座標詞彙）：18515 → 18601（含本段理由註解自己佔的行）。使用者已在票面
# 「Line-budget authorisations」段授權調高，終值照票上的規矩——量到的數字，不留餘裕。
# 兩處新增：
#   1. `test_architecture_boundaries.py::CoordinateDimensionSyncTest`（NEW，+72 行，含本段
#      理由本身）——**API 契約**：七個維度鍵名（`CONSTITUTION.md` 規則 5）活在三個地方
#      （`app/schedule/creative.py` 的 `COORDINATE_KEYS`、`coordinatesApi.ts` 的
#      `COORDINATE_DIMENSIONS`、`CampaignTree.tsx` 的 `COORDINATE_LABELS`），過去沒有機器
#      比對過。證過紅：把 `coordinatesApi.ts` 的 `"audience"` 改成 `"audiences"`，這支測試
#      立刻紅在 `['audience', ...] != ['audiences', ...]`，改回去綠（票面驗收報告有兩次
#      pytest 輸出）。
#   2. `test_schedule.py::CoordinateSeedTest`（擴充既有測試，+14 行）——**data
#      correctness**：新增斷言確認第一次讀完七個維度都有座標、六個新維度加總 33 個，讀
#      第二次仍是 33 個（不是 66）——這正是本票 done-check 1 的字面內容，不是新開測試。
#
# 票 M2（ADR 0059，`docs/issues/m2-approval-signs-a-ceiling/ticket.md`）：18601 → 18721
# （實測，含本段理由註解自己佔的行，也含 `KNOWN_MODULE_SIZES["app/core"]` 那筆理由自己
# 佔的行）。使用者已在票面「Line-budget authorisations」段授權
# 調高，終值照票上的規矩——量到的數字，不留餘裕。`test_approval.py` 新增三支，都是
# **money**（核准是花錢煞車，ADR 0040）：
#   1. `test_scaling_the_whole_tree_down_keeps_the_approval_valid`（done-check 1／4）——
#      只縮總額、`share` 不動，`matches_current_tree`／`within_approved_ceiling` 仍要是
#      true，`expected_to_date` 要跟著現在的總額走、比核准當時的總額算出來的小。證過紅：
#      把 `daily_amount` 放回 `_tree_signature()` 的 `_node()`，這支斷在
#      `self.assertTrue(after["matches_current_tree"])`（`AssertionError: False is not
#      true`，`test_architecture_boundaries.py:1166` 那次跑是另一支，這裡指
#      `test_approval.py` 這支本身）；拿掉又綠，7 passed。
#   2. `test_moving_budget_between_nodes_still_voids_it`（done-check 2）——把 `share` 在
#      兩個節點之間搬動、總額不變，`matches_current_tree` 要變 false。這是擋住 check 1
#      被誤讀成「整份雜湊都不用管金額」的底線（ticket 矛盾檢查表：`share` 不在雜湊裡兩支
#      都會變成互相矛盾）。
#   3. `test_above_the_ceiling_is_caught`（done-check 3）——把總額拉到核准當時的每日上限
#      之上，`within_approved_ceiling` 要變 false。
# 票 T8b：18721 → 18767（2026-09-04 實測，含本段理由註解自己佔的行）。開票當天餘裕是 0，
# 授權寫在這裡：新增的 36 行是一支測試
# （`test_schedule.py::CreativeApiContractTest::test_creative_prompt_carries_the_brand_coordinate_vocabulary`），
# 它守的是 API 契約——`schedule_creative` 的 prompt 有沒有帶著這個品牌的 `brand_coordinate`
# 詞彙表。沒有這一節，代理只能自己造詞，落地時 `repository._resolve_coordinates()` 比對
# `brand_coordinate.label` 全部落空、七維寫回 NULL，而畫面與閘門都是綠的——這正是
# BOARD.md「要找的四種病」第 (c) 種（功能靠運氣過，或根本不會紅）。
# 兩種紅法都實證過（不只一種）：（a）把 `coordinate_text` 從 `jobs.py` prompt 的 join 裡拿掉
# → `AssertionError: '## 這個品牌的座標詞彙表' not found`；（b）把停用／否決的過濾條件改成
# `if False:` → 停用掉的那個 offer 值又出現在 prompt 裡，斷在 `assertNotIn`。
# 票 T8b 實機驗收回收（2026-09-04 稍晚）：18767 → 18782。這一次**沒有新增測試**——
# 六處改的都是既有斷言：`bind_failure` 從比對一句籠統的整批訊息，改成比對「哪一個節點、
# 哪一種失敗」（找不到 vs 有兩個同名的），外加一條 `assertNotIn("組合")` 證明沒去比對的
# 那一層不會被假裝成失敗、一條 `count(...) == 1` 證明同名手足的原因只講一次。
# 斷言變強不變弱，多出來的行是那六處的理由註解。
# 檔案層 import 環掃描（2026-09-04 晚，看板「閘門」目標）：18782 → 18840。新增的是
# `FileImportCycleScanTest` 一支測試（14 行）＋ `_app_modules()`／`_module_of()`／
# `_file_import_graph()` 三個掃描零件，其餘是收合套件層圖之後改寫的 `_layer_import_graph()`。
# 守的是模組邊界（測試四類之外的第五類，本檔整支都是），不是畫面行為。
# 順手修掉一個盲點：`from app import storage` 這種寫法原本被 `_layer_of()` 判成 None，
# 三條 app.intake → app.storage 的依賴在舊的兩道掃描裡是隱形的。
# 七維同步閘門補強（2026-09-04 晚，看板「閘門」目標）：18846 → 18892。兩件事：
# `_one_declaration()`（同名宣告只准一份，擋掉審查用假宣告騙過閘門那一招）與
# `test_all_three_equal_the_constitution`（三份都要等於憲法規則 5，擋掉三份同時錯還全綠）。
# 守的是資料正確性——七個維度鍵名對不上，回來的廣告成效數字就掛錯座標。
# 同名最深層節點的 `node_key` 配對（2026-09-04，看板「廣告閉環」目標，
# `docs/issues/ad-loop/issue-same-name-leaf-node-key.md`）：18892 → 18919，含本段註解自己
# 佔的行。新增的是 `BuildCreativeTest` 一支測試（21 行、三個情境：照編號配／漏答退回名稱
# 排隊／答錯退回名稱排隊）。守的是資料正確性——兩個最深層節點同名時，名稱帶不出任何資訊，
# 這是這條 bug 唯一能被證偽的地方（審查原話：構造上無法證偽）。已證紅：把 `creative.py`
# 的編號配對分支關掉，只有「照編號配」那個情境紅，兩條退路維持綠。
#
# 票 02-env-flag-and-settings（ADR 0062）：18919 → 19052（含本段理由註解自己佔的行）。
#
# 這道棘輪在這張票落地前就已經在漏，不是這張票撞出來的：main chat 在 `HEAD`＝`227db09`
# （這張票、ADR 0062、契約頁都在，程式碼還沒動）上量過，`app/tests/` 當時已經是 18948
# 行，比凍結值 18919 多 29 行——閘門紅著被人合併進主線，沒有人跑過它。這裡調高的數字是
# 「29 行舊債＋這張票自己新增的行」疊出來的，不是假裝棘輪從 18919 乾淨地長起
# （`docs/tech-debt.md` §六判準：新增的行數是不是這張票的交付物本身）——29 行是被這次
# 一起吸收，寫在這裡讓六個月後的人看得到「被吸收」而不是被誤讀成「都是這張票寫的」。
#
# 四處貢獻：
#   1. `test_identity_auth.py`——`Hs256StartupGuardTest` 改對 `app.core.config.settings()`
#      斷言（原本測 `register()`），加一條 `.env.example` 不該帶生效的 `BRAND_OS_ENV=local`
#      的斷言；新增 `BootCheckReportsAllViolationsTest`（本票 §6 點名的唯一一支新測試——
#      §3「開機檢查一次列出全部違規，不是抓到第一條就停」，這是唯一沒有既有測試覆蓋的
#      性質，故意不逐變數各開一支）。
#   2. `conftest.py`——`BRAND_OS_ENV=local` 的 setdefault（票面 §6 點名）；新增
#      `_fresh_settings` fixture：`app.core.config.settings()` 是行程層快取單例
#      （ADR 0062），但既有測試靠切換 os.environ（`ANTHROPIC_API_KEY`／`BRAND_OS_TODAY`……）
#      在同一個 worker process 看到不同結果——這支 fixture 是 `test_settings_api.py`／
#      `test_dashboard_overview.py`／`test_core_db_pool.py`（三個都在本票 done-check 1 的
#      名單裡）繼續綠的必要條件，是交付物本身，不是為了繞過閘門塞進來的行（`docs/tech-debt.md`
#      §六那句判準）。round 2 補一句：`DATABASE_URL` 不靠這支快取——`coredb.dsn()` 是
#      §5a 的 `config.database_url()`，每次呼叫都直接讀 `os.environ`——`_bound_connection`
#      因此不用再依賴 `_fresh_settings` 的執行順序，round 1 那個相依關係跟著拿掉。
#   3. 本表（`KNOWN_MODULE_SIZES`）兩筆棘輪調整（`app`／`app/core`）各自的理由註解——
#      票面 done-check 5 點名「量到的數字，不留餘裕，一行理由」；`app/identity` round 1
#      量對了，round 2 沒有再動這一筆。
#   4. 本段理由註解自己（含上面「這道棘輪在落地前就已經在漏」那一段，done-check 5 點名的
#      新要求）。
TEST_LINES_CEILING = 19283  # 票 06-meta-name-lookup-tenant-symmetry：兩支新測試
# （`test_meta_daily_spend.py` `AdSetParentCrossOrgRefusedTest`／`AdParentCrossOrgRefusedTest`
# ＋共用 fixture）——屬租戶隔離：`ad_set_ids_by_exact_name`／`ad_ids_by_exact_name` 拿到別的
# 組織已綁定的 campaign／adset id 時，必須在碰 Meta 之前就拒絕（斷言 403，且 patch 掉的
# `graph.list_ad_sets`／`graph.list_ads` 的 call_count 為 0——只斷言拒絕不足以證明「沒有拿
# 這個組織的權杖去打別人的 id」）。先證過紅：把兩個呼叫點換成 `pass`，兩支同時紅在
# 「ApiError not raised」。這幾行還含本段理由註解自己佔的行。量到的數字，不留餘裕。
# 前一次是 19208——上雲債兩張一起落地。兩筆新測試都在全域 CLAUDE.md 允許的四類裡：
# (1) route B「codex_cli 只准 local」的守門測試（`test_identity_auth.py`
# `CodexCliProviderIsLocalOnlyTest`，+26 行）——屬金額：`.env` 帶著這一行部署上雲，每一次 AI
# 呼叫都會去執行一支不存在的指令，功能安靜壞掉而帳面看起來「沒有花錢」。兩半都證：codex_cli
# 在 production 炸、別的供應商值不被誤傷（禁的是值不是變數）。先證過紅：把新那張表換成空
# tuple，測試立刻紅。
# (2) 票 04 `RowHashNumericNormalisationTest`（`test_orders_channel.py`，+40 行）——屬金額：
# `_row_hash()` 對 int／float 不穩定，第二個非-float 呼叫端一出現去重就靜靜失效，同一天的
# 營收落兩列＝翻倍。三支斷言（雜湊穩定／真的只落一列／只有 note 不同時仍落兩列，最後一支
# 擋掉「把雜湊改成回傳常數」的假解法）。先證過紅：拿掉兩行 float() 正規化，立刻紅。
# 這幾行還含本段理由註解與上面 `KNOWN_MODULE_SIZES["app/core"]` 那筆理由註解自己佔的行。
# 量到的數字，不留餘裕。前一次是 19120——票 03-worker-own-process round 3（ADR 0063 amendment「release the
# lock, so nothing depends on test ordering」）：零新測試（done-check 11 明講不用）——這幾行
# 全是上面 `KNOWN_MODULE_SIZES["app"]` 那筆理由註解和本段理由註解自己變長多出來的行。量到的
# 數字，不留餘裕。前一次是 19112——票 03-worker-own-process round 2（ADR 0063 amendment「one
# worker, and the database says so」）：done-check 8 點名的新測試
# `WorkerProcessTest.test_second_worker_lock_guard_leaves_a_live_running_row_alone`（money：
# 第二個 worker 拿不到鎖時不准把第一個 worker 活著、已經付費的 llm_task 列掃成 failed），
# 連同本段＋下面 `KNOWN_MODULE_SIZES["app"]` 理由註解自己佔的行。前一次是 19051——票 03
# round 1（ADR 0063）：WorkerLifespanTest 兩支換 WorkerProcessTest 一支


def _line_totals() -> tuple:
    """(production 行數, test 行數)。只算 app/ 底下的 .py，不含 __pycache__。"""
    production = tests = 0
    for path in _iter_py_files():
        n = len(path.read_text(encoding="utf-8").splitlines())
        if _rel(path).startswith("app/tests/"):
            tests += n
        else:
            production += n
    return production, tests


class TestRatioTest(unittest.TestCase):
    """測試的絕對行數，只准往下（ADR 0041）。

    測試是有人要維護的程式碼，寫得越多不等於越安全（全域 `CLAUDE.md` 測試四類）。
    這道閘門把那條原本只是散文的目標接上機器——憲章明文：「一個沒有閘門的數字不是限制」。

    量絕對行數而不是比值，是 2026-08-30 的裁決：比值會因為「刪掉 production 死碼」而
    被動上漲，逼人去調鬆閘門本身才能通過，等於懲罰刪碼。絕對行數只在「真的多寫了測試」
    時才紅，因果對得上。
    """

    def test_test_lines_only_go_down(self):
        production, tests = _line_totals()
        ratio = round(tests / production, 3) if production else 0
        self.assertLessEqual(
            tests, TEST_LINES_CEILING,
            f"測試行數從 {TEST_LINES_CEILING} 漲到 {tests}"
            f"（production {production} 行，比值 {ratio}，目標 0.7）。\n"
            "先問這條測試守的是哪一件事——金額、租戶隔離、API 契約、資料正確性，四者以外"
            "不寫（全域 CLAUDE.md 測試四類）；畫面行為只給 frontend/e2e/smoke.spec.ts "
            "那一支端到端煙霧測試，不寫單元測試。\n"
            "刪 production 死碼不會讓這道閘門變紅（那正是 2026-08-30 改掉比值版的理由）——"
            "會紅就代表測試真的變多了。真的該漲就改 TEST_LINES_CEILING 那一行、把理由寫在"
            "它上面，reviewer 會在 diff 裡看到。",
        )


# 凍結於外殼切片後的實測值（2026-08-29）。`app/` 底下每個套件一個項目，`app` 這一項
# 是頂層的 .py（`main.py` 組裝根等）。**允許調高，但必須改這張表**——重點不是禁止成長，
# 是讓成長出現在 diff 裡有人看得到。廣告模組會在約 2,000 行撞上它，而不是 21,595 行。
KNOWN_MODULE_SIZES = {
    "app": 624,  # 票 03-worker-own-process round 3（ADR 0063 amendment「release the lock, so
                  # nothing depends on test ordering」）：worker.py 的 main() 補 try/finally
                  # 釋放 advisory lock（只有真的拿到鎖的那次呼叫才釋放）＋module docstring
                  # 補說明段，96→119（+23），main.py 沒動，624 = 505+119。量到的數字，不留
                  # 餘裕。前一次是 601——票 03-worker-own-process round 2（ADR 0063
                  # amendment「one worker, and the database says so」）：worker.py 補 session
                  # advisory lock（借鎖／衍生 key／拿不到就印一行印繁體中文訊息回傳）＋
                  # __main__ 的 KeyboardInterrupt 收尾，45→96（+51），main.py 沒動，
                  # 601 = 505+96。前一次是
                  # 550——票 03-worker-own-process round 1（ADR 0063）：worker 搬進
                  # app/worker.py，550 = 505+45。前一次是 526——
                  # 票 02-env-flag-and-settings（ADR 0062）：`app/main.py` 在 `_load_dotenv()`
                  # 後加一次 `core_config.settings()` 開機檢查呼叫（import＋呼叫＋理由註解，
                  # +5 行）；round 2 順手修正「identity 排最後」那段理由註解——它原本說
                  # register() 會在 IDENTITY_DEV_TOKEN 設定錯誤時 raise，這道檢查已經搬進
                  # settings()，comment 沒跟著改就變成一句假話（+2 行，理由改寫更長）。這張票
                  # 明講 app 這一項應該縮小：調到量到的數字，不留餘裕——上一個凍結值 553 本來就
                  # 比量到的基準寬，這裡拉緊。前一次是 553——
                  # 2026-08-30 補上設定頁「測試連線」的月費上限（小債）：那顆按鈕真的會打一次
                  # provider，原本不經 run_task() 所以完全繞過上限。7 行＝import gateway ＋
                  # 打 provider 前先問 check_spend_cap()。前一次是本機 codex CLI 線路
                  # （c47bc36）的 546：main.py 依環境變數換供應商
    "app/background": 162,  # 票 03-worker-own-process（ADR 0063）：搬進 app/worker.py，272→162。前一次是 272——
                             # 票 05-1：新增 enqueue()（defer 一個 job，同一個 lock 已經在
                             # todo 排隊就回 False）＋模組私有的 `_sync_app_for_defer()`
                             # （接 SyncPsycopgConnector，不能借 app() 那顆 async connector
                             # 的 pool，理由見模組檔頭「enqueue() 為什麼要蓋第二個 App」）。
                             # 前一次是 215——2026-08-29 修 Windows 起不來：worker 移到自己
                             # 的執行緒／loop（已被 ADR 0063 取代——worker 現在是自己的
                             # process，不再是掛進既有 process 的執行緒）
    "app/brand_intelligence": 2060,  # 票 S2（ADR 0044 落地）：復原 learning_ledger 的寫入
                                      # 函式——`create_learning_ledger_entry` 逐字照抄
                                      # `git show 7e0697e^:app/brand_intelligence/repository.py`
                                      # 復原，加一支新讀者 `list_learning_ledger_by_source_reading`
                                      # 給接受畫面判斷哪幾條已經勾過（D11），連同
                                      # `SOURCE_TRACK_IMPORTED` 常數與理由註解共 82 行。
                                      # 前一次的凍結值 2634 早在這張票之前就已經高過真實
                                      # 行數——2026-08-30 票 04（commit 7e0697e）刪掉
                                      # learning_ledger／strategy_hypothesis 整條讀寫面
                                      # （那次淨減 290 行），這道棘輪只鎖「不得再超過凍結
                                      # 值」，縮小之後沒有人回頭調低過那個數字（同一份
                                      # ponytail：FileLineCapTest 上方「縮小後不強制回來
                                      # 調低數字」）。這裡照票 S2 的要求把表格對齊實測值，
                                      # 不是新增了 574 行。
    "app/brand_web": 2091,  # 2026-08-30 刪失效規則卡（小債）：autonomy 那張卡的兩處專屬
                             # 驗證跟著走。前一次是 2155
    "app/core": 1775,  # 上雲債 route B（codex_cli 只准 local）：`config.py` 多一張
                        # `_FORBIDDEN_VALUES_OUTSIDE_LOCAL`——既有兩張表是「有值就違規」，
                        # 這條需求是「只有 codex_cli 這個值違規、其他供應商合法」，形狀塞不下，
                        # 所以是第三張表＋三行迴圈（+9 行）。量到的數字，不留餘裕。
                        # 前一次是 1766——票 02-env-flag-and-settings（ADR 0062）：新增 `app/core/config.py`
                        # （136 行，pydantic-settings 集中讀取 10 個環境變數＋開機驗證一次＋
                        # §5a 的 `database_url()` 例外——DATABASE_URL 不進快取，理由跟
                        # `app/background.app()` 的比對機制寫在函式自己的 docstring 裡）；
                        # `db.py` 的 `dsn()` 改叫 `config.database_url()`，不是
                        # `config.settings().database_url`（+2 行，含理由）；`settings.py`
                        # 刪掉 `API_KEY_ENV_VAR`／`LLM_MODEL_ENV_VAR`（改讀 settings() 之後
                        # 沒有呼叫端了）與 `import os`（-3 行）。1630 → 1766（+136 行）。
                        # round 1 量成 1740，round 2 補 §5a 的 `database_url()` 例外後重量。
                        # 量到的數字，不留餘裕。前一次是 1630——
                        # 票 M2（ADR 0059）：`approval.py` 的 `approve()` 加一個必填參數
                        # `max_daily_amount`（沒有預設值，理由寫在函式自己的 docstring 裡）、
                        # INSERT／`write_audit` 各多帶一欄——1622 → 1630（+8 行）。量到的
                        # 數字，不留餘裕。前一次是 1622——
                        # 票 M1（ADR 0058）：settings.py 從 `today_for_org()` 抽出姊妹函式
                        # `org_timezone()`（時區容錯只留一份），`_approval_overspend()`
                        # 比對 approved_at／today 之前先讓兩者落在同一個時區——
                        # 1613 → 1622（+9 行）。量到的數字，不留餘裕。前一次是 1613——
                        # 票 R3c（ADR 0052）：db.py 補 `set_tenant_scope()`（SET ROLE +
                        # set_config + commit）、`_reset_pooled_connection()`（pool() 的
                        # reset= callback，票裡點名「全票最重要的一行」）、`Conn.rollback()`
                        # 補上兩個沉默失敗防線的理由註解與重放邏輯、`Conn.__slots__` 多一個
                        # `_tenant_org_id` 欄位——db.py 218 → 272（+54 行），app/core 其餘
                        # 檔案沒動，1559 → 1613 剛好對得上。量到的數字，不留餘裕（docs/
                        # tech-debt.md §6 的裁決同樣適用於這次）。前一次是 1559——票 R3b（ADR
                        # 0052）：settings.py 的三處 Vault 直接存取改走
                        # core_vault_read_secret／save_secret／delete_secret 三道以管理員身分
                        # 執行、只認自己組織 secret 的門，＋5 行（含理由註解）。
                        # **這次調高是使用者 2026-09-02 的明示裁決**：全域規則「不得為了讓閘門
                        # 由紅轉綠而放寬容忍清單」與這張表自己的說明「允許調高，但必須改這張表」
                        # 直接相撞，而 app/core 當時正好卡在凍結值上、任何一行新增都是紅的。
                        # 裁決＝調高、寫理由、**調到量到的數字不留餘裕**（留餘裕等於廢掉棘輪）。
                        # 同一件事在 docs/tech-debt.md 有一條，下一個撞到的人不必重跑這段對話。
                        # 前一次是 1554——票 storage-04：素材資料夾設定退役，整支模組檔（131 行）連同
                        # main.py 的呼叫端一起刪。前一次是 1687——
                        # 2026-08-30 刪失效規則卡（小債）：rule_cards.py 的 6 張卡（budget_structure／
                        # sample_size／ad_creative_fatigue／pacing／health_lights／autonomy）隨
                        # app/ads/ 失去全部呼叫端，設定頁照樣顯示照樣可調＝使用者看得到的謊；
                        # 連 fatigue_level()／sample_size_verdict() 兩支零呼叫端純函數一起刪。
                        # 前一次是 2148
    "app/dashboard": 645,
    "app/identity": 529,  # 票 02-env-flag-and-settings（ADR 0062）：舊的「用 urlparse 判斷
                          # SUPABASE_URL 主機名」那支私有函式整支刪掉（判斷邏輯搬進
                          # app.core.config，這裡不再需要）；`register()` 的兩段 RuntimeError
                          # 啟動檢查搬進 `app.core.config.settings()`，只剩掛路由；
                          # `authenticate()` 的 dev_token 比對、`create_invite()` 的 `local`
                          # 旗標改讀 `settings()`（各加一行 import 抵銷一部分）。淨減。量到的
                          # 數字，不留餘裕。前一次是 539——
                          # 票 identity-hs256-startup-guard：`_is_local()` 從 routes.py 搬進
                          # __init__.py（兩個呼叫端共用同一份定義，不留第二份），register()
                          # 新增 IDENTITY_ALLOW_HS256 的啟動檢查，跟既有 IDENTITY_DEV_TOKEN
                          # 那道同形狀。前一次是 537（外殼切片凍結值）。
    "app/intake": 3571,  # 本機 codex CLI 線路（c47bc36）：card_test.py 診斷工具跟著印出這次
                          # 真正跑的供應商。前一次是 3570——
                          # 缺陷 1：intake_question 改走強制工具結構化輸出，新增
                          # _QUESTION_TOOL／_CHOICE_SCHEMA schema（散文裡的 JSON 格式
                          # 說明同時刪掉，仍淨增）。前一次是 3548
    "app/llm": 1482,  # 票 S2：providers.py 的 TASK_TYPE_LABELS／TASK_DEFAULTS 各補一行
                       # "onboarding_read"（跟既有三個排程任務同一組 thinking="high"，理由見
                       # `app/llm/providers.py` 該行註解），淨增 6 行。前一次的凍結值 1619
                       # 早在這張票之前就已經高過真實行數——2026-08-30 票 04（commit
                       # 7e0697e）同一次刪掉 learning_ledger／strategy_hypothesis 時，
                       # `context_compiler.py` 的【已驗證的學習】整節（兩個表的讀取面，
                       # 從沒有過真的呼叫端）也一起刪掉，那次淨減 167 行；這道棘輪縮小後
                       # 沒有人回頭調低過凍結值（同上，FileLineCapTest 的 ponytail 說明）。
                       # 這裡照票 S2 的要求把表格對齊實測值，不是新增了 137 行。
                       # 票 01：providers.py 的 TASK_TYPE_LABELS／TASK_DEFAULTS 各補一行
                       # "schedule_creative"（跟既有的 schedule_plan／schedule_tree 同一組）。
                       # 前一次是 1617——
                       # 2026-08-30 月費上限抽成 check_spend_cap()（小債）：算法原本寫死在
                       # run_task() 裡，設定頁「測試連線」繞過去了；抽成一支共用函式，第三個
                       # 呼叫端才不會又悄悄繞開。前一次是 1605——
                       # 本機 codex CLI 線路（c47bc36，使用者 2026-08-29 裁決調高明表）：
                       # CodexCliProvider 是 `Provider` 這個單方法 Protocol 的第三種實作
                       # （ADR 0032），265 行在 providers.py——prompt 攤平、圖片還原成暫存檔、
                       # Windows 程序樹逾時清理、截斷偵測；gateway/pricing 各補訂閱額度
                       # 不計費的分支。開發期不打 API 帳單靠這條線，正式版仍走 Anthropic。
                       # 前一次是 1311——
                       # 缺陷 1／2：parse_json_reply 換成 raw_decode 單錨點（含為什麼不能
                       # 退而求其次的理由註解）＋timeout_s 300 秒與 max_retries=0 兩段
                       # 來源註解（實測列號、SDK 常數位置）。前一次是票 09 的 1298
    "app/meta": 1659,  # 票 S2b B1（2026-08-31）：1646 → 1659。多的 13 行是
                       # `conversion_action_types()` 這一支存取子加它的理由註解——B1 的
                       # 「這個桶裡轉換最高的那一天」要用的「轉換」定義，必須跟 CPA 分母
                       # 的 `_CONVERSION_ACTION_PRIORITY` 是同一份。開一支存取子讓
                       # app/schedule 讀這一份，比在那邊抄第二份對照表便宜也安全：同一份
                       # 提示詞裡「轉換」有兩種定義的話，模型看到的 CPA 跟被挑出來的那
                       # 一天會來自兩套算法，而那種矛盾從輸出上完全看不出來。零新測試。
                       #
                       # 前一次是 1646——票 S2 實機驗收（第二件）：`campaign_ids_with_rows()`——真帳號
                       # Meta 列得出 58 個活動，這段期間有數字的只有 24 個，剩下 34 個
                       # 派分析師過去只會拿到空 CSV。呼叫端用這支把派工單篩過，被篩掉的
                       # 活動照票 S2 §1 報出來、不靜靜跳過。前一次是 1622——
                       # 票 S2 實機驗收：`_HISTORICAL_STATUSES` 拿掉 `DELETED`，上面補一段
                       # 實測紀錄——官方三個 edge 的參考頁都把 `DELETED` 印在枚舉裡，但
                       # 2026-08-31 對真帳號打 v26.0，三層只要陣列出現 `DELETED` 就回
                       # code 100／subcode 1815001「Invalid parameter」，拿掉就全部正常。
                       # 文件與實際行為不一致時以實際為準，量測寫在程式旁邊，免得下一個人
                       # 照文件又加回去。前一次是 1610——
                       # 票 S2：graph.py 新增 `list_entities`（三層物件端點，含逐頁查證的
                       # `effective_status` 官方枚舉值與 JSON 陣列編碼理由）與
                       # `list_ad_creatives`（逐廣告打文件記載的 per-ad edge，不用未證實的
                       # `?ids=` 批次或欄位展開語法）；repository.py 新增五支只讀
                       # `meta_entity_spend` 的函式（`entity_rows`／`entity_action_totals`／
                       # `spend_date_bounds`／`spend_dates_with_data`／
                       # `attribution_windows_in_range`，D6／D7）。多出來的行數大半是「文件
                       # 只證實了什麼、沒證實什麼」的理由註解，不是邏輯本身變複雜。
                       # 前一次是 1323——
                       # 2026-08-30 票 S1 審查缺陷修正（money）：cpa 從 `_RATE_METRICS`
                       # 抽成自己的 `_CPA_METRIC`，補上 roas 已經有的 `bool_and` 保護——
                       # `_CONVERSIONS_LATERAL` 對不上 action_type（含 actions 本身是 SQL
                       # NULL）時 `conv.conversions` 是 SQL NULL，SUM() 會跳過它不當 0 加總，
                       # 沒有這條保護，一天「有花費、沒追蹤到轉換」的花費照樣進分子、卻不
                       # 進分母，印出一個過度樂觀的假 CPA（GRILL 決定1(d)／SPEC §3.3：560
                       # 個有花費的廣告日只有 191 天有 purchase_roas，這是常態不是邊角案例）。
                       # 兩處呼叫端（逐實體、總計）都要接上；順帶把 `_RATE_METRICS` 上方、
                       # `spend_summary` docstring 裡「這四個不套用 bool_and」的舊說法改成
                       # 「ctr／cpc／cpm 不套用，cpa 要套用」。多出來的行數大半是理由註解。
                       # 前一次是 1300——
                       # 2026-08-30 票 S1（三層成效）：`meta_campaign_spend` → `meta_entity_
                       # spend`，graph.py 的 `list_campaign_insights` 換成三層共用的
                       # `list_entity_insights`／`_to_entity_row`（含 37→13 個月陷阱、
                       # 歸因窗常數的理由註解）；repository.py 的 `spend_summary` 加
                       # `level`（必填）與 `conversion_goal`（新關鍵字），新增 ctr／cpc／
                       # cpm／cpa 四個算式與 CPA 的 LATERAL join（含為什麼不能直接 join
                       # jsonb_array_elements 的實測理由）。多出來的行數大半是理由註解，
                       # 不是邏輯本身變複雜。前一次是 875——
                       # 2026-08-30 票 S0：`_fetch_all_pages` 擞到 `_MAX_PAGES` 改成拋例外、
                       # 不再回一份殘缺的清單（＋11 行，十行是為什麼不能默默截斷的理由與實測值；
                       # 程式本身是 `break`→`return` 加一句 raise）。前一次是 864——
                       # 2026-08-30 票 04-1b 組織時區：`_pull_one_account` 與 brand_spend 的
                       # 「今天」改問 `today_for_org()`（＋9 行，全是為什麼不能用 UTC 的理由
                       # 註解；程式碼本身是換掉兩行）。前一次是 855——
                       # 票 11 缺陷修正（2026-08-29 對真帳號實測）：名稱比對改讀平台上的活動
                       # 清單——graph.list_campaigns()＋_to_campaign()（28 行，含為什麼不能
                       # 讀 insights 的理由），campaign_ids_by_exact_name() 換成逐帳號比對
                       # ＋連不上 Meta 時回人話 502。前一次是 805——
                       # 票 11：campaign_ids_by_exact_name()（名稱精準比對，13 行）＋
                       # spend_summary 改成只按 campaign_id 分組（活動月中改名不再裂成
                       # 兩列各拿半個月花費，8 行含理由註解）
    "app/orders": 1423,  # 票 12：channel_revenue 一張表取代三張（刪掉藥局專屬那一整組
                          # 之後仍淨增）——官網帳本寫入路徑、channel_revenue_summary()、
                          # 通用手動登錄（含「官網不能手動登錄」那道錢的守門）
    "app/schedule": 3489,  # 真瀏覽器驗收兩個 bug（2026-08-31）：3461 → 3489。POST 建立讀取
                           # 之後，回應必須是**這一次**剛派出去的讀取——原本結尾
                           # `return brand_response(...)` 是去資料庫查「最新讀取」，而那幾列
                           # 要等 worker 跑起來才寫得進去，所以按下「重新開始讀取」當下回的
                           # 是上一次那份已完成的，畫面看起來像沒反應、人再按一次吃 409。
                           # read_id 本來就在那支函式手上。順手把讀取的 API 形狀抽成
                           # `_read_payload()` 一份（兩個呼叫端各組一次同一個字典必漂移）。
                           #
                           # 前一次是 3461——票 S2b B1＋完整性審查三件 major（2026-08-31）：3155 → 3461。
                           # 這是**淨**增加——同一批改動先刪掉了 `daily_csv()` 與
                           # `_daily_cell_value()` 共 69 行（`bucketed_csv()` 取代它們，
                           # 沒有第二個呼叫端，留著就是會漂移的死碼）。
                           #
                           # 加的東西：(1) B1／ADR 0045 的時間分桶——`time_bucket()`（週末
                           # 絕不跟平日併，這條規則連同理由只活在那一行）、`bucketed_csv()`
                           # 與它的 `_bucket_row()`／`_outlier_row()`／`_bucket_roas()`／
                           # `_action_sums()`／`_outlier_days()`／`_conversion_count()`；
                           # (2) `coverage_text()` 逐個實體點名整個窗口沒資料的桶——ADR
                           # 0045 原句要空桶各佔一列，2026-08-31 拿真帳號量過改成點名
                           # （195 實體 × 24 桶有 83% 是空的，照原句做列數從 3,531 漲到
                           # 5,702，B1 存在的理由當場消失；改動寫進 ADR 0045 自己那一節）；
                           # (3) 完整性審查三件 major：保險絲理由跟著回傳值走（四條路各有
                           # 各的理由，原本共用一句真帳號 34 次裡 27 次是假的話）、
                           # `unpaired` 分支補印 media_ids（69/158 則素材原本一個都沒印）、
                           # A1 註記行拿掉假的完整性宣稱。
                           #
                           # 這些行絕大多數是理由註解與 docstring 本身：`bucketed_csv()`
                           # 那族的函式本體加起來不到 120 行。
                           #
                           # 前一次是 3155——票 S2b A4 完整性審查回應第三輪（2026-08-31，真帳號
                           # 368741390835357，三個獨立審查者 realdata／fuse／gate 逐一
                           # 量到、上一輪綠燈閘門一樣守不住的資料正確性缺陷）：
                           # 3028 → 3155。修八個問題，全部根因修法（同一個 bug 出現在
                           # 兩個呼叫端的，只改共用函式，不逐一補丁）：`_STORY_SHAPES`
                           # 補上 `template_data`（第四種真實形狀，25/158 則素材）；
                           # 「這個形狀有沒有讀到東西」的判斷式一併看
                           # `child_attachments`，不再只看外層 body／title；CTA 在
                           # `_STORY_SHAPES` 分支跟 `asset_feed_spec` 分支都退回素材最
                           # 外層的 `call_to_action_type`（86/158 則廣告的 CTA 只在那裡
                           # 有）；`asset_customization_rules` 分組完之後斷言涵蓋率，
                           # body／title 資產沒被任何規則引用到就整組回空清單讓保險絲
                           # 接手（真帳號驗證過 label 解析法在這個帳號上讀不懂真配對，
                           # 不是試著解得更聰明）；`asset_feed_spec` 只有一邊
                           # bodies／titles 時，用素材最外層同名欄位補另一邊
                           # （35/158 則廣告）；新增共用的 `_extra_lines()`，
                           # `_unpaired_variant_lines()` 跟 `_ad_fact_card()` 都改叫
                           # 它——`extra` 的清單值（`descriptions`）原本直接塞進
                           # f-string 印成 Python `repr()`，帶換行的文案就不是逐字；
                           # 廣告組卡片加 `age_range`／`targeting_automation.
                           # advantage_audience`（30/50 個廣告組開了受眾擴張，
                           # age_min／age_max 因此被灌成平台上限）、
                           # `behaviors`／`industries`／`work_positions`
                           # （27/50 個廣告組帶了其中之一，原本完全沒被收集）、
                           # `excluded_product_audience_specs` 併入 exclusion_count；
                           # `totals_text()` 補上 `_ad_fact_card()` 那族已經在用的
                           # `_blank_or()`（真帳號 24 個活動 194 行指標原本全部印出裸的
                           # Python `None`）。多出的 127 行：八處修法本身（含新增的
                           # `_flexible_spec_items()`／`_flexible_spec_line()`／
                           # `_extra_lines()` 三支共用函式）＋各自的審查說明 docstring／
                           # 行內註解＋這筆理由本身；`onboarding_slice_totals.py` 因此
                           # 新增一個 cross-file import（`_blank_or`，見那個檔案自己的
                           # docstring）。
                           # 前一次是 3028——票 S2b A4 完整性審查回應第二輪（2026-08-31，真帳號
                           # 368741390835357）：2981 → 3028。修兩個第一輪審查沒抓到、
                           # 綠燈閘門一樣守不住的問題——`asset_feed_spec` 沒有
                           # `asset_customization_rules` 那個分支（真帳號 158 則素材
                           # 92 則是這個形狀，最常見的一種）原本把每個 body／title 各自
                           # 印成一則帶 `title：（無）`／`media_ids：[]`／
                           # `placement_count：1` 的假變體，三個欄位全是編出來的結構，
                           # 不是 Meta 給的事實；改成 `unpaired` 標記＋
                           # `_unpaired_variant_lines()` 印成兩份逐字清單＋一句配對規則
                           # 的說明。`_round_sig_figs()` 磨一個 ≥ 1000 的大數字（誇張的
                           # ROAS／CPM）留下的 Decimal 內部指數是正的，`str()` 印出來是
                           # `1.23E+3`，跟這支函式自己 docstring 講的「不會像 float 那樣
                           # 印成科學記號」正好相反——上一輪只修了小數字那半。多出的
                           # 47 行：兩處修法本身（`_creative_variants()` 沒有規則那個
                           # 分支、`_ad_fact_card()` 加 `_unpaired_variant_lines()`
                           # 分支、`_round_sig_figs()` 加一行重建）＋各自的審查說明
                           # docstring／行內註解＋這筆理由本身。
                           # 前一次是 2981——
                           # 票 S2b A4 完整性審查（2026-08-31，真帳號 368741390835357）：
                           # 2933 → 2981。修兩個綠燈閘門守不住的資料正確性 bug——
                           # `_resolve_labelled_asset()` 原本拿 AdAssetLabel 物件直接跟
                           # 字串比對，字典永遠不等於字串，這個帳號 23 則
                           # asset_customization_rules 素材全部因此掉進保險絲（量到
                           # 147,946 字元原始 JSON，改完只要 14,829）；`asset_feed_spec`
                           # 原本讀 `call_to_actions`（Meta 從不回這個鍵）又完全沒讀
                           # `descriptions`，CTA 永遠是 None、77 則素材的逐字說明悄悄
                           # 消失。多出的 48 行：兩段各自的審查說明（`_resolve_labelled_
                           # asset()` docstring／`_creative_variants()` 讀 cta_types／
                           # descriptions 那幾行行內註解）＋這筆理由本身。
                           # 前一次是 2933——
                           # 票 S2b（拆檔，二次）：2891 → 2933。`onboarding_slice.py`
                           # 頂到 `FILE_LINE_CAP = 800`（765 行，A1～A4 陸續加完），先拆
                           # 再讓 B1 加：拆成三個各自獨立的家族——結構與素材事實卡留住
                           # `onboarding_slice.py` 這個檔名（351，往後 A4 收尾多半落在
                           # 這裡，留最多餘裕）；期間總計／涵蓋範圍搬去新檔
                           # `onboarding_slice_totals.py`（189）；逐日 CSV／實體對照表／
                           # 四捨五入搬去新檔 `onboarding_slice_csv.py`（265）。函式本體
                           # 一行沒改，只動了檔案歸屬、import 跟三份 docstring；多出來的
                           # 42 行是兩份新檔各自的檔頭（含這行理由本身）跟 import 陳述式。
                           # 前一次是 2891——
                           # 票 S2b A4 審查回應（四位獨立審查者對同一份 diff）：2726 → 2891。
                           # 補回審查抓到的幾處真的漏資料：`_adset_fact_card()`／
                           # `_ad_fact_card()` 補回 `effective_status`／`optimization_goal`／
                           # `billing_event`（`app/meta/graph.py` 本來就打這幾個欄位回來，
                           # A4 漏接了，PAUSED／ARCHIVED 的實體因此跟正在跑的長得一模一樣）；
                           # `_creative_variants()` 改成 `_STORY_SHAPES` 逐形狀對欄位名
                           # （`video_data` 的標題鍵是 `title` 不是 `name`，原本讀錯鍵讓
                           # 影片廣告的標題整個消失、印出 `title：None`）、加輪播
                           # `child_attachments` 逐卡片抽變體、`asset_feed_spec` 沒有
                           # `asset_customization_rules` 時也能抽（最常見的 Advantage+
                           # 形狀，原本一律退保險絲）、任何一條版位規則對不到 label 就讓
                           # 整組退保險絲（不再只送對得到的那幾條）、media_ids 改成跨規則
                           # 聯集（原本只留第一條規則的）、object_story_spec 與
                           # asset_feed_spec 兩邊都帶文案時退保險絲（不再只印一半）；
                           # `_zero_sum_split()` 把「有回報但沒給數字」改進 unprovable
                           # （原本被 `setdefault` 偷渡成 0，跟這支函式自己要擋的
                           # blank→0 是同一種錯），並改用絕對值加總判斷有沒有活動（一筆
                           # 全額退款不再被講成「這個窗口沒有這個事件」）；
                           # `entity_dictionary_text()` 改用窗口內最後一次出現的名字
                           # （原本取第一次，實體改名時新名字會消失），分隔符改成跟
                           # `coverage_text()` 一致的 `[level] name（id）`（原本的 `｜`
                           # 是台灣廣告命名常見字元，會撐爆成分不清楚的欄位）；
                           # `_adset_fact_card()` 的興趣去重改用 (id, name) 當 key（原本
                           # 只用 id，沒有 id 的興趣全部收斂成同一把，honesty counter 卻
                           # 沒有跟著少算）；CPM／CPC 改走 `_round_money`（原本誤用
                           # `_round_sig_figs`，磨掉的精度跟 Ads Manager 顯示的對不上）；
                           # `_round_money`／`_round_sig_figs` 全程留在 `Decimal`（原本轉
                           # `float`，四捨五入到分可能差一分錢，小數字會印成科學記號進
                           # CSV）。`app/departments/ads/onboarding_read.md` 也跟著改
                           # （不計進這個數字，那個檔不是 .py）：「外殼不會改寫或摘要，
                           # 你看到的就是全部」這句話已經不成立，改成如實列出外殼真的做
                           # 了哪幾種形狀變動。一個字沒放寬任何既有規矩——全部是補回原本
                           # 該有、A4 漏接的資料，或修掉會把「無法證明」印成「證明是 0」
                           # 的邏輯錯誤，沒有新增任何摘要或臆測。前一次是 2726——
                           # 票 S2b A4（創意與受眾攤成事實卡）：2554 → 2726。
                           # `onboarding_slice.py` 428 → 600：`structure_text()` 從整包
                           # `json.dumps(indent=2)` 改成一個廣告組一張受眾卡、一則廣告一張
                           # 素材卡（2026-08-31 實機驗收量到舊寫法一個活動 97,220 字元）。
                           # 新函式：`_classify_audience_type()`（lookalike／retargeting／
                           # interest／prospecting 四選一，帶 `ponytail:` 標明是啟發式、
                           # 非 Meta 欄位）、`_adset_fact_card()`（受眾型態／前 10 個興趣＋
                           # 「還有 N 個未列出」／geo_locations／age_min／age_max／genders／
                           # exclusion_count，全部沿用 Meta 自己的鍵名，不新造友善名字）、
                           # `_resolve_labelled_asset()`（`asset_feed_spec` 用 adlabels 名字
                           # 間接對應，不是位置對位）、`_creative_variants()`（依序試
                           # `object_story_spec`／`asset_feed_spec`+`asset_customization_rules`
                           # ／素材最外層 `body`／`title` 三種已知形狀，同一份文案被好幾條
                           # 版位規則共用時分組回傳 `placement_count`，講清楚幾條規則共用，
                           # 不是每條各印一次；三種都抽不出 body 也抽不出 title 就回空清單）、
                           # `_ad_fact_card()`（呼叫端看到空清單就點火保險絲，原始素材 JSON
                           # 原封不動送出——票明講三個獨立審查者都要求這條，寧可貴不可漏）。
                           # `app/tests/test_onboarding_read.py` 新增一支
                           # `CreativeFuseSendsRawJsonOnUnexpectedShapeTest`（見下面
                           # `TEST_LINES_CEILING` 的理由）。**一個字都沒放寬既有規矩**：
                           # 保險絲是新增的安全網，不是砍掉任何一種原本讀得到的欄位；
                           # `targeting` 原始形狀不再整包塞給模型，但地理／年齡性別／興趣／
                           # 排除數這些欄位裡的內容一個字沒少，只是從一包 JSON 攤成講人話
                           # 的卡片。前一次是 2554——
                           # 票 S2b A2（每個實體的涵蓋範圍，外殼算好的）：2465 → 2554。
                           # `onboarding_slice.py` 349 → 428：新函式 `coverage_text()`（一個
                           # 實體一行，窗口天數／有資料天數／有花費卻沒 ROAS 的天數／首末
                           # 有資料／最長缺口，全部 Python 算好，不問模型——ADR 0045 把這兩個
                           # 涵蓋數字訂成未來時間分桶的先決條件）＋ `_longest_gap()`（缺口
                           # 計算涵蓋整段 `since`～`until`，不是只看第一筆到最後一筆資料
                           # 之間，這樣缺口落在窗口最前面或最後面也算得到），兩支都帶
                           # docstring 講清楚為什麼要收 `roster` 這個新參數。`onboarding.py`
                           # 呼叫端 590 → 600：組 `roster`（campaign 自己＋它的 adsets／ads，
                           # 不是只有 `rows` 裡真的有資料的那幾個，這樣一列資料都沒有的實體
                           # 才不會從涵蓋範圍那段消失）、呼叫 `coverage_text()`、`segment4`
                           # 清單裡多塞一個元素。**一個字都沒放寬既有規矩**：這是新增資訊，
                           # 不是砍任何東西，`totals_text()`／daily CSV 內容一個字沒動。
                           # 前一次是 2465——
                           # 票 S2b A3（實體對照表＋誠實精度）：2382 → 2465。
                           # `onboarding_slice.py` 269 → 349（新函式 `_round_money()`／
                           # `_round_sig_figs()`／`entity_dictionary_text()`／
                           # `_daily_cell_value()` 各自帶 docstring 講清楚「為什麼是分／
                           # 有效數字」跟「為什麼非 0 不會被磨成 0」；`daily_csv()` 從三元組
                           # 改回傳四元組，多出的第一個元素是實體對照表文字，資料列拿掉
                           # `entity_name`／`level` 兩欄；`totals_text()` 的花費／CTR／CPC／
                           # CPM／ROAS／CPA 六個數字全部套用同一組四捨五入）；`onboarding.py`
                           # 呼叫端 587 → 590（多接一個變數、`segment4` 改成用 filter 濾掉
                           # 空字串再組，因為 `entity_dict_text` 在整個活動一列資料都沒有時
                           # 會是空字串，不該留一段空白落在提示詞裡）。**一個字都沒放寬既有
                           # 規矩**：blank≠0、null≠0 兩條規矩原封不動；新增的四捨五入明文
                           # 保證「非 0 不會被磨成 0、`None` 不會變成 0」，是加一條規矩，不是
                           # 取代任何一條。前一次是 2382——
                           # 票 S2b A1（省掉整個窗口加總是 0 的 action 欄位，並在期間總計
                           # 那一行點名省了什麼、送了什麼）：2314 → 2382。`daily_csv()` 從
                           # 回傳一份字串改成回傳 (csv, 送出的欄位, 省掉的欄位)；新函式
                           # `_zero_sum_split()` 先加總才判斷是不是 0（assert 先、才能砍），
                           # 加總不出來的值當「無法證明是 0」留著送；`totals_text()` 多兩個
                           # 參數把這兩份名單印成一行，不在那裡重算一次。多的 68 行大宗是
                           # 這幾支函式和它們新增的 docstring（解釋「加總是 0」跟「整欄從
                           # 沒出現過」是兩件不同的事），`onboarding.py` 呼叫端跟著改。
                           # **一個字都沒放寬既有規矩**：blank≠0 那條規矩原封不動，這裡新增
                           # 的是另一條「證明是 0 才能砍」的規矩，不是取代它。前一次是 2314——
                           # 票 S2b 步驟 0（純搬移，不是新行為）：`onboarding.py` 當時
                           # 768 行、`FILE_LINE_CAP` 是 800，只剩 32 行餘裕，而 S2b 的
                           # A1～A4 與 B1 改的就是 segment [4] 那一族函式。七支搬進新的
                           # `onboarding_slice.py`（768 → 583），淨增的 20 行全部是新檔的
                           # 檔頭 docstring 與它自己的 import——一行函式本體都沒改，只有
                           # 函式名去掉開頭底線（它們現在是跨檔接口，底線原本的意思是
                           # 「這一檔私有」，已經不成立）。前一次是 2294——
                           # 票 S2 實機驗收（第三件，這是真的打過才看得見的缺陷）：
                           # `_daily_csv` 把 `actions`／`action_values` 攤平成欄位。原本
                           # 每一列塞一段原始 JSON，一個 722 列的活動組出 2,735,699 字元、
                           # 整份提示詞 2.1 MB，撞破本機 codex CLI 的 1,048,576 字元輸入
                           # 上限，24 個活動裡有 4 個整批讀不到。攤平之後同一份資料是
                           # 236,696 字元（11.6 倍），一天不刪、一個節點不省——SPEC §4
                           # 允許的正是這種「只改形狀不改內容」。多的行數大半是那段
                           # 實測理由與 `ponytail:`（再撞上限時的下一步是把工作項切成
                           # 一個廣告組，不是開始丟資料）。前一次是 2230——
                           # 票 S2 實機驗收（第二件）：dispatch 只派給「這段期間真的有
                           # 數字」的活動，沒有數字的進 `campaigns_without_numbers`，
                           # 提示詞（模型要知道自己看到的是子集合）與 API 回應（畫面要
                           # 看得見）各多一段。前一次是 2202——
                           # 票 S2 實機驗收第一次真的打 Meta 撿到的：`CAMPAIGNS_NOTE` 從
                           # 一行變三行——已刪除的活動 Meta 根本不讓我們列（實測見
                           # `app/meta/graph.py` 的 `_HISTORICAL_STATUSES`），報告表頭
                           # 那句誠實聲明因此要講得更精確，不能只說「不是全部」。
                           # 前一次是 2198——
                           # 票 S2 審查回應：`accept_conclusions()` 的 docstring 多一段
                           # `ponytail:`（13 行）——把「冪等是先查再寫、不是資料庫保證」這個
                           # 上限寫明白：沒有唯一索引，兩個同時進來的 accept 會各寫一列，而
                           # 重複的列會對下一期企劃謊稱「這條被觀察到兩次」（ADR 0044）。
                           # 修法是加唯一索引，而 ADR 0044 明文不准這張票動 schema，所以是
                           # 寫下來、不是蓋掉。前一次是 2185——
                           # 票 S2：兩個新檔——`onboarding.py`（dispatch＋fan-in＋
                           # procrastinate task body，同一個檔案兩種角色的理由見該檔檔頭）
                           # 與 `onboarding_routes.py`（第二個 `APIRouter`，不擠進已經在
                           # `FILE_LINE_CAP` 邊上的 `routes.py`，見該檔檔頭）；`__init__.py`／
                           # `jobs.py` 各補幾行掛第二個 router、第四個 task。前一次是 1462——
                           # 2026-08-30 票 S1：`_fill_node_spend`／`_approval_overspend`
                           # 呼叫 `meta_repo.spend_summary` 改傳 `level="campaign"`（三層
                           # 共用一張表之後，忘記篩層級會把 adset／ad 層的花費也算進來），
                           # 讀回應的鍵從 `summary["campaigns"]`／`c["campaign_id"]` 改成
                           # `summary["entities"]`／`e["entity_id"]`——10 行全是這兩處呼叫
                           # 端的理由註解。前一次是 1452——
                           # 票 05-1 fix round 1（money）：`schedule_tree`／
                           # `schedule_creative` 過去在 job 執行時用 `_latest_task_row()`
                           # 重讀「這個品牌最新一次」來源列——frozen decision 3 的
                           # 「一次一個」是按 task type 算的，擋不住兩種工作交錯排隊那段
                           # 窗口，job 真的跑到時可能撿到別種工作插隊留下的新 running
                           # 列，照著錯的（甚至空的）內容打代理，花錢。改成 enqueue 當下
                           # 把來源列 id 釘進 job 參數（`plan_task_id`／`tree_task_id`），
                           # job 只認這個 id。前一次是 1433——
                           # 票 05-1：三個生成端點不再在 request 裡打代理（POST 只驗證＋
                           # enqueue＋409），真正打代理的程式碼搬進新檔 jobs.py（含
                           # register_tasks()）——routes.py 淨減（798 → 661 行），jobs.py
                           # 新增 265 行，套件總數淨增。前一次是 1288——
                           # 2026-08-30 票 04-1b 組織時區：`_current_month_window()` 收
                            # (conn, org_id)、`_approval_overspend()` 的今天改問
                            # `today_for_org()`（＋3 行）。前一次是 1285——
                            # 2026-08-30 scope_ref 修正：改存被核准那棵樹的 id（＋2 行註解，
                            # 說明「簽的是哪一份」與「還是不是同一份」是兩件事）。前一次 1283
                            # ——票 01（approval-slice，ADR 0040）：核准端點＋金額／雜湊／超支
                           # 三個業務函式，`app/core/approval.py` 只管落地。前一次是 1145——
                           # 票 01（`.scratch/creative-slice/issues/01-ad-creative-per-ad-node.md`）：
                           # 第三個 task_type「schedule_creative」——app/schedule/creative.py
                           # 新檔（build_creative／creative_from_task_row，96 行）＋
                           # routes.py 的 POST .../creative、_run_creative()、
                           # _leaf_ad_node_names()／_creative_ad_node_names()、_brand_response()
                           # 多回一個 creative 鍵。前一次是 933——
                           # 2026-08-29：選定的產品名稱進 prompt（_validate_products() 改回傳
                           # 名稱、_plan_params_text() 多列一行）——沒有這 10 行，勾產品對代理
                           # 完全沒有作用，因為品牌上下文只吐「已確認的事實」。前一次是 923——
                           # 2026-08-29 修「畫面吐 [object Object]、活動樹算好的結果被下一次
                           # 嘗試蓋掉」（53c285e）：_display_task_row() 正在跑的時候繼續顯示
                           # 上一次成功的樹，另外標明有一次在跑。前一次是 883——
                           # 票 11：POST .../tree/bind（名稱比對、存平台 id、之後一律靠 id
                          # 讀數字）＋_fill_node_spend()／_current_month_window()（把票 05
                          # 的當月花費補到綁定節點上）＋tree.py 三個新欄位。前一次是票
                          # 10-feedback-entries 的 POST .../reject（784）
    "app/shared": 450,
    "app/storage": 163,  # 票 storage-01：新模組——put／get／delete／delete_prefix 四函式，
                          # 對 Supabase Storage 的 assets bucket（ADR 0043）。
                          # `_list_v2` 補 cursor 分頁（實測 2026-08-30，105 個物件、limit
                          # 10）：第二頁不帶上一頁的 `nextCursor` 當 `cursor`，API 會原地回
                          # 同一頁，不會往前走——單靠「hasNext 為真就重打同一個 body」會
                          # 卡死或漏物件。前一次是 154。
    "app/tools": 70,  # 票 03（ADR 0063）：spawn worker，58→70。2026-09-04 刪死碼 capacity_check.py（260
                       # 行，零呼叫端，服務已刪除的 Jinja／app/ads 舊 UI）。前一次是 318
}


def _module_sizes() -> dict:
    """{套件: 行數}。`app/tests/` 不算（測試由 TestRatioTest 管，且 800 行上限對它豁免）。"""
    sizes: dict = {}
    for path in _iter_py_files():
        rel = _rel(path)
        if rel.startswith("app/tests/"):
            continue
        parts = rel.split("/")
        module = f"{parts[0]}/{parts[1]}" if len(parts) > 2 else parts[0]
        sizes[module] = sizes.get(module, 0) + len(path.read_text(encoding="utf-8").splitlines())
    return sizes


class ModuleSizeRatchetTest(unittest.TestCase):
    """每個套件的行數凍在現況：長大要改上面那張表，改動就會出現在 diff 裡。

    跟 `KNOWN_OVERSIZED_FILES` 同一個形狀（凍結現況、只能改明表），全域規則「不得為了讓
    閘門由紅轉綠而放寬容忍清單」同樣適用於它——調高的那一次要說得出理由。
    """

    def test_no_module_grows_past_its_frozen_size(self):
        problems = [
            f"  {module}：{size} 行，比凍結值 {KNOWN_MODULE_SIZES[module]} 大"
            for module, size in sorted(_module_sizes().items())
            if module in KNOWN_MODULE_SIZES and size > KNOWN_MODULE_SIZES[module]
        ]
        self.assertEqual(
            problems, [],
            "以下套件超過凍結行數：\n" + "\n".join(problems)
            + "\n真的該長大就把 KNOWN_MODULE_SIZES 對應那一行改掉（reviewer 會在 diff 裡"
            "看到）。先問一句：這些行是同樣輸入必定同樣輸出的東西（算術、閘門、排序），"
            "還是猜出來的判斷？後者屬於 rules.md 或 agent，不屬於 Python。",
        )

    def test_module_list_matches_reality(self):
        """新套件不得靜悄悄出現，刪掉的套件不得留在表上——兩邊都要動到這張表。"""
        actual = set(_module_sizes())
        frozen = set(KNOWN_MODULE_SIZES)
        self.assertEqual(
            sorted(actual - frozen), [],
            "以下套件不在 KNOWN_MODULE_SIZES 裡。新開一個套件要在那張表補一行，"
            "順手回答：它為什麼是 Python 而不是一個部門資料夾（ADR 0028）？",
        )
        self.assertEqual(
            sorted(frozen - actual), [],
            "以下套件已經不存在，請從 KNOWN_MODULE_SIZES 劃掉（清單不留死名單）。",
        )


# ---------------------------------------------------------------------------
# 契約頁閘門（2026-09-04，BOARD.md ②）：`docs/contracts/<module>.md` 棘輪。
#
# 16 個 app/ 模組裡今天有 10 個沒有契約頁。跟 KNOWN_OVERSIZED_FILES 同一種棘輪：
# 開票當天這份豁免清單＝現況所以是綠的，新模組沒有頁會紅（不在清單裡＝沒有豁免），
# 補完一份契約頁就把那一行從清單劃掉。`app/departments`／`app/methodology` 是純
# prompt 素材、沒有一行 .py，所以不在 KNOWN_MODULE_SIZES 裡，但仍然算模組——契約頁
# 描述的是模組邊界與進入點，跟裡面是不是 Python 無關。
# ---------------------------------------------------------------------------

ALL_MODULE_DIRS = {
    p.name for p in APP_DIR.iterdir()
    if p.is_dir() and p.name not in {"tests", "__pycache__"}
}

MODULES_WITHOUT_CONTRACT = {
    "dashboard", "departments", "intake", "llm",
    "methodology", "orders", "shared", "storage", "tools",
}

CONTRACTS_DIR = REPO_ROOT / "docs" / "contracts"


class ContractPageRatchetTest(unittest.TestCase):
    """②契約頁閘門：MODULES_WITHOUT_CONTRACT 只准變短，不准變長。"""

    def test_module_without_contract_is_either_frozen_or_has_a_page(self):
        missing = [
            module for module in sorted(ALL_MODULE_DIRS - MODULES_WITHOUT_CONTRACT)
            if not (CONTRACTS_DIR / f"{module}.md").exists()
        ]
        self.assertEqual(
            missing, [],
            "以下模組沒有 docs/contracts/<module>.md，也不在 MODULES_WITHOUT_CONTRACT 的豁免"
            "清單裡（新模組要嘛補頁、要嘛說得出理由才准加進豁免清單，不得默默略過）：\n"
            + "\n".join(f"  {m}" for m in missing),
        )

    def test_frozen_list_is_not_stale(self):
        done = sorted(
            m for m in MODULES_WITHOUT_CONTRACT
            if (CONTRACTS_DIR / f"{m}.md").exists()
        )
        self.assertEqual(
            done, [],
            "以下模組已經補了契約頁，請從 MODULES_WITHOUT_CONTRACT 劃掉（清單只准變短）：\n"
            + "\n".join(f"  {m}" for m in done),
        )

    def test_frozen_list_matches_reality(self):
        stale_dirs = sorted(MODULES_WITHOUT_CONTRACT - ALL_MODULE_DIRS)
        self.assertEqual(
            stale_dirs, [],
            "以下模組已經不存在，請從 MODULES_WITHOUT_CONTRACT 劃掉（清單不留死名單）：\n"
            + "\n".join(f"  {m}" for m in stale_dirs),
        )


if __name__ == "__main__":
    unittest.main()
