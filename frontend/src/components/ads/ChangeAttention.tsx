import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, ClipboardCheck } from "lucide-react";
import { Button } from "@/components/layout/ui/button";
import { getChangeControlSummary, type ChangeControlSummary } from "@/lib/adsChangeApi";

export function ChangeAttention({ brandId }: { brandId: string }) {
  const [summary, setSummary] = useState<ChangeControlSummary | null>(null);
  const [failed, setFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); setSummary(null); setFailed(false);
    getChangeControlSummary(brandId, controller.signal).then(value => { if (!controller.signal.aborted) setSummary(value); }).catch(() => { if (!controller.signal.aborted) setFailed(true); });
    return () => controller.abort();
  }, [brandId, retry]);
  const labels: Record<string, string> = { draft: "待確認清單", approved: "待完成核對", deferred: "本次已暫緩" };
  return <section className="surface" aria-label="需要你決定的事">
    <div className="surface-header"><div className="flex items-center gap-2"><ClipboardCheck className="size-5 text-primary" /><h2>需要你決定的事</h2></div></div>
    <div className="surface-body space-y-3">
      {!summary && !failed && <p role="status" className="text-sm text-muted-foreground">正在整理待確認清單…</p>}
      {failed && <div className="space-y-2"><p role="alert" className="text-sm text-warning">目前無法讀取待辦，不能確認是否還有未完成項目。</p><Button variant="outline" size="sm" onClick={() => setRetry(value => value + 1)}>重新整理待辦</Button></div>}
      {summary && <>
        <p className="text-lg font-semibold">{summary.pending_count ? `${summary.pending_count} 份清單需要確認或核對` : "目前沒有待確認的變更清單"}</p>
        {!summary.pending_count && <p className="text-sm text-muted-foreground">從下方進入活動，查看成效或準備下一次調整。核准清單不會直接修改平台。</p>}
        <div className="divide-y divide-border">{summary.items.map(item => <Link key={item.id} to={`/brands/${brandId}/ads/campaigns/${item.campaign_id}?tab=changes&change=${encodeURIComponent(item.id)}`} className="flex items-center justify-between gap-3 py-3 text-sm hover:text-primary"><span className="min-w-0"><strong className="block break-words font-medium">{item.title}</strong><span className="mt-1 block text-xs text-muted-foreground">{item.campaign_name} · {labels[item.status] ?? "待查看"}{item.status === "approved" ? ` · ${item.pending_items} 項未完成` : ""}{item.unknown_items > 0 ? ` · ${item.unknown_items} 項結果未知` : ""}</span></span><ArrowRight className="size-4 shrink-0" /></Link>)}</div>
        {summary.truncated && <p className="text-xs text-muted-foreground">先顯示最近 20 份；其他待辦可由各活動的「變更與核對」查看。</p>}
      </>}
    </div>
  </section>;
}
