import {useEffect, useRef, useState, type ReactNode} from "react";
import type {CoordinateLearnings} from "@/lib/adsLearningsApi";
import type {LearningEvidence} from "@/lib/adsLearningEvidence";
import {SidePanel} from "@/components/layout/SidePanel";
import {Button} from "@/components/layout/ui/button";
import {LearningEvidenceCard, LearningEvidenceSource, LearningEvidenceState, LearningEvidenceOrigin, Segmented} from "../patterns";

export function QualifiedLearningList({data, onRetry, children, loading = false}: {data: CoordinateLearnings | null; onRetry: () => void; children?: ReactNode; loading?: boolean}) {
  const [filter, setFilter] = useState<"all" | "usable" | "history">("all");
  const [sourceId, setSourceId] = useState<string | null>(null);
  const title = useRef<HTMLHeadingElement>(null);
  const items = Array.from(new Map([
    ...(data?.campaigns.flatMap(campaign => campaign.rows.map(row => row.evidence).filter(Boolean)) ?? []),
    ...(data?.evidence_context?.items ?? []),
  ].map(row => [row.id, row])).values());
  const source = items.find(row => row.id === sourceId) ?? null;
  useEffect(() => { if (sourceId) title.current?.focus(); }, [sourceId]);
  const shown = items.filter(row => filter === "all" || (filter === "usable" ? row.use_state === "usable" : row.use_state !== "usable"));
  const audience = (row: LearningEvidence) => data?.campaigns.flatMap(c => c.rows).find(ad =>
    row.scope.customer_group_id !== null && ad.customer_group?.id === row.scope.customer_group_id)?.customer_group?.who;
  return <section className="surface min-w-0" data-slot="qualified-learning-list">
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-[22px] py-[18px]">
      <Segmented label="學習篩選" options={[{value: "all", label: "全部"}, {value: "usable", label: "可參考"}, {value: "history", label: "歷史與其他資料"}]} value={filter} onChange={setFilter} />
      <Button variant="ghost" size="sm" onClick={onRetry}>重新讀取 ↻</Button>
    </div>
    <div className="grid grid-cols-[minmax(0,1fr)_110px_120px_84px] gap-4 border-b border-border bg-background px-[22px] py-3 text-xs text-muted-foreground">
      <span>經驗與適用範圍</span><span>證據類型</span><span>目前用途</span><span>來源</span>
    </div>
    {shown.map(row => <div key={row.id} data-slot="library-learning-row" className="grid min-w-0 grid-cols-[minmax(0,1fr)_110px_120px_84px] items-center gap-4 border-b border-border px-[22px] py-[18px] last:border-b-0">
      <div className="min-w-0"><LearningEvidenceCard evidence={row} compact scopeLabel={`${row.scope.product_label ?? "商品尚未核實"} · ${audience(row) ?? "受眾名稱尚未提供"}`} /></div>
      <div><LearningEvidenceOrigin evidence={row} /></div><div><LearningEvidenceState evidence={row} /></div>
      <Button variant="ghost" size="sm" onClick={() => setSourceId(row.id)}>查看 →</Button>
    </div>)}
    {shown.length === 0 && <div className="px-[22px] py-12 text-center"><h3 className="font-semibold">{loading ? "正在讀取學習紀錄" : !data?.evidence_context ? "歷史適用性尚未核實" : items.length === 0 ? "還沒有學習紀錄" : "這個篩選沒有資料"}</h3><p className="mt-2 text-sm text-muted-foreground">{data?.evidence_context ? "切換篩選查看其他紀錄；新提案仍待驗證。" : "選擇商品並重新讀取，才能核對可參考範圍。"}</p></div>}
    {data?.evidence_context?.omitted ? <p className="px-[22px] py-3 text-xs text-muted-foreground">完整來源回應另省略 {data.evidence_context.omitted} 條；已提供的排名來源仍保留於此。</p> : null}
    <div className="[&>.surface]:border-0 [&>.surface]:border-t [&>.surface]:rounded-t-none">{children}</div>
    {source && <SidePanel ariaLabel="經驗來源與適用範圍" widthClassName="w-[600px]" onClose={() => setSourceId(null)}>
      <h3 ref={title} tabIndex={-1} className="text-lg font-semibold outline-none">經驗來源與適用範圍</h3>
      <LearningEvidenceSource evidence={source} audienceLabel={audience(source)} />
      <Button variant="outline" className="w-fit" onClick={() => setSourceId(null)}>返回</Button>
    </SidePanel>}
  </section>;
}
