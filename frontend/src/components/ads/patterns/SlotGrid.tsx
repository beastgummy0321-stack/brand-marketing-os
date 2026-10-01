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
 * - `blocked` (F44 `.slot.blk`): the two halves of a ready tile with the thumbnail dimmed and a soft danger border, the
 *   status chip (the caller's 卡住), then the reason region under both halves (`data-slot="slot-reason"`, prototype
 *   `.why`): one sentence with the offending words marked, 「另有 N 個原因」 when there are more, the caller's exits
 *   (`actions`, prototype `.ac`) and the caller's `note` (what the last recheck said).
 * The copy half (`data-slot="slot-copy"`) is 「✓ 文案 · <label>」 over a two-line clamp of the text; long names and
 * copy wrap (`overflow-wrap: anywhere`), never a control.
 * `offer` (F44): the ad's offer chip beside the name (`data-slot="slot-head"`); a name too long to share the line
 * keeps the full width and the chip goes under it. Without `offer` the name line is unchanged.
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

/** Why a slot is blocked: one sentence, the words it quotes (marked where they stand as a quoted item) and how many
 * other reasons there are. */
export interface SlotReason { text: string; terms: string[]; more?: number }

type SlotTileProps =
  | { variant: "ready"; name: string; thumbnailUrl: string | null; copy?: SlotCopyText | null; offer?: ReactNode; status?: ReactNode }
  | { variant: "copy-only"; name: string; copy: SlotCopyText; offer?: ReactNode; imageActions?: ReactNode; extra?: ReactNode; status?: ReactNode }
  | { variant: "image-only"; name: string; thumbnailUrl: string | null; offer?: ReactNode; copyActions?: ReactNode; status?: ReactNode }
  | { variant: "blocked"; name: string; thumbnailUrl: string | null; copy?: SlotCopyText | null; offer?: ReactNode; status?: ReactNode;
      reason: SlotReason; actions?: ReactNode; note?: ReactNode }
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
        <SlotHead name={props.name} offer={props.offer} />
        {props.copy && <CopyHalf copy={props.copy} />}
        {props.status && <div className="mt-auto self-start">{props.status}</div>}
      </div>
    );
  }
  if (props.variant === "blocked") {
    const more = props.reason.more ?? 0;
    return (
      <div data-slot="slot-tile" data-variant="blocked" role="listitem" className={cn(BOX, "border-danger/45 bg-card")}>
        <SlotThumb url={props.thumbnailUrl} dim />
        <SlotHead name={props.name} offer={props.offer} />
        {props.copy && <CopyHalf copy={props.copy} />}
        {props.status && <div className="self-start">{props.status}</div>}
        <div data-slot="slot-reason" className="flex flex-col gap-2 border-t border-border pt-2">
          <p className="text-[12.5px] leading-normal [overflow-wrap:anywhere]">{markTerms(props.reason.text, props.reason.terms)}</p>
          {more > 0 && <span className="text-[11.5px] text-muted-foreground">另有 {more} 個原因</span>}
          {props.actions && <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">{props.actions}</div>}
          {props.note}
        </div>
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
        <SlotHead name={props.name} offer={props.offer} />
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
        <SlotHead name={props.name} offer={props.offer} />
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

/** The tile's head: the ad name, and the ad's offer chip beside it when given (F44 prototype `.row` of `.nm` + `.chip`). */
function SlotHead({ name, offer }: { name: string; offer?: ReactNode }) {
  if (!offer) return <div className={NAME}>{name}</div>;
  return (
    <div data-slot="slot-head" className="flex flex-wrap items-start justify-between gap-x-1.5 gap-y-1">
      <div className={cn(NAME, "min-w-0")}>{name}</div>
      {offer}
    </div>
  );
}

/** The reason sentence with its offending words marked (prototype `.why p mark`). A term is marked only where it
 * stands as a quoted item — between 「／、 and 」／、 — so 「優惠」 is marked but the same characters inside
 * 「無優惠」 or in the rest of the sentence are not. */
function markTerms(text: string, terms: string[]): ReactNode {
  const words = terms.filter((t) => t !== "").sort((a, b) => b.length - a.length);
  if (words.length === 0) return text;
  const out: ReactNode[] = [];
  let plain = "";
  let i = 0;
  while (i < text.length) {
    const opened = i > 0 && (text[i - 1] === "「" || text[i - 1] === "、");
    const hit = opened ? words.find((w) => text.startsWith(w, i) && (text[i + w.length] === "」" || text[i + w.length] === "、")) : undefined;
    if (!hit) { plain += text[i]; i += 1; continue; }
    if (plain) { out.push(plain); plain = ""; }
    out.push(<mark key={i} className="rounded-[3px] bg-zone-over px-[3px] font-semibold text-danger">{hit}</mark>);
    i += hit.length;
  }
  if (plain) out.push(plain);
  return out;
}

/** The prototype's `.slot .th` / `.half.img`: full tile width, 96px tall; a missing or failed image is the neutral tile.
 * `dim` (F44 `.th.dim`): the blocked tile's thumbnail, greyed. */
function SlotThumb({ url, dim = false }: { url: string | null; dim?: boolean }) {
  const [failed, setFailed] = useState<string | null>(null);
  const tile = cn("h-24 w-full shrink-0 rounded-[7px] bg-muted object-cover", dim && "opacity-70 grayscale-[.6]");
  return url && failed !== url
    ? <img src={url} alt="" className={tile} loading="lazy" onError={() => setFailed(url)} />
    : <div className={tile} aria-hidden="true" />;
}
