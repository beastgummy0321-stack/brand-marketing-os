# 檔期還在跑，「建議下一期」卻說「這是第一期，還沒有上一期可以參考」

Status: open（drill 2026-09-09，Vivian step 11 **分數 2**、阿明 step 13）。**2／3 角色看到**，
兩人的反應差很多：阿明聳肩繼續開下一期，Vivian 判定「系統沒有下一期建議功能」而不導入。

成因：那句話的條件只有一個——`next_period_suggestion()` 回 `null`
（`frontend/src/components/schedule/ScheduleSetup.tsx:117`）。而
`app/schedule/period.py:346-348` 是 `latest_settled_period(...) is None → return None`：
**「沒有已結算的檔期」被寫成「這是第一期」**。兩人都有一期正在跑（阿明 09-09~09-23、
Vivian 09-10~09-24，演練當天 09-09），只是還沒到期、更不可能結算。

「結算這期」按鈕又只在 `period.status === "awaiting_data"` 才畫出來
（`frontend/src/components/schedule/PeriodPanel.tsx:39-52`），所以畫面上完全沒有東西告訴使用者
「要等這期跑完、結算過，下一期建議才會出現」。Vivian 的原話：
> 「我想基於這一週的成效（ROAS 2.20x）做下一期的規劃，但系統卻說『這是第一期』。」

同一個閘門還有第二個後果：方案 prompt 的【上一期】段（`app/schedule/jobs.py::_last_period_text`）
同樣只吃已結算的檔期，於是阿明第二期的方案寫「由於帳戶本月尚無花費資料」——當時儀表板上
明明有 5,180 TWD。**使用者會把這當成系統看不見自己的錢。**

`file:line`：`frontend/src/components/schedule/ScheduleSetup.tsx:117`（那句話）、
`app/schedule/period.py:346-348`（`null` 的真正條件）、
`frontend/src/components/schedule/PeriodPanel.tsx:39-52`（結算按鈕的出現條件）、
`app/schedule/jobs.py:285-291`（同一個閘門餵 prompt）。

做法（未裁決）：`next_period_suggestion()` 回 `null` 時分兩種狀態講——
沒有任何檔期＝「這是第一期」；有檔期但還沒結算＝「這一期到 <結束日> 才結束，
結算之後這裡會出現下一期的預算建議」。一句話兩個分支，資料 `period.status`／`end_date`
畫面已經有了。route A。
