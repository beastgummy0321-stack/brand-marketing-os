import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Chip, type ChipTone } from "./Chip";
import { ProgressSegments, type SegmentState } from "./ProgressSegments";

/** v10 `tabChanges()` `.tl` / `.tli` (F30): the campaign's change sets, newest first, on a vertical line. Each row:
 * a state dot, the time, the title, 「原因：…」 when given, the per-item `ProgressSegments` with 「x／N 已核對」,
 * the state chip and an optional action. State follows Feature F30 Contract E `timeline.rows[].state`; a rejected
 * set shows no progress (nothing to check). Unchecked items of a `stale` set are hatched (核准後方案改過).
 * `STATE_LABEL.platform` names no platform — the caller passes its own words (e.g. 「等你到 Meta 完成」) through
 * `label`. `data-slot="change-timeline"`, each row `data-variant` = its state. */

export type ChangeState = "verified" | "platform" | "check" | "rejected" | "draft" | "stale";

const DOT: Record<ChangeState, string> = {
  verified: "border-success bg-success",
  platform: "border-primary bg-primary",
  check: "border-primary bg-primary",
  rejected: "border-grade-thin bg-muted",
  draft: "border-grade-thin bg-muted",
  stale: "border-grade-watch bg-grade-watch",
};

export const CHANGE_STATE_TONE: Record<ChangeState, ChipTone> = {
  verified: "ok", platform: "accent", check: "warn", rejected: "neutral", draft: "neutral", stale: "warn",
};

export const CHANGE_STATE_LABEL: Record<ChangeState, string> = {
  verified: "✓ 已核對",
  platform: "等你到平台完成",
  check: "等核對",
  rejected: "已拒絕・不用處理",
  draft: "還沒核准",
  stale: "核准後方案改過",
};

export interface ChangeRow {
  key: string;
  /** Already formatted in the org timezone (「09/21 16:30」); 「—」 when the set has no time yet. */
  at: string;
  title: string;
  state: ChangeState;
  reason?: string | null;
  checked: number;
  total: number;
  /** Overrides `CHANGE_STATE_LABEL[state]`. */
  label?: string;
  action?: ReactNode;
}

export function ChangeTimeline({ rows, label = "變更紀錄" }: { rows: ChangeRow[]; label?: string }) {
  return (
    <ol data-slot="change-timeline" aria-label={label}
      className="relative m-0 list-none py-0 pr-0 pl-7 before:absolute before:top-1.5 before:bottom-1.5 before:left-[9px] before:border-l-2 before:border-border">
      {rows.map((r) => {
        const segments = Array.from({ length: r.total }, (_, k): { key: string; state: SegmentState } => (
          { key: String(k), state: k < r.checked ? "ok" : r.state === "stale" ? "changed" : "todo" }));
        return (
          <li key={r.key} data-variant={r.state} className="relative pb-[18px] last:pb-0">
            <i aria-hidden="true" className={cn("absolute top-3.5 -left-7 size-5 rounded-full border-2", DOT[r.state])} />
            <div className="flex flex-wrap items-center gap-2.5 py-2.5">
              <div className="min-w-[220px] flex-1">
                <div className="numeric text-[11.5px] text-muted-foreground">{r.at}</div>
                <b className="font-semibold [overflow-wrap:anywhere]">{r.title}</b>
                {r.reason && <div className="text-[11.5px] text-muted-foreground">原因：{r.reason}</div>}
                {r.state !== "rejected" && r.total > 0 && (
                  <>
                    <ProgressSegments segments={segments} className="mt-2 mb-0.5 max-w-[260px]" />
                    <div className="numeric text-[11.5px] text-muted-foreground">{r.checked}／{r.total} 已核對</div>
                  </>
                )}
              </div>
              <Chip tone={CHANGE_STATE_TONE[r.state]}>{r.label ?? CHANGE_STATE_LABEL[r.state]}</Chip>
              {r.action}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
