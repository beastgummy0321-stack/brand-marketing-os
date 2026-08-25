# -*- coding: utf-8 -*-
"""app/ads/nextcycle.py — 下期草案、規則卡、反回音室（票 13）。

判讀完成的同時就把下一期準備好（決策 0022 第 15 點）——使用者往下滑就看到一份填好的
下期計畫，點「就這樣開下期」即可，不用重新回答任何問題。

三件事都由程式決定、LLM 只寫說明文字：

1. **下期預算**：依判讀狀態走增幅階梯（app/ads/guardrails.py cap_scale_up），
   樣本少就只准小加。LLM 不決定加多少。
2. **規則卡**：同一個指紋標籤被退到門檻，就產一張候選長期規則，附證據。
   掛在下一期的計畫確認關卡裡、預設已同意——不新增第四道關卡（決策 0022 第 13 點）。
3. **反回音室**：比對本期素材與歷史採用素材的指紋距離，太像就產一條提示，
   並讓下一批生成時刻意留一組「故意不一樣」的實驗組。
"""

from typing import Optional

from app.ads import budget as ads_budget
from app.ads import fingerprint as fp
from app.ads import guardrails
from app.ads import reading as ads_reading
from app.ads import repository as ads_repo
from app.ads import target_cpa
from app.core.audit import write_audit
from app.core.db import new_id, now_utc, jsonb, DEV_ORG_ID

# `overclaim` 候選卡（見下方 build_overclaim_claim_cards）沿用的絕對次數門檻——那裡每一則
# 拒絕對應的是「這句話」本身（獨一無二的文字），不是可能重複出現很多次的指紋軸值，沒有
# 「分母」這個概念可比，所以維持原本的絕對次數，不受本票（修憲落地 G3）影響。
RULE_CARD_THRESHOLD = 2

# ---------------------------------------------------------------------------
# 規則卡相對判準（修憲落地 G3，決策 0035 第5點）
# ---------------------------------------------------------------------------
# 舊門檻只數分子（被拒幾次）不數分母（這個軸值總共出現過幾次），一期隨機退幾則素材就有
# 相當機率巧合撞到絕對次數、鑄成永久禁令。新門檻改看「這個軸值的拒絕比例，是否明顯高於
# 同一軸其他值的整體拒絕比例」，並且只算最近幾期（時間窗），不是無限期累加。

# 時間窗：只算最近幾期。
RULE_CARD_WINDOW_CYCLES = 3
# 分子門檻下限：被拒次數至少要這麼多，一次可能只是那則寫得爛。
RULE_CARD_MIN_REJECTIONS = 2
# 分母門檻下限：這個軸值至少要出現過這麼多次，樣本太少比例不可信。
RULE_CARD_MIN_SAMPLES = 2
# 拒絕比例要比同軸其他值的整體拒絕比例高出這個倍數以上，才算「這個方向真的有問題」，
# 不是雜訊——沒有其他值可比較時（例如新品牌剛開始），視為門檻自動通過。
RULE_CARD_RELATIVE_MULTIPLIER = 1.5

# `overclaim`（講得太滿）借用 creative_rule_card 表存放「登記為禁用宣稱」候選卡的
# sentinel 軸名——它不是 fingerprint.AXES 裡的真軸（決策 0030 第 6 點刻意不讓 overclaim
# 有軸，本票不改這個切分），只是借同一張表、同一套 pending/accepted/declined 狀態機，
# 不必為此新增表（修憲落地 L4 不動 schema）。`decide_rule_card`／模板靠這個值分岔行為。
OVERCLAIM_CLAIM_AXIS = "overclaim"

BUDGET_ADVICE = {
    "scale_candidate": "這期表現不錯，下期可以加碼",
    "maintain": "這期還行，下期維持一樣的預算",
    "learning": "還在摸索，下期先維持一樣的預算多看幾天",
    "pause_candidate": "這期沒賺到，下期先把預算收一半，換一批素材再試",
    "insufficient_data": "資料還不夠，下期維持一樣的預算把樣本跑足",
    "unclear_economics": "算不出賺不賺，下期先維持，並且把產品的成本售價補上",
}


def propose_budget(conn, brand_id: str, cycle_id: str) -> dict:
    """下期預算建議。加碼幅度由增幅階梯決定，程式說了算。"""
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    verdict = ads_reading.load(conn, brand_id, cycle_id)
    current = cycle["budget"] or 0
    status = (verdict["cycle"] or {}).get("status", "insufficient_data")

    conversions = 0.0
    row = conn.execute(
        "SELECT COALESCE(SUM(conversions), 0) c FROM performance_snapshot"
        " WHERE brand_id = %s AND campaign_cycle_id = %s AND quarantined = false",
        (brand_id, cycle_id),
    ).fetchone()
    if row:
        conversions = row["c"] or 0.0

    if status == "pause_candidate":
        proposed = round(current * 0.5, 2)
        cap = None
    else:
        cap = guardrails.cap_scale_up(current or 1, conversions)
        proposed = cap.max_budget if status == "scale_candidate" else current

    return {
        "status": status,
        "current_budget": current,
        "proposed_budget": proposed,
        "cap_ratio": cap.cap_ratio if cap else None,
        "conversions": conversions,
        "advice": BUDGET_ADVICE.get(status, "下期先維持一樣的預算"),
    }


# ---------------------------------------------------------------------------
# 樣本可信門檻與零轉換警示（票 03-sample-trust-threshold，ADR 0011 第一至三節）
# ---------------------------------------------------------------------------
# 可信門檻：轉換數達這個次數才算可信。沿用既有常數（target_cpa.WEEKLY_CONVERSIONS_PER_GROUP），
# 不另立一個一樣是 50 的新數字——內部既有常數與查證過的 madgicx 業界基準剛好一致。


def cell_trust_flags(conversions: float, spend: float, allocated_budget: float, *,
                     revenue: Optional[float] = None,
                     breakeven_roas: Optional[float] = None) -> dict:
    """切角歷史成效資料的兩道誠實旗標，只回傳「有值得提醒」的那幾個鍵——條件不成立時
    對應的鍵不出現（不是回傳 False），呼叫端用 `"evidence_sufficient" in flags` 判斷。

    - `evidence_sufficient: False`：累積轉換數不足可信門檻，仍然顯示該切角，只是誠實
      標「還不知道」，不排除（ADR 0009 誠實狀態優先）。
    - `underperforming: True`：花費已達分配預算一半（沿用 `budget.PAUSE_THRESHOLD_RATIO`
      這個既有比例概念，不是直接呼叫 budget.py 同一段程式碼——那支是檔期層級「該考慮暫停」，
      這裡是切角層級「這次沒打中」，場景不同、比例概念相同）之後，兩種證據途徑之一成立：
      1. 零轉換——已經有足夠證據，不是「還不知道」。
      2. `revenue`、`breakeven_roas` 兩個可選參數都有值時才啟用的第二途徑（票
         03-performance-reaches-the-user-and-the-next-cycle）：轉換數不為 0，但實際投報率
         （revenue / spend）低到 `reading.PAUSE_MARGIN` 這條停損線以下——花錢有轉換卻虧到
         該收手，跟零轉換一樣是「已經知道沒打中」，不是「還不知道」。
         門檻用「打平線 × PAUSE_MARGIN」而不是裸的打平線，因為檔期層 `reading.judge()` 本來
         就是這樣分的：低於打平線但還在 PAUSE_MARGIN 以上叫 learning「在打平線附近，再跑一陣
         子看看」，低於才叫 pause_candidate。沿用同一條線＝沿用既有那套「差」的定義，不另立
         第二套（D3）；缺任一個參數就維持今天只看零轉換的行為，呼叫端不必全部改寫。

    - `underperforming_reason`：只在 `underperforming` 出現時一起出現，標是上面哪一條途徑
      觸發——`"zero_conversion"`（零轉換）或 `"roas_below_stop_loss"`（有轉換但低於停損線）。
      兩條途徑的意思差很多，呼叫端寫給人看的理由不能共用同一句（驗收 A 第 4 節 6c）。

    兩者互相獨立，可能同時出現、也可能都不出現。
    """
    flags = {}
    if conversions < target_cpa.WEEKLY_CONVERSIONS_PER_GROUP:
        flags["evidence_sufficient"] = False
    spend_reached_half = (allocated_budget > 0
                          and spend >= allocated_budget * ads_budget.PAUSE_THRESHOLD_RATIO)
    if conversions == 0 and spend_reached_half:
        flags["underperforming"] = True
        flags["underperforming_reason"] = "zero_conversion"
    elif (spend_reached_half and revenue is not None and breakeven_roas is not None
          and spend > 0 and (revenue / spend) < breakeven_roas * ads_reading.PAUSE_MARGIN):
        flags["underperforming"] = True
        flags["underperforming_reason"] = "roas_below_stop_loss"
    return flags


def historical_cell_performance(conn, brand_id: str, exclude_cycle_id: Optional[str] = None) -> list:
    """品牌歷來每個切角（experiment_cell）累積的成效資料，各自附加 `cell_trust_flags()`
    的誠實旗標——不影響哪些切角被列出，只影響附加資訊（ADR 0011 第二節）。

    切角沒有自己的「分配預算」欄位：均分該切角所屬檔期的總預算（沿用 `budget.split_budget()`
    缺乏其他資料時的既有作法——找不到更好的權重就均分）。
    ponytail：均分假設同期切角預算平分，之後若切角有自己的預算欄位再改用真實值。

    成效資料走既有的 performance_snapshot → external_ad_mapping → publishing_package 鏈
    （比照 `reading._asset_totals()` 的既有 JOIN 寫法，只是改成依 `experiment_cell_id` 分組）。

    每列另外附上 `revenue`、`breakeven_roas`（票 03-performance-reaches-the-user-and-
    the-next-cycle，契約 B）：`breakeven_roas` 依切角所屬產品經濟資料算出；切角自己沒有
    product_id（真實資料常見，見票內 THE BUG）時退用該切角所屬檔期的打平線（該檔期各
    產品打平線的平均，同 `reading.py` 檔期層算法），兩邊都查不到就是 None，不猜。連同
    revenue 一起餵給 `cell_trust_flags()`，讓「轉換數不為 0 但沒打平」也能標成
    underperforming，不再只看零轉換。
    """
    cycles = ads_repo.list_cycles(conn, brand_id, include_archived=True)
    budget_by_cycle = {c["id"]: (c["budget"] or 0) for c in cycles}

    sql = "SELECT id, campaign_cycle_id, product_id, creative_angle FROM experiment_cell WHERE brand_id = %s"
    params = [brand_id]
    if exclude_cycle_id:
        sql += " AND campaign_cycle_id != %s"
        params.append(exclude_cycle_id)
    cell_rows = conn.execute(sql, params).fetchall()
    if not cell_rows:
        return []

    cells_per_cycle: dict = {}
    for row in cell_rows:
        cells_per_cycle[row["campaign_cycle_id"]] = cells_per_cycle.get(row["campaign_cycle_id"], 0) + 1

    perf_rows = conn.execute(
        "SELECT pkg.experiment_cell_id cell_id, COALESCE(SUM(ps.spend),0) spend,"
        " COALESCE(SUM(ps.conversions),0) conversions, COALESCE(SUM(ps.revenue),0) revenue"
        " FROM performance_snapshot ps"
        " JOIN external_ad_mapping xam ON xam.id = ps.external_ad_mapping_id"
        " JOIN publishing_package pkg ON pkg.id = xam.publishing_package_id"
        " WHERE ps.brand_id = %s AND ps.quarantined = false AND pkg.experiment_cell_id IS NOT NULL"
        " GROUP BY pkg.experiment_cell_id", (brand_id,),
    ).fetchall()
    perf_by_cell = {r["cell_id"]: {"spend": r["spend"], "conversions": r["conversions"],
                                   "revenue": r["revenue"]}
                    for r in perf_rows}

    # 每個切角的產品打平線只查一次、快取起來（票 03-performance-reaches-the-user-and-
    # the-next-cycle）：切角數可能遠大於相異產品數，不必每格各查一次 product_economics。
    # product_id 是 NULL 的切角另外按 campaign_cycle_id 快取檔期層打平線（同一份定義見
    # reading.py 算檔期層打平線那段：該檔期各產品打平線的平均，四捨五入到小數點兩位）。
    from app.brand_intelligence import repository as bi
    breakeven_by_product: dict = {}
    breakeven_by_cycle: dict = {}
    for row in cell_rows:
        pid = row["product_id"]
        if pid is not None:
            if pid not in breakeven_by_product:
                breakeven_by_product[pid] = ads_reading.breakeven_roas(
                    bi.get_product_economics(conn, brand_id, pid))
        elif row["campaign_cycle_id"] not in breakeven_by_cycle:
            knowns = [b for b in (
                ads_reading.breakeven_roas(bi.get_product_economics(conn, brand_id, p["product_id"]))
                for p in ads_repo.list_cycle_products(conn, brand_id, row["campaign_cycle_id"])) if b]
            breakeven_by_cycle[row["campaign_cycle_id"]] = (
                round(sum(knowns) / len(knowns), 2) if knowns else None)

    results = []
    for row in cell_rows:
        perf = perf_by_cell.get(row["id"], {"spend": 0.0, "conversions": 0.0, "revenue": 0.0})
        cycle_budget = budget_by_cycle.get(row["campaign_cycle_id"], 0)
        cell_count = cells_per_cycle.get(row["campaign_cycle_id"], 1)
        allocated_budget = round(cycle_budget / cell_count, 2) if cell_count else 0.0
        pid = row["product_id"]
        breakeven = (breakeven_by_product.get(pid) if pid is not None
                    else breakeven_by_cycle.get(row["campaign_cycle_id"]))
        results.append({
            "experiment_cell_id": row["id"],
            "campaign_cycle_id": row["campaign_cycle_id"],
            "product_id": row["product_id"],
            "creative_angle": row["creative_angle"],
            "spend": perf["spend"],
            "conversions": perf["conversions"],
            "revenue": perf["revenue"],
            "allocated_budget": allocated_budget,
            "breakeven_roas": breakeven,
            **cell_trust_flags(perf["conversions"], perf["spend"], allocated_budget,
                               revenue=perf["revenue"], breakeven_roas=breakeven),
        })
    return results


# ---------------------------------------------------------------------------
# 情境加權比較（票 02-occasion-weighted-recommendations，ADR 0011 第五節）
# ---------------------------------------------------------------------------
# 下期建議引擎比較歷史資料時（拒絕記憶指紋比對、新穎度、同溫層比率），跟這次檔期同一個
# 節日場合（campaign_cycle.occasion）的歷史資料權重加重，不同場合的仍然參與比較、只是
# 權重較低——不是排除、不做硬性樣本分割（新品牌可能整年只跑過一次某節日，分開比較會讓
# 它永遠沒有同場合資料可比，見 ADR 0011 第五節「當時排除了什麼」）。
#
# SAME／DIFFERENT 的確切倍率 ADR 沒有明文規定（只要求「較高」／「較低但不是排除」），
# 這裡選一個一眼看得出差異、又不會把不同場合資料壓到近乎消失的比例。

OCCASION_WEIGHT_SAME = 1.0
OCCASION_WEIGHT_DIFFERENT = 0.3


def _occasions_for_cycles(conn, cycle_ids: list) -> dict:
    """cycle_id → occasion。cycle_id 是 None（例如 adoption_decision 沒綁檔期的舊資料）
    或查無此檔期時，該筆不會出現在回傳字典裡——呼叫端用 `.get(cid)` 取，取不到視為未知。
    """
    ids = sorted({cid for cid in cycle_ids if cid})
    if not ids:
        return {}
    placeholders = ",".join("%s" for _ in ids)
    return {r["id"]: r["occasion"] for r in conn.execute(
        f"SELECT id, occasion FROM campaign_cycle WHERE id IN ({placeholders})", ids,
    )}


def _occasion_weight_map(conn, cycle_ids: list, current_occasion: Optional[str]) -> dict:
    """cycle_id → 情境權重。跟 `current_occasion` 同場合的歷史檔期權重較高、不同的較低但
    仍參與（不是排除）。

    `current_occasion` 缺值，或這批 `cycle_ids` 裡沒有任何一筆真的同場合時，全部退化成
    1.0（等同現行的無加權比較，不報錯、不空白）——加權只在「真的有同場合資料可比」時才
    有意義，不然只是無端壓低所有歷史資料的份量，沒有比較基準。
    """
    occasions = _occasions_for_cycles(conn, cycle_ids)
    if not current_occasion or current_occasion not in occasions.values():
        return {cid: 1.0 for cid in cycle_ids}
    return {cid: (OCCASION_WEIGHT_SAME if occasions.get(cid) == current_occasion
                  else OCCASION_WEIGHT_DIFFERENT) for cid in cycle_ids}


# ---------------------------------------------------------------------------
# 規則卡
# ---------------------------------------------------------------------------

def _recent_cycle_ids(conn, brand_id: str, window: int) -> list:
    """最近幾期的 cycle id（依建立時間新到舊）——規則卡相對判準的時間窗。"""
    rows = conn.execute(
        "SELECT id FROM campaign_cycle WHERE brand_id = %s ORDER BY created_at DESC LIMIT %s",
        (brand_id, window),
    ).fetchall()
    return [r["id"] for r in rows]


def _empty_stat_entry() -> dict:
    return {"appearances": 0, "rejections": 0, "policy_rejections": 0,
            "weighted_appearances": 0.0, "weighted_rejections": 0.0,
            "weighted_policy_rejections": 0.0, "ids": [], "reasons": set()}


def _axis_value_stats(conn, brand_id: str, cycle_ids: list,
                      current_occasion: Optional[str] = None) -> dict:
    """視窗內每個 (軸, 值) 出現過幾次、被拒幾次（含拆分出的政策拒絕次數）——相對判準的
    分子分母來源。

    出現次數（分母）以 `creative.list_variants()` 回傳的元件指紋為準（票
    03-close-repoint-gaps：資料源已改為主題表，`creative_variant` 沒有存活寫入路徑，
    直接查它分母恆為 0）。分母口徑因此收斂成「已採用主題底下的元件」，不是每一則
    生成過的草稿——這才是對的母體：分子（`adoption_decision` 的拒絕紀錄）只可能來自
    使用者在已採用主題裡真的看過的元件，把從未採用的草稿也算進分母只會虛增分母、
    讓規則卡更難冒出來，沒有意義。這是修憲落地 G1 抓到的原始缺陷（「只數分子不數
    分母」）的直接對症：分子單獨看起來再高，只要分母也高、比例不特別突出，就不該
    鑄成禁令。若一筆拒絕紀錄找不到對應的元件（例如舊資料），至少把這次拒絕本身算成
    一次出現，分母不能比分子還小。

    `rejections` 是總拒絕次數（含猜消費者反應的品味理由），`policy_rejections` 只算
    `reason_code` 落在 `fp.RULE_UPGRADABLE_REASONS` 白名單內的次數（票 T1）——升級成
    永久禁令只看後者，「觀察中」判準看前者。這兩個鍵、連同 `appearances`，都是**真實
    次數**（整數，不受加權影響）——`reject_count` 這類要給使用者看「被退幾次」的地方
    讀這幾個鍵，不然加權後會印出「被退 2.6 次」這種看不懂的小數。

    `weighted_appearances`／`weighted_rejections`／`weighted_policy_rejections`
    （票 02-occasion-weighted-recommendations，ADR 0011 第五節）：同一批資料再套一次
    `_occasion_weight_map()` 算出的情境權重（`current_occasion` 缺省時權重全部是 1.0，
    數值上等於真實次數），只給 `_rule_card_verdict()` 的門檻判斷用，不進畫面顯示。
    """
    if not cycle_ids:
        return {}
    weight_by_cycle = _occasion_weight_map(conn, cycle_ids, current_occasion)
    placeholders = ",".join("%s" for _ in cycle_ids)
    stats: dict = {}

    from app.ads import creative as ads_creative  # 延遲 import，比照 check_echo_chamber()

    for cycle_id in cycle_ids:
        weight = weight_by_cycle.get(cycle_id, 1.0)
        for variant in ads_creative.list_variants(conn, brand_id, cycle_id):
            raw = variant["fingerprint"] or {}
            for axis, value in fp.normalize(raw).items():
                entry = stats.setdefault((axis, value), _empty_stat_entry())
                entry["appearances"] += 1
                entry["weighted_appearances"] += weight

    for row in conn.execute(
        f"SELECT id, campaign_cycle_id, reason_code, fingerprint_json FROM adoption_decision"
        f" WHERE brand_id = %s AND decision = 'rejected' AND campaign_cycle_id IN ({placeholders})",
        (brand_id, *cycle_ids),
    ):
        axis = fp.REASON_TO_AXIS.get(row["reason_code"])
        if axis is None:
            continue  # 資料錯誤類的理由不升級成風格規則
        value = (row["fingerprint_json"] or {}).get(axis)
        if not value:
            continue
        weight = weight_by_cycle.get(row["campaign_cycle_id"], 1.0)
        entry = stats.setdefault((axis, value), _empty_stat_entry())
        entry["rejections"] += 1
        entry["weighted_rejections"] += weight
        if row["reason_code"] in fp.RULE_UPGRADABLE_REASONS:
            entry["policy_rejections"] += 1
            entry["weighted_policy_rejections"] += weight
        entry["ids"].append(row["id"])
        entry["reasons"].add(row["reason_code"])
        if entry["appearances"] < entry["rejections"]:
            entry["appearances"] = entry["rejections"]
        if entry["weighted_appearances"] < entry["weighted_rejections"]:
            entry["weighted_appearances"] = entry["weighted_rejections"]

    return stats


def _rule_card_verdict(stats: dict, axis: str, value: str) -> str:
    """這個 (軸, 值) 現在算「insufficient」（連觀察都不夠格）、「observing」（觀察中，
    只顯示不進 prompt）還是「pending」（達門檻，可以升級成候選卡）。三段判準（票 T1，
    使用者 2026-08-06 拍板）：

    1. 政策拒絕次數（`policy_rejections`，只算 off_brand／discount_too_deep 這類使用者
       自己的政策）達門檻、出現次數達門檻，且政策拒絕比例明顯高於同軸其他值的政策拒絕
       比例 → pending，可以升級成永久禁令。
    2. 否則，只要總拒絕次數（`rejections`，含猜消費者反應的品味理由）達門檻、出現次數
       達門檻 → observing。這段是「永遠停在觀察中」得以成立的關鍵：純品味訊號的
       `policy_rejections` 恆為 0，若只看政策次數會直接掉回 insufficient、從畫面上消失。
    3. 否則 → insufficient，連觀察都不夠格。

    門檻比較一律讀 `weighted_*` 鍵（票 02-occasion-weighted-recommendations，ADR 0011
    第五節：跟這次檔期同場合的歷史資料權重加重、不同場合較低但仍參與），不是真實次數——
    真實次數只給使用者看的顯示欄位用，見 `_axis_value_stats()` docstring。
    """
    entry = stats.get((axis, value), _empty_stat_entry())
    appearances = entry["weighted_appearances"]
    policy_rejections = entry["weighted_policy_rejections"]

    if policy_rejections >= RULE_CARD_MIN_REJECTIONS and appearances >= RULE_CARD_MIN_SAMPLES:
        other_policy = sum(e["weighted_policy_rejections"] for (a, v), e in stats.items()
                           if a == axis and v != value)
        other_appearances = sum(e["weighted_appearances"] for (a, v), e in stats.items()
                                if a == axis and v != value)
        # 沒有其他值可比較時（例如新品牌剛開始），視為門檻自動通過——baseline 比較
        # 一律只用政策次數，跟上面判準的口徑一致。
        if other_appearances == 0:
            return "pending"
        baseline = other_policy / other_appearances
        if (policy_rejections / appearances) >= baseline * RULE_CARD_RELATIVE_MULTIPLIER:
            return "pending"

    if entry["weighted_rejections"] >= RULE_CARD_MIN_REJECTIONS and appearances >= RULE_CARD_MIN_SAMPLES:
        return "observing"
    return "insufficient"


def build_rule_cards(conn, brand_id: str, actor: str, cycle_id: Optional[str] = None) -> int:
    """統計拒絕紀錄，把達相對門檻的指紋標籤變成候選規則卡。回傳新增張數。

    純程式統計，不經 LLM——「被退幾次、比例高不高」是數數，不是判斷。

    修憲落地 G3（決策 0035 第5點）：改成相對判準（該軸值出現過幾次、拒絕比例是否明顯
    高於同軸其他值）＋時間窗（只算最近 `RULE_CARD_WINDOW_CYCLES` 期），不再只看絕對次數；
    達門檻前先降級為「觀察中」（見 `list_observing_signals`），只顯示不進 prompt。

    票 T1（決策 2026-08-06）：相對門檻自此只適用政策類理由（`fp.RULE_UPGRADABLE_REASONS`
    白名單內的 off_brand／discount_too_deep）——猜消費者反應的三條理由（too_stiff、
    too_ad_like、hook_weak）不論被拒幾次、比例多高，都不會被這裡升級成 pending，永遠
    停在「觀察中」。

    `cycle_id`（票 02-occasion-weighted-recommendations，ADR 0011 第五節）：正在準備下期
    建議的那個檔期，`build()` 呼叫時會傳入，讀它的 `occasion` 欄位加權比較歷史拒絕紀錄。
    省略時（例如累積智慧頁的品牌整體統計，沒有「下期」這個概念）不加權，等同現行比較。
    """
    cycle_ids = _recent_cycle_ids(conn, brand_id, RULE_CARD_WINDOW_CYCLES)
    current_occasion = None
    if cycle_id:
        current_cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
        current_occasion = current_cycle.get("occasion") if current_cycle else None
    stats = _axis_value_stats(conn, brand_id, cycle_ids, current_occasion)

    created = 0
    ts = now_utc()
    for (axis, value), entry in stats.items():
        if _rule_card_verdict(stats, axis, value) != "pending":
            continue
        existing = conn.execute(
            "SELECT id, status FROM creative_rule_card WHERE brand_id = %s AND fingerprint_axis = %s"
            " AND fingerprint_value = %s", (brand_id, axis, value),
        ).fetchone()
        if existing:
            # 已經決定過的不再打擾；還沒決定的更新次數
            if existing["status"] == "pending":
                conn.execute(
                    "UPDATE creative_rule_card SET reject_count = %s, evidence_json = %s,"
                    " updated_at = %s WHERE id = %s",
                    (entry["rejections"],
                     jsonb({"decision_ids": entry["ids"],
                            "reasons": sorted(entry["reasons"])}),
                     ts, existing["id"]),
                )
            continue

        label = fp.axis_value_label(axis, value)
        conn.execute(
            "INSERT INTO creative_rule_card (id, org_id, brand_id, fingerprint_axis, fingerprint_value,"
            " proposed_rule_text, evidence_json, reject_count, status, created_at, updated_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s)",
            (new_id("rcd"), DEV_ORG_ID, brand_id, axis, value,
             f"以後不要再出「{fp.AXES[axis]['label']}是{label}」的素材",
             jsonb({"decision_ids": entry["ids"],
                    "reasons": sorted(entry["reasons"])}),
             entry["rejections"], ts, ts),
        )
        created += 1

    if created:
        write_audit(conn, brand_id=brand_id, entity_type="creative_rule_card",
                    entity_id=brand_id, action="propose_rule_cards", actor=actor,
                    before=None, after={"created": created})
    conn.commit()
    return created


def list_observing_signals(conn, brand_id: str) -> list:
    """還沒達到規則卡門檻、但已經有幾次被拒的軸值——只顯示讓使用者心裡有數，
    不產生候選卡、不進 context_compiler 組出的 prompt（決策 0035 第5點：達門檻前先降級
    為「觀察中」）。不落地成資料表列——純粹依當下資料即時算，跟人工決策無關，沒有
    「決定」這個動作可言，不必是一筆持久的紀錄。"""
    cycle_ids = _recent_cycle_ids(conn, brand_id, RULE_CARD_WINDOW_CYCLES)
    stats = _axis_value_stats(conn, brand_id, cycle_ids)
    signals = []
    for (axis, value), entry in stats.items():
        if _rule_card_verdict(stats, axis, value) != "observing":
            continue
        signals.append({
            "axis_label": fp.AXES[axis]["label"],
            "value_label": fp.axis_value_label(axis, value),
            "reject_count": entry["rejections"],
            "appearances": entry["appearances"],
        })
    return signals


def build_overclaim_claim_cards(conn, brand_id: str, actor: str) -> int:
    """`overclaim`（講得太滿）累積到門檻 → 為每一則還沒處理過的踩線素材各產一張候選卡
    （修憲落地 L4，決策 0034 第 8 點）：AI 自己已經寫出來的那句話直接當草稿，
    使用者按一下「登記」就直接寫進 claim（禁用宣稱），不必自己打字。

    維持決策 0030 第 6 點的切分——`overclaim` 不升級成風格禁令，本函式只補「該走
    claim 層」那條路，不碰 `fp.REASON_TO_AXIS["overclaim"] = None`。

    門檻沿用 RULE_CARD_THRESHOLD：一次可能只是那句寫得爛，累積到第二次才值得讓
    使用者決定要不要正式登記。回傳新增張數。
    """
    rows = conn.execute(
        "SELECT id, target_id FROM adoption_decision WHERE brand_id = %s AND decision = 'rejected'"
        " AND reason_code = 'overclaim'", (brand_id,),
    ).fetchall()
    if len(rows) < RULE_CARD_THRESHOLD:
        return 0

    from app.ads import creative as ads_creative

    created = 0
    ts = now_utc()
    for row in rows:
        variant_id = row["target_id"]
        existing = conn.execute(
            "SELECT id FROM creative_rule_card WHERE brand_id = %s AND fingerprint_axis = %s"
            " AND fingerprint_value = %s", (brand_id, OVERCLAIM_CLAIM_AXIS, variant_id),
        ).fetchone()
        if existing:
            continue  # 已經產過候選卡（或使用者已經決定過），不重複打擾
        variant = ads_creative.get_variant(conn, brand_id, variant_id)
        if not variant or not variant.get("content"):
            continue  # 素材被刪或內容是空的，沒有東西可以登記
        conn.execute(
            "INSERT INTO creative_rule_card (id, org_id, brand_id, product_id, fingerprint_axis,"
            " fingerprint_value, proposed_rule_text, evidence_json, reject_count, status,"
            " created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1, 'pending', %s, %s)",
            (new_id("rcd"), DEV_ORG_ID, brand_id, variant.get("product_id"), OVERCLAIM_CLAIM_AXIS, variant_id,
             variant["content"],
             jsonb({"decision_id": row["id"], "variant_id": variant_id}),
             ts, ts),
        )
        created += 1

    if created:
        write_audit(conn, brand_id=brand_id, entity_type="creative_rule_card",
                    entity_id=brand_id, action="propose_overclaim_claim_cards", actor=actor,
                    before=None, after={"created": created})
        conn.commit()
    return created


def _is_self_reported(row: dict) -> bool:
    """這張卡是使用者在前朝教訓訪談自述的，還是系統數出來的？

    自述卡的 `reject_count` 固定是 0（見 `app/ads/interview.py`），畫面若照著印
    會變成「你退過 0 次」這種自打嘴巴的句子，所以要分得出來。判斷靠 `evidence_json`
    的來源標記，不靠 `reject_count == 0` 猜——那是巧合成立，不是保證。
    """
    return (row.get("evidence_json") or {}).get("source") == "self_report"


def list_pending_rule_cards(conn, brand_id: str) -> list:
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM creative_rule_card WHERE brand_id = %s AND status = 'pending'"
        " ORDER BY reject_count DESC, created_at", (brand_id,),
    )]
    for row in rows:
        row["is_overclaim_claim"] = row["fingerprint_axis"] == OVERCLAIM_CLAIM_AXIS
        row["axis_label"] = fp.AXES.get(row["fingerprint_axis"], {}).get("label",
                                                                        row["fingerprint_axis"])
        row["value_label"] = fp.axis_value_label(row["fingerprint_axis"],
                                                 row["fingerprint_value"])
        row["self_reported"] = _is_self_reported(row)
    return rows


def list_active_bans(conn, brand_id: str) -> list:
    """現行生效中的禁令：規則卡已被人接受、且升級後的品牌智庫規則目前仍是 active 狀態。

    累積智慧頁「生效中的禁令」區塊用這份清單顯示、也讓使用者可以手動下架。判斷「規則是否
    還生效」沿用既有的 `bi.get_rule`（不自己寫查詢跨表 join），停用規則後（#56）這裡會
    自動跟著排除。
    """
    from app.brand_intelligence import repository as bi

    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM creative_rule_card WHERE brand_id = %s AND status = 'accepted'"
        " ORDER BY decided_at DESC", (brand_id,),
    )]
    bans = []
    for row in rows:
        rule = bi.get_rule(conn, brand_id, row["promoted_rule_id"]) if row["promoted_rule_id"] else None
        if rule is None or rule["status"] != "active":
            continue
        row["axis_label"] = fp.AXES.get(row["fingerprint_axis"], {}).get("label",
                                                                        row["fingerprint_axis"])
        row["value_label"] = fp.axis_value_label(row["fingerprint_axis"], row["fingerprint_value"])
        row["self_reported"] = _is_self_reported(row)
        bans.append(row)
    return bans


def decide_rule_card(conn, brand_id: str, card_id: str, *, accept: bool, actor: str) -> dict:
    """使用者對規則卡的決定。只有兩種候選卡目的地（票 T1 拿掉了曾經存在過的第三種方向，
    見 docs/adr/0007），靠 `fingerprint_axis` 是否等於 `OVERCLAIM_CLAIM_AXIS` 分辨：

    - **候選禁令卡**：接受升級為品牌智庫的長期 tone 規則（`promoted_rule_id` 寫入新規則 id）。
    - **overclaim 候選卡**：接受直接寫進 claim（禁用宣稱），不是升級成 rule。
    """
    row = conn.execute(
        "SELECT * FROM creative_rule_card WHERE brand_id = %s AND id = %s", (brand_id, card_id),
    ).fetchone()
    if row is None:
        raise ValueError("找不到這張規則卡")

    from app.brand_intelligence import repository as bi
    ts = now_utc()
    is_overclaim_claim = row["fingerprint_axis"] == OVERCLAIM_CLAIM_AXIS

    if is_overclaim_claim:
        # 接受＝直接寫進 claim（禁用宣稱），不是升級成 rule——這是決策 0034 第 8 點要補的
        # 那條「該走 claim 層」的路，跟下面 tone 規則的分支是兩種不同的目的地。
        # `promoted_rule_id` 刻意留空：這裡產生的是 claim_id 不是 rule_id，寫進去會被
        # `list_active_bans` 誤當成規則去查（查不到就自然跳過，不會壞，但語意不對），
        # claim_id 另外存進 evidence_json 供稽核追溯。
        claim_id = None
        if accept:
            claim = bi.create_claim(conn, brand_id, actor=actor,
                                    claim_text=row["proposed_rule_text"], claim_type="forbidden",
                                    product_id=row["product_id"])
            claim_id = claim["id"]
            # dict()：row["evidence_json"] 是 psycopg 直接解出的物件，不拷貝就地改會連帶
            # 動到下面 write_audit(before=dict(row)) 要用的「改之前」快照（02-3b）。
            evidence = dict(row["evidence_json"] or {})
            evidence["claim_id"] = claim_id
            conn.execute(
                "UPDATE creative_rule_card SET status = 'accepted', evidence_json = %s,"
                " decided_by = %s, decided_at = %s, updated_at = %s WHERE id = %s",
                (jsonb(evidence), actor, ts, ts, card_id),
            )
        else:
            conn.execute(
                "UPDATE creative_rule_card SET status = 'declined', decided_by = %s,"
                " decided_at = %s, updated_at = %s WHERE id = %s",
                (actor, ts, ts, card_id),
            )
        after = {"claim_id": claim_id}
    else:
        rule_id = None
        if accept:
            rule = bi.create_rule(conn, brand_id, rule_type="tone",
                                  content=row["proposed_rule_text"], severity="soft", actor=actor)
            rule_id = rule["id"]
        conn.execute(
            "UPDATE creative_rule_card SET status = %s, promoted_rule_id = %s, decided_by = %s,"
            " decided_at = %s, updated_at = %s WHERE id = %s",
            ("accepted" if accept else "declined", rule_id, actor, ts, ts, card_id),
        )
        after = {"promoted_rule_id": rule_id}

    write_audit(conn, brand_id=brand_id, entity_type="creative_rule_card", entity_id=card_id,
                action="accept_rule_card" if accept else "decline_rule_card", actor=actor,
                before=dict(row), after=after)
    conn.commit()
    return dict(conn.execute("SELECT * FROM creative_rule_card WHERE id = %s",
                             (card_id,)).fetchone())


# ---------------------------------------------------------------------------
# 反回音室
# ---------------------------------------------------------------------------

def adopted_fingerprints(conn, brand_id: str, exclude_cycle_id: Optional[str] = None) -> list:
    """這個品牌歷來採用過的素材指紋（比對基準），附上來源檔期 id——情境加權比較
    （票 02-occasion-weighted-recommendations，ADR 0011 第五節）要知道每筆歷史素材是
    哪一期採用的，才能跟這次檔期比對場合。回傳 `(fingerprint, campaign_cycle_id)` tuple 列表。
    """
    sql = ("SELECT campaign_cycle_id, fingerprint_json FROM adoption_decision WHERE brand_id = %s"
           " AND decision = 'adopted'")
    params = [brand_id]
    if exclude_cycle_id:
        sql += " AND (campaign_cycle_id IS NULL OR campaign_cycle_id != %s)"
        params.append(exclude_cycle_id)
    prints = []
    for row in conn.execute(sql, params):
        data = row["fingerprint_json"]
        if data:
            prints.append((data, row["campaign_cycle_id"]))
    return prints


def check_echo_chamber(conn, brand_id: str, cycle_id: str) -> Optional[guardrails.Finding]:
    """本期素材是不是在重複過去。太像就回一條提示（不擋路），否則回 None。

    跟這次檔期同場合的歷史採用素材權重加重、不同場合的較低但仍參與比較
    （票 02-occasion-weighted-recommendations，ADR 0011 第五節）。
    """
    from app.ads import creative as ads_creative

    candidates = [v["fingerprint"] for v in ads_creative.list_variants(conn, brand_id, cycle_id)
                  if not v["rejected"] and v["fingerprint"]]
    history_rows = adopted_fingerprints(conn, brand_id, exclude_cycle_id=cycle_id)
    if not candidates or not history_rows:
        return None

    history = [fingerprint for fingerprint, _ in history_rows]
    current_cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    current_occasion = current_cycle.get("occasion") if current_cycle else None
    weight_by_cycle = _occasion_weight_map(
        conn, [source_cycle_id for _, source_cycle_id in history_rows], current_occasion)
    weights = [weight_by_cycle.get(source_cycle_id, 1.0) for _, source_cycle_id in history_rows]

    ratio = fp.echo_chamber_ratio(candidates, history, weights)
    if ratio < 0.6:
        return None
    return guardrails.Finding(
        finding_type="echo_chamber",
        code="creatives_too_similar",
        severity="info",
        message=(f"這批素材有 {ratio:.0%} 跟過去用過的很像。"
                 "AI 讀自己上期的產出容易越轉越像自己，下期會刻意留一組不一樣的來試。"),
        source="pure_function",
        confidence_penalty=0.0,
        evidence={"ratio": ratio, "candidates": len(candidates), "history": len(history)},
    )


# ---------------------------------------------------------------------------
# 下期草案
# ---------------------------------------------------------------------------

def build(conn, brand_id: str, cycle_id: str, actor: str) -> dict:
    """判讀之後一次把下期該準備的都備好：預算建議、規則卡、回音室檢查。"""
    budget = propose_budget(conn, brand_id, cycle_id)
    cards = build_rule_cards(conn, brand_id, actor, cycle_id=cycle_id)
    overclaim_cards = build_overclaim_claim_cards(conn, brand_id, actor)

    echo = check_echo_chamber(conn, brand_id, cycle_id)
    ads_repo.replace_findings(conn, brand_id, cycle_id, "echo_chamber",
                              [echo] if echo else [])

    # needs_revalidation 到期重測（修憲落地 G4，決策 0035 第三節第 10 點）：判讀完成順手
    # 檢查一次有沒有學習條目掛滿幾期沒被重新驗證，跟規則卡／回音室一樣是「下期準備」的一環。
    stale_learnings = ads_reading.mark_stale_learnings_for_revalidation(conn, brand_id)

    verdict = ads_reading.load(conn, brand_id, cycle_id)
    content = {
        "budget": budget,
        "rule_cards_created": cards,
        "overclaim_claim_cards_created": overclaim_cards,
        "echo_chamber": bool(echo),
        "learnings_flagged_for_revalidation": stale_learnings,
        "per_product": [
            {"product_name": row["product_name"], "status": row["status"],
             "status_label": row["status_label"]}
            for row in verdict["products"]
        ],
        # 樣本可信門檻與零轉換警示（票 03-sample-trust-threshold）：歷來每個切角附加誠實旗標，
        # 不排除任何切角，只是附加資訊供使用者判斷要不要下期沿用。
        "historical_cells": historical_cell_performance(conn, brand_id, exclude_cycle_id=cycle_id),
    }

    ts = now_utc()
    conn.execute(
        "DELETE FROM recommendation WHERE brand_id = %s AND campaign_cycle_id = %s"
        " AND recommendation_type = 'next_cycle'", (brand_id, cycle_id),
    )
    conn.execute(
        "INSERT INTO recommendation (id, org_id, brand_id, campaign_cycle_id,"
        " performance_reading_id, recommendation_type, content_json, status,"
        " created_at, updated_at) VALUES (%s, %s, %s, %s, %s, 'next_cycle', %s, 'GENERATED', %s, %s)",
        (new_id("rec"), DEV_ORG_ID, brand_id, cycle_id,
         (verdict["cycle"] or {}).get("id"),
         jsonb(content), ts, ts),
    )
    conn.commit()
    return content


def load(conn, brand_id: str, cycle_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM recommendation WHERE brand_id = %s AND campaign_cycle_id = %s"
        " AND recommendation_type = 'next_cycle' ORDER BY created_at DESC LIMIT 1",
        (brand_id, cycle_id),
    ).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["content"] = data["content_json"] or {}
    return data
