import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/layout/ui/dialog";
import { Skeleton } from "@/components/layout/Skeleton";
import type { CampaignDetail } from "@/lib/adsApi";
import { cancelMaterialTask, MaterialRequestError } from "@/lib/adsMaterialApi";
import {
  chooseSlotCopy, fetchSlotThumbnail, getSlotCopyOptions, getSlots, isAuthThumbnail, uploadIntoSlot,
  type CampaignSlots, type ReplaceRequest, type Slot, type SlotCopy, type SlotCopyOption,
} from "@/lib/adsSlotsApi";
import { createUploadBatch, putUpload } from "@/lib/adsUserAssetsApi";
import { internalHref } from "@/lib/internalHref";
import { useApiRead } from "@/lib/useApiRead";
import { ActionBar, Chip, ProgressSegments, ReadFailed, SlotGrid, SlotTile, Thumb } from "../patterns";
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
 * The slots read fails on its own (`ReadFailed` + 重試); `advanced` (the folded old panels) stays usable. */

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

function ReadySlot({ slot }: { slot: Slot }) {
  const thumb = useShownThumbnail(slot.thumbnail_url);
  const status = slot.state === "in_progress"
    ? <Chip tone="accent">處理中</Chip>
    : slot.replace_task_id ? <Chip tone="warn">要換掉</Chip> : <Chip tone="ok">已確認</Chip>;
  return <SlotTile variant="ready" name={slot.name} thumbnailUrl={thumb} copy={slot.copy && copyText(slot.copy)} status={status} />;
}

/** The hidden file input and its 上傳 button, shared by the missing tile and the copy-only tile's image half. */
function UploadAction({ slot, busy, onPick }: { slot: Slot; busy: boolean; onPick: (file: File) => void }) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <>
      <input ref={input} type="file" accept="image/*,video/*" className="hidden" aria-label={`選擇「${slot.name}」的檔案`}
        onChange={(e) => { const file = e.target.files?.[0]; e.target.value = ""; if (file) onPick(file); }} />
      <Button variant="outline" size="sm" disabled={busy} aria-label={`上傳：${slot.name}`} onClick={() => input.current?.click()}>
        {busy ? "上傳中…" : "上傳"}
      </Button>
    </>
  );
}

function MissingSlot({ slot, workbenchHref, busy, onPick }: {
  slot: Slot; workbenchHref: string; busy: boolean; onPick: (file: File) => void;
}) {
  // Only a planned ad takes an upload (an imported campaign's slots are platform ads, always ready).
  const canUpload = slot.ad_id !== null;
  return (
    <SlotTile variant="missing" actions={<>
      {canUpload && <UploadAction slot={slot} busy={busy} onPick={onPick} />}
      <Button variant="link" size="xs" asChild><Link to={internalHref(slot.workbench_href ?? workbenchHref)}>從素材工作檯</Link></Button>
    </>} />
  );
}

/** The ad's selected workbench copy is known; the image half waits for the upload (which carries the copy in). */
function CopyOnlySlot({ slot, workbenchHref, busy, onPick }: {
  slot: Slot; workbenchHref: string; busy: boolean; onPick: (file: File) => void;
}) {
  // `copy_only` always carries its copy (Contract T); a row without one is drawn as missing rather than blank.
  if (!slot.copy) return <MissingSlot slot={slot} workbenchHref={workbenchHref} busy={busy} onPick={onPick} />;
  return (
    <SlotTile variant="copy-only" name={slot.name} copy={copyText(slot.copy)}
      imageActions={<UploadAction slot={slot} busy={busy} onPick={onPick} />}
      extra={slot.workbench_href
        ? <Button variant="link" size="xs" asChild><Link to={internalHref(slot.workbench_href)}>看圖片提示詞</Link></Button>
        : undefined}
      status={<Chip tone="warn">有文案，缺圖</Chip>} />
  );
}

/** A file is in the slot but its placement has no copy: the picker fills the other half. */
function ImageOnlySlot({ slot, onPickCopy }: { slot: Slot; onPickCopy: () => void }) {
  const thumb = useShownThumbnail(slot.thumbnail_url);
  return (
    <SlotTile variant="image-only" name={slot.name} thumbnailUrl={thumb}
      copyActions={<Button variant="link" size="xs" aria-label={`選一版文案：${slot.name}`} onClick={onPickCopy}>選一版文案</Button>}
      status={<Chip tone="warn">有圖，缺文案</Chip>} />
  );
}

/** The picker on an image-only slot: one button per workbench copy version; choosing writes it into the slot's
 * pending placement, confirms and assigns it (`chooseSlotCopy`). A 409 (`slot_no_file`) stays inside the dialog. */
function CopyPicker({ brandId, campaignId, slot, onClose, onChosen }: {
  brandId: string; campaignId: string; slot: Slot; onClose: () => void; onChosen: (slots: CampaignSlots) => void;
}) {
  const read = useApiRead((signal) => getSlotCopyOptions(brandId, campaignId, signal), [brandId, campaignId]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
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
        <DialogTitle className="text-[17px] [overflow-wrap:anywhere]">選一版文案放進「{slot.name}」</DialogTitle>
        <DialogDescription>工作檯已核准的文案版本。放進去後這一格就備妥；之後想改，到工作檯再產一版。</DialogDescription>
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

  const packId = c.asset_readiness.pack_id ?? null;
  const workbenchHref = packId ? `/brands/${brandId}/workbench/packs/${packId}` : `/brands/${brandId}/workbench`;
  const draft = isDraftCampaign(c, null);

  async function upload(slot: Slot, file: File) {
    if (!slot.ad_id || uploading) return;
    setUploading(slot.ad_id);
    setNote(null);
    try {
      const { batch } = await createUploadBatch(brandId, [{ filename: file.name, size: file.size, content_type: file.type, copy_fields: {} }]);
      const first = batch.uploads[0];
      if (!first) throw new Error("沒有收到上傳位置，請再試一次。");
      const saved = first.status === "complete" ? first : (await putUpload(brandId, first.id, file)).upload;
      if (saved.status !== "complete") throw new Error(saved.error ?? "原檔還沒存好，請再上傳一次。");
      const result = await uploadIntoSlot(brandId, c.id, slot.ad_id, { upload_id: saved.id });
      setFresh(result.slots);
      const returned = result.slots.groups.flatMap((g) => g.slots).find((s) => s.ad_id === slot.ad_id);
      setNote(result.placement.confirmed_at
        ? { name: slot.name, line: `已放進「${slot.name}」這一格，文案跟著帶進去了，這一格備妥。`, next: false }
        : returned?.state === "image_only"
          ? { name: slot.name, line: `已放進「${slot.name}」這一格；還缺文案，選一版就備妥。`, next: false }
          : { name: slot.name, line: `已放進「${slot.name}」這一格；${result.placement.pending_reason || "確認文案與用途後才算備妥"}。`, next: true });
      onPlacementChanged();
    } catch (err) {
      setNote({ name: slot.name, error: err instanceof Error ? err.message : "上傳沒有完成，請再試一次。" });
    } finally {
      setUploading(null);
    }
  }

  const slots = data?.groups.flatMap((g) => g.slots) ?? [];
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
          <h2 className={H2}>{data.ready}／{data.total} 格已備妥</h2>
          <Button variant="outline" size="sm" asChild><Link to={workbenchHref}>到素材工作檯</Link></Button>
        </div>
        <ProgressSegments className="max-w-[520px]" label={`${data.ready}／${data.total} 格已備妥`}
          segments={slots.map((s, i) => ({ key: `${s.ad_id ?? s.entity_id ?? i}`, state: s.state === "ready" ? "ok" : "todo", title: s.name }))} />
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
                    return <ReadySlot key={key} slot={s} />;
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
          onChosen={(next) => { setFresh(next); setNote({ name: picking.name, line: "文案已放進這一格，備妥。", next: false }); setPicking(null); onPlacementChanged(); }} />
      )}
      {advanced}
      <ActionBar back={{ label: "總覽", to: `/brands/${brandId}/ads/campaigns/${c.id}` }}
        hint={draft && missing > 0 ? `缺圖的那 ${missing} 則先不建立，不會花到錢；補上圖後再加上去` : undefined}>
        {draft && (ready === null
          ? <Button asChild><Link to={publishHref}>確認上架清單 →</Link></Button>
          : ready === 0
            ? <Button disabled>確認上架清單（0 則） →</Button>
            : <Button asChild><Link to={publishHref}>確認上架清單（{ready} 則） →</Link></Button>)}
      </ActionBar>
    </div>
  );
}
