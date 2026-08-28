"""app/ads/interview.py — 前朝教訓訪談（點選式三分流，GitHub issue #55）。

老品牌第一天就能把既有經驗交給系統：一次性點選式訪談，選項直接用票 #52 定版的四軸值
（`app.ads.fingerprint.AXES`），問「過去哪種切角／語氣／形式／賣點試過不行」與「哪種有效」。

答案依性質三分流（決策 0030 第 12 點），**一律不進 `learning_ledger`**——
ledger 只收經判讀驗證且經人確認的結論，訪談自述屬未驗證內容：

- 「試過不行」（負面）→ 候選規則卡（`creative_rule_card`，`reject_count=0`，
  `evidence_json` 標明來源為使用者自述）。使用者確認後才升級為 `rule`，
  走既有的 `nextcycle.decide_rule_card`（規則卡歸屬不因來源是統計還是自述而不同）。
- 「這個有效」（正面）→ 策略假設（`strategy_hypothesis`，status=proposed、
  `created_by`＝使用者、`source_cycle_id` 留空），下一期開期時由
  `attach_pending_hypotheses` 自動掛進 `campaign_cycle_hypothesis` 接受驗證。
- 兩者皆非的自由補充文字 → 只存進 `audit_log`，不進 prompt、不升級任何東西。

全程選填：`bad`／`good` 任何軸都可以不勾，補充文字可留空——跳過不擋任何流程（決策 0025）。
"""


from app.ads import fingerprint as fp
from app.brand_intelligence import repository as bi
from app.core.audit import write_audit
from app.core.db import DEV_ORG_ID, jsonb, new_id, now_utc


def _clean_selection(raw: dict | None) -> dict:
    """把表單送來的 {axis: [value, ...]} 收斂成合法值；非法軸／值直接丟棄
    （壞資料寧可不存，也不要汙染統計，同 fingerprint.is_valid 的原則）。"""
    cleaned: dict = {}
    for axis, values in (raw or {}).items():
        if axis not in fp.AXES:
            continue
        valid = [v for v in (values or []) if v in fp.AXES[axis]["values"]]
        if valid:
            cleaned[axis] = valid
    return cleaned


def _drop_conflicts(bad: dict, good: dict) -> list:
    """同一個軸值兩邊都勾了（既「試過不行」又「這個有效」）＝互相矛盾，兩邊都不採納。

    不採納而不是替使用者挑一邊：勾兩邊多半是手滑或會意錯，系統自作主張挑一邊，
    等於拿沒把握的資料去產禁令或假設，兩者都會跑到人面前要確認，錯了更難回收。
    回傳被剔除的項目（人話標籤）給呼叫端誠實告知，不擋送出（決策 0025 懶人優先）。
    """
    dropped = []
    for axis in list(bad):
        overlap = [v for v in bad[axis] if v in good.get(axis, [])]
        for value in overlap:
            bad[axis] = [v for v in bad[axis] if v != value]
            good[axis] = [v for v in good[axis] if v != value]
            dropped.append(f"{fp.AXES[axis]['label']}的「{fp.axis_value_label(axis, value)}」")
        if not bad[axis]:
            del bad[axis]
        if axis in good and not good[axis]:
            del good[axis]
    return dropped


def _create_self_report_card(conn, brand_id: str, axis: str, value: str, *, actor: str) -> dict | None:
    """自述負面 → 候選規則卡。同一軸值已經有候選卡（不論待決或已決）就不重複造。"""
    existing = conn.execute(
        "SELECT id FROM creative_rule_card WHERE brand_id = %s AND fingerprint_axis = %s"
        " AND fingerprint_value = %s", (brand_id, axis, value),
    ).fetchone()
    if existing is not None:
        return None

    label = fp.axis_value_label(axis, value)
    row_id = new_id("rcd")
    ts = now_utc()
    proposed_text = f"以後不要再出「{fp.AXES[axis]['label']}是{label}」的素材"
    evidence = jsonb({"source": "self_report"})
    conn.execute(
        "INSERT INTO creative_rule_card (id, org_id, brand_id, fingerprint_axis, fingerprint_value,"
        " proposed_rule_text, evidence_json, reject_count, status, created_at, updated_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 'pending', %s, %s)",
        (row_id, DEV_ORG_ID, brand_id, axis, value, proposed_text, evidence, ts, ts),
    )
    row = dict(conn.execute("SELECT * FROM creative_rule_card WHERE id = %s", (row_id,)).fetchone())
    write_audit(conn, brand_id=brand_id, entity_type="creative_rule_card", entity_id=row_id,
                action="self_report", actor=actor, before=None, after=row)
    return row


def submit(conn, brand_id: str, *, bad: dict | None, good: dict | None,
           note: str | None, actor: str) -> dict:
    """處理一次訪談送出，回傳 {"rule_cards": [...], "hypotheses": [...]} 供結果頁顯示這次記了什麼。"""
    bad = _clean_selection(bad)
    good = _clean_selection(good)
    conflicts = _drop_conflicts(bad, good)
    note = note.strip() if note and note.strip() else None

    created_cards = []
    for axis, values in bad.items():
        for value in values:
            card = _create_self_report_card(conn, brand_id, axis, value, actor=actor)
            if card:
                created_cards.append(card)

    created_hyps = []
    for axis, values in good.items():
        for value in values:
            label = fp.axis_value_label(axis, value)
            statement = f"{fp.AXES[axis]['label']}選「{label}」的素材過去有效"
            hyp = bi.create_strategy_hypothesis(
                conn, brand_id, hypothesis_type="message", statement=statement,
                created_by=actor, actor=actor, source_cycle_id=None,
            )
            created_hyps.append(hyp)

    if bad or good or note:
        write_audit(conn, brand_id=brand_id, entity_type="lesson_interview",
                    entity_id=new_id("itv"), action="submit", actor=actor,
                    before=None, after={"bad": bad, "good": good, "note": note})
    conn.commit()
    return {"rule_cards": created_cards, "hypotheses": created_hyps, "conflicts": conflicts}


def attach_pending_hypotheses(conn, brand_id: str, cycle_id: str) -> int:
    """把訪談留下、還沒掛進任何檔期的假設，掛進新開的這一期接受驗證（決策 0030 第 12 點）。

    只抓 `source_cycle_id IS NULL` 的 proposed 假設——這個特徵只有訪談會產生，
    正常開期流程一律帶 `source_cycle_id=cycle_id`（`app/ads/plan.py` `_persist`），
    所以不會誤抓其他假設。掛過一次之後就會出現在 campaign_cycle_hypothesis，
    不會被下一次開期重複掛進去。回傳掛了幾條。
    """
    rows = conn.execute(
        "SELECT id, hypothesis_type FROM strategy_hypothesis"
        " WHERE brand_id = %s AND status = 'proposed' AND source_cycle_id IS NULL"
        " AND id NOT IN (SELECT strategy_hypothesis_id FROM campaign_cycle_hypothesis"
        " WHERE brand_id = %s)", (brand_id, brand_id),
    ).fetchall()
    for row in rows:
        conn.execute(
            "INSERT INTO campaign_cycle_hypothesis (org_id, campaign_cycle_id,"
            " strategy_hypothesis_id, brand_id, role) VALUES (%s, %s, %s, %s, %s)"
            " ON CONFLICT (campaign_cycle_id, strategy_hypothesis_id) DO NOTHING",
            (DEV_ORG_ID, cycle_id, row["id"], brand_id, row["hypothesis_type"]),
        )
    if rows:
        conn.commit()
    return len(rows)
