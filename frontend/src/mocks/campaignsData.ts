/** 假資料源（票 B4-campaigns，畫面契約「假資料要求（醜資料）」節）。跟其他 feature 的假
 * 資料源各自獨立、各自可整包刪除——不共用 id 計數器或 store。公開的 `CampaignListItem`
 * 形狀只有契約定義的欄位；`background` 這種內部欄位（S8 詳情頁會沿用同一份假資料源，見
 * 契約「這次合併判斷」第三點）放在 `CampaignRecord`，不混進對外回應形狀。 */
import {
  CAMPAIGN_STATUS_LABELS,
  STAGE_LABELS,
  type CampaignBucket,
  type CampaignDataGrade,
  type CampaignDeleteImpact,
  type CampaignListItem,
  type CampaignStatus,
} from "@/lib/campaignsApi";

const OBJECTIVE_LABELS: Record<string, string> = {
  awareness: "知名度",
  traffic: "流量",
  engagement: "互動",
  leads: "潛在顧客",
  sales: "銷售",
};

const OBJECTIVE_TO_FUNNEL_STAGE: Record<string, string> = {
  awareness: "exposure",
  traffic: "consideration",
  engagement: "consideration",
  leads: "conversion",
  sales: "conversion",
};

const FUNNEL_STAGE_LABELS: Record<string, string> = {
  exposure: "曝光層",
  consideration: "考慮層",
  conversion: "轉換層",
};

interface CampaignReading {
  roas: number;
  status_label_reading: string;
  verdict_kind: "ok" | "danger" | "neutral";
  data_grade: CampaignDataGrade;
  vs_previous: "▲" | "▼" | "－";
}

export interface CampaignRecord {
  id: string;
  start_date: string;
  end_date: string;
  status: CampaignStatus;
  archived: boolean;
  phase: "simulation" | null;
  objective: string;
  /** 舊資料沒有這個推導鍵時漏斗階段徽章不顯示，跟 `pacing_strategy` 缺鍵的既有前例同精神
   * （`app/ads/routes_common.py` `_cycle_view()` 註解）。 */
  funnelStageKnown: boolean;
  budget: number;
  product_names: string[];
  /** S8 詳情頁會沿用同一份假資料源（契約段落「假資料要求」第 4 點），本輪清單不顯示。 */
  background: string;
  stage_index: number | null;
  days_left: number | null;
  reading: CampaignReading | null;
  deleteImpact: CampaignDeleteImpact[];
  /** S7.21：本期日花費曲線縮圖（取自排期規劃的逐日陣列，`null`＝沒有這份資料，舊檔期
   * 常見情形，S7.22）。 */
  dailyBudgets: number[] | null;
}

function daysBetween(start: string, end: string): number {
  const ms = new Date(end).getTime() - new Date(start).getTime();
  return Math.max(1, Math.round(ms / 86400000) + 1);
}

/** S7.21 假資料：沒有真正的排期規劃逐日陣列可查，用「先穩後衝」的平滑曲線近似
 * （跟 `pacing_curve.compute_curve()` 常見形狀同精神），純展示縮圖用，不代表真實逐日數字。 */
function buildDailyBudgetTrend(startDate: string, endDate: string, budget: number): number[] {
  const days = Math.min(30, daysBetween(startDate, endDate));
  const dailyAvg = budget / days;
  return Array.from({ length: days }, (_, i) =>
    Math.round(dailyAvg * (0.7 + 0.6 * Math.sin((i / Math.max(1, days - 1)) * Math.PI))),
  );
}

let idCounter = 0;
function nextId(): string {
  idCounter += 1;
  return `cyc-${idCounter}`;
}

const LONG_PRODUCT_NAMES = [
  "頂級膠原蛋白胜肽複方粉包（葡萄柚風味）30 入禮盒裝",
  "深海魚油 Omega-3 高濃縮軟膠囊 90 日份家庭號",
  "專利乳酸菌益生菌粉末隨身包（無添加糖配方）60 入",
  "天然植萃玻尿酸保濕精華液尊爵版 50ml 雙入組",
  "有機薑黃薑黃素高吸收率複方錠劑 180 錠瓶裝",
  "北歐藍藻螺旋藻綜合維他命礦物質咀嚼錠 120 錠",
];

const LONG_BACKGROUND =
  "這個品牌從 2021 年開始經營，一開始主要透過 Facebook 社團口碑擴散，客群集中在 35 到 50 歲的" +
  "上班族女性，後來陸續開拓 Instagram 與 LINE 官方帳號兩個通路。過去投放的經驗顯示，強調「有感」" +
  "「立即見效」這類誇大字眼的素材雖然點擊率高，但退貨率也明顯偏高，客服反映的抱怨集中在「效果" +
  "沒有廣告講的那麼快」。品牌主後來調整策略，改用比較保守務實的說法，例如強調「持續使用」「搭配" +
  "均衡飲食」這類但書，退貨率確實下降，但點擊率也跟著掉了一截，目前還在嘗試找兩者的平衡點。" +
  "另外品牌主提過，去年雙十一檔期因為同時衝刺兩個平台（蝦皮＋官網），倉庫爆單導致出貨延遲，" +
  "客訴大量湧入，這件事讓品牌主對「衝量」這件事變得比較保守，寧可穩紮穩打也不要重演一次。" +
  "產品線目前以保健食品為主，未來有計畫要往保養品延伸，但還在評估法規與成分供應商，這部分" +
  "還沒有明確時間表，暫時不列入本期的規劃考量範圍內，之後如果有進度會再另外補充說明。";

function buildRecord(input: {
  status: CampaignStatus;
  archived: boolean;
  start_date: string;
  end_date: string;
  objective: string;
  budget: number;
  product_names: string[];
  phase?: "simulation" | null;
  funnelStageKnown?: boolean;
  background?: string;
  stage_index?: number | null;
  days_left?: number | null;
  reading?: CampaignReading | null;
  deleteImpact?: CampaignDeleteImpact[];
  /** 只有 S7.23 醜資料（示範「陣列存在但 bucket !== closed 仍顯示『—』」）才需要手動給值；
   * 其餘記錄由 bucket／已判讀與否自動推算，不必逐筆手填。 */
  dailyBudgets?: number[] | null;
}): CampaignRecord {
  const bucket = input.archived ? "archived" : input.status === "CLOSED" ? "closed" : "in_progress";
  const dailyBudgets =
    input.dailyBudgets !== undefined
      ? input.dailyBudgets
      : bucket === "closed" && input.reading != null
        ? buildDailyBudgetTrend(input.start_date, input.end_date, input.budget)
        : null;
  return {
    id: nextId(),
    start_date: input.start_date,
    end_date: input.end_date,
    status: input.status,
    archived: input.archived,
    phase: input.phase ?? null,
    objective: input.objective,
    funnelStageKnown: input.funnelStageKnown ?? true,
    budget: input.budget,
    product_names: input.product_names,
    background: input.background ?? "",
    stage_index: input.stage_index ?? null,
    days_left: input.days_left ?? null,
    reading: input.reading ?? null,
    deleteImpact: input.deleteImpact ?? [],
    dailyBudgets,
  };
}

/** 15 期檔期：進行中 5、已結案 8、已封存 2（契約「假資料要求」第 1 點）。 */
export const campaignsStore: CampaignRecord[] = [
  // ---- 進行中（5）----
  buildRecord({
    status: "PLANNING", archived: false,
    start_date: "2026-08-01", end_date: "2026-08-31",
    objective: "awareness", budget: 6000,
    product_names: LONG_PRODUCT_NAMES, // 醜資料：6 個以上超長產品名
    stage_index: 1, days_left: 19,
  }),
  buildRecord({
    status: "PLAN_SELECT", archived: false,
    start_date: "2026-08-05", end_date: "2026-09-05",
    objective: "traffic", budget: 12000,
    product_names: ["每日益生菌粉包 30 入"],
    stage_index: 1, days_left: 24,
  }),
  buildRecord({
    status: "REVIEW", archived: false,
    start_date: "2026-07-20", end_date: "2026-08-20",
    objective: "leads", budget: 9000,
    product_names: [], // 醜資料：空陣列顯示「整個品牌」
    stage_index: 2, days_left: 8,
  }),
  buildRecord({
    status: "PRODUCTION", archived: false,
    start_date: "2026-08-10", end_date: "2026-09-10",
    objective: "engagement", budget: 15000,
    product_names: ["深海魚油軟膠囊 90 日份"],
    phase: "simulation", // 醜資料：紙上模擬徽章
    stage_index: 2, days_left: 29,
  }),
  buildRecord({
    status: "LIVE", archived: false,
    start_date: "2026-07-01", end_date: "2026-08-31",
    objective: "sales", budget: 20000,
    product_names: ["膠原蛋白胜肽粉包", "薑黃複方錠劑"],
    funnelStageKnown: false, // 醜資料：funnel_stage 為 null，漏斗階段徽章不顯示
    background: LONG_BACKGROUND, // 醜資料：background 500 字以上
    stage_index: 4, days_left: 19,
  }),

  // ---- 已結案（8）----
  buildRecord({
    status: "CLOSED", archived: false,
    start_date: "2026-05-01", end_date: "2026-05-31",
    objective: "sales", budget: 10000,
    product_names: ["膠原蛋白胜肽粉包"],
    reading: {
      roas: 2.35, status_label_reading: "賺",
      verdict_kind: "ok", data_grade: { kind: "calibrated", label: "已校準" },
      vs_previous: "▲",
    },
  }),
  buildRecord({
    status: "CLOSED", archived: false,
    start_date: "2026-04-01", end_date: "2026-04-30",
    objective: "sales", budget: 7000,
    product_names: ["薑黃複方錠劑"],
    // 醜資料：虧損檔期，roas 負值、成色「未校準」、走 danger 分支
    reading: {
      roas: -0.42, status_label_reading: "賠",
      verdict_kind: "danger", data_grade: { kind: "uncalibrated", label: "未校準" },
      vs_previous: "▼",
    },
  }),
  buildRecord({
    status: "CLOSED", archived: false,
    start_date: "2026-03-01", end_date: "2026-03-31",
    objective: "traffic", budget: 5000,
    product_names: ["每日益生菌粉包 30 入"],
    reading: null, // 醜資料：完全沒判讀過，ROAS／成色顯示「—」
  }),
  buildRecord({
    status: "CLOSED", archived: false,
    start_date: "2026-02-01", end_date: "2026-02-28",
    objective: "awareness", budget: 4000,
    product_names: ["深海魚油軟膠囊 90 日份"],
    reading: {
      roas: 1.1, status_label_reading: "打平",
      verdict_kind: "neutral", data_grade: { kind: "calibrated", label: "已校準" },
      vs_previous: "－",
    },
  }),
  buildRecord({
    status: "CLOSED", archived: false,
    start_date: "2026-01-01", end_date: "2026-01-31",
    objective: "leads", budget: 11000,
    product_names: ["膠原蛋白胜肽粉包", "每日益生菌粉包 30 入"],
    reading: {
      roas: 3.02, status_label_reading: "賺",
      verdict_kind: "ok", data_grade: { kind: "calibrated", label: "已校準" },
      vs_previous: "▲",
    },
  }),
  buildRecord({
    status: "CLOSED", archived: false,
    start_date: "2025-12-01", end_date: "2025-12-31",
    objective: "engagement", budget: 6500,
    product_names: ["薑黃複方錠劑"],
    reading: {
      roas: 0.85, status_label_reading: "賠",
      verdict_kind: "danger", data_grade: { kind: "uncalibrated", label: "未校準" },
      vs_previous: "▼",
    },
  }),
  buildRecord({
    status: "CLOSED", archived: false,
    start_date: "2025-11-01", end_date: "2025-11-30",
    objective: "sales", budget: 9000,
    product_names: ["膠原蛋白胜肽粉包"],
    reading: {
      roas: 1.98, status_label_reading: "賺",
      verdict_kind: "ok", data_grade: { kind: "calibrated", label: "已校準" },
      vs_previous: "▲",
    },
  }),
  buildRecord({
    status: "CLOSED", archived: false,
    start_date: "2025-10-01", end_date: "2025-10-31",
    objective: "traffic", budget: 5000,
    product_names: ["每日益生菌粉包 30 入"],
    reading: {
      roas: 1.02, status_label_reading: "打平",
      verdict_kind: "neutral", data_grade: { kind: "calibrated", label: "已校準" },
      vs_previous: "－",
    },
  }),

  // ---- 已封存（2）----
  buildRecord({
    status: "CLOSED", archived: true,
    start_date: "2025-09-01", end_date: "2025-09-30",
    objective: "sales", budget: 7000,
    product_names: ["膠原蛋白胜肽粉包"],
    reading: {
      roas: 1.5, status_label_reading: "賺",
      verdict_kind: "ok", data_grade: { kind: "calibrated", label: "已校準" },
      vs_previous: "▲",
    },
    // 醜資料：示範永久刪除確認側板，>=2 個項目 >0 筆
    deleteImpact: [
      { label: "廣告素材", count: 12 },
      { label: "成效判讀", count: 1 },
      { label: "投放交接包", count: 1 },
    ],
  }),
  buildRecord({
    status: "LIVE", archived: true,
    start_date: "2025-08-01", end_date: "2025-08-31",
    objective: "awareness", budget: 4000,
    product_names: ["每日益生菌粉包 30 入"],
    deleteImpact: [], // 對照組：封存但底下沒有任何連帶資料
    // 醜資料（S7.23）：dailyBudgets 陣列存在但 bucket 是 "archived" 不是 "closed"，
    // 驗證趨勢欄仍要顯示「—」，不能因為陣列存在就提早畫縮圖。
    dailyBudgets: buildDailyBudgetTrend("2025-08-01", "2025-08-31", 4000),
  }),
];

export function findCampaign(id: string): CampaignRecord | undefined {
  return campaignsStore.find((r) => r.id === id);
}

export function bucketOf(record: CampaignRecord): CampaignBucket {
  if (record.archived) return "archived";
  return record.status === "CLOSED" ? "closed" : "in_progress";
}

export function toListItem(record: CampaignRecord): CampaignListItem {
  const bucket = bucketOf(record);
  const funnelStage = record.funnelStageKnown ? OBJECTIVE_TO_FUNNEL_STAGE[record.objective] : null;
  const reading = record.status === "CLOSED" ? record.reading : null;
  return {
    id: record.id,
    start_date: record.start_date,
    end_date: record.end_date,
    status: record.status,
    status_label: CAMPAIGN_STATUS_LABELS[record.status],
    bucket,
    phase_label: record.phase === "simulation" ? "紙上模擬" : null,
    objective_label: OBJECTIVE_LABELS[record.objective] ?? record.objective,
    funnel_stage_label: funnelStage ? FUNNEL_STAGE_LABELS[funnelStage] : null,
    budget: record.budget,
    product_names: record.product_names,
    stage_index: bucket === "in_progress" ? record.stage_index : null,
    stage_label: bucket === "in_progress" && record.stage_index ? STAGE_LABELS[record.stage_index - 1] : null,
    days_left: bucket === "in_progress" ? record.days_left : null,
    roas: reading?.roas ?? null,
    status_label_reading: reading?.status_label_reading ?? null,
    verdict_kind: reading?.verdict_kind ?? null,
    data_grade: reading?.data_grade ?? null,
    vs_previous: reading?.vs_previous ?? null,
    // S7.21-23：只有 bucket === "closed" 才可能有值，其餘（進行中／封存）一律 null → 表格顯示「—」。
    trend_daily_budgets: bucket === "closed" ? record.dailyBudgets : null,
  };
}
