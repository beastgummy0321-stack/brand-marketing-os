/** 收件匣 API 型別與呼叫（票 B1-inbox，契約 `.scratch/grill/GRILL-B1-inbox.md`）。
 * 對應 app/core/interrupts.py（待辦／已結清單）與 app/core/prototype_phase.py（側板）。
 * 信封格式沿用既有慣例 {data, generated_at}，見 lib/api.ts `Envelope<T>`。 */
import type { AlertSeverity } from "./api";
import { apiFetch } from "./http";

export type InboxSeverity = AlertSeverity;

export interface InboxItem {
  id: string;
  brand_id: string | null;
  /** null＝全站事項（S2.3）。 */
  brand_name: string | null;
  category: string;
  category_label: string;
  severity: InboxSeverity;
  message: string;
  /** null＝沒有「詳情」可去（S2.7）。 */
  action_url: string | null;
  /** ISO 字串；已結清單才有值（S2.12）。 */
  resolved_at: string | null;
}

export interface InboxData {
  open: InboxItem[];
  done: InboxItem[];
}

interface Envelope<T> {
  data: T;
  generated_at: string;
}

export async function fetchInbox(): Promise<InboxData> {
  const res = await apiFetch("/api/inbox");
  if (!res.ok) {
    throw new Error(`收件匣讀取失敗（狀態碼 ${res.status}）`);
  }
  const body: Envelope<InboxData> = await res.json();
  return body.data;
}

export interface PrototypePhaseExemption {
  item: string;
  status: string;
}

export interface PrototypePhaseDetail {
  ended: boolean;
  /** 固定 4 筆（S2.17）。 */
  exemptions: PrototypePhaseExemption[];
}

export async function fetchPrototypePhase(): Promise<PrototypePhaseDetail> {
  const res = await apiFetch("/api/system/prototype-phase");
  if (!res.ok) {
    throw new Error(`原型階段詳情讀取失敗（狀態碼 ${res.status}）`);
  }
  const body: Envelope<PrototypePhaseDetail> = await res.json();
  return body.data;
}
