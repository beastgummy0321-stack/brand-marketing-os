-- T2 批次 A（契約 4.1）：人物誌是品牌層衍生資料；只新增這一張已批准的小表。
CREATE TABLE persona (
    id TEXT PRIMARY KEY,
    brand_id TEXT NOT NULL,
    title TEXT NOT NULL,
    when_needed TEXT NOT NULL,
    care_about TEXT NOT NULL,
    hesitation TEXT NOT NULL,
    where_to_find TEXT NOT NULL,
    created_at TEXT NOT NULL
);
