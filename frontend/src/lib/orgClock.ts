/** F36-I08 (drill-6 #20, ruling G, Contract U): the one place the ads UI asks "what day is it".
 *
 * Root cause this closes: six ads screens computed date defaults from `new Date()` (some
 * local, one UTC) because the frontend had no primitive for the organisation's timezone.
 * `/api/identity/me` now carries `org.timezone` (IANA) and `org.today`; this module turns the
 * timezone into dates. `today` from `/me` is only the boot value — `useOrgClock()` recomputes
 * from the timezone on every render so a tab left open overnight does not freeze on the load
 * date. The three `revisit_at` inputs keep the browser clock on purpose: they send an instant,
 * not a calendar date.
 *
 * Dates are YYYY-MM-DD strings. No Date objects leave this module, so callers cannot slide back
 * into local-time arithmetic. */
import { useWorkspace } from "@/components/layout/WorkspaceContext";

/** Mirrors `app/core/settings.py::DEFAULT_ORG_TIMEZONE` and its fallback rule: an unknown or
 * empty timezone name is treated as "not set", never as an error. */
export const DEFAULT_ORG_TIMEZONE = "Asia/Taipei";

function partsFormatter(tz: string): Intl.DateTimeFormat {
  // `sv-SE` prints ISO order (YYYY-MM-DD); parts are read by type below so the locale is only a
  // convention, not load-bearing.
  return new Intl.DateTimeFormat("sv-SE", {
    timeZone: tz,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

/** The timezone name to actually use: `tz` when Intl accepts it, else the default. */
export function resolveOrgTimezone(tz: string | null | undefined): string {
  if (!tz) return DEFAULT_ORG_TIMEZONE;
  try {
    partsFormatter(tz);
    return tz;
  } catch {
    return DEFAULT_ORG_TIMEZONE;
  }
}

function zonedYmd(tz: string, at: Date): { y: number; m: number; d: number } {
  const parts = partsFormatter(resolveOrgTimezone(tz)).formatToParts(at);
  const read = (type: Intl.DateTimeFormatPartTypes) =>
    Number(parts.find((part) => part.type === type)?.value);
  return { y: read("year"), m: read("month"), d: read("day") };
}

function ymdToString(y: number, m: number, d: number): string {
  // Date.UTC normalises overflow (day 32 → next month) and negative days; noon UTC keeps the
  // result inside the same civil day whatever the zone offset, so DST edges cannot shift it.
  return new Date(Date.UTC(y, m - 1, d, 12)).toISOString().slice(0, 10);
}

/** Today's calendar date (YYYY-MM-DD) in `tz`. */
export function orgToday(tz: string): string {
  const { y, m, d } = zonedYmd(tz, new Date());
  return ymdToString(y, m, d);
}

/** Today in `tz` shifted by `days` (negative = past), crossing month and year boundaries. */
export function orgDateShift(tz: string, days: number): string {
  const { y, m, d } = zonedYmd(tz, new Date());
  return ymdToString(y, m, d + days);
}

export interface OrgClock {
  timezone: string;
  today: string;
  shift: (days: number) => string;
}

/** The org clock for the current workspace. Must run under `WorkspaceProvider`. */
export function useOrgClock(): OrgClock {
  const { identity } = useWorkspace();
  const timezone = resolveOrgTimezone(identity.org.timezone);
  return {
    timezone,
    today: orgToday(timezone),
    shift: (days: number) => orgDateShift(timezone, days),
  };
}
