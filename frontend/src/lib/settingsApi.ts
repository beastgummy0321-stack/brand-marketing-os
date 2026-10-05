/** 設定頁 API 型別與呼叫（票 B1-settings，契約 `.scratch/grill/GRILL-B1-settings.md`）。
 * 對應 app/main.py 設定頁區塊與 app/core/rule_cards.py。信封格式沿用既有慣例
 * {data, generated_at}，見 lib/api.ts `Envelope<T>`。表單欄位名沿用既有 Jinja 表單
 * （settings.html／settings_ads.html）的既有欄位名，不自創命名。 */
import { fetchOverview } from "./api";
import { apiFetch, readJson, throwIfFailed } from "./http";

export interface ModelChoice {
  id: string;
  name: string;
  price_text: string;
}

export interface TaskModelThinkingRow {
  task_label: string;
  model_label: string;
  thinking_label: string;
}

export interface SettingsData {
  masked_key: string | null;
  api_key_source: "env" | "db" | null;
  db_key_present: boolean;
  model_choices: ModelChoice[];
  current_model: string;
  task_model_thinking_table: TaskModelThinkingRow[];
  intake_budget: number;
  /** 誰的金鑰付錢（票 04-1a，D4-3）：'platform'＝操作者付錢（今天預設）；
   * 'own'＝組織自己的金鑰付錢，月費上限只是參考數字（ai_cap_applies＝false）。 */
  ai_key_source: "platform" | "own";
  ai_cap_applies: boolean;
  /** 這個月整個組織已花的 AI 費用（US$，不分品牌）。 */
  ai_monthly_spend: number;
  /** 組織每月 AI 花費上限（US$）——跟上面 intake_budget（單一品牌、全期）是不同的
   * 兩道關卡，見 SpendCapSection／ApiKeySection 的標籤文案。 */
  ai_monthly_cost_limit: number;
  /** 目前登入者是不是這個組織的擁有者——AI 月費上限只有 owner 可以改。 */
  is_owner: boolean;
}

export interface RuleCardField {
  key: string;
  label: string;
  unit: string;
  help: string;
  value: number;
  /** S15.30「已自訂」標記：現值是否不等於系統預設值。 */
  customized: boolean;
}

export interface RuleCard {
  key: string;
  title: string;
  description: string;
  fields: RuleCardField[];
}

export interface RuleCardsData {
  brand_id: string;
  cards: RuleCard[];
}

export interface BrandOption {
  brand_id: string;
  brand_name: string;
}

interface Envelope<T> {
  data: T;
  generated_at: string;
}

export async function fetchSettings(): Promise<SettingsData> {
  const res = await apiFetch("/api/settings");
  const body = await readJson<Envelope<SettingsData>>(res, `設定讀取失敗（狀態碼 ${res.status}）`);
  return body.data;
}

async function postSettings(path: string, body: Record<string, unknown>): Promise<void> {
  const res = await apiFetch(`/api/settings/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  await throwIfFailed(res, `儲存失敗（狀態碼 ${res.status}）`);
}

export function saveApiKey(apiKey: string): Promise<void> {
  return postSettings("api-key", { api_key: apiKey });
}

export function clearApiKey(): Promise<void> {
  return postSettings("api-key/clear-db", {});
}

export function saveModel(llmModel: string): Promise<void> {
  return postSettings("model", { llm_model: llmModel });
}

/** F50 Contract I: the typed text (`typedValue`), null when blank; the server parses it and refuses with a
 * sentence naming the field. */
export function saveBudget(intakeBudget: string | null): Promise<void> {
  return postSettings("budget", { intake_budget: intakeBudget });
}

/** Same rule as `saveBudget`: the typed text or null. */
export function saveAiMonthlyCostLimit(limit: string | null): Promise<void> {
  return postSettings("ai-monthly-cost-limit", { ai_monthly_cost_limit: limit });
}

/** 品牌選擇器（S15.29）：不新開端點，沿用跨品牌總覽既有回應，只取 brand_id／brand_name
 * 兩欄（見契約「不用新增」節）。 */
export async function fetchBrandOptions(): Promise<BrandOption[]> {
  const cards = await fetchOverview();
  return cards.map((c) => ({ brand_id: c.brand_id, brand_name: c.brand_name }));
}

export async function fetchRuleCards(brandId: string): Promise<RuleCardsData> {
  const res = await apiFetch(`/api/settings/rule-cards/brands/${encodeURIComponent(brandId)}`);
  const body = await readJson<Envelope<RuleCardsData>>(res, `規則卡讀取失敗（狀態碼 ${res.status}）`);
  return body.data;
}

/** F50 Contract I: each field as typed (`typedValue`); the server parses it and refuses with the field's Bounds
 * sentence (`field_errors`). A percent field is the typed percent (70 = 70%). */
export async function saveRuleCard(
  brandId: string,
  cardKey: string,
  fields: Record<string, string>,
): Promise<RuleCard> {
  const res = await apiFetch(
    `/api/settings/rule-cards/brands/${encodeURIComponent(brandId)}/${encodeURIComponent(cardKey)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields),
    },
  );
  const body = await readJson<Envelope<RuleCard>>(res, `規則卡儲存失敗（狀態碼 ${res.status}）`);
  return body.data;
}

export async function resetRuleCard(brandId: string, cardKey: string): Promise<RuleCard> {
  const res = await apiFetch(
    `/api/settings/rule-cards/brands/${encodeURIComponent(brandId)}/${encodeURIComponent(cardKey)}/reset`,
    { method: "POST" },
  );
  const body = await readJson<Envelope<RuleCard>>(res, `規則卡重設失敗（狀態碼 ${res.status}）`);
  return body.data;
}
