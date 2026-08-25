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
  product_id: string;
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
  | {
      available: true;
      summary: string;
      suggestion: OpeningSuggestion;
      channel_ask: null;
      budget_basis: "closing_review" | "pain_amount";
    }
  | { available: false; reason: string; channel_ask?: ChannelAsk };

export interface ProposalBlocks {
  channels: ChannelPlan[];
  budget: unknown;
  creatives: unknown;
  tracking: unknown;
  brakes: string[];
  schedule: unknown;
}

export interface ChannelPlan {
  channel: string;
  enabled: boolean;
}

export interface ReadyProposalResponse {
  status: "ready";
  reason: string | null;
  blocks: ProposalBlocks;
  // estimated_generation_cost（票 13）：核可會觸發的預選素材生成，花費上限（不是精準
  // 預估——後端算的是 ceiling，實際花費通常更低），跟矩陣頁 MatrixCell 的
  // estimated_cost 同一個 cost_ceiling 天花板來源（後端 theme_batch.estimated_batch_
  // cost）。畫面文案要講「最多」不要講「預估」，見 ProposalBook.tsx。
  //
  // estimated_generation_timeout_seconds（票 13 付費手測缺陷 2）：後端背景生成的逾時
  // 天花板（後端 _proposal_generate_ceiling_seconds，跟 approve-status 判斷逾時用的
  // 是同一個算式）。前端輪詢的放棄時間點要以這個數字為準，不能寫死一個可能比伺服器
  // 天花板還短的常數——否則畫面會比伺服器先喊「花比較久」，而生成其實快成功了。
  //
  // generation_count（票 13 獨立審查最後一個 blocker）：這次核准實際會跑幾次序列生成
  // （後端 theme_batch.generation_count，跟花費預估／逾時天花板同一份計數）。等待中
  // 的文案要照這個數字講出跟批次規模相稱的等待時間，不能沿用單次生成慣例寫死的秒數
  // ——這條路線是 N 次序列生成，字面上會差好幾倍。
  approval: {
    approved: boolean;
    warning: string | null;
    estimated_generation_cost: number;
    estimated_generation_timeout_seconds: number;
    generation_count: number;
  };
}

export interface ApproveGenerateStatus {
  // partial（票 13）：work() 沒丟例外，但 theme_batch.generate_preselected_batch() 撞到
  // 花費上限提早收手，或部分生成本身失敗——不是靜默成功（done）也不是整批炸掉
  // （failed），message 會講清楚做出了幾份、缺的部分要怎麼辦。
  status: "running" | "done" | "partial" | "failed";
  message?: string;
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
    let message = `處理失敗（狀態碼 ${response.status}）`;
    try {
      const body = (await response.json()) as { error?: string };
      if (body.error) message = body.error;
    } catch {
      // 回應不是 JSON，用預設訊息。
    }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

const brandBase = (brandId: string) => `/api/campaigns/brands/${encodeURIComponent(brandId)}`;
const proposalBase = (brandId: string, cycleId: string) => `${brandBase(brandId)}/cycles/${encodeURIComponent(cycleId)}/proposal`;

export function fetchOpeningSuggestion(brandId: string, fromCycle?: string | null): Promise<OpeningSuggestionResponse> {
  const query = fromCycle ? `?from_cycle=${encodeURIComponent(fromCycle)}` : "";
  return request(`${brandBase(brandId)}/opening-suggestion${query}`);
}

export function answerOpeningChannel(brandId: string, answer: string, fromCycle?: string | null): Promise<void> {
  return request(`${brandBase(brandId)}/opening-suggestion/channel-answer`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ answer, from_cycle: fromCycle ?? null }),
  });
}

export function fetchProposal(brandId: string, cycleId: string): Promise<ProposalResponse> {
  return request(proposalBase(brandId, cycleId));
}

export function approveProposal(brandId: string, cycleId: string): Promise<void> {
  return request(proposalBase(brandId, cycleId) + "/approve", { method: "POST" });
}

/** 核可後背景生成預選素材的進度輪詢（票 13）：跟企劃出方案的 `/plan/status` 同一套
 * `_progress_state` 底層，回應一樣用 `{ data: {...} }` 信封包著，這裡直接拆開回傳。 */
export async function fetchApproveGenerateStatus(brandId: string, cycleId: string): Promise<ApproveGenerateStatus> {
  const body = await request<{ data: ApproveGenerateStatus }>(proposalBase(brandId, cycleId) + "/approve-status");
  return body.data;
}

export function returnProposal(brandId: string, cycleId: string): Promise<void> {
  return request(proposalBase(brandId, cycleId) + "/return", { method: "POST" });
}

export function updateChannelPlan(
  brandId: string,
  cycleId: string,
  channels: ChannelPlan[],
): Promise<{ channels: ChannelPlan[] }> {
  return request(`${brandBase(brandId)}/cycles/${encodeURIComponent(cycleId)}/channel-plan`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ channels: channels.map(({ channel, enabled }) => ({ channel, enabled })) }),
  });
}
