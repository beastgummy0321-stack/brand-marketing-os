import { useState } from "react";
import { Link } from "react-router-dom";
import type { LearningCampaign, LearningRow } from "@/lib/adsLearningsApi";
import { cn } from "@/lib/utils";
import { Chip, formatAmount } from "../patterns/Chip";

/** Money as the prototype prints it (`fmt`): whole units, thousands separators. */
export function learnMoney(value: number | null | undefined): string {
  return formatAmount(value === null || value === undefined ? null : Math.round(value)) ?? "—";
}

/** `YYYY-MM-DD` → `MM/DD`; anything else prints nothing (never a raw ISO string). */
export function shortDate(iso: string | null | undefined): string | null {
  const m = /^\d{4}-(\d{2})-(\d{2})/.exec(iso ?? "");
  return m ? `${m[1]}/${m[2]}` : null;
}

const isKeep = (row: LearningRow) => row.verdict !== "replace";

/** The verdict as served (`verdict_label`) plus every flag as a warn chip. */
export function VerdictChips({ row }: { row: LearningRow }) {
  return (
    <>
      <Chip tone={isKeep(row) ? "ok" : "bad"} data-verdict={row.verdict}>{row.verdict_label}</Chip>
      {row.flags.map((flag) => <Chip key={flag} tone="warn">{flag}</Chip>)}
    </>
  );
}

// Prototype `.lt-row`: 8 columns wide; ≤ 900px the cells regroup into four lines (rank+name+toggle, group,
// three numbers, verdict). Compact (`.lt.cp`) drops 花費／成交 and puts the group under the name.
const ROW_WIDE = "grid grid-cols-[28px_minmax(0,2.1fr)_minmax(0,1.1fr)_76px_52px_82px_minmax(0,1.7fr)_64px] gap-x-3 px-4 py-2.5";
const ROW_COMPACT = "grid grid-cols-[22px_minmax(0,1fr)_64px_auto_52px] gap-x-3 px-3 py-[9px]";
const ROW_NARROW =
  "max-[900px]:grid-cols-[22px_repeat(3,minmax(0,1fr))_auto] max-[900px]:gap-x-2 max-[900px]:gap-y-1 max-[900px]:p-3 " +
  "max-[900px]:[grid-template-areas:'rk_ad_ad_ad_tg'_'._gp_gp_gp_gp'_'._sp_sa_pe_pe'_'._vd_vd_vd_vd']";
const NUM = "text-right tabular-nums max-[900px]:flex max-[900px]:flex-col max-[900px]:text-left max-[900px]:text-[13px]";

function NumLabel({ children }: { children: string }) {
  return <span className="hidden text-[11px] font-normal text-muted-foreground max-[900px]:block">{children}</span>;
}

function RankedRow({ row, cap, compact, idPrefix }: { row: LearningRow; cap: number | null; compact: boolean; idPrefix: string }) {
  const [open, setOpen] = useState(false);
  const panelId = `${idPrefix}-co-${row.ad_id}`;
  const out = !isKeep(row);
  const per = row.cost_per_sale;
  const group = row.customer_group?.who ?? "未指定";
  const perCell = (
    <span
      data-slot="per-sale"
      className={cn(NUM, "font-bold max-[900px]:[grid-area:pe]", per === null ? "font-medium text-muted-foreground" : cap !== null && per <= cap && "text-success")}
    >
      <NumLabel>每筆成本</NumLabel>
      {per === null ? "沒賣出" : learnMoney(per)}
    </span>
  );
  const toggle = (
    <button
      type="button"
      aria-expanded={open}
      aria-controls={panelId}
      aria-label={`座標：${row.ad_name}`}
      onClick={() => setOpen((v) => !v)}
      className="justify-self-end whitespace-nowrap py-1 text-[12.5px] font-medium text-primary max-[900px]:[grid-area:tg]"
    >
      座標 <span aria-hidden="true" className="text-[10px]">{open ? "▴" : "▾"}</span>
    </button>
  );
  return (
    <div
      role="row"
      data-ad={row.ad_id}
      data-verdict={row.verdict}
      className={cn(compact ? ROW_COMPACT : ROW_WIDE, ROW_NARROW, "items-center border-t border-border")}
    >
      <span className="text-[12.5px] font-bold text-muted-foreground max-[900px]:[grid-area:rk]">{row.rank}</span>
      {compact ? (
        <span className={cn("min-w-0 font-semibold [overflow-wrap:anywhere] max-[900px]:[grid-area:ad]", out && "text-muted-foreground")}>
          {row.ad_name}
          <span className="block text-xs font-normal text-muted-foreground">{group}</span>
        </span>
      ) : (
        <>
          <span className={cn("min-w-0 font-semibold [overflow-wrap:anywhere] max-[900px]:[grid-area:ad]", out && "text-muted-foreground")}>{row.ad_name}</span>
          <span className={cn("min-w-0 text-[13px] max-[900px]:text-[12.5px] max-[900px]:[grid-area:gp]", (out || !row.customer_group) && "text-muted-foreground", "max-[900px]:text-muted-foreground")}>
            {group}
          </span>
          <span className={cn(NUM, "max-[900px]:[grid-area:sp]")}><NumLabel>花費</NumLabel>{learnMoney(row.spend)}</span>
          <span className={cn(NUM, "max-[900px]:[grid-area:sa]")}><NumLabel>成交</NumLabel>{row.sales}</span>
        </>
      )}
      {perCell}
      <span className="flex flex-wrap gap-[5px] max-[900px]:mt-1 max-[900px]:[grid-area:vd]"><VerdictChips row={row} /></span>
      {toggle}
      {open && (
        <div
          id={panelId}
          className="col-span-full mt-2.5 mb-0.5 grid grid-cols-3 gap-x-[18px] gap-y-2 rounded-lg bg-background px-3.5 py-2.5 max-[900px]:grid-cols-2 max-[900px]:px-3 max-[900px]:[grid-area:auto]"
        >
          {row.coordinates.length === 0 && <p className="col-span-full text-[13px] text-muted-foreground">這則廣告沒有記到座標。</p>}
          {row.coordinates.map((c) => (
            <div key={c.dimension} className="flex min-w-0 flex-col text-[13px]">
              <span className="text-[11.5px] text-muted-foreground">{c.dimension_label}</span>
              <b className="font-medium [overflow-wrap:anywhere]">{c.label}</b>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** One closed campaign's ranked table (prototype `learnTable`): header chips 〈closed_on〉 結案・上限・花／成交／每筆・
 * 留下 N・換掉 M, the served `rule_text`, then every ad in the served rank order with its coordinates folded.
 *
 * - `compact` — the strategy basis / closeout result variant: no 花費／成交 columns, no totals chip, no campaign link.
 * - `highlight` — the campaign the closeout just pointed at (`?campaign=`): ring + 「剛結案」 chip.
 * - `campaignHref` — app path of the campaign; shows 「到這個活動 →」 (wide only).
 * A campaign with `empty_reason` prints that sentence instead of a table. */
export function LearningsTable({ campaign, compact = false, highlight = false, campaignHref }: {
  campaign: LearningCampaign;
  compact?: boolean;
  highlight?: boolean;
  campaignHref?: string;
}) {
  const c = campaign;
  const closed = shortDate(c.closed_on);
  const hasRows = c.rows.length > 0;
  const idPrefix = `${compact ? "p" : "l"}-${c.campaign_id}`;
  return (
    <section
      id={`camp-${c.campaign_id}`}
      aria-label={c.campaign_name}
      data-highlight={highlight || undefined}
      className={cn(
        "overflow-hidden rounded-xl border border-border bg-card transition-shadow duration-300",
        highlight && "border-[#a397e9] shadow-[0_0_0_3px_var(--color-accent)]",
      )}
    >
      <div className={cn("flex flex-wrap items-start justify-between gap-3", compact ? "p-3" : "px-4 pt-3.5 pb-2.5")}>
        <div className="flex min-w-0 flex-col gap-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <b className="text-[15px]">{c.campaign_name}</b>
            {highlight && <Chip tone="accent">剛結案</Chip>}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {closed && <Chip className="border border-border bg-transparent">{closed} 結案</Chip>}
            {c.cap !== null && <Chip className="border border-border bg-transparent">上限 {learnMoney(c.cap)}</Chip>}
            {!compact && hasRows && (
              <Chip className="border border-border bg-transparent">
                花 {learnMoney(c.spend)}・成交 {c.sales ?? 0}・{c.cost_per_sale === null ? "沒賣出" : `每筆 ${learnMoney(c.cost_per_sale)}`}
              </Chip>
            )}
            {hasRows && <Chip tone="ok">留下 {c.counts.keep}</Chip>}
            {hasRows && <Chip tone="bad">換掉 {c.counts.replace}</Chip>}
          </div>
          {hasRows && <p className="text-[12.5px] text-muted-foreground">{c.rule_text}</p>}
        </div>
        {!compact && campaignHref && (
          <Link to={campaignHref} className="whitespace-nowrap text-[13px] font-medium text-primary hover:underline">到這個活動 →</Link>
        )}
      </div>
      {hasRows ? (
        <div role="table" aria-label={`${c.campaign_name} 每則廣告排名`} className="flex flex-col">
          <div
            role="row"
            className={cn(
              compact ? ROW_COMPACT : ROW_WIDE,
              "border-t border-border bg-background py-[7px] text-xs text-muted-foreground max-[900px]:hidden",
            )}
          >
            <span role="columnheader">#</span>
            {compact ? (
              <>
                <span role="columnheader">廣告｜顧客群</span>
                <span role="columnheader" className="text-right">每筆</span>
              </>
            ) : (
              <>
                <span role="columnheader">廣告</span>
                <span role="columnheader">顧客群</span>
                <span role="columnheader" className="text-right">花費</span>
                <span role="columnheader" className="text-right">成交</span>
                <span role="columnheader" className="text-right">每筆成本</span>
              </>
            )}
            <span role="columnheader">判定</span>
            <span role="columnheader"><span className="sr-only">座標</span></span>
          </div>
          {c.rows.map((row) => (
            <RankedRow key={row.ad_id} row={row} cap={c.cap} compact={compact} idPrefix={idPrefix} />
          ))}
        </div>
      ) : (
        <p data-slot="empty-reason" className="border-t border-border px-4 py-3 text-[13px] text-muted-foreground">
          {c.empty_reason ?? "這期沒有記學習"}
        </p>
      )}
    </section>
  );
}
