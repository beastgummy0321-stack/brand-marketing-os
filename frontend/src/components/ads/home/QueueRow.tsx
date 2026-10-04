import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import type { CloseoutQueueRow, QueueItem, QueueKind } from "@/lib/adsTriageApi";
import { cleanupAction, proposalAction, settleAction, type HomeDecision } from "./status";
import { Chip, KindMark } from "../patterns";
import { monthDay, shortName } from "./NextDates";

/** One home decision's action (feature F28 "Decisions on home": `cleanup`, `worse`, `refresh_creative`).
 * `cleanup`／`worse` follow their proposal through `home/status.ts` (same helpers the detail page and the flows use)
 * for the label and the link; with no proposal yet they use the prototype's own first-step words. Whether the row is
 * done is the row's own `done` (F47 Contract D), never re-derived here. */
export interface HomeAction { label: string; href: string | null; done: boolean }

export function homeAction(brandId: string, item: QueueItem): HomeAction {
  const campaignId = item.triage.campaign_id;
  if (item.kind_key === "cleanup") {
    const action = cleanupAction(brandId, item.cleanup?.campaign_id ?? campaignId, item.proposal, item.action_url);
    if (!action) return { label: "決定要不要關", href: null, done: item.done };
    return item.proposal === null ? { ...action, label: "決定要不要關", done: item.done } : { ...action, done: item.done };
  }
  if (item.kind_key === "worse") {
    const action = proposalAction(brandId, campaignId, item.triage.entity_id, item.proposal, "review");
    return item.proposal === null ? { ...action, label: "查原因", done: item.done } : { ...action, done: item.done };
  }
  return { label: "準備新素材", href: item.action_url, done: item.done };
}

/** The decision's own title, as the cards print it. */
export function decisionTitle(item: QueueItem): string {
  if (item.kind_key === "cleanup") {
    const n = item.cleanup?.ads.length ?? 0;
    return n ? `關 ${n} 則、留 ${item.cleanup?.keep.length ?? 0} 則` : "預算放不下全部在投的廣告";
  }
  if (item.kind_key === "refresh_creative") return `能判讀的素材只剩 ${item.refresh?.readable_count ?? 0} 則`;
  return item.triage.name ?? "未命名廣告";
}

/** A handled decision's chip (已拒絕／M/D 再看／已核對…). It links to its change set or review round, so a deferred
 * decision always has a way back (drill-10 Q2); a row with nowhere to go stays a plain chip. */
export function DoneChip({ action }: { action: HomeAction }) {
  const chip = <Chip tone={action.label.startsWith("✓") || action.label === "已核對" ? "ok" : "neutral"}>{action.label}</Chip>;
  if (!action.href) return chip;
  return (
    <Link to={action.href} className="rounded-full hover:opacity-80 focus-visible:outline-2 focus-visible:outline-ring">
      {chip}
    </Link>
  );
}

/** The fold's kind mark of an ad-level decision (v9 `qRow()`: 「✂ 清理」, 變貴, 補素材); other kinds carry none. */
function markOf(kind: QueueKind): { kind: "cut" | "worse" | "fresh"; label: string } | null {
  if (kind === "cleanup") return { kind: "cut", label: "清理" };
  if (kind === "worse") return { kind: "worse", label: "變貴" };
  if (kind === "refresh_creative") return { kind: "fresh", label: "補素材" };
  return null;
}

/** A decision folded under the three cards (prototype v9 `qRow()` vocabulary: kind mark, campaign, title, action).
 * The cleanup mark is `KindMark cut` 「✂ 清理」. */
export function QueueRow({ brandId, item, recovering }: { brandId: string; item: QueueItem; recovering: boolean }) {
  const mark = markOf(item.kind_key);
  const action = homeAction(brandId, item);
  const campaignName = item.cleanup?.campaign_name ?? item.refresh?.campaign_name ?? item.triage.campaign_name;
  return (
    <div className="flex flex-wrap items-center gap-3 border-t border-border py-2.5 first:border-t-0">
      {mark && <KindMark kind={mark.kind}>{mark.label}</KindMark>}
      <span className="min-w-0 flex-1 text-sm font-medium [overflow-wrap:anywhere]">{decisionTitle(item)}</span>
      <span className="text-xs text-muted-foreground">{shortName(campaignName)}</span>
      {recovering ? (
        <Chip>補完資料後更新</Chip>
      ) : action.done ? (
        <DoneChip action={action} />
      ) : action.href ? (
        <Button asChild size="sm" variant="outline"><Link to={action.href}>{action.label} →</Link></Button>
      ) : null}
    </div>
  );
}

/** F49 Contract Q: an ended campaign's closeout decision — its one step is the row's own `action_url` (the campaign's
 * 成效 tab with the close dialog open), never rebuilt here. A closeout row is never done: it leaves when the campaign
 * closes. */
export function closeoutAction(row: CloseoutQueueRow): HomeAction {
  return { label: "結案這一期", href: row.action_url, done: row.done };
}

/** What the closeout card says under its title: the end date and the ads its platform read still finds running. */
export function closeoutNote(row: CloseoutQueueRow): string {
  const { end_date: end, running } = row.closeout;
  const parts = [end ? `${monthDay(end)} 結束` : null, running.count > 0 ? `平台上還開著 ${running.count} 則` : null];
  return parts.filter(Boolean).join("・");
}

/** A closeout decision folded under the three cards (same row vocabulary as `QueueRow`). */
export function CloseoutRow({ row, recovering }: { row: CloseoutQueueRow; recovering: boolean }) {
  const action = closeoutAction(row);
  return (
    <div className="flex flex-wrap items-center gap-3 border-t border-border py-2.5 first:border-t-0">
      <Chip tone="warn">結案</Chip>
      <span className="min-w-0 flex-1 text-sm font-medium [overflow-wrap:anywhere]">{row.message}</span>
      <span className="text-xs text-muted-foreground">{shortName(row.closeout.campaign_name)}</span>
      {recovering ? (
        <Chip>補完資料後更新</Chip>
      ) : action.href ? (
        <Button asChild size="sm" variant="outline"><Link to={action.href}>{action.label} →</Link></Button>
      ) : null}
    </div>
  );
}

/** Where one board entry's step leads (the settle page's 「下一件」 reads it). */
export function decisionHref(brandId: string, d: HomeDecision): string | null {
  if (d.kind === "item") return homeAction(brandId, d.item).href;
  if (d.kind === "settle") return settleAction(brandId, d.row).href;
  return closeoutAction(d.row).href;
}
