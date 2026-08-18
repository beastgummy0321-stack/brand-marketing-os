# -*- coding: utf-8 -*-
"""app/llm/context_compiler.py — 把「最小必要上下文」組成 Prompt 文字，供 gateway 使用。

見 docs/design/04-context-scope.md、docs/design/06-llm-gateway.md §7、決策 0030（學習迴路接電）。

硬性規則：
1. 只取狀態 confirmed 的 Brand/Product Fact；pending 絕不進入（04 §2、§6）。
2. 只取狀態 active 的 Rule／Claim（repository.py 的 list_rules_for_*／list_claims_for_* 已過濾）。
3. 品牌層任務（product_id=None）只取「品牌整體」規則與宣稱，不含各產品專屬項目
   （04 §2：brand scope 只載入該 brand 的 Brand Facts／Rules，不含其他產品）——
   這裡刻意不用 repository.list_rules_for_brand／list_claims_for_brand 的原始回傳值，
   因為那兩個函式是給品牌檔案頁看「全部」用的，會混入各產品專屬項目（見 repository.py 頂部註解）。
4. 介面上只接受單一 brand_id（compile 簽名沒有「多品牌」的參數），從根本上不可能跨品牌組裝。
5. 【已驗證的學習】（來源 `learning_ledger`）與【尚未驗證的猜想】（來源 `strategy_hypothesis`
   status 為 proposed／testing）分兩段、不得混寫；未驗證段一律標明來源，不得以事實語氣呈現
   （domain.md：假設不得在 prompt 中冒充事實）。`learning_ledger` 現屬品牌永久層
   `app/brand_intelligence`（修憲落地 A3，決策 0037），本檔透過
   `repo.list_learnings_for_prompt()` 讀取，不再對表下原生 SQL（A1：跨層一律走公開函式）。
   零學習紀錄／零未結案假設時不新增任何段落，逐字相容既有輸出（回歸鐵條，見 issue #54 驗收條件）。
6. 跨分支知識可見性（A4）：`track` 參數＝目前呼叫端所屬分支，預設 `"ads"`
   （目前唯一存在的分支——見決策 0037 第三節，第 2 條分支尚未上線）。預設
   `include_cross_track=False`：只取這個分支自己學到的東西；開啟後會連別分支的學習一併
   帶入，並在該條目後標示「來源分支：xxx」，不得讓讀者誤以為是本分支自己驗證過的結論。
7. 規則進 prompt 上限（決策 0012 第二、三節）：hard 規則全部保留；soft 規則依
   `confirmed_at` 新到舊排序，兩者合計超過上限（`rule_cards`「rule_prompt_cap」卡）時，
   排比較後面的 soft 規則不進 prompt——不悄悄消失，`list_overflow_rules()` 供累積智慧頁
   顯示「有 N 條規則因超過上限未生效」清單。
"""

import sqlite3
from typing import Optional

from app.brand_intelligence import personas
from app.brand_intelligence import repository as repo
from app.core import rule_cards

_UNVALIDATED_STATUSES = ("proposed", "testing")

# A4 目前唯一存在的分支代號（第 2 條分支上線前，所有呼叫端實質上都是廣告分支）。
DEFAULT_TRACK = "ads"
PERSONA_PROMPT_CAP = 4
PERSONA_FIELD_CHAR_CAP = 80


def _persona_text(value) -> str:
    text = str(value or "").strip()
    return text[:PERSONA_FIELD_CHAR_CAP]


def _select_rules_for_prompt(conn: sqlite3.Connection, brand_id: str, rules: list) -> tuple:
    """規則進 prompt 的上限與排序（決策 0012 第二節）：hard 規則全部保留；soft 規則依
    `confirmed_at`（越新越優先）排序，兩者合計超過上限（rule_cards「rule_prompt_cap.
    max_active_rules」，該品牌覆寫值或系統預設 20）時，排比較後面的 soft 規則不進 prompt。

    回傳 (included, overflow)——overflow 供累積智慧頁「未生效清單」顯示用
    （list_overflow_rules，決策 0012 第三節：超額不悄悄丟棄）。
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


def list_overflow_rules(conn: sqlite3.Connection, brand_id: str) -> list:
    """因超過生成提示詞上限而未生效的規則清單（累積智慧頁用，決策 0012 第三節：超額不悄悄
    丟棄）。跟 compile() 用同一顆 `_select_rules_for_prompt` 排序＋套上限，且涵蓋 compile()
    實際會組出的每一種組合：品牌層任務（只有品牌整體規則）＋每個生效中產品的產品層任務
    （品牌整體＋該產品專屬規則合併後才套上限，跟 `list_rules_for_product` 一致）。合併後
    才超過上限、但品牌整體規則單獨算沒超過的產品專屬規則，只在產品層任務出現，若只算品牌
    層會被漏掉——這裡一併收進來，依 id 去重後回傳。
    """
    brand_rules = [r for r in repo.list_rules_for_brand(conn, brand_id) if r["product_id"] is None]
    _included, overflow = _select_rules_for_prompt(conn, brand_id, brand_rules)
    overflow_by_id = {r["id"]: r for r in overflow}

    for product in repo.list_products(conn, brand_id):
        if product["status"] != "active":
            continue
        product_rules = repo.list_rules_for_product(conn, brand_id, product["id"])
        _included, product_overflow = _select_rules_for_prompt(conn, brand_id, product_rules)
        for r in product_overflow:
            overflow_by_id[r["id"]] = r

    return list(overflow_by_id.values())


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


def _learning_source_note(entry: dict, *, current_track: str) -> str:
    """附來源期別、樣本數（決策 0030 第 11 點）與跨分支來源（A4）；缺值時省略該項而非
    顯示空白。來源分支只在「跟目前分支不同」時才附註——本分支自己的學習不必多此一舉。"""
    parts = []
    if entry.get("source_cycle_id"):
        parts.append(f"來源期別 {entry['source_cycle_id']}")
    if entry.get("sample_size"):
        parts.append(f"樣本數 {entry['sample_size']}")
    if entry.get("source_track") and entry["source_track"] != current_track:
        parts.append(f"來源分支：{entry['source_track']}")
    return f"（{'，'.join(parts)}）" if parts else ""


def compile(conn: sqlite3.Connection, brand_id: str, product_id: Optional[str] = None, *,
            track: str = DEFAULT_TRACK, include_cross_track: bool = False,
            include_personas: bool = True):
    """組出最小必要上下文。

    回傳 (text, knowledge_item_ids, brand_version, product_version)：
    - text：組好的 Prompt 文字片段（規則／宣稱／事實，帶人可讀分類標題）。
    - knowledge_item_ids：實際引用的 Knowledge Item id 清單（供 llm_task 稽核）。
    - brand_version：組裝當下的 brand.knowledge_version。
    - product_version：組裝當下的 product.knowledge_version；未指定 product_id 時為 None。

    `track`／`include_cross_track`：A4 跨分支知識可見性，見檔頭說明第 6 點。
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

    learnings = repo.list_learnings_for_prompt(
        conn, brand_id, track=track, product_id=product_id, include_cross_track=include_cross_track)
    if product_id is not None:
        hypotheses = [
            h for h in repo.list_strategy_hypotheses(conn, brand_id)
            if h["status"] in _UNVALIDATED_STATUSES
            and (h["product_id"] is None or h["product_id"] == product_id)
        ]
    else:
        hypotheses = [
            h for h in repo.list_strategy_hypotheses(conn, brand_id)
            if h["status"] in _UNVALIDATED_STATUSES and h["product_id"] is None
        ]

    knowledge_item_ids = (
        [r["id"] for r in rules]
        + [c["id"] for c in claims]
        + [f["id"] for f in brand_facts]
        + [f["id"] for f in product_facts]
        + [l["id"] for l in learnings]
        + [h["id"] for h in hypotheses]
        + [p["id"] for p in persona_rows]
    )

    sections = []
    if rules:
        sections.append("【限制】規則\n" + "\n".join(f"- {r['content']}" for r in rules))
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
    if learnings:
        sections.append(
            "【已驗證的學習】（來源：learning_ledger，經判讀驗證且經人確認）\n"
            + "\n".join(
                f"- {l['learning_text']}{_learning_source_note(l, current_track=track)}"
                for l in learnings
            )
        )
    if hypotheses:
        sections.append(
            "【尚未驗證的猜想】（來源：strategy_hypothesis，尚未經成效驗證，僅供參考、不得當作事實）\n"
            + "\n".join(f"- {h['statement']}" for h in hypotheses)
        )

    text = "\n\n".join(sections)
    product_version = product["knowledge_version"] if product is not None else None
    return text, knowledge_item_ids, brand["knowledge_version"], product_version
