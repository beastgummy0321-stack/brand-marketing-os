import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Chip, type ChipTone } from "./Chip";

/** v10 `connections()` `.src` (F30): one data source per row — a 44px icon tile, the source name with its state
 * chip (an `ok` chip is prefixed ✓), a muted note line, and an optional action on the right. `dimmed` is the
 * prototype's `opacity:.6` row for a platform without a reader (「尚未支援」). `data-slot="source-list"` /
 * `"source-row"`; `data-variant` is the chip tone. */

export function SourceList({ children, label = "資料來源" }: { children: ReactNode; label?: string }) {
  return <ul data-slot="source-list" aria-label={label} className="m-0 list-none p-0">{children}</ul>;
}

export function SourceRow({ icon, name, tone, status, note, action, dimmed = false }: {
  /** One glyph or a short letter, as the prototype (∞ ▤ ▢ G). */
  icon: ReactNode;
  name: ReactNode;
  tone: ChipTone;
  status: string;
  note?: ReactNode;
  action?: ReactNode;
  dimmed?: boolean;
}) {
  return (
    <li data-slot="source-row" data-variant={tone}
      className={cn("grid grid-cols-[44px_minmax(0,1fr)_auto] items-center gap-3.5 border-t border-border py-3.5 first:border-t-0", dimmed && "opacity-60")}>
      <span aria-hidden="true" className="grid size-11 place-items-center rounded-xl bg-muted text-lg font-bold text-muted-foreground">{icon}</span>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <b className="font-semibold">{name}</b>
          <Chip tone={tone}>{tone === "ok" ? "✓ " : ""}{status}</Chip>
        </div>
        {note && <div className="text-xs text-muted-foreground">{note}</div>}
      </div>
      {action ?? <span />}
    </li>
  );
}
