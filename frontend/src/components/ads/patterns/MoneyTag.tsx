import { cn } from "@/lib/utils";
import { formatAmount } from "./Chip";
import { Term } from "./Term";

export type MoneyTone = "gain" | "even" | "loss";
export interface MoneyFact { tone: MoneyTone; label: "有賺" | "剛好打平" | "在虧" }

/** Feature F29 Contract K: a cost per result measured against break-even (not the cap). Either value unknown →
 * null (never a guess). Within 2 % of break-even is 剛好打平; below is 有賺; above is 在虧. */
export function moneyTag(cost: number | null | undefined, breakEven: number | null | undefined): MoneyFact | null {
  if (cost === null || cost === undefined || breakEven === null || breakEven === undefined) return null;
  if (!Number.isFinite(cost) || !Number.isFinite(breakEven)) return null;
  // The small epsilon keeps an exact ±2 % (e.g. 509.6 against 520) on the 打平 side despite float rounding.
  if (Math.abs(cost - breakEven) <= Math.abs(breakEven) * 0.02 + 1e-9) return { tone: "even", label: "剛好打平" };
  return cost < breakEven ? { tone: "gain", label: "有賺" } : { tone: "loss", label: "在虧" };
}

const TONE: Record<MoneyTone, string> = {
  gain: "text-success-strong",
  even: "text-muted-foreground",
  loss: "text-grade-wasted-foreground",
};

/** v10 `.mtag`: 「・有賺（打平 520）」 beside a cost per result; hidden when either number is unknown.
 * `plain` (inside labels and buttons) drops the glossary term. `data-slot="money-tag"`. */
export function MoneyTag({ cost, breakEven, plain = false, className }: { cost: number | null | undefined; breakEven: number | null | undefined; plain?: boolean; className?: string }) {
  const fact = moneyTag(cost, breakEven);
  if (!fact) return null;
  return (
    <span data-slot="money-tag" data-variant={fact.tone} className={cn("text-[11.5px] font-medium whitespace-nowrap", TONE[fact.tone], className)}>
      ・<Term k="money" plain={plain}>{fact.label}</Term>（打平 {formatAmount(breakEven)}）
    </span>
  );
}
