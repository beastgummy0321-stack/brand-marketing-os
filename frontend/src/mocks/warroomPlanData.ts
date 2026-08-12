/** S8 作戰室「開檔／企劃」假資料（票 B4-warroom）。沿用 S7 已建的 15 筆 `campaignsStore`
 * （`campaignsData.ts` 檔頭註解已明講「S8 詳情頁會沿用同一份假資料源」），這裡只加算階段、
 * 企劃相關的衍生資料，不改動 S7 清單頁已驗收的資料本體。id 是模組載入時依序產生的
 * `cyc-1`…`cyc-15`（`campaignsData.ts` `nextId()`），順序固定，可安全用字面量索引。 */
import type {
  AccountStructure,
  Cycle,
  Dissent,
  PlanOption,
  RuleCardLearned,
  StructureGroup,
  TargetCpaView,
} from "@/lib/warroomApi";
import type { CampaignRecord } from "./campaignsData";

const OBJECTIVE_TO_FUNNEL_STAGE: Record<string, "exposure" | "consideration" | "conversion"> = {
  awareness: "exposure",
  traffic: "consideration",
  engagement: "consideration",
  leads: "conversion",
  sales: "conversion",
};

/** 素材／交接包訊號（真後端 `app/ads/stages.py derive_stage()` 用同一組訊號分出 PRODUCTION
 * 底下三格）：只有 cyc-4（PRODUCTION）需要，其餘狀態不看這兩個欄位。cyc-4 特意設成
 * 「素材已採用、交接包還沒建」＝交接包步驟空狀態（契約「四態」空態列點）。 */
const STAGE_SIGNALS: Record<string, { hasAdopted: boolean; packageCount: number }> = {
  "cyc-4": { hasAdopted: true, packageCount: 0 },
  "cyc-5": { hasAdopted: true, packageCount: 2 },
};

/** 7 格階段推導：中間 5 格邏輯原樣搬 `app/ads/stages.py derive_stage()`（查證日 2026-08-12），
 * 前後兩格是畫面層加的頭尾（契約「任務流版型」節）。 */
export function deriveStage(record: CampaignRecord): "plan" | "creative" | "handoff" | "prelaunch" | "performance" | "review" {
  if (record.status === "CLOSED") return "review";
  if (record.status === "LIVE" || record.status === "EVALUATING") return "performance";
  if (record.status === "PRODUCTION") {
    const signal = STAGE_SIGNALS[record.id] ?? { hasAdopted: false, packageCount: 0 };
    if (!signal.hasAdopted) return "creative";
    if (signal.packageCount === 0) return "handoff";
    return "prelaunch";
  }
  return "plan"; // PLANNING／PLAN_SELECT／REVIEW
}

export function buildCycle(record: CampaignRecord): Cycle {
  const daily = Math.round((record.budget / 14) * 100) / 100;
  return {
    id: record.id,
    brand_id: "demo",
    start_date: record.start_date,
    end_date: record.end_date,
    status: record.status,
    phase: record.phase ?? "normal",
    objective: record.objective,
    funnel_stage: record.funnelStageKnown ? OBJECTIVE_TO_FUNNEL_STAGE[record.objective] : null,
    budget: record.budget,
    duration_days: 14,
    daily_budget: daily,
    background: record.background || null,
    pacing_strategy: record.status === "PLANNING" ? "continuous" : record.id === "cyc-5" ? "pulse" : "continuous",
    pacing_reason:
      record.id === "cyc-5"
        ? "這次檔期綁了限時優惠，越接近檔期尾聲買氣通常越集中，把預算重心放到後段。"
        : "這次檔期沒有綁限時優惠，先用穩定投放，效果最容易判讀。",
    archived: record.archived,
    daily_below_floor: daily < 300,
  };
}

// ---- 目標 CPA 三層鏈（app/ads/target_cpa.py，查證日 2026-08-12，公式原樣搬）----

function budgetTiers(targetCpa: number): TargetCpaView["tiers"] {
  return {
    conservative: { label: "保守", weekly_budget: Math.round(targetCpa * 50 * 100) / 100, formula: `50 × 目標 CPA（${targetCpa}）／週` },
    recommended: { label: "建議", weekly_budget: Math.round(targetCpa * 75 * 100) / 100, formula: `75 × 目標 CPA（${targetCpa}）／週`, default: true },
    aggressive: { label: "積極", weekly_budget: Math.round(targetCpa * 100 * 100) / 100, formula: `100 × 目標 CPA（${targetCpa}）／週` },
  };
}

export function buildTargetCpaView(record: CampaignRecord): TargetCpaView {
  const isConversion = OBJECTIVE_TO_FUNNEL_STAGE[record.objective] === "conversion";
  if (!isConversion) {
    return {
      kind: "non_conversion",
      target_cpa: null,
      volume: null,
      tiers: {},
      range: { low: Math.round(record.budget * 0.7), high: Math.round(record.budget * 1.3), basis_label: "依上期同目標實際花費 ±30%" },
      learning_note: "這個目標不是轉換型，不套用目標 CPA 三層鏈，改看建議花費區間，避免做白工計算。",
    };
  }
  const targetCpa = 180; // 展示用固定值：某產品毛利／過去成交筆數推算出的目標 CPA
  const weeklyBudget = Math.round((record.budget / 14) * 7);
  return {
    kind: "conversion",
    target_cpa: { value: targetCpa, basis_label: "依產品毛利與過去成交筆數推算" },
    volume: {
      weekly_conversions: Math.round((weeklyBudget / targetCpa) * 10) / 10,
      groups_sustainable: Math.max(1, Math.floor(weeklyBudget / targetCpa / 5)),
      cycle_creative_cap: Math.max(2, Math.floor(weeklyBudget / targetCpa / 5) * 4),
    },
    tiers: budgetTiers(targetCpa),
    range: null,
    learning_note: "目標 CPA 是推算值，不是保證值——投放前幾天以「有沒有轉換」為主，別急著用單日 CPA 判斷成敗。",
  };
}

// ---- 帳戶結構（app/ads/account_structure.py:49-104，查證日 2026-08-12，門檻原樣搬）----

function group(role: string, label: string, ratio: number, dailyBudget: number): StructureGroup {
  const daily = Math.round(dailyBudget * 100) / 100;
  return { role, label, ratio: Math.round(ratio * 10000) / 10000, daily_budget: daily, below_floor: daily < 300 };
}

export function buildAccountStructure(record: CampaignRecord): AccountStructure {
  const dailyBudget = record.budget / 14;
  if (dailyBudget < 1500) {
    return {
      tier: "small",
      tier_label: "小預算",
      structure_label: "單一廣告組（不分 CBO／ABO，錢不夠拆）",
      groups: [group("test", "全額投入測試", 1, dailyBudget)],
      note: `日預算約 ${Math.round(dailyBudget).toLocaleString("zh-TW")} 元，低於中預算門檻：硬拆成兩組的話，每組都會低於 Meta 每組日預算下限，兩組都跑不出可判讀的數據。這期全額投入單一測試組。`,
    };
  }
  if (dailyBudget < 5000) {
    return {
      tier: "medium",
      tier_label: "中預算",
      structure_label: "CBO，兩組（驗證＋測試）",
      groups: [group("validation", "已驗證方向", 0.6, dailyBudget * 0.6), group("test", "新受眾／新素材測試", 0.4, dailyBudget * 0.4)],
      note: `日預算約 ${Math.round(dailyBudget).toLocaleString("zh-TW")} 元，用一個 CBO 活動、兩個廣告組：約 60% 留給比較有把握的方向，約 40% 留給新受眾或新素材測試。`,
    };
  }
  return {
    tier: "large",
    tier_label: "大預算",
    structure_label: "雙 CBO：放大＋測試",
    groups: [group("scaling", "放大活動（只放已驗證贏家）", 0.7, dailyBudget * 0.7), group("testing", "測試活動（新概念與迭代版本）", 0.3, dailyBudget * 0.3)],
    note: `日預算約 ${Math.round(dailyBudget).toLocaleString("zh-TW")} 元，開兩個獨立的 CBO 活動：放大活動抓約 70% 預算放已驗證贏家，測試活動抓約 30% 放新概念，用獨立保護預算避免贏家把新測試餓死。`,
  };
}

// ---- 方案卡／具名異議／規則卡（新設計內容，敘事文字為原型示範用，非外部規格）----

export function buildPlanOptions(record: CampaignRecord): PlanOption[] {
  return [
    {
      id: `${record.id}-opt-a`,
      is_recommended: true,
      summary: "以「有感有效」切角主攻暖受眾，搭配限時折扣衝轉換",
      difference: "跟方案 B 的差異：主打切角不同（有感有效 vs 真人見證），受眾配置也不同",
      audience: {
        tiers: {
          cold: { available: true, description: "興趣關鍵字＋類似受眾" },
          warm: { available: true, description: "近 30 天網站訪客再行銷" },
          hot: { available: record.status !== "PLANNING", description: "過去 180 天購買者", reason: record.status === "PLANNING" ? "還沒有夠多的歷史轉換資料" : undefined },
        },
        exclusions: ["近 14 天已購買者"],
      },
      angles: [
        { title: "有感有效", message: "強調產品實際使用後的具體感受，避免誇大字眼", why: "過去投放經驗顯示誇大用詞退貨率偏高" },
        { title: "限時優惠", message: "檔期內下單享折扣，製造行動誘因" },
      ],
      hypotheses: [{ statement: "暖受眾對「有感有效」切角的轉換率會優於冷受眾", verify: "本期投放結束後比對兩組轉換率" }],
    },
    {
      id: `${record.id}-opt-b`,
      is_recommended: false,
      summary: "以「真人見證」切角主攻冷受眾，先求觸及與熟悉度",
      difference: "跟方案 A 的差異：不綁限時優惠，先求品牌熟悉度累積",
      audience: {
        tiers: {
          cold: { available: true, description: "興趣關鍵字＋類似受眾" },
          warm: { available: true, description: "近 30 天網站訪客再行銷" },
          hot: { available: false, reason: "這個方案刻意不觸及熱受眾，避免打擾已成交客戶" },
        },
        exclusions: [],
      },
      angles: [{ title: "真人見證", message: "找實際使用者現身說法，建立信任感" }],
      hypotheses: null,
    },
  ];
}

export function buildDissents(record: CampaignRecord): Dissent[] {
  if (record.status === "PLANNING") return [];
  return [
    {
      id: `${record.id}-dissent-1`,
      target_type: "budget_allocation",
      suggestion: "測試組比例建議拉高到 50%，這個品牌過去驗證方向的樣本數還不夠多",
      reason: "歷史投放紀錄顯示這個品牌只跑過 2 期，「已驗證方向」的可信度還偏低",
    },
  ];
}

export function buildRuleCardsLearned(record: CampaignRecord): RuleCardLearned[] {
  if (record.id !== "cyc-3") return [];
  return [
    { text: "上一期「急迫催促」語氣的素材點擊率雖高，但退貨率也偏高，這期建議避開" },
    { text: "上一期「描繪使用情境」切角的轉換率明顯優於平均，這期可以再驗證一次" },
  ];
}

export const NEW_CYCLE_PRODUCTS = [
  { id: "prod-a", name: "每日益生菌粉包 30 入" },
  { id: "prod-b", name: "深海魚油軟膠囊 90 日份" },
  { id: "prod-c", name: "膠原蛋白胜肽粉包" },
];

// 滑桿檔位（app/ads/routes_common.py:28 SLIDER_STEPS，查證日 2026-08-12，原樣搬）
const SLIDER_STEPS = [1000, 2000, 3000, 5000, 8000, 10000, 15000, 20000, 30000, 50000, 80000, 100000];

export function buildSliderOptions() {
  return SLIDER_STEPS.map((amount) => {
    const MIN_DAILY_BUDGET = 300;
    let days = 14;
    if (amount / days < MIN_DAILY_BUDGET) days = Math.max(7, Math.min(30, Math.floor(amount / MIN_DAILY_BUDGET)));
    const dailyBudget = Math.round((amount / days) * 100) / 100;
    const belowFloor = dailyBudget < MIN_DAILY_BUDGET;
    return {
      amount,
      amount_label: amount.toLocaleString("zh-TW"),
      duration_days: days,
      daily_budget: Math.round(dailyBudget),
      daily_budget_label: Math.round(dailyBudget).toLocaleString("zh-TW"),
      below_floor: belowFloor,
      note: `這筆金額約買到 ${days} 天測試，` + (belowFloor ? "但每天預算偏低，可能只看得出哪張圖有人點，看不出能不能賺錢。" : "足夠看出哪些素材有人點、哪些帶得動成交。"),
    };
  });
}

// app/ads/routes_common.py:33-44（查證日 2026-08-12，原樣搬，5 選項對齊 Meta 官方成效目標分類）
export const NEW_CYCLE_OBJECTIVES = [
  { value: "awareness", label: "知名度", hint: "適合剛起步、還在找哪種說法有人理的階段，先求被更多人看到、記住這個品牌。" },
  { value: "traffic", label: "流量", hint: "適合想把人導去網站或某個頁面，讓更多人點進去看內容或商品。" },
  { value: "engagement", label: "互動", hint: "適合想累積留言、分享、按讚，經營粉專熱度的情況。" },
  { value: "leads", label: "潛在顧客", hint: "適合單價高、需要先收名單、之後再慢慢聊成交的生意。" },
  { value: "sales", label: "銷售", hint: "適合已經有商品頁、想直接看到訂單的情況。" },
];
