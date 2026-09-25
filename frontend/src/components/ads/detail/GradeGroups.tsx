import { useEffect, useState, type ReactNode } from "react";
import { Image as ImageIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { cn } from "@/lib/utils";
import type { QueueItem, TriageClosedBlock, TriageClosedItem, TriageItem } from "@/lib/adsTriageApi";
import { Chip, GRADE_FILL, GRADE_LABEL, formatAmount, type Grade } from "../patterns";
import { cleanupAction, proposalAction } from "../home/status";

/** F28-I10: the campaign detail's grade groups (prototype v9 `tabPerf()` groups + `row`). Every active ad arrives
 * already graded against the campaign's one cap (`TriageItem.grade`/`grade_label`, Feature F28 "Grades"); this
 * file only groups, orders and labels them, and picks each row's one action. */

/** One group per grade, in the prototype's `ORDER` (白花, 太貴, 偏貴, 划算, 還太新). `insufficient` splits by the
 * backend's own `grade_label` (還太新、看不準 below the sample gate, 資料不足 otherwise) so the two honest reasons
 * never share a heading; `no_target` (no cap at all) comes last. */
export type GroupKey = "wasted" | "over" | "watch" | "on_target" | "thin" | "no_data" | "no_target";
export const GROUP_ORDER: GroupKey[] = ["wasted", "over", "watch", "on_target", "thin", "no_data", "no_target"];
/** Prototype: 白花／太貴／偏貴 open, everything else folded. */
export const OPEN_BY_DEFAULT: GroupKey[] = ["wasted", "over", "watch"];

const GROUP_GRADE: Record<GroupKey, Grade> = {
  wasted: "wasted", over: "over", watch: "watch", on_target: "on_target",
  thin: "insufficient", no_data: "insufficient", no_target: "no_target",
};

export function groupOf(item: TriageItem): GroupKey {
  if (item.grade === "insufficient") return item.grade_label === GRADE_LABEL.insufficient ? "thin" : "no_data";
  return item.grade;
}

/** The summary's right-hand hint (prototype `tabPerf()`), from the cap T and the grade bands the kit ruler draws
 * (偏貴 up to 1.2 × T, 白花／還太新 against the 3 × T spend line). No cap, or a reason that is not about the spend
 * line (資料不足), prints no hint rather than an invented one. */
function groupHint(key: GroupKey, cap: number | null): string | null {
  if (cap === null) return null;
  const f = (v: number) => formatAmount(v) as string;
  switch (key) {
    case "wasted": return `花到 ${f(3 * cap)} 元還沒賣出`;
    case "over": return `每筆超過 ${f(cap * 1.2)} 元`;
    case "watch": return `每筆 ${f(cap)}–${f(cap * 1.2)} 元`;
    case "on_target": return `每筆不到 ${f(cap)} 元`;
    case "thin": return `還沒花到 ${f(3 * cap)} 元`;
    default: return null;
  }
}

/** Prototype `trend()`: the trend note under the name. `change_pct` is a ratio against the equal-length previous
 * window (`class` keeps that meaning, Feature F28 "Grades"); none → the prototype's own "沒有可比資料". */
export function trendNote(item: TriageItem): string {
  const days = item.window.days;
  if (item.change_pct === null) return `比前 ${days} 天：沒有可比資料`;
  const pct = Math.round(item.change_pct * 100);
  return `比前 ${days} 天 ${pct > 0 ? "▲" : pct < 0 ? "▼" : "±"}${Math.abs(pct)}%`;
}

/** What a row's one button does (prototype `row`): an ad inside this campaign's open cleanup row → 在清理提議 (the
 * cleanup decision, 白花 + 太貴 are one decision); else its own open `stop_loss`／`worse` row → 去處理; else 看紀錄
 * on the workspace performance tab. A row whose proposal is already done no longer counts as open. */
export interface RowAction { label: "在清理提議" | "去處理" | "看紀錄"; href: string }

export function recordHref(workspaceHref: string, entityId: string) {
  return `${workspaceHref}?tab=performance&ad=${entityId}`;
}

export function adActions(
  brandId: string, campaignId: string, workspaceHref: string, items: TriageItem[], queue: QueueItem[],
): Map<string, RowAction> {
  const actions = new Map<string, RowAction>();
  const cleanupRow = queue.find((q) => q.kind_key === "cleanup" && q.cleanup?.campaign_id === campaignId);
  const cleanup = cleanupRow ? cleanupAction(brandId, campaignId, cleanupRow.proposal, cleanupRow.action_url) : null;
  const inCleanup = new Set(cleanup && !cleanup.done ? cleanupRow!.cleanup!.ads.map((ad) => ad.entity_id) : []);
  for (const item of items) {
    const id = item.entity_id;
    if (inCleanup.has(id)) {
      actions.set(id, { label: "在清理提議", href: cleanup!.href });
      continue;
    }
    const own = queue.find((q) => q.triage.entity_id === id && (q.kind_key === "stop_loss" || q.kind_key === "worse"));
    const step = own
      ? proposalAction(brandId, campaignId, id, own.proposal, own.kind_key === "worse" ? "review" : "pause")
      : null;
    actions.set(id, step && !step.done
      ? { label: "去處理", href: step.href }
      : { label: "看紀錄", href: recordHref(workspaceHref, id) });
  }
  return actions;
}

/** Thumbnail: `thumbnail_url` may be null or an expiring CDN link — both fall back to one neutral placeholder. */
function AdThumb({ url }: { url: string | null }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [url]);
  return (
    <div className="flex size-10 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-muted" aria-hidden="true">
      {url !== null && !failed
        ? <img src={url} alt="" className="size-full object-cover" onError={() => setFailed(true)} />
        : <ImageIcon className="size-4 text-muted-foreground" />}
    </div>
  );
}

const money = (v: number | null) => (formatAmount(v) === null ? "未知" : `${formatAmount(v)} 元`);

/** The per-result column (prototype: 每賣一筆 ／ 購買 0 筆 ／ 還太新). Purchases read 每賣一筆; other result kinds
 * name their own result (`result_label` from the backend, never re-worded). */
function ResultCell({ item }: { item: TriageItem }) {
  const m = item.current;
  if (item.grade === "wasted") return <NumberCell label={m.result_label} value="0 筆" />;
  const label = m.result_kind === "purchase" || (m.result_kind === null && item.target.result_kind === "purchase")
    ? "每賣一筆" : `每次${m.result_label}成本`;
  if (item.grade === "insufficient") {
    const word = item.grade_label === GRADE_LABEL.insufficient ? "還太新" : item.grade_label;
    return <NumberCell label={label} value={<span className="text-[13px] font-medium text-muted-foreground">{word}</span>} />;
  }
  return <NumberCell label={label} value={money(m.cost_per_result)} />;
}

function NumberCell({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="text-right">
      <span className="block text-[11.5px] text-muted-foreground">{label}</span>
      <b className="numeric text-[15px] font-semibold whitespace-nowrap">{value}</b>
    </div>
  );
}

function ActionLink({ action }: { action: RowAction }) {
  return action.label === "看紀錄"
    ? <Button asChild variant="link" size="sm" className="h-auto px-0"><Link to={action.href}>看紀錄</Link></Button>
    : <Button asChild variant="outline" size="sm"><Link to={action.href}>{action.label}</Link></Button>;
}

// Prototype `.adrow`: 40px thumb · name + trend note · 花費 · per result · action.
const ROW = "grid grid-cols-[40px_minmax(0,1fr)_110px_100px_auto] items-center gap-3.5 border-t border-border py-[11px] first:border-t-0";

function AdRow({ item, action, highlighted, rowRef }: {
  item: TriageItem; action: RowAction; highlighted: boolean; rowRef: (el: HTMLDivElement | null) => void;
}) {
  const name = item.name ?? "（未命名廣告）";
  return (
    <div ref={rowRef} data-testid={`ad-row-${item.entity_id}`} className={cn(ROW, highlighted && "-mx-2 rounded-lg bg-accent/60 px-2 ring-1 ring-inset ring-primary")}>
      <AdThumb url={item.thumbnail_url} />
      <div className="min-w-0">
        <p className="text-sm font-semibold [overflow-wrap:anywhere]">{name}</p>
        <p className="text-[11.5px] text-muted-foreground">{trendNote(item)}</p>
      </div>
      <NumberCell label="花費" value={money(item.current.spend)} />
      <ResultCell item={item} />
      <div className="min-w-[92px] text-right"><ActionLink action={action} /></div>
    </div>
  );
}

/** Rows inside a group: most expensive per result first (prototype), unknown cost last, then by spend. */
function byCost(a: TriageItem, b: TriageItem) {
  const ca = a.current.cost_per_result, cb = b.current.cost_per_result;
  if (ca !== cb) return (cb ?? -1) - (ca ?? -1);
  return (b.current.spend ?? 0) - (a.current.spend ?? 0);
}

/** One `<details>` shell for a grade group and the closed group (prototype `.grp`): swatch, title, count chip, hint. */
function Fold({ swatch, title, count, hint, open, onToggle, muted = false, children }: {
  swatch: string; title: string; count: number; hint: string | null; open: boolean;
  onToggle: (open: boolean) => void; muted?: boolean; children: ReactNode;
}) {
  return (
    // No `overflow-hidden`: it would clip the summary's 3px focus outline. `.surface` sets its own background, which a
    // `bg-muted` utility cannot override, so the grey closed fold spells out the same border and radius instead.
    <details open={open} onToggle={(e) => onToggle(e.currentTarget.open)} className={cn("group", muted ? "min-w-0 rounded-xl border border-border bg-muted" : "surface")}>
      <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2.5 px-5 py-[13px] [&::-webkit-details-marker]:hidden">
        <span aria-hidden="true" className={cn("size-3 shrink-0 rounded-[3px]", swatch)} />
        <b className="text-sm font-semibold">{title}</b>
        <Chip>{count} 則</Chip>
        <span className="flex-1" />
        {hint && <span className="text-[11.5px] text-muted-foreground">{hint}</span>}
      </summary>
      <div className="px-5 pb-2">{children}</div>
    </details>
  );
}

export function GradeGroups({ items, cap, actions, openGroups, onToggle, highlightId, registerRow }: {
  items: TriageItem[];
  /** The campaign's resolved cap value (own or 暫用打平); null = no cap. */
  cap: number | null;
  actions: Map<string, RowAction>;
  openGroups: Set<GroupKey>;
  onToggle: (key: GroupKey, open: boolean) => void;
  highlightId: string | null;
  registerRow: (id: string, el: HTMLDivElement | null) => void;
}) {
  const grouped = new Map<GroupKey, TriageItem[]>();
  for (const item of items) {
    const key = groupOf(item);
    grouped.set(key, [...(grouped.get(key) ?? []), item]);
  }
  return (
    <div className="flex flex-col gap-2.5">
      {GROUP_ORDER.filter((key) => grouped.has(key)).map((key) => {
        const list = grouped.get(key)!.slice().sort(byCost);
        return (
          <Fold
            key={key}
            swatch={GRADE_FILL[GROUP_GRADE[key]]}
            title={key === "no_data" ? list[0].grade_label : GRADE_LABEL[GROUP_GRADE[key]]}
            count={list.length}
            hint={groupHint(key, cap)}
            open={openGroups.has(key)}
            onToggle={(open) => onToggle(key, open)}
          >
            {list.map((item) => (
              <AdRow
                key={item.entity_id}
                item={item}
                action={actions.get(item.entity_id)!}
                highlighted={item.entity_id === highlightId}
                rowRef={(el) => registerRow(item.entity_id, el)}
              />
            ))}
          </Fold>
        );
      })}
    </div>
  );
}

// A closed ad's own status chip: pause-family statuses read 已暫停, ARCHIVED 已封存; anything else (DELETED, null)
// stays the honest, generic 已關閉 rather than a raw enum value.
const CLOSED_STATUS_LABEL: Record<string, string> = {
  PAUSED: "已暫停", ADSET_PAUSED: "已暫停", CAMPAIGN_PAUSED: "已暫停", ARCHIVED: "已封存",
};
function closedStatusLabel(status: string | null): string {
  return (status && CLOSED_STATUS_LABEL[status]) || "已關閉";
}

function ClosedAdRow({ item, workspaceHref }: { item: TriageClosedItem; workspaceHref: string }) {
  const name = item.name ?? "（未命名廣告）";
  return (
    <div data-testid={`closed-ad-row-${item.entity_id}`} className={cn(ROW, "grid-cols-[40px_minmax(0,1fr)_110px_100px_auto_auto]")}>
      <AdThumb url={item.thumbnail_url} />
      <p className="min-w-0 text-sm font-semibold [overflow-wrap:anywhere]">{name}</p>
      <NumberCell label="花費" value={money(item.spend)} />
      <NumberCell label={`每次${item.result_label}成本`} value={money(item.cost_per_result)} />
      <Chip>{closedStatusLabel(item.native_status)}</Chip>
      <div className="min-w-[60px] text-right"><ActionLink action={{ label: "看紀錄", href: recordHref(workspaceHref, item.entity_id) }} /></div>
    </div>
  );
}

/** The closed ads (prototype: last, grey, folded by default): kept on record, never judged. */
export function ClosedGroup({ closed, workspaceHref, open, onToggle }: {
  closed: TriageClosedBlock; workspaceHref: string; open: boolean; onToggle: (open: boolean) => void;
}) {
  const remaining = closed.total - closed.items.length;
  return (
    <Fold
      swatch="bg-border" title="已關閉" count={closed.total} muted open={open} onToggle={onToggle}
      hint={`暫停 ${closed.paused}・已封存 ${closed.archived}・不列入判斷`}
    >
      {closed.items.map((item) => <ClosedAdRow key={item.entity_id} item={item} workspaceHref={workspaceHref} />)}
      {closed.truncated && <p className="py-2.5 text-[11.5px] text-muted-foreground">…其餘 {remaining} 則</p>}
    </Fold>
  );
}
