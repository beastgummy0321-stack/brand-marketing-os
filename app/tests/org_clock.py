"""app/tests/org_clock.py — the one clock test fixtures date their rows with.

Not a test module itself (pytest only collects `test_*.py`). Fixtures whose date feeds a path
the product reads in the org's own calendar (a change set's `month`, the spend route's month
window, budget pacing) must ask the product's clock, `coresettings.today_for_org`, not the
machine's (`db.now_utc()`, `datetime.now(UTC).date()`): between 00:00 and 08:00 Taipei time
on a month's first day the UTC date is still last month, so a UTC-dated fixture lands one
month early and the test goes red for eight hours a month (F43-I17).

Event times (`settled_at`, created/updated timestamps) stay UTC; they are not dates in the
org's calendar and do not go through here.

Both helpers resolve `today_for_org` through the module attribute at call time, so a test
that patches `app.core.settings.today_for_org` moves the fixtures with the product.

Tests of a managed module (e.g. `test_ads_*.py`) may import only declared modules and legacy
facades (tools/check_architecture.py) and this file is not declared in the ARCHITECTURE
manifest, so those tests call the same clock through the facade directly:
`coresettings.today_for_org(conn, org_id=...)`.
"""

from datetime import date

from app.core import settings as coresettings


def org_today(conn, org_id: str) -> date:
    """The org's today, the same answer the product gets."""
    return coresettings.today_for_org(conn, org_id=org_id)


def org_month(conn, org_id: str) -> str:
    """The org's current month as ``"YYYY-MM"`` (the change-set `month` format)."""
    return org_today(conn, org_id).strftime("%Y-%m")
