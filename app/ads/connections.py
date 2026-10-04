"""app/ads/connections.py — F30-I14 (Feature F30 Contract H): the connections page's one read.

`get_connections()` -> `{attention_count, sources, calendar}`. Read-only: it never enqueues a
sync, never calls a platform and never writes. Dates are the organisation's own
(`today_for_org`).

Sources, in screen order:
- One `ad_account` row per bound account per platform (the channel registry's reader), never a
  min across accounts. A platform with a reader but no bound account is one `platform` row in
  state `never`; a platform without a reader is one `platform` row in state `unsupported`
  (listed last).
- `orders` through the orders facade (`app/orders/repository.py`), `product_costs` through the
  products facade (the wizard's own list of finished sell-ways, `wizard_options.options`, so "has
  a cost" means exactly what the wizard means). Orders coverage ends at the later of the latest
  order date and the day before the latest import (org timezone), so an imported day with no
  orders is `ok` (F31-I07); the wait page reads this same source.

An account's days come from pull coverage, never from spend rows (a day read with no spend is
`ok`). Coverage is the union of the account's `monthly:*` reads in `ads_external_sync_job`
(account-wide, one month each: a succeeded task, and the `last_covered` range a reset task carries
from its last good read, so a read in flight or failed never un-proves days) and the read days of
each of its campaigns (`coverage.load`, F49 Contract V: a day with a row, or inside one of the
campaign's clean read ranges -- kept on a failed read, so a failure after a good read leaves only
the unread days missing). A read proves a day only once the day was over when the read finished:
each range ends at most the day before its finish moment (`completed_at` for a month task, the
section's `last_success_at` for a campaign) in the account's timezone, so a day read while still
running is never `ok`. A campaign misses its unread days that no monthly read covered either,
from its first read day on and inside its own dates; an account without campaign coverage misses
the days its monthly reads did not cover, from its first monthly day on. Days before any read are
`none`; an account never read at all misses every day (its note says 「還沒讀取過」, not a list of
dates).

Account state, first match: `auth_expired` / `failed` (the latest account-wide read -- the `list`
task, the newest `monthly` task or a read that could not be requested, judged by
`external_sync.outcome` (F49 Contract O) -- failed, or one of its open campaigns' own sync state is
failed / auth_expired; auth through the adapters' auth-error classifier) / `never` (no coverage
at all) / `missing_days` / `ok`. `missing_days` are the complete days (up to yesterday) of this
month or of the last `LOOKBACK_DAYS` days, whichever starts earlier -- so a gap just before the
1st still shows on the 1st. The calendar covers this month only; today and later days that are
not read yet are `future`.

F47 Contract H: a failed account's note is its reason, then its gap. Every source carries
`reread` -- on an `ad_account` row in state `failed` / `missing_days` / `never` it is the body of
`POST …/existing-campaigns/refresh` (`_reread`), else null.
"""

import calendar
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.ads import (
    adapters,
    channels,
    coverage,
    external_sync,
    lifecycle,
    repository,
    wizard_options,
)
from app.core import settings as coresettings
from app.orders import repository as orders_repo

LOOKBACK_DAYS = 28
_ORDER_PAGE = 1000
_FAILING = {"failed", "auth_expired"}
_ATTENTION_FREE = {"ok", "unsupported"}
_REREADABLE = {"failed", "missing_days", "never"}


def _md(day: date) -> str:
    return day.strftime("%m/%d")


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _covered(ranges, day: date) -> bool:
    return any(start <= day <= end for start, end in ranges)


def _moment(value):
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return value if isinstance(value, datetime) else None


def _proven_until(finished, zone):
    """The last day a read finished at `finished` proves (the day before, in `zone`); `None` when
    there is no finish moment (the ranges as recorded)."""
    moment = _moment(finished)
    return None if moment is None else moment.astimezone(zone).date() - timedelta(days=1)


def _proven(start, end, finished, zone):
    """`[start, end]` cut to the days already over when the read finished (`finished`, in the
    account's `zone`); `None` when no day is left. No finish moment -> the range as recorded."""
    start = start if isinstance(start, date) else date.fromisoformat(start)
    end = end if isinstance(end, date) else date.fromisoformat(end)
    moment = _moment(finished)
    if moment is not None:
        end = min(end, moment.astimezone(zone).date() - timedelta(days=1))
    return (start, end) if start <= end else None


def _zone(conn, org_id, account):
    try:
        return ZoneInfo(account.get("timezone_name") or "")
    except (ValueError, ZoneInfoNotFoundError):
        return coresettings.org_timezone(conn, org_id=org_id)


def _monthly_ranges(tasks, zone) -> list:
    ranges = []
    for key, task in tasks.items():
        if not key.startswith("monthly:"):
            continue
        proofs = [task.get("last_covered") or {}]
        if task.get("status") == "succeeded":
            proofs.append(task)
        for proof in proofs:
            if proof.get("start") and proof.get("end"):
                proven = _proven(proof["start"], proof["end"], proof.get("completed_at"), zone)
                if proven:
                    ranges.append(proven)
    return ranges


def _days_text(days: list[str]) -> str:
    shown = "、".join(_md(date.fromisoformat(d)) for d in days[:3])
    return shown + (f" 等 {len(days)} 天" if len(days) > 3 else "")


def _names_text(campaigns: list[dict]) -> str:
    shown = "、".join(c["name"] for c in campaigns[:2])
    return shown + (f" 等 {len(campaigns)} 個活動" if len(campaigns) > 2 else "")


def _source(key, kind, platform, name, state, note, *, last_success_at=None, missing_days=(),
            affected=(), action=None) -> dict:
    return {
        "key": key, "kind": kind, "platform": platform, "name": name, "state": state,
        "note": note, "last_success_at": last_success_at, "missing_days": list(missing_days),
        "affected_campaigns": list(affected), "action": action, "reread": None,
    }


def _reread(platform, account_id, state, missing_days, window_start, yesterday) -> dict | None:
    """F47 Contract H: the body of `POST …/existing-campaigns/refresh` that reads this account
    again -- the missing range (first to last unread day), else the page's window up to yesterday.
    Only for a read the user can repeat from here (`failed`, `missing_days`, `never`); an expired
    authorisation is fixed on the settings page instead, an `ok` account needs nothing."""
    if state not in _REREADABLE:
        return None
    start, end = (missing_days[0], missing_days[-1]) if missing_days else (
        window_start.isoformat(), yesterday.isoformat(),
    )
    return {"platform": platform, "source_account": account_id, "start": start, "end": end}


def _account_campaigns(conn, org_id, brand_id, platform, account_id) -> list[dict]:
    """The not-closed campaigns (`lifecycle.campaigns`) with a root on this account."""
    on_account = {
        row["campaign_id"] for row in conn.execute(
            "SELECT DISTINCT campaign_id FROM ads_external_entity WHERE org_id=%s "
            "AND brand_id=%s AND platform=%s AND source_account=%s AND parent_native_id IS NULL",
            (org_id, brand_id, platform, account_id),
        ).fetchall()
    }
    rows = [
        c for c in lifecycle.campaigns(conn, org_id, brand_id, lifecycle.NOT_CLOSED)
        if c["id"] in on_account
    ]
    return sorted(rows, key=lambda c: (c["name"] or "", c["id"]))


def _account(conn, org_id, brand_id, channel, account, span, accounts_cache):
    """One bound account: its source row and its calendar row."""
    platform, account_id = channel["key"], account["account_id"]
    today, window_start = span["today"], span["window_start"]
    yesterday = today - timedelta(days=1)
    job = conn.execute(
        "SELECT * FROM ads_external_sync_job WHERE org_id=%s AND brand_id=%s AND platform=%s "
        "AND source_account=%s",
        (org_id, brand_id, platform, account_id),
    ).fetchone()
    tasks = dict(job["tasks"] or {}) if job else {}
    zone = _zone(conn, org_id, account)
    monthly = _monthly_ranges(tasks, zone)
    moments = [job["last_success_at"]] if job else []
    failures = []  # (error_code, error text)
    newest_month = max((key for key in tasks if key.startswith("monthly:")), default=None)
    # F49 Contract O: the account-wide read (the list, the newest month, a request that could not
    # start) fails through the one sync outcome -- never a task's own error fields.
    account_tasks = {
        key: tasks[key] for key in ("list", newest_month, external_sync.REQUEST_TASK)
        if key and key in tasks
    }
    read = external_sync.outcome(account_tasks) if account_tasks else None
    if read and read["state"] in {"failed", "partial"}:
        failures.append((read["code"], read["text"]))
    auth = bool(read) and adapters.is_auth_error(platform, read["code"])
    for task in account_tasks.values():
        if task.get("status") == "succeeded":
            moments.append(task.get("completed_at"))

    ranges = list(monthly)
    missing: set[date] = set()
    affected = []
    campaign_covered = False
    for campaign in _account_campaigns(conn, org_id, brand_id, platform, account_id):
        observed = ((campaign.get("context_json") or {}).get("external_sync") or {}).get(
            "observations"
        ) or {}
        read = coverage.load(
            conn, org_id, brand_id, campaign, window_start, yesterday,
            proven_until=_proven_until(observed.get("last_success_at"), zone),
        ) if window_start <= yesterday else None
        sync = repository.campaign_sync_state(
            conn, org_id, brand_id, campaign, accounts_cache=accounts_cache,
        )
        moments.append(sync["last_success_at"])
        own: set[date] = set()
        if read is not None and read.first_read is not None and read.first_read <= yesterday:
            campaign_covered = True
            ranges.extend((day, day) for day in read.read_days(window_start, yesterday))
            start = max(window_start, read.first_read)
            own = {
                day for day in map(date.fromisoformat, read.missing(start, yesterday, cap=None))
                if not _covered(monthly, day)
            }
        if sync["state"] in _FAILING:
            failures.append((None, sync["error"]))
            auth = auth or sync["state"] == "auth_expired"
        if own or sync["state"] in _FAILING or sync["state"] == "disconnected":
            affected.append({"id": campaign["id"], "name": campaign["name"]})
        missing |= own
    if not ranges:
        missing = set(_days(window_start, yesterday))
    elif not campaign_covered:
        start = max(window_start, min(first for first, _ in monthly))
        missing = {day for day in _days(start, yesterday) if not _covered(monthly, day)}

    missing_days = sorted(day.isoformat() for day in missing)
    gap = f"{_days_text(missing_days)} 讀不到" if missing_days and ranges else ""
    if failures:
        state = "auth_expired" if auth else "failed"
        text = next((error for _, error in failures if error), None)
        reason = "授權已失效，重新授權後才能讀資料" if auth else text or "上次讀取失敗"
        # F47 Contract H: the reason first, then the gap -- a gap never hides why the read failed.
        note = f"{reason}；{gap}" if gap else reason
    elif not ranges:
        state, note = "never", "還沒讀取過"
    elif missing_days:
        state, note = "missing_days", gap
    else:
        state, note = "ok", "每天的資料都有讀到"
    if affected and state != "never":
        note += f"・{_names_text(affected)}先不判斷"
    href = f"/settings?tab={platform}"
    action = (
        {"label": "重新授權", "href": href} if state == "auth_expired"
        else {"label": "查看連線", "href": href} if state == "failed" else None
    )
    moments = [m for m in map(_moment, moments) if m is not None]
    label = account.get("name") or account_id
    source = _source(
        f"{platform}:{account_id}", "ad_account", platform,
        f"{channel['label']} 廣告帳戶・{label}", state, note,
        last_success_at=max(moments) if moments else None, missing_days=missing_days,
        affected=affected, action=action,
    )
    source["reread"] = _reread(platform, account_id, state, missing_days, window_start, yesterday)

    def day_state(day: date) -> str:
        if day > today:
            return "future"
        if day == today:
            return "ok" if _covered(ranges, day) else "future"
        if day in missing:
            return "missing"
        return "ok" if _covered(ranges, day) else "none"

    row = {
        "source_key": source["key"], "label": label,
        "days": [{"date": d.isoformat(), "state": day_state(d)} for d in span["month_days"]],
    }
    return source, row


def _order_span(conn, brand_id, zone) -> tuple[date, date, date | None] | None:
    """(earliest order date, latest order date, day of the latest import in `zone`) through the
    orders facade in one pass; `None` when no order has a date. The import moment is the newest
    `updated_at` / `created_at` of the brand's order rows (an import rewrites every row it
    carries, so the newest stamp is the latest import)."""
    total = orders_repo.count_orders(conn, brand_id)
    earliest = latest = imported = None
    offset = 0
    while offset < total:
        page = orders_repo.list_orders(conn, brand_id, limit=_ORDER_PAGE, offset=offset)
        if not page:
            break
        for row in page:
            day = row.get("order_date")
            if day is not None:
                earliest = day if earliest is None else min(earliest, day)
                latest = day if latest is None else max(latest, day)
            for moment in (row.get("updated_at"), row.get("created_at")):
                if isinstance(moment, datetime):
                    imported = moment if imported is None else max(imported, moment)
        offset += len(page)
    if earliest is None or latest is None:
        return None
    return earliest, latest, imported.astimezone(zone).date() if imported else None


def _orders(conn, org_id, brand_id, span):
    """Orders coverage runs from the earliest order date to the later of the latest order date
    and the day before the latest import (org timezone): an import is a full export up to the
    moment it ran, so a day with no orders that it covered is read, not missing -- the spend
    rule "a read proves a day once the day was over when the read finished". Complete days after
    that end are missing. Risk kept on purpose: importing an old export last marks later empty
    days ok."""
    today, window_start = span["today"], span["window_start"]
    dates = _order_span(conn, brand_id, coresettings.org_timezone(conn, org_id=org_id))
    href = {"label": "補報表", "href": f"/brands/{brand_id}/orders"}
    if dates is None:
        source = _source("orders", "orders", None, "商城訂單報表", "never", "還沒有匯入訂單",
                         action=href)
        days = [{"date": d.isoformat(), "state": "future" if d > today else "none"}
                for d in span["month_days"]]
        return source, {"source_key": "orders", "label": "商城訂單報表", "days": days}
    earliest, latest, imported = dates
    end = latest
    if imported is not None and imported - timedelta(days=1) > latest:
        end = imported - timedelta(days=1)
    missing_days = [
        day.isoformat()
        for day in _days(max(window_start, earliest), today - timedelta(days=1))
        if day > end
    ]
    note = f"最新匯入 {_md(imported)}" if imported is not None and end > latest \
        else f"最新到 {_md(latest)}"
    if missing_days:
        state = "missing_days"
        note += f"，缺 {_md(end + timedelta(days=1))} 之後"
    else:
        state = "ok"
    source = _source("orders", "orders", None, "商城訂單報表", state, note,
                     missing_days=missing_days, action=href if missing_days else None)

    def day_state(day: date) -> str:
        if day > today or (day == today and day > end):
            return "future"
        if day < earliest:
            return "none"
        return "ok" if day <= end else "missing"

    days = [{"date": d.isoformat(), "state": day_state(d)} for d in span["month_days"]]
    return source, {"source_key": "orders", "label": "商城訂單報表", "days": days}


def _product_costs(conn, org_id, brand_id):
    """F43-I04: judged on the finished sell-ways the wizard offers (`wizard_options.options`);
    none -> 「還沒有商品」 opening product onboarding, the same link as the readiness row."""
    products = wizard_options.options(conn, org_id, brand_id)["products"]
    href = f"/brands/{brand_id}/products"
    if not products:
        return _source("product_costs", "product_costs", None, "商品成本", "never", "還沒有商品",
                       action={"label": "去建立商品", "href": f"{href}/new"})
    costless = [p["name"] for p in products if not p["has_cost"]]
    note = f"{len(products)} 個賣法，{len(products) - len(costless)} 個有成本"
    if not costless:
        return _source("product_costs", "product_costs", None, "商品成本", "ok", note)
    shown = "、".join(costless[:3]) + (f" 等 {len(costless)} 個" if len(costless) > 3 else "")
    return _source("product_costs", "product_costs", None, "商品成本", "missing_cost",
                   f"{note}；{shown}缺成本", action={"label": "去填成本", "href": href})


def get_connections(conn, org_id: str, brand_id: str) -> dict:
    today = coresettings.today_for_org(conn, org_id=org_id)
    month_start = today.replace(day=1)
    month_end = today.replace(day=calendar.monthrange(today.year, today.month)[1])
    span = {
        "today": today,
        "window_start": min(month_start, today - timedelta(days=LOOKBACK_DAYS)),
        "month_days": _days(month_start, month_end),
    }
    sources, rows, unsupported = [], [], []
    accounts_cache: dict = {}
    for channel in channels.CHANNELS:
        reader = channels.external_reader(channel["key"])
        if reader is None:
            unsupported.append(_source(
                f"platform:{channel['key']}", "platform", channel["key"], channel["label"],
                "unsupported", "尚未支援，接上後開放",
            ))
            continue
        accounts = reader.accounts(conn, org_id, brand_id)
        if not accounts:
            sources.append(_source(
                f"platform:{channel['key']}", "platform", channel["key"], channel["label"],
                "never", "還沒有連接廣告帳戶",
                action={"label": "去連接", "href": f"/settings?tab={channel['key']}"},
            ))
            continue
        for account in accounts:
            source, row = _account(conn, org_id, brand_id, channel, account, span, accounts_cache)
            sources.append(source)
            rows.append(row)
    order_source, order_row = _orders(conn, org_id, brand_id, span)
    sources += [order_source, _product_costs(conn, org_id, brand_id), *unsupported]
    rows.append(order_row)
    return {
        "attention_count": sum(1 for s in sources if s["state"] not in _ATTENTION_FREE),
        "sources": sources,
        "calendar": {"month": today.strftime("%Y-%m"), "today": today.isoformat(), "rows": rows},
    }
