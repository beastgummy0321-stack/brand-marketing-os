/** 檔期清單 API 型別與呼叫（票 B4-campaigns，契約 `.scratch/grill/GRILL-B4-campaigns.md`）。
 * 型別逐字對照契約「假資料形狀（TypeScript）」節，不自創欄位（reuse-first.md 第四節）。
 * 狀態文字、目標文字、漏斗階段文字對照 `app/ads/routes_common.py:33-57`／`app/ads/plan.py:60-72`
 * （查證日 2026-08-12），四軸選項對照 `app/ads/fingerprint.py:19-67`（查證日 2026-08-12）——
 * 這幾份是後端已定版的封閉枚舉，前端原型照抄值與標籤，不是自己命名。 */

export type CampaignStatus =
  | "PLANNING" | "PLAN_SELECT" | "REVIEW" | "PRODUCTION" | "LIVE" | "EVALUATING" | "CLOSED";

export type CampaignBucket = "in_progress" | "closed" | "archived";
// in_progress = status !== "CLOSED" && !archived
// closed      = status === "CLOSED" && !archived
// archived    = archived（不分 status，S7.2 既有分類邏輯原樣沿用）

export interface CampaignDataGrade {
  kind: "calibrated" | string;
  label: string;
}

export interface CampaignListItem {
  id: string;
  start_date: string;
  end_date: string;
  status: CampaignStatus;
  status_label: string;
  bucket: CampaignBucket;
  phase_label: string | null;
  objective_label: string;
  funnel_stage_label: string | null;
  budget: number;
  product_names: string[];

  // 僅 bucket === "in_progress" 有值
  stage_index: number | null;
  stage_label: string | null;
  days_left: number | null;

  // 僅 bucket === "closed" 且已判讀過有值，否則全為 null
  roas: number | null;
  status_label_reading: string | null;
  verdict_kind: "ok" | "danger" | "neutral" | null;
  data_grade: CampaignDataGrade | null;
  vs_previous: "▲" | "▼" | "－" | null;
}

export interface CampaignDeleteImpact {
  label: string;
  count: number;
}

export interface InterviewAxisOption {
  value: string;
  label: string;
}

export interface InterviewAxis {
  key: "angle" | "tone" | "format" | "selling_point";
  label: string;
  question: string;
  values: InterviewAxisOption[];
}

export interface InterviewSubmitResult {
  rule_card_count: number;
  hypothesis_count: number;
  conflicts: string[];
}

export interface InterviewSelection {
  bad: Partial<Record<InterviewAxis["key"], string[]>>;
  good: Partial<Record<InterviewAxis["key"], string[]>>;
  note: string;
}

/** 檔期沒有名稱欄位，全站識別一律用起訖日期（`app/ads/routes_plan.py:197 _cycle_label()`）。 */
export function cycleLabel(item: { start_date: string; end_date: string }): string {
  return `${item.start_date} ～ ${item.end_date}`;
}

export const CAMPAIGN_STATUS_LABELS: Record<CampaignStatus, string> = {
  PLANNING: "計畫中",
  PLAN_SELECT: "等你選方案",
  REVIEW: "等你確認計畫",
  PRODUCTION: "做素材中",
  LIVE: "投放中",
  EVALUATING: "等你回填成效",
  CLOSED: "已結束",
};

export const STAGE_LABELS = ["計畫", "素材", "交接包", "投放前檢查", "成效"];

/** 前朝教訓訪談四軸定版選項（決策 0030 第二節，不接受再自創）。 */
export const INTERVIEW_AXES: InterviewAxis[] = [
  {
    key: "angle",
    label: "切角",
    question: "這則素材從哪個角度切入？",
    values: [
      { value: "pain", label: "點出痛點" },
      { value: "benefit", label: "直說好處" },
      { value: "proof", label: "拿證據說話" },
      { value: "testimonial", label: "真人見證" },
      { value: "scene", label: "描繪使用情境" },
      { value: "comparison", label: "對比" },
      { value: "identity", label: "訴諸身份認同" },
      { value: "curiosity", label: "製造好奇" },
    ],
  },
  {
    key: "tone",
    label: "語氣",
    question: "這則素材用什麼口氣講？",
    values: [
      { value: "warm", label: "親切溫暖" },
      { value: "professional", label: "專業可靠" },
      { value: "humorous", label: "幽默有趣" },
      { value: "urgent", label: "急迫催促" },
      { value: "blunt", label: "直白不修飾" },
    ],
  },
  {
    key: "format",
    label: "形式",
    question: "這則素材長什麼樣子？",
    values: [
      { value: "single_image", label: "單張圖" },
      { value: "carousel", label: "多圖輪播" },
      { value: "short_video", label: "短影片" },
      { value: "text_focus", label: "文字圖卡" },
    ],
  },
  {
    key: "selling_point",
    label: "賣點",
    question: "這則素材主打什麼？",
    values: [
      { value: "efficacy", label: "有感有效" },
      { value: "quality", label: "品質好" },
      { value: "price", label: "價格划算" },
      { value: "convenience", label: "方便省事" },
      { value: "uniqueness", label: "別人沒有" },
      { value: "safety", label: "安全無添加" },
    ],
  },
];

interface Envelope<T> {
  data: T;
  generated_at: string;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) {
    throw new Error(res.status === 404 ? "找不到這筆資料。" : `讀取失敗（狀態碼 ${res.status}）`);
  }
  const body: Envelope<T> = await res.json();
  return body.data;
}

async function postJson<T = void>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) {
    let message = `處理失敗（狀態碼 ${res.status}）`;
    try {
      const data = (await res.json()) as { error?: string };
      if (data.error) message = data.error;
    } catch {
      // 回應不是 JSON，用預設訊息。
    }
    throw new Error(message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ---- 檔期清單 ----

export function fetchCampaignList(brandId: string): Promise<CampaignListItem[]> {
  return getJson(`/api/campaigns/brands/${encodeURIComponent(brandId)}`);
}

export function archiveCampaign(brandId: string, cycleId: string): Promise<void> {
  return postJson(
    `/api/campaigns/brands/${encodeURIComponent(brandId)}/${encodeURIComponent(cycleId)}/archive`,
  );
}

// ---- 永久刪除 ----

export function fetchDeleteImpact(brandId: string, cycleId: string): Promise<CampaignDeleteImpact[]> {
  return getJson(
    `/api/campaigns/brands/${encodeURIComponent(brandId)}/${encodeURIComponent(cycleId)}/delete-impact`,
  );
}

export function deleteCampaign(brandId: string, cycleId: string, confirmName: string): Promise<void> {
  return postJson(
    `/api/campaigns/brands/${encodeURIComponent(brandId)}/${encodeURIComponent(cycleId)}/delete`,
    { confirm_name: confirmName },
  );
}

// ---- 前朝教訓訪談 ----

export function submitInterview(brandId: string, selection: InterviewSelection): Promise<InterviewSubmitResult> {
  return postJson(`/api/campaigns/brands/${encodeURIComponent(brandId)}/interview`, selection);
}
