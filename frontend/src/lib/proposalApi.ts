/**
 * 提案書 API 的唯一進入點。
 *
 * - 輸入／輸出：`fetchOpeningSuggestion`、`answerOpeningChannel`、`fetchProposal`、
 *   `approveProposal`、`returnProposal` 的參數與回傳型別均逐字對照 F1 API 契約。
 * - 呼叫端：`components/campaigns/OpeningSuggestionCard.tsx` 與
 *   `components/warroom/ProposalBook.tsx`。
 * - 不碰：不 import 元件或 `warroomApi.ts` 的內部實作；不在前端保存任何提案狀態。
 */

export interface OpeningSuggestion {
  platform: string;
  product_id: number;
  product_name: string;
  budget: number;
  duration_days: number;
  direction: string;
}

export interface ChannelAsk {
  question: string;
  options: string[];
}

export type OpeningSuggestionResponse =
  | { available: true; summary: string; suggestion: OpeningSuggestion; channel_ask: null }
  | { available: false; reason: string; channel_ask?: ChannelAsk };

export interface ProposalBlocks {
  channels: unknown;
  budget: unknown;
  creatives: unknown;
  tracking: unknown;
  brakes: string[];
  schedule: unknown;
}

export interface ReadyProposalResponse {
  status: "ready";
  reason: string | null;
  blocks: ProposalBlocks;
  approval: { approved: boolean; warning: string | null };
}

export interface PendingProposalResponse {
  status: "assembling" | "failed";
  reason: string | null;
  blocks: Record<string, never>;
  approval: Record<string, never>;
}

export type ProposalResponse = ReadyProposalResponse | PendingProposalResponse;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    const error = new Error(response.status === 404 ? "找不到這筆資料。" : `讀取失敗（狀態碼 ${response.status}）`);
    error.name = String(response.status);
    throw error;
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

const brandBase = (brandId: string) => `/api/campaigns/brands/${encodeURIComponent(brandId)}`;
const proposalBase = (brandId: string, cycleId: string) => `${brandBase(brandId)}/cycles/${encodeURIComponent(cycleId)}/proposal`;

export function fetchOpeningSuggestion(brandId: string): Promise<OpeningSuggestionResponse> {
  return request(`${brandBase(brandId)}/opening-suggestion`);
}

export function answerOpeningChannel(brandId: string, answer: string): Promise<void> {
  return request(`${brandBase(brandId)}/opening-suggestion/channel-answer`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ answer }),
  });
}

export function fetchProposal(brandId: string, cycleId: string): Promise<ProposalResponse> {
  return request(proposalBase(brandId, cycleId));
}

export function approveProposal(brandId: string, cycleId: string): Promise<void> {
  return request(proposalBase(brandId, cycleId) + "/approve", { method: "POST" });
}

export function returnProposal(brandId: string, cycleId: string): Promise<void> {
  return request(proposalBase(brandId, cycleId) + "/return", { method: "POST" });
}
