"""app/ads/result_kinds.py — F19-I06: the shared Chinese vocabulary for every ad's own "result"
kind (ARCHITECTURE.md §0 "程式整理，LLM 判斷" — this is a lookup table, not a judgment).

Platform-neutral: this file names no platform and imports no adapter. Adapters are the ones that
must stay inside this vocabulary, never the other way around -- `app/tests/test_ads_result_kinds.py`
enumerates every kind an adapter can actually produce (reading the adapter tables directly) and
asserts each one has a label here, so a new unlabelled kind fails that test.

Labels are Chinese nouns that fit the fixed sentence shape "每次<label>成本" everywhere the app
prints a per-result cost (`app/ads/routes.py`, `frontend/src/components/ads/target/
CampaignTargetPage.tsx`) -- never a verb, never a platform-specific phrase.
"""

LABELS: dict[str, str] = {
    "purchase": "購買",
    "engagement": "互動",
    "link_click": "點擊",
    "lead": "名單",
    "app_install": "安裝",
    "video_view": "觀看",
    "message": "訊息",
    "store_visit": "到店",
}

_GENERIC = "成果"


def label(kind: str | None) -> str:
    """Unknown or `None` -> the generic "成果", never a raw code."""
    if kind is None:
        return _GENERIC
    return LABELS.get(kind, _GENERIC)


def options() -> list[dict[str, str]]:
    """Stable order (dict insertion order) -- the target page's segmented control reads this
    list directly and never invents its own order or vocabulary."""
    return [{"kind": kind, "label": text} for kind, text in LABELS.items()]
