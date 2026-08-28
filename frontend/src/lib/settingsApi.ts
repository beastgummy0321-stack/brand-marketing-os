/** 設定頁 API 型別與呼叫（票 B1-settings，契約 `.scratch/grill/GRILL-B1-settings.md`）。
 * 對應 app/main.py 設定頁區塊與 app/core/rule_cards.py。信封格式沿用既有慣例
 * {data, generated_at}，見 lib/api.ts `Envelope<T>`。表單欄位名沿用既有 Jinja 表單
 * （settings.html／settings_ads.html）的既有欄位名，不自創命名。 */
import { fetchOverview } from "./api";
import { apiFetch } from "./http";

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
  /** 誰的金鑰付錢（票 04-1a，D4-3）：'platform'＝操作者付錢（今天預設）；
   * 'own'＝組織自己的金鑰付錢，月費上限只是參考數字（ai_cap_applies＝false）。 */
  ai_key_source: "platform" | "own";
  ai_cap_applies: boolean;
  /** 這個月整個組織已花的 AI 費用（US$，不分品牌）。 */
  ai_monthly_spend: number;
  /** 組織每月 AI 花費上限（US$）——跟上面 intake_budget（單一品牌、全期）是不同的
   * 兩道關卡，見 AssetsSection／ApiKeySection 的標籤文案。 */
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

/** 品牌層投放自動度的固定編碼：1＝保守檔、2＝放手檔。 */
export type AutonomyMode = 1 | 2;

export interface RuleCardsData {
  brand_id: string;
  /** 後端完整清單；投放自動度由 AutonomySection 專用渲染。 */
  cards: RuleCard[];
}

export interface BrandOption {
  brand_id: string;
  brand_name: string;
}

/** 「連接 Meta 廣告帳戶」卡（票 M1-01，`app/ads/routes_settings.py` `/api/settings/meta-mcp`）：
 * 跟上面既有唯讀 `MetaSection`（成效回讀用金鑰）是完全不同的一組憑證與端點，形狀不共用。 */
export interface MetaMcpPage {
  page_id: string;
  page_name: string;
}

export interface MetaMcpSettingsData {
  ok: boolean;
  account_id?: string;
  reason?: string;
  pages?: MetaMcpPage[];
  pages_error?: string | null;
  selected_page_id?: string | null;
}

interface Envelope<T> {
  data: T;
  generated_at: string;
}

export async function fetchSettings(): Promise<SettingsData> {
  const res = await apiFetch("/api/settings");
  if (!res.ok) {
    throw new Error(`設定讀取失敗（狀態碼 ${res.status}）`);
  }
  const body: Envelope<SettingsData> = await res.json();
  return body.data;
}

async function postSettings(path: string, body: Record<string, unknown>): Promise<void> {
  const res = await apiFetch(`/api/settings/${path}`, {
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

export function saveAiMonthlyCostLimit(limit: number): Promise<void> {
  return postSettings("ai-monthly-cost-limit", { ai_monthly_cost_limit: limit });
}

export async function fetchMetaMcpStatus(): Promise<MetaMcpSettingsData> {
  const res = await apiFetch("/api/settings/meta-mcp");
  if (!res.ok) {
    throw new Error(`讀取失敗（狀態碼 ${res.status}）`);
  }
  const body: Envelope<MetaMcpSettingsData> = await res.json();
  return body.data;
}

export async function saveMetaMcpPage(pageId: string): Promise<void> {
  const res = await apiFetch("/api/settings/meta-mcp/page", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ page_id: pageId }),
  });
  if (!res.ok) {
    let message = `儲存失敗（狀態碼 ${res.status}）`;
    try {
      const body = (await res.json()) as { error?: string };
      if (body.error) message = body.error;
    } catch {
      // 回應不是 JSON，用預設訊息。
    }
    throw new Error(message);
  }
}

export async function fetchStylePreference(brandId: string): Promise<{ text: string }> {
  const res = await apiFetch(`/api/settings/brands/${encodeURIComponent(brandId)}/style-preference`);
  if (!res.ok) throw new Error(`風格偏好讀取失敗（狀態碼 ${res.status}）`);
  return res.json() as Promise<{ text: string }>;
}

export async function saveStylePreference(brandId: string, text: string): Promise<{ text: string }> {
  const res = await apiFetch(`/api/settings/brands/${encodeURIComponent(brandId)}/style-preference`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) {
    let message = `儲存失敗（狀態碼 ${res.status}）`;
    try {
      const body = (await res.json()) as { error?: string };
      if (body.error) message = body.error;
    } catch {
      // 回應不是 JSON，用預設訊息。
    }
    throw new Error(message);
  }
  return res.json() as Promise<{ text: string }>;
}

/** 品牌選擇器（S15.29）：不新開端點，沿用跨品牌總覽既有回應，只取 brand_id／brand_name
 * 兩欄（見契約「不用新增」節）。 */
export async function fetchBrandOptions(): Promise<BrandOption[]> {
  const cards = await fetchOverview();
  return cards.map((c) => ({ brand_id: c.brand_id, brand_name: c.brand_name }));
}

export async function fetchRuleCards(brandId: string): Promise<RuleCardsData> {
  const res = await apiFetch(`/api/settings/rule-cards/brands/${encodeURIComponent(brandId)}`);
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
  const res = await apiFetch(
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
  const res = await apiFetch(
    `/api/settings/rule-cards/brands/${encodeURIComponent(brandId)}/${encodeURIComponent(cardKey)}/reset`,
    { method: "POST" },
  );
  if (!res.ok) {
    throw new Error(`規則卡重設失敗（狀態碼 ${res.status}）`);
  }
  const body: Envelope<RuleCard> = await res.json();
  return body.data;
}

export interface CalendarCategory {
  category: string;
  label: string;
  /** true＝正常提醒；false＝這個品牌永久關閉這個節日的提醒。 */
  enabled: boolean;
}

export interface CalendarCategoriesData {
  brand_id: string;
  categories: CalendarCategory[];
}

export async function fetchCalendarCategories(brandId: string): Promise<CalendarCategoriesData> {
  const res = await apiFetch(`/api/settings/calendar/brands/${encodeURIComponent(brandId)}`);
  if (!res.ok) {
    throw new Error(`節日提醒清單讀取失敗（狀態碼 ${res.status}）`);
  }
  const body: Envelope<CalendarCategoriesData> = await res.json();
  return body.data;
}

export async function toggleCalendarCategory(
  brandId: string,
  category: string,
  enabled: boolean,
): Promise<CalendarCategory> {
  const res = await apiFetch(
    `/api/settings/calendar/brands/${encodeURIComponent(brandId)}/${encodeURIComponent(category)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    },
  );
  if (!res.ok) {
    throw new Error(`節日提醒開關更新失敗（狀態碼 ${res.status}）`);
  }
  const body: Envelope<CalendarCategory> = await res.json();
  return body.data;
}
