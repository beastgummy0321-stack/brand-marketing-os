-- app/ads/migrations/0020_publishing_package_no_variant_fk.sql
-- 交接包脫鉤舊素材表（票 02-repoint-creative-readers，DEC-A）。
--
-- 背景：交付／交接包現在要能存「主題元件 id」（creative_theme_component.id，cthc_*），
-- 但 publishing_package.hook_id／.copy_variant_id／.script_id 原本硬綁
-- `REFERENCES creative_variant(id)`——存 cthc_* 進去會被外鍵擋下
-- （sqlite3.IntegrityError: FOREIGN KEY constraint failed，已實測驗證）。
-- 這三欄本來就沒有型別區分存的是哪張表的 id（只是 TEXT），拿掉外鍵不影響資料完整性，
-- 只是不再由資料庫層保證「這個 id 一定存在於 creative_variant」。
--
-- 保留其餘外鍵：campaign_cycle_id／experiment_cell_id／final_asset_id 不動。
-- creative_variant 表本身與其舊寫入路徑本票不動（見票 D6：另案處理）。
--
-- SQLite 沒有「ALTER TABLE DROP CONSTRAINT」，拿掉欄位上的 REFERENCES 只能整張表重建
-- （建新表／搬資料／砍舊表／改名）。app/core/db.py run_migrations() 把整份 migration 檔包在
-- 一個明確 BEGIN 交易裡逐句執行（修憲落地 A5）——`PRAGMA foreign_keys` 在交易中途切換是
-- 靜默的 no-op（已實測驗證：交易內執行 `PRAGMA foreign_keys = OFF` 之後讀回來仍是 1），
-- 所以整段重建必須在「外鍵持續生效」的前提下完成，不能像 SQLite 官方文件建議的那樣
-- 交易外先關外鍵。
--
-- 這造成一個真正的限制：external_ad_mapping.publishing_package_id 有
-- `REFERENCES publishing_package(id)`（無 ON DELETE 子句，預設 NO ACTION）——若直接
-- `DROP TABLE publishing_package`，只要有任何 external_ad_mapping 列引用著現存的
-- publishing_package 列，SQLite 會在 DROP 當下就丟出 FOREIGN KEY constraint failed
-- （已實測驗證：子表仍引用時 DROP 會炸；子表引用先清空、重建完再寫回原值則會成功）。
-- 因此下面先把 external_ad_mapping.publishing_package_id 暫存到一張過渡表、整批設回
-- NULL（可為 NULL 欄位，設回 NULL 不違反任何約束），等新表重建、改名回原本的表名之後，
-- 再用暫存的值寫回去——同一筆資料、同一個交易，只是中途借了個地方放一下，不是資料遺失。

CREATE TABLE _pp_migration_0020_stash (
    external_ad_mapping_id TEXT PRIMARY KEY,
    publishing_package_id TEXT NOT NULL
);

INSERT INTO _pp_migration_0020_stash (external_ad_mapping_id, publishing_package_id)
SELECT id, publishing_package_id FROM external_ad_mapping WHERE publishing_package_id IS NOT NULL;

UPDATE external_ad_mapping SET publishing_package_id = NULL WHERE publishing_package_id IS NOT NULL;

CREATE TABLE publishing_package_new (
    id TEXT PRIMARY KEY,                    -- pkg_*
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    experiment_cell_id TEXT REFERENCES experiment_cell(id),
    product_id TEXT,
    final_asset_id TEXT REFERENCES final_asset(id),
    hook_id TEXT,                           -- 原 REFERENCES creative_variant(id)，本票拿掉
    script_id TEXT,                         -- 同上
    copy_variant_id TEXT,                   -- 同上
    campaign_name TEXT NOT NULL,
    adset_name TEXT NOT NULL,
    ad_name TEXT NOT NULL,
    destination_url TEXT NOT NULL,
    utm_json TEXT NOT NULL,
    placement TEXT,
    objective TEXT,
    daily_budget REAL,
    note TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

INSERT INTO publishing_package_new (
    id, brand_id, campaign_cycle_id, experiment_cell_id, product_id, final_asset_id,
    hook_id, script_id, copy_variant_id, campaign_name, adset_name, ad_name,
    destination_url, utm_json, placement, objective, daily_budget, note, status, created_at
)
SELECT
    id, brand_id, campaign_cycle_id, experiment_cell_id, product_id, final_asset_id,
    hook_id, script_id, copy_variant_id, campaign_name, adset_name, ad_name,
    destination_url, utm_json, placement, objective, daily_budget, note, status, created_at
FROM publishing_package;

DROP TABLE publishing_package;

ALTER TABLE publishing_package_new RENAME TO publishing_package;

CREATE INDEX IF NOT EXISTS idx_publishing_package_brand_id ON publishing_package(brand_id);
CREATE INDEX IF NOT EXISTS idx_publishing_package_cycle_id ON publishing_package(campaign_cycle_id);

UPDATE external_ad_mapping
SET publishing_package_id = (
    SELECT publishing_package_id FROM _pp_migration_0020_stash
    WHERE _pp_migration_0020_stash.external_ad_mapping_id = external_ad_mapping.id
)
WHERE external_ad_mapping.id IN (SELECT external_ad_mapping_id FROM _pp_migration_0020_stash);

DROP TABLE _pp_migration_0020_stash;
