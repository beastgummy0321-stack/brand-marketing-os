import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/layout/ui/dialog";
import { existingCampaigns, importExisting, refreshExisting, syncJob, type ExistingPage } from "@/lib/adsExternalApi";

export function ExistingCampaignDialog({ brandId }: { brandId: string }) {
  const [open, setOpen] = useState(false);
  return <><Button variant="outline" onClick={() => setOpen(true)}>加入既有活動</Button>
    <Dialog open={open} onOpenChange={setOpen}><DialogContent className="max-w-3xl">
      <DialogTitle>加入既有活動</DialogTitle><DialogDescription>從品牌綁定帳號讀取；納入工作區不會改動平台設定。</DialogDescription>
      {open && <ExistingList key={brandId} brandId={brandId} />}
    </DialogContent></Dialog></>;
}
function ExistingList({ brandId }: { brandId: string }) {
  const navigate = useNavigate();
  const [page, setPage] = useState<ExistingPage | null>(null);
  const [source, setSource] = useState<{ platform?: string; source_account?: string }>({});
  const [busy, setBusy] = useState(false);
  const [mutating, setMutating] = useState(false);
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  const lifetime = useRef(new AbortController());
  useEffect(() => { lifetime.current = new AbortController(); return () => lifetime.current.abort(); }, []);
  async function load(cursor?: string) {
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    setBusy(true); setError("");
    try {
      const next = await existingCampaigns(brandId, { ...source, cursor }, controller.signal);
      if (!controller.signal.aborted) setPage(prev => ({ ...next, items: cursor ? [...(prev?.items ?? []), ...next.items] : next.items }));
    } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "讀取失敗。"); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  useEffect(() => { void load(); return () => request.current?.abort(); }, [brandId, source.platform, source.source_account]); // scoped request cancels old account pages
  useEffect(() => {
    if (!page?.job || !["pending", "running"].includes(page.job.status)) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      syncJob(brandId, page.job!.id, controller.signal).then(async ({ job }) => {
        if (controller.signal.aborted) return;
        if (!["pending", "running"].includes(job.status)) {
          const next = await existingCampaigns(brandId, { platform: page.platform, source_account: page.source_account }, controller.signal);
          if (!controller.signal.aborted) setPage(prev => !prev ? next : { ...next, items: [...new Map([...prev.items, ...next.items].map(i => [i.id, i])).values()], next_cursor: prev.next_cursor ?? next.next_cursor });
        } else setPage(prev => prev ? { ...prev, job } : prev);
      }).catch(e => { if (!controller.signal.aborted) setError(String(e)); });
    }, 3000);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [page?.job, brandId]);
  async function refresh() {
    if (!page?.platform || !page.source_account) return;
    const signal = lifetime.current.signal; setMutating(true); setError("");
    try { await refreshExisting(brandId, page.platform, page.source_account); if (!signal.aborted) await load(); }
    catch (e) { if (!signal.aborted) setError(String(e instanceof Error ? e.message : e)); }
    finally { if (!signal.aborted) setMutating(false); }
  }
  async function include(item: ExistingPage["items"][number]) {
    if (!page?.platform || !page.source_account || busy || mutating) return;
    const signal = lifetime.current.signal;
    setMutating(true); setError("");
    try {
      const result = await importExisting(brandId, { platform: page.platform, source_account: page.source_account, native_kind: item.native_kind, native_id: item.native_id });
      if (!signal.aborted) navigate(`/brands/${brandId}/ads/campaigns/${result.campaign.id}`);
    } catch (e) { if (!signal.aborted) setError(String(e instanceof Error ? e.message : e)); }
    finally { if (!signal.aborted) setMutating(false); }
  }
  return <div className="flex flex-col gap-3">
    <div className="flex items-center gap-2"><label htmlFor="existing-source">品牌綁定帳號</label>
      <select id="existing-source" disabled={mutating} className="rounded-md border border-border p-2" value={`${page?.platform ?? source.platform ?? ""}|${page?.source_account ?? source.source_account ?? ""}`} onChange={e => {
        request.current?.abort(); const [platform, source_account] = e.target.value.split("|");
        setPage(prev => prev ? { ...prev, platform, source_account, items: [], next_cursor: null, job: null } : null); setSource({ platform, source_account });
      }}>{page?.sources.map(s => <option key={`${s.platform}|${s.account_id}`} value={`${s.platform}|${s.account_id}`}>{s.label} · {s.name || s.account_id}</option>)}</select>
      <Button variant="outline" disabled={busy || mutating || !page?.sources.length} onClick={() => void refresh()}>更新清單</Button></div>
    {busy && <p role="status">讀取中…已快取的活動仍可查看。</p>}
    {error && <p role="alert" className="text-destructive">{error} <Button variant="outline" disabled={mutating} onClick={() => void load()}>重試讀取</Button></p>}
    {page?.job && <p className="text-sm text-muted-foreground">{["pending", "running"].includes(page.job.status) ? "平台資料同步中" : page.job.status === "succeeded" ? "清單已同步" : "同步有缺漏，可重試"} · 最近成功：{page.job.last_success_at ?? "尚未成功讀回"}</p>}
    {!busy && page && !page.items.length && <p>{page.sources.length ? "此帳號尚無已讀回活動；可更新清單，暫停或沒有花費的活動也會保留。" : "尚無可讀取的綁定帳號，請先至品牌連線設定核對。"}</p>}
    <div className="max-h-96 overflow-auto divide-y divide-border">{page?.items.map(item => <div key={item.id} className="flex items-center justify-between gap-3 py-3">
      <div><p className="font-medium">{item.snapshot.name || item.native_id}</p><p className="text-sm text-muted-foreground">{item.snapshot.native_status ?? "平台狀態未知"} · {item.snapshot.start_date ?? "開始日未知"} — {item.snapshot.end_date ?? "結束日未知"}</p></div>
      <Button disabled={busy || mutating} onClick={() => void include(item)}>納入並開啟</Button></div>)}</div>
    {page?.next_cursor && <Button variant="outline" disabled={busy || mutating} onClick={() => void load(page.next_cursor!)}>載入更多活動</Button>}
  </div>;
}
