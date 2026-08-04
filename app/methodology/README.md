---
來源: 各檔 frontmatter
複查到期日: 2027-02-01
---

# 方法論檔索引

`app/methodology/` 是**程式零件**：`app/llm/methodology.py` 依下方對照表，把指定的檔案**整份原文**組進生成 prompt。每一行在每次生成時都要付 token。

## 檔案索引

| 檔案 | 內容 |
|---|---|
| `ads.md` | Meta 打法、預算出價、擴量紀律、投放前清單、健康類廣告政策 |
| `ad-creative.md` | 三種生成模式、grounding 要求、15 款樣板、Meta 字數規格 |
| `ab-testing.md` | 樣本數速查表、Peeking 紀律、ICE 排序 |
| `copywriting.md` | 五大原則、寫作規則、CTA、Hook 公式、改寫範例、心理模型 |
| `creative-matrix.md` | 35 個創意角度、真人實拍 DNA、產圖硬規則、Hook 切法 |
| `customer-voice.md` | 顧客原話抽取規則、台灣在地管道 |

## 任務型別 → 必讀方法論檔對照表

| 任務型別 | 必讀方法論檔 |
|---|---|
| 檔期計畫生成 | `ads.md`、`ab-testing.md`、`customer-voice.md` |
| Hook／文案生成 | `ad-creative.md`、`copywriting.md`、`creative-matrix.md`、`customer-voice.md` |
| 圖片 Prompt 生成 | `creative-matrix.md`、`ad-creative.md` |
| 成效判讀／下期草案 | `ab-testing.md`、`ads.md` |
| 期中檢查點 | `ab-testing.md`（禁判勝負節） |

## 維護規則

- **每檔要有複查到期日**（frontmatter），到期進收件匣提醒。
- **上游更新＝人工重萃取**，來源在 `reference/marketingskills/`，不做自動同步。
- **新增檔要同步改上面兩張表**，不能只加檔案不更新索引。
- **只按消費拉動萃取**：沒有分支在用的方法論不要預先萃取，死文件只會增加維護負擔。
- **每檔 150 行上限**（`test_methodology.py` 把關）。超過就砍，不要放寬。
