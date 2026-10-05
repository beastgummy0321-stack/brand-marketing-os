/** F36-I08 (drill-6 #20, ruling G, Contract U); F50-I12 (feature F50 Contract K, audit W11): the one module that
 * builds or reads a `Date`.
 *
 * Root cause this closes: the ads screens printed every stamp in the viewer's zone, counted days from the laptop's
 * clock and parsed a picked date as UTC midnight, because the frontend had no primitive for the organisation's
 * calendar. `/api/identity/me` carries `org.timezone` (IANA) and `org.today`; this module turns the timezone into
 * dates and prints instants in it. `today` from `/me` is only the boot value — `useOrgClock()` recomputes from the
 * timezone on every render so a tab left open overnight does not freeze on the load date.
 *
 * Two kinds of value cross this boundary, both strings: a calendar day `YYYY-MM-DD` (day arithmetic is pure and
 * zone-free: `addDays`, `daysBetween`, `dayList`, `shiftMonth`) and an ISO instant, printed only through
 * `formatInstant(iso, tz, style)` or turned into the org's day with `orgDateOf(iso, tz)`. No Date object leaves this
 * module, so callers cannot slide back into local-time arithmetic; `clockGuards.test.ts` keeps it that way. */
import { useWorkspace } from "@/components/layout/WorkspaceContext";

/** Mirrors `app/core/settings.py::DEFAULT_ORG_TIMEZONE` and its fallback rule: an unknown or
 * empty timezone name is treated as "not set", never as an error. */
export const DEFAULT_ORG_TIMEZONE = "Asia/Taipei";

const DAY_MS = 86_400_000;
const PLAIN_DAY = /^(\d{4})-(\d{2})-(\d{2})$/;

function partsFormatter(tz: string): Intl.DateTimeFormat {
  // `sv-SE` prints ISO order (YYYY-MM-DD); parts are read by type below so the locale is only a
  // convention, not load-bearing.
  return new Intl.DateTimeFormat("sv-SE", {
    timeZone: tz,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
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

interface Zoned { y: number; m: number; d: number; h: number; min: number }

function zoned(tz: string, at: Date): Zoned {
  const parts = partsFormatter(resolveOrgTimezone(tz)).formatToParts(at);
  const read = (type: Intl.DateTimeFormatPartTypes) =>
    Number(parts.find((part) => part.type === type)?.value);
  return { y: read("year"), m: read("month"), d: read("day"), h: read("hour") % 24, min: read("minute") };
}

function ymdToString(y: number, m: number, d: number): string {
  // Date.UTC normalises overflow (day 32 → next month) and negative days; noon UTC keeps the
  // result inside the same civil day whatever the zone offset, so DST edges cannot shift it.
  return new Date(Date.UTC(y, m - 1, d, 12)).toISOString().slice(0, 10);
}

/** An ISO instant (also the `2026-10-01 15:10:33.055275+00:00` text Python prints) as a Date; null when unreadable
 * or when it carries no offset — a bare date is a calendar day, not an instant. */
function parseInstant(iso: string | null | undefined): Date | null {
  if (!iso || PLAIN_DAY.test(iso)) return null;
  const at = new Date(iso.trim().replace(" ", "T").replace(/(\.\d{3})\d+/, "$1"));
  return Number.isNaN(at.getTime()) ? null : at;
}

function dayParts(ymd: string): { y: number; m: number; d: number } | null {
  const match = PLAIN_DAY.exec(ymd);
  if (!match) return null;
  return { y: Number(match[1]), m: Number(match[2]), d: Number(match[3]) };
}

const pad = (n: number) => String(n).padStart(2, "0");

/** Today's calendar date (YYYY-MM-DD) in `tz`. */
export function orgToday(tz: string): string {
  const { y, m, d } = zoned(tz, new Date());
  return ymdToString(y, m, d);
}

/** Today in `tz` shifted by `days` (negative = past), crossing month and year boundaries. */
export function orgDateShift(tz: string, days: number): string {
  const { y, m, d } = zoned(tz, new Date());
  return ymdToString(y, m, d + days);
}

/** The org's calendar day (YYYY-MM-DD) an instant falls on; a plain `YYYY-MM-DD` is returned as is; unreadable → null. */
export function orgDateOf(iso: string | null | undefined, tz: string): string | null {
  if (iso && PLAIN_DAY.test(iso)) return iso;
  const at = parseInstant(iso);
  if (!at) return null;
  const { y, m, d } = zoned(tz, at);
  return ymdToString(y, m, d);
}

/** How a calendar day prints: `md` 10/3, `mmdd` 10/03, `ymd` 2026/10/03. */
export type DayStyle = "md" | "mmdd" | "ymd";
/** How an instant prints in the org zone: the day styles, `md_hm` 10/03 14:05 and `hm` 14:05. */
export type InstantStyle = DayStyle | "md_hm" | "hm";

/** A `YYYY-MM-DD` day in `style`; "" when it is not a day. */
export function formatDay(ymd: string | null | undefined, style: DayStyle): string {
  const p = ymd ? dayParts(ymd) : null;
  if (!p) return "";
  if (style === "md") return `${p.m}/${p.d}`;
  if (style === "mmdd") return `${pad(p.m)}/${pad(p.d)}`;
  return `${p.y}/${pad(p.m)}/${pad(p.d)}`;
}

/** An ISO instant printed on the org's clock (`tz`); "" when it is missing or unreadable. */
export function formatInstant(iso: string | null | undefined, tz: string, style: InstantStyle): string {
  const at = parseInstant(iso);
  if (!at) return "";
  const z = zoned(tz, at);
  const hm = `${pad(z.h)}:${pad(z.min)}`;
  if (style === "hm") return hm;
  if (style === "md_hm") return `${pad(z.m)}/${pad(z.d)} ${hm}`;
  return formatDay(ymdToString(z.y, z.m, z.d), style);
}

/** `ymd` shifted by `n` calendar days. */
export function addDays(ymd: string, n: number): string {
  const p = dayParts(ymd);
  return p ? ymdToString(p.y, p.m, p.d + n) : ymd;
}

function dayNumber(ymd: string): number | null {
  const p = dayParts(ymd);
  return p ? Math.round(Date.UTC(p.y, p.m - 1, p.d) / DAY_MS) : null;
}

/** Days from `a` to `b` counting both ends (10/01–10/07 → 7); null when either is not a day. */
export function daysBetween(a: string, b: string): number | null {
  const start = dayNumber(a), end = dayNumber(b);
  return start === null || end === null ? null : end - start + 1;
}

/** Every day from `a` to `b` inclusive, at most `max` of them (empty when `b` is before `a`). */
export function dayList(a: string, b: string, max = 400): string[] {
  const count = daysBetween(a, b);
  if (count === null || count <= 0) return [];
  return Array.from({ length: Math.min(count, max) }, (_, i) => addDays(a, i));
}

/** `YYYY-MM` shifted by whole months. */
export function shiftMonth(ym: string, n: number): string {
  const [y, m] = ym.split("-").map(Number);
  const total = y * 12 + (m - 1) + n;
  return `${Math.floor(total / 12)}-${pad((total % 12 + 12) % 12 + 1)}`;
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
