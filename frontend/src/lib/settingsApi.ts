/** 設定頁 API 型別與呼叫（票 B1-settings，契約 `.scratch/grill/GRILL-B1-settings.md`）。
 * 對應 app/main.py 設定頁區塊與 app/core/rule_cards.py。信封格式沿用既有慣例
 * {data, generated_at}，見 lib/api.ts `Envelope<T>`。表單欄位名沿用既有 Jinja 表單
 * （settings.html／settings_ads.html）的既有欄位名，不自創命名。 */
import { fetchOverview } from "./api";

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
  masked_meta_token: string | null;
  meta_account_id: string;
  masked_ga4_key: string | null;
  ga4_property_id: string;
  creative_root: string;
  prompt_header: string;
  intake_budget: number;
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
  /** 固定 6 張（S15.30）。 */
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
  const res = await fetch("/api/settings");
  if (!res.ok) {
    throw new Error(`設定讀取失敗（狀態碼 ${res.status}）`);
  }
  const body: Envelope<SettingsData> = await res.json();
  return body.data;
}

async function postSettings(path: string, body: Record<string, unknown>): Promise<void> {
  const res = await fetch(`/api/settings/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`儲存失敗（狀態碼 ${res.status}）`);
  }
}

export function saveMeta(metaAccountId: string, metaToken: string): Promise<void> {
  return postSettings("meta", { meta_account_id: metaAccountId, meta_token: metaToken });
}

export function saveGa4(propertyId: string, serviceAccountJson: string): Promise<void> {
  return postSettings("ga4", {
    ga4_property_id: propertyId,
    ga4_service_account_json: serviceAccountJson,
  });
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

export function saveCreativeRoot(creativeRoot: string): Promise<void> {
  return postSettings("creative-root", { creative_root: creativeRoot });
}

export function savePromptHeader(promptHeader: string): Promise<void> {
  return postSettings("prompt-header", { prompt_header: promptHeader });
}

export function saveBudget(intakeBudget: number): Promise<void> {
  return postSettings("budget", { intake_budget: intakeBudget });
}

/** 品牌選擇器（S15.29）：不新開端點，沿用跨品牌總覽既有回應，只取 brand_id／brand_name
 * 兩欄（見契約「不用新增」節）。 */
export async function fetchBrandOptions(): Promise<BrandOption[]> {
  const cards = await fetchOverview();
  return cards.map((c) => ({ brand_id: c.brand_id, brand_name: c.brand_name }));
}

export async function fetchRuleCards(brandId: string): Promise<RuleCardsData> {
  const res = await fetch(`/api/settings/rule-cards/brands/${encodeURIComponent(brandId)}`);
  if (!res.ok) {
    throw new Error(`規則卡讀取失敗（狀態碼 ${res.status}）`);
  }
  const body: Envelope<RuleCardsData> = await res.json();
  return body.data;
}

export async function saveRuleCard(
  brandId: string,
  cardKey: string,
  fields: Record<string, number>,
): Promise<RuleCard> {
  const res = await fetch(
    `/api/settings/rule-cards/brands/${encodeURIComponent(brandId)}/${encodeURIComponent(cardKey)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields),
    },
  );
  if (!res.ok) {
    throw new Error(`規則卡儲存失敗（狀態碼 ${res.status}）`);
  }
  const body: Envelope<RuleCard> = await res.json();
  return body.data;
}

export async function resetRuleCard(brandId: string, cardKey: string): Promise<RuleCard> {
  const res = await fetch(
    `/api/settings/rule-cards/brands/${encodeURIComponent(brandId)}/${encodeURIComponent(cardKey)}/reset`,
    { method: "POST" },
  );
  if (!res.ok) {
    throw new Error(`規則卡重設失敗（狀態碼 ${res.status}）`);
  }
  const body: Envelope<RuleCard> = await res.json();
  return body.data;
}
