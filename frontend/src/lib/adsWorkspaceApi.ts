/** frontend/src/lib/adsWorkspaceApi.ts — F30-I06 (Contract E): the campaign workspace reads.
 * Mirrors `app/ads/workspace_reads.py` exactly; no shared type grows (`CampaignDetail`,
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
 *   `null` on a draft. Inside it, `spend` is null when a day's spend is unknown, the rows mix
 *   currencies, or there is no row at all; a zero-spend day is a known 0.
 * - Structure grades are triage's (`TriageGrade`), null when the ad is not on a platform yet or the
 *   triage read failed. `closing` = an approved pause the readback has not confirmed yet.
 * - Timeline rows are newest first (`created_at DESC, id DESC`), at most 50 (`truncated` says
 *   there are more); superseded and deferred sets are not listed. */
import { apiFetch } from "./http";
import { BASE, parseJsonOrThrow } from "./adsApi";
import type { TriageGrade } from "./adsTriageApi";

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

export interface CampaignWorkspace {
  stage: WorkspaceStage;
  /** This campaign's open decision-queue rows; 0 on a draft or a closed campaign. */
  pending_count: number | null;
  daily_budget: number | null;
  /** Live (not closed) platform ads. */
  active_ads: number;
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
  cost_per_result: number | null;
  results: number | null;
  closing: boolean;
  /** Only on a planned ad not on a platform yet whose material is not ready. */
  missing_material: boolean;
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
