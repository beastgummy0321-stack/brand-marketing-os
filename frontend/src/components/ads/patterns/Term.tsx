import { useId, type ReactNode } from "react";
import { Chip, GRADE_LABEL, GRADE_TONE, type Grade } from "./Chip";
import { define, type GlossaryKey } from "./glossary";

/** v10 `.term`: a coined word with a dotted underline; its `glossary.ts` sentence shows on hover, keyboard
 * focus and tap (a tap focuses it). `plain` prints only the word — for labels and buttons, where a tap
 * must trigger the control. `data-slot="term"`. */
export function Term({ k, value, plain = false, children }: {
  k: GlossaryKey;
  /** Break-even's own value, shown inside its sentence. */
  value?: number | null;
  plain?: boolean;
  children: ReactNode;
}) {
  const id = useId();
  if (plain) return <>{children}</>;
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
        {define(k, value)}
      </span>
    </span>
  );
}

const GRADE_TERM: Record<Grade, GlossaryKey | null> = {
  on_target: "on_target", watch: "watch", over: "over", wasted: "wasted", insufficient: "thin", no_target: null,
};

/** v10 `gchip(g)`: the grade chip whose word is a glossary term. `plain` (inside a label or button) is the
 * v9 `GradeChip` look without the term. `grade === null` prints 未判斷. */
export function GradeTermChip({ grade, label, plain = false, className }: { grade: Grade | null; label?: string | null; plain?: boolean; className?: string }) {
  const g = grade ?? "no_target";
  const key = GRADE_TERM[g];
  const word = label || GRADE_LABEL[g];
  return (
    <Chip tone={GRADE_TONE[g]} data-grade={g} className={className}>
      {key && !plain ? <Term k={key}>{word}</Term> : word}
    </Chip>
  );
}
