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

import json
from typing import Optional

from app.ads import fingerprint as fp
from app.ads import guardrails
from app.ads import reading as ads_reading
from app.ads import repository as ads_repo
from app.core.audit import write_audit
from app.core.db import new_id, now_iso

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
        " WHERE brand_id = ? AND campaign_cycle_id = ? AND quarantined = 0",
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
# 規則卡
# ---------------------------------------------------------------------------

def _recent_cycle_ids(conn, brand_id: str, window: int) -> list:
    """最近幾期的 cycle id（依建立時間新到舊）——規則卡相對判準的時間窗。"""
    rows = conn.execute(
        "SELECT id FROM campaign_cycle WHERE brand_id = ? ORDER BY created_at DESC LIMIT ?",
        (brand_id, window),
    ).fetchall()
    return [r["id"] for r in rows]


def _empty_stat_entry() -> dict:
    return {"appearances": 0, "rejections": 0, "policy_rejections": 0, "ids": [], "reasons": set()}


def _axis_value_stats(conn, brand_id: str, cycle_ids: list) -> dict:
    """視窗內每個 (軸, 值) 出現過幾次、被拒幾次（含拆分出的政策拒絕次數）——相對判準的
    分子分母來源。

    出現次數（分母）以 `creative_variant` 的指紋為準，不論這則變體最後有沒有被拒；
    這是修憲落地 G1 抓到的原始缺陷（「只數分子不數分母」）的直接對症：分子單獨看
    起來再高，只要分母也高、比例不特別突出，就不該鑄成禁令。若一筆拒絕紀錄找不到
    對應的變體列（例如舊資料），至少把這次拒絕本身算成一次出現，分母不能比分子還小。

    `rejections` 是總拒絕次數（含猜消費者反應的品味理由），`policy_rejections` 只算
    `reason_code` 落在 `fp.RULE_UPGRADABLE_REASONS` 白名單內的次數（票 T1）——升級成
    永久禁令只看後者，「觀察中」判準看前者。
    """
    if not cycle_ids:
        return {}
    placeholders = ",".join("?" for _ in cycle_ids)
    stats: dict = {}

    for row in conn.execute(
        f"SELECT fingerprint_json FROM creative_variant"
        f" WHERE brand_id = ? AND campaign_cycle_id IN ({placeholders})",
        (brand_id, *cycle_ids),
    ):
        try:
            raw = json.loads(row["fingerprint_json"]) if row["fingerprint_json"] else {}
        except ValueError:
            continue
        for axis, value in fp.normalize(raw).items():
            stats.setdefault((axis, value), _empty_stat_entry())
            stats[(axis, value)]["appearances"] += 1

    for row in conn.execute(
        f"SELECT id, reason_code, fingerprint_json FROM adoption_decision"
        f" WHERE brand_id = ? AND decision = 'rejected' AND campaign_cycle_id IN ({placeholders})",
        (brand_id, *cycle_ids),
    ):
        axis = fp.REASON_TO_AXIS.get(row["reason_code"])
        if axis is None:
            continue  # 資料錯誤類的理由不升級成風格規則
        try:
            value = (json.loads(row["fingerprint_json"] or "{}") or {}).get(axis)
        except ValueError:
            continue
        if not value:
            continue
        entry = stats.setdefault((axis, value), _empty_stat_entry())
        entry["rejections"] += 1
        if row["reason_code"] in fp.RULE_UPGRADABLE_REASONS:
            entry["policy_rejections"] += 1
        entry["ids"].append(row["id"])
        entry["reasons"].add(row["reason_code"])
        if entry["appearances"] < entry["rejections"]:
            entry["appearances"] = entry["rejections"]

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
    """
    entry = stats.get((axis, value), _empty_stat_entry())
    appearances = entry["appearances"]
    policy_rejections = entry["policy_rejections"]

    if policy_rejections >= RULE_CARD_MIN_REJECTIONS and appearances >= RULE_CARD_MIN_SAMPLES:
        other_policy = sum(e["policy_rejections"] for (a, v), e in stats.items()
                           if a == axis and v != value)
        other_appearances = sum(e["appearances"] for (a, v), e in stats.items()
                                if a == axis and v != value)
        # 沒有其他值可比較時（例如新品牌剛開始），視為門檻自動通過——baseline 比較
        # 一律只用政策次數，跟上面判準的口徑一致。
        if other_appearances == 0:
            return "pending"
        baseline = other_policy / other_appearances
        if (policy_rejections / appearances) >= baseline * RULE_CARD_RELATIVE_MULTIPLIER:
            return "pending"

    if entry["rejections"] >= RULE_CARD_MIN_REJECTIONS and appearances >= RULE_CARD_MIN_SAMPLES:
        return "observing"
    return "insufficient"


def build_rule_cards(conn, brand_id: str, actor: str) -> int:
    """統計拒絕紀錄，把達相對門檻的指紋標籤變成候選規則卡。回傳新增張數。

    純程式統計，不經 LLM——「被退幾次、比例高不高」是數數，不是判斷。

    修憲落地 G3（決策 0035 第5點）：改成相對判準（該軸值出現過幾次、拒絕比例是否明顯
    高於同軸其他值）＋時間窗（只算最近 `RULE_CARD_WINDOW_CYCLES` 期），不再只看絕對次數；
    達門檻前先降級為「觀察中」（見 `list_observing_signals`），只顯示不進 prompt。

    票 T1（決策 2026-08-06）：相對門檻自此只適用政策類理由（`fp.RULE_UPGRADABLE_REASONS`
    白名單內的 off_brand／discount_too_deep）——猜消費者反應的三條理由（too_stiff、
    too_ad_like、hook_weak）不論被拒幾次、比例多高，都不會被這裡升級成 pending，永遠
    停在「觀察中」。
    """
    cycle_ids = _recent_cycle_ids(conn, brand_id, RULE_CARD_WINDOW_CYCLES)
    stats = _axis_value_stats(conn, brand_id, cycle_ids)

    created = 0
    ts = now_iso()
    for (axis, value), entry in stats.items():
        if _rule_card_verdict(stats, axis, value) != "pending":
            continue
        existing = conn.execute(
            "SELECT id, status FROM creative_rule_card WHERE brand_id = ? AND fingerprint_axis = ?"
            " AND fingerprint_value = ?", (brand_id, axis, value),
        ).fetchone()
        if existing:
            # 已經決定過的不再打擾；還沒決定的更新次數
            if existing["status"] == "pending":
                conn.execute(
                    "UPDATE creative_rule_card SET reject_count = ?, evidence_json = ?,"
                    " updated_at = ? WHERE id = ?",
                    (entry["rejections"],
                     json.dumps({"decision_ids": entry["ids"],
                                 "reasons": sorted(entry["reasons"])}, ensure_ascii=False),
                     ts, existing["id"]),
                )
            continue

        label = fp.axis_value_label(axis, value)
        conn.execute(
            "INSERT INTO creative_rule_card (id, brand_id, fingerprint_axis, fingerprint_value,"
            " proposed_rule_text, evidence_json, reject_count, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
            (new_id("rcd"), brand_id, axis, value,
             f"以後不要再出「{fp.AXES[axis]['label']}是{label}」的素材",
             json.dumps({"decision_ids": entry["ids"],
                         "reasons": sorted(entry["reasons"])}, ensure_ascii=False),
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
        "SELECT id, target_id FROM adoption_decision WHERE brand_id = ? AND decision = 'rejected'"
        " AND reason_code = 'overclaim'", (brand_id,),
    ).fetchall()
    if len(rows) < RULE_CARD_THRESHOLD:
        return 0

    from app.ads import creative as ads_creative

    created = 0
    ts = now_iso()
    for row in rows:
        variant_id = row["target_id"]
        existing = conn.execute(
            "SELECT id FROM creative_rule_card WHERE brand_id = ? AND fingerprint_axis = ?"
            " AND fingerprint_value = ?", (brand_id, OVERCLAIM_CLAIM_AXIS, variant_id),
        ).fetchone()
        if existing:
            continue  # 已經產過候選卡（或使用者已經決定過），不重複打擾
        variant = ads_creative.get_variant(conn, brand_id, variant_id)
        if not variant or not variant.get("content"):
            continue  # 素材被刪或內容是空的，沒有東西可以登記
        conn.execute(
            "INSERT INTO creative_rule_card (id, brand_id, product_id, fingerprint_axis,"
            " fingerprint_value, proposed_rule_text, evidence_json, reject_count, status,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'pending', ?, ?)",
            (new_id("rcd"), brand_id, variant.get("product_id"), OVERCLAIM_CLAIM_AXIS, variant_id,
             variant["content"],
             json.dumps({"decision_id": row["id"], "variant_id": variant_id}, ensure_ascii=False),
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
    try:
        return (json.loads(row.get("evidence_json") or "{}") or {}).get("source") == "self_report"
    except ValueError:
        return False


def list_pending_rule_cards(conn, brand_id: str) -> list:
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM creative_rule_card WHERE brand_id = ? AND status = 'pending'"
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
        "SELECT * FROM creative_rule_card WHERE brand_id = ? AND status = 'accepted'"
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
        "SELECT * FROM creative_rule_card WHERE brand_id = ? AND id = ?", (brand_id, card_id),
    ).fetchone()
    if row is None:
        raise ValueError("找不到這張規則卡")

    from app.brand_intelligence import repository as bi
    ts = now_iso()
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
            evidence = json.loads(row["evidence_json"] or "{}")
            evidence["claim_id"] = claim_id
            conn.execute(
                "UPDATE creative_rule_card SET status = 'accepted', evidence_json = ?,"
                " decided_by = ?, decided_at = ?, updated_at = ? WHERE id = ?",
                (json.dumps(evidence, ensure_ascii=False), actor, ts, ts, card_id),
            )
        else:
            conn.execute(
                "UPDATE creative_rule_card SET status = 'declined', decided_by = ?,"
                " decided_at = ?, updated_at = ? WHERE id = ?",
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
            "UPDATE creative_rule_card SET status = ?, promoted_rule_id = ?, decided_by = ?,"
            " decided_at = ?, updated_at = ? WHERE id = ?",
            ("accepted" if accept else "declined", rule_id, actor, ts, ts, card_id),
        )
        after = {"promoted_rule_id": rule_id}

    write_audit(conn, brand_id=brand_id, entity_type="creative_rule_card", entity_id=card_id,
                action="accept_rule_card" if accept else "decline_rule_card", actor=actor,
                before=dict(row), after=after)
    conn.commit()
    return dict(conn.execute("SELECT * FROM creative_rule_card WHERE id = ?",
                             (card_id,)).fetchone())


# ---------------------------------------------------------------------------
# 反回音室
# ---------------------------------------------------------------------------

def adopted_fingerprints(conn, brand_id: str, exclude_cycle_id: Optional[str] = None) -> list:
    """這個品牌歷來採用過的素材指紋（比對基準）。"""
    sql = ("SELECT fingerprint_json FROM adoption_decision WHERE brand_id = ?"
           " AND decision = 'adopted'")
    params = [brand_id]
    if exclude_cycle_id:
        sql += " AND (campaign_cycle_id IS NULL OR campaign_cycle_id != ?)"
        params.append(exclude_cycle_id)
    prints = []
    for row in conn.execute(sql, params):
        try:
            data = json.loads(row["fingerprint_json"] or "{}")
        except ValueError:
            continue
        if data:
            prints.append(data)
    return prints


def check_echo_chamber(conn, brand_id: str, cycle_id: str) -> Optional[guardrails.Finding]:
    """本期素材是不是在重複過去。太像就回一條提示（不擋路），否則回 None。"""
    from app.ads import creative as ads_creative

    candidates = [v["fingerprint"] for v in ads_creative.list_variants(conn, brand_id, cycle_id)
                  if not v["rejected"] and v["fingerprint"]]
    history = adopted_fingerprints(conn, brand_id, exclude_cycle_id=cycle_id)
    if not candidates or not history:
        return None

    ratio = fp.echo_chamber_ratio(candidates, history)
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
    cards = build_rule_cards(conn, brand_id, actor)
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
    }

    ts = now_iso()
    conn.execute(
        "DELETE FROM recommendation WHERE brand_id = ? AND campaign_cycle_id = ?"
        " AND recommendation_type = 'next_cycle'", (brand_id, cycle_id),
    )
    conn.execute(
        "INSERT INTO recommendation (id, brand_id, campaign_cycle_id,"
        " performance_reading_id, recommendation_type, content_json, status,"
        " created_at, updated_at) VALUES (?, ?, ?, ?, 'next_cycle', ?, 'GENERATED', ?, ?)",
        (new_id("rec"), brand_id, cycle_id,
         (verdict["cycle"] or {}).get("id"),
         json.dumps(content, ensure_ascii=False), ts, ts),
    )
    conn.commit()
    return content


def load(conn, brand_id: str, cycle_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM recommendation WHERE brand_id = ? AND campaign_cycle_id = ?"
        " AND recommendation_type = 'next_cycle' ORDER BY created_at DESC LIMIT 1",
        (brand_id, cycle_id),
    ).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["content"] = json.loads(data["content_json"] or "{}")
    return data
