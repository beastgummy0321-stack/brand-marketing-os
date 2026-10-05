import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/layout/ui/dialog";
import { existingCampaigns, importExisting, refreshExisting, type ExistingPage } from "@/lib/adsExternalApi";
import { formatInstant, useOrgClock } from "@/lib/orgClock";
import { useSyncOutcome } from "@/lib/useSyncOutcome";
import { Chip } from "./patterns";

/** `YYYY-MM-DD` → `MM/DD` (string slicing: a platform date has no time zone to shift). */
const md = (iso: string) => `${iso.slice(5, 7)}/${iso.slice(8, 10)}`;
/** F47-I08 (drill-10 §4.3): a platform campaign's own status in words and its dates as `MM/DD`, never the raw code
 * or ISO text. F49-I14 (Contract L): the word is the served `delivery_label`. */
function existingRowMeta(item: ExistingPage["items"][number]): string {
  const { start_date, end_date } = item.snapshot;
  const dates = `${start_date ? md(start_date) : "開始日未知"} – ${end_date ? md(end_date) : "結束日未知"}`;
  return item.delivery_label ? `${item.delivery_label} · ${dates}` : dates;
}

/** F49-I14 (Contract O): the account read this dialog asked for, followed through `useSyncOutcome`; its served `text`
 * (found, nothing read, partial／failed with the reason) and the last clean read. `onFinished` fires once, when the
 * read finished, so the list is read again from the cache it filled. */
function ListReadLine({ brandId, jobId, fallbackSuccess, onFinished }: {
  brandId: string; jobId: string; fallbackSuccess: string | null; onFinished: () => void;
}) {
  const outcome = useSyncOutcome({ brandId, jobId });
  const finish = useRef(onFinished);
  finish.current = onFinished;
  const reported = useRef(false);
  useEffect(() => {
    if (outcome.state === null || outcome.state === "running" || reported.current) return;
    reported.current = true;
    finish.current();
  }, [outcome.state]);
  return <ReadLine text={outcome.text} state={outcome.state} lastSuccessAt={outcome.lastSuccessAt ?? fallbackSuccess} error={outcome.error} />;
}

function ReadLine({ text, state, lastSuccessAt, error }: { text: string; state: string | null; lastSuccessAt: string | null; error?: string | null }) {
  const warn = state === "failed" || state === "partial";
  const { timezone } = useOrgClock();
  return <>
    {text && <p role="status" data-slot="list-read" data-state={state ?? undefined} className={`text-sm ${warn ? "text-warning" : "text-muted-foreground"}`}>
      {text} · 最近成功：{lastSuccessAt ? formatInstant(lastSuccessAt, timezone, "md_hm") : "尚未成功讀回"}
    </p>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </>;
}

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
  /** The account read this dialog posted (`round` mounts a fresh outcome reader per post). */
  const [read, setRead] = useState<{ account: string; jobId: string; round: number } | null>(null);
  const request = useRef<AbortController | null>(null);
  const lifetime = useRef(new AbortController());
  /** Accounts this dialog already asked the platform to read (once per account per opening). */
  const asked = useRef(new Set<string>());
  useEffect(() => { lifetime.current = new AbortController(); return () => lifetime.current.abort(); }, []);
  async function load(cursor?: string) {
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    setBusy(true); setError("");
    try {
      const next = await existingCampaigns(brandId, { ...source, cursor }, controller.signal);
      if (controller.signal.aborted) return;
      setPage(prev => ({ ...next, items: cursor ? [...(prev?.items ?? []), ...next.items] : next.items }));
      // F49 Contract O: the listing GET is read-only; opening the list (or another account) asks the platform for a
      // fresh read once. An account the server cannot read answers its cached rows with a failed outcome and no job:
      // that outcome is the answer, no read is posted.
      const account = `${next.platform ?? ""}|${next.source_account ?? ""}`;
      const unreadable = !next.job && next.outcome?.state === "failed";
      if (!cursor && next.platform && next.source_account && !unreadable && !asked.current.has(account)) {
        asked.current.add(account);
        void refresh(next);
      }
    } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "讀取失敗。"); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  useEffect(() => { void load(); return () => request.current?.abort(); }, [brandId, source.platform, source.source_account]); // scoped request cancels old account pages
  /** After the posted read finished: read that account's cached list again, keeping the pages already loaded. */
  async function reloadAfterRead(platform: string, source_account: string) {
    const signal = lifetime.current.signal;
    try {
      const next = await existingCampaigns(brandId, { platform, source_account }, signal);
      if (signal.aborted) return;
      setPage(prev => !prev || prev.source_account !== source_account ? prev : { ...next, items: [...new Map([...prev.items, ...next.items].map(i => [i.id, i])).values()], next_cursor: prev.next_cursor ?? next.next_cursor });
    } catch (e) { if (!signal.aborted) setError(e instanceof Error ? e.message : "讀取失敗。"); }
  }
  async function refresh(target: Pick<ExistingPage, "platform" | "source_account"> | null = page) {
    if (!target?.platform || !target.source_account) return;
    const { platform, source_account } = target;
    const signal = lifetime.current.signal; setMutating(true); setError("");
    try {
      const { job } = await refreshExisting(brandId, platform, source_account);
      if (!signal.aborted) setRead(prev => ({ account: `${platform}|${source_account}`, jobId: job.id, round: (prev?.round ?? 0) + 1 }));
    }
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
  const pageAccount = `${page?.platform ?? ""}|${page?.source_account ?? ""}`;
  const tracked = read && read.account === pageAccount ? read : null;
  return <div className="flex flex-col gap-3">
    <div className="flex items-center gap-2"><label htmlFor="existing-source">品牌綁定帳號</label>
      <select id="existing-source" disabled={mutating} className="rounded-md border border-border p-2" value={`${page?.platform ?? source.platform ?? ""}|${page?.source_account ?? source.source_account ?? ""}`} onChange={e => {
        request.current?.abort(); const [platform, source_account] = e.target.value.split("|");
        setPage(prev => prev ? { ...prev, platform, source_account, items: [], next_cursor: null, job: null, outcome: null } : null); setSource({ platform, source_account });
      }}>{page?.sources.map(s => <option key={`${s.platform}|${s.account_id}`} value={`${s.platform}|${s.account_id}`}>{s.label} · {s.name || s.account_id}</option>)}</select>
      <Button variant="outline" disabled={busy || mutating || !page?.sources.length} onClick={() => void refresh()}>更新清單</Button></div>
    {busy && <p role="status">讀取中…已快取的活動仍可查看。</p>}
    {error && <p role="alert" className="text-destructive">{error} <Button variant="outline" disabled={mutating} onClick={() => void load()}>重試讀取</Button></p>}
    {tracked
      ? <ListReadLine key={`${tracked.jobId}:${tracked.round}`} brandId={brandId} jobId={tracked.jobId} fallbackSuccess={page?.job?.last_success_at ?? null}
          onFinished={() => { const [platform, source_account] = tracked.account.split("|"); void reloadAfterRead(platform, source_account); }} />
      : page?.outcome && <ReadLine text={page.outcome.text} state={page.outcome.state} lastSuccessAt={page.job?.last_success_at ?? null} />}
    {!busy && page && !page.items.length && <p>{page.sources.length ? "此帳號尚無已讀回活動；可更新清單，暫停或沒有花費的活動也會保留。" : "尚無可讀取的綁定帳號，請先至品牌連線設定核對。"}</p>}
    <div className="max-h-96 overflow-auto divide-y divide-border">{page?.items.map(item => <div key={item.id} className="flex items-center justify-between gap-3 py-3">
      <div><p className="font-medium">{item.snapshot.name || item.native_id}</p><p className="text-sm text-muted-foreground">{existingRowMeta(item)}</p></div>
      {item.campaign_id
        // Already in a workspace: say so and open it — never offer to add the same platform campaign twice.
        ? <div className="flex shrink-0 items-center gap-2"><Chip>已在工作區</Chip>
            <Button variant="outline" disabled={mutating} onClick={() => navigate(`/brands/${brandId}/ads/campaigns/${item.campaign_id}`)}>打開</Button></div>
        : <Button disabled={busy || mutating} onClick={() => void include(item)}>納入並開啟</Button>}</div>)}</div>
    {page?.next_cursor && <Button variant="outline" disabled={busy || mutating} onClick={() => void load(page.next_cursor!)}>載入更多活動</Button>}
  </div>;
}
