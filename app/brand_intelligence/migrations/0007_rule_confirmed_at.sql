-- app/brand_intelligence/migrations/0007_rule_confirmed_at.sql
-- 規則最近確認時間（rule-lifecycle 02，ADR 0012 第二節）：prompt 上限超額時，soft 規則
-- 依這個時間排序（越新越優先）。只加欄位，不動既有列的其他值；既有列一併補成
-- created_at（等同「建立當下視為已確認」），向下相容，不需要使用者重新操作。
-- rule-lifecycle 01（有效期／重新確認）之後會加「重新確認」的顯式操作與 6 期未確認退回
-- pending_reconfirm 的邏輯，共用這一欄，屆時不用再改 schema。

ALTER TABLE rule ADD COLUMN confirmed_at TEXT;
UPDATE rule SET confirmed_at = created_at WHERE confirmed_at IS NULL;
