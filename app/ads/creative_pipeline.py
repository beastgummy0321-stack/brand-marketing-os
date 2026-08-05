# -*- coding: utf-8 -*-
"""app/ads/creative_pipeline.py — 內容產線小計（票 05-alerts-fuel-pipeline，駕駛艙用）。

獨立成小檔而不是加進 app/ads/creative.py：那檔已經超過 800 行拆檔門檻
（CLAUDE.md「單檔超過 800 行即為待拆，不得再往裡面加新功能」），新功能改開這檔，
不再往裡面加。
"""


def pipeline_counts(conn, brand_id: str) -> dict:
    """這個品牌全部素材依審核狀態計數，跨全部檔期不分期。DRAFT＝待審（還沒過關卡二
    素材採用，見 creative.approve_selection()）；APPROVED＝已發（關卡二採用後）。
    沒有任何素材時兩者皆回 0（空狀態）。"""
    rows = conn.execute(
        "SELECT status, COUNT(*) AS c FROM creative_variant WHERE brand_id = ? GROUP BY status",
        (brand_id,),
    ).fetchall()
    counts = {row["status"]: row["c"] for row in rows}
    return {"pending": counts.get("DRAFT", 0), "published": counts.get("APPROVED", 0)}
