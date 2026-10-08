import { campaignFlowPath } from "@/lib/adsRoutes";
/** F29-I15: the month review's plain-text facts — money words, dates, the weekly split of the pace data and the
 * month CSV (prototype v10 `csvMonth()`), built in the browser from the numbers the screen already shows (Feature
 * F29 decisions: no endpoint). Unknown numbers stay empty cells / 「未知」, never 0. */
import type { PeriodGradeRow } from "@/lib/adsMonthApi";
import { formatDay } from "@/lib/orgClock";
import { downloadCsv, formatAmount, type CsvCell } from "../patterns";

/** Preserve the source unit; no legacy default currency. */
export function money(value: number | null | undefined, currency?: string | null, verified = true): string {
  const text = formatAmount(value ?? null);
  return text === null ? "未知" : currency && verified ? `${text} ${currency}` : `${text}（幣別未核實）`;
}

/** `YYYY-MM` → its month number (9 for 2026-09). */
export const monthNum = (month: string) => Number(month.split("-")[1]);

const pad = (n: number) => String(n).padStart(2, "0");

/** 「09/05」 from a calendar day `YYYY-MM-DD`. An instant prints through `formatInstant(…, timezone, "mmdd")` on the org
 * clock (F50 Contract K), never here. */
export function mmdd(day: string): string {
  return formatDay(day, "mmdd");
}

/** 「兩」 for 2 in running text (「這兩天不計」); digits above nine. */
export function countWord(n: number): string {
  return ["", "一", "兩", "三", "四", "五", "六", "七", "八", "九"][n] ?? String(n);
}

/** The cleanup proposal of a campaign (the queue's own cleanup `action_url`). */
export function cleanupHref(brandId: string, campaignId: string): string {
  return campaignFlowPath(brandId, campaignId, ["propose", "cleanup", campaignId]);
}

/** One bar of 「每週花費 vs 預算步調」 (prototype `MONTHS[m].weeks`): days 1–7, 8–14, 15–21, 22–28, then the rest. */
export interface WeekBar {
  label: string;
  /** 「到 09/23」 when the data stops inside this week. */
  through: string | null;
  /** `future`: no complete day yet (還沒到); `unknown`: a day's spend in it is unknown. */
  state: "known" | "future" | "unknown";
  spend: number | null;
  /** The monthly budget spread evenly over the month's days, for this week's days; null without a budget. */
  pace: number | null;
}

/** Splits the home overview's cumulative daily spend (`pace.daily`, complete days only) into weeks. A missing or
 * null cumulative makes that week unknown, never 0. */
export function weekBars(month: string, daysInMonth: number, daily: { day: string; cumulative: number | null }[], budget: number | null, comparable = false): WeekBar[] {
  const mm = month.slice(5, 7);
  const cumulative = new Map<number, number | null>(daily.map((d) => [Number(d.day.slice(8, 10)), d.cumulative]));
  const lastDay = daily.reduce((max, d) => Math.max(max, Number(d.day.slice(8, 10))), 0);
  const at = (day: number): number | null => (day === 0 ? 0 : cumulative.get(day) ?? null);
  const bars: WeekBar[] = [];
  for (let start = 1; start <= daysInMonth; start += 7) {
    const end = Math.min(start + 6, daysInMonth);
    const label = `${mm}/${pad(start)}–${pad(end)}`;
    const pace = budget === null || !comparable ? null : (budget * (end - start + 1)) / daysInMonth;
    if (start > lastDay) {
      bars.push({ label, through: null, state: "future", spend: null, pace });
      continue;
    }
    const upTo = Math.min(end, lastDay);
    const a = at(upTo), b = at(start - 1);
    const through = upTo < end ? `到 ${mm}/${pad(upTo)}` : null;
    let gap = false;
    for (let day = start; day <= upTo; day += 1) if (at(day) === null) gap = true;
    bars.push(a === null || b === null || gap
      ? { label, through, state: "unknown", spend: null, pace }
      : { label, through, state: "known", spend: a - b, pace });
  }
  return bars;
}

/** The month CSV, one line per ad of `grades.rows` (every ad that spent in the month, same rows as the settle),
 * columns as the prototype `csvMonth()`. */
export function monthCsvRows(rows: PeriodGradeRow[]): CsvCell[][] {
  return [
    ["活動", "廣告", "花費", "平台成果數", "每筆成果成本", "上限", "等級", "花費幣別", "上限幣別", "上限比較限制"],
    ...rows.map((row) => [row.campaign_name, row.name, row.spend, row.results, row.cost_per_result, row.cap, row.grade_label, row.currency, row.cap_comparison?.currency, row.cap_comparison?.reason]),
  ];
}

export const monthCsvName = (month: string) => `${month}回顧.csv`;

export function downloadMonthCsv(month: string, rows: PeriodGradeRow[]): void {
  downloadCsv(monthCsvName(month), monthCsvRows(rows));
}
