import type { ReactNode } from "react";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

/** Kit pieces for the remaining v7 screens (F27): campaign chip, angle tags, learning card,
 * recovery steps, thumbnail tiles. Pure presentational; `data-slot` + `data-variant` are what
 * `frontend/scripts/ui-evidence.cjs` compares against the prototype class of the same piece. */

const OBJECTIVE = {
  sales: { mark: "購", cls: "bg-primary text-primary-foreground" },
  engagement: { mark: "互", cls: "bg-chart-aqua text-white" },
  traffic: { mark: "流", cls: "bg-chart-spend text-white" },
  other: { mark: "", cls: "bg-muted-foreground text-white" },
} as const;
export type ObjectiveKey = keyof typeof OBJECTIVE;

/** `.camp` + `.o-*`: campaign chip with an objective-derived letter tile (F27 decision Q6: derived
 * from the campaign's own objective, never invented). `other` shows the name's first character. */
export function CampaignChip({ objective, name, suffix, strong = false }: { objective: ObjectiveKey; name: string; suffix?: string; strong?: boolean }) {
  const o = OBJECTIVE[objective];
  return (
    <span data-slot="campaign-chip" data-variant={objective} className={cn("inline-flex min-w-0 items-center gap-1.5 text-xs whitespace-nowrap", strong ? "text-sm font-semibold text-foreground" : "text-muted-foreground")}>
      <i aria-hidden="true" className={cn("grid size-5 shrink-0 place-items-center rounded-md text-[11px] not-italic", o.cls)}>{o.mark || name.slice(0, 1)}</i>
      <span className="min-w-0 truncate">{name}{suffix && `・${suffix}`}</span>
    </span>
  );
}

/** `.tag` (+ `.on`): one selectable angle tag. */
export function TagToggle({ on, children, onClick, disabled }: { on: boolean; children: ReactNode; onClick?: () => void; disabled?: boolean }) {
  return (
    <button type="button" data-slot="tag-toggle" data-variant={on ? "on" : "off"} aria-pressed={on} disabled={disabled} onClick={onClick}
      className={cn("rounded-full border px-3.5 py-1 text-[13px] transition-colors", on ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card hover:border-primary")}>
      {children}
    </button>
  );
}

/** `.learn`: dashed accent card for a brand-learning prompt or result. */
export function LearnCard({ title, children, aside }: { title: ReactNode; children?: ReactNode; aside?: ReactNode }) {
  return (
    <div data-slot="learn-card" className="flex flex-wrap items-center gap-3 rounded-xl border border-dashed border-primary/40 bg-accent/60 px-4 py-3.5">
      <span className="text-xl" aria-hidden="true">📒</span>
      <div className="min-w-0 flex-1"><b className="text-sm">{title}</b>{children && <div className="mt-2">{children}</div>}</div>
      {aside && <div className="max-w-[260px] text-[13px] text-muted-foreground">{aside}</div>}
    </div>
  );
}

export interface RecoverStep { label: string; state: "done" | "active" | "todo" }
/** `.rec`: horizontal step progress (系統剛恢復). */
export function RecoverSteps({ steps }: { steps: RecoverStep[] }) {
  return (
    <ol data-slot="recover-steps" className="mt-3.5 flex flex-wrap items-center gap-y-2">
      {steps.map((s, i) => (
        <li key={s.label} className="flex items-center">
          {i > 0 && <span className="mx-2.5 h-px w-9 bg-border" aria-hidden="true" />}
          <span className={cn("flex items-center gap-2 text-[13px]", s.state === "active" ? "font-semibold text-foreground" : "text-muted-foreground")}>
            <i className={cn("grid size-6 place-items-center rounded-full text-xs not-italic",
              s.state === "done" ? "bg-success text-white" : s.state === "active" ? "bg-primary text-primary-foreground ring-4 ring-accent" : "bg-muted")} aria-hidden="true">
              {s.state === "done" ? <Check size={13} /> : i + 1}
            </i>
            {s.label}
          </span>
        </li>
      ))}
    </ol>
  );
}

/** `.tiles` + `.thumb`: a row of square thumbnails; `null` url → neutral tile, `hollow` → dashed empty slot. */
export function ThumbTiles({ items, size = 44, max, hollow = 0 }: { items: (string | null)[]; size?: number; max?: number; hollow?: number }) {
  const shown = max !== undefined ? items.slice(0, max) : items;
  const rest = items.length - shown.length;
  const tile = "shrink-0 rounded-[.6rem] bg-muted object-cover";
  return (
    <div data-slot="thumb-tiles" className="mt-2.5 flex flex-wrap items-center gap-1.5">
      {shown.map((url, i) => url
        ? <img key={i} src={url} alt="" className={tile} style={{ width: size, height: size }} loading="lazy" onError={(e) => { e.currentTarget.style.visibility = "hidden"; }} />
        : <div key={i} className={tile} style={{ width: size, height: size }} aria-hidden="true" />)}
      {Array.from({ length: hollow }, (_, i) => <div key={`h${i}`} className="shrink-0 rounded-[.6rem] border border-dashed border-border" style={{ width: size, height: size }} aria-hidden="true" />)}
      {rest > 0 && <span className="rounded-full bg-muted px-2.5 py-1 text-xs text-muted-foreground">＋{rest} 則</span>}
    </div>
  );
}
