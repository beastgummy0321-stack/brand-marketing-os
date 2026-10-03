"""scripts/drill/clock.py — drill-only clock: make the product believe today is another day.

Drill 6 (2026-09-26) runs three one-week ad periods in one afternoon. The product asks
"what day is it" through one choke point, `app.core.settings.today_for_org` (ticket 04-1b), so
that is the only thing patched: when `.scratch/drill/today` holds an ISO date, that date is
today for every org. Audit timestamps (`datetime.now(UTC)`) stay real, as that function's own
docstring says they should. `app.ads.triage` binds the name at import, so it is patched too.

Not for the product: only `scripts/drill/serve.py` and `scripts/drill/worker.py` call this.

    python -m scripts.drill.clock set 2026-10-02
    python -m scripts.drill.clock clear
    python -m scripts.drill.clock show
"""

import sys
from datetime import date, datetime
from pathlib import Path

TODAY_PATH = Path(__file__).resolve().parents[2] / ".scratch" / "drill" / "today"


def override() -> date | None:
    try:
        text = TODAY_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    return date.fromisoformat(text) if text else None


def install() -> None:
    from app.core import settings as coresettings

    real = coresettings.today_for_org

    def today_for_org(conn, *, org_id):
        return override() or real(conn, org_id=org_id)

    coresettings.today_for_org = today_for_org
    try:
        from app.ads import triage
        triage.today_for_org = today_for_org
    except ImportError:
        pass


def patch_modules(prefix: str = "app.") -> int:
    """Make `app.core.db.now_utc()` follow the drill clock (real time of day, drill date) —
    it is the one wall clock the ads centre reads besides `today_for_org` (review windows check
    the account's timezone through it; audit `*_at` columns take it too, so timestamps move with
    the drill, monotonic as long as the clock only moves forward). Also rebinds the name in any
    loaded `app.*` module that imported it directly. Call after the app is imported. The
    periodic sync throttle (`runtime._due`) compares against the real clock, so the operator
    requests syncs by hand per period (`fake_meta sync`), as the daily cron would."""
    import sys
    from app.core import db

    real = getattr(db, "_drill_real_now_utc", None) or db.now_utc
    db._drill_real_now_utc = real

    from datetime import timedelta, timezone

    local = timezone(timedelta(hours=8))  # drill orgs are Asia/Taipei

    def now_utc():
        # Swap the date in local time: on UTC, before 08:00 local the drill day ran one day ahead
        # (drill 11 — triage cutoff past the synced window, every ad 資料不足).
        value = real()
        o = override()
        if not o:
            return value
        return value.astimezone(local).replace(year=o.year, month=o.month, day=o.day).astimezone(value.tzinfo)

    n = 0
    for name, mod in list(sys.modules.items()):
        if not (name == "app" or name.startswith(prefix)) or mod is None:
            continue
        if getattr(mod, "now_utc", None) is real:
            mod.now_utc = now_utc
            n += 1
    return n


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd == "set":
        TODAY_PATH.parent.mkdir(parents=True, exist_ok=True)
        TODAY_PATH.write_text(date.fromisoformat(sys.argv[2]).isoformat(), encoding="utf-8")
        print(f"演練時鐘：今天＝{sys.argv[2]}（後端與 worker 會立即讀到，不用重啟）")
    elif cmd == "clear":
        TODAY_PATH.unlink(missing_ok=True)
        print("演練時鐘已清除，回到真實日期")
    else:
        print(override() or "（未設定，真實日期）")
