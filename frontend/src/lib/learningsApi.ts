/** 累積智慧 API：型別直接沿用後端既有資料鍵，只為畫面加上已存在的顯示欄位。 */

import { apiFetch } from "./http";

interface Envelope<T> {
  data: T;
  generated_at: string;
}

export interface LearningLedgerEntry {
  id: string;
  learning_text: string;
  meta_line: string;
}

export interface ActiveBan {
  id: string;
  promoted_rule_id: string;
  proposed_rule_text: string;
}

export interface PendingReconfirmRule {
  id: string;
  content: string;
  confirmed_at: string | null;
}

export interface PendingCard {
  id: string;
  proposed_rule_text: string;
}

export interface ObservingSignal {
  axis_label: string;
  value_label: string;
}

export interface PendingHypothesis {
  id: string;
  statement: string;
  status: string;
  status_label: string;
}

export interface OverflowRule {
  id: string;
  content: string;
}

export interface LearningSections {
  learnings: LearningLedgerEntry[];
  active_bans: ActiveBan[];
  pending_reconfirm_rules: PendingReconfirmRule[];
  pending_cards: PendingCard[];
  observing_signals: ObservingSignal[];
  pending_hypotheses: PendingHypothesis[];
  overflow_rules: OverflowRule[];
}

export interface LearningActionResult {
  ok: true;
  message: string;
}

function base(brandId: string): string {
  return `/api/campaigns/brands/${encodeURIComponent(brandId)}/learnings`;
}

async function responseError(res: Response, fallback: string): Promise<never> {
  try {
    const body = (await res.json()) as { detail?: string };
    if (body.detail) throw new Error(body.detail);
  } catch (error) {
    if (error instanceof Error) throw error;
  }
  throw new Error(fallback);
}

export async function fetchLearnings(brandId: string): Promise<LearningSections> {
  const res = await apiFetch(base(brandId));
  if (!res.ok) await responseError(res, `讀取失敗（狀態碼 ${res.status}）`);
  return ((await res.json()) as Envelope<LearningSections>).data;
}

async function act(brandId: string, path: string, body?: unknown): Promise<LearningActionResult> {
  const res = await apiFetch(`${base(brandId)}${path}`, {
    method: "POST",
    ...(body !== undefined ? { headers: { "content-type": "application/json" }, body: JSON.stringify(body) } : {}),
  });
  if (!res.ok) await responseError(res, `處理失敗（狀態碼 ${res.status}）`);
  return (await res.json()) as LearningActionResult;
}

export function deactivateLearning(brandId: string, entryId: string): Promise<LearningActionResult> {
  return act(brandId, `/ledger/${encodeURIComponent(entryId)}/deactivate`);
}

export function deactivateRule(brandId: string, ruleId: string): Promise<LearningActionResult> {
  return act(brandId, `/rules/${encodeURIComponent(ruleId)}/deactivate`);
}

export function reconfirmRule(brandId: string, ruleId: string): Promise<LearningActionResult> {
  return act(brandId, `/rules/${encodeURIComponent(ruleId)}/reconfirm`);
}

/** 規則卡的決定（票 T5-04）：接受才升級為品牌智庫的長期規則，戰情室企劃步驟「同意／不用」
 * 兩顆按鈕走這支，跟累積智慧頁的候選卡是同一批資料、同一支後端函式。 */
export function decideRuleCard(brandId: string, cardId: string, accepted: boolean): Promise<LearningActionResult> {
  return act(brandId, `/rule-cards/${encodeURIComponent(cardId)}/decide`, { accepted });
}
