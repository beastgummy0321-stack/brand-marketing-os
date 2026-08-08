-- app/ads/migrations/0015_creative_theme.sql
-- 主題資料模型（票 02-theme-tables，spec .scratch/creative-studio/issues/01-c-reshape-spec.md）。
--
-- 主題（creative_theme）＝一則廣告：屬於某個切角格（experiment_cell），對應某個廣告格式
-- （format_key，查 app/creative/format_specs.py 的 FORMAT_SPECS：single_image/carousel/video），
-- 有一句話名稱與素材資料夾短碼。底下掛多個主題元件（creative_theme_component：文案／標題／
-- 說明／圖片提示詞／輪播卡／腳本…，型別自由文字，對應 FORMAT_SPECS 各格式的 fields 鍵）。
--
-- 舊的素材產出表（creative_variant／final_asset）按 spec 定案封存不刪、不與本表建外鍵關聯
-- （C 段重做的是產出形狀，不是遷移舊資料）。
--
-- brand_id／campaign_cycle_id 反正規化到兩張表（比照 0011_settlement_snapshot.sql 的
-- reading_snapshot_input：兩層子表都直接帶 campaign_cycle_id），讓 app/ads/repository.py
-- CYCLE_CASCADE_TABLES／BRAND_CASCADE_TABLES 的刪除函式能一律用
-- `WHERE campaign_cycle_id = ?` / `WHERE brand_id = ?` 整批刪，不必多一層 join。

CREATE TABLE IF NOT EXISTS creative_theme (
    id TEXT PRIMARY KEY,                          -- cth_*
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    experiment_cell_id TEXT NOT NULL REFERENCES experiment_cell(id),  -- 所屬切角格
    format_key TEXT NOT NULL,                     -- single_image/carousel/video
    name TEXT NOT NULL,                            -- 一句話名稱
    folder_code TEXT NOT NULL,                     -- 素材資料夾短碼（四碼，資料夾命名＝人話名＋短碼）
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_creative_theme_brand_id ON creative_theme(brand_id);
CREATE INDEX IF NOT EXISTS idx_creative_theme_cycle_id ON creative_theme(campaign_cycle_id);
CREATE INDEX IF NOT EXISTS idx_creative_theme_cell_id ON creative_theme(experiment_cell_id);

CREATE TABLE IF NOT EXISTS creative_theme_component (
    id TEXT PRIMARY KEY,                          -- cthc_*
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    creative_theme_id TEXT NOT NULL REFERENCES creative_theme(id),
    component_type TEXT NOT NULL,                 -- image_prompt/body/title/description/
                                                    -- card_image_prompt/card_title/card_description/
                                                    -- script/hook_pool…（對應 format_specs 的 fields 鍵）
    sequence INTEGER,                              -- 輪播卡序；非輪播型 NULL
    content TEXT NOT NULL,
    fingerprint_json TEXT,                         -- 指紋（比照 creative_variant.fingerprint_json）
    over_budget INTEGER NOT NULL DEFAULT 0,        -- 超字標記：三道字數守門後仍超規格表預算
    similarity_flag INTEGER NOT NULL DEFAULT 0,    -- 標黃旗標：同批次相似度查核過近
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_creative_theme_component_theme_id
    ON creative_theme_component(creative_theme_id);
CREATE INDEX IF NOT EXISTS idx_creative_theme_component_brand_id
    ON creative_theme_component(brand_id);
CREATE INDEX IF NOT EXISTS idx_creative_theme_component_cycle_id
    ON creative_theme_component(campaign_cycle_id);
