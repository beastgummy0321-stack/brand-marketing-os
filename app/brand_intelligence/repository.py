"""app/brand_intelligence/repository.py — Brand Intelligence 存取層。

兩份原始文件皆已被 5eca0db 清除；欄位權威見 supabase/migrations/ 本身。

硬性規則（呼叫端請勿繞過）：
1. 所有品牌範圍查詢一律以 brand_id 過濾，沒有「查全部品牌資料」的無過濾入口。
   （brand 本身是隔離根鍵，list_brands() 是切換品牌用的清單，本來就橫跨品牌，不算例外。）
2. 每次資料異動（新增／編輯／確認）都寫一筆 audit_log，含 before/after JSON 與 actor。
3. brand_fact／product_fact／rule／claim 異動時，對應聚合（brand 或 product）的
   knowledge_version + 1（rule/claim 依 product_id 是否為空決定影響品牌還是產品聚合）。
4. 事實確認流程：pending → confirmed 時記錄 confirmed_by / confirmed_at。
5. 人工編輯直接生效、不退回 pending；編輯者成為最新確認人（決策 0013 用戶優先，
   取代原設計文件 §17 決策 3，該文件已被 5eca0db 清除）。
6. 產品以封存為預設；已封存的產品可再進一步硬刪除（delete_product），一併清掉本模組
   掛在該產品下的資料，audit_log 留下 before 全文與各表筆數（決策 0020，比照品牌 0015）。
   事實／規則／宣稱單筆硬刪除同樣適用（before 全文記 audit_log，決策 0013）。
7. 品牌以封存為預設；已封存的品牌可再進一步硬刪除（delete_brand），一併清掉本模組
   所有掛在該品牌下的資料，audit_log 留下 before 全文與各表筆數（決策 0015）。
   建檔精靈（intake）的資料由該模組自行清，本檔不跨模組刪表。
"""


from datetime import date

import psycopg

# Owned Channel 已拆進 repository_channels.py（票 B2-library，本檔行數頂到
# docs/tech-debt.md 凍結上限，不得再加）；這裡 re-export，讓既有 `repo.create_channel()`
# 等呼叫端寫法不必改。
from app.brand_intelligence.repository_channels import (  # noqa: F401
    create_channel,
    delete_channel,
    get_channel,
    list_channels,
    update_channel,
)
from app.core import cleanup
from app.core import settings as coresettings
from app.core.audit import write_audit
from app.core.db import Conn, ConnProxy, jsonb, new_id, now_utc


def _require(value, message: str) -> None:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(message)


def _row(cursor_row) -> dict | None:
    return dict(cursor_row) if cursor_row is not None else None


def _rows(cursor) -> list:
    return [dict(r) for r in cursor.fetchall()]


def _bump_brand_version(conn: Conn, brand_id: str) -> None:
    conn.execute(
        "UPDATE brand SET knowledge_version = knowledge_version + 1, updated_at = %s WHERE id = %s",
        (now_utc(), brand_id),
    )


def _bump_product_version(conn: Conn, brand_id: str, product_id: str) -> None:
    conn.execute(
        "UPDATE product SET knowledge_version = knowledge_version + 1, updated_at = %s "
        "WHERE brand_id = %s AND id = %s",
        (now_utc(), brand_id, product_id),
    )


# ---------------------------------------------------------------------------
# Brand
# ---------------------------------------------------------------------------

def create_brand(
    conn: Conn, *, org_id: str, name: str, client_name: str | None, actor: str
) -> dict:
    _require(name, "brand.name 為必填")
    _require(actor, "actor 為必填")
    brand_id = new_id("brd")
    ts = now_utc()
    row = {
        "id": brand_id, "name": name, "client_name": client_name or None,
        "status": "active", "knowledge_version": 1, "created_at": ts, "updated_at": ts,
    }
    conn.execute(
        "INSERT INTO brand (id, org_id, name, client_name, status, knowledge_version, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (row["id"], org_id, row["name"], row["client_name"], row["status"], row["knowledge_version"],
         row["created_at"], row["updated_at"]),
    )
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="brand", entity_id=brand_id,
                action="create", actor=actor, before=None, after=row)
    conn.commit()
    return row


def get_brand(conn: Conn | ConnProxy, brand_id: str) -> dict | None:
    return _row(conn.execute("SELECT * FROM brand WHERE id = %s", (brand_id,)).fetchone())


def _org_id_for_brand(conn: Conn, brand_id: str) -> str:
    """票 03-1：org_id 是 brand_id 的確定性函式，查一次權威值，不逐層往上傳當參數；
    不是隱藏 contextvar——輸入是明確的 brand_id。只有 create_brand() 例外，當參數傳入。"""
    row = conn.execute("SELECT org_id FROM brand WHERE id = %s", (brand_id,)).fetchone()
    if row is None:
        raise ValueError(f"找不到品牌：{brand_id}")
    return row["org_id"]


def list_brands(conn: Conn, org_id: str, status: str | None = None) -> list:
    """品牌切換器用的清單——橫跨一個組織底下所有品牌（票 03-1）。"""
    if status:
        return _rows(conn.execute(
            "SELECT * FROM brand WHERE org_id = %s AND status = %s ORDER BY name",
            (org_id, status)))
    return _rows(conn.execute("SELECT * FROM brand WHERE org_id = %s ORDER BY name", (org_id,)))


def update_brand(conn: Conn, brand_id: str, *, name: str,
                  client_name: str | None, status: str, actor: str) -> dict:
    _require(name, "brand.name 為必填")
    _require(actor, "actor 為必填")
    if status not in ("active", "archived"):
        raise ValueError("brand.status 只能是 active 或 archived（只封存不刪除）")
    before = get_brand(conn, brand_id)
    if before is None:
        raise ValueError(f"找不到品牌：{brand_id}")
    ts = now_utc()
    conn.execute(
        "UPDATE brand SET name = %s, client_name = %s, status = %s, updated_at = %s WHERE id = %s",
        (name, client_name or None, status, ts, brand_id),
    )
    after = get_brand(conn, brand_id)
    org_id = _org_id_for_brand(conn, brand_id)
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="brand", entity_id=brand_id,
                action="update", actor=actor, before=before, after=after)
    conn.commit()
    return after


# 平台中立轉換目標（票 A）：不得存 Meta 事件名，Meta 專屬欄位名只能關在
# app/ads/meta_api.py（決策 0016 硬性原則 1）。Meta 標準事件對照表由 README 記錄（票 B）。
CONVERSION_GOALS = ("purchase", "lead", "booking", "awareness")


def set_brand_switches(conn: Conn, brand_id: str, *,
                        market_region: str | None, conversion_goal: str | None,
                        actor: str) -> dict:
    """寫入 brand.market_region／brand.conversion_goal（票 A，方法論開關讀這兩欄）。"""
    _require(actor, "actor 為必填")
    if conversion_goal is not None and conversion_goal not in CONVERSION_GOALS:
        raise ValueError(f"conversion_goal 只能是 {'/'.join(CONVERSION_GOALS)} 其中之一")
    before = get_brand(conn, brand_id)
    if before is None:
        raise ValueError(f"找不到品牌：{brand_id}")
    ts = now_utc()
    conn.execute(
        "UPDATE brand SET market_region = %s, conversion_goal = %s, updated_at = %s WHERE id = %s",
        (market_region, conversion_goal, ts, brand_id),
    )
    after = get_brand(conn, brand_id)
    org_id = _org_id_for_brand(conn, brand_id)
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="brand", entity_id=brand_id,
                action="update", actor=actor, before=before, after=after)
    conn.commit()
    return after


def set_advertising_history(conn: Conn, brand_id: str, value: str, *, actor: str) -> dict:
    """F33-I01: facade for `app.brand_intelligence.advertising_history.set_advertising_history`
    (the one writer of `brand.advertising_history`) so other modules reach it through this
    declared entry. Imported lazily: that module imports `get_brand` from here."""
    from app.brand_intelligence import advertising_history

    return advertising_history.set_advertising_history(conn, brand_id, value, actor=actor)


def set_regulatory_regime(conn: Conn, brand_id: str, value: str | None, *, actor: str) -> dict:
    """F34-I01 (Contract R): facade for `app.brand_intelligence.regulatory_regime.set_regulatory_regime`
    (the one writer of `brand.regulatory_regime`; `None` clears). Imported lazily for the same
    reason as `set_advertising_history`."""
    from app.brand_intelligence import regulatory_regime

    return regulatory_regime.set_regulatory_regime(conn, brand_id, value, actor=actor)


# 方法論開關名（中文，供 app/methodology/README.md 對照表的（需要：X）條件比對，
# 見 app/llm/methodology.py）。只有 'website' 屬於網站型——值域見 app/core/vocab.py
# CHANNEL_TYPES，不自己發明值。
_WEBSITE_CHANNEL_TYPE = "website"


def compute_methodology_switches(conn: Conn, brand_id: str) -> dict:
    """算出方法論開關的四個布林值，供 app/llm/methodology.py 過濾 README 對照表的
    條件檔（票 A）。只讀既有資料／brand 的新兩欄，不另外新增狀態欄位。"""
    has_product = conn.execute(
        "SELECT 1 FROM product WHERE brand_id = %s LIMIT 1", (brand_id,)
    ).fetchone() is not None
    brand = get_brand(conn, brand_id)
    has_transaction = bool(brand) and brand["conversion_goal"] == "purchase"
    has_website = conn.execute(
        "SELECT 1 FROM owned_channel WHERE brand_id = %s AND channel_type = %s LIMIT 1",
        (brand_id, _WEBSITE_CHANNEL_TYPE),
    ).fetchone() is not None
    has_regulatory = conn.execute(
        "SELECT 1 FROM brand_fact WHERE brand_id = %s AND status = 'confirmed' "
        "AND fact_type = 'regulatory' LIMIT 1", (brand_id,)
    ).fetchone() is not None
    return {
        "有商品": has_product,
        "站內交易": has_transaction,
        "有自有網站": has_website,
        "健康類法規": has_regulatory,
    }


# 刪品牌時要清掉的本模組表，順序＝先子後父（Postgres 預設立即檢查外鍵，順序錯就會被擋）。
BRAND_CHILD_TABLES = (
    ("product_fact", "產品事實"),
    ("product_economics", "產品經濟數據"),
    ("product_economics_version", "產品經濟數字版本"),
    ("brand_performance_baseline", "成效基準"),
    ("rule", "規則"),
    ("claim", "宣稱"),
    ("official_asset", "官方素材"),
    ("owned_channel", "自有渠道"),
    ("customer_voice", "顧客原話"),
    ("brand_fact", "品牌事實"),
    ("source_reference", "來源出處"),
    ("brand_report", "品牌報告"),
    # learning_ledger 平時是 append-only、本層不開 DELETE 入口（鐵則 3，下架只改
    # expired）。刪整個品牌是那條規則的既有例外：品牌都不存在了，掛在它底下的學習
    # 留著只會變成指向不存在品牌的孤兒列。
    ("learning_ledger", "品牌學習紀錄"),
    ("product", "產品"),
)


def count_brand_data(conn: Conn, brand_id: str) -> list:
    """回傳 [(中文名稱, 筆數)]，給刪除確認頁列出「按下去會消失什麼」。"""
    return [
        (label, conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE brand_id = %s", (brand_id,)).fetchone()["n"])
        for table, label in BRAND_CHILD_TABLES
    ]


def count_pending_product_layer(conn: Conn, brand_id: str) -> int:
    """品牌底下所有產品的「待確認」筆數合計：產品事實 + 產品經濟數字（唯讀統計，
    issue #8 功能選單頁提醒卡＋品牌智庫首頁「產品」卡用）。"""
    fact_n = conn.execute(
        "SELECT COUNT(*) AS n FROM product_fact WHERE brand_id = %s AND status = 'pending'", (brand_id,),
    ).fetchone()["n"]
    econ_n = conn.execute(
        "SELECT COUNT(*) AS n FROM product_economics WHERE brand_id = %s AND status = 'pending'", (brand_id,),
    ).fetchone()["n"]
    return fact_n + econ_n


def delete_brand_data(conn: Conn, brand_id: str) -> dict:
    """清掉本模組掛在該品牌下的子表資料（只清 BRAND_CHILD_TABLES 這 14 張子表，
    不碰 brand 那一列、不寫稽核），登記進 app.core.cleanup 給 delete_brand() 呼叫用。
    只下 DELETE、不 commit（Q4 單一交易、全有全無，commit 由 delete_brand() 統一做）。
    """
    counts = dict(count_brand_data(conn, brand_id))
    for table, _label in BRAND_CHILD_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE brand_id = %s", (brand_id,))
    return counts


def delete_brand(conn: Conn, brand_id: str, *, actor: str) -> dict:
    """硬刪除一個已封存品牌與所有登記模組掛在它底下的資料，不可逆（決策 0015）。

    只收已封存的品牌：使用中的品牌得先封存，隔一道手續才刪得掉。
    透過 app.core.cleanup.delete_all() 清掉所有登記模組的資料（本模組「品牌智庫」
    自己也是登記模組之一，會被 delete_all 一併叫到，這裡不重複清），
    再刪 brand 本身那一列、寫稽核，整段只有這裡最後這一次 commit（Q4 全有全無）。

    票 02-1 起連線改成一條連線一個 request／一個背景工作（見 app/core/db.py
    connection()），不再是全 app 共用同一條連線：不 commit 不等於自動回捲，中途出錯
    若不明確 conn.rollback()，懸著的 DELETE 會留到這條連線被歸還連線池、下次借出時
    才被沖掉，而且沒有 audit_log 紀錄。所以這裡明確包 try/except，出錯就 rollback
    再往外拋。
    """
    _require(actor, "actor 為必填")
    before = get_brand(conn, brand_id)
    if before is None:
        raise ValueError(f"找不到品牌：{brand_id}")
    if before["status"] != "archived":
        raise ValueError("只有已封存的品牌可以刪除，請先把品牌封存。")

    # 票 02-1／02-3a：連線模型改成一條連線一個 request／一個背景工作（app/core/db.py
    # connection()），不再是全 app 共用同一條連線，「別人已經寫了東西但還沒 commit」
    # 這個空檔不會再發生於同一條連線上，原本的 in_transaction 搶佔檢查與顯式 BEGIN
    # 因此拿掉。外鍵順序也不必再靠 PRAGMA defer_foreign_keys 延後檢查：02-2 的集裝箱
    # 憲章把跨模組外鍵維持在 0（見 .scratch/saas/tickets/02-2-type-decisions.md 第 6
    # 點），各登記模組只剩模組內的外鍵，而各模組的 CHILD_TABLES／CASCADE_TABLES 早已
    # 手動排成子表先於父表的拓樸順序，順序本身就是正確的。
    org_id = _org_id_for_brand(conn, brand_id)
    try:
        counts = cleanup.delete_all(conn, brand_id)
        conn.execute("DELETE FROM brand WHERE id = %s", (brand_id,))
        write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="brand", entity_id=brand_id,
                    action="delete", actor=actor, before={**before, "deleted_counts": counts},
                    after=None, reason="把關人刪除已封存品牌（決策 0015）")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return counts


# ---------------------------------------------------------------------------
# Product
# ---------------------------------------------------------------------------

def create_product(conn: Conn, brand_id: str, *, name: str, actor: str,
                    parent_id: str | None = None) -> dict:
    """get-or-create; the index is the backstop.

    F36-I10 (drill-6 #16, Contract W): an active product whose trimmed, case-insensitive
    name already exists in the same scope (same brand for a parent, same parent for a
    sell-way) is returned unchanged -- no insert, no audit, no update. Archived rows do not
    count, so a new active product may reuse an archived name. The two partial unique
    indexes in `20260928000001_brand_intelligence_product_active_name_unique.sql` catch
    anything that slips past this lookup (rename / restore go through `update_product`).
    """
    _require(name, "product.name 為必填")
    _require(actor, "actor 為必填")
    name = name.strip()
    if get_brand(conn, brand_id) is None:
        raise ValueError(f"找不到品牌：{brand_id}")
    if parent_id is not None:
        parent = get_product(conn, brand_id, parent_id)
        if parent is None:
            raise ValueError(f"找不到母產品：{parent_id}")
        if parent["parent_id"] is not None:
            raise ValueError("賣法只能掛在母產品底下，不能再往下一層")
    existing = _row(conn.execute(
        "SELECT * FROM product WHERE brand_id = %s AND parent_id IS NOT DISTINCT FROM %s"
        " AND status = 'active' AND lower(btrim(name)) = lower(%s)",
        (brand_id, parent_id, name),
    ).fetchone())
    if existing is not None:
        return existing
    product_id = new_id("prd")
    ts = now_utc()
    row = {
        "id": product_id, "brand_id": brand_id, "name": name, "status": "active",
        "knowledge_version": 1, "created_at": ts, "updated_at": ts, "parent_id": parent_id,
    }
    org_id = _org_id_for_brand(conn, brand_id)
    conn.execute(
        "INSERT INTO product (id, org_id, brand_id, name, status, knowledge_version, created_at, "
        "updated_at, parent_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (row["id"], org_id, row["brand_id"], row["name"], row["status"], row["knowledge_version"],
         row["created_at"], row["updated_at"], row["parent_id"]),
    )
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="product", entity_id=product_id,
                action="create", actor=actor, before=None, after=row)
    conn.commit()
    return row


def get_product(conn: Conn, brand_id: str, product_id: str) -> dict | None:
    """跨品牌存取一律回 None（呼叫端轉成「找不到」），不得洩漏資料屬於其他品牌。"""
    return _row(conn.execute(
        "SELECT * FROM product WHERE id = %s AND brand_id = %s", (product_id, brand_id)
    ).fetchone())


def list_products(conn: Conn, brand_id: str) -> list:
    return _rows(conn.execute("SELECT * FROM product WHERE brand_id = %s ORDER BY name", (brand_id,)))


def knowledge_product_id(conn: Conn, brand_id: str, product_id: str) -> str:
    """產品知識（事實、宣稱、商品照、座標）掛母產品，金額掛賣法——這支是唯一的解析器
    （ARCHITECTURE.md §8 第 1 條），回 `COALESCE(parent_id, id)`；找不到這顆產品就原樣回傳
    `product_id`（呼叫端自己決定怎麼處理「找不到」，這裡不代為判斷）。"""
    product = get_product(conn, brand_id, product_id)
    if product is None:
        return product_id
    return product["parent_id"] or product_id


def update_product(conn: Conn, brand_id: str, product_id: str, *,
                    name: str, status: str, actor: str) -> dict:
    _require(name, "product.name 為必填")
    _require(actor, "actor 為必填")
    if status not in ("active", "archived"):
        raise ValueError("product.status 只能是 active 或 archived（只封存不刪除）")
    before = get_product(conn, brand_id, product_id)
    if before is None:
        raise ValueError(f"找不到產品：{product_id}")
    ts = now_utc()
    try:
        conn.execute(
            "UPDATE product SET name = %s, status = %s, updated_at = %s WHERE id = %s AND brand_id = %s",
            (name, status, ts, product_id, brand_id),
        )
    except psycopg.errors.UniqueViolation:
        # F36-I10: rename or restore collided with an active same-name product in the same
        # scope (partial unique indexes, see create_product). Roll back so the connection is
        # usable again, then surface it as the same ValueError family the routes map to 4xx.
        conn.rollback()
        raise ValueError("已有同名產品") from None
    after = get_product(conn, brand_id, product_id)
    org_id = _org_id_for_brand(conn, brand_id)
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="product", entity_id=product_id,
                action="update", actor=actor, before=before, after=after)
    conn.commit()
    return after


# 刪產品時要清掉的本模組表，只挑 product_id 對得上這顆產品的列（同一張表裡 product_id
# 為 NULL 或屬於別的產品的列不會被這個條件選到，不會誤刪品牌層或別的產品的資料）。
PRODUCT_CHILD_TABLES = (
    ("product_fact", "產品事實"),
    ("product_economics", "產品經濟數據"),
    ("product_economics_version", "產品經濟數字版本"),
    ("brand_performance_baseline", "成效基準"),
    ("rule", "規則"),
    ("claim", "宣稱"),
    ("official_asset", "官方素材"),
    ("learning_ledger", "品牌學習紀錄"),
)


def count_product_data(conn: Conn, brand_id: str, product_id: str) -> list:
    """回傳 [(中文名稱, 筆數)]，給刪除確認頁列出「按下去會消失什麼」。"""
    return [
        (label, conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE brand_id = %s AND product_id = %s",
            (brand_id, product_id)).fetchone()["n"])
        for table, label in PRODUCT_CHILD_TABLES
    ]


def delete_product_data(conn: Conn, brand_id: str, product_id: str) -> dict:
    """清掉本模組掛在該產品下的子表資料（只清 PRODUCT_CHILD_TABLES 這 8 張子表，
    不碰 product 那一列、不寫稽核），登記進 app.core.cleanup 給 delete_product() 呼叫用。
    只下 DELETE、不 commit（Q4 單一交易、全有全無，commit 由 delete_product() 統一做）。
    """
    counts = dict(count_product_data(conn, brand_id, product_id))
    for table, _label in PRODUCT_CHILD_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE brand_id = %s AND product_id = %s",
                      (brand_id, product_id))
    return counts


def delete_product(conn: Conn, brand_id: str, product_id: str, *, actor: str) -> dict:
    """硬刪除一個已封存產品與所有登記模組掛在它底下的資料，不可逆（決策 0020，比照品牌 0015）。

    只收已封存的產品：使用中的產品得先封存，隔一道手續才刪得掉。

    交易處理比照 delete_brand()：透過 app.core.cleanup.delete_all_product()
    清掉所有登記模組掛在這顆產品底下的資料（本模組「品牌智庫」自己也是登記模組之一，
    會被 delete_all_product 一併叫到，這裡不重複清），再刪 product 本身那一列、寫稽核，
    整段只有這裡最後這一次 commit（Q4 全有全無）。

    票 02-1 起連線改成一條連線一個 request／一個背景工作（見 app/core/db.py
    connection()），不再是全 app 共用同一條連線：不 commit 不等於自動回捲，中途出錯
    若不明確 conn.rollback()，懸著的 DELETE 會留到這條連線被歸還連線池、下次借出時
    才被沖掉，而且沒有 audit_log 紀錄。所以這裡明確包 try/except，出錯就 rollback
    再往外拋。
    """
    _require(actor, "actor 為必填")
    before = get_product(conn, brand_id, product_id)
    if before is None:
        raise ValueError(f"找不到產品：{product_id}")
    if before["status"] != "archived":
        raise ValueError("只有已封存的產品可以刪除，請先把產品封存。")

    # 票 02-1／02-3a：理由同 delete_brand()——連線改成一條連線一個 request／一個背景
    # 工作，不再全 app 共用一條，原本的 in_transaction 搶佔檢查、顯式 BEGIN、PRAGMA
    # defer_foreign_keys 都拿掉（跨模組外鍵已在 02-2 維持在 0，各模組表本就照子表先於
    # 父表排序）。
    org_id = _org_id_for_brand(conn, brand_id)
    try:
        counts = cleanup.delete_all_product(conn, brand_id, product_id)
        conn.execute("DELETE FROM product WHERE id = %s AND brand_id = %s", (product_id, brand_id))
        write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="product", entity_id=product_id,
                    action="delete", actor=actor, before={**before, "deleted_counts": counts},
                    after=None, reason="把關人刪除已封存產品（決策 0020）")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return counts


# ---------------------------------------------------------------------------
# Brand Fact
# ---------------------------------------------------------------------------

def create_brand_fact(conn: Conn, brand_id: str, *, actor: str, fact_type: str,
                       label: str, value: str, status: str,
                       source_reference_id: str | None = None,
                       confidence: str | None = None,
                       confirmed_by: str | None = None) -> dict:
    _require(fact_type, "brand_fact.fact_type 為必填")
    _require(label, "brand_fact.label 為必填")
    _require(value, "brand_fact.value 為必填")
    _require(actor, "actor 為必填")
    if status not in ("confirmed", "pending"):
        raise ValueError("brand_fact.status 只能是 confirmed 或 pending")
    if status == "confirmed":
        _require(confirmed_by, "狀態為已確認時，confirmed_by 為必填")
    fact_id = new_id("bft")
    ts = now_utc()
    row = {
        "id": fact_id, "brand_id": brand_id, "fact_type": fact_type, "label": label, "value": value,
        "status": status, "source_reference_id": source_reference_id, "confidence": confidence,
        "confirmed_by": confirmed_by if status == "confirmed" else None,
        "confirmed_at": ts if status == "confirmed" else None,
        "created_at": ts, "updated_at": ts,
    }
    org_id = _org_id_for_brand(conn, brand_id)
    conn.execute(
        "INSERT INTO brand_fact (id, org_id, brand_id, fact_type, label, value, status, source_reference_id, "
        "confidence, confirmed_by, confirmed_at, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (row["id"], org_id, row["brand_id"], row["fact_type"], row["label"], row["value"], row["status"],
         row["source_reference_id"], row["confidence"], row["confirmed_by"], row["confirmed_at"],
         row["created_at"], row["updated_at"]),
    )
    _bump_brand_version(conn, brand_id)
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="brand_fact", entity_id=fact_id,
                action="create", actor=actor, before=None, after=row)
    conn.commit()
    return row


def get_brand_fact(conn: Conn, brand_id: str, fact_id: str) -> dict | None:
    return _row(conn.execute(
        "SELECT * FROM brand_fact WHERE id = %s AND brand_id = %s", (fact_id, brand_id)
    ).fetchone())


def list_brand_facts(conn: Conn, brand_id: str, status: str | None = None) -> list:
    if status:
        return _rows(conn.execute(
            "SELECT * FROM brand_fact WHERE brand_id = %s AND status = %s ORDER BY created_at",
            (brand_id, status),
        ))
    return _rows(conn.execute(
        "SELECT * FROM brand_fact WHERE brand_id = %s ORDER BY created_at", (brand_id,)
    ))


def update_brand_fact(conn: Conn, brand_id: str, fact_id: str, *, actor: str,
                       fact_type: str, label: str, value: str,
                       source_reference_id: str | None = None,
                       confidence: str | None = None) -> dict:
    """編輯事實內容。人工編輯直接生效、不退回待確認（決策 0013 用戶優先：
    人親手改的內容本身就是最高權威的確認；編輯者成為最新確認人）。"""
    _require(fact_type, "brand_fact.fact_type 為必填")
    _require(label, "brand_fact.label 為必填")
    _require(value, "brand_fact.value 為必填")
    _require(actor, "actor 為必填")
    before = get_brand_fact(conn, brand_id, fact_id)
    if before is None:
        raise ValueError(f"找不到品牌事實：{fact_id}")
    was_confirmed = before["status"] == "confirmed"
    ts = now_utc()
    confirmed_by = actor if was_confirmed else before["confirmed_by"]
    confirmed_at = ts if was_confirmed else before["confirmed_at"]
    conn.execute(
        "UPDATE brand_fact SET fact_type = %s, label = %s, value = %s, "
        "source_reference_id = %s, confidence = %s, confirmed_by = %s, confirmed_at = %s, updated_at = %s "
        "WHERE id = %s AND brand_id = %s",
        (fact_type, label, value, source_reference_id, confidence,
         confirmed_by, confirmed_at, ts, fact_id, brand_id),
    )
    after = get_brand_fact(conn, brand_id, fact_id)
    _bump_brand_version(conn, brand_id)
    reason = "人工編輯直接生效（決策 0013）" if was_confirmed else None
    org_id = _org_id_for_brand(conn, brand_id)
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="brand_fact", entity_id=fact_id,
                action="update", actor=actor, before=before, after=after, reason=reason)
    conn.commit()
    return after


def _delete_entity(conn: Conn, brand_id: str, table: str, entity_id: str, *,
                    actor: str, kind_label: str) -> None:
    """硬刪除一筆品牌資料，before 全文記進 audit_log 可追溯（決策 0013：把關人可直接清資料）。"""
    _require(actor, "actor 為必填")
    before = _row(conn.execute(
        f"SELECT * FROM {table} WHERE id = %s AND brand_id = %s", (entity_id, brand_id)).fetchone())
    if before is None:
        raise ValueError(f"找不到{kind_label}：{entity_id}")
    conn.execute(f"DELETE FROM {table} WHERE id = %s AND brand_id = %s", (entity_id, brand_id))
    _bump_brand_version(conn, brand_id)
    org_id = _org_id_for_brand(conn, brand_id)
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type=table, entity_id=entity_id,
                action="delete", actor=actor, before=before, after=None,
                reason="把關人刪除（決策 0013）")
    conn.commit()


def delete_brand_fact(conn, brand_id: str, fact_id: str, *, actor: str) -> None:
    _delete_entity(conn, brand_id, "brand_fact", fact_id, actor=actor, kind_label="品牌事實")


def delete_product_fact(conn, brand_id: str, fact_id: str, *, actor: str) -> None:
    _delete_entity(conn, brand_id, "product_fact", fact_id, actor=actor, kind_label="產品事實")


def delete_rule(conn, brand_id: str, rule_id: str, *, actor: str) -> None:
    _delete_entity(conn, brand_id, "rule", rule_id, actor=actor, kind_label="規則")


def delete_claim(conn, brand_id: str, claim_id: str, *, actor: str) -> None:
    _delete_entity(conn, brand_id, "claim", claim_id, actor=actor, kind_label="宣稱")


def confirm_brand_fact(conn: Conn, brand_id: str, fact_id: str, *,
                        confirmed_by: str, actor: str) -> dict:
    _require(confirmed_by, "confirmed_by 為必填")
    _require(actor, "actor 為必填")
    before = get_brand_fact(conn, brand_id, fact_id)
    if before is None:
        raise ValueError(f"找不到品牌事實：{fact_id}")
    ts = now_utc()
    conn.execute(
        "UPDATE brand_fact SET status = 'confirmed', confirmed_by = %s, confirmed_at = %s, updated_at = %s "
        "WHERE id = %s AND brand_id = %s",
        (confirmed_by, ts, ts, fact_id, brand_id),
    )
    after = get_brand_fact(conn, brand_id, fact_id)
    _bump_brand_version(conn, brand_id)
    org_id = _org_id_for_brand(conn, brand_id)
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="brand_fact", entity_id=fact_id,
                action="confirm", actor=actor, before=before, after=after)
    conn.commit()
    return after


# ---------------------------------------------------------------------------
# Product Fact
# ---------------------------------------------------------------------------

def create_product_fact(conn: Conn, brand_id: str, product_id: str, *, actor: str,
                         fact_type: str, label: str, value: str, status: str,
                         source_reference_id: str | None = None,
                         confidence: str | None = None,
                         confirmed_by: str | None = None) -> dict:
    _require(fact_type, "product_fact.fact_type 為必填")
    _require(label, "product_fact.label 為必填")
    _require(value, "product_fact.value 為必填")
    _require(actor, "actor 為必填")
    if status not in ("confirmed", "pending"):
        raise ValueError("product_fact.status 只能是 confirmed 或 pending")
    if status == "confirmed":
        _require(confirmed_by, "狀態為已確認時，confirmed_by 為必填")
    fact_id = new_id("pft")
    ts = now_utc()
    row = {
        "id": fact_id, "product_id": product_id, "brand_id": brand_id, "fact_type": fact_type,
        "label": label, "value": value, "status": status, "source_reference_id": source_reference_id,
        "confidence": confidence,
        "confirmed_by": confirmed_by if status == "confirmed" else None,
        "confirmed_at": ts if status == "confirmed" else None,
        "created_at": ts, "updated_at": ts,
    }
    org_id = _org_id_for_brand(conn, brand_id)
    conn.execute(
        "INSERT INTO product_fact (id, org_id, product_id, brand_id, fact_type, label, value, status, "
        "source_reference_id, confidence, confirmed_by, confirmed_at, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (row["id"], org_id, row["product_id"], row["brand_id"], row["fact_type"], row["label"], row["value"],
         row["status"], row["source_reference_id"], row["confidence"], row["confirmed_by"],
         row["confirmed_at"], row["created_at"], row["updated_at"]),
    )
    _bump_product_version(conn, brand_id, product_id)
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="product_fact", entity_id=fact_id,
                action="create", actor=actor, before=None, after=row)
    conn.commit()
    return row


def get_product_fact(conn: Conn, brand_id: str, product_id: str,
                      fact_id: str) -> dict | None:
    return _row(conn.execute(
        "SELECT * FROM product_fact WHERE id = %s AND brand_id = %s AND product_id = %s",
        (fact_id, brand_id, product_id),
    ).fetchone())


def list_product_facts(conn: Conn, brand_id: str, product_id: str,
                        status: str | None = None) -> list:
    if status:
        return _rows(conn.execute(
            "SELECT * FROM product_fact WHERE brand_id = %s AND product_id = %s AND status = %s "
            "ORDER BY created_at",
            (brand_id, product_id, status),
        ))
    return _rows(conn.execute(
        "SELECT * FROM product_fact WHERE brand_id = %s AND product_id = %s ORDER BY created_at",
        (brand_id, product_id),
    ))


def update_product_fact(conn: Conn, brand_id: str, product_id: str, fact_id: str, *,
                         actor: str, fact_type: str, label: str, value: str,
                         source_reference_id: str | None = None,
                         confidence: str | None = None) -> dict:
    """編輯事實內容。人工編輯直接生效、不退回待確認（決策 0013 用戶優先）。"""
    _require(fact_type, "product_fact.fact_type 為必填")
    _require(label, "product_fact.label 為必填")
    _require(value, "product_fact.value 為必填")
    _require(actor, "actor 為必填")
    before = get_product_fact(conn, brand_id, product_id, fact_id)
    if before is None:
        raise ValueError(f"找不到產品事實：{fact_id}")
    was_confirmed = before["status"] == "confirmed"
    ts = now_utc()
    confirmed_by = actor if was_confirmed else before["confirmed_by"]
    confirmed_at = ts if was_confirmed else before["confirmed_at"]
    conn.execute(
        "UPDATE product_fact SET fact_type = %s, label = %s, value = %s, "
        "source_reference_id = %s, confidence = %s, confirmed_by = %s, confirmed_at = %s, updated_at = %s "
        "WHERE id = %s AND brand_id = %s AND product_id = %s",
        (fact_type, label, value, source_reference_id, confidence,
         confirmed_by, confirmed_at, ts, fact_id, brand_id, product_id),
    )
    after = get_product_fact(conn, brand_id, product_id, fact_id)
    _bump_product_version(conn, brand_id, product_id)
    reason = "人工編輯直接生效（決策 0013）" if was_confirmed else None
    org_id = _org_id_for_brand(conn, brand_id)
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="product_fact", entity_id=fact_id,
                action="update", actor=actor, before=before, after=after, reason=reason)
    conn.commit()
    return after


def confirm_product_fact(conn: Conn, brand_id: str, product_id: str, fact_id: str, *,
                          confirmed_by: str, actor: str) -> dict:
    _require(confirmed_by, "confirmed_by 為必填")
    _require(actor, "actor 為必填")
    before = get_product_fact(conn, brand_id, product_id, fact_id)
    if before is None:
        raise ValueError(f"找不到產品事實：{fact_id}")
    ts = now_utc()
    conn.execute(
        "UPDATE product_fact SET status = 'confirmed', confirmed_by = %s, confirmed_at = %s, updated_at = %s "
        "WHERE id = %s AND brand_id = %s AND product_id = %s",
        (confirmed_by, ts, ts, fact_id, brand_id, product_id),
    )
    after = get_product_fact(conn, brand_id, product_id, fact_id)
    _bump_product_version(conn, brand_id, product_id)
    org_id = _org_id_for_brand(conn, brand_id)
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="product_fact", entity_id=fact_id,
                action="confirm", actor=actor, before=before, after=after)
    conn.commit()
    return after


# ---------------------------------------------------------------------------
# Product Economics（依 product_id 只保留一筆現行資料；新值進來即更新既有列）
# ---------------------------------------------------------------------------

def get_product_economics(conn: Conn, brand_id: str, product_id: str) -> dict | None:
    return _row(conn.execute(
        "SELECT * FROM product_economics WHERE brand_id = %s AND product_id = %s "
        "ORDER BY updated_at DESC LIMIT 1",
        (brand_id, product_id),
    ).fetchone())


_ASSUMPTION_FIELDS = frozenset({"cost", "shipping", "close_rate"})


def save_product_economics(conn: Conn, brand_id: str, product_id: str, *, actor: str,
                            selling_price: float, currency: str, confirmed_by: str,
                            fixed_cost: float | None = None,
                            unit_variable_cost: float | None = None,
                            shipping_cost: float | None = None,
                            effective_from: str | None = None,
                            effective_to: str | None = None,
                            close_rate: float | None = None,
                            assumptions: list[str] | None = None) -> dict:
    _require(currency, "product_economics.currency 為必填")
    _require(confirmed_by, "confirmed_by 為必填")
    _require(actor, "actor 為必填")
    if selling_price is None:
        raise ValueError("product_economics.selling_price 為必填")
    if close_rate is not None and not (0 < close_rate <= 1):
        raise ValueError("product_economics.close_rate 必須介於 0（不含）到 1（含）之間")
    if assumptions is not None and not set(assumptions) <= _ASSUMPTION_FIELDS:
        raise ValueError(f"product_economics.assumptions 只能是 {sorted(_ASSUMPTION_FIELDS)}")
    before = get_product_economics(conn, brand_id, product_id)
    ts = now_utc()
    org_id = _org_id_for_brand(conn, brand_id)
    row = {
        "id": before["id"] if before else new_id("pec"),
        "product_id": product_id, "brand_id": brand_id, "selling_price": selling_price,
        "fixed_cost": fixed_cost, "unit_variable_cost": unit_variable_cost,
        "shipping_cost": shipping_cost, "currency": currency,
        "effective_from": effective_from, "effective_to": effective_to, "status": "confirmed",
        "source_reference_id": before["source_reference_id"] if before else None,
        "confirmed_by": confirmed_by, "confirmed_at": ts,
        "created_at": before["created_at"] if before else ts, "updated_at": ts,
        "close_rate": close_rate, "assumptions_json": list(assumptions) if assumptions else None,
    }
    # ADR 0053 §5：成本一改就是新的一版，只能從今天生效、絕不回溯——關掉這個產品目前開著
    # 的那一版（若有），開一筆新的、從組織自己的今天生效（today_for_org，不是 date.today()：
    # 機器的今天跟組織的今天在台北時區每天差 8 小時）。同一天存兩次會關出一筆
    # [today, today) 的零長度版本，這是對的、讀起來等於沒發生，不加分支去閃避它（票 T2c
    # 矛盾檢查段）——close 跟 insert 兩句話跟下面 product_economics 的寫入共用同一個
    # request 交易，靠函式最後同一個 conn.commit() 一起落地。
    today = coresettings.today_for_org(conn, org_id=org_id)
    open_version = conn.execute(
        "SELECT id, version FROM product_economics_version"
        " WHERE product_id = %s AND effective_to IS NULL",
        (product_id,),
    ).fetchone()
    if open_version is not None:
        conn.execute(
            "UPDATE product_economics_version SET effective_to = %s WHERE id = %s",
            (today, open_version["id"]),
        )
    conn.execute(
        "INSERT INTO product_economics_version (id, org_id, brand_id, product_id, version,"
        " selling_price, fixed_cost, unit_variable_cost, shipping_cost, currency,"
        " effective_from, effective_to, created_by, created_at, close_rate, assumptions_json)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, %s, %s, %s, %s)",
        (new_id("pev"), org_id, brand_id, product_id,
         (open_version["version"] if open_version else 0) + 1,
         selling_price, fixed_cost, unit_variable_cost, shipping_cost, currency,
         today, actor, ts, row["close_rate"], jsonb(row["assumptions_json"])),
    )
    if before:
        conn.execute(
            "UPDATE product_economics SET selling_price = %s, fixed_cost = %s, unit_variable_cost = %s, "
            "shipping_cost = %s, currency = %s, effective_from = %s, effective_to = %s, "
            "status = %s, confirmed_by = %s, confirmed_at = %s, updated_at = %s, close_rate = %s, "
            "assumptions_json = %s WHERE id = %s",
            (row["selling_price"], row["fixed_cost"], row["unit_variable_cost"], row["shipping_cost"],
             row["currency"], row["effective_from"], row["effective_to"],
             row["status"], row["confirmed_by"], row["confirmed_at"], row["updated_at"],
             row["close_rate"], jsonb(row["assumptions_json"]), row["id"]),
        )
        action = "update"
    else:
        conn.execute(
            "INSERT INTO product_economics (id, org_id, product_id, brand_id, selling_price, fixed_cost, "
            "unit_variable_cost, shipping_cost, currency, effective_from, effective_to, "
            "status, source_reference_id, confirmed_by, confirmed_at, created_at, updated_at, "
            "close_rate, assumptions_json) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (row["id"], org_id, row["product_id"], row["brand_id"], row["selling_price"], row["fixed_cost"],
             row["unit_variable_cost"], row["shipping_cost"], row["currency"],
             row["effective_from"], row["effective_to"], row["status"], row["source_reference_id"],
             row["confirmed_by"], row["confirmed_at"], row["created_at"], row["updated_at"],
             row["close_rate"], jsonb(row["assumptions_json"])),
        )
        action = "create"
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="product_economics", entity_id=row["id"],
                action=action, actor=actor, before=before, after=row)
    conn.commit()
    return row


def economics_at(conn: Conn, brand_id: str, product_id: str, on_date: date) -> dict | None:
    """哪一版 product_economics_version 在 `on_date` 生效（ADR 0053 §5）：`[effective_from,
    effective_to)` 半開區間包含 `on_date` 的那一筆。T5 的毛利計算用它讀「當時生效」的成本，
    不吃 product_economics 的現在值——本票沒有呼叫端，先落地給下一票用。"""
    return _row(conn.execute(
        "SELECT * FROM product_economics_version WHERE brand_id = %s AND product_id = %s"
        " AND effective_from <= %s AND (effective_to IS NULL OR effective_to > %s)",
        (brand_id, product_id, on_date, on_date),
    ).fetchone())


def get_latest_product_source_url(conn: Conn, brand_id: str,
                                   product_id: str) -> str | None:
    """這個產品最近一次帶網址的來源引用文字（產品事實或經濟數字都算），給「AI 再次調研」
    表單預填網址用；沒有就回 None（架構限制：使用者填的網址存在 source_reference.title，
    見 app/main.py 的 _create_source_ref）。"""
    row = conn.execute(
        "SELECT sr.title AS url, t.created_at FROM ("
        "  SELECT source_reference_id, created_at FROM product_fact WHERE brand_id = %s AND product_id = %s"
        "  UNION ALL"
        "  SELECT source_reference_id, created_at FROM product_economics WHERE brand_id = %s AND product_id = %s"
        ") t JOIN source_reference sr ON sr.id = t.source_reference_id"
        " WHERE sr.title LIKE 'http%%' ORDER BY t.created_at DESC LIMIT 1",
        (brand_id, product_id, brand_id, product_id),
    ).fetchone()
    return row["url"] if row else None


def create_pending_product_economics(conn: Conn, brand_id: str, product_id: str, *, actor: str, selling_price: float, currency: str,
                                      source_reference_id: str | None) -> dict:
    """AI 快掃抓到售價、這個產品目前完全沒有經濟數字列時才呼叫——建一筆 pending，
    固定成本／單位變動成本／運費留白，等使用者到「更新數字」補齊或直接一鍵確認。"""
    _require(currency, "product_economics.currency 為必填")
    _require(actor, "actor 為必填")
    ts = now_utc()
    row = {
        "id": new_id("pec"), "product_id": product_id, "brand_id": brand_id,
        "selling_price": selling_price, "fixed_cost": None, "unit_variable_cost": None,
        "shipping_cost": None, "currency": currency,
        "effective_from": None, "effective_to": None, "status": "pending",
        "source_reference_id": source_reference_id, "confirmed_by": None, "confirmed_at": None,
        "created_at": ts, "updated_at": ts,
    }
    org_id = _org_id_for_brand(conn, brand_id)
    conn.execute(
        "INSERT INTO product_economics (id, org_id, product_id, brand_id, selling_price, fixed_cost, "
        "unit_variable_cost, shipping_cost, currency, effective_from, effective_to, "
        "status, source_reference_id, confirmed_by, confirmed_at, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (row["id"], org_id, row["product_id"], row["brand_id"], row["selling_price"], row["fixed_cost"],
         row["unit_variable_cost"], row["shipping_cost"], row["currency"],
         row["effective_from"], row["effective_to"], row["status"], row["source_reference_id"],
         row["confirmed_by"], row["confirmed_at"], row["created_at"], row["updated_at"]),
    )
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="product_economics", entity_id=row["id"],
                action="create", actor=actor, before=None, after=row)
    conn.commit()
    return row


def confirm_product_economics(conn: Conn, brand_id: str, product_id: str, *,
                                confirmed_by: str, actor: str) -> dict:
    """待確認經濟數字的一鍵確認（比照 confirm_product_fact 的最小版）：只翻狀態，
    不動欄位內容——欄位若還沒補齊，使用者仍可之後用「更新數字」補上。"""
    _require(confirmed_by, "confirmed_by 為必填")
    _require(actor, "actor 為必填")
    before = get_product_economics(conn, brand_id, product_id)
    if before is None:
        raise ValueError(f"找不到產品經濟數字：{product_id}")
    ts = now_utc()
    conn.execute(
        "UPDATE product_economics SET status = 'confirmed', confirmed_by = %s, confirmed_at = %s, "
        "updated_at = %s WHERE id = %s",
        (confirmed_by, ts, ts, before["id"]),
    )
    after = get_product_economics(conn, brand_id, product_id)
    org_id = _org_id_for_brand(conn, brand_id)
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="product_economics", entity_id=before["id"],
                action="confirm", actor=actor, before=before, after=after)
    conn.commit()
    return after


# ---------------------------------------------------------------------------
# Learning Ledger（append-only；寫入端見 F03-I02——結案與「採用」各寫一條，見呼叫端 `ads`）
# ---------------------------------------------------------------------------

_LEARNING_CONFIDENCE = ("observed", "likely", "validated")


def record_learning(conn: Conn, brand_id: str, *, actor: str, learning_text: str,
                     applicability_scope: str, confidence: str, sample_size: str,
                     source_cycle_id: str | None = None, product_id: str | None = None,
                     platform: str | None = None, needs_revalidation: bool = False,
                     learned_at=None, source_track: str = "ads") -> dict:
    _require(actor, "actor 為必填")
    _require(learning_text, "learning_ledger.learning_text 為必填")
    _require(applicability_scope, "learning_ledger.applicability_scope 為必填")
    if confidence not in _LEARNING_CONFIDENCE:
        raise ValueError(f"learning_ledger.confidence 只能是 {_LEARNING_CONFIDENCE} 之一")
    org_id = _org_id_for_brand(conn, brand_id)
    ts = now_utc()
    row = {
        "id": new_id("lrn"), "org_id": org_id, "brand_id": brand_id, "product_id": product_id,
        "platform": platform, "learning_text": learning_text,
        "applicability_scope": applicability_scope, "source_cycle_id": source_cycle_id,
        "sample_size": sample_size, "confidence": confidence,
        "needs_revalidation": needs_revalidation, "learned_at": learned_at or ts,
        "created_by": actor, "created_at": ts, "source_track": source_track,
    }
    conn.execute(
        "INSERT INTO learning_ledger (id, org_id, brand_id, product_id, platform, learning_text,"
        " applicability_scope, source_cycle_id, sample_size, confidence, needs_revalidation,"
        " learned_at, created_by, created_at, source_track)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (row["id"], row["org_id"], row["brand_id"], row["product_id"], row["platform"],
         row["learning_text"], row["applicability_scope"], row["source_cycle_id"],
         row["sample_size"], row["confidence"], row["needs_revalidation"], row["learned_at"],
         row["created_by"], row["created_at"], row["source_track"]),
    )
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="learning_ledger",
                entity_id=row["id"], action="create", actor=actor, before=None, after=row)
    conn.commit()
    return row


def list_learnings(conn: Conn, brand_id: str, *, product_id: str | None = None,
                    include_expired: bool = False, limit: int = 50,
                    source_track: str | None = None) -> list:
    sql = "SELECT * FROM learning_ledger WHERE brand_id = %s"
    params = [brand_id]
    if product_id is not None:
        sql += " AND product_id = %s"
        params.append(product_id)
    if not include_expired:
        sql += " AND expired = false"
    if source_track is not None:
        sql += " AND source_track = %s"
        params.append(source_track)
    sql += " ORDER BY learned_at DESC LIMIT %s"
    params.append(limit)
    return _rows(conn.execute(sql, tuple(params)))


def expire_learning(conn: Conn, brand_id: str, learning_id: str, *, actor: str) -> dict | None:
    """Expires one learning row（結案時降級舊贏家用）。過期一筆已過期的行是 no-op，仍回傳該行。"""
    before = _rows(conn.execute(
        "SELECT * FROM learning_ledger WHERE brand_id = %s AND id = %s", (brand_id, learning_id),
    ))
    if not before:
        return None
    before = before[0]
    org_id = _org_id_for_brand(conn, brand_id)
    conn.execute(
        "UPDATE learning_ledger SET expired = true WHERE brand_id = %s AND id = %s",
        (brand_id, learning_id),
    )
    after = _rows(conn.execute(
        "SELECT * FROM learning_ledger WHERE brand_id = %s AND id = %s", (brand_id, learning_id),
    ))[0]
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="learning_ledger",
                entity_id=learning_id, action="update", actor=actor, before=before, after=after)
    conn.commit()
    return after


# ---------------------------------------------------------------------------
# Rule
# ---------------------------------------------------------------------------

def create_rule(conn: Conn, brand_id: str, *, actor: str, rule_type: str, content: str,
                 severity: str, product_id: str | None = None,
                 source_reference_id: str | None = None) -> dict:
    _require(rule_type, "rule.rule_type 為必填")
    _require(content, "rule.content 為必填")
    _require(actor, "actor 為必填")
    if severity not in ("hard", "soft"):
        raise ValueError("rule.severity 只能是 hard 或 soft")
    rule_id = new_id("rul")
    ts = now_utc()
    row = {
        "id": rule_id, "brand_id": brand_id, "product_id": product_id, "rule_type": rule_type,
        "content": content, "severity": severity, "status": "active",
        "source_reference_id": source_reference_id, "created_at": ts, "updated_at": ts,
        "confirmed_at": ts,  # 建立即視為已確認（rule-lifecycle 02，ADR 0012 第二節）；
        # 重新確認的顯式操作留給 rule-lifecycle 01。
    }
    org_id = _org_id_for_brand(conn, brand_id)
    conn.execute(
        "INSERT INTO rule (id, org_id, brand_id, product_id, rule_type, content, severity, status, "
        "source_reference_id, created_at, updated_at, confirmed_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (row["id"], org_id, row["brand_id"], row["product_id"], row["rule_type"], row["content"],
         row["severity"], row["status"], row["source_reference_id"], row["created_at"],
         row["updated_at"], row["confirmed_at"]),
    )
    if product_id:
        _bump_product_version(conn, brand_id, product_id)
    else:
        _bump_brand_version(conn, brand_id)
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="rule", entity_id=rule_id,
                action="create", actor=actor, before=None, after=row)
    conn.commit()
    return row


def get_rule(conn: Conn, brand_id: str, rule_id: str) -> dict | None:
    return _row(conn.execute(
        "SELECT * FROM rule WHERE id = %s AND brand_id = %s", (rule_id, brand_id)).fetchone())


def update_rule(conn: Conn, brand_id: str, rule_id: str, *, actor: str,
                 rule_type: str, content: str, severity: str, product_id: str | None = None,
                 source_reference_id: str | None = None) -> dict:
    """編輯規則內容，比照 update_brand_fact：人工編輯直接生效（決策 0013）。"""
    _require(rule_type, "rule.rule_type 為必填")
    _require(content, "rule.content 為必填")
    _require(actor, "actor 為必填")
    if severity not in ("hard", "soft"):
        raise ValueError("rule.severity 只能是 hard 或 soft")
    before = get_rule(conn, brand_id, rule_id)
    if before is None:
        raise ValueError(f"找不到規則：{rule_id}")
    ts = now_utc()
    conn.execute(
        "UPDATE rule SET rule_type = %s, content = %s, severity = %s, product_id = %s, "
        "source_reference_id = %s, updated_at = %s WHERE id = %s AND brand_id = %s",
        (rule_type, content, severity, product_id, source_reference_id, ts, rule_id, brand_id),
    )
    after = get_rule(conn, brand_id, rule_id)
    if product_id:
        _bump_product_version(conn, brand_id, product_id)
    else:
        _bump_brand_version(conn, brand_id)
    if before["product_id"] and before["product_id"] != product_id:
        _bump_product_version(conn, brand_id, before["product_id"])
    org_id = _org_id_for_brand(conn, brand_id)
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="rule", entity_id=rule_id,
                action="update", actor=actor, before=before, after=after,
                reason="人工編輯直接生效（決策 0013）")
    conn.commit()
    return after


def deactivate_rule(conn: Conn, brand_id: str, rule_id: str, *, actor: str) -> dict:
    """停用規則（GitHub issue #56，決策 0030）：把 `rule.status` 改為非 active 但保留該列，
    不同於 `delete_rule`（硬刪）與 `update_rule`（不碰 status）——兩者都接不住「下架但留紀錄」。
    停用後 `list_rules_for_brand`／`list_rules_for_product` 的 `WHERE status = 'active'`
    會自動排除這一列，不再進 `context_compiler` 組出的生成 prompt。
    屬新增程式碼、不是改 schema（`rule.status` 為無 CHECK 的 TEXT）。"""
    _require(actor, "actor 為必填")
    before = get_rule(conn, brand_id, rule_id)
    if before is None:
        raise ValueError(f"找不到規則：{rule_id}")
    ts = now_utc()
    conn.execute(
        "UPDATE rule SET status = 'inactive', updated_at = %s WHERE id = %s AND brand_id = %s",
        (ts, rule_id, brand_id),
    )
    after = get_rule(conn, brand_id, rule_id)
    if after["product_id"]:
        _bump_product_version(conn, brand_id, after["product_id"])
    else:
        _bump_brand_version(conn, brand_id)
    org_id = _org_id_for_brand(conn, brand_id)
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="rule", entity_id=rule_id,
                action="deactivate", actor=actor, before=before, after=after,
                reason="人工下架，不再進生成 prompt（決策 0030）")
    conn.commit()
    return after


def list_rules_for_brand(conn: Conn, brand_id: str) -> list:
    """品牌底下所有生效中的規則（含品牌整體與各產品專屬——品牌檔案頁要看到全部）。

    規則不再過期（dead-code-sweep 票 04，2026-08-30 使用者裁決）：曾經有一支
    rule_lifecycle.sweep_expired_rules() 在這裡先把逾期未重新確認的 soft 規則掃成
    pending_reconfirm，唯一能救回來的入口只長在已刪除的累積智慧頁，等於規則會無聲
    消失、沒人救得回來。裁決：使用者寫的規則除非自己刪除，否則永遠生效——已刪除該
    掃描與 pending_reconfirm 狀態的所有讀寫端；測到的資料庫沒有任何列處在
    pending_reconfirm，故不需放寬這裡的 status 過濾。"""
    return _rows(conn.execute(
        "SELECT * FROM rule WHERE brand_id = %s AND status = 'active' ORDER BY created_at",
        (brand_id,),
    ))


def list_rules_for_product(conn: Conn, brand_id: str, product_id: str) -> list:
    """整個品牌的規則 + 本產品專屬規則（不含其他產品的專屬規則）。理由同 list_rules_for_brand
    ——規則不再過期（dead-code-sweep 票 04）。"""
    return _rows(conn.execute(
        "SELECT * FROM rule WHERE brand_id = %s AND status = 'active' "
        "AND (product_id IS NULL OR product_id = %s) ORDER BY created_at",
        (brand_id, product_id),
    ))


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------

def create_claim(conn: Conn, brand_id: str, *, actor: str, claim_text: str,
                  claim_type: str, product_id: str | None = None,
                  evidence_source_reference_id: str | None = None) -> dict:
    _require(claim_text, "claim.claim_text 為必填")
    _require(actor, "actor 為必填")
    if claim_type not in ("approved", "high_risk", "forbidden"):
        raise ValueError("claim.claim_type 只能是 approved / high_risk / forbidden")
    claim_id = new_id("clm")
    ts = now_utc()
    row = {
        "id": claim_id, "brand_id": brand_id, "product_id": product_id, "claim_text": claim_text,
        "claim_type": claim_type, "evidence_source_reference_id": evidence_source_reference_id,
        "status": "active", "created_at": ts, "updated_at": ts,
    }
    org_id = _org_id_for_brand(conn, brand_id)
    conn.execute(
        "INSERT INTO claim (id, org_id, brand_id, product_id, claim_text, claim_type, "
        "evidence_source_reference_id, status, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (row["id"], org_id, row["brand_id"], row["product_id"], row["claim_text"], row["claim_type"],
         row["evidence_source_reference_id"], row["status"], row["created_at"], row["updated_at"]),
    )
    if product_id:
        _bump_product_version(conn, brand_id, product_id)
    else:
        _bump_brand_version(conn, brand_id)
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="claim", entity_id=claim_id,
                action="create", actor=actor, before=None, after=row)
    conn.commit()
    return row


def get_claim(conn: Conn, brand_id: str, claim_id: str) -> dict | None:
    return _row(conn.execute(
        "SELECT * FROM claim WHERE id = %s AND brand_id = %s", (claim_id, brand_id)).fetchone())


def update_claim(conn: Conn, brand_id: str, claim_id: str, *, actor: str,
                  claim_text: str, claim_type: str, product_id: str | None = None,
                  evidence_source_reference_id: str | None = None) -> dict:
    """編輯宣稱內容，比照 update_brand_fact：人工編輯直接生效（決策 0013）。"""
    _require(claim_text, "claim.claim_text 為必填")
    _require(actor, "actor 為必填")
    if claim_type not in ("approved", "high_risk", "forbidden"):
        raise ValueError("claim.claim_type 只能是 approved / high_risk / forbidden")
    before = get_claim(conn, brand_id, claim_id)
    if before is None:
        raise ValueError(f"找不到宣稱：{claim_id}")
    ts = now_utc()
    conn.execute(
        "UPDATE claim SET claim_text = %s, claim_type = %s, product_id = %s, "
        "evidence_source_reference_id = %s, updated_at = %s WHERE id = %s AND brand_id = %s",
        (claim_text, claim_type, product_id, evidence_source_reference_id, ts, claim_id, brand_id),
    )
    after = get_claim(conn, brand_id, claim_id)
    if product_id:
        _bump_product_version(conn, brand_id, product_id)
    else:
        _bump_brand_version(conn, brand_id)
    if before["product_id"] and before["product_id"] != product_id:
        _bump_product_version(conn, brand_id, before["product_id"])
    org_id = _org_id_for_brand(conn, brand_id)
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="claim", entity_id=claim_id,
                action="update", actor=actor, before=before, after=after,
                reason="人工編輯直接生效（決策 0013）")
    conn.commit()
    return after


def list_claims_for_brand(conn: Conn, brand_id: str) -> list:
    """品牌底下所有生效中的宣稱（含品牌整體與各產品專屬——品牌檔案頁要看到全部）。"""
    return _rows(conn.execute(
        "SELECT * FROM claim WHERE brand_id = %s AND status = 'active' ORDER BY created_at",
        (brand_id,),
    ))


def list_claims_for_product(conn: Conn, brand_id: str, product_id: str) -> list:
    """整個品牌的宣稱 + 本產品專屬宣稱（不含其他產品的專屬宣稱）。"""
    return _rows(conn.execute(
        "SELECT * FROM claim WHERE brand_id = %s AND status = 'active' "
        "AND (product_id IS NULL OR product_id = %s) ORDER BY created_at",
        (brand_id, product_id),
    ))


# ---------------------------------------------------------------------------
# Owned Channel：已拆進 repository_channels.py（見本檔頭 import），這裡不再放定義。
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Source Reference（基本建立與查詢，無 UI 亦需可程式存取）
# ---------------------------------------------------------------------------

def create_source_reference(conn: Conn, brand_id: str, *, actor: str, title: str,
                             source_type: str, captured_date, url: str | None = None,
                             published_date=None, locale: str | None = None,
                             note: str | None = None) -> dict:
    """captured_date／published_date：`date` 物件（source_reference 兩欄是 Postgres date，
    02-3b：呼叫端不再傳 ISO 字串）。"""
    _require(title, "source_reference.title 為必填")
    _require(source_type, "source_reference.source_type 為必填")
    _require(captured_date, "source_reference.captured_date 為必填")
    _require(actor, "actor 為必填")
    src_id = new_id("src")
    ts = now_utc()
    row = {
        "id": src_id, "brand_id": brand_id, "title": title, "url": url, "source_type": source_type,
        "published_date": published_date, "captured_date": captured_date, "locale": locale,
        "note": note, "created_at": ts,
    }
    org_id = _org_id_for_brand(conn, brand_id)
    conn.execute(
        "INSERT INTO source_reference (id, org_id, brand_id, title, url, source_type, published_date, "
        "captured_date, locale, note, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (row["id"], org_id, row["brand_id"], row["title"], row["url"], row["source_type"],
         row["published_date"], row["captured_date"], row["locale"], row["note"], row["created_at"]),
    )
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="source_reference", entity_id=src_id,
                action="create", actor=actor, before=None, after=row)
    conn.commit()
    return row


def get_source_reference(conn: Conn, brand_id: str,
                          source_reference_id: str) -> dict | None:
    return _row(conn.execute(
        "SELECT * FROM source_reference WHERE id = %s AND brand_id = %s",
        (source_reference_id, brand_id),
    ).fetchone())


def list_source_references(conn: Conn, brand_id: str) -> list:
    return _rows(conn.execute(
        "SELECT * FROM source_reference WHERE brand_id = %s ORDER BY created_at DESC", (brand_id,)
    ))


# ---------------------------------------------------------------------------
# Official Asset（基本建立與查詢，無 UI 亦需可程式存取）
# ---------------------------------------------------------------------------

def create_official_asset(conn: Conn, brand_id: str, *, actor: str, asset_kind: str,
                           storage_key: str, product_id: str | None = None,
                           title: str | None = None, usage_note: str | None = None) -> dict:
    _require(asset_kind, "official_asset.asset_kind 為必填")
    _require(storage_key, "official_asset.storage_key 為必填")
    _require(actor, "actor 為必填")
    asset_id = new_id("oas")
    ts = now_utc()
    row = {
        "id": asset_id, "brand_id": brand_id, "product_id": product_id, "asset_kind": asset_kind,
        "storage_key": storage_key, "title": title, "usage_note": usage_note, "status": "active",
        "created_at": ts, "updated_at": ts,
    }
    org_id = _org_id_for_brand(conn, brand_id)
    conn.execute(
        "INSERT INTO official_asset (id, org_id, brand_id, product_id, asset_kind, storage_key, title, "
        "usage_note, status, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (row["id"], org_id, row["brand_id"], row["product_id"], row["asset_kind"], row["storage_key"],
         row["title"], row["usage_note"], row["status"], row["created_at"], row["updated_at"]),
    )
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="official_asset", entity_id=asset_id,
                action="create", actor=actor, before=None, after=row)
    conn.commit()
    return row


def list_official_assets(conn: Conn, brand_id: str) -> list:
    return _rows(conn.execute(
        "SELECT * FROM official_asset WHERE brand_id = %s ORDER BY created_at DESC", (brand_id,)
    ))


def get_official_asset(conn: Conn, brand_id: str, asset_id: str) -> dict | None:
    return _row(conn.execute(
        "SELECT * FROM official_asset WHERE id = %s AND brand_id = %s", (asset_id, brand_id)
    ).fetchone())


def delete_official_asset(conn: Conn, brand_id: str, asset_id: str, *, actor: str) -> None:
    _delete_entity(conn, brand_id, "official_asset", asset_id, actor=actor, kind_label="官方素材")


# ---------------------------------------------------------------------------
# Brand Performance Baseline（基本建立與查詢，無 UI 亦需可程式存取）
# ---------------------------------------------------------------------------

def create_brand_performance_baseline(conn: Conn, brand_id: str, *, actor: str,
                                       metric: str, value: float, as_of_date: str, created_by: str,
                                       product_id: str | None = None, unit: str | None = None,
                                       basis_note: str | None = None,
                                       source_cycle_id: str | None = None,
                                       sample_note: str | None = None) -> dict:
    _require(metric, "brand_performance_baseline.metric 為必填")
    _require(as_of_date, "brand_performance_baseline.as_of_date 為必填")
    _require(created_by, "brand_performance_baseline.created_by 為必填")
    _require(actor, "actor 為必填")
    if value is None:
        raise ValueError("brand_performance_baseline.value 為必填")
    baseline_id = new_id("bpb")
    ts = now_utc()
    row = {
        "id": baseline_id, "brand_id": brand_id, "product_id": product_id, "metric": metric,
        "value": value, "unit": unit, "basis_note": basis_note, "source_cycle_id": source_cycle_id,
        "sample_note": sample_note, "as_of_date": as_of_date, "created_by": created_by,
        "created_at": ts, "updated_at": ts,
    }
    org_id = _org_id_for_brand(conn, brand_id)
    conn.execute(
        "INSERT INTO brand_performance_baseline (id, org_id, brand_id, product_id, metric, value, unit, "
        "basis_note, source_cycle_id, sample_note, as_of_date, created_by, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (row["id"], org_id, row["brand_id"], row["product_id"], row["metric"], row["value"], row["unit"],
         row["basis_note"], row["source_cycle_id"], row["sample_note"], row["as_of_date"],
         row["created_by"], row["created_at"], row["updated_at"]),
    )
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="brand_performance_baseline",
                entity_id=baseline_id, action="create", actor=actor, before=None, after=row)
    conn.commit()
    return row


def list_brand_performance_baselines(conn: Conn, brand_id: str) -> list:
    return _rows(conn.execute(
        "SELECT * FROM brand_performance_baseline WHERE brand_id = %s ORDER BY as_of_date DESC",
        (brand_id,),
    ))


# ---------------------------------------------------------------------------
# Brand Report（顧問分析報告，決策 0017：只 INSERT、永不 UPDATE，歷史留著不做清單頁）
# ---------------------------------------------------------------------------

def create_brand_report(conn: Conn, brand_id: str, *, actor: str, model: str,
                         llm_task_id: str | None, brand_version: int,
                         source_fact_count: int, sections: dict) -> dict:
    _require(actor, "actor 為必填")
    _require(model, "brand_report.model 為必填")
    report_id = new_id("rpt")
    ts = now_utc()
    row = {
        "id": report_id, "brand_id": brand_id, "generated_at": ts, "generated_by": actor,
        "model": model, "llm_task_id": llm_task_id, "brand_version": brand_version,
        "source_fact_count": source_fact_count,
        "sections_json": sections,
    }
    org_id = _org_id_for_brand(conn, brand_id)
    conn.execute(
        "INSERT INTO brand_report (id, org_id, brand_id, generated_at, generated_by, model, llm_task_id, "
        "brand_version, source_fact_count, sections_json) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (row["id"], org_id, row["brand_id"], row["generated_at"], row["generated_by"], row["model"],
         row["llm_task_id"], row["brand_version"], row["source_fact_count"], jsonb(row["sections_json"])),
    )
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="brand_report", entity_id=report_id,
                action="create", actor=actor,
                after={"model": model, "llm_task_id": llm_task_id, "source_fact_count": source_fact_count},
                reason="生成顧問分析報告")
    conn.commit()
    row["sections"] = sections
    return row


def get_latest_brand_report(conn: Conn, brand_id: str) -> dict | None:
    row = _row(conn.execute(
        "SELECT * FROM brand_report WHERE brand_id = %s ORDER BY generated_at DESC, id DESC LIMIT 1",
        (brand_id,),
    ).fetchone())
    if row is not None:
        row["sections"] = row["sections_json"]
    return row


# ---------------------------------------------------------------------------
# Customer Voice（顧客原話語料庫，GitHub issue #14，決策 0023 第 18a 條／0024 第 2 條）
# ---------------------------------------------------------------------------

def _with_extraction(row: dict | None) -> dict | None:
    if row is not None:
        row["extraction"] = row["extraction_json"]
    return row


def create_customer_voice(conn: Conn, brand_id: str, *, actor: str, raw_text: str,
                           source_channel: str, source_type: str, extraction: list,
                           source_detail: str | None = None,
                           llm_task_id: str | None = None) -> dict:
    _require(raw_text, "customer_voice.raw_text 為必填")
    _require(source_channel, "customer_voice.source_channel 為必填")
    _require(actor, "actor 為必填")
    if source_type not in ("manual", "crawler"):
        raise ValueError("customer_voice.source_type 只能是 manual 或 crawler")
    cv_id = new_id("cvc")
    ts = now_utc()
    row = {
        "id": cv_id, "brand_id": brand_id, "raw_text": raw_text, "source_channel": source_channel,
        "source_detail": source_detail or None, "source_type": source_type, "status": "active",
        "extraction_json": extraction, "llm_task_id": llm_task_id,
        "created_by": actor, "created_at": ts, "updated_at": ts,
    }
    org_id = _org_id_for_brand(conn, brand_id)
    conn.execute(
        "INSERT INTO customer_voice (id, org_id, brand_id, raw_text, source_channel, source_detail, "
        "source_type, status, extraction_json, llm_task_id, created_by, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (row["id"], org_id, row["brand_id"], row["raw_text"], row["source_channel"], row["source_detail"],
         row["source_type"], row["status"], jsonb(row["extraction_json"]), row["llm_task_id"],
         row["created_by"], row["created_at"], row["updated_at"]),
    )
    _bump_brand_version(conn, brand_id)
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="customer_voice", entity_id=cv_id,
                action="create", actor=actor, before=None,
                after={**row, "extraction": extraction})
    conn.commit()
    return _with_extraction(row)


def get_customer_voice(conn: Conn, brand_id: str, cv_id: str) -> dict | None:
    return _with_extraction(_row(conn.execute(
        "SELECT * FROM customer_voice WHERE id = %s AND brand_id = %s", (cv_id, brand_id)
    ).fetchone()))


def get_customer_voice_by_llm_task_id(conn: Conn, brand_id: str, llm_task_id: str) -> dict | None:
    """票 08：品牌智庫抽原話搬上佇列後，狀態端點靠這個查回「這個 llm_task 列真的
    落庫了嗎」——`create_customer_voice()` 一律記下自己的 `llm_task_id`（見上方），
    這裡只是反過來查。找不到＝那一次呼叫解析失敗（誠實失敗，沒有入庫），不是還沒跑完
    ——呼叫端已經先確認過 `llm_task.status == 'succeeded'` 才會查到這裡。"""
    return _with_extraction(_row(conn.execute(
        "SELECT * FROM customer_voice WHERE brand_id = %s AND llm_task_id = %s",
        (brand_id, llm_task_id),
    ).fetchone()))


def list_customer_voices(conn: Conn, brand_id: str,
                          status: str | None = None) -> list:
    if status:
        rows = _rows(conn.execute(
            "SELECT * FROM customer_voice WHERE brand_id = %s AND status = %s ORDER BY created_at DESC",
            (brand_id, status),
        ))
    else:
        rows = _rows(conn.execute(
            "SELECT * FROM customer_voice WHERE brand_id = %s ORDER BY created_at DESC", (brand_id,)
        ))
    return [_with_extraction(r) for r in rows]


def set_customer_voice_status(conn: Conn, brand_id: str, cv_id: str, *,
                               status: str, actor: str) -> dict:
    """封存／恢復（決策 0023 第 8 條：新資料實體必附封存＋刪除；封存與刪除各自獨立，
    封存不是刪除的前置條件——這裡沿用 brand／product 的封存欄位模式，但刪除比照
    _delete_entity，任何狀態都能刪）。"""
    _require(actor, "actor 為必填")
    if status not in ("active", "archived"):
        raise ValueError("customer_voice.status 只能是 active 或 archived")
    before = get_customer_voice(conn, brand_id, cv_id)
    if before is None:
        raise ValueError(f"找不到顧客原話：{cv_id}")
    ts = now_utc()
    conn.execute(
        "UPDATE customer_voice SET status = %s, updated_at = %s WHERE id = %s AND brand_id = %s",
        (status, ts, cv_id, brand_id),
    )
    after = get_customer_voice(conn, brand_id, cv_id)
    org_id = _org_id_for_brand(conn, brand_id)
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="customer_voice", entity_id=cv_id,
                action="archive" if status == "archived" else "restore", actor=actor,
                before=before, after=after)
    conn.commit()
    return after


def delete_customer_voice(conn, brand_id: str, cv_id: str, *, actor: str) -> None:
    _delete_entity(conn, brand_id, "customer_voice", cv_id, actor=actor, kind_label="顧客原話")


# ---------------------------------------------------------------------------
# 清理登記處（第 2 刀）：向 app.core.cleanup 登記本模組的清點／清除函式，
# 刪品牌時由登記處統一呼叫，本模組不必再被別人手寫死「記得通知它」。
# ---------------------------------------------------------------------------

cleanup.register("品牌智庫", count_brand=count_brand_data, delete_brand=delete_brand_data,
                 brand_tables={t for t, _ in BRAND_CHILD_TABLES},
                 count_product=count_product_data, delete_product=delete_product_data,
                 product_tables={t for t, _ in PRODUCT_CHILD_TABLES})
