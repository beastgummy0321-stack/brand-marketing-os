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
| `creative-matrix.md` | 35 個創意角度、真人實拍 DNA、產圖硬規則、Hook 切法、影片腳本框架 |
| `customer-voice.md` | 顧客原話抽取規則、台灣在地管道 |

## 任務型別 → 必讀方法論檔對照表

| 任務型別 | 必讀方法論檔 |
|---|---|
| 檔期計畫生成 | `ads.md`、`ab-testing.md`、`customer-voice.md` |
| Hook／文案生成 | `ad-creative.md`、`copywriting.md`、`creative-matrix.md`、`customer-voice.md` |
| 圖片 Prompt 生成 | `creative-matrix.md`、`ad-creative.md` |
| 影片腳本生成 | `creative-matrix.md`、`copywriting.md` |
| 成效判讀／下期草案 | `ab-testing.md`、`ads.md` |
| 期中檢查點 | `ab-testing.md`（禁判勝負節） |

## 維護規則

- **每檔要有複查到期日**（frontmatter），到期進收件匣提醒。
- **上游更新＝人工重萃取**，來源在 `reference/marketingskills/`，不做自動同步。
- **新增檔要同步改上面兩張表**，不能只加檔案不更新索引。
- **只按消費拉動萃取**：沒有分支在用的方法論不要預先萃取，死文件只會增加維護負擔。
- **每檔 150 行上限**（`test_methodology.py` 把關）。超過就砍，不要放寬。
- **數字要有出處**：不在 `reference/` 樹裡的外部數字一律登記在下表。查不到出處的數字不得留在方法論檔裡。

## 外部來源登記（不在 `reference/` 樹裡的數字）

本檔不會被組進 prompt（`methodology.py` 只解析上面的對照表），所以網址寫在這裡不必付 token。

| 方法論位置 | 數字 | 出處 |
|---|---|---|
| `ads.md` §1 產能基準 | 保健類微型級距每週 3 則、頂級距 46 則 | Motion Creative Benchmarks 2026（2025-09-01–2026-01-01，578,750 則素材／6,015 帳戶／$1.29B）<https://motionapp.com/library/research/creative-benchmarks-2026/testing-by-vertical> |
| `ads.md` §3 帳戶 2–3 個活動 | 月花費 $1K–10K 建議 2–3 個活動 | <https://benly.ai/learn/meta-ads/ad-account-structure>（分級表，非 Meta 官方） |
| `ads.md` §4 ASC 低約 5% | 未設既有顧客預算上限時，每次購買成本降幅 | Meta 官方 <https://www.facebook.com/business/ads/meta-advantage/advantage-plus-shopping-ads>（2023 年的 17% 為舊版說法，勿再引用） |
| `ads.md` §5 概念壽命 2–3 週、10 天曲線 | 業界回報值，Meta 未公布官方數字 | <https://adlibrary.com/posts/ad-fatigue> |
