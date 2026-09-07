import { Link } from "react-router-dom";
import { Check, ArrowRight } from "lucide-react";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { Textarea } from "@/components/layout/ui/textarea";
import { formatCurrency } from "@/lib/format";
import type { ProductListItem } from "@/lib/productsApi";
import type { ScheduleState } from "@/lib/scheduleApi";

export interface ScheduleDraft {
  selectedIds: string[];
  platform: string;
  objective: string;
  promotionNote: string;
  planCount: number;
  startDate: string;
  endDate: string;
}

export function ScheduleSetup({ brandId, schedule, products, draft, onChange, confirming, onConfirm, submitting, submitError, onStart, busy }: {
  brandId: string;
  schedule: ScheduleState;
  products: ProductListItem[];
  draft: ScheduleDraft;
  onChange: (patch: Partial<ScheduleDraft>) => void;
  confirming: boolean;
  onConfirm: (value: boolean) => void;
  submitting: boolean;
  submitError: string | null;
  onStart: () => void;
  busy: boolean;
}) {
  const activeProducts = products.filter((product) => product.status === "active");
  const selectedNames = activeProducts.filter((product) => draft.selectedIds.includes(product.id)).map((product) => product.name);
  const objectives = schedule.objectives.filter((item) => item.platform === draft.platform);
  const platformLabel = schedule.platforms.find((item) => item.id === draft.platform)?.label ?? "尚未選擇";
  const objectiveLabel = objectives.find((item) => item.value === draft.objective)?.label ?? "尚未選擇";
  const planCounts = Array.from({ length: Math.max(schedule.plan_count_max - schedule.plan_count_min + 1, 0) }, (_, index) => schedule.plan_count_min + index);
  const validDates = draft.startDate !== "" && draft.endDate !== "" && draft.endDate >= draft.startDate;
  const canConfirm = draft.selectedIds.length > 0 && draft.platform !== "" && draft.objective !== "" && validDates && !busy;

  return <div className="grid grid-cols-[minmax(0,1fr)_280px] items-start gap-5">
    <section className="surface">
      <div className="surface-header"><h2>這期要投放哪些產品</h2><span className="text-xs text-muted-foreground">已選 {selectedNames.length} 項</span></div>
      <div className="surface-body flex flex-col gap-6">
        {activeProducts.length === 0 ? <div className="rounded-lg bg-muted/60 p-4 text-sm"><p className="mb-3 text-muted-foreground">這個品牌底下還沒有可投放的產品，先新增產品再開始規劃。</p><Button variant="outline" asChild><Link to={`/brands/${brandId}/products`}>前往產品頁</Link></Button></div> : <div className="grid max-h-56 grid-cols-1 gap-2 overflow-y-auto">
          {activeProducts.map((product) => <label key={product.id} className="flex cursor-pointer items-center gap-3 rounded-lg border border-border px-3 py-2.5 text-sm has-[:checked]:border-primary/30 has-[:checked]:bg-accent/50">
            <input type="checkbox" checked={draft.selectedIds.includes(product.id)} onChange={() => onChange({ selectedIds: draft.selectedIds.includes(product.id) ? draft.selectedIds.filter((id) => id !== product.id) : [...draft.selectedIds, product.id] })} />{product.name}
          </label>)}
        </div>}
        <div className="flex flex-col gap-5 border-t border-border pt-5">
          <fieldset className="flex flex-col gap-2"><legend className="mb-2 text-sm font-medium">平台</legend><div className="flex flex-wrap gap-4">{schedule.platforms.map((item) => <label key={item.id} className={`flex items-center gap-2 text-sm ${item.enabled ? "text-foreground" : "text-muted-foreground"}`}>
            <input type="radio" name="platform" checked={draft.platform === item.id} disabled={!item.enabled} onChange={() => onChange({ platform: item.id, objective: schedule.objectives.find((objective) => objective.platform === item.id)?.value ?? "" })} />{item.label}{!item.enabled && "（尚未啟用）"}
          </label>)}</div></fieldset>
          <div className="grid grid-cols-[minmax(0,1fr)_120px] gap-4">
            <label className="flex flex-col gap-2 text-sm"><span className="font-medium">行銷目標</span><select value={draft.objective} onChange={(event) => onChange({ objective: event.target.value })}>{objectives.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
            <label className="flex flex-col gap-2 text-sm"><span className="font-medium">要幾個方案</span><select value={draft.planCount} onChange={(event) => onChange({ planCount: Number(event.target.value) })}>{planCounts.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
          </div>
          <label className="flex flex-col gap-2 text-sm"><span className="font-medium">促銷或重點（選填）</span><Textarea value={draft.promotionNote} onChange={(event) => onChange({ promotionNote: event.target.value })} rows={3} placeholder="例如：這期主打新品上市" /></label>
          <div className="grid grid-cols-2 gap-4">
            <label className="flex min-w-0 flex-col gap-2 text-sm"><span className="font-medium">開始日</span><Input type="date" value={draft.startDate} onChange={(event) => onChange({ startDate: event.target.value })} /></label>
            <label className="flex min-w-0 flex-col gap-2 text-sm"><span className="font-medium">結束日</span><Input type="date" value={draft.endDate} min={draft.startDate || undefined} onChange={(event) => onChange({ endDate: event.target.value })} /></label>
          </div>
          {draft.startDate !== "" && draft.endDate !== "" && draft.endDate < draft.startDate && <p role="alert" className="text-sm text-danger">結束日不能早於開始日。</p>}
        </div>
        {!confirming && <Button type="button" className="self-start" disabled={!canConfirm} onClick={() => onConfirm(true)}>確認<ArrowRight className="size-4" aria-hidden="true" /></Button>}
      </div>
    </section>
    <aside className="surface sticky top-[88px]">
      <div className="surface-header"><h2>{confirming ? "確認這期要排程的內容" : "本期設定摘要"}</h2></div>
      <div className="surface-body flex flex-col gap-4">
        <div><p className="text-xs text-muted-foreground">本期每日預算</p><p className="mt-2 text-2xl font-semibold numeric">{formatCurrency(schedule.daily_budget)}</p>
          {schedule.daily_budget <= 0 && <p className="mt-2 text-xs leading-5 text-warning">尚未設定，請到設定頁的品牌規則參數填入「檔期日預算」。</p>}
        </div>
        <dl className="flex flex-col gap-3 border-t border-border pt-4 text-sm">
          <Summary label="產品" value={selectedNames.join("、") || "尚未選擇"} />
          <Summary label="平台" value={platformLabel} />
          <Summary label="行銷目標" value={objectiveLabel} />
          <Summary label="方案數" value={String(draft.planCount)} />
          <Summary label="檔期" value={validDates ? `${draft.startDate} ～ ${draft.endDate}` : "尚未填妥"} />
          {draft.promotionNote && <Summary label="促銷或重點" value={draft.promotionNote} />}
        </dl>
        {submitError && <p role="alert" className="text-sm text-danger">{submitError}</p>}
        {confirming && <div className="flex flex-col gap-3 border-t border-border pt-4">
          <p className="text-xs leading-5 text-muted-foreground">開始排程會建立 AI 方案工作，依目前設定的模型與費用上限執行。</p>
          <Button type="button" onClick={onStart} disabled={!canConfirm || submitting}>{submitting ? "排程中…" : <><Check className="size-4" aria-hidden="true" />開始排程</>}</Button>
          <Button type="button" variant="outline" onClick={() => onConfirm(false)} disabled={submitting}>修改</Button>
        </div>}
      </div>
    </aside>
  </div>;
}

function Summary({ label, value }: { label: string; value: string }) {
  return <div><dt className="mb-1 text-xs text-muted-foreground">{label}</dt><dd className="break-words leading-6">{value}</dd></div>;
}
