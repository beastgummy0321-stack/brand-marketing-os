import { useState } from "react";
import { ArrowRight, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { Badge } from "@/components/layout/ui/badge";
import { EmptyState } from "@/components/layout/EmptyState";
import { formatCurrency } from "@/lib/format";
import { SCHEDULE_REJECT_CATEGORIES, type RejectSeverity, type SchedulePlanItem, type ScheduleState } from "@/lib/scheduleApi";

export interface FeedbackEntry {
  id: number;
  severity: RejectSeverity;
  ruleType: string;
  content: string;
}

export function PlanComparison({ plan, expandingIndex, expandError, onExpand, feedbackByPlan, onAddFeedback, onUpdateFeedback, onRemoveFeedback, onReject, rejecting, rejectError, busy }: {
  plan: NonNullable<ScheduleState["plan"]>;
  expandingIndex: number | null;
  expandError: string | null;
  onExpand: (index: number) => void;
  feedbackByPlan: Record<number, FeedbackEntry[]>;
  onAddFeedback: (index: number) => void;
  onUpdateFeedback: (index: number, id: number, patch: Partial<FeedbackEntry>) => void;
  onRemoveFeedback: (index: number, id: number) => void;
  onReject: () => void;
  rejecting: boolean;
  rejectError: string | null;
  busy: boolean;
}) {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const index = selectedIndex < plan.plans.length ? selectedIndex : 0;
  const selected = plan.plans[index];
  const totalFeedbackCount = Object.values(feedbackByPlan).reduce((count, entries) => count + entries.length, 0);

  if (plan.failure) return <div role="alert" className="surface p-5"><h2 className="mb-2 text-base">方案產出失敗</h2><p className="text-sm text-danger">{plan.failure}</p><p className="mt-3 text-sm text-muted-foreground">可回到「設定檔期」調整內容後重新送出。</p></div>;
  if (!selected) return <div className="surface"><EmptyState title={plan.running ? "方案準備中" : "尚無可比較的方案"} description={plan.running ? "完成後會顯示在這裡，可以先離開，回來後繼續查看。" : "回到設定檔期，確認產品與日期後開始排程。"} /></div>;

  return <div className="flex flex-col gap-5">
    <div className="grid grid-cols-[230px_minmax(0,1fr)] items-start gap-5">
      <aside className="surface sticky top-[88px] overflow-hidden">
        <div className="surface-header"><h2>選擇方案</h2><span className="text-xs text-muted-foreground">{plan.plans.length} 個</span></div>
        <div className="max-h-[55vh] overflow-y-auto" role="group" aria-label="方案選擇">
          {plan.plans.map((item, itemIndex) => <button key={itemIndex} type="button" aria-pressed={index === itemIndex} onClick={() => setSelectedIndex(itemIndex)} className={`flex w-full flex-col gap-2 border-t border-border px-5 py-4 text-left hover:bg-muted/60 ${index === itemIndex ? "bg-accent/60" : ""}`}>
            <span className="flex w-full items-center justify-between gap-2 text-sm font-semibold"><span>方案 {itemIndex + 1}</span>{(feedbackByPlan[itemIndex]?.length ?? 0) > 0 && <Badge variant="secondary">{feedbackByPlan[itemIndex].length} 則意見</Badge>}</span>
            <span className="line-clamp-3 text-xs leading-5 text-muted-foreground">{item.summary}</span>
          </button>)}
        </div>
        {plan.sources.length > 0 && <details className="border-t border-border px-5 py-3"><summary className="text-xs font-medium">排程前查到的資料（{plan.sources.length}）</summary><ul className="mt-2 flex max-h-48 flex-col gap-3 overflow-y-auto text-xs">{plan.sources.map((source, sourceIndex) => <li key={sourceIndex}><a href={source.url} target="_blank" rel="noreferrer" className="break-words leading-5 text-primary hover:underline">{source.title || source.url}</a></li>)}</ul></details>}
      </aside>
      <section className="surface">
        <div className="surface-header"><h2>方案 {index + 1}</h2><Button type="button" onClick={() => onExpand(index)} disabled={busy || expandingIndex !== null}>{expandingIndex === index ? "展開中…" : <>用這個方案展開<ArrowRight className="size-4" aria-hidden="true" /></>}</Button></div>
        <div className="surface-body flex flex-col gap-5">
          {expandError && <p role="alert" className="text-sm text-danger">{expandError}</p>}
          <p className="max-w-[var(--width-prose)] whitespace-pre-wrap text-sm leading-7">{selected.summary}</p>
          {selected.reasoning && <p className="max-w-[var(--width-prose)] whitespace-pre-wrap text-sm leading-7 text-muted-foreground">{selected.reasoning}</p>}
          <PlanSplits plan={selected} />
          <FeedbackControl entries={feedbackByPlan[index] ?? []} onAdd={() => onAddFeedback(index)} onUpdate={(id, patch) => onUpdateFeedback(index, id, patch)} onRemove={(id) => onRemoveFeedback(index, id)} />
        </div>
      </section>
    </div>
    <div className="surface flex flex-wrap items-center justify-between gap-4 px-5 py-4">
      <div><p className="text-sm font-medium">這批方案共 {totalFeedbackCount} 則意見</p><p className="mt-1 text-xs text-muted-foreground">可先切換方案逐一留下意見，再合併送出，重新產生整批方案。</p>{rejectError && <p role="alert" className="mt-2 text-sm text-danger">{rejectError}</p>}</div>
      <Button type="button" variant="outline" className="border-danger/30 text-danger hover:bg-danger/5 hover:text-danger" onClick={onReject} disabled={totalFeedbackCount === 0 || rejecting || busy}>{rejecting ? "送出中…" : "這批都不要，重新出方案"}</Button>
    </div>
  </div>;
}

function PlanSplits({ plan }: { plan: SchedulePlanItem }) {
  if (plan.splits.length === 0) return null;
  return <div className="table-surface"><table className="text-left text-sm"><thead><tr><th>方向</th><th>比例</th><th>每日金額</th><th>理由</th></tr></thead><tbody>{plan.splits.map((split, index) => <tr key={index} className="border-t border-border"><td>{split.label}</td><td className="whitespace-nowrap">{(split.share * 100).toFixed(0)}%</td><td className="whitespace-nowrap">{formatCurrency(split.daily_amount)}</td><td className="min-w-40 leading-6">{split.why}</td></tr>)}</tbody></table></div>;
}

function FeedbackControl({ entries, onAdd, onUpdate, onRemove }: { entries: FeedbackEntry[]; onAdd: () => void; onUpdate: (id: number, patch: Partial<FeedbackEntry>) => void; onRemove: (id: number) => void }) {
  return <div className="flex flex-col gap-4 border-t border-border pt-5">
    <div className="flex items-center justify-between"><h3 className="text-sm">這個方案的意見</h3><Button type="button" variant="outline" size="sm" onClick={onAdd}><Plus className="size-4" aria-hidden="true" />加一條意見</Button></div>
    {entries.length === 0 && <p className="text-xs leading-5 text-muted-foreground">記下偏好或不能採用的紅線，切換方案時會保留。</p>}
    <div className="flex max-h-80 flex-col gap-4 overflow-y-auto">
      {entries.map((entry, index) => <div key={entry.id} className="flex flex-col gap-2 border-b border-border pb-4 last:border-b-0">
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-xs"><span className="text-muted-foreground">意見 {index + 1}</span><select aria-label={`意見 ${index + 1} 嚴重程度`} value={entry.severity} onChange={(event) => onUpdate(entry.id, { severity: event.target.value as RejectSeverity })}><option value="soft">偏好</option><option value="hard">紅線</option></select></label>
          {entry.severity === "soft" && <select aria-label={`意見 ${index + 1} 類別`} value={entry.ruleType} onChange={(event) => onUpdate(entry.id, { ruleType: event.target.value })}>{SCHEDULE_REJECT_CATEGORIES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>}
          <Button type="button" variant="ghost" size="icon-sm" className="ml-auto text-muted-foreground hover:text-danger" aria-label={`移除意見 ${index + 1}`} onClick={() => onRemove(entry.id)}><Trash2 className="size-4" aria-hidden="true" /></Button>
        </div>
        <Input aria-label={`意見 ${index + 1} 內容`} value={entry.content} onChange={(event) => onUpdate(entry.id, { content: event.target.value })} maxLength={100} placeholder="一句話說明哪裡不對" />
        <p className="text-xs text-muted-foreground">一句話就好；系統只記得 20 條規則，寫太長會擠掉別的。</p>
      </div>)}
    </div>
  </div>;
}
