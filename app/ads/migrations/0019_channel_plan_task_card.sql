-- app/ads/migrations/0019_channel_plan_task_card.sql
-- T3：Act2 五類管道分工與 Act3 任務卡。兩表都依檔期而生，檔期刪除時連帶刪除。

CREATE TABLE IF NOT EXISTS channel_plan (
    id TEXT PRIMARY KEY,
    brand_id TEXT NOT NULL,
    cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
    channel TEXT NOT NULL,
    job TEXT NOT NULL,
    pct INTEGER NOT NULL,
    expected TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    depth TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (brand_id, cycle_id, channel)
);
CREATE INDEX idx_channel_plan_brand_cycle ON channel_plan(brand_id, cycle_id);

CREATE TABLE IF NOT EXISTS task_card (
    id TEXT PRIMARY KEY,
    brand_id TEXT NOT NULL,
    cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
    channel TEXT NOT NULL,
    title TEXT NOT NULL,
    draft_hint TEXT,
    done INTEGER NOT NULL DEFAULT 0 CHECK (done IN (0, 1)),
    created_at TEXT NOT NULL,
    done_at TEXT
);
CREATE INDEX idx_task_card_brand_cycle ON task_card(brand_id, cycle_id);
