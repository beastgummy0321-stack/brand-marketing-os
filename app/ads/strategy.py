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

from app.ads import budget
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import settings as coresettings
from app.core.db import APP_DIR
from app.llm import gateway, providers

DEPARTMENT_PATH = APP_DIR / "departments" / "ads" / "strategy.md"

# 唯一的供應商實例，比照 app/ads/brief.py：測試用
# `mock.patch.object(strategy, "PROVIDER", FakeProvider(...))` 換掉。
PROVIDER = providers.AnthropicProvider()

_ROLES = frozenset({"new", "retarget", "explore"})

STRATEGY_FAILED_MESSAGE = "AI 沒能整理出一個可信的策略，請再試一次。"


def _days(start_date, end_date) -> int:
    if start_date is None or end_date is None:
        return 0
    return max((end_date - start_date).days + 1, 0)


def _brand_facts_section(conn, brand_id: str) -> tuple[str, list[dict]]:
    facts = bi_repo.list_brand_facts(conn, brand_id, status="confirmed")
    if not facts:
        return "【品牌事實】（尚無確認過的事實）", []
    lines = [f"- {f['label']}：{f['value']}（更新於 {f['updated_at']}）" for f in facts]
    basis = [{"id": f["id"], "label": f["label"], "updated_at": f["updated_at"]} for f in facts]
    return "【品牌事實】\n" + "\n".join(lines), basis


def _products_section(
    conn, org_id: str, brand_id: str, product_ids: list[str],
) -> tuple[str, list[dict]]:
    """這個 Campaign 自己的商品（`context_json.product_ids`，已由 F03-I19 的 PATCH 過濾過只
    會是這個品牌自己的商品）；今天有效的價格，過期一律標出來，絕不悄悄當現在的價格用
    （跟 `app/ads/brief.py::_products_context` 同一條規則）。"""
    if not product_ids:
        return "【商品】（這個 Campaign 沒有指定商品）", []
    today = coresettings.today_for_org(conn, org_id=org_id)
    lines: list[str] = []
    basis: list[dict] = []
    for product_id in product_ids:
        product = bi_repo.get_product(conn, brand_id, product_id)
        if product is None:
            continue  # 存的 id 對不到現存商品——不編一個不存在的商品進 prompt
        economics = bi_repo.get_product_economics(conn, brand_id, product_id)
        if economics is None:
            lines.append(f"- {product['name']}｜沒有價格資料")
            continue
        effective_to = economics.get("effective_to")
        stale = effective_to is not None and effective_to < today
        price = economics.get("selling_price")
        line = f"- {product['name']}｜售價 {price}"
        if stale:
            line += "（價格可能過期，僅供參考）"
        lines.append(line)
        basis.append({
            "product_id": product_id, "price": price,
            "effective_from": economics.get("effective_from"), "stale": stale,
        })
    text = (
        "【商品與今天的價格】\n" + "\n".join(lines) if lines else "【商品】（沒有可用的價格資料）"
    )
    return text, basis


def _learnings_section(conn, brand_id: str) -> tuple[str, list[dict]]:
    """`list_learnings(conn, brand_id)`——不帶 `product_id`：那是等值過濾，帶了會把幾乎所有
    品牌層學習都濾掉（F03.md 對 F03-I05 的明確警告）。"""
    learnings = bi_repo.list_learnings(conn, brand_id)
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


def _validate_reply(data) -> dict | None:
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
        if role not in _ROLES:
            return None
        label = item.get("label")
        if not isinstance(label, str) or not label.strip():
            return None
        pct = item.get("pct")
        if isinstance(pct, bool) or not isinstance(pct, (int, float)):
            return None
        rationale = item.get("rationale")
        validated_allocation.append({
            "role": role, "label": label, "pct": float(pct),
            "rationale": rationale if isinstance(rationale, str) else None,
        })

    pct_sum = sum(row["pct"] for row in validated_allocation)
    if not (99 <= pct_sum <= 101) or any(row["pct"] < 0 for row in validated_allocation):
        # 回覆的百分比沒有大致加總到 100，或帶負數——`budget.split()` 的餘數規則會把落差整個
        # 塞進佔比最大的那一項，畫面卻照樣印模型回的原始百分比，兩邊會對不起來。
        return None
    roles = [row["role"] for row in validated_allocation]
    if len(roles) != len(set(roles)):
        # 同一個 role 出現兩次：`plan.adopt_strategy` 用 role 當 key 塞金額，重複的 role 會
        # 讓其中一列的金額悄悄消失，group 日預算加總就會少於 budget_planned（§0）。
        return None

    def _str_list(value):
        return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []

    alternatives = data.get("alternatives")
    return {
        "allocation": validated_allocation,
        "why": _str_list(data.get("why")),
        "unknowns": _str_list(data.get("unknowns")),
        "alternatives": alternatives if isinstance(alternatives, list) else [],
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


def generate(conn, org_id: str, brand_id: str, campaign_id: str, *, actor: str) -> dict:
    """組context、打模型、套 `budget.scenarios()`／`budget.split()`，整包寫進
    `ads_campaign.budget_basis_json`。失敗（provider 出錯或回覆解不出來）一律 `ValueError`，
    不落地任何東西——草稿留在 `draft`，沒有寫一半的策略。"""
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

    history = ads_repo.budget_history(conn, org_id, brand_id)
    days = _days(campaign["start_date"], campaign["end_date"])
    scenario_result = budget.scenarios(
        conn, org_id, brand_id, product_ids=product_ids, days=days, history=history,
    )
    scenarios_text = _scenarios_section(scenario_result)

    knowledge_item_ids = (
        [f["id"] for f in facts_basis]
        + [p["product_id"] for p in prices_basis]
        + [row["id"] for row in learnings_basis]
    )
    brand = bi_repo.get_brand(conn, brand_id)
    assert brand is not None  # 已經讀得到這個品牌的 campaign，品牌本身一定還在

    department_text = DEPARTMENT_PATH.read_text(encoding="utf-8")
    prompt = (
        department_text
        + "\n\n## 這次投放\n\n"
        + f"目標句子：{campaign['goal_text']}\n"
        + f"objective：{campaign['objective']}\n"
        + f"success_metric：{campaign['success_metric']}\n"
        + f"success_target：{campaign.get('success_target')}\n"
        + f"期間：{campaign['start_date']} ~ {campaign['end_date']}"
        + "\n\n" + facts_text
        + "\n\n" + products_text
        + "\n\n" + learnings_text
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
    strategy_payload = _validate_reply(data) if data is not None else None
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
        "estimated_fields": estimated_fields,
    }
    budget_basis_json = {"strategy": strategy_payload, "scenarios": scenario_result, "basis": basis}
    ads_repo.save_strategy(conn, org_id, brand_id, campaign_id, budget_basis_json=budget_basis_json)
    detail = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)
    assert detail is not None
    return detail


def select_scenario(conn, org_id: str, brand_id: str, campaign_id: str, *,
                     scenario_key: str, custom_total: float | None = None, actor: str) -> dict:
    """使用者選最低／推薦／積極，或手打一個總額——重新用已存的百分比 `split()` 出金額，
    寫 `budget_planned`／`budget_scenario`（§0）。"""
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
        if row is None or row["total"] is None:
            raise ValueError("scenario_unknown")
        total = row["total"]

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
