"""app/ads — 廣告分支（路線圖分支 1）：開期 → 計畫 → 素材 → 交接包 → 成效 → 判讀 → 下期草案。

共識與拆票見 docs/decisions/0022；資料表見 migrations/0001_tables.sql
（設計來源 docs/design/03-data-model.md §4、§5）。

模組切分：03 §8 的五個概念模組（Campaign Planning／Creative Studio／Publishing Handoff／
Performance Analytics／Experimentation）在實作上合併為本模組，理由見 migrations 檔頭。
"""


def register(app) -> None:
    """掛本模組所有路由（票 03-1：main.py 的 include_router 改成呼叫每個模組的
    register()，機械式搬移，路由本身不變）。"""
    from app.ads.routes import router as ads_router
    from app.ads.routes_claims_api import router as claims_api_router
    from app.ads.routes_learnings_api import router as learnings_api_router
    from app.ads.routes_onboarding_api import router as onboarding_api_router

    app.include_router(ads_router)
    app.include_router(claims_api_router)
    app.include_router(onboarding_api_router)
    app.include_router(learnings_api_router)
