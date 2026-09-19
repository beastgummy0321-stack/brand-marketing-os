"""Brand-only evidence: collected amounts, uncertainty, mirrors and isolation."""

import json
from datetime import date

import pytest

from app.brand_intelligence import repository as brands
from app.core.db import DEV_ORG_ID, current, new_id
from app.orders import repository as orders
from app.orders import review_evidence
from app.orders.channel import record_channel_entry

START = date(2026, 9, 1)
END = date(2026, 9, 30)


@pytest.fixture
def brand():
    return brands.create_brand(current(), name="虛構營收證據商店", client_name=None,
                               actor="test", org_id=DEV_ORG_ID)["id"]


def _save(brand, number, amount, *, refund=0, payment="paid", status="open",
          day="2026-09-05"):
    orders.save_orders(current(), brand, [{
        "order_number": number, "order_date": day, "total_amount": amount,
        "refunded_amount": refund, "financial_status": payment,
        "order_status": status,
        "billing_email": "fictional-sensitive@example.invalid",
    }], source="easystore_xlsx", actor="test")


def _read(brand, org=DEV_ORG_ID):
    return review_evidence(current(), org, brand, start=START, end=END)


def _channel(brand, source, amount, currency):
    current().execute(
        "INSERT INTO channel_revenue"
        " (id, org_id, brand_id, channel, entry_date, revenue, source, currency)"
        " VALUES (%s, %s, %s, 'physical_store', '2026-09-05', %s, %s, %s)",
        (new_id("chr"), DEV_ORG_ID, brand, amount, source, currency),
    )


def test_paid_pending_refunded_and_void_are_not_conflated(brand):
    _save(brand, "paid", 100)
    _save(brand, "pending", 200, payment="pending")
    _save(brand, "refund", 40, refund=60, payment="refunded")
    _save(brand, "partial-refund", 80, refund=30, payment="partially_refunded")
    _save(brand, "void", 400, status="cancelled")
    _save(brand, "unknown", 300, payment=None)
    _save(brand, "partial-payment", 20, payment="partially_paid")
    _save(brand, "outside", 9999, day="2026-08-31")
    result = _read(brand)
    summary = result["order_summary"]
    assert summary["count"] == 7
    assert summary["non_void_count"] == 6
    assert summary["void_count"] == 1
    assert summary["refunded_count"] == 2
    assert summary["unpaid_count"] == 1
    assert summary["unknown_payment_count"] == 2
    assert summary["order_net_amount"] == 650
    assert summary["paid_net_amount"] == 130
    assert summary["paid_count"] == 3
    assert summary["currency"] is None
    assert summary["currency_basis"] == "unknown"
    assert summary["coverage"] == "unknown"
    assert summary["latest_import_at"]
    assert result["attribution"] == "unavailable"
    assert "fictional-sensitive" not in json.dumps(result)
    assert not ({"customer_id", "order_number", "billing_email", "identity_hash"}
                & set(summary))


def test_negative_refund_is_preserved_and_import_default_is_not_currency_evidence(brand):
    _save(brand, "over-refund", 40, refund=60, payment="refunded")
    stored = current().execute(
        "SELECT currency FROM order_record WHERE brand_id = %s", (brand,),
    ).fetchone()
    assert stored["currency"] == "TWD"
    result = _read(brand)
    assert result["order_summary"]["paid_net_amount"] == -20
    assert result["order_summary"]["currency"] is None
    assert result["order_summary"]["reported_currencies"] == ["TWD"]
    assert result["channels"][0]["currency"] is None
    assert result["channels"][0]["source_type"] == "order_mirror"
    assert result["channels"][0]["amount"] == -20


def test_missing_amount_and_payment_evidence_never_become_zero(brand):
    _save(brand, "missing-total", None, payment=None)
    _save(brand, "missing-refund", 100, refund=None, payment="paid")
    result = _read(brand)
    summary = result["order_summary"]
    assert summary["count"] == 2
    assert summary["unknown_amount_count"] == 2
    assert summary["known_net_count"] == 0
    assert summary["known_paid_net_count"] == 0
    assert summary["order_net_amount"] is None
    assert summary["paid_net_amount"] is None
    assert summary["unknown_payment_count"] == 1
    assert result["channels"][0]["amount"] is None
    assert result["channels"][0]["unknown_amount_count"] == 2


def test_empty_and_unpaid_are_not_confirmed_receipts(brand):
    empty = _read(brand)
    assert empty["order_summary"]["count"] == 0
    assert empty["order_summary"]["order_net_amount"] is None
    assert empty["order_summary"]["paid_net_amount"] is None
    assert empty["order_summary"]["latest_import_at"] is None
    assert empty["channels"] == []
    _save(brand, "unpaid", 100, payment="pending")
    summary = _read(brand)["order_summary"]
    assert summary["order_net_amount"] == 100
    assert summary["paid_net_amount"] is None


def test_mirrors_and_channel_sources_currencies_stay_separate(brand):
    _save(brand, "website", 100)
    record_channel_entry(current(), brand, channel="physical_store", entry_date="2026-09-05",
                         revenue=100, actor="test")
    _channel(brand, "manual", 200, "USD")
    _channel(brand, "manual", 300, "TWD")
    _channel(brand, "shop_api", 100, "TWD")
    _channel(brand, "shop_api", None, "TWD")
    result = _read(brand)
    assert len(result["channels"]) == 5
    indexed = {(r["source"], r["currency"]): r for r in result["channels"]}
    assert indexed[("manual", None)]["amount"] == 100
    assert indexed[("manual", "USD")]["amount"] == 200
    assert indexed[("manual", "TWD")]["amount"] == 300
    assert indexed[("shop_api", "TWD")]["amount"] == 100
    assert indexed[("shop_api", "TWD")]["row_count"] == 2
    assert indexed[("shop_api", "TWD")]["unknown_amount_count"] == 1
    assert indexed[("easystore_xlsx", None)]["source_type"] == "order_mirror"
    assert result["order_summary"]["order_net_amount"] == 100
    assert "total_revenue" not in result


def test_reimport_and_explicit_zero_remain_one_known_order(brand):
    _save(brand, "same-order", 100)
    _save(brand, "same-order", 100, refund=100, payment="refunded")
    result = _read(brand)
    assert result["order_summary"]["count"] == 1
    assert result["order_summary"]["paid_net_amount"] == 0
    assert result["channels"][0]["row_count"] == 1
    assert result["channels"][0]["amount"] == 0


def test_mixed_stored_order_currencies_are_not_added(brand):
    _save(brand, "twd", 100)
    _save(brand, "usd", 20)
    current().execute(
        "UPDATE order_record SET currency = 'USD'"
        " WHERE brand_id = %s AND order_number = 'usd'", (brand,),
    )
    summary = _read(brand)["order_summary"]
    assert summary["order_net_amount"] is None
    assert summary["paid_net_amount"] is None
    assert summary["currency"] is None


def test_org_brand_and_dates_are_isolated(brand):
    other = brands.create_brand(current(), name="虛構別間商店", client_name=None,
                                actor="test", org_id=DEV_ORG_ID)["id"]
    _save(brand, "own", 100, day="2026-09-01")
    _save(brand, "own-last", 200, day="2026-09-30")
    _save(brand, "after", 9000, day="2026-10-01")
    _save(other, "other", 999)
    _channel(other, "manual", 888, "TWD")
    result = _read(brand)
    assert result["order_summary"]["order_net_amount"] == 300
    assert result["channels"][0]["amount"] == 300
    wrong_org = _read(brand, org="org_no_access")
    assert wrong_org["order_summary"]["count"] == 0
    assert wrong_org["channels"] == []
    assert _read("brand_missing")["order_summary"]["count"] == 0


@pytest.mark.parametrize(("start", "end"), [
    (date(2026, 9, 1), date(2026, 10, 2)),
    (date(2026, 9, 2), date(2026, 9, 1)),
    ("2026-09-01", date(2026, 9, 1)),
])
def test_invalid_window_fails_before_any_read(start, end):
    with pytest.raises(ValueError):
        review_evidence(None, DEV_ORG_ID, "brand", start=start, end=end)


def test_inclusive_31_days_are_allowed(brand):
    result = review_evidence(current(), DEV_ORG_ID, brand,
                             start=date(2026, 8, 1), end=date(2026, 8, 31))
    assert result["start"] == "2026-08-01"
    assert result["end"] == "2026-08-31"
