"""app/ads/actual_format.py — F46 Contract F: the format that ships is the uploaded file's.

A slot holds one file, so what goes out is decided by that file alone: a `video/*` original is a
video, any other file a single image (a carousel planned with one file ships as a single image).
One reader, ads-private: the learning coordinates (`live_creative.learning_coordinates`), the
launch handoff list's 「格式」 row (`launch_view`) and the slot's `format_note` (`slots`) all ask
here. The planned `format_key` stays the plan; this module never writes it.
"""

from app.ads import repository as ads_repo
from app.ads import user_assets_repository as user_assets

VIDEO = "video"
SINGLE_IMAGE = "single_image"
CAROUSEL = "carousel"


def of_asset(asset: dict | None) -> str | None:
    """`video` for a `video/*` original, `single_image` for any other file, None without one."""
    if asset is None:
        return None
    mime = str(asset.get("mime_type") or "").lower()
    return VIDEO if mime.startswith("video/") else SINGLE_IMAGE


def of_placement(conn, org, brand, campaign_id, placement_id, revision=None) -> str | None:
    """The actual format of a placement's original (`revision=None` = its current revision);
    None when the placement or its original cannot be read."""
    if not placement_id:
        return None
    try:
        placement = user_assets.placement(conn, org, brand, campaign_id, placement_id, revision)
        asset = user_assets.get_asset(conn, org, brand, placement["asset_id"])
    except ValueError:
        return None
    return of_asset(asset)


def of_ad(conn, org, brand, campaign_id, ad: dict) -> str | None:
    """The actual format of the ad's assigned material (`material_placement_id` at
    `material_placement_revision`); None for an ad with no material."""
    return of_placement(
        conn, org, brand, campaign_id,
        ad.get("material_placement_id"), ad.get("material_placement_revision"),
    )


def labels(conn, org, brand) -> dict:
    """`format` key -> the brand's own label (`coordinate_vocabulary`)."""
    return {
        row["key"]: row["label"]
        for row in ads_repo.coordinate_vocabulary(conn, org, brand)
        if row["dimension"] == "format"
    }


def label(key: str, names: dict) -> str:
    return names.get(key) or key


def note(planned_key: str | None, actual_key: str | None, names: dict) -> str | None:
    """The slot's sentence when what ships differs from the plan; None when equal or either is
    unknown. A carousel with one file reads as the prototype's sentence."""
    if not planned_key or not actual_key or planned_key == actual_key:
        return None
    if planned_key == CAROUSEL and actual_key == SINGLE_IMAGE:
        return "規劃是輪播，只放了 1 張圖，會以單圖上架"
    planned, actual = label(planned_key, names), label(actual_key, names)
    return f"規劃是{planned}，放的是{actual}，會以{actual}上架"
