# 刪品牌的清理登記處漏了九張帶 brand_id 的表，而它宣稱的涵蓋率警報器不存在

Status: 開著——2026-09-07 幫使用者洗本機資料時，`delete_brand()` 直接拋 FK 例外撞出來的。
在真的有付費使用者之前必須修：刪品牌是使用者按得到的按鈕，現在有兩種壞法。

## 成因

`app/core/cleanup.py` 是登記制：各模組在自己的 `repository.py` 檔尾 `register()` 進來，宣告
`brand_tables`（刪品牌時本模組會清哪些表）。`delete_brand()`（`app/brand_intelligence/repository.py:254`）
叫 `cleanup.delete_all()` 跑完所有登記模組，再刪 `brand` 那一列。

`cleanup.py:37-40` 的說明寫著這份宣告的唯一存在理由是給「涵蓋率警報器
（`app/tests/test_cleanup_coverage.py`）」比對——**那個檔案不存在**。`app/tests/` 底下跟 cleanup
有關的只有 `test_cleanup_registry.py`，而它測的是登記機制本身（用假模組驗參數檢查、全有全無回捲），
從頭到尾沒有拿真資料庫的表清單來比對。所以「宣告了但沒人清」這件事沒有任何東西會叫。

實測（2026-09-07，本機）：8 個登記模組宣告 33 張表，資料庫裡帶 `brand_id` 的表有 42 張，差 9 張。

```python
declared = set().union(*(e["brand_tables"] for e in cleanup._REGISTRY.values()))
real = {r["table_name"] for r in conn.execute(
    "select table_name from information_schema.columns"
    " where table_schema='public' and column_name='brand_id'")}
sorted(real - declared)
```

漏掉的九張，按後果分兩類：

| 表 | 有沒有 FK 指向 `brand` | 後果 |
|---|---|---|
| `campaign_period` | 有 | **刪不掉**：`ForeignKeyViolation`，整個交易回捲 |
| `channel_entity_map` | 有 | 同上 |
| `llm_task` | 沒有 | 悄悄留下。裡面的 `rendered_output` 是這個品牌的 AI 產出全文 |
| `campaign_period_budget_version` | 沒有 | 悄悄留下 |
| `period_node_membership` | 沒有 | 悄悄留下 |
| `approval` | 沒有 | 悄悄留下 |
| `decision` | 沒有 | 悄悄留下 |
| `brand_dismissed_calendar_category` | 沒有 | 悄悄留下 |
| `audit_log` | 沒有 | 可能是故意的——稽核紀錄本來就該活過被稽核的對象。要在 ADR 裡講明，不是默認 |

## 影響

1. **排程過的品牌刪不掉。** 只要出過一次方案就有 `campaign_period` 一列，使用者按刪除只會拿到一個
   資料庫例外。今天撞到的就是這個。
2. **刪得掉的那些品牌會留下資料。** `llm_task` 帶著該品牌的 AI 產出全文，刪完還在庫裡。多租戶上線後
   這是「使用者刪了品牌，內容還在」——真的要在收費前處理掉。
3. 兩種壞法的共同根因是同一個：**設計依賴的那個警報器從來沒被寫出來**，而文件寫得像它存在。

## 修法

三件事，順序不能顛倒：

1. 先補 `app/tests/test_cleanup_coverage.py`：查 `information_schema` 拿所有帶 `brand_id` 的表，
   減掉登記處宣告的集合，差集非空就紅。**要先證紅一次**（現在它本來就會紅，九張表就是證據）。
   刻意不清的表（`audit_log`）走一份寫在測試裡、只准變短的豁免清單，並附一句理由。
2. 各模組把自己的表補進 `register()` 的 `brand_tables` 與 `delete_brand`：`campaign_period`／
   `campaign_period_budget_version`／`period_node_membership`／`channel_entity_map` 屬 schedule，
   `llm_task` 屬 llm，`approval`／`decision`／`brand_dismissed_calendar_category` 屬 core。
3. 刪除順序照 FK 拓樸排：`llm_task` 指向 `campaign_period`，所以 `llm_task` 要先刪。
   今天手動洗的時候就是因為先刪 `campaign_period` 才撞第二次例外。

`file:line`：`app/core/cleanup.py:37-40`（宣稱的警報器）、`app/brand_intelligence/repository.py:254-286`
（`delete_brand()`）、`app/schedule/repository.py:720-731`（schedule 的登記，缺四張表）。
