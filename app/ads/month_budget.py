"""Monthly envelopes and conservative commitments. No model or platform mutation.

One source grain supplies spending; budget owners supply future estimates. Neither
an approval nor a reported reduction creates money. Missing coverage stays unknown.
"""

import calendar
import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from app.ads import ad_status, channels
from app.ads.external_repository import is_monthly_budget_row
from app.brand_intelligence import repository as brands
from app.core import db, input_rules, settings
from app.core.audit import write_audit
from app.core.db import now_utc

NOTICE = "節慶包含在月總額內。這是系統提醒與核准前檢查，不是平台限額，也不會讓平台自動停花。"


def month_start(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}", value):
        raise ValueError("請選擇預算月份。")
    try:
        return date.fromisoformat(value + "-01")
    except ValueError:
        raise ValueError("預算月份無效。") from None


def money(value):
    if isinstance(value, bool):
        raise ValueError("請輸入有效且非負的金額。")
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0 or result > Decimal("9999999999999999.99"):
            raise ValueError
        return result.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ValueError("請輸入有效且非負的金額。") from None


_TOTAL_CEILING = Decimal("9999999999999999.99")


def total(value):
    """The monthly total as typed (F47 Contract A): ``> 0``, never coerced. Unset stays ``null``
    (no row); 0 has no planning meaning (the home pace chart divides by it); a negative is
    refused."""
    number = input_rules.positive(value, "每月品牌總額")
    result = Decimal(str(number))
    if result > _TOTAL_CEILING:
        raise input_rules.InputRuleError("每月品牌總額太大了，請確認金額。")
    return result.quantize(Decimal("0.01"))


def lock(conn, org, brand):
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f"ads-budget:{org}:{brand}",)
    )


def _brand(conn, org, brand):
    row = brands.get_brand(conn, brand)
    if row is None or row["org_id"] != org:
        raise ValueError("找不到這個品牌。")


def _date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10]) if value else None


def _fresh(value):
    if not value:
        return False
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    # F39-I06: one clock -- `now_utc` is a module-level name so the drill clock
    # (`scripts/drill/clock.py::patch_modules`) can rebind it; never `datetime.now`.
    return now_utc() - stamp < timedelta(hours=24)


def pending_days(item, *, start, today) -> int:
    """How many days of month `start` a pending budget or launch item still reserves: from the
    later of the item's start and the first future day (today or the month's first day) to the
    earlier of its end and the month's last day, both inclusive; 0 when it misses the month."""
    end = start.replace(day=calendar.monthrange(start.year, start.month)[1])
    target, after = item.get("target") or {}, item.get("after") or {}
    first_future = max(start, today)
    stop = min(end, _date(after.get("end_date") or target.get("end_date")) or end)
    begin = max(
        first_future, _date(after.get("start_date") or target.get("start_date")) or first_future
    )
    return max((stop - begin).days + 1, 0)


def calculate(*, amount, currency, start, today, entities, observations, pending, uncertainties):
    """Pure evidence calculation, independently exercised with contradictory fixtures.

    Conversion attribution can change without a new spend. Choose one latest
    observation per source/native/day/grain; never sum attribution variants.
    """
    end = start.replace(day=calendar.monthrange(start.year, start.month)[1])
    issues = list(uncertainties)
    by_id = {e["id"]: e for e in entities}
    selected = {}
    for row in observations:
        entity = by_id.get(row["entity_id"])
        if not entity or not start <= _date(row["day"]) <= end:
            continue
        key = (
            entity["platform"],
            entity["source_account"],
            entity["native_kind"],
            entity["native_id"],
            str(row["day"]),
            row["metric_scope"],
        )
        previous = selected.get(key)
        if (
            previous
            and previous.get("observed_at") == row.get("observed_at")
            and (previous.get("spend"), previous.get("currency"))
            != (row.get("spend"), row.get("currency"))
        ):
            issues.append("同一期花費有互相衝突的來源，需重新同步核對。")
        if not previous or str(row.get("observed_at") or "") > str(
            previous.get("observed_at") or ""
        ):
            selected[key] = row
    spent = Decimal(0)
    spend_evidence = 0
    spent_today = {}
    for row in selected.values():
        entity = by_id[row["entity_id"]]
        if row.get("currency") != currency or row.get("spend") is None:
            issues.append("部分花費幣別或金額不明，不能換算成確定餘額。")
            continue
        value = money(row["spend"])
        if not entity.get("parent_native_id") and row["metric_scope"] == entity["native_kind"]:
            spent += value
            spend_evidence += 1
        if _date(row["day"]) == today and row["metric_scope"] == entity["native_kind"]:
            spent_today[entity["id"]] = value

    first_future = max(start, today)
    ongoing = Decimal(0)
    owners = {}
    owner_ids = {
        (e["platform"], e["source_account"], e["native_kind"], e["native_id"])
        for e in entities
        if e.get("budget_amount") is not None
    }
    for entity in entities:
        if entity["native_kind"] in {"ad"}:
            continue
        if ad_status.is_closed(entity.get("native_status")):
            continue
        parent_key = (
            entity["platform"],
            entity["source_account"],
            entity.get("parent_native_kind"),
            entity.get("parent_native_id"),
        )
        if parent_key in owner_ids:
            if entity.get("budget_amount") is not None:
                issues.append("父層與子層都有預算，實際預算控制層级待核對。")
            continue
        # Only explicit source evidence may delegate to child budget owners.
        # Missing amount or raw fields is not proof of an absent parent budget.
        # `budget_type in (None, "unknown")`: the schema has no spare `None` for this (F25-I01
        # 2026-09-22 "ABO without a schema change") -- the real writer (`meta_read.py::_entity`)
        # marks a verified ABO campaign as `budget_type="unknown"` with `budget_raw.owner`, so
        # `"unknown"` counts here too; `None` stays accepted for a pure-function `calculate()`
        # fixture that predates the schema constraint. Either way `budget_raw.owner` still has to
        # read `"children_verified"` -- an ordinary "never synced" `unknown` row carries no such
        # marker and still falls through to the uncertainty below.
        if (
            entity.get("budget_amount") is None
            and entity.get("budget_type") in (None, "unknown")
            and (entity.get("budget_raw") or {}).get("owner") == "children_verified"
        ) and any(
            e.get("parent_native_id") == entity["native_id"]
            and e["platform"] == entity["platform"]
            and e["source_account"] == entity["source_account"]
            and e.get("budget_amount") is not None
            for e in entities
        ):
            continue
        stop = min(end, _date(entity.get("end_date")) or end)
        begin = max(first_future, _date(entity.get("start_date")) or first_future)
        if stop < begin:
            continue
        if entity.get("native_status") is None:
            issues.append("部分活動是否持續投放尚不明，請讀回平台設定。")
        if entity.get("currency") != currency or entity.get("budget_amount") is None:
            issues.append("持續投放的預算金額、單位或幣別未核實。")
            continue
        if entity.get("budget_type") != "daily":
            issues.append("總額預算尚缺完整生命週期花費，剩餘承諾待核對。")
            continue
        days = (stop - begin).days + 1
        value = money(entity["budget_amount"])
        # Today's overspend never consumes tomorrow's remaining allocation.
        today_credit = (
            min(value, spent_today.get(entity["id"], Decimal(0))) if begin == today else Decimal(0)
        )
        commitment = value * days - today_credit
        ongoing += commitment
        owners[entity["id"]] = {
            "daily": value, "days": days, "commitment": commitment, "name": entity.get("name"),
        }

    # Multiple not-yet-read-back edits of one budget cannot compound the original
    # forecast. Reserve the greatest approved increase; never net a pending decrease.
    holds = {}
    for item in pending:
        kind = item.get("kind") or item.get("change_kind")
        if kind not in {"budget", "launch", "new_ad"}:
            continue
        target = item.get("target") or {}
        target_id = item.get("target_id") or target.get("id")
        before, after = item.get("before") or {}, item.get("after") or {}
        if kind == "budget" and after.get("daily_amount") is None:
            continue
        new_daily = money(after.get("daily_amount", 0))
        base = owners.get(target_id)
        old_daily = base["daily"] if base else money(before.get("daily_amount") or 0)
        days = pending_days(item, start=start, today=today)
        # Even a 'confirmed' action continues to reserve against a stale snapshot.
        delta = max(new_daily - old_daily, Decimal(0)) * days
        holds[target_id] = max(holds.get(target_id, Decimal(0)), delta)
    reserved = sum(holds.values(), Decimal(0))
    issues = list(dict.fromkeys(issues))
    available = (
        money(amount) - spent - ongoing - reserved if amount is not None and not issues else None
    )
    # F40-I01: the approve page's 預留 breakdown -- one line per budget owner still running
    # this month (the same `owners` map `ongoing` sums), largest commitment first, so the page
    # can print 「9 月活動還有 5 天沒跑完，每天 1,500」 without a second calculation.
    ongoing_owners = [
        {
            "entity_id": entity_id, "name": owner["name"], "daily": float(owner["daily"]),
            "days": owner["days"], "commitment": float(owner["commitment"]),
        }
        for entity_id, owner in sorted(
            owners.items(), key=lambda pair: pair[1]["commitment"], reverse=True,
        )
    ]
    return {
        "known_spend": float(spent) if spend_evidence or not issues else None,
        "ongoing_estimate": float(ongoing) if not issues else None,
        "known_ongoing_estimate": float(ongoing),
        "reserved_increases": float(reserved),
        "available": float(available) if available is not None else None,
        "uncertainties": issues,
        "can_increase": available is not None and available > 0,
        "ongoing_owners": ongoing_owners,
        "period_end": end.isoformat(),
        "notice": NOTICE,
    }


def _inventory(conn, org, brand, start, today):
    coverage_end = min(today, start.replace(day=calendar.monthrange(start.year, start.month)[1]))
    covered_accounts = {}
    entities = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM ads_external_entity WHERE org_id=%s AND brand_id=%s", (org, brand)
        ).fetchall()
    ]
    observations = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM ads_external_daily WHERE org_id=%s AND brand_id=%s "
            "AND day >= %s AND day<=%s",
            (org, brand, start, today),
        ).fetchall()
    ]
    issues = []
    accounts = []
    for channel in channels.CHANNELS:
        reader = channels.external_reader(channel["key"])
        if reader:
            accounts.extend(
                {**a, "platform": channel["key"]} for a in reader.accounts(conn, org, brand)
            )
    if not accounts:
        issues.append("尚未接上可核對的廣告帳戶，請先完成連線。")
    zone = str(settings.org_timezone(conn, org_id=org))
    envelope = conn.execute(
        "SELECT currency FROM ads_month_budget WHERE org_id=%s AND brand_id=%s AND month=%s",
        (org, brand, start),
    ).fetchone()
    currencies = {a.get("currency") for a in accounts}
    if (
        None in currencies
        or len(currencies) > 1
        or (envelope and currencies != {envelope["currency"]})
    ):
        issues.append("帳戶幣別未知或與月預算不一致，不能混合花費。")
    for account in accounts:
        platform, account_id = account["platform"], account["account_id"]
        if account.get("timezone_name") != zone:
            issues.append("帳戶與品牌月份的時區不一致或未知，需核對花費切日口徑。")
        job = conn.execute(
            "SELECT * FROM ads_external_sync_job WHERE org_id=%s AND brand_id=%s "
            "AND platform=%s AND source_account=%s",
            (org, brand, platform, account_id),
        ).fetchone()
        monthly = ((job["tasks"] if job else {}) or {}).get(
            "monthly:" + start.strftime("%Y-%m"), {}
        )
        coverage = monthly.get("coverage") or {}
        if (
            monthly.get("status") != "succeeded"
            or coverage.get("scope") != "account_campaign_day"
            or (_date(coverage.get("start")) or date.max) > start
            or (_date(coverage.get("end")) or date.min) < coverage_end
            or not _fresh(monthly.get("completed_at"))
            or coverage.get("currency") != account.get("currency")
            or not account.get("currency")
            or coverage.get("timezone_name") != account.get("timezone_name")
            or coverage.get("unassigned_native_ids") != []
        ):
            issues.append("帳戶整月花費涵蓋範圍與歷史活動歸屬尚待核對。")
        else:
            covered_accounts[(platform, account_id)] = monthly
        listed = conn.execute(
            "SELECT native_kind,native_id FROM ads_external_listing "
            "WHERE org_id=%s AND brand_id=%s "
            "AND platform=%s AND source_account=%s",
            (org, brand, platform, account_id),
        ).fetchall()
        roots = {
            (e["native_kind"], e["native_id"])
            for e in entities
            if e["platform"] == platform
            and e["source_account"] == account_id
            and not e.get("parent_native_id")
        }
        if any((r["native_kind"], r["native_id"]) not in roots for r in listed):
            issues.append("帳戶仍有未承接的活動，品牌花費歸屬尚不完整。")
    account_keys = {(a["platform"], a["account_id"]) for a in accounts}
    if any((e["platform"], e["source_account"]) not in account_keys for e in entities):
        issues.append("部分歷史來源已斷線，持續投放與花費無法核對。")
    for campaign in conn.execute(
        "SELECT * FROM ads_campaign WHERE org_id=%s AND brand_id=%s", (org, brand)
    ).fetchall():
        if campaign["origin"] == "imported":
            campaign_accounts = {
                (e["platform"], e["source_account"])
                for e in entities
                if e["campaign_id"] == campaign["id"] and not e.get("parent_native_id")
            }
            if campaign_accounts and campaign_accounts <= covered_accounts.keys():
                continue
            sync = (campaign["context_json"] or {}).get("external_sync", {})
            coverage = (sync.get("observations") or {}).get("coverage") or {}
            if (_date(coverage.get("start")) or date.max) > start or (
                _date(coverage.get("end")) or date.min
            ) < min(today, start.replace(day=calendar.monthrange(start.year, start.month)[1])):
                issues.append("本月成效仍有缺日，已知花費不是完整月累計。")
        elif campaign.get("external_id") and not any(
            e["native_id"] == campaign["external_id"] and not e.get("parent_native_id")
            for e in entities
        ):
            issues.append("既有綁定活動尚未承接到可核對的花費資料。")
    duplicate = conn.execute(
        "SELECT 1 FROM ads_external_entity a JOIN ads_external_entity b ON a.org_id=b.org_id "
        "AND a.platform=b.platform AND a.source_account=b.source_account "
        "AND a.native_kind=b.native_kind "
        "AND a.native_id=b.native_id AND a.brand_id<>b.brand_id "
        "WHERE a.org_id=%s AND a.brand_id=%s LIMIT 1",
        (org, brand),
    ).fetchone()
    if duplicate:
        issues.append("同一平台物件被多個品牌承接，請先釐清花費歸屬。")
    # Successful account-month reads are the authoritative spend grain. A previous
    # row omitted by a complete reread must not survive as stale monthly spending.
    by_id = {e["id"]: e for e in entities}
    filtered = []
    for observation in observations:
        entity = by_id.get(observation["entity_id"], {})
        monthly = covered_accounts.get((entity.get("platform"), entity.get("source_account")))
        if monthly and not entity.get("parent_native_id"):
            if not is_monthly_budget_row(observation.get("attribution_key")):
                continue
            if monthly.get("started_at") and datetime.fromisoformat(
                str(observation["observed_at"])
            ) < datetime.fromisoformat(str(monthly["started_at"])):
                continue
        filtered.append(observation)
    return entities, filtered, issues


def _pending(conn, org, brand, month):
    rows = conn.execute(
        "SELECT a.* FROM ads_action a JOIN ads_change_set s ON a.change_set_id=s.id "
        "WHERE a.org_id=%s AND a.brand_id=%s AND s.status='approved' AND s.month=%s",
        (org, brand, month),
    ).fetchall()
    return [
        {
            "kind": r["after_json"].get("change_kind"),
            "target_id": r["target_id"],
            "target": r["after_json"].get("target", {}),
            "before": r["before_json"],
            "after": r["after_json"],
        }
        for r in rows
    ]


def view(conn, org, brand, month, *, additional=()):
    _brand(conn, org, brand)
    start = month_start(month)
    today = settings.today_for_org(conn, org_id=org)
    row = conn.execute(
        "SELECT * FROM ads_month_budget WHERE org_id=%s AND brand_id=%s AND month=%s",
        (org, brand, start),
    ).fetchone()
    entities, observations, issues = _inventory(conn, org, brand, start, today)
    currencies = {e["currency"] for e in entities if e.get("currency")}
    currency = row["currency"] if row else next(iter(currencies)) if len(currencies) == 1 else None
    if currency is None:
        issues.append("尚未確認月預算幣別。")
    result = calculate(
        amount=row["amount"] if row else None,
        currency=currency,
        start=start,
        today=today,
        entities=entities,
        observations=observations,
        pending=[*_pending(conn, org, brand, month), *additional],
        uncertainties=issues,
    )
    return {
        **result,
        "month": month,
        "currency": currency,
        "amount": float(row["amount"]) if row else None,
        "revision": row["revision"] if row else 0,
        "confirmed_at": row["confirmed_at"] if row else None,
    }


def save(conn, org, brand, *, month, currency, amount, expected_revision, actor):
    _brand(conn, org, brand)
    start = month_start(month)
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("請選擇三碼預算幣別。")
    value = total(amount)
    lock(conn, org, brand)
    row = conn.execute(
        "SELECT * FROM ads_month_budget WHERE org_id=%s AND brand_id=%s AND month=%s FOR UPDATE",
        (org, brand, start),
    ).fetchone()
    if type(expected_revision) is not int or expected_revision != (row["revision"] if row else 0):
        raise ValueError("月預算已被更新，請重新載入後確認。")
    if row and row["currency"] != currency:
        raise ValueError("已確認的月份不能直接換幣別，請先核對帳戶與花費口徑。")
    record_id = row["id"] if row else db.new_id("amb")
    conn.execute(
        "INSERT INTO ads_month_budget(id,org_id,brand_id,month,currency,amount,confirmed_by) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(org_id,brand_id,month) DO UPDATE SET "
        "amount=EXCLUDED.amount,revision=ads_month_budget.revision+1,confirmed_by=EXCLUDED.confirmed_by,confirmed_at=now()",
        (record_id, org, brand, start, currency, value, actor),
    )
    write_audit(
        conn,
        org_id=org,
        brand_id=brand,
        entity_type="ads_month_budget",
        entity_id=record_id,
        action="confirm",
        actor=actor,
        before={"amount": float(row["amount"])} if row else {},
        after={"month": month, "currency": currency, "amount": float(value)},
    )
    conn.commit()
    return view(conn, org, brand, month)


def preflight(conn, org, brand, month, items):
    lock(conn, org, brand)
    increases = []
    for item in items:
        kind = item.get("kind")
        before, after = item.get("before") or {}, item.get("after") or {}
        if kind in {"launch", "new_ad"} or (
            kind == "budget"
            and (
                before.get("daily_amount") is None
                or money(after.get("daily_amount")) > money(before["daily_amount"])
            )
        ):
            increases.append(item)
    if not increases:
        return {"can_increase": False, "notice": NOTICE}
    if month != settings.today_for_org(conn, org_id=org).strftime("%Y-%m"):
        raise ValueError("新增花費請在執行月份重新確認月預算與最新資料。")
    budget = view(conn, org, brand, month, additional=items)
    if budget["amount"] is None or budget["uncertainties"]:
        raise ValueError("餘額尚不確定，暫不能核准新增花費；可補資料、檢視或核准降低風險的操作。")
    if budget["available"] is None or budget["available"] < 0:
        raise ValueError("這份變更超過本月總額；尚未讀回完成的降額不能先釋放額度。")
    return budget
