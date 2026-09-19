"""Fail-closed policy for the Meta HTTP boundary, including legacy pagination.

An HTTP GET is not sufficient: Graph accepts method overrides and arbitrary edges.
Only the reads used by this package are permitted. Account/brand authorization stays
in the repository; this policy does not grant access to another account.
"""

import json
import re
from urllib.parse import parse_qsl, urlsplit

_PATH = re.compile(
    r"(?:me/adaccounts|act_[0-9]+/(?:campaigns|insights)|[0-9]+(?:/(?:adsets|ads|insights))?)"
)
_PARAMS = {
    "fields", "limit", "after", "before", "__paging_token", "level",
    "time_increment", "time_range", "action_attribution_windows", "effective_status",
}
_FIELDS = set(
    "id account_id name currency timezone_name objective effective_status status configured_status "
    "start_time stop_time "
    "end_time daily_budget lifetime_budget campaign_id campaign_name adset_id adset_name "
    "ad_id ad_name account_currency date_start date_stop spend impressions clicks purchase_roas "
    "actions action_values created_time updated_time creative body title image_hash image_url "
    "video_id thumbnail_url object_story_spec asset_feed_spec product_set_id".split()
)
_CURSORS = {"after", "before", "__paging_token"}
_JSON_PARAMS = {"time_range", "action_attribution_windows", "effective_status"}
_DENIED = "這項平台請求不符合唯讀範圍，未送出。"


class ReadPolicyError(ValueError):
    """Contains no provider URL, request value or credential."""


def _reject():
    raise ReadPolicyError(_DENIED)


def _fields_valid(value: str) -> bool:
    # No Graph modifiers, aliases or arbitrary field expansion. Parse nesting rather
    # than merely rejecting a few known mutation words.
    tokens = re.findall(r"[a-z_]+|[{},]", value)
    if "".join(tokens) != value or not tokens or value.count("{") > 8:
        return False
    pos = 0

    def fields(nested=False):
        nonlocal pos
        while pos < len(tokens):
            if tokens[pos] not in _FIELDS:
                return False
            pos += 1
            if pos < len(tokens) and tokens[pos] == "{":
                pos += 1
                if not fields(True):
                    return False
            if pos == len(tokens):
                return not nested
            if nested and tokens[pos] == "}":
                pos += 1
                return True
            if tokens[pos] != ",":
                return False
            pos += 1
        return False

    return fields() and pos == len(tokens)


def prepare_read(url: str, params: dict | None, headers: dict, base_url: str):
    """Return canonical URL, safe query and headers; never send credentials in URLs."""
    if not isinstance(url, str) or len(url) > 32768 or any(ord(c) < 33 for c in url):
        _reject()
    try:
        parsed, base = urlsplit(url), urlsplit(base_url)
        if (
            parsed.scheme != "https" or parsed.netloc != "graph.facebook.com"
            or parsed.fragment or not parsed.path.startswith(base.path + "/")
            or not _PATH.fullmatch(parsed.path[len(base.path) + 1:])
        ):
            _reject()
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True,
                          max_num_fields=30)
    except ValueError:
        raise ReadPolicyError(_DENIED) from None
    if not isinstance(headers, dict) or set(headers) != {"Authorization"}:
        _reject()
    auth = headers["Authorization"]
    if (not isinstance(auth, str) or not auth.startswith("Bearer ") or len(auth) <= 7
            or any(ord(c) < 33 or ord(c) == 127 for c in auth[7:])):
        _reject()
    if params is not None and not isinstance(params, dict):
        _reject()
    query = {}
    for key, value in [*pairs, *(params or {}).items()]:
        if key in query or not isinstance(key, str):
            _reject()
        if key == "access_token":
            # Meta's paging URL may echo the credential. Authenticate using the
            # existing header only; a different credential is never accepted.
            if value != auth[7:] or key in query:
                _reject()
        elif key not in _PARAMS:
            _reject()
        if type(value) not in (str, int):
            _reject()
        value = str(value)
        if not value or len(value) > 8192 or any(ord(c) < 32 or ord(c) == 127 for c in value):
            _reject()
        query[key] = value
    query.pop("access_token", None)
    for key, value in query.items():
        if key == "fields" and not _fields_valid(value):
            _reject()
        if key in _CURSORS and len(value) > 4096:
            _reject()
        if key == "limit" and (not value.isascii() or not value.isdigit()
                               or not 1 <= int(value) <= 200):
            _reject()
        if key == "level" and value not in {"campaign", "adset", "ad"}:
            _reject()
        if key == "time_increment" and value != "1":
            _reject()
        if key in _JSON_PARAMS:
            try:
                parsed_value = json.loads(value)
            except ValueError:
                raise ReadPolicyError(_DENIED) from None
            if key == "time_range":
                if (not isinstance(parsed_value, dict) or set(parsed_value) != {"since", "until"}
                        or any(not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v)
                               for v in parsed_value.values())):
                    _reject()
            elif (not isinstance(parsed_value, list) or len(parsed_value) > 20
                  or any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_]+", v)
                         for v in parsed_value)):
                _reject()
    return f"https://graph.facebook.com{parsed.path}", query, {"Authorization": auth}


def next_read_page(url, params, next_url, headers, base_url):
    """Pin pagination to the original read; only cursor values may change."""
    safe_url, original, _ = prepare_read(url, params, headers, base_url)
    next_path, following, _ = prepare_read(next_url, None, headers, base_url)
    if next_path != safe_url:
        _reject()
    for key, value in following.items():
        if key in _CURSORS:
            continue
        if key not in original:
            _reject()
        # Meta may serialize JSON without spaces or with a different object-key
        # order. Keep the original request, accepting equivalent values only.
        same = (json.loads(original[key]) == json.loads(value)
                if key in _JSON_PARAMS else original[key] == value)
        if not same:
            _reject()
    cursors = {key: value for key, value in following.items() if key in _CURSORS}
    if not cursors or cursors == {key: value for key, value in original.items() if key in _CURSORS}:
        _reject()
    return safe_url, {**{k: v for k, v in original.items() if k not in _CURSORS}, **cursors}


def safe_response(body):
    """Provider errors may echo a URL/token. Retain a numeric code, never raw text."""
    if not isinstance(body, dict):
        raise ReadPolicyError("Meta 回了看不懂的內容，請稍後再試。")
    if "error" not in body:
        return body
    error = body["error"]
    code = error.get("code") if isinstance(error, dict) else None
    code = code if type(code) is int else None
    label = code if code is not None else "未知"
    return {"error": {"code": code, "message": f"平台無法讀取此資料（代碼 {label}）。"}}
