"""app/schedule/jobs.py — the schedule generations' actual LLM work, private to this
package (only app/schedule/__init__.py exports anything from here, container contract §1).

票 05-1：`app/schedule/routes.py`'s POST endpoints no longer call the LLM inside the
HTTP request (see that file's docstring for why — a two-to-six-minute blocking POST that a
killed process leaves stuck `running` forever). They validate, then
`background.enqueue("background.<task_type>", ...)` and return immediately. The actual prompt
assembly and `gateway.run_task()` call — what `routes.py`'s `_run_plan`/`_run_tree`
used to do after validation — lives here instead, as procrastinate task
bodies with the frozen signatures the ticket names:

    schedule_plan(org_id, brand_id, product_ids, platform, objective, promotion_note, plan_count)
    schedule_tree(org_id, brand_id, plan_index)

票 05（ADR 0068 §2）：`schedule_tree()` no longer discards the row after `gateway.run_task()` —
on a successful expansion it submits one workbench brief per deepest node; the workbench now
owns copy generation and the third generation task body this module used to run has no callers
left (retired this ticket, see git history for its shape).

F02-I02（ARCHITECTURE.md §5.4，2026-09-12 reset）：the per-leaf loop now hands the whole
expanded tree to the workbench in **one call**, `app.workbench.submit_pack` (entry point only)
— one pack per tree, one set per deepest node, `required_outputs = {"copy": 1,
"image_prompt": 1}` (one node is one ad, it needs one selected copy and one selected image
prompt). The old per-leaf entry point is retired; `submit_pack` is the only door in.

Each opens its own `app.core.db.connection()` — a worker job never inherits a request's
connection. `org_id` is a required first parameter on all of them (ADR 0038 gate,
`app/tests/test_background.py::TaskSignatureOrgIdGateTest`, scoped to `background.`-prefixed
task names — these register under exactly that prefix, see `register_tasks()` below).

Freely imports `routes.py`'s private helpers (`_latest_task_row`, `_load_platform_data`, the
task-type constants) — both files live inside the same `app.schedule` package, so this is an
intra-package call, not a cross-module one (container contract §1 is about crossing package
boundaries, not files within one). `routes.py` does not import this file back: the endpoints
only need the task *name* string (`f"background.{TASK_TYPE}"`, built from routes.py's own
constants) to enqueue, never a function from here — keeps this a one-directional dependency,
no cycle to detect.

The validation that decides whether a run is worth queueing at all (products exist, platform/
objective/plan-count are valid, budget is set, the plan/tree being expanded actually succeeded,
the spend cap isn't hit) stays in `routes.py`, running synchronously before `enqueue()` — see
that file's docstring. A job body here re-derives what it needs from `brand_id`/`plan_index`
(the frozen row lookups, not re-validation): the request already checked those hold at enqueue
time, and frozen decision 3 (one run at a time per brand per task type) means nothing else can
have changed the picture out from under it before the worker gets to it.
"""

import logging

from app import (
    background,
    workbench,  # module entry point only (docs/contracts/workbench.md)
)
from app.brand_intelligence import repository as bi_repo
from app.core import rule_cards
from app.core.db import connection, jsonb, new_id
from app.llm import context_compiler, gateway, methodology, providers
from app.schedule import binding as binding_mod
from app.schedule import diagnosis as diagnosis_mod
from app.schedule import history as history_mod
from app.schedule import performance as performance_mod
from app.schedule import period_repository as period_repo
from app.schedule import plan as plan_mod
from app.schedule import repository, routes, state
from app.schedule import scoring as scoring_mod

# 唯一的供應商實例：這些 task body 現在是全站唯一真的打代理的地方（routes.py 的生成端點
# 自己不再打），比照 routes.py 搬過來之前的既有寫法——測試用
# `mock.patch.object(jobs, "PROVIDER", FakeProvider(...))` 換掉。
PROVIDER = providers.AnthropicProvider()


def _compile_brand_context(conn, brand_id: str, product_ids: list) -> tuple:
    """對每個選定產品各跑一次 `context_compiler.compile()`，用空行接起來；`knowledge_item_ids`
    取聯集、保留原順序去重。回傳 (prompt 片段, knowledge_item_ids, brand_version)。

    ponytail: 品牌層段落（規則／宣稱／品牌事實）會隨產品數重複出現——每個產品各自一次
    compile()，沒有跨產品去重這件事。這是票 07 明文接受的上限（最薄路徑，先求打通），
    真的因為 prompt 太長而困擾時再考慮把品牌層與產品層拆開各編一次。
    """
    texts, knowledge_item_ids, seen = [], [], set()
    brand_version = None
    for product_id in product_ids:
        text, ids, brand_version, _product_version = context_compiler.compile(
            conn, brand_id, product_id
        )
        texts.append(text)
        for kid in ids:
            if kid not in seen:
                seen.add(kid)
                knowledge_item_ids.append(kid)
    return "\n\n".join(texts), knowledge_item_ids, brand_version


def _plan_params_text(platform_label: str, objective_label: str, promotion_note: str,
                       plan_count: int, product_names: list) -> str:
    return "\n".join([
        "## 這次排程的參數",
        f"平台：{platform_label}",
        f"這期要投放的產品：{'、'.join(product_names)}",
        f"行銷目標：{objective_label}",
        f"促銷或重點：{promotion_note or '（未填寫）'}",
        f"要幾個方案：{plan_count}",
    ])


def _tree_params_text(platform_label: str, plan_index: int, chosen_plan: dict) -> str:
    lines = [
        "## 這次要展開的參數",
        f"平台：{platform_label}",
        f"選定的方案（第 {plan_index + 1} 個）摘要：{chosen_plan['summary']}",
        f"這個方案的理由：{chosen_plan['reasoning']}",
        "這個方案裡錢怎麼分：",
    ]
    for split in chosen_plan["splits"]:
        lines.append(
            f"- {split['label']}：{split['share'] * 100:.0f}%，"
            f"每日 {split['daily_amount']} 元（{split['why']}）"
        )
    return "\n".join(lines)


def _cpa_cell(cpa: float | None, conversion_goal: str | None) -> str:
    """票 01：CPA 那一格——有數字就印數字；沒有數字時，區分「有設轉換目標但沒追蹤到」
    跟「根本沒設轉換目標」，兩句話意義不同，不能都印同一個「未追蹤」。"""
    if cpa is not None:
        return f"{cpa:,.0f}"
    return "未追蹤" if conversion_goal else "未設定轉換目標"


def _account_performance_text(perf: dict, breakeven: tuple[float | None, str]) -> str:
    """票 01（`docs/issues/plan-quality/`）：`performance.ad_performance()` 的輸出 → 這一節
    prompt 文字。逐幣別一段（頭行、打平線、方向性提示、逐廣告表），最後一次性附收斂指令。

    打平線那一行、`DIRECTIONAL_ONLY_NOTE`、`_pct`／`_roas_text` 都是重用
    `diagnosis_mod`（同一個套件 `app/schedule/` 內，私有符號可以跨檔案叫，見
    `docs/contracts/schedule.md` 對 `routes.py`／`jobs.py` 既有的說法）；打平線的措辭字面
    照抄 `diagnosis_mod.compress()` 那兩行，`compress()` 本身沒有把它拆成一支可以共用的
    函式，這裡不為了兩個呼叫端去改一支矛盾檢查段沒有點名要動的既有函式（ceiling）。"""
    window = perf["window"]
    currencies = perf["currencies"]
    if not currencies:
        return (
            "【這個帳戶目前的成效】\n"
            f"這個月（{window['start_date']} ~ {window['end_date']}）還沒有任何 Meta 花費資料。"
        )

    roas, source = breakeven
    breakeven_line = (
        f"打平線 {roas:.2f}x，來自{source}" if roas is not None else f"算不出打平線：{source}"
    )
    conversion_goal = perf["conversion_goal"]

    out = [f"【這個帳戶目前的成效】（Meta 廣告層，{window['start_date']} ~ {window['end_date']}）"]
    for cur in currencies:
        total = cur["total"]
        out.append(
            f"# 幣別 {cur['currency']}｜本月總花費 {total['spend']:,.0f}｜"
            f"保守 ROAS {diagnosis_mod._roas_text(total['roas_conservative'])}｜"
            f"樂觀 ROAS {diagnosis_mod._roas_text(total['roas'])}｜"
            f"追蹤覆蓋率 {total['roas_coverage']:.0%}｜{total['ad_count']} 則廣告"
        )
        out.append(breakeven_line)
        out.append(diagnosis_mod.DIRECTIONAL_ONLY_NOTE)
        out.append("| 廣告 | 花費 | 佔比 | 保守 ROAS | 樂觀 ROAS | 追蹤覆蓋率 | CPA |")
        out.append("|---|---|---|---|---|---|---|")
        for ad in cur["ads"]:
            out.append(
                f"| {ad['entity_name']} | {ad['spend']:,.0f} |"
                f" {diagnosis_mod._pct(ad['spend'], total['spend'])} |"
                f" {diagnosis_mod._roas_text(ad['roas_conservative'])} |"
                f" {diagnosis_mod._roas_text(ad['roas'])} |"
                f" {ad['roas_coverage']:.0%} | {_cpa_cell(ad['cpa'], conversion_goal)} |"
            )
    out.append(
        "方案的 summary 與 reasoning 要引用上面的數字：指名哪一則廣告、哪個數字、這一期要"
        "把它推到多少。"
    )
    return "\n".join(out)


_HISTORY_COORDINATE_HEADER = "座標（受眾／痛點／切角／鉤子／證明／優惠／格式）"
_HISTORY_CLOSING_LINE = (
    "投放史是起點，不是答案：說明這一期哪些座標值得再試、哪些不必重走，並指名是哪一則"
    "廣告的哪個數字讓你這樣判斷。"
)


def _history_coordinate_cell(coordinates: dict, labels: dict) -> str:
    """跟 `_coordinate_cell()` 同一個標籤查法（`labels.get((dimension, key), key)`，缺的
    印 `—`），但 `history.tagged_history()` 的 item 形狀是 `{dimension: key}`，不是
    `node_result["coordinates_json"]` 那種 `{dimension}_key`——不能直接呼叫
    `_coordinate_cell()`，另開一支比改那支的輸入形狀便宜（那支還有 smart-loop 03 的呼叫端）。"""
    return "／".join(
        "—" if coordinates.get(d) is None else labels.get((d, coordinates[d]), coordinates[d])
        for d in repository.COORDINATE_KEYS
    )


def _history_text(items: list[dict], labels: dict, breakeven: tuple[float | None, str]) -> str:
    """票 past-ads/05（ADR 0067 §1.10）：`history.tagged_history()` 的輸出 → `schedule_plan()`
    prompt 的最後一節【投放史】——系統接手之前這個帳戶自己投過、owner 親自標了座標的廣告，
    數字＋座標＋owner 自己的一句話。空清單 → `""`（既有 `if section` join 直接跳過這一節；
    只有 `schedule_plan()` 呼叫，`schedule_tree()` 不呼叫，ADR 0067 §1.10：那份 prompt
    這一期還沒有節點名字／文案可以對照老廣告）。

    打平線那一行沿用 `_account_performance_text()` 字面同一句（那支自己沒把它拆成共用
    函式，這裡不為了兩個呼叫端去改一支矛盾檢查段沒有點名要動的既有函式，ceiling）；
    `roas_coverage` 沿用同一支既有的 `.0%` 格式（`diagnosis_mod._pct()` 是「花費 / 總花費」
    那種兩個金額相除，這裡已經是 `_bucket()` 算好的比率，套 `_pct(x, 1)` 只是繞一圈拿到
    一模一樣的字串，這裡不繞）。"""
    if not items:
        return ""

    first = min(item["first_seen_date"] for item in items)
    last = max(item["last_seen_date"] for item in items)
    roas, source = breakeven
    breakeven_line = (
        f"打平線 {roas:.2f}x，來自{source}" if roas is not None else f"算不出打平線：{source}"
    )

    by_currency: dict[str, list[dict]] = {}
    for item in items:
        by_currency.setdefault(item["currency"], []).append(item)

    out = [
        "【投放史】（系統接手之前，這個帳戶自己投過、老闆親自標了座標的廣告；"
        f"{first.isoformat()}–{last.isoformat()}）",
        breakeven_line,
        diagnosis_mod.DIRECTIONAL_ONLY_NOTE,
    ]
    for currency, cur_items in sorted(by_currency.items()):
        out.append(f"# 幣別 {currency}")
        out.append(
            f"| 廣告 | 投放期間 | 花費 | 保守 ROAS | 樂觀 ROAS | 追蹤覆蓋率 | "
            f"{_HISTORY_COORDINATE_HEADER} | 老闆的話 |"
        )
        out.append("|---|---|---|---|---|---|---|---|")
        for item in cur_items:
            note_cell = (item["owner_note"] or "").replace("|", "｜")
            out.append(
                f"| {item['name']} |"
                f" {item['first_seen_date'].isoformat()}–{item['last_seen_date'].isoformat()} |"
                f" {item['spend']:,.0f} |"
                f" {diagnosis_mod._roas_text(item['roas_conservative'])} |"
                f" {diagnosis_mod._roas_text(item['roas'])} |"
                f" {item['roas_coverage']:.0%} |"
                f" {_history_coordinate_cell(item['coordinates'], labels)} |"
                f" {note_cell} |"
            )
    out.append(_HISTORY_CLOSING_LINE)
    return "\n".join(out)


_LAST_PERIOD_DEPTH_LABELS = {2: "組合", 3: "廣告"}  # same two labels as
# frontend/src/lib/scheduleApi.ts's NODE_RESULT_DEPTH_LABELS -- one source of Chinese wording
# per screen; this one is prompt text, not the screen, so it is not imported from there.

_LAST_PERIOD_CLOSING_LINE = (
    "上一期的判決是這一期的起點：說明哪些節點要延續、哪些要換、為什麼；"
    "「看不出」不是失敗，是樣本不夠。"
)


def _coordinate_cell(node_result: dict, labels: dict) -> str:
    """票 smart-loop 03：depth-3 node 的座標欄——七個 `*_key` 值各自轉成 label（查不到就印
    key 本身，`performance_mod._coordinate_labels()` 既有的 fallback 慣例），用「／」接起來；
    一個維度沒填（`None`）印 `—`（跟這一列其他缺值欄位同一個記號）。"""
    coordinates = node_result["coordinates_json"] or {}
    parts = []
    for dimension in repository.COORDINATE_KEYS:
        key = coordinates.get(f"{dimension}_key")
        parts.append("—" if key is None else labels.get((dimension, key), key))
    return "／".join(parts)


def _last_period(conn, org_id: str, brand_id: str) -> tuple[dict, list] | None:
    """票 04：`_last_period_text()`／`_continuity_text()` 共用的讀——最近一個已結算檔期
    連同它的逐節點記分列，只查一次（ticket §1「Do not query the rows twice」）；
    `schedule_tree()` 兩段 prompt 都要同一份 `results`。`None`：沒有已結算的檔期，或那個
    檔期結算時零個節點被記分（品牌層數字不算「決策的記憶」，見 `_last_period_text()` 呼叫端
    docstring）。"""
    period = period_repo.latest_settled_period(conn, org_id, brand_id)
    if period is None:
        return None
    results = period_repo.period_node_results(conn, org_id, brand_id, period["id"])
    if not results:
        return None
    return period, results


def _last_period_text(
    last_period: tuple[dict, list] | None, conn, org_id: str, brand_id: str
) -> str:
    """票 smart-loop 03：`schedule_plan()`／`schedule_tree()` prompt 的最後一段——上一個
    已結算檔期的逐節點判決，讓代理在畫這一期之前先看到上一期誰賺誰賠。`""`：`last_period`
    是 `None`（`_last_period()` 已經判過的兩種「沒有」）。"""
    if last_period is None:
        return ""
    period, results = last_period

    labels = performance_mod._coordinate_labels(conn, org_id, brand_id)
    depth_totals: dict[int, float] = {}
    depth_counts: dict[int, int] = {2: 0, 3: 0}
    verdict_counts = {"win": 0, "lose": 0, "unclear": 0}
    for r in results:
        depth_totals[r["depth"]] = depth_totals.get(r["depth"], 0.0) + r["actual_spend"]
        depth_counts[r["depth"]] += 1
        verdict_counts[r["verdict"]] += 1

    breakeven = results[0]["breakeven_roas"]  # ticket §2：這一期所有列同一個值
    breakeven_text = f"{breakeven:.2f}x" if breakeven is not None else "算不出"
    out = [
        f"【上一期】{period['start_date'].isoformat()} ~ {period['end_date'].isoformat()}｜"
        f"日預算 {float(period['daily_budget']):,.0f}｜"
        f"結算花費 {float(period['settled_spend']):,.0f}｜"
        f"這期間全通路營收 {float(period['settled_revenue']):,.0f}｜"
        f"打平線 {breakeven_text}",
        f"判決：{scoring_mod.VERDICT_LABELS['win']} {verdict_counts['win']}、"
        f"{scoring_mod.VERDICT_LABELS['lose']} {verdict_counts['lose']}、"
        f"{scoring_mod.VERDICT_LABELS['unclear']} {verdict_counts['unclear']}"
        f"（組合 {depth_counts[2]}、廣告 {depth_counts[3]}）",
        "| 節點 | 層 | 座標 | 核准比例 | 實花 | 實花佔比 | 保守 ROAS | 樂觀 ROAS | 判決 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        share = r["approved_share"]
        share_cell = "—" if share is None else f"{share * 100:.0f}%"
        coord_cell = _coordinate_cell(r, labels) if r["depth"] == 3 else "—"
        out.append(
            f"| {r['node_name']} | {_LAST_PERIOD_DEPTH_LABELS[r['depth']]} | {coord_cell} |"
            f" {share_cell} | {r['actual_spend']:,.0f} |"
            f" {diagnosis_mod._pct(r['actual_spend'], depth_totals[r['depth']])} |"
            f" {diagnosis_mod._roas_text(r['roas_conservative'])} |"
            f" {diagnosis_mod._roas_text(r['roas_optimistic'])} |"
            f" {scoring_mod.VERDICT_LABELS[r['verdict']]} |"
        )
    out.append(_LAST_PERIOD_CLOSING_LINE)
    return "\n".join(out)


_CONTINUITY_KEEP_HEADER = (
    "上一期判決「賺」或「看不出」的節點，這一期**名字一字不改**地沿用"
    "（系統靠名稱把它接回同一個 Meta 物件，改一個字就接不回去）："
)
_CONTINUITY_REPLACE_HEADER = (
    "上一期判決「賠」的節點不要沿用：換名字、換座標（七個維度至少一個跟舊的不同），並在"
    "該節點的 warnings 寫一句「取代上一期的 <舊名>」："
)
# 票 05（ADR 0069 §2）：程式會把沿用節點的座標蓋成上一期表格裡那一列的座標欄
# （`binding._apply_continuity()`），不管代理這次寫了什麼——這句話只是讓代理少猜一次，
# 蓋不蓋是程式決定的，不是這句話決定的。
_CONTINUITY_CLOSING_LINE = (
    "沿用的節點可以改 share、fields、children；name 與 coordinates 都不能動——"
    "coordinates 照【上一期】表的座標欄逐字抄。"
)


def _continuity_campaign_names(
    conn, org_id: str, brand_id: str, node_results: list[dict]
) -> list[str]:
    """票 04 Amendment 2026-09-08（第一輪驗收撞牆）：depth 1（活動）從沒被記分過
    （ADR 0066 rule 2），不在 `node_results` 裡，但 `binding.bind_tree()` 由上而下比對——
    第一層這一期改了名字就對不上，底下所有節點這次整批不比對
    （`bind_failure_message()`：「上一層沒有配對成功時，它底下的節點這次不會比對」）。名字
    只能從**上一棵樹自己的**綁定列找（ADR 0064：一個綁定屬於做出它的那棵樹），不是疊圖用
    的 `bindings_by_node_key()`——`node_results` 每一列的 `source_tree_task_id` 是那棵樹的
    id，同一期全部同一個值。`node_results` 是空清單（沒有已結算檔期，或那個檔期零個節點
    被記分）→ `[]`，不查。"""
    if not node_results:
        return []
    source_tree_task_id = node_results[0]["source_tree_task_id"]
    bindings = repository.bindings_for_tree(
        conn, org_id, brand_id, binding_mod.CHANNEL_KEY, source_tree_task_id
    )
    return [
        b["node_name_at_bind"] for node_key, b in sorted(bindings.items()) if "." not in node_key
    ]


def _continuity_text(node_results: list[dict], campaign_names: list[str]) -> str:
    """票 04：tree prompt 的最後一段，緊接在【上一期】後面——是對那一段動手的指令
    （`docs/contracts/schedule.md`「Position in the prompt decides whether an instruction
    runs」），只有 `schedule_tree()` 呼叫（`schedule_plan()` 那一階段還沒有節點名字）。
    `win`／`unclear` 判決的節點名字原字沿用——綁定靠精準比對名稱（`binding.py`
    `campaign_ids_by_exact_name`），改名字就接不回同一個 Meta 物件；`lose` 判決的節點要
    換名字。哪一塊有列才印哪一塊。`node_results` 是空清單（`schedule_tree()` 在
    `_last_period()` 回 `None` 時傳空清單）→ `""`。

    票 04 Amendment：`campaign_names`（`_continuity_campaign_names()` 算好的第一層名字，
    caller 傳進來，這裡不查表）先印在沿用區最前面、標籤是「活動」——depth 1 從沒有判決，
    不是 `keep_rows` 的一部分，但它決定沿用區這個標題底下要不要印、不是只搭 `keep_rows`
    的便車：`campaign_names` 有值但這一期剛好沒有 `win`／`unclear` 節點時，沿用區照樣印
    （只有活動那幾行）——不然新樹的活動就沒有沿用指令，跟 depth 2／3 的沿用邏輯脫節。"""
    keep_rows = [r for r in node_results if r["verdict"] in ("win", "unclear")]
    lose_rows = [r for r in node_results if r["verdict"] == "lose"]
    if not keep_rows and not lose_rows and not campaign_names:
        return ""

    out = ["【延續】"]
    if keep_rows or campaign_names:
        out.append(_CONTINUITY_KEEP_HEADER)
        out.extend(f"- 活動：{name}" for name in campaign_names)
        out.extend(
            f"- {_LAST_PERIOD_DEPTH_LABELS[r['depth']]}：{r['node_name']}" for r in keep_rows
        )
    if lose_rows:
        out.append(_CONTINUITY_REPLACE_HEADER)
        out.extend(
            f"- {_LAST_PERIOD_DEPTH_LABELS[r['depth']]}：{r['node_name']}" for r in lose_rows
        )
    out.append(_CONTINUITY_CLOSING_LINE)
    return "\n".join(out)


def _coordinate_vocabulary_text(conn, org_id: str, brand_id: str) -> str:
    """票 05（ADR 0069 §1）：活動樹 prompt 的**最後**一段——七個維度各自可用的座標
    label，跟 copy prompt 既有的「vocabulary last」順序同一條規則（ADR 0068 §6，T8b
    量到的：「答完再照做」這種指令放最後才會被照做）。停用／被否決的 label 都不列（票面
    原文，兩個條件都濾——`history.py` 只濾 `disabled_at`，不是同一條規則）；維度中文名
    沿用 `diagnosis.DIMENSION_LABELS`，不另開一份。只讀 `repository.list_coordinates()`
    （schedule 自己的表），不 import workbench（只准 import `__init__`，ADR 0068 §2）。"""
    labels_by_dimension: dict[str, list[str]] = {dim: [] for dim in repository.COORDINATE_KEYS}
    for row in repository.list_coordinates(conn, org_id, brand_id):
        if row["disabled_at"] is not None or row["rejected"]:
            continue
        labels_by_dimension[row["dimension"]].append(row["label"])
    lines = ["## 座標詞彙表"]
    lines.extend(
        f"{diagnosis_mod.DIMENSION_LABELS[dimension]}：{'、'.join(labels_by_dimension[dimension])}"
        for dimension in repository.COORDINATE_KEYS
    )
    return "\n".join(lines)


def schedule_plan(org_id: str, brand_id: str, product_ids: list, platform: str, objective: str,
                   promotion_note: str, plan_count: int,
                   campaign_period_id: str | None = None) -> None:
    """procrastinate task body（`background.schedule_plan`）——`routes.py` 的 `_run_plan()`
    驗證通過、`enqueue()` 成功之後，真正打代理、寫 `llm_task` 的地方。"""
    with connection() as conn:
        product_names = routes._validate_products(conn, brand_id, product_ids)
        data = state._load_platform_data()
        daily_budget = rule_cards.get_value(conn, brand_id, "schedule_budget", "daily_budget")
        platform_label = next(p["label"] for p in data["platforms"] if p["id"] == platform)
        objective_label = next(
            o["label"] for o in data["objectives"]
            if o["platform"] == platform and o["value"] == objective
        )

        brand_context, knowledge_item_ids, brand_version = _compile_brand_context(
            conn, brand_id, product_ids
        )
        department_text = state.DEPARTMENT_FILE.read_text(encoding="utf-8")
        methodology_result = methodology.compile(
            conn, state.METHODOLOGY_TASK_LABELS, brand_id=brand_id
        )
        params_text = _plan_params_text(
            platform_label, objective_label, promotion_note, plan_count, product_names
        )
        performance = performance_mod.ad_performance(conn, org_id, brand_id)
        breakeven = diagnosis_mod.breakeven_roas(conn, org_id, brand_id)
        performance_text = _account_performance_text(performance, breakeven)
        last_period_text = _last_period_text(
            _last_period(conn, org_id, brand_id), conn, org_id, brand_id
        )
        # 票 past-ads/05（ADR 0067 §1.10）：只有 schedule_plan() 拿——schedule_tree() 那份
        # prompt 這一期還沒有節點名字／文案可以對照老廣告。位置排在
        # last_period_text 之後、整份 prompt 最後一段（docs/contracts/schedule.md「Position
        # in the prompt decides」）；打平線跟 performance_text 同一份 breakeven，不重算。
        history_text = _history_text(
            history_mod.tagged_history(conn, org_id, brand_id),
            performance_mod._coordinate_labels(conn, org_id, brand_id),
            breakeven,
        )
        prompt = "\n\n".join(
            section for section in
            (department_text, methodology_result.text, params_text, brand_context,
             performance_text, last_period_text, history_text) if section
        )

        context = gateway.TaskContext(
            context_scope={
                "brand_id": brand_id, "product_ids": product_ids, "daily_budget": daily_budget,
                "platform": platform, "objective": objective,
                "promotion_note": promotion_note, "plan_count": plan_count,
            },
            knowledge_item_ids=knowledge_item_ids,
            brand_version=brand_version,
            product_version=None,
        )
        gateway.run_task(
            conn, PROVIDER, brand_id=brand_id, task_type=state.TASK_TYPE,
            prompt_template_id=state.TASK_TYPE, prompt_template_version="v1",
            system=None, messages=[{"role": "user", "content": prompt}], context=context,
            campaign_period_id=campaign_period_id,
            # 網路搜尋暫緩（ADR 0048）：這裡曾傳 tools=[providers.WEB_SEARCH_TOOL]。機制還在，
            # 開回來是加回這一個參數，不動 schema。開回來的條件見該 ADR。
        )


def schedule_tree(org_id: str, brand_id: str, plan_index: int, plan_task_id: str,
                   campaign_period_id: str | None = None) -> None:
    """procrastinate task body（`background.schedule_tree`）——見 `schedule_plan()` 檔頭。

    fix round 1：`plan_task_id` 是 `routes._run_tree()` enqueue 當下釘住的那一列 id，不能
    改成「重讀這個品牌最新一次 schedule_plan」——frozen decision 3 的「一次一個」是
    **按 task type** 算的，不是按品牌算的：這個 job 排隊等執行的時候，使用者可能已經按了
    另一種工作（例如產素材），那一種工作自己的『最新一列』會變，但不會動到這裡要的這一列。
    只有『同一個 brand／同一個 task type』才保證不會被插隊；跨 task type 重讀『最新』就是在
    賭一個沒人保證過的東西。"""
    with connection() as conn:
        plan_row = gateway.get_task(conn, plan_task_id)
        # routes.py 的 _run_tree() 在 enqueue 之前已經驗證過這一列存在且 succeeded；
        # 列從不刪除，這裡讀回來的就是釘住的那一列本身。
        assert plan_row is not None
        plan_scope = plan_row.get("context_scope_json") or {}
        daily_budget = plan_scope.get("daily_budget", 0)
        product_ids = plan_scope.get("product_ids", [])
        platform = plan_scope.get("platform", "")

        plans, _failure = plan_mod.build_plans(plan_row.get("rendered_output") or "", daily_budget)
        chosen_plan = plans[plan_index]

        data = state._load_platform_data()
        platform_label = next(
            (p["label"] for p in data["platforms"] if p["id"] == platform), platform
        )
        objective = plan_scope.get("objective", "")
        objective_label = next(
            (o["label"] for o in data["objectives"]
             if o["platform"] == platform and o["value"] == objective),
            objective,
        )

        brand_context, knowledge_item_ids, brand_version = _compile_brand_context(
            conn, brand_id, product_ids
        )
        department_text = state.TREE_DEPARTMENT_FILE.read_text(encoding="utf-8")
        methodology_result = methodology.compile(
            conn, state.METHODOLOGY_TASK_LABELS, brand_id=brand_id
        )
        params_text = _tree_params_text(platform_label, plan_index, chosen_plan)
        last_period = _last_period(conn, org_id, brand_id)
        last_period_text = _last_period_text(last_period, conn, org_id, brand_id)
        node_results = last_period[1] if last_period else []
        campaign_names = _continuity_campaign_names(conn, org_id, brand_id, node_results)
        continuity_text = _continuity_text(node_results, campaign_names)
        coordinate_vocabulary_text = _coordinate_vocabulary_text(conn, org_id, brand_id)
        prompt = "\n\n".join(
            section for section in
            (department_text, methodology_result.text, params_text, brand_context,
             last_period_text, continuity_text, coordinate_vocabulary_text) if section
        )

        context = gateway.TaskContext(
            context_scope={
                "brand_id": brand_id, "plan_index": plan_index, "daily_budget": daily_budget,
                "source_plan_task_id": plan_row["id"],
            },
            knowledge_item_ids=knowledge_item_ids,
            brand_version=brand_version,
            product_version=None,
        )
        row = gateway.run_task(
            conn, PROVIDER, brand_id=brand_id, task_type=state.TREE_TASK_TYPE,
            prompt_template_id=state.TREE_TASK_TYPE, prompt_template_version="v1",
            system=None, messages=[{"role": "user", "content": prompt}], context=context,
            options=gateway.TaskOptions(max_tokens=24000, timeout_s=480.0),
            campaign_period_id=campaign_period_id,
        )

        # F02-I02（ARCHITECTURE.md §5.4）：展開成功就把整棵樹交棒成**一個**任務包——一個
        # pack 一次 `submit_pack()` 呼叫，一個最深層節點一個 set，`required_outputs =
        # {"copy": 1, "image_prompt": 1}`（一個節點就是一則廣告，需要一份選定文案、一份
        # 選定圖片提示詞）。重建這棵樹、取文件順序的最深層節點兩步，跟票 05 過去
        # 產內容那一步用的是同一組讀法：`tree_with_bindings()`＋`_leaf_ad_nodes()`。整包
        # 一次 try/except：一次失敗的交棒只記一行 log，不影響已經 commit 的樹（tree row 由
        # `run_task()` 自己落地，pack 是它的下游，不是它的一部分）——不逐節點各自
        # try/except，pack 本來就是一次性寫入（`submit_pack()` 檔頭）。
        if row["status"] == "succeeded":
            tree = binding_mod.tree_with_bindings(conn, row, org_id, brand_id)
            leaves = state._leaf_ad_nodes(tree["nodes"]) if tree["failure"] is None else []
            if leaves:
                period_row = (
                    period_repo.get_period(conn, org_id, brand_id, campaign_period_id)
                    if campaign_period_id else None
                )
                pack_name = (
                    period_row["name"] if period_row
                    else f"{platform_label} 方案 {plan_index + 1}"
                )
                promotion_note = plan_scope.get("promotion_note")
                try:
                    workbench.submit_pack(conn, org_id, brand_id, {
                        "source_kind": "schedule_node",
                        "source_ref": {"source_tree_task_id": row["id"]},
                        "name": pack_name,
                        "summary": {
                            "情境": chosen_plan.get("summary"),
                            "重點訊息": promotion_note,
                        },
                        "context": {
                            "product_ids": product_ids,
                            "platform": platform_label,
                            "goal": objective_label,
                        },
                        "sets": [
                            {
                                "name": leaf["name"],
                                "source_ref": {
                                    "node_key": leaf["node_key"],
                                    "source_tree_task_id": row["id"],
                                    "node_name": leaf["name"],
                                },
                                "product_id": product_ids[0] if product_ids else None,
                                # 票 05（ADR 0069 §3）：這個節點的座標（含沿用節點被程式
                                # 蓋過的那一份，binding.tree_with_bindings() 讀時 overlay
                                # 已經疊上）隨 set 交棒——空維度丟棄，舊樹（沒有
                                # coordinates 欄位）的節點一律得到 `{}`。這是這棵樹展開
                                # 當下那一刻的值（下一次結算之後畫面重讀會不會不一樣，見
                                # docs/contracts/workbench.md 那條已知落差）。
                                "coordinates": {
                                    k: v for k, v in (leaf.get("coordinates") or {}).items() if v
                                },
                                "style_key": "ugc",
                                "required_outputs": {"copy": 1, "image_prompt": 1},
                                "request": {
                                    "use_brand_knowledge": True, "product_ids": product_ids,
                                    "copy_length": leaf.get("copy_length") or "short",
                                    "promotion_note": promotion_note,
                                    # `required_outputs["image_prompt"]` 進了 `parts`
                                    # （`submit_pack()` 從 `required_outputs.keys()`
                                    # 衍生），工作檯就要求這欄 1–30（ARCHITECTURE.md
                                    # §5.7 的 UI 預帶值同一條規則：彈性格式 -> 10，否則 3）。
                                    "image_prompt_count": (
                                        10 if (leaf.get("coordinates") or {}).get("format")
                                        == "彈性格式" else 3
                                    ),
                                },
                            }
                            for leaf in leaves
                        ],
                    })
                except Exception:
                    logging.getLogger(__name__).exception(
                        "workbench.submit_pack 失敗：tree_task_id=%s", row["id"],
                    )


def schedule_diagnosis(org_id: str, brand_id: str) -> None:
    """procrastinate task body（`background.performance_reading`）——票 01（T6c）：程式壓縮
    （`diagnosis.compress()`）→ 三次 `gateway.run_task()`（素材／受眾／錢，固定分工，決定 3）
    → 程式收斂（`diagnosis.converge()`，決定 2／ADR 0057 §6）→ 寫回同一輪第三列（budget）
    `structured_output_json`（決定 8，零 migration，`llm_task.rendered_output` 三個 lens 各自
    的原文原封不動留在各自那一列）。跟另外三支不一樣：這裡不需要凍結任何上一輪的 row id
    ——每次都是重新從目前的花費／綁定/座標現況算，沒有「插隊」問題。"""
    with connection() as conn:
        performance = performance_mod.brand_creative_performance(conn, org_id, brand_id)
        breakeven = diagnosis_mod.breakeven_roas(conn, org_id, brand_id)
        compressed = diagnosis_mod.compress(performance, breakeven)
        # issue diagnosis-lacks-checkable-numbers：核准活動樹那一步講過的提醒，判讀這一步也
        # 要看得到——否則系統會一邊提醒「不以點擊率單獨判斷」，一邊推薦一條只看 ROAS 的建議。
        reminders = diagnosis_mod.reminders_text(diagnosis_mod.tree_reminders(conn, brand_id))
        # 票 05：判讀讀的是診斷已經在讀的那棵樹（`diagnosis_mod.tree_reminders` 用的同一支
        # `state._display_task_row`），跟外殼判斷「這棵樹以為的預算層」是否跟 Meta 實際掛
        # 預算的層吻合——None 就不加這段，prompt 不變。
        tree_row_for_budget, _tree_running = state._display_task_row(
            conn, brand_id, state.TREE_TASK_TYPE
        )
        budget_note = (
            binding_mod.budget_placement_note(conn, org_id, brand_id, tree_row_for_budget)
            if tree_row_for_budget is not None else None
        )
        budget_section = (
            f"【預算層級】\n{budget_note}\n"
            "這一期各座標花多少是 Meta 最佳化器分配的結果，不是使用者的實驗設計；花費差異"
            "不能讀成使用者的選擇，也不能當成對照實驗的結果。"
        ) if budget_note else None

        label_to_key = diagnosis_mod.label_map_from_performance(performance)

        methodology_result = methodology.compile(
            conn, state.DIAGNOSIS_METHODOLOGY_TASK_LABELS, brand_id=brand_id
        )
        brand = bi_repo.get_brand(conn, brand_id)
        brand_version = brand["knowledge_version"] if brand else 1

        round_id = new_id("dgr")
        raw_outputs: list[dict] = []
        row = None
        # 票 F04-I05：三個 lens 共用的前四段（methodology／compressed／reminders／budget）
        # 逐字相同，只算一次（本來每一圈重算），標上 cache_control 讓 Anthropic 第二三次
        # 用讀取價（0.1 倍）取代重新輸入——這是全站唯一一個「同樣的 bytes 在幾秒內故意送三次」
        # 的呼叫點；其他呼叫點每次 prompt 都不同，加快取只會多付 25% 寫入費（ARCHITECTURE.md §1）。
        # `app/llm/providers.py::_build_codex_prompt` 已經會把 list content 攤平、只取
        # type == "text" 的 block，cache_control 這個鍵它看都不看，本機 codex 線路不受影響。
        shared_prefix = "\n\n".join(
            section for section in (methodology_result.text, compressed, reminders, budget_section)
            if section
        )
        for lens in diagnosis_mod.LENSES:
            context = gateway.TaskContext(
                context_scope={"brand_id": brand_id, "round_id": round_id, "lens": lens},
                knowledge_item_ids=[], brand_version=brand_version, product_version=None,
            )
            row = gateway.run_task(
                conn, PROVIDER, brand_id=brand_id, task_type=state.DIAGNOSIS_TASK_TYPE,
                prompt_template_id=state.DIAGNOSIS_TASK_TYPE, prompt_template_version="v1",
                system=None,
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": shared_prefix,
                     "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": "\n\n" + diagnosis_mod.role_text(lens)},
                ]}],
                context=context,
            )
            parsed = plan_mod._extract_last_json_block(row.get("rendered_output") or "")
            raw = (parsed or {}).get("suggestions") if isinstance(parsed, dict) else None
            valid = diagnosis_mod._valid_suggestions(
                raw if isinstance(raw, list) else [], label_to_key
            )
            for item in valid:
                item["lens"] = lens
            raw_outputs.extend(valid)

        assert row is not None  # diagnosis_mod.LENSES 非空，迴圈至少跑過一次，這裡必然有值
        # issue diagnosis-lacks-checkable-numbers：收斂完由程式補上可核對的數字（這一組的
        # 花費／廣告數／ROAS＋同維度前三名對照組），在寫進 structured_output_json 之前補，
        # 讓那一輪的數字跟那一輪的建議凍在一起——之後月份一換，讀回來的數字才不會偷偷變成
        # 另一個月的（「追溯改寫歷史」那一族）。
        converged = diagnosis_mod.attach_checkable_numbers(
            diagnosis_mod.converge(raw_outputs), performance
        )
        # 決定 8：收斂後的前 5 條寫回**同一輪第三列**（budget，三個 lens 固定跑的最後一個）
        # 的 structured_output_json——不另建表，`round_id` 相同即可認親。
        conn.execute(
            "UPDATE llm_task SET structured_output_json = %s WHERE id = %s",
            (jsonb(converged), row["id"]),
        )
        conn.commit()


_JOBS = {
    state.TASK_TYPE: schedule_plan,
    state.TREE_TASK_TYPE: schedule_tree,
    state.DIAGNOSIS_TASK_TYPE: schedule_diagnosis,
}


def register_tasks() -> None:
    """掛三個生成 task，冪等（可以呼叫任意次）——同一個原因、同一個模式，見
    `app/meta/daily_pull.py` 檔頭：`app.background.app()` 的 DSN 換了會整顆重建，只註冊一次
    在 import 期會在任何 DSN 換過之後悄悄失效。task 名稱＝`background.<task_type>`，跟
    `routes.py` 端點 enqueue 時組的字串（`f"background.{TASK_TYPE}"`）是同一個。"""
    for task_type, func in _JOBS.items():
        background.register(f"background.{task_type}", func)
