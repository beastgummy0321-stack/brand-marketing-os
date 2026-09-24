import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

const TONE = {
  neutral: "bg-muted text-muted-foreground",
  accent: "bg-secondary text-secondary-foreground",
  ok: "bg-success/10 text-success",
  warn: "bg-warning/10 text-warning",
  bad: "bg-destructive/10 text-destructive",
  /** v9 `.chip.over` (太貴): the over-cap zone colour, one step softer than 白花. */
  over: "bg-danger/10 text-danger/90",
  /** v9 `.chip.stop` (白花): the strongest red chip. */
  stop: "bg-danger/20 font-semibold text-danger",
} as const;
export type ChipTone = keyof typeof TONE;

/** The prototype's `.chip` (`.v` = accent, `.ok`, `.warn`, `.bad`; v9 adds `.over`, `.stop`). `data-tone` is what
 * `frontend/scripts/ui-evidence.cjs` compares against the prototype class. */
export function Chip({ tone = "neutral", className, ...props }: ComponentProps<"span"> & { tone?: ChipTone }) {
  return (
    <span
      data-slot="chip"
      data-tone={tone}
      className={cn("inline-flex w-fit shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-xs", TONE[tone], className)}
      {...props}
    />
  );
}

/** Feature F28 contract: a triage item's `grade` against the campaign's one cap. */
export type Grade = "on_target" | "watch" | "over" | "wasted" | "insufficient" | "no_target";

/** Default words per grade (prototype `G`). The API's `grade_label` wins when given: `insufficient` reads
 * 「還太新、看不準」 below the sample gate and 「資料不足」 for any other reason. */
export const GRADE_LABEL: Record<Grade, string> = {
  on_target: "划算",
  watch: "偏貴",
  over: "太貴",
  wasted: "白花",
  insufficient: "還太新、看不準",
  no_target: "未判斷",
};

export const GRADE_TONE: Record<Grade, ChipTone> = {
  on_target: "ok",
  watch: "warn",
  over: "over",
  wasted: "stop",
  insufficient: "neutral",
  no_target: "neutral",
};

/** Fill per grade for dots, swatches and band segments (prototype `--g-*`), from the existing tokens only. */
export const GRADE_FILL: Record<Grade, string> = {
  on_target: "bg-success",
  watch: "bg-warning/80",
  over: "bg-danger/65",
  wasted: "bg-danger",
  insufficient: "bg-muted-foreground/30",
  no_target: "bg-chart-rest",
};

/** Text colour per grade (zone labels, band headings). */
export const GRADE_TEXT: Record<Grade, string> = {
  on_target: "text-success",
  watch: "text-warning",
  over: "text-danger/90",
  wasted: "text-danger",
  insufficient: "text-muted-foreground",
  no_target: "text-muted-foreground",
};

/** v9 `gchip()`: the grade as a chip. `grade === null` (not judged) prints 未判斷. */
export function GradeChip({ grade, label, className }: { grade: Grade | null; label?: string | null; className?: string }) {
  const g = grade ?? "no_target";
  return <Chip tone={GRADE_TONE[g]} data-grade={g} className={className}>{label || GRADE_LABEL[g]}</Chip>;
}

/** Amounts as the prototype prints them (`fmt`): thousands separators, at most two decimals. `null` stays
 * unknown — the caller prints its own unknown word, never 0. */
export function formatAmount(value: number | null | undefined): string | null {
  if (value === null || value === undefined || !Number.isFinite(value)) return null;
  return value.toLocaleString("en-US", { maximumFractionDigits: 2 });
}
