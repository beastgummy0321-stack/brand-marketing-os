# 演練 12 修復交接

## Execution update — 2026-10-06

The user approved the supervisor's presented F52 scope, 24-ticket order, delegation and acceptance
with "開始". Harness execution authorization is recorded and the feature branch has started.
The planning-only statements below describe the original handoff, not the current authorization.
Implementation and acceptance remain pending; original evidence and F48–F51 stay unchanged/open.

Beast，這份交接只完成系統規劃；尚未開始施工、監工、產品測試或審核。

## 下一個 session 先讀

1. [F52 計畫書](../../../.work/features/F52.md)：範圍、24 張工作票、先後順序與未授權狀態。
2. [問題核對表](remediation-findings.md)：36 個項目的證據、糾錯與負責票號。
3. [驗收標準](acceptance.md)：A01–A14，包含完整三期、數字對帳、故障復原與畫面驗收。
4. 只按接手工作閱讀領域規格：[投放中心](../../architecture/ads.md#654-drill-12-remediation-contracts-f52-planned-2026-10-06)、
   [素材工作檯](../../architecture/workbench.md#518-drill-12-creative-and-control-contracts-f52-planned-2026-10-06)、
   [建檔](../../architecture/intake.md#f52-drill-12-policy-and-source-attribution-contracts-planned-2026-10-06)。

工作票已寫在 `.work/ready/F52-I01.md` 至 `F52-I24.md`。
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
合併與完整整合；最後將所有畫面並排與新演練結果一次交給使用者。

本次只授權規劃。貼上下面的開場後，才由新 session 按其中的明確指示啟動。
若只請接手者讀文件，不能把文件中的 ready 狀態當成開工許可。
F48–F51 保持未結案；F52 也不代替它們的人工驗收。

## 開工前確認

- 規劃基準：`84a5640a`；所在分支：`feature/audit-d-http-figures-wizard-platform`。
- 預定施工分支：`codex/drill12-system-contracts`，此 session 尚未建立。
- 重新查看 Git 現況、現有工作與服務擁有者；不要直接使用舊報告的程序編號。
- Harness 使用本 session 主機載入的插件位置。沒有狀態注入才依 CLAUDE.md 查狀態。
- 未改產品程式、資料庫、服務或舊演練證據；未 commit、merge、push。
- 最後門檻仍是九項各至少 7 分、擋路缺陷 0 個；未達即保留開啟，
  不用平均分數、局部補測或佇列完成冒充結案。
- 不操作真實投放、不要求使用者花錢跑廣告、不啟用付費圖片服務。

## 可直接貼到新 session 的開場

> 讀取 D:\0UserProfile\Desktop\marketing\docs\drills\drill-12\Handoff.md 與其指向的 F52 計畫。我核准這份 F52 的範圍、24 張票順序與驗收標準。由你擔任監工，安排其他 Agent 分別施工、檢驗與獨立審核，依 Harness 執行整批；不要讓施工者自審。保留演練 12 原始證據與 F48–F51 未結案狀態，完成後交付整合結果、畫面並排及新的九面向演練報告。不得 push、操作真實投放或以未測項目冒充通過；只有會改變產品決策或擴大範圍的事項才回來問我。
