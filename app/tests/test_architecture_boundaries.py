"""app/tests/test_architecture_boundaries.py — A1 三層地界的機器檢查（修憲落地 A2）。

見 docs/architecture-rules.md A1。地界靠讀文件、沒有機器檢查是體檢（19-constitution-audit.md
第七節）點名的致命發現，這裡補上兩道掃描：

1. **import 掃描**：除排除清單外，任何模組不得 import 分支專屬層。
2. **跨層原生 SQL 掃描**：任何模組不得直接對「品牌永久層」（`app.brand_intelligence`）
   或「分支專屬層」的資料表下原生 SQL，必須走該層的公開函式（A1、鐵則 7）。
   實測原有三處偷讀（見 docs/design/19-constitution-audit.md 第七節），先列進
   KNOWN_SQL_VIOLATIONS 讓測試通過——這是明文記錄的欠帳（見 docs/rule-checks.md）。
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
# 分支專屬的東西，見 architecture-rules.md A1。
BRAND_PERMANENT_TABLES = {
    "brand", "brand_fact", "brand_performance_baseline", "brand_report", "claim",
    "customer_voice", "learning_ledger", "official_asset", "owned_channel", "persona", "product",
    "product_economics", "product_fact", "rule", "source_reference", "strategy_hypothesis",
}

_SQL_TABLE_REF = re.compile(r"(?:FROM|INTO|UPDATE|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.IGNORECASE)

# 已知違例（三處偷讀，體檢 19-constitution-audit.md 第七節；狀態見 docs/rule-checks.md）。
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
            "以下模組 import 了分支專屬層，違反 A1 三層地界（排除清單見 architecture-rules.md）：\n"
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


# ---- A1 檢查④：依賴方向（誰可以 import 誰）----
# 層級定義原本在 docs/architecture-rules.md，該檔已被 5eca0db「乾淨重啟」清除。
# 重建成這張表而不是重寫一份文件：文件會腐爛、沒人讀，這張表每次跑測試都會執行。
# 規則：只准依賴排在自己前面的層。順序由現況推導——這是唯一一種讓違規數收斂到
# 「只剩 brand_intelligence 那三條」的排法，其餘七個套件零違規。
LAYER_ORDER = [
    "app.core",                # 基礎設施：DB、migration、audit、interrupts
    "app.brand_intelligence",  # 品牌永久層
    "app.llm",                 # AI gateway 與 prompt 組裝
    "app.shared",              # web 骨架（app、templates、共用 ctx）
    "app.identity",            # 票 03-1：身分／租戶（JWT、org 解析），依賴 app.shared 的
                                # ApiError／conn；app.shared 對它的依賴是函式內延遲 import
                                # （見 require_actor()），這裡的靜態掃描看不到，不算環
    "app.intake",              # 建檔精靈
    "app.brand_web",           # 品牌智庫 web 路由
    "app.orders",              # 訂單
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
                problems.append(f"  {rel}：{count} 行，新超過 {FILE_LINE_CAP} 行上限——先拆再加")
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



# ---------------------------------------------------------------------------
# A1 檢查⑥⑦：量。票 shell-06（HANDOFF-shell-slice.md §4）。
#
# 為什麼要有這兩道：`app/ads/` 長到 21,595 行的過程中，既有三道閘門**一次都沒有紅過**。
#   - `FileLineCapTest` 管的是「單檔」800 行。那 21,595 行攤在幾十個檔案裡，每一個都在
#     800 以下，每一個都通過。
#   - `LayerDirectionTest`／`ImportCycleScanTest` 管的是耦合，不是體積。廣告模組的耦合
#     一直很乾淨——41 個 import 全部是模組層級的。
# 三道閘門都沒錯，只是都沒在看「量」。下面兩道補這一格。
#
# **誠實的天花板，寫在這裡而不是只寫在票裡**：這兩道抓不到真正的病因——為一個還沒有人
# 跑過的系統寫 21,595 行猜出來的門檻。「先用手做，痛過兩次再寫成程式」才是對的規則，
# 而它**不可機器檢查**。這兩道買到的是早 10 倍的警報（廣告模組會在約 2,000 行就撞上
# `ModuleSizeRatchetTest`，而不是 21,595 行），不是解藥。真正擋得住的那條規則現在寫在
# 全域 `CLAUDE.md`：任何數字門檻都要說得出來源，「業界標準」不算來源。
# ---------------------------------------------------------------------------

# 凍結於外殼切片後的實測值（2026-08-29）：production 15,634 行、tests 13,418 行。
# 切之前是 39,257／42,166（1.074×）——切完降到 0.858×，因為刪掉的測試（28,748 行）比
# 刪掉的程式（23,623 行）更多。交接文件預測「切完會變成 1.13×，更糟」，實測不成立：
# 它假設只刪 81 個廣告測試檔，實際刪了 95 個。`docs/workflow-diet.md` 第 4 條的目標是 0.7×。
# 這個天花板含本檔這兩道閘門自己的 128 行——閘門也是測試，也算進它自己管的數字裡。
# **只准往下**：這個數字是天花板，不是配額。
TEST_RATIO_CEILING = 0.858


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
    """測試行數相對程式行數的比值，只准往下。

    測試是有人要維護的程式碼，寫得越多不等於越安全（`docs/workflow-diet.md` 第 4 條）。
    這道閘門把那條原本只是散文的目標接上機器——憲章明文：「一個沒有閘門的數字不是限制」。
    """

    def test_ratio_only_goes_down(self):
        production, tests = _line_totals()
        ratio = round(tests / production, 3)
        self.assertLessEqual(
            ratio, TEST_RATIO_CEILING,
            f"測試行數比值從 {TEST_RATIO_CEILING} 漲到 {ratio}"
            f"（production {production} 行、tests {tests} 行）。\n"
            "這道閘門只准往下。要加測試就先問它守的是哪一件事——金額、租戶隔離、API 契約、"
            "資料正確性，四者以外不寫（docs/workflow-diet.md 第 4 條）；畫面行為只給"
            "frontend/e2e/smoke.spec.ts 那一支端到端煙霧測試，不寫單元測試。\n"
            "真的該漲（例如新增了一整層資料正確性測試），就把 TEST_RATIO_CEILING 改掉——"
            "改在這一行，reviewer 會在 diff 裡看到。",
        )


# 凍結於外殼切片後的實測值（2026-08-29）。`app/` 底下每個套件一個項目，`app` 這一項
# 是頂層的 .py（`main.py` 組裝根等）。**允許調高，但必須改這張表**——重點不是禁止成長，
# 是讓成長出現在 diff 裡有人看得到。廣告模組會在約 2,000 行撞上它，而不是 21,595 行。
KNOWN_MODULE_SIZES = {
    "app": 519,
    "app/brand_intelligence": 2634,
    "app/brand_web": 2155,
    "app/core": 2148,
    "app/dashboard": 645,
    "app/identity": 537,
    "app/intake": 3548,
    "app/llm": 1271,
    "app/orders": 1409,
    "app/shared": 450,
    "app/tools": 318,
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


if __name__ == "__main__":
    unittest.main()
