import { cn } from "@/lib/utils";
import { Chip, formatAmount } from "./Chip";

/** Kit pieces for the v9 strategy budget cards (prototype `budgetBlock()` and `allocBlock()`). Pure presentational;
 * `data-slot` is what `frontend/scripts/ui-evidence.cjs` compares against the prototype. */

export interface ScenarioRow {
  /** Feature F28 "Budget scenarios": row keys are unchanged (`cap` is the 照預算上限 row). */
  key: string;
  label: string;
  /** null = the row cannot be computed yet (no cost cap) and cannot be picked. */
  total: number | null;
  /** Amount above the budget cap (API `over_cap`); > 0 draws the hatched over segment. */
  overCap: number | null;
  recommended?: boolean;
  saved?: boolean;
}

const OVER_HATCH = "bg-[repeating-linear-gradient(45deg,var(--color-warning)_0_4px,color-mix(in_oklab,var(--color-warning)_45%,white)_4px_8px)]";
const MISSING_HATCH = "bg-[repeating-linear-gradient(45deg,var(--color-border)_0_4px,var(--color-background)_4px_8px)]";
const GRID = "grid w-full grid-cols-[118px_minmax(0,1fr)_150px] items-center gap-3.5 rounded-[10px] border border-transparent px-3 py-2.5 text-left";

/** `.sc` rows under a `預算上限` line: each scenario total as a bar up to the budget cap, the part above it hatched,
 * with the cap as one vertical line through every row. Picking a row only reports `onSelect`; the over-cap
 * confirmation is the caller's (`ConfirmSheet variant="over-cap"`). */
export function ScenarioBars({ rows, budgetCap, selected, onSelect, resultCap = null, missingText = "要先設上限", label = "預算情境" }: {
  rows: ScenarioRow[];
  /** API `budget_cap`; null draws no cap line. */
  budgetCap: number | null;
  selected: string | null;
  onSelect: (key: string) => void;
  /** The campaign's cost-per-result cap, for 「約 N 筆購買」 under an in-cap total. */
  resultCap?: number | null;
  missingText?: string;
  label?: string;
}) {
  const totals = rows.map((r) => r.total ?? 0);
  const max = budgetCap !== null ? Math.max(budgetCap * 1.25, ...totals) : Math.max(1, ...totals) * 1.1;
  const pc = (v: number) => (v / max) * 100;
  return (
    <div data-slot="scenario-bars" role="radiogroup" aria-label={label}>
      {budgetCap !== null && (
        <div className={cn(GRID, "h-[18px] py-0")} aria-hidden="true">
          <span />
          <div className="relative"><span className="absolute -translate-x-1/2 text-[11.5px] font-bold whitespace-nowrap" style={{ left: `${pc(budgetCap)}%` }}>預算上限 {formatAmount(budgetCap)}</span></div>
          <span />
        </div>
      )}
      {rows.map((row) => {
        if (row.total === null) {
          return (
            <div key={row.key} className={cn(GRID, "opacity-60")} data-key={row.key}>
              <div><b className="text-sm">{row.label}</b></div>
              <div className="relative h-4"><i className={cn("absolute inset-0 rounded", MISSING_HATCH)} /></div>
              <div className="text-right text-[11.5px] text-muted-foreground">{missingText}</div>
            </div>
          );
        }
        const over = (row.overCap ?? 0) > 0;
        const within = budgetCap !== null ? Math.min(row.total, budgetCap) : row.total;
        const on = selected === row.key;
        const caption = over
          ? <span className="font-semibold text-warning">超出 {formatAmount(row.overCap)}</span>
          : resultCap ? `約 ${formatAmount(Math.floor(row.total / resultCap))} 筆購買` : budgetCap !== null ? "在預算上限內" : null;
        return (
          <button
            key={row.key} type="button" role="radio" aria-checked={on} data-key={row.key} onClick={() => onSelect(row.key)}
            className={cn(GRID, "hover:bg-accent/40", on && "border-primary bg-accent/50 ring-1 ring-primary")}
          >
            <div className="flex flex-wrap items-center gap-1.5">
              <b className="text-sm">{row.label}</b>
              {row.recommended && <Chip tone="accent">推薦</Chip>}
              {row.saved && <Chip tone="ok">已儲存</Chip>}
            </div>
            <div className="relative h-4" aria-hidden="true">
              <i className="absolute inset-y-0 left-0 rounded bg-primary" style={{ width: `${pc(within)}%` }} />
              {over && budgetCap !== null && (
                <i data-part="over" className={cn("absolute inset-y-0 rounded-r", OVER_HATCH)} style={{ left: `${pc(budgetCap)}%`, width: `${pc(row.overCap as number)}%` }} />
              )}
              {budgetCap !== null && <u className="absolute -top-[5px] -bottom-[5px] border-l-2 border-foreground" style={{ left: `${pc(budgetCap)}%` }} />}
            </div>
            <div className="numeric text-right">
              <b className="block text-[17px]">{formatAmount(row.total)}</b>
              {caption && <span className="text-[11.5px] text-muted-foreground">{caption}</span>}
            </div>
          </button>
        );
      })}
    </div>
  );
}

/** Fill per allocation part, in the order the bar draws its non-zero parts. */
export const ALLOCATION_FILL = ["bg-chart-revenue", "bg-chart-spend", "bg-chart-aqua", "bg-chart-soft", "bg-chart-rest"] as const;

/** The fill each drawn part gets (a 0% part is not drawn and gets none) — exported so a caller that prints its own
 * per-part rows (the strategy tab's 「預算怎麼分」) paints the same swatch as the bar segment. */
export function allocationFills(parts: { key: string; pct: number }[]): Record<string, string> {
  const fills: Record<string, string> = {};
  parts.filter((p) => p.pct > 0).forEach((p, i) => { fills[p.key] = ALLOCATION_FILL[i % ALLOCATION_FILL.length]; });
  return fills;
}

/** `.alloc` + legend: how the period budget splits across audiences. `total === null` prints percentages only
 * (「選好預算後算金額」 is the caller's heading note). `legend={false}` is the F41 prototype's thin `.bb` bar — no text
 * in the segments and no legend line — for a caller that prints one row per part itself (swatches: `allocationFills`). */
export function AllocationBar({ parts, total, legend = true }: { parts: { key: string; label: string; pct: number }[]; total: number | null; legend?: boolean }) {
  const shown = parts.filter((p) => p.pct > 0);
  const fills = allocationFills(parts);
  if (!legend) {
    return (
      <div data-slot="allocation-bar" className="my-2.5 flex h-3 overflow-hidden rounded-md bg-muted" aria-hidden="true">
        {shown.map((p) => <i key={p.key} data-key={p.key} className={cn("block", fills[p.key])} style={{ width: `${p.pct}%` }} />)}
      </div>
    );
  }
  return (
    <div data-slot="allocation-bar">
      <div className="flex h-[34px] gap-0.5 overflow-hidden rounded-lg">
        {shown.map((p) => (
          <i key={p.key} className={cn("flex items-center overflow-hidden px-2.5 text-[12.5px] font-semibold whitespace-nowrap text-white not-italic", fills[p.key])} style={{ width: `${p.pct}%` }}>
            {p.pct >= 15 ? `${p.label} ${p.pct}%` : `${p.pct}%`}
          </i>
        ))}
      </div>
      <div className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-muted-foreground">
        {shown.map((p) => (
          <span key={p.key}>
            <i className={cn("mr-1.5 inline-block size-2 rounded-[2px]", fills[p.key])} />
            {p.label} {p.pct}%{total !== null && `・${formatAmount(Math.round((total * p.pct) / 100))}`}
          </span>
        ))}
      </div>
    </div>
  );
}
