"""app/ads/reading_settlement.py — 結算保護（票 06-settlement-must-survive-a-rejudge）。

從 `app/ads/reading.py`（凍結 1039 行、不得再長）拆出來的小檔——這兩個純函數只有
run() 這一個呼叫端，不是新開的容器（集裝箱憲章：拆檔不是拆模組）。

D3：已結案（CLOSED）的檔期只有兩種觸發還能再判一次——final_settlement（結算本身）、
late_data（票 #38 補件重判）；其餘一律拒絕，回一句白話理由，講清楚「結算還在」。
"""


SETTLED_TRIGGERS = ("final_settlement", "late_data")


def refusal_reason(cycle_status: str, trigger_reason: str | None) -> str | None:
    """可以跑就回 None；已結案又不是補件／結算本身，回白話拒絕理由（D3）。"""
    if cycle_status == "CLOSED" and trigger_reason not in SETTLED_TRIGGERS:
        return ("這期已經結算完成，覆盤也出來了，所以不再重新判讀——"
                "原本的結算結果原封不動留著。想看最新的數字，直接看這期的覆盤。")
    return None


def is_settlement_run(cycle_status: str, trigger_reason: str | None) -> bool:
    """這次產生的判讀是不是「結算版」（D4：拿來標 is_tentative、決定要不要整批清空舊版）。

    只有 late_data 能在 CLOSED 檔期跑到這裡（其餘觸發已被 refusal_reason() 擋下），
    所以 CLOSED 檔期上的 late_data 重判也算結算版——它取代的是原本的結算版本，
    不是與之並存的暫定版。
    """
    return trigger_reason == "final_settlement" or cycle_status == "CLOSED"
