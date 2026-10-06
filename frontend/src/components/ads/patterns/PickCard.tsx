import { createContext, useContext, useId, useRef, type KeyboardEvent, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Thumb } from "./LoopPieces";

/** v10 `newStep1()` `.pick` + `.pk` (F30): a single-choice card grid. `PickGroup` is the `role="radiogroup"` grid
 * (three columns); each `PickCard` is a `role="radio"` card with `aria-checked`. Keyboard follows the radio
 * pattern: Tab reaches the picked card (or every card while nothing is picked), arrows and Home/End move to and
 * pick the next enabled card, Space/Enter pick the focused one.
 * Two layouts, as the prototype: with `thumbnailUrl` (a product — 52px thumbnail beside the words) or with
 * `icon` (`.pk.goal` — an objective, icon tile above the words). A `disabledReason` card is a reserved seat: grey, not
 * pickable, and its `disabledReason` replaces the note. `data-slot="pick-group"` /
 * `"pick-card"`, `data-variant` picked／open／reserved. */

interface PickCtx { value: string | null; pick: (value: string) => void }
const Ctx = createContext<PickCtx | null>(null);

export function PickGroup({ label, value, onChange, children, className }: {
  label: string;
  value: string | null;
  onChange: (value: string) => void;
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const keys = ["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp", "Home", "End"];
    if (!keys.includes(e.key) || !ref.current) return;
    const radios = Array.from(ref.current.querySelectorAll<HTMLButtonElement>("[role=radio]:not(:disabled)"));
    if (radios.length === 0) return;
    e.preventDefault();
    const at = radios.indexOf(document.activeElement as HTMLButtonElement);
    const next = e.key === "Home" ? 0
      : e.key === "End" ? radios.length - 1
      : e.key === "ArrowRight" || e.key === "ArrowDown" ? (at + 1) % radios.length
      : (at - 1 + radios.length) % radios.length;
    const target = radios[next];
    target.focus();
    const v = target.dataset.value;
    if (v !== undefined) onChange(v);
  };
  return (
    <Ctx.Provider value={{ value, pick: onChange }}>
      <div ref={ref} data-slot="pick-group" role="radiogroup" aria-label={label} onKeyDown={onKeyDown}
        className={cn("grid grid-cols-3 gap-3", className)}>
        {children}
      </div>
    </Ctx.Provider>
  );
}

export function PickCard({ value, title, note, badge, thumbnailUrl, icon, disabledReason, busy = false }: {
  value: string;
  title: string;
  note?: ReactNode;
  badge?: ReactNode;
  /** Product layout; `null` draws the neutral tile. Leave undefined for the icon layout. */
  thumbnailUrl?: string | null;
  icon?: ReactNode;
  disabledReason?: string | null;
  busy?: boolean;
}) {
  const ctx = useContext(Ctx);
  const checked = ctx?.value === value;
  const product = thumbnailUrl !== undefined;
  const reasonId = useId();
  const reason = disabledReason || null;
  const unavailable = Boolean(busy || reason);
  const words = reason || note;
  return (
    <button type="button" role="radio" aria-checked={checked} data-slot="pick-card" data-value={value}
      data-variant={unavailable ? "reserved" : checked ? "picked" : "open"} disabled={unavailable} /* DISABLED_OK: native control derives state from busy or its visible reason */ aria-busy={busy || undefined} aria-describedby={reason ? reasonId : undefined}
      tabIndex={checked || ctx?.value == null ? 0 : -1} onClick={() => ctx?.pick(value)}
      className={cn("flex rounded-xl border text-left transition-colors disabled:cursor-default disabled:opacity-100",
        product ? "items-center gap-3 p-3" : "flex-col items-start gap-1.5 p-[18px]",
        unavailable ? "border-border bg-muted text-muted-foreground"
          : checked ? "border-primary bg-accent/50 shadow-[0_0_0_1px_var(--color-primary)]" : "border-border bg-card hover:border-primary")}>
      {product
        ? <Thumb url={thumbnailUrl} size={52} />
        : icon !== undefined && (
          <span aria-hidden="true" className={cn("grid size-11 place-items-center rounded-xl text-xl",
            unavailable ? "bg-card text-muted-foreground" : "bg-accent text-accent-foreground")}>{icon}</span>
        )}
      {product ? (
        <span className="min-w-0">
          <b className="block font-semibold [overflow-wrap:anywhere]">{title}</b>
          {words && <span id={reason ? reasonId : undefined} className="block text-xs text-muted-foreground">{words}</span>}
          {badge && <span className="mt-1 block">{badge}</span>}
        </span>
      ) : (
        <>
          <b className="text-base font-semibold">{title}</b>
          {words && <span id={reason ? reasonId : undefined} className="text-xs text-muted-foreground">{words}</span>}
          {badge}
        </>
      )}
    </button>
  );
}
