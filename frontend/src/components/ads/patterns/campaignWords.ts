import type { CampaignLifecycle } from "@/lib/adsApi";

/** F47-I08 (drill-10 §4.3 「同一活動三處狀態字不同」), F49 Contract L: the one word a campaign is called by on every ads
 * screen (workspace head, home rows, all-campaigns list) is the served `lifecycle.label` (`app/ads/lifecycle.py`
 * `LABELS`／`IMPORTED_LABELS`); the screen keeps no word table of its own. Also the one Chinese word for a platform's
 * own status (`native_status`, e.g. Meta's ACTIVE) until F49-I14 moves its last caller onto `delivery_label`. */

/** Kept only because `patterns/index.ts` (not this issue's file) re-exports the name; it holds no lifecycle word any
 * more and goes together with that re-export line. */
export const CAMPAIGN_WORD = {} as const;

/** What the page shows while a campaign read carries no `lifecycle` (never on a real response). */
const UNKNOWN_WORD = "—";
/** The one fallback a caller can vouch for without the served state: its own answer that the campaign is not on a
 * platform yet (the workspace's `ws.draft`). */
const NOT_ON_PLATFORM_WORD = "草稿";

/** The campaign's served lifecycle word. The second argument (kept so older callers compile unchanged) is read only
 * when no `lifecycle` was served; it never overrides the served word. */
export function campaignWord(c: { lifecycle?: CampaignLifecycle | null }, opts: {
  onPlatform?: boolean;
} = {}): string {
  return c.lifecycle?.label ?? (opts.onPlatform === false ? NOT_ON_PLATFORM_WORD : UNKNOWN_WORD);
}

/** A closed campaign never says 在投: 「已結案」, or 「已結案・平台上還開著 N 則」 while N of its platform ads still run
 * (`running` = the served `running.count`). `label` is the served closed label when the caller has it. */
export function closedWord(running: number, label = "已結案"): string {
  return running > 0 ? `${label}・平台上還開著 ${running} 則` : label;
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
