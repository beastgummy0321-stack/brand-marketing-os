import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";

/** v10 `wsHead()` `.rail` (F30): the campaign workspace's stage rail — six clickable stations joined by short
 * connectors. A done station shows ✓ on a soft disc, the current one is filled and carries `aria-current="step"`,
 * the rest show their number. A connector is filled (`.rail s.dn`) when the station after it is done or current.
 * A station with `to` is a link; without it, `onSelect(key)` runs. `data-slot="stage-rail"`. */

export interface StageStation { key: string; label: string; to?: string }

export function StageRail({ stations, current, done, onSelect, label = "活動進度" }: {
  stations: StageStation[];
  /** Key of the current station (Feature F30 Contract E `stage.key`). */
  current: string;
  /** Keys of the done stations (Contract E `stage.done`); not assumed to be a prefix of the list. */
  done: string[];
  onSelect?: (key: string) => void;
  label?: string;
}) {
  const doneSet = new Set(done);
  return (
    <nav data-slot="stage-rail" aria-label={label} className="mt-4 mb-[18px]">
      <ol className="flex flex-wrap items-center gap-y-2">
        {stations.map((s, i) => {
          const on = s.key === current;
          const dn = !on && doneSet.has(s.key);
          const state = on ? "current" : dn ? "done" : "todo";
          const cls = cn(
            "flex items-center gap-2 rounded-lg px-1.5 py-1 text-[13px]",
            on ? "font-bold text-foreground" : "font-medium text-muted-foreground hover:text-foreground",
          );
          const body = (
            <>
              <i aria-hidden="true" className={cn("grid size-6 shrink-0 place-items-center rounded-full text-[11.5px] font-bold not-italic",
                on ? "bg-primary text-primary-foreground ring-4 ring-accent" : dn ? "bg-secondary text-accent-foreground" : "bg-muted")}>
                {dn ? "✓" : i + 1}
              </i>
              {dn && <span className="sr-only">已完成：</span>}
              {s.label}
            </>
          );
          return (
            <li key={s.key} data-state={state} className="flex items-center">
              {i > 0 && <span aria-hidden="true" className={cn("h-0.5 w-7 shrink-0", on || dn ? "bg-chart-soft" : "bg-border")} />}
              {s.to
                ? <Link to={s.to} className={cls} aria-current={on ? "step" : undefined}>{body}</Link>
                : <button type="button" className={cls} aria-current={on ? "step" : undefined} onClick={() => onSelect?.(s.key)}>{body}</button>}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
