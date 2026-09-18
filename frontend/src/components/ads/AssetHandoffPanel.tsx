import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/layout/ui/button";
import { CopyIconButton } from "@/components/layout/CopyIconButton";
import { existingCampaigns, type NativeEntity, type SourceAccount } from "@/lib/adsExternalApi";
import { assetHandoff, bindingAction, bindingCandidates, versionMetrics, type AssetHandoff, type BindingCandidate, type Placement, type VersionMetrics } from "@/lib/adsUserAssetsApi";
import { AuthAssetMedia } from "./AuthAssetMedia";
import { COPY_FIELDS } from "./UserAssetsLibrary";

function HandoffPanel({ brandId, campaignId, placement: p, readOnly, entities = [] }: { brandId: string; campaignId: string; placement: Placement; readOnly: boolean; entities?: NativeEntity[] }) {
  const [handoff, setHandoff] = useState<AssetHandoff | null>(null); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const [sources, setSources] = useState<SourceAccount[]>([]); const [sourceIndex, setSourceIndex] = useState("");
  const [candidates, setCandidates] = useState<BindingCandidate[]>([]); const [cursor, setCursor] = useState<string | null>(null);
  const [selected, setSelected] = useState(""); const [checked, setChecked] = useState(false); const [metrics, setMetrics] = useState<VersionMetrics | null>(null);
  const [start, setStart] = useState(() => new Date(Date.now() - 29 * 86400000).toISOString().slice(0, 10));
  const [end, setEnd] = useState(() => new Date().toISOString().slice(0, 10));
  const lifetime = useRef(new AbortController());
  useEffect(() => { lifetime.current = new AbortController(); return () => lifetime.current.abort(); }, []);
  async function load(signal: AbortSignal) { const result = await assetHandoff(brandId, campaignId, p); if (!signal.aborted) setHandoff(result); }
  useEffect(() => {
    let active = true;
    assetHandoff(brandId, campaignId, p).then(v => { if (active) setHandoff(v); }).catch(e => { if (active) setError(String(e)); });
    existingCampaigns(brandId).then(v => { if (active) setSources(v.sources); }).catch(e => { if (active) setError(String(e)); });
    return () => { active = false; };
  }, [brandId, campaignId, p.id, p.revision]);
  async function action(fn: () => Promise<unknown>) { const signal = lifetime.current.signal; setBusy(true); setError(""); try { await fn(); if (!signal.aborted) { await load(signal); setMetrics(null); } } catch (e) { if (!signal.aborted) setError(e instanceof Error ? e.message : String(e)); } finally { if (!signal.aborted) setBusy(false); } }
  async function candidatesPage(more = false) {
    const source = sources[Number(sourceIndex)]; if (!source || sourceIndex === "") return;
    const signal = lifetime.current.signal; setBusy(true); setError("");
    try { const result = await bindingCandidates(brandId, campaignId, p, source.platform, source.account_id, more ? cursor ?? undefined : undefined); if (signal.aborted) return; setCandidates(prev => more ? [...prev, ...result.candidates] : result.candidates); setCursor(result.next_cursor); }
    catch (e) { if (!signal.aborted) setError(e instanceof Error ? e.message : String(e)); } finally { if (!signal.aborted) setBusy(false); }
  }
  return <section className="rounded-md border border-border p-4"><h3 className="font-semibold">手動交接 · 第 {p.revision} 版</h3>
    {!handoff && !error && <p role="status">讀取交接內容…</p>}{error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {handoff && <div className="mt-3 flex flex-col gap-3"><p className="text-sm">{handoff.notice}</p><AuthAssetMedia brandId={brandId} assetId={p.asset_id} filename={p.filename} mime={p.mime_type} />
      <div className="flex items-center gap-2 text-sm">建議追蹤名稱：{handoff.tracking_name}<CopyIconButton ariaLabel="複製追蹤名稱" getText={() => handoff.tracking_name} /></div>
      {Object.entries(handoff.effective_copy).map(([key, value]) => <div className="flex items-start gap-2 border-t border-border pt-2" key={key}><span className="w-12 shrink-0 text-sm">{COPY_FIELDS.find(f => f.key === key)?.label ?? key}</span><p className="min-w-0 flex-1 whitespace-pre-wrap break-words text-sm">{value || "待補"}</p><CopyIconButton ariaLabel={`複製${key}`} getText={() => value} /></div>)}
      <p className="text-sm">用途：{handoff.purpose ?? "待補"} · 目的節點：{entities.find(e => e.id === handoff.destination_entity_id)?.name ?? (handoff.destination_entity_id ? "已保存目的節點（請載入本活動目的節點核對）" : "沿活動安排")} · {handoff.start_date ?? "開始日待核對"} — {handoff.end_date ?? "結束日待核對"}</p>
      <details><summary className="cursor-pointer text-sm">原文與補充文案分開查看</summary><p className="whitespace-pre-wrap text-sm">原文：{JSON.stringify(handoff.original_copy, null, 2)}</p><p className="whitespace-pre-wrap text-sm">補充：{JSON.stringify(handoff.suggested_copy, null, 2)}</p></details>
      <p className="text-sm font-medium">廣告存在、素材版本與成效歸屬是三件不同的事。</p>
      {!handoff.bindings.length && <p className="text-sm">尚未記錄上架，也尚未讀回平台廣告。素材版本與成效待核對。</p>}
      {handoff.bindings.map(b => <div key={b.id} className="rounded bg-muted p-3 text-sm"><p>廣告存在：{b.existence_status === "platform_confirmed" ? "平台已讀回廣告與父層關係" : b.existence_status === "self_reported" ? "使用者自行回報，尚未由平台證實" : "平台核對待完成"}</p><p>素材版本：{b.evidence_level === "media_verified" ? "已有平台素材等價證據" : b.evidence_level === "user_verified" ? "使用者已核對；平台尚未證明素材等價" : "尚未核對是否使用這一版素材"}</p><p>成效歸屬：需完整日期與連續版本證據，另行檢查。</p><p>最近讀回：{b.last_verified_at ?? "尚未成功"}{b.valid_to ? ` · 對應已於 ${b.valid_to} 結束` : ""}</p>{b.stale_reason && <p className="text-warning">{b.stale_reason}</p>}{!b.valid_to && <Button variant="outline" size="sm" disabled={busy} onClick={() => void action(() => bindingAction(brandId, campaignId, p, "end-binding", { binding_id: b.id }))}>結束這筆對應</Button>}</div>)}
      {!readOnly && p.is_current && <><Button variant="outline" disabled={busy} onClick={() => void action(() => bindingAction(brandId, campaignId, p, "self-report"))}>我已手動上架（僅自行回報）</Button>
        <div className="flex flex-wrap items-center gap-2"><label>平台帳號<select aria-label="核對平台帳號" className="ml-2 rounded border border-border p-2" value={sourceIndex} disabled={busy} onChange={e => { setSourceIndex(e.target.value); setCandidates([]); setCursor(null); setSelected(""); setChecked(false); }}><option value="">選擇綁定帳號</option>{sources.map((s, i) => <option key={`${s.platform}:${s.account_id}`} value={i}>{s.label} · {s.name ?? s.account_id}</option>)}</select></label><Button variant="outline" disabled={busy || sourceIndex === ""} onClick={() => void candidatesPage()}>載入平台候選</Button></div>
        <p className="text-xs text-muted-foreground">候選來自快取；選定後會重新讀取指定廣告、父層與活動，僅查看資料。</p>
        {sourceIndex !== "" && !candidates.length && <p className="text-sm">尚無已載入候選；請先同步本活動的原始結構，再載入候選。</p>}
        {candidates.length > 0 && <select aria-label="選擇平台廣告" className="rounded border border-border p-2" value={selected} disabled={busy} onChange={e => { setSelected(e.target.value); setChecked(false); }}><option value="">選擇廣告</option>{candidates.map(c => <option key={c.entity_id} value={c.entity_id}>{c.name ?? c.native_id} · {c.native_id}</option>)}</select>}
        {cursor && <Button variant="outline" disabled={busy} onClick={() => void candidatesPage(true)}>更多候選</Button>}
        <label className="text-sm"><input type="checkbox" checked={checked} disabled={busy} onChange={e => setChecked(e.target.checked)} /> 我已自行比對這一版原檔與文案（不當作平台素材等價證據）</label>
        <Button disabled={busy || !selected} onClick={() => void action(() => bindingAction(brandId, campaignId, p, "verify-binding", { entity_id: selected, user_verified: checked }))}>{busy ? "核對中…" : "重新讀回並核對廣告"}</Button></>}
      <details><summary className="cursor-pointer font-medium">檢查這一版的成效歸屬</summary><div className="mt-3 flex flex-wrap items-center gap-2"><label>開始日<input aria-label="版本成效開始日" type="date" value={start} onChange={e => setStart(e.target.value)} /></label><label>結束日<input aria-label="版本成效結束日" type="date" value={end} onChange={e => setEnd(e.target.value)} /></label><Button variant="outline" disabled={busy || !start || !end} onClick={() => { const signal = lifetime.current.signal; setBusy(true); setError(""); void versionMetrics(brandId, campaignId, p, start, end).then(v => { if (!signal.aborted) setMetrics(v); }).catch(e => { if (!signal.aborted) setError(String(e)); }).finally(() => { if (!signal.aborted) setBusy(false); }); }}>讀取版本成效</Button></div>
        {metrics && !metrics.observations.length && <p className="text-sm">目前沒有可讀取的原生觀測；版本成效未知。</p>}{metrics?.observations.map(o => <div className="border-t border-border py-2 text-sm" key={`${o.binding_id}:${o.id}`}><p>{o.day} · {o.currency ?? "幣別未知"} · {o.metric_scope} · {o.attribution_key}</p><p>原生花費 {o.spend ?? "未知"} · 曝光 {o.impressions ?? "未知"} · 點擊 {o.clicks ?? "未知"} · 購買 {o.purchases ?? "未知"} · 收入 {o.revenue ?? "未知"}</p><p>{o.attributed ? "此筆觀測有足夠證據歸屬本版" : `不可歸屬本版：${o.unattributed_reason ?? "證據不足"}`}</p></div>)}
      </details>
    </div>}
  </section>;
}

export function AssetHandoffPanel(props: Parameters<typeof HandoffPanel>[0]) { return <HandoffPanel key={`${props.brandId}:${props.campaignId}:${props.placement.id}:${props.placement.revision}`} {...props} />; }
