import pytest

from app.brand_intelligence import benchmarks


@pytest.mark.parametrize("key", ["gross_margin", "shipping_cost", "close_rate"])
def test_get_returns_record(key):
    record = benchmarks.get(key)
    assert record["key"] == key
    assert isinstance(record["value"], (int, float))


def test_ratio_values_in_range():
    assert 0 < benchmarks.get("gross_margin")["value"] < 1
    assert 0 < benchmarks.get("close_rate")["value"] < 1


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
