/** frontend/src/lib/adsWorkspaceApi.ts — F30-I06 (Contract E): the campaign workspace reads.
 * Shapes served by `app/ads/workspace_reads.py`; no shared type grows (`CampaignDetail`,
 * `TriageItem`, `ChangeSet` stay as they are).
 *
 * Rules the screen can rely on (never re-derive them here):
 * - `stage` comes from the one backend function (`app/ads/campaign_stage.py`); `done` lists every
 *   stage before `key`, in rail order.
 * - `null` means unknown — never read it as 0. A sub-read that failed is `null` on its own field
 *   (`pending_count`, `daily_budget`, `can_support`, `next_sync_at`, `totals`, `draft`); an unknown
 *   `pending_count` shows no number. A failed read never promotes the stage to `decide`.
 * - `daily_budget` and `can_support` come from one rule: on a launched campaign the daily budget
 *   owners of its active ads (the number the cleanup proposal uses); on a draft the plan's group
 *   total, with `can_support` null.
 * - `totals` is the last 14 complete days in the org timezone (`start`–`end`, yesterday back);
 *   `null` on a draft. Inside it, `spend`, `results` and `cost_per_result` are all null when any
 *   day of the window was never read from the platform (outside the campaign's recorded sync
 *   coverage, or no coverage at all) — an unread day is never counted as 0. Over a fully read
 *   window `spend` is still null when a day's spend is unknown, the rows mix currencies, or there
 *   is no row at all; a read day with zero spend (a 0 row, or no row) is a known 0.
 * - Structure grades are triage's (`TriageGrade`), null when the ad is not on a platform yet or the
 *   triage read failed. `closing` = an approved pause the readback has not confirmed yet.
 * - Timeline rows are newest first (`created_at DESC, id DESC`), at most 50 (`truncated` says
 *   there are more); superseded and deferred sets are not listed. */
import { apiFetch } from "./http";
import { BASE, parseJsonOrThrow, type CampaignLifecycle, type RunningAds } from "./adsApi";
import type { TriageGrade, TriageSampleView } from "./adsTriageApi";
import type { SlotState } from "./adsSlotsApi";

export type WorkspaceStageKey = "plan" | "assets" | "launch" | "read" | "decide" | "review";

export interface WorkspaceStage { key: WorkspaceStageKey; done: WorkspaceStageKey[] }

export interface WorkspaceTotals {
  start: string;
  end: string;
  currency: string | null;
  spend: number | null;
  results: number | null;
  cost_per_result: number | null;
}

/** The draft checklist: 上限、預算、素材 x／y、上架 n／N (`launch_*` are 0／0 before approval). */
export interface WorkspaceDraft {
  cap_set: boolean;
  budget_set: boolean;
  slots_ready: number;
  slots_total: number;
  launch_checked: number;
  launch_total: number;
}

/** F47 Contract E: `waiting` = on the platform and the sync table has no day with spend > 0 for it (never synced
 * since launch included); `live` = some day spent; `null` for a draft, a closed campaign, or a failed read — unknown
 * is never promoted to either. */
export type WorkspaceDelivery = "waiting" | "live";

export interface CampaignWorkspace {
  stage: WorkspaceStage;
  /** This campaign's open decision-queue rows; 0 on a draft or a closed campaign. */
  pending_count: number | null;
  delivery: WorkspaceDelivery | null;
  daily_budget: number | null;
  /** Running platform ads (`running.count`, F49 Contract L). */
  active_ads: number;
  /** F49 Contract L: the served lifecycle and 「在投」 with the read time it rests on. */
  lifecycle?: CampaignLifecycle;
  running?: RunningAds;
  can_support: number | null;
  next_sync_at: string | null;
  /** Days (YYYY-MM-DD) of the judged window never read from the platform — the campaign's
   * `data_status.missing_days` (triage window); `[]` on a draft, null when the read failed. */
  missing_days: string[] | null;
  totals: WorkspaceTotals | null;
  draft: WorkspaceDraft | null;
}

export interface StructureAd {
  /** The planned ad (app-built); null for a platform ad the plan does not hold. */
  ad_id: string | null;
  /** The platform ad; null while the planned ad is not on a platform yet. */
  entity_id: string | null;
  name: string;
  thumbnail_url: string | null;
  /** The ad's own spend over the window its grade was judged on; null when unknown. */
  spend: number | null;
  grade: TriageGrade | null;
  grade_label: string | null;
  /** F48 Contract R: the grade's reason (`too_new` = 剛開始, `spend_over_target_no_result` = 沒賣出, other codes on
   * `insufficient` = 資料不足); `null` when the ad has no grade. Screens branch on it, never on `grade_label`. */
  reason_code: string | null;
  /** F48 Contract R: the graded window's sample size (shown as 「樣本少」 when `few`, never a gate); `null` without a grade. */
  sample: TriageSampleView | null;
  cost_per_result: number | null;
  results: number | null;
  closing: boolean;
  /** Only on a planned ad not on a platform yet whose material is not ready. F49 Contract T: kept only as
   * `slot_state !== "ready"` (same source) until the structure tab reads `slot_state` (F49-I13). */
  missing_material: boolean;
  /** F49 Contract T: the planned ad's slot state from the one slot read (`GET …/slots`); null for a platform ad the
   * plan does not hold and when the slot read failed. Optional only for older fixtures. */
  slot_state?: SlotState | null;
  /** F49 Contract T: that state's chip word (served; never a local word table). */
  slot_label?: string | null;
}

export interface StructureGroup {
  /** The plan group (app-built); null for a platform parent (imported, or an unplanned ad). */
  group_id: string | null;
  name: string;
  daily_budget: number | null;
  ads: StructureAd[];
}

export interface CampaignStructure { groups: StructureGroup[] }

export type TimelineState = "verified" | "platform" | "check" | "rejected" | "draft" | "stale";

export interface TimelineRow {
  change_set_id: string;
  title: string;
  at: string;
  state: TimelineState;
  reason: string | null;
  checked: number;
  total: number;
  /** Launch sets only (the first launch is 1). */
  version: number | null;
}

export interface CampaignTimeline { rows: TimelineRow[]; truncated: boolean }

async function read<T>(
  brand: string, campaign: string, path: string, failure: string, signal?: AbortSignal,
): Promise<T> {
  try {
    const response = await apiFetch(
      `${BASE}/brands/${encodeURIComponent(brand)}/campaigns/${encodeURIComponent(campaign)}/${path}`,
      { signal },
    );
    return await parseJsonOrThrow<T>(response, failure);
  } catch (error) {
    if (error instanceof TypeError) throw new Error("未收到伺服器回應，請重試。");
    throw error;
  }
}

export function getCampaignWorkspace(
  brand: string, campaign: string, signal?: AbortSignal,
): Promise<CampaignWorkspace> {
  return read(brand, campaign, "workspace", "讀取活動進度失敗。", signal);
}

export function getCampaignStructure(
  brand: string, campaign: string, signal?: AbortSignal,
): Promise<CampaignStructure> {
  return read(brand, campaign, "structure", "讀取投放結構失敗。", signal);
}

export function getCampaignTimeline(
  brand: string, campaign: string, signal?: AbortSignal,
): Promise<CampaignTimeline> {
  return read(brand, campaign, "timeline", "讀取變更紀錄失敗。", signal);
}
