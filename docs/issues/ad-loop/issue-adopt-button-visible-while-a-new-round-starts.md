# 按下「跑一次判讀」之後、新一輪真的開跑之前，舊建議的「採用」還按得下去

Status: 開著——票 02 的獨立審查（2026-09-06）抓到，判 note 不判 reject，理由見下。

## 成因

`frontend/src/components/cockpit/DiagnosisPanel.tsx:132-154`（`DiagnosisResult`）決定要不要顯示
建議卡（含「採用」按鈕）只看 `diagnosis.status`，不看 `submitting`／`busy`。

按下按鈕後 `onRun()` 一 resolve 就 `setState({status:"ready", diagnosis})`，而那個回應**幾乎必然
還是上一輪的** `succeeded`——worker 要先跑完 `brand_creative_performance()`＋`breakeven_roas()`＋
`compress()`＋`methodology.compile()`（`app/schedule/jobs.py:336-352`）才寫得出新一輪第一列
`running`。所以舊的 5 張卡與「採用」按鈕在這段空窗期照樣可見可點。

實際擋住它的是「下一次 2 秒輪詢會摸到新一輪的 `running` 列，把卡片藏起來」——worker 起跑
（含前置運算與排隊延遲）超過 2 秒時，這個空窗就還在。

## 影響

使用者在空窗期按「採用」→ 後端已經在讀新一輪（還沒跑完）→ 回 400
（`SUGGESTION_NOT_FOUND_MESSAGE`）。乾淨的錯誤，沒有寫壞資料、沒有跨租戶、沒有算錯錢，
但畫面出現一句莫名其妙的錯誤訊息。

## 為什麼票 02 沒有當場修

票沒有任何一條 done-check 說「採用零 400」；不落在四類 route C（schema／模組邊界／金流／
租戶隔離）之一，所以審查判 note 而非 reject（`agent-brief.md` 的三判決規則）。

## 修法（便宜）

`DiagnosisResult` 在 `panel.busy` 為真時就把建議卡（或至少「採用」按鈕）停用，不要只靠輪詢
把它藏起來——按鈕的可用與否跟「有沒有一輪正在跑」綁在一起，而不是跟「上一次讀到什麼」綁在一起。

`frontend/src/components/cockpit/DiagnosisPanel.tsx:132`
