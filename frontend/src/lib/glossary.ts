/** 白話詞彙字典（票 01-glossary-icon，G11 契約）：矩陣頁詞彙旁「?」圖示點開的白話解釋。
 * 內容鏡射 `app/dashboard/glossary.py`（白話版權威來源）——矩陣頁是純前端 SPA，沒有伺服器
 * 樣板把 Python 字典注入瀏覽器，只能在這裡另存一份給 bundle 直接讀，兩邊手動同步（目前
 * 只有 2 條，維護成本低；詞條變多再考慮建置期產生）。跟 `app/dashboard/glossary.py`、
 * `CONTEXT.md` 三份分開維護、不互相引用，見 GRILL-DONE-G11-glossary-icon-contract.md。
 *
 * 頁面載入時字典已經隨 bundle 帶進來，點「?」開關 popover是純前端互動，不打後端 API
 * （契約 G11.2）。 */
export const GLOSSARY: Record<string, { term: string; text: string }> = {
  angle: {
    term: "切角",
    text: "為什麼要買這個東西的理由（例如：省錢、划算、健康）。同一個切角底下會有好幾種不同的說法去表達它，但講的都是同一個理由。",
  },
  candidate: {
    term: "候選",
    text: "系統生成出來、還沒被選定使用的主題。候選不代表品質差，只是還沒被你按下「採用」而已。",
  },
};
