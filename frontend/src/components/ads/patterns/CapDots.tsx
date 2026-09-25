/** Kit piece for the v9 capacity dots (prototype `stepProp()` `.capdots`): one square per active ad, the ones the
 * budget carries before the line, the ones a cleanup closes after it (cleanup payload `keep` / `ads`).
 * `data-slot="cap-dots"`. The caller prints the words (「每日 1,200 撐 6 則」) beside it; `label` names it for
 * screen readers when there are no such words. */
export function CapDots({ keep, close, label }: { keep: number; close: number; label?: string }) {
  return (
    <div data-slot="cap-dots" className="flex items-center gap-[3px]" {...(label ? { role: "img", "aria-label": label } : { "aria-hidden": true })}>
      {Array.from({ length: Math.max(0, keep) }, (_, i) => <i key={`k${i}`} data-part="keep" className="size-3 rounded-[3px] bg-chart-soft" />)}
      <u className="mx-[3px] h-[18px] w-0.5 bg-foreground" />
      {Array.from({ length: Math.max(0, close) }, (_, i) => <i key={`c${i}`} data-part="close" className="size-3 rounded-[3px] border-[1.5px] border-warning/80 bg-card" />)}
    </div>
  );
}
