import { ApiResponseError } from "@/lib/http";
import { useAssetDraftGuard } from "./useAssetDraftGuard";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { Textarea } from "@/components/layout/ui/textarea";
import { type CampaignDetail } from "@/lib/adsApi";
import type { NativeEntity } from "@/lib/adsExternalApi";
import { getHandoff } from "@/lib/adsHandoffApi";
import { attachUpload, attachAsset, listPlacements, listSuggestionBatches, getSuggestionBatch, suggestAssets, confirmPlacement, revisePlacement, type CopyFields, type Placement, type SuggestionBatch, type SuggestionResult } from "@/lib/adsUserAssetsApi";
import { UserAssetsLibrary, CopyEditor, COPY_FIELDS } from "./UserAssetsLibrary";
import { AssetHandoffPanel } from "./AssetHandoffPanel";
import { Chip } from "./patterns";

/** Copy slots (headline／body／description) still blank on a placement; F36 ruling F counts these, never regenerates. */
const blankCount = (p: Placement) => COPY_FIELDS.filter(f => !(p.copy_fields[f.key] ?? "").trim()).length;

/** F34 `.statute` piece (prototype f34-statutory #/assets): same markup as the workbench version list. Warn only. */
function StatuteNote({ warning }: { warning: NonNullable<Placement["statutory_warning"]> }) {
  return <div role="status" data-slot="statute-note" className="mt-2 flex w-full flex-col gap-1.5 rounded-md bg-warning/10 p-3 text-[13px] text-warning">
    <div className="flex flex-wrap items-center gap-1.5"><b className="font-semibold text-warning-strong">食安法提醒</b>{warning.terms.map(t => <span key={t.term} className="inline-flex items-center gap-1 rounded-full border border-warning/35 bg-card px-2 text-xs font-semibold text-warning-strong">{t.term}<span className="text-[11px] font-normal text-warning">{t.tier_label}</span></span>)}</div>
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1"><span>{warning.sentence}</span><a className="font-medium text-warning-strong underline underline-offset-[3px]" href={warning.href} target="_blank" rel="noreferrer">衛福部認定準則</a></div>
  </div>;
}

export function UserAssetPlacements(props: { brandId: string; campaign: CampaignDetail; onChanged?: () => void }) {
  return <Placements key={`${props.brandId}:${props.campaign.id}`} {...props} />;
}
function Placements({ brandId, campaign, onChanged }: { brandId: string; campaign: CampaignDetail; onChanged?: () => void }) {
  const [rows, setRows] = useState<Placement[]>([]); const [batches, setBatches] = useState<SuggestionBatch[]>([]);
  const [batchCursor, setBatchCursor] = useState<string | null>(null); const [batch, setBatch] = useState<SuggestionBatch | null>(null);
  const [selected, setSelected] = useState<string[]>([]); const [summary, setSummary] = useState("");
  const [applyDraft, setApplyDraft] = useState<CopyFields>({}); const [applyStatus, setApplyStatus] = useState("");
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false); const [loading, setLoading] = useState(true);
  // F49-I14 (Contract D): the 目的節點 options are the handoff read's `destinations` (the campaign's own platform objects,
  // whatever its origin); with none, its `destinations_note` says why and the picker is hidden.
  const [entities, setEntities] = useState<NativeEntity[]>([]); const [destinationsNote, setDestinationsNote] = useState<string | null>(null);
  const requestKey = useRef<{ signature: string; key: string } | null>(null); const alive = useRef(true);
  const readOnly = campaign.lifecycle?.state === "closed";
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const load = useCallback(async () => {
    const result = await listPlacements(brandId, campaign.id);
    if (alive.current) setRows([...result.placements].sort((a, b) => a.id.localeCompare(b.id)));
  }, [brandId, campaign.id]);
  async function loadBatches(cursor?: string) {
    const result = await listSuggestionBatches(brandId, campaign.id, cursor);
    if (alive.current) { setBatches(prev => cursor ? [...prev, ...result.batches] : result.batches); setBatchCursor(result.next_cursor); }
  }
  async function loadDestinations() {
    try { const v = await getHandoff(brandId, campaign.id); if (alive.current) { setEntities(v.destinations); setDestinationsNote(v.destinations.length ? null : v.destinations_note ?? null); } }
    catch (e) { if (alive.current) setDestinationsNote(`目的節點讀取失敗：${e instanceof Error ? e.message : String(e)}`); }
  }
  useEffect(() => { Promise.all([load(), loadBatches(), loadDestinations()]).catch(e => { if (alive.current) setError(String(e)); }).finally(() => { if (alive.current) setLoading(false); }); }, [load]);
  useEffect(() => {
    if (!batch || !["queued", "pending", "running"].includes(batch.status)) return;
    let cancelled = false;
    const timer = setTimeout(() => { getSuggestionBatch(brandId, campaign.id, batch.id).then(v => { if (!cancelled) { setBatch(v.batch); void loadBatches(); } }).catch(e => { if (!cancelled) setError(String(e)); }); }, 2500);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [batch, brandId, campaign.id]);
  async function generate(ids: string[]) {
    if (busy || !ids.length || ids.length > 10) return;
    setBusy(true); setError("");
    const selectedRows = rows.filter(p => p.is_current && ids.includes(p.id));
    const signature = JSON.stringify({ placements: selectedRows.map(p => [p.id, p.revision]), summary, goal: campaign.goal_text, objective: campaign.objective, target: campaign.cap.value });
    if (requestKey.current?.signature !== signature) requestKey.current = { signature, key: crypto.randomUUID() };
    try {
      const result = await suggestAssets(brandId, campaign.id, selectedRows, requestKey.current.key, summary);
      if (alive.current) { setBatch(result.batch); await loadBatches(); }
    } catch (e) { if (alive.current) setError(e instanceof Error ? e.message : String(e)); }
    finally { if (alive.current) setBusy(false); }
  }
  /** F36 ruling D: one copy → every current unconfirmed placement, one `revisePlacement` each (own revision history);
   * purpose／dates untouched; a 409 stops the loop and names the file. F47-I06 (Q6): sent as `apply_copy` — the server
   * keeps a placement's current text for every blank field and refuses three blank fields; extra keys are kept. */
  async function applyAll() {
    const targets = rows.filter(p => p.is_current && !p.confirmed_at);
    if (busy || !targets.length) return;
    setBusy(true); setError(""); setApplyStatus("");
    const copy = Object.fromEntries(COPY_FIELDS.map(f => [f.key, applyDraft[f.key] ?? ""]));
    let done = 0;
    try {
      for (const p of targets) {
        try { await revisePlacement(brandId, campaign.id, p.id, { apply_copy: copy, expected_revision: p.revision }); done++; }
        catch (e) {
          if (e instanceof ApiResponseError && e.status === 409) { setError(`${p.filename} 已有新版本，套用停在這件（已套 ${done} 件）；重新讀取安排後再套一次。`); break; }
          throw e;
        }
      }
      if (done && alive.current) setApplyStatus(`已套到 ${done} 件待處理，各存了一版；逐件檢查並確認。`);
      await load(); onChanged?.();
    } catch (e) { if (alive.current) setError(e instanceof Error ? e.message : String(e)); }
    finally { if (alive.current) setBusy(false); }
  }
  const applyBlank = COPY_FIELDS.every(f => !(applyDraft[f.key] ?? "").trim());
  const current = rows.filter(p => p.is_current); const required = current.filter(p => p.required);
  const pending = current.filter(p => !p.confirmed_at); const confirmedCount = current.length - pending.length;
  // F36 ruling F: the AI block only fills blanks — count the selected (or all) unconfirmed placements with a blank slot.
  const blankRows = (selected.length ? pending.filter(p => selected.includes(p.id)) : pending).filter(p => blankCount(p) > 0);
  const fillCount = Math.min(blankRows.length, 10);
  return <div className="flex flex-col gap-4">
    <UserAssetsLibrary brandId={brandId} readOnly={readOnly} onAttach={async upload => { await attachUpload(brandId, campaign.id, upload.id); await load(); }} onAttachAsset={async id => { await attachAsset(brandId, campaign.id, id); await load(); }} />
    <section className="surface"><div className="surface-header"><h2>自帶素材安排</h2><Button variant="outline" onClick={() => { setError(""); void Promise.all([load(), loadBatches()]).catch(e => setError(String(e))); }}>重新讀取安排</Button></div><div className="surface-body flex flex-col gap-4">
      <p className="font-medium">必用 {required.length} 件 · 已確認 {required.filter(p => p.confirmed_at).length} 件 · 待處理 {required.filter(p => !p.confirmed_at).length} 件</p><p className="text-sm text-muted-foreground">這份清單獨立於工作檯素材就位數。每件必用都須確認安排，或保留明確待處理原因；內部確認不代表平台已上架。操作順序：展開「編輯原文與內部安排」→ 填妥標題、內文、說明及用途 → 儲存新版 → 檢查並確認 → 手動交接。</p>
      {loading && <p role="status">讀取安排中…</p>}{error && <p role="alert" className="text-destructive">{error}</p>}
      {!loading && !current.length && <p>尚未加入自帶素材，請從上方品牌上傳紀錄加入此活動。</p>}
      {current.length > 0 && !readOnly && <div className="flex flex-col gap-2.5 rounded-[10px] border border-primary bg-primary/5 p-3.5"><div><h3 className="font-semibold">一份文案套到全部待處理</h3><p className="text-xs text-muted-foreground">有填的欄位會蓋掉那 {pending.length} 件的原文；已確認的 {confirmedCount} 件不動。</p></div><CopyEditor prefix="套用" value={applyDraft} disabled={busy} onChange={setApplyDraft} /><div className="flex flex-wrap items-center gap-3"><Button variant="outline" disabled={busy || !pending.length || applyBlank} disabledReason={!busy && pending.length > 0 && applyBlank ? "三欄都是空的，沒有可以套用的內容。" : undefined} onClick={() => void applyAll()}>套用到 {pending.length} 件待處理</Button><span className="text-xs text-muted-foreground">套用後每件各存一版，空白的欄位保留原文；仍要逐件「檢查並確認」</span></div>{applyStatus && <p role="status" className="text-sm">{applyStatus}</p>}</div>}
      {current.length > 0 && !readOnly && <div className="flex flex-col gap-2.5 rounded-lg border border-border p-4"><div className="flex flex-wrap items-center justify-between gap-3"><h3 className="font-semibold">補空白文案（選用）</h3><Chip>{blankRows.length ? `${blankRows.length} 件有空白欄` : "沒有空白欄"}</Chip></div><p className="text-xs text-muted-foreground">只補空白欄位、只用品牌已確認的事實或中性 CTA；已有原文不改。要換一整份新文案，到素材頁的格子按「選一版文案」。</p><div className="flex flex-wrap items-center gap-3"><Button variant="outline" disabled={busy || !fillCount} onClick={() => { const ids = blankRows.slice(0, 10).map(p => p.id); setSelected(ids); void generate(ids); }}>{busy ? "送出中…" : `為 ${fillCount} 件補空白文案`}</Button>{!fillCount && <span className="text-sm text-muted-foreground">選取的都填滿了，沒有可補的欄位。</span>}<Button variant="link" size="sm" asChild><Link to="?tab=assets">到素材頁選一版文案 →</Link></Button></div>{blankRows.length > 10 && <p className="text-xs text-muted-foreground">每批最多 10 件；其餘 {blankRows.length - 10} 件仍保留待處理。</p>}<label className="block text-sm">整批素材說明（未核實）<Textarea aria-label="整批素材說明" maxLength={2000} value={summary} onChange={e => { setSummary(e.target.value); requestKey.current = null; }} /></label></div>}
      <details><summary className="cursor-pointer font-medium">先前建議批次 · {batches.length} 筆</summary><div className="max-h-60 overflow-auto">{batches.map(b => <div key={b.id} className="flex flex-wrap items-center justify-between gap-2 border-t border-border py-2 text-sm"><span>{b.created_at} · {b.status === "succeeded" ? "已取得建議" : ["queued", "pending", "running"].includes(b.status) ? "處理中／待核對" : "未完成"}{b.error ? ` · ${b.error}` : ""}</span><Button variant="outline" size="sm" onClick={() => { void getSuggestionBatch(brandId, campaign.id, b.id).then(v => setBatch(v.batch)).catch(e => setError(String(e))); }}>查看本批</Button></div>)}</div>{batchCursor && <Button variant="outline" onClick={() => void loadBatches(batchCursor).catch(e => setError(String(e)))}>更多建議批次</Button>}</details>
      {batch && <div className="rounded bg-muted p-3 text-sm"><p>目前批次：{batch.id} · {batch.status === "succeeded" ? "建議已備妥，請逐件核對" : batch.error ?? "尚未完成，請稍後查看；可先手動編輯"}</p>{batch.stale && <p className="text-warning">資料或版本已改變，此批建議已過時，不能覆蓋現版。</p>}<p>{batch.usage_notice}</p><p>{batch.retry_notice}</p><p>本批之外仍有 {batch.remaining_count ?? "未知"} 件待處理。</p></div>}
      <div className="flex flex-col gap-3">{current.map(p => <PlacementEditor key={p.id} brandId={brandId} campaignId={campaign.id} placement={p} history={rows.filter(h => h.id === p.id && !h.is_current)} entities={entities} destinationsNote={destinationsNote} readOnly={readOnly} selected={selected.includes(p.id)} onSelect={value => { setSelected(prev => value ? [...prev, p.id] : prev.filter(id => id !== p.id)); requestKey.current = null; }} result={batch?.results?.find(r => r.id === p.id && r.revision === p.revision)} batch={batch} onReload={async () => { await load(); onChanged?.(); }} />)}</div>
    </div></section>
  </div>;
}
function PlacementEditor({ brandId, campaignId, placement: p, history, entities, destinationsNote, readOnly, selected, onSelect, result, batch, onReload }: {
  brandId: string; campaignId: string; placement: Placement; history: Placement[]; entities: NativeEntity[]; destinationsNote: string | null; readOnly: boolean;
  selected: boolean; onSelect: (value: boolean) => void; result?: SuggestionResult; batch: SuggestionBatch | null; onReload: () => Promise<void>;
}) {
  const from = (v: Placement) => ({ copy_fields: v.copy_fields, required: v.required, purpose: v.purpose ?? "", destination_entity_id: v.destination_entity_id ?? "", start_date: v.start_date ?? "", end_date: v.end_date ?? "" });
  const [draft, setDraft] = useState(() => from(p)); const [base, setBase] = useState(p.revision);
  const [baseline, setBaseline] = useState(() => JSON.stringify(from(p)));
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false); const [showHandoff, setShowHandoff] = useState<number | null>(null);
  const dirty = JSON.stringify(draft) !== baseline;
  const conflict = dirty && base !== p.revision;
  // No local edits → nothing to protect: follow the server (also after 「套用到全部待處理」 bumps the revision).
  useEffect(() => {
    if (!dirty) { const next = from(p); setDraft(next); setBaseline(JSON.stringify(next)); setBase(p.revision); }
  }, [p, dirty]);
  useAssetDraftGuard(dirty);

  async function save() {
    if (conflict || busy) return; setBusy(true); setError("");
    try {
      const { placement } = await revisePlacement(brandId, campaignId, p.id, { ...draft, expected_revision: base, destination_entity_id: draft.destination_entity_id || null, start_date: draft.start_date || null, end_date: draft.end_date || null });
      setBase(placement.revision); setDraft(from(placement)); setBaseline(JSON.stringify(from(placement))); await onReload();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); if (e instanceof ApiResponseError && e.status === 409) await onReload(); }
    finally { setBusy(false); }
  }
  async function confirm(batchId: string | null) {
    if (dirty || conflict || busy) return; setBusy(true); setError("");
    try { const { placement } = await confirmPlacement(brandId, campaignId, p, batchId); if (placement.pending_reasons?.length) setError(placement.pending_reasons.join("；")); await onReload(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); if (e instanceof ApiResponseError && e.status === 409) await onReload(); }
    finally { setBusy(false); }
  }
  return <article className="rounded-md border border-border p-4"><div className="flex flex-wrap items-center gap-3">{!readOnly && <input aria-label={`納入建議 ${p.filename}`} type="checkbox" checked={selected} onChange={e => onSelect(e.target.checked)} />}<h3 className="font-semibold">{p.filename} · 第 {p.revision} 版</h3><span className="text-sm">{p.required ? "必用" : "選用"} · {p.confirmed_at ? "已確認內部安排" : "待處理"}</span>{p.confirmed_at ? <Chip tone="ok">已確認</Chip> : blankCount(p) === 0 ? <Chip tone="accent">文案齊了</Chip> : <Chip tone="warn">缺 {blankCount(p)} 欄</Chip>}{dirty &&<span className="text-sm text-warning">有未儲存編輯</span>}</div>
    <p className="mt-2 text-sm">{p.asset_status === "ready" ? "原檔預覽完成" : p.asset_error ?? "原檔處理待完成"}{!p.confirmed_at ? ` · ${p.pending_reason || "請核對文案、用途與媒體後確認安排"}` : ""}</p>
    {p.statutory_warning && <StatuteNote warning={p.statutory_warning} />}
    {error && <p role="alert" className="mt-2 text-sm text-destructive">{error}</p>}
    {conflict && <div className="mt-2 text-sm text-warning"><p>伺服器已是第 {p.revision} 版；您的本機編輯仍保留，尚未覆蓋新版本。</p><Button variant="outline" onClick={() => { setBase(p.revision); setBaseline(JSON.stringify(from(p))); setError(""); }}>以最新版本為基礎保留我的編輯</Button><Button variant="outline" onClick={() => { setDraft(from(p)); setBase(p.revision); setBaseline(JSON.stringify(from(p))); setError(""); }}>放棄本機編輯，使用最新內容</Button></div>}
    <details className="mt-3" open={!p.confirmed_at}><summary className="cursor-pointer font-medium">編輯原文與內部安排{dirty ? "（未儲存）" : ""}</summary><div className="mt-3 flex flex-col gap-3"><CopyEditor prefix={`${p.filename}安排`} value={draft.copy_fields} disabled={readOnly || busy} onChange={copy_fields => setDraft(v => ({ ...v, copy_fields }))} /><label className="text-sm">用途<input aria-label={`${p.filename}用途`} className="ml-2 rounded border border-border p-2" disabled={readOnly || busy} value={draft.purpose} onChange={e => setDraft(v => ({ ...v, purpose: e.target.value }))} maxLength={4000} /></label><label className="text-sm"><input type="checkbox" disabled={readOnly || busy} checked={draft.required} onChange={e => setDraft(v => ({ ...v, required: e.target.checked }))} /> 此素材必用</label>{entities.length > 0
        ? <label className="text-sm">安排目的<select aria-label={`${p.filename}目的節點`} className="ml-2 rounded border border-border p-2" disabled={readOnly || busy} value={draft.destination_entity_id} onChange={e => setDraft(v => ({ ...v, destination_entity_id: e.target.value }))}><option value="">未指定（沿活動安排）</option>{draft.destination_entity_id && !entities.some(e => e.id === draft.destination_entity_id) && <option value={draft.destination_entity_id}>已保存的目的節點</option>}{entities.map(e => <option key={e.id} value={e.id}>{e.native_label ?? "原生項目"} · {e.name ?? e.native_id}</option>)}</select></label>
        : <p data-slot="destinations-note" className="text-sm text-muted-foreground">安排目的：{destinationsNote ?? "沿活動安排"}</p>}<div className="flex flex-wrap gap-3"><label className="text-sm">內部開始日<input aria-label={`${p.filename}內部開始日`} type="date" disabled={readOnly || busy} value={draft.start_date} onChange={e => setDraft(v => ({ ...v, start_date: e.target.value }))} /></label><label className="text-sm">內部結束日<input aria-label={`${p.filename}內部結束日`} type="date" disabled={readOnly || busy} value={draft.end_date} onChange={e => setDraft(v => ({ ...v, end_date: e.target.value }))} /></label></div><p className="text-xs text-muted-foreground">修改會建立新版，保留舊確認與核對紀錄；原文的其他欄位一併保留。這裡不會修改平台設定。</p>{!readOnly && <Button disabled={!dirty || busy || conflict} onClick={() => void save()}>儲存為新版安排</Button>}</div></details>
    {result && <div className="mt-3 rounded bg-muted p-3 text-sm"><h4 className="font-medium">本批補充建議（{p.confirmed_at && p.suggestion_batch_id === batch?.id ? "已採用" : "尚未採用"}）</h4><div>{Object.entries(result.suggested_copy).map(([key, value]) => <p className="whitespace-pre-wrap" key={key}>{COPY_FIELDS.find(f => f.key === key)?.label ?? key}：{value}</p>)}</div><p>用途：{result.purpose} · 目的節點：{entities.find(e => e.id === result.destination_entity_id)?.name ?? "沿活動安排"}</p>{result.pending_reasons.map(reason => <p className="text-warning" key={reason}>{reason}</p>)}{Array.isArray(result.notes) && result.notes.map((note, i) => <p key={i}>{String(note)}</p>)}</div>}
    {!readOnly && !p.confirmed_at && <div className="mt-3 flex flex-wrap gap-2"><Button variant="outline" disabled={busy || dirty || conflict} onClick={() => void confirm(null)}>只用我的文案，檢查並確認</Button>{result && batch && <Button disabled={busy || dirty || conflict || batch.stale || batch.status !== "succeeded"} onClick={() => void confirm(batch.id)}>核對後確認這件建議</Button>}</div>}
    {dirty && <p className="mt-2 text-sm">請先儲存編輯，才能以該版確認；不會自動提交。</p>}
    <div className="mt-3 flex flex-wrap gap-2">{p.confirmed_at && <Button variant="outline" onClick={() => setShowHandoff(showHandoff === p.revision ? null : p.revision)}>手動交接與平台核對</Button>}{history.filter(h => h.confirmed_at).map(h => <Button key={h.revision} variant="outline" size="sm" onClick={() => setShowHandoff(showHandoff === h.revision ? null : h.revision)}>查看第 {h.revision} 版歷史／結束對應</Button>)}</div>
    {showHandoff !== null && <AssetHandoffPanel key={showHandoff} brandId={brandId} campaignId={campaignId} placement={showHandoff === p.revision ? p : history.find(h => h.revision === showHandoff)!} entities={entities} destinationsNote={destinationsNote} readOnly={readOnly} />}
  </article>;
}
