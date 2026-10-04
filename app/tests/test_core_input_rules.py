"""app/tests/test_core_input_rules.py — F47 Contract A: the one store-time input rule module.

Pure functions, no database: each rule keeps exactly what was sent or refuses with one sentence
naming the field; nothing is coerced.
"""

import math
import re
import struct
import zlib
from datetime import date, datetime
from decimal import Decimal

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


def _png_chunk(ctype: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", zlib.crc32(ctype + data))


def _png(width=1, height=1) -> bytes:
    return (b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + _png_chunk(b"IEND", b""))


def _jpeg(width=1, height=1) -> bytes:
    app0 = b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof0 = b"\xff\xc0\x00\x0b\x08" + struct.pack(">HH", height, width) + b"\x01\x01\x11\x00"
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xd9"


def _webp(fourcc=b"VP8L", payload=b"\x2f\x00\x00\x00\x00", riff_extra=0) -> bytes:
    body = b"WEBP" + fourcc + struct.pack("<I", len(payload)) + payload
    return b"RIFF" + struct.pack("<I", len(body) + riff_extra) + body


VP8_1X1 = b"\x00\x00\x00\x9d\x01\x2a\x01\x00\x01\x00"

PNG = _png()
JPEG = _jpeg()


@pytest.mark.parametrize("content,mime", [
    (PNG, "image/png"),
    (PNG + b"trailing image data", "image/png"),
    (JPEG, "image/jpeg"),
    (_webp(), "image/webp"),
    (_webp(b"VP8 ", VP8_1X1), "image/webp"),
    (_webp(b"VP8X", b"\x00" * 10), "image/webp"),
    (b"GIF89a\x01\x00\x01\x00", "image/gif"),
    (b"GIF87a\x01\x00\x01\x00", "image/gif"),
    (b"\x00\x00\x00\x18ftypisom", "video/mp4"),
    (b"\x00\x00\x00\x18ftypqt  ", "video/quicktime"),
    (b"hello", None),
    (b"", None),
])
def test_sniff(content, mime):
    assert r.sniff(content) == mime


@pytest.mark.parametrize("content", [
    b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4,  # signature + junk (the acceptance case)
    PNG[:20],  # truncated IHDR
    PNG[:29] + b"\x00\x00\x00\x00" + PNG[33:],  # bad CRC
    _png(width=0),
    b"\xff\xd8\xff" + bytes(range(256)) * 4,
    _jpeg(height=0),
    JPEG[:-13],  # cut inside the frame header
    b"\xff\xd8\xff\xda\x00\x02",  # scan data before any frame header
    _webp(riff_extra=100),  # RIFF size larger than the bytes sent
    _webp(b"VP8 ", b"\x00" * 10),  # VP8 without its start code
    _webp(b"VP8L", b"\x00\x00\x00\x00\x00"),  # VP8L without its signature byte
    _webp(b"JUNK", b"\x00" * 10),
    b"GIF89a\x00\x00\x01\x00",
    b"GIF89a\x01",
])
def test_sniff_refuses_an_image_whose_header_does_not_decode(content):
    assert r.sniff(content) is None


def test_kinds_text():
    assert r.kinds_text(("image/jpeg",)) == "JPEG"
    assert r.kinds_text(("image/jpeg", "image/png", "image/webp")) == "JPEG、PNG 或 WebP"


def test_check_image_upload():
    kinds = ("image/jpeg", "image/png", "image/webp")
    assert r.check_image_upload("photo.jpg", PNG, kinds) == "image/png"
    with pytest.raises(r.InputRuleError,
                       match="^「broken.png」的內容不是JPEG、PNG 或 WebP 圖片，請換一張。$"):
        r.check_image_upload("broken.png", b"\x89PNG\r\n\x1a\n" + b"\x07" * 64, kinds)
    with pytest.raises(r.InputRuleError, match="^「empty.jpg」是空的檔案，請換一個。$"):
        r.check_image_upload("empty.jpg", b"", kinds)
    with pytest.raises(r.InputRuleError,
                       match="^「text.jpg」的內容不是JPEG、PNG 或 WebP 圖片，請換一張。$"):
        r.check_image_upload("text.jpg", b"plain text", kinds)
    with pytest.raises(r.InputRuleError, match="不是JPEG、PNG 或 WebP 圖片"):
        r.check_image_upload("anim.gif", b"GIF89a\x01\x00\x01\x00", kinds)


# ---------------------------------------------------------------------------
# F50 Contract I: the rest of the one table (one test per rule and case; the good value passes
# unchanged, the bad value gets the exact sentence).
# ---------------------------------------------------------------------------

def _refused(sentence):
    return pytest.raises(r.InputRuleError, match="^" + re.escape(sentence) + "$")


def test_count():
    assert r.count(3, "數量") == 3
    assert r.count("12", "數量") == 12
    assert r.count(0, "數量") == 0
    assert r.count(2.0, "數量") == 2
    assert r.count(None, "數量", optional=True) is None
    assert r.count(" ", "數量", optional=True) is None
    for bad in (-2, "-2", 1.5, "1.5", "abc", True, None, ""):
        with _refused("數量要是 0 以上的整數。"):
            r.count(bad, "數量")
    assert r.count(1, "件數", minimum=1) == 1
    with _refused("件數要是 1 以上的整數。"):
        r.count(0, "件數", minimum=1)


def test_percent():
    assert r.percent(20, "成交率") == 20.0
    assert r.percent("100", "成交率") == 100.0
    assert r.percent(0.5, "成交率") == 0.5
    assert r.percent("", "成交率", optional=True) is None
    for bad in (0, -1, 100.01, 120, "abc", None):
        with _refused("成交率要大於 0、最多 100（填 20 代表 20%）。"):
            r.percent(bad, "成交率")


def test_rate_fraction_is_the_one_scale():
    assert r.rate_fraction(20) == 0.2
    assert r.rate_fraction(Decimal("45")) == 0.45


def test_iso_date():
    assert r.iso_date("2026-10-05", "日期") == date(2026, 10, 5)
    assert r.iso_date(" 2026-10-05 ", "日期") == date(2026, 10, 5)
    assert r.iso_date(date(2026, 10, 5), "日期") == date(2026, 10, 5)
    assert r.iso_date(datetime(2026, 10, 5, 23, 30), "日期") == date(2026, 10, 5)
    assert r.iso_date(None, "日期", optional=True) is None
    for bad in ("13/06/2026", "2026-13-01", "2026-02-30", "20261005", "2026-10-05T00:00",
                "yesterday", 20261005, None, ""):
        with _refused("日期請用 YYYY-MM-DD 格式（例如 2026-10-05）。"):
            r.iso_date(bad, "日期")


def test_date_order_reads_iso_only():
    with _refused("開始日請用 YYYY-MM-DD 格式（例如 2026-10-05）。"):
        r.date_order("01/10/2026", "2026-10-02")


def test_date_within():
    assert r.date_within("2026-10-05", "2026-10-01", "2026-10-31", "投放組日期", "活動期間") \
        == date(2026, 10, 5)
    assert r.date_within("2026-10-01", date(2026, 10, 1), None, "投放組日期", "活動期間") \
        == date(2026, 10, 1)
    for bad in ("2026-09-30", "2026-11-01"):
        with _refused("投放組日期要在活動期間（2026-10-01～2026-10-31）內。"):
            r.date_within(bad, "2026-10-01", "2026-10-31", "投放組日期", "活動期間")


def test_one_of():
    allowed = {"discount": "折扣規則", "refund": "退款政策"}
    assert r.one_of("refund", "口徑類型", allowed) == "refund"
    for bad in ("unknown", "折扣規則", None, ""):
        with _refused("口徑類型只能選：折扣規則、退款政策。"):
            r.one_of(bad, "口徑類型", allowed)


def test_url():
    assert r.url(" https://example.com/a?b=1 ", "官網") == "https://example.com/a?b=1"
    assert r.url("http://localhost:8710/x", "官網") == "http://localhost:8710/x"
    assert r.url("", "官網", optional=True) is None
    for bad in ("https://", "example.com", "ftp://example.com", "https://exa mple.com",
                "https://localhost.", "javascript:alert(1)", "https://nodot"):
        with _refused(f"官網「{bad}」不是完整的網址，請從 https:// 開始，例如 https://example.com。"):
            r.url(bad, "官網")


def test_urls():
    assert r.urls(["https://a.com", " ", None, "https://b.com"], "網址", max_count=5) == \
        ["https://a.com", "https://b.com"]
    with _refused("最多填 5 個網址。"):
        r.urls([f"https://a{i}.com" for i in range(6)], "網址", max_count=5)
    with _refused("網址「https://」不是完整的網址，請從 https:// 開始，例如 https://example.com。"):
        r.urls(["https://a.com", "https://"], "網址", max_count=5)


def test_upload_caps_and_sentences():
    assert r.UPLOAD_CAPS == {"brand_photo": 10 * 1024 * 1024, "library_asset": 50 * 1024 * 1024,
                             "ad_asset": 50 * 1024 * 1024}
    r.check_upload("a.jpg", 10 * 1024 * 1024, path="brand_photo")  # exactly the cap passes
    with _refused("「a.jpg」是空的檔案，請換一個。"):
        r.check_upload("a.jpg", 0, path="brand_photo")
    # A 10.04 MB file (as a MiB display rounds it) is over a 10 MiB cap: bytes, no rounding;
    # one byte over is over.
    for size in (int(10.04 * 1024 * 1024), 10 * 1024 * 1024 + 1):
        with _refused("「a.jpg」超過 10 MB，請換一個小一點的檔案。"):
            r.check_upload("a.jpg", size, path="brand_photo")
    with _refused("「v.mp4」超過 50 MB，請換一個小一點的檔案。"):
        r.check_upload("v.mp4", 50 * 1024 * 1024 + 1, path="ad_asset")


def test_api_key():
    assert r.api_key("  sk-ant-api03-abc  ") == "sk-ant-api03-abc"
    for bad in ("abc", "", "   ", None, "sk-ant-", "sk-ant- abc", "sk-ant-ab\tc", "sk-abc", 123):
        with _refused("AI 金鑰要以 sk-ant- 開頭，請從 Anthropic 主控台複製完整的一串。"):
            r.api_key(bad)


def test_vocab_require_is_one_of_over_the_vocab_list():
    from app.core import vocab

    assert vocab.require("channel", "physical_store") == "physical_store"
    assert vocab.require("policy", "ship_threshold") == "ship_threshold"
    assert vocab.require("persona", "kol") == "kol"
    assert vocab.require("customer_voice_source", "shopee") == "shopee"
    labels = "、".join(label for _key, label in vocab.CHANNEL_TYPES)
    with _refused(f"通路只能選：{labels}。"):
        vocab.require("channel", "pharmacy")
    with _refused("宣稱類型只能選：可用、高風險、禁用。"):
        vocab.require("claim", "xyz")
    with pytest.raises(KeyError):
        vocab.require("no_such_kind", "x")
