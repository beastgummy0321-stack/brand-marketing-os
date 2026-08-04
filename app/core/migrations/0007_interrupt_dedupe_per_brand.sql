-- app/core/migrations/0007_interrupt_dedupe_per_brand.sql
-- 修憲落地 M6（docs/design/19-constitution-audit.md 第三節；決策 0037 第 18 條授權的
-- 本批唯一 schema 變更）：去重鍵原本只建在 dedupe_key 上，兩個品牌若剛好產生同一把
-- dedupe_key（例如同一天的「檔期提醒」），後到的那個品牌的提醒會被靜默吞掉——
-- 打斷佇列是 DESIGN.md §20.2 強制的全站唯一提醒出口，這是體檢找到唯一「現在就已經在漏」
-- 的品牌隔離缺陷。改法：唯一索引改建在 (brand_id, dedupe_key) 上，讓不同品牌各自去重。
--
-- brand_id 為 NULL 的全站層提醒怎麼辦：SQLite 對 UNIQUE 索引的 NULL 語意是「只要索引欄位
-- 之一是 NULL，這一列就不會跟任何其他列比對相等」（見 SQLite 官方文件 CREATE INDEX 章節），
-- 也就是說 (brand_id, dedupe_key) 索引**不會**阻擋兩筆 brand_id 皆為 NULL、dedupe_key
-- 相同的列互相重複——DB 層對全站層提醒不提供去重保障。這點不是本票新引入的缺口：
-- 應用層 enqueue()（app/core/interrupts.py）本來就是靠「INSERT 前先查有沒有同鍵」
-- 這一步在做真正的去重判斷，DB 唯一索引只是最後一道防線。本票同一 commit 已把
-- enqueue() 的查重條件從「WHERE dedupe_key = ?」改成「WHERE dedupe_key = ? AND
-- brand_id IS ?」（SQLite 的 IS 運算子對 NULL 值也能正確比對），全站層（brand_id 皆
-- NULL）提醒之間的去重因此仍由應用層負責、行為與改動前一致，不受這次索引改動影響。

DROP INDEX IF EXISTS idx_interrupt_dedupe_key;
CREATE UNIQUE INDEX IF NOT EXISTS idx_interrupt_brand_dedupe_key
    ON interrupt(brand_id, dedupe_key);
