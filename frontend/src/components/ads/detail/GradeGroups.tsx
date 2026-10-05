import { campaignPath } from "@/lib/adsRoutes";
import { useEffect, useState, type ReactNode } from "react";
import { Image as ImageIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { cn } from "@/lib/utils";
import type { QueueItem, TriageClosedBlock, TriageClosedItem, TriageItem } from "@/lib/adsTriageApi";
import {
  Chip, GRADE_FILL, MoneyTag, Term, formatAmount, gradeWord, sampleWords, unsoldLine, useAdsRules, watchLine,
  type AdsRules, type Grade,
} from "../patterns";
import { cleanupAction, proposalAction } from "../home/status";
import { perSaleAmount } from "../patterns/csv";

/** F28-I10, v10 F29-I13: the campaign detail's grade groups (prototype v10 `tabPerf()` groups + `row` + `menu()`).
 * Every active ad arrives already graded against the campaign's one cap (`TriageItem.grade`/`grade_label`, Feature
 * F28 "Grades"); this file only groups, orders and labels them, picks each row's one decision button (在清理提議／去處理,
 * none otherwise) and places the row's 「⋯」 menu, which the page supplies (換掉這一則／看紀錄). Every cost per purchase
 * carries its money tag against break-even (`MoneyTag`, Contract K). */

/** One group per grade, in the prototype's `ORDER` (沒賣出, 太貴, 偏貴, 划算, 剛開始). `insufficient` splits by the
 * backend's own `reason_code` (`too_new` = 剛開始、數字還不夠, any other = 資料不足, F48 Contract R) so the two honest
 * reasons never share a heading; `no_target` (no cap at all) comes last. */
export type GroupKey = "wasted" | "over" | "watch" | "on_target" | "thin" | "no_data" | "no_target";
export const GROUP_ORDER: GroupKey[] = ["wasted", "over", "watch", "on_target", "thin", "no_data", "no_target"];
/** Prototype: 沒賣出／太貴／偏貴 open, everything else folded. */
export const OPEN_BY_DEFAULT: GroupKey[] = ["wasted", "over", "watch"];

const GROUP_GRADE: Record<GroupKey, Grade> = {
  wasted: "wasted", over: "over", watch: "watch", on_target: "on_target",
  thin: "insufficient", no_data: "insufficient", no_target: "no_target",
};

export function groupOf(item: TriageItem): GroupKey {
  if (item.grade === "insufficient") return item.reason_code === "too_new" ? "thin" : "no_data";
  return item.grade;
}

/** The summary's right-hand hint (prototype `tabPerf()`), from the cap T and the served grade bands the kit ruler
 * draws (偏貴 up to the served band, 沒賣出／剛開始 against the served spend line; F48 Contract R-API). No cap, rules not
 * loaded yet, or a reason that is not about the spend line (資料不足), prints no hint rather than an invented one. */
function groupHint(key: GroupKey, cap: number | null, rules: AdsRules | null): string | null {
  if (cap === null || rules === null) return null;
  const f = (v: number) => formatAmount(v) as string;
  switch (key) {
    case "wasted": return `花到 ${f(unsoldLine(rules, cap))} 元還沒賣出`;
    case "over": return `每筆超過 ${f(watchLine(rules, cap))} 元`;
    case "watch": return `每筆 ${f(cap)}–${f(watchLine(rules, cap))} 元`;
    case "on_target": return `每筆不到 ${f(cap)} 元`;
    case "thin": return `還沒花到 ${f(unsoldLine(rules, cap))} 元`;
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

/** Where an ad leads (prototype `row`): an ad inside this campaign's open cleanup row → 在清理提議 (the cleanup
 * decision, 沒賣出 + 太貴 are one decision); else its own open `stop_loss`／`worse` row → 去處理; else 看紀錄 on the
 * workspace performance tab (the row shows no button then — 看紀錄 is in its 「⋯」 menu; a ruler dot still goes there).
 * A row whose proposal is already done no longer counts as open. */
export interface RowAction { label: "在清理提議" | "去處理" | "看紀錄"; href: string }

export function recordHref(brandId: string, campaignId: string, entityId: string) {
  return campaignPath(brandId, campaignId, {tab: "perf", ad: entityId});
}

/** The open cleanup decision of this campaign (its step href and ads), or null once it is done. */
export function openCleanup(brandId: string, campaignId: string, queue: QueueItem[]): { href: string; ids: Set<string> } | null {
  const row = queue.find((q) => q.kind_key === "cleanup" && q.cleanup?.campaign_id === campaignId);
  const step = row ? cleanupAction(brandId, campaignId, row.proposal, row.action_url) : null;
  if (!row || !step || step.done) return null;
  return { href: step.href, ids: new Set(row.cleanup!.ads.map((ad) => ad.entity_id)) };
}

export function adActions(
  brandId: string, campaignId: string, items: TriageItem[], queue: QueueItem[],
): Map<string, RowAction> {
  const actions = new Map<string, RowAction>();
  const cleanup = openCleanup(brandId, campaignId, queue);
  for (const item of items) {
    const id = item.entity_id;
    if (cleanup?.ids.has(id)) {
      actions.set(id, { label: "在清理提議", href: cleanup.href });
      continue;
    }
    const own = queue.find((q) => q.triage.entity_id === id && (q.kind_key === "stop_loss" || q.kind_key === "worse"));
    const step = own
      ? proposalAction(brandId, campaignId, id, own.proposal, own.kind_key === "worse" ? "review" : "pause")
      : null;
    actions.set(id, step && !step.done
      ? { label: "去處理", href: step.href }
      : { label: "看紀錄", href: recordHref(brandId, campaignId, id) });
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
const perSale = (v: number | null) => (perSaleAmount(v) === null ? "未知" : `${perSaleAmount(v)} 元`);

const isPurchase = (item: TriageItem) =>
  item.current.result_kind === "purchase" || (item.current.result_kind === null && item.target.result_kind === "purchase");

/** The per-result column (prototype: 每賣一筆 + money tag ／ 購買 0 筆 ／ 剛開始). Purchases read 每賣一筆 and carry the
 * money tag against break-even (hidden when either number is unknown); other result kinds name their own result
 * (`result_label` from the backend, never re-worded) and get no money tag — break-even is per sale. */
function ResultCell({ item, breakEven }: { item: TriageItem; breakEven: number | null }) {
  const m = item.current;
  if (item.grade === "wasted") return <NumberCell label={m.result_label} value="0 筆" />;
  const purchase = isPurchase(item);
  const label = purchase ? "每賣一筆" : `每次${m.result_label}成本`;
  if (item.grade === "insufficient") {
    const word = item.reason_code === "too_new" ? <Term k="thin">{item.grade_label}</Term> : item.grade_label;
    return <NumberCell label={label} value={<span className="text-[13px] font-medium text-muted-foreground">{word}</span>} />;
  }
  return (
    <NumberCell label={label} value={perSale(m.cost_per_result)}>
      {purchase && <MoneyTag cost={m.cost_per_result} breakEven={breakEven} className="block" />}
    </NumberCell>
  );
}

function NumberCell({ label, value, children }: { label: string; value: ReactNode; children?: ReactNode }) {
  return (
    <div className="text-right">
      <span className="block text-[11.5px] text-muted-foreground">{label}</span>
      <b className="numeric text-[15px] font-semibold whitespace-nowrap">{value}</b>
      {children}
    </div>
  );
}

/** The row's decision button: only 在清理提議／去處理; 看紀錄 lives in the 「⋯」 menu (prototype v10 `row`). */
function DecisionLink({ action }: { action: RowAction }) {
  if (action.label === "看紀錄") return null;
  return <Button asChild variant="outline" size="sm"><Link to={action.href}>{action.label}</Link></Button>;
}

/** The grades a cost or a known zero ranks (the sample chips show beside these only; 剛開始／資料不足 already say it). */
const GRADED = new Set<Grade>(["on_target", "watch", "over", "wasted"]);

// Prototype `.adrow`: 40px thumb · name + trend note · 花費 · per result · decision + menu.
const ROW = "grid grid-cols-[40px_minmax(0,1fr)_110px_100px_auto] items-center gap-3.5 border-t border-border py-[11px] first:border-t-0";

/** What the page adds to a row: its 「⋯」 menu, whether a 換掉這一則 request is open, and the last failure of one. */
export interface RowExtras { menu: ReactNode; requestOpen: boolean; error: string | null }

function AdRow({ item, action, breakEven, extras, highlighted, rowRef, pauseHref }: {
  item: TriageItem; action: RowAction; breakEven: number | null; extras: RowExtras | null;
  highlighted: boolean; rowRef: (el: HTMLDivElement | null) => void; pauseHref: string | null;
}) {
  const name = item.name ?? "（未命名廣告）";
  const rules = useAdsRules();
  // F48 Contract R: a small sample beside a graded ad (樣本少) — shown, never a gate.
  const sample = GRADED.has(item.grade) ? sampleWords(rules, item.sample) : [];
  return (
    <div ref={rowRef} data-testid={`ad-row-${item.entity_id}`} className={cn(ROW, highlighted && "-mx-2 rounded-lg bg-accent/60 px-2 ring-1 ring-inset ring-primary")}>
      <AdThumb url={item.thumbnail_url} />
      <div className="min-w-0">
        <p className="text-sm font-medium [overflow-wrap:anywhere]">{name}</p>
        <p className="text-[11.5px] text-muted-foreground">
          {trendNote(item)}
          {sample.map((word) => <Chip key={word} data-part="sample" className="ml-1.5 py-0.5 align-middle">{word}</Chip>)}
          {extras?.requestOpen && <Chip tone="accent" className="ml-1.5 py-0.5 align-middle">換掉這一則・需求已開</Chip>}
        </p>
        {extras?.error && <p role="alert" className="text-[11.5px] font-medium text-danger">{extras.error}</p>}
      </div>
      <NumberCell label="花費" value={money(item.current.spend)} />
      <ResultCell item={item} breakEven={breakEven} />
      <div className="flex min-w-[92px] items-center justify-end gap-1.5">
        <DecisionLink action={action} />
        {pauseHref && <Button asChild variant="outline" size="sm"><Link to={pauseHref}>暫停</Link></Button>}
        {extras?.menu}
      </div>
    </div>
  );
}

/** Rows inside a group: most expensive per result first (prototype), unknown cost last, then by spend. */
function byCost(a: TriageItem, b: TriageItem) {
  const ca = a.current.cost_per_result, cb = b.current.cost_per_result;
  if (ca !== cb) return (cb ?? -1) - (ca ?? -1);
  if (a.current.spend == null) return b.current.spend == null ? 0 : 1;
  if (b.current.spend == null) return -1;
  return b.current.spend - a.current.spend;
}

/** One `<details>` shell for a grade group and the closed group (prototype `.grp`): swatch, title, count chip, hint. */
function Fold({ swatch, title, count, hint, open, onToggle, muted = false, children }: {
  swatch: string; title: string; count: number | null; hint: string | null; open: boolean;
  onToggle: (open: boolean) => void; muted?: boolean; children: ReactNode;
}) {
  return (
    // No `overflow-hidden`: it would clip the summary's 3px focus outline. `.surface` sets its own background, which a
    // `bg-muted` utility cannot override, so the grey closed fold spells out the same border and radius instead.
    <details open={open} onToggle={(e) => onToggle(e.currentTarget.open)} className={cn("group", muted ? "min-w-0 rounded-xl border border-border bg-muted" : "surface")}>
      <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2.5 px-5 py-[13px] [&::-webkit-details-marker]:hidden">
        <span aria-hidden="true" className={cn("size-3 shrink-0 rounded-[3px]", swatch)} />
        <b className="text-sm font-semibold">{title}</b>
        {count !== null && <Chip>{count} 則</Chip>}
        <span className="flex-1" />
        {hint && <span className="text-[11.5px] text-muted-foreground">{hint}</span>}
      </summary>
      <div className="px-5 pb-2">{children}</div>
    </details>
  );
}

export function GradeGroups({ items, cap, breakEven = null, dataReason = null, actions, extras, pauseHref, openGroups, onToggle, highlightId, registerRow }: {
  items: TriageItem[];
  /** The campaign's resolved cap value (own or 暫用打平); null = no cap. */
  cap: number | null;
  /** The campaign's break-even per sale (money tags); null = unknown, no tag. */
  breakEven?: number | null;
  /** The campaign's one "why no data" sentence (`data.status.label`) when its data is not whole: the 資料不足 group's
   * hint. Never re-derived here. */
  dataReason?: string | null;
  actions: Map<string, RowAction>;
  extras?: (item: TriageItem) => RowExtras;
  /** F45-I06 (ads.md §6.49): every active row's 「暫停」 → the pause page that reads the ad itself (`from=perf`). */
  pauseHref?: (item: TriageItem) => string;
  openGroups: Set<GroupKey>;
  onToggle: (key: GroupKey, open: boolean) => void;
  highlightId: string | null;
  registerRow: (id: string, el: HTMLDivElement | null) => void;
}) {
  const rules = useAdsRules();
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
            title={list[0].grade_label || gradeWord(rules, GROUP_GRADE[key], list[0].reason_code) || ""}
            count={list.length}
            hint={key === "no_data" ? dataReason : groupHint(key, cap, rules)}
            open={openGroups.has(key)}
            onToggle={(open) => onToggle(key, open)}
          >
            {list.map((item) => (
              <AdRow
                key={item.entity_id}
                item={item}
                action={actions.get(item.entity_id)!}
                breakEven={breakEven}
                extras={extras ? extras(item) : null}
                highlighted={item.entity_id === highlightId}
                rowRef={(el) => registerRow(item.entity_id, el)}
                pauseHref={pauseHref ? pauseHref(item) : null}
              />
            ))}
          </Fold>
        );
      })}
    </div>
  );
}

/** Prototype v10 closed row: thumb, name, status — kept on record, never judged, so no numbers and no decision. The
 * status is the served delivery word (F49 Contract L: the platform adapter's status table), never a local map. */
function ClosedAdRow({ item }: { item: TriageClosedItem }) {
  const name = item.name ?? "（未命名廣告）";
  return (
    <div data-testid={`closed-ad-row-${item.entity_id}`} className={cn(ROW, "grid-cols-[40px_minmax(0,1fr)_auto]")}>
      <AdThumb url={item.thumbnail_url} />
      <p className="min-w-0 text-sm font-medium [overflow-wrap:anywhere]">{name}</p>
      <Chip>{item.delivery?.label ?? item.delivery_label}</Chip>
    </div>
  );
}

/** The closed ads (prototype v10: under the 不在投的 heading, last, grey, folded by default): kept on record, never
 * judged, not counted in the active number above. The hint counts them by the served delivery groups (`groups`, first
 * seen first; they add up to `total`). */
export function ClosedGroup({ closed, open, onToggle }: {
  closed: TriageClosedBlock; open: boolean; onToggle: (open: boolean) => void;
}) {
  const remaining = closed.total - closed.items.length;
  const counts = (closed.groups ?? []).map((g) => `${g.label} ${g.count}`);
  return (
    <section aria-label="不在投的">
      <h2 className="mt-3 mb-2.5 text-[15px] font-semibold text-muted-foreground">不在投的</h2>
      <Fold
        swatch="bg-border" title={`共 ${closed.total} 則`} count={null} muted open={open} onToggle={onToggle}
        hint={[...counts, "不算在上面的在投數量裡"].join("・")}
      >
        {closed.items.map((item) => <ClosedAdRow key={item.entity_id} item={item} />)}
        {closed.truncated && <p className="py-2.5 text-[11.5px] text-muted-foreground">…其餘 {remaining} 則</p>}
      </Fold>
    </section>
  );
}
