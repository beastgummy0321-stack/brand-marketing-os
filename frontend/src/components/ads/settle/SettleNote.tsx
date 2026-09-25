import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import type { SettleRow, SettleView } from "@/lib/adsSettleApi";
import { ActionBar, FlowTo, LearnLine, MoneyRule, MoneyTag, OriginTag, ResultHero, formatAmount } from "../patterns";
import { angleOf, learnRows, type AnglePicks } from "./SettleAngles";
import { FROM_META, campaignOf, isImported, money, rangeText, stampText, yuan } from "./settleCsv";

/** F29-I12 step 3 「寫進筆記本」 (prototype v10 `stepNote()`, hash `d/settle/note` before and after `settleWrite`):
 * the learnings in two groups, one POST for all of them, then the written state — what was written, how the brand
 * notebook grew, and where it goes next. The learning text itself carries no numbers (Feature F29 decisions); the
 * cost is printed beside it. */

function Learning({ view, row, angle }: { view: SettleView; row: SettleRow; angle: string }) {
  const campaign = campaignOf(view, row);
  const good = row.fate === "effective";
  const cost = row.cost_per_result;
  return (
    <LearnLine
      tone={good ? "ok" : "no"}
      title={<>
        「{angle}」對這群受眾{good ? "有效" : "無效"}
        {good && cost !== null && row.cap !== null && (
          <span className="font-normal text-muted-foreground">（每筆 {formatAmount(Math.floor(cost))}，上限 {formatAmount(row.cap)}）</span>
        )}
      </>}
      meta={<span className="inline-flex flex-wrap items-center gap-x-1">
        <span>{campaign.name}</span>
        {isImported(campaign.origin) && <OriginTag>{FROM_META}</OriginTag>}
        {row.group_name && <span>・{row.group_name}</span>}
        {row.grade === "wasted" && <span>・花 {money(row.spend)}沒賣出</span>}
        {row.grade === "over" && <span>・每筆 {yuan(cost)}，上限 {formatAmount(row.cap) ?? "未知"}</span>}
        <MoneyTag cost={cost} breakEven={row.break_even} />
      </span>}
    />
  );
}

function Groups({ view, rows }: { view: SettleView; rows: { row: SettleRow; angle: string }[] }) {
  const good = rows.filter((x) => x.row.fate === "effective");
  const bad = rows.filter((x) => x.row.fate === "ineffective");
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
      {card(`有效 ${good.length} 條`, "text-success", "划算的", good)}
      {card(`無效 ${bad.length} 條`, "text-danger", "太貴、沒賣出的", bad)}
    </div>
  );
}

export function SettleNote({ view, header, picks, busy, error, onWrite, homeHref, angleHref, newHref, next }: {
  view: SettleView; header: ReactNode; picks: AnglePicks; busy: boolean; error: string | null; onWrite: () => void;
  homeHref: string; angleHref: string; newHref: string; next: { href: string } | null;
}) {
  if (view.status === "written" && view.written) {
    const written = view.written;
    const rows = learnRows(view).filter((row) => row.written_angle).map((row) => ({ row, angle: row.written_angle as string }));
    const before = Math.max(0, view.notebook.count - written.count);
    return (
      <>
        <div className="flex max-w-[1260px] flex-col gap-4">
          {header}
          <ResultHero
            tone="ok" title={`寫好了 ${written.count} 條：有效 ${written.effective}、無效 ${written.ineffective}`}
            note={`寫於 ${stampText(written.at)}・上一期 ${rangeText(view.start, view.end)}`}
          />
          <FlowTo
            from={{ label: "品牌筆記本", value: `多了 ${written.count} 條`, note: `原本 ${before} 條` }}
            to={{ label: "下一個新活動", value: "策略會先讀這些", note: "有效的多用，無效的避開" }}
          />
          <Groups view={view} rows={rows} />
        </div>
        <div className="flex-1" />
        <ActionBar back={{ label: "投放中心", to: homeHref }}>
          <Button variant="outline" asChild><Link to={newHref}>＋ 建立活動</Link></Button>
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
        <MoneyRule />
        {error && (
          <div role="alert" className="rounded-xl bg-danger/10 px-5 py-4 text-sm">
            <b>還沒寫進筆記本</b>
            <div className="mt-0.5 text-xs text-muted-foreground">{error} 你選的主打都還在，可以再按一次。</div>
          </div>
        )}
      </div>
      <div className="flex-1" />
      <ActionBar back={{ label: "確認主打", to: angleHref }} exit={{ label: "晚點再結算", to: homeHref }} hint="寫進後，下一個新活動的策略會讀">
        <Button disabled={busy || rows.length === 0} onClick={onWrite}>{busy ? "寫入中…" : `寫進筆記本（${rows.length} 條）→`}</Button>
      </ActionBar>
    </>
  );
}
