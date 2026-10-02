import { cn } from "@/lib/utils";

/** Kit piece for the v9 progress segments (prototype `.prog`): one equal segment per item — launch items on the
 * handoff (`pubProg()`), change-set rows on 變更與核對, slots on 素材. `data-slot="progress-segments"`.
 * The 素材 slots add two states (F44 prototype `.prog i.run` / `i.bad`): `running` = 處理中, finishing by itself;
 * `blocked` = 卡住, the danger colour. F45 (prototype `f45-slot-states` `.prog i.wait`): `waiting` = 等你, the user's
 * next action — a soft amber of its own, never the 處理中 colour. */

export type SegmentState = "ok" | "built" | "mismatch" | "changed" | "todo" | "running" | "waiting" | "blocked";

const FILL: Record<SegmentState, string> = {
  ok: "bg-success",
  built: "bg-chart-soft",
  mismatch: "bg-warning/80",
  changed: "bg-[repeating-linear-gradient(45deg,var(--color-warning)_0_3px,color-mix(in_oklab,var(--color-warning)_30%,white)_3px_6px)]",
  todo: "bg-muted",
  running: "bg-chart-soft",
  waiting: "bg-warning/55",
  blocked: "bg-danger",
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
