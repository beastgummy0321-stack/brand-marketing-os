# 演練 12 修復交接

## Execution update — 2026-10-07

All 24 F52 repair issues are DONE and locally merged on `codex/drill12-system-contracts`.
Latest repair merge HEAD: `2559254e1bc63c5594f2b67d508897aefecf9c86`.
The newest user instruction is to pause after repairs and report progress, without beginning
the next complete test round. Harness F52 authorization is revoked at this safe point.
Repair queue progress is 24/24 (100%); final integration, independent three-period/control/fault/
quality acceptance and human acceptance remain deferred. F52 and F48–F51 stay open.

24 張修復票已完成施工、必要檢查、獨立審查與本機合併，目前暫停。
這個 100% 只代表已規劃修復票全部完成；完整驗證尚未執行，原演練不能改判通過。

## 下一個 session 先讀

1. [F52 計畫書](../../../.work/features/F52.md)：範圍、24 張已完成工作票與目前暫停邊界。
2. [問題核對表](remediation-findings.md)：36 個項目的證據、糾錯與負責票號。
3. [驗收標準](acceptance.md)：A01–A14，包含完整三期、數字對帳、故障復原與畫面驗收。
4. 只按接手工作閱讀領域規格：[投放中心](../../architecture/ads.md#654-drill-12-remediation-contracts-f52-planned-2026-10-06)、
   [素材工作檯](../../architecture/workbench.md#518-drill-12-creative-and-control-contracts-f52-planned-2026-10-06)、
   [建檔](../../architecture/intake.md#f52-drill-12-policy-and-source-attribution-contracts-planned-2026-10-06)。

工作票在 `.work/done/F52-I01.md` 至 `F52-I24.md`；沒有待做或施工中的 F52 修復票。
規劃文件與票使用英文，方便其他 Agent 依同一份明確規格施工。

## 核心修復方向

策略、實際配置與文案要用同一份已接受的決策，像同一張施工圖一路交到工地，
不能上游說要學生、下游卻全部做健身族。程式負責金額、範圍與對應檢查，
模型負責受眾與創意判斷；保留廣告不預設全部升成主力。

成效數字要帶明確期間；核准要核准畫面上看到的版本；新廣告要回到原交接項目核對；
跨月重試要救回原本失敗的月份。剩餘畫面問題按畫面分票，
已修好的負數、儲存遺失、預算重複保留與離線提示則做回歸檢查。

## 已糾正的報告解讀

- 文案固定產出五版符合既有規則；「可填一版」才是畫面問題。
- 被質疑的幾句預填內容存在網站副本；有來源不等於內容真實或可合法刊登。
- P2/P3 有換掉較差廣告，不能說完全沒有學習；問題是理由與實際配置不一致。
- 模擬成效低落是未過門檻，不能直接當成某一行程式錯誤，也不能調模擬器讓它過。
- 已補測或已修復不會把演練 12 改成通過；原始資料與分數保留。
- 停 worker 沒中斷跑在 Web 的策略工作；真正的策略中斷與登入過期仍須補驗。
- 三份控制項清單的計數方式不同，不能相加算總通過率。

## 接手者的權責

接手 Agent 擔任監工，按票分配 Coding、檢驗與獨立審核 Agent。
施工者不能兼任自己重要變更的獨立審核者。監工維護票與範圍、安排隔離環境、
合併與證據保存。未來獲得明確恢復指示後，才進行完整整合與新演練。

先前的「開始」已授權並完成整批修復；使用者後來要求修完即停。
不能沿用舊的整批授權，自動啟動下一輪完整驗證。只讀交接不等於恢復執行。
F48–F51 保持未結案；F52 也不代替它們的人工驗收。

## 恢復完整驗證前確認

- 歷史規劃基準：`84a5640a`；目前分支：`codex/drill12-system-contracts`。
- 修復合併版本：`2559254e1bc63c5594f2b67d508897aefecf9c86`；其後只更新這次暫停交接。
- 重新查看 Git 現況、現有工作與服務擁有者；不要直接使用舊報告的程序編號。
- Harness 使用本 session 主機載入的插件位置。沒有狀態注入才依 CLAUDE.md 查狀態。
- 修復已在本機 commit、merge；未 push，未操作真實投放，原演練證據未改。
- 修復預覽已停止。完整整合、新三期演練、真正登入過期、控制項與故障驗收仍待恢復後執行。
- 最後門檻仍是九項各至少 7 分、擋路缺陷 0 個；未達即保留開啟，
  不用平均分數、局部補測或佇列完成冒充結案。
- 不操作真實投放、不要求使用者花錢跑廣告、不啟用付費圖片服務。

## 可直接貼到新 session 的開場

> 讀取 D:\0UserProfile\Desktop\marketing\docs\drills\drill-12\Handoff.md 與其指向的 F52 計畫。24 張修復票已完成，目前暫停。先核對目前版本與未驗證清單並回報，不重做已完成修復，也不啟動完整整合或新演練；等待我明確要求恢復。保留原始證據與 F48–F52 未結案狀態，不 push、不操作真實投放。

## 最後一張修復的交件位置

- 最後修復來源：`87d67a54`；必要檢查為資料端 69 項與 5 子案例、前端 131 項，以及程式與建置檢查。
- 獨立審查：`.harness/scratch/f52/reviews/I14-87d67a54.json`，兩軸皆 CLEAR、0 項問題。
- 固定來源、原始紀錄、畫面與並排：`.harness/scratch/f52/tests/I14-87d67a54-receipts/`。
- 本張合併檢查：`.harness/scratch/f52/tests/I14-87d67a54-merge/`，8 項通過。
- 畫面證據是本機隔離資料與登入替身；一般對照為資料缺漏畫面，完整 Live 金額分支另有元件檢查。
  不能宣稱真正 Auth、Meta、模型、三期品質、完整控制項或人工驗收已通過。
