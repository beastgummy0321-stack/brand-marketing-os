import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import type { SettleCampaign, SettleRow, SettleView } from "@/lib/adsSettleApi";
import { cn } from "@/lib/utils";
import {
  ActionBar, Chip, GradeBar, GradeTermChip, Meter, MoneyTag, OriginTag, Term, Thumb, formatAmount, type GradeBarBucket,
} from "../patterns";
import { FROM_META, SETTLE_RULE, campaignOf, campaignShort, downloadSettleCsv, isImported, money, rangeText, yuan } from "./settleCsv";

/** F29-I12 step 1 「這期成績」 (prototype v10 `stepRes()` + `glRow()`, hash `d/settle/res`): the month's numbers,
 * the share of spend that was 划算 with its grade bar, then one card per campaign whose ads are graded against that
 * campaign's own cap. Nothing is written here; 下載 CSV saves exactly these numbers. */

const TONE_TEXT = { ok: "text-success", warn: "text-warning", bad: "text-danger", mut: "text-muted-foreground" } as const;

function Kv({ label, value, note, tone = "mut" }: { label: string; value: string; note: ReactNode; tone?: keyof typeof TONE_TEXT }) {
  return (
    <div className="min-w-0 py-0.5 md:px-5 md:first:pl-0">
      <span className="block text-xs text-muted-foreground">{label}</span>
      <b className="numeric my-0.5 block text-[22px] font-semibold tracking-tight">{value}</b>
      <span className={cn("block text-xs", TONE_TEXT[tone])}>{note}</span>
    </div>
  );
}

/** Where the whole period's cost per result sits against the campaigns' own caps (prototype `cppNote`). */
function cppNote(view: SettleView): { tone: keyof typeof TONE_TEXT; text: string } {
  const capped = view.campaigns.filter((c) => c.cap !== null);
  if (view.cost_per_result === null) return { tone: "mut", text: "還算不出來" };
  if (capped.length === 0) return { tone: "mut", text: "活動都還沒設上限，不比較" };
  const caps = capped.map((c) => (c.cap as { value: number }).value);
  const list = capped.map((c) => `${campaignShort(c.name)} ${formatAmount((c.cap as { value: number }).value)}`).join("、");
  const cpp = view.cost_per_result;
  if (cpp <= Math.min(...caps)) return { tone: "ok", text: `在每個活動自己的上限內（${list}）` };
  if (cpp <= Math.max(...caps)) return { tone: "warn", text: `介於各活動的上限之間（${list}）` };
  return { tone: "bad", text: `比每個活動的上限都高（${list}）` };
}

function budgetNote(view: SettleView): { tone: keyof typeof TONE_TEXT; text: string } {
  if (view.budget === null) return { tone: "mut", text: "這期沒設預算" };
  if (view.spent === null) return { tone: "mut", text: `這期預算 ${formatAmount(view.budget)}` };
  return view.spent <= view.budget
    ? { tone: "ok", text: `在這期預算 ${formatAmount(view.budget)} 內` }
    : { tone: "bad", text: `超出這期預算 ${money(view.spent - view.budget)}` };
}

function Numbers({ view }: { view: SettleView }) {
  const budget = budgetNote(view);
  const cpp = cppNote(view);
  return (
    <section aria-label="這期數字" className="surface grid grid-cols-2 gap-x-5 gap-y-3 px-[22px] py-5 md:grid-cols-4 md:gap-x-0 md:gap-y-0 md:divide-x md:divide-border">
      <Kv label="期間" value={rangeText(view.start, view.end)} note={`${view.days} 天・${view.status === "not_ended" ? "還沒結束" : "已結束"}`} />
      <Kv label="花費" value={money(view.spent)} note={budget.text} tone={budget.tone} />
      <Kv
        label="購買" value={view.results === null ? "未知" : `${formatAmount(view.results)} 筆`}
        note={view.on_target_results === null ? "划算的廣告賣了幾筆還不知道" : `${formatAmount(view.on_target_results)} 筆來自划算的廣告`}
        tone={view.on_target_results ? "ok" : "mut"}
      />
      <Kv label="每賣一筆花多少" value={yuan(view.cost_per_result)} note={cpp.text} tone={cpp.tone} />
    </section>
  );
}

/** One break-even for the rules line only when every campaign shares it; otherwise the term stays without a value. */
function sharedBreakEven(campaigns: SettleCampaign[]): number | null {
  const values = new Set(campaigns.map((c) => c.break_even));
  return values.size === 1 ? [...values][0] : null;
}

function Share({ view }: { view: SettleView }) {
  const pct = view.on_target_spend_share === null ? null : Math.round(view.on_target_spend_share * 100);
  const buckets: GradeBarBucket[] = view.buckets.map((b) => ({ grade: b.grade, amount: b.amount, count: b.count }));
  return (
    <section aria-label="花得划算的比例" className="surface px-[22px] py-5">
      <div className="mb-1.5 flex flex-wrap items-baseline gap-3">
        <span className={cn("numeric text-[30px] font-semibold tracking-tight", pct === null ? "text-muted-foreground" : "text-success")}>
          {pct === null ? "—" : `${pct}%`}
        </span>
        <span className="text-base font-medium">的錢花得<Term k="on_target">划算</Term></span>
      </div>
      <GradeBar buckets={buckets} withMoney breakEven={sharedBreakEven(view.campaigns)} />
      <div className="mt-2 text-xs text-muted-foreground">
        <i aria-hidden="true" className="mr-[5px] inline-block size-2 rounded-[2px] bg-primary" />{SETTLE_RULE}
      </div>
    </section>
  );
}

const FATE_TEXT = {
  effective: { text: "記成有效", cls: "text-success" },
  ineffective: { text: "記成無效", cls: "text-danger" },
  skip: { text: "不記", cls: "text-muted-foreground" },
} as const;

/** The sample gate in words (ads.md §6.17 ruling: spend ≥ 3 × cap, or ≥ 10 results over ≥ 7 days). */
function gateText(cap: number | null): string {
  return cap === null ? "（要跑滿 7 天賣出 10 筆）" : `（要花到 ${money(3 * cap)}，或跑滿 7 天賣出 10 筆）`;
}

/** Prototype `glRow()`: thumbnail, name + ad set, the cost against the cap (or why it is not graded), grade + fate. */
export function GradedRow({ row }: { row: SettleRow }) {
  const cap = row.cap;
  const graded = cap !== null && (row.grade === "on_target" || row.grade === "watch" || row.grade === "over" || row.grade === "wasted");
  const thin = !graded;
  let viz: ReactNode;
  if (!graded) {
    const lead = row.grade === "insufficient" && row.grade_label !== "資料不足"
      ? <><Term k="thin">{row.grade_label}</Term>，這期不記</>
      : <>{row.grade_label}，這期不記</>;
    viz = (
      <>
        <div className="text-[13px] font-medium">{lead}</div>
        <div className="text-[11.5px]">
          花 {money(row.spend)}・{row.results === null ? "筆數未知" : `${formatAmount(row.results)} 筆`}
          {row.grade === "insufficient" && row.grade_label !== "資料不足" && gateText(cap)}
        </div>
      </>
    );
  } else if (row.grade === "wasted") {
    const line = 3 * cap;
    viz = (
      <Meter
        value={row.spend} max={line * 1.4} marker={line} tone="danger"
        left={<>花 {money(row.spend)}・0 筆</>}
        right={<>花到 {formatAmount(line)} 還一筆都沒賣，就算「<Term k="wasted">沒賣出</Term>」</>}
      />
    );
  } else {
    viz = (
      <Meter
        value={row.cost_per_result} max={cap * 1.6} marker={cap}
        tone={row.grade === "on_target" ? "success" : row.grade === "watch" ? "warning" : "danger"}
        left={<>每筆 {yuan(row.cost_per_result)}<MoneyTag cost={row.cost_per_result} breakEven={row.break_even} /></>}
        right={<>上限 {formatAmount(cap)}</>}
      />
    );
  }
  const fate = FATE_TEXT[row.fate];
  return (
    <li data-fate={row.fate} className={cn(
      "grid grid-cols-[36px_minmax(0,1fr)_auto] items-center gap-3.5 border-t border-border py-[11px] first:border-t-0 md:grid-cols-[40px_minmax(0,1fr)_minmax(150px,230px)_104px]",
      thin && "text-muted-foreground",
    )}>
      <span className={cn(thin && "opacity-55 grayscale")}><Thumb url={row.thumbnail_url} size={40} /></span>
      <div className="min-w-0">
        <div className={cn("font-medium [overflow-wrap:anywhere]", !thin && "text-foreground")}>{row.name ?? "（未命名廣告）"}</div>
        {row.group_name && <div className="text-[11.5px] text-muted-foreground [overflow-wrap:anywhere]">{row.group_name}</div>}
      </div>
      <div className="col-span-2 col-start-2 row-start-2 md:col-span-1 md:col-start-auto md:row-start-auto">{viz}</div>
      <div className="col-start-3 row-start-1 flex flex-col items-end text-right md:col-start-auto md:row-start-auto">
        {thin ? <Chip tone="neutral">不記</Chip> : (
          <>
            <GradeTermChip grade={row.grade} label={row.grade_label} />
            <div className={cn("mt-1 text-[11.5px]", fate.cls)}>{row.skip_reason ?? fate.text}</div>
          </>
        )}
      </div>
    </li>
  );
}

function capChip(campaign: SettleCampaign): ReactNode {
  const who = campaignShort(campaign.name);
  if (campaign.cap === null) return <Chip tone="neutral">{who}沒設上限</Chip>;
  const word = campaign.cap.basis === "break_even" ? "暫用打平線" : "的上限";
  return <Chip tone="accent">{who}{word} {formatAmount(campaign.cap.value)}</Chip>;
}

export function CampaignCard({ view, campaign }: { view: SettleView; campaign: SettleCampaign }) {
  const rows = view.rows.filter((row) => row.campaign_id === campaign.campaign_id);
  const status = campaign.data_status;
  return (
    <section aria-label={campaign.name} className="surface px-[22px] py-5">
      <div className="mb-3.5 flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex min-w-0 flex-wrap items-center gap-2 text-[15px] font-semibold">
          <span className="[overflow-wrap:anywhere]">{campaign.name}</span>
          {isImported(campaign.origin) && <OriginTag>{FROM_META}</OriginTag>}
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          {status.state !== "ready" && status.label && <Chip tone="warn">{status.label}</Chip>}
          {capChip(campaign)}
        </div>
      </div>
      <ol>{rows.map((row) => <GradedRow key={row.entity_id} row={row} />)}</ol>
    </section>
  );
}

/** The campaigns in the order the rows name them (a row whose campaign is gone still gets its own card). */
export function settleCampaigns(view: SettleView): SettleCampaign[] {
  const seen = new Map<string, SettleCampaign>();
  for (const campaign of view.campaigns) seen.set(campaign.campaign_id, campaign);
  for (const row of view.rows) if (!seen.has(row.campaign_id)) seen.set(row.campaign_id, campaignOf(view, row));
  return [...seen.values()].filter((c) => view.rows.some((row) => row.campaign_id === c.campaign_id));
}

export function SettleResult({ view, header, homeHref, angleHref, noteHref }: {
  view: SettleView; header: ReactNode; homeHref: string; angleHref: string; noteHref: string;
}) {
  const open = view.status === "open";
  return (
    <>
      <div className="flex max-w-[1260px] flex-col gap-4">
        {header}
        <Numbers view={view} />
        <Share view={view} />
        {view.rows.length === 0 && (
          <p className="surface px-[22px] py-5 text-sm text-muted-foreground">這期沒有花到錢的廣告，沒有要記的。</p>
        )}
        {settleCampaigns(view).map((campaign) => <CampaignCard key={campaign.campaign_id} view={view} campaign={campaign} />)}
      </div>
      <div className="flex-1" />
      <ActionBar
        back={{ label: "投放中心", to: homeHref }}
        exit={open ? { label: "晚點再結算", to: homeHref } : undefined}
        hint={open ? "這一步還不會寫進筆記本" : view.status === "not_ended" ? "這個月還沒結束，結束後才能結算" : undefined}
      >
        <Button variant="outline" onClick={() => downloadSettleCsv(view)}>下載 CSV</Button>
        {view.status === "written"
          ? <Button asChild><Link to={noteHref}>看寫進筆記本的內容 →</Link></Button>
          : open
            ? <Button asChild><Link to={angleHref}>下一步：確認主打什麼 →</Link></Button>
            : <Button disabled>下一步：確認主打什麼 →</Button>}
      </ActionBar>
    </>
  );
}
