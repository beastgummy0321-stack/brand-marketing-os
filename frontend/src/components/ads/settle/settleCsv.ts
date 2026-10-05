/** F29-I12: the settle's plain-text facts — the words every step prints for the same number, and the step-1 CSV
 * (prototype v10 `csvSettle()`), built in the browser from the numbers the screen already shows (Feature F29
 * decisions: no endpoint). Unknown numbers stay empty cells / 「未知」, never 0. */
import type { SettleCampaign, SettleFate, SettleRow, SettleView } from "@/lib/adsSettleApi";
import { downloadCsv, formatAmount, type AdsRules, type CsvCell } from "../patterns";
import { perSaleAmount } from "../patterns/csv";
import { formatInstant } from "@/lib/orgClock";

/** The origin tag of a campaign read from the platform instead of built here (prototype `FROM_META`). */
export const FROM_META = "從 Meta 帶進來";
/** The one sentence of what gets written (prototype `SETTLE_RULE`), from the served verdict words (F48 Contract R
 * "derived rulers": 留下 → 有效, 換掉 → 無效, a row the ranking cannot place → 不記). `null` until the rules load. */
export function settleRule(rules: AdsRules | null): string | null {
  if (!rules) return null;
  const { keep, replace } = rules.labels.verdict;
  return `排名${keep}的記成有效、${replace}的記成無效；排不上名的不記`;
}

export const FATE_WORD: Record<SettleFate, string> = { effective: "有效", ineffective: "無效", skip: "不記" };

export const isImported = (origin: string | null | undefined) => origin === "imported";

/** 「1,234 元」, or 「未知」 for an unknown amount. */
export function money(value: number | null | undefined): string {
  const text = formatAmount(value ?? null);
  return text === null ? "未知" : `${text} 元`;
}

/** A cost per result as whole yuan through the one per-sale rule (rounded, F47-I06), or 「未知」. */
export function yuan(value: number | null | undefined): string {
  const text = perSaleAmount(value);
  return text === null ? "未知" : `${text} 元`;
}

/** 「日常商品推廣」 from 「日常商品推廣・轉換」 (prototype `name.split("・")[0]`), capped so a long real name stays a label. */
export function campaignShort(name: string, max = 12): string {
  const head = name.split("・")[0] || name;
  return head.length > max ? `${head.slice(0, max)}…` : head;
}

/** 「08/01–08/31」 from two ISO dates. */
export function rangeText(start: string, end: string): string {
  const md = (iso: string) => iso.slice(5, 10).replace("-", "/");
  return `${md(start)}–${md(end)}`;
}

/** 「09/23 10:20」 on the org clock (`timezone`, F50 Contract K); unreadable → "". */
export function stampText(iso: string, timezone: string): string {
  return formatInstant(iso, timezone, "md_hm");
}

/** The campaign of a row: its own entry in `campaigns`, or a stand-in from the row when the campaign is gone. */
export function campaignOf(view: SettleView, row: SettleRow): SettleCampaign {
  return view.campaigns.find((c) => c.campaign_id === row.campaign_id) ?? {
    campaign_id: row.campaign_id, name: row.campaign_name, origin: row.origin,
    cap: row.cap === null ? null : { value: row.cap, basis: null }, break_even: row.break_even,
    data_status: { state: "ready", label: "", missing_days: [], last_success_at: null },
  };
}

/** 「2／5」, the row's served place in its campaign's ranking; `null` when it is not ranked. */
export function rankText(row: Pick<SettleRow, "rank" | "of">): string | null {
  return row.rank === null || row.of === null ? null : `${row.rank}／${row.of}`;
}

/** The step-1 table, one line per ad, columns as the prototype `csvSettle()` plus the served rank and sales (F48-I09);
 * rows in the served order. */
export function settleCsvRows(view: SettleView): CsvCell[][] {
  return [
    ["活動", "來源", "廣告組", "廣告", "花費", "購買", "每賣一筆", "上限", "等級", "排名", "成交", "寫進筆記本"],
    ...view.rows.map((row) => {
      const campaign = campaignOf(view, row);
      return [
        campaign.name, isImported(campaign.origin) ? FROM_META : "本系統", row.group_name, row.name,
        row.spend, row.results, row.cost_per_result, row.cap, row.grade_label, rankText(row), row.sales, FATE_WORD[row.fate],
      ];
    }),
  ];
}

export function downloadSettleCsv(view: SettleView): void {
  downloadCsv(`結算-${view.month}.csv`, settleCsvRows(view));
}
