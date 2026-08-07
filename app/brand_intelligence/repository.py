# -*- coding: utf-8 -*-
"""app/brand_intelligence/repository.py — Brand Intelligence 存取層。

見 docs/design/03-data-model.md §3.2、§7；DESIGN.md §17 決策 3。

硬性規則（呼叫端請勿繞過）：
1. 所有品牌範圍查詢一律以 brand_id 過濾，沒有「查全部品牌資料」的無過濾入口。
   （brand 本身是隔離根鍵，list_brands() 是切換品牌用的清單，本來就橫跨品牌，不算例外。）
2. 每次資料異動（新增／編輯／確認）都寫一筆 audit_log，含 before/after JSON 與 actor。
3. brand_fact／product_fact／rule／claim 異動時，對應聚合（brand 或 product）的
   knowledge_version + 1（rule/claim 依 product_id 是否為空決定影響品牌還是產品聚合）。
4. 事實確認流程：pending → confirmed 時記錄 confirmed_by / confirmed_at。
5. 人工編輯直接生效、不退回 pending；編輯者成為最新確認人（決策 0013 用戶優先，
   取代原 DESIGN.md §17 決策 3）。
6. 產品以封存為預設；已封存的產品可再進一步硬刪除（delete_product），一併清掉本模組
   掛在該產品下的資料，audit_log 留下 before 全文與各表筆數（決策 0020，比照品牌 0015）。
   事實／規則／宣稱單筆硬刪除同樣適用（before 全文記 audit_log，決策 0013）。
7. 品牌以封存為預設；已封存的品牌可再進一步硬刪除（delete_brand），一併清掉本模組
   所有掛在該品牌下的資料，audit_log 留下 before 全文與各表筆數（決策 0015）。
   建檔精靈（intake）的資料由該模組自行清，本檔不跨模組刪表。
"""

import json
import sqlite3
from typing import Optional

from app.core import cleanup
from app.core.audit import write_audit
from app.core.db import new_id, now_iso


def _require(value, message: str) -> None:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(message)


def _row(cursor_row) -> Optional[dict]:
    return dict(cursor_row) if cursor_row is not None else None


def _rows(cursor) -> list:
    return [dict(r) for r in cursor.fetchall()]


def _bump_brand_version(conn: sqlite3.Connection, brand_id: str) -> None:
    conn.execute(
        "UPDATE brand SET knowledge_version = knowledge_version + 1, updated_at = ? WHERE id = ?",
        (now_iso(), brand_id),
    )


def _bump_product_version(conn: sqlite3.Connection, brand_id: str, product_id: str) -> None:
    conn.execute(
        "UPDATE product SET knowledge_version = knowledge_version + 1, updated_at = ? "
        "WHERE brand_id = ? AND id = ?",
        (now_iso(), brand_id, product_id),
    )


# ---------------------------------------------------------------------------
# Brand
# ---------------------------------------------------------------------------

def create_brand(conn: sqlite3.Connection, *, name: str, client_name: Optional[str], actor: str) -> dict:
    _require(name, "brand.name 為必填")
    _require(actor, "actor 為必填")
    brand_id = new_id("brd")
    ts = now_iso()
    row = {
        "id": brand_id, "name": name, "client_name": client_name or None,
        "status": "active", "knowledge_version": 1, "created_at": ts, "updated_at": ts,
    }
    conn.execute(
        "INSERT INTO brand (id, name, client_name, status, knowledge_version, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (row["id"], row["name"], row["client_name"], row["status"], row["knowledge_version"],
         row["created_at"], row["updated_at"]),
    )
    write_audit(conn, brand_id=brand_id, entity_type="brand", entity_id=brand_id,
                action="create", actor=actor, before=None, after=row)
    conn.commit()
    return row


def get_brand(conn: sqlite3.Connection, brand_id: str) -> Optional[dict]:
    return _row(conn.execute("SELECT * FROM brand WHERE id = ?", (brand_id,)).fetchone())


def list_brands(conn: sqlite3.Connection, status: Optional[str] = None) -> list:
    """品牌切換器用的清單，橫跨所有品牌（brand 是隔離根鍵本身，不受品牌過濾規則限制）。"""
    if status:
        return _rows(conn.execute("SELECT * FROM brand WHERE status = ? ORDER BY name", (status,)))
    return _rows(conn.execute("SELECT * FROM brand ORDER BY name"))


def update_brand(conn: sqlite3.Connection, brand_id: str, *, name: str,
                  client_name: Optional[str], status: str, actor: str) -> dict:
    _require(name, "brand.name 為必填")
    _require(actor, "actor 為必填")
    if status not in ("active", "archived"):
        raise ValueError("brand.status 只能是 active 或 archived（只封存不刪除）")
    before = get_brand(conn, brand_id)
    if before is None:
        raise ValueError(f"找不到品牌：{brand_id}")
    ts = now_iso()
    conn.execute(
        "UPDATE brand SET name = ?, client_name = ?, status = ?, updated_at = ? WHERE id = ?",
        (name, client_name or None, status, ts, brand_id),
    )
    after = get_brand(conn, brand_id)
    write_audit(conn, brand_id=brand_id, entity_type="brand", entity_id=brand_id,
                action="update", actor=actor, before=before, after=after)
    conn.commit()
    return after


# 平台中立轉換目標（票 A）：不得存 Meta 事件名，Meta 專屬欄位名只能關在
# app/ads/meta_api.py（決策 0016 硬性原則 1）。Meta 標準事件對照表由 README 記錄（票 B）。
CONVERSION_GOALS = ("purchase", "lead", "booking", "awareness")


def set_brand_switches(conn: sqlite3.Connection, brand_id: str, *,
                        market_region: Optional[str], conversion_goal: Optional[str],
                        actor: str) -> dict:
    """寫入 brand.market_region／brand.conversion_goal（票 A，方法論開關讀這兩欄）。"""
    _require(actor, "actor 為必填")
    if conversion_goal is not None and conversion_goal not in CONVERSION_GOALS:
        raise ValueError(f"conversion_goal 只能是 {'/'.join(CONVERSION_GOALS)} 其中之一")
    before = get_brand(conn, brand_id)
    if before is None:
        raise ValueError(f"找不到品牌：{brand_id}")
    ts = now_iso()
    conn.execute(
        "UPDATE brand SET market_region = ?, conversion_goal = ?, updated_at = ? WHERE id = ?",
        (market_region, conversion_goal, ts, brand_id),
    )
    after = get_brand(conn, brand_id)
    write_audit(conn, brand_id=brand_id, entity_type="brand", entity_id=brand_id,
                action="update", actor=actor, before=before, after=after)
    conn.commit()
    return after


# 方法論開關名（中文，供 app/methodology/README.md 對照表的（需要：X）條件比對，
# 見 app/llm/methodology.py）。只有 'website' 屬於網站型——值域見 app/mock_data.py
# CHANNEL_TYPES，不自己發明值。
_WEBSITE_CHANNEL_TYPE = "website"


def compute_methodology_switches(conn: sqlite3.Connection, brand_id: str) -> dict:
    """算出方法論開關的四個布林值，供 app/llm/methodology.py 過濾 README 對照表的
    條件檔（票 A）。只讀既有資料／brand 的新兩欄，不另外新增狀態欄位。"""
    has_product = conn.execute(
        "SELECT 1 FROM product WHERE brand_id = ? LIMIT 1", (brand_id,)
    ).fetchone() is not None
    brand = get_brand(conn, brand_id)
    has_transaction = bool(brand) and brand["conversion_goal"] == "purchase"
    has_website = conn.execute(
        "SELECT 1 FROM owned_channel WHERE brand_id = ? AND channel_type = ? LIMIT 1",
        (brand_id, _WEBSITE_CHANNEL_TYPE),
    ).fetchone() is not None
    has_regulatory = conn.execute(
        "SELECT 1 FROM brand_fact WHERE brand_id = ? AND status = 'confirmed' "
        "AND fact_type = 'regulatory' LIMIT 1", (brand_id,)
    ).fetchone() is not None
    return {
        "有商品": has_product,
        "站內交易": has_transaction,
        "有自有網站": has_website,
        "健康類法規": has_regulatory,
    }


# 刪品牌時要清掉的本模組表，順序＝先子後父（PRAGMA foreign_keys = ON，順序錯就會被擋）。
BRAND_CHILD_TABLES = (
    ("product_fact", "產品事實"),
    ("product_economics", "產品經濟數據"),
    ("brand_performance_baseline", "成效基準"),
    ("rule", "規則"),
    ("claim", "宣稱"),
    ("official_asset", "官方素材"),
    ("strategy_hypothesis", "策略假設"),
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


def count_brand_data(conn: sqlite3.Connection, brand_id: str) -> list:
    """回傳 [(中文名稱, 筆數)]，給刪除確認頁列出「按下去會消失什麼」。"""
    return [
        (label, conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE brand_id = ?", (brand_id,)).fetchone()[0])
        for table, label in BRAND_CHILD_TABLES
    ]


def count_pending_product_layer(conn: sqlite3.Connection, brand_id: str) -> int:
    """品牌底下所有產品的「待確認」筆數合計：產品事實 + 產品經濟數字（唯讀統計，
    issue #8 功能選單頁提醒卡＋品牌智庫首頁「產品」卡用）。"""
    fact_n = conn.execute(
        "SELECT COUNT(*) FROM product_fact WHERE brand_id = ? AND status = 'pending'", (brand_id,),
    ).fetchone()[0]
    econ_n = conn.execute(
        "SELECT COUNT(*) FROM product_economics WHERE brand_id = ? AND status = 'pending'", (brand_id,),
    ).fetchone()[0]
    return fact_n + econ_n


def delete_brand_data(conn: sqlite3.Connection, brand_id: str) -> dict:
    """清掉本模組掛在該品牌下的子表資料（只清 BRAND_CHILD_TABLES 這 13 張子表，
    不碰 brand 那一列、不寫稽核），登記進 app.core.cleanup 給 delete_brand() 呼叫用。
    只下 DELETE、不 commit（Q4 單一交易、全有全無，commit 由 delete_brand() 統一做）。
    """
    counts = dict(count_brand_data(conn, brand_id))
    for table, _label in BRAND_CHILD_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE brand_id = ?", (brand_id,))
    return counts


def delete_brand(conn: sqlite3.Connection, brand_id: str, *, actor: str) -> dict:
    """硬刪除一個已封存品牌與所有登記模組掛在它底下的資料，不可逆（決策 0015）。

    只收已封存的品牌：使用中的品牌得先封存，隔一道手續才刪得掉。
    透過 app.core.cleanup.delete_all() 清掉所有登記模組的資料（本模組「品牌智庫」
    自己也是登記模組之一，會被 delete_all 一併叫到，這裡不重複清），
    再刪 brand 本身那一列、寫稽核，整段只有這裡最後這一次 commit（Q4 全有全無）。

    app 全程共用同一條 DB 連線（見 app/core/db.py connect()）：不 commit 不等於自動
    回捲，中途出錯若不明確 conn.rollback()，懸著的 DELETE 會等到下一個不相干的請求
    在同一條連線上 commit() 時被一起沖進 DB，而且沒有 audit_log 紀錄。所以這裡明確
    包 try/except，出錯就 rollback 再往外拋。
    """
    _require(actor, "actor 為必填")
    before = get_brand(conn, brand_id)
    if before is None:
        raise ValueError(f"找不到品牌：{brand_id}")
    if before["status"] != "archived":
        raise ValueError("只有已封存的品牌可以刪除，請先把品牌封存。")

    # 這條連線是全 app 共用的（app/core/db.py connect()），背景執行緒也在用
    # （app/ads/routes.py 的 _progress_run，例如 Meta 回填、AI 生成等待頁）。
    # 如果撞上「別人已經寫了東西但還沒 commit」的空檔：
    #   - 下面的 BEGIN 會拋 OperationalError（不能在交易裡再開交易），
    #   - 接著 except 的 rollback() 會把對方那筆還沒 commit、跟刪品牌毫無關係的資料
    #     一起沖銷掉，而對方之後 commit() 不會報錯，等於資料靜默消失。
    # 所以這裡先擋下來、給人話錯誤請他重試，而不是硬闖。刪品牌是罕見的手動操作，
    # 請使用者等一下遠比靜默弄丟別人的資料好。

    if conn.in_transaction:
        raise RuntimeError("系統正在處理其他工作，現在不能刪除品牌。請等幾秒後再試一次。")

    try:
        # 延後外鍵檢查到 COMMIT 那一刻（第 5 刀）：各登記模組刪各自的表時，例如
        # cycle_shopee_code（訂單模組）REFERENCES campaign_cycle(id)（廣告模組），
        # 若哪個先刪錯了順序（父表先於子表），SQLite 預設會當場擋下。開這個 PRAGMA 後，
        # 外鍵檢查延到整個交易 COMMIT 時才做一次——只要 COMMIT 那一刻資料是乾淨的
        # （刪品牌就是把相關資料全部清光，最後一定乾淨），中途誰先誰後完全不重要，
        # 模組之間也不必再協調登記順序。SQLite 會在每次 COMMIT／ROLLBACK 時自動把它
        # 轉回 OFF，不會外溢到下一個不相干的操作。
        #
        # 這裡先明確 BEGIN、才下 PRAGMA，順序不是隨意的，親自測過才知道：Python 的
        # sqlite3 模組只在遇到第一個 DML（INSERT/UPDATE/DELETE）時才隱式開交易，
        # PRAGMA 本身、SELECT 都不會開交易。而下面 cleanup.delete_all() 呼叫的每個
        # 模組的 delete_brand 函式，內部第一步都是 count_brand_data()（一串 SELECT）
        # 才接 DELETE——若 PRAGMA 下在交易外面，SQLite 會把「沒有顯式交易時的每一句
        # 陳述式」各自當成一個獨立的隱式交易，那串 SELECT 執行完就會讓 defer_foreign_
        # keys 悄悄被重置回 OFF，等真正的 DELETE 跑到時保護已經失效（親測過會炸，
        # 見 app/tests/test_orders_core_brand_cleanup.py 的 PRAGMA 生效證明測試）。
        # 先 BEGIN 讓交易先開好，PRAGMA 才會跟後面所有 SELECT／DELETE 綁在同一個交易裡。
        conn.execute("BEGIN")
        conn.execute("PRAGMA defer_foreign_keys = ON")
        counts = cleanup.delete_all(conn, brand_id)
        conn.execute("DELETE FROM brand WHERE id = ?", (brand_id,))
        write_audit(conn, brand_id=brand_id, entity_type="brand", entity_id=brand_id,
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

def create_product(conn: sqlite3.Connection, brand_id: str, *, name: str, actor: str) -> dict:
    _require(name, "product.name 為必填")
    _require(actor, "actor 為必填")
    if get_brand(conn, brand_id) is None:
        raise ValueError(f"找不到品牌：{brand_id}")
    product_id = new_id("prd")
    ts = now_iso()
    row = {
        "id": product_id, "brand_id": brand_id, "name": name, "status": "active",
        "knowledge_version": 1, "created_at": ts, "updated_at": ts,
    }
    conn.execute(
        "INSERT INTO product (id, brand_id, name, status, knowledge_version, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (row["id"], row["brand_id"], row["name"], row["status"], row["knowledge_version"],
         row["created_at"], row["updated_at"]),
    )
    write_audit(conn, brand_id=brand_id, entity_type="product", entity_id=product_id,
                action="create", actor=actor, before=None, after=row)
    conn.commit()
    return row


def get_product(conn: sqlite3.Connection, brand_id: str, product_id: str) -> Optional[dict]:
    """跨品牌存取一律回 None（呼叫端轉成「找不到」），不得洩漏資料屬於其他品牌。"""
    return _row(conn.execute(
        "SELECT * FROM product WHERE id = ? AND brand_id = ?", (product_id, brand_id)
    ).fetchone())


def list_products(conn: sqlite3.Connection, brand_id: str) -> list:
    return _rows(conn.execute("SELECT * FROM product WHERE brand_id = ? ORDER BY name", (brand_id,)))


def update_product(conn: sqlite3.Connection, brand_id: str, product_id: str, *,
                    name: str, status: str, actor: str) -> dict:
    _require(name, "product.name 為必填")
    _require(actor, "actor 為必填")
    if status not in ("active", "archived"):
        raise ValueError("product.status 只能是 active 或 archived（只封存不刪除）")
    before = get_product(conn, brand_id, product_id)
    if before is None:
        raise ValueError(f"找不到產品：{product_id}")
    ts = now_iso()
    conn.execute(
        "UPDATE product SET name = ?, status = ?, updated_at = ? WHERE id = ? AND brand_id = ?",
        (name, status, ts, product_id, brand_id),
    )
    after = get_product(conn, brand_id, product_id)
    write_audit(conn, brand_id=brand_id, entity_type="product", entity_id=product_id,
                action="update", actor=actor, before=before, after=after)
    conn.commit()
    return after


# 刪產品時要清掉的本模組表，只挑 product_id 對得上這顆產品的列（同一張表裡 product_id
# 為 NULL 或屬於別的產品的列不會被這個條件選到，不會誤刪品牌層或別的產品的資料）。
PRODUCT_CHILD_TABLES = (
    ("product_fact", "產品事實"),
    ("product_economics", "產品經濟數據"),
    ("brand_performance_baseline", "成效基準"),
    ("rule", "規則"),
    ("claim", "宣稱"),
    ("official_asset", "官方素材"),
    ("strategy_hypothesis", "策略假設"),
    ("learning_ledger", "品牌學習紀錄"),
)


def count_product_data(conn: sqlite3.Connection, brand_id: str, product_id: str) -> list:
    """回傳 [(中文名稱, 筆數)]，給刪除確認頁列出「按下去會消失什麼」。"""
    return [
        (label, conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE brand_id = ? AND product_id = ?",
            (brand_id, product_id)).fetchone()[0])
        for table, label in PRODUCT_CHILD_TABLES
    ]


def delete_product_data(conn: sqlite3.Connection, brand_id: str, product_id: str) -> dict:
    """清掉本模組掛在該產品下的子表資料（只清 PRODUCT_CHILD_TABLES 這 8 張子表，
    不碰 product 那一列、不寫稽核），登記進 app.core.cleanup 給 delete_product() 呼叫用。
    只下 DELETE、不 commit（Q4 單一交易、全有全無，commit 由 delete_product() 統一做）。
    """
    counts = dict(count_product_data(conn, brand_id, product_id))
    for table, _label in PRODUCT_CHILD_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE brand_id = ? AND product_id = ?",
                      (brand_id, product_id))
    return counts


def delete_product(conn: sqlite3.Connection, brand_id: str, product_id: str, *, actor: str) -> dict:
    """硬刪除一個已封存產品與所有登記模組掛在它底下的資料，不可逆（決策 0020，比照品牌 0015）。

    只收已封存的產品：使用中的產品得先封存，隔一道手續才刪得掉。

    交易處理比照 delete_brand()（第 6 刀補齊，之前只有 try/except 沒有 BEGIN 也沒有
    PRAGMA，跨模組會踩到第 5 刀踩過的兩個坑）：透過 app.core.cleanup.delete_all_product()
    清掉所有登記模組掛在這顆產品底下的資料（本模組「品牌智庫」自己也是登記模組之一，
    會被 delete_all_product 一併叫到，這裡不重複清），再刪 product 本身那一列、寫稽核，
    整段只有這裡最後這一次 commit（Q4 全有全無）。

    app 全程共用同一條 DB 連線（見 app/core/db.py connect()）：不 commit 不等於自動
    回捲，中途出錯若不明確 conn.rollback()，懸著的 DELETE 會等到下一個不相干的請求
    在同一條連線上 commit() 時被一起沖進 DB，而且沒有 audit_log 紀錄。所以這裡明確
    包 try/except，出錯就 rollback 再往外拋。
    """
    _require(actor, "actor 為必填")
    before = get_product(conn, brand_id, product_id)
    if before is None:
        raise ValueError(f"找不到產品：{product_id}")
    if before["status"] != "archived":
        raise ValueError("只有已封存的產品可以刪除，請先把產品封存。")

    # 這條連線是全 app 共用的（app/core/db.py connect()），背景執行緒也在用
    # （app/ads/routes.py 的 _progress_run，例如 Meta 回填、AI 生成等待頁）。理由同
    # delete_brand()：撞上「別人已經寫了東西但還沒 commit」的空檔，硬闖會讓 rollback()
    # 沖銷對方不相干的資料且對方毫無感覺。所以先擋下來、給人話錯誤請他重試。
    if conn.in_transaction:
        raise RuntimeError("系統正在處理其他工作，現在不能刪除產品。請等幾秒後再試一次。")

    try:
        # 延後外鍵檢查到 COMMIT 那一刻（同 delete_brand() 的理由）：各登記模組刪各自的表
        # 時，跨模組登記順序不必協調。BEGIN 必須先於 PRAGMA，理由同 delete_brand()——
        # Python 的 sqlite3 只在遇到 DML 才隱式開交易，PRAGMA／SELECT 都不會開交易，
        # 若 PRAGMA 下在交易外面，後面每個模組 delete_product 內部第一步的 SELECT
        # （count_product_data）就會讓它悄悄被重置回 OFF。
        conn.execute("BEGIN")
        conn.execute("PRAGMA defer_foreign_keys = ON")
        counts = cleanup.delete_all_product(conn, brand_id, product_id)
        conn.execute("DELETE FROM product WHERE id = ? AND brand_id = ?", (product_id, brand_id))
        write_audit(conn, brand_id=brand_id, entity_type="product", entity_id=product_id,
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

def create_brand_fact(conn: sqlite3.Connection, brand_id: str, *, actor: str, fact_type: str,
                       label: str, value: str, status: str,
                       source_reference_id: Optional[str] = None,
                       confidence: Optional[str] = None,
                       confirmed_by: Optional[str] = None) -> dict:
    _require(fact_type, "brand_fact.fact_type 為必填")
    _require(label, "brand_fact.label 為必填")
    _require(value, "brand_fact.value 為必填")
    _require(actor, "actor 為必填")
    if status not in ("confirmed", "pending"):
        raise ValueError("brand_fact.status 只能是 confirmed 或 pending")
    if status == "confirmed":
        _require(confirmed_by, "狀態為已確認時，confirmed_by 為必填")
    fact_id = new_id("bft")
    ts = now_iso()
    row = {
        "id": fact_id, "brand_id": brand_id, "fact_type": fact_type, "label": label, "value": value,
        "status": status, "source_reference_id": source_reference_id, "confidence": confidence,
        "confirmed_by": confirmed_by if status == "confirmed" else None,
        "confirmed_at": ts if status == "confirmed" else None,
        "created_at": ts, "updated_at": ts,
    }
    conn.execute(
        "INSERT INTO brand_fact (id, brand_id, fact_type, label, value, status, source_reference_id, "
        "confidence, confirmed_by, confirmed_at, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (row["id"], row["brand_id"], row["fact_type"], row["label"], row["value"], row["status"],
         row["source_reference_id"], row["confidence"], row["confirmed_by"], row["confirmed_at"],
         row["created_at"], row["updated_at"]),
    )
    _bump_brand_version(conn, brand_id)
    write_audit(conn, brand_id=brand_id, entity_type="brand_fact", entity_id=fact_id,
                action="create", actor=actor, before=None, after=row)
    conn.commit()
    return row


def get_brand_fact(conn: sqlite3.Connection, brand_id: str, fact_id: str) -> Optional[dict]:
    return _row(conn.execute(
        "SELECT * FROM brand_fact WHERE id = ? AND brand_id = ?", (fact_id, brand_id)
    ).fetchone())


def list_brand_facts(conn: sqlite3.Connection, brand_id: str, status: Optional[str] = None) -> list:
    if status:
        return _rows(conn.execute(
            "SELECT * FROM brand_fact WHERE brand_id = ? AND status = ? ORDER BY created_at",
            (brand_id, status),
        ))
    return _rows(conn.execute(
        "SELECT * FROM brand_fact WHERE brand_id = ? ORDER BY created_at", (brand_id,)
    ))


def update_brand_fact(conn: sqlite3.Connection, brand_id: str, fact_id: str, *, actor: str,
                       fact_type: str, label: str, value: str,
                       source_reference_id: Optional[str] = None,
                       confidence: Optional[str] = None) -> dict:
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
    ts = now_iso()
    confirmed_by = actor if was_confirmed else before["confirmed_by"]
    confirmed_at = ts if was_confirmed else before["confirmed_at"]
    conn.execute(
        "UPDATE brand_fact SET fact_type = ?, label = ?, value = ?, "
        "source_reference_id = ?, confidence = ?, confirmed_by = ?, confirmed_at = ?, updated_at = ? "
        "WHERE id = ? AND brand_id = ?",
        (fact_type, label, value, source_reference_id, confidence,
         confirmed_by, confirmed_at, ts, fact_id, brand_id),
    )
    after = get_brand_fact(conn, brand_id, fact_id)
    _bump_brand_version(conn, brand_id)
    reason = "人工編輯直接生效（決策 0013）" if was_confirmed else None
    write_audit(conn, brand_id=brand_id, entity_type="brand_fact", entity_id=fact_id,
                action="update", actor=actor, before=before, after=after, reason=reason)
    conn.commit()
    return after


def _delete_entity(conn: sqlite3.Connection, brand_id: str, table: str, entity_id: str, *,
                    actor: str, kind_label: str) -> None:
    """硬刪除一筆品牌資料，before 全文記進 audit_log 可追溯（決策 0013：把關人可直接清資料）。"""
    _require(actor, "actor 為必填")
    before = _row(conn.execute(
        f"SELECT * FROM {table} WHERE id = ? AND brand_id = ?", (entity_id, brand_id)).fetchone())
    if before is None:
        raise ValueError(f"找不到{kind_label}：{entity_id}")
    conn.execute(f"DELETE FROM {table} WHERE id = ? AND brand_id = ?", (entity_id, brand_id))
    _bump_brand_version(conn, brand_id)
    write_audit(conn, brand_id=brand_id, entity_type=table, entity_id=entity_id,
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


def confirm_brand_fact(conn: sqlite3.Connection, brand_id: str, fact_id: str, *,
                        confirmed_by: str, actor: str) -> dict:
    _require(confirmed_by, "confirmed_by 為必填")
    _require(actor, "actor 為必填")
    before = get_brand_fact(conn, brand_id, fact_id)
    if before is None:
        raise ValueError(f"找不到品牌事實：{fact_id}")
    ts = now_iso()
    conn.execute(
        "UPDATE brand_fact SET status = 'confirmed', confirmed_by = ?, confirmed_at = ?, updated_at = ? "
        "WHERE id = ? AND brand_id = ?",
        (confirmed_by, ts, ts, fact_id, brand_id),
    )
    after = get_brand_fact(conn, brand_id, fact_id)
    _bump_brand_version(conn, brand_id)
    write_audit(conn, brand_id=brand_id, entity_type="brand_fact", entity_id=fact_id,
                action="confirm", actor=actor, before=before, after=after)
    conn.commit()
    return after


# ---------------------------------------------------------------------------
# Product Fact
# ---------------------------------------------------------------------------

def create_product_fact(conn: sqlite3.Connection, brand_id: str, product_id: str, *, actor: str,
                         fact_type: str, label: str, value: str, status: str,
                         source_reference_id: Optional[str] = None,
                         confidence: Optional[str] = None,
                         confirmed_by: Optional[str] = None) -> dict:
    _require(fact_type, "product_fact.fact_type 為必填")
    _require(label, "product_fact.label 為必填")
    _require(value, "product_fact.value 為必填")
    _require(actor, "actor 為必填")
    if status not in ("confirmed", "pending"):
        raise ValueError("product_fact.status 只能是 confirmed 或 pending")
    if status == "confirmed":
        _require(confirmed_by, "狀態為已確認時，confirmed_by 為必填")
    fact_id = new_id("pft")
    ts = now_iso()
    row = {
        "id": fact_id, "product_id": product_id, "brand_id": brand_id, "fact_type": fact_type,
        "label": label, "value": value, "status": status, "source_reference_id": source_reference_id,
        "confidence": confidence,
        "confirmed_by": confirmed_by if status == "confirmed" else None,
        "confirmed_at": ts if status == "confirmed" else None,
        "created_at": ts, "updated_at": ts,
    }
    conn.execute(
        "INSERT INTO product_fact (id, product_id, brand_id, fact_type, label, value, status, "
        "source_reference_id, confidence, confirmed_by, confirmed_at, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (row["id"], row["product_id"], row["brand_id"], row["fact_type"], row["label"], row["value"],
         row["status"], row["source_reference_id"], row["confidence"], row["confirmed_by"],
         row["confirmed_at"], row["created_at"], row["updated_at"]),
    )
    _bump_product_version(conn, brand_id, product_id)
    write_audit(conn, brand_id=brand_id, entity_type="product_fact", entity_id=fact_id,
                action="create", actor=actor, before=None, after=row)
    conn.commit()
    return row


def get_product_fact(conn: sqlite3.Connection, brand_id: str, product_id: str,
                      fact_id: str) -> Optional[dict]:
    return _row(conn.execute(
        "SELECT * FROM product_fact WHERE id = ? AND brand_id = ? AND product_id = ?",
        (fact_id, brand_id, product_id),
    ).fetchone())


def list_product_facts(conn: sqlite3.Connection, brand_id: str, product_id: str,
                        status: Optional[str] = None) -> list:
    if status:
        return _rows(conn.execute(
            "SELECT * FROM product_fact WHERE brand_id = ? AND product_id = ? AND status = ? "
            "ORDER BY created_at",
            (brand_id, product_id, status),
        ))
    return _rows(conn.execute(
        "SELECT * FROM product_fact WHERE brand_id = ? AND product_id = ? ORDER BY created_at",
        (brand_id, product_id),
    ))


def update_product_fact(conn: sqlite3.Connection, brand_id: str, product_id: str, fact_id: str, *,
                         actor: str, fact_type: str, label: str, value: str,
                         source_reference_id: Optional[str] = None,
                         confidence: Optional[str] = None) -> dict:
    """編輯事實內容。人工編輯直接生效、不退回待確認（決策 0013 用戶優先）。"""
    _require(fact_type, "product_fact.fact_type 為必填")
    _require(label, "product_fact.label 為必填")
    _require(value, "product_fact.value 為必填")
    _require(actor, "actor 為必填")
    before = get_product_fact(conn, brand_id, product_id, fact_id)
    if before is None:
        raise ValueError(f"找不到產品事實：{fact_id}")
    was_confirmed = before["status"] == "confirmed"
    ts = now_iso()
    confirmed_by = actor if was_confirmed else before["confirmed_by"]
    confirmed_at = ts if was_confirmed else before["confirmed_at"]
    conn.execute(
        "UPDATE product_fact SET fact_type = ?, label = ?, value = ?, "
        "source_reference_id = ?, confidence = ?, confirmed_by = ?, confirmed_at = ?, updated_at = ? "
        "WHERE id = ? AND brand_id = ? AND product_id = ?",
        (fact_type, label, value, source_reference_id, confidence,
         confirmed_by, confirmed_at, ts, fact_id, brand_id, product_id),
    )
    after = get_product_fact(conn, brand_id, product_id, fact_id)
    _bump_product_version(conn, brand_id, product_id)
    reason = "人工編輯直接生效（決策 0013）" if was_confirmed else None
    write_audit(conn, brand_id=brand_id, entity_type="product_fact", entity_id=fact_id,
                action="update", actor=actor, before=before, after=after, reason=reason)
    conn.commit()
    return after


def confirm_product_fact(conn: sqlite3.Connection, brand_id: str, product_id: str, fact_id: str, *,
                          confirmed_by: str, actor: str) -> dict:
    _require(confirmed_by, "confirmed_by 為必填")
    _require(actor, "actor 為必填")
    before = get_product_fact(conn, brand_id, product_id, fact_id)
    if before is None:
        raise ValueError(f"找不到產品事實：{fact_id}")
    ts = now_iso()
    conn.execute(
        "UPDATE product_fact SET status = 'confirmed', confirmed_by = ?, confirmed_at = ?, updated_at = ? "
        "WHERE id = ? AND brand_id = ? AND product_id = ?",
        (confirmed_by, ts, ts, fact_id, brand_id, product_id),
    )
    after = get_product_fact(conn, brand_id, product_id, fact_id)
    _bump_product_version(conn, brand_id, product_id)
    write_audit(conn, brand_id=brand_id, entity_type="product_fact", entity_id=fact_id,
                action="confirm", actor=actor, before=before, after=after)
    conn.commit()
    return after


# ---------------------------------------------------------------------------
# Product Economics（依 product_id 只保留一筆現行資料；新值進來即更新既有列）
# ---------------------------------------------------------------------------

def get_product_economics(conn: sqlite3.Connection, brand_id: str, product_id: str) -> Optional[dict]:
    return _row(conn.execute(
        "SELECT * FROM product_economics WHERE brand_id = ? AND product_id = ? "
        "ORDER BY updated_at DESC LIMIT 1",
        (brand_id, product_id),
    ).fetchone())


def save_product_economics(conn: sqlite3.Connection, brand_id: str, product_id: str, *, actor: str,
                            selling_price: float, currency: str, confirmed_by: str,
                            fixed_cost: Optional[float] = None,
                            unit_variable_cost: Optional[float] = None,
                            shipping_cost: Optional[float] = None,
                            cpa_roas_basis: Optional[str] = None,
                            effective_from: Optional[str] = None,
                            effective_to: Optional[str] = None) -> dict:
    _require(currency, "product_economics.currency 為必填")
    _require(confirmed_by, "confirmed_by 為必填")
    _require(actor, "actor 為必填")
    if selling_price is None:
        raise ValueError("product_economics.selling_price 為必填")
    before = get_product_economics(conn, brand_id, product_id)
    ts = now_iso()
    row = {
        "id": before["id"] if before else new_id("pec"),
        "product_id": product_id, "brand_id": brand_id, "selling_price": selling_price,
        "fixed_cost": fixed_cost, "unit_variable_cost": unit_variable_cost,
        "shipping_cost": shipping_cost, "currency": currency, "cpa_roas_basis": cpa_roas_basis,
        "effective_from": effective_from, "effective_to": effective_to, "status": "confirmed",
        "source_reference_id": before["source_reference_id"] if before else None,
        "confirmed_by": confirmed_by, "confirmed_at": ts,
        "created_at": before["created_at"] if before else ts, "updated_at": ts,
    }
    if before:
        conn.execute(
            "UPDATE product_economics SET selling_price = ?, fixed_cost = ?, unit_variable_cost = ?, "
            "shipping_cost = ?, currency = ?, cpa_roas_basis = ?, effective_from = ?, effective_to = ?, "
            "status = ?, confirmed_by = ?, confirmed_at = ?, updated_at = ? WHERE id = ?",
            (row["selling_price"], row["fixed_cost"], row["unit_variable_cost"], row["shipping_cost"],
             row["currency"], row["cpa_roas_basis"], row["effective_from"], row["effective_to"],
             row["status"], row["confirmed_by"], row["confirmed_at"], row["updated_at"], row["id"]),
        )
        action = "update"
    else:
        conn.execute(
            "INSERT INTO product_economics (id, product_id, brand_id, selling_price, fixed_cost, "
            "unit_variable_cost, shipping_cost, currency, cpa_roas_basis, effective_from, effective_to, "
            "status, source_reference_id, confirmed_by, confirmed_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row["id"], row["product_id"], row["brand_id"], row["selling_price"], row["fixed_cost"],
             row["unit_variable_cost"], row["shipping_cost"], row["currency"], row["cpa_roas_basis"],
             row["effective_from"], row["effective_to"], row["status"], row["source_reference_id"],
             row["confirmed_by"], row["confirmed_at"], row["created_at"], row["updated_at"]),
        )
        action = "create"
    write_audit(conn, brand_id=brand_id, entity_type="product_economics", entity_id=row["id"],
                action=action, actor=actor, before=before, after=row)
    conn.commit()
    return row


def get_latest_product_source_url(conn: sqlite3.Connection, brand_id: str,
                                   product_id: str) -> Optional[str]:
    """這個產品最近一次帶網址的來源引用文字（產品事實或經濟數字都算），給「AI 再次調研」
    表單預填網址用；沒有就回 None（架構限制：使用者填的網址存在 source_reference.title，
    見 app/main.py 的 _create_source_ref）。"""
    row = conn.execute(
        "SELECT sr.title AS url, t.created_at FROM ("
        "  SELECT source_reference_id, created_at FROM product_fact WHERE brand_id = ? AND product_id = ?"
        "  UNION ALL"
        "  SELECT source_reference_id, created_at FROM product_economics WHERE brand_id = ? AND product_id = ?"
        ") t JOIN source_reference sr ON sr.id = t.source_reference_id"
        " WHERE sr.title LIKE 'http%' ORDER BY t.created_at DESC LIMIT 1",
        (brand_id, product_id, brand_id, product_id),
    ).fetchone()
    return row["url"] if row else None


def create_pending_product_economics(conn: sqlite3.Connection, brand_id: str, product_id: str, *,
                                      actor: str, selling_price: float, currency: str,
                                      source_reference_id: Optional[str]) -> dict:
    """AI 快掃抓到售價、這個產品目前完全沒有經濟數字列時才呼叫——建一筆 pending，
    固定成本／單位變動成本／運費留白，等使用者到「更新數字」補齊或直接一鍵確認。"""
    _require(currency, "product_economics.currency 為必填")
    _require(actor, "actor 為必填")
    ts = now_iso()
    row = {
        "id": new_id("pec"), "product_id": product_id, "brand_id": brand_id,
        "selling_price": selling_price, "fixed_cost": None, "unit_variable_cost": None,
        "shipping_cost": None, "currency": currency, "cpa_roas_basis": None,
        "effective_from": None, "effective_to": None, "status": "pending",
        "source_reference_id": source_reference_id, "confirmed_by": None, "confirmed_at": None,
        "created_at": ts, "updated_at": ts,
    }
    conn.execute(
        "INSERT INTO product_economics (id, product_id, brand_id, selling_price, fixed_cost, "
        "unit_variable_cost, shipping_cost, currency, cpa_roas_basis, effective_from, effective_to, "
        "status, source_reference_id, confirmed_by, confirmed_at, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (row["id"], row["product_id"], row["brand_id"], row["selling_price"], row["fixed_cost"],
         row["unit_variable_cost"], row["shipping_cost"], row["currency"], row["cpa_roas_basis"],
         row["effective_from"], row["effective_to"], row["status"], row["source_reference_id"],
         row["confirmed_by"], row["confirmed_at"], row["created_at"], row["updated_at"]),
    )
    write_audit(conn, brand_id=brand_id, entity_type="product_economics", entity_id=row["id"],
                action="create", actor=actor, before=None, after=row)
    conn.commit()
    return row


def confirm_product_economics(conn: sqlite3.Connection, brand_id: str, product_id: str, *,
                                confirmed_by: str, actor: str) -> dict:
    """待確認經濟數字的一鍵確認（比照 confirm_product_fact 的最小版）：只翻狀態，
    不動欄位內容——欄位若還沒補齊，使用者仍可之後用「更新數字」補上。"""
    _require(confirmed_by, "confirmed_by 為必填")
    _require(actor, "actor 為必填")
    before = get_product_economics(conn, brand_id, product_id)
    if before is None:
        raise ValueError(f"找不到產品經濟數字：{product_id}")
    ts = now_iso()
    conn.execute(
        "UPDATE product_economics SET status = 'confirmed', confirmed_by = ?, confirmed_at = ?, "
        "updated_at = ? WHERE id = ?",
        (confirmed_by, ts, ts, before["id"]),
    )
    after = get_product_economics(conn, brand_id, product_id)
    write_audit(conn, brand_id=brand_id, entity_type="product_economics", entity_id=before["id"],
                action="confirm", actor=actor, before=before, after=after)
    conn.commit()
    return after


# ---------------------------------------------------------------------------
# Rule
# ---------------------------------------------------------------------------

def create_rule(conn: sqlite3.Connection, brand_id: str, *, actor: str, rule_type: str, content: str,
                 severity: str, product_id: Optional[str] = None,
                 source_reference_id: Optional[str] = None) -> dict:
    _require(rule_type, "rule.rule_type 為必填")
    _require(content, "rule.content 為必填")
    _require(actor, "actor 為必填")
    if severity not in ("hard", "soft"):
        raise ValueError("rule.severity 只能是 hard 或 soft")
    rule_id = new_id("rul")
    ts = now_iso()
    row = {
        "id": rule_id, "brand_id": brand_id, "product_id": product_id, "rule_type": rule_type,
        "content": content, "severity": severity, "status": "active",
        "source_reference_id": source_reference_id, "created_at": ts, "updated_at": ts,
    }
    conn.execute(
        "INSERT INTO rule (id, brand_id, product_id, rule_type, content, severity, status, "
        "source_reference_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (row["id"], row["brand_id"], row["product_id"], row["rule_type"], row["content"],
         row["severity"], row["status"], row["source_reference_id"], row["created_at"],
         row["updated_at"]),
    )
    if product_id:
        _bump_product_version(conn, brand_id, product_id)
    else:
        _bump_brand_version(conn, brand_id)
    write_audit(conn, brand_id=brand_id, entity_type="rule", entity_id=rule_id,
                action="create", actor=actor, before=None, after=row)
    conn.commit()
    return row


def get_rule(conn: sqlite3.Connection, brand_id: str, rule_id: str) -> Optional[dict]:
    return _row(conn.execute(
        "SELECT * FROM rule WHERE id = ? AND brand_id = ?", (rule_id, brand_id)).fetchone())


def update_rule(conn: sqlite3.Connection, brand_id: str, rule_id: str, *, actor: str,
                 rule_type: str, content: str, severity: str, product_id: Optional[str] = None,
                 source_reference_id: Optional[str] = None) -> dict:
    """編輯規則內容，比照 update_brand_fact：人工編輯直接生效（決策 0013）。"""
    _require(rule_type, "rule.rule_type 為必填")
    _require(content, "rule.content 為必填")
    _require(actor, "actor 為必填")
    if severity not in ("hard", "soft"):
        raise ValueError("rule.severity 只能是 hard 或 soft")
    before = get_rule(conn, brand_id, rule_id)
    if before is None:
        raise ValueError(f"找不到規則：{rule_id}")
    ts = now_iso()
    conn.execute(
        "UPDATE rule SET rule_type = ?, content = ?, severity = ?, product_id = ?, "
        "source_reference_id = ?, updated_at = ? WHERE id = ? AND brand_id = ?",
        (rule_type, content, severity, product_id, source_reference_id, ts, rule_id, brand_id),
    )
    after = get_rule(conn, brand_id, rule_id)
    if product_id:
        _bump_product_version(conn, brand_id, product_id)
    else:
        _bump_brand_version(conn, brand_id)
    if before["product_id"] and before["product_id"] != product_id:
        _bump_product_version(conn, brand_id, before["product_id"])
    write_audit(conn, brand_id=brand_id, entity_type="rule", entity_id=rule_id,
                action="update", actor=actor, before=before, after=after,
                reason="人工編輯直接生效（決策 0013）")
    conn.commit()
    return after


def deactivate_rule(conn: sqlite3.Connection, brand_id: str, rule_id: str, *, actor: str) -> dict:
    """停用規則（GitHub issue #56，決策 0030）：把 `rule.status` 改為非 active 但保留該列，
    不同於 `delete_rule`（硬刪）與 `update_rule`（不碰 status）——兩者都接不住「下架但留紀錄」。
    停用後 `list_rules_for_brand`／`list_rules_for_product` 的 `WHERE status = 'active'`
    會自動排除這一列，不再進 `context_compiler` 組出的生成 prompt。
    屬新增程式碼、不是改 schema（`rule.status` 為無 CHECK 的 TEXT）。"""
    _require(actor, "actor 為必填")
    before = get_rule(conn, brand_id, rule_id)
    if before is None:
        raise ValueError(f"找不到規則：{rule_id}")
    ts = now_iso()
    conn.execute(
        "UPDATE rule SET status = 'inactive', updated_at = ? WHERE id = ? AND brand_id = ?",
        (ts, rule_id, brand_id),
    )
    after = get_rule(conn, brand_id, rule_id)
    if after["product_id"]:
        _bump_product_version(conn, brand_id, after["product_id"])
    else:
        _bump_brand_version(conn, brand_id)
    write_audit(conn, brand_id=brand_id, entity_type="rule", entity_id=rule_id,
                action="deactivate", actor=actor, before=before, after=after,
                reason="人工下架，不再進生成 prompt（決策 0030）")
    conn.commit()
    return after


def list_rules_for_brand(conn: sqlite3.Connection, brand_id: str) -> list:
    """品牌底下所有生效中的規則（含品牌整體與各產品專屬——品牌檔案頁要看到全部）。"""
    return _rows(conn.execute(
        "SELECT * FROM rule WHERE brand_id = ? AND status = 'active' ORDER BY created_at",
        (brand_id,),
    ))


def list_rules_for_product(conn: sqlite3.Connection, brand_id: str, product_id: str) -> list:
    """整個品牌的規則 + 本產品專屬規則（不含其他產品的專屬規則）。"""
    return _rows(conn.execute(
        "SELECT * FROM rule WHERE brand_id = ? AND status = 'active' "
        "AND (product_id IS NULL OR product_id = ?) ORDER BY created_at",
        (brand_id, product_id),
    ))


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------

def create_claim(conn: sqlite3.Connection, brand_id: str, *, actor: str, claim_text: str,
                  claim_type: str, product_id: Optional[str] = None,
                  evidence_source_reference_id: Optional[str] = None) -> dict:
    _require(claim_text, "claim.claim_text 為必填")
    _require(actor, "actor 為必填")
    if claim_type not in ("approved", "high_risk", "forbidden"):
        raise ValueError("claim.claim_type 只能是 approved / high_risk / forbidden")
    claim_id = new_id("clm")
    ts = now_iso()
    row = {
        "id": claim_id, "brand_id": brand_id, "product_id": product_id, "claim_text": claim_text,
        "claim_type": claim_type, "evidence_source_reference_id": evidence_source_reference_id,
        "status": "active", "created_at": ts, "updated_at": ts,
    }
    conn.execute(
        "INSERT INTO claim (id, brand_id, product_id, claim_text, claim_type, "
        "evidence_source_reference_id, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (row["id"], row["brand_id"], row["product_id"], row["claim_text"], row["claim_type"],
         row["evidence_source_reference_id"], row["status"], row["created_at"], row["updated_at"]),
    )
    if product_id:
        _bump_product_version(conn, brand_id, product_id)
    else:
        _bump_brand_version(conn, brand_id)
    write_audit(conn, brand_id=brand_id, entity_type="claim", entity_id=claim_id,
                action="create", actor=actor, before=None, after=row)
    conn.commit()
    return row


def get_claim(conn: sqlite3.Connection, brand_id: str, claim_id: str) -> Optional[dict]:
    return _row(conn.execute(
        "SELECT * FROM claim WHERE id = ? AND brand_id = ?", (claim_id, brand_id)).fetchone())


def update_claim(conn: sqlite3.Connection, brand_id: str, claim_id: str, *, actor: str,
                  claim_text: str, claim_type: str, product_id: Optional[str] = None,
                  evidence_source_reference_id: Optional[str] = None) -> dict:
    """編輯宣稱內容，比照 update_brand_fact：人工編輯直接生效（決策 0013）。"""
    _require(claim_text, "claim.claim_text 為必填")
    _require(actor, "actor 為必填")
    if claim_type not in ("approved", "high_risk", "forbidden"):
        raise ValueError("claim.claim_type 只能是 approved / high_risk / forbidden")
    before = get_claim(conn, brand_id, claim_id)
    if before is None:
        raise ValueError(f"找不到宣稱：{claim_id}")
    ts = now_iso()
    conn.execute(
        "UPDATE claim SET claim_text = ?, claim_type = ?, product_id = ?, "
        "evidence_source_reference_id = ?, updated_at = ? WHERE id = ? AND brand_id = ?",
        (claim_text, claim_type, product_id, evidence_source_reference_id, ts, claim_id, brand_id),
    )
    after = get_claim(conn, brand_id, claim_id)
    if product_id:
        _bump_product_version(conn, brand_id, product_id)
    else:
        _bump_brand_version(conn, brand_id)
    if before["product_id"] and before["product_id"] != product_id:
        _bump_product_version(conn, brand_id, before["product_id"])
    write_audit(conn, brand_id=brand_id, entity_type="claim", entity_id=claim_id,
                action="update", actor=actor, before=before, after=after,
                reason="人工編輯直接生效（決策 0013）")
    conn.commit()
    return after


def list_claims_for_brand(conn: sqlite3.Connection, brand_id: str) -> list:
    """品牌底下所有生效中的宣稱（含品牌整體與各產品專屬——品牌檔案頁要看到全部）。"""
    return _rows(conn.execute(
        "SELECT * FROM claim WHERE brand_id = ? AND status = 'active' ORDER BY created_at",
        (brand_id,),
    ))


def list_claims_for_product(conn: sqlite3.Connection, brand_id: str, product_id: str) -> list:
    """整個品牌的宣稱 + 本產品專屬宣稱（不含其他產品的專屬宣稱）。"""
    return _rows(conn.execute(
        "SELECT * FROM claim WHERE brand_id = ? AND status = 'active' "
        "AND (product_id IS NULL OR product_id = ?) ORDER BY created_at",
        (brand_id, product_id),
    ))


# ---------------------------------------------------------------------------
# Owned Channel
# ---------------------------------------------------------------------------

_CHANNEL_PLATFORM_DEFAULT = {"website": "web", "fb_page": "meta", "ig_account": "meta"}


def create_channel(conn: sqlite3.Connection, brand_id: str, *, actor: str, channel_type: str,
                    name: str, identifier: Optional[str] = None, status: str = "active",
                    platform: Optional[str] = None) -> dict:
    _require(channel_type, "owned_channel.channel_type 為必填")
    _require(name, "owned_channel.name 為必填")
    _require(actor, "actor 為必填")
    if status not in ("active", "inactive"):
        raise ValueError("owned_channel.status 只能是 active 或 inactive")
    resolved_platform = platform or _CHANNEL_PLATFORM_DEFAULT.get(channel_type, "web")
    channel_id = new_id("och")
    ts = now_iso()
    row = {
        "id": channel_id, "brand_id": brand_id, "channel_type": channel_type,
        "platform": resolved_platform, "name": name, "identifier": identifier, "status": status,
        "created_at": ts, "updated_at": ts,
    }
    conn.execute(
        "INSERT INTO owned_channel (id, brand_id, channel_type, platform, name, identifier, status, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (row["id"], row["brand_id"], row["channel_type"], row["platform"], row["name"],
         row["identifier"], row["status"], row["created_at"], row["updated_at"]),
    )
    write_audit(conn, brand_id=brand_id, entity_type="owned_channel", entity_id=channel_id,
                action="create", actor=actor, before=None, after=row)
    conn.commit()
    return row


def list_channels(conn: sqlite3.Connection, brand_id: str) -> list:
    return _rows(conn.execute(
        "SELECT * FROM owned_channel WHERE brand_id = ? ORDER BY created_at", (brand_id,)
    ))


# ---------------------------------------------------------------------------
# Source Reference（基本建立與查詢，無 UI 亦需可程式存取）
# ---------------------------------------------------------------------------

def create_source_reference(conn: sqlite3.Connection, brand_id: str, *, actor: str, title: str,
                             source_type: str, captured_date: str, url: Optional[str] = None,
                             published_date: Optional[str] = None, locale: Optional[str] = None,
                             note: Optional[str] = None) -> dict:
    _require(title, "source_reference.title 為必填")
    _require(source_type, "source_reference.source_type 為必填")
    _require(captured_date, "source_reference.captured_date 為必填")
    _require(actor, "actor 為必填")
    src_id = new_id("src")
    ts = now_iso()
    row = {
        "id": src_id, "brand_id": brand_id, "title": title, "url": url, "source_type": source_type,
        "published_date": published_date, "captured_date": captured_date, "locale": locale,
        "note": note, "created_at": ts,
    }
    conn.execute(
        "INSERT INTO source_reference (id, brand_id, title, url, source_type, published_date, "
        "captured_date, locale, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (row["id"], row["brand_id"], row["title"], row["url"], row["source_type"],
         row["published_date"], row["captured_date"], row["locale"], row["note"], row["created_at"]),
    )
    write_audit(conn, brand_id=brand_id, entity_type="source_reference", entity_id=src_id,
                action="create", actor=actor, before=None, after=row)
    conn.commit()
    return row


def get_source_reference(conn: sqlite3.Connection, brand_id: str,
                          source_reference_id: str) -> Optional[dict]:
    return _row(conn.execute(
        "SELECT * FROM source_reference WHERE id = ? AND brand_id = ?",
        (source_reference_id, brand_id),
    ).fetchone())


def list_source_references(conn: sqlite3.Connection, brand_id: str) -> list:
    return _rows(conn.execute(
        "SELECT * FROM source_reference WHERE brand_id = ? ORDER BY created_at DESC", (brand_id,)
    ))


# ---------------------------------------------------------------------------
# Official Asset（基本建立與查詢，無 UI 亦需可程式存取）
# ---------------------------------------------------------------------------

def create_official_asset(conn: sqlite3.Connection, brand_id: str, *, actor: str, asset_kind: str,
                           file_path: str, product_id: Optional[str] = None,
                           title: Optional[str] = None, usage_note: Optional[str] = None) -> dict:
    _require(asset_kind, "official_asset.asset_kind 為必填")
    _require(file_path, "official_asset.file_path 為必填")
    _require(actor, "actor 為必填")
    asset_id = new_id("oas")
    ts = now_iso()
    row = {
        "id": asset_id, "brand_id": brand_id, "product_id": product_id, "asset_kind": asset_kind,
        "file_path": file_path, "title": title, "usage_note": usage_note, "status": "active",
        "created_at": ts, "updated_at": ts,
    }
    conn.execute(
        "INSERT INTO official_asset (id, brand_id, product_id, asset_kind, file_path, title, "
        "usage_note, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (row["id"], row["brand_id"], row["product_id"], row["asset_kind"], row["file_path"],
         row["title"], row["usage_note"], row["status"], row["created_at"], row["updated_at"]),
    )
    write_audit(conn, brand_id=brand_id, entity_type="official_asset", entity_id=asset_id,
                action="create", actor=actor, before=None, after=row)
    conn.commit()
    return row


def list_official_assets(conn: sqlite3.Connection, brand_id: str) -> list:
    return _rows(conn.execute(
        "SELECT * FROM official_asset WHERE brand_id = ? ORDER BY created_at DESC", (brand_id,)
    ))


def get_official_asset(conn: sqlite3.Connection, brand_id: str, asset_id: str) -> Optional[dict]:
    return _row(conn.execute(
        "SELECT * FROM official_asset WHERE id = ? AND brand_id = ?", (asset_id, brand_id)
    ).fetchone())


def delete_official_asset(conn: sqlite3.Connection, brand_id: str, asset_id: str, *, actor: str) -> None:
    _delete_entity(conn, brand_id, "official_asset", asset_id, actor=actor, kind_label="官方素材")


# ---------------------------------------------------------------------------
# Strategy Hypothesis（基本建立與查詢，無 UI 亦需可程式存取）
# ---------------------------------------------------------------------------

def create_strategy_hypothesis(conn: sqlite3.Connection, brand_id: str, *, actor: str,
                                hypothesis_type: str, statement: str, created_by: str,
                                product_id: Optional[str] = None,
                                source_cycle_id: Optional[str] = None) -> dict:
    _require(hypothesis_type, "strategy_hypothesis.hypothesis_type 為必填")
    _require(statement, "strategy_hypothesis.statement 為必填")
    _require(created_by, "strategy_hypothesis.created_by 為必填")
    _require(actor, "actor 為必填")
    hyp_id = new_id("hyp")
    ts = now_iso()
    row = {
        "id": hyp_id, "brand_id": brand_id, "product_id": product_id,
        "hypothesis_type": hypothesis_type, "statement": statement, "status": "proposed",
        "source_cycle_id": source_cycle_id, "created_by": created_by, "expired_at": None,
        "created_at": ts, "updated_at": ts,
    }
    conn.execute(
        "INSERT INTO strategy_hypothesis (id, brand_id, product_id, hypothesis_type, statement, "
        "status, source_cycle_id, created_by, expired_at, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (row["id"], row["brand_id"], row["product_id"], row["hypothesis_type"], row["statement"],
         row["status"], row["source_cycle_id"], row["created_by"], row["expired_at"],
         row["created_at"], row["updated_at"]),
    )
    write_audit(conn, brand_id=brand_id, entity_type="strategy_hypothesis", entity_id=hyp_id,
                action="create", actor=actor, before=None, after=row)
    conn.commit()
    return row


def list_strategy_hypotheses(conn: sqlite3.Connection, brand_id: str) -> list:
    return _rows(conn.execute(
        "SELECT * FROM strategy_hypothesis WHERE brand_id = ? ORDER BY created_at DESC", (brand_id,)
    ))


def get_strategy_hypothesis(conn: sqlite3.Connection, brand_id: str, hypothesis_id: str) -> Optional[dict]:
    return _row(conn.execute(
        "SELECT * FROM strategy_hypothesis WHERE id = ? AND brand_id = ?", (hypothesis_id, brand_id)
    ).fetchone())


# 生命週期（docs/domain.md）：Proposed → Testing → Supported／Rejected／Inconclusive／Expired。
HYPOTHESIS_STATUSES = ("proposed", "testing", "supported", "rejected", "inconclusive", "expired")


def update_hypothesis_status(conn: sqlite3.Connection, brand_id: str, hypothesis_id: str, *,
                              status: str, actor: str) -> dict:
    """假設結案（GitHub issue #53）：只改 status，不碰其他欄位——`status` 為無 CHECK 的 TEXT，
    這是新增程式碼、不是改 schema。"""
    _require(status, "strategy_hypothesis.status 為必填")
    _require(actor, "actor 為必填")
    if status not in HYPOTHESIS_STATUSES:
        raise ValueError(f"未知的假設狀態：{status}")
    before = get_strategy_hypothesis(conn, brand_id, hypothesis_id)
    if before is None:
        raise ValueError("找不到這條策略假設")
    conn.execute(
        "UPDATE strategy_hypothesis SET status = ?, updated_at = ? WHERE id = ? AND brand_id = ?",
        (status, now_iso(), hypothesis_id, brand_id),
    )
    after = get_strategy_hypothesis(conn, brand_id, hypothesis_id)
    write_audit(conn, brand_id=brand_id, entity_type="strategy_hypothesis", entity_id=hypothesis_id,
                action="update_status", actor=actor, before=before, after=after)
    conn.commit()
    return after


# ---------------------------------------------------------------------------
# Brand Performance Baseline（基本建立與查詢，無 UI 亦需可程式存取）
# ---------------------------------------------------------------------------

def create_brand_performance_baseline(conn: sqlite3.Connection, brand_id: str, *, actor: str,
                                       metric: str, value: float, as_of_date: str, created_by: str,
                                       product_id: Optional[str] = None, unit: Optional[str] = None,
                                       basis_note: Optional[str] = None,
                                       source_cycle_id: Optional[str] = None,
                                       sample_note: Optional[str] = None) -> dict:
    _require(metric, "brand_performance_baseline.metric 為必填")
    _require(as_of_date, "brand_performance_baseline.as_of_date 為必填")
    _require(created_by, "brand_performance_baseline.created_by 為必填")
    _require(actor, "actor 為必填")
    if value is None:
        raise ValueError("brand_performance_baseline.value 為必填")
    baseline_id = new_id("bpb")
    ts = now_iso()
    row = {
        "id": baseline_id, "brand_id": brand_id, "product_id": product_id, "metric": metric,
        "value": value, "unit": unit, "basis_note": basis_note, "source_cycle_id": source_cycle_id,
        "sample_note": sample_note, "as_of_date": as_of_date, "created_by": created_by,
        "created_at": ts, "updated_at": ts,
    }
    conn.execute(
        "INSERT INTO brand_performance_baseline (id, brand_id, product_id, metric, value, unit, "
        "basis_note, source_cycle_id, sample_note, as_of_date, created_by, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (row["id"], row["brand_id"], row["product_id"], row["metric"], row["value"], row["unit"],
         row["basis_note"], row["source_cycle_id"], row["sample_note"], row["as_of_date"],
         row["created_by"], row["created_at"], row["updated_at"]),
    )
    write_audit(conn, brand_id=brand_id, entity_type="brand_performance_baseline",
                entity_id=baseline_id, action="create", actor=actor, before=None, after=row)
    conn.commit()
    return row


def list_brand_performance_baselines(conn: sqlite3.Connection, brand_id: str) -> list:
    return _rows(conn.execute(
        "SELECT * FROM brand_performance_baseline WHERE brand_id = ? ORDER BY as_of_date DESC",
        (brand_id,),
    ))


# ---------------------------------------------------------------------------
# Brand Report（顧問分析報告，決策 0017：只 INSERT、永不 UPDATE，歷史留著不做清單頁）
# ---------------------------------------------------------------------------

def create_brand_report(conn: sqlite3.Connection, brand_id: str, *, actor: str, model: str,
                         llm_task_id: Optional[str], brand_version: int,
                         source_fact_count: int, sections: dict) -> dict:
    _require(actor, "actor 為必填")
    _require(model, "brand_report.model 為必填")
    report_id = new_id("rpt")
    ts = now_iso()
    row = {
        "id": report_id, "brand_id": brand_id, "generated_at": ts, "generated_by": actor,
        "model": model, "llm_task_id": llm_task_id, "brand_version": brand_version,
        "source_fact_count": source_fact_count,
        "sections_json": json.dumps(sections, ensure_ascii=False),
    }
    conn.execute(
        "INSERT INTO brand_report (id, brand_id, generated_at, generated_by, model, llm_task_id, "
        "brand_version, source_fact_count, sections_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (row["id"], row["brand_id"], row["generated_at"], row["generated_by"], row["model"],
         row["llm_task_id"], row["brand_version"], row["source_fact_count"], row["sections_json"]),
    )
    write_audit(conn, brand_id=brand_id, entity_type="brand_report", entity_id=report_id,
                action="create", actor=actor,
                after={"model": model, "llm_task_id": llm_task_id, "source_fact_count": source_fact_count},
                reason="生成顧問分析報告")
    conn.commit()
    row["sections"] = sections
    return row


def get_latest_brand_report(conn: sqlite3.Connection, brand_id: str) -> Optional[dict]:
    row = _row(conn.execute(
        "SELECT * FROM brand_report WHERE brand_id = ? ORDER BY generated_at DESC, id DESC LIMIT 1",
        (brand_id,),
    ).fetchone())
    if row is not None:
        row["sections"] = json.loads(row["sections_json"])
    return row


# ---------------------------------------------------------------------------
# Customer Voice（顧客原話語料庫，GitHub issue #14，決策 0023 第 18a 條／0024 第 2 條）
# ---------------------------------------------------------------------------

def _with_extraction(row: Optional[dict]) -> Optional[dict]:
    if row is not None:
        row["extraction"] = json.loads(row["extraction_json"])
    return row


def create_customer_voice(conn: sqlite3.Connection, brand_id: str, *, actor: str, raw_text: str,
                           source_channel: str, source_type: str, extraction: list,
                           source_detail: Optional[str] = None,
                           llm_task_id: Optional[str] = None) -> dict:
    _require(raw_text, "customer_voice.raw_text 為必填")
    _require(source_channel, "customer_voice.source_channel 為必填")
    _require(actor, "actor 為必填")
    if source_type not in ("manual", "crawler"):
        raise ValueError("customer_voice.source_type 只能是 manual 或 crawler")
    cv_id = new_id("cvc")
    ts = now_iso()
    row = {
        "id": cv_id, "brand_id": brand_id, "raw_text": raw_text, "source_channel": source_channel,
        "source_detail": source_detail or None, "source_type": source_type, "status": "active",
        "extraction_json": json.dumps(extraction, ensure_ascii=False), "llm_task_id": llm_task_id,
        "created_by": actor, "created_at": ts, "updated_at": ts,
    }
    conn.execute(
        "INSERT INTO customer_voice (id, brand_id, raw_text, source_channel, source_detail, "
        "source_type, status, extraction_json, llm_task_id, created_by, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (row["id"], row["brand_id"], row["raw_text"], row["source_channel"], row["source_detail"],
         row["source_type"], row["status"], row["extraction_json"], row["llm_task_id"],
         row["created_by"], row["created_at"], row["updated_at"]),
    )
    _bump_brand_version(conn, brand_id)
    write_audit(conn, brand_id=brand_id, entity_type="customer_voice", entity_id=cv_id,
                action="create", actor=actor, before=None,
                after={**row, "extraction": extraction})
    conn.commit()
    return _with_extraction(row)


def get_customer_voice(conn: sqlite3.Connection, brand_id: str, cv_id: str) -> Optional[dict]:
    return _with_extraction(_row(conn.execute(
        "SELECT * FROM customer_voice WHERE id = ? AND brand_id = ?", (cv_id, brand_id)
    ).fetchone()))


def list_customer_voices(conn: sqlite3.Connection, brand_id: str,
                          status: Optional[str] = None) -> list:
    if status:
        rows = _rows(conn.execute(
            "SELECT * FROM customer_voice WHERE brand_id = ? AND status = ? ORDER BY created_at DESC",
            (brand_id, status),
        ))
    else:
        rows = _rows(conn.execute(
            "SELECT * FROM customer_voice WHERE brand_id = ? ORDER BY created_at DESC", (brand_id,)
        ))
    return [_with_extraction(r) for r in rows]


def set_customer_voice_status(conn: sqlite3.Connection, brand_id: str, cv_id: str, *,
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
    ts = now_iso()
    conn.execute(
        "UPDATE customer_voice SET status = ?, updated_at = ? WHERE id = ? AND brand_id = ?",
        (status, ts, cv_id, brand_id),
    )
    after = get_customer_voice(conn, brand_id, cv_id)
    write_audit(conn, brand_id=brand_id, entity_type="customer_voice", entity_id=cv_id,
                action="archive" if status == "archived" else "restore", actor=actor,
                before=before, after=after)
    conn.commit()
    return after


def delete_customer_voice(conn, brand_id: str, cv_id: str, *, actor: str) -> None:
    _delete_entity(conn, brand_id, "customer_voice", cv_id, actor=actor, kind_label="顧客原話")


# ---------------------------------------------------------------------------
# Learning Ledger（修憲落地 A3，決策 0037 第三節；docs/architecture-rules.md A1／A4）
#
# 遷自 app/ads——Brand Learning 依 docs/domain.md 是品牌永久層概念，不該只讓廣告分支
# 摸得到。append-only（鐵則 3 單向鐵律：學習只能補充事實層，永遠不得回寫或改寫事實層，
# 本模組的 brand_fact／product_fact 寫入函式在別處，這裡不得也不會碰它們——
# 見 app/tests/test_learning_ledger_unidirectional.py 的機器檢查）。
# 各分支自己的 repository 應包一層薄封裝呼叫這裡的公開函式，不得對本表下原生 SQL
# （A1：跨層一律走公開函式）；app/ads/repository.py 是目前唯一的例子。
# ---------------------------------------------------------------------------

def create_learning_ledger_entry(conn: sqlite3.Connection, brand_id: str, *, learning_text: str,
                                  applicability_scope: str, created_by: str, actor: str,
                                  source_track: str, product_id: Optional[str] = None,
                                  platform: Optional[str] = None,
                                  source_cycle_id: Optional[str] = None,
                                  source_reading_id: Optional[str] = None,
                                  source_hypothesis_id: Optional[str] = None,
                                  sample_size: Optional[str] = None,
                                  confidence: Optional[str] = None) -> dict:
    """已驗證的正面學習入帳（append-only，鐵則 3）：只新增，本層不提供 UPDATE／DELETE
    入口（下架走 deactivate_learning_ledger_entry，只改 expired，不改內容）。只收
    「經判讀驗證且經人確認」的條目——由呼叫端保證（決策 0030 第一節第 1 點）。

    `source_track` 必填、不給預設值（A4）：來源分支不該用猜的，呼叫端（或它自己模組的
    薄封裝，如 app/ads/repository.py）必須明確交代這筆學習是哪個分支學到的。
    """
    _require(learning_text, "learning_ledger.learning_text 為必填")
    _require(applicability_scope, "learning_ledger.applicability_scope 為必填")
    _require(created_by, "learning_ledger.created_by 為必填")
    _require(source_track, "learning_ledger.source_track 為必填")
    _require(actor, "actor 為必填")
    entry_id = new_id("lrn")
    ts = now_iso()
    row = {
        "id": entry_id, "brand_id": brand_id, "product_id": product_id, "platform": platform,
        "learning_text": learning_text, "applicability_scope": applicability_scope,
        "source_cycle_id": source_cycle_id, "source_reading_id": source_reading_id,
        "source_hypothesis_id": source_hypothesis_id, "sample_size": sample_size,
        "confidence": confidence, "needs_revalidation": 0, "expired": 0,
        "learned_at": ts, "created_by": created_by, "created_at": ts, "source_track": source_track,
    }
    conn.execute(
        "INSERT INTO learning_ledger (id, brand_id, product_id, platform, learning_text,"
        " applicability_scope, source_cycle_id, source_reading_id, source_hypothesis_id,"
        " sample_size, confidence, needs_revalidation, expired, learned_at, created_by,"
        " created_at, source_track) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (row["id"], row["brand_id"], row["product_id"], row["platform"], row["learning_text"],
         row["applicability_scope"], row["source_cycle_id"], row["source_reading_id"],
         row["source_hypothesis_id"], row["sample_size"], row["confidence"],
         row["needs_revalidation"], row["expired"], row["learned_at"], row["created_by"],
         row["created_at"], row["source_track"]),
    )
    write_audit(conn, brand_id=brand_id, entity_type="learning_ledger", entity_id=entry_id,
                action="create", actor=actor, before=None, after=row)
    conn.commit()
    return row


def list_learning_ledger(conn: sqlite3.Connection, brand_id: str, *,
                          include_expired: bool = False) -> list:
    """累積智慧頁讀取用：已驗證的正面學習清單（不分分支——頁面是給人看「這個品牌學到
    什麼」，不是給 prompt 組裝用；分支過濾只在 `list_learnings_for_prompt` 做，見下）。
    預設只列 `expired = 0`，跟 `list_learnings_for_prompt` 讀取端的過濾條件一致。"""
    sql = "SELECT * FROM learning_ledger WHERE brand_id = ?"
    if not include_expired:
        sql += " AND expired = 0"
    sql += " ORDER BY learned_at DESC"
    return _rows(conn.execute(sql, (brand_id,)))


def deactivate_learning_ledger_entry(conn: sqlite3.Connection, brand_id: str, entry_id: str, *,
                                      actor: str) -> dict:
    """下架一條已確認學習：把 `expired` 標成 1，不刪列、不改 `learning_text` 等內容欄位
    ——append-only 表不提供 UPDATE 指的是改寫學習內容本身；`expired` 是本表建表時就留給
    下架用的狀態欄，`list_learnings_for_prompt` 讀取端已過濾 `expired = 0`。"""
    if not actor:
        raise ValueError("actor 為必填")
    before = _row(conn.execute(
        "SELECT * FROM learning_ledger WHERE id = ? AND brand_id = ?", (entry_id, brand_id),
    ).fetchone())
    if before is None:
        raise ValueError(f"找不到這條學習紀錄：{entry_id}")
    conn.execute(
        "UPDATE learning_ledger SET expired = 1 WHERE id = ? AND brand_id = ?",
        (entry_id, brand_id),
    )
    after = _row(conn.execute(
        "SELECT * FROM learning_ledger WHERE id = ? AND brand_id = ?", (entry_id, brand_id),
    ).fetchone())
    write_audit(conn, brand_id=brand_id, entity_type="learning_ledger", entity_id=entry_id,
                action="deactivate", actor=actor, before=before, after=after,
                reason="人工下架，不再進生成 prompt（決策 0030）")
    conn.commit()
    return after


def list_learnings_for_prompt(conn: sqlite3.Connection, brand_id: str, *,
                               track: str, product_id: Optional[str] = None,
                               include_cross_track: bool = False) -> list:
    """`app/llm/context_compiler.py` 組 prompt 專用（A1：跨層一律走公開函式，不得對本表
    下原生 SQL）。A4 跨分支知識可見性：預設（`include_cross_track=False`）只回傳
    `source_track == track` 的條目；開啟後回傳全部分支，呼叫端須在 prompt 標示來源分支
    （見 context_compiler._learning_source_note）。"""
    _require(track, "list_learnings_for_prompt 的 track 為必填")
    if product_id is not None:
        sql = ("SELECT * FROM learning_ledger WHERE brand_id = ? AND expired = 0"
               " AND (product_id IS NULL OR product_id = ?)")
        params = [brand_id, product_id]
    else:
        sql = "SELECT * FROM learning_ledger WHERE brand_id = ? AND expired = 0 AND product_id IS NULL"
        params = [brand_id]
    if not include_cross_track:
        sql += " AND source_track = ?"
        params.append(track)
    sql += " ORDER BY learned_at"
    return _rows(conn.execute(sql, params))


def learning_ledger_entry_exists(conn: sqlite3.Connection, brand_id: str,
                                  *, product_id: Optional[str], learning_text: str) -> bool:
    """這個品牌、這個範圍（品牌整體或同一產品）下，同一句學習文字是否已經進過帳
    （修憲落地 G4，決策 0035 第三節第 8 點：`_ledger_confidence` 的「是否被獨立重測過」判斷用）。"""
    return conn.execute(
        "SELECT 1 FROM learning_ledger WHERE brand_id = ? AND product_id IS ?"
        " AND learning_text = ? LIMIT 1",
        (brand_id, product_id, learning_text),
    ).fetchone() is not None


def unlink_learning_ledger_reading(conn: sqlite3.Connection, reading_ids: list) -> None:
    """把 learning_ledger 指向這些判讀版次的 `source_reading_id` 解除關聯（設為 NULL），
    不刪列——append-only 表本身不受影響，只是來源指標失效。呼叫端（`app/ads`）負責算出
    要解除哪些 `performance_reading.id`：本函式刻意不自己下子查詢去查那張表，
    避免品牌永久層反向依賴分支專屬層的資料表（A1 單向地界）。"""
    if not reading_ids:
        return
    placeholders = ",".join("?" for _ in reading_ids)
    conn.execute(
        f"UPDATE learning_ledger SET source_reading_id = NULL"
        f" WHERE source_reading_id IN ({placeholders})",
        list(reading_ids),
    )


def unlink_learning_ledger_cycle(conn: sqlite3.Connection, cycle_id: str) -> None:
    """把 learning_ledger 指向這個檔期的 `source_cycle_id` 解除關聯（設為 NULL），不刪列
    ——學習是跨期累積的資產，來源檔期被刪不代表學習作廢。"""
    conn.execute(
        "UPDATE learning_ledger SET source_cycle_id = NULL WHERE source_cycle_id = ?",
        (cycle_id,),
    )


def mark_learning_ledger_needs_revalidation(conn: sqlite3.Connection, brand_id: str,
                                             entry_id: str) -> None:
    """單條標記「建議找機會重新驗證」（修憲落地 G4，決策 0035 第三節第 10 點）：只提醒、
    不擋路、不自動下架（決策 0013）。"""
    conn.execute(
        "UPDATE learning_ledger SET needs_revalidation = 1 WHERE id = ? AND brand_id = ?",
        (entry_id, brand_id),
    )


# ---------------------------------------------------------------------------
# 清理登記處（第 2 刀）：向 app.core.cleanup 登記本模組的清點／清除函式，
# 刪品牌時由登記處統一呼叫，本模組不必再被別人手寫死「記得通知它」。
# ---------------------------------------------------------------------------

cleanup.register("品牌智庫", count_brand=count_brand_data, delete_brand=delete_brand_data,
                 brand_tables={t for t, _ in BRAND_CHILD_TABLES},
                 count_product=count_product_data, delete_product=delete_product_data,
                 product_tables={t for t, _ in PRODUCT_CHILD_TABLES})
