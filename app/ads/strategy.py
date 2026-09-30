"""app/ads/strategy.py — F03-I05: one recommended strategy, with its reasons and its unknowns,
and the loop's memory in it (§0 "strategy" link). Input: the draft campaign, the brand facts
with their update times, today's effective product prices for this campaign's own products, the
learnings from `learning_ledger`, and the program's budget scenarios. Output: the strategy
payload the plan issue (F03-I06) turns into rows. Trace: the `llm_task` row plus a `basis` naming
exactly which rows fed the prompt (查看策略依據). Private to app/ads (container contract §1):
only `routes.py` imports `generate`/`select_scenario`.

The model never does arithmetic: it returns percentages (`allocation[].pct`) and reasons only;
`budget.split()` (the program) turns a percentage into a NT$ amount. `budget_planned` is a record
of what the user adopted — after 採用策略 the group daily budgets are the truth, and nothing here
ever recomputes `budget_planned` from them (F03.md "One source of truth for money").
"""

from datetime import UTC, datetime

from app.ads import (
    budget,
    calendar_tw,
    coordinate_learning,
    judgment,
    launch_settings,
    learning,
    targets,
)
from app.ads import repository as ads_repo
from app.brand_intelligence import benchmarks
from app.brand_intelligence import repository as bi_repo
from app.core import rule_cards
from app.core import settings as coresettings
from app.core.db import APP_DIR
from app.llm import gateway, providers

DEPARTMENT_PATH = APP_DIR / "departments" / "ads" / "strategy.md"

# 唯一的供應商實例，比照 app/ads/brief.py：測試用
# `mock.patch.object(strategy, "PROVIDER", FakeProvider(...))` 換掉。
PROVIDER = providers.AnthropicProvider()

# F33-I01（ruling 1A）：三個角色的固定順序——【可用角色】那一行照這個順序印（Contract P），
# `_available_roles()` 只會從這裡拿掉沒有來源的 `retarget`，不會加新角色。
_ROLE_ORDER = ("new", "retarget", "explore")

# role -> 中文名稱：程式自己填 label，不再叫模型回一個我們已經知道的答案（F04-I03）。
_ROLE_LABELS = {"new": "新客", "retarget": "再行銷", "explore": "探索"}

# 這段的上限跟 `list_learnings` 的上限一樣是模組層常數：不是可調規則卡（那是給使用者調的
# 門檻），這裡只是「prompt 別灌爆」的成本上限。
_MAX_LEARNINGS = 10
# 讀幾筆來挑「每個商品最新一條」——同一個上限的讀取量，不是 prompt 的條數。
_LEARNING_SCAN = 200

STRATEGY_FAILED_MESSAGE = "AI 沒能整理出一個可信的策略，請再試一次。"


def _days(start_date, end_date) -> int:
    if start_date is None or end_date is None:
        return 0
    return max((end_date - start_date).days + 1, 0)


def _brand_facts_section(conn, brand_id: str) -> tuple[str, list[dict]]:
    """事實太多會把 prompt 灌到失焦——跟 `app/llm/context_compiler.py` 同一張規則卡
    （`rule_prompt_cap.max_active_rules`），只是這裡挑的是新到舊的事實，不是規則。
    `basis` 只收真的進 prompt 的那幾筆：查看策略依據要等於模型真的看過的東西。"""
    facts = bi_repo.list_brand_facts(conn, brand_id, status="confirmed")
    if not facts:
        return "【品牌事實】（尚無確認過的事實）", []
    cap = int(rule_cards.get_value(conn, brand_id, "rule_prompt_cap", "max_active_rules"))
    facts = sorted(
        facts, key=lambda f: f.get("confirmed_at") or f.get("created_at"), reverse=True,
    )
    kept, omitted = facts[:cap], facts[cap:]
    lines = [f"- {f['label']}：{f['value']}" for f in kept]
    if omitted:
        lines.append(f"（另有 {len(omitted)} 筆較舊的品牌事實沒有列出）")
    basis = [{"id": f["id"], "label": f["label"], "updated_at": f["updated_at"]} for f in kept]
    return "【品牌事實】\n" + "\n".join(lines), basis


# 一個母產品最多印幾種賣法（ARCHITECTURE.md §1：每個進 prompt 的清單都要 cap）。
_MAX_SELL_WAYS = 8


def _sell_way_display_name(full_name: str) -> str:
    """賣法的顯示名已經是「<母產品名> · <賣法>」，這裡只印「 · 」後半段；找不到分隔就整個印。"""
    return full_name.split(" · ", 1)[-1]


def _products_section(
    conn, org_id: str, brand_id: str, product_ids: list[str],
) -> tuple[str, list[dict]]:
    """這個 Campaign 自己的商品（`context_json.product_ids`，已由 F03-I19 的 PATCH 過濾過只
    會是這個品牌自己的商品）；今天有效的價格，過期一律標出來，絕不悄悄當現在的價格用
    （跟 `app/ads/brief.py::_products_context` 同一條規則）。

    一個產品、很多賣法（ARCHITECTURE.md §8 第 1 條）：知識掛母產品、金額掛賣法。這裡先按
    `bi_repo.knowledge_product_id()` 分組，一個母產品一個事實區塊＋一行賣法價格清單；
    `basis` 仍然一個賣法一筆，畫面的「查看策略依據」對得起來。"""
    if not product_ids:
        return "【商品】（這個 Campaign 沒有指定商品）", []
    today = coresettings.today_for_org(conn, org_id=org_id)
    fact_cap = int(rule_cards.get_value(conn, brand_id, "rule_prompt_cap", "max_active_rules"))

    groups: dict[str, list[str]] = {}
    for product_id in product_ids:
        product = bi_repo.get_product(conn, brand_id, product_id)
        if product is None:
            continue  # 存的 id 對不到現存商品——不編一個不存在的商品進 prompt
        mother_id = bi_repo.knowledge_product_id(conn, brand_id, product_id)
        groups.setdefault(mother_id, []).append(product_id)

    lines: list[str] = []
    basis: list[dict] = []
    for mother_id, sell_way_ids in groups.items():
        mother = bi_repo.get_product(conn, brand_id, mother_id)
        mother_name = mother["name"] if mother else mother_id

        facts = sorted(
            bi_repo.list_product_facts(conn, brand_id, mother_id, status="confirmed"),
            key=lambda f: f.get("confirmed_at") or f["created_at"], reverse=True,
        )
        kept_facts, omitted_facts = facts[:fact_cap], facts[fact_cap:]
        fact_text = (
            "；".join(f"{f['label']}：{f['value']}" for f in kept_facts)
            if kept_facts else "尚無確認過的事實"
        )
        if omitted_facts:
            fact_text += f"（另有 {len(omitted_facts)} 筆較舊的事實沒有列出）"

        sell_way_pieces: list[str] = []
        for product_id in sell_way_ids[:_MAX_SELL_WAYS]:
            sell_way = bi_repo.get_product(conn, brand_id, product_id)
            display = _sell_way_display_name(sell_way["name"]) if sell_way else product_id
            economics = bi_repo.get_product_economics(conn, brand_id, product_id)
            if economics is None:
                sell_way_pieces.append(f"{display} 沒有價格資料")
                continue
            effective_to = economics.get("effective_to")
            stale = effective_to is not None and effective_to < today
            price = economics.get("selling_price")
            piece = f"{display} NT${price}"
            if stale:
                piece += "（價格可能過期，僅供參考）"
            sell_way_pieces.append(piece)
            basis.append({
                "product_id": product_id, "price": price,
                "effective_from": economics.get("effective_from"), "stale": stale,
                "assumptions": list(economics.get("assumptions_json") or []),
                "sell_way_name": display,
            })
        sell_way_overflow = len(sell_way_ids) - _MAX_SELL_WAYS
        sell_way_text = "／".join(sell_way_pieces)
        if sell_way_overflow > 0:
            sell_way_text += f"（另有 {sell_way_overflow} 種賣法沒有列出）"

        lines.append(f"- {mother_name}｜事實：{fact_text}\n  賣法：{sell_way_text}")

    text = "【商品】\n" + "\n".join(lines) if lines else "【商品】（沒有可用的價格資料）"
    return text, basis


# product_economics.assumptions_json 的欄位名 -> app.brand_intelligence.benchmarks 的 key
# （ruling 17：假設值的名稱與百分比一律從那份對照表取，這裡不重寫一份文字）。
_ASSUMPTION_BENCHMARK_KEYS = {
    "cost": "gross_margin", "shipping": "shipping_cost", "close_rate": "close_rate",
}


def _assumption_note(prices_basis: list[dict]) -> str | None:
    """一個都沒有假設值就回 `None`（呼叫端不落地這個鍵）；否則印「用的是假設：<賣法>的
    <label、label>——之後用真實數字取代」，名稱與百分比全部來自 `benchmarks.get()`。"""
    parts = []
    for row in prices_basis:
        fields = row.get("assumptions") or []
        labels = [
            benchmarks.get(_ASSUMPTION_BENCHMARK_KEYS[f])["label"]
            for f in fields if f in _ASSUMPTION_BENCHMARK_KEYS
        ]
        if labels:
            parts.append(f"{row.get('sell_way_name') or row['product_id']}的" + "、".join(labels))
    if not parts:
        return None
    return f"用的是假設：{'；'.join(parts)}——之後用真實數字取代。"


# 事件學習（暫停確認、A/B、月結算：`ads_learnings.py`／`settle.py`）的 scope 都以這個前綴開頭，
# 每一條是一個獨立發現；其餘的 ads 軌列是 `learning.write_learning` 寫的「這一期結案判決」句子。
_EVENT_SCOPE_PREFIX = "ads;"


def _newest_per_product(rows: list[dict]) -> list[dict]:
    """F41-I02 (drill-8 #11): one current campaign verdict per `product_id` -- `rows` come newest
    first (`learned_at DESC`), so the first verdict of each product wins; a NULL product is one
    brand-level row. An older period's verdict that contradicts the newer one never reaches the
    model. Event learnings (`ads;` scope: each one its own finding, never a period verdict) pass
    through untouched; the order stays newest first."""
    seen: set = set()
    kept = []
    for row in rows:
        if not (row.get("applicability_scope") or "").startswith(_EVENT_SCOPE_PREFIX):
            if row.get("product_id") in seen:
                continue
            seen.add(row.get("product_id"))
        kept.append(row)
    return kept


def _learnings_section(conn, brand_id: str) -> tuple[str, list[dict]]:
    """`list_learnings(conn, brand_id)`——不帶 `product_id`：那是等值過濾，帶了會把幾乎所有
    品牌層學習都濾掉（F03.md 對 F03-I05 的明確警告）。F41-I02：每個商品只留最新一條
    （`_newest_per_product`），prompt 與 `basis.learnings` 用同一份縮減後的清單。"""
    learnings = _newest_per_product(
        bi_repo.list_learnings(conn, brand_id, limit=_LEARNING_SCAN, source_track="ads"),
    )[:_MAX_LEARNINGS]
    if not learnings:
        return "【過去的學習】（這個品牌還沒有任何學習記錄）", []
    lines = [
        f"- {row['learning_text']}（{row['confidence']}"
        + ("，需要重新驗證" if row["needs_revalidation"] else "") + "）"
        for row in learnings
    ]
    basis = [
        {
            "id": row["id"], "text": row["learning_text"], "level": row["confidence"],
            "needs_revalidation": row["needs_revalidation"],
        }
        for row in learnings
    ]
    return "【過去的學習】\n" + "\n".join(lines), basis


def _scenarios_section(scenario_result: dict) -> str:
    lines = [
        f"- {row['label']}（{row['key']}）：日預算 {row['daily']}／{row['caption']}"
        for row in scenario_result["scenarios"]
    ]
    header = (
        f"【程式算好的預算情境（{scenario_result['mode']}，"
        f"推薦 {scenario_result['recommended']}）】"
    )
    return header + "\n" + "\n".join(lines)


def _str_list(value) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _pct_sum_valid(allocation: list[dict]) -> bool:
    """同一條「加總落在 99～101、不能是負數」的規則，`_validate_reply` 跟
    `set_allocation` 共用（F04-I13）——理由見下面 `_validate_reply` 那段。"""
    pct_sum = sum(row["pct"] for row in allocation)
    return (99 <= pct_sum <= 101) and all(row["pct"] >= 0 for row in allocation)


def _validate_reply(data, available: frozenset[str]) -> dict | None:
    """`available` 是程式列給模型的【可用角色】（Contract P）：回覆點名一個不在裡面的角色
    （例如沒有再行銷來源的品牌被分了 `retarget`）就整包退回 `None`——`plan.py` 會把每個
    分配到的角色展開成投放組，一個交接時拿不到受眾的再行銷組不能活到那一步。"""
    if not isinstance(data, dict):
        return None
    allocation = data.get("allocation")
    if not isinstance(allocation, list) or not allocation:
        return None
    validated_allocation = []
    for item in allocation:
        if not isinstance(item, dict):
            return None
        role = item.get("role")
        if role not in available:
            return None
        pct = item.get("pct")
        if isinstance(pct, bool) or not isinstance(pct, (int, float)):
            return None
        rationale = item.get("rationale")
        # `label` 由程式對照 `_ROLE_LABELS` 填，不再要求模型回——那是花錢買一個我們已經知道
        # 的答案（F04-I03）。模型舊行為回了 `label` 也不理會，一律以程式的對照表為準。
        validated_allocation.append({
            "role": role, "label": _ROLE_LABELS[role], "pct": float(pct),
            "rationale": rationale if isinstance(rationale, str) else None,
        })

    if not _pct_sum_valid(validated_allocation):
        # 回覆的百分比沒有大致加總到 100，或帶負數——`budget.split()` 的餘數規則會把落差整個
        # 塞進佔比最大的那一項，畫面卻照樣印模型回的原始百分比，兩邊會對不起來。
        return None
    roles = [row["role"] for row in validated_allocation]
    if len(roles) != len(set(roles)):
        # 同一個 role 出現兩次：`plan.adopt_strategy` 用 role 當 key 塞金額，重複的 role 會
        # 讓其中一列的金額悄悄消失，group 日預算加總就會少於 budget_planned（§0）。
        return None

    alternatives = data.get("alternatives")
    return {
        "allocation": validated_allocation,
        "why": _str_list(data.get("why")),
        "unknowns": _str_list(data.get("unknowns")),
        "alternatives": alternatives if isinstance(alternatives, list) else [],
        "learning_goals": _str_list(data.get("learning_goals"))[:3],
    }


def _apply_amounts(allocation: list[dict], total: float | None) -> list[dict]:
    """把模型的百分比換成整數 NT$（`budget.split()`），總和精準等於 `total`——`total` 是
    `None`（冷啟動又沒有價格資料）時金額一律 `None`，不是 0（沒有依據的 0 一樣是編數字）。
    用位置索引當 `split()` 的 key，避免兩個角色剛好同一句 label 撞在一起。"""
    if total is None or not allocation:
        return [dict(row, amount=None) for row in allocation]
    weights = {str(i): (row["pct"] or 0) / 100 for i, row in enumerate(allocation)}
    amounts_by_index = {row["label"]: row["amount"] for row in budget.split(total, weights)}
    return [
        dict(row, amount=amounts_by_index.get(str(i)))
        for i, row in enumerate(allocation)
    ]


def _count_text(value) -> str:
    """一個平台讀回的合計：`None` 是「這個欄位沒追蹤到」，不是 0（不編數字）。"""
    if value is None:
        return "不知道（沒追蹤到）"
    number = float(value)
    return f"{int(number):,}" if number.is_integer() else f"{number:,}"


def _starting_point_section(brand: dict, history: dict | None, reads: dict, campaign: dict) -> str:
    """F33-I01：程式早就知道、以前卻沒進 prompt 的「這個品牌從哪裡開始」。每一行不知道就寫
    不知道；沒讀過平台資料寫「還沒讀過」，不是 0。訂單不在 ads 模組（`may_depend_on` 沒有
    `orders`），所以固定一行叫模型別假設有回購名單。"""
    advertising_history = brand.get("advertising_history")
    if advertising_history == "has_history":
        asked = "精靈答過：投放過"
    elif advertising_history == "none":
        asked = "精靈答過：沒投放過"
    else:
        asked = "精靈還沒問"

    if history is None:
        history_text = "沒有可用的花費歷史"
    else:
        history_text = f"{history['source_text']}（樣本 {history['sample_days']} 天）"

    if not reads["external_rows_ever"]:
        readback = "還沒讀過平台資料"
    elif not reads["external_rows_90d"]:
        readback = "近 90 天沒有資料（更早的有讀過）"
    else:
        readback = (
            f"點擊 {_count_text(reads['external_clicks_90d'])}、"
            f"購買 {_count_text(reads['external_purchases_90d'])}"
        )

    loop_purchases = reads["loop_purchases"]
    loop_text = f"{_count_text(loop_purchases)} 筆" if loop_purchases else "沒有"

    pixels = launch_settings.cached_pixels(campaign)
    pixel_text = f"已讀到 {len(pixels)} 個像素" if pixels is not None else "還沒讀像素"

    # F39-I05 (drill-7 #5): once the brand has closed campaigns through the system, the wizard
    # answer is only an initial value and the closed periods are stated as facts.
    closed_lines = _closed_campaign_lines(reads)
    if closed_lines:
        asked = (
            f"{asked}（初始值；已用這個系統結案 {reads['closed_campaigns']} 期，"
            "以下列實際結果為準）"
        )

    return "【這個品牌的起點】\n" + "\n".join([
        f"- 投放過沒：{asked}",
        *closed_lines,
        f"- 花費歷史：{history_text}",
        f"- 近 90 天平台讀回：{readback}",
        f"- 迴圈購買（已結案的活動）：{loop_text}",
        f"- 像素：{pixel_text}",
        "- 訂單：訂單資料不在這裡，別假設有回購名單",
    ])


def _closed_campaign_lines(reads: dict) -> list[str]:
    """F39-I05: 「已結案 N 期；最近一期…」 -- one line, only with N >= 1. A missing number or
    verdict prints 「—」 (older `verdict_json` shapes are not backfilled); money prints the way
    the learning sentence prints it."""
    closed_campaigns = reads.get("closed_campaigns") or 0
    if closed_campaigns < 1:
        return []
    last = reads.get("last_closed") or {}
    actual = _money_or_dash(last.get("actual"))
    target = _money_or_dash(last.get("target"))
    verdict = last.get("verdict") or "—"
    return [
        f"- 已結案：{closed_campaigns} 期；最近一期「{last.get('name') or '—'}」"
        f"每筆 {actual} 對上限 {target}，結果 {verdict}"
    ]


def _money_or_dash(value) -> str:
    if value is None:
        return "—"
    return str(learning._number(float(value)))


def _available_roles(brand: dict, reads: dict) -> list[str]:
    """Ruling 1A：`retarget` 只在有再行銷來源時才列——精靈答過投放過、近 90 天平台讀回有點擊、
    或任何一種購買（迴圈或平台）> 0。只有「> 0」，大小交給模型衡量。`new`／`explore` 永遠在。"""
    has_source = (
        brand.get("advertising_history") == "has_history"
        or (reads["external_clicks_90d"] or 0) > 0
        or (reads["external_purchases_90d"] or 0) > 0
        or (reads["loop_purchases"] or 0) > 0
    )
    return [role for role in _ROLE_ORDER if role != "retarget" or has_source]


def _available_roles_section(roles: list[str]) -> str:
    """Contract P：第一行正好是 `【可用角色】`，第二行是角色 key 用「、」接起來（固定順序）。
    e2e 的腳本供應商照這段文字決定回幾個角色，改字先看 F33-I00。"""
    return "【可用角色】\n" + "、".join(roles)


def _cap_text(cap: float | None) -> str:
    """The one cap as the strategy prompt reads it (F28-I01) -- `未設定`, never a guessed number."""
    return "未設定" if cap is None else f"{round(cap):,}"


def generate(conn, org_id: str, brand_id: str, campaign_id: str, *, actor: str) -> dict:
    """組context、打模型、套 `budget.scenarios()`／`budget.split()`，整包寫進
    `ads_campaign.budget_basis_json`。失敗（provider 出錯或回覆解不出來）一律 `ValueError`，
    不落地任何東西——草稿留在 `draft`，沒有寫一半的策略。"""
    ads_repo.require_internal_campaign(conn, org_id, brand_id, campaign_id)
    campaign = ads_repo.get_campaign(conn, org_id, brand_id, campaign_id)
    if campaign is None:
        raise ValueError("campaign_unknown")
    if campaign.get("budget_planned") is not None:
        # 重算今天只會拿新推薦的情境總額去 split() ——已採用的 `budget_planned` 會悄悄跟畫面上
        # 存的分配金額對不上，F03-I06 已經照 `budget_planned` 建過投放組(§0)。
        raise ValueError("strategy_already_adopted")

    product_ids = list((campaign.get("context_json") or {}).get("product_ids") or [])
    facts_text, facts_basis = _brand_facts_section(conn, brand_id)
    products_text, prices_basis = _products_section(conn, org_id, brand_id, product_ids)
    learnings_text, learnings_basis = _learnings_section(conn, brand_id)
    # F39-I02：程式統計的【座標成績表】接在學習句子之後——上一期哪則廣告划算、哪則太貴，
    # 讓分配的 `rationale` 點得出名字；空表就寫「還沒有成績表」，規則不生效。
    # F41-I02：同一份成績表同時產生 prompt 文字與「用到的學習」的座標列（basis 就是模型看過的）。
    board = coordinate_learning.scoreboard(conn, org_id, brand_id)
    board_text, board_ids = coordinate_learning.scoreboard_section(
        conn, org_id, brand_id, board=board,
    )
    coordinate_rows = coordinate_learning.learning_rows(conn, org_id, brand_id, board)

    brand = bi_repo.get_brand(conn, brand_id)
    assert brand is not None  # 已經讀得到這個品牌的 campaign，品牌本身一定還在
    labels = judgment.conversion_labels(brand.get("conversion_goal"))

    history = ads_repo.budget_history(conn, org_id, brand_id)
    days = _days(campaign["start_date"], campaign["end_date"])
    cap = targets.resolve(conn, org_id, brand_id, campaign)["value"]
    scenario_result = budget.scenarios(
        conn, org_id, brand_id, product_ids=product_ids, days=days, history=history,
        conversion_label=labels["conversion"], cap=cap,
    )
    scenario_result = budget.current_scenarios(
        scenario_result, campaign, labels["conversion"], cap=cap,
    )
    scenarios_text = _scenarios_section(scenario_result)

    reads = ads_repo.starting_point_reads(conn, org_id, brand_id)
    starting_point_text = _starting_point_section(brand, history, reads, campaign)
    available_roles = _available_roles(brand, reads)
    roles_text = _available_roles_section(available_roles)
    # F33-I02（Contract Q）：靜態台灣行事曆只列跟期間重疊的列；表外年份會附「沒有資料」的註記。
    calendar_text = calendar_tw.prompt_section(campaign["start_date"], campaign["end_date"])

    knowledge_item_ids = (
        [f["id"] for f in facts_basis]
        + [p["product_id"] for p in prices_basis]
        + [row["id"] for row in learnings_basis]
        + board_ids
    )

    department_text = DEPARTMENT_PATH.read_text(encoding="utf-8")
    prompt = (
        department_text
        + "\n\n## 這次投放\n\n"
        + f"目標句子：{campaign['goal_text']}\n"
        + f"objective：{campaign['objective']}\n"
        + f"上限（每筆購買成本）：{_cap_text(cap)}\n"
        + f"期間：{campaign['start_date']} ~ {campaign['end_date']}"
        + "\n\n" + starting_point_text
        + "\n\n" + roles_text
        + "\n\n" + calendar_text
        + "\n\n" + facts_text
        + "\n\n" + products_text
        + "\n\n" + learnings_text
        + "\n\n" + board_text
        + "\n\n" + scenarios_text
    )

    context = gateway.TaskContext(
        context_scope={"brand_id": brand_id, "campaign_id": campaign_id},
        knowledge_item_ids=knowledge_item_ids, brand_version=brand["knowledge_version"],
    )
    task_row = gateway.run_task(
        conn, PROVIDER, brand_id=brand_id, task_type="ads_strategy",
        prompt_template_id="ads_strategy", prompt_template_version="v1",
        system=None, messages=[{"role": "user", "content": prompt}], context=context,
        options=gateway.TaskOptions(max_tokens=2000, timeout_s=60.0, max_retries=0),
    )
    if task_row["status"] != "succeeded":
        raise ValueError("strategy_failed")
    data = gateway.parse_json_reply(task_row.get("rendered_output") or "")
    strategy_payload = (
        _validate_reply(data, frozenset(available_roles)) if data is not None else None
    )
    if strategy_payload is None:
        raise ValueError("strategy_failed")

    recommended_row = next(
        row for row in scenario_result["scenarios"] if row["key"] == scenario_result["recommended"]
    )
    strategy_payload["allocation"] = _apply_amounts(
        strategy_payload["allocation"], recommended_row["total"],
    )

    estimated_fields = ["daily", "total"] if scenario_result["mode"] == "cold_start" else []
    basis = {
        "knowledge_item_ids": knowledge_item_ids, "llm_task_id": task_row["id"],
        "input_context_hash": task_row["input_context_hash"],
        "brand_facts": facts_basis, "prices": prices_basis, "learnings": learnings_basis,
        "coordinate_scoreboard": board_ids, "coordinate_learnings": coordinate_rows,
        "estimated_fields": estimated_fields,
    }
    assumption_note = _assumption_note(prices_basis)
    if assumption_note is not None:
        basis["assumption_note"] = assumption_note
    budget_basis_json = {"strategy": strategy_payload, "scenarios": scenario_result, "basis": basis}
    ads_repo.save_strategy(conn, org_id, brand_id, campaign_id, budget_basis_json=budget_basis_json)
    detail = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)
    assert detail is not None
    return detail


class OverCapUnconfirmed(ValueError):
    """F28-I03: the chosen total is above the campaign's budget cap and the caller did not send
    `confirm_over_cap` -- carries the numbers the refusal states."""

    def __init__(self, *, total: float, cap: int, over: int):
        super().__init__("over_cap_unconfirmed")
        self.total, self.cap, self.over = total, cap, over


def select_scenario(conn, org_id: str, brand_id: str, campaign_id: str, *,
                     scenario_key: str, custom_total: float | None = None,
                     confirm_over_cap: bool = False, actor: str) -> dict:
    """使用者選最低／推薦／積極／照預算上限，或手打一個總額——重新用已存的百分比 `split()`
    出金額，寫 `budget_planned`／`budget_scenario`（§0）。

    F28-I03：總額超過預算上限（`constraints_json.budget`）時必須帶 `confirm_over_cap=True`，
    否則 `OverCapUnconfirmed`；確認過就存，並在 `budget_basis_json.over_cap_confirmation`
    記下誰、何時、總額、上限、超出多少。上限內或沒有上限時照舊（不留確認紀錄）。"""
    ads_repo.require_internal_campaign(conn, org_id, brand_id, campaign_id)
    campaign = ads_repo.get_campaign(conn, org_id, brand_id, campaign_id)
    if campaign is None:
        raise ValueError("campaign_unknown")
    budget_basis_json = campaign.get("budget_basis_json") or {}
    scenario_result = budget_basis_json.get("scenarios")
    strategy_payload = budget_basis_json.get("strategy")
    if not scenario_result or not strategy_payload:
        raise ValueError("strategy_not_generated")

    if custom_total is not None:
        if isinstance(custom_total, bool) or custom_total <= 0:
            raise ValueError("custom_total_invalid")
        total = custom_total
    else:
        row = next(
            (r for r in scenario_result["scenarios"] if r["key"] == scenario_key), None,
        )
        if row is None:
            raise ValueError("scenario_unknown")
        if row["total"] is None:
            raise ValueError("scenario_amount_unknown")
        total = row["total"]

    budget_cap = budget.budget_cap_of(campaign.get("constraints_json"))
    over = budget.amount_over_cap(total, budget_cap)
    budget_basis_json = {
        k: v for k, v in budget_basis_json.items() if k != "over_cap_confirmation"
    }
    if over:
        assert budget_cap is not None  # `over` is only ever positive against a known cap
        if not confirm_over_cap:
            raise OverCapUnconfirmed(total=total, cap=budget_cap, over=over)
        budget_basis_json["over_cap_confirmation"] = {
            "by": actor, "at": datetime.now(UTC).isoformat(), "total": total,
            "cap": budget_cap, "over": over,
        }

    strategy_payload = dict(strategy_payload)
    strategy_payload["allocation"] = _apply_amounts(strategy_payload["allocation"], total)
    budget_basis_json = {**budget_basis_json, "strategy": strategy_payload}
    ads_repo.select_scenario(
        conn, org_id, brand_id, campaign_id, scenario_key=scenario_key,
        budget_planned=total, budget_basis_json=budget_basis_json,
    )
    detail = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)
    assert detail is not None
    return detail


def set_allocation(conn, org_id: str, brand_id: str, campaign_id: str, *,
                    allocation: list[dict], actor: str) -> dict:
    """F04-I13：採用之前調整三個角色的百分比——`rationale`／`label` 沿用模型當初那一項的值
    （角色的理由是模型寫的，使用者改的只是比例），金額一律 `_apply_amounts()` 重算，不自己
    乘除（§0「模型只回百分比，金額一律 `budget.split()`」）。"""
    ads_repo.require_internal_campaign(conn, org_id, brand_id, campaign_id)
    campaign = ads_repo.get_campaign(conn, org_id, brand_id, campaign_id)
    if campaign is None:
        raise ValueError("campaign_unknown")
    budget_basis_json = campaign.get("budget_basis_json") or {}
    strategy_payload = budget_basis_json.get("strategy")
    if not strategy_payload:
        raise ValueError("strategy_not_generated")

    detail = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)
    assert detail is not None
    if detail["groups"]:
        # 投放組已經展開——group 日預算才是採用後的真相（F03 決策 3），這裡不准回頭改分配。
        raise ValueError("plan_already_adopted")

    existing_by_role = {row["role"]: row for row in strategy_payload["allocation"]}
    validated_allocation = []
    for item in allocation:
        role = item.get("role") if isinstance(item, dict) else None
        if role not in existing_by_role:
            raise ValueError("allocation_invalid")
        pct = item.get("pct")
        if isinstance(pct, bool) or not isinstance(pct, (int, float)):
            raise ValueError("allocation_invalid")
        existing = existing_by_role[role]
        validated_allocation.append({
            "role": role, "label": existing["label"], "pct": float(pct),
            "rationale": existing["rationale"],
        })

    roles = [row["role"] for row in validated_allocation]
    if set(roles) != set(existing_by_role) or len(roles) != len(set(roles)):
        # 不是新增角色的入口——角色集合必須跟既有策略一模一樣，重複的角色一樣會讓
        # `plan.adopt_strategy` 用 role 當 key 塞金額時悄悄少一項。
        raise ValueError("allocation_invalid")
    if not _pct_sum_valid(validated_allocation):
        raise ValueError("allocation_invalid")

    total = campaign.get("budget_planned")
    if total is None:
        scenario_result = budget_basis_json.get("scenarios") or {}
        recommended_row = next(
            (r for r in scenario_result.get("scenarios", [])
             if r["key"] == scenario_result.get("recommended")), None,
        )
        total = recommended_row["total"] if recommended_row else None

    strategy_payload = dict(strategy_payload)
    strategy_payload["allocation"] = _apply_amounts(validated_allocation, total)
    budget_basis_json = {**budget_basis_json, "strategy": strategy_payload}
    ads_repo.save_strategy(conn, org_id, brand_id, campaign_id, budget_basis_json=budget_basis_json)
    detail = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)
    assert detail is not None
    return detail


def set_budget_cap(conn, org_id: str, brand_id: str, campaign_id: str, *,
                   budget_cap, actor: str) -> dict:
    """F28-I03 (user ruling 2026-09-25): the budget cap stays editable after the wizard, in any
    campaign status. A positive whole number sets `constraints_json.budget`, `None` clears it;
    anything else is `ValueError("budget_cap_invalid")`. Internal planning number only: it never
    writes the platform, never touches `budget_planned` or the saved scenario, and is not part of
    any handoff premise -- the next scenarios read (`budget.current_scenarios`) reflects it."""
    if budget_cap is not None and (
        isinstance(budget_cap, bool) or not isinstance(budget_cap, int) or budget_cap <= 0
    ):
        raise ValueError("budget_cap_invalid")
    ads_repo.set_budget_cap(conn, org_id, brand_id, campaign_id, budget_cap=budget_cap)
    detail = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)
    assert detail is not None
    return detail
