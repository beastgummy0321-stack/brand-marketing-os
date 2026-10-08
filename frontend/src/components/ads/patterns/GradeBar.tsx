import { GRADE_FILL, formatAmount, type Grade } from "./Chip";
import { GradeRules } from "./GradeRules";
import { gradeWord, useAdsRules } from "./rules";

/** One bucket of spend per grade (Feature F29 Contract C/E `buckets`). `amount` null = unknown: it draws no
 * width and prints as unknown, never as 0. */
export interface GradeBarBucket { grade: Grade | "ungraded"; amount: number | null; count: number; currency?: string | null }

const HATCH = "bg-[repeating-linear-gradient(45deg,var(--color-border)_0_4px,var(--color-background)_4px_8px)]";
const ORDER = [
  { key: "on_target", fill: GRADE_FILL.on_target },
  { key: "watch", fill: GRADE_FILL.watch },
  { key: "over", fill: GRADE_FILL.over },
  { key: "wasted", fill: GRADE_FILL.wasted },
  { key: "insufficient", fill: HATCH },
  { key: "no_target", fill: GRADE_FILL.no_target }, // 未判斷 (no cap, or `ungraded`)
] as const;

/** v10 `gradeBar()` (settle step 1, month review): the period's spend split by grade, with a legend of
 * 「<grade> N 則・X 元」 and — unless `rules={false}` — the grade rules under it. `data-slot="grade-bar"`. */
export function GradeBar({ buckets, withMoney = false, thinLabel, rules = true, breakEven }: {
  buckets: GradeBarBucket[];
  withMoney?: boolean;
  /** Replaces 「剛開始、數字還不夠」 in the legend when a screen words the thin bucket differently. */
  thinLabel?: string;
  rules?: boolean;
  breakEven?: number | null;
}) {
  const merged = ORDER.map((o) => {
    const own = buckets.filter((b) => b.grade === o.key || (o.key === "no_target" && b.grade === "ungraded"));
    const known = own.filter((b) => typeof b.amount === "number" && Number.isFinite(b.amount));
    const units = new Set(own.map((b) => typeof b.currency === "string" && b.currency.trim() ? b.currency : null));
    const currency = units.size === 1 ? [...units][0] : null;
    const amount = own.length === 1 ? known[0]?.amount ?? null
      : own.length && known.length === own.length && currency ? known.reduce((s, b) => s + (b.amount as number), 0) : null;
    return {
      ...o,
      count: own.reduce((s, b) => s + b.count, 0),
      currency,
      amount,
      supplied: own.length > 0,
      width: amount ?? 0, // ZERO_OK: absent width is geometry only; comparable requires every supplied amount known before summing widths.
    };
  }).filter((o) => o.supplied);
  const units = new Set(merged.map((o) => o.currency));
  const comparable = merged.length > 0 && units.size === 1 && !units.has(null) && merged.every((o) => o.amount !== null);
  const total = comparable ? merged.reduce((s, o) => s + o.width, 0) : 0;
  const served = useAdsRules();
  // Served words (F48 Contract R-API); the thin bucket reads 剛開始、數字還不夠 unless the screen words it itself.
  const label = (key: (typeof ORDER)[number]["key"]) => (key === "insufficient" && thinLabel ? thinLabel : gradeWord(served, key) ?? "");
  return (
    <div data-slot="grade-bar">
      <div className="mt-1 mb-2 flex h-3 overflow-hidden rounded-md bg-muted" aria-hidden="true">
        {total > 0 && merged.map((o) => (o.width > 0 ? <i key={o.key} data-grade={o.key} className={`block ${o.fill}`} style={{ width: `${(o.width / total) * 100}%` }} /> : null))}
      </div>
      {merged.length > 0 && !comparable && <p className="mb-2 text-xs text-muted-foreground">{units.size === 1 && !units.has(null)
        ? "花費金額未知，不比較花費占比。"
        : "幣別不同或尚未核實，不比較花費占比。"}</p>}
      <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-muted-foreground">
        {merged.map((o) => (
          <span key={o.key} data-grade={o.key}>
            <i aria-hidden="true" className={`mr-[5px] inline-block size-2 rounded-[2px] ${o.fill}`} />
            {label(o.key)} {o.count} 則
            {withMoney && (o.amount === null ? "・金額未知" : `・${formatAmount(o.amount)} ${o.currency ?? "幣別未知"}`)}
          </span>
        ))}
      </div>
      {rules && <GradeRules breakEven={breakEven} />}
    </div>
  );
}
