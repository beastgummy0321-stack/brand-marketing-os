# brand_intelligence —— 品牌／產品事實、規則、宣稱、渠道等資料底座（Phase 0）。
# 該檔已被 5eca0db 清除；欄位權威見 supabase/migrations/ 本身。

# 人物誌自有清理登記需在套件載入時生效，避免只用 repository 刪品牌時漏清新表。
from app.brand_intelligence import personas as personas  # noqa: E402,F401
