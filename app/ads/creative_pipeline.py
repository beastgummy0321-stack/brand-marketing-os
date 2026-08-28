"""app/ads/creative_pipeline.py — 內容產線小計（票 05-alerts-fuel-pipeline，駕駛艙用）。

獨立成小檔而不是加進 app/ads/creative.py：那檔已經超過 800 行拆檔門檻
（CLAUDE.md「單檔超過 800 行即為待拆，不得再往裡面加新功能」），新功能改開這檔，
不再往裡面加。
"""

from app.ads import theme_repository as theme_repo


def pipeline_counts(conn, brand_id: str) -> dict:
    """這個品牌全部素材依審核狀態計數，跨全部檔期不分期（票 03-close-repoint-gaps：
    資料源改為主題表——creative_variant 沒有存活寫入路徑，查它兩個數字恆為 0）。
    pending＝主題還沒採用（對應舊 DRAFT／待審）；published＝主題已採用（對應舊
    APPROVED／已發，見 theme_repository.count_components_by_adoption() docstring）。
    沒有任何素材時兩者皆回 0（空狀態）。"""
    return theme_repo.count_components_by_adoption(conn, brand_id)
