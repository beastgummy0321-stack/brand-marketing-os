/** 全站背景工作單一出口 API 型別與呼叫（票 B4-warroom；F29-I05 feature Contract G）。
 * 型別逐欄對照 `app/dashboard/routes_jobs_api.py`：資料來源是 procrastinate 佇列本身，每件
 * 工作都有它在整條佇列裡的位置（進行中排最前面）；其他組織的工作只算進 `other_count`。 */

import { apiFetch } from "./http";

export type ActiveJobKind =
  | "scan" | "persona" | "product_research" | "library_convert"
  | "brand_report" | "schedule_plan" | "schedule_tree" | "schedule_diagnosis" | "workbench_generate"
  | "meta_pull" | "meta_backfill" | "ads_sync" | "ads_runtime" | "ads_review" | "ads_angles"
  | "ads_asset_preview" | "ads_asset_suggestions" | "other";
export type ActiveJobStatus = "running" | "queued";

export interface ActiveJob {
  brand_id: string;
  brand_name: string;
  kind: ActiveJobKind;
  status: ActiveJobStatus;
  stage: string;
  /** ISO time the running job started; "" while queued. */
  started_at: string;
  action_url: string;
  /** 1-based over the whole queue (every tenant), running jobs first. */
  position: number;
  task_name: string;
  scope: { campaign_id?: string; entity_id?: string };
  /** Seconds running (running) or waiting (queued); null for a job scheduled later. */
  waited_seconds: number | null;
}

export interface ActiveJobsSnapshot {
  data: ActiveJob[];
  /** Every queued or running job, all tenants. */
  total: number;
  /** Jobs in `total` that are not listed in `data` (other orgs, or no brand). */
  other_count: number;
  done_today: number;
  failed_today: number;
  generated_at: string;
}

/** Read after 「正在」 too (the top-bar pill says 「正在同步成效」), so every label is a verb phrase. */
export const ACTIVE_JOB_KIND_LABELS: Record<ActiveJobKind, string> = {
  scan: "建檔初掃",
  persona: "生成人物誌",
  product_research: "調研產品",
  library_convert: "轉換智庫原話",
  brand_report: "撰寫顧問分析報告",
  schedule_plan: "出方案",
  schedule_tree: "展開活動樹",
  schedule_diagnosis: "判讀檔期成效",
  workbench_generate: "生成素材",
  meta_pull: "讀取 Meta 花費",
  meta_backfill: "補抓過去的廣告",
  ads_sync: "同步成效",
  ads_runtime: "檢查活動",
  ads_review: "判讀活動成效",
  ads_angles: "整理廣告主打",
  ads_asset_preview: "產生素材預覽",
  ads_asset_suggestions: "產生素材建議",
  other: "處理背景工作",
};

export async function fetchActiveJobs(): Promise<ActiveJobsSnapshot> {
  const res = await apiFetch("/api/jobs/active");
  if (!res.ok) throw new Error(`讀取失敗（狀態碼 ${res.status}）`);
  return (await res.json()) as ActiveJobsSnapshot;
}
