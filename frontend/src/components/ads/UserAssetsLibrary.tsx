import { isRejected } from "@/lib/http";
import { useAssetDraftGuard } from "./useAssetDraftGuard";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/layout/ui/button";
import { Textarea } from "@/components/layout/ui/textarea";
import { listUserAssets, createUploadBatch, putUpload, retryUpload, getUploadBatch, retryPreview, type AssetLibrary, type AssetUpload, type CopyFields } from "@/lib/adsUserAssetsApi";
import { AuthAssetMedia } from "./AuthAssetMedia";
import { Chip } from "./patterns";

export const COPY_FIELDS = [{ key: "headline", label: "標題" }, { key: "body", label: "內文" }, { key: "description", label: "說明" }] as const;
export function CopyEditor({ value, onChange, prefix, disabled = false }: { value: CopyFields; onChange: (copy: CopyFields) => void; prefix: string; disabled?: boolean }) {
  return <div className="grid gap-3 lg:grid-cols-3">{COPY_FIELDS.map(f => <label key={f.key} className="text-sm">{f.label}<Textarea aria-label={`${prefix}${f.label}`} maxLength={4000} disabled={disabled} value={value[f.key] ?? ""} onChange={e => onChange({ ...value, [f.key]: e.target.value })} /></label>)}</div>;
}
/** F36 ruling D: one 「本批共用原文」 per batch; a file carries its own `copy` only after 「這張另外寫」 (`own`). */
interface LocalFile { key: string; file: File; copy: CopyFields; own?: boolean; error?: string }
export function uploadChunks<T extends { file: File; copy: CopyFields }>(items: T[]): T[][] {
  const chunks: T[][] = []; let current: T[] = [];
  const size = (rows: T[]) => new TextEncoder().encode(JSON.stringify({ files: rows.map(v => ({ filename: v.file.name, size: v.file.size, content_type: v.file.type, copy_fields: v.copy })) })).length;
  for (const item of items) {
    if (current.length && (current.length >= 10 || size([...current, item]) > 60 * 1024)) { chunks.push(current); current = []; }
    current.push(item);
  }
  if (current.length) chunks.push(current);
  return chunks;
}
const emptyLibrary: AssetLibrary = { assets: [], uploads: [], next_cursor: null, next_upload_cursor: null };
function mergeRows<T extends { id: string }>(old: T[], next: T[]): T[] { return [...new Map([...old, ...next].map(r => [r.id, r])).values()]; }
export async function twoAtATime<T>(items: T[], run: (item: T) => Promise<void>) {
  let index = 0;
  await Promise.all([0, 1].map(async () => { while (index < items.length) await run(items[index++]); }));
}
function Library({ brandId, onSelection, onBusy, onAttach, onAttachAsset, readOnly = false }: {
  brandId: string; onSelection?: (uploads: AssetUpload[]) => void; onBusy?: (busy: boolean) => void;
  onAttach?: (upload: AssetUpload) => Promise<void>; onAttachAsset?: (id: string) => Promise<void>; readOnly?: boolean;
}) {
  const [library, setLibrary] = useState<AssetLibrary>(emptyLibrary);
  const [local, setLocal] = useState<LocalFile[]>([]); const [shared, setShared] = useState<CopyFields>({}); const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false); const [loading, setLoading] = useState(false); const [error, setError] = useState("");
  useAssetDraftGuard(local.length > 0);
  const [stages, setStages] = useState<Record<string, string>>({});
  const files = useRef(new Map<string, File>()); const controller = useRef(new AbortController());
  const selectionCallback = useRef(onSelection); selectionCallback.current = onSelection;
  const busyCallback = useRef(onBusy); busyCallback.current = onBusy;
  useEffect(() => { selectionCallback.current?.(library.uploads.filter(u => selected.has(u.id))); }, [library.uploads, selected]);
  useEffect(() => { busyCallback.current?.(busy || local.length > 0); }, [busy, local.length]);
  useEffect(() => { controller.current = new AbortController(); return () => controller.current.abort(); }, [brandId]);
  const load = useCallback(async (cursor?: string | null, uploadCursor?: string | null, kind?: "assets" | "uploads") => {
    const signal = controller.current.signal;
    setLoading(true); setError("");
    try {
      const next = await listUserAssets(brandId, cursor, uploadCursor, signal);
      if (!signal.aborted) setLibrary(prev => !kind ? { ...next, assets: mergeRows(prev.assets, next.assets), uploads: mergeRows(prev.uploads, next.uploads) } : kind === "assets" ? { ...prev, assets: mergeRows(prev.assets, next.assets), next_cursor: next.next_cursor } : { ...prev, uploads: mergeRows(prev.uploads, next.uploads), next_upload_cursor: next.next_upload_cursor });
    } catch (e) { if (!signal.aborted) setError(e instanceof Error ? e.message : "讀取品牌素材失敗。"); }
    finally { if (!signal.aborted) setLoading(false); }
  }, [brandId]);
  useEffect(() => { void load(); }, [load]);
  function updateUpload(upload: AssetUpload) { setLibrary(prev => ({ ...prev, uploads: mergeRows(prev.uploads, [upload]) })); }
  function stage(id: string, text: string) { setStages(prev => ({ ...prev, [id]: text })); }
  async function send(upload: AssetUpload, file: File, signal: AbortSignal) {
    if (signal.aborted) return;
    if (file.size > 50 * 1024 * 1024 || !file.size) { stage(upload.id, "檔案必須介於 1 byte 與 50 MiB，請重新選檔。"); return; }
    stage(upload.id, "上傳原檔中…");
    try { const result = await putUpload(brandId, upload.id, file, signal); if (signal.aborted) return; updateUpload(result.upload); stage(upload.id, result.upload.status === "complete" ? "原檔已保存，預覽另行處理" : result.upload.error ?? "待處理"); }
    catch (e) { if (!signal.aborted) stage(upload.id, e instanceof Error ? e.message : "上傳失敗，可重試。"); }
  }
  async function start() {
    if (busy || !local.length) return;
    const signal = controller.current.signal;
    setBusy(true); setError(""); const accepted = new Set<string>(); const queue: { upload: AssetUpload; file: File }[] = [];
    try {
      // Files without their own copy send the shared copy as their `copy_fields`; the batch API stays per file.
      for (const chunk of uploadChunks(local.map(v => v.own ? v : { ...v, copy: shared }))) {
        if (signal.aborted) break;
        try {
          const { batch } = await createUploadBatch(brandId, chunk.map(v => ({ filename: v.file.name, size: v.file.size, content_type: v.file.type, copy_fields: v.copy })));
          if (signal.aborted) return;
          batch.uploads.forEach((upload, index) => { accepted.add(chunk[index].key); files.current.set(upload.id, chunk[index].file); updateUpload(upload); queue.push({ upload, file: chunk[index].file }); });
          setSelected(prev => new Set([...prev, ...batch.uploads.map(u => u.id)]));
        } catch (e) { if (signal.aborted) return; setError(`部分批次尚未建立，選檔與原文保留：${e instanceof Error ? e.message : String(e)}`); }
      }
      const remaining = local.filter(v => !accepted.has(v.key)); setLocal(remaining); if (!remaining.length) setShared({});
      await twoAtATime(queue, async ({ upload, file }) => { if (upload.status !== "failed") await send(upload, file, signal); });
      if (!signal.aborted) await load();
    } finally { if (!signal.aborted) setBusy(false); }
  }
  async function retry(u: AssetUpload, replacement?: File) {
    if (busy) return;
    const signal = controller.current.signal;
    setBusy(true); setError(""); stage(u.id, "先核對伺服器保存狀態…");
    try {
      let upload: AssetUpload;
      try { upload = (await retryUpload(brandId, u.id)).upload; }
      catch (e) {
        // Only the missing-original refusal plus a fresh durable descriptor, never arbitrary 409.
        if (!isRejected(e, "asset_file_missing")) throw e;
        const { batch } = await getUploadBatch(brandId, u.batch_id, signal);
        const fresh = batch.uploads.find(row => row.id === u.id);
        if (!fresh || (fresh.status !== "complete" && (fresh.storage_key !== null && fresh.sha256 !== null))) throw e;
        upload = fresh;
      }
      if (signal.aborted) return; updateUpload(upload);
      if (upload.status === "complete") { stage(u.id, "原檔已保存，無需重傳"); await load(); return; }
      const file = replacement ?? files.current.get(u.id);
      if (!file) { stage(u.id, "原檔尚未傳完，請重新選擇同名且同大小的檔案。"); return; }
      if (file.name !== u.filename || file.size !== u.expected_size) { stage(u.id, "檔名或大小不符，請選擇原檔；新檔請另建上傳。"); return; }
      files.current.set(u.id, file); await send(upload, file, signal); if (!signal.aborted) await load();
    } catch (e) { if (!signal.aborted) stage(u.id, e instanceof Error ? e.message : "核對失敗，未重新上傳。"); }
    finally { if (!signal.aborted) setBusy(false); }
  }
  async function action(run: () => Promise<unknown>) { const signal = controller.current.signal; setBusy(true); setError(""); try { await run(); if (!signal.aborted) await load(); } catch (e) { if (!signal.aborted) setError(e instanceof Error ? e.message : String(e)); } finally { if (!signal.aborted) setBusy(false); } }
  return <section className="surface"><div className="surface-header"><h2>自帶圖片／影片</h2><Button variant="outline" disabled={busy || loading} onClick={() => void load()}>重新載入品牌素材</Button></div><div className="surface-body flex flex-col gap-4">
    <p className="text-sm text-muted-foreground">原檔與每批原文保存於品牌。每檔最多 50 MiB；超過 10 檔自動拆批，最多同時傳 2 檔。相同內容共用原檔，不覆蓋每批文案。</p>
    {!readOnly && <label className="text-sm font-medium">選擇圖片或影片<input aria-label="選擇自帶素材" type="file" multiple accept="image/*,video/*" disabled={busy} className="ml-3" onChange={e => {
      const next = Array.from(e.target.files ?? []).map(file => ({ key: crypto.randomUUID(), file, copy: {} })); setLocal(prev => [...prev, ...next]); e.target.value = "";
    }} /></label>}
    {local.length > 0 && <div className="flex flex-col gap-3"><p>待上傳 {local.length} 檔，分成 {uploadChunks(local).length} 批。</p>
      <div className="flex flex-col gap-2.5 rounded-[10px] border border-primary bg-primary/5 p-3.5"><div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="font-semibold">本批共用原文</h3><p className="text-xs text-muted-foreground">這一批 {local.length} 檔都用這份；某一張要不一樣，在它那張按「這張另外寫」。</p></div><Chip tone="accent">套在 {local.filter(f => !f.own).length} 檔</Chip></div><CopyEditor prefix="共用" value={shared} disabled={busy} onChange={setShared} /></div>
      <div className="flex max-h-[30rem] flex-col gap-2.5 overflow-auto">{local.map(item => <div key={item.key} className="flex flex-col gap-2 rounded-lg border border-border p-3"><div className="flex flex-wrap items-center justify-between gap-2"><p>{item.file.name} · {(item.file.size / 1024 / 1024).toFixed(1)} MiB</p><div className="flex flex-wrap items-center gap-2">{item.own
        ? <><Chip>自己的原文</Chip><Button variant="link" size="sm" disabled={busy} onClick={() => setLocal(v => v.map(f => f.key === item.key ? { ...f, own: false } : f))}>改回共用</Button></>
        : <><Chip tone="accent">沿用共用原文</Chip><Button variant="link" size="sm" disabled={busy} onClick={() => setLocal(v => v.map(f => f.key === item.key ? { ...f, own: true, copy: { ...shared } } : f))}>這張另外寫</Button></>}<Button variant="ghost" size="sm" disabled={busy} onClick={() => setLocal(v => v.filter(f => f.key !== item.key))}>移除</Button></div></div>{item.own && <CopyEditor prefix={`${item.file.name}原文`} value={item.copy} disabled={busy} onChange={copy => setLocal(v => v.map(f => f.key === item.key ? { ...f, copy } : f))} />}</div>)}</div>
      <div className="flex flex-wrap items-center gap-3"><Button disabled={busy} onClick={() => void start()}>保存原檔與原文</Button><span className="text-sm text-muted-foreground">{local.length} 檔各帶自己的原文送出（共用的那幾檔＝同一份）</span></div></div>}
    {loading && <p role="status">讀取品牌素材中…</p>}{busy && <p role="status">處理中，完成原檔 {library.uploads.filter(u => selected.has(u.id) && u.status === "complete").length}／{selected.size} 檔。請等待目前步驟完成。</p>}
    {error && <p role="alert" className="text-destructive">{error}</p>}
    <details open={library.uploads.length > 0}><summary className="cursor-pointer font-medium">品牌上傳紀錄 · 已載入 {library.uploads.length} 筆{library.next_upload_cursor ? "，尚有更多" : ""}</summary><div className="mt-3 max-h-96 overflow-auto divide-y divide-border">{library.uploads.map(u => <div key={u.id} className="flex flex-col gap-2 py-3">
      <div className="flex flex-wrap items-center gap-3">{onSelection && <input aria-label={`選取 ${u.filename}`} type="checkbox" checked={selected.has(u.id)} disabled={busy || readOnly} onChange={e => setSelected(prev => { const next = new Set(prev); if (e.target.checked) next.add(u.id); else next.delete(u.id); return next; })} />}<span className="font-medium">{u.filename}</span><span className="text-sm">{u.status === "complete" ? "原檔已保存" : "待處理"}</span></div>
      <p role="status" className="text-sm text-muted-foreground">{stages[u.id] ?? u.error ?? (u.status !== "complete" ? "尚未傳完；先重試核對，再選取原檔續傳。" : "預覽狀態請見品牌原檔。")}</p>
      <details><summary className="cursor-pointer text-sm">本批原文</summary>{Object.entries(u.copy_fields).map(([k, v]) => <p className="whitespace-pre-wrap text-sm" key={k}>{COPY_FIELDS.find(f => f.key === k)?.label ?? k}：{v || "待補"}</p>)}</details>
      {!readOnly && <div className="flex flex-wrap gap-2">{u.status !== "complete" && <><Button variant="outline" size="sm" disabled={busy} onClick={() => void retry(u)}>重試／核對保存</Button><label className="text-sm">重新選原檔<input aria-label={`重選 ${u.filename}`} disabled={busy} type="file" onChange={e => { const file = e.target.files?.[0]; if (file) void retry(u, file); e.target.value = ""; }} /></label></>}{onAttach && u.status === "complete" && <Button size="sm" disabled={busy} onClick={() => void action(() => onAttach(u))}>加入此活動（保留本批原文）</Button>}</div>}
    </div>)}</div>{library.next_upload_cursor && <Button variant="outline" disabled={loading || busy} onClick={() => void load(null, library.next_upload_cursor, "uploads")}>載入更多上傳紀錄</Button>}</details>
    <details><summary className="cursor-pointer font-medium">品牌原檔 · 已載入 {library.assets.length} 件{library.next_cursor ? "，尚有更多" : ""}</summary><div className="mt-3 grid max-h-[32rem] gap-3 overflow-auto lg:grid-cols-2">{library.assets.map(a => <div key={a.id} className="rounded border border-border p-3"><p className="font-medium">{a.filename}</p><p className="text-sm">{a.status === "ready" ? "預覽完成" : a.error ?? "預覽待處理，原檔可下載"}</p><AuthAssetMedia brandId={brandId} assetId={a.id} filename={a.filename} mime={a.mime_type} duration={a.duration} />{a.status !== "ready" && !readOnly && <Button variant="outline" size="sm" disabled={busy} onClick={() => void action(() => retryPreview(brandId, a.id))}>重試預覽處理</Button>}{onAttachAsset && !readOnly && <Button variant="outline" size="sm" disabled={busy} onClick={() => void action(() => onAttachAsset(a.id))}>以空白文案加入此活動</Button>}</div>)}</div>{library.next_cursor && <Button variant="outline" disabled={loading || busy} onClick={() => void load(library.next_cursor, null, "assets")}>載入更多原檔</Button>}</details>
    {!loading && !library.uploads.length && !local.length && <p className="text-sm text-muted-foreground">品牌尚無自帶素材。加入原檔後可安排文案，不必先產生圖片。</p>}
  </div></section>;
}

export function UserAssetsLibrary(props: Parameters<typeof Library>[0]) { return <Library key={props.brandId} {...props} />; }
