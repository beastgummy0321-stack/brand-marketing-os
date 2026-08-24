# -*- coding: utf-8 -*-
"""app/ads/reading_verdict.py — 判讀結論周邊的純函式（票 10-split-reading-py）。

從 `app/ads/reading.py`（凍結 1039 行、不得再長）拆出來的小檔——這幾個函式原樣搬過來，
只有 reading.py 這一個呼叫端，不是新開的容器（集裝箱憲章：拆檔不是拆模組）。

跟 `reading_baselines.py`／`reading_hypotheses.py` 不一樣的是，這裡沒有共同主題——
是把「不碰 `PROVIDER`、不碰 `orders_repo`／`orders_channel`」這兩個熱門全域變數的
剩餘小函式湊在一起，才能讓 reading.py 瘦下來（票 10 的 D3 只點名基線／LLM 文案／假設
三個縫，但 LLM 文案那個縫裡的 `_explain`／`_explain_diff`／`_explain_hypotheses` 全部
要用到 `PROVIDER`——多達十幾個 `app/tests/test_*.py`〔不在這張票能碰的檔案清單內〕
直接改 `reading.PROVIDER = FakeProvider(...)` 之後預期判讀會呼叫到假的那顆；`PROVIDER`
如果搬去別的檔案，`reading.PROVIDER = X` 只是幫 reading 模組另外掛一個名字，不會改到
真正執行 `gateway.run_task(...)` 那個檔案自己模組層的 `PROVIDER`，等於悄悄換回真的
Provider——這樣的搬法不是「純搬移」，是行為改變，所以 LLM 文案那個縫沒有動、留在
reading.py。這裡另外湊的這批函式是為了在不能動 LLM 文案縫的前提下，還是把行數壓下來。
"""

from typing import Optional

from app.ads import budget as budget_calc
from app.ads import performance as ads_performance

# 翻盤分級規則（票 #38，決策 0025 判讀節奏第 5 點：「翻盤警示分級——微調不吵、判定翻盤才
# 進佇列」）：規則寫死在程式，不用 LLM 判斷、不用可調參數。判讀結論只分三群——正向可以
# 加碼、負向該停損、中間還看不準——補件後只有「正向→負向」或「負向→正向」跨群才算真正
# 翻盤；停在同一群內的變化（含還是看不準）都算微調，不驚動使用者。
_POSITIVE_STATUSES = {"scale_candidate", "maintain"}
_NEGATIVE_STATUSES = {"pause_candidate"}

# 假設結案預選（票 F3-signoff-residue，取代票 #53／修憲落地 G4／決策 0035 第三節第 6
# 點原本的作法）：那個舊版本只要 scale_candidate／pause_candidate 這兩個「真正算得出
# 方向」的整體結論出現、且這期真的做過對照（comparison_cells 足夠），就預選成立／不
# 成立——但「整體判讀結論偏正向」不等於「這條假設自己的 A／B 對照數字真的支持它」，
# 預選值來自產品／檔期層級的聚合結論，不是這條假設自己那幾個切角的比較結果，使用者
# 十之八九照預選送出，等於用聚合方向幫這條假設背書，跟票 #53 當初想避免的橡皮圖章是
# 同一種問題，只是換了個更隱蔽的來源。UX 誠實面改成：不管整體結論多明確、對照做得多
# 完整，畫面一律預選「看不出來」，使用者要主動選「成立」才算數（同精神：B0-21）。
#
# 寫入端的把關（`guard_supported_verdict`，reading_hypotheses.py）維持不變——沒有真對照
# 的「成立」照樣在入帳前被程式擋下、降級成「看不出來」；這裡改的純粹是畫面預選這一層，
# 兩層各管各的，互不取代。


def _verdict_group(status: Optional[str]) -> str:
    """翻盤警示（`classify_verdict_shift`）與回購雙線衝突（`_repurchase_line`）專用的
    正負向分群——`maintain` 算正面在這兩個用途下是對的。**假設結案預選不用這個**，
    見下面 `_preselect_hypothesis_status`。"""
    if status in _POSITIVE_STATUSES:
        return "positive"
    if status in _NEGATIVE_STATUSES:
        return "negative"
    return "uncertain"


def _preselect_hypothesis_status(status: Optional[str]) -> str:  # noqa: ARG001 — 見上方票 F3 說明
    """畫面預選一律「看不出來」，不再依整體判讀結論猜方向（票 F3-signoff-residue）。

    `status` 參數保留只是不改呼叫端（`reading_hypotheses.build_hypothesis_items` 的
    `preselect_fn` 注入介面）簽章——集裝箱憲章第 6 節：改進入點簽章是契約變更，這裡
    沒有非改不可的理由，維持既有介面比較乾淨。"""
    return "inconclusive"


def classify_verdict_shift(before_status: Optional[str], after_status: Optional[str]) -> str:
    """'unchanged'（結論沒變）／'adjustment'（微調，不吵）／'reversal'（翻盤，要進佇列）。"""
    if before_status == after_status:
        return "unchanged"
    if {_verdict_group(before_status), _verdict_group(after_status)} == {"positive", "negative"}:
        return "reversal"
    return "adjustment"


def _unsettled_note(ratio: Optional[float]) -> str:
    """期末暫定判讀標注「未結案訂單佔 X%」（決策 0025 判讀節奏第 5 點）：貨到付款＋超商取貨
    型態下，這些訂單期末後才會定案，暫定結論可能因此翻盤。"""
    if ratio is None:
        return "沒有比對得到訂單資料，看不出未結案訂單的比例。"
    return f"這期還有 {ratio:.0%} 的訂單尚未結案（出貨或取貨還沒完成），這是暫定結論。"


def breakeven_roas(economics: Optional[dict]) -> Optional[float]:
    """打平所需的投報率＝售價 ÷ 單位毛利。算不出來回 None（不猜）。"""
    if not economics:
        return None
    margin = budget_calc.gross_margin(economics)
    price = economics.get("selling_price")
    if not margin or not price:
        return None
    return round(float(price) / margin, 2)


def cycle_breakeven_roas(conn, brand_id: str, allocations: list) -> Optional[float]:
    """檔期層打平線＝這期各產品打平線的平均，四捨五入到小數點兩位；一個都算不出來回 None。

    原本內嵌在 `reading.load()` 裡，ADR 0025 把它抽成函式：週提案卡的廣告層停掉卡也要用
    同一條線，`reading.py` 已經到單檔行數上限，而兩個地方各算一次數字會兜不起來（票 09 D1）。
    """
    from app.brand_intelligence import repository as bi
    known = [b for b in (breakeven_roas(bi.get_product_economics(conn, brand_id, a["product_id"]))
                         for a in allocations) if b]
    return round(sum(known) / len(known), 2) if known else None


def repurchase_breakeven_roas(first_order_breakeven: Optional[float],
                              multiplier: Optional[float]) -> Optional[float]:
    """含 90 天回購的實質打平線（票 #39，決策 0025 第 7 點）：回購讓客戶在 90 天內帶來
    `multiplier` 倍首單的淨營收，所以首單廣告投報率不用到打平線就已經回本——
    實質打平線＝首單打平線 ÷ 回購倍數。任一邊算不出來就回 None，不猜。"""
    if not first_order_breakeven or not multiplier:
        return None
    return round(first_order_breakeven / multiplier, 2)


def prediction_settlement(conn, brand_id: str, cycle: Optional[dict]) -> Optional[dict]:
    """兌現預言卡的資料組裝（決策 0039 第 13–16 條，票 F5）。cycle 傳哪一期就對哪一期的
    區間快照兌現——判讀頁出口傳「正在看的這期」自己，第二期檔期內頁出口傳「上一期」
    （見 app/ads/routes.py 兩個呼叫端；上一期由 onboarding.previous_cycle() 取得，本函式
    接受 None 直接短路，呼叫端不必自己先判斷有沒有上一期）。快照讀取一律走
    forecast_snapshot()（票 F1單點 helper），沒存過快照的期不出卡，不補算（鐵則 16）；
    一筆成效資料都還沒有時同樣不出卡——「兌現」需要真的有結果可以對，不能拿零筆資料充數。
    """
    from app.ads import onboarding as ads_onboarding

    if cycle is None:
        return None
    forecast = ads_onboarding.forecast_snapshot(cycle)
    if not forecast:
        return None
    totals = ads_performance.totals(conn, brand_id, cycle["id"])
    if not totals["rows"]:
        return None
    return {
        "forecast": forecast,
        "clicks": totals["clicks"],
        "conversions": totals["conversions"],
        "spend": totals["spend"],
        "budget": cycle["budget"],
        "gap": ads_onboarding.forecast_gap(forecast, totals),
    }


def money_line(cycle: dict, totals: dict, kpis: dict) -> str:
    """判讀白話 prompt 的第一段：實際花費／營收擺前面，計畫預算明講只是上限。

    只餵「計畫預算」時，模型會把預算當成花掉的錢，再乘投報率反推出一個從沒發生過的營收
    （ACCEPTANCE-A 第 4 節第 6b 題：實際花 12,000、營收 72,000，模型講成花 30,000、賺回
    180,000）。roas 是 None＝這期沒收到營收資料，要講「不知道」，不能講「營收 0」（鐵則 16）。
    """
    roas = (kpis or {}).get("roas")
    earned = (f"，實際帶回營收 {totals.get('revenue') or 0:,.0f} 元，投報率 {roas:.2f} 倍"
              if roas is not None else "；這期沒收到營收資料，帶回多少錢算不出來")
    return (f"檔期：{cycle['start_date']} 到 {cycle['end_date']}\n"
            f"這期實際花了 {totals.get('spend') or 0:,.0f} 元{earned}\n"
            f"計畫預算 {cycle['budget']:,.0f} 元（這是預算上限，不是花掉的錢；"
            f"不可以拿它當花費，也不可以拿它乘投報率去推算營收）")
