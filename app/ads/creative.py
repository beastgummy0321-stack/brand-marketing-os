"""app/ads/creative.py — 素材包的生成與改寫（票 6）。

依已確認的計畫（app/ads/plan.py）產出每個切角的素材變體，每一則都帶：
- experiment_cell_id：回溯得到是哪個切角（成效歸因的鏈條起點）
- fingerprint_json：四軸結構化指紋（app/ads/fingerprint.py），拒絕記憶靠它累積

第一批只出圖片提示詞，不直接生圖（決策 0022 第 3 題）——`final_asset` 的位置已經留好，
分支 3 視覺資產建好後接上同一個位置即可。

拒絕時的當場改寫（ADHD 設計輸入方向二）：使用者按「不要這個」並選理由後，
系統把該理由轉成負面約束、只重寫這一則，放回同一個位置。不加新關卡、不離開這一頁。
"""

from collections import Counter
from collections.abc import Callable
from typing import NamedTuple

from app.ads import creative_matrix as cmx
from app.ads import fingerprint as fp
from app.ads import plan as ads_plan
from app.ads import repository as ads_repo
from app.ads import theme_repository as theme_repo
from app.brand_intelligence import repository as bi
from app.core import settings as coresettings
from app.core.audit import write_audit
from app.core.db import jsonb, new_id, now_utc
from app.llm import context_compiler, gateway, methodology, pricing, providers

PROVIDER = providers.AnthropicProvider()  # 測試整包換掉

CREATIVE_MAX_TOKENS = 16000  # 也是花費上限攔截（票 M2）的呼叫前保守估計依據，見 generate()

# 對應 app/methodology/README.md 對照表的列名（票 11）；一次生成同時出 Hook／文案／
# 圖片提示詞，兩列都要吃，改對照表內容不必改這裡。
METHODOLOGY_TASK_LABELS = ["Hook／文案生成", "圖片 Prompt 生成"]

# 每個切角要產幾則、各是什麼型別。數量是可設定值，不寫死在 prompt（build.md §26）。
VARIANTS_PER_CELL = {"image_prompt": 1, "hook": 2, "copy": 1}

VARIANT_LABELS = {
    "image_prompt": "圖片提示詞",
    "hook": "開場白",
    "copy": "廣告文案",
    "script": "影片腳本",
}

# 票 02-repoint-creative-readers D3：新舊素材型別詞彙唯一對照表，只在這裡放一份。
# description 故意不列入（DEC-B，使用者尚未決定要不要收進交接包）——不對照就等於不存在，
# 讀取層（_component_to_variant）看到不在這張表裡的 component_type 一律跳過，不會外洩。
COMPONENT_TYPE_TO_VARIANT_TYPE = {
    "title": "hook",
    "body": "copy",
    "image_prompt": "image_prompt",
}

PARSE_FAIL_MESSAGE = "AI 有回覆，但格式讀不成預期的樣子。可以再試一次。"
HOOK_DIVERSITY_FAIL_MESSAGE = (
    "這批 Hook 切法不夠多樣，看起來像同一種切法換句話說，已經擋下沒有存檔，可以再產一次。"
)
NO_CUSTOMER_VOICE_TEXT = (
    "（這個品牌目前沒有任何顧客原話語料，本批素材照樣生成，但誠實不編造顧客原話或出處。）"
)

_SYSTEM = (
    "你是資深廣告文案，正在替客戶產出一批 Meta 廣告素材。"
    "只回傳 JSON，不要任何 JSON 以外的文字。除了圖片提示詞可用英文，其餘一律繁體中文。"
)


def _variant_brief(variants_per_cell: dict | None = None) -> str:
    return "\n".join(
        f"- {key}（{VARIANT_LABELS[key]}）：{count} 則"
        for key, count in (variants_per_cell or VARIANTS_PER_CELL).items()
    )


def _customer_voice_block(conn, brand_id: str, limit: int = 30) -> tuple:
    """顧客原話語料組成 prompt 區塊。回傳 (block_text, corpus_available)。

    語料庫空時照樣生成（決策 0013），只是誠實告訴模型「沒有語料，不要編」；
    corpus_available 供呼叫端存進每則素材，頁面才能誠實標注「無顧客原話支撐」
    （決策 0023 第 18a 點）。
    """
    lines = []
    for row in bi.list_customer_voices(conn, brand_id, status="active"):
        source = row["source_channel"] + (f"／{row['source_detail']}" if row.get("source_detail") else "")
        for item in row["extraction"]:
            lines.append(f"- 「{item['quote']}」（{item['insight']}）— 出處：{source}")
            if len(lines) >= limit:
                break
        if len(lines) >= limit:
            break
    if not lines:
        return NO_CUSTOMER_VOICE_TEXT, False
    return ("顧客原話語料（能用就優先引用原文用詞，並在 quote_source 標出處；"
            "不要把原話改寫成行銷腔）：\n" + "\n".join(lines)), True


def _build_user_text(brand: dict, cycle: dict, plan: dict, cells: list,
                     context_text: str, methodology_text: str, constraints: list,
                     customer_voice_text: str, *,
                     variants_per_cell: dict | None = None) -> str:
    cell_lines = "\n".join(
        f"- 切角 {index + 1}（id={cell['id']}）：{cell['creative_angle']}"
        for index, cell in enumerate(cells)
    )
    parts = [
        f"品牌名稱：{brand['name']}",
        f"本期打法：{plan['summary']}",
        f"要打的人：{ads_plan.audience_summary_text(plan['audience'])}",
        f"要產素材的切角：\n{cell_lines}",
        context_text if context_text else "（目前沒有任何已確認的品牌資料。）",
    ]

    if methodology_text:
        parts.append("【方法論】產出素材時請依循以下專業行銷準則：\n" + methodology_text)

    if constraints:
        parts.append(
            "這個品牌過去被退過的東西，這次不要再出現：\n"
            + "\n".join(f"- {c}" for c in constraints)
        )

    parts.append(customer_voice_text)

    parts.append(
        "每個切角都要產出：\n" + _variant_brief(variants_per_cell) + "\n\n"
        "每一則都要標上四個軸的指紋，值只能從下面挑，不可以自己發明：\n"
        + fp.prompt_vocabulary()
    )
    parts.append(
        "八條硬規則：\n"
        "1. 只能用上面已登錄的宣稱，不得放寬、不得新增；硬性限制規則一律遵守。\n"
        "2. 不要編造規格、成分、檢驗數據或名人推薦。\n"
        "3. 圖片提示詞要能直接貼進生圖工具，寫清楚畫面內容、構圖與風格。\n"
        "4. 同一個切角底下的幾則不要只是換句話說，要真的不一樣。\n"
        "5. 每一則都要標 creative_angle_number（1 到 35 的整數，對應上面方法論創意矩陣列出的"
        "角度編號），只能選矩陣裡實際存在的角度，不可以自己編號。\n"
        "6. 每一則都要標 on_camera（true 或 false）：這則實際上有沒有人物入鏡。是 true 時，"
        "描述要照方法論『真人實拍 DNA』規則寫（台灣面孔、台灣場景、景深散景、人物與產品都對焦"
        "清晰）；是 false 時（純產品圖、資訊圖、純色塊字卡），不要出現任何人物或人物相關描述。\n"
        "7. variant_type 是 hook 或 copy 時要標 cut_type（下面切法之一，不可以自創）：\n"
        + cmx.cut_type_vocabulary() + "\n"
        f"這批 Hook 至少要橫跨 {cmx.HOOK_CUT_TYPE_MIN_DISTINCT} 種不同切法，不能全部是"
        "同一種切法換句話說。\n"
        "8. 能用上面的顧客原話語料就優先引用原文用詞，在 quote_source 標出處；沒有引用原話"
        "就把 quote_source 留 null，不要編造出處或原話。"
    )
    parts.append(
        "輸出格式：只回傳以下 JSON：\n"
        '{"variants": [{"cell_id": "上面那些 id 之一", "variant_type": "image_prompt/hook/copy",'
        ' "content": "素材內容本身", "rationale": "為什麼這樣寫",'
        ' "creative_angle_number": 1到35的整數, "on_camera": true 或 false,'
        ' "cut_type": "hook 或 copy 才需要，上面切法 key 之一，其餘型別留 null",'
        ' "quote_source": "有引用顧客原話時標出處，否則 null",'
        ' "fingerprint": {"angle": "...", "tone": "...", "format": "...", "selling_point": "..."}}]}'
    )
    return "\n\n".join(parts)


class NormalizeResult(NamedTuple):
    """驗形結果：不再只回「剩下的」，連同被剔除的則數與存活型別統計一起回報（票 30）。

    variants：存活變體，全數被剔除或原本就沒有時為 None（沿用舊有「失敗」語意）。
    dropped：這批原始回覆裡，因為認不得的 cell_id／型別、缺角度編號、缺出鏡標注、
        或缺合法切法而被丟掉的則數。
    type_counts：存活變體依 variant_type 的則數統計，呼叫端拿它跟 VARIANTS_PER_CELL
        比對就知道整批缺了哪個型別。
    """

    variants: list | None
    dropped: int
    type_counts: Counter


def _normalize(data, valid_cell_ids: set) -> NormalizeResult:
    """驗證形狀。認不得的 cell_id／型別，或缺角度編號、出鏡標注的則直接丟掉；一則都不剩才算失敗。

    hook／copy 還要求合法的 cut_type（票 7：切法要能程式判定，不能自己造詞）；
    image_prompt 沒有 cut_type 硬性要求，有給值時仍驗形，格式不對就存 None。
    """
    if not isinstance(data, dict):
        return NormalizeResult(None, 0, Counter())
    raw_items = data.get("variants") or []
    variants = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        variant_type = item.get("variant_type")
        cell_id = item.get("cell_id")
        if not isinstance(content, str) or not content.strip():
            continue
        if variant_type not in VARIANT_LABELS or cell_id not in valid_cell_ids:
            continue
        angle_number = item.get("creative_angle_number")
        if not cmx.is_valid_angle_number(angle_number):
            continue
        on_camera = item.get("on_camera")
        if not isinstance(on_camera, bool):
            continue
        cut_type = item.get("cut_type")
        if cut_type not in cmx.CUT_TYPES:
            if variant_type in ("hook", "copy"):
                continue  # 這兩種型別的切法多樣性要能程式判定，沒有合法切法就整則丟掉
            cut_type = None
        quote_source = item.get("quote_source")
        quote_source = (quote_source.strip()
                        if isinstance(quote_source, str) and quote_source.strip() else None)
        variants.append({
            "cell_id": cell_id,
            "variant_type": variant_type,
            "content": content.strip(),
            "rationale": (item.get("rationale") or "").strip()
            if isinstance(item.get("rationale"), str) else "",
            "fingerprint": fp.normalize(item.get("fingerprint")),
            "creative_angle_number": angle_number,
            "on_camera": on_camera,
            "cut_type": cut_type,
            "quote_source": quote_source,
        })
    return NormalizeResult(variants or None, len(raw_items) - len(variants),
                           Counter(v["variant_type"] for v in variants))


def _product_scoped_bans(conn, brand_id: str, product_ids: list) -> str:
    """本期涉及產品的專屬禁用宣稱與硬規則，併入生成端 context（修憲落地 L3，決策 0034 第 5 點）。

    `context_compiler.compile()` 一次只吃單一 `product_id`（04 §2：brand scope 不含任何產品專屬
    項目），而一個檔期可能橫跨多個產品（決策 0022 第 5 點）——不能靠改 compile() 的介面解決，
    所以另外把「本期涉及的每個產品」專屬（`product_id` 精準等於該產品，不含品牌整體，品牌整體
    那份已經在 `compile(conn, brand_id)` 的結果裡）的 forbidden claim／hard rule 撈出來，
    用同一套「絕對不能講」格式併進 prompt。只補這兩種——不是把整個產品 context 塞進來，
    避免跟 compile() 的既有邏輯重複（不閉門造車）。
    """
    lines = []
    for product_id in product_ids:
        product = bi.get_product(conn, brand_id, product_id)
        if product is None:
            continue
        forbidden = [c for c in bi.list_claims_for_product(conn, brand_id, product_id)
                    if c["product_id"] == product_id and c["claim_type"] == "forbidden"]
        hard_rules = [r for r in bi.list_rules_for_product(conn, brand_id, product_id)
                     if r["product_id"] == product_id and r["severity"] == "hard"]
        for c in forbidden:
            lines.append(f"-（{product['name']}）{c['claim_text']}")
        for r in hard_rules:
            lines.append(f"-（{product['name']}）{r['content']}")
    if not lines:
        return ""
    return "【絕對不能講（連近義改寫也不行）】本期產品專屬禁令\n" + "\n".join(lines)


def _rejection_constraints(conn, brand_id: str, limit: int = 12) -> list:
    """把過去的拒絕紀錄整理成「不要再出現」的人話約束（拒絕記憶的入口）。

    程式彙整、程式判定——LLM 只是收到一份現成清單，不負責回憶也不負責歸納。
    """
    rows = conn.execute(
        "SELECT reason_code, fingerprint_json FROM adoption_decision"
        " WHERE brand_id = %s AND decision = 'rejected' ORDER BY decided_at DESC LIMIT %s",
        (brand_id, limit * 3),
    ).fetchall()

    seen, constraints = set(), []
    for row in rows:
        axis = fp.REASON_TO_AXIS.get(row["reason_code"])
        if axis is None:
            continue
        value = (row["fingerprint_json"] or {}).get(axis)
        if not value or (axis, value) in seen:
            continue
        seen.add((axis, value))
        constraints.append(
            f"{fp.AXES[axis]['label']}是「{fp.axis_value_label(axis, value)}」的那種"
            f"（曾因「{fp.REJECT_REASON_LABELS.get(row['reason_code'], '')}」被退掉）"
        )
        if len(constraints) >= limit:
            break
    return constraints


def generate(conn, brand_id: str, cycle_id: str, actor: str, *,
            include_methodology: bool = True,
            on_stage: Callable[[str], None] | None = None) -> tuple:
    """產出本期素材包。成功回 (True, None)；失敗回 (False, 人話錯誤)，不入庫。

    include_methodology=False（票 11 效果盲測專用）：略過方法論載入，其餘完全相同，
    見 app/ads/plan.py generate_options() 同一參數的說明。

    on_stage（票 29，等待頁誠實化）：見 app/ads/plan.py generate_options() 同一參數的說明。
    """
    brand = bi.get_brand(conn, brand_id)
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    if brand is None or cycle is None:
        raise ValueError("找不到品牌或廣告檔期")

    plan_row = ads_plan.get_latest_plan(conn, brand_id, cycle_id)
    if plan_row is None or plan_row["status"] != "approved":
        return False, "這期的計畫還沒確認，先確認計畫再做素材。"

    cells = [dict(r) for r in conn.execute(
        "SELECT * FROM experiment_cell WHERE brand_id = %s AND campaign_cycle_id = %s ORDER BY id",
        (brand_id, cycle_id),
    )]
    if not cells:
        return False, "這期沒有可用的切角，請重新產一次計畫。"

    # 花費上限攔截（票 M2）：跟計畫生成、品牌智庫的產品調研共用同一道上限與同一個檢查函式。
    model = providers.resolve_model(task_type="creative_batch", conn=conn)
    budget_err = coresettings.budget_exceeded_message(
        conn, brand_id, pricing.cost_ceiling(model, CREATIVE_MAX_TOKENS),
        action="這期的素材生成",
        fallback_hint="可以先採用已經產出的素材，或到設定頁調高上限後再試。")
    if budget_err:
        return False, budget_err

    # 修憲落地 L3（決策 0034 第 5 點）：品牌層 compile() 濾掉所有產品專屬項目，生成端因此看不到
    # 產品層禁令——寫的時候看不到、掃的時候才看到，而掃到只標黃。
    # 這期只涉及 0～1 個產品時，直接傳 product_id 讓 compile() 照既有邏輯把該產品完整的
    # 已確認事實／規則／宣稱一併帶進來（04 §2）。一個檔期可能橫跨多個產品時（決策 0022 第 5
    # 點），compile() 一次只吃單一 product_id，退而求其次：只把每個產品的 forbidden claim／
    # hard rule 併入品牌層 context（不是整份產品 context，避免品牌層內容被重複列出）。
    cell_product_ids = sorted({c["product_id"] for c in cells if c["product_id"]})
    if len(cell_product_ids) <= 1:
        single_product_id = cell_product_ids[0] if cell_product_ids else None
        context_text, knowledge_item_ids, brand_version, _ = context_compiler.compile(
            conn, brand_id, single_product_id)
    else:
        context_text, knowledge_item_ids, brand_version, _ = context_compiler.compile(conn, brand_id)
        product_ban_text = _product_scoped_bans(conn, brand_id, cell_product_ids)
        if product_ban_text:
            context_text = (f"{context_text}\n\n{product_ban_text}" if context_text
                            else product_ban_text)
            for product_id in cell_product_ids:
                knowledge_item_ids += [
                    c["id"] for c in bi.list_claims_for_product(conn, brand_id, product_id)
                    if c["product_id"] == product_id and c["claim_type"] == "forbidden"
                ] + [
                    r["id"] for r in bi.list_rules_for_product(conn, brand_id, product_id)
                    if r["product_id"] == product_id and r["severity"] == "hard"
                ]
    methodology_result = (
        methodology.compile(conn, METHODOLOGY_TASK_LABELS, brand_id=brand_id, actor=actor)
        if include_methodology
        else methodology.MethodologyResult(text="", missing_files=[], loaded_files=[])
    )
    customer_voice_text, customer_voice_available = _customer_voice_block(conn, brand_id)
    constraints = _rejection_constraints(conn, brand_id)
    valid_cell_ids = {c["id"] for c in cells}
    user_text = _build_user_text(brand, cycle, plan_row["plan"], cells, context_text,
                                 methodology_result.text, constraints, customer_voice_text)

    if on_stage:
        on_stage("ask_ai")
    task = gateway.run_task(
        conn, PROVIDER, brand_id=brand_id, task_type="creative_batch",
        prompt_template_id="creative_batch", prompt_template_version="v1",
        system=_SYSTEM, messages=[{"role": "user", "content": user_text}],
        context=gateway.TaskContext(
            context_scope={"brand_id": brand_id, "campaign_cycle_id": cycle_id,
                           # 這次真的組進 prompt 的方法論檔，事後回推不出來（ADR 0009）
                           "methodology_files": methodology_result.loaded_files},
            knowledge_item_ids=knowledge_item_ids, brand_version=brand_version,
        ),
        # 開網路搜尋（ADR 0005）：素材要貼到當下的話題與檔期，讓 AI 自己去查。補打缺型別
        # （_backfill_missing_types）與單則改寫（rewrite）沿用同一批已經查過的上下文，不重複
        # 開搜尋——ADR 首波只點名「素材生成」這一處。
        options=gateway.TaskOptions(max_tokens=CREATIVE_MAX_TOKENS,
                                    tools=[providers.WEB_SEARCH_TOOL]),
    )
    if task["status"] != "succeeded":
        return False, task["error"]
    if on_stage:
        on_stage("save")

    result = _normalize(gateway.parse_json_reply(task["rendered_output"]), valid_cell_ids)
    if result.variants is None:
        return False, PARSE_FAIL_MESSAGE
    variants = result.variants

    # 缺型別自動補打一次（票 30）：跟預期的型別集合（VARIANTS_PER_CELL／VARIANT_LABELS）比對，
    # 整批裡完全沒出現的型別才算缺——只補這些型別，只打一次，不迴圈重試、不整批重來。
    missing_types = sorted(set(VARIANTS_PER_CELL) - set(result.type_counts))
    if missing_types:
        variants = variants + _backfill_missing_types(
            conn, brand, cycle, plan_row["plan"], cells, context_text, methodology_result.text,
            constraints, customer_voice_text, valid_cell_ids, missing_types,
            brand_id=brand_id, cycle_id=cycle_id,
            knowledge_item_ids=knowledge_item_ids, brand_version=brand_version,
        )
        missing_types = sorted(set(VARIANTS_PER_CELL) - {v["variant_type"] for v in variants})

    hook_cut_types = [v["cut_type"] for v in variants if v["variant_type"] == "hook"]
    if not cmx.hook_diversity_ok(hook_cut_types):
        return False, HOOK_DIVERSITY_FAIL_MESSAGE

    _persist(conn, brand_id, cycle_id, cells, variants, actor, methodology_result.missing_files,
            customer_voice_available, missing_types)
    return True, None


def _backfill_missing_types(conn, brand: dict, cycle: dict, plan: dict, cells: list,
                            context_text: str, methodology_text: str, constraints: list,
                            customer_voice_text: str, valid_cell_ids: set, missing_types: list,
                            *, brand_id: str, cycle_id: str, knowledge_item_ids: list,
                            brand_version: int) -> list:
    """整批驗形後仍缺的型別，只補打一次 LLM（只問缺的型別，重用 generate() 同一套 prompt
    組法與驗形，不是另建一套平行機制）。回傳這次補到、且型別確實在 missing_types 內的變體；
    補失敗或補了仍缺就回空 list——呼叫端據此老實標注頁面，不重試、不整批重來。
    """
    variants_per_cell = {t: VARIANTS_PER_CELL[t] for t in missing_types}
    user_text = _build_user_text(brand, cycle, plan, cells, context_text, methodology_text,
                                 constraints, customer_voice_text,
                                 variants_per_cell=variants_per_cell)
    task = gateway.run_task(
        conn, PROVIDER, brand_id=brand_id, task_type="creative_backfill",
        prompt_template_id="creative_backfill", prompt_template_version="v1",
        system=_SYSTEM, messages=[{"role": "user", "content": user_text}],
        context=gateway.TaskContext(
            context_scope={"brand_id": brand_id, "campaign_cycle_id": cycle_id},
            knowledge_item_ids=knowledge_item_ids, brand_version=brand_version,
        ),
        options=gateway.TaskOptions(max_tokens=16000),
    )
    if task["status"] != "succeeded":
        return []
    result = _normalize(gateway.parse_json_reply(task["rendered_output"]), valid_cell_ids)
    return [v for v in (result.variants or []) if v["variant_type"] in missing_types]


def _brief_for_cell(conn, brand_id: str, cycle_id: str, cell: dict, ts: str) -> str:
    """每個切角一份 Execution Brief，變體掛在它下面（03 §4.2 的鏈條）。"""
    org_id = bi.get_brand(conn, brand_id)["org_id"]
    existing = conn.execute(
        "SELECT id FROM creative_brief WHERE brand_id = %s AND experiment_cell_id = %s",
        (brand_id, cell["id"]),
    ).fetchone()
    if existing:
        return existing["id"]
    brief_id = new_id("cbf")
    conn.execute(
        "INSERT INTO creative_brief (id, org_id, campaign_cycle_id, experiment_cell_id, brand_id,"
        " brief_type, purpose, status, created_at, updated_at)"
        " VALUES (%s, %s, %s, %s, %s, 'copy', %s, 'dispatched', %s, %s)",
        (brief_id, org_id, cycle_id, cell["id"], brand_id, cell["creative_angle"] or "本期切角", ts, ts),
    )
    return brief_id


def _persist(conn, brand_id: str, cycle_id: str, cells: list, variants: list,
             actor: str, methodology_missing: list | None = None,
             customer_voice_available: bool = True,
             missing_creative_types: list | None = None) -> None:
    org_id = bi.get_brand(conn, brand_id)["org_id"]
    ts = now_utc()
    briefs = {cell["id"]: _brief_for_cell(conn, brand_id, cycle_id, cell, ts) for cell in cells}
    cell_products = {cell["id"]: cell["product_id"] for cell in cells}
    # 方法論缺席清單、顧客原話語料是否可用、補打一次後仍缺的型別，存進每則的 attributes_json
    # （同一批共用同一份值）——不新增表／欄位，頁面讀變體時就能誠實標注這批的生成條件
    # （決策 0023/0024；缺型別標注見票 30）。
    methodology_missing = methodology_missing or []
    missing_creative_types = missing_creative_types or []

    for rank, variant in enumerate(variants, start=1):
        cell_id = variant["cell_id"]
        conn.execute(
            "INSERT INTO creative_variant (id, org_id, variant_type, creative_brief_id,"
            " campaign_cycle_id, experiment_cell_id, brand_id, product_id, attributes_json,"
            " fingerprint_json, rationale, recommendation_rank, status, created_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'DRAFT', %s)",
            (new_id("cvr"), org_id, variant["variant_type"], briefs[cell_id], cycle_id, cell_id,
             brand_id, cell_products.get(cell_id),
             jsonb({"content": variant["content"],
                    "methodology_missing": methodology_missing,
                    "creative_angle_number": variant["creative_angle_number"],
                    "on_camera": variant["on_camera"],
                    "cut_type": variant["cut_type"],
                    "quote_source": variant["quote_source"],
                    "customer_voice_available": customer_voice_available,
                    "missing_creative_types": missing_creative_types}),
             jsonb(variant["fingerprint"]),
             variant["rationale"], rank, ts),
        )

    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="campaign_cycle", entity_id=cycle_id,
                action="generate_creatives", actor=actor, before=None,
                after={"variant_count": len(variants)})
    conn.commit()


# ---------------------------------------------------------------------------
# 讀取與採用／拒絕（票 02-repoint-creative-readers：資料源改為 creative_theme／
# creative_theme_component，經 app/ads/theme_repository.py 讀取——D2 單向依賴，本檔
# 不直接查那兩張表。creative_variant 沒有任何存活寫入路徑，讀它只會看到空殼，
# 詳見票面 Problem 段落與 D6）。
# ---------------------------------------------------------------------------

def _cell_product_ids(conn, brand_id: str, cycle_id: str) -> dict:
    """{experiment_cell_id: product_id}——experiment_cell 不是主題表，直接查（D2 只限主題
    資料要經 theme_repository，切角格本來就是 generate() 也在用的既有查法）。"""
    return {row["id"]: row["product_id"] for row in conn.execute(
        "SELECT id, product_id FROM experiment_cell WHERE brand_id = %s AND campaign_cycle_id = %s",
        (brand_id, cycle_id),
    )}


def _component_to_variant(component: dict, theme: dict, product_id: str | None) -> dict | None:
    """主題元件 → 舊素材形狀（D1 回傳形狀不變）。component_type 對不到 D3 對照表的
    （目前只有 description，DEC-B）一律回 None，呼叫端跳過——不對照就等於不外洩。

    theme_component 沒有 creative_angle_number／on_camera／cut_type／quote_source／
    customer_voice_available／methodology_missing／missing_creative_types 這些舊欄位
    （本來就屬於 creative_variant.attributes_json 的內容，主題模型沒有對應概念）；
    保留 key、給安全預設值，模板／前端只讀得到「有沒有這個 key」不會 KeyError，
    不臆測補一份假資料。
    """
    variant_type = COMPONENT_TYPE_TO_VARIANT_TYPE.get(component["component_type"])
    if variant_type is None:
        return None
    fingerprint = component.get("fingerprint_json") or {}
    return {
        "id": component["id"],
        "brand_id": component["brand_id"],
        "campaign_cycle_id": component["campaign_cycle_id"],
        "experiment_cell_id": theme["experiment_cell_id"],
        "product_id": product_id,
        "variant_type": variant_type,
        "type_label": VARIANT_LABELS.get(variant_type, variant_type),
        "content": component["content"],
        "fingerprint": fingerprint,
        "fingerprint_text": fp.describe(fingerprint),
        "rejected": component["rejected"],
        "reject_reason_label": component["reject_reason_label"],
        "auto_held": component["auto_held"],
        # routes_common.py 用 decision["decision"] == "adopted" 驅動 5 步進度軌；主題化之後
        # 採用是主題級的（theme_repository.adopt_theme），這裡回傳的元件本來就只來自已採用
        # 主題（見 list_variants 的過濾），所以一律是已採用形狀——decision 仍可能是 None
        # （get_variant 對非已採用主題的元件單獨查時），但 key 一定在。
        "decision": {"decision": "adopted"} if theme.get("status") == "adopted" else None,
        "creative_angle_number": None,
        "on_camera": None,
        "cut_type": None,
        "cut_type_label": None,
        "quote_source": None,
        "customer_voice_available": None,
        "methodology_missing": [],
        "missing_creative_types": [],
        "rationale": "",
    }


def list_variants(conn, brand_id: str, cycle_id: str) -> list:
    """本期已採用主題的元件，轉譯成舊素材形狀（D1）。D4：只有主題本身已採用，底下的
    元件才算「活的」出現在這份清單——草稿主題的元件不出現，不論退件與否；已出現的
    元件仍各自帶 rejected／reject_reason_label，呼叫端（delivery／handoff／compliance）
    照舊自行過濾，不在這裡先濾掉退件項（否則 compliance 掃不到已退件仍要重掃的
    auto_held 那類、delivery 也對不出「這格全退光」）。"""
    themes = theme_repo.list_themes_for_cycle(conn, brand_id, cycle_id, status="adopted")
    product_ids = _cell_product_ids(conn, brand_id, cycle_id)
    rows = []
    for theme in themes:
        product_id = product_ids.get(theme["experiment_cell_id"])
        for component in theme["components"]:
            row = _component_to_variant(component, theme, product_id)
            if row is not None:
                rows.append(row)
    return rows


def group_by_cell(conn, brand_id: str, cycle_id: str) -> list:
    """素材依切角分組，供頁面一組一組顯示。"""
    cells = [dict(r) for r in conn.execute(
        "SELECT * FROM experiment_cell WHERE brand_id = %s AND campaign_cycle_id = %s ORDER BY id",
        (brand_id, cycle_id),
    )]
    variants = list_variants(conn, brand_id, cycle_id)
    groups = []
    for cell in cells:
        items = [v for v in variants if v["experiment_cell_id"] == cell["id"]]
        if items:
            groups.append({"cell": cell, "variants": items})
    return groups


def get_variant(conn, brand_id: str, variant_id: str) -> dict | None:
    """單則查詢，不受 D4「主題已採用」門檻限制——呼叫端（例如 handoff 回填交接包已存的
    id、nextcycle 的 overclaim 候選卡）本來就可能查一個已經不再是最新採用狀態的元件，
    id 存在就該查得到，是否「活的」由呼叫端自己的情境判斷。"""
    component = theme_repo.get_component(conn, brand_id, variant_id)
    if component is None:
        return None
    theme = theme_repo.get_theme(conn, brand_id, component["creative_theme_id"])
    if theme is None:
        return None
    product_id = None
    if theme.get("experiment_cell_id"):
        cell = conn.execute(
            "SELECT product_id FROM experiment_cell WHERE brand_id = %s AND id = %s",
            (brand_id, theme["experiment_cell_id"]),
        ).fetchone()
        product_id = cell["product_id"] if cell else None
    return _component_to_variant(component, theme, product_id)


def reject(conn, brand_id: str, variant_id: str, *, reason_code: str, actor: str,
           reason_text: str | None = None) -> dict:
    """記下一次拒絕，含當下的指紋快照（變體之後若被改寫，記憶仍指向被退的那一版）。

    票 02-repoint-creative-readers：轉呼叫 theme_repository.reject_component()，複用它
    對 D4 退件的判定與寫入（target_type='theme_component'），不在這裡重寫一份判定邏輯。
    """
    variant = get_variant(conn, brand_id, variant_id)
    if variant is None:
        raise ValueError("找不到這則素材")
    theme_repo.reject_component(conn, brand_id, variant_id, reason_code=reason_code,
                                actor=actor, reason_text=reason_text)
    return variant


# 命中量到這個數字才在頁面上顯示「一次全部勾回」的批次按鈕（修憲落地 L2，決策 0034 第 25
# 條第 3 點）。1～2 則逐則點「勾回」跟批次沒差；命中內建詞庫裡「改善」這類日常用語一次
# 命中一堆素材時，逐則點就是體檢報告講的「第一期黃標轟炸」，所以從 3 則起給批次選項。
BATCH_RESTORE_THRESHOLD = 3


def restore(conn, brand_id: str, variant_id: str, *, actor: str) -> dict:
    """一鍵勾回：把系統自動預設挑掉（法規命中）的素材改回採用（修憲落地 L2）。

    只用來勾回**系統自動**挑掉的那些——使用者自己手動挑掉的那則已經被 `rewrite` 改寫掉、
    原內容不再是「這一則」了，沒有勾回的意義，UI 也不會給這個按鈕。

    票 02-repoint-creative-readers：決策紀錄改寫 target_type='theme_component'，才跟
    theme_repository 的退件查詢（_attach_component_decision）對得上。主題模型目前沒有
    「單元件恢復採用」的既有函式可呼叫（theme_repository 只有退件 reject_component()），
    維持舊碼原本直接寫 adoption_decision 的風格，只換 target_type。
    """
    org_id = bi.get_brand(conn, brand_id)["org_id"]
    variant = get_variant(conn, brand_id, variant_id)
    if variant is None:
        raise ValueError("找不到這則素材")
    conn.execute(
        "INSERT INTO adoption_decision (id, org_id, brand_id, campaign_cycle_id, target_type, target_id,"
        " decision, fingerprint_json, decided_by, decided_at)"
        " VALUES (%s, %s, %s, %s, 'theme_component', %s, 'adopted', %s, %s, %s)",
        (new_id("adp"), org_id, brand_id, variant["campaign_cycle_id"], variant_id,
         jsonb(variant["fingerprint"]), actor, now_utc()),
    )
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="creative_theme_component", entity_id=variant_id,
                action="compliance_restore", actor=actor,
                before={"decision": "rejected"}, after={"decision": "adopted"})
    conn.commit()
    return variant


def restore_all_auto_held(conn, brand_id: str, cycle_id: str, *, actor: str) -> int:
    """批次一鍵：把這期所有還處在「系統自動預設挑掉」狀態的素材一次勾回（修憲落地 L2，
    決策 0034 第 25 條第 3 點）。回傳勾回則數。"""
    org_id = bi.get_brand(conn, brand_id)["org_id"]
    ts = now_utc()
    restored = 0
    for variant in list_variants(conn, brand_id, cycle_id):
        if not variant["auto_held"]:
            continue
        conn.execute(
            "INSERT INTO adoption_decision (id, org_id, brand_id, campaign_cycle_id, target_type,"
            " target_id, decision, fingerprint_json, decided_by, decided_at)"
            " VALUES (%s, %s, %s, %s, 'theme_component', %s, 'adopted', %s, %s, %s)",
            (new_id("adp"), org_id, brand_id, cycle_id, variant["id"],
             jsonb(variant["fingerprint"]), actor, ts),
        )
        restored += 1
    if restored:
        write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="campaign_cycle", entity_id=cycle_id,
                    action="compliance_restore_batch", actor=actor, before=None,
                    after={"restored": restored})
        conn.commit()
    return restored


def learned_message(reason_code: str, fingerprint: dict) -> str:
    """拒絕當下回給使用者的一句話：「我學到：你不接受＿＿」。"""
    axis = fp.REASON_TO_AXIS.get(reason_code)
    value = (fingerprint or {}).get(axis) if axis else None
    if axis and value:
        return (f"我學到了：{fp.AXES[axis]['label']}是「{fp.axis_value_label(axis, value)}」"
                "的那種你不接受，之後會少出這類。")
    return "我學到了：這則你不接受，之後產素材會避開同一種寫法。"


REWRITE_FAIL_MESSAGE = "改寫沒成功，這則先留著原本的，你可以再按一次或直接略過。"


def rewrite(conn, brand_id: str, variant_id: str, *, reason_code: str, actor: str) -> tuple:
    """被退的那一則當場改寫一版，放回原位（同關卡內完成，不加新關卡）。

    回 (True, 新變體 id)；失敗回 (False, 人話錯誤)——原本那則保持被退狀態，不留半成品。
    """
    org_id = bi.get_brand(conn, brand_id)["org_id"]
    variant = get_variant(conn, brand_id, variant_id)
    if variant is None:
        raise ValueError("找不到這則素材")
    brand = bi.get_brand(conn, brand_id)
    # 修憲落地 L3：改寫是單一變體的重寫，該變體本來就已知屬於哪個產品（或品牌整體），
    # 直接傳 product_id 讓 compile() 照 04 §2 的既有邏輯把該產品的專屬禁令一併帶進來。
    context_text, knowledge_item_ids, brand_version, _ = context_compiler.compile(
        conn, brand_id, variant["product_id"])

    reason_label = fp.REJECT_REASON_LABELS.get(reason_code, "")
    user_text = "\n\n".join([
        f"品牌名稱：{brand['name']}",
        context_text if context_text else "（目前沒有任何已確認的品牌資料。）",
        f"這是一則{VARIANT_LABELS.get(variant['variant_type'], '素材')}，客戶退掉了：\n"
        f"「{variant['content']}」",
        f"退掉的理由是：{reason_label}",
        "請重寫一則同型別、同一個切角的素材，明確避開上面那個問題，"
        "不要只是換句話說。宣稱與限制規則照舊不得放寬。",
        "每一則都要標上四個軸的指紋，值只能從下面挑：\n" + fp.prompt_vocabulary(),
        '輸出格式：只回傳 {"content": "...", "rationale": "...", '
        '"fingerprint": {"angle": "...", "tone": "...", "format": "...", "selling_point": "..."}}',
    ])

    task = gateway.run_task(
        conn, PROVIDER, brand_id=brand_id, task_type="creative_rewrite",
        prompt_template_id="creative_rewrite", prompt_template_version="v1",
        system=_SYSTEM, messages=[{"role": "user", "content": user_text}],
        context=gateway.TaskContext(
            context_scope={"brand_id": brand_id,
                           "campaign_cycle_id": variant["campaign_cycle_id"]},
            knowledge_item_ids=knowledge_item_ids, brand_version=brand_version,
        ),
        options=gateway.TaskOptions(max_tokens=4000),
    )
    if task["status"] != "succeeded":
        return False, task["error"] or REWRITE_FAIL_MESSAGE

    data = gateway.parse_json_reply(task["rendered_output"])
    if not isinstance(data, dict) or not isinstance(data.get("content"), str) \
            or not data["content"].strip():
        return False, REWRITE_FAIL_MESSAGE

    new_variant_id = new_id("cvr")
    conn.execute(
        "INSERT INTO creative_variant (id, org_id, variant_type, creative_brief_id, campaign_cycle_id,"
        " experiment_cell_id, brand_id, product_id, attributes_json, fingerprint_json,"
        " rationale, recommendation_rank, status, created_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'DRAFT', %s)",
        (new_variant_id, org_id, variant["variant_type"], variant["creative_brief_id"],
         variant["campaign_cycle_id"], variant["experiment_cell_id"], brand_id,
         variant["product_id"],
         jsonb({"content": data["content"].strip(),
                "rewritten_from": variant_id,
                # 改寫沿用原本那則的角度／出鏡／切法／原話出處——這是同一個創意位置的
                # 換稿，不是重新選角度（票 7：矩陣選角只在整批生成時做一次）。
                "creative_angle_number": variant["creative_angle_number"],
                "on_camera": variant["on_camera"],
                "cut_type": variant["cut_type"],
                "quote_source": variant["quote_source"],
                "customer_voice_available": variant["customer_voice_available"]}),
         jsonb(fp.normalize(data.get("fingerprint"))),
         (data.get("rationale") or "").strip() if isinstance(data.get("rationale"), str) else "",
         variant["recommendation_rank"], now_utc()),
    )
    conn.commit()
    return True, new_variant_id


def approve_selection(conn, brand_id: str, cycle_id: str, actor: str, *, commit: bool = True) -> int:
    """關卡二：把還沒被退掉的素材一次記為採用（反對制）。回傳採用則數。

    反對制的意思就在這裡——使用者什麼都不點也能過關，系統採用的是「他沒有反對的」。

    票 02-repoint-creative-readers：主題化之後，「採用」這個動作已經在專屬的採用主題
    畫面完成（theme_repository.adopt_theme()，見 app/ads/routes_creative_theme.py 的
    /adopt 路由）——`list_variants()` 本來就只回傳已採用主題底下的元件（D4），能走到這裡
    代表對應的主題早就採用過了。主題模型也沒有「單一元件標記已採用」這個顆粒度（AC3：
    不提供逐欄位勾選採用），所以這裡不再重複寫一筆一模一樣的決策紀錄（否則『交付確認』
    因補件被呼叫兩次，就會多出兩筆內容相同的採用紀錄）。反對制在這一關真正剩下的事，
    是把「使用者沒有手動退掉的則數」算出來、留一筆稽核紀錄，供呼叫端（delivery.confirm）
    判斷「有沒有東西可以交付」——沒有東西時回 0，跟舊行為一致。
    """
    adopted = len([v for v in list_variants(conn, brand_id, cycle_id) if not v["rejected"]])

    org_id = bi.get_brand(conn, brand_id)["org_id"]
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="campaign_cycle", entity_id=cycle_id,
                action="approve_creatives", actor=actor, before=None,
                after={"adopted": adopted})
    if commit:
        conn.commit()
    return adopted
