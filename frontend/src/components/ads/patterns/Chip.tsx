import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

const TONE = {
  neutral: "bg-muted text-muted-foreground",
  accent: "bg-secondary text-secondary-foreground",
  ok: "bg-success/10 text-success",
  warn: "bg-warning/10 text-warning",
  bad: "bg-destructive/10 text-destructive",
} as const;

/** The v7 prototype's `.chip` (`.v` = accent, `.ok`, `.warn`, `.bad`). `data-tone` is what
 * `frontend/scripts/ui-evidence.cjs` compares against the prototype class. */
export function Chip({ tone = "neutral", className, ...props }: ComponentProps<"span"> & { tone?: keyof typeof TONE }) {
  return (
    <span
      data-slot="chip"
      data-tone={tone}
      className={cn("inline-flex w-fit shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-xs", TONE[tone], className)}
      {...props}
    />
  );
}
