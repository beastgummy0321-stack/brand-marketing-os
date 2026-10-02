"""app/core/input_rules.py — the one home of input checks at store time (F47 Contract A).

Contract A: a store either keeps exactly what was sent or refuses with one Chinese sentence that
names the field. It never coerces: no negative -> 0, no 0 -> unset, no clamp. An optional number
sent empty / ``None`` means unset.

- money: finite; a selling price ``> 0``; cost fields and shipping ``>= 0`` (shipping on every
  path, lead decision); channel revenue ``>= 0`` (0 is stored as 0).
- ranges: each rule-card number field declares its own bounds (a margin is ``0 < x < 1``); a
  (min, max) pair with min > max is refused; dates: end ``>=`` start.
- uploads: one content sniff (JPEG, PNG, WebP, GIF, MP4, MOV signatures; images must also have a
  readable header with dimensions, stdlib only — no image library). Each upload path keeps
  its own allowed kinds and size cap; content wins over the file name (a real PNG named ``.jpg``
  is accepted and stored as PNG).

Every refusal is an ``InputRuleError`` (a ``ValueError``) whose text is the user sentence, so
routes that already map ``ValueError`` to 400 show it unchanged. This module imports nothing from
a managed module; stores in ``ads``, ``intake`` and the legacy packages call it instead of keeping
copies.
"""

from __future__ import annotations

import math
import struct
import zlib
from datetime import date
from decimal import Decimal


class InputRuleError(ValueError):
    """A refused input; ``str(exc)`` is the sentence shown to the user."""


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------

def _empty(value) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def number(value, label: str, *, optional: bool = False) -> float | None:
    """A finite number (int / float / Decimal / numeric text). Empty or ``None`` = unset when
    ``optional``, else refused. Booleans are not numbers."""
    if _empty(value):
        if optional:
            return None
        raise InputRuleError(f"{label}請填數字。")
    if isinstance(value, bool):
        raise InputRuleError(f"{label}請填數字。")
    if isinstance(value, str):
        try:
            value = float(value.strip().replace(",", ""))
        except ValueError:
            raise InputRuleError(f"{label}請填數字。") from None
    if not isinstance(value, (int, float, Decimal)):
        raise InputRuleError(f"{label}請填數字。")
    result = float(value)
    if not math.isfinite(result):
        raise InputRuleError(f"{label}請填數字。")
    return result


def positive(value, label: str, *, optional: bool = False) -> float | None:
    """``> 0`` (a selling price, a budget)."""
    result = number(value, label, optional=optional)
    if result is not None and result <= 0:
        raise InputRuleError(f"{label}要大於 0。")
    return result


def non_negative(value, label: str, *, optional: bool = False) -> float | None:
    """``>= 0`` (a cost, a revenue); 0 is kept as 0."""
    result = number(value, label, optional=optional)
    if result is not None and result < 0:
        raise InputRuleError(f"{label}不能是負數。")
    return result


class Bounds:
    """A number field's declared range. ``low_open`` / ``high_open`` exclude the end itself;
    ``None`` = no bound on that side. ``hint`` is appended to the refusal (an example)."""

    def __init__(self, low: float | None = None, high: float | None = None, *,
                 low_open: bool = False, high_open: bool = False, hint: str = ""):
        self.low, self.high = low, high
        self.low_open, self.high_open = low_open, high_open
        self.hint = hint

    def contains(self, value: float) -> bool:
        if self.low is not None and (value <= self.low if self.low_open else value < self.low):
            return False
        return not (self.high is not None
                    and (value >= self.high if self.high_open else value > self.high))

    def sentence(self, label: str) -> str:
        parts = []
        if self.low is not None:
            parts.append(f"大於 {_fmt(self.low)}" if self.low_open else f"至少 {_fmt(self.low)}")
        if self.high is not None:
            parts.append(f"小於 {_fmt(self.high)}" if self.high_open else f"最多 {_fmt(self.high)}")
        rule = "、".join(parts) if parts else "是數字"
        return f"{label}要{rule}{('（' + self.hint + '）') if self.hint else ''}。"


def _fmt(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def within(value, label: str, bounds: Bounds, *, optional: bool = False) -> float | None:
    """A number inside ``bounds``; the refusal names the field and the range."""
    try:
        result = number(value, label, optional=optional)
    except InputRuleError:
        raise InputRuleError(bounds.sentence(label)) from None
    if result is not None and not bounds.contains(result):
        raise InputRuleError(bounds.sentence(label))
    return result


def ordered_pair(low: float | None, high: float | None, low_label: str, high_label: str) -> None:
    """A (min, max) pair: min > max is refused with one sentence naming both."""
    if low is not None and high is not None and low > high:
        raise InputRuleError(
            f"{low_label}（{_fmt(low)}）不能大於{high_label}（{_fmt(high)}）。")


def date_order(start, end, start_label: str = "開始日", end_label: str = "結束日") -> None:
    """End ``>=`` start; either side unset passes. Accepts ``date`` or ISO ``YYYY-MM-DD`` text.
    When only one side is patched the caller passes the stored other side."""
    if _empty(start) or _empty(end):
        return
    s = start if isinstance(start, date) else date.fromisoformat(str(start)[:10])
    e = end if isinstance(end, date) else date.fromisoformat(str(end)[:10])
    if e < s:
        raise InputRuleError(f"{end_label}不能早於{start_label}。")


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------

KIND_LABELS = {
    "image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WebP", "image/gif": "GIF",
    "video/mp4": "MP4", "video/quicktime": "MOV",
}

_MP4_BRANDS = {
    b"isom", b"iso2", b"iso5", b"iso6", b"mp41", b"mp42", b"avc1", b"M4V ", b"MSNV", b"dash",
}


def _png_header_ok(content: bytes) -> bool:
    # First chunk must be IHDR: length 13, CRC over type+data, width/height > 0.
    length, ctype = struct.unpack(">I4s", content[8:16])
    data, crc = content[16:29], content[29:33]
    if length != 13 or ctype != b"IHDR" or len(crc) != 4:
        return False
    width, height = struct.unpack(">II", data[:8])
    return (zlib.crc32(ctype + data) == struct.unpack(">I", crc)[0]
            and width > 0 and height > 0)


_JPEG_SOF = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


def _jpeg_header_ok(content: bytes) -> bool:
    # Walk the marker segments up to the first SOFn and read its height/width.
    i = 2
    while i + 4 <= len(content):
        if content[i] != 0xFF:
            return False
        marker = content[i + 1]
        if marker == 0xFF:  # fill byte
            i += 1
            continue
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:  # standalone markers
            i += 2
            continue
        if marker in (0xD9, 0xDA):  # end of image / scan data before any frame header
            return False
        (length,) = struct.unpack(">H", content[i + 2:i + 4])
        if length < 2:
            return False
        if marker in _JPEG_SOF:
            if length < 7 or i + 9 > len(content):
                return False
            height, width = struct.unpack(">HH", content[i + 5:i + 9])
            return height > 0 and width > 0
        i += 2 + length
    return False


def _webp_header_ok(content: bytes) -> bool:
    # RIFF size must fit the bytes sent; the first chunk is VP8 / VP8L / VP8X with dimensions.
    (riff_size,) = struct.unpack("<I", content[4:8])
    if riff_size < 4 or 8 + riff_size > len(content):
        return False
    fourcc, (chunk_size,) = content[12:16], struct.unpack("<I", content[16:20])
    payload = content[20:20 + chunk_size]
    if fourcc == b"VP8 ":
        if len(payload) < 10 or payload[3:6] != b"\x9d\x01\x2a":
            return False
        width, height = struct.unpack("<HH", payload[6:10])
        return width & 0x3FFF > 0 and height & 0x3FFF > 0
    if fourcc == b"VP8L":  # dimensions are stored minus one, so always > 0
        return len(payload) >= 5 and payload[0] == 0x2F
    if fourcc == b"VP8X":  # canvas size stored minus one
        return len(payload) >= 10
    return False


def _gif_header_ok(content: bytes) -> bool:
    width, height = struct.unpack("<HH", content[6:10])
    return width > 0 and height > 0


def _header_ok(check, content: bytes) -> bool:
    try:
        return check(content)
    except (struct.error, IndexError):  # truncated header
        return False


def sniff(content: bytes) -> str | None:
    """The media type the bytes really are, or ``None``. Images must also carry a readable
    header (dimensions > 0, PNG IHDR CRC) so a signature followed by junk is not an image."""
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png" if _header_ok(_png_header_ok, content) else None
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg" if _header_ok(_jpeg_header_ok, content) else None
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp" if _header_ok(_webp_header_ok, content) else None
    if content[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif" if _header_ok(_gif_header_ok, content) else None
    if content[4:8] == b"ftyp":
        brand = content[8:12]
        if brand == b"qt  ":
            return "video/quicktime"
        if brand in _MP4_BRANDS:
            return "video/mp4"
    return None


def kinds_text(allowed) -> str:
    """``("image/jpeg", "image/png", "image/webp")`` -> 「JPEG、PNG 或 WebP」."""
    labels = [KIND_LABELS[m] for m in allowed]
    return labels[0] if len(labels) == 1 else "、".join(labels[:-1]) + " 或 " + labels[-1]


def check_image_upload(filename: str, content: bytes, allowed) -> str:
    """An uploaded image: refused when empty or when its content is not one of ``allowed``
    (the file name's extension is not consulted). Returns the sniffed media type to store."""
    name = filename or "檔案"
    if not content:
        raise InputRuleError(f"「{name}」是空的檔案，請換一個。")
    mime = sniff(content)
    if mime is None or mime not in allowed:
        raise InputRuleError(f"「{name}」的內容不是{kinds_text(allowed)} 圖片，請換一張。")
    return mime
