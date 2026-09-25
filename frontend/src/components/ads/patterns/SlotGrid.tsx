import { useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

/** v10 `tabAssets()` `.slots` + `.slot` (F30): the material grid of one ad group — auto-fill 128px tiles.
 * `SlotTile` variants mirror the prototype classes:
 * - `ready` (`.slot`): full-width thumbnail, the ad name, a status chip under it (the caller's `Chip`).
 * - `missing` (`.slot.miss`): dashed tile with ＋, 「缺 1 則」 and the caller's actions (上傳, 從素材工作檯).
 * - `reserved` (`.slot.seat`): the in-app image seat — grey, dashed, **not clickable** and without a button
 *   (a reserved seat is not a refusal; its note reads 「接上後開放」).
 * `data-slot="slot-grid"` / `"slot-tile"`, `data-variant` = the variant. */

export function SlotGrid({ children, label }: { children: ReactNode; label?: string }) {
  return (
    <div data-slot="slot-grid" role="list" aria-label={label} className="grid grid-cols-[repeat(auto-fill,minmax(128px,1fr))] gap-3">
      {children}
    </div>
  );
}

type SlotTileProps =
  | { variant: "ready"; name: string; thumbnailUrl: string | null; status?: ReactNode }
  | { variant: "missing"; title?: string; status?: ReactNode; actions?: ReactNode }
  | { variant: "reserved"; title: string; note?: string; icon?: ReactNode };

const BOX = "flex min-h-[176px] flex-col gap-1.5 rounded-[10px] border p-2";

export function SlotTile(props: SlotTileProps) {
  if (props.variant === "ready") {
    return (
      <div data-slot="slot-tile" data-variant="ready" role="listitem" className={cn(BOX, "border-border bg-card")}>
        <SlotThumb url={props.thumbnailUrl} />
        <div className="text-[11.5px] font-medium [overflow-wrap:anywhere]">{props.name}</div>
        {props.status && <div className="self-start">{props.status}</div>}
      </div>
    );
  }
  if (props.variant === "missing") {
    return (
      <div data-slot="slot-tile" data-variant="missing" role="listitem"
        className={cn(BOX, "items-center justify-center border-[1.5px] border-dashed border-grade-thin bg-background/50 text-center")}>
        <span aria-hidden="true" className="text-[22px] text-muted-foreground/60">＋</span>
        <b className="text-xs font-semibold">{props.title ?? "缺 1 則"}</b>
        {props.status}
        {props.actions && <div className="flex flex-col items-center gap-1.5">{props.actions}</div>}
      </div>
    );
  }
  return (
    <div data-slot="slot-tile" data-variant="reserved" role="listitem"
      className={cn(BOX, "items-center justify-center border-dashed border-border bg-muted text-center text-muted-foreground")}>
      <span aria-hidden="true" className="text-xl">{props.icon ?? "✦"}</span>
      <b className="text-xs font-semibold">{props.title}</b>
      <span className="text-[11.5px]">{props.note ?? "接上後開放"}</span>
    </div>
  );
}

/** The prototype's `.slot .th`: full tile width, 96px tall; a missing or failed image is the neutral tile. */
function SlotThumb({ url }: { url: string | null }) {
  const [failed, setFailed] = useState<string | null>(null);
  const tile = "h-24 w-full shrink-0 rounded-[7px] bg-muted object-cover";
  return url && failed !== url
    ? <img src={url} alt="" className={tile} loading="lazy" onError={() => setFailed(url)} />
    : <div className={tile} aria-hidden="true" />;
}
