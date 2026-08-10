# -*- coding: utf-8 -*-
"""app/dashboard/glossary.py — 白話詞彙字典（票 01-glossary-icon，G11 契約）。

`CONTEXT.md` 給開發者／AI 看；本檔是同一批詞條的白話版，給使用者看，兩份分開維護、
不互相引用（CONTEXT.md「詞彙表機制」節）。矩陣頁是純前端 SPA（`frontend/`，ADR 0003），
沒有伺服器樣板把這份字典注入瀏覽器的橋接管道，因此畫面實際讀的是鏡射同一份內容的
`frontend/src/lib/glossary.ts`——本檔是白話版的權威來源（之後若有 Jinja 頁面要用同一份
詞彙，直接 import 這裡，不必另外改寫）。

範圍只收已知看不懂的詞（目前「切角」「候選」），非整份 `CONTEXT.md` 都做；之後發現
別的詞看不懂，照同機制加一條即可。
"""

GLOSSARY: dict[str, dict[str, str]] = {
    "angle": {
        "term": "切角",
        "text": (
            "為什麼要買這個東西的理由（例如：省錢、划算、健康）。同一個切角底下會有"
            "好幾種不同的說法去表達它，但講的都是同一個理由。"
        ),
    },
    "candidate": {
        "term": "候選",
        "text": "系統生成出來、還沒被選定使用的主題。候選不代表品質差，只是還沒被你按下「採用」而已。",
    },
}
