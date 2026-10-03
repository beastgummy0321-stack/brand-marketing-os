/** frontend/src/lib/adsSettleApi.ts — F29-I03 Contract E: the period settle (one period = one
 * calendar month in the org timezone). Mirrors `app/ads/settle.py`/`app/ads/settle_routes.py`
 * exactly — the GET/POST response is flat (no outer wrapper key). Rows are the month review's own
 * `grade_period` rows (`PeriodGradeRow`) plus the settle's fate; unknown numbers are `null`,
 * never 0. Errors carry the backend `code` (`settle_not_ended`, `settle_angle_missing`,
 * `settle_angle_invalid`) so the page can branch on it. */
import { apiFetch } from "./http";
import { BASE } from "./adsApi";
import type { PeriodGradeBucket, PeriodGradeRow } from "./adsMonthApi";
import type { LearningVerdict } from "./adsLearningsApi";
import type { CampaignDataStatus, CapBasis } from "./adsTriageApi";

/** `not_ended`: the month is not over yet in the org timezone (nothing can be written);
 * `open`: ended, nothing written; `written`: the month's learnings are in the brand notebook. */
export type SettleStatus = "not_ended" | "open" | "written";
/** F48 Contract R "derived rulers": the row's place in its campaign's `learning_rank` ranking decides — 留下
 * (`keep`／`keep_relative`) → `effective`, 換掉 (`replace`) → `ineffective`, a row the ranking cannot place (unknown
 * results or spend, mixed currency) → `skip` (never written, needs no pick; `skip_reason` says why). */
export type SettleFate = "effective" | "ineffective" | "skip";
/** `not_needed`: no pick is needed from the AI (a skip or already written row, or an ad with no
 * copy to read — a non-skip row with no copy still needs a pick, typed by the user). */
export type SettleAnglesStatus = "pending" | "ready" | "failed" | "not_needed";

export interface SettleAngles { status: SettleAnglesStatus; candidates: string[] }

export interface SettleRow extends PeriodGradeRow {
  /** F48-I02: the row's place in its campaign's `learning_rank` ranking, as served (print it, never re-rank): `rank`
   * of `of` (both `null` when the row is not ranked), `sales` its known sales, `few` = fewer than
   * `rules.grade.sample_few` sales (「樣本少」), `verdict`／`verdict_label` 留下／換掉, `flags` the served flag words. */
  rank: number | null; of: number | null; sales: number | null; few: boolean;
  verdict: LearningVerdict | null; verdict_label: string | null; flags: string[];
  fate: SettleFate;
  /** Why a row is not written although it has a grade: 「資料缺天，這期不記」 (its campaign has unsynced days in the
   * month) or 「沒有可排名的數字」 (the ranking cannot place it). `null` on written rows. */
  skip_reason: string | null;
  /** The ad's own copy (first body, else title); null when the ad has none. */
  copy_text: string | null;
  angles: SettleAngles;
  /** The angle already written to the notebook for this ad; null until written. */
  written_angle: string | null;
}

export interface SettleCampaign {
  campaign_id: string; name: string; origin: string;
  cap: { value: number; basis: CapBasis | null } | null;
  break_even: number | null;
  data_status: CampaignDataStatus;
}

export interface SettleWritten {
  at: string; by: string; count: number; effective: number; ineffective: number;
}

export interface SettleView {
  month: string; start: string; end: string; days: number; status: SettleStatus;
  currency: string | null;
  spent: number | null;
  /** The month budget, only when it is in the same currency as the spend. */
  budget: number | null;
  results: number | null;
  cost_per_result: number | null;
  on_target_results: number | null;
  /** 0–1 share of the spend that went to 划算 ads; null when the spend is unknown. */
  on_target_spend_share: number | null;
  buckets: PeriodGradeBucket[];
  campaigns: SettleCampaign[];
  rows: SettleRow[];
  /** How many ads-track learnings the brand notebook holds right now. */
  notebook: { count: number };
  written: SettleWritten | null;
}

/** One pick per non-skip row not written yet; `angle` is 1–12 characters after trimming. Picks
 * for skip rows are ignored. */
export interface SettlePick { entity_id: string; angle: string }

export class SettleRequestRejected extends Error {
  code: string | null;
  status: number;
  constructor(message: string, code: string | null, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

const settlePath = (brand: string) => `${BASE}/brands/${encodeURIComponent(brand)}/settle`;

async function json<T>(path: string, method: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await apiFetch(path, { method, signal, ...(body === undefined ? {} : {
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }) });
  } catch (error) {
    if (error instanceof TypeError) throw new Error("未收到伺服器回應，結果尚未確認。請重試。");
    throw error;
  }
  if (!response.ok) {
    let code: string | null = null;
    let message = "目前無法完成，請稍後重試。";
    try {
      const data = (await response.json()) as { error?: { code?: string; message?: string } };
      if (data.error?.code) code = data.error.code;
      if (data.error?.message) message = data.error.message;
    } catch {
      // 回應不是 JSON，用預設訊息，`code` 維持 `null`。
    }
    if (response.status >= 400 && response.status < 500) {
      throw new SettleRequestRejected(message, code, response.status);
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

/** `month` omitted = the latest ended month in the org timezone. */
export function getSettle(brand: string, month?: string, signal?: AbortSignal) {
  const query = month ? `?month=${encodeURIComponent(month)}` : "";
  return json<SettleView>(`${settlePath(brand)}${query}`, "GET", undefined, signal);
}

/** Writes one learning per non-skip row; a repeat writes nothing twice. Returns the fresh view. */
export function writeSettle(brand: string, month: string, picks: SettlePick[], signal?: AbortSignal) {
  return json<SettleView>(settlePath(brand), "POST", { month, picks }, signal);
}
