"""app/ads/wizard_options.py — F30-I04 (Contract B): what the new-campaign wizard can pick.

`options()` -> `{products: [{id, name, price|null, currency|null, thumbnail_url|null, has_cost}],
objectives: [objective]}`. Pure read, no model call, no write. Products and their economics and
photos come only through the `app.brand_intelligence.repository` facade (no new code there).

Product rules:
- Active only (archived products, and sell ways under an archived product, are left out), in
  the facade's name order.
- One product, many sell ways (ARCHITECTURE.md §8 item 1): money hangs off each sell way, so a
  product that has active sell ways is represented by those sell ways, not by itself; a product
  without sell ways is listed as it is.
- `price`/`currency`/`has_cost` come from the product's *current* economics only: a row whose
  window has not started or has already ended (`effective_to < today`, the same stale rule
  `brief.py` uses) is not current, so it yields `price=None` and `has_cost=False` -- never a
  stale price shown as today's. `has_cost` means the current unit variable cost is set; a
  confirmed row with no cost is `False`. "Today" is the organisation's own date.
- `thumbnail_url` is the newest `product_photo` official asset of the product that owns the
  knowledge (the parent for a sell way). It is the same authenticated same-origin file route
  the library uses (`/brands/{b}/assets/file/{asset}/{filename}`), so the browser loads it with
  the session token, not as a plain `<img>`; `None` when there is no photo.
"""

from pathlib import Path

from app.ads import objectives
from app.brand_intelligence import repository as bi_repo
from app.core import settings as coresettings

_PHOTO_KIND = "product_photo"


def _is_current(economics: dict, today) -> bool:
    start, end = economics.get("effective_from"), economics.get("effective_to")
    return (start is None or start <= today) and (end is None or end >= today)


def _thumbnails(conn, brand_id: str) -> dict:
    """knowledge product id -> newest photo URL (`list_official_assets` is newest first)."""
    urls: dict = {}
    for asset in bi_repo.list_official_assets(conn, brand_id):
        product_id = asset.get("product_id")
        if (asset.get("asset_kind") != _PHOTO_KIND or not product_id
                or asset.get("status") != "active" or product_id in urls):
            continue
        filename = Path(asset["storage_key"]).name
        urls[product_id] = f"/brands/{brand_id}/assets/file/{asset['id']}/{filename}"
    return urls


def sellable_products(conn, brand_id: str) -> list[dict]:
    """The products the wizard offers, in name order -- also the only ids a structured create
    accepts (`brief._check_picks`), so the list and the create can never disagree."""
    return _sellable(bi_repo.list_products(conn, brand_id))


def _sellable(products: list[dict]) -> list[dict]:
    active = [p for p in products if p.get("status") == "active"]
    active_ids = {p["id"] for p in active}
    parents_with_sell_ways = {p["parent_id"] for p in active if p.get("parent_id")}
    return [
        p for p in active
        if (p.get("parent_id") is None or p["parent_id"] in active_ids)
        and p["id"] not in parents_with_sell_ways
    ]


def _product_option(conn, brand_id: str, product: dict, today, thumbnails: dict) -> dict:
    economics = bi_repo.get_product_economics(conn, brand_id, product["id"])
    current = economics if economics is not None and _is_current(economics, today) else None
    price = current.get("selling_price") if current else None
    return {
        "id": product["id"],
        "name": product["name"],
        "price": float(price) if price is not None else None,
        "currency": current.get("currency") if current else None,
        "thumbnail_url": thumbnails.get(product.get("parent_id") or product["id"]),
        "has_cost": bool(current) and current.get("unit_variable_cost") is not None,
    }


def options(conn, org_id: str, brand_id: str) -> dict:
    today = coresettings.today_for_org(conn, org_id=org_id)
    thumbnails = _thumbnails(conn, brand_id)
    products = [
        _product_option(conn, brand_id, product, today, thumbnails)
        for product in sellable_products(conn, brand_id)
    ]
    return {"products": products, "objectives": objectives.catalog()}
