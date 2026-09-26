import { cn } from "@/lib/utils";

/** v10 `connections()` `.calg` (F30): one row per data source, one square per day of the month. A 150px label
 * column, then one equal column per day; the header prints the day number on 1, 5, 10 … 30. Cell states follow
 * Feature F30 Contract H: `ok` filled, `missing` hollow with a dashed danger border, `none` and `future` muted;
 * `today` is ringed. Every cell carries a title such as 「9/17 缺資料」. Dates are ISO `YYYY-MM-DD` in the org
 * timezone (the caller's read already fixed the zone). `data-slot="day-grid"`. */

export type DayState = "ok" | "missing" | "none" | "future";
export interface DayGridRow { key: string; label: string; days: { date: string; state: DayState }[] }

/** Swatch classes per state, shared with `Legend` so the legend and the grid never drift. */
export const DAY_SWATCH: Record<DayState | "today", string> = {
  ok: "bg-chart-revenue",
  missing: "border-[1.5px] border-dashed border-danger bg-card",
  none: "bg-muted",
  future: "bg-muted",
  today: "bg-card shadow-[0_0_0_1.5px_var(--color-foreground)]",
};

export const DAY_WORD: Record<DayState, string> = { ok: "有資料", missing: "缺資料", none: "不需要", future: "還沒到" };

const TICKS = new Set([1, 5, 10, 15, 20, 25, 30]);
const dayOf = (iso: string) => Number(iso.slice(8, 10));
const shortDate = (iso: string) => `${Number(iso.slice(5, 7))}/${dayOf(iso)}`;

export function DayGrid({ rows, today, label = "每天的資料" }: { rows: DayGridRow[]; today?: string | null; label?: string }) {
  if (rows.length === 0) return null;
  const dates = rows[0].days.map((d) => d.date);
  return (
    <div data-slot="day-grid" role="group" aria-label={label}
      className="grid items-center gap-[3px]" style={{ gridTemplateColumns: `150px repeat(${dates.length}, minmax(0, 1fr))` }}>
      <span />
      {dates.map((d) => <span key={d} aria-hidden="true" className="text-center text-[10.5px] text-muted-foreground">{TICKS.has(dayOf(d)) ? dayOf(d) : ""}</span>)}
      {rows.map((row) => [
        // Prototype `.calg` labels wrap: a long account name takes more lines in its 150px column, never an ellipsis.
        <span key={`${row.key}:label`} className="pr-2 text-xs leading-snug font-medium [overflow-wrap:anywhere]">{row.label}</span>,
        ...row.days.map((d) => {
          const title = `${shortDate(d.date)} ${DAY_WORD[d.state]}`;
          return (
            <span key={`${row.key}:${d.date}`} role="img" title={title} aria-label={`${row.label} ${title}`} data-state={d.state}
              data-today={d.date === today ? "" : undefined}
              className={cn("aspect-square min-w-0 rounded", DAY_SWATCH[d.state],
                d.date === today && "shadow-[0_0_0_2px_var(--color-card),0_0_0_3.5px_var(--color-foreground)]")} />
          );
        }),
      ])}
    </div>
  );
}
