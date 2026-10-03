import { useId, type ReactNode } from "react";
import { Chip, GRADE_TONE, type Grade } from "./Chip";
import { define, type GlossaryKey } from "./glossary";
import { gradeWord, useAdsRules } from "./rules";

/** v10 `.term`: a coined word with a dotted underline; its served glossary sentence (`glossary.ts`, F48 Contract
 * R-API) shows on hover, keyboard focus and tap (a tap focuses it). `plain` prints only the word — for labels and
 * buttons, where a tap must trigger the control. While the rules are not loaded the word prints without its sentence.
 * `data-slot="term"`. */
export function Term({ k, value, plain = false, children }: {
  k: GlossaryKey;
  /** Break-even's own value, shown inside its sentence. */
  value?: number | null;
  plain?: boolean;
  children: ReactNode;
}) {
  const id = useId();
  const rules = useAdsRules();
  if (plain) return <>{children}</>;
  const sentence = define(k, value, rules);
  if (!sentence) return <span data-slot="term">{children}</span>;
  return (
    <span
      data-slot="term" tabIndex={0} aria-describedby={id}
      onKeyDown={(e) => { if (e.key === "Escape") e.currentTarget.blur(); }}
      className="group/term relative inline cursor-help border-b border-dotted border-current outline-offset-2"
    >
      {children}
      <span
        role="tooltip" id={id}
        className="absolute top-[calc(100%+6px)] left-0 z-30 hidden w-max max-w-[min(260px,70vw)] rounded-lg bg-foreground px-[11px] py-2 text-left text-xs leading-normal font-normal tracking-normal whitespace-normal text-white group-hover/term:block group-focus/term:block"
      >
        {sentence}
      </span>
    </span>
  );
}

const GRADE_TERM: Record<Grade, GlossaryKey | null> = {
  on_target: "on_target", watch: "watch", over: "over", wasted: "wasted", insufficient: "thin", no_target: null,
};

/** v10 `gchip(g)`: the grade chip whose word is a glossary term. The word is the payload's `label` first, else the
 * served word of the grade (`reasonCode` splits `insufficient` into 剛開始／資料不足). `plain` (inside a label or button)
 * is the v9 `GradeChip` look without the term. `grade === null` prints 未判斷. */
export function GradeTermChip({ grade, label, reasonCode, plain = false, className }: {
  grade: Grade | null; label?: string | null; reasonCode?: string | null; plain?: boolean; className?: string;
}) {
  const rules = useAdsRules();
  const g = grade ?? "no_target";
  const key = g === "insufficient" && reasonCode && reasonCode !== "too_new" ? null : GRADE_TERM[g];
  const word = label || gradeWord(rules, g, reasonCode) || "";
  return (
    <Chip tone={GRADE_TONE[g]} data-grade={g} className={className}>
      {key && !plain ? <Term k={key}>{word}</Term> : word}
    </Chip>
  );
}
