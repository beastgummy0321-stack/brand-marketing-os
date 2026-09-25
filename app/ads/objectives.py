"""app/ads/objectives.py — F30-I04 (Contract C): the one campaign-objective catalog.

One merged cross-platform list. `key` is the internal objective word stored in
`ads_campaign.objective`; `platforms` names the matching native objective on each ad platform
(`None` where the platform has no such objective). Only `available` objectives can be picked;
the reserved seats (互動, App 推廣, 來店) are listed so the wizard can show 「尚未開放」, never
built. 加購物車 is a Sales optimisation event, not an objective: still accepted from the model's
free-text parse (`ACCEPTED`), never listed. Grading families stay in
`repository.objective_family` -- this table does not change how a campaign is judged.

Private to app/ads (container contract §1): `brief.py`, `wizard_options.py` and `routes.py`.
"""

from app.ads import channels

# The catalog records the objective vocabulary of the first two registry channels (the two ad
# platforms whose objective lists are known); their keys come from the registry, never a
# platform-name literal here (§0: platform names only live in channels.py).
_PLATFORM_KEYS = tuple(c["key"] for c in channels.CHANNELS[:2])

# (key, description, available, (platform-0 label, platform-1 label))
_ROWS = (
    ("購買", "看每賣一筆花多少", True, ("銷售業績", "銷售")),
    ("名單", "看每筆名單成本", True, ("潛在顧客", "潛在客戶")),
    ("流量", "看每次點進網站花多少", True, ("流量", "網站流量")),
    ("知名度", "看多少人看到", True, ("知名度", "品牌認知度和觸及率")),
    ("互動", "看每次互動成本", False, ("互動", "YouTube 觸及、觀看與互動")),
    ("App 推廣", "看每次安裝成本", False, ("應用程式推廣", "應用程式推廣")),
    ("來店", "看來店人數", False, (None, "來店客數與本地推廣")),
)

CATALOG: tuple[dict, ...] = tuple(
    {
        "key": key, "label": key, "description": description, "available": available,
        "platforms": dict(zip(_PLATFORM_KEYS, labels, strict=True)),
    }
    for key, description, available, labels in _ROWS
)

# Accepted but unlisted: a Sales optimisation event the free-text parse may still return.
_UNLISTED_ACCEPTED = ("加購物車",)

AVAILABLE = frozenset(row["key"] for row in CATALOG if row["available"])
RESERVED = frozenset(row["key"] for row in CATALOG if not row["available"])
ACCEPTED = AVAILABLE | frozenset(_UNLISTED_ACCEPTED)


def catalog() -> list[dict]:
    """A fresh copy of the catalog, in display order (callers may mutate their copy)."""
    return [{**row, "platforms": dict(row["platforms"])} for row in CATALOG]


def label(key: str) -> str:
    return next((row["label"] for row in CATALOG if row["key"] == key), key)


def check(key) -> str:
    """Validate a picked objective. Returns the key; raises `ValueError` with
    `objective_unavailable` for a reserved seat, `objective_unknown` for anything else not
    accepted."""
    if isinstance(key, str) and key in ACCEPTED:
        return key
    if isinstance(key, str) and key in RESERVED:
        raise ValueError("objective_unavailable")
    raise ValueError("objective_unknown")
