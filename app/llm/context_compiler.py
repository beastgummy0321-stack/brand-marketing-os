"""app/llm/context_compiler.py — 把「最小必要上下文」組成 Prompt 文字，供 gateway 使用。

兩份原始文件皆已被 5eca0db 清除；權威現在是這支檔案的硬性規則本身。

硬性規則：
1. 只取狀態 confirmed 的 Brand/Product Fact；pending 絕不進入（04 §2、§6）。
2. 只取狀態 active 的 Rule／Claim（repository.py 的 list_rules_for_*／list_claims_for_* 已過濾）。
3. 品牌層任務（product_id=None）只取「品牌整體」規則與宣稱，不含各產品專屬項目
   （04 §2：brand scope 只載入該 brand 的 Brand Facts／Rules，不含其他產品）——
   這裡刻意不用 repository.list_rules_for_brand／list_claims_for_brand 的原始回傳值，
   因為那兩個函式是給品牌檔案頁看「全部」用的，會混入各產品專屬項目（見 repository.py 頂部註解）。
4. 介面上只接受單一 brand_id（compile 簽名沒有「多品牌」的參數），從根本上不可能跨品牌組裝。
5. 規則進 prompt 上限（決策 0012 第二、三節）：hard 規則全部保留；soft 規則依
   `confirmed_at` 新到舊排序，兩者合計超過上限（`rule_cards`「rule_prompt_cap」卡）時，
   排比較後面的 soft 規則不進 prompt。

dead-code-sweep 票 04（2026-08-30 使用者裁決）：【已驗證的學習】（learning_ledger）與
【尚未驗證的猜想】（strategy_hypothesis）兩段已整段刪除——兩張表的唯一寫入端都掛在已刪除的
`app/ads/` 底下，這裡的讀取端因此永遠只讀得到空集合，兩段 prompt 段落永遠不會出現。
`list_overflow_rules()`（曾是累積智慧頁專用）同票一併刪除：同一頁被刪後，它只剩測試在呼叫。
兩張表本身連同 `rule_prompt_cap` 卡都還在（Ceiling：不動 schema、不動 rule_prompt_cap 卡）。
"""


from app.brand_intelligence import personas
from app.brand_intelligence import repository as repo
from app.core import rule_cards
from app.core.db import Conn
from app.core.vocab import EXPERIMENT_RULE_TYPE

PERSONA_PROMPT_CAP = 4
PERSONA_FIELD_CHAR_CAP = 80


def _persona_text(value) -> str:
    text = str(value or "").strip()
    return text[:PERSONA_FIELD_CHAR_CAP]


def _select_rules_for_prompt(conn: Conn, brand_id: str, rules: list) -> tuple:
    """規則進 prompt 的上限與排序（決策 0012 第二節）：hard 規則全部保留；soft 規則依
    `confirmed_at`（越新越優先）排序，兩者合計超過上限（rule_cards「rule_prompt_cap.
    max_active_rules」，該品牌覆寫值或系統預設 20）時，排比較後面的 soft 規則不進 prompt。

    回傳 (included, overflow)。overflow 曾供已刪除的累積智慧頁「未生效清單」顯示
    （list_overflow_rules，dead-code-sweep 票 04 隨頁一起刪除）；compile() 仍要這顆函式
    做截斷本身，overflow 半邊留著但目前沒有消費端。
    """
    cap = int(rule_cards.get_value(conn, brand_id, "rule_prompt_cap", "max_active_rules"))
    hard = [r for r in rules if r["severity"] == "hard"]
    soft_sorted = sorted(
        (r for r in rules if r["severity"] != "hard"),
        key=lambda r: r["confirmed_at"] or r["created_at"],
        reverse=True,
    )
    remaining = max(cap - len(hard), 0)
    return hard + soft_sorted[:remaining], soft_sorted[remaining:]


def format_claims(claims: list) -> list:
    """宣稱依 claim_type 拆成「可以講」與「絕對不能講」兩個標題明確的區塊（決策 0034 第 6 點）。

    改前的格式是 `- [forbidden] 內容`，整份 prompt 沒有一句話說明 forbidden 是不准講——
    等於把最危險的句子當可用清單示範給寫手看。改法：英文狀態值（approved/high_risk/forbidden）
    一律不進 prompt；forbidden 獨立成「絕對不能講（連近義改寫也不行）」區塊；
    approved／high_risk 併入「可以講」區塊，high_risk 額外附風險提醒（不得被靜默併成一般可用宣稱）。
    回傳區塊清單（0～2 段），供 compile() 直接併進 sections。
    """
    usable = [c for c in claims if c["claim_type"] != "forbidden"]
    forbidden = [c for c in claims if c["claim_type"] == "forbidden"]
    blocks = []
    if usable:
        lines = [
            f"- {c['claim_text']}"
            + ("（高風險：使用前務必先確認佐證）" if c["claim_type"] == "high_risk" else "")
            for c in usable
        ]
        blocks.append("【可以講】宣稱\n" + "\n".join(lines))
    if forbidden:
        blocks.append(
            "【絕對不能講（連近義改寫也不行）】宣稱\n"
            + "\n".join(f"- {c['claim_text']}" for c in forbidden)
        )
    return blocks


def compile(conn: Conn, brand_id: str, product_id: str | None = None, *,
            include_personas: bool = True):
    """組出最小必要上下文。

    回傳 (text, knowledge_item_ids, brand_version, product_version)：
    - text：組好的 Prompt 文字片段（規則／宣稱／事實，帶人可讀分類標題）。
    - knowledge_item_ids：實際引用的 Knowledge Item id 清單（供 llm_task 稽核）。
    - brand_version：組裝當下的 brand.knowledge_version。
    - product_version：組裝當下的 product.knowledge_version；未指定 product_id 時為 None。
    """
    brand = repo.get_brand(conn, brand_id)
    if brand is None:
        raise ValueError(f"找不到品牌：{brand_id}")

    product = None
    if product_id is not None:
        product = repo.get_product(conn, brand_id, product_id)
        if product is None:
            raise ValueError(f"找不到產品：{product_id}（或不屬於品牌 {brand_id}）")

    brand_facts = repo.list_brand_facts(conn, brand_id, status="confirmed")
    persona_rows = (
        personas.list_personas(conn, brand_id, limit=PERSONA_PROMPT_CAP)
        if include_personas else []
    )
    product_facts = (
        repo.list_product_facts(conn, brand_id, product_id, status="confirmed")
        if product_id is not None else []
    )

    if product_id is not None:
        rules_all = repo.list_rules_for_product(conn, brand_id, product_id)
        claims = repo.list_claims_for_product(conn, brand_id, product_id)
    else:
        rules_all = [r for r in repo.list_rules_for_brand(conn, brand_id) if r["product_id"] is None]
        claims = [c for c in repo.list_claims_for_brand(conn, brand_id) if c["product_id"] is None]
    rules, _overflow_rules = _select_rules_for_prompt(conn, brand_id, rules_all)

    knowledge_item_ids = (
        [r["id"] for r in rules]
        + [c["id"] for c in claims]
        + [f["id"] for f in brand_facts]
        + [f["id"] for f in product_facts]
        + [p["id"] for p in persona_rows]
    )

    # issue adopted-advice-can-invert（2026-09-06 演練）：行動與限制分兩個抽屜。採用一條成效
    # 判讀寫出來的規則（`EXPERIMENT_RULE_TYPE`）講的是「這一期要去做的實驗」；跟「不准做的
    # 事」放同一段，模型會抓住句子前半的現況陳述、把「去測試 X」讀成「先不要用 X」——三個
    # 角色各採用一條，反了一條，反的那條正是「去測一件從沒測過的事」。
    constraint_rules = [r for r in rules if r["rule_type"] != EXPERIMENT_RULE_TYPE]
    experiment_rules = [r for r in rules if r["rule_type"] == EXPERIMENT_RULE_TYPE]

    sections = []
    if constraint_rules:
        sections.append(
            "【限制】規則\n" + "\n".join(f"- {r['content']}" for r in constraint_rules)
        )
    sections.extend(format_claims(claims))
    if brand_facts:
        sections.append(
            "【事實】品牌事實\n" + "\n".join(f"- {f['label']}：{f['value']}" for f in brand_facts)
        )
    if product_facts:
        sections.append(
            "【事實】產品事實\n" + "\n".join(f"- {f['label']}：{f['value']}" for f in product_facts)
        )
    if persona_rows:
        sections.append(
            "【典型客人】\n" + "\n".join(
                f"- {_persona_text(p['title'])}｜什麼時候需要：{_persona_text(p['when_needed'])}"
                f"｜在意：{_persona_text(p['care_about'])}｜猶豫：{_persona_text(p['hesitation'])}"
                f"｜去哪找他：{_persona_text(p['where_to_find'])}"
                for p in persona_rows
            )
        )

    if experiment_rules:
        # 擺在所有段落的最後（`docs/contracts/schedule.md`「Position in the prompt decides
        # whether an instruction runs」，T8b 實機驗收量到的：同一句指令放中間會被前面幾千字
        # 蓋過去）——這一段是要被執行的動作，不是背景資料。
        sections.append(
            "【本期要測的】\n"
            "這一段是這一期要主動去做的事，不是禁止事項；每一條都要在這一期的方案裡排到。\n"
            + "\n".join(f"- {r['content']}" for r in experiment_rules)
        )

    text = "\n\n".join(sections)
    product_version = product["knowledge_version"] if product is not None else None
    return text, knowledge_item_ids, brand["knowledge_version"], product_version
