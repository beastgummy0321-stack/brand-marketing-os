# -*- coding: utf-8 -*-
"""app/llm/pricing.py — 模型費率表（供應商原生計價幣別 USD，美元／百萬 token）。

見 docs/design/06-llm-gateway.md §12（PriceBook）。刻意只有一個 dict，不散落他處
（本輪任務指示）；之後如供應商調整報價，直接改這個 dict 並在下方註明來源日期。
"""

# 來源日期：2026-08-01（claude-opus-5／claude-sonnet-5／claude-haiku-4-5 沿用 2026-07-27
# 取自 Anthropic 官方定價頁的既有數字；claude-fable-5 新增，查證來源：claude-api skill
# 內建的模型定價表（cached: 2026-06-24，與 shared/models.md 一致）——US$10／US$50 每百萬
# token。如有調整請連同來源日期一併更新）。
PRICING = {
    "claude-opus-5": {
        "input_per_mtok": 5.0,
        "output_per_mtok": 25.0,
    },
    "claude-sonnet-5": {
        "input_per_mtok": 3.0,
        "output_per_mtok": 15.0,
    },
    "claude-haiku-4-5": {
        "input_per_mtok": 1.0,
        "output_per_mtok": 5.0,
    },
    "claude-fable-5": {
        "input_per_mtok": 10.0,
        "output_per_mtok": 50.0,
    },
}


# 網路搜尋（ADR 0005）按次計費，與模型無關，不進上面那張表。官方原文：「Web search is
# available on the Claude API for $10 per 1,000 searches, plus standard token costs」
# 來源：https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool.md
# （查證日 2026-08-11）。搜尋出錯不計費，API 也不會把它算進 web_search_requests。
WEB_SEARCH_USD_PER_SEARCH = 10.0 / 1000


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """回傳美元成本（06 §12：幣別以供應商原生 USD 記錄，顯示幣別換算屬報表層）。

    找不到該模型的費率時拋出人話錯誤——不悄悄算出 0 或亂猜費率（誠實狀態，principles 第 16 條）。
    """
    rate = PRICING.get(model)
    if rate is None:
        raise ValueError(f"沒有「{model}」的費率設定，請先在 app/llm/pricing.py 補上")
    return (
        (input_tokens / 1_000_000) * rate["input_per_mtok"]
        + (output_tokens / 1_000_000) * rate["output_per_mtok"]
    )


def cost_ceiling(model: str, max_output_tokens: int) -> float:
    """呼叫前的保守天花板估計（美元）：假設這次呼叫的輸出把 max_output_tokens 全部打滿、
    只用輸出費率（通常比輸入貴，抓不到真的用量校準資料時當「不會低估」的上界）。

    給還沒有像 app/intake/script.py 那樣真實用量校準資料的呼叫端用（例如廣告分支的
    計畫／素材生成，票 M2）——不比照 intake 編一個看起來很準的校準數字，改用已知費率表
    ×已設定的 max_tokens 上限，誠實承認這只是保守估計（principles 第 16 條，不捏造數字）。
    找不到該模型的費率時回 0（呼叫前攔截不是這個函式該報的錯，交給 calculate_cost 在
    呼叫後誠實地噴錯）。
    """
    rate = PRICING.get(model)
    if rate is None:
        return 0.0
    return (max_output_tokens / 1_000_000) * rate["output_per_mtok"]
