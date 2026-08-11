/** 假資料源（票 B2-library，畫面契約第 1 段，見 `~/.claude/screen-contract.md` 第十二節）。
 * 單一目錄、單一入口——散落在元件裡的假資料一律禁止。固定選項清單一律從 `lib/libraryApi.ts`
 * import（那裡才是唯一來源，照抄 `app/mock_data.py:20-156`，查證日 2026-08-11），這裡不重複
 * 定義——app 元件也讀同一份，兩邊選項才不會兜不起來。示範內容本身（人名、品牌名、評論原文）
 * 是虛構情境，不對應任何後端既有資料。 */
import {
  ASSET_KINDS,
  BRAND_FACT_TYPES,
  CHANNEL_TYPES,
  CLAIM_TYPES,
  CUSTOMER_VOICE_CHANNELS,
  optionLabel,
  RULE_TYPES,
  type ClaimType,
  type CustomerVoiceExtractionItem,
  type CustomerVoiceSignal,
  type CustomerVoiceTaskLayer,
  type LibraryAsset,
  type LibraryBrandFact,
  type LibraryBrandProfile,
  type LibraryChannel,
  type LibraryClaim,
  type LibraryCustomerVoice,
  type LibraryData,
  type LibraryProductOption,
  type LibraryRule,
  type RuleSeverity,
} from "@/lib/libraryApi";

let idCounter = 0;
function nextId(prefix: string): string {
  idCounter += 1;
  return `${prefix}-${idCounter}`;
}

// ---- 產品清單（供各分頁「適用範圍」下拉；至少一筆長名稱測試不爆版）----

const PRODUCTS: LibraryProductOption[] = [
  { id: "product-1", name: "薑黃暖薑飲" },
  { id: "product-2", name: "青花椰精華液" },
  { id: "product-3", name: "冷壓初榨橄欖油禮盒組（2026 春季限定版・附贈木製托盤）" },
];

function scopeLabel(productId: string | null): string {
  if (!productId) return "整個品牌";
  return PRODUCTS.find((p) => p.id === productId)?.name ?? productId;
}

// ---- 品牌事實：30+ 筆，含逾期未確認、超長名稱 ----

function buildFacts(): LibraryBrandFact[] {
  const facts: LibraryBrandFact[] = [];
  const confirmedCount = 20;
  for (let i = 0; i < confirmedCount; i++) {
    const factType = BRAND_FACT_TYPES[i % BRAND_FACT_TYPES.length][0];
    const staleDaysAgo = i === 0 ? 210 : 30 + (i % 5) * 20; // 第一筆刻意逾 180 天
    facts.push({
      id: nextId("fact"),
      fact_type: factType,
      fact_type_label: optionLabel(BRAND_FACT_TYPES, factType),
      label:
        i === 1
          ? "品牌核心定位敘述長版本測試用超長事實名稱：主打天然發酵、可追溯產地、無添加防腐劑的健康零食線"
          : `事實摘要 ${i + 1}：${optionLabel(BRAND_FACT_TYPES, factType)}相關的既定作法`,
      value:
        `這是第 ${i + 1} 筆已確認的品牌事實內容，說明品牌在「${optionLabel(BRAND_FACT_TYPES, factType)}」` +
        `這個面向的具體做法與依據，供 AI 生成內容時直接引用。`,
      status: "confirmed",
      confirmed_by: i % 3 === 0 ? "小陳" : "客戶窗口 Amy",
      confirmed_at: new Date(Date.now() - staleDaysAgo * 86_400_000).toISOString(),
      stale_label: staleDaysAgo > 180 ? `上次確認 ${Math.round(staleDaysAgo / 30)} 個月前` : null,
      source_reference: i % 4 === 0 ? null : "2025-03 客戶提供的品牌手冊 p.12",
    });
  }
  const pendingCount = 12;
  for (let i = 0; i < pendingCount; i++) {
    const factType = BRAND_FACT_TYPES[i % BRAND_FACT_TYPES.length][0];
    facts.push({
      id: nextId("fact"),
      fact_type: factType,
      fact_type_label: optionLabel(BRAND_FACT_TYPES, factType),
      label: `待確認事實 ${i + 1}：${optionLabel(BRAND_FACT_TYPES, factType)}相關的暫定說法`,
      value: `這條還沒跟客戶對過，先暫記為「${optionLabel(BRAND_FACT_TYPES, factType)}」的候選內容。`,
      status: "pending",
      confirmed_by: null,
      confirmed_at: null,
      stale_label: null,
      source_reference: null,
    });
  }
  return facts;
}

// ---- 限制規則：30+ 筆，severity 兩種都涵蓋，含產品範圍 ----

function buildRules(): LibraryRule[] {
  const rules: LibraryRule[] = [];
  const count = 32;
  for (let i = 0; i < count; i++) {
    const ruleType = RULE_TYPES[i % RULE_TYPES.length][0];
    const severity: RuleSeverity = i % 3 === 0 ? "hard" : "soft";
    const productId = i % 5 === 0 ? PRODUCTS[i % PRODUCTS.length].id : null;
    rules.push({
      id: nextId("rule"),
      rule_type: ruleType,
      rule_type_label: optionLabel(RULE_TYPES, ruleType),
      content: `第 ${i + 1} 條規則：${optionLabel(RULE_TYPES, ruleType)}相關，內容產出時${severity === "hard" ? "一定要擋下" : "盡量照做"}。`,
      severity,
      product_id: productId,
      scope_label: scopeLabel(productId),
      source_reference: i % 2 === 0 ? "2025-03 客戶提供的品牌手冊" : null,
    });
  }
  return rules;
}

// ---- 宣稱：三類都涵蓋，高風險至少一筆缺佐證，30+ 筆 ----

function buildClaims(): LibraryClaim[] {
  const claims: LibraryClaim[] = [];
  const count = 33;
  for (let i = 0; i < count; i++) {
    const claimType = CLAIM_TYPES[i % CLAIM_TYPES.length][0] as ClaimType;
    const productId = i % 6 === 0 ? PRODUCTS[i % PRODUCTS.length].id : null;
    const missingEvidence = claimType === "high_risk" && i % 6 === 1; // 至少一筆高風險缺佐證
    claims.push({
      id: nextId("claim"),
      claim_text: `宣稱第 ${i + 1} 則：本產品${claimType === "forbidden" ? "絕對禁止提到療效字樣" : "具有第三方檢驗支持的功效描述"}。`,
      claim_type: claimType,
      product_id: productId,
      scope_label: scopeLabel(productId),
      evidence_source_reference:
        claimType === "forbidden" || missingEvidence ? null : "2025-03 第三方成分檢驗報告",
    });
  }
  return claims;
}

// ---- 官方素材：30+ 筆，含壞圖與無標題 ----

/** 縮圖用內嵌 SVG data URI，不打真的網路請求（安全規則「禁止真實網路請求」對前端假資料
 * 同樣適用，不能因為只是佔位圖就打去外部圖床）。純色塊＋種類文字，夠用來測格線與壞圖態。 */
const THUMB_COLORS = ["#0369a1", "#b45309", "#1e7a46", "#8b2f6b", "#0f6e75", "#7a4a1e"];
function placeholderThumb(seed: number, text: string): string {
  const color = THUMB_COLORS[seed % THUMB_COLORS.length];
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="320" height="240">` +
    `<rect width="320" height="240" fill="${color}"/>` +
    `<text x="160" y="124" font-family="sans-serif" font-size="20" fill="#fff" text-anchor="middle">${text}</text>` +
    `</svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

function buildAssets(): LibraryAsset[] {
  const assets: LibraryAsset[] = [];
  const count = 30;
  for (let i = 0; i < count; i++) {
    const kind = ASSET_KINDS[i % ASSET_KINDS.length][0] as LibraryAsset["asset_kind"];
    const productId = i % 4 === 0 ? PRODUCTS[i % PRODUCTS.length].id : null;
    const broken = i === 2; // 至少一筆指向不存在的檔案，測壞圖態
    assets.push({
      id: nextId("asset"),
      asset_kind: kind,
      asset_kind_label: optionLabel(ASSET_KINDS, kind),
      title: i === 4 ? null : `${optionLabel(ASSET_KINDS, kind)}素材 ${i + 1}`,
      product_id: productId,
      product_name: productId ? scopeLabel(productId) : null,
      file_url: broken
        ? "/brands/mock-brand/assets/file/does-not-exist/missing.png"
        : placeholderThumb(i, optionLabel(ASSET_KINDS, kind)),
    });
  }
  return assets;
}

// ---- 自有渠道：30+ 筆，含超長網址 ----

function buildChannels(): LibraryChannel[] {
  const channels: LibraryChannel[] = [];
  const count = 30;
  for (let i = 0; i < count; i++) {
    const type = CHANNEL_TYPES[i % CHANNEL_TYPES.length][0] as LibraryChannel["channel_type"];
    channels.push({
      id: nextId("channel"),
      channel_type: type,
      channel_type_label: optionLabel(CHANNEL_TYPES, type),
      name: `渠道帳號 ${i + 1}`,
      identifier:
        i === 3
          ? "https://example-shop.com/collections/2026-spring-limited-edition-gift-set/products/turmeric-ginger-warm-drink-30-packs-bundle?utm_source=instagram&utm_medium=bio-link&utm_campaign=spring-launch"
          : type === "website"
            ? `https://example-brand-${i}.com`
            : `@brand_channel_${i}`,
      status: i % 5 === 0 ? "inactive" : "active",
    });
  }
  return channels;
}

// ---- 顧客原話：30+ 筆，含空抽取結果、超長原文 ----

const SIGNAL_CYCLE: CustomerVoiceSignal[] = ["unprompted", "prompted"];
const TASK_LAYER_CYCLE: CustomerVoiceTaskLayer[] = ["functional", "emotional", "social"];

function buildExtraction(seed: number): CustomerVoiceExtractionItem[] {
  if (seed % 7 === 0) return []; // 至少一筆 AI 抽取為空陣列
  const n = 1 + (seed % 3);
  return Array.from({ length: n }, (_, j) => ({
    task_layer: TASK_LAYER_CYCLE[(seed + j) % TASK_LAYER_CYCLE.length],
    quote: `「用了大概兩週之後感覺真的有差，本來很擔心踩雷第 ${seed + j} 次」`,
    insight: "顧客在意的是實際見效時間，不是成分表本身。",
    signal: SIGNAL_CYCLE[(seed + j) % SIGNAL_CYCLE.length],
  }));
}

function buildCustomerVoices(): LibraryCustomerVoice[] {
  const voices: LibraryCustomerVoice[] = [];
  const activeCount = 24;
  for (let i = 0; i < activeCount; i++) {
    const channel = CUSTOMER_VOICE_CHANNELS[i % CUSTOMER_VOICE_CHANNELS.length][0];
    const longText = i === 5;
    voices.push({
      id: nextId("cv"),
      source_channel: channel,
      source_channel_label: optionLabel(CUSTOMER_VOICE_CHANNELS, channel),
      source_detail: i % 3 === 0 ? null : `商品評論區，2026-0${(i % 6) + 1}`,
      raw_text: longText
        ? "這是一段刻意拉很長的原文，用來測試 <details> 收合不會撐爆卡片：".repeat(40) +
          "整體來說用起來還算滿意，唯一比較在意的是包裝的密封性，運送途中有一次微微滲漏，但客服處理得很快，補寄了一份新的過來，讓人覺得售後有被照顧到，這點會列入是否回購的考量之一。"
        : "剛拿到的時候有點半信半疑，用了兩週之後真的有感，會再回購。",
      status: "active",
      extraction: buildExtraction(i),
    });
  }
  const archivedCount = 8;
  for (let i = 0; i < archivedCount; i++) {
    const channel = CUSTOMER_VOICE_CHANNELS[i % CUSTOMER_VOICE_CHANNELS.length][0];
    voices.push({
      id: nextId("cv"),
      source_channel: channel,
      source_channel_label: optionLabel(CUSTOMER_VOICE_CHANNELS, channel),
      source_detail: null,
      raw_text: "已封存的舊評論內容，之前抽取過重點，現在先收起來不影響目前的清單。",
      status: "archived",
      extraction: [],
    });
  }
  return voices;
}

function buildProfile(
  status: "active" | "archived",
  impact: { label: string; count: number }[],
): LibraryBrandProfile {
  return {
    id: "mock-brand",
    name: "阿福環保收納 測試品牌",
    client_name: "自營",
    status,
    market_region: "TW",
    conversion_goal: "purchase",
    industry: "home_lifestyle",
    delete_impact: impact.filter((row) => row.count > 0),
  };
}

/** 正常態：六分頁皆有資料，品牌狀態設為「已封存」方便直接點進危險區驗兩步刪除。 */
export function buildNormalLibrary(): LibraryData {
  const facts = buildFacts();
  const rules = buildRules();
  const claims = buildClaims();
  const assets = buildAssets();
  const channels = buildChannels();
  const customer_voices = buildCustomerVoices();
  return {
    brand: buildProfile("archived", [
      { label: "品牌事實", count: facts.length },
      { label: "限制規則", count: rules.length },
      { label: "宣稱", count: claims.length },
      { label: "官方素材", count: assets.length },
      { label: "自有渠道", count: channels.length },
      { label: "顧客原話", count: customer_voices.length },
    ]),
    products: PRODUCTS,
    facts,
    rules,
    claims,
    assets,
    channels,
    customer_voices,
  };
}

/** 空態：六分頁皆空、也沒有任何產品（測 S5.18「品牌沒有產品」），品牌狀態「使用中」
 * 方便驗危險區鎖住的樣子。 */
export function buildEmptyLibrary(): LibraryData {
  return {
    brand: buildProfile("active", []),
    products: [],
    facts: [],
    rules: [],
    claims: [],
    assets: [],
    channels: [],
    customer_voices: [],
  };
}

/** 可變的正常態資料倉庫：POST 端點直接改這裡，GET 端點原樣回傳，讓原型看起來像真的能存檔
 * （票 B2-library；比照 B1 rule-cards 的可變 store 寫法）。「空」情境固定回傳全空結構，
 * 不受這裡的異動影響——跟 B1 INBOX_EMPTY／INBOX_NORMAL 分兩份常數是同一個理由。 */
export let libraryStore: LibraryData = buildNormalLibrary();

export function resetLibraryStore(): void {
  libraryStore = buildNormalLibrary();
}

export { nextId };
