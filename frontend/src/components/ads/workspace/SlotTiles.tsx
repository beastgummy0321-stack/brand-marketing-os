import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/layout/ui/dialog";
import { Textarea } from "@/components/layout/ui/textarea";
import { Skeleton } from "@/components/layout/Skeleton";
import {
  chooseSlotCopy, editSlotCopy, fetchSlotThumbnail, getSlotCopyOptions, isAuthThumbnail,
  type CampaignSlots, type Slot, type SlotCopy, type SlotCopyOption, type SlotJob, type SlotStatutory,
} from "@/lib/adsSlotsApi";
import type { CopyFields } from "@/lib/adsUserAssetsApi";
import { useApiRead } from "@/lib/useApiRead";
import { Chip, ReadFailed, SlotTile, type ChipTone } from "../patterns";

/** The 素材 tab's slot tiles and their two dialogs (moved out of `AssetsBody`, F45-I08). One tile per Contract F/T/D/W
 * state: ready, in progress and retrying (`ReadySlot`; a running slot says what runs — F45 prototype `f45-slot-states`
 * `.why .job`), waiting (`WaitingSlot`, the server's next action), blocked (`BlockedSlot`), failed (`FailedSlot`, the
 * workbench exit), missing, copy-only and image-only; the copy picker (`CopyPicker`) and the in-place copy editor
 * (`CopyEditor`, 保存後馬上檢查).
 * F49 Contract T: every tile's chip prints the served `state_label` and its line the served `state_text` — no tile
 * picks its own state word. Only the chip's colour is chosen here (`STATE_TONE`, presentation). */

export const VIDEO_NEEDED = "這格要影片腳本，照片不算";
const SHARED_IMAGE = "同一張圖，文案不同";
export const isVideoSlot = (slot: Slot) => slot.format_key === "video";
export const flatSlots = (data: CampaignSlots) => data.groups.flatMap((g) => g.slots);
/** The prototype's `.btn.s.go`: the slot's one next step, primary-bordered; long server sentences wrap. */
const GO = "h-auto min-h-8 max-w-full shrink whitespace-normal border-primary py-1 text-left font-semibold text-primary hover:text-primary";

/** The chip colour per slot state (presentation only; the word is the served `state_label`). */
export const STATE_TONE: Record<Slot["state"], ChipTone> = {
  ready: "ok", in_progress: "accent", retrying: "accent", failed: "bad", blocked: "bad",
  waiting: "warn", image_only: "warn", copy_only: "warn", missing: "warn",
};

/** The slot's served chip (`state_label`), with an optional suffix; nothing when the read carries no label. */
function StateChip({ slot, suffix = "" }: { slot: Slot; suffix?: string }) {
  if (!slot.state_label) return null;
  return <Chip tone={STATE_TONE[slot.state]}>{slot.state_label}{suffix}</Chip>;
}

/** The slot's served sentence (`state_text`) as the muted line under its chip; nothing when it is empty. */
function StateLine({ slot }: { slot: Slot }) {
  if (!slot.state_text) return null;
  return <p data-slot="slot-state-text" className="text-[11.5px] leading-[1.45] text-muted-foreground [overflow-wrap:anywhere]">{slot.state_text}</p>;
}

/** The ad's offer coordinate as the tile head's chip — the served label, accent unless its `offer_key` is `none`
 * (無優惠; F48: the tone branches on the key, never the label); nothing for an ad without one. */
function offerChip(slot: Slot): ReactNode {
  if (!slot.offer_label) return undefined;
  return <Chip tone={slot.offer_key === "none" ? "neutral" : "accent"}>{slot.offer_label}</Chip>;
}

/** The URL an `<img>` can load: a platform URL as is; an authenticated user-asset path fetched into an object URL
 * (revoked when it changes or unmounts). `null` while loading or when the fetch fails — the neutral tile. */
export function useShownThumbnail(url: string | null): string | null {
  const [made, setMade] = useState<{ from: string; src: string } | null>(null);
  useEffect(() => {
    if (!isAuthThumbnail(url)) return;
    const controller = new AbortController();
    let objectUrl: string | null = null;
    fetchSlotThumbnail(url, controller.signal).then((blob) => {
      if (controller.signal.aborted) return;
      objectUrl = URL.createObjectURL(blob);
      setMade({ from: url, src: objectUrl });
    }).catch(() => { /* the neutral tile stands in; a thumbnail never blanks the grid */ });
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [url]);
  if (!isAuthThumbnail(url)) return url;
  return made?.from === url ? made.src : null;
}

/** The copy half's words: the version label and `headline　body` (a copy with neither shows its description). */
function copyText(copy: SlotCopy): { label: string; text: string } {
  const text = [copy.headline, copy.body].filter((t): t is string => !!t && t.trim() !== "").join("　");
  return { label: copy.label, text: text || copy.description || "" };
}

/** What the last 再檢查一次／確認 of a slot said: still blocked (`line`), or the call failed (`error`). */
export type Checked = { adId: string; line: string; error: boolean };

function CheckedNote({ checked, failed = "沒有檢查成功" }: { checked: Checked | null; failed?: string }) {
  if (!checked) return null;
  return checked.error
    ? <p role="alert" className="text-xs text-danger">{failed}：{checked.line}</p>
    : <p role="status" className="text-xs text-muted-foreground">{checked.line}</p>;
}

/** The job line of a running slot (prototype `.job`): the served sentence (「圖片處理中」／「文案產生中」), what runs,
 * 「已寫好 d／n」 with its bar only when the workbench read gives both numbers, and 「自動更新，不用重整」 (the tab re-reads
 * while anything runs). A retrying slot (F49 Contract T) has no job: its line is the served sentence alone (the error
 * and when the next attempt is due), and it keeps polling like a running one. */
function JobLine({ job, text }: { job: SlotJob | null; text: string | undefined }) {
  const counted = job?.done != null && job.of != null && job.of > 0 ? { done: job.done, of: job.of } : null;
  const what = job?.kind === "copy"
    ? `工作檯正在寫${job.of ? ` ${job.of} 版` : ""}文案${counted ? `，已寫好 ${counted.done}／${counted.of}` : ""}`
    : job?.kind === "preview" ? "把這張圖和文案合成預覽" : null;
  return (
    <div className="flex items-start gap-2 text-[12.5px] leading-normal">
      <Spinner className="mt-[3px]" />
      <div className="min-w-0 [overflow-wrap:anywhere]">
        {/* A slot without its sentence (older data) says only that it updates by itself — never a guessed state. */}
        {text && <b className="font-semibold">{text}</b>}{text && what && "："}{what}
        {counted && (
          <span data-slot="slot-job-steps" aria-hidden="true" className="mt-[5px] flex w-[120px] max-w-full gap-[3px]">
            {Array.from({ length: counted.of }, (_, i) => <i key={i} className={`h-1 flex-1 rounded-sm ${i < counted.done ? "bg-primary" : "bg-muted"}`} />)}
          </span>
        )}
        <small className="block text-[11.5px] text-muted-foreground" data-slot="slot-polling">自動更新，不用重整</small>
      </div>
    </div>
  );
}

/** F46 Contract F (prototype `f45-slot-states` slot a2, `.slot .note`): the file ships in another format than planned —
 * a fact under the status chip, never a block (「ⓘ 規劃是輪播，只放了 1 張圖，會以單圖上架」). */
function FormatNote({ text }: { text: string }) {
  return (
    <p data-slot="slot-format-note" className="flex gap-[5px] text-[11.5px] leading-[1.45] text-muted-foreground [overflow-wrap:anywhere]">
      <i aria-hidden="true" className="shrink-0 not-italic">ⓘ</i>{text}
    </p>
  );
}

/** F48 Contract G (F34 remind-only): the statutory reminder for the slot's copy — one muted line under the copy half:
 * the terms the copy hits, the server's sentence and the regulation link. It never blocks the slot. */
function StatutoryLine({ statutory }: { statutory: SlotStatutory }) {
  return (
    <p data-slot="slot-statutory" className="text-[11.5px] leading-[1.45] text-muted-foreground [overflow-wrap:anywhere]">
      <b className="font-semibold">食安法提醒</b>
      {statutory.terms.map((t) => <span key={t.term}>・「{t.term}」{t.tier_label}</span>)}
      <span>：{statutory.sentence} </span>
      <a className="underline underline-offset-2" href={statutory.href} target="_blank" rel="noreferrer">衛福部認定準則</a>
    </p>
  );
}

/** A ready, in-progress or retrying slot. `shared`: another slot in the same response shows the same thumbnail (one
 * original backing several ads) — the caption and 換一張 (a new upload into this ad's slot). `justDone`: this slot was
 * not ready in an earlier read of the same screen and became ready (the served chip + 「・剛處理好」).
 * F49 Contract T: a ready planned ad whose launch is not approved yet (`copy_editable`) offers 換文案 (`onPickCopy`, the
 * copy picker); after the approval the served sentence says the copy is frozen. `checked`: why the last 換文案 was
 * refused, beside the tile. */
export function ReadySlot({ slot, shared, justDone, busy, onPick, onPickCopy, checked = null }: {
  slot: Slot; shared: boolean; justDone: boolean; busy: boolean; onPick: (file: File) => void;
  onPickCopy?: () => void; checked?: Checked | null;
}) {
  const thumb = useShownThumbnail(slot.thumbnail_url);
  const running = slot.state === "in_progress" || slot.state === "retrying";
  const chip = !running && slot.replace_task_id
    ? <Chip tone="warn">要換掉</Chip>
    : <StateChip slot={slot} suffix={!running && justDone ? "・剛處理好" : ""} />;
  const swap = !running && slot.copy_editable === true && slot.ad_id !== null && !!onPickCopy;
  const status = (
    <div className="flex flex-col items-start gap-1">
      {shared && !running && (
        <span className="flex flex-wrap items-center gap-x-1.5 text-[11px] text-muted-foreground" data-slot="slot-shared">
          {SHARED_IMAGE}
          {slot.ad_id !== null && <UploadAction slot={slot} busy={busy} onPick={onPick} label="換一張" variant="link" />}
        </span>
      )}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        {chip}
        {swap && <Button variant="link" size="xs" className="h-auto px-0" aria-label={`換文案：${slot.name}`} onClick={onPickCopy}>換文案</Button>}
      </div>
      {!running && <StateLine slot={slot} />}
      {slot.format_note && <FormatNote text={slot.format_note} />}
      {slot.statutory && <StatutoryLine statutory={slot.statutory} />}
      <CheckedNote checked={checked} failed="文案沒有換成" />
    </div>
  );
  return (
    <SlotTile variant="ready" name={slot.name} thumbnailUrl={thumb} copy={slot.copy && copyText(slot.copy)} offer={offerChip(slot)} status={status}
      emptyCopy={slot.state === "in_progress" && slot.job?.kind === "copy" ? "文案還在寫" : undefined}
      job={running ? <JobLine job={slot.job} text={slot.state_text} /> : undefined} />
  );
}

/** F49 Contract T: the ad's workbench set failed to write its copy. The served chip and sentence (the error), and the
 * exit that reruns it — the ad's set on the workbench (`workbench_href`, else the campaign's pack). Nothing changes it by
 * itself, so it does not poll. */
export function FailedSlot({ slot, workbenchHref }: { slot: Slot; workbenchHref: string }) {
  const thumb = useShownThumbnail(slot.thumbnail_url);
  return (
    <SlotTile variant="blocked" name={slot.name} thumbnailUrl={thumb} copy={slot.copy && copyText(slot.copy)} offer={offerChip(slot)}
      status={<StateChip slot={slot} />} reason={{ text: slot.state_text ?? "", terms: [] }}
      actions={
        <Button variant="outline" size="sm" className={GO} asChild>
          <Link to={slot.workbench_href ?? workbenchHref}>到工作檯重新產生 →</Link>
        </Button>
      } />
  );
}

/** F45: nothing runs and nothing refused — the user's next action, in the server's words. `pick_on_workbench` → the
 * ad's workbench set (「〈text〉 →」); `confirm_copy` → the button that runs the confirmation again (`onConfirm`) and
 * 改文案 (the editor). A `waiting` state without its action reads as unknown, never as a fake button. */
export function WaitingSlot({ slot, workbenchHref, checking, checked, onConfirm, onEdit }: {
  slot: Slot; workbenchHref: string; checking: boolean; checked: Checked | null; onConfirm: () => void; onEdit: () => void;
}) {
  const thumb = useShownThumbnail(slot.thumbnail_url);
  const next = slot.waiting;
  let actions: ReactNode = null;
  if (next?.action === "pick_on_workbench") {
    actions = (
      <Button variant="outline" size="sm" className={GO} asChild>
        <Link to={slot.workbench_href ?? workbenchHref}>{next.text} →</Link>
      </Button>
    );
  } else if (next?.action === "confirm_copy" && slot.ad_id !== null) {
    actions = <>
      <Button variant="outline" size="sm" className={GO} disabled={checking} onClick={onConfirm}>{checking ? "檢查中…" : next.text}</Button>
      <Button variant="link" size="xs" className="h-auto px-0" aria-label={`改文案：${slot.name}`} onClick={onEdit}>改文案</Button>
    </>;
  }
  return (
    <SlotTile variant="waiting" name={slot.name} thumbnailUrl={thumb} copy={slot.copy && copyText(slot.copy)} offer={offerChip(slot)}
      emptyCopy="還沒選文案" status={<>
        {/* The served sentence is the next action itself (the button below); the chip says whose turn it is. */}
        <StateChip slot={slot} />
        {slot.copy && slot.statutory && <StatutoryLine statutory={slot.statutory} />}
      </>} actions={actions}
      note={<>
        {!next && <p className="text-xs text-muted-foreground">下一步讀不到，請重新整理。</p>}
        <CheckedNote checked={checked} />
      </>} />
  );
}

/** F44: a slot whose confirmation was refused, or whose file failed. The tile says why and offers the exit that fixes
 * that reason — F45: a copy reason → 改這句文案 (the editor) and 到工作檯換一版 → (the ad's set; without one, the
 * 換一版文案 picker); a file reason → 換一張 — and 再檢查一次 for a reason fixed somewhere else. A `blocked` state
 * without its reason reads as unknown. F49 Contract T: a refused assignment (reason kind `assign`, `fix: null` — a
 * closed campaign, an approved launch) shows its sentence with 再檢查一次 only. */
export function BlockedSlot({ slot, uploading, checking, checked, onPick, onPickCopy, onEdit, onRecheck }: {
  slot: Slot; uploading: boolean; checking: boolean; checked: Checked | null;
  onPick: (file: File) => void; onPickCopy: () => void; onEdit: () => void; onRecheck: () => void;
}) {
  const thumb = useShownThumbnail(slot.thumbnail_url);
  const blocked = slot.blocked ?? { text: slot.state_text || "這一格停下來的原因讀不到。", terms: [], fix: null, more: 0 };
  return (
    <SlotTile variant="blocked" name={slot.name} thumbnailUrl={thumb} copy={slot.copy && copyText(slot.copy)} offer={offerChip(slot)}
      status={<>
        <StateChip slot={slot} />
        {slot.statutory && <StatutoryLine statutory={slot.statutory} />}
      </>} reason={{ text: blocked.text, terms: blocked.terms, more: blocked.more }}
      actions={slot.ad_id !== null && <>
        {blocked.fix === "copy" && <Button variant="outline" size="sm" className={GO} aria-label={`改這句文案：${slot.name}`} onClick={onEdit}>改這句文案</Button>}
        {blocked.fix === "copy" && (slot.workbench_href
          ? <Button variant="link" size="xs" className="h-auto px-0" asChild><Link to={slot.workbench_href}>到工作檯換一版 →</Link></Button>
          : <Button variant="link" size="xs" className="h-auto px-0" aria-label={`換一版文案：${slot.name}`} onClick={onPickCopy}>換一版文案</Button>)}
        {blocked.fix === "file" && <UploadAction slot={slot} busy={uploading} onPick={onPick} label="換一張" className={GO} />}
        <Button variant="link" size="xs" className="h-auto px-0" disabled={checking} aria-label={`${checking ? "檢查中…" : "再檢查一次"}：${slot.name}`} onClick={onRecheck}>
          {checking ? "檢查中…" : "再檢查一次"}
        </Button>
      </>}
      note={<CheckedNote checked={checked} />} />
  );
}

/** The small spinner of a running job (the prototype's `.spin`). */
function Spinner({ className = "" }: { className?: string }) {
  return <span aria-hidden="true" className={`inline-block size-3.5 shrink-0 animate-spin rounded-full border-2 border-chart-soft border-t-primary ${className}`} />;
}

/** The hidden file input and its button, shared by the missing tile, the copy-only tile's image half, the video
 * placeholder (上傳影片, `accept="video/*"`), the blocked tile (換一張) and the shared-image caption (換一張, a link). The
 * input's `accept` is only a hint to the file dialog; the upload still refuses a photo on a video slot. */
function UploadAction({ slot, busy, onPick, label, variant = "outline", className }: {
  slot: Slot; busy: boolean; onPick: (file: File) => void; label?: string; variant?: "outline" | "link"; className?: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  const video = isVideoSlot(slot);
  const text = label ?? (video ? "上傳影片" : "上傳");
  return (
    <>
      <input ref={input} type="file" accept={video ? "video/*" : "image/*,video/*"} className="hidden" aria-label={`選擇「${slot.name}」的檔案`}
        onChange={(e) => { const file = e.target.files?.[0]; e.target.value = ""; if (file) onPick(file); }} />
      <Button variant={variant} size={variant === "link" ? "xs" : "sm"} className={className} disabled={busy} aria-label={`${text}：${slot.name}`} onClick={() => input.current?.click()}>
        {busy ? "上傳中…" : text}
      </Button>
    </>
  );
}

/** The image half of a video-format slot: the dashed placeholder sentence over 上傳影片 (never the photo button). */
function VideoPlaceholder({ slot, busy, onPick }: { slot: Slot; busy: boolean; onPick: (file: File) => void }) {
  return (
    <div className="flex flex-col items-center gap-1.5" data-slot="slot-video">
      <b className="text-xs font-semibold text-accent-foreground">{VIDEO_NEEDED}</b>
      {slot.ad_id !== null && <UploadAction slot={slot} busy={busy} onPick={onPick} />}
    </div>
  );
}

export function MissingSlot({ slot, workbenchHref, busy, onPick }: {
  slot: Slot; workbenchHref: string; busy: boolean; onPick: (file: File) => void;
}) {
  // Only a planned ad takes an upload (an imported campaign's slots are platform ads, always ready).
  const canUpload = slot.ad_id !== null;
  const to = slot.workbench_href ?? workbenchHref;
  // F49 Contract T: the tile names its ad (like every other tile) over the served chip and sentence; a video-format
  // slot says what it needs instead of the sentence.
  const status = <>
    <StateChip slot={slot} />
    {isVideoSlot(slot)
      ? <p className="text-[11.5px] font-semibold leading-[1.45] text-accent-foreground">{VIDEO_NEEDED}</p>
      : <StateLine slot={slot} />}
  </>;
  return (
    <SlotTile variant="missing" title={slot.name} status={status} actions={<>
      {canUpload && <UploadAction slot={slot} busy={busy} onPick={onPick} />}
      <Button variant="link" size="xs" asChild><Link to={to}>從素材工作檯</Link></Button>
    </>} />
  );
}

/** The ad's selected workbench copy is known; the image half waits for the upload (which carries the copy in). */
export function CopyOnlySlot({ slot, workbenchHref, busy, onPick }: {
  slot: Slot; workbenchHref: string; busy: boolean; onPick: (file: File) => void;
}) {
  // `copy_only` always carries its copy (Contract T); a row without one is drawn as missing rather than blank.
  if (!slot.copy) return <MissingSlot slot={slot} workbenchHref={workbenchHref} busy={busy} onPick={onPick} />;
  const video = isVideoSlot(slot);
  return (
    <SlotTile variant="copy-only" name={slot.name} copy={copyText(slot.copy)} offer={offerChip(slot)}
      imageActions={video ? <VideoPlaceholder slot={slot} busy={busy} onPick={onPick} /> : <UploadAction slot={slot} busy={busy} onPick={onPick} />}
      extra={slot.workbench_href || slot.statutory ? <>
        {slot.statutory && <StatutoryLine statutory={slot.statutory} />}
        {slot.workbench_href && <Button variant="link" size="xs" asChild><Link to={slot.workbench_href}>看圖片提示詞</Link></Button>}
      </> : undefined}
      status={<><StateChip slot={slot} /><StateLine slot={slot} /></>} />
  );
}

/** A file is in the slot but its placement has no copy: the picker fills the other half. */
export function ImageOnlySlot({ slot, onPickCopy }: { slot: Slot; onPickCopy: () => void }) {
  const thumb = useShownThumbnail(slot.thumbnail_url);
  return (
    <SlotTile variant="image-only" name={slot.name} thumbnailUrl={thumb} offer={offerChip(slot)}
      copyActions={<Button variant="link" size="xs" aria-label={`選一版文案：${slot.name}`} onClick={onPickCopy}>選一版文案</Button>}
      status={<><StateChip slot={slot} /><StateLine slot={slot} /></>} />
  );
}

/** The picker on an image-only slot: one button per workbench copy version; choosing writes it into the slot's
 * pending placement, confirms and assigns it (`chooseSlotCopy`). A 409 (`slot_no_file`) stays inside the dialog.
 * On a blocked slot without a workbench set (F44, 換一版文案) it is the same picker under the prototype's words: the
 * chosen version replaces the refused copy and the confirmation runs again — the slot comes back ready or blocked.
 * F49 Contract T: on a ready slot whose launch is not approved yet (換文案) the chosen version revises the confirmed
 * material and the confirmation runs again; a refusal (the launch was approved meanwhile) goes to `onRefused` — the
 * server's sentence beside the tile — instead of staying in the dialog. */
export function CopyPicker({ brandId, campaignId, slot, onClose, onChosen, onRefused }: {
  brandId: string; campaignId: string; slot: Slot; onClose: () => void; onChosen: (slots: CampaignSlots) => void;
  onRefused?: (message: string) => void;
}) {
  const read = useApiRead((signal) => getSlotCopyOptions(brandId, campaignId, signal), [brandId, campaignId]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const swap = slot.state === "blocked" || slot.state === "ready";
  const terms = slot.blocked?.terms ?? [];
  async function choose(option: SlotCopyOption) {
    if (!slot.ad_id || busy) return;
    setBusy(option.version_id);
    setError(null);
    try {
      const result = await chooseSlotCopy(brandId, campaignId, slot.ad_id, { set_id: option.set_id, version_id: option.version_id });
      onChosen(result.slots);
    } catch (err) {
      const message = err instanceof Error ? err.message : "文案沒有放進去，請再試一次。";
      if (onRefused) onRefused(message);
      else setError(message);
    } finally {
      setBusy(null);
    }
  }
  return (
    <Dialog open onOpenChange={(open) => { if (!open && !busy) onClose(); }}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-[560px]">
        <DialogTitle className="text-[17px] [overflow-wrap:anywhere]">{swap ? `「${slot.name}」換一版文案` : `選一版文案放進「${slot.name}」`}</DialogTitle>
        <DialogDescription>
          {!swap
            ? "工作檯已核准的文案版本。放進去後這一格就備妥；之後想改，到工作檯再產一版。"
            : slot.state === "ready"
              ? "選另一版文案換上去，這一格會馬上再檢查一次；上架清單核准前都還能換。"
              : terms.length > 0
                ? `選一版沒有寫「${terms.join("、")}」的文案，這一格會馬上再檢查一次。`
                : "選另一版文案，這一格會馬上再檢查一次。"}
        </DialogDescription>
        {read.status === "error"
          ? <ReadFailed what={`文案版本讀不到：${read.error}`} onRetry={read.reload} />
          : !read.data
            ? <Skeleton className="h-24 w-full" />
            : read.data.options.length === 0
              ? <p className="text-sm text-muted-foreground">工作檯還沒有文案版本；先到工作檯做一版。</p>
              : (
                <div className="flex flex-col gap-2" role="list" aria-label="文案版本">
                  {read.data.options.map((o, i) => (
                    <Button key={`${o.set_id}:${o.version_id}`} variant="outline" role="listitem" autoFocus={i === 0}
                      disabled={busy !== null} onClick={() => void choose(o)}
                      className="h-auto flex-col items-start gap-0.5 whitespace-normal px-3 py-2.5 text-left font-normal">
                      <span className="text-[11.5px] text-muted-foreground">{o.label}</span>
                      <span className="text-[13px] [overflow-wrap:anywhere]">
                        {o.copy_fields.headline && <b>{o.copy_fields.headline}</b>}{o.copy_fields.headline && o.copy_fields.body ? "　" : ""}{o.copy_fields.body}
                      </span>
                    </Button>
                  ))}
                </div>
              )}
        {error && <p role="alert" className="text-sm text-danger">沒有放進去：{error}</p>}
        <div className="flex justify-end">
          <Button variant="ghost" disabled={busy !== null} onClick={onClose}>取消</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** The copy fields the editor shows: one per non-empty field of the slot's copy, in 標題／內文／說明 order; a slot
 * with no copy at all gets the body alone. */
const COPY_FIELDS: { key: "headline" | "body" | "description"; label: string }[] = [
  { key: "headline", label: "標題" }, { key: "body", label: "內文" }, { key: "description", label: "說明" },
];
function editedFields(copy: SlotCopy | null): typeof COPY_FIELDS {
  const shown = COPY_FIELDS.filter((f) => !!copy?.[f.key]?.trim());
  return shown.length > 0 ? shown : COPY_FIELDS.filter((f) => f.key === "body");
}

/** F45 (prototype `dialog()` edit): the slot's copy edited in place — one labelled field per non-empty copy field
 * (only 內文 → the single textarea), 「保存後馬上檢查」; 保存 sends the fields (`editSlotCopy`), the confirmation runs at
 * once and the returned slots replace the grid. An empty field is refused here, before any request. */
export function CopyEditor({ brandId, campaignId, slot, onClose, onSaved }: {
  brandId: string; campaignId: string; slot: Slot; onClose: () => void; onSaved: (slots: CampaignSlots) => void;
}) {
  const fields = editedFields(slot.copy);
  const [values, setValues] = useState<CopyFields>(() => Object.fromEntries(fields.map((f) => [f.key, slot.copy?.[f.key] ?? ""])));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const single = fields.length === 1;
  async function save() {
    if (!slot.ad_id || saving) return;
    const sent: CopyFields = Object.fromEntries(fields.map((f) => [f.key, (values[f.key] ?? "").trim()]));
    const empty = fields.find((f) => !sent[f.key]);
    if (empty) { setError(single ? "文案不能是空的" : `${empty.label}不能是空的`); return; }
    setSaving(true);
    setError(null);
    try {
      const result = await editSlotCopy(brandId, campaignId, slot.ad_id, sent);
      onSaved(result.slots);
    } catch (err) {
      setError(err instanceof Error ? err.message : "文案沒有保存，請再試一次。");
      setSaving(false);
    }
  }
  return (
    <Dialog open onOpenChange={(open) => { if (!open && !saving) onClose(); }}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-[540px]">
        <DialogTitle className="text-[15px] [overflow-wrap:anywhere]">改「{slot.name}」的文案</DialogTitle>
        <DialogDescription className="sr-only">保存後馬上檢查這一格</DialogDescription>
        <div className="flex flex-col gap-3">
          {fields.map((f, i) => (
            <label key={f.key} className="flex flex-col gap-1">
              {!single && <span className="text-xs font-medium text-muted-foreground">{f.label}</span>}
              <Textarea aria-label={single ? "文案" : f.label} autoFocus={i === 0} disabled={saving} value={values[f.key] ?? ""}
                className="min-h-24 resize-y" aria-invalid={!!error && !(values[f.key] ?? "").trim()}
                onChange={(e) => { const v = e.target.value; setValues((prev) => ({ ...prev, [f.key]: v })); }} />
            </label>
          ))}
        </div>
        {error && <p role="alert" className="text-sm text-danger">{error}</p>}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-[11.5px] text-muted-foreground">保存後馬上檢查</span>
          <div className="flex gap-2">
            <Button variant="ghost" disabled={saving} onClick={onClose}>取消</Button>
            <Button disabled={saving} onClick={() => void save()}>{saving ? "檢查中…" : "保存"}</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
