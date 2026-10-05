import pytest

from app.brand_intelligence import benchmarks


@pytest.mark.parametrize("key", ["gross_margin", "shipping_cost", "close_rate"])
def test_get_returns_record(key):
    record = benchmarks.get(key)
    assert record["key"] == key
    assert isinstance(record["value"], (int, float))


def test_rates_are_served_as_percents():
    # F50 Contract I (decision 9): rates are served 0–100 with unit 「%」, as a user types them.
    assert benchmarks.get("gross_margin")["value"] == 45
    assert benchmarks.get("close_rate")["value"] == 20
    for key in ("gross_margin", "close_rate"):
        assert benchmarks.get(key)["unit"] == "%"
        assert 0 < benchmarks.get(key)["value"] < 100


def test_margin_rule_card_default_is_the_benchmark():
    # User ruling 2026-10-04: one assumed gross margin default -- the benchmark 45 %. The rule
    # card cannot import brand_intelligence (core is below it), so this pins the two together.
    from app.core import rule_cards

    field = rule_cards.CARDS["gross_margin"]["fields"]["gross_margin_rate"]
    assert field["default"] == benchmarks.get("gross_margin")["value"]


def test_shipping_cost_is_positive_integer():
    value = benchmarks.get("shipping_cost")["value"]
    assert isinstance(value, int)
    assert value > 0


def test_source_text_gross_margin_has_source():
    text = benchmarks.source_text("gross_margin")
    assert "來源：" in text
    assert "NYU" in text


def test_source_text_shipping_cost_has_no_source_label():
    text = benchmarks.source_text("shipping_cost")
    assert "來源" not in text


def test_get_unknown_key_raises():
    with pytest.raises(KeyError):
        benchmarks.get("nonexistent")
