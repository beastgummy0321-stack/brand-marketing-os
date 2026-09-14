# 精靈步驟 3 按「下一步」不推進 `current_step`；重訪不記「廣告帶來的是什麼」、賣法列順序反轉

Status: 2026-09-14 F05 收尾真瀏覽器走查（站 2、站 6）量到，DB 與截圖在當次 scratchpad `walk2/`。

事實：
- `saveOfferings` 只 `state.touch(..., 3)`，按「下一步」後 `intake_draft.current_step` 仍是 3；重整回到步驟 3，
  步驟軌的「接工具」是 disabled（要再按一次下一步）。
- 重訪步驟 3 時「商品」有選、「廣告帶來的是什麼」空白 → helper「選一下廣告帶來的是什麼。」、下一步 disabled。
  這個選擇沒有落地欄位（它只決定 `close_rate` 要不要問），重進來反推不出來。
- 賣法列順序與輸入相反（`list_products` 是 `ORDER BY name`；F05 決策 23 已記「第一個賣法」同一根因）。

做法（未裁決）：`saveOfferings` 成功後 touch 到 4；「廣告帶來的是什麼」從 `close_rate IS NULL` 反推（直接下單）
或存進 `assumptions_json` 旁一個小欄；賣法排序改 `created_at`。三件都小，同一張票。
