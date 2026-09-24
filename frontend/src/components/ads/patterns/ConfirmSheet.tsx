import { useId, type ComponentProps, type ReactNode } from "react";
import { Button } from "@/components/layout/ui/button";
import { cn } from "@/lib/utils";
import { formatAmount } from "./Chip";

/** Kit piece for the v9 inline confirmations that need an explicit second yes (prototype `budgetBlock()` `.confirm`
 * and `act.revertOpen` `.sheet`): `over-cap` (a budget above the budget cap, Feature F28 "Budget scenarios") and
 * `revert` (改回核准時的設定, "Stale launch"). Inline under the content, not a modal.
 * `data-slot="confirm-sheet"` + `data-variant` is what `frontend/scripts/ui-evidence.cjs` compares. */

const OVER_HATCH = "bg-[repeating-linear-gradient(45deg,var(--color-warning)_0_4px,color-mix(in_oklab,var(--color-warning)_45%,white)_4px_8px)]";

export function ConfirmSheet({ variant, title, split, children, actions }: {
  variant: "over-cap" | "revert";
  title: ReactNode;
  /** over-cap: the chosen total split at the budget cap (`within` = the cap, `over` = API `over_cap`). */
  split?: { within: number; over: number };
  /** Body lines (revert: each diffed value 「field：now → approved」). */
  children?: ReactNode;
  actions: ReactNode;
}) {
  const titleId = useId();
  if (variant === "revert") {
    return (
      <section data-slot="confirm-sheet" data-variant="revert" role="alertdialog" aria-labelledby={titleId} className="mt-3.5 flex flex-wrap items-end gap-3 rounded-[10px] bg-warning/10 px-4 py-3.5">
        <div className="min-w-60 flex-1">
          <b id={titleId}>{title}</b>
          {children && <div className="text-xs text-muted-foreground">{children}</div>}
        </div>
        <div className="flex flex-wrap gap-2">{actions}</div>
      </section>
    );
  }
  const total = split ? split.within + split.over : 0;
  return (
    <section data-slot="confirm-sheet" data-variant="over-cap" role="alertdialog" aria-labelledby={titleId} className="mt-3 flex flex-wrap items-center gap-4 rounded-[10px] border border-warning/30 bg-warning/10 px-[18px] py-3.5">
      <span className="grid size-10 shrink-0 place-items-center rounded-full bg-warning/80 font-bold text-white" aria-hidden="true">!</span>
      <div className="min-w-60 flex-1">
        <b id={titleId} className="text-[15px]">{title}</b>
        {split && total > 0 && (
          <>
            <div className="mt-2 mb-1.5 flex h-3 overflow-hidden rounded-md bg-muted" aria-hidden="true">
              <i className="block bg-primary" style={{ width: `${(split.within / total) * 100}%` }} />
              <i className={cn("block flex-1", OVER_HATCH)} />
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-muted-foreground">
              <span><i className="mr-1.5 inline-block size-2 rounded-[2px] bg-primary" />預算上限內 {formatAmount(split.within)}</span>
              <span><i className="mr-1.5 inline-block size-2 rounded-[2px] bg-warning/80" />超出 {formatAmount(split.over)}</span>
            </div>
          </>
        )}
        {children}
      </div>
      <div className="flex flex-wrap gap-2">{actions}</div>
    </section>
  );
}

/** The prototype's `.btn.warnp`: the one amber-filled "yes, even so" button inside a ConfirmSheet. */
export function WarnButton({ className, ...props }: ComponentProps<typeof Button>) {
  return <Button {...props} data-variant="warn" className={cn("bg-warning/85 text-white hover:bg-warning", className)} />;
}
