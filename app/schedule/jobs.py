"""app/schedule/jobs.py — the three schedule generations' actual LLM work, private to this
package (only app/schedule/__init__.py exports anything from here, container contract §1).

票 05-1：`app/schedule/routes.py`'s three POST endpoints no longer call the LLM inside the
HTTP request (see that file's docstring for why — a two-to-six-minute blocking POST that a
killed process leaves stuck `running` forever). They validate, then
`background.enqueue("background.<task_type>", ...)` and return immediately. The actual prompt
assembly and `gateway.run_task()` call — what `routes.py`'s `_run_plan`/`_run_tree`/
`_run_creative` used to do after validation — lives here instead, as three procrastinate task
bodies with the frozen signatures the ticket names:

    schedule_plan(org_id, brand_id, product_ids, platform, objective, promotion_note, plan_count)
    schedule_tree(org_id, brand_id, plan_index)
    schedule_creative(org_id, brand_id)

Each opens its own `app.core.db.connection()` — a worker job never inherits a request's
connection. `org_id` is a required first parameter on all three (ADR 0038 gate,
`app/tests/test_background.py::TaskSignatureOrgIdGateTest`, scoped to `background.`-prefixed
task names — these three register under exactly that prefix, see `register_tasks()` below).

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

import json

from app.background import app as background_app
from app.brand_intelligence import repository as bi_repo
from app.core import rule_cards
from app.core.db import connection, jsonb, new_id
from app.llm import context_compiler, gateway, methodology, providers
from app.schedule import binding as binding_mod
from app.schedule import diagnosis as diagnosis_mod
from app.schedule import performance as performance_mod
from app.schedule import plan as plan_mod
from app.schedule import repository, routes, state

# 唯一的供應商實例：這三支 task body 現在是全站唯一真的打代理的地方（routes.py 的三支 POST
# 端點自己不再打），比照 routes.py 搬過來之前的既有寫法——測試用
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


def _creative_params_text(tree: dict) -> str:
    body = {"levels": tree["levels"], "nodes": tree["nodes"]}
    return "\n".join([
        "## 這次要產文案的活動結構",
        json.dumps(body, ensure_ascii=False, indent=2),
    ])


def _coordinate_vocabulary_text(coordinates: list[dict]) -> str:
    """票 T8b：把這個品牌的座標詞彙表變成 prompt 的一節。

    為什麼非有這一節不可：落地時 `repository._resolve_coordinates()` 拿代理回的字串去比對
    `brand_coordinate.label`，比對不到就寫 `NULL`。所以只在部門任務檔改一句「七維都要填」而
    不附這份清單，代理會自己造詞、七格照樣全是 NULL——畫面上卻長得像功能已經動了。

    清單從資料庫讀、不是從 `repository._SEED_COORDINATES` 讀：使用者在「創意座標」分頁停用
    掉的詞（`routes.disable_brand_coordinate`）與自己加的詞（`create_brand_coordinate`）都要
    算數，代理不該挑一個使用者已經劃掉的值。被 `feedback` 否決過的（`rejected`）同樣不給。
    維度順序照 `COORDINATE_KEYS`，跟部門任務檔列的七個鍵同一個順序。"""
    by_dimension: dict[str, list[str]] = {}
    for row in coordinates:
        if row["disabled_at"] is not None or row["rejected"]:
            continue
        situation = (row["attributes"] or {}).get("situation") or ""
        by_dimension.setdefault(row["dimension"], []).append(
            f"- {row['label']}" + (f"——{situation}" if situation else "")
        )
    sections = [
        f"### {dimension}\n" + "\n".join(by_dimension[dimension])
        for dimension in repository.COORDINATE_KEYS if by_dimension.get(dimension)
    ]
    if not sections:
        return ""
    # 這一節排在整份 prompt 的**最後**，而且自己帶一句短提醒——不是為了好看，是量出來的
    # （票 T8b 實機驗收，2026-09-04）：同一顆模型、同一份詞彙表，2,210 字的小 prompt 七格
    # 全填對；21,679 字的正式 prompt 只填得出 `angle`。差別不在措辭（「七個都要填」加了、
    # 拿掉、換成長解釋各試過一輪，都是 1/7），在於座標指令被 8,300 字方法論與 8,600 字
    # 活動樹推到兩萬字之前。**改這裡的順序前先讀這段**：把它搬回中間就會退回 1/7。
    return "\n\n".join([
        "## 這個品牌的座標詞彙表",
        "上面每一則內容的 `coordinates` 七個鍵**都要填**，值就是下面各段列出的 label 原文"
        "（破折號後面是這個值什麼時候用，是說明、不是值的一部分）。"
        "沒放證明填「無證明」、沒給優惠填「無優惠」——那是值，不是 `null`。",
        *sections,
    ])


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
        prompt = "\n\n".join(
            section for section in
            (department_text, methodology_result.text, params_text, brand_context,
             performance_text) if section
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

        brand_context, knowledge_item_ids, brand_version = _compile_brand_context(
            conn, brand_id, product_ids
        )
        department_text = state.TREE_DEPARTMENT_FILE.read_text(encoding="utf-8")
        methodology_result = methodology.compile(
            conn, state.METHODOLOGY_TASK_LABELS, brand_id=brand_id
        )
        params_text = _tree_params_text(platform_label, plan_index, chosen_plan)
        prompt = "\n\n".join(
            section for section in
            (department_text, methodology_result.text, params_text, brand_context) if section
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
        gateway.run_task(
            conn, PROVIDER, brand_id=brand_id, task_type=state.TREE_TASK_TYPE,
            prompt_template_id=state.TREE_TASK_TYPE, prompt_template_version="v1",
            system=None, messages=[{"role": "user", "content": prompt}], context=context,
            options=gateway.TaskOptions(max_tokens=24000, timeout_s=480.0),
            campaign_period_id=campaign_period_id,
        )


def schedule_creative(org_id: str, brand_id: str, tree_task_id: str,
                       campaign_period_id: str | None = None) -> None:
    """procrastinate task body（`background.schedule_creative`）——見 `schedule_plan()` 檔頭。

    fix round 1：`tree_task_id` 是 `routes._run_creative()` enqueue 當下釘住的那一列 id，
    理由跟 `schedule_tree()` 的 `plan_task_id` 一模一樣——這個 job 排隊等執行時，使用者可能
    已經又按了「展開活動樹」，插進一列新的 running `schedule_tree`；重讀『這個品牌最新一次
    schedule_tree』會撿到那一列還在跑、`tree_from_task_row()` 對 running 列回
    `levels: []`／`nodes: []` 不拋例外（app/schedule/tree.py），這支 job 會照著一個空活動樹
    組 prompt、照樣打代理——花了錢，產出跟任何廣告節點對不上。同一個既有的 `source_plan_task_id`
    釘法（見下面 `plan_scope`）已經對過一層，這裡是把同一個模式套用到再上一層。"""
    with connection() as conn:
        tree_row = gateway.get_task(conn, tree_task_id)
        # routes.py 的 _run_creative() 在 enqueue 之前已經驗證過這一列存在且 succeeded；
        # 列從不刪除，這裡讀回來的就是釘住的那一列本身。
        assert tree_row is not None
        tree = binding_mod.tree_with_bindings(conn, tree_row, org_id, brand_id)

        plan_scope = tree_row.get("context_scope_json") or {}
        plan_row = gateway.get_task(conn, plan_scope.get("source_plan_task_id") or "")
        plan_row_scope = (plan_row.get("context_scope_json") or {}) if plan_row else {}
        product_ids = plan_row_scope.get("product_ids", [])

        brand_context, knowledge_item_ids, brand_version = _compile_brand_context(
            conn, brand_id, product_ids
        )
        department_text = state.CREATIVE_DEPARTMENT_FILE.read_text(encoding="utf-8")
        # 票 T1：跟 schedule_plan／schedule_tree 一樣接方法論——這支 job 過去沒有這一段，
        # `creative-matrix.md`（35 個角度）與 `meta-format-specs.md`（5 個變體、字數上限）
        # 都沒有真的貼進 prompt，代理只能自己亂猜。票 T1 站③收尾：改用自己專屬一張清單
        # （見 state.CREATIVE_METHODOLOGY_TASK_LABELS 的理由註解），不再跟計畫／活動樹共用。
        methodology_result = methodology.compile(
            conn, state.CREATIVE_METHODOLOGY_TASK_LABELS, brand_id=brand_id
        )
        # 票 T8b：座標詞彙表放**最後**一段，理由與量到的數字見 `_coordinate_vocabulary_text()`
        # 的檔頭註解——它是這份 prompt 裡唯一「寫完文案之後才要回答」的東西，排在兩萬字
        # 之前就會被淹掉。
        coordinate_text = _coordinate_vocabulary_text(
            repository.list_coordinates(conn, org_id, brand_id)
        )
        params_text = _creative_params_text(tree)
        prompt = "\n\n".join(
            section for section in
            (department_text, methodology_result.text, params_text, brand_context,
             coordinate_text) if section
        )

        context = gateway.TaskContext(
            context_scope={
                "brand_id": brand_id, "source_tree_task_id": tree_row["id"],
                "plan_index": tree["plan_index"],
            },
            knowledge_item_ids=knowledge_item_ids,
            brand_version=brand_version,
            product_version=None,
        )
        gateway.run_task(
            conn, PROVIDER, brand_id=brand_id, task_type=state.CREATIVE_TASK_TYPE,
            prompt_template_id=state.CREATIVE_TASK_TYPE, prompt_template_version="v1",
            system=None, messages=[{"role": "user", "content": prompt}], context=context,
            options=gateway.TaskOptions(max_tokens=24000, timeout_s=480.0),
            campaign_period_id=campaign_period_id,
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

        coordinates = repository.list_coordinates(conn, org_id, brand_id)
        label_to_key = {(c["dimension"], c["label"]): c["key"] for c in coordinates}

        methodology_result = methodology.compile(
            conn, state.DIAGNOSIS_METHODOLOGY_TASK_LABELS, brand_id=brand_id
        )
        brand = bi_repo.get_brand(conn, brand_id)
        brand_version = brand["knowledge_version"] if brand else 1

        round_id = new_id("dgr")
        raw_outputs: list[dict] = []
        row = None
        for lens in diagnosis_mod.LENSES:
            prompt = "\n\n".join(
                section for section in
                (methodology_result.text, compressed, reminders,
                 diagnosis_mod.role_text(lens)) if section
            )
            context = gateway.TaskContext(
                context_scope={"brand_id": brand_id, "round_id": round_id, "lens": lens},
                knowledge_item_ids=[], brand_version=brand_version, product_version=None,
            )
            row = gateway.run_task(
                conn, PROVIDER, brand_id=brand_id, task_type=state.DIAGNOSIS_TASK_TYPE,
                prompt_template_id=state.DIAGNOSIS_TASK_TYPE, prompt_template_version="v1",
                system=None, messages=[{"role": "user", "content": prompt}], context=context,
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
    state.CREATIVE_TASK_TYPE: schedule_creative,
    state.DIAGNOSIS_TASK_TYPE: schedule_diagnosis,
}


def register_tasks() -> None:
    """掛三個生成 task，冪等（可以呼叫任意次）——同一個原因、同一個模式，見
    `app/meta/daily_pull.py` 檔頭：`app.background.app()` 的 DSN 換了會整顆重建，只註冊一次
    在 import 期會在任何 DSN 換過之後悄悄失效。task 名稱＝`background.<task_type>`，跟
    `routes.py` 端點 enqueue 時組的字串（`f"background.{TASK_TYPE}"`）是同一個。"""
    a = background_app()
    for task_type, func in _JOBS.items():
        name = f"background.{task_type}"
        if name not in a.tasks:
            a.task(name=name)(func)
