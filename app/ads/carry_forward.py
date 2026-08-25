# -*- coding: utf-8 -*-
"""app/ads/carry_forward.py — R3-carry-forward-winners：「沿用有效方向」要真的讀贏家
（B0-29／B0-36）。

開下一期選「沿用有效方向」時，企劃 prompt（`plan.py`）過去只帶得到品牌事實／規則／宣稱與
`learning_ledger` 裡的抽象學習文字，從沒帶過「上期到底哪支切角真的打贏了」這種具體、帶
數字的證據，也沒帶過「哪個方向已經驗證賠錢、別再選」——AI 因此常常整批換成沒出現過的新
切角（B0-29），或是把從沒真的 A/B 對照過的假設當方案依據（B0-36）。這兩支函式把「贏家」
「該避開的方向」從既有的歷史資料表裡撈出來，交給 `plan.py` 的 prompt 組裝函式塞進企劃
prompt，供 `plan.generate_options()` 呼叫。

拆成獨立小檔而不是加進 `app/ads/nextcycle.py`：那檔已經 798 行，貼近 800 行單檔上限
（CLAUDE.md／`test_architecture_boundaries.py::FileLineCapTest`），這裡兩支函式各自完整、
只依賴 `nextcycle.historical_cell_performance()` 與品牌智庫的公開讀取函式，獨立成檔不會
逼著 `nextcycle.py` 也要拆（比照 `reading_hypotheses.py` 從 `reading.py` 拆出來的既有
先例：拆檔不是拆模組，這裡跟 `plan.py`／`nextcycle.py` 仍是同一個容器）。
"""

from typing import Optional

from app.ads import nextcycle
from app.ads import reading_hypotheses
from app.brand_intelligence import repository as bi

# 票 F7：`learning_ledger.confidence` 只有這三種值（見 `app/ads/reading.py`
# LEDGER_CONFIDENCE_LABELS），且只在假設被判「成立」時才寫入（`resolve_hypotheses()`
# 唯一入帳點）——這裡不 import 整支 reading.py 只為了一個常數，本地留一份就好。
_SIGNED_OFF_CONFIDENCE = ("preliminary", "moderate", "reinforced")


def prior_winners(conn, brand_id: str, product_ids: Optional[set] = None,
                  exclude_cycle_id: Optional[str] = None, limit: int = 3) -> list:
    """歷來真正打贏的切角，依 ROAS 高到低取前 `limit` 名：切角名、ROAS、花費、轉換數、
    來源期別，供企劃 prompt 具名引用（契約第 2 點）。

    兩個來源合併去重（票 F7，2026-08-25 使用者裁決 option 1）：
    1. `historical_cell_performance()`——誠實門檻跟 R2 的 `guard_supported_verdict()`／
       `reading_hypotheses.comparison_cells()` 同一種原則（樣本不足就不准冒充結論，鐵則
       16）：標 `evidence_sufficient: False`（轉換數不到可信門檻）或 `underperforming: True`
       的切角，以及算不出 ROAS（沒花費或沒營收資料）的切角一律不算贏家。大品牌走這條，
       這條的統計門檻（`target_cpa.WEEKLY_CONVERSIONS_PER_GROUP`）維持不變。
    2. `_signed_off_winners()`——人已經在判讀頁親自簽核「成立」的學習，不受統計門檻限制：
       低門檻給人簽的、高門檻給機器自動加碼／停損卡用，兩件事分開。

    同一個切角、同一個來源期別若兩條來源都算出來，算同一個贏家（取 ROAS 較高的那筆）。

    product_ids 給定且非空時，只算落在這些產品底下、或沒有 product_id（品牌層歷史舊資料
    常見，見 `historical_cell_performance()` docstring）的切角；給 None／空集合時不篩產品，
    整個品牌的歷史都算——沒指定個別產品的檔期（`allocations` 是空的）就該看品牌全部歷史。
    """
    cells = nextcycle.historical_cell_performance(conn, brand_id, exclude_cycle_id=exclude_cycle_id)
    winners = []
    for cell in cells:
        if product_ids and cell["product_id"] is not None and cell["product_id"] not in product_ids:
            continue
        if cell.get("evidence_sufficient") is False or cell.get("underperforming"):
            continue
        spend, revenue = cell["spend"], cell["revenue"]
        if not spend or revenue is None:
            continue
        winners.append({
            "angle": cell["creative_angle"], "roas": round(revenue / spend, 2), "spend": spend,
            "conversions": cell["conversions"], "source_cycle_id": cell["campaign_cycle_id"],
        })
    winners.extend(_signed_off_winners(conn, brand_id, product_ids, exclude_cycle_id))

    deduped = {}
    for w in winners:
        key = (w["angle"], w["source_cycle_id"])
        if key not in deduped or w["roas"] > deduped[key]["roas"]:
            deduped[key] = w
    result = sorted(deduped.values(), key=lambda w: w["roas"], reverse=True)
    return result[:limit]


def _signed_off_winners(conn, brand_id: str, product_ids: Optional[set],
                        exclude_cycle_id: Optional[str]) -> list:
    """第二個贏家來源（票 F7，橋接修正票 F11）：使用者親自簽核「成立」的假設，不管統計
    證據夠不夠——人已經看過並排的 A／B 數字才按下確認，門檻比機器自動判定低是刻意的
    （契約：低門檻給人簽的，高門檻給機器自己做的；`target_cpa.WEEKLY_CONVERSIONS_PER_GROUP`
    不受影響）。

    `strategy_hypothesis` 跟 `experiment_cell` 之間沒有外鍵，F7 原本的橋是「那期 ROAS 最高的
    切角」——但「那期打最好的」不等於「這條假設在講的」，F11 重現的正是這個誤配（票內
    `fatigue` 案例）。改用學習句子本身當橋：只認「這條假設的來源期別（
    `reading_hypotheses.comparison_cells()`，已經只挑真的對回成效資料的切角）裡，切角名稱
    真的被寫進 `learning_text` 這句人話」的切角（`reading_hypotheses.named_cells()`，票 L1
    抽成共用），全部算數（不是只取一個），各自帶自己的 ROAS。句子沒提到任何一個切角時，
    這條 ledger entry 不貢獻贏家——沒把握就不猜（鐵則 16）。
    """
    winners = []
    for entry in bi.list_learning_ledger(conn, brand_id):
        if not entry["source_hypothesis_id"] or entry["confidence"] not in _SIGNED_OFF_CONFIDENCE:
            continue
        hyp = bi.get_strategy_hypothesis(conn, brand_id, entry["source_hypothesis_id"])
        if hyp is None or hyp["status"] != "supported" or not hyp["source_cycle_id"]:
            continue
        cycle_id = hyp["source_cycle_id"]
        if exclude_cycle_id and cycle_id == exclude_cycle_id:
            continue
        if product_ids and hyp["product_id"] is not None and hyp["product_id"] not in product_ids:
            continue
        cells = reading_hypotheses.comparison_cells(conn, brand_id, cycle_id, hyp["product_id"])
        for cell in reading_hypotheses.named_cells(cells, entry["learning_text"]):
            roas = cell["kpis"]["roas"]
            if roas is None:
                continue
            winners.append({
                "angle": cell["creative_angle"], "roas": roas, "spend": cell["spend"],
                "conversions": cell["conversions"], "source_cycle_id": cycle_id,
            })
    return winners


def rejected_directions(conn, brand_id: str, product_ids: Optional[set] = None,
                        limit: int = 5) -> list:
    """已判讀「不成立」的方向（覆盤③三選一結案，`strategy_hypothesis.status == 'rejected'`），
    最新的排前面，供企劃 prompt 明講「這個方向上期賠錢，已避開」（契約第 3 點），不讓 AI
    又選回頭路——B0-36 重現的正是「避開了但沒有一句話說明理由」。

    product_ids 給定且非空時只算這些產品專屬、或品牌層（`product_id` 為 None）的假設；
    給 None／空集合時不篩產品。
    """
    result = []
    for h in bi.list_strategy_hypotheses(conn, brand_id):
        if h["status"] != "rejected":
            continue
        if product_ids and h["product_id"] is not None and h["product_id"] not in product_ids:
            continue
        result.append({"id": h["id"], "statement": h["statement"],
                       "source_cycle_id": h["source_cycle_id"]})
    return result[:limit]
