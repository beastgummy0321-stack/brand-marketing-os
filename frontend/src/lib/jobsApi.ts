/** 全站生成進度單一出口 API 型別與呼叫（票 B4-warroom，`.scratch/grill/GRILL-B4-warroom.md`
 * 「全站生成進度單一出口（模組邊界定案）」節）。型別逐字對照契約「假資料形狀」節的
 * `ActiveJob`——聚合對象刻意只有 intake／products／library 三處既有 `JobRegistry`，
 * 不含廣告模組的生成進度（該模組已於外殼切片刪除），所以 `kind` 沒有任何 campaigns
 * 分支的值。2026-09-06 演練後補上排程三個 kind（出方案／展開活動樹／產素材）：它們是產品
 * 裡最慢的三個工作，原本按下去按鈕變灰、鈴鐺卻寫「目前沒有進行中的背景工作」。 */

import { apiFetch } from "./http";

export type ActiveJobKind = "scan" | "question" | "paste_fix" | "persona" | "product_research" | "library_convert" | "brand_report" | "schedule_plan" | "schedule_tree" | "workbench_generate";
export type ActiveJobStatus = "waiting" | "running" | "done" | "failed";

export interface ActiveJob {
  brand_id: string;
  brand_name: string;
  kind: ActiveJobKind;
  status: ActiveJobStatus;
  stage: string;
  started_at: string;
  action_url: string;
}

export const ACTIVE_JOB_KIND_LABELS: Record<ActiveJobKind, string> = {
  scan: "建檔初掃",
  question: "建檔問答",
  paste_fix: "建檔貼回修格式",
  persona: "人物誌生成",
  product_research: "產品調研",
  library_convert: "智庫轉換",
  brand_report: "顧問分析報告",
  schedule_plan: "出方案",
  schedule_tree: "展開活動樹",
  workbench_generate: "素材生成",
};

interface Envelope<T> {
  data: T;
  generated_at: string;
}

export async function fetchActiveJobs(): Promise<ActiveJob[]> {
  const res = await apiFetch("/api/jobs/active");
  if (!res.ok) throw new Error(`讀取失敗（狀態碼 ${res.status}）`);
  const body: Envelope<ActiveJob[]> = await res.json();
  return body.data;
}
