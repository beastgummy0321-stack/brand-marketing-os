import { useEffect, useState, type ReactNode } from "react";

/** v10 publish `.fl` + `.cpb` (F30): the field line under a launch item or the launch-settings box — each field
 * is 「label **value**」 and, when `copy` is on, a small 複製 button that puts the value on the clipboard (the
 * user pastes it into the platform by hand). `CopyFields` is the wrapping `.fl` row. After a copy the button
 * reads 已複製 for 2 s; when the browser refuses the clipboard it reads 請手動選取複製 instead, never a silent
 * success; while the clipboard has not answered it reads 複製中… (F51 Contract S, drill-11 c1-10: a pending copy showed
 * nothing). This and `layout/CopyIconButton` are the only callers of `navigator.clipboard` (F47-I02 guard). `data-slot="copy-fields"` / `"copy-field"`. */

export function CopyFields({ children }: { children: ReactNode }) {
  return <div data-slot="copy-fields" className="mt-1 flex flex-wrap gap-x-3.5 gap-y-1.5 text-[12.5px] text-muted-foreground">{children}</div>;
}

type CopyState = "idle" | "copying" | "copied" | "failed";
const WORD: Record<CopyState, string> = { idle: "複製", copying: "複製中…", copied: "已複製", failed: "請手動選取複製" };
/** F47 Contract B: 「已複製」 stays 2 s, same as `layout/CopyIconButton`. */
const FEEDBACK_MS = 2000;

export function CopyField({ label, value, copy = true, onCopied }: {
  label: string;
  value: string;
  copy?: boolean;
  onCopied?: (value: string) => void;
}) {
  const [state, setState] = useState<CopyState>("idle");
  useEffect(() => {
    if (state === "idle" || state === "copying") return;
    const t = setTimeout(() => setState("idle"), FEEDBACK_MS);
    return () => clearTimeout(t);
  }, [state]);
  const doCopy = async () => {
    if (state === "copying") return;
    setState("copying");
    try {
      if (!navigator.clipboard) throw new Error("no clipboard");
      await navigator.clipboard.writeText(value);
      setState("copied");
      onCopied?.(value);
    } catch {
      setState("failed");
    }
  };
  return (
    <span data-slot="copy-field">
      {label} <b className="font-semibold text-foreground [overflow-wrap:anywhere]">{value}</b>
      {copy && (
        <button type="button" onClick={() => void doCopy()} aria-label={`複製${label}`} aria-busy={state === "copying" || undefined}
          className="ml-1 rounded-md border border-border bg-card px-[7px] py-px text-[11.5px] text-muted-foreground hover:border-primary hover:text-primary">
          <span aria-live="polite">{WORD[state]}</span>
        </button>
      )}
    </span>
  );
}
