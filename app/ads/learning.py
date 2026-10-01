"""app/ads/learning.py — F03-I12: the one sentence the next campaign's strategy reads (§0 the
"learning" link). Private to app/ads (container contract §1): only `closeout.py` imports this.

No model call in F03 (§0 "one sentence built by the program from the campaign's own facts") —
the sentence is assembled from `verdict`/`verdict_json`, which `closeout._judge` already built
from real numbers. Persisted through `app.brand_intelligence.repository.record_learning` (the
ledger API reviewed for F03-I02, §0) with `source_cycle_id = campaign_id`; never a `brand_fact`
or a `rule` row (ruling 15/16 — only the user's own typed feedback becomes a rule).
"""

from typing import cast

from app.ads import live_creative, sell_way, targets
from app.brand_intelligence import repository as bi_repo
from app.core.db import Conn, ConnProxy

_AnyConn = Conn | ConnProxy

_COORDINATE_DIMENSIONS = (
    "audience_key", "pain_key", "angle_key", "hook_key", "proof_key", "offer_key", "format_key",
)


def _sentence(campaign: dict, verdict: str, verdict_json: dict) -> str:
    """F28-I01: every campaign is judged on cost per result against its one cap, so the label is
    always 每筆成本."""
    label = "每筆成本"
    name = campaign["name"]
    sample = verdict_json.get("sample_bucket")
    if verdict == "看不出":
        missing = verdict_json.get("missing", "")
        return f"「{name}」這次投放{missing}（樣本{sample}），{label}上限暫時看不出達成與否。"
    target = _number(verdict_json.get("target"))
    actual = _number(verdict_json.get("actual"))
    return f"「{name}」{label}上限 {target}，實際 {actual}，結果{verdict}（樣本{sample}）。"


def _number(value):
    """Money as the sentence prints it: 2 decimals at most, and a whole number without `.0`
    (the cap is stored as numeric, so 300 reads back as 300.0)."""
    if not isinstance(value, float):
        return value
    rounded = round(value, 2)
    return int(rounded) if rounded.is_integer() else rounded


def _applicability_scope(detail: dict) -> str:
    """§0「applicability_scope = the coordinates the campaign concentrated on」——這裡取的是
    廣告座標的 key 本身，不是查 `brand_coordinate` 換成人看的 label（那要多一次跨模組查詢，
    F03 沒有要這麼細）。
    ponytail: raw coordinate keys, not labels — upgrade to labels via
    `app/ads/repository.py::coordinate_vocabulary` if 品牌智庫 ever needs to render this nicely.
    """
    keys: set[str] = set()
    for group in detail.get("groups", []):
        for ad in group.get("ads", []):
            for dimension in _COORDINATE_DIMENSIONS:
                value = ad.get(dimension)
                if value:
                    keys.add(value)
    return "、".join(sorted(keys)) if keys else "brand"


def _needs_revalidation(conn: _AnyConn, brand_id: str, campaign: dict) -> bool:
    """§0：來源商品換價（`product_economics` 生效日晚於這個 Campaign 跑的時候）就標
    `needs_revalidation`——180 天的門檻是讀時算的（策略任務那邊），這裡只管換價這一半。
    只看 Campaign 的賣法（`sell_way.of_campaign`，F44 Contract A：`context_json.product_ids`
    的第一個）：一個 Campaign 通常圍著一個主打商品轉，跟 §0「product_id = the ad's own,
    falling back to the Campaign's first context_json.product_ids entry」用同一個退回順序。"""
    product_id = sell_way.of_campaign(campaign)
    if product_id is None:
        return False
    econ = bi_repo.get_product_economics(cast(Conn, conn), brand_id, product_id)
    end_date = campaign.get("end_date")
    if econ is None or econ.get("effective_from") is None or end_date is None:
        return False
    return str(econ["effective_from"]) > str(end_date)


def _confidence(conn: _AnyConn, org_id: str, brand_id: str, campaign: dict, verdict: str) -> str:
    """分級死規則（F03 決策 3，F28-I01 改分群）：1 個活動＝`observed`；同一品牌、同一種成果
    （`targets.effective_result_kind`）、同方向（同一個 verdict）累計 ≥2＝`likely`；≥3＝
    `validated`（另一條「同期對照」留給 F04 的人工勾）。`看不出` 不指向任何方向，永遠是
    `observed`。系統自建的活動沒存 `result_kind` 時一律算購買——SQL 用同一條規則。"""
    if verdict == "看不出":
        return "observed"
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM ads_campaign WHERE org_id = %s AND brand_id = %s"
        " AND id != %s AND verdict = %s"
        " AND COALESCE(result_kind, CASE WHEN origin <> 'imported' THEN 'purchase' END)"
        " IS NOT DISTINCT FROM %s",
        (org_id, brand_id, campaign["id"], verdict, targets.effective_result_kind(campaign)),
    ).fetchone()
    assert row is not None  # COUNT(*) 一定回一列
    same_direction = row["n"] + 1  # +1 = 這個 Campaign 自己
    if same_direction >= 3:
        return "validated"
    if same_direction >= 2:
        return "likely"
    return "observed"


def write_learning(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str, verdict: str,
                    verdict_json: dict, *, actor: str) -> dict:
    """結案（或自動結案）寫的那一條學習。`campaign_id` 而非整包 `campaign` dict：這裡自己
    重讀 `campaign_detail`（要投放組／廣告的座標湊 `applicability_scope`），呼叫端
    （`closeout.close`）已經有的那份 dict 只到 campaign 欄位，不值得為了少一次查詢多傳一個
    尚未組好的大 dict。"""
    from app.ads import repository as ads_repo  # 延遲 import 避免循環（closeout.py 已是入口）

    detail = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)
    if detail is None:
        raise ValueError("campaign_unknown")
    # F31-I05 Contract O: the scope names the coordinates the creatives were made for.
    detail = live_creative.with_learning_coordinates(conn, org_id, brand_id, detail)

    text = _sentence(detail, verdict, verdict_json)
    if verdict_json.get("data_source") == "isolated_simulation":
        text = "【隔離模擬，非市場實證】" + text
    confidence = _confidence(conn, org_id, brand_id, detail, verdict)
    needs_revalidation = _needs_revalidation(conn, brand_id, detail)

    return bi_repo.record_learning(
        cast(Conn, conn), brand_id, actor=actor, learning_text=text,
        applicability_scope=_applicability_scope(detail), confidence=confidence,
        sample_size=str(verdict_json.get("sample_bucket")), source_cycle_id=campaign_id,
        needs_revalidation=needs_revalidation,
    )
