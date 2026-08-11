/** 假資料源（票 B2-products，畫面契約第 1 段）。跟 `mocks/data.ts`（品牌智庫）各自獨立、
 * 各自可整包刪除——不共用 id 計數器或 store，只共用「假資料只放 mocks/ 目錄」這條規則。
 * 固定選項清單改從 `lib/productsApi.ts` import（唯一來源），這裡不重複定義。 */
import {
  CLAIM_TYPES,
  CURRENCIES,
  optionLabel,
  PRODUCT_FACT_TYPES,
  RULE_TYPES,
  type ClaimType,
  type ProductClaim,
  type ProductDeleteImpact,
  type ProductDetailBundle,
  type ProductEconomics,
  type ProductFact,
  type ProductListItem,
  type ProductRule,
  type ResearchJobState,
} from "@/lib/productsApi";

let idCounter = 0;
function nextId(prefix: string): string {
  idCounter += 1;
  return `${prefix}-${idCounter}`;
}

interface ProductRecord {
  id: string;
  name: string;
  status: "active" | "archived";
  knowledge_version: number;
  latest_source_url: string | null;
  facts: ProductFact[];
  economics: ProductEconomics | null;
  claims: ProductClaim[];
}

const BRAND_ID = "mock-brand";
const PRODUCT_COUNT = 25;

// ---- 品牌層規則（product_id = null，套用到所有產品）----
const BRAND_RULES: ProductRule[] = [
  {
    id: "rule-brand-1",
    severity: "hard",
    rule_type: "forbidden_word",
    rule_type_label: optionLabel(RULE_TYPES, "forbidden_word"),
    content: "不得使用「療效」「治癒」等醫療用語。",
    product_id: null,
  },
  {
    id: "rule-brand-2",
    severity: "soft",
    rule_type: "tone",
    rule_type_label: optionLabel(RULE_TYPES, "tone"),
    content: "文案語氣維持溫暖、口語化，避免生硬的條列式賣點堆疊。",
    product_id: null,
  },
];

// ---- 品牌層宣稱（product_id = null）----
const BRAND_CLAIMS: ProductClaim[] = [
  {
    id: "claim-brand-1",
    claim_type: "approved",
    claim_text: "本品牌成分皆通過第三方檢驗。",
    evidence_source_reference: "2025-03 第三方成分檢驗報告",
    product_id: null,
  },
  {
    id: "claim-brand-2",
    claim_type: "forbidden",
    claim_text: "絕對禁止提到「醫療級」字樣。",
    evidence_source_reference: null,
    product_id: null,
  },
];

function buildFacts(productIndex: number): ProductFact[] {
  if (productIndex === 1) return []; // 剛建立、AI 還沒跑完：事實數與待確認數都是 0
  const facts: ProductFact[] = [];
  const confirmedCount = productIndex === 0 ? 30 : 2 + (productIndex % 4);
  for (let i = 0; i < confirmedCount; i++) {
    const factType = PRODUCT_FACT_TYPES[i % PRODUCT_FACT_TYPES.length][0];
    facts.push({
      id: nextId("pfact"),
      fact_type: factType,
      fact_type_label: optionLabel(PRODUCT_FACT_TYPES, factType),
      label: `事實摘要 ${i + 1}：${optionLabel(PRODUCT_FACT_TYPES, factType)}相關的既定作法`,
      value: `這是第 ${i + 1} 筆已確認的產品事實內容，說明「${optionLabel(PRODUCT_FACT_TYPES, factType)}」這個面向的具體做法。`,
      status: "confirmed",
      confirmed_by: i % 2 === 0 ? "小陳" : "客戶窗口 Amy",
      confirmed_at: new Date(Date.now() - (30 + i) * 86_400_000).toISOString(),
      source_reference: i % 3 === 0 ? null : "2025-03 客戶提供的產品型錄 p.4",
    });
  }
  // 至少一筆 AI 快掃寫入的中文詞、不在六個內建鍵裡（S6.22 fallback 顯示測試）
  if (productIndex === 0) {
    facts.push({
      id: nextId("pfact"),
      fact_type: "價格帶",
      fact_type_label: "價格帶",
      label: "定價落在中高價位帶",
      value: "AI 快掃從產品頁抓到的定價描述，尚未對應到六個內建分類鍵，原樣顯示中文詞。",
      status: "confirmed",
      confirmed_by: "AI 快掃",
      confirmed_at: new Date().toISOString(),
      source_reference: null,
    });
  }
  const pendingCount = productIndex === 0 ? 23 : productIndex % 3; // 產品 0 測兩位數待確認
  for (let i = 0; i < pendingCount; i++) {
    const factType = PRODUCT_FACT_TYPES[i % PRODUCT_FACT_TYPES.length][0];
    facts.push({
      id: nextId("pfact"),
      fact_type: factType,
      fact_type_label: optionLabel(PRODUCT_FACT_TYPES, factType),
      label: `待確認事實 ${i + 1}：${optionLabel(PRODUCT_FACT_TYPES, factType)}相關的暫定說法`,
      value: `AI 調研抓到但還沒人確認的內容，暫記為「${optionLabel(PRODUCT_FACT_TYPES, factType)}」的候選內容。`,
      status: "pending",
      confirmed_by: null,
      confirmed_at: null,
      source_reference: null,
    });
  }
  return facts;
}

function buildEconomics(productIndex: number): ProductEconomics | null {
  const currency = CURRENCIES[0][0];
  if (productIndex % 4 === 1) return null; // 尚未填寫
  if (productIndex % 4 === 2) {
    // 待確認：AI 快掃只抓到售價，刻意用 0 測「經濟數字 0」的醜資料
    return {
      selling_price: 0,
      fixed_cost: null,
      unit_variable_cost: null,
      shipping_cost: null,
      currency,
      cpa_roas_basis: null,
      effective_from: null,
      status: "pending",
      confirmed_by: null,
    };
  }
  // 已確認，其中一筆刻意用負數運費（活動折抵）測「經濟數字負數」的醜資料
  return {
    selling_price: 590 + productIndex * 10,
    fixed_cost: 5000,
    unit_variable_cost: 120,
    shipping_cost: productIndex === 3 ? -30 : 80,
    currency,
    cpa_roas_basis: "以月結算，含平台抽成",
    effective_from: "2026-01-01",
    status: "confirmed",
    confirmed_by: "小陳",
  };
}

function buildProductClaims(productIndex: number): ProductClaim[] {
  if (productIndex !== 0) return [];
  return [
    {
      id: nextId("pclaim"),
      claim_type: "high_risk" as ClaimType,
      claim_text: "有助於提升代謝效率。",
      evidence_source_reference: null, // 高風險缺佐證，觸發警示
      product_id: "product-0",
    },
    {
      id: nextId("pclaim"),
      claim_type: CLAIM_TYPES[0][0],
      claim_text: "本產品原料來自可追溯產地。",
      evidence_source_reference: "2025-06 供應商產地證明",
      product_id: "product-0",
    },
  ];
}

function buildProducts(): ProductRecord[] {
  const products: ProductRecord[] = [];
  for (let i = 0; i < PRODUCT_COUNT; i++) {
    const status: "active" | "archived" = i % 5 === 4 ? "archived" : "active";
    const name =
      i === 0
        ? "日常薑黃錠 60 錠・旗艦升級版・加量不加價限定包裝（2026 春季共同開發專案聯名紀念版）"
        : `品項 ${i + 1} 號商品`;
    products.push({
      id: `product-${i}`,
      name,
      status,
      knowledge_version: 1 + (i % 4),
      latest_source_url: i % 3 === 0 ? null : `https://example-brand.com/products/item-${i}`,
      facts: buildFacts(i),
      economics: buildEconomics(i),
      claims: buildProductClaims(i),
    });
  }
  return products;
}

function productRulesFor(record: ProductRecord): ProductRule[] {
  const own: ProductRule[] =
    record.id === "product-0"
      ? [
          {
            id: "rule-product-0-own",
            severity: "hard",
            rule_type: "platform_spec",
            rule_type_label: optionLabel(RULE_TYPES, "platform_spec"),
            content: "這款產品的廣告素材一律要露出成分表特寫。",
            product_id: record.id,
          },
        ]
      : [];
  return [...BRAND_RULES, ...own];
}

function productClaimsFor(record: ProductRecord): ProductClaim[] {
  return [...BRAND_CLAIMS, ...record.claims];
}

function toListItem(record: ProductRecord): ProductListItem {
  const pending = record.facts.filter((f) => f.status === "pending").length;
  return {
    id: record.id,
    name: record.name,
    status: record.status,
    fact_count: record.facts.length,
    pending_fact_count: pending,
    economics_status: record.economics === null ? "none" : record.economics.status,
  };
}

function toDetailBundle(record: ProductRecord): ProductDetailBundle {
  const pendingFacts = record.facts.filter((f) => f.status === "pending").length;
  const rules = productRulesFor(record);
  const claims = productClaimsFor(record);
  return {
    id: record.id,
    brand_id: BRAND_ID,
    name: record.name,
    status: record.status,
    knowledge_version: record.knowledge_version,
    cards: [
      { key: "facts", title: "產品事實", count: record.facts.length, pending: pendingFacts },
      {
        key: "economics-view",
        title: "產品經濟數字",
        count: record.economics ? 1 : 0,
        pending: record.economics?.status === "pending" ? 1 : 0,
      },
      { key: "rules", title: "適用規則", count: rules.length, pending: 0 },
      { key: "claims", title: "適用宣稱", count: claims.length, pending: 0 },
    ],
    latest_source_url: record.latest_source_url,
    economics_pending: record.economics?.status === "pending",
    facts: record.facts,
    economics: record.economics,
    rules,
    claims,
  };
}

function deleteImpactFor(record: ProductRecord): ProductDeleteImpact[] {
  const rows: ProductDeleteImpact[] = [
    { label: "產品事實", count: record.facts.length },
    { label: "產品經濟數字", count: record.economics ? 1 : 0 },
    { label: "產品專屬規則", count: record.id === "product-0" ? 1 : 0 },
    { label: "產品專屬宣稱", count: record.claims.length },
  ];
  return rows.filter((r) => r.count > 0);
}

/** 可變的正常態資料倉庫（比照 `mocks/data.ts` 的 `libraryStore` 寫法）。 */
export let productsStore: ProductRecord[] = buildProducts();

export function resetProductsStore(): void {
  idCounter = 0;
  productsStore = buildProducts();
}

export function findProduct(productId: string): ProductRecord | undefined {
  return productsStore.find((p) => p.id === productId);
}

export function normalProductList(): ProductListItem[] {
  return productsStore.map(toListItem);
}

export function productDetail(productId: string): ProductDetailBundle | null {
  const record = findProduct(productId);
  return record ? toDetailBundle(record) : null;
}

export function productDeleteImpact(productId: string): ProductDeleteImpact[] {
  const record = findProduct(productId);
  return record ? deleteImpactFor(record) : [];
}

export { nextId };
export type { ProductRecord };

// ---- 背景調研工作狀態（S6.29–S6.31）：跟品牌智庫的顧客原話 job map 是同一種模式，
// 各自獨立的 Map，不共用。key = product_id，一個產品同時只會有一份調研在跑。 ----
export const researchJobs = new Map<string, ResearchJobState>();

/** 預先固定兩個產品的調研狀態，讓原型不用手動觸發就能直接看到「進行中」「失敗」的樣子
 * （task 指示「背景調研假資料要能切換三種樣子」）：
 * - product-1：facts 是空的（剛建立），調研永遠停在「進行中」，已等秒數隨瀏覽時間增加。
 * - product-4：調研已經「失敗」，開著錯誤列＋「知道了」按鈕。
 * 其餘產品沒有 job，代表「完成」（或從未調研過）的一般穩態，跟大多數產品一樣。 */
export function seedResearchJobs(): void {
  researchJobs.set("product-1", {
    status: "running",
    stage: "整理事實中",
    started_at: new Date(Date.now() - 12_000).toISOString(),
    usual_range_text: "30 到 60 秒",
    error: null,
    added_count: null,
    price_created: false,
  });
  researchJobs.set("product-4", {
    status: "failed",
    stage: "整理事實中",
    started_at: new Date(Date.now() - 40_000).toISOString(),
    usual_range_text: "30 到 60 秒",
    error:
      "這個品牌目前已經花了 US$ 12.40，這次調研預估要花 US$ 0.30，會超過設定頁目前的 US$ 12.50 花費上限。可以到「設定」頁調高上限，或先用「新增這個產品」手動建立。",
    added_count: null,
    price_created: false,
  });
}
seedResearchJobs();
