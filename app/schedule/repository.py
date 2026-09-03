"""app/schedule/repository.py — private DB access for the brand-coordinate vocabulary and
the creative-loop tables (ticket T1b, ADR 0050). Private to app/schedule (container contract
§1): only app/schedule/routes.py imports this; nothing outside app/schedule ever does.

Five tables (supabase/migrations/20260901000002_schedule_creative_coordinates.sql):
    brand_coordinate        — the seven-dimension vocabulary (constitution rule 5), one row
                               per (brand, dimension, key); the 35 angle seeds are
                               transcribed from app/methodology/creative-matrix.md and never
                               change key once minted (T5 groups performance by it).
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


def ensure_coordinates_seeded(conn: _AnyConn, org_id: str, brand_id: str) -> None:
    """讀座標之前先確認種子已經下過——只在這個品牌一列 `dimension='angle'` 都沒有時才寫，
    讀第二次不會多寫 35 列（票 T1b done-check：讀兩次不是 70 列）。"""
    existing = conn.execute(
        "SELECT 1 FROM brand_coordinate WHERE brand_id = %s AND dimension = 'angle' LIMIT 1",
        (brand_id,),
    ).fetchone()
    if existing is not None:
        return
    for key, category, label, situation, lever, person_on_camera, funnel_stage in _SEED_ANGLES:
        conn.execute(
            "INSERT INTO brand_coordinate (id, org_id, brand_id, dimension, key, label,"
            " category, attributes_json) VALUES (%s, %s, %s, 'angle', %s, %s, %s, %s)"
            " ON CONFLICT (brand_id, dimension, key) DO NOTHING",
            (new_id("crd"), org_id, brand_id, key, label, category,
             jsonb({"situation": situation, "lever": lever,
                    "person_on_camera": person_on_camera, "funnel_stage": funnel_stage})),
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


def _find_or_create_slot(conn: _AnyConn, org_id: str, brand_id: str, ad_node_name: str,
                          source_tree_task_id: str | None) -> str:
    row = conn.execute(
        "SELECT id FROM creative_slot WHERE org_id = %s AND brand_id = %s"
        " AND ad_node_name = %s AND source_tree_task_id IS NOT DISTINCT FROM %s",
        (org_id, brand_id, ad_node_name, source_tree_task_id),
    ).fetchone()
    if row is not None:
        return row["id"]
    slot_id = new_id("csl")
    conn.execute(
        "INSERT INTO creative_slot (id, org_id, brand_id, ad_node_name,"
        " source_tree_task_id, status) VALUES (%s, %s, %s, %s, %s, 'open')",
        (slot_id, org_id, brand_id, ad_node_name, source_tree_task_id),
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
        slot_id = _find_or_create_slot(conn, org_id, brand_id, ad["node"], source_tree_task_id)
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
    （`_run_bind`）呼叫這支，讀樹的疊圖永遠不建這一列。"""
    conn.execute(
        "INSERT INTO ad_channel (id, org_id, channel_key, label, enabled)"
        " VALUES (%s, %s, 'meta', 'Meta', true) ON CONFLICT (org_id, channel_key) DO NOTHING",
        (new_id("adch"), org_id),
    )
    row = conn.execute(
        "SELECT id FROM ad_channel WHERE org_id = %s AND channel_key = 'meta'", (org_id,),
    ).fetchone()
    assert row is not None  # 上面剛 INSERT／DO NOTHING 過，這一列必然存在
    return row["id"]


def upsert_binding(conn: _AnyConn, *, org_id: str, brand_id: str, channel_id: str,
                    node_key: str, node_name_at_bind: str, external_id: str,
                    external_status: str | None) -> None:
    """綁定一個節點。`ON CONFLICT` 的鍵就是節點的身分 `(org_id, brand_id, channel_id,
    node_key)`——改名之後重綁是覆寫同一列，不是撞唯一鍵（ADR 0055 §2／§4：位置是身分，
    重綁覆寫、不留歷史）。呼叫端批次呼叫，這裡不 commit。"""
    conn.execute(
        "INSERT INTO channel_entity_map (id, org_id, brand_id, channel_id, node_key,"
        " node_name_at_bind, external_id, external_status, external_status_at, local_state)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now(), 'mapped')"
        " ON CONFLICT (org_id, brand_id, channel_id, node_key) DO UPDATE SET"
        " external_id = excluded.external_id,"
        " node_name_at_bind = excluded.node_name_at_bind,"
        " external_status = excluded.external_status,"
        " external_status_at = excluded.external_status_at,"
        " local_state = 'mapped', updated_at = now()",
        (new_id("cem"), org_id, brand_id, channel_id, node_key, node_name_at_bind,
         external_id, external_status),
    )


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
