"""Read-only, brand-level evidence from orders' existing owned tables.

The importer stores a default TWD, not source currency evidence. Never promote
that default to a confirmed currency or treat the website mirror as extra sales.
Only database aggregates leave this facade; customer fields are never selected.
"""

from datetime import date, datetime
from decimal import Decimal

from app.core.db import Conn


def _json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def review_evidence(conn: Conn, org_id: str, brand_id: str, *,
                    start: date, end: date) -> dict:
    """Aggregate collected rows in an inclusive window of at most 31 days.

Amounts are known-row subtotals, not evidence of complete shop coverage. Payment
means the imported financial_status explicitly says paid/refunded; pending,
authorized and partially paid do not establish the full amount received.
"""
    if type(start) is not date or type(end) is not date:
        raise ValueError("起訖日期必須是日期")
    if not 0 <= (end - start).days < 31:
        raise ValueError("查詢期間需為 1 至 31 天，且結束日期不得早於開始日期")
    if not org_id or not brand_id:
        raise ValueError("組織與品牌為必填")

    summary_row = conn.execute(
        """
        WITH scoped AS (
            SELECT total_amount - refunded_amount AS net_amount,
                   refunded_amount,
                   LOWER(BTRIM(COALESCE(order_status, ''))) IN
                       ('cancelled', 'canceled', 'voided', 'void') AS is_void,
                   LOWER(BTRIM(COALESCE(financial_status, ''))) AS payment,
                   NULLIF(UPPER(BTRIM(currency)), '') AS stored_currency,
                   updated_at
              FROM order_record
             WHERE org_id = %s AND brand_id = %s
               AND order_date BETWEEN %s AND %s
        ), classified AS (
            SELECT net_amount, refunded_amount, is_void, updated_at, stored_currency,
                   payment IN ('paid', 'refunded', 'partially_refunded') AS is_paid,
                   payment IN ('pending', 'unpaid', 'voided', 'void', 'cancelled',
                               'canceled', 'failed', 'authorized') AS is_unpaid,
                   payment IN ('refunded', 'partially_refunded') AS is_refunded
              FROM scoped
        )
        SELECT COUNT(*) AS count,
               COUNT(*) FILTER (WHERE NOT is_void) AS non_void_count,
               COUNT(*) FILTER (WHERE is_void) AS void_count,
               COUNT(*) FILTER (WHERE is_unpaid) AS unpaid_count,
               COUNT(*) FILTER (WHERE NOT is_paid AND NOT is_unpaid)
                   AS unknown_payment_count,
               COUNT(*) FILTER (WHERE refunded_amount > 0 OR is_refunded)
                   AS refunded_count,
               COUNT(*) FILTER (WHERE NOT is_void AND net_amount IS NULL)
                   AS unknown_amount_count,
               COUNT(*) FILTER (WHERE NOT is_void AND net_amount IS NOT NULL)
                   AS known_net_count,
               COUNT(*) FILTER (WHERE NOT is_void AND is_paid) AS paid_count,
               COUNT(*) FILTER (WHERE NOT is_void AND is_paid AND net_amount IS NOT NULL)
                   AS known_paid_net_count,
               CASE WHEN COUNT(DISTINCT COALESCE(stored_currency, '?')) <= 1
                    THEN SUM(net_amount) FILTER (WHERE NOT is_void) END AS order_net_amount,
               CASE WHEN COUNT(DISTINCT COALESCE(stored_currency, '?')) <= 1
                    THEN SUM(net_amount) FILTER (WHERE NOT is_void AND is_paid)
                    END AS paid_net_amount,
               ARRAY_AGG(DISTINCT stored_currency) FILTER (WHERE stored_currency IS NOT NULL)
                   AS reported_currencies,
               MAX(updated_at) AS latest_import_at
          FROM classified
        """,
        (org_id, brand_id, start, end),
    ).fetchone()
    assert summary_row is not None  # Ungrouped SQL aggregation always returns one row.
    summary = {key: _json_value(value) for key, value in summary_row.items()}
    summary["reported_currencies"] = summary["reported_currencies"] or []
    summary.update(currency=None, currency_basis="unknown", coverage="unknown")

    channel_rows = conn.execute(
        """
        WITH scoped AS (
            SELECT c.channel, c.source, c.currency,
                   CASE WHEN o.id IS NULL THEN c.revenue
                        WHEN o.total_amount IS NULL OR o.refunded_amount IS NULL THEN NULL
                        WHEN LOWER(BTRIM(COALESCE(o.order_status, ''))) IN
                            ('cancelled', 'canceled', 'voided', 'void') THEN 0
                        ELSE o.total_amount - o.refunded_amount END AS revenue,
                   o.id IS NOT NULL AS is_mirror
              FROM channel_revenue c
              LEFT JOIN order_record o ON c.channel = 'website'
                   AND o.org_id = c.org_id AND o.brand_id = c.brand_id
                   AND o.order_number = c.external_id
             WHERE c.org_id = %s AND c.brand_id = %s
               AND c.entry_date BETWEEN %s AND %s
        ), classified AS (
            SELECT channel, source, revenue,
                   CASE WHEN is_mirror THEN NULL
                        ELSE NULLIF(UPPER(BTRIM(currency)), '') END AS currency,
                   CASE WHEN is_mirror THEN 'order_mirror'
                        WHEN source = 'manual' THEN 'manual'
                        ELSE 'imported' END AS source_type
              FROM scoped
        )
        SELECT channel, source, source_type, currency, SUM(revenue) AS amount,
               COUNT(*) AS row_count,
               COUNT(*) FILTER (WHERE revenue IS NULL) AS unknown_amount_count
          FROM classified
         GROUP BY channel, source, source_type, currency
         ORDER BY channel, source, source_type, currency NULLS LAST
        """,
        (org_id, brand_id, start, end),
    ).fetchall()
    channels = [{key: _json_value(value) for key, value in row.items()} for row in channel_rows]
    return {
        "scope": "brand", "start": start.isoformat(), "end": end.isoformat(),
        "order_summary": summary, "channels": channels,
        "attribution": "unavailable",
        "limitations": [
            "僅列出已匯入且有日期的資料，無法確認是否涵蓋完整期間或全部訂單。",
            "訂單幣別缺乏來源證據；既有匯入預設幣別不代表原始交易幣別。",
            "訂單淨額只計入未作廢且金額與退款額都有記錄的列；缺值不當成零。",
            "付款淨額只計入明確已付款或已退款狀態的未作廢訂單，"
            "不是金流結算或銀行入帳證明；未付款與狀態不明的訂單另外計數。",
            "金額為有數值列的小計，缺值列不計；儲存幣別不一致時不加總訂單金額。",
            "官網同步帳與訂單可能是同一筆收入；各通路、幣別與來源分列，不能相加當總營收。",
            "通路金額未必有付款狀態或退款證據，手動登記與匯入資料也可能重疊。",
            "資料依訂單或通路記錄日期篩選，退款不是按實際退款發生日期彙整。",
            "這是品牌層級資料，無法歸因至個別廣告，不可用同日營收推算廣告收入。",
        ],
    }
