# Brand Marketing OS

品牌行銷作業系統的共同語彙。只收這個專案特有、且容易被講混的詞。

## 方法論與提示詞

**方法論檔**：
`app/methodology/` 底下的 `.md`，會被 `app/llm/methodology.py` **整份原文組進 prompt**。它是程式零件，不是文件——每一行在每次生成時都要付 token。
_Avoid_: 文件、參考資料、docs

**對照表**：
`app/methodology/README.md` 裡「任務型別 → 必讀方法論檔」那張表，決定某類生成要餵哪幾份方法論檔。程式只解析這張表，README 其餘內容不影響行為。
_Avoid_: 索引、清單

## 文件膨脹

**強制載入預算**：
`CLAUDE.md`、`AGENTS.md`，加上它們兩個點名要讀的所有 `.md`，行數總和。這是唯一真正花 context 的量——沒被點名的檔案躺在磁碟上是零成本。
_Avoid_: 文件總量、行數上限、doc diet

**Sprawl（蔓生）**：
檔案單純太長，即使每一行都還有效、都不重複。
_Avoid_: 冗長、肥大

**Sediment（沉積）**：
舊內容一層層堆積永遠沒清掉，因為「加東西感覺安全、刪東西感覺危險」。沒有修剪紀律的檔案的預設下場。
_Avoid_: 累積、腐化、遺留

**No-op（白工指令）**：
模型本來就會照做的指示，寫了等於白付 token。檢驗方法：這行有沒有改變模型的預設行為？
_Avoid_: 廢話、贅述

**Duplication（重複）**：
同一個意思寫在兩個以上的地方。除了浪費 token，還會讓那個意思顯得比實際更重要。
_Avoid_: 重工、複製

（Sprawl／Sediment／No-op／Duplication 借自 [mattpocock/skills](https://github.com/mattpocock/skills) 的 `writing-great-skills`。）
