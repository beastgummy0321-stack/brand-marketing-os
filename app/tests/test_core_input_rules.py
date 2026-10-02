"""app/tests/test_core_input_rules.py — F47 Contract A: the one store-time input rule module.

Pure functions, no database: each rule keeps exactly what was sent or refuses with one sentence
naming the field; nothing is coerced.
"""

import math
from datetime import date

import pytest

from app.core import input_rules as r


def test_errors_are_value_errors():
    assert issubclass(r.InputRuleError, ValueError)


@pytest.mark.parametrize("value,expected", [(5, 5.0), (0.5, 0.5), ("12", 12.0), ("1,280", 1280.0)])
def test_number_keeps_value(value, expected):
    assert r.number(value, "售價") == expected


@pytest.mark.parametrize("value", [None, "", "  "])
def test_optional_empty_is_unset(value):
    assert r.number(value, "售價", optional=True) is None
    assert r.positive(value, "售價", optional=True) is None
    assert r.non_negative(value, "成本", optional=True) is None
    assert r.signed(value, "運費", optional=True) is None


@pytest.mark.parametrize("value", [None, "", "abc", True, float("nan"), math.inf, [1]])
def test_required_or_bad_number_refused(value):
    with pytest.raises(r.InputRuleError, match="^售價請填數字。$"):
        r.number(value, "售價")


def test_positive():
    assert r.positive(0.01, "售價") == 0.01
    for bad in (0, -1):
        with pytest.raises(r.InputRuleError, match="^售價要大於 0。$"):
            r.positive(bad, "售價")


def test_non_negative_keeps_zero():
    assert r.non_negative(0, "營收") == 0.0
    with pytest.raises(r.InputRuleError, match="^營收不能是負數。$"):
        r.non_negative(-5, "營收")


def test_signed_keeps_negative_as_typed():
    assert r.signed(-20, "運費") == -20.0


def test_bounds_open_interval():
    margin = r.Bounds(0, 1, low_open=True, high_open=True, hint="例如 0.7 代表毛利 70%")
    assert r.within(0.7, "毛利率", margin) == 0.7
    for bad in (0, 1, 7, -0.1, "x", None):
        with pytest.raises(r.InputRuleError,
                           match=r"^毛利率要大於 0、小於 1（例如 0.7 代表毛利 70%）。$"):
            r.within(bad, "毛利率", margin)
    assert r.within(None, "毛利率", margin, optional=True) is None


def test_bounds_closed_interval():
    b = r.Bounds(1, 10)
    assert r.within(1, "數量", b) == 1 and r.within(10, "數量", b) == 10
    with pytest.raises(r.InputRuleError, match="^數量要至少 1、最多 10。$"):
        r.within(11, "數量", b)


def test_ordered_pair():
    r.ordered_pair(3, 3, "下限", "上限")
    r.ordered_pair(None, 3, "下限", "上限")
    with pytest.raises(r.InputRuleError, match="^方案數量下限（6）不能大於方案數量上限（3）。$"):
        r.ordered_pair(6, 3, "方案數量下限", "方案數量上限")


def test_date_order():
    r.date_order("2026-10-01", "2026-10-01")
    r.date_order(date(2026, 10, 1), None)
    r.date_order("", "2026-01-01")
    with pytest.raises(r.InputRuleError, match="^結束日不能早於開始日。$"):
        r.date_order("2026-10-02", date(2026, 10, 1))


@pytest.mark.parametrize("content,mime", [
    (b"\x89PNG\r\n\x1a\nxx", "image/png"),
    (b"\xff\xd8\xff\xe0xx", "image/jpeg"),
    (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
    (b"GIF89a....", "image/gif"),
    (b"GIF87a....", "image/gif"),
    (b"\x00\x00\x00\x18ftypisom", "video/mp4"),
    (b"\x00\x00\x00\x18ftypqt  ", "video/quicktime"),
    (b"hello", None),
    (b"", None),
])
def test_sniff(content, mime):
    assert r.sniff(content) == mime


def test_kinds_text():
    assert r.kinds_text(("image/jpeg",)) == "JPEG"
    assert r.kinds_text(("image/jpeg", "image/png", "image/webp")) == "JPEG、PNG 或 WebP"


def test_check_image_upload():
    kinds = ("image/jpeg", "image/png", "image/webp")
    assert r.check_image_upload("photo.jpg", b"\x89PNG\r\n\x1a\nxx", kinds) == "image/png"
    with pytest.raises(r.InputRuleError, match="^「empty.jpg」是空的檔案，請換一個。$"):
        r.check_image_upload("empty.jpg", b"", kinds)
    with pytest.raises(r.InputRuleError,
                       match="^「text.jpg」的內容不是JPEG、PNG 或 WebP 圖片，請換一張。$"):
        r.check_image_upload("text.jpg", b"plain text", kinds)
    with pytest.raises(r.InputRuleError, match="不是JPEG、PNG 或 WebP 圖片"):
        r.check_image_upload("anim.gif", b"GIF89a....", kinds)
