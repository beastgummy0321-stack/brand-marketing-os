"""app/schedule/repository.py — private DB access for the brand-coordinate vocabulary and
the creative-loop tables (ticket T1b, ADR 0050). Private to app/schedule (container contract
§1): only app/schedule/routes.py imports this; nothing outside app/schedule ever does.

Five tables (supabase/migrations/20260901000002_schedule_creative_coordinates.sql):
    brand_coordinate        — the seven-dimension vocabulary (constitution rule 5), one row
                               per (brand, dimension, key); the 35 angle seeds are
                               transcribed from app/methodology/creative-matrix.md, and the
                               33 seeds across the other six dimensions (ticket T8a) from
                               that ticket's own vocabulary tables — never change key once
                               minted (T5 groups performance by it).
    creative_slot            — one row per ad node × source tree: "what this slot wants now".
    creative_candidate       — the Nth attempt at filling a slot; freezes the seven
                               dimensions AGAIN (constitution rule 7) as *_key columns plus a
                               snapshot, so a later coordinate rename never rewrites what a
                               past ad was tagged as.
    creative_candidate_item  — carousel cards; exactly one row per candidate in v1.
    feedback                 — a rejection, scoped to a coordinate, a candidate, or (T2) a
                               period; `brand_coordinate.disabled_at` is the screen switch,
                               `feedback` is the loop's own judgement (station ① decision 1).

Who seeds a new brand: this module, lazily, on first read of that brand's coordinates
(`ensure_coordinates_seeded`) — not a trigger on `brand`, not a call from
`app.brand_intelligence.repository.create_brand()` (ADR 0049 rule 3: one module never writes
another module's territory). Brands that already existed when this ticket's migration ran
were back-filled by the migration itself, with the same 35 rows.
"""

from app.core import cleanup
from app.core.db import Conn, ConnProxy, jsonb, new_id, now_utc
from app.schedule.creative import COORDINATE_KEYS

_AnyConn = Conn | ConnProxy

# 35 個角度種子，逐字對照 app/methodology/creative-matrix.md:12-46（同一份清單也活在
# supabase/migrations/20260901000002_schedule_creative_coordinates.sql 的 SQL 版本裡，給
# 既有品牌做遷移期一次性回填——SQL migration 叫不到這支 Python 模組，兩邊只能各自一份）。
# 每個 tuple：(key, category, label, situation, lever, person_on_camera, funnel_stage)。
_SEED_ANGLES: tuple = (
    ("scarcity_marketing", "促銷", "稀缺性行銷",
     "真的限量的商品、快閃檔期、周年慶捆綁", "稀缺＋損失厭惡", "否", "末端"),
    ("limited_time_offer", "促銷", "限時福利",
     "真的有時限的優惠、清倉、滿額加贈", "急迫＋損失厭惡", "否", "末端"),
    ("product_explainer", "賣家視角", "產品講解",
     "新品上市、成分或功能需要教育市場", "具體性降低不確定感", "否", "後段"),
    ("product_evolution", "賣家視角", "產品進化論",
     "有真實迭代歷程、想展現「有在聽顧客」", "IKEA 效應＋互惠", "可", "中段"),
    ("user_survey_interaction", "賣家視角", "用戶調查互動",
     "決定下一批品項或版本時（限有可迭代的商品或服務規格：口味、包裝、功能版本等）",
     "承諾一致性＋IKEA 效應", "可", "中段"),
    ("self_deprecating_rebuttal", "賣家視角", "自黑／回應質疑",
     "有真實負評或常見疑慮，願意公開拆解", "疵點效應", "是", "後段"),
    ("benefit_explainer", "買家視角", "功能收益講解",
     "有真實使用者願意現身說具體改善", "框架效應", "是", "後段"),
    ("pairing_recommendation", "買家視角", "搭配推薦展示",
     "想拓展使用情境、延伸單次消費金額（限有商品或服務組合可搭售時）", "可得性捷思", "可", "中段"),
    ("daily_use_sharing", "買家視角", "日常應用分享",
     "想提高「每天都會用到」的實用感", "可得性捷思", "可", "中段"),
    ("user_case_story", "買家視角", "用戶案例故事",
     "有真實顧客願意分享完整故事", "社會證明", "是", "末端"),
    ("empathy_driven", "感性", "共情驅動",
     "送禮情境、家庭關係、情感訴求", "情感喚起", "可", "前段"),
    ("identity_affiliation", "感性", "身分認同",
     "想精準鎖定特定族群（上班族、新手媽媽）", "統一原則", "可", "前段"),
    ("price_reversal", "感性", "價格反轉",
     "實際單價遠低於顧客第一印象", "錨定＋對比", "否", "前段"),
    ("social_flex", "感性", "社交炫耀",
     "外型或話題性夠強、容易被朋友問", "社會證明＋模仿慾望", "可", "中段"),
    ("values_and_beliefs", "感性", "價值觀理念",
     "品牌有明確理念（環保、極簡、在地）要長期經營", "統一原則", "否", "中段"),
    ("pain_point_barrage", "感性", "痛點轟炸",
     "有一個具體、高頻的痛苦瞬間可聚焦", "損失厭惡＋可得性捷思", "可", "最前段"),
    ("trending_topic_tiein", "感性", "熱點借勢",
     "節慶、時事、季節熱潮明確且在時效內", "從眾＋單純曝光", "可", "前段"),
    ("precision_dissuasion", "反向行銷", "精準勸退",
     "想篩出精準受眾、降低無效點擊", "逆反心理＋自我選擇", "可", "前段"),
    ("expert_endorsement", "權威", "專家背書",
     "有真實醫師／營養師／教練願意背書", "權威效應", "是", "後段"),
    ("credential_showcase", "權威", "資質認證展示",
     "有真實檢驗報告、專利、獎項", "權威效應", "否", "後段"),
    ("data_endorsement", "權威", "數據背書",
     "有真實銷量、好評率、回購率", "社會證明（數字化）", "否", "末端"),
    ("personal_track_record", "權威", "個人經歷背書",
     "有真實長年經驗者（非明星代言）願意現身", "權威＋相似性偏誤", "是", "後段"),
    ("immersive_asmr", "審美治癒", "沉浸式／ASMR",
     "開箱、使用過程本身有明顯聲音質感", "峰值體驗；感官沉浸", "否", "前段"),
    ("mood_cinematic", "審美治癒", "氛圍感大片",
     "想賣一種生活風格而不只是功能", "模仿慾望＋生活方式框架", "可", "中段"),
    ("hardcore_review", "理性", "硬核測評",
     "有可公開驗證的極限實驗或量化數據", "權威＋具體性證據", "可", "後段"),
    ("how_to_tutorial", "理性", "乾貨教程",
     "顧客常用錯方法、需要示範正確用法", "互惠＋權威", "可", "中段"),
    ("competitor_comparison", "理性", "競品對比",
     "有可佐證的功能差異，用畫面對比而非指名貶低", "對比＋錨定", "否", "前段"),
    ("trend_forecast", "理性", "趨勢預測分析",
     "想吸引早期採用者、理念認同者", "稀缺（早期身分）＋權威", "否", "中段"),
    ("deep_teardown", "視覺", "深度拆解",
     "產品結構、用料、工藝是賣點（限有實體商品；純服務或虛擬商品不適用）",
     "好奇缺口＋具體性", "否", "後段"),
    ("factory_traceability", "視覺", "工廠溯源",
     "有真實可拍攝的產地或產線（限有實體製造流程；代工貼牌無產線可拍、或服務型商品不適用）",
     "權威＋信任捷思", "可", "後段"),
    ("ugc_disguise", "Meta 特化", "UGC 偽裝",
     "想降低廣告感、提高自然互動、壓低 CPM", "相似性偏誤＋降低廣告防禦", "是", "前段"),
    ("scroll_stopping_visual", "Meta 特化", "滑動阻斷視覺",
     "Feed 冷開場，要提高第一張圖的停留率", "對比效應（視覺異常即停留）", "否", "最前段"),
    ("category_replacement", "Meta 特化", "品類替換對峙",
     "顧客現有替代方案明確（自己熬湯、喝咖啡）", "對比＋錨定", "可", "前段"),
    ("moment_anchoring", "Meta 特化", "時刻錨定",
     "想把產品綁進顧客一天中的具體時刻", "情境錨定", "可", "中段"),
    ("objection_qa_barrage", "Meta 特化", "疑慮 Q&A 連發",
     "末端猶豫受眾、常見疑慮明確可條列", "損失規避", "可", "末端"),
)

# 票 T8a：另外六個維度共 33 個種子，逐字對照
# docs/issues/t8a-six-dimension-vocabulary/ticket.md 的六張表（hook 那張本身逐字對照
# app/methodology/copywriting.md:35-43，format 那張逐字對照
# app/methodology/meta-format-specs.md:16,34,49）。跟 `_SEED_ANGLES` 一樣，SQL migration 版
# 活在 supabase/migrations/20260904000002_schedule_brand_coordinate_six_dimensions.sql，兩邊
# 手動同步（SQL migration 叫不到這支 Python 模組）。
# 每個維度一個 tuple，裡面每列一個 4-tuple：(key, category, label, situation)——`category`
# 整個維度只有一個值仍逐列重複，跟 `_SEED_ANGLES` 同一種形狀，`ensure_coordinates_seeded`
# 才能用同一套解構寫法。`attributes_json` 只有 `situation`——`lever`／`person_on_camera`／
# `funnel_stage` 是角度專屬欄位，這裡不寫（`CoordinateAttributes` 每個欄位本來就是選填）。
_SEED_COORDINATES: dict = {
    "audience": (
        ("cold_unaware", "漏斗關係", "陌生・不知有問題", "連自己有這個困擾都還沒意識到"),
        ("cold_problem_aware", "漏斗關係", "陌生・知道問題", "知道自己痛，不知道有解法"),
        ("warm_engaged", "漏斗關係", "互動過・沒買", "看過、點過、加過購物車"),
        ("customer_repeat", "漏斗關係", "已購・回購", "買過，這則是要他再買"),
        ("lapsed", "漏斗關係", "流失・喚回", "買過但久沒回來"),
    ),
    "pain": (
        ("cost", "痛苦類型", "太貴", "花太多錢，或覺得不值這個價"),
        ("effort", "痛苦類型", "太麻煩", "花太多時間、步驟太多、要學"),
        ("uncertainty", "痛苦類型", "怕買錯", "不知道有沒有效、不知道適不適合自己"),
        ("availability", "痛苦類型", "買不到", "缺貨、通路不便、取得困難"),
        ("experience", "痛苦類型", "用起來不舒服", "現有方案能用但體驗差"),
        ("identity", "痛苦類型", "不像我", "面子、不符合我想成為的樣子"),
    ),
    "hook": (
        ("pain_question", "標題公式", "痛點提問", "還在為{痛點}{受影響的行為}？"),
        ("outcome_led", "標題公式", "結果導向", "達成{渴望}不必{代價}"),
        ("never_again", "標題公式", "永不再犯", "再也不用{討厭的事}"),
        ("contrast_flip", "標題公式", "反差對比", "你以為是{貴／麻煩}？其實{便宜／簡單}"),
        ("proof_led", "標題公式", "證明導向", "{數字}{人}用{產品}達到{結果}"),
    ),
    "proof": (
        ("customer_review", "證據來源", "顧客評論原話",
         "評論卡、見證疊層、前後對比——原文照搬，不改寫"),
        ("expert_endorsement", "證據來源", "專家背書", "真實醫師／營養師／教練現身"),
        ("lab_report", "證據來源", "檢驗報告／認證", "檢驗數據、專利、獎項"),
        ("sales_numbers", "證據來源", "銷售數據", "銷量、好評率、回購率——絕不捏造"),
        ("media_coverage", "證據來源", "媒體報導", "只能用真的報導過你的媒體"),
        ("founder_voice", "證據來源", "創辦人第一手", "創辦初衷、起源故事——捏造會整個垮掉"),
        ("none", "證據來源", "無證明", "純訴求，這一則不帶任何外部證據"),
    ),
    "offer": (
        ("none", "誘因類型", "無優惠", "只講價值，不給誘因"),
        ("discount", "誘因類型", "折扣特價", "錨定效應、尾數定價"),
        ("bundle", "誘因類型", "組合加贈", "心理帳戶、免費效應"),
        ("free_shipping", "誘因類型", "免運", "免費效應——拉首購比等額折扣有感"),
        ("trial_sample", "誘因類型", "試用體驗", "互惠原則、承諾與一致性"),
        ("guarantee", "誘因類型", "保證退換", "後悔規避"),
        ("limited_time", "誘因類型", "限時限量",
         "稀缺與急迫——只在真的限時限量時用，捏造見禁用手法"),
    ),
    "format": (
        ("single_image", "Meta 版位", "單圖", "4:5，1080×1350（查證日 2026-08-07）"),
        ("carousel", "Meta 版位", "輪播", "多卡，每卡連結由組裝時帶入"),
        ("video", "Meta 版位", "影片", "每主題媒體上限 1（主題＝腳本）"),
    ),
}


def ensure_coordinates_seeded(conn: _AnyConn, org_id: str, brand_id: str) -> None:
    """讀座標之前先確認七個維度的種子都下過——逐維度探測，不是只認 `dimension='angle'`
    （票 T8a：只認 angle 會讓這張票之前就種過的品牌，另外六個維度永遠種不進去）。讀第二次
    不會多寫（探測擋住重複呼叫，`ON CONFLICT (brand_id, dimension, key) DO NOTHING` 兜底，
    票 T8a done-check：讀兩次不是 136〔68×2〕列）。"""
    existing_dims = {
        row["dimension"] for row in conn.execute(
            "SELECT DISTINCT dimension FROM brand_coordinate WHERE brand_id = %s", (brand_id,)
        ).fetchall()
    }
    if "angle" not in existing_dims:
        for key, category, label, situation, lever, person_on_camera, funnel_stage in _SEED_ANGLES:
            conn.execute(
                "INSERT INTO brand_coordinate (id, org_id, brand_id, dimension, key, label,"
                " category, attributes_json) VALUES (%s, %s, %s, 'angle', %s, %s, %s, %s)"
                " ON CONFLICT (brand_id, dimension, key) DO NOTHING",
                (new_id("crd"), org_id, brand_id, key, label, category,
                 jsonb({"situation": situation, "lever": lever,
                        "person_on_camera": person_on_camera, "funnel_stage": funnel_stage})),
            )
    for dimension, rows in _SEED_COORDINATES.items():
        if dimension in existing_dims:
            continue
        for key, category, label, situation in rows:
            conn.execute(
                "INSERT INTO brand_coordinate (id, org_id, brand_id, dimension, key, label,"
                " category, attributes_json) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (brand_id, dimension, key) DO NOTHING",
                (new_id("crd"), org_id, brand_id, dimension, key, label, category,
                 jsonb({"situation": situation})),
            )
    conn.commit()


def _coordinate_view(row: dict) -> dict:
    return {
        "id": row["id"], "dimension": row["dimension"], "key": row["key"],
        "label": row["label"], "category": row["category"],
        "canonical_key": row["canonical_key"], "attributes": row["attributes_json"] or {},
        "disabled_at": row["disabled_at"], "rejected": bool(row["rejected"]),
    }


_REJECTED_SUBQUERY = (
    "EXISTS (SELECT 1 FROM feedback f WHERE f.scope = 'coordinate'"
    " AND f.coordinate_id = c.id AND f.lifted_at IS NULL) AS rejected"
)


def list_coordinates(conn: _AnyConn, org_id: str, brand_id: str) -> list[dict]:
    ensure_coordinates_seeded(conn, org_id, brand_id)
    rows = conn.execute(
        f"SELECT c.*, {_REJECTED_SUBQUERY} FROM brand_coordinate c"
        " WHERE c.org_id = %s AND c.brand_id = %s"
        " ORDER BY c.dimension, c.category NULLS LAST, c.label",
        (org_id, brand_id),
    ).fetchall()
    return [_coordinate_view(dict(r)) for r in rows]


def get_coordinate(conn: _AnyConn, org_id: str, brand_id: str, coordinate_id: str) -> dict | None:
    row = conn.execute(
        f"SELECT c.*, {_REJECTED_SUBQUERY} FROM brand_coordinate c"
        " WHERE c.org_id = %s AND c.brand_id = %s AND c.id = %s",
        (org_id, brand_id, coordinate_id),
    ).fetchone()
    return _coordinate_view(dict(row)) if row is not None else None


def create_coordinate(conn: _AnyConn, org_id: str, brand_id: str, dimension: str, label: str,
                       category: str | None) -> dict:
    """key 伺服器端現生——使用者自己新增的座標沒有人手轉譯好的英文慣用詞可用，開一個
    不透明 id 當 key 就夠（跟 35 個種子那種「T5 要拿來分組、永不改」的可讀 key 是兩回事，
    ponytail：不做中文轉拼音，真的需要人類可讀 key 時再加）。"""
    coordinate_id = new_id("crd")
    key = new_id("k")
    conn.execute(
        "INSERT INTO brand_coordinate (id, org_id, brand_id, dimension, key, label, category)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (coordinate_id, org_id, brand_id, dimension, key, label, category),
    )
    conn.commit()
    row = get_coordinate(conn, org_id, brand_id, coordinate_id)
    assert row is not None  # 剛寫進去的那一列，找不到代表資料庫壞了，不是正常分支
    return row


def set_coordinate_disabled(conn: _AnyConn, org_id: str, brand_id: str, coordinate_id: str,
                             disabled: bool) -> dict | None:
    conn.execute(
        "UPDATE brand_coordinate SET disabled_at = %s, updated_at = now()"
        " WHERE id = %s AND org_id = %s AND brand_id = %s",
        (now_utc() if disabled else None, coordinate_id, org_id, brand_id),
    )
    conn.commit()
    return get_coordinate(conn, org_id, brand_id, coordinate_id)


# ---- creative loop persistence：票 01 的 build_creative() 撐過外殼之後落地 ---------------

def _resolve_coordinates(conn: _AnyConn, org_id: str, brand_id: str,
                          coordinates: dict) -> tuple[dict, str]:
    """把 `coordinates` 每個維度的字串比對回這個品牌的 `brand_coordinate.label`——比對不到
    就是 `*_key = NULL`，不整批作廢（票 T1b 第 4 節：座標是診斷用中繼資料，一個維度查無此
    字不該讓文案跟著作廢；T1 站③收尾同一條規矩的延伸）。"""
    keys: dict = {}
    unresolved = any_value = False
    for dimension in COORDINATE_KEYS:
        value = coordinates.get(dimension)
        if value is None:
            keys[dimension] = None
            continue
        any_value = True
        row = conn.execute(
            "SELECT key FROM brand_coordinate WHERE org_id = %s AND brand_id = %s"
            " AND dimension = %s AND label = %s",
            (org_id, brand_id, dimension, value),
        ).fetchone()
        if row is None:
            unresolved = True
            keys[dimension] = None
        else:
            keys[dimension] = row["key"]
    status = "tagged" if (any_value and not unresolved) else "pending"
    return keys, status


def _find_or_create_slot(conn: _AnyConn, org_id: str, brand_id: str, node_key: str,
                          source_tree_task_id: str | None) -> str:
    row = conn.execute(
        "SELECT id FROM creative_slot WHERE org_id = %s AND brand_id = %s"
        " AND node_key = %s AND source_tree_task_id IS NOT DISTINCT FROM %s",
        (org_id, brand_id, node_key, source_tree_task_id),
    ).fetchone()
    if row is not None:
        return row["id"]
    slot_id = new_id("csl")
    conn.execute(
        "INSERT INTO creative_slot (id, org_id, brand_id, node_key,"
        " source_tree_task_id, status) VALUES (%s, %s, %s, %s, %s, 'open')",
        (slot_id, org_id, brand_id, node_key, source_tree_task_id),
    )
    return slot_id


def persist_creative_result(conn: _AnyConn, org_id: str, brand_id: str, task_id: str,
                             source_tree_task_id: str | None, ads: list) -> None:
    """票 01 的 `schedule_creative` 任務成功之後，把每個廣告節點的內容落地成
    `creative_slot` + `creative_candidate` + `creative_candidate_item`——冪等，靠
    `llm_task_id` 判斷這個任務是不是已經落過地，讀第二次不會多寫一份（呼叫端：
    `routes._brand_response()`，每次 GET 成功的 creative 都會呼叫一次，跟 35 個座標種子
    同一套「讀的時候順手確保落地」寫法）。v1 一格一個候選：`generation_round` 取這個
    slot 目前最大值 +1，不是寫死 1——同一個 slot 之後真的重跑（draw-again，非本票範圍）
    不會撞 `UNIQUE(slot_id, generation_round)`。"""
    already = conn.execute(
        "SELECT 1 FROM creative_candidate WHERE llm_task_id = %s LIMIT 1", (task_id,)
    ).fetchone()
    if already is not None:
        return
    # 座標比對要靠這個品牌的 brand_coordinate 已經有種子——使用者不見得先開過「創意座標」
    # 分頁，落地前自己確保一次（跟 list_coordinates() 同一支冪等函式，讀第二次不動作）。
    ensure_coordinates_seeded(conn, org_id, brand_id)
    for ad in ads:
        slot_id = _find_or_create_slot(conn, org_id, brand_id, ad["node_key"], source_tree_task_id)
        round_row = conn.execute(
            "SELECT COALESCE(MAX(generation_round), 0) + 1 AS n FROM creative_candidate"
            " WHERE slot_id = %s", (slot_id,),
        ).fetchone()
        generation_round = round_row["n"] if round_row is not None else 1
        keys, status = _resolve_coordinates(conn, org_id, brand_id, ad["coordinates"])
        candidate_id = new_id("cca")
        conn.execute(
            "INSERT INTO creative_candidate (id, org_id, brand_id, slot_id, generation_round,"
            " audience_key, pain_key, angle_key, hook_key, proof_key, offer_key, format_key,"
            " coordinates_snapshot_json, coordinates_status, visual_tone, visual_concept,"
            " llm_task_id)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (candidate_id, org_id, brand_id, slot_id, generation_round,
             keys["audience"], keys["pain"], keys["angle"], keys["hook"], keys["proof"],
             keys["offer"], keys["format"], jsonb(ad["coordinates"]), status,
             ad["visual_tone"], ad["visual_concept"], task_id),
        )
        conn.execute(
            "INSERT INTO creative_candidate_item (id, org_id, brand_id, candidate_id,"
            " position, fields_json) VALUES (%s, %s, %s, %s, 1, %s)",
            (new_id("cci"), org_id, brand_id, candidate_id, jsonb(ad["fields"])),
        )
        conn.execute(
            "UPDATE creative_slot SET status = 'filled', updated_at = now() WHERE id = %s",
            (slot_id,),
        )
    conn.commit()


# ---- feedback：一條意見（票 01 station ① decision 1）------------------------------------
# 這一版沒有路由呼叫這兩支——挑選器（跳過被拒絕的座標／候選）是之後的票，這裡先把落地的
# 地方蓋好（ADR 0050「doors that are not tables」同一套精神：欄位／函式先在，開關留給
# 之後）。

def create_feedback(conn: _AnyConn, org_id: str, brand_id: str, *, scope: str,
                     coordinate_id: str | None, candidate_id: str | None,
                     reason_code: str, note: str | None, created_by: str | None) -> dict:
    feedback_id = new_id("fbk")
    conn.execute(
        "INSERT INTO feedback (id, org_id, brand_id, scope, coordinate_id, candidate_id,"
        " reason_code, note, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (feedback_id, org_id, brand_id, scope, coordinate_id, candidate_id, reason_code,
         note, created_by),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM feedback WHERE id = %s", (feedback_id,)).fetchone()
    assert row is not None  # 剛寫進去的那一列，找不到代表資料庫壞了，不是正常分支
    return dict(row)


def lift_feedback(conn: _AnyConn, org_id: str, brand_id: str, feedback_id: str) -> None:
    conn.execute(
        "UPDATE feedback SET lifted_at = now() WHERE id = %s AND org_id = %s AND brand_id = %s",
        (feedback_id, org_id, brand_id),
    )
    conn.commit()


# ---- campaign_period（票 T2b，ADR 0053）--------------------------------------------------
# 誕生在表單、結算靠手動：草稿（status='planning'）一個品牌最多一列，出方案第二次以後
# 改的是同一列的日期／預算（決策 1）；結算的算法（哪天算誰的、算多少錢）留在 routes.py，
# 這裡只管落地。

def upsert_draft_period(conn: _AnyConn, org_id: str, brand_id: str, *, name: str,
                         start_date, end_date, daily_budget: float, currency: str) -> str:
    """按 `出方案` 一次：這個品牌還有草稿就改日期／預算，沒有就新開一列——三次按下去
    不留三個檔期（ADR 0053 決策 1）。"""
    updated = conn.execute(
        "UPDATE campaign_period SET name = %s, start_date = %s, end_date = %s,"
        " daily_budget = %s, currency = %s, updated_at = now()"
        " WHERE org_id = %s AND brand_id = %s AND status = 'planning' RETURNING id",
        (name, start_date, end_date, daily_budget, currency, org_id, brand_id),
    ).fetchone()
    if updated is not None:
        conn.commit()
        return updated["id"]
    period_id = new_id("cpd")
    conn.execute(
        "INSERT INTO campaign_period (id, org_id, brand_id, name, start_date, end_date,"
        " daily_budget, currency) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (period_id, org_id, brand_id, name, start_date, end_date, daily_budget, currency),
    )
    conn.commit()
    return period_id


def get_latest_period(conn: _AnyConn, org_id: str, brand_id: str) -> dict | None:
    """畫面目前顯示的那一個——「最新一列是真相」，跟 `routes._latest_task_row()` 同一個
    既有慣例（ADR 0053 consequences 段：這條慣例的收斂留給 T5，T2b 不先改）。"""
    row = conn.execute(
        "SELECT * FROM campaign_period WHERE org_id = %s AND brand_id = %s"
        " ORDER BY created_at DESC LIMIT 1",
        (org_id, brand_id),
    ).fetchone()
    return dict(row) if row is not None else None


def get_period(conn: _AnyConn, org_id: str, brand_id: str, period_id: str) -> dict | None:
    """結算端點專用：`org_id`／`brand_id` 都在 WHERE 裡——`period_id` 是呼叫端（使用者）
    給的，不能只信任主鍵比對，另一個組織的檔期 id 必須查不到（租戶界線）。"""
    row = conn.execute(
        "SELECT * FROM campaign_period WHERE id = %s AND org_id = %s AND brand_id = %s",
        (period_id, org_id, brand_id),
    ).fetchone()
    return dict(row) if row is not None else None


def list_non_draft_periods(conn: _AnyConn, org_id: str, brand_id: str) -> list[dict]:
    """ADR 0053 決策 4：日子的擁有權只看「結算當下存在」的非草稿檔期——草稿從沒被使用者
    核准過，不佔任何一天。"""
    rows = conn.execute(
        "SELECT * FROM campaign_period WHERE org_id = %s AND brand_id = %s"
        " AND status != 'planning'",
        (org_id, brand_id),
    ).fetchall()
    return [dict(r) for r in rows]


def approve_draft_period(conn: _AnyConn, org_id: str, brand_id: str) -> None:
    """ADR 0053 決策 1：核准活動樹的那一press＝「這期真的要投」，草稿在這裡變 running。
    找不到草稿就什麼都不做——這個品牌上一次的草稿可能已經被核准過了，這次核准只是
    撤回又核准同一棵樹。"""
    conn.execute(
        "UPDATE campaign_period SET status = 'running', updated_at = now()"
        " WHERE org_id = %s AND brand_id = %s AND status = 'planning'",
        (org_id, brand_id),
    )
    conn.commit()


def advance_period_to_awaiting_data(conn: _AnyConn, org_id: str, period_id: str) -> None:
    """ADR 0053 決策 2：`running` 過了 `end_date` 自動變 `awaiting_data`——讀的時候順手算，
    不是背景工作；一次 UPDATE，冪等（讀第二次不會出事，WHERE 沒有狀態條件單純是覆寫同一個
    值）。"""
    conn.execute(
        "UPDATE campaign_period SET status = 'awaiting_data', updated_at = now()"
        " WHERE id = %s AND org_id = %s",
        (period_id, org_id),
    )
    conn.commit()


def write_settlement(conn: _AnyConn, *, org_id: str, period_id: str, spend: float,
                      revenue: float, settled_at, force_early: bool) -> None:
    """落地一次結算（或重新結算）的快照——呼叫端負責在重新結算時先把舊的三個數字寫進
    audit_log（ADR 0053 §3：快照可以被換掉，不能悄悄換掉）。`status` 一律變成 `settled`
    （ADR 0053 consequences：四態機的最後一態），`force_settled_*` 只在提早結算時才寫。"""
    if force_early:
        conn.execute(
            "UPDATE campaign_period SET status = 'settled', settled_spend = %s,"
            " settled_revenue = %s, settled_at = %s, version = version + 1,"
            " force_settled_at = %s, force_settled_reason = 'early', updated_at = now()"
            " WHERE id = %s AND org_id = %s",
            (spend, revenue, settled_at, settled_at, period_id, org_id),
        )
    else:
        conn.execute(
            "UPDATE campaign_period SET status = 'settled', settled_spend = %s,"
            " settled_revenue = %s, settled_at = %s, version = version + 1, updated_at = now()"
            " WHERE id = %s AND org_id = %s",
            (spend, revenue, settled_at, period_id, org_id),
        )
    conn.commit()


# ---- 票 T3b（ADR 0055）：節點綁定，channel_entity_map ------------------------------------

def bindings_by_node_key(conn: _AnyConn, org_id: str, brand_id: str, channel_key: str) -> dict:
    """這個品牌在這個通路上，`node_key → {external_id, node_name_at_bind}`（只挑
    `local_state = 'mapped'` 的列——`binding.tree_with_bindings()` 疊圖用）。跟
    `ad_channel` JOIN 是為了用 `channel_key`（'meta'）而不是內部 id 篩——沒有那一列，
    JOIN 自然是空集合，讀從不建它（ADR 0055 §4／§5：讀永遠不寫）。"""
    rows = conn.execute(
        "SELECT cem.node_key, cem.external_id, cem.node_name_at_bind"
        " FROM channel_entity_map cem JOIN ad_channel ch"
        " ON ch.id = cem.channel_id AND ch.org_id = cem.org_id"
        " WHERE cem.org_id = %s AND cem.brand_id = %s AND ch.channel_key = %s"
        " AND cem.local_state = 'mapped'",
        (org_id, brand_id, channel_key),
    ).fetchall()
    return {r["node_key"]: dict(r) for r in rows}


def ensure_meta_channel(conn: _AnyConn, org_id: str) -> str:
    """這個組織的 'meta' `ad_channel` id，第一次用時現生（ADR 0055 §5）——只有寫入路徑
    （`_run_bind`）呼叫這支，讀樹的疊圖永遠不建這一列。

    票 T4／ADR 0056 §1：`ad_channel` 不再有 `label`——顯示名稱一律從
    `channel_catalogue.json` 用 `channel_key` 查，不存進這張表。"""
    conn.execute(
        "INSERT INTO ad_channel (id, org_id, channel_key, enabled)"
        " VALUES (%s, %s, 'meta', true) ON CONFLICT (org_id, channel_key) DO NOTHING",
        (new_id("adch"), org_id),
    )
    row = conn.execute(
        "SELECT id FROM ad_channel WHERE org_id = %s AND channel_key = 'meta'", (org_id,),
    ).fetchone()
    assert row is not None  # 上面剛 INSERT／DO NOTHING 過，這一列必然存在
    return row["id"]


def upsert_binding(conn: _AnyConn, *, org_id: str, brand_id: str, channel_id: str,
                    node_key: str, node_name_at_bind: str, external_id: str,
                    external_status: str | None, source_tree_task_id: str | None) -> None:
    """綁定一個節點。`ON CONFLICT` 的鍵就是節點的身分 `(org_id, brand_id, channel_id,
    node_key)`——改名之後重綁是覆寫同一列，不是撞唯一鍵（ADR 0055 §2／§4：位置是身分，
    重綁覆寫、不留歷史）。呼叫端批次呼叫，這裡不 commit。

    `source_tree_task_id`（票 T5，ADR 0057 §2）：這次 `bind_tree()` 執行當下那一列
    `schedule_tree` 的 id，三個深度都傳同一個值——**這一欄長在列上，不是只長在某個
    深度**，`binding.py` 三段迴圈共用同一個 `tree_row["id"]`。只有深度 3 的值真的有讀者
    （T5 拿它去找回綁定當下那棵樹的 `creative_slot`），深度 1／2 目前沒有創意、也永遠不
    會有（migration 註解原話），但欄位不分深度特例，函式簽章也不分。重綁覆寫整列時這一
    欄跟著被覆寫，不留歷史（ADR 0055 §4 既有規則，這裡沒有另開一條）。"""
    conn.execute(
        "INSERT INTO channel_entity_map (id, org_id, brand_id, channel_id, node_key,"
        " node_name_at_bind, external_id, external_status, external_status_at, local_state,"
        " source_tree_task_id)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now(), 'mapped', %s)"
        " ON CONFLICT (org_id, brand_id, channel_id, node_key) DO UPDATE SET"
        " external_id = excluded.external_id,"
        " node_name_at_bind = excluded.node_name_at_bind,"
        " external_status = excluded.external_status,"
        " external_status_at = excluded.external_status_at,"
        " local_state = 'mapped', source_tree_task_id = excluded.source_tree_task_id,"
        " updated_at = now()",
        (new_id("cem"), org_id, brand_id, channel_id, node_key, node_name_at_bind,
         external_id, external_status, source_tree_task_id),
    )


def depth_three_bindings(conn: _AnyConn, org_id: str, brand_id: str, channel_key: str) -> dict:
    """票 T5（ADR 0057 §1／§2）：這個品牌在這個通路上，深度 3（廣告）的
    `node_key → {external_id, node_name_at_bind, source_tree_task_id}`——`bindings_by_node_key`
    的深度 3 切片，多帶 `source_tree_task_id`（那支只給 `binding.tree_with_bindings()` 疊圖
    用，不需要這一欄；T5 要用它找回綁定當下那棵樹，凍結列表的鍵，見 ADR 0057 §2：絕不能
    用「現在最新的樹」代替）。同樣只挑 `local_state = 'mapped'`，讀從不寫。"""
    rows = conn.execute(
        "SELECT cem.node_key, cem.external_id, cem.node_name_at_bind, cem.source_tree_task_id"
        " FROM channel_entity_map cem JOIN ad_channel ch"
        " ON ch.id = cem.channel_id AND ch.org_id = cem.org_id"
        " WHERE cem.org_id = %s AND cem.brand_id = %s AND ch.channel_key = %s"
        " AND cem.local_state = 'mapped' AND cem.depth = 3",
        (org_id, brand_id, channel_key),
    ).fetchall()
    return {r["node_key"]: dict(r) for r in rows}


def creative_candidates_for_brand(conn: _AnyConn, org_id: str, brand_id: str) -> dict:
    """票 T5（ADR 0057 §1／§2）：這個品牌每個 `(node_key, source_tree_task_id)` 位置最新一輪
    候選的七個 `*_key` 欄位——「最新」是同一個 slot 裡最大的 `generation_round`（**絕不是
    「最新的樹」**——那是另一個軸，slot 本身已經凍住是哪棵樹，ADR 0057 §2 的核心規則）。
    `DISTINCT ON` 一次撈完整個品牌，`app/schedule/performance.py` 拿它當查表用，不逐一 ad
    各查一次（ADR 0057 §1：join 在 Python 做，不是逐列打 DB）。"""
    rows = conn.execute(
        "SELECT DISTINCT ON (cs.node_key, cs.source_tree_task_id)"
        " cs.node_key, cs.source_tree_task_id, cc.audience_key, cc.pain_key, cc.angle_key,"
        " cc.hook_key, cc.proof_key, cc.offer_key, cc.format_key"
        " FROM creative_slot cs JOIN creative_candidate cc ON cc.slot_id = cs.id"
        " WHERE cs.org_id = %s AND cs.brand_id = %s"
        " ORDER BY cs.node_key, cs.source_tree_task_id, cc.generation_round DESC",
        (org_id, brand_id),
    ).fetchall()
    return {(r["node_key"], r["source_tree_task_id"]): dict(r) for r in rows}


# ---- 票 T3e（ADR 0055 §11）：period_node_membership，深度 2 節點綁定時記一列 -------------

def insert_period_node_membership(conn: _AnyConn, *, org_id: str, brand_id: str,
                                   campaign_period_id: str, channel_id: str, node_key: str,
                                   from_date, to_date, allocation_weight: float = 1.0) -> None:
    """一個深度 2 節點綁定成功、且品牌當下有檔期時記一列（ticket §1）——`from_date`／
    `to_date` 是檔期自己的 `start_date`／`end_date`，記的是「規劃上屬於哪一期」，不是
    「哪幾天真的有花費」。`ON CONFLICT DO NOTHING` 對的是 migration 那條唯一鍵
    `(org_id, brand_id, campaign_period_id, channel_id, node_key)`——同一個節點在同一期
    按第二次綁定鈕不會多寫一列（ticket done-check 3：雙寫在結構上不可能）。呼叫端批次
    呼叫，這裡不 commit（跟 `upsert_binding` 同一個既有慣例）。"""
    conn.execute(
        "INSERT INTO period_node_membership (id, org_id, brand_id, campaign_period_id,"
        " channel_id, node_key, from_date, to_date, allocation_weight)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
        " ON CONFLICT (org_id, brand_id, campaign_period_id, channel_id, node_key) DO NOTHING",
        (new_id("pnm"), org_id, brand_id, campaign_period_id, channel_id, node_key,
         from_date, to_date, allocation_weight),
    )


def period_node_memberships_for_brand(conn: _AnyConn, org_id: str, brand_id: str) -> list[dict]:
    """這個品牌全部的 `period_node_membership`，JOIN 上 `channel_entity_map` 換出
    `entity_id`——ticket §4 講的「這個品牌的 memberships 跟指名它們實體的綁定」：
    membership 本身只存 `node_key`，`period.node_level_spend()` 要拿
    `meta_repo.daily_entity_spend()` 回來的 `entity_id` 去對，兩邊得先接在一起。"""
    rows = conn.execute(
        "SELECT pnm.campaign_period_id, pnm.from_date, pnm.to_date, pnm.allocation_weight,"
        " cem.external_id AS entity_id"
        " FROM period_node_membership pnm JOIN channel_entity_map cem"
        " ON cem.org_id = pnm.org_id AND cem.brand_id = pnm.brand_id"
        " AND cem.channel_id = pnm.channel_id AND cem.node_key = pnm.node_key"
        " WHERE pnm.org_id = %s AND pnm.brand_id = %s",
        (org_id, brand_id),
    ).fetchall()
    return [dict(r) for r in rows]


# ---- 品牌刪除清理登記（app/core/cleanup.py；pattern: app/meta/repository.py:526）---------

_CHILD_TABLES = (
    ("feedback", "回饋"),
    # creative_candidate_item 也會被 creative_candidate 的 ON DELETE CASCADE 帶走，這裡仍
    # 明寫一次 DELETE（先於 candidate），跟其餘子表統一走同一套清理路徑、同一套清點方式。
    ("creative_candidate_item", "廣告內容候選欄位"),
    ("creative_candidate", "廣告內容候選"),
    ("creative_slot", "廣告節點欄位"),
    ("brand_coordinate", "品牌創意座標"),
)


def _count_brand(conn: _AnyConn, brand_id: str) -> list:
    counts = []
    for table, label in _CHILD_TABLES:
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE brand_id = %s", (brand_id,)
        ).fetchone()
        counts.append((label, row["n"] if row is not None else 0))
    return counts


def _delete_brand(conn: _AnyConn, brand_id: str) -> dict:
    counts = dict(_count_brand(conn, brand_id))
    for table, _label in _CHILD_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE brand_id = %s", (brand_id,))
    return counts


cleanup.register(
    "創意座標與素材候選",
    count_brand=_count_brand,
    delete_brand=_delete_brand,
    brand_tables=frozenset({
        "brand_coordinate", "creative_slot", "creative_candidate",
        "creative_candidate_item", "feedback",
    }),
    count_product=None,
    delete_product=None,
    product_tables=frozenset(),
)
