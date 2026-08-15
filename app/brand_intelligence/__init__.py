# brand_intelligence —— 品牌／產品事實、規則、宣稱、渠道等資料底座（Phase 0）。
# 見 docs/design/03-data-model.md §3.2。

# 人物誌自有清理登記需在套件載入時生效，避免只用 repository 刪品牌時漏清新表。
from app.brand_intelligence import personas as personas  # noqa: E402,F401
