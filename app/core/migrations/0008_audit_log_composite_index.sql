-- app/core/migrations/0008_audit_log_composite_index.sql
-- 修憲落地 A5（architecture-rules.md A5）：audit_log 缺 (brand_id, created_at) 複合索引，
-- 而分支 7 成效中樞的本職就是跨分支月報（依 brand_id 篩、依 created_at 排序／區間查詢）。

CREATE INDEX IF NOT EXISTS idx_audit_log_brand_created
    ON audit_log(brand_id, created_at);
