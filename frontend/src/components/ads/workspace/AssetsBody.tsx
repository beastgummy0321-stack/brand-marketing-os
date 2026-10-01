import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/layout/ui/dialog";
import { Skeleton } from "@/components/layout/Skeleton";
import type { CampaignDetail } from "@/lib/adsApi";
import { cancelMaterialTask, MaterialRequestError } from "@/lib/adsMaterialApi";
import {
  chooseSlotCopy, fetchSlotThumbnail, getSlotCopyOptions, getSlots, isAuthThumbnail, recheckSlot, SlotRecheckError, uploadIntoSlot,
  type CampaignSlots, type ReplaceRequest, type Slot, type SlotCopy, type SlotCopyOption,
} from "@/lib/adsSlotsApi";
import { createUploadBatch, putUpload } from "@/lib/adsUserAssetsApi";
import { internalHref } from "@/lib/internalHref";
import { useApiRead } from "@/lib/useApiRead";
import { ActionBar, Chip, ProgressSegments, ReadFailed, SlotGrid, SlotTile, Thumb, type SegmentState } from "../patterns";
import { isDraftCampaign } from "./WorkspaceHead";

/** v10 (F30-I11) the workspace's 素材 tab body (prototype `tabAssets()` / `slotsOf()`), from `GET …/slots`
 * (Contract F):
 * - 素材需求 card, only while 「換掉這一則」 requests are open: the replaced ad (thumbnail and name; a deleted ad reads
 *   as unknown, never blank), the request's own `state_label` with its date, and 取消需求 (a 409 says why inline).
 * - The main card: 「x／y 格已備妥」 over one progress segment per slot, then per ad group a `SlotGrid` of two-half
 *   tiles (F35 Contract T, 圖｜文案) — ready (已確認, or 要換掉 while a replace request is open), in progress (處理中:
 *   a file waiting for confirmation, a revised material or a workbench pack being made), copy-only (有文案，缺圖: the
 *   ad's selected workbench copy with 上傳 and 看圖片提示詞), image-only (有圖，缺文案: a file with 「選一版文案」), missing
 *   (缺 1 則: 上傳 and 從素材工作檯) and the reserved 站內出圖 seat.
 * - Draft: 「確認上架清單（n 則）」 to the publish page; the ads without ready material are not in the launch batch
 *   (F30 Unresolved 1), which the bar's hint says.
 * An upload sends no `copy_fields`: the program carries the ad's workbench copy in and the slot is ready at once
 * (the returned `placement.confirmed_at`); a file whose ad has no copy comes back `image_only` and the tile offers the
 * picker (a kit `Dialog` over `getSlotCopyOptions` → `chooseSlotCopy`); anything else still waits in 進階 for the user
 * to confirm (「去確認安排 →」). User-uploaded thumbnails sit behind the bearer token and are fetched, never linked.
 * The slots read fails on its own (`ReadFailed` + 重試); `advanced` (the folded old panels) stays usable.
 * F40-I09 (drill-7 #14 #6, prototype `#/assets`): while any slot is 處理中 the slots are re-read every 3 s (the tile says
 * 「處理中・自動更新，不用重整」 and flips to 已確認・剛處理好 by itself); a `format_key === "video"` slot asks for a video
 * (「這格要影片腳本，照片不算」, 上傳影片; a photo is refused before any upload); a thumbnail that another slot in the same
 * response shows too prints 「同一張圖，文案不同」 with 換一張 (one original may back several ads, never a warning).
 * F44-I05 (drill-9 #2, prototype `f44-blocked-slot`, Contract D): a slot whose confirmation was refused is 卡住, not
 * 處理中 for ever — the tile says why in one sentence (the offending words marked, 「另有 N 個原因」) and offers the exit
 * that fixes that reason: `fix: "copy"` → 換一版文案 (the same picker) and 到工作檯改文案 when the ad has a set;
 * `fix: "file"` → 換一張 (the slot upload); always 再檢查一次 (`recheckSlot`, whose slots replace the grid). The card
 * head counts the blocked slots, their progress segments are the danger colour and the draft bar says they are not
 * in the launch list. A blocked slot does not poll: nothing changes it by itself. Every planned slot's head carries
 * its ad's offer chip (`offer_label`). */

const POLL_MS = 3000;
const VIDEO_NEEDED = "這格要影片腳本，照片不算";
const SHARED_IMAGE = "同一張圖，文案不同";
const NO_OFFER = "無優惠";
const isVideoSlot = (slot: Slot) => slot.format_key === "video";
const flatSlots = (data: CampaignSlots) => data.groups.flatMap((g) => g.slots);

/** The ad's offer coordinate as the tile head's chip (accent unless it is 無優惠); nothing for an ad without one. */
function offerChip(slot: Slot): ReactNode {
  if (!slot.offer_label) return undefined;
  return <Chip tone={slot.offer_label === NO_OFFER ? "neutral" : "accent"}>{slot.offer_label}</Chip>;
}

/** The progress segment per slot state (prototype `.prog i.ok` / `.run` / `.bad`); every other state is still to do. */
const SEGMENT: Partial<Record<Slot["state"], SegmentState>> = { ready: "ok", in_progress: "running", blocked: "blocked" };

const CARD = "surface px-[22px] py-5";
const HEAD = "mb-3.5 flex flex-wrap items-center justify-between gap-3";
const H2 = "text-[15px] font-semibold";
const ROW = "grid grid-cols-[40px_minmax(0,1fr)_auto_auto] items-center gap-3.5 py-[11px]";

/** A timezone-carrying instant as `MM/DD`, printed in the browser's zone like the other workspace dates. */
function monthDay(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}/${pad(d.getDate())}`;
}

/** The URL an `<img>` can load: a platform URL as is; an authenticated user-asset path fetched into an object URL
 * (revoked when it changes or unmounts). `null` while loading or when the fetch fails — the neutral tile. */
function useShownThumbnail(url: string | null): string | null {
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

function RequestRow({ request, busy, error, onCancel }: {
  request: ReplaceRequest; busy: boolean; error: string | null; onCancel: () => void;
}) {
  const thumb = useShownThumbnail(request.replaces.thumbnail_url);
  const name = request.replaces.name;
  return (
    <div className="border-t border-border first:border-t-0" data-testid="replace-request">
      <div className={ROW}>
        <Thumb url={thumb} size={40} />
        <div className="min-w-0">
          <div className="text-[11.5px] text-muted-foreground">換掉這一則</div>
          {name
            ? <div className="font-medium [overflow-wrap:anywhere]">{name}</div>
            : <div className="text-muted-foreground">名稱讀不到（這則廣告可能已從平台刪除）</div>}
        </div>
        <Chip tone="accent">{request.state_label}・{monthDay(request.created_at)}</Chip>
        <Button variant="ghost" size="sm" disabled={busy} onClick={onCancel}>{busy ? "取消中…" : "取消需求"}</Button>
      </div>
      {error && <p role="alert" className="pb-2.5 pl-[54px] text-xs text-danger">沒有取消：{error}</p>}
    </div>
  );
}

function RequestsCard({ brandId, campaignId, slots, onChanged }: {
  brandId: string; campaignId: string; slots: CampaignSlots; onChanged: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  if (slots.requests.length === 0) return null;
  async function cancel(taskId: string) {
    setBusy(taskId);
    setErrors((prev) => { const next = { ...prev }; delete next[taskId]; return next; });
    try {
      await cancelMaterialTask(brandId, campaignId, taskId);
      onChanged();
    } catch (err) {
      const message = err instanceof Error ? err.message : "取消的結果沒有收到，請重新讀取確認。";
      setErrors((prev) => ({ ...prev, [taskId]: message }));
      // A 409 says why (`material_task_in_use`: an approved change set uses it; `material_unavailable`: it is gone or
      // changed) — re-read so the card shows what is true now; the reason stays under the row.
      if (err instanceof MaterialRequestError && err.status === 409) onChanged();
    } finally {
      setBusy(null);
    }
  }
  return (
    <section className={CARD} aria-label="素材需求">
      <div className={HEAD}>
        <h2 className={H2}>素材需求 {slots.requests.length} 張</h2>
        <span className="text-xs text-muted-foreground">做好後換進原本那一格</span>
      </div>
      <div className="border-t border-border">
        {slots.requests.map((r) => (
          <RequestRow key={r.task_id} request={r} busy={busy === r.task_id} error={errors[r.task_id] ?? null}
            onCancel={() => void cancel(r.task_id)} />
        ))}
      </div>
      {slots.requests_truncated && <p className="pt-2 text-xs text-muted-foreground">只列出最近 100 張需求。</p>}
    </section>
  );
}

/** The copy half's words: the version label and `headline　body` (a copy with neither shows its description). */
function copyText(copy: SlotCopy): { label: string; text: string } {
  const text = [copy.headline, copy.body].filter((t): t is string => !!t && t.trim() !== "").join("　");
  return { label: copy.label, text: text || copy.description || "" };
}

/** A ready or in-progress slot. `shared`: another slot in the same response shows the same thumbnail (one original
 * backing several ads) — the caption and 換一張 (a new upload into this ad's slot). `justDone`: this slot was 處理中 in an
 * earlier read of the same screen and the poll flipped it (「已確認・剛處理好」). */
function ReadySlot({ slot, shared, justDone, busy, onPick }: {
  slot: Slot; shared: boolean; justDone: boolean; busy: boolean; onPick: (file: File) => void;
}) {
  const thumb = useShownThumbnail(slot.thumbnail_url);
  const inProgress = slot.state === "in_progress";
  const chip = inProgress
    ? <Chip tone="accent"><Spinner />處理中</Chip>
    : slot.replace_task_id ? <Chip tone="warn">要換掉</Chip> : <Chip tone="ok">{justDone ? "已確認・剛處理好" : "已確認"}</Chip>;
  const status = (
    <div className="flex flex-col items-start gap-1">
      {shared && !inProgress && (
        <span className="flex flex-wrap items-center gap-x-1.5 text-[11px] text-muted-foreground" data-slot="slot-shared">
          {SHARED_IMAGE}
          {slot.ad_id !== null && <UploadAction slot={slot} busy={busy} onPick={onPick} label="換一張" variant="link" />}
        </span>
      )}
      {chip}
      {inProgress && <span className="text-[11px] text-muted-foreground" data-slot="slot-polling">處理中・自動更新，不用重整</span>}
    </div>
  );
  return <SlotTile variant="ready" name={slot.name} thumbnailUrl={thumb} copy={slot.copy && copyText(slot.copy)} offer={offerChip(slot)} status={status} />;
}

/** What the last 再檢查一次 of a slot said: still blocked (`line`), or the call failed (`error`). */
type Checked = { adId: string; line: string; error: boolean };

/** F44: a slot whose confirmation was refused, or whose file failed. The tile says why and offers the exit that fixes
 * that reason — another copy version (the picker; the ad's workbench set when it has one) or another file — and
 * 再檢查一次 for a reason that was fixed somewhere else. A `blocked` state without its reason reads as unknown. */
function BlockedSlot({ slot, uploading, checking, checked, onPick, onPickCopy, onRecheck }: {
  slot: Slot; uploading: boolean; checking: boolean; checked: Checked | null;
  onPick: (file: File) => void; onPickCopy: () => void; onRecheck: () => void;
}) {
  const thumb = useShownThumbnail(slot.thumbnail_url);
  const blocked = slot.blocked ?? { text: "卡住的原因讀不到。", terms: [], fix: null, more: 0 };
  return (
    <SlotTile variant="blocked" name={slot.name} thumbnailUrl={thumb} copy={slot.copy && copyText(slot.copy)} offer={offerChip(slot)}
      status={<Chip tone="bad">卡住</Chip>} reason={{ text: blocked.text, terms: blocked.terms, more: blocked.more }}
      actions={slot.ad_id !== null && <>
        {blocked.fix === "copy" && <Button variant="outline" size="sm" aria-label={`換一版文案：${slot.name}`} onClick={onPickCopy}>換一版文案</Button>}
        {blocked.fix === "copy" && slot.workbench_href && (
          <Button variant="link" size="xs" className="h-auto px-0" asChild><Link to={internalHref(slot.workbench_href)}>到工作檯改文案 →</Link></Button>
        )}
        {blocked.fix === "file" && <UploadAction slot={slot} busy={uploading} onPick={onPick} label="換一張" />}
        <Button variant="link" size="xs" className="h-auto px-0" disabled={checking} aria-label={`${checking ? "檢查中…" : "再檢查一次"}：${slot.name}`} onClick={onRecheck}>
          {checking ? "檢查中…" : "再檢查一次"}
        </Button>
      </>}
      note={checked && (checked.error
        ? <p role="alert" className="text-xs text-danger">沒有檢查成功：{checked.line}</p>
        : <p role="status" className="text-xs text-muted-foreground">{checked.line}</p>)} />
  );
}

/** The small spinner inside the 處理中 chip (the prototype's `.spin`). */
function Spinner() {
  return <span aria-hidden="true" className="inline-block size-3 shrink-0 animate-spin rounded-full border-[1.5px] border-chart-soft border-t-primary" />;
}

/** The hidden file input and its button, shared by the missing tile, the copy-only tile's image half, the video
 * placeholder (上傳影片, `accept="video/*"`) and the shared-image caption (換一張, a link). The input's `accept` is
 * only a hint to the file dialog; `upload()` still refuses a photo on a video slot. */
function UploadAction({ slot, busy, onPick, label, variant = "outline" }: {
  slot: Slot; busy: boolean; onPick: (file: File) => void; label?: string; variant?: "outline" | "link";
}) {
  const input = useRef<HTMLInputElement>(null);
  const video = isVideoSlot(slot);
  const text = label ?? (video ? "上傳影片" : "上傳");
  return (
    <>
      <input ref={input} type="file" accept={video ? "video/*" : "image/*,video/*"} className="hidden" aria-label={`選擇「${slot.name}」的檔案`}
        onChange={(e) => { const file = e.target.files?.[0]; e.target.value = ""; if (file) onPick(file); }} />
      <Button variant={variant} size={variant === "link" ? "xs" : "sm"} disabled={busy} aria-label={`${text}：${slot.name}`} onClick={() => input.current?.click()}>
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

function MissingSlot({ slot, workbenchHref, busy, onPick }: {
  slot: Slot; workbenchHref: string; busy: boolean; onPick: (file: File) => void;
}) {
  // Only a planned ad takes an upload (an imported campaign's slots are platform ads, always ready).
  const canUpload = slot.ad_id !== null;
  const to = internalHref(slot.workbench_href ?? workbenchHref);
  if (isVideoSlot(slot)) {
    return (
      <SlotTile variant="missing" title={VIDEO_NEEDED} status={<Chip tone="warn">缺影片</Chip>} actions={<>
        {canUpload && <UploadAction slot={slot} busy={busy} onPick={onPick} />}
        <Button variant="link" size="xs" asChild><Link to={to}>從素材工作檯</Link></Button>
      </>} />
    );
  }
  return (
    <SlotTile variant="missing" actions={<>
      {canUpload && <UploadAction slot={slot} busy={busy} onPick={onPick} />}
      <Button variant="link" size="xs" asChild><Link to={to}>從素材工作檯</Link></Button>
    </>} />
  );
}

/** The ad's selected workbench copy is known; the image half waits for the upload (which carries the copy in). */
function CopyOnlySlot({ slot, workbenchHref, busy, onPick }: {
  slot: Slot; workbenchHref: string; busy: boolean; onPick: (file: File) => void;
}) {
  // `copy_only` always carries its copy (Contract T); a row without one is drawn as missing rather than blank.
  if (!slot.copy) return <MissingSlot slot={slot} workbenchHref={workbenchHref} busy={busy} onPick={onPick} />;
  const video = isVideoSlot(slot);
  return (
    <SlotTile variant="copy-only" name={slot.name} copy={copyText(slot.copy)} offer={offerChip(slot)}
      imageActions={video ? <VideoPlaceholder slot={slot} busy={busy} onPick={onPick} /> : <UploadAction slot={slot} busy={busy} onPick={onPick} />}
      extra={slot.workbench_href
        ? <Button variant="link" size="xs" asChild><Link to={internalHref(slot.workbench_href)}>看圖片提示詞</Link></Button>
        : undefined}
      status={<Chip tone="warn">{video ? "缺影片" : "有文案，缺圖"}</Chip>} />
  );
}

/** A file is in the slot but its placement has no copy: the picker fills the other half. */
function ImageOnlySlot({ slot, onPickCopy }: { slot: Slot; onPickCopy: () => void }) {
  const thumb = useShownThumbnail(slot.thumbnail_url);
  return (
    <SlotTile variant="image-only" name={slot.name} thumbnailUrl={thumb} offer={offerChip(slot)}
      copyActions={<Button variant="link" size="xs" aria-label={`選一版文案：${slot.name}`} onClick={onPickCopy}>選一版文案</Button>}
      status={<Chip tone="warn">有圖，缺文案</Chip>} />
  );
}

/** The picker on an image-only slot: one button per workbench copy version; choosing writes it into the slot's
 * pending placement, confirms and assigns it (`chooseSlotCopy`). A 409 (`slot_no_file`) stays inside the dialog.
 * On a blocked slot (F44, 換一版文案) it is the same picker under the prototype's words: the chosen version replaces the
 * refused copy and the confirmation runs again — the slot comes back ready or blocked for the new copy's reason. */
function CopyPicker({ brandId, campaignId, slot, onClose, onChosen }: {
  brandId: string; campaignId: string; slot: Slot; onClose: () => void; onChosen: (slots: CampaignSlots) => void;
}) {
  const read = useApiRead((signal) => getSlotCopyOptions(brandId, campaignId, signal), [brandId, campaignId]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const swap = slot.state === "blocked";
  const terms = slot.blocked?.terms ?? [];
  async function choose(option: SlotCopyOption) {
    if (!slot.ad_id || busy) return;
    setBusy(option.version_id);
    setError(null);
    try {
      const result = await chooseSlotCopy(brandId, campaignId, slot.ad_id, { set_id: option.set_id, version_id: option.version_id });
      onChosen(result.slots);
    } catch (err) {
      setError(err instanceof Error ? err.message : "文案沒有放進去，請再試一次。");
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

/** The status line under the progress bar: what the last upload or copy choice did, and the next step when one is
 * still needed (a placement that waits in 進階 for the user's confirmation). */
type Note = { name: string; error: string } | { name: string; line: string; next: boolean };

/** What the picker's choice did, from the slot the server returned: ready only when it says ready (a chosen copy can
 * still be refused, then the tile carries the reason). */
function chosenLine(before: Slot, after: Slot | undefined): string {
  const swapped = before.state === "blocked";
  if (after?.state === "ready") return swapped ? "文案換好了，這一格已確認" : "文案已放進這一格，備妥。";
  if (after?.state === "blocked") return swapped ? "文案換好了，這一格還是卡住，原因寫在格子裡。" : "文案已放進這一格，但卡住了，原因寫在格子裡。";
  return swapped ? "文案換好了，這一格還在處理中。" : "文案已放進這一格，還在處理中。";
}

export function AssetsBody({ brandId, campaign: c, refreshKey, advanced, onPlacementChanged, onOpenPlacements, onRequestsChanged }: {
  brandId: string;
  campaign: CampaignDetail;
  /** Changes when something outside this body (the folded material panels) may have changed the slots. */
  refreshKey: number;
  /** The folded old panels (「進階」), shown between the cards and the action bar. */
  advanced: ReactNode;
  /** A slot upload created or changed a placement: the folded placement list re-reads. */
  onPlacementChanged: () => void;
  /** Opens the folded placement list and scrolls to it (the next step of an unconfirmed upload). */
  onOpenPlacements: () => void;
  /** A request was cancelled (or found gone): the folded request list re-reads, and `refreshKey` re-reads the slots. */
  onRequestsChanged: () => void;
}) {
  const read = useApiRead((signal) => getSlots(brandId, c.id, signal), [brandId, c.id]);
  // A change made in the folded panels re-reads in place (the last good slots stay on screen, no skeleton flash).
  const seenKey = useRef(refreshKey);
  const reload = read.reload;
  useEffect(() => { if (seenKey.current !== refreshKey) { seenKey.current = refreshKey; reload(); } }, [refreshKey, reload]);
  // The upload's own response carries the fresh slots; it stands until the next read.
  const [fresh, setFresh] = useState<CampaignSlots | null>(null);
  useEffect(() => { setFresh(null); }, [read.data]);
  const data = fresh ?? read.data;
  const [uploading, setUploading] = useState<string | null>(null);
  const [note, setNote] = useState<Note | null>(null);
  const [picking, setPicking] = useState<Slot | null>(null);
  const [checking, setChecking] = useState<string | null>(null);
  const [checked, setChecked] = useState<Checked | null>(null);

  const packId = c.asset_readiness.pack_id ?? null;
  const workbenchHref = packId ? `/brands/${brandId}/workbench/packs/${packId}` : `/brands/${brandId}/workbench`;
  const draft = isDraftCampaign(c, null);

  const slots = data ? flatSlots(data) : [];
  const blockedCount = slots.filter((s) => s.state === "blocked").length;
  // Polling: while any slot is 處理中 (a file being confirmed, a revised material, a workbench pack being made) the
  // slots are re-read every 3 s in place; the interval goes when none is in progress or the body unmounts.
  // A blocked slot waits for the user, so it never keeps the interval alive.
  const polling = slots.some((s) => s.state === "in_progress");
  useEffect(() => {
    if (!polling) return;
    const timer = setInterval(reload, POLL_MS);
    return () => clearInterval(timer);
  }, [polling, reload]);
  // The ads that became ready on this screen (「已確認・剛處理好」): a poll flipped them from 處理中, or an exit of a
  // blocked slot (another copy, another file, a recheck) unblocked them.
  const wasInProgress = useRef<Set<string>>(new Set());
  const [justDone, setJustDone] = useState<Set<string>>(() => new Set());
  useEffect(() => {
    if (!data) return;
    const now = new Set<string>();
    const done: string[] = [];
    for (const s of flatSlots(data)) {
      if (!s.ad_id) continue;
      if (s.state === "in_progress" || s.state === "blocked") now.add(s.ad_id);
      else if (s.state === "ready" && wasInProgress.current.has(s.ad_id)) done.push(s.ad_id);
    }
    wasInProgress.current = now;
    if (done.length) setJustDone((prev) => new Set([...prev, ...done]));
  }, [data]);
  // One original backing several ads: a thumbnail that more than one slot in this response shows.
  const thumbnailCount = new Map<string, number>();
  for (const s of slots) if (s.thumbnail_url) thumbnailCount.set(s.thumbnail_url, (thumbnailCount.get(s.thumbnail_url) ?? 0) + 1);
  const isShared = (s: Slot) => !!s.thumbnail_url && (thumbnailCount.get(s.thumbnail_url) ?? 0) > 1;

  async function upload(slot: Slot, file: File) {
    if (!slot.ad_id || uploading) return;
    if (isVideoSlot(slot) && !file.type.startsWith("video/")) {
      // Refused before any byte goes up: the slot's format needs a video.
      setNote({ name: slot.name, error: VIDEO_NEEDED });
      return;
    }
    setUploading(slot.ad_id);
    setNote(null);
    setChecked(null);
    try {
      const { batch } = await createUploadBatch(brandId, [{ filename: file.name, size: file.size, content_type: file.type, copy_fields: {} }]);
      const first = batch.uploads[0];
      if (!first) throw new Error("沒有收到上傳位置，請再試一次。");
      const saved = first.status === "complete" ? first : (await putUpload(brandId, first.id, file)).upload;
      if (saved.status !== "complete") throw new Error(saved.error ?? "原檔還沒存好，請再上傳一次。");
      const result = await uploadIntoSlot(brandId, c.id, slot.ad_id, { upload_id: saved.id });
      setFresh(result.slots);
      const returned = flatSlots(result.slots).find((s) => s.ad_id === slot.ad_id);
      setNote(result.placement.confirmed_at
        ? { name: slot.name, line: `已放進「${slot.name}」這一格，文案跟著帶進去了，這一格備妥。`, next: false }
        : returned?.state === "image_only"
          ? { name: slot.name, line: `已放進「${slot.name}」這一格；還缺文案，選一版就備妥。`, next: false }
          : returned?.state === "blocked"
            // The refusal and its exit are on the tile; the folded placement list is not the next step.
            ? { name: slot.name, line: `已放進「${slot.name}」這一格，但卡住了，原因寫在格子裡。`, next: false }
            : { name: slot.name, line: `已放進「${slot.name}」這一格；${result.placement.pending_reason || "確認文案與用途後才算備妥"}。`, next: true });
      onPlacementChanged();
    } catch (err) {
      setNote({ name: slot.name, error: err instanceof Error ? err.message : "上傳沒有完成，請再試一次。" });
    } finally {
      setUploading(null);
    }
  }

  /** 再檢查一次: the confirmation runs again and the returned slots replace the grid. Still blocked says so on the
   * tile; `slot_no_file` (nothing left to check — the slot changed elsewhere) just re-reads; any other failure says
   * why on the tile. */
  async function recheck(slot: Slot) {
    const adId = slot.ad_id;
    if (!adId || checking) return;
    setChecking(adId);
    setChecked(null);
    setNote(null);
    try {
      const result = await recheckSlot(brandId, c.id, adId);
      setFresh(result.slots);
      const after = flatSlots(result.slots).find((s) => s.ad_id === adId);
      if (after?.state === "blocked") {
        const same = (after.blocked?.text ?? null) === (slot.blocked?.text ?? null);
        setChecked({ adId, line: same ? "還是卡住：原因沒有變" : "還是卡住：原因換了", error: false });
      }
      onPlacementChanged();
    } catch (err) {
      if (err instanceof SlotRecheckError && err.code === "slot_no_file") reload();
      else setChecked({ adId, line: err instanceof Error ? err.message : "請稍後再試。", error: true });
    } finally {
      setChecking(null);
    }
  }

  const ready = data?.ready ?? null;
  const total = data?.total ?? null;
  const missing = ready !== null && total !== null ? total - ready : 0;

  let main: ReactNode;
  if (read.status === "error" && !data) {
    main = <ReadFailed what={`素材格子讀不到：${read.error}　下方「進階」的素材需求與自帶素材仍可使用。`} onRetry={read.reload} />;
  } else if (!data) {
    main = <Skeleton className="h-60 w-full" />;
  } else if (data.total === 0) {
    main = (
      <section className={CARD} aria-label="素材">
        <h2 className={H2}>還沒有要放素材的格子</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {c.origin === "imported" ? "還沒讀回平台上的廣告。" : "這個活動還沒有廣告；先在投放結構加廣告。"}
        </p>
      </section>
    );
  } else {
    main = (
      <section className={CARD} aria-label="素材">
        <div className={HEAD}>
          <div className="flex flex-wrap items-center gap-2.5">
            <h2 className={H2}>{data.ready}／{data.total} 格已備妥</h2>
            {blockedCount > 0 && <Chip tone="bad">{blockedCount} 格卡住</Chip>}
          </div>
          <Button variant="outline" size="sm" asChild><Link to={workbenchHref}>到素材工作檯</Link></Button>
        </div>
        <ProgressSegments className="max-w-[520px]" label={`${data.ready}／${data.total} 格已備妥${blockedCount > 0 ? `，${blockedCount} 格卡住` : ""}`}
          segments={slots.map((s, i) => ({ key: `${s.ad_id ?? s.entity_id ?? i}`, state: SEGMENT[s.state] ?? "todo", title: s.name }))} />
        {note && ("error" in note
          ? <p role="alert" className="mt-3 text-sm text-danger">「{note.name}」沒有上傳成功：{note.error}</p>
          : <div role="status" className="mt-3 flex flex-wrap items-center gap-3 rounded-lg bg-muted px-4 py-2.5 text-sm">
              <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">{note.line}</span>
              {note.next && <Button size="sm" onClick={onOpenPlacements}>去確認安排 →</Button>}
            </div>)}
        <div className="mt-[18px] flex flex-col gap-4">
          {data.groups.map((g, gi) => {
            const groupReady = g.slots.filter((s) => s.state === "ready").length;
            return (
              <div key={g.group_id ?? `group-${gi}`}>
                <div className="mb-2.5 flex items-center gap-2">
                  <h2 className={H2}>{g.name || "未命名廣告組"}</h2>
                  <Chip>{groupReady}／{g.slots.length}</Chip>
                </div>
                <SlotGrid label={g.name || "未命名廣告組"}>
                  {g.slots.map((s, si) => {
                    const key = s.ad_id ?? s.entity_id ?? si;
                    if (s.state === "missing") {
                      return <MissingSlot key={key} slot={s} workbenchHref={workbenchHref} busy={uploading === s.ad_id} onPick={(file) => void upload(s, file)} />;
                    }
                    if (s.state === "copy_only") {
                      return <CopyOnlySlot key={key} slot={s} workbenchHref={workbenchHref} busy={uploading === s.ad_id} onPick={(file) => void upload(s, file)} />;
                    }
                    if (s.state === "image_only") return <ImageOnlySlot key={key} slot={s} onPickCopy={() => { setNote(null); setPicking(s); }} />;
                    if (s.state === "blocked") {
                      return (
                        <BlockedSlot key={key} slot={s} uploading={uploading === s.ad_id} checking={checking === s.ad_id}
                          checked={checked && checked.adId === s.ad_id ? checked : null} onPick={(file) => void upload(s, file)}
                          onPickCopy={() => { setNote(null); setChecked(null); setPicking(s); }} onRecheck={() => void recheck(s)} />
                      );
                    }
                    return (
                      <ReadySlot key={key} slot={s} shared={isShared(s)} justDone={!!s.ad_id && justDone.has(s.ad_id)}
                        busy={uploading === s.ad_id} onPick={(file) => void upload(s, file)} />
                    );
                  })}
                  <SlotTile variant="reserved" title="站內出圖" note="接上後開放" />
                </SlotGrid>
              </div>
            );
          })}
        </div>
      </section>
    );
  }

  const publishHref = `/brands/${brandId}/ads/campaigns/${c.id}/publish`;
  return (
    <div className="flex flex-col gap-4">
      {data && <RequestsCard brandId={brandId} campaignId={c.id} slots={data} onChanged={onRequestsChanged} />}
      {main}
      {picking && (
        <CopyPicker brandId={brandId} campaignId={c.id} slot={picking} onClose={() => setPicking(null)}
          onChosen={(next) => {
            setFresh(next);
            setNote({ name: picking.name, line: chosenLine(picking, flatSlots(next).find((s) => s.ad_id === picking.ad_id)), next: false });
            setPicking(null);
            onPlacementChanged();
          }} />
      )}
      {advanced}
      <ActionBar back={{ label: "總覽", to: `/brands/${brandId}/ads/campaigns/${c.id}` }}
        hint={!draft ? undefined : blockedCount > 0 ? `${blockedCount} 格卡住，處理好才會進上架清單` : missing > 0 ? `缺圖的那 ${missing} 則先不建立，不會花到錢；補上圖後再加上去` : undefined}>
        {draft && (ready === null
          ? <Button asChild><Link to={publishHref}>確認上架清單 →</Link></Button>
          : ready === 0
            ? <Button disabled>確認上架清單（0 則） →</Button>
            : <Button asChild><Link to={publishHref}>確認上架清單（{ready} 則） →</Link></Button>)}
      </ActionBar>
    </div>
  );
}
