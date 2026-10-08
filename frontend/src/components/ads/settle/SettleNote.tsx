import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import type { SettleRow, SettleView } from "@/lib/adsSettleApi";
import { ActionBar, FlowTo, LearnLine, OriginTag, ResultHero } from "../patterns";
import { useOrgClock } from "@/lib/orgClock";
import { angleOf, learnRows, type AnglePicks } from "./SettleAngles";
import { FROM_META, campaignOf, isImported, money, rangeText, stampText, yuan } from "./settleCsv";

/** F29-I12 step 3 「寫進筆記本」 (prototype v10 `stepNote()`, hash `d/settle/note` before and after `settleWrite`):
 * the learnings in two groups, one POST for all of them, then the written state — what was written, how the brand
 * notebook grew, and where it goes next. The learning text itself carries no numbers (Feature F29 decisions); the
 * cost is printed beside it. */

function Learning({ view, row, angle }: { view: SettleView; row: SettleRow; angle: string }) {
  const campaign = campaignOf(view, row);
  const good = row.fate === "effective";
  const unknown = row.fate === "skip";
  const cost = row.cost_per_result;
  const title = <>
        「{angle}」・{unknown ? "目前待核實" : good ? "本期成本達標" : "本期成本未達標"}
      </>;
  const meta = <span className="inline-flex flex-wrap items-center">
        <span className="[overflow-wrap:anywhere]">{campaign.name}</span>
        {isImported(campaign.origin) && <span className="mx-1"><OriginTag>{FROM_META}</OriginTag></span>}
        {row.group_name && <span>・{row.group_name}</span>}
        <span>・花 {money(row.spend, row.currency)}・每筆成果 {yuan(cost, row.currency)}</span>
        {row.cap !== null && <span>・上限 {money(row.cap, row.cap_comparison?.currency)}</span>}
        {row.cap_comparison?.reason && <span>・{row.cap_comparison.message ?? "上限單位尚未核實"}</span>}
        {unknown && <span>・{row.skip_reason ?? "當前來源資格尚未核實"}</span>}
      </span>;
  if (unknown) return <div className="grid grid-cols-[28px_minmax(0,1fr)] items-center gap-3 border-t border-border py-3 first:border-t-0">
    <span aria-hidden="true" className="grid size-[26px] place-items-center rounded-lg bg-muted text-muted-foreground">?</span>
    <div className="min-w-0"><b className="font-semibold">{title}</b><div className="mt-0.5 text-[11.5px] text-muted-foreground">{meta}</div></div>
  </div>;
  return <LearnLine tone={good ? "ok" : "no"} title={title} meta={meta} />;
}

function Groups({ view, rows, written = false }: { view: SettleView; rows: { row: SettleRow; angle: string }[]; written?: boolean }) {
  const good = rows.filter((x) => x.row.fate === "effective");
  const bad = rows.filter((x) => x.row.fate === "ineffective");
  const unknown = rows.filter((x) => x.row.fate === "skip");
  const card = (title: string, cls: string, note: string, list: typeof rows) => (
    <section aria-label={title} className="surface px-[22px] py-5">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
        <h2 className={`text-[15px] font-semibold ${cls}`}>{title}</h2>
        <span className="text-xs text-muted-foreground">{note}</span>
      </div>
      {list.length === 0
        ? <p className="py-3 text-sm text-muted-foreground">這期沒有</p>
        : list.map((x) => <Learning key={x.row.entity_id} view={view} row={x.row} angle={x.angle} />)}
    </section>
  );
  return (
    <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-2">
      {card(`目前成本達標 ${good.length} 條`, "text-success", "當前成本符合上限", good)}
      {card(`目前成本未達標 ${bad.length} 條`, "text-danger", "成本偏高或尚無成果", bad)}
      {written && unknown.length > 0 && card(`目前待核實 ${unknown.length} 條`, "text-muted-foreground", "保留已寫紀錄，不視為當前可沿用", unknown)}
    </div>
  );
}

export function SettleNote({ view, header, picks, busy, error, onWrite, homeHref, angleHref, continuation, next }: {
  view: SettleView; header: ReactNode; picks: AnglePicks; busy: boolean; error: string | null; onWrite: () => void;
  homeHref: string; angleHref: string; continuation?: ReactNode; next: { href: string } | null;
}) {
  const { timezone } = useOrgClock();
  if (view.status === "written" && view.written) {
    const written = view.written;
    const rows = view.rows.filter((row) => row.written_angle).map((row) => ({ row, angle: row.written_angle as string }));
    const before = Math.max(0, view.notebook.count - written.count);
    return (
      <>
        <div className="flex max-w-[1260px] flex-col gap-4">
          {header}
          <ResultHero
            tone="ok" title={`已寫 ${written.count} 條：留存分類有效 ${written.effective}、無效 ${written.ineffective}、未核實 ${written.unknown ?? "未知"}`}
            note={`寫於 ${stampText(written.at, timezone)}・上一期 ${rangeText(view.start, view.end)}`}
          />
          <FlowTo
            from={{ label: "品牌筆記本", value: `多了 ${written.count} 條`, note: `原本 ${before} 條` }}
            to={{ label: "下一個新活動", value: "先核對當前資格", note: "歷史排序不是成功證明，少樣本只作測試或對照" }}
          />
          <p className="text-xs text-muted-foreground">上方是當時留存分類，下方是目前來源成本；兩者可能不同，不代表某個說法造成成果。</p>
          <Groups view={view} rows={rows} written />
          {written.count > rows.length && <p className="surface px-5 py-4 text-sm text-muted-foreground">另有 {written.count - rows.length} 條已寫紀錄，目前無法逐列核對原來源與主打；不推定其當前成效。</p>}
          {continuation}
        </div>
        <div className="flex-1" />
        <ActionBar back={{ label: "投放中心", to: homeHref }}>
          {next
            ? <Button asChild><Link to={next.href}>下一件 →</Link></Button>
            : <Button asChild><Link to={homeHref}>回投放中心 →</Link></Button>}
        </ActionBar>
      </>
    );
  }

  const rows = learnRows(view).map((row) => ({ row, angle: angleOf(row, picks[row.entity_id]) ?? "" }));
  return (
    <>
      <div className="flex max-w-[1260px] flex-col gap-4">
        {header}
        <Groups view={view} rows={rows} />
        <p className="text-xs text-muted-foreground">這些是平台成果成本的紀錄；並非付款收入或已核實獲利，也不能證明主打造成成果。</p>
        {error && (
          <div role="alert" className="rounded-xl bg-danger/10 px-5 py-4 text-sm">
            <b>還沒寫進筆記本</b>
            <div className="mt-0.5 text-xs text-muted-foreground">{error} 你選的主打都還在，可以再按一次。</div>
          </div>
        )}
      </div>
      <div className="flex-1" />
      <ActionBar back={{ label: "確認主打", to: angleHref }} exit={{ label: "晚點再結算", to: homeHref }} hint="寫進後，下一個新活動的策略會讀">
        <Button busy={busy} disabledReason={rows.length === 0 ? "還沒有可寫進筆記本的項目" : undefined} onClick={onWrite}>{busy ? "寫入中…" : `寫進筆記本（${rows.length} 條）→`}</Button>
      </ActionBar>
    </>
  );
}
