"""app/ads/wizard_options.py — F30-I04 (Contract B), re-cut by F43-I04: what the new-campaign
wizard can pick.

`options()` -> `{products: [option], objectives: [objective], default_objective: key|null}`, one
option per finished sell-way:
`{id, name, display_name, kind ("single" | "bundle"), knowledge_product_id,
knowledge_product_name, price|null, currency|null, has_cost, break_even|null, cap_per_sale|null,
offer_labels, customer_groups [{id, who}], landing_url|null, thumbnail_url|null}`. Pure read, no
model call, no write. Sell-ways, their economics, groups, offers and photos come only through the
`app.brand_intelligence.repository` facade.

Pickable rule (F43 「only sell-ways are pickable」, `sellable_products`):
- a sell-way of `list_sell_ways` (a row with components, or an F05 sell-way under its product);
  a knowledge product itself is never offered;
- the sell-way is active and every one of its knowledge products (`knowledge_product_ids`) is
  active and finished (`onboarding_step` NULL) -- a 建到一半 product's sell-ways are left out;
- order: single sell-ways grouped by knowledge product (its name order; the `#/new` section
  header), each group in creation order; then bundles in creation order.

Numbers:
- `price`/`currency`/`has_cost`/`break_even` come from the sell-way's *current* effective economics
  only (`get_product_economics`: a bundle's NULL cost is Σ its components); a row whose window has
  not started or has already ended (`effective_to < today`, the same stale rule `brief.py` uses)
  is not current -> `None`/`False`, never a stale price shown as today's. "Today" is the
  organisation's own date. `break_even` is `budget.breakeven_cpa` (the one formula).
- `cap_per_sale` is effective: the sell-way's own cap, else its break-even (`None` when neither).
- `offer_labels` = the offers `offer_sources` finds for the sell-way (the rule behind
  `available_offer_keys`): its own price offer as 「組合價」 (more than one unit) / 「優惠價」, then
  each brand policy's offer word (「免運」…), each once.
- `landing_url` = the sell-way's effective landing (its own, else the first product's page).
- `default_objective` (F43-I18) = the brand's `conversion_goal` through
  `objectives.for_conversion_goal` (`None` when unset: no preselection).
- `thumbnail_url` is the newest `product_photo` official asset of the first knowledge product that
  has one -- the authenticated same-origin file route the library uses
  (`/brands/{b}/assets/file/{asset}/{filename}`); `None` when there is no photo.
"""

from pathlib import Path

from app.ads import objectives
from app.ads.budget import breakeven_cpa
from app.brand_intelligence import repository as bi_repo
from app.core import settings as coresettings
from app.core import vocab

_PHOTO_KIND = "product_photo"
_OWN_OFFER_WORDS = {"bundle": "組合價", "discount": "優惠價"}


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
    """The finished sell-ways the wizard offers, in the wizard's order (module docstring) -- also
    the only ids a structured create accepts (`brief._check_picks`), so the list and the create
    can never disagree. Each item is the `list_sell_ways` item plus `knowledge_products` (the
    product rows of `knowledge_product_ids`, in order)."""
    products = {p["id"]: p for p in bi_repo.list_products(conn, brand_id)}
    out = []
    for way in bi_repo.list_sell_ways(conn, brand_id):
        if way.get("status") != "active" or way.get("onboarding_step") is not None:
            continue
        knowledge = [products.get(pid)
                     for pid in bi_repo.knowledge_product_ids(conn, brand_id, way["id"])]
        if not knowledge or any(
            p is None or p.get("status") != "active" or p.get("onboarding_step") is not None
            for p in knowledge
        ):
            continue
        out.append({**way, "knowledge_products": knowledge})
    # Stable sort: creation order is kept inside each group.
    return sorted(out, key=lambda w: (w["kind"] == "bundle",
                                      "" if w["kind"] == "bundle"
                                      else w["knowledge_products"][0]["name"]))


def customer_groups(conn, brand_id: str, sell_way: dict) -> list[dict]:
    """Every customer group of the sell-way's knowledge products (product order, then position)
    -- the campaign's default audience (`brief`) and the wizard's list."""
    return [group for product in sell_way["knowledge_products"]
            for group in bi_repo.list_customer_groups(conn, brand_id, product["id"])]


def product_customer_groups(conn, brand_id: str, product_ids: list[str]) -> list[dict]:
    """F43-I18: every customer group behind a campaign's `context_json.product_ids` -- the
    knowledge products of each (`knowledge_product_ids`, each once), then their groups in
    position order. For a pickable sell-way this equals `customer_groups` (same resolver); it
    also answers for a row that is not pickable (an old campaign's product)."""
    knowledge_ids: list[str] = []
    for product_id in product_ids:
        for knowledge_id in bi_repo.knowledge_product_ids(conn, brand_id, product_id):
            if knowledge_id not in knowledge_ids:
                knowledge_ids.append(knowledge_id)
    return customer_groups(conn, brand_id, {"knowledge_products": [
        {"id": knowledge_id} for knowledge_id in knowledge_ids
    ]})


def _offer_labels(conn, brand_id: str, sell_way_id: str) -> list[str]:
    policy_sentences = {p["sentence"] for p in bi_repo.list_brand_policies(conn, brand_id)
                        if p["status"] == "confirmed"}
    own, policies = [], []
    for row in bi_repo.offer_sources(conn, brand_id, sell_way_id):
        if row["sentence"] in policy_sentences:
            policies.append(vocab.offer_label(row["offer_key"]))
        else:  # the sell-way's own price offer (list price above price)
            own.append(_OWN_OFFER_WORDS.get(row["offer_key"], vocab.offer_label(row["offer_key"])))
    return list(dict.fromkeys(own + policies))


def _product_option(conn, brand_id: str, way: dict, today, thumbnails: dict) -> dict:
    economics = way.get("economics")
    current = economics if economics is not None and _is_current(economics, today) else None
    price = current.get("selling_price") if current else None
    break_even = breakeven_cpa(current)
    own_cap = current.get("cap_per_sale") if current else None
    first = way["knowledge_products"][0]
    return {
        "id": way["id"],
        "name": way["name"],
        "display_name": way["display_name"],
        "kind": way["kind"],
        "knowledge_product_id": first["id"],
        "knowledge_product_name": first["name"],
        "price": float(price) if price is not None else None,
        "currency": current.get("currency") if current else None,
        "has_cost": bool(current) and current.get("unit_variable_cost") is not None,
        "break_even": float(break_even) if break_even is not None else None,
        "cap_per_sale": float(own_cap) if own_cap is not None else (
            float(break_even) if break_even is not None else None),
        "offer_labels": _offer_labels(conn, brand_id, way["id"]),
        "customer_groups": [{"id": g["id"], "who": g["who"]}
                            for g in customer_groups(conn, brand_id, way)],
        "landing_url": way.get("effective_landing_url"),
        "thumbnail_url": next((thumbnails[p["id"]] for p in way["knowledge_products"]
                               if p["id"] in thumbnails), None),
    }


def options(conn, org_id: str, brand_id: str) -> dict:
    today = coresettings.today_for_org(conn, org_id=org_id)
    thumbnails = _thumbnails(conn, brand_id)
    products = [
        _product_option(conn, brand_id, way, today, thumbnails)
        for way in sellable_products(conn, brand_id)
    ]
    brand = bi_repo.get_brand(conn, brand_id) or {}
    return {
        "products": products, "objectives": objectives.catalog(),
        "default_objective": objectives.for_conversion_goal(brand.get("conversion_goal")),
    }
