# A node's coordinates are re-guessed by the copy model every period; nothing carries them from one period to the next

Status: open（2026-09-09 drill 3 量到，主聊天對資料庫核實）。判斷題（座標由誰擁有：樹、工單、還是文案模型）
是不可逆決定，不在票裡自己填——等使用者裁決後開票（route C，動模組邊界）。

## 成因（file:line）

- 樹的節點沒有座標：`app/schedule/tree.py` 讀 `rendered_output` 出來的 leaf 只有 `fields`（格式／主要文字／標題／CTA）
  與 `warnings`，沒有任何 `*_key`（drill 3 兩棵樹 `llm_01M22EXJHR7CM84ATB1T6VK0FD`、`llm_01M22YAMNNJ3AZP5BW2BKHD7TW` 逐 leaf 檢查）。
- 交棒時明寫不帶座標：`app/schedule/jobs.py:551` `"coordinates": None` → 每一份 `workbench_brief.coordinates_snapshot_json` 都是 `{}`
  （MOVE Daily 17 份工單全部 `{}`），所以文案提示詞的「既有座標（延續語氣參考用）」一行永遠不出現（`app/workbench/prompts.py:28-31`）。
- 座標其實來自文案模型的回覆：`app/schedule/state.py:194` `copy_output.get("coordinates_json")` → `creative_candidate`。
  同一個「沿用」節點兩期被猜成不同座標：01A 第一期 (pain=effort, hook=outcome_led)，第二期 (pain=experience, hook=pain_question)。
- `period_node_result.coordinates_json` 因此也是模型猜的（ADR 0066 的計分讀的是 `creative_candidate`）。

## 影響

- 閉環的證明「採用 → 下一次提案延續贏家座標」目前只在**名稱**層成立（新樹確實寫「延續 01A、01C、02B、03A、03C」、
  「取代 01B…」），在**座標**層不成立：下一期的判讀會把 01A 的成績記到另一組座標上，兩期的判讀互相對不上。
- 使用者在工作檯／投放包看不到節點座標（drill 3 小文的卡點），因為根本沒有。
- `format_key` 仍出現 `single_image`（Meta 已無單圖；票 05 只改了畫面標籤）。

## 可能的做法（供裁決，不是決定）

1. 樹出座標：`schedule_tree` 任務檔要求每個廣告節點回七維 key，交棒時寫進 `coordinates_snapshot_json`，文案模型只延續不重猜；
   `_sync_creative_candidate` 改讀工單快照，模型回的座標只在快照缺項時補。
2. 延續期：出方案／展開時把上一期 `period_node_result.coordinates_json` 按節點名稱帶給樹模型（「沿用」的節點座標不變）。
3. 兩者都做（推薦）：1 讓座標有唯一來源，2 讓「沿用」真的沿用。
