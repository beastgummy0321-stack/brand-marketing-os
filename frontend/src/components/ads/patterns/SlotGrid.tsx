import { useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

/** The 素材 grid of one ad group and its tiles (F30; two halves since F35; F44 卡住; F45 prototype `f45-slot-states`
 * `.slots` / `.slot`, the layout spec since F45-I08).
 * `SlotGrid`: an auto-fill grid of tiles at least 270px wide and at most three to a row (the prototype's three columns
 * inside its content width); narrower than 270px it is one column.
 * `SlotTile`: one frame for every variant — the picture cell on the left (104 × 78), the text column on the right (the
 * ad name with its offer chip, the copy, the status chip at the bottom), and, when the slot has one, the row under both
 * (prototype `.why`). Variants:
 * - `ready` (`.slot`): the thumbnail, the copy (`copy`, or the muted `emptyCopy`), the status chip; `job` (F45) is what
 *   runs on a 處理中 slot, in the row under both (`data-slot="slot-job"`).
 * - `waiting` (F45 `.slot.wait`): a soft warning border, the caller's 等你 chip, the next-action row
 *   (`data-slot="slot-next"`: the caller's `actions` and `note`).
 * - `blocked` (F44 `.slot.blk`): the thumbnail dimmed, a soft danger border, no ✓ on the copy, the reason row
 *   (`data-slot="slot-reason"`): one sentence with the offending words marked, 「另有 N 個原因」, the caller's exits
 *   (`actions`) and `note` (what the last recheck said).
 * - `copy-only`: the dashed picture cell (＋, 「缺圖」, the caller's `imageActions` — 上傳), the copy, `extra`
 *   (看圖片提示詞), the status chip.
 * - `image-only`: the thumbnail, the dashed copy box (「缺文案」 + the caller's `copyActions` — 選一版文案).
 * - `missing`: a dashed frame, the dashed ＋ cell, 「缺 1 則」 (or `title`), the status and the caller's actions.
 * - `reserved`: the in-app image seat — grey, dashed, **not clickable** and without a button (its note 「接上後開放」).
 * The copy (`data-slot="slot-copy"`) is 「✓ 文案 · <label>」 over the text clamped to three lines; long names and copy
 * wrap (`overflow-wrap: anywhere`) inside the right column. `offer`: the ad's offer chip beside the name
 * (`data-slot="slot-head"`); without `offer` the name line is unchanged.
 * `data-slot="slot-grid"` / `"slot-tile"`, `data-variant` = the variant. */

export function SlotGrid({ children, label }: { children: ReactNode; label?: string }) {
  return (
    <div data-slot="slot-grid" role="list" aria-label={label}
      className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,max(270px,calc((100%_-_24px)/3))),1fr))] gap-3">
      {children}
    </div>
  );
}

/** The copy's words: the version label (「工作檯第 1 版」／已確認／待確認) and the clamped text. */
export interface SlotCopyText { label: string; text: string }

/** Why a slot is blocked: one sentence, the words it quotes (marked where they stand as a quoted item) and how many
 * other reasons there are. */
export interface SlotReason { text: string; terms: string[]; more?: number }

type SlotTileProps =
  | { variant: "ready"; name: string; thumbnailUrl: string | null; copy?: SlotCopyText | null; emptyCopy?: string; offer?: ReactNode; status?: ReactNode;
      job?: ReactNode }
  | { variant: "waiting"; name: string; thumbnailUrl: string | null; copy?: SlotCopyText | null; emptyCopy?: string; offer?: ReactNode;
      status?: ReactNode; actions?: ReactNode; note?: ReactNode }
  | { variant: "copy-only"; name: string; copy: SlotCopyText; offer?: ReactNode; imageActions?: ReactNode; extra?: ReactNode; status?: ReactNode }
  | { variant: "image-only"; name: string; thumbnailUrl: string | null; offer?: ReactNode; copyActions?: ReactNode; status?: ReactNode }
  | { variant: "blocked"; name: string; thumbnailUrl: string | null; copy?: SlotCopyText | null; offer?: ReactNode; status?: ReactNode;
      reason: SlotReason; actions?: ReactNode; note?: ReactNode }
  | { variant: "missing"; title?: string; status?: ReactNode; actions?: ReactNode }
  | { variant: "reserved"; title: string; note?: string; icon?: ReactNode };

const NAME = "text-[12.5px] font-semibold leading-snug [overflow-wrap:anywhere]";
const DASHED = "border-[1.5px] border-dashed border-grade-thin bg-background/50";
const CELL = "flex min-h-[78px] w-[104px] flex-col items-center justify-center gap-1 rounded-[7px] px-1.5 py-2 text-center";
const ACTIONS = "flex flex-wrap items-center gap-x-3 gap-y-1.5";

/** The frame every variant shares (prototype `.slot`): picture cell | text column, then the row under both. */
function Frame({ variant, className, picture, under, underSlot, children }: {
  variant: string; className: string; picture: ReactNode; under?: ReactNode; underSlot?: string; children: ReactNode;
}) {
  return (
    // A container query: a tile squeezed below ~17rem (a very narrow screen) stacks the picture over the text instead
    // of leaving the text column a few characters wide.
    <div data-slot="slot-tile" data-variant={variant} role="listitem" className={cn("@container rounded-[10px] border p-2.5", className)}>
      <div className="grid h-full grid-cols-[104px_minmax(0,1fr)] content-start gap-2.5 @max-[17rem]:grid-cols-1">
        <div className="flex flex-col items-start gap-1.5">{picture}</div>
        <div className="flex min-w-0 flex-col gap-1">{children}</div>
        {under && <div data-slot={underSlot} className="col-span-full flex flex-col gap-2 border-t border-border pt-2">{under}</div>}
      </div>
    </div>
  );
}

/** The status chip at the bottom of the text column (prototype `.ft`). */
function Foot({ children }: { children: ReactNode }) {
  return <div className="mt-auto flex flex-col items-start gap-1 self-start pt-1">{children}</div>;
}

export function SlotTile(props: SlotTileProps) {
  if (props.variant === "ready") {
    return (
      <Frame variant="ready" className="border-border bg-card" picture={<SlotThumb url={props.thumbnailUrl} />}
        under={props.job} underSlot="slot-job">
        <SlotHead name={props.name} offer={props.offer} />
        {/* A slot with a running job is not confirmed yet: no ✓ beside its copy. */}
        {props.copy ? <CopyHalf copy={props.copy} tick={!props.job} /> : props.emptyCopy && <NoCopyHalf text={props.emptyCopy} />}
        {props.status && <Foot>{props.status}</Foot>}
      </Frame>
    );
  }
  if (props.variant === "waiting") {
    return (
      <Frame variant="waiting" className="border-warning/45 bg-card" picture={<SlotThumb url={props.thumbnailUrl} />} underSlot="slot-next"
        under={<>
          {props.actions && <div className={ACTIONS}>{props.actions}</div>}
          {props.note}
        </>}>
        <SlotHead name={props.name} offer={props.offer} />
        {props.copy ? <CopyHalf copy={props.copy} tick={false} /> : props.emptyCopy && <NoCopyHalf text={props.emptyCopy} />}
        {props.status && <Foot>{props.status}</Foot>}
      </Frame>
    );
  }
  if (props.variant === "blocked") {
    const more = props.reason.more ?? 0;
    return (
      <Frame variant="blocked" className="border-danger/45 bg-card" picture={<SlotThumb url={props.thumbnailUrl} dim />} underSlot="slot-reason"
        under={<>
          <p className="text-[12.5px] leading-normal [overflow-wrap:anywhere]">{markTerms(props.reason.text, props.reason.terms)}</p>
          {more > 0 && <span className="text-[11.5px] text-muted-foreground">另有 {more} 個原因</span>}
          {props.actions && <div className={ACTIONS}>{props.actions}</div>}
          {props.note}
        </>}>
        <SlotHead name={props.name} offer={props.offer} />
        {props.copy && <CopyHalf copy={props.copy} tick={false} />}
        {props.status && <Foot>{props.status}</Foot>}
      </Frame>
    );
  }
  if (props.variant === "copy-only") {
    return (
      <Frame variant="copy-only" className="border-border bg-card" picture={
        <div className={cn(CELL, DASHED, "text-muted-foreground")}>
          <span aria-hidden="true" className="text-lg leading-none text-muted-foreground/60">＋</span>
          <b className="text-xs font-semibold text-foreground">缺圖</b>
          {props.imageActions}
        </div>
      }>
        <SlotHead name={props.name} offer={props.offer} />
        <CopyHalf copy={props.copy} />
        {props.extra && <div className="self-start">{props.extra}</div>}
        {props.status && <Foot>{props.status}</Foot>}
      </Frame>
    );
  }
  if (props.variant === "image-only") {
    return (
      <Frame variant="image-only" className="border-border bg-card" picture={<SlotThumb url={props.thumbnailUrl} />}>
        <SlotHead name={props.name} offer={props.offer} />
        <div data-slot="slot-copy" data-variant="missing"
          className={cn(DASHED, "flex min-h-[52px] flex-col items-center justify-center gap-[3px] rounded-[7px] px-2 py-1.5 text-center text-muted-foreground")}>
          <b className="text-xs font-semibold text-foreground">缺文案</b>
          {props.copyActions}
        </div>
        {props.status && <Foot>{props.status}</Foot>}
      </Frame>
    );
  }
  if (props.variant === "missing") {
    return (
      <Frame variant="missing" className={cn(DASHED, "rounded-[10px]")} picture={
        <div aria-hidden="true" className={cn(CELL, DASHED, "text-[22px] text-muted-foreground/60")}>＋</div>
      }>
        <b className="text-[12.5px] font-semibold leading-snug [overflow-wrap:anywhere]">{props.title ?? "缺 1 則"}</b>
        {props.status && <div className="self-start">{props.status}</div>}
        {props.actions && <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1.5 pt-1">{props.actions}</div>}
      </Frame>
    );
  }
  return (
    <Frame variant="reserved" className="border-dashed border-border bg-muted text-muted-foreground" picture={
      <div aria-hidden="true" className={cn(CELL, "border border-dashed border-border text-xl")}>{props.icon ?? "✦"}</div>
    }>
      <b className="text-[12.5px] font-semibold">{props.title}</b>
      <span className="text-[11.5px]">{props.note ?? "接上後開放"}</span>
    </Frame>
  );
}

/** The prototype's `.cp .t`: 「✓ 文案 · <label>」 over the copy, clamped to three lines. `tick={false}` (blocked,
 * waiting): no ✓ — a tick beside 「卡住」／「待確認」 would say two things at once. */
function CopyHalf({ copy, tick = true }: { copy: SlotCopyText; tick?: boolean }) {
  return (
    <div data-slot="slot-copy" data-variant="filled" className="flex min-w-0 flex-col gap-0.5">
      <span className="flex items-center gap-1 text-[10.5px] text-muted-foreground">
        {tick && <i aria-hidden="true" className="not-italic font-bold text-success">✓</i>}文案 · {copy.label}
      </span>
      <p className="line-clamp-3 text-[12.5px] leading-[1.45] [overflow-wrap:anywhere]">{copy.text}</p>
    </div>
  );
}

/** No copy yet (prototype `.cp .t.none`): the muted sentence where the copy goes. */
function NoCopyHalf({ text }: { text: string }) {
  return <p data-slot="slot-copy" data-variant="none" className="text-[12.5px] leading-[1.45] text-muted-foreground">{text}</p>;
}

/** The tile's head: the ad name, and the ad's offer chip beside it when given (prototype `.row` of `.nm` + `.chip`). */
function SlotHead({ name, offer }: { name: string; offer?: ReactNode }) {
  if (!offer) return <div className={NAME}>{name}</div>;
  return (
    // A name too long to share the line keeps the full width and the chip goes under it — never a name squeezed to a
    // few characters per line beside the chip.
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

/** The prototype's `.slot .im .th`: 104 × 78; a missing or failed image is the neutral tile. `dim` (`.th.dim`): the
 * blocked tile's thumbnail, greyed. */
function SlotThumb({ url, dim = false }: { url: string | null; dim?: boolean }) {
  const [failed, setFailed] = useState<string | null>(null);
  const tile = cn("h-[78px] w-[104px] shrink-0 rounded-[7px] bg-muted object-cover", dim && "opacity-70 grayscale-[.6]");
  return url && failed !== url
    ? <img src={url} alt="" className={tile} loading="lazy" onError={() => setFailed(url)} />
    : <div className={tile} aria-hidden="true" />;
}
