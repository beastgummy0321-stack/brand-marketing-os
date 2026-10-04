"""app/ads/coverage.py — F49 Contract V: which days of a campaign were read. Private to app/ads.

One answer to "was this day read?", whatever order several reads finished in:

- `data` — the campaign has a non-monthly `ads_external_daily` row that day (any metric scope);
- `empty` — no row, but the day lies in a clean observations read range recorded for the campaign
  (a platform returns no row for a zero-delivery day, so a cleanly read day with no row is a known
  zero, not a gap);
- `missing` — anything else.

The recorded ranges live in `context_json.external_sync.observations.ranges` as the merged union
of every clean read (`with_range`, called by the two writers `external_repository.record_sync`
and `adapters/simulated.extend_coverage`); the legacy single `coverage` range is read as one more
range and no longer written. A failed read never removes a range.

Every judged window is clipped to the campaign: it ends at `min(cutoff, end_date)` and starts no
earlier than `start_date` (`window`, `Days.clip`), so a day the campaign did not run is never a
missing day. Readers call this module only; nothing else reads the stored ranges (scanner:
`test_ads_one_ruler.py`). Read-only apart from the pure `with_range`.
"""

from datetime import date, datetime, timedelta

from app.ads.external_repository import MONTHLY_BUDGET_ATTRIBUTION_KEY

DATA, EMPTY, MISSING = "data", "empty", "missing"
# A served list of missing days stops here (F24-I01): a wall of dates says nothing more.
MISSING_CAP = 31


def _day(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _merge(ranges) -> list[tuple[date, date]]:
    """Sorted union of `(start, end)` pairs; overlapping or adjacent ranges become one."""
    merged: list[list[date]] = []
    for start, end in sorted(r for r in ranges if r[0] <= r[1]):
        if merged and start <= merged[-1][1] + timedelta(days=1):
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def _stored(observations: dict | None) -> list[tuple[date, date]]:
    """The ranges one observations section recorded: `ranges` plus the legacy `coverage`."""
    observations = observations or {}
    found = []
    for item in [*(observations.get("ranges") or []), observations.get("coverage")]:
        if isinstance(item, dict):
            start, end = _day(item.get("start")), _day(item.get("end"))
            if start is not None and end is not None:
                found.append((start, end))
    return _merge(found)


def _observations(campaign: dict) -> dict:
    sync = (campaign.get("context_json") or {}).get("external_sync") or {}
    return sync.get("observations") or {}


def recorded(campaign: dict) -> list[tuple[date, date]]:
    """The campaign's clean observations read ranges, merged, oldest first."""
    return _stored(_observations(campaign))


def with_range(observations: dict | None, start, end) -> list[dict]:
    """The writers' one rule: the stored union plus `[start, end]`, as stored (ISO dates)."""
    ranges = _stored(observations)
    start, end = _day(start), _day(end)
    if start is not None and end is not None:
        ranges = _merge([*ranges, (start, end)])
    return [{"start": s.isoformat(), "end": e.isoformat()} for s, e in ranges]


def served(campaign: dict) -> list[dict]:
    """The recorded ranges as served JSON (`external_view.coverage`)."""
    return [{"start": s.isoformat(), "end": e.isoformat()} for s, e in recorded(campaign)]


def clip(campaign: dict, start: date, end: date) -> tuple[date, date]:
    """`[start, end]` cut to the campaign's own dates; `start > end` when nothing is left."""
    first, last = _day(campaign.get("start_date")), _day(campaign.get("end_date"))
    if first is not None and start < first:
        start = first
    if last is not None and end > last:
        end = last
    return start, end


def window(campaign: dict, cutoff: date, days: int) -> tuple[date, date]:
    """The `days`-long window ending at `min(cutoff, end_date)`, starting no earlier than
    `start_date`. Empty (`start > end`) when the campaign starts after that end."""
    _, end = clip(campaign, cutoff, cutoff)
    start, end = clip(campaign, end - timedelta(days=days - 1), end)
    return start, end


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


class Days:
    """One campaign's day states over a loaded span (`load`). Every question is clipped to the
    campaign's own dates first; asking outside the loaded span is a programming error."""

    DATA, EMPTY, MISSING = DATA, EMPTY, MISSING

    def __init__(self, campaign: dict, span: tuple[date, date], states: dict, ever_read: bool,
                 first_read: date | None = None, ranges: list | None = None):
        self.campaign = campaign
        self.span = span
        self.states = states
        # The recorded clean read ranges (as proven) the `empty` days come from.
        self.ranges = ranges or []
        # The earliest day known read: a recorded range's start or a row day inside the span.
        self.first_read = first_read
        # Nothing was ever read (no recorded range, no row): callers say 「還沒讀過」 instead of
        # listing every day (`missing` returns [] then; `covered` stays False).
        self.never_read = not ever_read

    def clip(self, start: date, end: date) -> tuple[date, date]:
        return clip(self.campaign, start, end)

    def window(self, cutoff: date, days: int) -> tuple[date, date]:
        return window(self.campaign, cutoff, days)

    def _states(self, start: date, end: date) -> list[tuple[date, str]]:
        start, end = self.clip(start, end)
        if start > end:
            return []
        if start < self.span[0] or end > self.span[1]:
            raise ValueError("coverage_outside_loaded_span")
        return [(day, self.states[day]) for day in _days(start, end)]

    def covered(self, start: date, end: date) -> bool:
        """Every campaign day of `[start, end]` is `data` or `empty`."""
        return all(state != MISSING for _, state in self._states(start, end))

    def cleanly_read(self, start: date, end: date) -> bool:
        """Every campaign day of `[start, end]` lies in a recorded clean read range -- the whole
        day was read, so a row absent for one ad is that ad's zero. A row alone proves its own
        day was read (`covered`), not that every ad's rows of that day arrived (a partial page)."""
        start, end = self.clip(start, end)
        return all(any(s <= day <= e for s, e in self.ranges) for day in
                   (_days(start, end) if start <= end else []))

    def missing(self, start: date, end: date, *, cap: int | None = MISSING_CAP) -> list[str]:
        """The campaign days of `[start, end]` nobody read, oldest first (ISO), capped; `[]` when
        nothing was ever read (that is its own answer, `never_read`)."""
        if self.never_read:
            return []
        days = [day.isoformat() for day, state in self._states(start, end) if state == MISSING]
        return days if cap is None else days[:cap]

    def days(self, start: date, end: date) -> list[dict]:
        """`[{day, state}]` over the campaign days of `[start, end]`."""
        return [{"day": day.isoformat(), "state": state} for day, state in self._states(start, end)]

    def read_days(self, start: date, end: date) -> list[date]:
        return [day for day, state in self._states(start, end) if state != MISSING]

    def read_span(self, start: date, end: date) -> dict | None:
        """`{start, end}`: the first and last read day inside `[start, end]`, `None` when none."""
        read = self.read_days(start, end)
        if not read:
            return None
        return {"start": read[0].isoformat(), "end": read[-1].isoformat()}


def load(conn, org_id: str, brand_id: str, campaign: dict, start: date, end: date, *,
         proven_until: date | None = None) -> Days:
    """The day states of `campaign` over `[start, end]` -- one read of its row days. A recorded
    range proves an empty day only up to `proven_until` when given (a day still running when the
    read finished is not proven by it)."""
    ranges = recorded(campaign)
    if proven_until is not None:
        ranges = [(s, min(e, proven_until)) for s, e in ranges if s <= proven_until]
    rows = set()
    if start <= end:
        rows = {
            row["day"] for row in conn.execute(
                "SELECT DISTINCT day FROM ads_external_daily WHERE org_id=%s AND brand_id=%s "
                "AND campaign_id=%s AND day BETWEEN %s AND %s "
                "AND attribution_key IS DISTINCT FROM %s",
                (org_id, brand_id, campaign["id"], start, end, MONTHLY_BUDGET_ATTRIBUTION_KEY),
            ).fetchall()
        }
    states = {}
    for day in _days(start, end) if start <= end else []:
        if day in rows:
            states[day] = DATA
        elif any(s <= day <= e for s, e in ranges):
            states[day] = EMPTY
        else:
            states[day] = MISSING
    first_read = min([*(s for s, _ in ranges), *rows], default=None)
    ever_read = bool(recorded(campaign)) or bool(rows) or conn.execute(
        "SELECT 1 FROM ads_external_daily WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND attribution_key IS DISTINCT FROM %s LIMIT 1",
        (org_id, brand_id, campaign["id"], MONTHLY_BUDGET_ATTRIBUTION_KEY),
    ).fetchone() is not None
    return Days(campaign, (start, end), states, ever_read, first_read, ranges)


def day_states(conn, org_id: str, brand_id: str, campaign: dict, start: date,
               end: date) -> dict:
    """`{date: data | empty | missing}` for every day of `[start, end]` (not clipped)."""
    return load(conn, org_id, brand_id, campaign, start, end).states


def missing_days(conn, org_id: str, brand_id: str, campaign: dict, start: date, end: date, *,
                 cap: int | None = MISSING_CAP) -> list[str]:
    """The campaign days of `[start, end]` nobody read (clipped, capped; `[]` if never read)."""
    return load(conn, org_id, brand_id, campaign, start, end).missing(start, end, cap=cap)


def covered(conn, org_id: str, brand_id: str, campaign: dict, start: date, end: date) -> bool:
    """Every campaign day of `[start, end]` (clipped to its dates) is `data` or `empty`."""
    return load(conn, org_id, brand_id, campaign, start, end).covered(start, end)


def gap(conn, org_id: str, brand_id: str, campaign: dict, start: date, end: date) -> dict:
    """`{never_synced, missing_days}` of `[start, end]`: never read at all is its own answer
    (`missing_days: []`), never a wall of dates."""
    days = load(conn, org_id, brand_id, campaign, start, end)
    return {"never_synced": days.never_read, "missing_days": days.missing(start, end)}
