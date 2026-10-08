"""app/core/input_rules.py — the one table of input rules at store time (F47 Contract A, F50
Contract I). This docstring is the rule list; a store calls these functions instead of keeping a
copy, and the browser sends what was typed and prints the sentence (decision 11).

Contract A: a store either keeps exactly what was sent or refuses with one Chinese sentence that
names the field. It never coerces: no negative -> 0, no 0 -> unset, no clamp. An optional value
sent empty / ``None`` means unset (blank is unknown, 0 is a real zero).

Rules (function — accepts — refusal, exact):

- number: ``number(v, label)`` — finite int / float / Decimal / numeric text (``1,280``); bool
  refused — 「{label}請填數字。」
- money > 0: ``positive`` — selling price, list price, cap per sale, settings spend cap and AI
  monthly limit — 「{label}要大於 0。」
- money >= 0: ``non_negative`` — cost, shipping, fixed cost, SKU unit cost, channel revenue —
  「{label}不能是負數。」
- declared range: ``within(v, label, Bounds)`` — inside the field's ``Bounds`` (rule cards) — the
  Bounds sentence.
- min <= max: ``ordered_pair`` — low <= high (``price`` <= ``list_price`` as 售價／原價) —
  「{low}（n）不能大於{high}（m）。」
- whole count: ``count(v, label, minimum=0)`` — int or integer text; bool refused —
  「{label}要是 {minimum} 以上的整數。」
- percent: ``percent(v, label)`` — ``0 < x <= 100`` (stored 0–100, ``close_rate``) —
  「{label}要大於 0、最多 100（填 20 代表 20%）。」
- percent -> multiplier: ``rate_fraction(pct)`` = ``pct / 100``, the one place a stored percent
  is scaled.
- ISO date: ``iso_date(v, label)`` — a ``date`` (a ``datetime`` gives its date) or
  ``YYYY-MM-DD`` text — 「{label}請用 YYYY-MM-DD 格式（例如 2026-10-05）。」
- end >= start: ``date_order`` — either side unset passes — 「{end}不能早於{start}。」
- date in a window: ``date_within(day, start, end, label, window_label)`` —
  ``start <= day <= end`` — 「{label}要在{window_label}（{start}～{end}）內。」
- enum: ``one_of(v, label, allowed)`` — a key of ``allowed`` (vocab lists go through
  ``vocab.require``) — 「{label}只能選：{labels joined by 、}。」
- URL: ``url(v, label)`` — trimmed; http／https; host with a dot or ``localhost``; no whitespace
  — 「{label}「{v}」不是完整的網址，請從 https:// 開始，例如 https://example.com。」
- URL list: ``urls(vs, label, max_count=)`` — each ``url()``, blanks skipped, at most
  ``max_count`` — 「最多填 {max_count} 個網址。」
- upload size: ``check_upload(name, size, path=)`` — ``0 < size <= UPLOAD_CAPS[path]`` (bytes,
  no rounding) — empty 「「{name}」是空的檔案，請換一個。」; oversize
  「「{name}」超過 {cap_mb} MB，請換一個小一點的檔案。」
- image content: ``check_image_upload`` — the sniffed type is one of ``allowed`` —
  「「{name}」的內容不是… 圖片，請換一張。」
- AI key: ``api_key(v)`` — trimmed, starts ``sk-ant-``, no whitespace —
  「AI 金鑰要以 sk-ant- 開頭，請從 Anthropic 主控台複製完整的一串。」

- uploads: one content sniff (JPEG, PNG, WebP, GIF, MP4, MOV signatures; images must also have a
  readable header with dimensions, stdlib only — no image library). Each upload path keeps
  its own allowed kinds; its size cap is ``UPLOAD_CAPS`` (brand photos 10 MiB — they are sent to
  the model; library and ad files 50 MiB — the Storage limit). Content wins over the file name (a
  real PNG named ``.jpg`` is accepted and stored as PNG).
- vendor files: an importer turns a vendor cell into a ``date`` (or leaves the text) and the store
  runs ``iso_date``; an unreadable date refuses that row with its reason, never a ``[:10]`` slice.

Every refusal is an ``InputRuleError`` (a ``ValueError``) whose text is the user sentence, so
routes that already map ``ValueError`` to 400 show it unchanged. This module imports nothing from
a managed module. Machine check: ``app/tests/test_input_rules_gate.py`` (backend) and
``frontend/src/lib/clientRules.test.ts`` (browser).
"""

from __future__ import annotations

import math
import re
import struct
import zlib
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import urlsplit


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


def count(value, label: str, *, minimum: int = 0, optional: bool = False) -> int | None:
    """A whole number ``>= minimum`` (a quantity). An int, an integral float or integer text;
    booleans and fractions are refused."""
    sentence = f"{label}要是 {minimum} 以上的整數。"
    if _empty(value):
        if optional:
            return None
        raise InputRuleError(sentence)
    if isinstance(value, bool):
        raise InputRuleError(sentence)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not re.fullmatch(r"[+-]?\d+", text):
            raise InputRuleError(sentence)
        result = int(text)
    elif isinstance(value, int):
        result = value
    elif isinstance(value, (float, Decimal)) and math.isfinite(value) and value == int(value):
        result = int(value)
    else:
        raise InputRuleError(sentence)
    if result < minimum:
        raise InputRuleError(sentence)
    return result


def percent(value, label: str, *, optional: bool = False) -> float | None:
    """A percent stored 0–100: ``0 < x <= 100`` (填 20 = 20%)."""
    sentence = f"{label}要大於 0、最多 100（填 20 代表 20%）。"
    try:
        result = number(value, label, optional=optional)
    except InputRuleError:
        raise InputRuleError(sentence) from None
    if result is not None and not 0 < result <= 100:
        raise InputRuleError(sentence)
    return result


def rate_fraction(pct) -> float:
    """A stored percent (0–100) as a multiplier — the one place the scale changes."""
    return float(pct) / 100


_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def iso_date(value, label: str, *, optional: bool = False) -> date | None:
    """A calendar date: a ``date`` (a ``datetime`` gives its date) or ``YYYY-MM-DD`` text."""
    sentence = f"{label}請用 YYYY-MM-DD 格式（例如 2026-10-05）。"
    if _empty(value):
        if optional:
            return None
        raise InputRuleError(sentence)
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and _ISO_DATE.fullmatch(value.strip()):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            pass
    raise InputRuleError(sentence)


def date_order(start, end, start_label: str = "開始日", end_label: str = "結束日") -> None:
    """End ``>=`` start; either side unset passes. Accepts ``date`` or ISO ``YYYY-MM-DD`` text.
    When only one side is patched the caller passes the stored other side."""
    if _empty(start) or _empty(end):
        return
    s = iso_date(start, start_label)
    e = iso_date(end, end_label)
    if s is not None and e is not None and e < s:
        raise InputRuleError(f"{end_label}不能早於{start_label}。")


def date_within(day, start, end, label: str, window_label: str) -> date:
    """``start <= day <= end`` (an ad set inside its campaign); an unset side is no bound."""
    d = iso_date(day, label)
    if d is None:  # not optional: iso_date has refused already
        raise InputRuleError(f"{label}請用 YYYY-MM-DD 格式（例如 2026-10-05）。")
    s = iso_date(start, window_label, optional=True)
    e = iso_date(end, window_label, optional=True)
    if (s is not None and d < s) or (e is not None and d > e):
        span = f"{s.isoformat() if s else ''}～{e.isoformat() if e else ''}"
        raise InputRuleError(f"{label}要在{window_label}（{span}）內。")
    return d


# ---------------------------------------------------------------------------
# Choices, URLs, keys
# ---------------------------------------------------------------------------

def one_of(value, label: str, allowed: Mapping[str, str]) -> str:
    """A key of ``allowed`` ({key: label}); the refusal lists the labels."""
    if isinstance(value, str) and value in allowed:
        return value
    raise InputRuleError(f"{label}只能選：{'、'.join(allowed.values())}。")


def url(value, label: str, *, optional: bool = False) -> str | None:
    """A full http(s) address: trimmed, a host with a dot (or ``localhost``), no whitespace."""
    text = value.strip() if isinstance(value, str) else ("" if value is None else str(value))
    if not text:
        if optional:
            return None
        raise InputRuleError(
            f"{label}「」不是完整的網址，請從 https:// 開始，例如 https://example.com。")
    sentence = f"{label}「{text}」不是完整的網址，請從 https:// 開始，例如 https://example.com。"
    credentials_message = f"{label}網址不可包含帳號或密碼，請使用公開頁面網址。"
    try:
        parsed = urlsplit(text)
        if parsed.username is not None or parsed.password is not None:
            raise InputRuleError(credentials_message)
    except ValueError:
        if "@" in text:
            raise InputRuleError(credentials_message) from None
    if any(c.isspace() for c in text):
        raise InputRuleError(sentence)
    try:
        parts = urlsplit(text)
        host = parts.hostname or ""
    except ValueError:
        raise InputRuleError(sentence) from None
    if parts.scheme not in ("http", "https") or not (
            host == "localhost" or ("." in host and not host.startswith(".")
                                    and not host.endswith("."))):
        raise InputRuleError(sentence)
    return text


def urls(values: Iterable | None, label: str, *, max_count: int) -> list[str]:
    """Each value through ``url()`` (blank rows skipped); at most ``max_count``."""
    kept: list[str] = []
    for v in values or []:
        checked = url(v, label, optional=True)
        if checked is not None:
            kept.append(checked)
    if len(kept) > max_count:
        raise InputRuleError(f"最多填 {max_count} 個網址。")
    return kept


API_KEY_PREFIX = "sk-ant-"


def api_key(value) -> str:
    """An Anthropic key: trimmed, starts ``sk-ant-``, no whitespace inside."""
    text = value.strip() if isinstance(value, str) else ""
    if (not text.startswith(API_KEY_PREFIX) or len(text) == len(API_KEY_PREFIX)
            or any(c.isspace() for c in text)):
        raise InputRuleError("AI 金鑰要以 sk-ant- 開頭，請從 Anthropic 主控台複製完整的一串。")
    return text


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------

_MIB = 1024 * 1024

# Size cap per upload path, in bytes (no rounding): brand photos are sent to the model
# (`app/llm/providers.py` image limit); library and ad files hit the Supabase Storage limit.
UPLOAD_CAPS = {
    "brand_photo": 10 * _MIB,
    "library_asset": 50 * _MIB,
    "ad_asset": 50 * _MIB,
}


def check_upload(name: str, size: int, *, path: str) -> None:
    """An upload's size: empty and oversize files get their own sentence."""
    shown = name or "檔案"
    if not size or size <= 0:
        raise InputRuleError(f"「{shown}」是空的檔案，請換一個。")
    cap = UPLOAD_CAPS[path]
    if size > cap:
        raise InputRuleError(f"「{shown}」超過 {cap // _MIB} MB，請換一個小一點的檔案。")

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
