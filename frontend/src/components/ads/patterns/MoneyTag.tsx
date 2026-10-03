import { cn } from "@/lib/utils";
import { formatAmount } from "./Chip";
import { Term } from "./Term";
import { useAdsRules } from "./rules";

export type MoneyTone = "gain" | "even" | "loss";
export interface MoneyFact { tone: MoneyTone; label: "有賺" | "剛好打平" | "在虧" }

/** Feature F29 Contract K: a cost per result measured against break-even (not the cap). Either value unknown, or the
 * served band (`rules.grade.break_even_band`, F48 Contract R-API) not loaded → null (never a guess). Within ±band of
 * break-even is 剛好打平; below is 有賺; above is 在虧. */
export function moneyTag(cost: number | null | undefined, breakEven: number | null | undefined, band: number | null | undefined): MoneyFact | null {
  if (cost === null || cost === undefined || breakEven === null || breakEven === undefined) return null;
  if (band === null || band === undefined) return null;
  if (!Number.isFinite(cost) || !Number.isFinite(breakEven)) return null;
  // The small epsilon keeps an exact ±band (e.g. 509.6 against 520) on the 打平 side despite float rounding.
  if (Math.abs(cost - breakEven) <= Math.abs(breakEven) * band + 1e-9) return { tone: "even", label: "剛好打平" };
  return cost < breakEven ? { tone: "gain", label: "有賺" } : { tone: "loss", label: "在虧" };
}

const TONE: Record<MoneyTone, string> = {
  gain: "text-success-strong",
  even: "text-muted-foreground",
  loss: "text-grade-wasted-foreground",
};

/** v10 `.mtag`: 「・有賺（打平 520）」 beside a cost per result; hidden when either number (or the served band) is unknown.
 * `plain` (inside labels and buttons) drops the glossary term. `data-slot="money-tag"`. */
export function MoneyTag({ cost, breakEven, plain = false, className }: { cost: number | null | undefined; breakEven: number | null | undefined; plain?: boolean; className?: string }) {
  const rules = useAdsRules();
  const fact = moneyTag(cost, breakEven, rules?.grade.break_even_band);
  if (!fact) return null;
  return (
    <span data-slot="money-tag" data-variant={fact.tone} className={cn("text-[11.5px] font-medium whitespace-nowrap", TONE[fact.tone], className)}>
      ・<Term k="money" plain={plain}>{fact.label}</Term>（打平 {formatAmount(breakEven)}）
    </span>
  );
}
