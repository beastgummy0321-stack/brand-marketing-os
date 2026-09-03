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

/** 票 01（ADR 0040）：核准——花錢煞車。`spend_to_date` 是 null 代表這棵樹還沒有任何節點
 * 配對到通路上的活動，不是「花了 0 元」（兩件事不同，見 `CampaignTree.tsx`）。
 * `matches_current_tree` 是 false 代表樹的內容跟簽核當下已經不一樣（重新展開過），畫面
 * 要說清楚、請使用者重新核准，不是悄悄沿用舊的簽核。 */
export interface ScheduleApproval {
  id: string;
  approved_amount: number;
  approved_by: string;
  approved_at: string;
  matches_current_tree: boolean;
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
  /** null＝這棵樹從沒核准過，或最新一次核准已經撤回。 */
  approval: ScheduleApproval | null;
}

/** 票 01：活動樹每個最深層節點各配一份內容——`label`／`value` 都是後端部門任務檔
 * （`app/departments/creative/ad_creative.md`）的決定，這裡的型別一樣不知道任何具體欄位
 * 叫什麼名字，跟 `CampaignTreeField` 同一個道理。票 T1：`value` 收 `string | string[]`，
 * 後端一律正規化成陣列（`app/schedule/creative.py` `_valid_creative_fields`），這裡不再是
 * 單一字串。 */
export interface CreativeField {
  label: string;
  value: string[];
}

/** 票 T1：`CONSTITUTION.md` 規則 5 簽下的七個維度名稱——這則內容產出當下選定的座標，值是
 * 非空字串或 `null`（vocabulary 驗證留給 T1b，這裡的型別不知道每個值合不合法）。 */
export interface CreativeCoordinates {
  audience: string | null;
  pain: string | null;
  angle: string | null;
  hook: string | null;
  proof: string | null;
  offer: string | null;
  format: string | null;
}

export interface CreativeAd {
  node: string;
  coordinates: CreativeCoordinates;
  fields: CreativeField[];
  warnings: string[];
}

export interface CreativeResult {
  task_id: string;
  created_at: string;
  source_tree_task_id: string;
  ads: CreativeAd[];
  narrative: string;
  failure: string | null;
  running: boolean;
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
}

export interface ScheduleState {
  daily_budget: number;
  plan_count_min: number;
  plan_count_max: number;
  platforms: SchedulePlatformOption[];
  objectives: ScheduleObjectiveOption[];
  plan: SchedulePlan | null;
  tree: CampaignTreeResult | null;
  creative: CreativeResult | null;
  period: SchedulePeriod | null;
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

/** 票 01：把已展開的活動樹每個最深層節點各配一份內容——比對規則、儲存位置全部凍結在
 * 後端，這裡只負責打那支端點，回傳整個 `ScheduleState`（跟其他三支端點一樣，`creative`
 * 欄位換新）。 */
export async function generateCreative(brandId: string): Promise<ScheduleState> {
  const res = await apiFetch(`/api/schedule/brands/${encodeURIComponent(brandId)}/creative`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!res.ok) {
    let message = `產出失敗（狀態碼 ${res.status}）`;
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
