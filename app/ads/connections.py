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
  products facade (the wizard's own product list, `wizard_options.options`, so "has a cost" means
  exactly what the wizard means).

An account's days come from pull coverage, never from spend rows (a day read with no spend is
`ok`). Coverage is the union of the account's succeeded `monthly:*` reads in
`ads_external_sync_job` (account-wide, one month each) and the recorded observations coverage of
each of its campaigns (`triage._coverage`, kept on a failed read, so a failure after a good read
leaves only the unread days missing). A campaign misses the days after its own coverage that no
monthly read covered either (`triage._missing_days`), from its first covered day on; an account
without campaign coverage misses the days its monthly reads did not cover, from its first
monthly day on. Days before any read are `none`; an account never read at all misses every day.

Account state, first match: `auth_expired` / `failed` (the latest account-wide read -- the `list`
task or this month's `monthly` task -- failed, or one of its open campaigns' own sync state is
failed / auth_expired; auth through the adapters' auth-error classifier) / `never` (no coverage
at all) / `missing_days` / `ok`. `missing_days` are the complete days (up to yesterday) of this
month or of the last `LOOKBACK_DAYS` days, whichever starts earlier -- so a gap just before the
1st still shows on the 1st. The calendar covers this month only; today and later days that are
not read yet are `future`.
"""

import calendar
from datetime import date, datetime, timedelta

from app.ads import adapters, channels, repository, triage, wizard_options
from app.core import settings as coresettings
from app.orders import repository as orders_repo

LOOKBACK_DAYS = 28
_ORDER_PAGE = 200
_FAILING = {"failed", "auth_expired"}
_ATTENTION_FREE = {"ok", "unsupported"}


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
        "affected_campaigns": list(affected), "action": action,
    }


def _account_campaigns(conn, org_id, brand_id, platform, account_id) -> list[dict]:
    rows = conn.execute(
        "SELECT DISTINCT c.* FROM ads_campaign c JOIN ads_external_entity e "
        "ON e.campaign_id=c.id AND e.org_id=c.org_id AND e.brand_id=c.brand_id "
        "WHERE c.org_id=%s AND c.brand_id=%s AND c.status != 'closed' AND e.platform=%s "
        "AND e.source_account=%s AND e.parent_native_id IS NULL ORDER BY c.name, c.id",
        (org_id, brand_id, platform, account_id),
    ).fetchall()
    return [dict(row) for row in rows]


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
    monthly = [
        (date.fromisoformat(task["start"]), date.fromisoformat(task["end"]))
        for key, task in tasks.items()
        if key.startswith("monthly:") and task.get("status") == "succeeded"
        and task.get("start") and task.get("end")
    ]
    moments = [job["last_success_at"]] if job else []
    failures = []  # (error_code, error text)
    auth = False
    for key in ("list", "monthly:" + today.strftime("%Y-%m")):
        task = tasks.get(key)
        if not task:
            continue
        if task.get("status") == "failed":
            failures.append((task.get("error_code"), (task.get("errors") or [None])[0]))
            auth = auth or adapters.is_auth_error(platform, task.get("error_code"))
        elif task.get("status") == "succeeded":
            moments.append(task.get("completed_at"))

    ranges = list(monthly)
    missing: set[date] = set()
    affected = []
    campaign_covered = False
    for campaign in _account_campaigns(conn, org_id, brand_id, platform, account_id):
        coverage = triage._coverage(campaign)
        sync = repository.campaign_sync_state(
            conn, org_id, brand_id, campaign, accounts_cache=accounts_cache,
        )
        moments.append(sync["last_success_at"])
        own: set[date] = set()
        if coverage is not None:
            campaign_covered = True
            ranges.append(coverage)
            start = max(window_start, coverage[0])
            own = {
                day for day in map(date.fromisoformat,
                                   triage._missing_days(coverage, start, yesterday))
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
    gap = f"{_days_text(missing_days)} 讀不到" if missing_days else ""
    if failures:
        state = "auth_expired" if auth else "failed"
        text = next((error for _, error in failures if error), None)
        note = gap or ("授權已失效，重新授權後才能讀資料" if auth else text or "上次讀取失敗")
    elif not ranges:
        state, note = "never", "還沒讀過這個帳戶的資料"
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


def _order_dates(conn, brand_id) -> tuple[date, date] | None:
    """(earliest, latest) non-null order dates through the orders facade, `None` when there is
    none. `list_orders` sorts `order_date DESC` with NULLs first, so the last row is the
    earliest date and the first dated row is the latest."""
    total = orders_repo.count_orders(conn, brand_id)
    latest, offset = None, 0
    while latest is None and offset < total:
        page = orders_repo.list_orders(conn, brand_id, limit=_ORDER_PAGE, offset=offset)
        if not page:
            break
        latest = next((row["order_date"] for row in page if row["order_date"] is not None), None)
        offset += len(page)
    if latest is None:
        return None
    earliest = orders_repo.list_orders(conn, brand_id, limit=1, offset=total - 1)[0]["order_date"]
    return (earliest or latest), latest


def _orders(conn, brand_id, span):
    today, window_start = span["today"], span["window_start"]
    dates = _order_dates(conn, brand_id)
    href = {"label": "補報表", "href": f"/brands/{brand_id}/orders"}
    if dates is None:
        source = _source("orders", "orders", None, "商城訂單報表", "never", "還沒有匯入訂單",
                         action=href)
        days = [{"date": d.isoformat(), "state": "future" if d > today else "none"}
                for d in span["month_days"]]
        return source, {"source_key": "orders", "label": "商城訂單報表", "days": days}
    earliest, latest = dates
    missing_days = [
        day.isoformat()
        for day in _days(max(window_start, earliest), today - timedelta(days=1))
        if day > latest
    ]
    note = f"最新到 {_md(latest)}"
    if missing_days:
        state = "missing_days"
        note += f"，缺 {_md(latest + timedelta(days=1))} 之後"
    else:
        state = "ok"
    source = _source("orders", "orders", None, "商城訂單報表", state, note,
                     missing_days=missing_days, action=href if missing_days else None)

    def day_state(day: date) -> str:
        if day > today or (day == today and day > latest):
            return "future"
        if day < earliest:
            return "none"
        return "ok" if day <= latest else "missing"

    days = [{"date": d.isoformat(), "state": day_state(d)} for d in span["month_days"]]
    return source, {"source_key": "orders", "label": "商城訂單報表", "days": days}


def _product_costs(conn, org_id, brand_id):
    products = wizard_options.options(conn, org_id, brand_id)["products"]
    href = f"/brands/{brand_id}/products"
    if not products:
        return _source("product_costs", "product_costs", None, "商品成本", "never", "還沒有商品",
                       action={"label": "去建立商品", "href": href})
    costless = [p["name"] for p in products if not p["has_cost"]]
    note = f"{len(products)} 個商品，{len(products) - len(costless)} 個有成本"
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
    order_source, order_row = _orders(conn, brand_id, span)
    sources += [order_source, _product_costs(conn, org_id, brand_id), *unsupported]
    rows.append(order_row)
    return {
        "attention_count": sum(1 for s in sources if s["state"] not in _ATTENTION_FREE),
        "sources": sources,
        "calendar": {"month": today.strftime("%Y-%m"), "today": today.isoformat(), "rows": rows},
    }
