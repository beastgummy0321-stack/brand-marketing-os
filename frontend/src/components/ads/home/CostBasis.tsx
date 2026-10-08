import { formatAmount } from "../patterns";
import { currencyPrefix } from "./MonthMoney";

/** A comparable hypothetical cost reference, never paid profit or attributed revenue. */
export function CostBasis({ value, currency }: { value: number | null; currency: string | null }) {
  if (value === null || currency === null) return null;
  return <span className="block text-xs text-muted-foreground">假設打平成本 {currencyPrefix(currency)}{formatAmount(value)}</span>;
}
