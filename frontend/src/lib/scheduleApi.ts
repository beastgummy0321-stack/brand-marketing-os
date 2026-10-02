/** 檔期規劃 API 型別與呼叫（票 07：最薄路徑；票 08：表單加平台／目標／促銷重點／方案數，
 * 一次回 N 個方案）。對應 `app/schedule/routes.py`。
 * 這支端點不用 `{data, generated_at}` 信封（見 `lib/api.ts` 的 `Envelope<T>`）——
 * 票 07 settled 段「API — 字面契約」直接寫死回應形狀，這裡逐欄對照，不套用別支
 * feature 的信封慣例。 */
import type { Coordinate, CoordinateDimension } from "./coordinatesApi";
import { apiFetch, errorMessageFrom, throwIfFailed } from "./http";

export interface ScheduleSplit {
  label: string;
  share: number;
  why: string;
  daily_amount: number;
}

export interface SchedulePlanItem {
  summary: string;
  reasoning: string;
  splits: ScheduleSplit[];
}

export interface ScheduleSource {
  title: string;
  url: string;
}

export interface SchedulePlan {
  task_id: string;
  created_at: string;
  product_ids: string[];
  daily_budget: number;
  platform: string;
  objective: string;
  promotion_note: string;
  narrative: string;
  plans: SchedulePlanItem[];
  sources: ScheduleSource[];
  failure: string | null;
  running: boolean;
}

/** 平台／行銷目標選項——內容全部來自 `app/schedule/channel_catalogue.json`，前端只轉譯
 * 成畫面，不自己寫死任何平台或目標的中文字（票 08：CONTEXT.md 的三詞界線）。 */
export interface SchedulePlatformOption {
  id: string;
  label: string;
  enabled: boolean;
}

export interface ScheduleObjectiveOption {
  platform: string;
  value: string;
  label: string;
  source_url: string;
  verified_date: string;
}

/** 票 09：選定一個方案展開成的三層結構——`levels`／`budget_level` 是代理自己回報的，
 * 這裡的型別跟外殼一樣不知道任何通路的詞彙。 */
export interface CampaignTreeField {
  label: string;
  value: string;
}

export interface CampaignTreeNode {
  name: string;
  /** ADR 0055 §1：這個節點在活動結構裡的位置路徑（"1.1.1" 這種），身分認的是這個，不是
   * `name`——票 05 起，排程頁靠它把節點對回 `ScheduleBrief.node_key`。 */
  node_key: string;
  fields: CampaignTreeField[];
  share: number | null;
  daily_amount: number | null;
  warnings: string[];
  children: CampaignTreeNode[];
  /** 票 11：只有第一層節點會綁——更深的節點這三欄一律 null。 */
  bound_external_id: string | null;
  spend: number | null;
  roas: number | null;
  /** 票 04：讀時 overlay，名字＋層跟上一個已結算檔期的某個記分節點對上時是那一列的
   * node_key，否則 null（第一層一律 null，從沒被記過分）。 */
  continued_from_node_key: string | null;
  /** 票 05（ADR 0069）：只有第三層節點有值（七個維度各自一個 label 或 null，某個維度
   * 不適用就是 null），第一、二層一律 null。沿用節點（`continued_from_node_key` 非
   * null）的座標是程式蓋成上一期的，不是代理這次寫的。 */
  coordinates: Partial<Record<CoordinateDimension, string | null>> | null;
}

/** 票 01（ADR 0040）：核准——花錢煞車。`spend_to_date` 是 null 代表這棵樹還沒有任何節點
 * 配對到通路上的活動，不是「花了 0 元」（兩件事不同，見 `CampaignTree.tsx`）。
 * `matches_current_tree` 是 false 代表樹的結構跟簽核當下已經不一樣（重新展開過，或節點
 * 之間的 `share` 被搬動過），畫面要說清楚、請使用者重新核准，不是悄悄沿用舊的簽核。
 * 票 M2（ADR 0059）：`matches_current_tree` 不再管總額縮放——`max_daily_amount` 是簽核
 * 當下定的每日上限，`current_daily_amount` 是樹現在的總額，`within_approved_ceiling` 是
 * 前者有沒有壓在後者之下。總額只准往下滑仍算數；壓過上限就是另一個警訊，兩者是分開的
 * 兩件事。 */
export interface ScheduleApproval {
  id: string;
  approved_amount: number;
  approved_by: string;
  approved_at: string;
  matches_current_tree: boolean;
  max_daily_amount: number;
  current_daily_amount: number;
  within_approved_ceiling: boolean;
  spend_to_date: number | null;
  expected_to_date: number;
  days_elapsed: number;
}

export interface CampaignTreeResult {
  task_id: string;
  created_at: string;
  plan_index: number;
  levels: string[];
  budget_level: number | null;
  nodes: CampaignTreeNode[];
  narrative: string;
  failure: string | null;
  running: boolean;
  /** 票 11：只在「配對」這支端點的回應裡會非 null（不落地儲存）——GET／tree／reject
   * 一律是 null。 */
  bind_failure: string | null;
  /** 票 05：跟 bind_failure 同一條規則——只在「配對」端點的回應裡會非 null，讀 Meta 現算
   * 現讀、不落地儲存；非 null 代表這棵樹以為預算在哪一層跟 Meta 實際掛預算的層不一致。 */
  budget_note: string | null;
  /** null＝這棵樹從沒核准過，或最新一次核准已經撤回。 */
  approval: ScheduleApproval | null;
}

/** 票 05（ADR 0068）：活動樹每個最深層節點自動提交的一份工作檯工單摘要——文案／圖片
 * 提示詞的產出與型別都在 `app.workbench`，這裡只讀 `adopted_output()` 攤平後的形狀
 * （`app/schedule/state.py` `_copy_summary`／`_image_prompt_summary`）。`status`：
 * 這份工單自己的狀態（`queued`／`running`／`done`／`failed`／`closed`），或 `"missing"`
 * ——這個最深層節點還沒有工單（舊樹留下的、或提交失敗）。 */
export interface ScheduleBriefCopy {
  is_adopted: boolean;
  generation_round: number;
  copy_length: "short" | "medium" | "long";
  bodies: string[];
  headlines: string[];
  descriptions: string[];
  visual_tone: "暗調強對比" | "暖調生活" | null;
  visual_concept: string | null;
  validation: string[];
  warnings: string[];
}

export interface ScheduleBriefImagePrompts {
  generation_round: number;
}

export interface ScheduleBrief {
  node_key: string;
  node_name: string;
  brief_id: string | null;
  status: string;
  last_error: string | null;
  copy: ScheduleBriefCopy | null;
  image_prompts: ScheduleBriefImagePrompts | null;
}

/** 票 T2b（ADR 0053）：檔期——誕生在表單，結算靠使用者按鍵。`settled` 是 `null` 代表
 * 還沒結算過；`late_*_since` 是「現在」跟凍結快照的差，`0` 代表沒有晚到的錢，`null`
 * 代表還沒結算所以無從比較（跟 `settled` 是不是 `null` 是同一件事，見後端說明）。 */
export interface SchedulePeriodSettled {
  spend: number;
  revenue: number;
  settled_at: string;
  late_spend_since: number;
  late_revenue_since: number;
}

/** Ticket smart-loop 01 (ADR 0066): one bound node's score for this period, written when the
 * period settles. `depth` is 2 (ad set, carries the approved share) or 3 (ad, carries
 * `coordinates_json`) -- depth 1 is never scored. `roas_conservative`/`roas_optimistic` are
 * both true (docs/contracts/schedule.md "One coordinate has two ROAS values"); `verdict` is
 * derived from both against `breakeven_roas`. */
export interface SchedulePeriodNodeResult {
  node_key: string;
  depth: 2 | 3;
  node_name: string;
  external_id: string;
  approved_share: number | null;
  approved_daily_amount: number | null;
  actual_spend: number;
  revenue_tracked: number | null;
  roas_conservative: number | null;
  roas_optimistic: number | null;
  roas_coverage: number;
  breakeven_roas: number | null;
  breakeven_source: string;
  verdict: "win" | "lose" | "unclear";
  coordinates_json: Record<string, string | null> | null;
}

export interface SchedulePeriod {
  id: string;
  name: string;
  status: "planning" | "running" | "awaiting_data" | "settled";
  start_date: string;
  end_date: string;
  daily_budget: number | null;
  currency: string;
  settle_advice_date: string;
  settled: SchedulePeriodSettled | null;
  node_results: SchedulePeriodNodeResult[];
}

/** Ticket smart-loop 05: read-time, nothing stored -- `null` before the brand has any settled
 * period (first period, the screen says so). `direction`/`verdict` follow the same
 * `win`/`lose`/`unclear` -> `up`/`down`/`hold` mapping as the node-result verdict (ADR 0066
 * rule 4), computed spend-weighted across the last settled period's depth-2 rows. */
export interface NextPeriodSuggestion {
  based_on_period_id: string;
  based_on_name: string;
  start_date: string;
  end_date: string;
  baseline_daily_budget: number;
  daily_budget: number;
  direction: "up" | "down" | "hold";
  step_rate: number;
  verdict: "win" | "lose" | "unclear";
  roas_conservative: number | null;
  roas_optimistic: number | null;
  breakeven_roas: number | null;
  why: string;
  overlaps: string[];
}

/** F02-I04 (ARCHITECTURE.md §5.5): the "可以下一步" signal, a state read through
 * `workbench.pack_for_source` -- never a callback. `state` is the Chinese word
 * `pack_for_source` returns (待處理／進行中／待核准／已完成), passed through untranslated.
 * `null` when the tree has no pack yet. */
export interface CreativePackSignal {
  pack_id: string;
  state: string;
  approved_at: string | null;
  sets_total: number;
  sets_done: number;
}

export interface ScheduleState {
  daily_budget: number;
  plan_count_min: number;
  plan_count_max: number;
  knowledge_gaps: string[];
  platforms: SchedulePlatformOption[];
  objectives: ScheduleObjectiveOption[];
  plan: SchedulePlan | null;
  tree: CampaignTreeResult | null;
  briefs: ScheduleBrief[];
  creative_pack: CreativePackSignal | null;
  period: SchedulePeriod | null;
  next_period_suggestion: NextPeriodSuggestion | null;
}

export interface CreateSchedulePlanInput {
  productIds: string[];
  platform: string;
  objective: string;
  promotionNote: string;
  planCount: number;
  startDate: string;
  endDate: string;
}

/** 狀態徽章文字（票 T2b「The screen」）——四個狀態、逐字四句，畫面元件照抄，不重譯。 */
export const PERIOD_STATUS_LABELS: Record<SchedulePeriod["status"], string> = {
  planning: "規劃中",
  running: "進行中",
  awaiting_data: "已結束，需人工確認",
  settled: "已結算",
};

/** 票 smart-loop 01（ADR 0066）：節點記分表格文字，畫面元件照抄。 */
export const NODE_RESULT_DEPTH_LABELS: Record<SchedulePeriodNodeResult["depth"], string> = {
  2: "組合",
  3: "廣告",
};
export const NODE_RESULT_VERDICT_LABELS: Record<SchedulePeriodNodeResult["verdict"], string> = {
  win: "賺",
  lose: "賠",
  unclear: "看不出",
};

/** 票 10-feedback-entries（ADR 0037）：拒絕一批方案的回饋條目——嚴重程度只問「紅線／
 * 偏好」兩個值，決定 rule.severity 與是否需要選類別，畫面從不問內容是哪種危害
 * （ADR 0037「dropdown 只問後果，不問內容」）。 */
export type RejectSeverity = "hard" | "soft";

/** soft 回饋可選的類別——`app/core/vocab.py` RULE_TYPES 為本模組新增的五個（四個偏好分類
 * ＋other），跟 `libraryApi.ts` 的 RULE_TYPES 是同一個常數的不同鏡射，各自獨立維護
 * （沿用既有慣例：那份鏡射也不從後端動態抓）。 */
export const SCHEDULE_REJECT_CATEGORIES: [string, string][] = [
  ["angle", "切角"],
  ["audience", "受眾"],
  ["product_pick", "商品選擇"],
  ["budget_split", "預算分配"],
  ["other", "其他"],
];

export interface RejectEntryInput {
  severity: RejectSeverity;
  ruleType: string;
  content: string;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await apiFetch(path);
  if (res.status === 404) throw new Error("找不到這個品牌。");
  await throwIfFailed(res, `讀取失敗（狀態碼 ${res.status}）`);
  return (await res.json()) as T;
}

export function fetchSchedule(brandId: string): Promise<ScheduleState> {
  return getJson(`/api/schedule/brands/${encodeURIComponent(brandId)}`);
}

export async function createSchedulePlan(
  brandId: string,
  input: CreateSchedulePlanInput,
): Promise<ScheduleState> {
  const res = await apiFetch(`/api/schedule/brands/${encodeURIComponent(brandId)}/plans`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      product_ids: input.productIds,
      platform: input.platform,
      objective: input.objective,
      promotion_note: input.promotionNote,
      plan_count: input.planCount,
      start_date: input.startDate,
      end_date: input.endDate,
    }),
  });
  if (!res.ok) {
    let message = `排程失敗（狀態碼 ${res.status}）`;
    try {
      const data = (await res.json()) as { error?: { message?: string } };
      message = errorMessageFrom(data, message);
    } catch {
      // 回應不是 JSON，用預設訊息。
    }
    throw new Error(message);
  }
  return (await res.json()) as ScheduleState;
}

/** 票 09：選定一個既有方案，展開成三層結構。回傳形狀跟 `fetchSchedule`／
 * `createSchedulePlan` 一樣是整個 `ScheduleState`（`tree` 欄位換新），不另開一個窄的
 * 回應形狀。 */
export async function expandPlanIntoTree(brandId: string, planIndex: number): Promise<ScheduleState> {
  const res = await apiFetch(`/api/schedule/brands/${encodeURIComponent(brandId)}/tree`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ plan_index: planIndex }),
  });
  if (!res.ok) {
    let message = `展開失敗（狀態碼 ${res.status}）`;
    try {
      const data = (await res.json()) as { error?: { message?: string } };
      message = errorMessageFrom(data, message);
    } catch {
      // 回應不是 JSON，用預設訊息。
    }
    throw new Error(message);
  }
  return (await res.json()) as ScheduleState;
}

/** 票 11：把已展開的樹跟通路那邊實際發布的成果對起來——比對規則、儲存位置全部凍結在
 * 後端，這裡只負責打那支端點，回傳整個 `ScheduleState`（跟其他三支端點一樣，`tree`
 * 欄位換新）。 */
export async function bindScheduleTree(brandId: string): Promise<ScheduleState> {
  const res = await apiFetch(`/api/schedule/brands/${encodeURIComponent(brandId)}/tree/bind`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!res.ok) {
    let message = `配對失敗（狀態碼 ${res.status}）`;
    try {
      const data = (await res.json()) as { error?: { message?: string } };
      message = errorMessageFrom(data, message);
    } catch {
      // 回應不是 JSON，用預設訊息。
    }
    throw new Error(message);
  }
  return (await res.json()) as ScheduleState;
}

/** 票 01（ADR 0040）：核准目前展開的活動樹——金額、雜湊全部在後端算，這裡不接受、也
 * 不送任何金額欄位（花錢的數字只能由伺服器自己算）。回傳整個 `ScheduleState`（`tree`
 * 欄位換新，帶著新的 `approval`）。 */
export async function approveScheduleTree(brandId: string): Promise<ScheduleState> {
  const res = await apiFetch(`/api/schedule/brands/${encodeURIComponent(brandId)}/tree/approve`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!res.ok) {
    let message = `核准失敗（狀態碼 ${res.status}）`;
    try {
      const data = (await res.json()) as { error?: { message?: string } };
      message = errorMessageFrom(data, message);
    } catch {
      // 回應不是 JSON，用預設訊息。
    }
    throw new Error(message);
  }
  return (await res.json()) as ScheduleState;
}

/** 票 01（ADR 0040）：撤回目前有效的核准——舊列留著（`revoked_at` 標記），不會被刪除。 */
export async function revokeScheduleApproval(brandId: string): Promise<ScheduleState> {
  const res = await apiFetch(
    `/api/schedule/brands/${encodeURIComponent(brandId)}/tree/approve/revoke`,
    { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({}) },
  );
  if (!res.ok) {
    let message = `撤回失敗（狀態碼 ${res.status}）`;
    try {
      const data = (await res.json()) as { error?: { message?: string } };
      message = errorMessageFrom(data, message);
    } catch {
      // 回應不是 JSON，用預設訊息。
    }
    throw new Error(message);
  }
  return (await res.json()) as ScheduleState;
}

/** 票 T2b（ADR 0053）：結算目前這個檔期——算法全部在後端，這裡不接受、也不送任何金額
 * 欄位。回傳整個 `ScheduleState`（`period` 欄位換新，帶著新的 `settled`）。 */
export async function settleSchedulePeriod(brandId: string, periodId: string): Promise<ScheduleState> {
  const res = await apiFetch(
    `/api/schedule/brands/${encodeURIComponent(brandId)}/periods/${encodeURIComponent(periodId)}/settle`,
    { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({}) },
  );
  if (!res.ok) {
    let message = `結算失敗（狀態碼 ${res.status}）`;
    try {
      const data = (await res.json()) as { error?: { message?: string } };
      message = errorMessageFrom(data, message);
    } catch {
      // 回應不是 JSON，用預設訊息。
    }
    throw new Error(message);
  }
  return (await res.json()) as ScheduleState;
}

/** 票 10-feedback-entries：拒絕整批方案——每條意見變一列規則，再用凍結參數重新排程，
 * 回傳形狀跟其他兩個動作一樣是整個 `ScheduleState`（`plan` 換新）。 */
export async function rejectSchedulePlans(
  brandId: string,
  entries: RejectEntryInput[],
): Promise<ScheduleState> {
  const res = await apiFetch(`/api/schedule/brands/${encodeURIComponent(brandId)}/reject`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      entries: entries.map((e) => ({
        severity: e.severity,
        rule_type: e.severity === "soft" ? e.ruleType : null,
        content: e.content,
      })),
    }),
  });
  if (!res.ok) {
    let message = `送出失敗（狀態碼 ${res.status}）`;
    try {
      const data = (await res.json()) as { error?: { message?: string } };
      message = errorMessageFrom(data, message);
    } catch {
      // 回應不是 JSON，用預設訊息。
    }
    throw new Error(message);
  }
  return (await res.json()) as ScheduleState;
}

/** 票 T5（ADR 0057）：本月每個座標維度的花費／成效——沒有查詢參數，窗口固定是這個日曆月
 * （跟 `metaApi.ts` 的 `fetchMetaSpend` 同一個窗口）。`untagged` 是桶子不是破洞：一支花費
 * 列碰不到某個維度的座標就落在那個維度自己的 `untagged` 裡，`values[]` 加上
 * `untagged.spend` 等於 `total_spend`，逐維度、逐幣別都成立。`revenue`／`roas` 是 `null`
 * 代表未追蹤，不是 0（跟 `formatMetaRoas` 既有規則一樣）。 */
export interface CreativePerformanceUntagged {
  spend: number;
  ad_count: number;
}

export interface CreativePerformanceValue {
  key: string;
  label: string;
  spend: number;
  impressions: number;
  clicks: number;
  revenue: number | null;
  roas: number | null;
  roas_coverage: number;
  ad_count: number;
}

export interface CreativePerformanceDimension {
  dimension: CoordinateDimension;
  untagged: CreativePerformanceUntagged;
  values: CreativePerformanceValue[];
}

export interface CreativePerformanceCurrency {
  currency: string;
  total_spend: number;
  untagged: CreativePerformanceUntagged;
  dimensions: CreativePerformanceDimension[];
}

export interface CreativePerformance {
  window: { start_date: string; end_date: string };
  currencies: CreativePerformanceCurrency[];
}

export function fetchCreativePerformance(brandId: string): Promise<CreativePerformance> {
  return getJson(`/api/schedule/brands/${encodeURIComponent(brandId)}/creative-performance`);
}

/** 票 02（T6c）：成效判讀——`app/schedule/diagnosis.py` `brand_diagnosis_response()` 的形狀
 * 逐欄對照，不套用 `Envelope<T>` 信封（跟這支檔案其他端點同一個既有理由）。`status: null`
 * 代表這個品牌從沒跑過判讀；`running` 沿用既有 `llm_task` 輪詢慣例。`agreed_by` 是說過這件
 * 事的 lens 名字清單，長度 ≥2 代表兩個以上判讀器都這麼說。`no_tagged_spend` 只在
 * `suggestions` 是空陣列時才有意義，分辨「這個月全部沒座標可談」與「有座標但這輪沒建議」
 * 兩種完全不同的原因（票面「四個狀態」第 4 點）。 */
export interface DiagnosisSuggestion {
  dimension: CoordinateDimension;
  coordinate_key: string;
  coordinate_label: string;
  direction: "scale_up" | "scale_down" | "keep" | "test";
  impact_spend: number;
  headline: string;
  evidence: string;
  agreed_by: string[];
  /** issue diagnosis-lacks-checkable-numbers：程式從同一份壓縮輸入抄過來的可核對數字
   * （不是 AI 講的）。`numbers` 是這條建議自己那一組，`compared_with` 是同一維度花費前三
   * 名的對照組。2026-09-06 之前跑的舊判讀沒有這兩個欄位，畫面要容得下 undefined。 */
  currency: string | null;
  numbers: DiagnosisCheckableNumbers | null;
  compared_with: DiagnosisCheckableNumbers[];
  /** F31-I06 (Contract K): already adopted as a brand rule, computed server-side with the
   * same key the adopt route dedupes on — survives a reload. */
  adopted: boolean;
}

export interface DiagnosisCheckableNumbers {
  label: string;
  spend: number;
  ad_count: number;
  roas: number | null;
  roas_conservative: number | null;
  roas_coverage: number;
}

export interface DiagnosisWindow {
  start_date: string;
  end_date: string;
  days_with_data: number;
}

export interface DiagnosisBreakeven {
  roas: number | null;
  source: string;
}

export interface Diagnosis {
  status: "running" | "succeeded" | "failed" | null;
  window: DiagnosisWindow;
  breakeven: DiagnosisBreakeven;
  directional_only: boolean;
  suggestions: DiagnosisSuggestion[];
  lenses: Record<string, string>;
  no_tagged_spend: boolean;
}

export function fetchDiagnosis(brandId: string): Promise<Diagnosis> {
  return getJson(`/api/schedule/brands/${encodeURIComponent(brandId)}/diagnosis`);
}

export async function runDiagnosis(brandId: string): Promise<Diagnosis> {
  const res = await apiFetch(`/api/schedule/brands/${encodeURIComponent(brandId)}/diagnosis`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!res.ok) {
    let message = `判讀失敗（狀態碼 ${res.status}）`;
    try {
      const data = (await res.json()) as { error?: { message?: string } };
      message = errorMessageFrom(data, message);
    } catch {
      // 回應不是 JSON，用預設訊息。
    }
    throw new Error(message);
  }
  return (await res.json()) as Diagnosis;
}

/** 票 02：「採用」一條建議 → 品牌規則卡（`app/schedule/routes.py` `_run_diagnosis_adopt`）。
 * 回傳新規則列的 `id`／`content`，不是整份 `ScheduleState`（`adopt` 不動 `plan`／`tree`／
 * `creative`——矛盾檢查段第二組裁決：採用不重跑方案）。 */
export interface DiagnosisAdoptResult {
  id: string;
  content: string;
}

export async function adoptSuggestion(
  brandId: string,
  suggestionIndex: number,
): Promise<DiagnosisAdoptResult> {
  const res = await apiFetch(
    `/api/schedule/brands/${encodeURIComponent(brandId)}/diagnosis/adopt`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ suggestion_index: suggestionIndex }),
    },
  );
  if (!res.ok) {
    let message = `採用失敗（狀態碼 ${res.status}）`;
    try {
      const data = (await res.json()) as { error?: { message?: string } };
      message = errorMessageFrom(data, message);
    } catch {
      // 回應不是 JSON，用預設訊息。
    }
    throw new Error(message);
  }
  return (await res.json()) as DiagnosisAdoptResult;
}

// ---- 票 past-ads/03（ADR 0067）：投放史頁面——讀老廣告的成效排名，owner 自己標座標 ----

export type HistoryVerdict = "win" | "lose" | "unclear";

export interface HistoryCreative {
  body: string | null;
  title: string | null;
  image_url: string | null;
}

export type HistoryCoordinateKeys = Record<CoordinateDimension, string | null>;

export interface HistoryCard {
  external_id: string;
  name: string;
  why: string[];
  first_seen_date: string;
  last_seen_date: string;
  spend: number;
  impressions: number;
  clicks: number;
  revenue: number | null;
  roas: number | null;
  roas_conservative: number | null;
  roas_coverage: number;
  cpa: number | null;
  verdict: HistoryVerdict;
  creative: HistoryCreative | null;
  creative_error: string | null;
  coordinates: HistoryCoordinateKeys;
  coordinates_status: "tagged" | "pending" | "not_applicable";
  owner_note: string | null;
}

export interface HistoryCurrency {
  currency: string;
  cards: HistoryCard[];
}

export interface HistoryBackfill {
  running: boolean;
  earliest_spend_date: string | null;
  latest_spend_date: string | null;
  ad_rows: number;
}

export interface History {
  connected: boolean;
  backfill: HistoryBackfill | null;
  breakeven: DiagnosisBreakeven | null;
  currencies: HistoryCurrency[];
  coordinates: Coordinate[];
}

export function fetchHistory(brandId: string): Promise<History> {
  return getJson(`/api/schedule/brands/${encodeURIComponent(brandId)}/history`);
}

export interface TagHistoryAdBody {
  coordinates: HistoryCoordinateKeys;
  owner_note: string | null;
}

export interface TagHistoryAdResult {
  external_id: string;
  coordinates: HistoryCoordinateKeys;
  coordinates_status: "tagged" | "pending" | "not_applicable";
  owner_note: string | null;
  tagged_at: string;
}

export async function tagHistoryAd(
  brandId: string,
  externalId: string,
  body: TagHistoryAdBody,
): Promise<TagHistoryAdResult> {
  const res = await apiFetch(
    `/api/schedule/brands/${encodeURIComponent(brandId)}/history/${encodeURIComponent(externalId)}`,
    {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  if (!res.ok) {
    let message = `標記失敗（狀態碼 ${res.status}）`;
    try {
      const data = (await res.json()) as { error?: { message?: string } };
      message = errorMessageFrom(data, message);
    } catch {
      // 回應不是 JSON，用預設訊息。
    }
    throw new Error(message);
  }
  return (await res.json()) as TagHistoryAdResult;
}

/** 票 past-ads/09（ADR 0067 §1.9 amendment）：owner 按「重新抓素材」——清掉這批 id 的
 * 素材快取，畫面接著會再呼叫一次 `fetchHistory()` 讓卡片重新出現。 */
export interface RefetchHistoryCreativesResult {
  cleared: number;
}

export async function refetchHistoryCreatives(
  brandId: string,
  externalIds: string[],
): Promise<RefetchHistoryCreativesResult> {
  const res = await apiFetch(
    `/api/schedule/brands/${encodeURIComponent(brandId)}/history/creatives/refetch`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ external_ids: externalIds }),
    },
  );
  if (!res.ok) {
    let message = `重新抓素材失敗（狀態碼 ${res.status}）`;
    try {
      const data = (await res.json()) as { error?: { message?: string } };
      message = errorMessageFrom(data, message);
    } catch {
      // 回應不是 JSON，用預設訊息。
    }
    throw new Error(message);
  }
  return (await res.json()) as RefetchHistoryCreativesResult;
}
