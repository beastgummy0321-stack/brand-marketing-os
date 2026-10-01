"""scripts/drill/site.py — frozen copy of beastprime.com.tw for the AI prefill (drill 9).

    .venv/Scripts/python.exe -m scripts.drill.site build .harness/scratch/drill9/site_raw_20261001

`build` turns raw HTML (fetched 2026-10-01) into the plain text `app.core.net.fetch_url` would
extract, minus what the 2026-09-26 records cannot back (docs/drills/drill-9/plan.md §1), and
writes `scripts/drill/site/<page>.txt`. `install()` points every module-level `fetch_url` the
prefill uses at those files: https://beastprime.com.tw/<path> → the matching page, any other
URL → unreadable. The persona types and the product stores the real URLs. Drill only.
"""

import pathlib
import sys
import urllib.parse

SITE_DIR = pathlib.Path(__file__).with_name("site")
HOST = "beastprime.com.tw"

# raw file stem → served page key
PAGES = {
    "home": "home",
    "pages_about-us": "pages/about-us",
    "pages_refund-policy": "pages/refund-policy",
    "products_beast-gummy-trial-pack-3-pieces": "products/beast-gummy-trial-pack-3-pieces",
    "products_beast-gummy-value-bundle-3-boxes": "products/beast-gummy-value-bundle-3-boxes",
    "products_beast-gummy-ultimate-bundle-5-boxes-2-packs": "products/beast-gummy-ultimate-bundle-5-boxes-2-packs",
    "products_beast-gummy-12-box-collectors-bundle-tshirt": "products/beast-gummy-12-box-collectors-bundle-tshirt",
    "products_beast-prime-danny-1st-anniversary-collaboration-tshirt":
        "products/beast-prime-danny-1st-anniversary-collaboration-tshirt",
}

# Not in the 2026-09-26 records (user ruling 2026-10-01: strip all three).
STRIP = [
    "新東西不敢嘗試？ 聯繫我們，免費給您試用包！ 點擊體驗·極致效率 ",
    "科學證實口腔微血管吸收更快速[1]， 避免如傳統提神產品的作用時間過長。 ",
    "4. 科學證實：口腔咀嚼快速吸收",
]
REPLACE_WITH = {"4. 科學證實：口腔咀嚼快速吸收": "4. 口腔咀嚼快速吸收"}
FORBIDDEN = ["爆能", "試用包", "科學證實", "[1]"]


def _key(url: str) -> str | None:
    parts = urllib.parse.urlsplit(url.strip())
    if parts.hostname not in (HOST, "www." + HOST):
        return None
    path = urllib.parse.unquote(parts.path).strip("/")
    if not path:
        return "home"
    if "/products/" in "/" + path:  # collections/<c>/products/<slug> → products/<slug>
        path = "products/" + ("/" + path).rsplit("/products/", 1)[-1].split("/")[0]
    return path


def fetch_url(url: str) -> tuple:
    from app.core import net

    key = _key(url)
    page = SITE_DIR / f"{key.replace('/', '_')}.txt" if key else None
    if page is None or not page.exists():
        return False, ""
    return True, page.read_text(encoding="utf-8")[: net.URL_EXCERPT_CHARS]


def install() -> None:
    import app.brand_web.product_ai_calls
    import app.intake.ai
    import app.intake.product_prefill

    for mod in (app.intake.ai, app.intake.product_prefill, app.brand_web.product_ai_calls):
        mod.fetch_url = fetch_url


def build(raw_dir: str) -> None:
    from app.core import net

    SITE_DIR.mkdir(exist_ok=True)
    for stem, key in PAGES.items():
        raw = (pathlib.Path(raw_dir) / f"{stem}.html").read_text(encoding="utf-8", errors="replace")
        extractor = net._TextExtractor()
        extractor.feed(raw)
        text = " ".join(extractor.chunks)
        for s in STRIP:
            text = text.replace(s, REPLACE_WITH.get(s, ""))
        left = [w for w in FORBIDDEN if w in text]
        assert not left, f"{stem}: still has {left}"
        (SITE_DIR / f"{key.replace('/', '_')}.txt").write_text(text, encoding="utf-8")
        print(f"{key}: {len(text)} chars")


if __name__ == "__main__":
    if sys.argv[1:2] == ["build"]:
        build(sys.argv[2])
    else:
        raise SystemExit(__doc__)
