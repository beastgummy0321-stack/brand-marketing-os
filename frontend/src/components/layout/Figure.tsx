import { useFigureBases, formatFigure, type FigureBasis, type FigureUnit } from "@/lib/figures";
import { cn } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "./ui/tooltip";

/** A second basis printed beside the first (「保守 2.10x・樂觀 2.45x」). */
export interface FigureAlt {
  basis: string;
  value: number | null;
}

/** F51 Contract F (W16): one piece prints a number with its basis — the value by the basis unit (money with its
 * currency, a ratio as `2.10x`, a count), the basis `label` as its caption and the `formula` behind a `?` tooltip,
 * all read from `GET /api/figures` (`useFigureBases`), never restated here. Unknown (`null`) prints `unknown`
 * (default 「不明」), never 0. `alt` adds a second basis of the same figure (保守 with 樂觀 beside it). While the
 * bases load the value prints without caption (a money value is told apart by its `currency`). */
export function Figure({
  basis,
  value,
  currency,
  alt,
  unknown = "不明",
  className,
}: {
  /** The basis code — the payload key the value came from (`roas_all_spend`, `earn_after_cost_and_ads` …). */
  basis: string;
  value: number | null | undefined;
  /** A money value's currency (always passed for money: currencies are never mixed). */
  currency?: string | null;
  alt?: FigureAlt;
  /** What an unknown value prints; the payload's own reason when it has one. */
  unknown?: string;
  className?: string;
}) {
  const bases = useFigureBases();
  const main = bases?.[basis];
  const second = alt ? bases?.[alt.basis] : undefined;
  const unitOf = (b: FigureBasis | undefined): FigureUnit => b?.unit ?? (currency ? "money" : "ratio");
  const print = (b: FigureBasis | undefined, v: number | null | undefined) =>
    v == null ? unknown : formatFigure(unitOf(b), v, currency);

  if (alt) {
    return (
      <span data-slot="figure" data-basis={basis} className={cn("inline-flex flex-wrap items-baseline gap-x-1", className)}>
        <Part basis={main} text={print(main, value)} known={value != null} />
        <span aria-hidden="true" className="text-muted-foreground">・</span>
        <Part basis={second} text={print(second, alt.value)} known={alt.value != null} />
      </span>
    );
  }
  return (
    <span data-slot="figure" data-basis={basis} className={cn("inline-flex flex-wrap items-baseline gap-x-1", className)}>
      <span data-slot="figure-value" className={cn("tabular-nums", value == null && "text-muted-foreground")}>
        {print(main, value)}
      </span>
      {main && <Caption basis={main} />}
    </span>
  );
}

/** One basis inside an `alt` pair: caption first, then the value (「保守 2.10x」). */
function Part({ basis, text, known }: { basis: FigureBasis | undefined; text: string; known: boolean }) {
  return (
    <span className="inline-flex items-baseline gap-x-1">
      {basis && <Caption basis={basis} />}
      <span data-slot="figure-value" className={cn("tabular-nums", !known && "text-muted-foreground")}>{text}</span>
    </span>
  );
}

/** The basis label, with its formula behind a `?` (hover or keyboard focus). */
function Caption({ basis }: { basis: FigureBasis }) {
  return (
    <span data-slot="figure-caption" className="inline-flex items-center gap-0.5 text-xs text-muted-foreground">
      {basis.label}
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              aria-label={`${basis.label}怎麼算：${basis.formula}`}
              className="inline-flex size-3.5 items-center justify-center rounded-full border border-border text-[9px] leading-none text-muted-foreground hover:border-primary hover:text-primary"
            >
              ?
            </button>
          </TooltipTrigger>
          <TooltipContent>{basis.formula}</TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </span>
  );
}
