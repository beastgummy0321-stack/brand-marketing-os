"""app/orders/repository.py — 訂單／顧客資料存取層＋統計卡（GitHub issue #33）。

比照 app/ads/repository.py 慣例：一律以 brand_id 過濾、每次異動寫 audit_log。
訂單／顧客／SKU 成本掛品牌層，**不進**app/ads/repository.py 的 CYCLE_CASCADE_TABLES
（決策 0025 補遺第 1 點：新資料源開新表，訂單不因刪某一期廣告檔期而消失）。

同一張訂單重複匯入（歷史回填月份重疊、或同一個檔案重丟）以 (brand_id, order_number)
為準整批覆寫：EasyStore 匯出是「當下完整快照」不是逐筆事件，覆寫最新狀態才對——
跟 performance_snapshot 的 append-only 是不同性質的資料，不能照搬同一套規則。
"""

from datetime import date, timedelta

from app.brand_intelligence import repository as bi_repo
from app.core import cleanup
from app.core.audit import write_audit
from app.core.db import Conn, new_id, now_utc
from app.orders import identity as identity_mod

VOIDED_ORDER_STATUSES = {"cancelled", "canceled", "voided", "void"}

# 統計卡預設視窗：比照 app/ads/sync.py DEFAULT_LOOKBACK_DAYS 的「最近一段時間」慣例。
DEFAULT_STATS_WINDOW_DAYS = 30

# 回購倍數（GitHub issue #39，決策 0025 第 7 點）：程式常數，不走規則卡——
# 「90 天觀察期」與「30 位樣本門檻」是這個功能定義本身的一部分，不是使用者會想調的營運參數。
REPURCHASE_OBSERVATION_DAYS = 90
REPURCHASE_MIN_SAMPLE = 30

POLICY_TYPE_LABELS = {"discount": "折扣規則", "refund": "退款政策"}


def _rows(cursor) -> list:
    return [dict(r) for r in cursor.fetchall()]


def _row(cursor_row) -> dict | None:
    return dict(cursor_row) if cursor_row is not None else None


def _is_voided(order_status) -> bool:
    return (order_status or "").strip().lower() in VOIDED_ORDER_STATUSES


# ---------------------------------------------------------------------------
# 顧客
# ---------------------------------------------------------------------------

def _upsert_customer(conn: Conn, brand_id: str, identity_hash: str,
                     identity_type: str, order_date: str | None, ts: str, org_id: str) -> str:
    existing = conn.execute(
        "SELECT * FROM customer WHERE brand_id = %s AND identity_hash = %s",
        (brand_id, identity_hash),
    ).fetchone()
    if existing:
        # first_order_at 是 timestamptz；order_date 是匯入列截到日期的字串（見呼叫端
        # str(order_date)[:10]），比較前先把 first 也收斂成同一種「YYYY-MM-DD」字串
        # （02-3b：型別改了，比較基準要對齊，不能拿 str 跟 datetime 直接比）。
        first = existing["first_order_at"]
        first_date = first.date().isoformat() if first else None
        if order_date and (not first_date or order_date < first_date):
            conn.execute(
                "UPDATE customer SET first_order_at = %s, updated_at = %s WHERE id = %s",
                (order_date, ts, existing["id"]),
            )
        return existing["id"]
    customer_id = new_id("cus")
    conn.execute(
        "INSERT INTO customer (id, org_id, brand_id, identity_hash, identity_type, first_order_at,"
        " created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (customer_id, org_id, brand_id, identity_hash, identity_type, order_date, ts, ts),
    )
    return customer_id


# ---------------------------------------------------------------------------
# 匯入落庫（app/orders/importer.py 解析出來的訂單列在這裡寫進 DB）
# ---------------------------------------------------------------------------

def save_orders(conn: Conn, brand_id: str, rows: list, *,
                source: str, actor: str, result=None, import_batch_id: str | None = None):
    """把 importer 解析好的訂單列（含 items）落地。回傳 app.orders.importer.OrderImportResult。

    匯入前先跑一次雜湊一致性自檢（app.orders.identity.consistency_self_check）：
    正規化規則本身壞了要整批擋下，不是等匯完才發現同一個人被算成兩個顧客。
    """
    from app.orders.importer import OrderImportResult  # 延後匯入，避免與 importer 循環相依

    if not actor or not actor.strip():
        raise ValueError("actor 為必填")
    identity_mod.consistency_self_check()
    org_id = bi_repo.get_brand(conn, brand_id)["org_id"]

    result = result or OrderImportResult()
    ts = now_utc()
    batch_id = import_batch_id or f"orders_{ts}"

    for row in rows:
        order_number = (row.get("order_number") or "").strip() if row.get("order_number") else None
        if not order_number:
            continue
        order_date = row.get("order_date")
        order_date = str(order_date)[:10] if order_date else None

        identity_hash, identity_type = identity_mod.identity_key(
            billing_email=row.get("billing_email"), billing_phone=row.get("billing_phone"))
        customer_id = None
        if identity_hash:
            customer_id = _upsert_customer(conn, brand_id, identity_hash, identity_type,
                                           order_date, ts, org_id)

        existing = conn.execute(
            "SELECT id FROM order_record WHERE brand_id = %s AND order_number = %s",
            (brand_id, order_number),
        ).fetchone()
        if existing:
            order_id = existing["id"]
            conn.execute(
                "UPDATE order_record SET customer_id = %s, order_date = %s, total_amount = %s,"
                " refunded_amount = %s, financial_status = %s, fulfillment_status = %s,"
                " order_status = %s, voucher_code = %s, source = %s, import_batch_id = %s,"
                " updated_at = %s WHERE id = %s",
                (customer_id, order_date, row.get("total_amount"), row.get("refunded_amount"),
                 row.get("financial_status"), row.get("fulfillment_status"),
                 row.get("order_status"), row.get("voucher_code"), source, batch_id, ts,
                 order_id),
            )
            conn.execute("DELETE FROM order_item WHERE order_id = %s", (order_id,))
            result.orders_updated += 1
        else:
            order_id = new_id("ord")
            conn.execute(
                "INSERT INTO order_record (id, org_id, brand_id, customer_id, order_number, order_date,"
                " total_amount, refunded_amount, financial_status, fulfillment_status,"
                " order_status, voucher_code, currency, source, import_batch_id, created_at,"
                " updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (order_id, org_id, brand_id, customer_id, order_number, order_date,
                 row.get("total_amount"), row.get("refunded_amount"),
                 row.get("financial_status"), row.get("fulfillment_status"),
                 row.get("order_status"), row.get("voucher_code"), "TWD", source, batch_id,
                 ts, ts),
            )
            result.orders_imported += 1

        for item in row.get("items") or []:
            if item.get("sku") is None and item.get("item_price") is None and item.get("quantity") is None:
                continue
            conn.execute(
                "INSERT INTO order_item (id, org_id, brand_id, order_id, sku, item_price, quantity,"
                " created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (new_id("oit"), org_id, brand_id, order_id, item.get("sku"), item.get("item_price"),
                 item.get("quantity"), ts),
            )
            result.items_imported += 1

    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="order_record", entity_id=brand_id,
                action="import_orders", actor=actor,
                before=None, after={"source": source, "imported": result.orders_imported,
                                    "updated": result.orders_updated,
                                    "items": result.items_imported})
    conn.commit()
    return result


# ---------------------------------------------------------------------------
# 逐 SKU 成本登記（選填；沒登記就誠實顯示「不知道成本」，不假裝算得出毛利）
# ---------------------------------------------------------------------------

def list_sku_costs(conn: Conn, brand_id: str) -> list:
    return _rows(conn.execute(
        "SELECT * FROM sku_cost WHERE brand_id = %s ORDER BY sku", (brand_id,)
    ))


def set_sku_cost(conn: Conn, brand_id: str, sku: str, unit_cost: float, *,
                 actor: str, today: str | None = None) -> dict:
    if not sku or not sku.strip():
        raise ValueError("SKU 為必填")
    if unit_cost is None or unit_cost < 0:
        raise ValueError("單位成本要是不小於 0 的數字")
    if not actor or not actor.strip():
        raise ValueError("actor 為必填")
    sku = sku.strip()
    ts = now_utc()
    org_id = bi_repo.get_brand(conn, brand_id)["org_id"]
    existing = conn.execute(
        "SELECT id FROM sku_cost WHERE brand_id = %s AND sku = %s", (brand_id, sku)
    ).fetchone()
    if existing:
        cost_id = existing["id"]
        conn.execute("UPDATE sku_cost SET unit_cost = %s, updated_at = %s WHERE id = %s",
                     (unit_cost, ts, cost_id))
    else:
        cost_id = new_id("skc")
        conn.execute(
            "INSERT INTO sku_cost (id, org_id, brand_id, sku, unit_cost, updated_at)"
            " VALUES (%s, %s, %s, %s, %s, %s)", (cost_id, org_id, brand_id, sku, unit_cost, ts),
        )
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="sku_cost", entity_id=cost_id,
                action="set", actor=actor, before=None, after={"sku": sku, "unit_cost": unit_cost})
    _bump_sku_cost_version(conn, brand_id, sku, unit_cost, actor=actor, today=today, org_id=org_id)
    conn.commit()
    return {"id": cost_id, "sku": sku, "unit_cost": unit_cost}


# ---------------------------------------------------------------------------
# SKU 成本版本歷史（issue #37）：sku_cost 上面是「現行值」，這裡另存生效區間版本，
# 讓判讀快照（app/ads/settlement.py）能引用「當時生效」的那一版——成本回改
# 不會偷改到歷史判讀引用的數字（決策 0025 審查補遺 C）。
# ---------------------------------------------------------------------------

def _bump_sku_cost_version(conn: Conn, brand_id: str, sku: str, unit_cost: float,
                            *, actor: str, org_id: str, today: str | None = None) -> dict:
    today = today or date.today().isoformat()
    prev = conn.execute(
        "SELECT * FROM sku_cost_version WHERE brand_id = %s AND sku = %s AND valid_to IS NULL",
        (brand_id, sku),
    ).fetchone()
    # prev["unit_cost"] 是 numeric(Decimal)；跟浮點數 unit_cost 直接 == 比較幾乎永遠不等
    # （Decimal('1.10') == 1.1 是 False），先轉 float 才是真的在比數值有沒有變（02-3b）。
    if prev is not None and float(prev["unit_cost"]) == unit_cost:
        return dict(prev)  # 成本沒變動，不長新版
    ts = now_utc()
    version = (prev["version"] if prev else 0) + 1
    if prev is not None:
        conn.execute("UPDATE sku_cost_version SET valid_to = %s WHERE id = %s", (today, prev["id"]))
    version_id = new_id("skv")
    conn.execute(
        "INSERT INTO sku_cost_version (id, org_id, brand_id, sku, version, unit_cost, valid_from,"
        " valid_to, created_by, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, %s, %s)",
        (version_id, org_id, brand_id, sku, version, unit_cost, today, actor, ts),
    )
    return {"id": version_id, "brand_id": brand_id, "sku": sku, "version": version,
            "unit_cost": unit_cost, "valid_from": today, "valid_to": None}


def list_effective_sku_costs(conn: Conn, brand_id: str) -> list:
    """每個 SKU 目前生效中的成本版本（valid_to IS NULL）。判讀快照凍結當下引用這份清單，
    不直接讀 sku_cost 現行值——現行值之後若被覆寫，快照引用的版本 id 仍指向這裡的舊列。"""
    rows = _rows(conn.execute(
        "SELECT * FROM sku_cost_version WHERE brand_id = %s AND valid_to IS NULL ORDER BY sku",
        (brand_id,),
    ))
    # unit_cost 是 numeric（Decimal）；讀取端單一收口轉型（同 _with_float_budget 既有
    # 模式），呼叫端 settlement.py 把它 str() 進 reading_snapshot_input.value 才不會
    # 印出 "10.00" 這種帶零填充尾數的字串（02-3c）。
    for row in rows:
        if row.get("unit_cost") is not None:
            row["unit_cost"] = float(row["unit_cost"])
    return rows


# ---------------------------------------------------------------------------
# 統計卡（5 項，issue #33）：確定性計算，不經 LLM（決策 0016 硬性原則 4）
# ---------------------------------------------------------------------------

def sku_margins(conn: Conn, brand_id: str, *, since: str | None = None,
                until: str | None = None) -> list:
    """逐 SKU 營收／毛利。沒登記單位成本的 SKU，margin 回 None（誠實顯示不知道成本）。"""
    voided_placeholders = ",".join("%s" for _ in VOIDED_ORDER_STATUSES)
    sql = (
        "SELECT oi.sku, SUM(oi.item_price * oi.quantity) revenue, SUM(oi.quantity) quantity"
        " FROM order_item oi JOIN order_record o ON o.id = oi.order_id"
        f" WHERE oi.brand_id = %s AND oi.sku IS NOT NULL AND oi.sku != ''"
        f" AND (o.order_status IS NULL OR LOWER(o.order_status) NOT IN ({voided_placeholders}))"
    )
    params: list = [brand_id, *VOIDED_ORDER_STATUSES]
    if since:
        sql += " AND o.order_date >= %s"
        params.append(since)
    if until:
        sql += " AND o.order_date <= %s"
        params.append(until)
    sql += " GROUP BY oi.sku ORDER BY revenue DESC"
    rows = _rows(conn.execute(sql, params))

    # unit_cost 是 numeric(Decimal)；下面跟 SUM(...) 算出來的 float 營收混算，讀取端先轉
    # float（02-3b：Decimal 不能直接跟 float 做算術）。
    costs = {r["sku"]: float(r["unit_cost"]) for r in conn.execute(
        "SELECT sku, unit_cost FROM sku_cost WHERE brand_id = %s", (brand_id,))}
    for row in rows:
        unit_cost = costs.get(row["sku"])
        row["unit_cost"] = unit_cost
        row["margin"] = (round(row["revenue"] - unit_cost * (row["quantity"] or 0), 2)
                         if unit_cost is not None else None)
    return rows


def stats(conn: Conn, brand_id: str, *, since: str | None = None,
         until: str | None = None, today: str | None = None) -> dict:
    """五項統計卡：實收營收（扣退款棄單）、新舊客、客單價、回購率、逐 SKU 毛利。

    預設視窗＝最近 30 天。任何指標的分母是 0 時回 None，不回 0 或假造——
    「沒得算」跟「等於 0」是兩件事（鐵則 16，比照 app/ads/performance.py compute_kpis）。
    完全沒有歷史資料時 has_history=False，畫面顯示「累積中」而不是報錯（決策 0025 第 6 點）。
    """
    today = today or date.today().isoformat()
    until = until or today
    since = since or (date.fromisoformat(until) - timedelta(days=DEFAULT_STATS_WINDOW_DAYS)).isoformat()

    orders = _rows(conn.execute(
        "SELECT * FROM order_record WHERE brand_id = %s AND order_date >= %s AND order_date <= %s",
        (brand_id, since, until),
    ))
    valid_orders = [o for o in orders if not _is_voided(o["order_status"])]

    order_count = len(valid_orders)
    # BUG 修復（route=C 02-3c）：total_amount/refunded_amount 是 numeric 欄位，sum() 出來
    # 是 Decimal；讀取端單一收口轉 float，下游（app/dashboard/repository.py _roas()）
    # 才不會回傳跟自己宣告型別（Optional[float]）不符的 Decimal。
    net_revenue = (float(sum((o["total_amount"] or 0) - (o["refunded_amount"] or 0)
                            for o in valid_orders)) if orders else None)
    average_order_value = (round(net_revenue / order_count, 2)
                           if (net_revenue is not None and order_count) else None)

    customer_ids = {o["customer_id"] for o in valid_orders if o["customer_id"]}
    new_customers = existing_customers = 0
    for cid in customer_ids:
        customer = conn.execute(
            "SELECT first_order_at FROM customer WHERE id = %s", (cid,)
        ).fetchone()
        # BUG 修復（route=C 02-3c，app/orders/repository.py:311）：first_order_at 是
        # timestamptz 欄位讀回來的 datetime，since 是純日期字串（"YYYY-MM-DD"）；
        # SQLite 兩邊都是字串才比得起來，Postgres 型別不同直接 TypeError。比較前
        # 先收斂成同一種「日期」再比。
        if (customer and customer["first_order_at"]
                and customer["first_order_at"].date() >= date.fromisoformat(since)):
            new_customers += 1
        else:
            existing_customers += 1

    repurchase_rate = None
    if customer_ids:
        repeaters = sum(
            1 for cid in customer_ids
            if conn.execute(
                "SELECT COUNT(*) c FROM order_record WHERE brand_id = %s AND customer_id = %s",
                (brand_id, cid),
            ).fetchone()["c"] >= 2
        )
        repurchase_rate = round(repeaters / len(customer_ids), 4)

    has_history = conn.execute(
        "SELECT 1 FROM order_record WHERE brand_id = %s LIMIT 1", (brand_id,)
    ).fetchone() is not None

    return {
        "since": since,
        "until": until,
        "has_history": has_history,
        "order_count": order_count,
        "net_revenue": net_revenue,
        "average_order_value": average_order_value,
        "new_customers": new_customers,
        "existing_customers": existing_customers,
        "repurchase_rate": repurchase_rate,
        "repurchase_sample_size": len(customer_ids),
        "sku_margins": sku_margins(conn, brand_id, since=since, until=until),
    }


# ---------------------------------------------------------------------------
# 回購倍數（GitHub issue #39）：首單打平線之外，另算一條「含 90 天回購」的實質倍數，
# 供 app/ads/reading.py 把打平線放寬——回購越強，越不需要靠首單就打平。
# ---------------------------------------------------------------------------

def repurchase_multiplier(conn: Conn, brand_id: str, *,
                          today: str | None = None) -> dict:
    """回購倍數＝滿 90 天觀察期顧客「90 天內淨營收加總」除以「首單淨營收加總」。

    只算 first_order_at 已經滿 90 天的顧客（觀察期還沒跑完的顧客不算，避免統計未完成的
    視窗）；樣本數低於 REPURCHASE_MIN_SAMPLE 就回 multiplier=None——不能拿小樣本冒充規律
    （決策 0025 第 7 點）。首單淨營收為 0 或負值（全額退款）的顧客不計入分母，避免除以 0。
    """
    today = today or date.today().isoformat()
    cutoff = (date.fromisoformat(today) - timedelta(days=REPURCHASE_OBSERVATION_DAYS)).isoformat()
    customers = _rows(conn.execute(
        "SELECT id, first_order_at FROM customer WHERE brand_id = %s AND first_order_at IS NOT NULL"
        " AND first_order_at <= %s", (brand_id, cutoff),
    ))

    first_total = 0.0
    window_total = 0.0
    sample = 0
    for cust in customers:
        window_end = (cust["first_order_at"].date()
                      + timedelta(days=REPURCHASE_OBSERVATION_DAYS)).isoformat()
        orders = _rows(conn.execute(
            "SELECT total_amount, refunded_amount, order_status FROM order_record"
            " WHERE brand_id = %s AND customer_id = %s AND order_date >= %s AND order_date <= %s"
            " ORDER BY order_date", (brand_id, cust["id"], cust["first_order_at"], window_end),
        ))
        valid = [o for o in orders if not _is_voided(o["order_status"])]
        if not valid:
            continue
        # BUG 修復（route=C 02-3c，app/orders/repository.py:384）：total_amount/
        # refunded_amount 是 numeric 欄位讀回來的 Decimal；first_total/window_total 是
        # float 起手（0.0），float += Decimal 直接 TypeError。讀取端就近轉 float。
        first_net = float((valid[0]["total_amount"] or 0) - (valid[0]["refunded_amount"] or 0))
        if first_net <= 0:
            continue
        window_net = float(sum((o["total_amount"] or 0) - (o["refunded_amount"] or 0) for o in valid))
        first_total += first_net
        window_total += window_net
        sample += 1

    insufficient = sample < REPURCHASE_MIN_SAMPLE
    multiplier = (round(window_total / first_total, 4)
                 if (first_total and not insufficient) else None)
    return {"multiplier": multiplier, "sample_size": sample, "insufficient_sample": insufficient}


# ---------------------------------------------------------------------------
# 折扣／退款口徑變更紀錄（GitHub issue #39，決策 0025 第 4 點）：跨口徑比較要標「不同尺」，
# 這裡只負責記變更日與描述，「哪次比較該標不同尺」的判斷留給 app/ads/reading.py。
# ---------------------------------------------------------------------------

def record_policy_change(conn: Conn, brand_id: str, *, policy_type: str,
                         changed_at: str, description: str, actor: str) -> dict:
    if policy_type not in POLICY_TYPE_LABELS:
        raise ValueError(f"不認得的口徑類型：{policy_type}")
    if not changed_at or not changed_at.strip():
        raise ValueError("變更日為必填")
    if not description or not description.strip():
        raise ValueError("變更說明為必填")
    if not actor or not actor.strip():
        raise ValueError("actor 為必填")
    ts = now_utc()
    org_id = bi_repo.get_brand(conn, brand_id)["org_id"]
    row_id = new_id("pcl")
    conn.execute(
        "INSERT INTO policy_change_log (id, org_id, brand_id, policy_type, changed_at, description,"
        " created_by, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (row_id, org_id, brand_id, policy_type, changed_at.strip(), description.strip(), actor, ts),
    )
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="policy_change_log", entity_id=row_id,
                action="create", actor=actor,
                before=None, after={"policy_type": policy_type, "changed_at": changed_at,
                                    "description": description})
    conn.commit()
    return {"id": row_id, "policy_type": policy_type, "changed_at": changed_at,
            "description": description}


def list_policy_changes(conn: Conn, brand_id: str, *,
                        until: str | None = None) -> list:
    sql = "SELECT * FROM policy_change_log WHERE brand_id = %s"
    params: list = [brand_id]
    if until:
        sql += " AND changed_at <= %s"
        params.append(until)
    sql += " ORDER BY changed_at DESC"
    rows = _rows(conn.execute(sql, params))
    # BUG 修復（route=C 02-3c，NEW）：changed_at 只曾經寫入純日期字串（record_policy_
    # change() 呼叫端只填 "YYYY-MM-DD"），但欄位型別是 timestamptz；Postgres 讀回來是
    # 帶時分秒的 datetime（"2026-08-01T00:00:00+00:00"），對外 API 回應變出多餘的時間
    # 部分——只留日期，符合原本寫入的語意。
    for row in rows:
        if row["changed_at"] is not None:
            row["changed_at"] = row["changed_at"].date().isoformat()
    return rows


def list_orders(conn: Conn, brand_id: str, limit: int = 50,
                offset: int = 0) -> list:
    return _rows(conn.execute(
        "SELECT * FROM order_record WHERE brand_id = %s ORDER BY order_date DESC, created_at DESC"
        " LIMIT %s OFFSET %s", (brand_id, limit, offset),
    ))


def count_orders(conn: Conn, brand_id: str) -> int:
    """品牌全部訂單筆數，供唯讀清單 API 計算分頁總數。"""
    return conn.execute(
        "SELECT COUNT(*) AS n FROM order_record WHERE brand_id = %s", (brand_id,)
    ).fetchone()["n"]


# ---------------------------------------------------------------------------
# 配碼歸因（GitHub issue #35）：app/ads/codes.py 依此清單比對 voucher_code，
# 分類毛歸因／淨歸因／排除／自然。這裡只給資料，分類規則屬於 ads 模組
# （鐵則 7：模組間走明確介面，不跨模組直接 join 對方的表）。
# ---------------------------------------------------------------------------

def list_orders_in_range(conn: Conn, brand_id: str, since: str,
                         until: str) -> list:
    """本期日期範圍內、非作廢的訂單（含 voucher_code／attribution_override），供歸因分類用。"""
    rows = _rows(conn.execute(
        "SELECT * FROM order_record WHERE brand_id = %s AND order_date >= %s AND order_date <= %s"
        " ORDER BY order_date", (brand_id, since, until),
    ))
    return [o for o in rows if not _is_voided(o["order_status"])]


# 已結案的出貨狀態值：目前只認 EasyStore 真實匯出檔驗證過的 'fulfilled'（決策 0025
# 使用者真實 Export_Orders 檔已驗證的欄名／格式）。其餘值或空值一律算「未結案」，
# 不誤判成已結——貨到付款＋超商取貨型態下，還沒出貨完成的訂單都可能在期末後才棄單退款
# （決策 0025 判讀節奏第 5 點）；之後遇到別的平台或別的狀態字串再補，不先猜（鐵則：
# 認不出就誠實說，不硬猜）。
SETTLED_FULFILLMENT_STATUSES = {"fulfilled"}


def unsettled_order_ratio(conn: Conn, brand_id: str, since: str,
                          until: str) -> float | None:
    """這段期間的訂單裡，還沒結案（出貨／取貨完成）的佔比。期末暫定判讀用這個標注
    「未結案訂單佔 X%，此為暫定結論」（決策 0025 判讀節奏第 5 點）。

    分母是非作廢訂單筆數，是 0 時回 None——沒有訂單資料就是沒得算，不是 0%（鐵則 16）。
    """
    orders = list_orders_in_range(conn, brand_id, since, until)
    if not orders:
        return None
    unsettled = sum(
        1 for o in orders
        if (o["fulfillment_status"] or "").strip().lower() not in SETTLED_FULFILLMENT_STATUSES
    )
    return round(unsettled / len(orders), 4)


def set_attribution_override(conn: Conn, brand_id: str, order_id: str,
                             excluded: bool, *, actor: str) -> dict:
    """訂單手動標記「非廣告來源」／取消標記。淨歸因看這個欄位排除，毛歸因不受影響。"""
    if not actor or not actor.strip():
        raise ValueError("actor 為必填")
    before = conn.execute(
        "SELECT * FROM order_record WHERE brand_id = %s AND id = %s", (brand_id, order_id)
    ).fetchone()
    if before is None:
        raise ValueError("找不到這筆訂單")
    value = "excluded" if excluded else None
    ts = now_utc()
    org_id = bi_repo.get_brand(conn, brand_id)["org_id"]
    conn.execute(
        "UPDATE order_record SET attribution_override = %s, updated_at = %s WHERE id = %s",
        (value, ts, order_id),
    )
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="order_record", entity_id=order_id,
                action="set_attribution_override", actor=actor,
                before={"attribution_override": before["attribution_override"]},
                after={"attribution_override": value})
    conn.commit()
    return {"id": order_id, "attribution_override": value}


# ---------------------------------------------------------------------------
# 刪品牌（第 5 刀「訂單模組接上清理登記處」）
#
# 這 9 張表都掛 brand_id，彼此之間、跟本模組其他表之間都沒有真的外鍵約束
# （order_item.order_id、order_record.customer_id 都只是欄位，schema 沒下 REFERENCES）。
# 票 02-3a：cycle_shopee_code.campaign_cycle_id -> campaign_cycle(id) 這條唯一的跨模組
# 外鍵已在 02-2 拿掉（集裝箱憲章禁止跨模組外鍵，見
# .scratch/saas/tickets/02-2-type-decisions.md 第 6 點），改成不帶 REFERENCES 的純
# TEXT 欄位，跨模組清理順序從此不重要，不必再靠 PRAGMA defer_foreign_keys 之類的機制。
BRAND_CASCADE_TABLES = (
    ("customer", "顧客"),
    ("order_record", "訂單"),
    ("order_item", "訂單品項"),
    ("sku_cost", "SKU 成本"),
    ("sku_cost_version", "SKU 成本版本歷史"),
    ("pharmacy_batch", "藥局出貨批次"),
    ("shopee_report_row", "蝦皮賣家中心報表"),
    ("policy_change_log", "折扣／退款口徑變更紀錄"),
    ("cycle_shopee_code", "蝦皮期別配碼與回收數"),
)


def count_brand_data(conn: Conn, brand_id: str) -> list:
    """刪品牌前的清點（比照 app/ads/repository.py 的 count_brand_data），給刪除確認頁
    列出「按下去會消失什麼」。跟 delete_brand_data 讀同一份 BRAND_CASCADE_TABLES——
    「清點清一份、清除清另一份，兩邊不同步」正是這整串 bug 的根因。"""
    counts = []
    for table, label in BRAND_CASCADE_TABLES:
        n = conn.execute(
            f"SELECT COUNT(*) AS c FROM {table} WHERE brand_id = %s", (brand_id,)
        ).fetchone()["c"]
        if n:
            counts.append((label, n))
    return counts


def delete_brand_data(conn: Conn, brand_id: str) -> dict:
    """清掉本模組掛在該品牌下的資料（BRAND_CASCADE_TABLES 這 9 張表），登記進
    app.core.cleanup 給 delete_brand() 呼叫用。只下 DELETE、不 commit、不 rollback
    （Q4 單一交易、全有全無，commit 與 rollback 統一在 brand_intelligence.delete_brand()）。
    """
    counts = dict(count_brand_data(conn, brand_id))
    for table, _label in BRAND_CASCADE_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE brand_id = %s", (brand_id,))
    return counts


# ---------------------------------------------------------------------------
# 清理登記處（第 2 刀）：向 app.core.cleanup 登記本模組的清點／清除函式，刪品牌時
# 由登記處統一呼叫，本模組不必再被別人手寫死「記得通知它」。
# ---------------------------------------------------------------------------

cleanup.register("訂單", count_brand=count_brand_data, delete_brand=delete_brand_data,
                 brand_tables={t for t, _ in BRAND_CASCADE_TABLES},
                 count_product=None, delete_product=None, product_tables=frozenset())
