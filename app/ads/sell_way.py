"""app/ads/sell_way.py — F44 (Contract A): the one place that answers 「which sell-way does this
campaign / this ad sell」. The campaign owns the sell-way (the first of its
`context_json.product_ids`); `ads_ad.product_id` is an optional per-ad override that nothing
fills at plan time. `budget._economics_for` (the first sell-way *with economics*) is a different
rule and stays where it is. Private to app/ads.
"""


def of_campaign(campaign: dict) -> str | None:
    """The campaign's sell-way id, or `None` for a campaign without a product (judged at brand
    level by its readers)."""
    product_ids = (campaign.get("context_json") or {}).get("product_ids") or []
    return product_ids[0] if product_ids else None


def of_campaign_id(conn, org_id: str, brand_id: str, campaign_id: str | None) -> str | None:
    """`of_campaign` for a caller that only holds the id (F48 Contract W: a change item or a
    settle row names its campaign by id). `None` for an unknown campaign or one without a
    product (an imported campaign)."""
    if not campaign_id:
        return None
    row = conn.execute(
        "SELECT context_json FROM ads_campaign WHERE org_id = %s AND brand_id = %s AND id = %s",
        (org_id, brand_id, campaign_id),
    ).fetchone()
    return of_campaign(dict(row)) if row is not None else None


def of_ad(ad: dict, campaign: dict) -> str | None:
    """The ad's sell-way id: its own `product_id` when set, else the campaign's."""
    return ad.get("product_id") or of_campaign(campaign)
