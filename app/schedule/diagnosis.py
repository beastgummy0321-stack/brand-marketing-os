"""app/schedule/diagnosis.py — 票 01（T6c 凍結形狀見 `docs/contracts/schedule.md`）：
成效判讀（後端）。

Private to app/schedule/（集裝箱憲章第一節）：只有 `app/schedule/routes.py`／`jobs.py` 匯入
這裡的函式，外面任何模組都不 import 這個檔案。

一條線：畫面按「跑一次診斷」→ `compress()`（程式壓縮，純算術）→ 三次 LLM（素材／受眾／錢，
`jobs.schedule_diagnosis()`）→ `converge()`（程式收斂：去重＋按影響金額排序取前 5，
ADR 0057 §6）→ 存回同一輪第三列 `llm_task.structured_output_json`（決定 8，零 migration）→
`brand_diagnosis_response()` 讀回來。收斂只信程式算的錢，AI 只負責判斷方向——這條界線是
2026-08-31「24-agent／130 條建議」失敗教訓定案的，這個檔案是它的落地。

打平線＝1÷毛利率（決定 1），四層 fallback，絕不回 1.0（那等於宣稱毛利 100%，會把賠錢的
座標畫成贏家）：
  ①這個月官網訂單算出來的實際毛利率（`app/orders.repository.sku_margins`，已登記成本的
    SKU 才算數；一個都沒登記＝已知營收為 0＝往下一層）
  ②這一期方案選的產品，自己填的售價與單位變動成本（`product_economics`）——issue
    diagnosis-lacks-checkable-numbers：使用者兩個產品的數字都填好了（1880／520、990／240，
    毛利 72%／76%），中間卻沒有這一層，打平線用的是預設 0.70。填了資料就要被用到。
  ③規則卡 `gross_margin`（決定 1b，`app/core/rule_cards.py` 新增一筆，default 0.70）
  ④三層都沒有算出一個 >0 的毛利率＝回 (None, 人話原因)，畫面明說算不出來。
"""

from __future__ import annotations

from datetime import timedelta

from app.brand_intelligence import repository as bi_repo
from app.core import rule_cards, vocab
from app.core import settings as coresettings
from app.orders import repository as orders_repo
from app.schedule import performance, state
from app.schedule import tree as tree_mod

# 七個維度的中文標籤，跟 `app/schedule/creative.py` 的 `COORDINATE_KEYS` 同一個順序來源
# （不另開一份清單）——`performance._coordinate_labels()` 給的是座標**值**的 label，這裡是
# 維度本身的 label，兩者不是同一件事。
DIMENSION_LABELS = {
    "audience": "受眾", "pain": "痛點", "angle": "切角", "hook": "鉤子",
    "proof": "證明", "offer": "優惠", "format": "格式",
}

# 決定 3：三個固定 agent 按判斷維度分工，各自只准講自己那一面。budget（預算搬移）不是自己
# 另一個維度——它是「從錢的角度」重新看同一組七個既有維度，跟 creative／audience 用的是
# 同一份座標詞彙表，只是判斷立場不同（2026-09-06 探針量到：受眾器與預算器的建議會重疊）。
LENSES = ("creative", "audience", "budget")
_LENS_DIMENSIONS = {
    "creative": ("angle", "hook", "proof", "offer", "format"),
    "audience": ("audience", "pain"),
    "budget": tuple(DIMENSION_LABELS),
}
_LENS_TOPIC = {
    "creative": "角度／鉤子／證明／優惠／格式——內容本身好不好",
    "audience": "受眾／痛點——這群人對不對",
    "budget": "預算怎麼在既有的座標之間搬動——錢該往哪裡加碼、從哪裡收回",
}

_VALID_DIRECTIONS = frozenset({"scale_up", "scale_down", "keep", "test"})

# 決定 4（`ab-testing.md:75` 原文）：不寫樣本門檻常數、不查 §3 速查表，固定印這一句。
DIRECTIONAL_ONLY_NOTE = "這是方向性判讀，不是統計顯著的結論。"

# spec 新規則：一個維度底下每個座標值都只掛 1 則廣告、且跟另一個維度的分組完全相同時的提示。
COLLINEAR_NOTE = "這幾個維度分不開，因為背後是同一批廣告"


def breakeven_roas(conn, org_id: str, brand_id: str) -> tuple[float | None, str]:
    """打平線（見檔頭三層 fallback）。視窗跟 `performance.brand_creative_performance()`
    同一個（`state._current_month_window`）——AI 看到的數字必須跟畫面那張圖是同一份
    （`docs/contracts/schedule.md`「Position in the prompt decides...」旁邊那條量到的教訓
    的同一種精神：兩份窗口才是更大的錯，2026-09-06 plan review 定案）。"""
    month_start, month_end = state._current_month_window(conn, org_id)
    since = month_start.isoformat()
    until = (month_end - timedelta(days=1)).isoformat()

    sku_rows = orders_repo.sku_margins(conn, brand_id, since=since, until=until)
    known = [r for r in sku_rows if r["margin"] is not None]
    known_revenue = sum(r["revenue"] for r in known)
    if known_revenue:
        margin_rate = sum(r["margin"] for r in known) / known_revenue
        if margin_rate > 0:
            return round(1 / margin_rate, 2), f"這個月官網訂單實際毛利率 {margin_rate:.0%}"

    plan_margin = _plan_products_margin_rate(conn, brand_id)
    if plan_margin is not None:
        return round(1 / plan_margin, 2), f"這一期產品填的售價與成本，毛利率 {plan_margin:.0%}"

    card_margin_rate = rule_cards.get_value(conn, brand_id, "gross_margin", "gross_margin_rate")
    if card_margin_rate and card_margin_rate > 0:
        return round(1 / card_margin_rate, 2), f"規則卡毛利率 {card_margin_rate:.0%}"

    return None, "還沒有毛利率"


def _plan_products_margin_rate(conn, brand_id: str) -> float | None:
    """打平線第②層（issue diagnosis-lacks-checkable-numbers）：這一期方案選的產品，自己填
    的售價與單位變動成本算出來的毛利率。兩者都填齊、售價 > 0 的產品才算數；一個都沒有就回
    None，往下一層（規則卡）走。

    「哪些產品算在這一期裡」＝最新那一列 `schedule_plan` 的 `context_scope_json.product_ids`
    ——出方案時使用者自己勾的那幾個，不是品牌全部的產品（使用者裁決 2026-09-06）。
    加權方式：Σ(售價−成本) ÷ Σ售價，等於「每個產品各賣一單位」的毛利率——逐產品銷量要等
    訂單資料，那正是第①層在做的事，這一層是第①層還沒有資料時的替代品。
    """
    plan_row, _running = state._display_task_row(conn, brand_id, state.TASK_TYPE)
    product_ids = ((plan_row or {}).get("context_scope_json") or {}).get("product_ids") or []
    price_total = 0.0
    margin_total = 0.0
    for product_id in product_ids:
        row = bi_repo.get_product_economics(conn, brand_id, product_id)
        if row is None or row["unit_variable_cost"] is None:
            continue
        price = float(row["selling_price"])
        cost = float(row["unit_variable_cost"])
        if price <= 0:
            continue
        price_total += price
        margin_total += price - cost
    if price_total <= 0 or margin_total <= 0:
        return None
    return margin_total / price_total


def tree_reminders(conn, brand_id: str) -> list[str]:
    """目前這棵活動樹上還掛著的提醒（節點 `warnings`，去重保序）。

    issue diagnosis-lacks-checkable-numbers 的第二個根因：提醒與判讀是兩套規則、互不引用
    ——核准活動樹那一步系統提醒過「要觀察毛利、購買成本與客單價，不以點擊率單獨判斷」，
    判讀卻推薦了一條只看 ROAS 的折扣建議，等於系統自己打自己臉。這支把提醒撈出來給判讀的
    prompt 看；沒有「解除」這個狀態可以問（樹上就只有這一份），所以是「目前這棵樹上的」，
    不是「還沒解除的」。"""
    row, _running = state._display_task_row(conn, brand_id, state.TREE_TASK_TYPE)
    if row is None:
        return []
    tree = tree_mod.tree_from_task_row(row)
    seen: list[str] = []

    def walk(nodes: list) -> None:
        for node in nodes:
            for warning in node["warnings"] or []:
                if warning not in seen:
                    seen.append(warning)
            walk(node["children"])

    walk(tree["nodes"])
    return seen


def reminders_text(reminders: list[str]) -> str:
    """`tree_reminders()` → prompt 的一段；沒有提醒就回空字串（呼叫端會把空段落濾掉）。"""
    if not reminders:
        return ""
    return "\n".join(
        ["## 這個品牌的活動樹上還掛著這些提醒",
         "下面每一條都是這套系統自己在核准那一步講過的話。你的建議不可以跟它們互相矛盾；"
         "真的要建議相反的方向，就在 `evidence` 裡明講為什麼這一次不適用。"]
        + [f"- {r}" for r in reminders]
    )


def _checkable(value: dict) -> dict:
    """一個座標值 → 使用者可以自己核對的那幾個數字（`_bucket()` 的既有欄位，不重算）。"""
    return {
        "label": value["label"], "spend": value["spend"], "ad_count": value["ad_count"],
        "roas": value["roas"], "roas_conservative": value["roas_conservative"],
        "roas_coverage": value["roas_coverage"],
    }


def attach_checkable_numbers(suggestions: list, performance: dict) -> list:
    """每條建議補上「這一組的花費／廣告數／ROAS」與同一維度其他座標值的對照數字。純函數。

    issue diagnosis-lacks-checkable-numbers：有三年經驗的使用者逐條檢查後，只採用「有寫
    花費」的那幾條——「折扣特價優惠優於無優惠，ROAS 2.50x 高於無優惠的 2.01x」被她拒絕，
    因為沒有兩邊各自的花費與樣本數可以核對。那些數字本來就在同一份壓縮輸入裡（座標成效表
    逐值都有），只是組句子時沒印出來。這裡由程式從 `performance` 直接抄，不叫 AI 再講一次
    ——收斂只信程式算的錢（檔頭那條界線）。

    `compared_with` 按花費由大到小取前 3：對照組是給人核對用的，不是把整張表再貼一次。
    """
    out = []
    for suggestion in suggestions:
        values, currency = _dimension_values(performance, suggestion)
        mine = next((v for v in values if v["key"] == suggestion["coordinate_key"]), None)
        peers = sorted(
            (v for v in values if v["key"] != suggestion["coordinate_key"]),
            key=lambda v: -v["spend"],
        )[:3]
        out.append({
            **suggestion,
            "currency": currency,
            "numbers": _checkable(mine) if mine is not None else None,
            "compared_with": [_checkable(v) for v in peers],
        })
    return out


def _dimension_values(performance: dict, suggestion: dict) -> tuple[list, str | None]:
    """這條建議那個維度的座標值清單，以及它們屬於哪個幣別。

    ponytail: 同一個座標值出現在兩個幣別時，取「這條建議的座標值花費比較大」的那一個幣別，
    整組對照數字都從同一個幣別來——絕不跨幣別相加（ADR 0057 §4）。升級路徑：真的有品牌同時
    跑兩個幣別時，改成逐幣別各給一組數字，畫面也要跟著分兩行。"""
    best: tuple[list, str | None] = ([], None)
    best_spend = -1.0
    for cur in performance["currencies"]:
        for dim in cur["dimensions"]:
            if dim["dimension"] != suggestion["dimension"]:
                continue
            mine = next(
                (v for v in dim["values"] if v["key"] == suggestion["coordinate_key"]), None
            )
            spend = mine["spend"] if mine is not None else -0.5
            if spend > best_spend:
                best_spend = spend
                best = (dim["values"], cur["currency"])
    return best


def has_any_tagged_spend(performance: dict) -> bool:
    """任一幣別、任一維度只要有一個座標值（不是「未標座標」）就算有東西可談——矛盾檢查段
    裁決：零座標時不叫代理硬掰，`suggestions` 直接是空的。"""
    return any(
        dim["values"] for cur in performance["currencies"] for dim in cur["dimensions"]
    )


def _pct(spend: float, total: float) -> str:
    return f"{spend / total:.0%}" if total else "—"


def _roas_text(value: float | None) -> str:
    return f"{value:.2f}x" if value is not None else "未追蹤"


def _collinear_dimensions(dimensions: list) -> set[str]:
    """哪些維度彼此分不開：每個維度自己「全部座標值都只掛 1 則廣告」才夠資格比較，資格內
    再用排序過的花費指紋（同一批廣告的花費金額本身就是一組近乎唯一的指紋）比對是否為同一批
    廣告——`compress()` 只拿得到 `performance.brand_creative_performance()` 聚合完的輸出
    （沒有逐廣告的 entity id 可比對），這是在這份輸入下最便宜、且跟 2026-09-06 探針實際量到
    的案例（角度／鉤子／證明／優惠／格式四個維度花費逐字重複）完全對得上的做法。"""
    fingerprints: dict[str, tuple] = {}
    for dim in dimensions:
        values = dim["values"]
        if values and all(v["ad_count"] == 1 for v in values):
            fingerprints[dim["dimension"]] = tuple(sorted(round(v["spend"], 2) for v in values))
    groups: dict[tuple, list[str]] = {}
    for dim_key, fingerprint in fingerprints.items():
        groups.setdefault(fingerprint, []).append(dim_key)
    return {dim_key for group in groups.values() if len(group) > 1 for dim_key in group}


def compress(performance: dict, breakeven: tuple[float | None, str]) -> str:
    """吃 `performance.brand_creative_performance()` 的原樣輸出，吐 markdown 純文字。
    純函數、無 I/O。逐幣別一段：打平線＋來源、方向性判讀提示、逐維度一張表（座標值、花費、
    佔比、保守／樂觀 ROAS、追蹤覆蓋率、廣告數，按花費由大到小排），未標座標當一列印出來
    （標「不可讀」，它是桶子不是破洞——ADR 0057 §5），共線的維度旁邊多印一行提示。"""
    currencies = performance["currencies"]
    if not currencies:
        window = performance["window"]
        return (
            f"這個月（{window['start_date']} ~ {window['end_date']}）沒有任何 Meta 花費資料。"
            f"\n{DIRECTIONAL_ONLY_NOTE}"
        )

    roas, source = breakeven
    breakeven_line = (f"打平線 {roas:.2f}x，來自{source}" if roas is not None
                      else f"算不出打平線：{source}")

    out: list[str] = []
    for cur in currencies:
        total = cur["total_spend"]
        out.append(
            f"# 幣別 {cur['currency']}｜本月總花費 {total:,.0f}"
            f"（{performance['window']['start_date']} ~ {performance['window']['end_date']}）"
        )
        out.append(breakeven_line)
        out.append(DIRECTIONAL_ONLY_NOTE)
        collinear = _collinear_dimensions(cur["dimensions"])
        for dim in cur["dimensions"]:
            values = sorted(dim["values"], key=lambda v: -v["spend"])
            out.append(f"\n## {DIMENSION_LABELS[dim['dimension']]}")
            if dim["dimension"] in collinear:
                out.append(f"（{COLLINEAR_NOTE}）")
            out.append("| 座標值 | 花費 | 佔比 | 保守 ROAS | 樂觀 ROAS | 追蹤覆蓋率 | 廣告數 |")
            out.append("|---|---|---|---|---|---|---|")
            for v in values:
                out.append(
                    f"| {v['label']} | {v['spend']:,.0f} | {_pct(v['spend'], total)} |"
                    f" {_roas_text(v['roas_conservative'])} | {_roas_text(v['roas'])} |"
                    f" {v['roas_coverage']:.0%} | {v['ad_count']} |"
                )
            untagged = dim["untagged"]
            if untagged["spend"]:
                out.append(
                    f"| （這個維度沒有座標值） | {untagged['spend']:,.0f} |"
                    f" {_pct(untagged['spend'], total)} | 不可讀 | 不可讀 | 不可讀 |"
                    f" {untagged['ad_count']} |"
                )
    return "\n".join(out)


def label_map_from_performance(performance: dict) -> dict[tuple[str, str], str]:
    """`(dimension, label) → key` built from **this round's compressed table**, not the brand's
    whole registered-coordinate library (`schedule_repo.list_coordinates()`). plan-quality ticket 02
    (2026-09-08): a coordinate with zero spend this
    round is absent from `performance["currencies"][*]["dimensions"][*]["values"]` — the same
    `values` list `compress()` prints — so it is absent here too, and an agent citing it is
    dropped by `_valid_suggestions()`. This is "coordinates that have a spend row this round",
    not "coordinates with spend > 0": `_currency_view()` buckets every row regardless of amount,
    and this function does not add an amount filter — the map must match what the table showed.
    `untagged` buckets are not coordinates and are skipped. Two currencies naming the same
    `(dimension, label)` collapse to one entry (last one wins; they are identical)."""
    return {
        (dim["dimension"], value["label"]): value["key"]
        for currency in performance["currencies"]
        for dim in currency["dimensions"]
        for value in dim["values"]
    }


def role_text(lens: str) -> str:
    """這個 lens 的角色與輸出格式段——**位置固定擺在 prompt 最後一段**
    （`docs/contracts/schedule.md`「Position in the prompt decides whether an instruction
    runs」，T8b 實機驗收量到的：同一句指令放中間會被前面幾千字方法論／資料蓋過去，放最後
    七格全填對）。純函數，不吃品牌資料——座標詞彙表已經在 `compress()` 印出來的表格裡，
    這裡只教格式，不重複列一次座標清單。"""
    dims = "、".join(f'"{d}"' for d in _LENS_DIMENSIONS[lens])
    return "\n".join([
        "## 你的角色與輸出格式",
        f"你這一輪只負責「{_LENS_TOPIC[lens]}」這個角度，只准對上面表格裡已經出現過的座標值",
        f"下判斷，`dimension` 只能填 {dims} 其中之一——不是這幾個維度的事不要講。",
        "看完上面的資料，回覆最後一段附一個 fenced json block，形狀如下（`suggestions` 可以是",
        "空陣列——上面的表格如果沒有任何一列有意義的座標值可以判斷，就回空陣列，不要硬掰）：",
        '```json',
        '{"suggestions": [{"dimension": "...", "coordinate_label": "...",',
        ' "direction": "scale_up | scale_down | keep | test", "impact_spend": 0,',
        ' "headline": "...", "evidence": "..."}]}',
        '```',
        "`coordinate_label` 必須逐字照抄上面表格「座標值」欄的文字（不可以自己發明新的座標",
        "值）；`impact_spend` 填那一列的「花費」欄；`direction` 只能是 scale_up／scale_down／",
        "keep／test 四個字之一。",
    ])


def _valid_suggestions(raw: list, label_to_key: dict[tuple[str, str], str]) -> list[dict]:
    """代理原始 `suggestions` → 過濾＋補上 `coordinate_key`。代理只看得到座標值的中文
    label（`compress()` 表格），不知道內部 key，所以這裡用 `(dimension, label) → key`
    （`label_map_from_performance()`——這一輪壓縮表裡實際出現的座標值，不是品牌整個座標
    庫）把它解回真正的 key——跟 `repository._resolve_coordinates()` 同一個既有手法（比對不到
    就丟掉這一條，不整批作廢）。`coordinate_key` 對不上這一輪表格裡座標值的那一條整條丟掉：
    代理捏造的座標值、或引用一個這一輪零花費的舊座標值，都不進收斂
    （plan-quality 票 02，2026-09-08）。"""
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        dimension = item.get("dimension")
        label = item.get("coordinate_label")
        direction = item.get("direction")
        impact_spend = item.get("impact_spend")
        if not isinstance(dimension, str) or not isinstance(label, str):
            continue
        key = label_to_key.get((dimension, label))
        if key is None or direction not in _VALID_DIRECTIONS:
            continue
        if isinstance(impact_spend, bool) or not isinstance(impact_spend, (int, float)):
            continue
        out.append({
            "dimension": dimension, "coordinate_key": key, "coordinate_label": label,
            "direction": direction, "impact_spend": float(impact_spend),
            "headline": str(item.get("headline", "")), "evidence": str(item.get("evidence", "")),
        })
    return out


def converge(outputs: list[dict]) -> list[dict]:
    """三個 agent（已過 `_valid_suggestions` 過濾、各自帶 `lens` 標記）的建議 → 前 5 條
    （ADR 0057 §6）。純函數。去重鍵 `(dimension, coordinate_key, direction)`：同鍵留
    `impact_spend` 最大那條的內文，`agreed_by` 把說過這件事的 lens 名字累加成名單（去重保序
    ——重複是信號不是雜訊，spec 新規則）。排序 `impact_spend` 由大到小，取前 5。"""
    best: dict[tuple, dict] = {}
    for item in outputs:
        dedup_key = (item["dimension"], item["coordinate_key"], item["direction"])
        lens = item.get("lens")
        existing = best.get(dedup_key)
        if existing is None:
            entry = {k: v for k, v in item.items() if k != "lens"}
            entry["agreed_by"] = [lens] if lens else []
            best[dedup_key] = entry
            continue
        if lens and lens not in existing["agreed_by"]:
            existing["agreed_by"].append(lens)
        if item["impact_spend"] > existing["impact_spend"]:
            agreed_by = existing["agreed_by"]
            entry = {k: v for k, v in item.items() if k != "lens"}
            entry["agreed_by"] = agreed_by
            best[dedup_key] = entry
    ranked = sorted(best.values(), key=lambda e: -e["impact_spend"])
    return ranked[:5]


# 決定 9（`rule_type` 由 `dimension` 決定，只用 angle／audience／budget_split 三個值）已由
# issue adopted-advice-can-invert 撤銷：七維座標有七個維度、規則型別只有三個，鉤子的結論
# 會被塞進角度的抽屜，下一次 prompt 就把它當角度限制讀。採用現在一律寫
# `vocab.EXPERIMENT_RULE_TYPE`（見 `app/schedule/routes.py::_run_diagnosis_adopt`），維度
# 留在句子裡，不再借別的抽屜；這裡因此不再有「維度換型別」這支函式。


def _round_rows(conn, brand_id: str) -> list[dict]:
    """最新一輪（`round_id` 相同）的 `performance_reading` 列，最多三列。讀 `llm_task` 直接
    下 SQL——跟 `state._latest_task_row()`／`_display_task_row()` 同一個既有慣例（那兩支就是
    這樣直接查 `llm_task`，`app.llm` 沒有另開一支「按 brand/task_type 查多列」的讀取）。"""
    rows = conn.execute(
        "SELECT * FROM llm_task WHERE brand_id = %s AND task_type = %s"
        " ORDER BY started_at DESC LIMIT 30",
        (brand_id, state.DIAGNOSIS_TASK_TYPE),
    ).fetchall()
    rows = [dict(r) for r in rows]
    if not rows:
        return []
    round_id = (rows[0].get("context_scope_json") or {}).get("round_id")
    return [r for r in rows if (r.get("context_scope_json") or {}).get("round_id") == round_id]


def _round_result(rows: list[dict]) -> tuple[str | None, list[dict]]:
    """`rows`（`_round_rows()` 的輸出，同一輪三個 lens）→ (那一輪的日期, 收斂後前 5 條建議)。
    只有整輪三個 lens 都成功才有東西可讀——GET 回應（`brand_diagnosis_response`）與「採用」
    路由（`routes.py` 的 `_run_diagnosis_adopt`）共用這份讀法，不重複寫一次「找 budget lens
    那列、解析 structured_output_json」的邏輯（兩邊的建議清單、索引順序才保證對得上號）。
    還沒判讀過、或這一輪還沒跑完，回 `(None, [])`。"""
    if not rows or any(r["status"] != "succeeded" for r in rows):
        return None, []
    budget_row = next(
        (r for r in rows if (r.get("context_scope_json") or {}).get("lens") == "budget"), None
    )
    if budget_row is None:
        return None, []
    suggestions = list(budget_row.get("structured_output_json") or [])
    return budget_row["started_at"].date().isoformat(), suggestions


def latest_round(conn, brand_id: str) -> tuple[str | None, list[dict]]:
    """`_round_result()` 的獨立呼叫版——「採用」路由自己呼叫這支，不必重新寫一次
    `_round_rows()` 那段「找最新一輪」。"""
    return _round_result(_round_rows(conn, brand_id))


def adopt_content(suggestion: dict, round_date: str) -> str:
    """「採用」把一條建議寫成規則卡的內文（決定 8）：`source_reference_id` 不能用——那一欄
    FK 指向 `source_reference`，塞 `llm_task.id` 會違反約束（plan review 實跑 SQL 證明）。
    來源改寫進這段文字，沿用 `DIRECTIONAL_ONLY_NOTE`（決定 4，`ab-testing.md:75` 原文）而不是
    另外寫一句意思一樣的話——兩份說同一件事的文字，其中一份遲早會跟另一份對不上。"""
    headline = suggestion["headline"].strip()
    evidence = suggestion["evidence"].strip()
    body = f"{headline}，{evidence}" if evidence else headline
    if not body.endswith(("。", "！", "？")):
        body += "。"
    return f"{body}\n（本條來自 {round_date} 的成效判讀，{DIRECTIONAL_ONLY_NOTE}）"


def adopt_key(suggestion: dict, round_date: str) -> tuple[str, str]:
    """The one key a suggestion is "adopted" under: `(rule_type, content)` of the brand-wide
    rule `_run_diagnosis_adopt()` writes. The adopt route dedupes on it and the diagnosis
    response marks `adopted` with it (F31-I06, Contract K), so the two can never disagree.
    Adopting always writes `vocab.EXPERIMENT_RULE_TYPE` (issue adopted-advice-can-invert)."""
    return vocab.EXPERIMENT_RULE_TYPE, adopt_content(suggestion, round_date)


def adopted_rule(conn, brand_id: str, key: tuple[str, str]) -> dict | None:
    """The active brand-wide rule stored under `key`, or None. Product-specific rules never
    count: adopting writes a brand-wide rule only."""
    rule_type, content = key
    return next(
        (r for r in bi_repo.list_rules_for_brand(conn, brand_id)
         if r["product_id"] is None and r["rule_type"] == rule_type and r["content"] == content),
        None,
    )


def _mark_adopted(
    conn, brand_id: str, round_date: str | None, suggestions: list[dict],
) -> list[dict]:
    """Each suggestion plus `adopted: bool` (Contract K). One rule read for the whole list."""
    if round_date is None or not suggestions:
        return [{**s, "adopted": False} for s in suggestions]
    keys = {
        (r["rule_type"], r["content"])
        for r in bi_repo.list_rules_for_brand(conn, brand_id) if r["product_id"] is None
    }
    return [{**s, "adopted": adopt_key(s, round_date) in keys} for s in suggestions]


def brand_diagnosis_response(conn, org_id: str, brand_id: str) -> dict:
    """`GET /api/schedule/brands/{brand_id}/diagnosis` 的本體，`POST` 剛 enqueue 完也回這個
    形狀（比照既有三支生成端點的既有慣例）。`window`／`breakeven` 每次都現查（決定 8：
    `context_scope_json` 字面契約只有三個鍵，沒有地方凍結這兩個數字；規則卡毛利率、月份都
    是會變的東西，現查才不會讓使用者看到一個過期的打平線）。"""
    month_start, month_end = state._current_month_window(conn, org_id)
    today = coresettings.today_for_org(conn, org_id=org_id)
    window = {
        "start_date": month_start.isoformat(),
        "end_date": (month_end - timedelta(days=1)).isoformat(),
        # ponytail: 日曆天數（今天以前月內經過的天數），不是「真的查得到花費資料的天數」
        # ——查後者要另外問 meta_entity_spend，這裡不重讀 performance.py 已經查過的同一批
        # 列（那支的輸出形狀是鎖住的契約，不能為了多吐一個天數欄位就改）。兩者在稀疏帳號
        # 上會有落差；升級路徑：`performance.py` 的輸出形狀真的需要納入這個數字時，跟
        # `roas_conservative` 一樣走一次站①討論再加欄位。
        "days_with_data": max((today - month_start).days, 0),
    }
    roas, source = breakeven_roas(conn, org_id, brand_id)
    breakeven = {"roas": roas, "source": source}

    rows = _round_rows(conn, brand_id)
    if not rows:
        return {
            "status": None, "window": window, "breakeven": breakeven,
            "directional_only": True, "suggestions": [], "lenses": {},
        }

    by_lens = {(r.get("context_scope_json") or {}).get("lens"): r for r in rows}
    if any(r["status"] == "running" for r in rows):
        status = "running"
    elif all(r["status"] == "succeeded" for r in rows):
        status = "succeeded"
    else:
        status = "failed"

    # `_round_result()` 自己會判斷「整輪是否都成功」，這裡不再重複那個判斷；`status` 是
    # 給畫面看的字（running／succeeded／failed），跟 `_round_result()` 內部的守門條件是
    # 同一件事的兩種寫法（都成功 ⇔ status == "succeeded"）。
    round_date, suggestions = _round_result(rows)
    suggestions = _mark_adopted(conn, brand_id, round_date, suggestions)

    lenses = {lens: (row.get("rendered_output") or "") for lens, row in by_lens.items() if lens}

    # 空的建議清單有兩種完全不同的原因，畫面要說的話也不同（票 01 矛盾檢查段的裁決）：
    # 這個月的花費全部落在「未標座標」（沒有東西可談），或是有座標但代理這一輪沒給建議。
    # 只在真的空了才現查一次 performance——正常情況（有建議）不多打一次資料庫。
    no_tagged_spend = False
    if status == "succeeded" and not suggestions:
        no_tagged_spend = not has_any_tagged_spend(
            performance.brand_creative_performance(conn, org_id, brand_id)
        )

    return {
        "status": status, "window": window, "breakeven": breakeven,
        "directional_only": True, "suggestions": suggestions, "lenses": lenses,
        "no_tagged_spend": no_tagged_spend,
    }
