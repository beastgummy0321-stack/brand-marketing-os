import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import type { SettleQueueRow } from "@/lib/adsTriageApi";
import { Chip, GradeBar, Term } from "../patterns";
import { FROM_META } from "../settle/settleCsv";
import { settleAction } from "./status";

/** v10 home 「結算上一期」 (prototype `settleCard()`): the brand queue's open period-settle row
 * (`QueuePayload.settle`, Contract E), drawn as one card spanning the decisions row. Everything it prints comes from
 * the row's own `settle` payload: the month's range, how many campaigns (and how many came from Meta), how many ads
 * will be written, and the month's spend by grade. The grade words are already defined by the band above, so the bar
 * carries no second legend of rules. */

/** `2026-08-01` → `08/01` (the prototype's period format). */
function md(iso: string): string {
  return `${iso.slice(5, 7)}/${iso.slice(8, 10)}`;
}

/** 「08/01–08/31」: the settled period as printed on the card and in the 今天處理過 fold. */
export function settleRange(row: SettleQueueRow): string {
  return `${md(row.settle.start)}–${md(row.settle.end)}`;
}

function scopeText(row: SettleQueueRow): string {
  const { campaign_count: n, imported_count: imported } = row.settle;
  return `${settleRange(row)}・${n} 個活動${imported > 0 ? `（${imported} 個${FROM_META}）` : ""}`;
}

export function SettleCard({ brandId, row, recovering }: { brandId: string; row: SettleQueueRow; recovering: boolean }) {
  const action = settleAction(brandId, row);
  return (
    <article aria-label="結算上一期" className="col-span-full flex flex-col gap-3.5 rounded-xl border border-border bg-card px-5 py-[18px]">
      <div className="flex flex-wrap items-center gap-4">
        <span aria-hidden="true" className="grid size-12 shrink-0 place-items-center rounded-[10px] bg-accent text-xl text-accent-foreground">✎</span>
        <div className="min-w-[200px] flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Chip tone="accent">結算上一期</Chip>
            <span className="text-sm text-muted-foreground">{scopeText(row)}</span>
          </div>
          <div className="mt-1.5 text-base font-semibold">
            {row.settle.learnable_count} 則的成績可以寫進<Term k="notebook">筆記本</Term>
          </div>
        </div>
        <div className="min-w-0 max-w-[360px] flex-[1_1_260px]">
          <GradeBar buckets={row.settle.buckets} rules={false} />
        </div>
        {recovering ? (
          <Chip>補完資料後更新</Chip>
        ) : (
          <Button asChild variant="outline"><Link to={action.href}>{action.label} →</Link></Button>
        )}
      </div>
    </article>
  );
}

/** The settle row folded under the three cards, or handled today (prototype `homeDecide()` doneFold label
 * 「結算上一期 08/08–09/07」). */
export function SettleRow({ brandId, row, recovering }: { brandId: string; row: SettleQueueRow; recovering: boolean }) {
  const action = settleAction(brandId, row);
  return (
    <div className="flex flex-wrap items-center gap-3 border-t border-border py-2.5 first:border-t-0">
      <Chip tone="accent">結算上一期</Chip>
      <span className="min-w-0 flex-1 text-sm font-medium">{row.settle.learnable_count} 則的成績可以寫進筆記本</span>
      <span className="text-xs text-muted-foreground">{settleRange(row)}</span>
      {recovering ? (
        <Chip>補完資料後更新</Chip>
      ) : action.done ? (
        <Chip tone="ok">{action.label}</Chip>
      ) : (
        <Button asChild size="sm" variant="outline"><Link to={action.href}>{action.label} →</Link></Button>
      )}
    </div>
  );
}
