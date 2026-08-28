"""app/ads/checkpoint.py — 期中檢查點（票 9，GitHub issue #19，決策 0023 第 16 點）。

第 3 天與第 7 天：提醒卡觸發 → 當場匯入 CSV → 立即跑健康檢查。跟 `app/ads/reading.py`
的成效判讀是兩條分開的流程——這裡**明文不判勝負**，只回答兩件事（第 3 天）加一件事
（第 7 天）：

1. 學習期正不正常（有沒有出現資料合理性海關擋下來的異常訊號）。
2. 錢有沒有在花。
3.（第 7 天加）素材有沒有出現疲勞訊號（讀 `app.core.rule_cards` 的示範規則卡）。

這是 `app/methodology/ab-testing.md` 第 4、7 節 Peeking Problem 紀律在產品裡的具體落地：
`run()` 刻意不呼叫 `reading.judge()`，回傳的 dict 不含 status／ROAS／打平線等任何會被讀成
「贏了／輸了」的欄位。

**判讀規則與數據來源解耦**：這裡只讀 `performance_snapshot`（CSV、手動、未來 Meta API
自動同步三軌都寫進同一張表，見 `app/ads/performance.py`），本檔完全不碰 CSV 解析本身，
API 軌接上後不用改這裡一行。
"""


from app.ads import performance as ads_performance
from app.ads import repository as ads_repo
from app.ads.guardrails import check_data_sanity
from app.core import rule_cards
from app.core.audit import write_audit
from app.core.db import DEV_ORG_ID, jsonb, new_id, now_utc

KIND_LABELS = {"day3": "第 3 天健康檢查", "day7": "第 7 天健康檢查"}

# 提醒卡的 kind（app/ads/onboarding.py）→ 檢查點的 kind。到期日提醒（cycle_end）不是
# 期中檢查點，不在這張對照表裡。
REMINDER_TO_CHECKPOINT_KIND = {
    "day3_look_dont_touch": "day3",
    "day7_report": "day7",
}

# ponytail：素材疲勞判定需要「受眾類型」（冷受眾開發／再行銷／小眾），但目前系統還沒有
# 把帳戶結構落地成真的 ad-group 資料表（app/ads/account_structure.py 只算底案，不落庫）、
# CSV 匯入也沒有逐廣告組拆帳。第 3／7 天的期中檢查點在檔期一開始就會觸發，這個階段
# 幾乎必然還在冷受眾開發（再行銷要有累積轉換的名單才能開，不可能這麼早就有），所以先用
# 三種受眾類型裡門檻最嚴格的「冷受眾開發」當保守預設——寧可提早示警，不要少報。
# 等 ad-group 落地成真的資料表，改讀每組實際的受眾類型。
FATIGUE_AUDIENCE_TYPE = "cold"


def run(conn, brand_id: str, cycle_id: str, kind: str, *, actor: str,
        csv_text: str | None = None) -> dict:
    """跑一次期中健康檢查：可選先匯入 CSV，再讀目前累積的成效算健康訊號並落庫。

    回傳的 dict 保證不含任何「贏／輸」等級的欄位（硬規則，不是漏寫）。

    期中檢查點是事件不是死線（決策 0025 審查補遺第 4 點）：檔期一旦不再是 LIVE
    （代表期末判讀已經跑過，見 app/ads/reading.py run()），日3／日7 這兩個檢查點就沒有
    意義了——直接回報「併入期末判讀」，不寫入新的檢查點紀錄，使用者不用回頭補做。
    """
    if kind not in KIND_LABELS:
        raise ValueError(f"不認得的檢查點類型：{kind}")
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    if cycle is None:
        raise ValueError("找不到廣告檔期")

    if cycle["status"] != "LIVE":
        return {
            "kind": kind, "kind_label": KIND_LABELS[kind], "merged_into_final": True,
            "data_sufficient": None, "import_errors": [], "import_count": 0,
            "spend": None, "spend_ok": None, "spend_note": None,
            "learning_normal": None, "learning_note": None, "fatigue": None,
        }

    import_errors: list = []
    import_count = 0
    if csv_text and csv_text.strip():
        import_result = ads_performance.import_csv(conn, brand_id, cycle_id, csv_text,
                                                    actor=actor)
        import_errors = import_result.errors
        import_count = import_result.imported
        if not import_errors:
            ads_performance.save_derived_metrics(conn, brand_id, cycle_id)

    totals = ads_performance.totals(conn, brand_id, cycle_id)
    data_sufficient = bool(totals["rows"])

    result = {
        "kind": kind,
        "kind_label": KIND_LABELS[kind],
        "data_sufficient": data_sufficient,
        "import_errors": import_errors,
        "import_count": import_count,
        "spend": totals.get("spend") or 0,
        "spend_ok": None,
        "spend_note": "這期還沒有任何成效資料，先匯入 CSV 才能看健康訊號。",
        "learning_normal": None,
        "learning_note": "這期還沒有任何成效資料，先匯入 CSV 才能看健康訊號。",
        "fatigue": None,
        "reach": None,
    }

    if data_sufficient:
        spend = totals.get("spend") or 0
        result["spend_ok"] = spend > 0
        result["spend_note"] = (
            f"已經花了 {spend:,.0f}，錢有在動。" if spend > 0 else
            "目前累積花費是 0，這不正常——去 Meta 後台確認廣告有沒有真的在跑、審核有沒有卡住。"
        )

        sanity = check_data_sanity(totals)
        result["learning_normal"] = not sanity
        result["learning_note"] = ("數字沒有出現異常訊號，學習期看起來正常。" if not sanity
                                   else "；".join(f.message for f in sanity))

        if kind == "day3":
            # 觸及是漏斗上層（曝光期）主指標，第 3 天正是看這個的時候（票 03-add-reach-metric）。
            # 缺欄不擋匯入，但要有針對性的人話提醒——比照下面 day7 缺頻率欄的既有寫法。
            reach = ads_performance.total_reach(conn, brand_id, cycle_id)
            if reach is None:
                result["reach"] = {
                    "reach": None,
                    "note": "這批 CSV 沒有帶「觸及人數」欄位，看不出這期廣告觸及了多少人——"
                            "匯出時記得勾選觸及欄，或去 Meta 後台直接看。",
                }
            else:
                result["reach"] = {
                    "reach": reach,
                    "note": f"目前累積觸及 {reach:,} 人。",
                }

        if kind == "day7":
            frequency = ads_performance.max_frequency(conn, brand_id, cycle_id)
            if frequency is None:
                result["fatigue"] = {
                    "frequency": None,
                    "note": "這批 CSV 沒有帶「頻率」欄位，看不出素材有沒有疲勞——"
                            "匯出時記得勾選頻率欄，或去 Meta 後台直接看。",
                }
            else:
                status = rule_cards.classify_ad_frequency(conn, brand_id, FATIGUE_AUDIENCE_TYPE, frequency)
                result["fatigue"] = {
                    "frequency": frequency,
                    "status": status,
                    "status_label": rule_cards.FATIGUE_STATUS_LABELS[status],
                    "audience_type": FATIGUE_AUDIENCE_TYPE,
                    "audience_type_label": rule_cards.AUDIENCE_TYPE_LABELS[FATIGUE_AUDIENCE_TYPE],
                    "note": ("目前頻率看起來還健康。" if status == "safe" else
                             "頻率已經進警示區，同一批人開始看膩了，該準備替補素材。" if status == "warning" else
                             "頻率已經到危險等級，這個概念大概率已經耗盡，考慮換素材或退場。"),
                }

    return _store(conn, brand_id, cycle_id, kind, result, actor)


def _store(conn, brand_id: str, cycle_id: str, kind: str, result: dict, actor: str) -> dict:
    ts = now_utc()
    checkpoint_id = new_id("chk")
    conn.execute(
        "INSERT INTO cycle_checkpoint (id, org_id, brand_id, campaign_cycle_id, kind, result_json,"
        " status, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, 'active', %s, %s)",
        (checkpoint_id, DEV_ORG_ID, brand_id, cycle_id, kind,
         jsonb(result), ts, ts),
    )
    write_audit(conn, brand_id=brand_id, entity_type="cycle_checkpoint", entity_id=checkpoint_id,
                action="create", actor=actor, before=None, after=result)
    conn.commit()
    result["id"] = checkpoint_id
    result["created_at"] = ts
    return result


def _row(conn, brand_id: str, checkpoint_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM cycle_checkpoint WHERE id = %s AND brand_id = %s",
        (checkpoint_id, brand_id),
    ).fetchone()
    return dict(row) if row else None


def list_checkpoints(conn, brand_id: str, cycle_id: str) -> list:
    """這期做過的所有檢查點，最新的在前面。"""
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM cycle_checkpoint WHERE brand_id = %s AND campaign_cycle_id = %s"
        " ORDER BY created_at DESC", (brand_id, cycle_id),
    )]
    for row in rows:
        row["result"] = row["result_json"]
        row["kind_label"] = KIND_LABELS.get(row["kind"], row["kind"])
    return rows


def set_status(conn, brand_id: str, checkpoint_id: str, *, status: str, actor: str) -> dict:
    """封存／恢復（決策 0023 第 8 條：新資料實體必附封存＋刪除）。"""
    if status not in ("active", "archived"):
        raise ValueError("cycle_checkpoint.status 只能是 active 或 archived")
    before = _row(conn, brand_id, checkpoint_id)
    if before is None:
        raise ValueError(f"找不到檢查點紀錄：{checkpoint_id}")
    ts = now_utc()
    conn.execute("UPDATE cycle_checkpoint SET status = %s, updated_at = %s WHERE id = %s",
                (status, ts, checkpoint_id))
    after = _row(conn, brand_id, checkpoint_id)
    write_audit(conn, brand_id=brand_id, entity_type="cycle_checkpoint", entity_id=checkpoint_id,
                action="archive" if status == "archived" else "restore", actor=actor,
                before=before, after=after)
    conn.commit()
    return after


def delete(conn, brand_id: str, checkpoint_id: str, *, actor: str) -> None:
    """硬刪除，before 全文記進稽核（比照 customer_voice：任何狀態都能刪，不用先封存）。"""
    before = _row(conn, brand_id, checkpoint_id)
    if before is None:
        raise ValueError(f"找不到檢查點紀錄：{checkpoint_id}")
    conn.execute("DELETE FROM cycle_checkpoint WHERE id = %s AND brand_id = %s",
                (checkpoint_id, brand_id))
    write_audit(conn, brand_id=brand_id, entity_type="cycle_checkpoint", entity_id=checkpoint_id,
                action="delete", actor=actor, before=before, after=None)
    conn.commit()
