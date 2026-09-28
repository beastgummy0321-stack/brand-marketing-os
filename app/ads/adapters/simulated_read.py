"""app/ads/adapters/simulated_read.py — F37 Contract R: the simulated channel as a platform to
the sync pipeline. `channels.external_reader("simulated")` returns a `SimulatedReader`, so
「重新讀取平台」 (`POST …/campaigns/{c}/sync`) and the 05:00 `dispatch_daily` read a simulated
campaign the same way they read a real one -- no real/simulated branch in the core.

Only observations carry data: `read_observations` regenerates, through the one generator
`simulated.day_rows` and the one seed rule `simulated.day_rng`, exactly the rows publish-time
`generate_outcomes` wrote, so a re-read is an idempotent upsert. Structure, creatives, listing
and monthly reads have nothing to report (the chain is registered at publish) and answer with an
empty page. A closed campaign, or one whose numbers are user-typed during simulation recovery,
reads nothing -- those rows are never overwritten.
"""

from datetime import date, timedelta

from app.ads import repository as ads_repo
from app.ads.adapters import simulated
from app.ads.adapters.external import SourcePage, SourceReadError
from app.core import settings as coresettings

ACCOUNT_NAME = "模擬通路"
PAGE_SIZE = 100  # `external_sync._save_page` refuses a page of more than 100 nodes


def _day(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


class SimulatedReader:
    def accounts(self, conn, org_id, brand_id) -> list[dict]:
        return [{
            "account_id": simulated.SOURCE_ACCOUNT, "name": ACCOUNT_NAME,
            "currency": simulated.CURRENCY,
            "timezone_name": str(coresettings.org_timezone(conn, org_id=org_id)),
        }]

    def sync_scopes(self, conn) -> list[dict]:  # noqa: ARG002 — roots come from ads_external_entity
        return []

    def binding_kinds(self) -> tuple[str, ...]:
        return ()

    def verify_native(self, conn, org_id, brand_id, account, *, native_kind, native_id,
                      root_kind, root_id, original) -> dict:
        raise SourceReadError("模擬通路沒有可核對的平台物件。", "unsupported")

    def list_existing(self, conn, org_id, brand_id, account, **kwargs) -> SourcePage:
        return SourcePage([])

    def read_structure(self, conn, org_id, brand_id, account, **kwargs) -> SourcePage:
        return SourcePage([])

    def read_creatives(self, conn, org_id, brand_id, account, **kwargs) -> SourcePage:
        return SourcePage([])

    def pixels(self, conn, org_id, brand_id, account) -> list[dict]:
        # A simulated account has no tracking pixels; `launch_settings` shows this as unreadable.
        raise SourceReadError("模擬通路沒有可讀的像素。", "unsupported")

    def monthly_supported(self) -> bool:
        # No account-month spend proof exists for a simulated account, so the sync job asks
        # for no `monthly:` task (the month budget never lists this account: not in CHANNELS).
        return False

    def read_monthly(self, conn, org_id, brand_id, account, *, start, end, cursor=None,
                     **kwargs) -> SourcePage:
        return SourcePage([])

    def read_observations(self, conn, org_id, brand_id, account, *, native_id, start, end,
                          cursor=None, **kwargs) -> SourcePage:
        rows = _rows(conn, org_id, brand_id, native_id, _day(start), _day(end))
        offset = int((cursor or {}).get("offset") or 0)
        following = offset + PAGE_SIZE
        return SourcePage(
            rows[offset:following],
            cursor={"offset": following} if following < len(rows) else None,
        )


def _rows(conn, org_id, brand_id, native_id, start: date, end: date) -> list[dict]:
    root = conn.execute(
        "SELECT campaign_id FROM ads_external_entity WHERE org_id = %s AND brand_id = %s"
        " AND platform = %s AND source_account = %s AND native_id = %s"
        " AND parent_native_id IS NULL",
        (org_id, brand_id, simulated.PLATFORM, simulated.SOURCE_ACCOUNT, native_id),
    ).fetchone()
    if root is None:
        return []
    campaign_id = root["campaign_id"]
    detail = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)
    if detail is None or detail["status"] == "closed" or detail["start_date"] is None:
        return []
    if (detail.get("context_json") or {}).get("simulation_recovery"):
        return []
    last = min(end, coresettings.today_for_org(conn, org_id=org_id))
    if detail["end_date"] is not None:
        last = min(last, detail["end_date"])
    day = max(start, detail["start_date"])
    rows = []
    while day <= last:
        rows.extend(simulated.day_rows(detail, day, simulated.day_rng(campaign_id, day)))
        day += timedelta(days=1)
    return rows
