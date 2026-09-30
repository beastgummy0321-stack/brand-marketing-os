/** frontend/src/lib/adsStrategyTypes.ts — F41-I04: the strategy shapes inside `ads_campaign.budget_basis_json`
 * (`strategy` and `basis`). Type-only; split out of `adsApi.ts` for its 800-line cap, which re-exports them so
 * importers keep using `@/lib/adsApi`. Mirrors `app/ads/strategy.py` (`generate_strategy`'s `basis`) and
 * `app/ads/coordinate_learning.py` (`learning_rows`). */

export type StrategyRole = "new" | "retarget" | "explore";

export interface StrategyAllocationItem {
  role: StrategyRole;
  label: string;
  pct: number;
  rationale: string | null;
  /** 已套用 `budget.split()` 的金額，跟 `total` 精準加總——冷啟動沒有依據時是 `null`。 */
  amount: number | null;
}

export interface StrategyPayload {
  allocation: StrategyAllocationItem[];
  why: string[];
  unknowns: string[];
  alternatives: unknown[];
  /** F04-I13：這一輪想學到什麼，最多 3 條；舊資料沒有這個鍵時當空陣列讀，可選。 */
  learning_goals?: string[];
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

/** 查看策略依據：這個策略用到哪些品牌事實／商品價格／學習／llm_task，畫面照這個列。 */
export interface StrategyBasis {
  knowledge_item_ids: string[];
  llm_task_id: string;
  input_context_hash: string;
  brand_facts: StrategyBasisFact[];
  prices: StrategyBasisPrice[];
  learnings: StrategyBasisLearning[];
  /** F41-I02：上一期各則廣告的座標成績；F41 前產生的策略沒有這個鍵，當空陣列讀。 */
  coordinate_learnings?: StrategyCoordinateLearning[];
  estimated_fields: string[];
  /** F05-I12：一個都沒有假設值時這個鍵不存在（後端不落地空字串）。 */
  assumption_note?: string;
}
