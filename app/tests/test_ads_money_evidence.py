"""Money estimates never turn missing economics or collected orders into profit."""

from datetime import date, timedelta
from unittest import mock

import pytest

from app import orders
from app.ads import budget, coverage, home_overview, month_summary, targets
from app.ads import repository as ads_repository
from app.brand_intelligence import repository as brands
from app.core import db
from app.core import settings as coresettings
from app.orders import repository as order_repository
from app.tests.fixtures.ads_external import outcome_seed
from app.tests.test_ads_home_overview import _ad, _imported, _obs


@pytest.mark.parametrize("shipping,expected", [(None, None), (0, 350), (50, 300)])
def test_unknown_shipping_is_not_free_shipping(shipping, expected):
    assert budget.breakeven_cpa({
        "selling_price": 500, "unit_variable_cost": 150, "shipping_cost": shipping,
    }) == expected


@pytest.mark.parametrize("product_ids,shipping,missing", [
    (["one", "two"], 0, "sales_mix"), (["one"], None, "shipping_cost"),
])
def test_own_cap_survives_unknown_economics_without_inventing_margin(
    product_ids, shipping, missing,
):
    with (
        mock.patch.object(brands, "get_product_economics", return_value={
            "selling_price": 500, "unit_variable_cost": 150,
            "shipping_cost": shipping, "currency": "TWD",
        }),
        mock.patch.object(brands, "knowledge_product_ids", return_value=["knowledge"]),
    ):
        cap = targets.resolve(None, "org", "brand", {
            "target_basis": "own", "target_cost": 100, "result_kind": "purchase",
            "context_json": {"product_ids": product_ids},
        })
    assert cap["value"] == 100
    assert cap["missing"] == []
    assert cap["break_even"] is None
    assert missing in cap["economics_basis"]["missing"]
    assert cap["product_id"] == ("one" if len(product_ids) == 1 else None)


def test_multiple_products_are_not_an_arbitrary_first_economics_row():
    with mock.patch.object(brands, "get_product_economics") as read:
        assert budget.economics_for(None, "brand", ["a", "b"]) == (None, None)
    read.assert_not_called()


@pytest.fixture
def brand():
    return brands.create_brand(db.current(), org_id=db.DEV_ORG_ID,
                               name="Money evidence fixture", client_name=None, actor="test")["id"]


def _save(brand, number, amount, *, payment="paid", refund=0, day="2026-09-05"):
    order_repository.save_orders(db.current(), brand, [{
        "order_number": number, "total_amount": amount, "refunded_amount": refund,
        "financial_status": payment, "order_status": "open", "order_date": day,
    }], source="easystore_xlsx", actor="test")


def test_month_paid_subtotal_does_not_include_pending_cod_or_unknown(brand):
    _save(brand, "paid", 100)
    _save(brand, "refunded", 100, payment="partially_refunded", refund=30)
    _save(brand, "pending-cod", 900, payment="pending")
    _save(brand, "unknown", 800, payment=None)
    _save(brand, "unknown-amount", 700, refund=None)
    _save(brand, "prior", 50, day="2026-08-05")
    view = month_summary._orders_comparison(db.current(), db.DEV_ORG_ID, brand,
                                          date(2026, 9, 1), 10)
    assert view["this_net"] == 170
    assert view["this_count"] == 2
    assert view["previous_net"] == 50
    assert view["change_pct"] is None
    assert view["amount_basis"] == "paid_net_amount"
    assert view["order_book"]["this_net"] == 1870
    assert view["this_evidence"]["order_summary"]["unknown_payment_count"] == 1
    assert view["this_evidence"]["order_summary"]["unpaid_count"] == 1
    assert view["this_evidence"]["order_summary"]["paid_count"] == 3
    assert set(view["comparison_missing"]) == {"currency", "coverage", "payment", "amount"}


@pytest.mark.parametrize("today,month", [(date(2026, 9, 1), "2026-09"),
                                        (date(2026, 9, 10), "2026-10")])
def test_no_elapsed_window_never_calls_order_facade(brand, today, month):
    with (
        mock.patch.object(coresettings, "today_for_org", return_value=today),
        mock.patch.object(coverage, "last_complete_day", return_value=today - timedelta(days=1)),
        mock.patch.object(orders, "review_evidence") as read,
    ):
        home = home_overview.get_overview(db.current(), db.DEV_ORG_ID, brand, month)
        summary = month_summary.get_summary(db.current(), db.DEV_ORG_ID, brand, month)
    assert home["commerce"] is None
    assert summary["orders"] is None
    assert summary["data_days"] == 0
    assert summary["grades"]["rows"] == []
    assert summary["grades"]["missing"] == []
    assert summary["grades"]["spent"] is None
    read.assert_not_called()


def test_home_and_month_share_platform_elapsed_window_and_exact_facade(brand):
    conn, org = db.current(), db.DEV_ORG_ID
    campaign = _imported(conn, org, brand, "Elapsed fixture", "native", cap=100)
    ad = _ad(conn, org, brand, campaign, "ad", "native")
    _obs(conn, org, brand, campaign, ad, date(2026, 9, 8), spend=100, count=2)
    _obs(conn, org, brand, campaign, ad, date(2026, 9, 9), spend=9000, count=99)
    _save(brand, "elapsed", 100)
    _save(brand, "today", 9999, day="2026-09-10")
    with (
        mock.patch.object(coresettings, "today_for_org", return_value=date(2026, 9, 10)),
        mock.patch.object(coverage, "last_complete_day", return_value=date(2026, 9, 8)),
    ):
        home = home_overview.get_overview(db.current(), db.DEV_ORG_ID, brand, "2026-09")
        summary = month_summary.get_summary(db.current(), db.DEV_ORG_ID, brand, "2026-09")
    expected = orders.review_evidence(db.current(), db.DEV_ORG_ID, brand,
                                     start=date(2026, 9, 1), end=date(2026, 9, 8))
    assert home["commerce"] == expected
    assert summary["orders"]["this_evidence"] == expected
    assert summary["data_days"] == 8
    assert summary["days_elapsed"] == 10
    assert summary["orders"]["this_net"] == 100
    assert summary["total_spend"] == home["spent"] == 100
    assert summary["grades"]["spent"] == summary["total_spend"]
    assert sum(b["amount"] for b in summary["grades"]["buckets"]) == summary["total_spend"]
    assert summary["campaigns"][0]["result_count"] == home["money"]["purchases"] == 2
    assert home["commerce"]["channels"][0]["source_type"] == "order_mirror"
    assert "total_revenue" not in home["commerce"]
    assert home["commerce"]["attribution"] == "unavailable"
    assert home["money"]["earn_after_cost_and_ads"] is None


def test_failed_commerce_read_is_independent_nullable_block(brand):
    def failed_read(*args, **kwargs):
        db.current().execute("SELECT 1/0")  # Abort the real transaction, not just a Python error.

    with (
        mock.patch.object(coresettings, "today_for_org", return_value=date(2026, 9, 10)),
        mock.patch.object(coverage, "last_complete_day", return_value=date(2026, 9, 9)),
        mock.patch.object(orders, "review_evidence", side_effect=failed_read),
    ):
        home = home_overview.get_overview(db.current(), db.DEV_ORG_ID, brand, "2026-09")
    assert home["commerce"] is None
    assert home["pace"] is not None
    assert home["money"] is not None
    assert db.current().execute("SELECT 1 AS healthy").fetchone()["healthy"] == 1


@pytest.mark.parametrize("shipping,cost,product_currency,multiple,expected,missing", [
    (0, 150, "TWD", False, 600, None),
    (None, 150, "TWD", False, None, "shipping_cost"),
    (0, None, "TWD", False, None, "product_cost"),
    (0, 150, "USD", False, None, "currency"),
    (0, 150, "TWD", True, None, "sales_mix"),
])
def test_home_margin_is_a_unit_currency_checked_hypothesis(
    brand, shipping, cost, product_currency, multiple, expected, missing,
):
    conn, org = db.current(), db.DEV_ORG_ID
    product = brands.create_product(conn, brand, name="Fixture sell-way", actor="test")["id"]
    brands.save_product_economics(conn, brand, product, selling_price=500,
                                 currency=product_currency, unit_variable_cost=cost,
                                 shipping_cost=shipping, confirmed_by="test", actor="test")
    campaign = _imported(conn, org, brand, "Purchase fixture", "native",
                         product_id=product, cap=100)
    if multiple:
        second = brands.create_product(conn, brand, name="Other sell-way", actor="test")["id"]
        conn.execute("UPDATE ads_campaign SET context_json=context_json || %s WHERE id=%s",
                     (db.jsonb({"product_ids": [product, second]}), campaign))
        conn.commit()
    ad = _ad(conn, org, brand, campaign, "ad", "native")
    _obs(conn, org, brand, campaign, ad, date(2026, 9, 5), spend=100, count=2)
    _save(brand, "same-day-unassigned", 99999)
    with (
        mock.patch.object(coresettings, "today_for_org", return_value=date(2026, 9, 10)),
        mock.patch.object(coverage, "last_complete_day", return_value=date(2026, 9, 9)),
    ):
        home = home_overview.get_overview(conn, org, brand, "2026-09")
    money = home["money"]
    assert money["earn_after_cost_and_ads"] == expected
    assert money["cap"]["value"] == 100  # Own cap does not fabricate a margin.
    assert money["estimate_basis"]["kind"] == "platform_purchase_margin"
    assert money["estimate_basis"]["missing"] == money["earn_missing"]
    assert len(money["estimate_basis"]["assumptions"]) == 3
    if missing:
        assert missing in money["earn_missing"]
    else:
        assert money["earn_missing"] == []
    assert home["commerce"]["order_summary"]["paid_net_amount"] == 99999
    assert home["commerce"]["attribution"] == "unavailable"
    assert "revenue" not in home["campaigns"][0]


@pytest.mark.parametrize(
    "currency,coverage_state,payment_unknown,unknown_amount,expected_missing", [
    (None, "complete", 0, False, "currency"),
    ("TWD", "unknown", 0, False, "coverage"),
    ("TWD", "complete", 1, False, "payment"),
    ("TWD", "complete", 0, True, "amount"),
    ("TWD", "complete", 0, False, None),
    ],
)
def test_comparison_requires_equal_currency_coverage_and_payment_amount_evidence(
    brand, currency, coverage_state, payment_unknown, unknown_amount, expected_missing,
):
    _save(brand, "this", 100)
    _save(brand, "prior", 50, day="2026-08-05")
    facade = orders.review_evidence

    def read(conn, org, brand_id, **window):
        value = facade(conn, org, brand_id, **window)
        value["order_summary"].update(
            currency=currency, currency_basis="source" if currency else "unknown",
            coverage=coverage_state, unknown_payment_count=payment_unknown,
            paid_count=2 if unknown_amount else 1,
        )
        return value

    with mock.patch.object(orders, "review_evidence", side_effect=read):
        view = month_summary._orders_comparison(db.current(), db.DEV_ORG_ID, brand,
                                              date(2026, 9, 1), 10)
    assert view["change_pct"] == (1.0 if expected_missing is None else None)
    assert view["comparison_missing"] == ([expected_missing] if expected_missing else [])


@pytest.mark.parametrize(
    "product_currency,status,cap,source_unknown,observed,expected_cap,expected_earn", [
        ("USD", "confirmed", 100, False, ["TWD"], 100, None),
        ("TWD", "pending", 100, False, ["TWD"], 100, None),
        ("USD", "confirmed", None, False, ["TWD"], None, None),
        ("TWD", "pending", None, False, ["TWD"], None, None),
        ("TWD", "confirmed", None, False, ["TWD"], 350, 600),
        ("TWD", "confirmed", 100, False, [None], None, None),
        ("TWD", "confirmed", 100, False, ["TWD", "USD"], None, None),
        ("TWD", "confirmed", 100, True, ["TWD"], None, 600),
    ],
)
def test_home_and_month_use_the_canonical_cap_and_economics_units(
    brand, product_currency, status, cap, source_unknown, observed, expected_cap, expected_earn,
):
    conn, org = db.current(), db.DEV_ORG_ID
    product = brands.create_product(conn, brand, name="Unit fixture", actor="test")["id"]
    brands.save_product_economics(conn, brand, product, selling_price=500,
                                 currency=product_currency, unit_variable_cost=150,
                                 shipping_cost=0, confirmed_by="test", actor="test")
    if status == "pending":
        # Historical full-number rows may still lack confirmation; fixture owns this item.
        conn.execute("UPDATE product_economics SET status='pending'"
                     " WHERE brand_id=%s AND product_id=%s", (brand, product))
        conn.commit()
    campaign = _imported(conn, org, brand, "Unit fixture", "native",
                         product_id=product, cap=cap)
    if source_unknown:
        conn.execute("UPDATE ads_campaign SET context_json=context_json || %s WHERE id=%s",
                     (db.jsonb({"field_sources": {"cap": "legacy"}}), campaign))
        conn.commit()
    ad = _ad(conn, org, brand, campaign, "ad", "native")
    for i, currency in enumerate(observed):
        _obs(conn, org, brand, campaign, ad, date(2026, 9, 5 + i), spend=100,
             count=2, currency=currency)
    # Unit arithmetic assumes a completed read; missing-period eligibility has separate falsifiers.
    outcome_seed.set_coverage(conn, org, brand, campaign, date(2026, 9, 1), date(2026, 9, 9))
    with (
        mock.patch.object(coresettings, "today_for_org", return_value=date(2026, 9, 10)),
        mock.patch.object(coverage, "last_complete_day", return_value=date(2026, 9, 9)),
    ):
        home = home_overview.get_overview(conn, org, brand, "2026-09")
        month = month_summary.get_summary(conn, org, brand, "2026-09")
    assert home["money"]["earn_after_cost_and_ads"] == expected_earn
    expected_break_even = 350 if expected_earn is not None else None
    for shown in (home["money"]["cap"], home["campaigns"][0]["cap"]):
        if expected_cap is None:
            assert shown is None
        else:
            assert shown["value"] == expected_cap
            assert shown["break_even"] == expected_break_even
    if expected_earn is None:
        assert "currency" in home["money"]["earn_missing"]
    row = month["campaigns"][0]
    expected_currency = observed[0] if len(observed) == 1 else None
    assert row["currency"] == expected_currency
    assert home["campaigns"][0]["currency"] == expected_currency
    assert row["target"] == expected_cap
    assert row["verdict"] == ("met" if expected_cap is not None else "unjudged")
    graded = month["grades"]["rows"][0]
    assert graded["grade"] == ("on_target" if expected_cap is not None else "insufficient")
    assert row["cap_comparison"] == graded["cap_comparison"]
    expected_spend = 100 if len(observed) == 1 and observed[0] is not None else None
    assert home["spent"] == month["total_spend"] == month["grades"]["spent"] == expected_spend
    raw = ads_repository.get_campaign(conn, org, brand, campaign)
    resolved = targets.resolve(conn, org, brand, raw)
    assert resolved["value"] == (cap if cap is not None else 350)
    for container in (home["money"], home["campaigns"][0], row):
        assert container["configured_cap"]["value"] == resolved["value"]
        assert container["configured_cap"]["basis"] == resolved["basis"]

def test_cost_glossary_does_not_infer_loss_from_an_own_cap():
    from app.ads import triage

    glossary = triage.rules()["glossary"]
    assert "賣越多虧越多" not in glossary["over"]
    assert "不能單憑此判定盈虧" in glossary["over"]
    assert "已付款利潤" in glossary["money"]
    assert "來源" in glossary["break_even"]
    assert "支出風險" in glossary["wasted"]
