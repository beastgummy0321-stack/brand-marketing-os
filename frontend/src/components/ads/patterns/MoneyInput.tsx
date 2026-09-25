import type { KeyboardEvent } from "react";
import { cn } from "@/lib/utils";

/** v10 `.money` (F30): an amount field — the currency prefix inside the box, a large tabular number, the focus ring
 * on the whole box. Whole amounts only: a change that is not digits after dropping thousands separators and
 * spaces is ignored, so letters, signs, decimals and exponents never reach the value (the prototype's
 * 「請填大於 0 的整數金額」). Empty is `null`, never 0. `onEnter` runs on Enter (the prototype saves the cap on
 * Enter). `data-slot="money-input"`. */

const MAX_DIGITS = 12;

export function MoneyInput({ value, onChange, label, currency = "NT$", id, placeholder, disabled, invalid, onEnter, className }: {
  value: number | null;
  onChange: (value: number | null) => void;
  /** Accessible name when no visible `<label for={id}>` names it. */
  label?: string;
  currency?: string;
  id?: string;
  placeholder?: string;
  disabled?: boolean;
  invalid?: boolean;
  onEnter?: () => void;
  className?: string;
}) {
  const accept = (raw: string) => {
    const text = raw.replace(/[,\s]/g, "");
    if (!/^\d*$/.test(text) || text.length > MAX_DIGITS) return;
    onChange(text === "" ? null : Number(text));
  };
  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && onEnter) { e.preventDefault(); onEnter(); }
  };
  return (
    <div data-slot="money-input" data-variant={invalid ? "invalid" : "ok"}
      className={cn("inline-flex w-[180px] items-center rounded-lg border bg-card px-3 focus-within:border-primary focus-within:ring-[3px] focus-within:ring-accent",
        invalid ? "border-danger" : "border-input", disabled && "bg-muted", className)}>
      <span aria-hidden="true" className="text-muted-foreground">{currency}</span>
      <input id={id} type="text" inputMode="numeric" autoComplete="off" aria-label={label} aria-invalid={invalid || undefined}
        value={value === null ? "" : String(value)} placeholder={placeholder} disabled={disabled}
        onChange={(e) => accept(e.target.value)} onKeyDown={onKeyDown}
        className="numeric w-full min-w-0 border-0 bg-transparent px-2 py-[9px] text-base font-semibold outline-none focus-visible:outline-none" />
    </div>
  );
}
