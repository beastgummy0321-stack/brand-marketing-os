/** frontend/src/lib/adsStrategyTypes.ts — F41-I04: the strategy shapes inside `ads_campaign.budget_basis_json`
 * (`strategy` and `basis`). Type-only; split out of `adsApi.ts` for its 800-line cap, which re-exports them so
 * importers keep using `@/lib/adsApi`. Shapes served by `app/ads/strategy.py` (`generate_strategy`'s `basis`) and
 * `app/ads/coordinate_learning.py` (`learning_rows`). */

import type { CoordinateLearnings } from "./adsLearningsApi";

export type StrategyRole = "new" | "retarget" | "explore";

export interface StrategyAllocationItem {
  role: StrategyRole;
  label: string;
  pct: number;
  rationale: string | null;
  /** 已套用 `budget.split()` 的金額，跟 `total` 精準加總——冷啟動沒有依據時是 `null`。 */
  amount: number | null;
}

/** F48 Contract S: one program-built fact line under the strategy (`strategy._facts`), recomputed on every campaign
 * read — the screen prints `text` as is, after a lead word for its `kind`. */
export interface StrategyFact {
  kind: "groups" | "offers" | "numbers" | "capacity" | "learnings";
  text: string;
}

export interface StrategyPayload {
  allocation: StrategyAllocationItem[];
  why: string[];
  unknowns: string[];
  alternatives: string[];
  /** F04-I13：這一輪想學到什麼，最多 3 條；舊資料沒有這個鍵時當空陣列讀，可選。 */
  learning_goals?: string[];
  /** F48 Contract S: the facts the program built (groups／offers／numbers／capacity／learnings); a strategy from
   * before F48 read through a backend that predates it has none. */
  facts?: StrategyFact[] | null;
}

export interface StrategyBasisFact {
  id: string;
  label: string;
  updated_at: string;
}

export interface StrategyBasisPrice {
  product_id: string;
  price: number | null;
  effective_from: string | null;
  stale: boolean;
  /** F05-I12：`product_economics.assumptions_json`——非空代表這筆價格用的是假設值。 */
  assumptions: string[];
  sell_way_name: string;
}

export interface StrategyBasisLearning {
  id: string;
  text: string;
  level: string;
  needs_revalidation: boolean;
}

/** F41-I02 `coordinate_learning.learning_rows`: one ad of the last closed campaign the planner saw, by label. */
export interface StrategyCoordinateLearning {
  grade: "on_target" | "watch" | "over" | "wasted";
  grade_label: string;
  /** null when the stored scope has no number (an older learning row). */
  cost_per_result: number | null;
  ad_name: string;
  campaign_name: string;
  /** `none` coordinates are omitted by the backend. */
  coordinates: { dimension: string; dimension_label: string; label: string }[];
}

/** F48 Contract M: `budget_preview` — the whole daily the structure will get for the chosen total (`daily_of`) and
 * the period total that daily really spends (`total_of`); `note` (「每天要是整數，這期實際 X」) only when they differ. */
export interface BudgetPreview {
  daily: number | null;
  total: number | null;
  chosen: number;
  note: string | null;
}

/** F48 decision 8: one ad set re-split by a new total chosen after adoption (`plan.resplit_groups`). */
export interface ResplitRow {
  group_id: string;
  role: StrategyRole;
  before: number;
  after: number;
}

/** F48-I06: one row of this period's coordinate menu (`plan.served`) — the keys the plan and hand edits may use. */
export interface PlanMenuRow {
  dimension: string;
  key: string;
  label: string;
}

/** F48 Contract C: what this period's daily budget carries (`plan.served`); `carried` = ads carried from the
 * previous period. */
export interface PlanCapacity {
  daily: number;
  cap: number;
  can_support: number;
  ceiling: number;
  carried?: number;
}

/** 查看策略依據：這個策略用到哪些品牌事實／商品價格／學習／llm_task，畫面照這個列。 */
export interface StrategyBasis {
  knowledge_item_ids: string[];
  llm_task_id: string;
  input_context_hash: string;
  brand_facts: StrategyBasisFact[];
  prices: StrategyBasisPrice[];
  learnings: StrategyBasisLearning[];
  /** F41-I02：上一期各則廣告的座標成績；F41 前產生的策略沒有這個鍵，當空陣列讀。F46 起不再寫入（舊策略照讀）。 */
  coordinate_learnings?: StrategyCoordinateLearning[];
  /** F46-I04 (Contract L): the learnings view the planner was prompted with — the same ranking 品牌智庫「投放學到的」
   * shows. Absent on strategies made before F46. */
  ranked_learnings?: CoordinateLearnings;
  estimated_fields: string[];
  /** F05-I12：一個都沒有假設值時這個鍵不存在（後端不落地空字串）。 */
  assumption_note?: string;
}
