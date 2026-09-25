import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { Skeleton } from "@/components/layout/Skeleton";
import type { CampaignDetail } from "@/lib/adsApi";
import { cancelMaterialTask, MaterialRequestError } from "@/lib/adsMaterialApi";
import {
  fetchSlotThumbnail, getSlots, isAuthThumbnail, uploadIntoSlot,
  type CampaignSlots, type ReplaceRequest, type Slot,
} from "@/lib/adsSlotsApi";
import { createUploadBatch, putUpload, type Placement } from "@/lib/adsUserAssetsApi";
import { useApiRead } from "@/lib/useApiRead";
import { ActionBar, Chip, ProgressSegments, ReadFailed, SlotGrid, SlotTile, Thumb } from "../patterns";
import { isDraftCampaign } from "./WorkspaceHead";

/** v10 (F30-I11) the workspace's 素材 tab body (prototype `tabAssets()` / `slotsOf()`), from `GET …/slots`
 * (Contract F):
 * - 素材需求 card, only while 「換掉這一則」 requests are open: the replaced ad (thumbnail and name; a deleted ad reads
 *   as unknown, never blank), the request's own `state_label` with its date, and 取消需求 (a 409 says why inline).
 * - The main card: 「x／y 格已備妥」 over one progress segment per slot, then per ad group a `SlotGrid` — ready
 *   (已確認, or 要換掉 while a replace request is open), in progress (a file waiting for confirmation, a revised
 *   material or a workbench pack being made), missing (上傳 and 從素材工作檯) and the reserved 站內出圖 seat.
 * - Draft: 「確認上架清單（n 則）」 to the publish page; the ads without ready material are not in the launch batch
 *   (F30 Unresolved 1), which the bar's hint says.
 * A file uploaded into a slot waits for its placement to be confirmed: the next step comes from the upload's own
 * `placement`, not from the slot. User-uploaded thumbnails sit behind the bearer token and are fetched, never linked.
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

function ReadySlot({ slot }: { slot: Slot }) {
  const thumb = useShownThumbnail(slot.thumbnail_url);
  const status = slot.state === "in_progress"
    ? <Chip tone="accent">處理中</Chip>
    : slot.replace_task_id ? <Chip tone="warn">要換掉</Chip> : <Chip tone="ok">已確認</Chip>;
  return <SlotTile variant="ready" name={slot.name} thumbnailUrl={thumb} status={status} />;
}

function MissingSlot({ slot, workbenchHref, busy, onPick }: {
  slot: Slot; workbenchHref: string; busy: boolean; onPick: (file: File) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  // Only a planned ad takes an upload (an imported campaign's slots are platform ads, always ready).
  const canUpload = slot.ad_id !== null;
  return (
    <SlotTile variant="missing" actions={<>
      {canUpload && <>
        <input ref={input} type="file" accept="image/*,video/*" className="hidden" aria-label={`選擇「${slot.name}」的檔案`}
          onChange={(e) => { const file = e.target.files?.[0]; e.target.value = ""; if (file) onPick(file); }} />
        <Button variant="outline" size="sm" disabled={busy} aria-label={`上傳：${slot.name}`} onClick={() => input.current?.click()}>
          {busy ? "上傳中…" : "上傳"}
        </Button>
      </>}
      <Button variant="link" size="xs" asChild><Link to={workbenchHref}>從素材工作檯</Link></Button>
    </>} />
  );
}

type UploadNote = { name: string; placement: Placement } | { name: string; error: string };

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
  const [note, setNote] = useState<UploadNote | null>(null);

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
      setNote({ name: slot.name, placement: result.placement });
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
              <span className="min-w-0 flex-1">
                已放進「{note.name}」這一格
                {note.placement.confirmed_at ? "，這一格已備妥。" : `；${note.placement.pending_reason || "確認文案與用途後才算備妥"}。`}
              </span>
              {!note.placement.confirmed_at && <Button size="sm" onClick={onOpenPlacements}>去確認安排 →</Button>}
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
                  {g.slots.map((s, si) => s.state === "missing"
                    ? <MissingSlot key={s.ad_id ?? s.entity_id ?? si} slot={s} workbenchHref={workbenchHref}
                        busy={uploading === s.ad_id} onPick={(file) => void upload(s, file)} />
                    : <ReadySlot key={s.ad_id ?? s.entity_id ?? si} slot={s} />)}
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
