"""app/ads/customer_groups.py — F43-I02: the 【這個賣法的顧客】 prompt section the strategy and
delivery-plan builders share. The program picks and caps the groups (the campaign's
`context_json.customer_group_ids`, else every group of the sell-way's knowledge products); the
model only uses what is listed. Private to app/ads: `strategy.py` and `plan.py` import it;
F46: `assets.py` resolves an ad's stored group for the copy brief.
"""

from app.brand_intelligence import repository as bi_repo
from app.core import vocab

HEADER = "【這個賣法的顧客】"
NO_GROUPS_TEXT = "（這個商品還沒有建顧客群）"
NO_PRODUCT_TEXT = "（這個 Campaign 沒有指定商品）"

# F43 Decisions 「Planner wiring」: prompt caps, not rule cards.
_MAX_PER_PRODUCT = 3
_MAX_TOTAL = 6


def knowledge_product_ids(conn, brand_id: str, product_ids: list[str]) -> list[str]:
    """The knowledge products behind the campaign's sell-way(s), in order, each once (a bundle
    has several; an old campaign may list several sell-ways of one product)."""
    seen: list[str] = []
    for product_id in product_ids:
        for knowledge_id in bi_repo.knowledge_product_ids(conn, brand_id, product_id):
            if knowledge_id not in seen:
                seen.append(knowledge_id)
    return seen


def _groups(conn, brand_id: str, knowledge_ids: list[str], picked) -> tuple[list[dict], int]:
    """(listed groups, how many more exist). `picked` = the campaign's `customer_group_ids`: a
    non-empty list narrows the sell-way's groups to those ids; missing, empty, or no longer
    matching any group -> every group (the campaign default)."""
    per_product = [
        bi_repo.list_customer_groups(conn, brand_id, knowledge_id) for knowledge_id in knowledge_ids
    ]
    if isinstance(picked, list) and picked:
        wanted = set(picked)
        narrowed = [[g for g in groups if g["id"] in wanted] for groups in per_product]
        if any(narrowed):
            per_product = narrowed
    total = sum(len(groups) for groups in per_product)
    listed = [g for groups in per_product for g in groups[:_MAX_PER_PRODUCT]][:_MAX_TOTAL]
    return listed, total - len(listed)


def _line(n: int, group: dict) -> str:
    pains = "、".join(
        f"{vocab.pain_label(key)}（pain={key}）" for key in group.get("pain_keys") or []
    )
    return (
        f"第 {n} 群：{group['who']}｜煩惱：{pains}"
        f"｜顧客會說：{group.get('quote') or '（沒寫）'}"
        f"｜什麼時候用：{group.get('when_used') or '（沒寫）'}"
    )


def prompt_groups(conn, org_id: str, brand_id: str, campaign: dict) -> tuple[str, list[dict]]:
    """(section text, the listed group rows in prompt order -- 第 N 群 is `listed[N-1]`). F46
    Contract A: the delivery planner maps the reply's `customer_group` number through this list,
    so the text and the list come from one read. ≤3 groups per knowledge product, ≤6 in all, with
    a 「另有 N 群沒有列出」 line when capped. `org_id` scopes the call like every section builder;
    the groups themselves are brand-scoped."""
    context = campaign.get("context_json") or {}
    product_ids = list(context.get("product_ids") or [])
    if not product_ids:
        return HEADER + NO_PRODUCT_TEXT, []
    knowledge_ids = knowledge_product_ids(conn, brand_id, product_ids)
    listed, omitted = _groups(conn, brand_id, knowledge_ids, context.get("customer_group_ids"))
    if not listed:
        return HEADER + NO_GROUPS_TEXT, []
    lines = [_line(n, group) for n, group in enumerate(listed, start=1)]
    if omitted > 0:
        lines.append(f"（另有 {omitted} 群沒有列出）")
    return HEADER + "\n" + "\n".join(lines), listed


def prompt_section(conn, org_id: str, brand_id: str, campaign: dict) -> tuple[str, list[str]]:
    """(section text, ids of the listed groups) -- `prompt_groups` with ids only."""
    text, listed = prompt_groups(conn, org_id, brand_id, campaign)
    return text, [group["id"] for group in listed]


def groups_by_id(conn, brand_id: str, campaign: dict) -> dict[str, dict]:
    """Every customer group of the campaign's knowledge products, by id -- how a stored
    `ads_ad.customer_group_id` resolves back to its row (a deleted group is simply absent)."""
    product_ids = list((campaign.get("context_json") or {}).get("product_ids") or [])
    found: dict[str, dict] = {}
    for knowledge_id in knowledge_product_ids(conn, brand_id, product_ids):
        for group in bi_repo.list_customer_groups(conn, brand_id, knowledge_id):
            found[group["id"]] = group
    return found


def brief_text(group: dict) -> str:
    """F46 Contract A: the copy step's `request.customer_group`,
    「〈who〉｜煩惱：〈pain labels〉｜顧客會說：〈quote〉｜什麼時候用：〈when〉」.
    Missing parts are omitted, not printed as 「沒寫」."""
    parts = [str(group.get("who") or "").strip()]
    pains = "、".join(vocab.pain_label(key) for key in group.get("pain_keys") or [])
    if pains:
        parts.append(f"煩惱：{pains}")
    quote = str(group.get("quote") or "").strip()
    if quote:
        parts.append(f"顧客會說：{quote}")
    when_used = str(group.get("when_used") or "").strip()
    if when_used:
        parts.append(f"什麼時候用：{when_used}")
    return "｜".join(part for part in parts if part)
