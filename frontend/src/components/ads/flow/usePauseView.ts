/** F45-I06 (ads.md §6.49): the pause page's own read of one ad (Contract P) and the pieces of the page that
 * depend only on it and on the URL — the back link, the dates it prints, the window line. Root cause it closes
 * (drill 10 §1 #4): the page used to find its ad only through a home-queue row, so every entry that is not the
 * home queue (覆盤「停掉這則」, 讀回頁「暫停舊廣告」, the 成效 tab) landed on 「找不到」. Kept out of `ConfirmPage.tsx`
 * so that page stays under the 800-line cap. */
import { getPauseView, type PauseView, type TriageWindow } from "@/lib/adsTriageApi";
import { formatInstant } from "@/lib/orgClock";
import { useApiRead, type ApiRead } from "@/lib/useApiRead";
import { reviewRoundPath } from "../review/reviewFlow";
import { changeStepPath, type PauseFrom } from "./changeFlow";

/** Reads Contract P only while `entityId` is set (the pause propose route); otherwise resolves `null`. */
export function usePauseView(brandId: string, campaignId: string, entityId: string | null): ApiRead<PauseView | null> {
  return useApiRead<PauseView | null>(
    (signal) => (entityId ? getPauseView(brandId, campaignId, entityId, signal) : Promise.resolve(null)),
    [brandId, campaignId, entityId],
  );
}

/** The pause's reason (F48 Contract R "reason texts"): the served `reason_text`, built from this ad's own grade and
 * numbers. Without one the ad has no score yet — said as such, with the server's grade word when there is one. */
export function pauseReason(view: PauseView): string {
  if (view.reason_text?.trim()) return view.reason_text.trim();
  const label = view.triage?.grade_label;
  return label ? `這則還沒有分數：${label}` : "這則還沒有分數";
}

export interface PauseBack { label: string; to: string }

/** `?from=perf|review|verify&ref=…` → where 「←」 goes and what it is called (prototype `FROM`). A review or
 * verify entry without its `ref`, an unknown `from` or none at all go back to 投放中心. */
export function pauseBack(brandId: string, campaignId: string, from: string | null, ref: string | null): PauseBack {
  const home = { label: "投放中心", to: `/brands/${brandId}/ads` };
  const kind = from as PauseFrom | null;
  if (kind === "perf") return { label: "成效", to: `/brands/${brandId}/ads/campaigns/${campaignId}?tab=perf` };
  if (kind === "review" && ref) return { label: "覆盤", to: reviewRoundPath(brandId, campaignId, ref, "prepare") };
  if (kind === "verify" && ref) return { label: "核對結果", to: changeStepPath(brandId, campaignId, ref, "verify") };
  return home;
}

/** The evidence card's closed chip: 「已暫停・〈MM/DD〉在平台上關掉」 (date left out when unknown). */
export function closedNote(view: PauseView, timezone: string): string {
  // MM/DD on the org clock (`lib/orgClock`, F50 Contract K); unknown → the date is left out.
  return `已暫停・${formatInstant(view.closed_at, timezone, "mmdd")}在平台上關掉`;
}

/** The ad's own window (calendar dates, no timezone): 「09/26～10/02・7 天」. */
export function windowText(window: TriageWindow): string {
  const md = (ymd: string) => `${ymd.slice(5, 7)}/${ymd.slice(8, 10)}`;
  return `${md(window.start)}～${md(window.end)}・${window.days} 天`;
}
