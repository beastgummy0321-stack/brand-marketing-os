/** 檔期規劃 API 型別與呼叫（票 07：最薄路徑；票 08：表單加平台／目標／促銷重點／方案數，
 * 一次回 N 個方案）。對應 `app/schedule/routes.py`。
 * 這支端點不用 `{data, generated_at}` 信封（見 `lib/api.ts` 的 `Envelope<T>`）——
 * 票 07 settled 段「API — 字面契約」直接寫死回應形狀，這裡逐欄對照，不套用別支
 * feature 的信封慣例。 */
import { apiFetch, errorMessageFrom } from "./http";

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

/** 平台／行銷目標選項——內容全部來自 `app/schedule/platform_objectives.json`，前端只轉譯
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
  fields: CampaignTreeField[];
  share: number | null;
  daily_amount: number | null;
  warnings: string[];
  children: CampaignTreeNode[];
  /** 票 11：只有第一層節點會綁——更深的節點這三欄一律 null。 */
  bound_external_id: string | null;
  spend: number | null;
  roas: number | null;
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
}

export interface ScheduleState {
  daily_budget: number;
  plan_count_min: number;
  plan_count_max: number;
  platforms: SchedulePlatformOption[];
  objectives: ScheduleObjectiveOption[];
  plan: SchedulePlan | null;
  tree: CampaignTreeResult | null;
}

export interface CreateSchedulePlanInput {
  productIds: string[];
  platform: string;
  objective: string;
  promotionNote: string;
  planCount: number;
}

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
  if (!res.ok) {
    throw new Error(res.status === 404 ? "找不到這個品牌。" : `讀取失敗（狀態碼 ${res.status}）`);
  }
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
