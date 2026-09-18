import { NativeCreativeView } from "./NativeCreativeView";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/layout/ui/button";
import { externalView, syncCampaign, syncJob, type ExternalView } from "@/lib/adsExternalApi";
import { patchCampaign, type CampaignDetail } from "@/lib/adsApi";

function ExternalPanel({ brandId, campaign, onCampaignChange }: { brandId: string; campaign: CampaignDetail; onCampaignChange: (c: CampaignDetail) => void }) {
  const [view, setView] = useState<ExternalView | null>(null);
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const [goal, setGoal] = useState(campaign.goal_text || "");
  const [jobId, setJobId] = useState<string | null>(null);
  const request = useRef<AbortController | null>(null);
  const lifetime = useRef(new AbortController());
  useEffect(() => { lifetime.current = new AbortController(); return () => lifetime.current.abort(); }, []);
  async function load(kind?: "entity" | "observation") {
    request.current?.abort(); const controller = new AbortController(); request.current = controller;
    setBusy(true); setError("");
    try {
      const next = await externalView(brandId, campaign.id, kind ? { [`${kind}_cursor`]: (kind === "entity" ? view?.next_entity_cursor : view?.next_observation_cursor) ?? undefined } : {}, controller.signal);
      if (!controller.signal.aborted) setView(prev => !prev || !kind ? next : kind === "entity"
        ? { ...prev, entities: [...prev.entities, ...next.entities], next_entity_cursor: next.next_entity_cursor }
        : { ...prev, observations: [...prev.observations, ...next.observations], next_observation_cursor: next.next_observation_cursor });
    } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "讀取失敗。"); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  useEffect(() => { void load(); return () => request.current?.abort(); }, [brandId, campaign.id]);
  useEffect(() => {
    if (!jobId) return;
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try { const result = await syncJob(brandId, jobId!, controller.signal);
        if (controller.signal.aborted) return;
        if (["pending", "running"].includes(result.job.status)) timer = setTimeout(() => void poll(), 3000);
        else { setJobId(null); await load(); }
      } catch (e) { if (!controller.signal.aborted) { setError(String(e)); setJobId(null); } }
    }
    timer = setTimeout(() => void poll(), 2000); return () => { controller.abort(); clearTimeout(timer); };
  }, [jobId, brandId]);
  async function sync() { const signal = lifetime.current.signal; setError(""); try { const result = await syncCampaign(brandId, campaign.id); if (!signal.aborted) setJobId(result.job.id); } catch (e) { if (!signal.aborted) setError(String(e)); } }
  async function saveGoal() { const signal = lifetime.current.signal; setBusy(true); try { const result = await patchCampaign(brandId, campaign.id, { goal_text: goal, objective: goal }); if (!signal.aborted) onCampaignChange(result); } catch (e) { if (!signal.aborted) setError(String(e)); } finally { if (!signal.aborted) setBusy(false); } }
  return <section className="surface"><div className="surface-header"><h2>既有平台活動</h2><Button variant="outline" disabled={busy || !!jobId} onClick={() => void sync()}>{jobId ? "同步中…" : "重新讀取平台"}</Button></div>
    <div className="surface-body flex flex-col gap-4">
      <p className="text-sm">{campaign.capabilities?.unavailable.strategy ?? "此處保留平台原始資料；內部安排不會改動平台設定。"}</p>
      <div><label className="block text-sm" htmlFor="imported-goal">內部活動目標（待補也能查看資料）</label><div className="flex gap-2"><input id="imported-goal" className="min-w-0 flex-1 rounded border border-border p-2" value={goal} onChange={e => setGoal(e.target.value)} /><Button disabled={busy || !goal.trim()} onClick={() => void saveGoal()}>儲存目標</Button></div></div>
      {busy && <p role="status">讀取中…</p>}{error && <p role="alert" className="text-destructive">{error} <Button variant="outline" onClick={() => void load()}>重試</Button></p>}
      {view?.connections.map(c => <p key={`${c.platform}:${c.source_account}`} className="text-sm">來源 {c.platform} · 帳號 {c.source_account} · {c.state === "connected" ? "已連線" : "連線已中斷，保留歷史"}</p>)}
      {view && <p className="text-sm">最近成功：{[...Object.values(view.sync).map(state => state.last_success_at), ...view.entities.map(e => e.last_success_at)].filter(Boolean).sort().at(-1) ?? "尚未成功讀回"}。原始花費依層級、幣別與歸因方式分開；缺漏不補零。</p>}
      {view && Object.entries(view.sync).map(([section, state]) => <div key={section} className="rounded bg-muted p-2 text-sm"><p>{({ structure: "原生結構", creatives: "素材資料", observations: "成效資料" } as Record<string, string>)[section] ?? section}：{state.status ?? "狀態未知"} · 最近成功 {state.last_success_at ?? "尚未成功"}</p>{(state.error || state.error_code) && <p className="text-warning">{state.error ?? state.error_code}</p>}<p>資料涵蓋範圍：{view.coverage[section] == null ? "未知／尚未完整" : JSON.stringify(view.coverage[section])}</p></div>)}
      <details><summary className="cursor-pointer font-medium">原生結構與預算 · 已載入 {view?.entities.length ?? 0} 筆{view?.next_entity_cursor ? "，尚有更多" : ""}</summary>
        <div className="mt-3 max-h-96 overflow-auto divide-y divide-border">{view?.entities.map(e => <div key={e.id} className="py-3 text-sm"><p className="font-medium">{e.native_label ?? "原生項目"} · {e.name ?? e.native_id} · {e.native_status ?? "平台狀態未知"}</p><p>父項目：{e.parent_native_id ?? "根節點"} · {e.start_date ?? "開始日未知"} — {e.end_date ?? "結束日未知"}</p><p>預算：{e.budget_amount === null ? "金額未知／尚未換算" : `${e.budget_amount} ${e.currency ?? "幣別未知"}`} · {e.budget_type}</p>{Object.keys(e.budget_raw ?? {}).length > 0 && <p>平台原始值（未換算）：{JSON.stringify(e.budget_raw)}</p>}{e.sync_error && <p className="text-warning">{e.sync_error}</p>}<NativeCreativeView creative={e.creative} /></div>)}</div>
        {view?.next_entity_cursor && <Button variant="outline" disabled={busy} onClick={() => void load("entity")}>載入更多結構</Button>}
      </details>
      <details><summary className="cursor-pointer font-medium">原始成效 · {view?.window.start} — {view?.window.end}</summary>
        <div className="mt-3 max-h-96 overflow-auto"><table className="w-full text-left text-sm"><thead><tr>{["日期", "原生層級／項目", "歸因", "幣別", "花費", "曝光", "點擊", "購買", "收入"].map(t => <th className="p-2" key={t}>{t}</th>)}</tr></thead><tbody>{view?.observations.map(o => <tr key={o.id} className="border-t border-border"><td className="p-2">{o.day}</td><td>{view.entities.find(e => e.id === o.entity_id)?.name ?? o.entity_id} · {o.metric_scope}</td><td>{o.attribution_key}</td><td>{o.currency ?? "未知"}</td><td>{o.spend ?? "未知"}</td><td>{o.impressions ?? "未知"}</td><td>{o.clicks ?? "未知"}</td><td>{o.purchases ?? "未知"}</td><td>{o.revenue ?? "未知"}</td></tr>)}</tbody></table></div>
        {!view?.observations.length && !busy && <p className="text-sm">尚無已讀回的成效；不代表花費為零。</p>}
        {view?.next_observation_cursor && <Button variant="outline" disabled={busy} onClick={() => void load("observation")}>載入更多成效</Button>}
      </details>
    </div></section>;
}

export function ExternalCampaignPanel(props: Parameters<typeof ExternalPanel>[0]) { return <ExternalPanel key={`${props.brandId}:${props.campaign.id}`} {...props} />; }
