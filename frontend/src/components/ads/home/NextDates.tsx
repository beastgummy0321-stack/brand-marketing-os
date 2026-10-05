import type { ReactNode } from "react";
import { Button } from "@/components/layout/ui/button";
import type { HomeOverview, HomeTimelineItem } from "@/lib/adsHomeApi";
import { useOrgClock } from "@/lib/orgClock";
import { NextUpStrip, type NextUpItem } from "../patterns";

/** Board D 「接下來」 strip (prototype v9 `homeNext()`): today and what today needs, this month's review, then
 * campaign starts and ends from the overview `timeline` (F28-I06, soonest first; the strip shows four). */

/** `YYYY-MM-DD` → 「10/01」 (month unpadded, day padded, as the prototype prints it). */
export function monthDay(iso: string): string {
  const [, m, d] = iso.split("-");
  return `${Number(m)}/${d}`;
}

/** The part of a campaign name before 「・」 (prototype `campShort`), for tight spots. */
export function shortName(name: string): string {
  return name.split("・")[0] || name;
}

/** What 「今天」 says about the decisions block (its own request, see `TodayDecisions`). */
export type TodayNote =
  | { kind: "loading" } | { kind: "syncing" } | { kind: "error" } | { kind: "open"; count: number } | { kind: "none" };

function todayBody(note: TodayNote, onJump: () => void): ReactNode {
  switch (note.kind) {
    case "loading": return <span className="text-muted-foreground">正在整理今天的判斷</span>;
    case "syncing": return <span className="text-muted-foreground">同步中，完成後再判斷</span>;
    case "error": return <Button variant="link" className="h-auto p-0 font-semibold text-danger" onClick={onJump}>判斷讀取失敗 ↓</Button>;
    case "open": return <Button variant="link" className="h-auto p-0 font-semibold" onClick={onJump}>{note.count} 件要你決定 ↓</Button>;
    case "none": return <span className="text-muted-foreground">沒有要決定的事</span>;
  }
}

function itemBody(item: HomeTimelineItem, monthNo: number): ReactNode {
  const name = item.name ? shortName(item.name) : "活動";
  switch (item.kind) {
    case "month_review": return <span>{monthNo} 月回顧</span>;
    case "campaign_start":
      return <span className="[overflow-wrap:anywhere]">{name}開始{item.ready === false && <span className="text-warning"> ・還沒準備好</span>}</span>;
    case "campaign_end": return <span className="[overflow-wrap:anywhere]">{name}這一期結束</span>;
    default: return null;
  }
}

export function NextDates({ home, note, onJump }: { home: HomeOverview | null; note: TodayNote; onJump: () => void }) {
  // Before the overview answers, 「今天」 is the org's today (F50 Contract K), never the laptop's.
  const { today } = useOrgClock();
  const timeline = home?.timeline ?? [{ date: today, kind: "today" as const, campaign_id: null, name: null, ready: null }];
  const items: NextUpItem[] = timeline.slice(0, 4).map((item, i) => {
    const [, m] = item.date.split("-");
    const monthNo = Number(m);
    if (item.kind === "today") {
      return { key: `today-${i}`, kind: "today", date: `${monthNo}/${Number(item.date.slice(8, 10))} 今天`, body: todayBody(note, onJump) };
    }
    const date = item.kind === "month_review" ? `${monthNo}/${Number(item.date.slice(8, 10))}` : monthDay(item.date);
    return { key: `${item.kind}-${item.campaign_id ?? ""}-${i}`, kind: item.kind, date, body: itemBody(item, monthNo), ready: item.ready };
  });
  return <NextUpStrip items={items} />;
}
