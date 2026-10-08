"""Private, read-only coordinate vocabulary shared by workbench's DB consumers.

Schedule owns vocabulary seeding. This admitted read duplicates its query without
importing schedule or creating coordinates as a side effect of prompt construction.
"""

from app.core.db import Conn, ConnProxy


def list_coordinate_vocabulary(conn: Conn | ConnProxy, org_id: str, brand_id: str) -> list:
    """Keep the existing scope, ordering and rejection projection for both readers."""
    rows = conn.execute(
        "SELECT c.*, EXISTS (SELECT 1 FROM feedback f WHERE f.scope = 'coordinate'"
        " AND f.coordinate_id = c.id AND f.lifted_at IS NULL) AS rejected"
        " FROM brand_coordinate c WHERE c.org_id = %s AND c.brand_id = %s"
        " ORDER BY c.dimension, c.category NULLS LAST, c.label",
        (org_id, brand_id),
    ).fetchall()
    return [
        {"dimension": r["dimension"], "key": r["key"], "label": r["label"],
         "attributes": r["attributes_json"] or {}, "disabled_at": r["disabled_at"],
         "rejected": bool(r["rejected"])}
        for r in (dict(row) for row in rows)
    ]
