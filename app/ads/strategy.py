"""app/ads/strategy.py — F03-I05: one recommended strategy, with its reasons and its unknowns,
and the loop's memory in it (§0 "strategy" link). Input: the draft campaign, the brand facts
with their update times, today's effective product prices for this campaign's own products, the
learnings from `learning_ledger`, and the program's budget scenarios. Output: the strategy
payload the plan issue (F03-I06) turns into rows. Trace: the `llm_task` row plus a `basis` naming
exactly which rows fed the prompt (查看策略依據). Private to app/ads (container contract §1):
only `routes.py` imports `generate`/`select_scenario`.

The model never does arithmetic: it returns percentages (`allocation[].pct`) and reasons only;
`budget.split()` (the program) turns a percentage into a NT$ amount. `budget_planned` is a record
of what the user adopted — after 採用策略 the group daily budgets are the truth (F03.md "One source
of truth for money"); F48 Contract M: adopt, and a new total chosen after adoption
(`select_scenario` -> `plan.resplit_groups`), store `total_of(Σ group daily, days)` as it.

F48 (Contracts P and S): the prompt is built from `planner_context` (the sell-way, its 「不能講」,
the offers, the groups, its learnings, last period's goals, the capacity line). The facts under
the strategy -- groups, offers, numbers, capacity, learnings -- are written by the program
(`_facts`, recomputed on every campaign read by `current_facts`); the model writes connecting
prose only, and a reply whose prose carries a digit, `%` or `NT$` is refused.
"""

import hashlib
import json
import math
import re
from copy import deepcopy

from app import workbench
from app.ads import (
    budget,
    calendar_tw,
    customer_groups,
    judgment,
    launch_settings,
    learning,
    learning_rank,
    plan,
    planner_context,
    sell_way,
    targets,
    triage,
)
from app.ads import repository as ads_repo
from app.brand_intelligence import benchmarks
from app.brand_intelligence import repository as bi_repo
from app.core import db, input_rules, rule_cards, vocab
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

STRATEGY_FAILED_MESSAGE = "AI 沒能整理出一個可信的策略，請再試一次。"

# The strategy call's timeout; `busy.py` reads it (F50 Contract J).
TIMEOUT_S = 60.0

#: F50 Contract J (R7 B3): every rule that refuses a strategy reply, code -> reason (printed after
#: `STRATEGY_FAILED_MESSAGE`); `llm_failed` gets the provider's kind (`plan.llm_failed_reason`).
REFUSALS = {
    "llm_failed": plan.REFUSALS["llm_failed"],
    "reply_unreadable": "AI 的回覆不是看得懂的格式",
    "reply_invalid": "AI 的回覆缺了欄位，或格式不對",
    "number_in_prose": "AI 在說明裡自己寫了數字（數字只能由程式算）",
    "role_unavailable": "AI 分了這個品牌現在用不到的角色",
    "pct_invalid": "AI 給的比例加起來不是 100，或有負數",
    "role_repeated": "AI 把同一個角色分了兩次",
    "slots_missing": "AI 沒有列出可採用的受眾、優惠與沿用安排",
}


def _refused(code: str, task_id: str | None) -> "plan.PlannerRefused":
    return plan.PlannerRefused("strategy_failed", code, REFUSALS[code], task_id)


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
    basis = [{"id": f["id"], "label": f["label"], "value": f["value"],
              "updated_at": f["updated_at"]} for f in kept]
    return "【品牌事實】\n" + "\n".join(lines), basis


# F48 Contract P: the 【這個賣法】 block lives in `planner_context` (one implementation).
_products_section = planner_context.products_section


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


def _learnings_section(conn, brand_id: str, product_id: str | None = None) -> tuple[str, list]:
    """【過去的學習】 and its basis from one read (`planner_context.ads_learnings`): one current
    verdict per sell-way, event learnings kept, capped. With `product_id`, that sell-way's rows
    and brand-level ones only (F48 Contract P)."""
    rows = planner_context.ads_learnings(conn, brand_id, product_id)
    return planner_context.learnings_text(rows), planner_context.learnings_basis(rows)


def _scenarios_section(scenario_result: dict) -> str:
    lines = [
        f"- {row['label']}（{row['key']}）：日預算 {row['daily']}／{row['caption']}"
        for row in scenario_result["scenarios"]
    ]
    recommended = scenario_result["recommended"]
    pick_text = "推薦 " + recommended if recommended else "目前無推薦"
    header = (
        f"【程式算好的預算情境（{scenario_result['mode']}，"
        f"{pick_text}）】"
    )
    return header + "\n" + "\n".join(lines) + "\n【預算建議】\n" + json.dumps(
        scenario_result.get("advice"), ensure_ascii=False, default=str,
    )


def _str_list(value) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _pct_sum_valid(allocation: list[dict]) -> bool:
    """同一條「加總落在 99～101、不能是負數」的規則，`_validate_reply` 跟
    `set_allocation` 共用（F04-I13）——理由見下面 `_validate_reply` 那段。"""
    pct_sum = sum(row["pct"] for row in allocation)
    return (99 <= pct_sum <= 101) and all(row["pct"] >= 0 for row in allocation)


# F48 Contract S: the numbers are the program's (`facts`); prose carrying one is refused.
_NUMBER_IN_PROSE = re.compile(r"[0-9０-９%％]|NT\$")


def _has_number(texts, names=()) -> bool:
    """A digit, `%` or `NT$` left in any string once every name the model was given (`names`,
    longest first -- `planner_context.quoted_names`) is removed: quoting 「咖啡因 150mg」 is a
    name, not a number the model wrote."""
    for text in texts:
        if not isinstance(text, str):
            continue
        for name in names:
            text = text.replace(name, "")
        if _NUMBER_IN_PROSE.search(text):
            return True
    return False


def _validate_reply(data, available: frozenset[str], names=()) -> dict | None:
    """`available` 是程式列給模型的【可用角色】（Contract P）：回覆點名一個不在裡面的角色
    （例如沒有再行銷來源的品牌被分了 `retarget`）就整包退回 `None`——`plan.py` 會把每個
    分配到的角色展開成投放組，一個交接時拿不到受眾的再行銷組不能活到那一步。
    F48 Contract S：`rationale`／`why`／`unknowns`／`learning_goals` 去掉程式給過的名稱
    （`names`）後還帶阿拉伯數字、`%` 或 `NT$` 就退回；`alternatives` 有給就必須是字串陣列。
    F50 Contract J：`_check_reply` is the same judgement naming the rule."""
    return _check_reply(data, available, names)[0]


def _check_reply(data, available: frozenset[str], names=()) -> tuple[dict | None, str | None]:
    """`_validate_reply`'s rules, returning `(payload, None)` or `(None, code)` with a code of
    `REFUSALS` (F50 Contract J)."""
    invalid = (None, "reply_invalid")
    if not isinstance(data, dict):
        return invalid
    prose = [data.get(key) for key in ("why", "unknowns", "learning_goals")]
    if _has_number([t for value in prose if isinstance(value, list) for t in value], names):
        return None, "number_in_prose"
    slots = data.get("slots")
    if isinstance(slots, list) and _has_number([
        s.get(k) for s in slots if isinstance(s, dict) for k in ("rationale", "test_intent")
    ], names):
        return None, "number_in_prose"
    alternatives = data.get("alternatives", [])
    if not isinstance(alternatives, list) or not all(isinstance(a, str) for a in alternatives):
        return invalid
    allocation = data.get("allocation")
    if not isinstance(allocation, list) or not allocation:
        return invalid
    validated_allocation = []
    for item in allocation:
        if not isinstance(item, dict):
            return invalid
        role = item.get("role")
        if role not in available:
            return None, "role_unavailable"
        pct = item.get("pct")
        if isinstance(pct, bool) or not isinstance(pct, (int, float)) or not math.isfinite(pct):
            return invalid
        rationale = item.get("rationale")
        if _has_number([rationale], names):
            return None, "number_in_prose"
        # `label` 由程式對照 `_ROLE_LABELS` 填，不再要求模型回——那是花錢買一個我們已經知道
        # 的答案（F04-I03）。模型舊行為回了 `label` 也不理會，一律以程式的對照表為準。
        validated_allocation.append({
            "role": role, "label": _ROLE_LABELS[role], "pct": float(pct),
            "rationale": rationale if isinstance(rationale, str) else None,
        })

    if not _pct_sum_valid(validated_allocation):
        # 回覆的百分比沒有大致加總到 100，或帶負數——`budget.split()` 的餘數規則會把落差整個
        # 塞進佔比最大的那一項，畫面卻照樣印模型回的原始百分比，兩邊會對不起來。
        return None, "pct_invalid"
    roles = [row["role"] for row in validated_allocation]
    if len(roles) != len(set(roles)):
        # 同一個 role 出現兩次：`plan.adopt_strategy` 用 role 當 key 塞金額，重複的 role 會
        # 讓其中一列的金額悄悄消失，group 日預算加總就會少於 budget_planned（§0）。
        return None, "role_repeated"

    return {
        "slots": data.get("slots"),
        "allocation": validated_allocation,
        "why": _str_list(data.get("why")),
        "unknowns": _str_list(data.get("unknowns")),
        "alternatives": alternatives,
        "learning_goals": _str_list(data.get("learning_goals"))[:3],
    }, None


def decision_context(ctx: dict, campaign: dict) -> dict:
    """Stable IDs and decision facts; never hash render labels or read timestamps."""
    carried = ctx.get("carried_candidates") or []
    return {
        "campaign_id": campaign["id"],
        "product_ids": ctx.get("product_ids") or [],
        "dates": [str(campaign.get(k)) for k in ("start_date", "end_date")],
        "objective": campaign.get("objective"),
        "goal": campaign.get("goal_text"),
        "budget_planned": (
            float(campaign["budget_planned"])
            if campaign.get("budget_planned") is not None
            else None
        ),
        "constraints": campaign.get("constraints_json") or {},
        "budget_advice": ctx.get("budget_advice"),
        "continuation": ctx.get("continuation"),
        "customers": [
            {
                k: g.get(k)
                for k in (
                    "id",
                    "product_id",
                    "position",
                    "who",
                    "pain_keys",
                    "quote",
                    "when_used",
                    "source",
                )
            }
            for g in ctx["customer_groups"]
        ],
        "offers": [{"key": o["key"], "sentence": o["sentence"]} for o in ctx["offers"]],
        "menu": sorted((r["dimension"], r["key"]) for r in ctx["menu"]),
        "forbidden": ctx["forbidden"],
        "capacity": ctx.get("capacity"),
        "learnings": sorted([
            {"id": r["id"], "text": r["learning_text"],
             "meaning_revision": (r.get("evidence") or {}).get("meaning_revision")}
            for r in ctx["learnings"]["ads"]
        ], key=lambda row: row["id"]),
        "learning_revision": (ctx["learnings"].get("evidence_context") or {}).get("revision"),
        "ranked_ids": ctx["ranked_ids"],
        "calendar": ctx.get("calendar_evidence") or [],
        "brand_facts": [
            {"id": r["id"], "value": r.get("value")} for r in ctx.get("brand_facts") or []
        ],
        "prices": [
            {k: r.get(k) for k in ("product_id", "price", "stale", "assumptions")}
            for r in ctx.get("prices") or []
        ],
        "product_facts": [
            {"id": k["id"], "facts": k["facts"]}
            for b in ctx.get("product_blocks") or []
            for k in b["knowledge"]
        ],
        "results": [
            {
                **{
                    k: r.get(k)
                    for k in ("ad_id", "sales", "spend", "cost_per_sale", "verdict", "flags")
                },
                "coordinates": [(v["dimension"], v["key"]) for v in r.get("coordinates") or []],
                "meaning_revision": (r.get("evidence") or {}).get("meaning_revision"),
            }
            for c in ctx["learnings"]["ranked"]["campaigns"]
            for r in c["rows"]
        ],
        "previous_goals": (ctx.get("previous") or {}).get("learning_goals") or [],
        "evidence_refs": (
            [{"kind": "learning", "id": r["id"]} for r in ctx["learnings"]["ads"]]
            + [{"kind": "learning", "id": i} for i in ctx["ranked_ids"]]
            + [
                {"kind": "result", "id": r["ad_id"]}
                for c in ctx["learnings"]["ranked"]["campaigns"]
                for r in c["rows"]
            ]
            + [{"kind": "brand_fact", "id": r["id"]} for r in ctx.get("brand_facts") or []]
            + [{"kind": "calendar", "id": r["id"]} for r in ctx.get("calendar_evidence") or []]
        ),
        "carried": [
            {
                "id": i["ad"]["id"],
                "role": i["role"],
                "customer_group_id": i["ad"].get("customer_group_id"),
                "coordinates": {d: i["ad"].get(f"{d}_key") for d in plan._COORDINATE_DIMENSIONS},
                "creative": i["creative"],
                "eligibility": i.get("eligibility"),
            }
            for i in carried
        ],
    }


_BINDING_PROMPT_CAP = 24


def decision_prompt_context(ctx: dict, campaign: dict) -> dict:
    """Only assignment choices reach the model; full semantic snapshots remain program-owned."""
    lists = {
        "customers": [{"id": g["id"]} for g in ctx["customer_groups"]],
        "offers": [{"key": o["key"]} for o in ctx["offers"]],
        "menu": [{k: r[k] for k in ("dimension", "key", "label")} for r in ctx["menu"]],
        "carried": [{"id": i["ad"]["id"], "role": i["role"],
                     "customer_group_id": i["ad"].get("customer_group_id"),
                     "coordinates": {d: i["ad"].get(f"{d}_key")
                                     for d in plan._COORDINATE_DIMENSIONS},
                     "creative": i["creative"] is not None,
                     "eligibility": {"state": (i.get("eligibility") or {}).get("state")}}
                    for i in ctx.get("carried_candidates") or []],
        "evidence_refs": decision_context(ctx, campaign)["evidence_refs"],
    }
    return {**{key: rows[:_BINDING_PROMPT_CAP] for key, rows in lists.items()},
            "capacity": ctx.get("capacity"),
            "budget_advice": ctx.get("budget_advice"),
            "omitted": {key: max(0, len(rows) - _BINDING_PROMPT_CAP)
                        for key, rows in lists.items()}}


def executable_decision(ctx: dict, campaign: dict, payload: dict) -> dict:
    """Validate a proposed commitment before it is served and again before persistence."""
    slots = payload.get("slots") or (payload.get("decision") or {}).get("slots") or []
    reasons = []
    def refuse(code, message, ids=()):
        reasons.append({"code": code, "message": message, "slot_ids": list(ids)})
    allocation = payload.get("allocation") or []
    roles = {r["role"] for r in allocation}
    group_ids = {g["id"] for g in ctx["customer_groups"]}
    offer_keys = {o["key"] for o in ctx["offers"]} | {"none"}
    carried = {i["ad"]["id"]: i for i in ctx.get("carried_candidates") or []}
    evidence = {("learning", r["id"]) for r in ctx["learnings"]["ads"]}
    evidence |= {("learning", i) for i in ctx["ranked_ids"]}
    evidence |= {("result", r["ad_id"]) for c in ctx["learnings"]["ranked"]["campaigns"]
                 for r in c["rows"]}
    evidence |= {("calendar", r["id"]) for r in ctx.get("calendar_evidence") or []}
    evidence |= {("brand_fact", r["id"]) for r in ctx.get("brand_facts") or []}
    seen, carry_seen, per_role, groups_per_role = set(), set(), {}, {}
    names = planner_context.quoted_names(ctx)
    if not isinstance(slots, list) or not slots:
        refuse("slots_missing", "請重新產生策略，確認每則廣告的安排。")
        slots = []
    for slot in slots:
        if (not isinstance(slot, dict) or any(not isinstance(slot.get(k), str)
                for k in ("id", "role", "offer_key"))
                or any(k not in slot or (slot.get(k) is not None
                                        and not isinstance(slot.get(k), str))
                       for k in ("customer_group_id", "carry_from_ad_id", "test_intent"))):
            refuse("slot_invalid", "廣告安排格式無效。")
            continue
        sid, role = slot.get("id"), slot.get("role")
        ids = [sid] if isinstance(sid, str) else []
        if not isinstance(sid, str) or not sid.strip() or len(sid) > 100 or sid in seen:
            refuse("slot_id_invalid", "每則廣告需要不同且有效的安排代號。", ids)
        seen.add(sid)
        if role not in roles:
            refuse("slot_role_invalid", "廣告角色不在這份分配裡。", ids)
        per_role[role] = per_role.get(role, 0) + 1
        gid = slot.get("customer_group_id")
        if (gid not in group_ids if group_ids else gid is not None):
            refuse("customer_group_unavailable", "所選顧客群已刪除或不屬於這次企劃，請重選。", ids)
        groups_per_role.setdefault(role, set()).add(gid)
        if slot.get("offer_key") not in offer_keys:
            refuse("offer_unavailable", "所選優惠這期不能使用，請重選。", ids)
        carry_id, intent = slot.get("carry_from_ad_id"), slot.get("test_intent")
        rationale = slot.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            refuse(
                "slot_rationale_missing",
                "每則廣告需要說明安排理由與依據限制，請重新產生策略。",
                ids,
            )
        if _has_number([rationale, intent], names):
            refuse("number_in_prose", REFUSALS["number_in_prose"], ids)
        has_intent = isinstance(intent, str) and bool(intent.strip())
        if bool(carry_id) == has_intent:
            refuse("slot_intent_invalid", "請選擇沿用原廣告，或明確提出新測試。", ids)
        if carry_id:
            item = carried.get(carry_id)
            if (carry_id in carry_seen or item is None or item["creative"] is None
                    or (item.get("eligibility") or {}).get("state") == "blocked"):
                refuse("carry_unavailable", "這則廣告的原圖文無法沿用，請修訂安排。", ids)
            elif (item["ad"].get("customer_group_id") != gid
                  or item["ad"].get("offer_key") != slot.get("offer_key")):
                refuse("carry_binding_changed", "沿用原圖文必須保留它的顧客群與優惠。", ids)
            carry_seen.add(carry_id)
        refs = slot.get("evidence_refs")
        if not isinstance(refs, list) or (evidence and not refs) or any(
                not isinstance(r, dict) or not isinstance(r.get("kind"), str)
                or not isinstance(r.get("id"), str)
                or (r["kind"], r["id"]) not in evidence for r in refs):
            refuse("evidence_unavailable", "安排引用的依據不在這次已讀資料裡。", ids)
    if set(per_role) != roles or any(n > plan._MAX_ADS_PER_GROUP for n in per_role.values()):
        refuse("role_capacity", "每個已分配角色需要廣告，且不能超過同組件數上限。")
    if any(len(ids) > 1 for ids in groups_per_role.values()):
        refuse("role_audience_conflict", "同一投放組不能承諾不同顧客群，請調整角色或安排。")
    capacity = ctx.get("capacity")
    if capacity is None:
        refuse("capacity_unknown", "先設定有效的每筆成本上限與預算，才能確認安排是否放得下。")
    elif len(slots) > capacity["ceiling"]:
        refuse("capacity_exceeded", "預算放不下這些廣告，請調整預算或安排。", seen)
    if capacity and allocation:
        amounts = plan._role_amounts(allocation, capacity["daily"])
        if any(amount <= 0 for amount in amounts.values()):
            refuse("allocation_too_small", "部分角色分不到正數日預算，請調整比例或預算。")
    stable = {"inputs": decision_context(ctx, campaign), "slots": slots,
              "allocation": [{"role": r["role"], "pct": r["pct"]} for r in allocation]}
    revision = hashlib.sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False,
                                       default=str).encode()).hexdigest()
    return {"schema_version": 1, "revision": revision, "state": "proposed", "slots": slots,
            "budget_advice": ctx.get("budget_advice"),
            "feasibility": {"state": "blocked" if reasons else "ready", "reasons": reasons}}


def _prepared_decision_context(conn, org, brand, campaign):
    """Share the same facts and recommended-budget fallback for reads and edits."""
    current = budget.advice(conn, org, brand, campaign)
    campaign = {**campaign, "budget_advice": {key: value for key, value in current.items()
                                             if key != "retain"}}
    campaign = budget.reconcile_campaign(
        campaign, cap=targets.resolve(conn, org, brand, campaign)["value"], current_advice=current,
    )
    ctx = planner_context.planner_context(conn, org, brand, sell_way.of_campaign(campaign),
                                          campaign=campaign)
    if ctx["capacity"] is None and campaign.get("budget_planned") is None:
        scenarios = (campaign.get("budget_basis_json") or {}).get("scenarios") or {}
        row = next((r for r in scenarios.get("scenarios", [])
                    if r["key"] == scenarios.get("recommended")), {})
        ctx["capacity"] = planner_context.capacity_of(row.get("daily"), ctx["cap"])
    _, ctx["brand_facts"] = _brand_facts_section(conn, brand)
    return ctx


def refresh_decision(conn, org, brand, campaign, payload):
    """Refresh bindings after budget/allocation edits; labels never determine a binding."""
    if not payload.get("decision"):
        return
    ctx = _prepared_decision_context(conn, org, brand, campaign)
    previous = payload["decision"]
    payload["decision"] = executable_decision(ctx, campaign, payload)
    if previous.get("state") in ("adopted", "modified"):
        payload["decision"]["state"] = "modified"
        payload["decision"]["receipt"] = previous.get("receipt")
        payload["rationale_state"] = "stale"


def _slot_display(ctx, slot):
    """Read-only labels from the same context that checked this served revision."""
    customers = {g["id"]: g["who"] for g in ctx["customer_groups"]}
    offers = {o["key"]: f"{o['label']}：{o['sentence']}" for o in ctx["offers"]}
    carried = {i["ad"]["id"]: i["ad"]["name"] for i in ctx["carried_candidates"]}
    evidence = {("learning", r["id"]): r["learning_text"] for r in ctx["learnings"]["ads"]}
    for identifier in ctx["ranked_ids"]:
        evidence.setdefault(("learning", identifier), "本期可用的投放學習排名")
    for campaign in ctx["learnings"]["ranked"]["campaigns"]:
        for row in campaign["rows"]:
            labels = [row.get("verdict_label"), *(row.get("flags") or [])]
            limits = "・".join(label for label in labels if label)
            label = f"{campaign['campaign_name']}／{row['ad_name']}"
            if limits:
                label += f"（{limits}）"
            evidence[("result", row["ad_id"])] = label
            if row.get("learning_id"):
                evidence[("learning", row["learning_id"])] = label
    evidence.update({("brand_fact", r["id"]): f"{r['label']}：{r['value']}"
                     for r in ctx.get("brand_facts") or []})
    evidence.update({("calendar", r["id"]): r["name"] for r in ctx.get("calendar_evidence") or []})
    customer_id = slot.get("customer_group_id")
    offer_key = slot.get("offer_key")
    carry_id = slot.get("carry_from_ad_id")
    raw_refs = slot.get("evidence_refs")
    refs = raw_refs if isinstance(raw_refs, list) else []
    displayed_refs = [r for r in refs[:3] if isinstance(r, dict)]
    return {
        "customer_group_label": customers.get(
            customer_id if isinstance(customer_id, str) else "", "已刪除或不在本期的顧客群"
        ) if customer_id is not None else "尚未指定顧客群",
        "offer_label": "不使用優惠" if slot.get("offer_key") == "none" else offers.get(
            offer_key if isinstance(offer_key, str) else "", "已失效或不在本期的優惠"
        ),
        "carried_ad_label": carried.get(
            carry_id if isinstance(carry_id, str) else "", "原廣告已不在可保留資料中"
        ) if carry_id is not None else None,
        "evidence": [dict(r, label=evidence.get(
            (str(r.get("kind")), str(r.get("id"))), "依據已不在本期資料中"
        )) for r in displayed_refs],
        "evidence_omitted": len(refs) - len(displayed_refs),
    }


def served_basis(campaign: dict, basis: dict) -> dict:
    """Add conservative fields to an old display snapshot without reading today's ledger."""
    result = deepcopy(basis)
    product = (basis.get("planner_context") or {}).get("product_id")
    rows = [{"id": row["id"], "org_id": campaign["org_id"], "brand_id": campaign["brand_id"],
             "product_id": product, "learning_text": row.get("text") or "",
             "applicability_scope": "", "needs_revalidation": row.get("needs_revalidation")}
            for row in result.get("learnings") or [] if not row.get("evidence")]
    for closed in (result.get("ranked_learnings") or {}).get("campaigns") or []:
        for row in closed.get("rows") or []:
            if not row.get("evidence"):
                rows.append({"id": row["learning_id"], "org_id": campaign["org_id"],
                             "brand_id": campaign["brand_id"],
                             "product_id": closed.get("sell_way_id"),
                             "learning_text": row.get("ad_name") or "", "applicability_scope": ""})
    current = {"org_id": campaign["org_id"], "brand_id": campaign["brand_id"],
               "product_id": product, "org_day": None, "conditions": {}, "mode": "real"}
    projected = workbench.qualify_learning_evidence(
        rows, current, min_result_events=triage.MIN_RESULT_EVENTS, max_age_days=180,
    )
    by_id = {item["id"]: item for item in projected["items"]}
    for row in result.get("learnings") or []:
        if not row.get("evidence"):
            row["evidence"] = by_id[row["id"]]
    ranked = result.get("ranked_learnings") or {}
    for closed in ranked.get("campaigns") or []:
        for row in closed.get("rows") or []:
            if not row.get("evidence"):
                row["evidence"] = by_id[row["learning_id"]]
    context = {"schema_version": 1, "revision": projected["revision"], "scope_product_id": product,
               "scope_label": None, "eligible_count": 0, "items": projected["items"][:30],
               "omitted": max(len(projected["items"]) - 30, 0)}
    result.setdefault("evidence_context", context)
    if "ranked_learnings" in result:
        ranked.setdefault("evidence_context", result["evidence_context"])
    return result


def served_decision(conn, org, brand, campaign, groups):
    """Separate candidate facts, proposed commitments and actual saved targeting."""
    payload = (campaign.get("budget_basis_json") or {}).get("strategy") or {}
    saved = payload.get("decision")
    decision = deepcopy(saved) if saved else None
    ctx = _prepared_decision_context(conn, org, brand, campaign)
    if saved and saved.get("state") == "proposed":
        assert decision is not None
        current = executable_decision(ctx, campaign, payload)
        decision["feasibility"] = current["feasibility"]
        if current["revision"] != saved["revision"]:
            decision["feasibility"] = {"state": "blocked", "reasons": [
                *current["feasibility"]["reasons"], {"code": "strategy_changed",
                    "message": "安排的依據已更新，請重新產生策略並確認。", "slot_ids": []}]}
    decision = decision or {
        "schema_version": 1,
        "revision": "",
        "state": "legacy_unbound",
        "slots": [],
        "feasibility": {
            "state": "blocked",
            "reasons": [
                {
                    "code": "strategy_confirmation_required",
                    "message": "舊策略尚未綁定安排，請重新產生並確認。",
                    "slot_ids": [],
                }
            ],
        },
    }
    names = {g["id"]: g["who"] for g in ctx["customer_groups"]}
    proposed = [s for s in decision["slots"] if isinstance(s, dict)]
    for slot in proposed:
        slot["display"] = _slot_display(ctx, slot)
    proposed_ids = {s["customer_group_id"] for s in proposed
                    if isinstance(s.get("customer_group_id"), str)}
    ads = [a for g in groups for a in g.get("ads") or []]
    actual_ids = set(a.get("customer_group_id") for a in ads) - {None}
    decision["facts"] = {
        "continuation": ctx.get("continuation"),
        "available": {"customer_groups": len(names), "customer_group_names": list(names.values())},
        "proposed": {
            "customer_groups": len(proposed_ids),
            "delivery_groups": len(
                set(s["role"] for s in proposed if isinstance(s.get("role"), str))
            ),
            "ads": len(decision["slots"]),
            "customer_group_names": [names.get(i, "已刪除的顧客群") for i in sorted(proposed_ids)],
            "unknown_audience_ads": sum(s.get("customer_group_id") is None for s in proposed),
        },
        "actual": {
            "customer_groups": len(actual_ids),
            "delivery_groups": len(groups),
            "ads": len(ads),
            "customer_group_names": [names.get(i, "已刪除的顧客群") for i in sorted(actual_ids)],
            "unknown_audience_ads": sum(a.get("customer_group_id") is None for a in ads),
        },
    }
    return decision


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
    # F51 (planning #15): no closed campaign yet -> 沒有; closed but the purchases were never
    # tracked -> 未追蹤 (never 沒有, never 0); a counted zero -> 0 筆.
    if not reads["closed_campaigns"]:
        loop_text = "沒有"
    elif loop_purchases is None:
        loop_text = "未追蹤"
    else:
        loop_text = f"{_count_text(loop_purchases)} 筆"

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
    return "未設定" if cap is None else f"{budget.whole(cap):,}"


def generate(conn, org_id: str, brand_id: str, campaign_id: str, *, actor: str) -> dict:
    """組context、打模型、套 `budget.scenarios()`／`budget.split()`，整包寫進
    `ads_campaign.budget_basis_json`。失敗（provider 出錯或回覆解不出來）一律 `ValueError`，
    不落地任何東西——草稿留在 `draft`，沒有寫一半的策略。"""
    ads_repo.require_internal_campaign(conn, org_id, brand_id, campaign_id)
    campaign = ads_repo.get_campaign(conn, org_id, brand_id, campaign_id)
    if campaign is None:
        raise ValueError("campaign_unknown")
    if campaign["status"] != "draft":
        # 重算今天只會拿新推薦的情境總額去 split() ——已採用的 `budget_planned` 會悄悄跟畫面上
        # 存的分配金額對不上，F03-I06 已經照 `budget_planned` 建過投放組(§0)。
        raise ValueError("strategy_already_adopted")

    product_ids = list((campaign.get("context_json") or {}).get("product_ids") or [])
    facts_text, facts_basis = _brand_facts_section(conn, brand_id)
    # F48 Contract P：這個賣法、不能講、顧客群、優惠、學習、排名、上一期想學的、撐得起幾則——
    # 一份 planner_context，策略與投放結構讀同一份。
    ctx = planner_context.planner_context(
        conn, org_id, brand_id, sell_way.of_campaign(campaign), campaign=campaign,
    )
    ctx["brand_facts"] = facts_basis

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
    current_advice = budget.advice(conn, org_id, brand_id, campaign)
    scenario_result = budget.apply_advice(scenario_result, current_advice)
    ctx["budget_advice"] = scenario_result["advice"]
    scenarios_text = _scenarios_section(scenario_result)
    recommended_row = next((row for row in scenario_result["scenarios"]
                            if row["key"] == scenario_result["recommended"]), None)
    if ctx["capacity"] is None and campaign.get("budget_planned") is None:
        # No adopted budget yet: the capacity line reads the recommended scenario's day.
        ctx["capacity"] = planner_context.capacity_of(
            recommended_row.get("daily") if recommended_row else None, cap,
        )

    reads = ads_repo.starting_point_reads(conn, org_id, brand_id)
    starting_point_text = _starting_point_section(brand, history, reads, campaign)
    available_roles = _available_roles(brand, reads)
    roles_text = _available_roles_section(available_roles)
    # F33-I02（Contract Q）：靜態台灣行事曆只列跟期間重疊的列；表外年份會附「沒有資料」的註記。
    calendar_text = calendar_tw.prompt_section(campaign["start_date"], campaign["end_date"])

    knowledge_item_ids = [f["id"] for f in facts_basis] + ctx["knowledge_item_ids"]
    sections = "".join(
        "\n\n" + planner_context.section_text(ctx, which)
        for which in ("product", "forbidden", "customers", "offers", "learnings", "ranked",
                      "previous", "capacity")
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
        + sections
        + "\n\n" + scenarios_text
        + "\n\n【可綁定安排】\n" + json.dumps(decision_prompt_context(ctx, campaign),
                                                ensure_ascii=False, default=str)
    )

    context = gateway.TaskContext(
        context_scope={"brand_id": brand_id, "campaign_id": campaign_id},
        knowledge_item_ids=knowledge_item_ids, brand_version=brand["knowledge_version"],
    )
    names = planner_context.quoted_names(ctx)

    def ask(refused: list[plan.PlannerRefused]) -> tuple[dict, dict]:
        # F50 (user ruling 2026-10-04): a retry carries the refusal at the end of the prompt.
        text = prompt + ("\n\n" + plan.refusal_section(refused) if refused else "")
        task_row = gateway.run_task(
            conn, PROVIDER, brand_id=brand_id, task_type="ads_strategy",
            prompt_template_id="ads_strategy", prompt_template_version="v1",
            system=None, messages=[{"role": "user", "content": text}], context=context,
            options=gateway.TaskOptions(max_tokens=2000, timeout_s=TIMEOUT_S, max_retries=0),
        )
        if task_row["status"] != "succeeded":
            raise plan.PlannerRefused("strategy_failed", "llm_failed",
                                      plan.llm_failed_reason(task_row), task_row["id"])
        data = gateway.parse_json_reply(task_row.get("rendered_output") or "")
        if data is None:
            raise _refused("reply_unreadable", task_row["id"])
        payload, code = _check_reply(data, frozenset(available_roles), names)
        if payload is None:
            raise _refused(code or "reply_invalid", task_row["id"])
        if not isinstance(payload.get("slots"), list) or not payload["slots"]:
            raise _refused("slots_missing", task_row["id"])
        return task_row, payload

    task_row, strategy_payload = plan.ask_with_one_retry(conn, ask, campaign_id=campaign_id)

    strategy_payload["allocation"] = _apply_amounts(
        strategy_payload["allocation"], campaign["budget_planned"]
        if campaign.get("budget_planned") is not None
        else recommended_row.get("total") if recommended_row else None,
    )
    strategy_payload["facts"] = _facts(ctx, strategy_payload["allocation"], recommended_row)
    strategy_payload["decision"] = executable_decision(ctx, campaign, strategy_payload)
    strategy_payload.pop("slots", None)

    estimated_fields = ["daily", "total"] if scenario_result["mode"] == "cold_start" else []
    basis = {
        "evidence_context": ctx["learnings"]["evidence_context"],
        "knowledge_item_ids": knowledge_item_ids, "llm_task_id": task_row["id"],
        "input_context_hash": task_row["input_context_hash"],
        "brand_facts": facts_basis, "prices": ctx["prices"],
        "learnings": planner_context.learnings_basis(ctx["learnings"]["ads"]),
        "coordinate_scoreboard": ctx["ranked_ids"], "ranked_learnings": ctx["learnings"]["ranked"],
        "estimated_fields": estimated_fields,
        "planner_context": {
            "product_id": (ctx["product"] or {}).get("id"),
            "forbidden_count": len(ctx["forbidden"]),
            "offers": [offer["key"] for offer in ctx["offers"]],
            "previous_campaign_id": (ctx["previous"] or {}).get("campaign_id"),
            "continuation": ctx.get("continuation"),
        },
    }
    assumption_note = _assumption_note(ctx["prices"])
    if assumption_note is not None:
        basis["assumption_note"] = assumption_note
    budget_basis_json = {"strategy": strategy_payload, "scenarios": scenario_result, "basis": basis}
    ads_repo.save_strategy(conn, org_id, brand_id, campaign_id, budget_basis_json=budget_basis_json)
    detail = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)
    assert detail is not None
    return detail


# -- F48 Contract S: the facts under the strategy, written by the program -------------------------


def _offer_label(ctx: dict, key: str) -> str:
    listed = next((offer["label"] for offer in ctx["offers"] if offer["key"] == key), None)
    return str(listed or vocab.offer_label(key))


def _groups_fact(whos: list[str], empty: str) -> str:
    return f"這期打 {len(whos)} 群：{'、'.join(whos)}" if whos else empty


def _numbers_fact(ctx: dict) -> str:
    """The cap; the newest closed period of this sell-way, its best 每筆 with the ad's name and
    sales; how many periods it closed. Money through `learning_rank.whole`."""
    cap = ctx["cap"]
    parts = ["沒有設上限" if cap is None else f"上限每筆 {learning_rank.whole(cap)}"]
    previous = ctx["previous"]
    if previous is None:
        parts.append("這個賣法還沒有結案過")
        return "；".join(parts)
    best = previous["best"]
    if best is None:
        parts.append(f"上一期「{previous['name']}」沒有一則賣出")
    else:
        parts.append(
            f"上一期「{previous['name']}」最好的是「{best['ad_name']}」"
            f"每筆 {learning_rank.whole(best['cost_per_sale'])}（賣 {best['sales']} 筆）"
        )
    parts.append(f"已結案 {previous['closed_count']} 期")
    return "；".join(parts)


def _facts(ctx: dict, allocation: list[dict], scenario_row: dict | None, *,
           adopted: dict | None = None) -> list[dict]:
    """Contract S: `[{kind, text}]` for groups, offers, numbers, capacity and learnings, every
    number from the program's rows. `adopted` = `{groups: [who], offers: {key: ads}}` read off the
    campaign's ads once the plan is adopted (`current_facts`); before that, the listed groups and
    the available offers with their sentences."""
    if adopted is not None:
        groups = _groups_fact(adopted["groups"], "這期的廣告沒有綁顧客群")
        offers = "、".join(
            f"用了〈{_offer_label(ctx, key)}〉 {count} 則"
            for key, count in adopted["offers"].items()
        ) or "這期的廣告沒有用優惠"
    else:
        groups = ("可選顧客群：" + "、".join(g["who"] for g in ctx["customer_groups"])
                  if ctx["customer_groups"] else "沒有可選顧客群，受眾未知")
        offers = "可用的優惠：" + "；".join(
            f"〈{offer['label']}〉{offer['sentence']}" for offer in ctx["offers"]
        ) if ctx["offers"] else "沒有可用優惠"
    capacity = ctx["capacity"]
    if capacity is None and scenario_row is not None:
        capacity = planner_context.capacity_of(scenario_row.get("daily"), ctx["cap"])
    if capacity is not None:
        capacity = {**capacity}
    counts = [c["counts"] for c in ctx["learnings"]["ranked"]["campaigns"]]
    learnings = (
        f"讀了上幾期的排名：留下 {sum(c['keep'] for c in counts)} 則、"
        f"換掉 {sum(c['replace'] for c in counts)} 則；"
        f"過去的學習 {len(ctx['learnings']['ads'])} 條"
    )
    return [
        {"kind": "groups", "text": groups},
        {"kind": "offers", "text": offers},
        {"kind": "numbers", "text": _numbers_fact(ctx)},
        {"kind": "capacity", "text": planner_context.capacity_line(capacity)},
        {"kind": "learnings", "text": learnings},
    ]


def current_facts(conn, org_id: str, brand_id: str, campaign: dict, *,
                  groups: list[dict] | None = None) -> list[dict] | None:
    """The facts as they read now (the campaign read serves these, not the stored copy): once the
    campaign has ads, the groups line names the ads' bound customer groups and the offers line
    counts ads per offer. `groups` = the campaign's delivery groups with their `ads` (the read
    already holds them). `None` for a campaign without a strategy or an imported one."""
    budget_basis_json = campaign.get("budget_basis_json") or {}
    strategy_payload = budget_basis_json.get("strategy")
    if not strategy_payload or campaign.get("origin") == "imported":
        return None
    ctx = planner_context.planner_context(
        conn, org_id, brand_id, sell_way.of_campaign(campaign), campaign=campaign,
    )
    scenarios = budget_basis_json.get("scenarios") or {}
    scenario_row = next(
        (row for row in scenarios.get("scenarios") or []
         if row.get("key") == scenarios.get("recommended")), None,
    )
    ads = [ad for group in groups or [] for ad in group.get("ads") or []]
    adopted = None
    if ads:
        by_id = customer_groups.groups_by_id(conn, brand_id, campaign)
        bound = dict.fromkeys(ad["customer_group_id"] for ad in ads if ad.get("customer_group_id"))
        offers: dict[str, int] = {}
        for ad in ads:
            key = ad.get("offer_key")
            if key and key != "none":
                offers[key] = offers.get(key, 0) + 1
        adopted = {
            "groups": [(by_id.get(group_id) or {}).get("who") or "已刪除的顧客群"
                       for group_id in bound],
            "offers": offers,
        }
    return _facts(ctx, strategy_payload.get("allocation") or [], scenario_row, adopted=adopted)


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
    記下誰、何時、總額、上限、超出多少。上限內或沒有上限時照舊（不留確認紀錄）。

    F48 Contract M／decision 8: a draft stores the chosen total unchanged (the read serves
    `budget_preview`). After adoption the ad sets are re-split (`plan.resplit_groups`, unbound
    `ready` only, else `campaign_bound`) and the returned detail carries `resplit`."""
    ads_repo.require_internal_campaign(conn, org_id, brand_id, campaign_id)
    campaign = ads_repo.get_campaign(conn, org_id, brand_id, campaign_id)
    if campaign is None:
        raise ValueError("campaign_unknown")
    budget_basis_json = campaign.get("budget_basis_json") or {}
    scenario_result = budget_basis_json.get("scenarios")
    strategy_payload = budget_basis_json.get("strategy")
    if not scenario_result or not strategy_payload:
        raise ValueError("strategy_not_generated")

    row = next((r for r in scenario_result["scenarios"] if r["key"] == scenario_key), None)
    if scenario_key == "retain" and (row is None or row.get("currency") != "TWD"):
        raise ValueError("scenario_unknown")
    if row and (row.get("currency") not in {None, "TWD"}
                or row.get("reason") in {
                    "planning_currency_unverified", "planning_currency_mismatch",
                }):
        raise ValueError("scenario_amount_unknown")
    if custom_total is not None:
        if isinstance(custom_total, bool) or custom_total <= 0:
            raise ValueError("custom_total_invalid")
        total = custom_total
    else:
        if row is None:
            raise ValueError("scenario_unknown")
        if row["total"] is None:
            raise ValueError("scenario_amount_unknown")
        total = row["total"]

    # F48 Contract M: a total below the day count buys a daily of 0 -- nothing to split.
    if budget.daily_of(total, budget.period_days(campaign)) == 0:
        raise ValueError("total_below_one_per_day")
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
            "by": actor, "at": db.now_utc().isoformat(), "total": total,
            "cap": budget_cap, "over": over,
        }

    # F48 decision 8: after adoption a new total re-splits the (still unbound) ad sets and the
    # stored total is adopt's rounding of it; a draft stores the chosen total unchanged.
    resplit = None
    budget_planned = total
    if campaign["status"] != "draft":
        resplit, budget_planned = plan.resplit_groups(conn, org_id, brand_id, campaign, total)
    strategy_payload = dict(strategy_payload)
    strategy_payload["allocation"] = _apply_amounts(strategy_payload["allocation"], total)
    refresh_decision(conn, org_id, brand_id,
                     {**campaign, "budget_planned": budget_planned}, strategy_payload)
    budget_basis_json = {**budget_basis_json, "strategy": strategy_payload}
    ads_repo.select_scenario(
        conn, org_id, brand_id, campaign_id, scenario_key=scenario_key,
        budget_planned=budget_planned, budget_basis_json=budget_basis_json,
    )
    detail = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)
    assert detail is not None
    return {**detail, "resplit": resplit}


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
        if isinstance(pct, bool) or not isinstance(pct, (int, float)) or not math.isfinite(pct):
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
    refresh_decision(conn, org_id, brand_id, campaign, strategy_payload)
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
    writes the platform or changes the selected plan budget/scenario. The constraints refresh
    the stored strategy revision; launch provenance detects that accepted strategy changed.
    The next scenarios read (`budget.current_scenarios`) reflects the updated cap."""
    if budget_cap is not None:
        # F50 Contract I: a whole number (never a bool) > 0 through `input_rules.count`.
        if isinstance(budget_cap, bool) or not isinstance(budget_cap, int):
            raise ValueError("budget_cap_invalid")
        try:
            input_rules.count(budget_cap, "預算上限", minimum=1)
        except input_rules.InputRuleError:
            raise ValueError("budget_cap_invalid") from None
    ads_repo.set_budget_cap(conn, org_id, brand_id, campaign_id, budget_cap=budget_cap)
    detail = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)
    assert detail is not None
    return detail
