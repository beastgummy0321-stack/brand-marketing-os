/** 全站生成進度單一出口 API 型別與呼叫（票 B4-warroom，`.scratch/grill/GRILL-B4-warroom.md`
 * 「全站生成進度單一出口（模組邊界定案）」節）。型別逐字對照契約「假資料形狀」節的
 * `ActiveJob`——聚合對象刻意只有 intake／products／library 三處既有 `JobRegistry`，
 * 不含廣告模組的生成進度（該模組已於外殼切片刪除），所以 `kind` 沒有任何 campaigns
 * 分支的值。 */

import { apiFetch } from "./http";

export type ActiveJobKind = "scan" | "question" | "paste_fix" | "product_research" | "library_convert" | "brand_report";
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
  product_research: "產品調研",
  library_convert: "智庫轉換",
  brand_report: "顧問分析報告",
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
