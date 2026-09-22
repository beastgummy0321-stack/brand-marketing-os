import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Kit pieces of the v7 repair-flow steps 1–3 (F23, prototype `review()`/`prepare()`/`copy()`).
 * Pure presentational; `data-slot` + `data-variant` are what `frontend/scripts/ui-evidence.cjs`
 * compares against the prototype class of the same piece. */

const fmt = (v: number | null) => (v === null ? null : v.toLocaleString("zh-TW", { maximumFractionDigits: 2 }));

/** `.ev`: one evidence line — label, previous/current bars, current value over 「前期 X」, delta.
 * `current === null` draws the hatched 「待確認」 bar and no delta; `previous === null` prints
 * 「前期 未知」. Delta is `▲/▼N%` of current against previous, 「持平」 when rounded 0. */
export function EvidenceRow({ label, previous, current, unknownLabel = "待確認" }: {
  label: string; previous: number | null; current: number | null; unknownLabel?: string;
}) {
  const max = Math.max(previous ?? 0, current ?? 0) || 1;
  const pct = (v: number | null) => (v === null ? 0 : (v / max) * 100);
  let delta = "";
  if (previous !== null && current !== null && previous !== 0) {
    const r = Math.round(((current - previous) / previous) * 100);
    delta = r === 0 ? "持平" : `${r > 0 ? "▲" : "▼"}${Math.abs(r)}%`;
  }
  return (
    <div data-slot="evidence-row" data-variant={current === null ? "unknown" : "known"}
      className="grid grid-cols-[96px_1fr_84px_52px] items-center gap-2.5 border-t border-border py-[11px] first:border-t-0">
      <div className="text-[13px] text-muted-foreground">{label}</div>
      <div aria-hidden="true">
        <div className="my-[3px] h-[7px] rounded bg-border" style={{ width: `${pct(previous)}%` }} />
        {current === null
          ? <div className="my-[3px] h-[7px] w-3/5 rounded bg-[repeating-linear-gradient(45deg,var(--border),var(--border)_4px,transparent_4px,transparent_8px)]" />
          : <div className="my-[3px] h-[7px] rounded bg-primary" style={{ width: `${pct(current)}%` }} />}
      </div>
      <div className="numeric text-right">
        <b className="block text-base">{current === null ? <span className="font-normal text-muted-foreground">{unknownLabel}</span> : fmt(current)}</b>
        <small className="text-[11.5px] text-muted-foreground">前期 {previous === null ? "未知" : fmt(previous)}</small>
      </div>
      <div className="numeric text-right text-xs font-semibold">{delta}</div>
    </div>
  );
}

/** `.ladder`: 改文案 → 換圖 → 退役, `current` = the creative's step from its handling history. */
export function Ladder({ steps, current }: { steps: string[]; current?: number }) {
  return (
    <div data-slot="ladder" data-variant="live" className="flex items-center text-xs text-muted-foreground" aria-label="處理階梯">
      {steps.map((s, i) => (
        <span key={s} className="flex items-center">
          {i > 0 && <span className="h-px w-[18px] bg-border" aria-hidden="true" />}
          <b className={cn("rounded-full px-3 py-1 font-medium",
            i === current ? "bg-primary text-primary-foreground" : current !== undefined && i < current ? "bg-secondary text-secondary-foreground" : "bg-muted")}>{s}</b>
        </span>
      ))}
    </div>
  );
}

/** `.opt` (+ `.pick`): one direction card on 選方向. `disabled` = not available here (grey, not
 * clickable); `disabledNote` says why (default 接上後開放 — never a refusal wording). */
export function OptionCard({ icon, title, note, picked = false, recommended = false, disabled = false, disabledNote = "接上後開放", onClick }: {
  icon: ReactNode; title: string; note: string; picked?: boolean; recommended?: boolean; disabled?: boolean; disabledNote?: string; onClick?: () => void;
}) {
  return (
    <button type="button" data-slot="option-card" data-variant={disabled ? "reserved" : picked ? "picked" : "open"}
      aria-pressed={disabled ? undefined : picked} disabled={disabled} onClick={onClick}
      className={cn("rounded-xl border p-5 text-left transition-colors",
        disabled ? "cursor-default border-border bg-muted text-muted-foreground" : picked ? "border-primary bg-accent shadow-[0_0_0_1px_var(--primary)]" : "border-border bg-card hover:border-primary")}>
      <div className="text-2xl" aria-hidden="true">{icon}</div>
      <b className="mt-2.5 mb-1 block text-[15px]">{title}{recommended && <span className="ml-1.5 rounded-full bg-secondary px-2 py-0.5 text-xs font-medium text-secondary-foreground">建議</span>}</b>
      <span className="text-[13px] text-muted-foreground">{disabled ? disabledNote : note}</span>
    </button>
  );
}

/** `.old` / `.new`: a copy block (title bold + body, pre-wrap). `marks` = lines to highlight
 * (the lines that will be replaced, or that differ from what was approved). */
export function CopyBlock({ tone, title, body, marks }: { tone: "old" | "new"; title: string | null; body: string | null; marks?: Set<string> }) {
  const lines = (body ?? "").split("\n");
  return (
    <div data-slot="copy-block" data-variant={tone} className={cn("rounded-lg p-3.5 text-[13.5px] leading-[1.65] whitespace-pre-wrap", tone === "old" ? "bg-muted" : "bg-accent")}>
      {title !== null && <b className={cn(marks?.has(title) && "bg-warning/30")}>{title}</b>}
      {title !== null && "\n"}
      {lines.map((l, i) => (
        <span key={i}>{marks?.has(l.trim()) && l.trim() ? <mark className="bg-warning/30">{l}</mark> : l}{i < lines.length - 1 && "\n"}</span>
      ))}
    </div>
  );
}

/** `.days`: one tile per calendar day of a short range; `missing` days are hollow with a dashed
 * danger border (prototype `.days i.x`). Labels are the day-of-month. */
export function DayTiles({ days, missing, size = 40 }: { days: string[]; missing: Set<string>; size?: number }) {
  return (
    <div data-slot="day-tiles" className="flex flex-wrap gap-1" aria-label="每日資料">
      {days.map((d) => {
        const gap = missing.has(d);
        return (
          <i key={d} title={gap ? `${d} 缺資料` : d} aria-label={gap ? `${d} 缺資料` : d}
            className={cn("grid place-items-center rounded-md text-[13px] not-italic", gap ? "border border-dashed border-danger bg-card text-danger" : "bg-primary text-primary-foreground")}
            style={{ width: size, height: size }}>{Number(d.slice(-2))}</i>
        );
      })}
    </div>
  );
}
