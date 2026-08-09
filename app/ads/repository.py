# -*- coding: utf-8 -*-
"""app/ads/repository.py — 廣告模組存取層。

硬性規則（比照 brand_intelligence/repository.py）：
1. 所有查詢一律以 brand_id 過濾，沒有「查全部品牌」的無過濾入口。
2. 每次異動寫一筆 audit_log（含 before/after 與 actor）。
3. **不直接讀寫品牌智庫的資料表**——需要產品事實或單位經濟時，一律呼叫
   `brand_intelligence.repository` 的函式（鐵則 7：模組間走明確介面，不偷讀彼此內部資料）。
4. append-only 的表（campaign_plan、performance_snapshot）本層不提供 UPDATE／DELETE 入口。

`learning_ledger` 已遷入品牌永久層（修憲落地 A3，決策 0037；docs/architecture-rules.md A1）：
本檔的 `*_learning_ledger*` 系列函式只是薄封裝，實際存取都轉呼叫
`app.brand_intelligence.repository` 的公開函式，固定帶 `source_track="ads"`
（本模組是目前唯一的分支代號）。呼叫端介面刻意保持不變，不強迫既有呼叫者改寫。
"""

import json
import sqlite3
from datetime import date, timedelta
from typing import Optional

from app.ads import budget as budget_calc
from app.brand_intelligence import repository as bi
from app.core import cleanup
from app.core.audit import write_audit
from app.core.db import new_id, now_iso


def _rows(cursor) -> list:
    return [dict(r) for r in cursor.fetchall()]


def _row(cursor_row) -> Optional[dict]:
    return dict(cursor_row) if cursor_row is not None else None


# ---------------------------------------------------------------------------
# 開期前的體檢（Fact Audit）：只提示、不擋路（決策 0013、roadmap 硬性原則 5）
# ---------------------------------------------------------------------------

def check_readiness(conn: sqlite3.Connection, brand_id: str, product_ids: list) -> list:
    """回傳「資料缺這些，精準度會打折」的人話提示，每則附一鍵去補的連結。

    刻意不回傳「可否開期」的布林值——沒有任何一項缺漏能擋住開期。
    """
    notes = []

    confirmed_facts = [f for f in bi.list_brand_facts(conn, brand_id)
                       if f.get("status") == "confirmed"]
    if not confirmed_facts:
        notes.append({
            "code": "no_brand_facts",
            "message": "這個品牌還沒有已確認的品牌事實，AI 只能靠品牌名稱猜，內容會比較空泛。",
            "action_label": "去補品牌事實",
            "action_url": f"/brands/{brand_id}/hub/facts",
        })

    missing_economics = []
    for product_id in product_ids:
        product = bi.get_product(conn, brand_id, product_id)
        if product is None:
            continue
        if budget_calc.gross_margin(bi.get_product_economics(conn, brand_id, product_id)) is None:
            missing_economics.append(product)
    if missing_economics:
        names = "、".join(p["name"] for p in missing_economics)
        notes.append({
            "code": "missing_economics",
            "message": (f"「{names}」還沒有可用的成本售價，預算只能平均分配，"
                        "分完不一定符合各產品的實際賺頭。"),
            "action_label": "去填成本售價",
            "action_url": f"/brands/{brand_id}/hub/products",
        })

    for product_id in product_ids:
        product = bi.get_product(conn, brand_id, product_id)
        if product is None:
            continue
        facts = bi.list_product_facts(conn, brand_id, product_id)
        if not [f for f in facts if f.get("status") == "confirmed"]:
            notes.append({
                "code": "product_not_researched",
                "message": (f"「{product['name']}」還沒有已確認的產品事實，"
                            "這期針對它產出的內容精準度會打折。"),
                "action_label": "去深入調研",
                "action_url": f"/brands/{brand_id}/products/{product_id}",
            })
    return notes


# ---------------------------------------------------------------------------
# 廣告檔期
# ---------------------------------------------------------------------------

def _economics_for(conn: sqlite3.Connection, brand_id: str, product_ids: list) -> list:
    """組 split_budget 要的輸入，經品牌智庫的公開介面取單位經濟。"""
    return [{"product_id": pid,
             "economics": bi.get_product_economics(conn, brand_id, pid)}
            for pid in product_ids]


def create_cycle(conn: sqlite3.Connection, brand_id: str, *, product_ids: list,
                 pain_value: float, objective: str, actor: str,
                 phase: str = "normal", start_date: Optional[str] = None,
                 duration_days: Optional[int] = None, background: Optional[str] = None,
                 currency: str = "TWD") -> dict:
    """開一期廣告檔期，同時寫好各產品的預算分配。

    預算、期長、停損全部由 app/ads/budget.py 的純函數算（決策 0016 硬性原則 4：
    數字走程式）；本函式只負責把算出來的結果落地。

    duration_days 省略時採系統建議值（`plan_from_pain` 依金額反推）；使用者在開期表單
    自訂天數（票 3，7–30 天）時傳入，日預算改用單純除法（budget_calc.daily_budget_for）
    重算——天數已經是人選的，程式不再自作主張改動它。
    """
    if not objective or not objective.strip():
        raise ValueError("本期目標為必填")
    if not actor:
        raise ValueError("actor 為必填")

    from app.ads import plan as ads_plan  # 延遲匯入避免循環匯入（plan.py 已匯入本模組）
    funnel_stage = ads_plan.derive_funnel_stage(objective.strip())

    plan = budget_calc.plan_from_pain(pain_value)
    if duration_days:
        daily, below_floor = budget_calc.daily_budget_for(pain_value, duration_days)
        plan = budget_calc.CyclePlan(
            total_budget=plan.total_budget, duration_days=duration_days, daily_budget=daily,
            daily_stop_loss=round(daily * budget_calc.DAILY_STOP_LOSS_MULTIPLIER, 2),
            pause_threshold_spend=plan.pause_threshold_spend, daily_below_floor=below_floor,
        )
    start = date.fromisoformat(start_date) if start_date else date.today()
    end = start + timedelta(days=plan.duration_days - 1)

    cycle_id = new_id("ccy")
    ts = now_iso()
    row = {
        "id": cycle_id,
        "brand_id": brand_id,
        "ad_account_id": None,
        "product_scope_json": json.dumps(product_ids, ensure_ascii=False),
        "objective": objective.strip(),
        "funnel_stage": funnel_stage,
        "budget": plan.total_budget,
        "currency": currency,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "target_market": None,
        "channels_json": json.dumps(["meta"], ensure_ascii=False),
        "placements_json": None,
        "offer_id": None,
        "landing_page": None,
        "background": background.strip() if background and background.strip() else None,
        "status": "PLANNING",
        "close_reason": None,
        "blocked": None,
        "needs_information": None,
        "archived": 0,
        "plan_version": 0,
        "phase": phase,
        "pain_slider_value": pain_value,
        "derived_plan_json": json.dumps({
            "duration_days": plan.duration_days,
            "daily_budget": plan.daily_budget,
            "daily_stop_loss": plan.daily_stop_loss,
            "pause_threshold_spend": plan.pause_threshold_spend,
            "daily_below_floor": plan.daily_below_floor,
        }, ensure_ascii=False),
        "diff_snapshot_json": None,
        "created_at": ts,
        "updated_at": ts,
    }
    conn.execute(
        "INSERT INTO campaign_cycle (id, brand_id, ad_account_id, product_scope_json, objective,"
        " funnel_stage, budget, currency, start_date, end_date, target_market, channels_json,"
        " placements_json, offer_id, landing_page, background, status, close_reason, blocked,"
        " needs_information, archived, plan_version, phase, pain_slider_value, derived_plan_json,"
        " diff_snapshot_json, created_at, updated_at)"
        " VALUES (:id, :brand_id, :ad_account_id, :product_scope_json, :objective, :funnel_stage,"
        " :budget, :currency, :start_date, :end_date, :target_market, :channels_json,"
        " :placements_json, :offer_id, :landing_page, :background, :status, :close_reason, :blocked,"
        " :needs_information, :archived, :plan_version, :phase, :pain_slider_value,"
        " :derived_plan_json, :diff_snapshot_json, :created_at, :updated_at)",
        row,
    )

    for allocation in budget_calc.split_budget(
        plan.total_budget, _economics_for(conn, brand_id, product_ids)
    ):
        conn.execute(
            "INSERT INTO campaign_cycle_product (id, campaign_cycle_id, brand_id, product_id,"
            " allocated_budget, allocation_ratio, allocation_basis, economics_missing,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id("ccp"), cycle_id, brand_id, allocation.product_id,
             allocation.allocated_budget, allocation.allocation_ratio,
             allocation.allocation_basis, 1 if allocation.economics_missing else 0, ts, ts),
        )

    write_audit(conn, brand_id=brand_id, entity_type="campaign_cycle", entity_id=cycle_id,
                action="create", actor=actor, before=None, after=row)
    conn.commit()

    # 前朝教訓訪談留下、還沒掛進任何檔期的假設，開期當下自動掛進這一期（決策 0030 第 12 點，
    # 票 #55）。查詢本身是空表也不貴，不用額外開關。
    from app.ads import interview as ads_interview
    ads_interview.attach_pending_hypotheses(conn, brand_id, cycle_id)

    # 第一期真的要投的檔期標記為校準期，計畫確認時會先預告「這期大概會是什麼樣」（票 15）
    if phase == "normal":
        from app.ads import onboarding
        if onboarding.mark_calibration_if_first(conn, brand_id, cycle_id):
            row["phase"] = "calibration"
            # 開期當下把校準區間寫死存快照，履行 schema 註解承諾（票 F1，決策 0039 第 14 條）：
            # 對帳一律讀這份快照，不得日後拿當時已經換過的基線重算出不同數字。
            forecast = onboarding.calibration_forecast(conn, brand_id, cycle_id)
            if forecast:
                plan = json.loads(row["derived_plan_json"])
                plan["forecast"] = forecast
                row["derived_plan_json"] = json.dumps(plan, ensure_ascii=False)
                conn.execute(
                    "UPDATE campaign_cycle SET derived_plan_json = ? WHERE id = ?",
                    (row["derived_plan_json"], cycle_id),
                )
                conn.commit()
    return row


def get_cycle(conn: sqlite3.Connection, brand_id: str, cycle_id: str) -> Optional[dict]:
    return _row(conn.execute(
        "SELECT * FROM campaign_cycle WHERE brand_id = ? AND id = ?", (brand_id, cycle_id)
    ).fetchone())


def list_cycles(conn: sqlite3.Connection, brand_id: str, include_archived: bool = False) -> list:
    sql = "SELECT * FROM campaign_cycle WHERE brand_id = ?"
    if not include_archived:
        sql += " AND archived = 0"
    sql += " ORDER BY start_date DESC, id DESC"
    return _rows(conn.execute(sql, (brand_id,)))


def has_any_cycle(conn: sqlite3.Connection, brand_id: str) -> bool:
    """這個品牌跑過任何一期沒有？決定要不要提供紙上模擬入口（決策 0022 第 14 點）。"""
    return conn.execute(
        "SELECT 1 FROM campaign_cycle WHERE brand_id = ? LIMIT 1", (brand_id,)
    ).fetchone() is not None


def list_cycle_products(conn: sqlite3.Connection, brand_id: str, cycle_id: str) -> list:
    """本期各產品的預算分配，附上產品名稱（名稱經品牌智庫介面取得，不 join 它的表）。"""
    rows = _rows(conn.execute(
        "SELECT * FROM campaign_cycle_product WHERE brand_id = ? AND campaign_cycle_id = ?"
        " ORDER BY allocated_budget DESC, id",
        (brand_id, cycle_id),
    ))
    for row in rows:
        product = bi.get_product(conn, brand_id, row["product_id"])
        row["product_name"] = product["name"] if product else "（產品已刪除）"
    return rows


def update_cycle_status(conn: sqlite3.Connection, brand_id: str, cycle_id: str, *,
                        status: str, actor: str) -> dict:
    before = get_cycle(conn, brand_id, cycle_id)
    if before is None:
        raise ValueError(f"找不到廣告檔期：{cycle_id}")
    conn.execute(
        "UPDATE campaign_cycle SET status = ?, updated_at = ? WHERE brand_id = ? AND id = ?",
        (status, now_iso(), brand_id, cycle_id),
    )
    after = get_cycle(conn, brand_id, cycle_id)
    write_audit(conn, brand_id=brand_id, entity_type="campaign_cycle", entity_id=cycle_id,
                action="update_status", actor=actor, before=before, after=after)
    conn.commit()
    return after


def derived_plan(cycle: dict) -> dict:
    """把 derived_plan_json 解回 dict（介面每頁都要用，集中在這裡解一次）。"""
    raw = cycle.get("derived_plan_json")
    return json.loads(raw) if raw else {}


def list_archived_cycles(conn: sqlite3.Connection, brand_id: str) -> list:
    """已封存的檔期清單（廣告首頁「顯示已封存」收合區塊用）。"""
    return _rows(conn.execute(
        "SELECT * FROM campaign_cycle WHERE brand_id = ? AND archived = 1"
        " ORDER BY start_date DESC, id DESC", (brand_id,)
    ))


def set_cycle_archived(conn: sqlite3.Connection, brand_id: str, cycle_id: str, *,
                       archived: bool, actor: str) -> dict:
    """封存／恢復檔期（GitHub issue #28：任何狀態——PLANNING、LIVE、CLOSED……——都能封存，
    封存與工作流狀態互不影響）。"""
    if not actor or not actor.strip():
        raise ValueError("actor 為必填")
    before = get_cycle(conn, brand_id, cycle_id)
    if before is None:
        raise ValueError(f"找不到廣告檔期：{cycle_id}")
    ts = now_iso()
    conn.execute(
        "UPDATE campaign_cycle SET archived = ?, updated_at = ? WHERE brand_id = ? AND id = ?",
        (1 if archived else 0, ts, brand_id, cycle_id),
    )
    after = get_cycle(conn, brand_id, cycle_id)
    write_audit(conn, brand_id=brand_id, entity_type="campaign_cycle", entity_id=cycle_id,
                action="archive" if archived else "restore", actor=actor, before=before, after=after)
    conn.commit()
    return after


# ---------------------------------------------------------------------------
# 真刪除檔期（GitHub issue #28，比照決策 0020 產品先例：先封存、輸入名稱確認、
# 刪除前自動備份）。
# ---------------------------------------------------------------------------

# 刪檔期時要一併清掉的本模組子表，順序＝先子後父（PRAGMA foreign_keys = ON，順序錯就會被擋，
# 見 app/core/db.py connect()）。這份順序是依 app/ads/migrations/*.sql 的 REFERENCES 欄位
# 手動拓樸排序：例如 external_ad_mapping 被 campaign_activation/performance_snapshot/
# performance_reading/derived_metric 引用，得先清那幾張才能清它自己；它又引用
# publishing_package／final_asset，所以它得排在那兩張之前。
# learning_ledger 不在這裡：它是跨期累積的學習紀錄（見 repository 檔頭），來源檔期被刪
# 不代表學習本身作廢，見 delete_cycle() 內的解除關聯處理（不刪列，只把外鍵欄位設為 NULL）。
CYCLE_CASCADE_TABLES = (
    ("finding", "掃描與對帳提示"),
    ("interrupt", "打斷佇列提醒"),  # 檔期提醒卡票 #32 起改走全站打斷佇列（app/core/interrupts.py）
    ("cycle_checklist_item", "投放前檢查清單紀錄"),
    ("cycle_checkpoint", "期中健康檢查紀錄"),
    ("cycle_code_verification", "上線前配碼校驗紀錄"),  # 票 #35：這一期的規劃產物，隨期消失
    ("cycle_voucher_code", "期別配碼"),  # 票 #35：比照 publishing_package，不比照 learning_ledger 脫鉤
    ("cycle_shopee_code", "蝦皮期別配碼與回收數"),  # 票 #40：比照 cycle_voucher_code，同一邏輯
    ("rule_dissent", "AI 具名異議"),
    ("campaign_plan_option", "待選方案"),
    ("adoption_decision", "素材採用／拒絕決定"),
    ("campaign_plan", "已核准的正式計畫"),
    ("campaign_cycle_product", "產品預算分配"),
    ("campaign_cycle_goal", "本期目標關聯"),
    ("campaign_cycle_hypothesis", "本期假設關聯"),
    ("recommendation", "下一步建議"),
    ("reading_snapshot_input", "判讀快照明細"),  # 票 #37：先刪子表，reading_snapshot 才刪得掉
    ("reading_snapshot", "判讀快照"),  # 票 #37：判讀當下的凍結紀錄，隨檔期史一起消失
    ("settlement_version", "結算版次"),  # 票 #37：版次號碼是這期判讀史的一部分，不是跨期資產
    ("derived_metric", "衍生成效指標"),
    ("campaign_activation", "投放啟動紀錄"),
    ("performance_snapshot", "成效數據"),
    ("performance_reading", "成效判讀"),
    ("external_ad_mapping", "Meta 廣告物件對應"),
    ("publishing_package", "投放交接包"),
    ("final_asset", "定稿素材檔"),
    ("creative_variant", "廣告素材"),
    ("creative_brief", "素材需求簡報"),
    ("creative_theme_component", "主題元件"),  # 票 02-theme-tables，先於 creative_theme 清（子表）
    ("creative_theme", "主題"),  # 票 02-theme-tables，先於 experiment_cell 清（引用它）
    ("experiment_cell", "實驗組合（受眾×訊息×格式）"),
)


def count_cycle_data(conn: sqlite3.Connection, brand_id: str, cycle_id: str) -> list:
    """回傳 [(中文名稱, 筆數)]，給刪除確認頁列出「按下去會消失什麼」（比照 count_product_data）。"""
    return [
        (label, conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE campaign_cycle_id = ?", (cycle_id,)
        ).fetchone()[0])
        for table, label in CYCLE_CASCADE_TABLES
    ]


def delete_cycle(conn: sqlite3.Connection, brand_id: str, cycle_id: str, *, actor: str) -> dict:
    """硬刪除一個已封存檔期與它掛的全部連帶資料，不可逆（比照決策 0020 產品先例）。

    只收已封存的檔期：使用中或已結束的檔期都得先封存，隔一道手續才刪得掉。
    """
    if not actor or not actor.strip():
        raise ValueError("actor 為必填")
    before = get_cycle(conn, brand_id, cycle_id)
    if before is None:
        raise ValueError(f"找不到廣告檔期：{cycle_id}")
    if not before["archived"]:
        raise ValueError("只有已封存的檔期可以刪除，請先把檔期封存。")

    counts = dict(count_cycle_data(conn, brand_id, cycle_id))

    # learning_ledger 解除關聯（不刪列）：先斷開指向這期判讀的列，再斷開指向這期本身的列，
    # 避免 PRAGMA foreign_keys=ON 擋下後面對 performance_reading／campaign_cycle 的 DELETE。
    # learning_ledger 現屬品牌永久層（修憲落地 A3），本模組只算出要解除哪些
    # performance_reading id，實際的 UPDATE 走 bi.unlink_learning_ledger_reading／
    # unlink_learning_ledger_cycle 兩個公開函式（A1：跨層一律走公開函式，不對別層的表下 SQL）。
    reading_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM performance_reading WHERE campaign_cycle_id = ?", (cycle_id,)
    ).fetchall()]
    bi.unlink_learning_ledger_reading(conn, reading_ids)
    bi.unlink_learning_ledger_cycle(conn, cycle_id)
    # 灌水係數與事後誤差紀錄比照 learning_ledger 脫鉤（票 #36）：跨期累積校準，
    # 不因來源檔期被刪就消失，只解除關聯。
    conn.execute(
        "UPDATE ad_revenue_coefficient SET source_cycle_id = NULL WHERE source_cycle_id = ?",
        (cycle_id,),
    )
    conn.execute(
        "UPDATE ad_revenue_coefficient_error_log SET campaign_cycle_id = NULL"
        " WHERE campaign_cycle_id = ?",
        (cycle_id,),
    )

    for table, _label in CYCLE_CASCADE_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE campaign_cycle_id = ?", (cycle_id,))
    conn.execute("DELETE FROM campaign_cycle WHERE id = ? AND brand_id = ?", (cycle_id, brand_id))

    write_audit(conn, brand_id=brand_id, entity_type="campaign_cycle", entity_id=cycle_id,
                action="delete", actor=actor, before={**before, "deleted_counts": counts},
                after=None, reason="把關人刪除已封存檔期（比照決策 0020）")
    conn.commit()
    return counts


# ---------------------------------------------------------------------------
# Finding（法務掃描、對帳、增幅上限、資料合理性共用同一張表）
# ---------------------------------------------------------------------------

def replace_findings(conn: sqlite3.Connection, brand_id: str, cycle_id: str,
                     finding_type: str, findings: list) -> int:
    """把某一類 Finding 整批換掉（重掃就是重算，不累積歷史殘留）。回傳寫入筆數。

    findings 是 app/ads/guardrails.py 的 Finding dataclass 清單——法務掃描與對帳
    產出的是同一種結構，所以共用這一個落庫入口。
    """
    conn.execute(
        "DELETE FROM finding WHERE brand_id = ? AND campaign_cycle_id = ? AND finding_type = ?",
        (brand_id, cycle_id, finding_type),
    )
    ts = now_iso()
    for finding in findings:
        conn.execute(
            "INSERT INTO finding (id, brand_id, campaign_cycle_id, finding_type, target_type,"
            " target_id, severity, code, message, evidence_json, confidence_penalty, source,"
            " resolved, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
            (new_id("fnd"), brand_id, cycle_id, finding.finding_type,
             "variant" if finding.evidence.get("variant_id") else "cycle",
             finding.evidence.get("variant_id") or cycle_id,
             finding.severity, finding.code, finding.message,
             json.dumps(finding.evidence, ensure_ascii=False),
             finding.confidence_penalty, finding.source, ts),
        )
    conn.commit()
    return len(findings)


def list_findings(conn: sqlite3.Connection, brand_id: str, cycle_id: str,
                  finding_type: Optional[str] = None) -> list:
    sql = ("SELECT * FROM finding WHERE brand_id = ? AND campaign_cycle_id = ? AND resolved = 0")
    params = [brand_id, cycle_id]
    if finding_type:
        sql += " AND finding_type = ?"
        params.append(finding_type)
    return _rows(conn.execute(sql + " ORDER BY severity DESC, created_at", params))


# ---------------------------------------------------------------------------
# 具名異議（票 5）：AI 對帳戶結構／預算配置底案或明顯薄弱的 Offer 提出的建議，
# 老闆的採納結果留紀錄供事後驗證 AI 異議的準確度（決策 0023 第 25 點）。
# ---------------------------------------------------------------------------

def replace_pending_dissents(conn: sqlite3.Connection, brand_id: str, cycle_id: str,
                             dissents: list, llm_task_id: Optional[str], *,
                             target_types: Optional[tuple] = None) -> int:
    """整批換掉這一輪還沒被老闆處理過（pending）的舊異議；已經決定過的（adopted/rejected）
    留著不動——那是事後驗證用的歷史紀錄，不因為重新生成方案而消失。

    target_types 省略＝清掉這期全部 pending 異議（既有呼叫端行為：app/ads/plan.py 一次生成
    account_structure/budget_allocation/offer 三種，一起換）。傳了就只清同一批次的類型
    （app/ads/reading.py 的回購校正異議獨立一批，不能清掉還沒被決定的方案異議——issue #39）。
    """
    sql = "DELETE FROM rule_dissent WHERE brand_id = ? AND campaign_cycle_id = ? AND status = 'pending'"
    params: list = [brand_id, cycle_id]
    if target_types:
        placeholders = ",".join("?" for _ in target_types)
        sql += f" AND target_type IN ({placeholders})"
        params.extend(target_types)
    conn.execute(sql, params)
    ts = now_iso()
    for d in dissents:
        conn.execute(
            "INSERT INTO rule_dissent (id, brand_id, campaign_cycle_id, target_type, suggestion,"
            " reason, llm_task_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
            (new_id("dsn"), brand_id, cycle_id, d["target_type"], d["suggestion"], d["reason"],
             llm_task_id, ts),
        )
    conn.commit()
    return len(dissents)


def list_dissents(conn: sqlite3.Connection, brand_id: str, cycle_id: str,
                  status: Optional[str] = None) -> list:
    sql = "SELECT * FROM rule_dissent WHERE brand_id = ? AND campaign_cycle_id = ?"
    params = [brand_id, cycle_id]
    if status:
        sql += " AND status = ?"
        params.append(status)
    return _rows(conn.execute(sql + " ORDER BY created_at", params))


def decide_dissent(conn: sqlite3.Connection, brand_id: str, cycle_id: str, dissent_id: str,
                   decision: str, actor: str) -> dict:
    """老闆對一筆異議拍板：採納或不採納。留 before/after 稽核，供日後驗證 AI 異議準確度。"""
    if decision not in ("adopted", "rejected"):
        raise ValueError("採納結果只能是「採納」或「不採納」")
    row = conn.execute(
        "SELECT * FROM rule_dissent WHERE id = ? AND brand_id = ? AND campaign_cycle_id = ?",
        (dissent_id, brand_id, cycle_id),
    ).fetchone()
    if row is None:
        raise ValueError("找不到這筆異議紀錄，可能已經重新生成過方案了。")
    before = dict(row)
    ts = now_iso()
    conn.execute(
        "UPDATE rule_dissent SET status = ?, decided_by = ?, decided_at = ? WHERE id = ?",
        (decision, actor, ts, dissent_id),
    )
    after = {**before, "status": decision, "decided_by": actor, "decided_at": ts}
    write_audit(conn, brand_id=brand_id, entity_type="rule_dissent", entity_id=dissent_id,
                action="decide", actor=actor, before=before, after=after)
    conn.commit()
    return after


# ---------------------------------------------------------------------------
# 學習迴路（GitHub issue #53，決策 0030）：假設結案讀取＋學習入帳
# ---------------------------------------------------------------------------

def list_cycle_hypotheses(conn: sqlite3.Connection, brand_id: str, cycle_id: str) -> list:
    """這期開期時掛進來的策略假設。策略假設住品牌智庫（跨模組），這裡只查本模組的連結表
    拿到 id，實際內容一律經 `brand_intelligence.repository` 的公開函式讀取（規則 3）。"""
    links = _rows(conn.execute(
        "SELECT strategy_hypothesis_id, role FROM campaign_cycle_hypothesis"
        " WHERE brand_id = ? AND campaign_cycle_id = ?", (brand_id, cycle_id),
    ))
    result = []
    for link in links:
        hypothesis = bi.get_strategy_hypothesis(conn, brand_id, link["strategy_hypothesis_id"])
        if hypothesis is not None:
            result.append(hypothesis)
    return result


def create_learning_ledger_entry(conn: sqlite3.Connection, brand_id: str, *, learning_text: str,
                                  applicability_scope: str, created_by: str, actor: str,
                                  product_id: Optional[str] = None, platform: Optional[str] = None,
                                  source_cycle_id: Optional[str] = None,
                                  source_reading_id: Optional[str] = None,
                                  source_hypothesis_id: Optional[str] = None,
                                  sample_size: Optional[str] = None,
                                  confidence: Optional[str] = None) -> dict:
    """已驗證的正面學習入帳（append-only，鐵則 3）：只新增，本層不提供 UPDATE／DELETE
    入口。只收「經判讀驗證且經人確認」的條目——由呼叫端保證（決策 0030 第一節第 1 點）。

    薄封裝：`learning_ledger` 已遷入品牌永久層（修憲落地 A3），實際寫入轉呼叫
    `brand_intelligence.repository`，固定帶 `source_track="ads"`（A4：來源分支不得省略，
    本模組是目前唯一的分支代號）。
    """
    return bi.create_learning_ledger_entry(
        conn, brand_id, learning_text=learning_text, applicability_scope=applicability_scope,
        created_by=created_by, actor=actor, source_track="ads", product_id=product_id,
        platform=platform, source_cycle_id=source_cycle_id, source_reading_id=source_reading_id,
        source_hypothesis_id=source_hypothesis_id, sample_size=sample_size, confidence=confidence,
    )


def list_learning_ledger(conn: sqlite3.Connection, brand_id: str, *,
                          include_expired: bool = False) -> list:
    """累積智慧頁（GitHub issue #56）讀取用：已驗證的正面學習清單。薄封裝，見檔頭說明。"""
    return bi.list_learning_ledger(conn, brand_id, include_expired=include_expired)


def deactivate_learning_ledger_entry(conn: sqlite3.Connection, brand_id: str, entry_id: str, *,
                                      actor: str) -> dict:
    """下架一條已確認學習（GitHub issue #56）：把 `expired` 標成 1，不刪列、不改內容。
    薄封裝，見檔頭說明。"""
    return bi.deactivate_learning_ledger_entry(conn, brand_id, entry_id, actor=actor)


# ---------------------------------------------------------------------------
# 刪品牌（第 4 刀「廣告模組接上清理登記處」）
#
# 排序沿用 CYCLE_CASCADE_TABLES（刪檔期時已經按外鍵拓樸排好序的正確答案），條件從
# campaign_cycle_id 換成 brand_id；扣掉其中兩張不屬於本模組的表——interrupt（core 的
# 打斷佇列）與 cycle_shopee_code（orders 的蝦皮期別配碼）——刪檔期時本模組去清它們是
# 既有行為不動，但刪品牌時這兩張歸第 5 刀，不在本模組宣告範圍內。
#
# 再接上 CYCLE_CASCADE_TABLES 之外、只在品牌層才要清的表（先子後父）：
#   - ad_revenue_coefficient_error_log 先於 ad_revenue_coefficient（前者引用後者）
#   - ad_revenue_coefficient 引用 campaign_cycle，且是判讀之後才累積的校準值，
#     排在 CYCLE_CASCADE_TABLES 裡的 reading_snapshot 之後
#   - activation_authorization 排在 campaign_activation 之後（後者引用前者）
#   - success_criterion 排在 marketing_goal 之前（前者引用後者）；marketing_goal
#     也被 campaign_cycle_goal 引用，campaign_cycle_goal 已經排在更前面
#   - offer／brand_checklist_item／ga4_summary／ga4_sync_status 無外鍵，順序不拘
#   - creative_rule_card 排在 campaign_cycle 之前（前者引用後者）
#   - campaign_cycle 是這一串（ad_account 之外）全部東西的根，必須最後刪
_BRAND_ONLY_CASCADE_TABLES = (
    ("ad_revenue_coefficient_error_log", "灌水係數事後誤差紀錄"),
    ("ad_revenue_coefficient", "回購灌水校準係數"),
    ("activation_authorization", "投放啟動具名授權"),
    ("success_criterion", "成功標準"),
    ("marketing_goal", "行銷目標"),
    ("offer", "優惠方案"),
    ("brand_checklist_item", "品牌層檢查清單項目"),
    ("ga4_summary", "GA4 流量彙總"),
    ("ga4_sync_status", "GA4 同步驗證狀態"),
    ("creative_rule_card", "候選規則卡"),
    ("campaign_cycle", "廣告檔期"),
)

# 刪品牌時本模組會清掉的完整表清單。count_brand_data／delete_brand_data 共用同一份，
# 不各自維護一份——「清點清一份、清除清另一份，兩邊不同步」正是這整串 bug 的根因。
#
# ad_account／discovered_campaign 沒有 brand_id 欄位，是帳號層資料，刻意不在這份清單裡：
# 誤刪它們會弄壞別的品牌。
BRAND_CASCADE_TABLES = tuple(
    (table, label) for table, label in CYCLE_CASCADE_TABLES
    if table not in ("interrupt", "cycle_shopee_code")
) + _BRAND_ONLY_CASCADE_TABLES


def count_brand_data(conn: sqlite3.Connection, brand_id: str) -> list:
    """刪品牌前的清點（比照 brand_intelligence.count_brand_data 的回傳格式），給刪除
    確認頁列出「按下去會消失什麼」。跟 delete_brand_data 讀同一份 BRAND_CASCADE_TABLES。"""
    counts = []
    for table, label in BRAND_CASCADE_TABLES:
        n = conn.execute(
            f"SELECT COUNT(*) AS c FROM {table} WHERE brand_id = ?", (brand_id,)
        ).fetchone()["c"]
        if n:
            counts.append((label, n))
    return counts


def delete_brand_data(conn: sqlite3.Connection, brand_id: str) -> dict:
    """清掉本模組掛在該品牌下的資料（BRAND_CASCADE_TABLES 這 37 張子表），登記進
    app.core.cleanup 給 delete_brand() 呼叫用。只下 DELETE、不 commit、不 rollback
    （Q4 單一交易、全有全無，commit 與 rollback 統一在 brand_intelligence.delete_brand()）。
    """
    counts = dict(count_brand_data(conn, brand_id))
    for table, _label in BRAND_CASCADE_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE brand_id = ?", (brand_id,))
    return counts


# ---------------------------------------------------------------------------
# 刪產品（第 6 刀「廣告模組接上刪產品清理登記處」）：品牌智庫的 delete_product() 硬刪
# 一顆已封存產品時，本模組掛在該產品底下的資料要一併清掉，不然就是孤兒列。
#
# 這 10 張表都直接帶 product_id 欄位（不是外鍵、是跨模組引用，見各表 CREATE TABLE 旁
# 的註解），只挑 product_id 對得上這顆產品的列，同一張表裡 product_id 為 NULL（品牌層
# 總結）或屬於別的產品的列不會被這個條件選到，不會誤刪品牌層或別的產品的資料。
#
# 排序照依賴關係排（子表在前、父表在後——即使 delete_product() 會開
# PRAGMA defer_foreign_keys=ON、順序本身不影響正確性，這裡仍照拓樸順序排，跟
# BRAND_CASCADE_TABLES／CYCLE_CASCADE_TABLES 維持同樣的可讀性風格）：
#   - recommendation 引用 performance_reading，排在它前面
#   - derived_metric 引用 performance_snapshot，排在它前面
#   - publishing_package 引用 creative_variant／experiment_cell，排在它們前面
#   - performance_reading／creative_variant 都引用 experiment_cell，排在它前面
PRODUCT_CASCADE_TABLES = (
    ("recommendation", "下一步建議"),
    ("derived_metric", "衍生成效指標"),
    ("publishing_package", "投放交接包"),
    ("performance_reading", "成效判讀"),
    ("performance_snapshot", "成效數據"),
    ("creative_variant", "廣告素材"),
    ("experiment_cell", "實驗組合（受眾×訊息×格式）"),
    ("creative_rule_card", "候選規則卡"),
    ("marketing_goal", "行銷目標"),
    ("campaign_cycle_product", "產品預算分配"),
)

# 上面那 10 張是「自己就掛著 product_id」的表，照 product_id 篩就刪得掉。
# 但還有一類表：它們自己沒有 product_id，卻用外鍵指著上面那些會被刪掉的列——
# 父列被刪、子列留著就是懸空外鍵，整個刪除會在 COMMIT 被擋下（實測過：拿真實資料庫
# 複本刪一個虛構產品，就是被 creative_brief -> experiment_cell 與
# external_ad_mapping -> publishing_package 擋下來的）。
# 而且它有傳遞性：把 external_ad_mapping 納入清理之後，指向它的 campaign_activation
# 又變成新的懸空來源。手工維護一份清單一定會漏掉第二層、第三層，所以這裡改成沿著
# 外鍵自動走一遍——只往「誰指著我」的方向走（要刪的列被誰參照），不往「我指著誰」
# 的方向走（那些是別人的資料，不該跟著刪）。
#
# 這份標籤表只負責把走到的表翻成人話給刪除確認頁看；走不走得到由 schema 決定，
# 不由這份表決定。走到了卻沒登記標籤，就用表名當標籤，不會靜靜漏掉。
_PRODUCT_CASCADE_LABELS = {
    "creative_brief": "素材需求簡報",
    "final_asset": "定稿素材檔",
    "external_ad_mapping": "Meta 廣告物件對應",
    "campaign_activation": "投放啟動紀錄",
    "campaign_cycle_goal": "本期目標關聯",
    "success_criterion": "成功判準",
    "creative_theme": "主題",  # 票 02-theme-tables：自己沒 product_id，靠外鍵沿 experiment_cell 走到
    "creative_theme_component": "主題元件",  # 同上，沿 creative_theme 走到
}


def _inbound_fks(conn) -> dict:
    """{被指向的表: [(子表, 子表的外鍵欄位, 父表被指向的欄位), ...]}，從真實 schema 讀。

    不假設父表的主鍵一定叫 id——外鍵可以指向任何欄位，PRAGMA 第 5 欄就是答案
    （為 None 代表指向父表的主鍵）。
    """
    out = {}
    for (table,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        for fk in conn.execute(f"PRAGMA foreign_key_list({table})"):
            out.setdefault(fk[2], []).append((table, fk[3], fk[4] or "id"))
    return out


def _product_cascade_scope(conn, brand_id: str, product_id: str) -> dict:
    """從 PRODUCT_CASCADE_TABLES 那 10 張屬於這顆產品的列出發，沿外鍵反覆找出所有
    「指著它們」的列，回傳 {表名: set(rowid)}，找到不再有新東西為止（傳遞閉包）。

    用 rowid 而不是 id：連結表（例如 campaign_cycle_goal）是複合主鍵、根本沒有 id 欄位，
    而 rowid 是 SQLite 每張一般表都有的內建列識別碼。
    """
    scope: dict = {}
    for table, _label in PRODUCT_CASCADE_TABLES:
        rows = {r[0] for r in conn.execute(
            f"SELECT rowid FROM {table} WHERE brand_id = ? AND product_id = ?",
            (brand_id, product_id))}
        if rows:
            scope[table] = rows
    inbound = _inbound_fks(conn)
    changed = True
    while changed:
        changed = False
        for parent in list(scope):
            for child, fk_col, parent_col in inbound.get(parent, []):
                parent_rowids = list(scope[parent])
                if not parent_rowids:
                    continue
                marks = ",".join("?" for _ in parent_rowids)
                keys = [r[0] for r in conn.execute(
                    f"SELECT {parent_col} FROM {parent} WHERE rowid IN ({marks})", parent_rowids)
                    if r[0] is not None]
                if not keys:
                    continue
                kmarks = ",".join("?" for _ in keys)
                found = {r[0] for r in conn.execute(
                    f"SELECT rowid FROM {child} WHERE {fk_col} IN ({kmarks})", keys)}
                new = found - scope.get(child, set())
                if new:
                    scope.setdefault(child, set()).update(new)
                    changed = True
    return scope


def count_product_data(conn: sqlite3.Connection, brand_id: str, product_id: str) -> list:
    """刪產品前的清點（比照 count_brand_data 的回傳格式），給刪除確認頁列出「按下去會
    消失什麼」。跟 delete_product_data 共讀同一份 PRODUCT_CASCADE_TABLES，不各寫一份，
    避免清點與清除不同步（第 4 刀吃過的虧）。"""
    counts = []
    for table, label in PRODUCT_CASCADE_TABLES:
        n = conn.execute(
            f"SELECT COUNT(*) AS c FROM {table} WHERE brand_id = ? AND product_id = ?",
            (brand_id, product_id),
        ).fetchone()["c"]
        if n:
            counts.append((label, n))
    # 沿外鍵走到的連帶列（自己沒有 product_id 的那些表），見 _product_cascade_scope
    scope = _product_cascade_scope(conn, brand_id, product_id)
    direct = {t for t, _ in PRODUCT_CASCADE_TABLES}
    for table in sorted(scope):
        if table in direct:
            continue
        counts.append((_PRODUCT_CASCADE_LABELS.get(table, table), len(scope[table])))
    return counts


def delete_product_data(conn: sqlite3.Connection, brand_id: str, product_id: str) -> dict:
    """清掉本模組掛在該產品下的資料（PRODUCT_CASCADE_TABLES 這 10 張表），登記進
    app.core.cleanup 給 brand_intelligence.delete_product() 呼叫用。只下 DELETE、不
    commit、不 rollback（Q4 單一交易、全有全無，commit 與 rollback 統一在
    brand_intelligence.delete_product()）。
    """
    counts = dict(count_product_data(conn, brand_id, product_id))
    # 先把整個連帶範圍算出來（含沿外鍵走到的第二層、第三層），再依 id 刪。
    # 一定要先算完再刪：父列一旦刪掉，子查詢就撈不到它的子列了。
    scope = _product_cascade_scope(conn, brand_id, product_id)
    direct = {t for t, _ in PRODUCT_CASCADE_TABLES}
    for table in scope:
        if table in direct:
            continue
        ids = list(scope[table])
        marks = ",".join("?" for _ in ids)
        conn.execute(f"DELETE FROM {table} WHERE rowid IN ({marks})", ids)
    for table, _label in PRODUCT_CASCADE_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE brand_id = ? AND product_id = ?",
                     (brand_id, product_id))
    return counts


# ---------------------------------------------------------------------------
# 清理登記處（第 2 刀）：向 app.core.cleanup 登記本模組的清點／清除函式，刪品牌時
# 由登記處統一呼叫，本模組不必再被別人手寫死「記得通知它」。
#
# 舊版這裡曾寫死「品牌智庫必須比本模組先登記」，理由是舊資料庫的 learning_ledger
# 可能帶 REFERENCES campaign_cycle(id) 外鍵，登記順序錯了 DELETE 會被 FK 擋下。
# 第 5 刀把這個問題連根拔掉：app/brand_intelligence/repository.py 的 delete_brand()
# 交易一開始就下 `PRAGMA defer_foreign_keys = ON`，外鍵檢查延到 COMMIT 才做一次，
# 跨模組登記順序從此完全不重要——包含 learning_ledger／campaign_cycle 這條、
# 也包含 cycle_shopee_code（訂單模組）／campaign_cycle（本模組）那條。
#
# app/tests/test_ads_brand_cleanup.py 那條「品牌智庫要比廣告先登記」的順序釘子測試
# 留著沒刪：現在它驗證的不是「必要條件」而是「回歸保險」——就算哪天真的不小心把
# PRAGMA 那行刪掉，至少這條舊約束的順序還在，不會立刻整批爆掉。
# ---------------------------------------------------------------------------

cleanup.register("廣告", count_brand=count_brand_data, delete_brand=delete_brand_data,
                 brand_tables={t for t, _ in BRAND_CASCADE_TABLES},
                 count_product=count_product_data, delete_product=delete_product_data,
                 product_tables={t for t, _ in PRODUCT_CASCADE_TABLES})
