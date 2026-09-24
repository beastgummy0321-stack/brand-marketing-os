import { cn } from "@/lib/utils";

/** Kit piece for the v9 progress segments (prototype `.prog`): one equal segment per item — launch items on the
 * handoff (`pubProg()`), change-set rows on 變更與核對, slots on 素材. `data-slot="progress-segments"`. */

export type SegmentState = "ok" | "built" | "mismatch" | "changed" | "todo";

const FILL: Record<SegmentState, string> = {
  ok: "bg-success",
  built: "bg-chart-soft",
  mismatch: "bg-warning/80",
  changed: "bg-[repeating-linear-gradient(45deg,var(--color-warning)_0_3px,color-mix(in_oklab,var(--color-warning)_30%,white)_3px_6px)]",
  todo: "bg-muted",
};

export function ProgressSegments({ segments, label, className }: {
  segments: { key: string; state: SegmentState; title?: string }[];
  /** Screen-reader summary, e.g. 「2／11 已核對」 (the visible count is the caller's heading). */
  label?: string;
  className?: string;
}) {
  return (
    <div data-slot="progress-segments" className={cn("my-2.5 flex h-2.5 gap-[3px]", className)} {...(label ? { role: "img", "aria-label": label } : { "aria-hidden": true })}>
      {segments.map((s) => <i key={s.key} data-state={s.state} title={s.title} className={cn("flex-1 rounded-[3px]", FILL[s.state])} />)}
    </div>
  );
}
