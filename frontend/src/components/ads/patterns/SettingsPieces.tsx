import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Chip } from "./Chip";

/** Kit pieces for the v10 launch settings (Feature F29 Contract I; prototype `setCard()` and the readback card of
 * `pubVerify()`). Choices use native `<select>` / checkboxes and `FlowPieces` `Segmented`; these pieces are the
 * frame around them. */

/** `.setg`: three columns of setting fields; `SettingField wide` spans two. */
export function SettingsGrid({ children }: { children: ReactNode }) {
  return <div data-slot="settings-grid" className="grid grid-cols-3 gap-x-4 gap-y-3.5">{children}</div>;
}

/** `.fld` of the settings card: label + 「建議」 (still the recommended value) or 「你改的」 (the user changed it),
 * one plain note line, then the control. `tag` null prints no tag. `data-slot="setting-field"`. */
export function SettingField({ label, htmlFor, tag, note, wide = false, children }: {
  label: string; htmlFor?: string; tag: "recommended" | "edited" | null; note?: ReactNode; wide?: boolean; children: ReactNode;
}) {
  return (
    <div data-slot="setting-field" data-variant={tag ?? "none"} className={cn("min-w-0", wide && "col-span-2")}>
      <label htmlFor={htmlFor} className="mb-1 block text-xs text-muted-foreground">
        {label}
        {tag && <Chip tone={tag === "recommended" ? "accent" : "neutral"} className="ml-1.5 px-1.5 py-0">{tag === "recommended" ? "建議" : "你改的"}</Chip>}
      </label>
      {note && <div className="mb-1.5 text-[11.5px] text-muted-foreground">{note}</div>}
      {children}
    </div>
  );
}

/** `.chip.nr`: 「讀不到」 — the platform value could not be read (white, dashed outline). */
export function UnreadChip({ children = "讀不到" }: { children?: ReactNode }) {
  return <Chip data-tone="unread" className="border border-dashed border-muted-foreground/45 bg-card">{children}</Chip>;
}

export type ReadbackState = "match" | "differ" | "unreadable" | "self_confirmed";
export interface ReadbackField {
  key: string; label: string; expected_label: string; observed_label: string | null; state: ReadbackState; reason: string | null;
}

/** The readback card's header chips: 對上了 N (self-confirmed counts as matched), 不一樣 N, 讀不到 N. */
export function ReadbackSummary({ fields }: { fields: Pick<ReadbackField, "state">[] }) {
  const n = (s: ReadbackState[]) => fields.filter((f) => s.includes(f.state)).length;
  const differ = n(["differ"]), unread = n(["unreadable"]);
  return (
    <div className="flex flex-wrap gap-1.5">
      <Chip tone="ok">對上了 {n(["match", "self_confirmed"])}</Chip>
      {differ > 0 && <Chip tone="warn">不一樣 {differ}</Chip>}
      {unread > 0 && <UnreadChip>讀不到 {unread}</UnreadChip>}
    </div>
  );
}

/** `.rb`: one setting read back from the platform — label, the approved value (and what the platform shows when
 * it differs), the state chip; an unreadable field takes the caller's 「我看過了，一樣」 action.
 * `platform` names where the value was read (e.g. 「Meta」). `data-slot="readback-row"`, `data-variant` = state. */
export function ReadbackRow({ field, platform, action }: { field: ReadbackField; platform: string; action?: ReactNode }) {
  const { state } = field;
  return (
    <div data-slot="readback-row" data-variant={state} className="grid grid-cols-[96px_minmax(0,1fr)_auto] items-center gap-3 border-t border-border py-[11px] first:border-t-0">
      <span className="text-xs text-muted-foreground">{field.label}</span>
      <div className="min-w-0">
        {state === "differ" ? (
          <div className="text-xs">
            <b className="text-warning-strong">不一樣</b>（{platform} 上是 <mark className="rounded-[3px] bg-zone-watch px-px text-inherit">{field.observed_label ?? "讀不到"}</mark>，這裡是 {field.expected_label}）
          </div>
        ) : (
          <>
            <div className="text-xs [overflow-wrap:anywhere]">{field.expected_label}</div>
            {state === "unreadable" && field.reason && <div className="text-[11.5px] text-muted-foreground">{field.reason}</div>}
          </>
        )}
      </div>
      <div className="flex flex-wrap items-center justify-end gap-1.5">
        {state === "match" && <Chip tone="ok">對上了</Chip>}
        {state === "self_confirmed" && <Chip tone="ok">你確認一樣</Chip>}
        {state === "differ" && <Chip tone="warn">不一樣</Chip>}
        {state === "unreadable" && <><UnreadChip />{action}</>}
      </div>
    </div>
  );
}
