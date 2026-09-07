import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Inbox, ListFilter, RefreshCw } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { PageTabs } from "@/components/layout/PageTabs";
import { EmptyState } from "@/components/layout/EmptyState";
import { Pager } from "@/components/layout/Pager";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import { resolveAlert } from "@/lib/api";
import { fetchInbox, type InboxData, type InboxSeverity } from "@/lib/inboxApi";
import { SEVERITY_LABEL } from "@/lib/severity";
import { usePagination } from "@/lib/usePagination";
import { InboxItemCard, InboxItemDetail } from "./InboxItemCard";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: InboxData };

export function InboxPage() {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "done" ? "done" : "open";
  const [brand, setBrand] = useState("all");
  const [severity, setSeverity] = useState<InboxSeverity | "all">("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const requestId = useRef(0);
  const items = state.status === "ready" ? state.data[tab] : [];
  const allItems = state.status === "ready" ? [...state.data.open, ...state.data.done] : [];
  const brands = [...new Map(allItems.map((item) => [item.brand_id ?? "global", item.brand_name ?? "全站"])).entries()];
  const filtered = items.filter((item) => (brand === "all" || (item.brand_id ?? "global") === brand) && (severity === "all" || item.severity === severity));
  const pagination = usePagination(filtered, 8);
  const selected = pagination.pageItems.find((item) => item.id === selectedId) ?? pagination.pageItems[0];

  function load() {
    const id = ++requestId.current;
    setState({ status: "loading" });
    fetchInbox()
      .then((data) => { if (id === requestId.current) setState({ status: "ready", data }); })
      .catch((err: unknown) => { if (id === requestId.current) setState({ status: "error", message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。" }); });
  }
  useEffect(() => { load(); return () => { requestId.current += 1; }; }, []);

  function handleResolve(id: string) {
    if (resolvingId) return;
    setErrors((previous) => { const next = { ...previous }; delete next[id]; return next; });
    setResolvingId(id);
    resolveAlert(id)
      .then(() => { setResolvingId(null); load(); })
      .catch((err: unknown) => {
        setResolvingId(null);
        setErrors((previous) => ({ ...previous, [id]: err instanceof Error ? err.message : "「知道了」失敗，請稍後再試。" }));
      });
  }

  return <div className="flex flex-col gap-5">
    <PageHeader title="收件匣" description="集中查看跨品牌待辦，依品牌與嚴重度安排處理順序。" actions={<Button variant="outline" onClick={load} disabled={state.status === "loading" || resolvingId !== null}><RefreshCw className="size-4" aria-hidden="true" />重新整理</Button>} />
    <PageTabs value={tab} onChange={(value) => { setParams((previous) => { const next = new URLSearchParams(previous); next.set("tab", value); return next; }); setSelectedId(null); pagination.resetPage(); }} items={[
      { value: "open", label: "待處理", count: state.status === "ready" ? state.data.open.length : undefined },
      { value: "done", label: "已處理", count: state.status === "ready" ? state.data.done.length : undefined },
    ]} />
    {state.status === "loading" && <div aria-label="收件匣載入中" className="grid grid-cols-2 gap-5"><Skeleton className="h-[440px]" /><Skeleton className="h-[440px]" /></div>}
    {state.status === "error" && <div className="surface"><EmptyState title="讀取失敗" description={state.message} onAction={load} actionLabel="重新載入" /></div>}
    {state.status === "ready" && <div className="surface overflow-hidden">
      <div className="flex flex-wrap items-center gap-4 border-b border-border px-5 py-4">
        <ListFilter className="size-4 text-muted-foreground" aria-hidden="true" />
        <label className="flex items-center gap-2 text-sm"><span className="text-muted-foreground">品牌</span><select value={brand} onChange={(event) => { setBrand(event.target.value); setSelectedId(null); pagination.resetPage(); }} className="max-w-56"><option value="all">全部品牌</option>{brands.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
        <label className="flex items-center gap-2 text-sm"><span className="text-muted-foreground">嚴重度</span><select value={severity} onChange={(event) => { setSeverity(event.target.value as InboxSeverity | "all"); setSelectedId(null); pagination.resetPage(); }}><option value="all">全部嚴重度</option>{Object.entries(SEVERITY_LABEL).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <span className="ml-auto text-xs text-muted-foreground">符合 {filtered.length} 筆</span>
      </div>
      {filtered.length === 0 ? <div className="flex flex-col items-center py-8"><Inbox className="size-7 text-muted-foreground" aria-hidden="true" /><EmptyState title={items.length === 0 ? tab === "open" ? "目前沒有待處理事項" : "目前沒有已處理事項" : "沒有符合條件的事項"} description={items.length === 0 ? "系統會在需要你注意時，把相關事項送進收件匣。" : "試試其他品牌或嚴重度，查看相關事項。"} actionLabel={items.length > 0 ? "清除篩選" : undefined} onAction={items.length > 0 ? () => { setBrand("all"); setSeverity("all"); pagination.resetPage(); } : undefined} /></div> : <div className="grid min-h-[440px] grid-cols-[minmax(280px,0.95fr)_minmax(320px,1.05fr)]">
        <div ref={pagination.topRef} className="min-w-0 border-r border-border">
          <ul aria-label={tab === "open" ? "待處理事項" : "已處理事項"}>{pagination.pageItems.map((item) => <InboxItemCard key={item.id} item={item} selected={selected?.id === item.id} onSelect={() => setSelectedId(item.id)} />)}</ul>
          {pagination.pageCount > 1 && <div className="px-5 pb-4"><Pager page={pagination.page} pageCount={pagination.pageCount} totalCount={pagination.totalCount} onChange={(page) => { setSelectedId(null); pagination.goToPage(page); }} /></div>}
        </div>
        <div className="min-w-0">{selected && <InboxItemDetail item={selected} variant={tab} resolving={resolvingId === selected.id} busy={resolvingId !== null} error={errors[selected.id]} onResolve={handleResolve} />}</div>
      </div>}
    </div>}
  </div>;
}
