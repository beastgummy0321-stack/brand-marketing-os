"""Persistent, organisation-scoped isolation marker for local simulation brands."""

from app.core import settings

MESSAGE = "這是隔離模擬品牌，不能使用真實平台配對或成效回收。"


def enabled(conn, org_id: str, brand_id: str) -> bool:
    return settings.get_setting(conn, f"ads_simulation_brand:{brand_id}", org_id=org_id) == "1"


def lock(conn, org_id: str, brand_id: str) -> None:
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (f"ads-simulation:{org_id}:{brand_id}",),
    )


def require_real(conn, org_id: str, brand_id: str) -> None:
    lock(conn, org_id, brand_id)
    if enabled(conn, org_id, brand_id):
        raise ValueError(MESSAGE)
