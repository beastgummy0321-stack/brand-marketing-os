# 開通 LLM 網路搜尋（Anthropic web_search 伺服器端工具）

_Status: partially retired — the mechanism survives, both call sites were deleted with `app/ads/`. See ADR 0030._

舊前提：系統的 AI 呼叫（`app/llm/providers.py` `AnthropicProvider.complete()`）不掛任何工具，AI 看不到網路——這也是交接包設計成「使用者手動搬去外部 Claude/ChatGPT」的原因之一。使用者的駕駛艙願景要求系統像「連著網路的廣告顧問團隊」，知道當下檔期與市場氛圍。

決策：在 `complete()` 加可選 `tools` 參數，**預設不開**，由呼叫端逐一決定。首波只開兩處：打法生成（`app/ads/plan.py`）與素材生成（`app/ads/creative.py`），設定 `web_search`、`max_uses` 2–3、`user_location` 國碼 TW。成本量級：每次搜尋約 US$0.01＋結果 token 費，單次呼叫約多 US$0.02–0.05，計入既有 `llm_task.cost` 與全站花費上限。

**2026-08-11 落地時的更正**：本 ADR 原文把「下期建議（`app/ads/nextcycle.py`）」列為第三個開通點，但該檔案完全沒有 LLM 呼叫——沒有 import `app.llm`，預算建議來自寫死的 `BUDGET_ADVICE` 字典（該檔 docstring 自陳「三件事都由程式決定」）。這個開通點在程式裡不存在，實際只落地上述兩處。`app/ads/reading.py` 的三個 AI 呼叫（結算差異解釋、成效判讀、假說覆核）都是「系統已算好結論、AI 只翻人話」，開搜尋沒有意義，不列入。

替代方案曾評估：自建爬蟲／接 Google Trends 類第三方 API——前者是業界大廠養監測系統的重路線，後者官方 API 未開放且民間方案有法律灰色地帶，均不採。

## Consequences

- ADR 0001 的結論（方法論檔整份注入）**仍然有效**：web_search 是伺服器端搜尋工具，模型依舊不能讀本機檔案，progressive disclosure 的前提沒有成立。
- 搜尋結果進 prompt 會增加輸入 token，開通處的單次成本上升，花費上限檢查照舊生效。
- 繁中搜尋品質無官方保證，開通後需實測；品質不佳時退路是關掉該呼叫點的 tools 參數。
- 交接包的「外部深度調研」仍無法被取代（外部 Claude 的長時間研究能力非單次 web_search 可比），自動化另案。
