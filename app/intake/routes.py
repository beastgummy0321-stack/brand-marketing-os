"""Legacy intake page routes are removed; only photo-file delivery remains.

Public entry point: ``router``. Input/output: the photo GET endpoint accepts a
brand ID and filename, returns the registered photo file, and preserves existing
404 behavior. Consumer: ``app/main.py``. This module does not import or modify
routes_api, repositories, business logic, or methodology.
"""

from fastapi import APIRouter, Request
from fastapi.responses import Response

import app.shared.web as main_mod
from app import storage
from app.intake import state

router = APIRouter()


def _draft_or_404(brand_id: str) -> dict:
    return state.require_draft(brand_id, conn=main_mod.conn)


@router.get("/brands/{brand_id}/intake/photos/{filename}")
def intake_photo(request: Request, brand_id: str, filename: str):
    """Return only a photo registered for the brand's active intake draft."""
    actor = main_mod.require_actor(request)
    main_mod.require_brand(brand_id, actor)
    draft = _draft_or_404(brand_id)
    entry = next((p for p in (draft.get("photos") or []) if p.get("name") == filename), None)
    if entry is None or not entry.get("storage_key"):
        raise main_mod.NotFoundKind("\u9019\u5f35\u7167\u7247")
    content, content_type = storage.get(org_id=actor.org_id, key=entry["storage_key"])
    return Response(content=content, media_type=content_type)
