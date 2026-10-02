import type { CampaignStatus } from "@/lib/adsApi";

/** F47-I08 (drill-10 §4.3 「同一活動三處狀態字不同」): the one word a campaign is called by on every ads screen
 * (workspace head, home rows, all-campaigns list), and the one Chinese word for a platform's own status
 * (`native_status`, e.g. Meta's ACTIVE) — never the raw platform code.
 *
 * A campaign not on a platform yet is 草稿 whether or not its launch list was approved (`ready` is not a second
 * word); an imported campaign is on its platform from the start (its stored status stays the default `draft`). */

export const CAMPAIGN_WORD = {
  draft: "草稿",
  live: "投放中",
  ended: "已結束",
  closed: "已結案",
} as const;

export function campaignWord(c: { status: CampaignStatus; origin?: "internal" | "imported" }, opts: {
  /** The workspace's own answer (`ws.draft === null`) when the screen has it; else the campaign's status decides. */
  onPlatform?: boolean;
} = {}): string {
  if (c.status === "closed") return CAMPAIGN_WORD.closed;
  if (c.status === "ended") return CAMPAIGN_WORD.ended;
  const onPlatform = opts.onPlatform ?? (c.origin === "imported" || c.status === "live");
  return onPlatform ? CAMPAIGN_WORD.live : CAMPAIGN_WORD.draft;
}

/** A closed campaign never says 在投: 「已結案」, or 「已結案・平台上還開著 N 則」 while N of its platform ads are not closed. */
export function closedWord(activeAds: number): string {
  return activeAds > 0 ? `${CAMPAIGN_WORD.closed}・平台上還開著 ${activeAds} 則` : CAMPAIGN_WORD.closed;
}

const NATIVE_WORD: Record<string, string> = {
  ACTIVE: "開啟中",
  PAUSED: "已暫停",
  DELETED: "已刪除",
  ARCHIVED: "已封存",
};

/** A platform object's own status in Chinese; anything else (or nothing) is 「平台狀態不明」. */
export function nativeStatusWord(status: string | null | undefined): string {
  return (status && NATIVE_WORD[status.toUpperCase()]) || "平台狀態不明";
}
