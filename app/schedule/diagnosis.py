"""app/schedule/diagnosis.py — 票 01（T6c，`docs/issues/ad-loop/spec.md` 「T6c 規格」節）：
成效判讀（後端）。

Private to app/schedule/（集裝箱憲章第一節）：只有 `app/schedule/routes.py`／`jobs.py` 匯入
這裡的函式，外面任何模組都不 import 這個檔案。

一條線：畫面按「跑一次診斷」→ `compress()`（程式壓縮，純算術）→ 三次 LLM（素材／受眾／錢，
`jobs.schedule_diagnosis()`）→ `converge()`（程式收斂：去重＋按影響金額排序取前 5，
ADR 0057 §6）→ 存回同一輪第三列 `llm_task.structured_output_json`（決定 8，零 migration）→
`brand_diagnosis_response()` 讀回來。收斂只信程式算的錢，AI 只負責判斷方向——這條界線是
2026-08-31「24-agent／130 條建議」失敗教訓定案的，這個檔案是它的落地。

打平線＝1÷毛利率（決定 1），三層 fallback，絕不回 1.0（那等於宣稱毛利 100%，會把賠錢的
座標畫成贏家）：
  ①這個月官網訂單算出來的實際毛利率（`app/orders.repository.sku_margins`，已登記成本的
    SKU 才算數；一個都沒登記＝已知營收為 0＝往下一層）
  ②規則卡 `gross_margin`（決定 1b，`app/core/rule_cards.py` 新增一筆，default 0.70）
  ③兩層都沒有算出一個 >0 的毛利率＝回 (None, 人話原因)，畫面明說算不出來。
"""

from __future__ import annotations

from datetime import timedelta

from app.core import rule_cards
from app.core import settings as coresettings
from app.orders import repository as orders_repo
from app.schedule import performance, state

# 七個維度的中文標籤，跟 `app/schedule/creative.py` 的 `COORDINATE_KEYS` 同一個順序來源
# （不另開一份清單）——`performance._coordinate_labels()` 給的是座標**值**的 label，這裡是
# 維度本身的 label，兩者不是同一件事。
DIMENSION_LABELS = {
    "audience": "受眾", "pain": "痛點", "angle": "角度", "hook": "鉤子",
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

    card_margin_rate = rule_cards.get_value(conn, brand_id, "gross_margin", "gross_margin_rate")
    if card_margin_rate and card_margin_rate > 0:
        return round(1 / card_margin_rate, 2), f"規則卡毛利率 {card_margin_rate:.0%}"

    return None, "還沒有毛利率"


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
    （`schedule_repo.list_coordinates()` 現有資料）把它解回真正的 key——跟
    `repository._resolve_coordinates()` 同一個既有手法（比對不到就丟掉這一條，不整批作廢）。
    `coordinate_key` 對不上這個品牌現有座標的那一條整條丟掉：代理捏造的座標值不進收斂。"""
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


# 決定 9：`rule_type` 由 `dimension` 決定，只用既有三個值。前兩條涵蓋現行七個維度
# （COORDINATE_KEYS）；第三條（budget_split）現在留好、合法輸入碰不到——跟 `direction`
# 四選項現在只用得到前三個是同一個道理（ticket 原文：枚舉現在就留好，日後開啟是打開開關，
# 不是改結構）。
_AUDIENCE_DIMENSIONS = frozenset({"audience", "pain"})
_ANGLE_DIMENSIONS = frozenset({"angle", "hook", "proof", "offer", "format"})


def rule_type_for_dimension(dimension: str) -> str:
    if dimension in _AUDIENCE_DIMENSIONS:
        return "audience"
    if dimension in _ANGLE_DIMENSIONS:
        return "angle"
    return "budget_split"


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
    suggestions = [
        {**entry, "rule_type": rule_type_for_dimension(entry["dimension"])}
        for entry in budget_row.get("structured_output_json") or []
    ]
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
    _round_date, suggestions = _round_result(rows)

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
