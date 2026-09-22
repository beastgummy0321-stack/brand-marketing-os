import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

/** Kit pieces of the v7 repair flow (F22, prototype `confirmPage()`/`handoff()`/`verify()`).
 * Pure presentational; `data-slot` + `data-variant` are what `frontend/scripts/ui-evidence.cjs`
 * compares against the prototype class of the same piece. */

export interface FlowStep { label: string; to?: string }

/** `.sh`: step dots with inline labels (`.dots/.d/.dl`), right-hand context (`.qpos`), then title +
 * purpose (`.row/.purpose`). Steps before `current` are links when they carry `to`. */
export function FlowHeader({ steps, current, context, title, purpose, aside }: {
  steps: FlowStep[]; current: number; context?: ReactNode; title: string; purpose?: string; aside?: ReactNode;
}) {
  return (
    <header data-slot="flow-header" className="mb-5">
      <div className="mb-3.5 flex flex-wrap items-center gap-y-2">
        <ol className="flex items-center">
          {steps.map((step, i) => {
            const done = i < current;
            const dot = cn(
              "flex size-[26px] shrink-0 items-center justify-center rounded-full text-xs font-semibold",
              done ? "bg-success text-white" : i === current ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
            );
            return (
              <li key={step.label} className="flex items-center" aria-current={i === current ? "step" : undefined}>
                {i > 0 && <span className="mr-2.5 h-px w-[22px] bg-border" aria-hidden="true" />}
                {done && step.to
                  ? <Link to={step.to} className={dot} aria-label={`回到${step.label}`}><Check size={13} /></Link>
                  : <span className={dot}>{done ? <Check size={13} /> : i + 1}</span>}
                <span className={cn("mr-2.5 ml-1.5 text-xs", i === current ? "font-semibold text-foreground" : "text-muted-foreground")}>{step.label}</span>
              </li>
            );
          })}
        </ol>
        {context && <div className="ml-auto flex items-center gap-3.5 text-xs text-muted-foreground">{context}</div>}
      </div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          {purpose && <p className="mt-1 text-[15px] text-muted-foreground">{purpose}</p>}
        </div>
        {aside && <div>{aside}</div>}
      </div>
    </header>
  );
}

const KIND = {
  stop: { mark: "■", cls: "bg-danger/10 text-danger" },
  worse: { mark: "▼", cls: "bg-warning/10 text-warning" },
  up: { mark: "▲", cls: "bg-success/10 text-success" },
} as const;
/** `.kind.stop/.worse/.up`. */
export function KindMark({ kind, children }: { kind: keyof typeof KIND; children: ReactNode }) {
  return (
    <span data-slot="kind-mark" data-variant={kind} className={cn("inline-flex w-fit items-center gap-1.5 rounded-full px-2.5 py-[3px] text-xs font-semibold", KIND[kind].cls)}>
      <span aria-hidden="true">{KIND[kind].mark}</span>{children}
    </span>
  );
}

const METER_TONE = { danger: "bg-danger", warning: "bg-warning", success: "bg-success" } as const;
/** `.meter` + `.cap`: `value` against an axis of `max`, optional marker line; captions left/right.
 * Renders captions only when `value` or `max` is unknown (null) — never a guessed bar. */
export function Meter({ value, max, marker, tone, left, right }: {
  value: number | null; max: number | null; marker?: number | null; tone: keyof typeof METER_TONE; left?: ReactNode; right?: ReactNode;
}) {
  const known = value !== null && max !== null && max > 0;
  const pct = (v: number) => Math.min(100, Math.max(0, (v / (max as number)) * 100));
  return (
    <div data-slot="meter" data-variant={tone}>
      {known && (
        <div className="relative mt-1.5 mb-1 h-2.5 rounded-md bg-muted" aria-hidden="true">
          <div className={cn("absolute inset-y-0 left-0 rounded-md", METER_TONE[tone])} style={{ width: `${pct(value)}%` }} />
          {marker != null && <div className="absolute -top-1 -bottom-1 w-0.5 bg-foreground" style={{ left: `${pct(marker)}%` }} />}
        </div>
      )}
      {(left || right) && (
        <div className="numeric flex justify-between gap-2 text-[11.5px] text-muted-foreground"><span>{left}</span><span>{right}</span></div>
      )}
    </div>
  );
}

/** `.todo` + `.no`: one numbered manual step; `done` turns the number into a green check. */
export function TodoRow({ no, done = false, children, action }: { no: number; done?: boolean; children: ReactNode; action?: ReactNode }) {
  return (
    <div data-slot="todo-row" data-variant={done ? "done" : "open"} className="flex items-center gap-4 border-t border-border py-[18px] first:border-t-0">
      <div className={cn("flex size-8 shrink-0 items-center justify-center rounded-full font-bold", done ? "bg-success text-white" : "bg-muted text-muted-foreground")}>
        {done ? <Check size={16} aria-label="已完成" /> : no}
      </div>
      <div className="min-w-0 flex-1 text-[15px]">{children}</div>
      {action && <div className="flex shrink-0 flex-col gap-2">{action}</div>}
    </div>
  );
}

const HERO = {
  ok: { box: "bg-success/10", big: "bg-success", mark: "✓" },
  warn: { box: "bg-warning/10", big: "bg-warning", mark: "≠" },
  bad: { box: "bg-danger/10", big: "bg-danger", mark: "!" },
  neutral: { box: "bg-muted", big: "bg-muted-foreground", mark: "…" },
} as const;
/** `.hero.ok/.warn/.bad` (+ `neutral` for 核對中, which the prototype does not draw). */
export function ResultHero({ tone, title, note, mark }: { tone: keyof typeof HERO; title: string; note?: ReactNode; mark?: string }) {
  return (
    <div data-slot="result-hero" data-variant={tone} role="status" className={cn("flex items-center gap-4 rounded-xl p-5", HERO[tone].box)}>
      <div className={cn("flex size-12 shrink-0 items-center justify-center rounded-full text-[22px] text-white", HERO[tone].big)} aria-hidden="true">{mark ?? HERO[tone].mark}</div>
      <div className="min-w-0 flex-1">
        <h2 className="text-xl font-semibold">{title}</h2>
        {note && <p className="mt-1 text-[15px] text-muted-foreground">{note}</p>}
      </div>
    </div>
  );
}

export interface RailCell { title: string; note: string; ok?: boolean }
/** `.rail`: what happens next, one cell per fact that really exists (no placeholder cells). */
export function StatusRail({ cells }: { cells: RailCell[] }) {
  if (cells.length === 0) return null;
  return (
    <div data-slot="status-rail" className="grid overflow-hidden rounded-xl border border-border" style={{ gridTemplateColumns: `repeat(${cells.length}, minmax(0, 1fr))` }}>
      {cells.map((cell) => (
        <div key={cell.title} className={cn("border-l border-border px-4 py-3.5 text-sm text-muted-foreground first:border-l-0", cell.ok && "bg-success/10")}>
          <b className={cn("mb-0.5 block", cell.ok ? "text-success" : "text-foreground")}>{cell.ok && "✓ "}{cell.title}</b>
          {cell.note}
        </div>
      ))}
    </div>
  );
}

/** `.seg`: single choice among a few options. */
export function Segmented<T extends string>({ label, options, value, onChange }: {
  label: string; options: { value: T; label: string }[]; value: T; onChange: (value: T) => void;
}) {
  return (
    <div data-slot="segmented" role="group" aria-label={label} className="inline-flex overflow-hidden rounded-lg border border-border">
      {options.map((option) => (
        <button
          key={option.value} type="button" aria-pressed={option.value === value} onClick={() => onChange(option.value)}
          className={cn("relative px-3.5 py-2 text-sm focus-visible:z-10", option.value === value ? "bg-accent font-semibold text-accent-foreground" : "bg-card hover:bg-muted")}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/** `.sheet`: inline decision form under the page content (not a modal). Fields wrap; actions last. */
export function DecisionSheet({ title, children, actions }: { title?: string; children: ReactNode; actions: ReactNode }) {
  return (
    <section data-slot="decision-sheet" aria-label={title ?? "決定"} className="mt-4 flex flex-wrap items-end gap-3 rounded-xl border border-border bg-card px-5 py-4 shadow-sm">
      {title && <b className="self-center">{title}</b>}
      {children}
      <div className="flex gap-3">{actions}</div>
    </section>
  );
}

/** `.bar`: sticky bottom action bar — back on the left; hint, secondary and primary on the right.
 * Sticky inside the page flow, same technique as `target/CampaignTargetPage`. */
export function ActionBar({ back, hint, children }: { back?: ReactNode; hint?: string; children?: ReactNode }) {
  return (
    <div data-slot="action-bar" className="sticky bottom-0 z-10 -mx-[22px] mt-6 flex flex-wrap items-center gap-3 border-t border-border bg-card/95 px-[22px] py-3 backdrop-blur xl:-mx-7 xl:px-7">
      {back}
      <div className="ml-auto flex flex-wrap items-center gap-2">
        {hint && <small className="text-xs text-muted-foreground">{hint}</small>}
        {children}
      </div>
    </div>
  );
}
