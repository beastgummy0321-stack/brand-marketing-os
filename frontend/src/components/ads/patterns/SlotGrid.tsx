import { useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

/** v10 `tabAssets()` `.slots` + `.slot` (F30, two halves since F35): the material grid of one ad group — auto-fill
 * 148px tiles, each the image half over the ad name over the copy half, one status chip at the bottom.
 * `SlotTile` variants mirror the prototype classes:
 * - `ready` (`.slot`): the thumbnail, the ad name, the copy half when given (`copy`), a status chip (the caller's `Chip`).
 * - `copy-only` (`[data-variant=copy-only]`): the dashed image half (＋, 「缺圖」, the caller's `imageActions` — 上傳),
 *   the name, the copy half, the caller's `extra` (看圖片提示詞), the status chip.
 * - `image-only` (`[data-variant=image-only]`): the thumbnail, the name, the dashed copy half (「缺文案」 + the caller's
 *   `copyActions` — 選一版文案), the status chip.
 * - `missing` (`.slot.miss`): dashed tile with ＋, 「缺 1 則」 and the caller's actions (上傳, 從素材工作檯).
 * - `reserved` (`.slot.seat`): the in-app image seat — grey, dashed, **not clickable** and without a button
 *   (a reserved seat is not a refusal; its note reads 「接上後開放」).
 * The copy half (`data-slot="slot-copy"`) is 「✓ 文案 · <label>」 over a two-line clamp of the text; long names and
 * copy wrap (`overflow-wrap: anywhere`), never a control.
 * `data-slot="slot-grid"` / `"slot-tile"`, `data-variant` = the variant. */

export function SlotGrid({ children, label }: { children: ReactNode; label?: string }) {
  return (
    <div data-slot="slot-grid" role="list" aria-label={label} className="grid grid-cols-[repeat(auto-fill,minmax(148px,1fr))] gap-3">
      {children}
    </div>
  );
}

/** The copy half's words: the version label (「工作檯第 1 版」／已確認／待確認) and the clamped text. */
export interface SlotCopyText { label: string; text: string }

type SlotTileProps =
  | { variant: "ready"; name: string; thumbnailUrl: string | null; copy?: SlotCopyText | null; status?: ReactNode }
  | { variant: "copy-only"; name: string; copy: SlotCopyText; imageActions?: ReactNode; extra?: ReactNode; status?: ReactNode }
  | { variant: "image-only"; name: string; thumbnailUrl: string | null; copyActions?: ReactNode; status?: ReactNode }
  | { variant: "missing"; title?: string; status?: ReactNode; actions?: ReactNode }
  | { variant: "reserved"; title: string; note?: string; icon?: ReactNode };

const BOX = "flex min-h-[212px] flex-col gap-1.5 rounded-[10px] border p-2";
const NAME = "text-[11.5px] font-medium [overflow-wrap:anywhere]";
const DASHED = "border-[1.5px] border-dashed border-grade-thin bg-background/50 text-center";
const HALF = "min-w-0 rounded-[7px]";

export function SlotTile(props: SlotTileProps) {
  if (props.variant === "ready") {
    return (
      <div data-slot="slot-tile" data-variant="ready" role="listitem" className={cn(BOX, "border-border bg-card")}>
        <SlotThumb url={props.thumbnailUrl} />
        <div className={NAME}>{props.name}</div>
        {props.copy && <CopyHalf copy={props.copy} />}
        {props.status && <div className="mt-auto self-start">{props.status}</div>}
      </div>
    );
  }
  if (props.variant === "copy-only") {
    return (
      <div data-slot="slot-tile" data-variant="copy-only" role="listitem" className={cn(BOX, "border-border bg-card")}>
        <div className={cn(HALF, DASHED, "flex h-24 w-full shrink-0 flex-col items-center justify-center gap-1 text-muted-foreground")}>
          <span aria-hidden="true" className="text-xl leading-none text-muted-foreground/60">＋</span>
          <b className="text-xs font-semibold text-foreground">缺圖</b>
          {props.imageActions}
        </div>
        <div className={NAME}>{props.name}</div>
        <CopyHalf copy={props.copy} />
        {props.extra && <div className="self-start">{props.extra}</div>}
        {props.status && <div className="mt-auto self-start">{props.status}</div>}
      </div>
    );
  }
  if (props.variant === "image-only") {
    return (
      <div data-slot="slot-tile" data-variant="image-only" role="listitem" className={cn(BOX, "border-border bg-card")}>
        <SlotThumb url={props.thumbnailUrl} />
        <div className={NAME}>{props.name}</div>
        <div data-slot="slot-copy" data-variant="missing"
          className={cn(HALF, DASHED, "flex min-h-[58px] flex-col items-center justify-center gap-[3px] px-2 py-1.5 text-muted-foreground")}>
          <b className="text-xs font-semibold text-foreground">缺文案</b>
          {props.copyActions}
        </div>
        {props.status && <div className="mt-auto self-start">{props.status}</div>}
      </div>
    );
  }
  if (props.variant === "missing") {
    return (
      <div data-slot="slot-tile" data-variant="missing" role="listitem"
        className={cn(BOX, DASHED, "items-center justify-center")}>
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

/** The prototype's `.slot .half.txt`: 「✓ 文案 · <label>」 over the copy, clamped to two lines. */
function CopyHalf({ copy }: { copy: SlotCopyText }) {
  return (
    <div data-slot="slot-copy" data-variant="filled"
      className={cn(HALF, "flex min-h-[58px] flex-col gap-0.5 border border-border bg-muted px-2 py-1.5")}>
      <span className="flex items-center gap-1 text-[10.5px] text-muted-foreground">
        <i aria-hidden="true" className="not-italic font-bold text-success">✓</i>文案 · {copy.label}
      </span>
      <p className="line-clamp-2 text-xs leading-[1.4] [overflow-wrap:anywhere]">{copy.text}</p>
    </div>
  );
}

/** The prototype's `.slot .th` / `.half.img`: full tile width, 96px tall; a missing or failed image is the neutral tile. */
function SlotThumb({ url }: { url: string | null }) {
  const [failed, setFailed] = useState<string | null>(null);
  const tile = "h-24 w-full shrink-0 rounded-[7px] bg-muted object-cover";
  return url && failed !== url
    ? <img src={url} alt="" className={tile} loading="lazy" onError={() => setFailed(url)} />
    : <div className={tile} aria-hidden="true" />;
}
