import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";
import { gradeWord, useAdsRules } from "./rules";

const TONE = {
  neutral: "bg-muted text-muted-foreground",
  accent: "bg-secondary text-secondary-foreground",
  ok: "bg-zone-ok text-success",
  warn: "bg-zone-watch text-warning",
  bad: "bg-zone-over text-danger",
  /** v9 `.chip.over` (太貴): the over-cap zone colour, one step softer than 沒賣出. */
  over: "bg-zone-over text-grade-over-foreground",
  /** v9 `.chip.stop` (沒賣出): the strongest red chip. */
  stop: "bg-grade-wasted-soft text-grade-wasted-foreground",
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

export const GRADE_TONE: Record<Grade, ChipTone> = {
  on_target: "ok",
  watch: "warn",
  over: "over",
  wasted: "stop",
  insufficient: "neutral",
  no_target: "neutral",
};

/** Fill per grade for dots, swatches and band segments (prototype `--g-*`; 划算 = success, 未判斷 = `--c5`). */
export const GRADE_FILL: Record<Grade, string> = {
  on_target: "bg-success",
  watch: "bg-grade-watch",
  over: "bg-grade-over",
  wasted: "bg-grade-wasted",
  insufficient: "bg-grade-thin",
  no_target: "bg-chart-rest",
};

/** Text colour per grade (zone labels, band headings). */
export const GRADE_TEXT: Record<Grade, string> = {
  on_target: "text-success",
  watch: "text-warning",
  over: "text-grade-over-foreground",
  wasted: "text-grade-wasted",
  insufficient: "text-muted-foreground",
  no_target: "text-muted-foreground",
};

/** v9 `gchip()`: the grade as a chip — the payload's `label` first, else the served word of the grade (F48 Contract
 * R-API; `reasonCode` splits `insufficient`). `grade === null` (not judged) prints 未判斷. */
export function GradeChip({ grade, label, reasonCode, className }: { grade: Grade | null; label?: string | null; reasonCode?: string | null; className?: string }) {
  const rules = useAdsRules();
  const g = grade ?? "no_target";
  return <Chip tone={GRADE_TONE[g]} data-grade={g} className={className}>{label || gradeWord(rules, g, reasonCode) || ""}</Chip>;
}

/** Amounts as the prototype prints them (`fmt`): thousands separators, at most two decimals. `null` stays
 * unknown — the caller prints its own unknown word, never 0. */
export function formatAmount(value: number | null | undefined): string | null {
  if (value === null || value === undefined || !Number.isFinite(value)) return null;
  return value.toLocaleString("en-US", { maximumFractionDigits: 2 });
}
