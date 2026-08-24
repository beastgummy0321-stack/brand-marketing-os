/** 提案書「物件區塊」通用欄位格式化（B0-30／B0-37：預算配置、追蹤健檢兩種完全不同的資料
 * 結構，用舊版「印出所有欄位值、丟掉鍵名」的寫法各自漏出裸資料庫欄位黏成一串）。
 *
 * 這支不是為那兩個區塊各寫一份格式化，是給 ProposalBook.tsx 的 `ProposalValue` 一套通用
 * 規則：任何物件的鍵值都印得出「標籤：值」，內部識別碼（id／*_id／時間戳）一律不對使用者
 * 顯示——下一種新區塊類型長出新的資料形狀時，套用同一支就好，不必再開一次同樣的病。
 *
 * 純函式、不含 JSX，可以直接被 Node 執行（見同層 `proposalFieldFormat.selfcheck.mts`），
 * 也是 ProposalBook.tsx 匯入的同一份邏輯，不是各自抄一份。
 */

// 明確帶副檔名（tsconfig `allowImportingTsExtensions`）：這支檔案要能被
// `node proposalFieldFormat.selfcheck.mts` 直接執行（見同層檔案），Node 原生 ESM loader
// 不像 Vite/tsc 的 bundler 解析模式會自動補副檔名。
import { formatCurrency, formatPercent, formatSyncTime } from "./format.ts";
import { TRACKING_CHANNEL_LABELS } from "./trackingChannelLabels.ts";

/** 純內部識別碼：對使用者顯示「ccp_01…」「brd_01…」這種字串不會有任何意義，一律不顯示
 * （跟 B0-11「不把內部代號當人話說」同一個鐵則）。 */
export function isInternalIdKey(key: string): boolean {
  return key === "id" || key.endsWith("_id");
}

/** 建立／更新時間戳：對非工程背景的品牌主幾乎沒有可行動的意義，一律不顯示。 */
const HIDDEN_FIELD_KEYS = new Set(["created_at", "updated_at"]);

export function shouldHideField(key: string): boolean {
  return isInternalIdKey(key) || HIDDEN_FIELD_KEYS.has(key);
}

/** 已知欄位的白話標籤；不在表裡的鍵名退回「底線換空格」，至少看得出是哪個欄位，不會沒有
 * 標籤地把值原封不動印出來。 */
const FIELD_LABELS: Record<string, string> = {
  product_name: "產品",
  allocated_budget: "分配預算",
  allocation_ratio: "佔比",
  allocation_basis: "分配依據",
  economics_missing: "缺毛利資料",
  key: "項目",
  status: "狀態",
  sub: "細節",
  checked_at: "上次檢查",
  hidden: "已隱藏",
  message: "說明",
  action: "後續動作",
  kind: "類型",
  missing: "還缺",
  url: "網址",
  needs_setup: "還要設定",
  note: "備註",
  // 預算配置區塊（app/ads/proposal.py:77-83）。
  budget: "總預算",
  allocations: "各產品分配",
  forecast: "成效預估",
  // 追蹤健檢區塊（app/ads/tracking.py:587）。
  channels: "通路清單",
  ready: "已就緒",
  total: "追蹤路數",
};

export function fieldLabel(key: string): string {
  return FIELD_LABELS[key] ?? key.replace(/_/g, " ");
}

/** 這兩個區塊本身就有的內部代號式列舉值。日後遇到新的列舉值就加一行，不是重寫整支
 * 渲染邏輯（同一種「登記制」精神，比照 FIELD_LABELS）。 */
const VALUE_LABELS: Record<string, string> = {
  economics: "依產品毛利",
  estimated: "用平均毛利估算",
  even: "平均分配",
  ok: "沒問題",
  off: "尚未設定",
  bad: "異常",
  warn: "還沒驗到",
  install: "去裝追蹤碼",
  fill: "去補資料",
  none: "不用處理",
  // 追蹤健檢五路通路的 key 值（app/ads/tracking.py:539-546、552-…）；跟
  // TrackingHealthPage.tsx 的 CHANNEL_CONFIG 共用同一份標籤，不重複打一次。
  ...TRACKING_CHANNEL_LABELS,
};

const ISO_DATETIME_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/;

/** 物件裡一個純量欄位（字串／數字／布林）的顯示文字。`key` 給了才套用金額／佔比這類
 * 需要知道欄位語意的格式化；沒有 key（陣列項目、區塊頂層純量）就只做通用格式化。 */
export function formatScalarField(value: string | number | boolean, key?: string): string {
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "number") {
    if (key && /budget|amount|cost/i.test(key)) return formatCurrency(value);
    if (key && /ratio/i.test(key)) return formatPercent(value);
    return value.toLocaleString("zh-TW");
  }
  if (ISO_DATETIME_RE.test(value)) return formatSyncTime(value);
  return VALUE_LABELS[value] ?? value;
}
