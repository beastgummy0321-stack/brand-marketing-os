"""app/ads/theme_attribution.py — 主題元件層歸因（票 12-attribution-adjust，D 段）。

同步時拉回的 body／title／description 素材元件層 breakdown（app/ads/meta_api.py
ComponentBreakdownRow）直接覆蓋寫回 creative_theme_component 自己的最新成效欄位
（app/ads/migrations/0016_theme_component_performance.sql 加的
meta_asset_id／performance_impressions／performance_clicks／performance_conversions／
performance_synced_at）。規格書與使用者故事只要求同一主題內文案誰贏誰輸的當下相對排名，
不需要時間序列，所以不開獨立快照表，每次同步覆蓋舊值即可。

對回主題元件靠 Meta 素材 id（meta_asset_id）跨次同步保持穩定：
- 第一次看到某個 meta_asset_id：靠文字完全吻合，在「這個檔期＋這個元件型別」範圍內找
  唯一對應的 creative_theme_component（bootstrap 對應）。找不到或不唯一就不對回，這一筆
  這次同步直接跳過——ponytail：已知天花板，同批文字剛好重複或系統存檔文字已經跟 Meta
  不同步時會落空，之後真的常發生再加更嚴謹的比對。
- 之後同一個 meta_asset_id 再出現：查 creative_theme_component.meta_asset_id 直接認回，
  比對這次 Meta 端文字跟系統存檔目前的內容——一致就零動作；不一致代表使用者在 Meta
  後台手動改了文案，呼叫引擎的無狀態重打指紋入口（theme_engine.refresh_component_fingerprint）
  算新指紋，文字與指紋一起寫回 creative_theme_component，並留一筆稽核（票 12 驗收 2）。
"""


from app.ads import theme_engine
from app.core.audit import write_audit
from app.core.db import jsonb, now_utc

# Meta breakdown 鍵 → creative_theme_component.component_type（本系統的欄位名沒有
# _asset 尾碼，見 app/creative/theme_engine.py normalize_single_image()）。
_ASSET_FIELD_TO_COMPONENT_TYPE = (
    ("body_asset", "body"), ("title_asset", "title"), ("description_asset", "description"),
)


def record_component_breakdown(conn, brand_id: str, cycle_id: str | None, row, *,
                               actor: str) -> None:
    """一列 meta_api.ComponentBreakdownRow → 覆蓋更新一到三個 creative_theme_component
    的最新成效（body/title/description 各有值才更新）。沒有檔期歸屬（cycle_id is None，
    這支廣告還沒認領到任何品牌檔期）時整批跳過——creative_theme_component 一定掛在某個
    檔期底下，沒檔期就沒有元件可比對。
    """
    if cycle_id is None:
        return
    for asset_field, component_type in _ASSET_FIELD_TO_COMPONENT_TYPE:
        asset = getattr(row, asset_field, None)
        if not isinstance(asset, dict):
            continue
        asset_id = asset.get("id")
        text = asset.get("text")
        if not asset_id or not isinstance(text, str) or not text.strip():
            continue
        _record_one(conn, brand_id, cycle_id, row, component_type=component_type,
                   asset_id=str(asset_id), text=text.strip(), actor=actor)


def _record_one(conn, brand_id: str, cycle_id: str, row, *, component_type: str,
                asset_id: str, text: str, actor: str) -> None:
    component_id = _resolve_component(conn, brand_id, cycle_id, asset_id, component_type, text,
                                      actor=actor)
    if component_id is None:
        return  # 對不回任何元件（bootstrap 找不到或不唯一）：這一筆這次同步沒地方落地
    conn.execute(
        "UPDATE creative_theme_component SET meta_asset_id = %s, performance_impressions = %s,"
        " performance_clicks = %s, performance_conversions = %s, performance_synced_at = %s"
        " WHERE brand_id = %s AND id = %s",
        (asset_id, row.impressions, row.clicks, row.conversions, now_utc(), brand_id,
         component_id),
    )


def _resolve_component(conn, brand_id: str, cycle_id: str, asset_id: str, component_type: str,
                       text: str, *, actor: str) -> str | None:
    prior = conn.execute(
        "SELECT id FROM creative_theme_component WHERE brand_id = %s AND meta_asset_id = %s"
        " AND component_type = %s",
        (brand_id, asset_id, component_type),
    ).fetchone()
    if prior:
        component_id = prior["id"]
        _reconcile_if_changed(conn, brand_id, component_id, text, actor=actor)
        return component_id

    # 第一次看到這個 Meta 素材 id：靠文字完全吻合，在這個檔期＋型別範圍內找唯一對應的
    # 元件。使用者剛把系統產出的文字貼進 Meta 後台時，文字理應一字不差。
    matches = conn.execute(
        "SELECT id FROM creative_theme_component WHERE brand_id = %s AND campaign_cycle_id = %s"
        " AND component_type = %s AND content = %s",
        (brand_id, cycle_id, component_type, text),
    ).fetchall()
    return matches[0]["id"] if len(matches) == 1 else None


def _reconcile_if_changed(conn, brand_id: str, component_id: str, text: str, *,
                          actor: str) -> None:
    row = conn.execute(
        "SELECT content FROM creative_theme_component WHERE brand_id = %s AND id = %s",
        (brand_id, component_id),
    ).fetchone()
    if row is None or row["content"] == text:
        return  # 一致 → 零動作（票 12 驗收 2）

    new_fingerprint = theme_engine.refresh_component_fingerprint(conn, brand_id, text)
    before = {"content": row["content"]}
    conn.execute(
        "UPDATE creative_theme_component SET content = %s, fingerprint_json = %s"
        " WHERE brand_id = %s AND id = %s",
        (text, jsonb(new_fingerprint) if new_fingerprint else None,
         brand_id, component_id),
    )
    write_audit(conn, brand_id=brand_id, entity_type="creative_theme_component",
               entity_id=component_id, action="sync_from_meta", actor=actor,
               before=before, after={"content": text},
               reason="偵測到 Meta 端文案跟系統存檔不一致（可能被人工改過），自動同步並重打指紋")


# ---------------------------------------------------------------------------
# 元件層相對排名（票 12 驗收 4）
# ---------------------------------------------------------------------------

def rank_theme_components(conn, brand_id: str, theme_id: str) -> list:
    """主題底下每個文字元件的相對排名：同一元件型別（body/title/description）內部各自
    排名，只回排名所需的比較用指標（曝光／點擊／轉換）——刻意不回花費或營收，那兩項要
    對得上 Meta 官方報表才有意義，元件層數字本來就不保證對得起來，不提供絕對值對帳介面
    （ADR 0008 二、票 12 驗收 4）。還沒同步過（performance_synced_at 是 NULL）的元件不
    出現在結果裡。
    """
    rows = [dict(r) for r in conn.execute(
        "SELECT id AS component_id, component_type,"
        " performance_impressions AS impressions, performance_clicks AS clicks,"
        " performance_conversions AS conversions"
        " FROM creative_theme_component"
        " WHERE brand_id = %s AND creative_theme_id = %s AND performance_synced_at IS NOT NULL",
        (brand_id, theme_id),
    )]

    by_type: dict = {}
    for row in rows:
        by_type.setdefault(row["component_type"], []).append(row)

    result = []
    for component_type, items in by_type.items():
        items.sort(key=lambda r: r["conversions"], reverse=True)
        for rank, item in enumerate(items, start=1):
            item["rank"] = rank
            result.append(item)
    return result
