"""Fallback benchmark values for "I don't know" onboarding fields.

Evidence file: `.harness/scratch/research-onboarding.md` — every value below was
verified line by line against a primary source, including the ones that turned
out to have none (shipping cost).

Taiwan has no citable primary-source figure for any of these: ECPay's numbers
are themselves attributed to US WordStream data, and SHOPLINE/91APP/agency blog
posts carry no methodology. So all three values here are overseas figures, and
the screen must say so out loud rather than pretend otherwise.

The model never supplies these numbers. The honest replacement path is this
brand's own closed-loop results (F06), not a nicer-looking blog post.

Scale (F50 Contract I, decision 9): a rate is served as the percent a user would type -- gross
margin 45, close rate 20, `unit: "%"`; a multiplier goes through `input_rules.rate_fraction`.
The gross margin is also the one assumed margin default: the `gross_margin` rule card's default
(`app/core/rule_cards.py`) is this value, pinned by `app/tests/test_benchmarks.py`.
"""

BENCHMARKS = {
    "gross_margin": {
        "key": "gross_margin",
        "value": 45,
        "unit": "%",
        "label": "毛利率假設 45%",
        "note": "美國 2025 基準，起點用",
        "source": (
            "NYU Stern Damodaran《Margins by Sector》，"
            "資料日 2026-01（美國上市公司分業毛利率）"
        ),
        "source_url": "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/margin.html",
        "fetched_at": "2026-09-14",
    },
    "shipping_cost": {
        "key": "shipping_cost",
        "value": 80,
        "unit": "TWD",
        "label": "運費 NT$80",
        "note": "常見值，屬本站慣例",
        "source": None,  # 本站慣例；畫面上不准寫「來源：…」
        "source_url": None,
        "fetched_at": "2026-09-14",
    },
    "close_rate": {
        "key": "close_rate",
        "value": 20,
        "unit": "%",
        "label": "成交率假設 20%",
        "note": "海外平均，非台灣",
        "source": "HubSpot 2024 銷售調查：全業平均成交率 20%",
        "source_url": "https://blog.hubspot.com/sales/new-sales-close-rate-industry-benchmarks-how-does-your-close-rate-compare",
        "fetched_at": "2026-09-14",
    },
}


def get(key: str) -> dict:
    """Return the benchmark record for `key`, or raise if unknown."""
    try:
        return BENCHMARKS[key]
    except KeyError:
        raise KeyError(f"no benchmark for {key!r}") from None


def source_text(key: str) -> str:
    """The single place that composes the screen's benchmark sentence."""
    record = get(key)
    label = record["label"]
    note = record["note"]
    source = record["source"]
    if source is None:
        return f"{label} · {note}，之後可以再改"
    return f"{label} · {note} · 來源：{source}"
