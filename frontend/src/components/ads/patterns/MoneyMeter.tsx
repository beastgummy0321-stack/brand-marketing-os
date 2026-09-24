import { cn } from "@/lib/utils";
import { formatAmount } from "./Chip";

/** Kit piece for the v9 cost meter with a cap line: `.cpm` (home money card, size `lg` with the 0 / cap / end axis)
 * and `.hb` (home campaign rows, size `sm`). `data-slot="money-meter"` + `data-variant` = size.
 *
 * With a cap the axis runs to 4/3 × cap, so the cap line sits at 75% exactly as in the prototype. The fill colour
 * compares the value with the cap (≤ cap 划算 green, ≤ 1.2 × cap amber, above red). `value === null` draws the
 * empty track only — never a zero-length bar that reads as 0. */

export type MoneyMeterTone = "auto" | "primary";

export function MoneyMeter({ value, cap = null, max, size = "sm", tone = "auto" }: {
  value: number | null;
  cap?: { value: number; basis: "own" | "break_even" } | null;
  /** Axis end when there is no cap (the prototype's fixed fallback, or the month total for a share bar). */
  max?: number | null;
  size?: "lg" | "sm";
  /** `primary`: a plain share bar (「花了多少」 column) instead of a cost-vs-cap colour. */
  tone?: MoneyMeterTone;
}) {
  const scale = cap ? (cap.value * 4) / 3 : max ?? null;
  const known = value !== null && scale !== null && scale > 0;
  const pct = known ? Math.min(100, Math.max(0, ((value as number) / (scale as number)) * 100)) : 0;
  const fill = tone === "primary"
    ? "bg-primary"
    : !cap
      ? size === "lg" ? "bg-success" : "bg-chart-rest"
      : (value as number) <= cap.value ? "bg-success" : (value as number) <= cap.value * 1.2 ? "bg-warning/80" : "bg-danger";
  const lg = size === "lg";
  return (
    <div data-slot="money-meter" data-variant={size}>
      <div className={cn("relative bg-muted", lg ? "mt-2.5 h-2.5 rounded-md" : "h-2 rounded-[5px]")} aria-hidden="true">
        {known && <i className={cn("absolute inset-y-0 left-0", lg ? "rounded-md" : "rounded-[5px]", fill)} style={{ width: `${pct}%` }} />}
        {cap && <u className={cn("absolute left-3/4 w-0.5 bg-foreground", lg ? "-top-[5px] -bottom-[5px]" : "-top-1 -bottom-1")} />}
      </div>
      {lg && (
        <div className="numeric relative mt-1.5 h-4 text-xs text-muted-foreground">
          <span className="absolute left-0">0</span>
          {cap && <span className="absolute left-3/4 -translate-x-1/2 whitespace-nowrap">{cap.basis === "break_even" ? "打平" : "上限"} {formatAmount(cap.value)}</span>}
          {scale !== null && <span className="absolute right-0">{formatAmount(Math.round(scale))}</span>}
        </div>
      )}
    </div>
  );
}
