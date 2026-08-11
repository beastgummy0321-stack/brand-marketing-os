/** 假資料源（票 B1-inbox／B1-settings，畫面契約第 1 段，見 `~/.claude/screen-contract.md`
 * 第十二節）。單一目錄、單一入口——散落在元件裡的假資料一律禁止。真實文案／數值來源標在
 * 各常數註解，能對到後端既有原始碼的一律照抄，不自創外部形狀。 */
import type { InboxData, InboxItem, PrototypePhaseDetail } from "@/lib/inboxApi";
import type { DashboardBrandCard } from "@/lib/api";
import type {
  BrandOption,
  ModelChoice,
  RuleCard,
  RuleCardsData,
  SettingsData,
  TaskModelThinkingRow,
} from "@/lib/settingsApi";

// ---------------------------------------------------------------------------
// 收件匣（S2）
// ---------------------------------------------------------------------------

/** 對照真實 `app/core/interrupts.py` CATEGORIES（10 筆）；另外兩筆
 * `ad_account_suspended`／`brand_delete_scheduled` 是示範用（該檔目前登記表裡還沒有任何
 * 類別觸發 money_loss／irreversible，兩級也要在畫面上看得到，先放兩筆情境示範——真實類別
 * 出現後這裡直接刪掉改用真的，見契約 S2.4 假資料要求「四種 severity 各至少一筆」）。 */
const CATEGORY_SEVERITY: Record<string, { severity: InboxItem["severity"]; label: string }> = {
  cycle_reminder: { severity: "informational", label: "檔期提醒" },
  code_surge_alert: { severity: "rule_warning", label: "用碼異常警示" },
  revenue_reconcile_due: { severity: "informational", label: "營收對帳提醒" },
  reading_reversal: { severity: "rule_warning", label: "判讀翻盤警示" },
  repurchase_conflict: { severity: "rule_warning", label: "回購校正異議" },
  hypothesis_unresolved: { severity: "informational", label: "假設待結案" },
  prototype_phase_ended: { severity: "rule_warning", label: "原型階段結束提醒" },
  auto_sync_failed: { severity: "rule_warning", label: "自動同步失敗" },
  pacing_overspend: { severity: "rule_warning", label: "檔期步調－燒太快" },
  pacing_underspend: { severity: "rule_warning", label: "檔期步調－花不完" },
  ad_account_suspended: { severity: "money_loss", label: "廣告帳戶已停權" },
  brand_delete_scheduled: { severity: "irreversible", label: "品牌刪除已排程" },
};
const CATEGORY_KEYS = Object.keys(CATEGORY_SEVERITY);

/** index 0＝全站事項（null）；index 1 刻意取長字串（契約假資料要求）。 */
const INBOX_BRANDS: { id: string | null; name: string | null }[] = [
  { id: null, name: null },
  { id: "brand-1", name: "測試用超長品牌名稱有限公司　旗艦生活風格系列" },
  { id: "brand-2", name: "小島野餐" },
  { id: "brand-3", name: "北風羊毛" },
  { id: "brand-4", name: "深夜廚房" },
];

function buildOpenItems(): InboxItem[] {
  const items: InboxItem[] = [];
  const total = 42; // 契約要求「待辦清單至少 40 筆」
  for (let i = 0; i < total; i++) {
    const category = CATEGORY_KEYS[i % CATEGORY_KEYS.length];
    const meta = CATEGORY_SEVERITY[category];
    const brand = INBOX_BRANDS[i % INBOX_BRANDS.length];
    items.push({
      id: `open-${i}`,
      brand_id: brand.id,
      brand_name: brand.name,
      category,
      category_label: meta.label,
      severity: meta.severity,
      message:
        i === 0
          ? "本期步調偏差已連續三天超過門檻，建議儘快調整每日預算配置"
          : `${meta.label}：第 ${i + 1} 筆待處理事項`,
      action_url:
        category === "prototype_phase_ended"
          ? "/system/prototype-phase"
          : i % 5 === 0
            ? null
            : `/brands/brand-1/ads/cycle-${i}`,
      resolved_at: null,
    });
  }
  return items;
}

function buildDoneItems(): InboxItem[] {
  // 天數 offset：含 0（今天結案）與 400（很久以前，測試「N 天前」文案不爆版）。
  const offsetsDays = [0, 1, 3, 10, 45, 400, 2, 7];
  const now = Date.now();
  return offsetsDays.map((offset, i) => {
    const category = CATEGORY_KEYS[i % CATEGORY_KEYS.length];
    const meta = CATEGORY_SEVERITY[category];
    const brand = INBOX_BRANDS[i % INBOX_BRANDS.length];
    return {
      id: `done-${i}`,
      brand_id: brand.id,
      brand_name: brand.name,
      category,
      category_label: meta.label,
      severity: meta.severity,
      message: `${meta.label}：已處理完成的第 ${i + 1} 筆`,
      action_url: i % 3 === 0 ? null : `/brands/brand-1/ads/cycle-${i}`,
      resolved_at: new Date(now - offset * 86_400_000).toISOString(),
    };
  });
}

export const INBOX_NORMAL: InboxData = { open: buildOpenItems(), done: buildDoneItems() };
export const INBOX_EMPTY: InboxData = { open: [], done: [] };

/** 逐字對照真實 `app/core/prototype_phase.py` EXEMPTIONS（2026-08-03 盤點版本）。 */
export const PROTOTYPE_PHASE_EXEMPTIONS = [
  {
    item: "明文 API 金鑰入庫",
    status:
      "修憲落地 M4 已把環境變數 ANTHROPIC_API_KEY 設為優先來源" +
      "（app/core/settings.py get_api_key）；DB 回退仍會存明文、仍隨 backups/ 外流" +
      "（決策 0008）。待決：要不要拿掉 DB 回退這條路徑。",
  },
  {
    item: "全域單一無鎖連線",
    status:
      "修憲落地 M3 已加鎖（app/core/db.py _LockingConnection，" +
      "序列化所有進出 sqlite3 底層的呼叫）；仍是單一連線、不是連線池。" +
      "待決：要不要拆連線池。",
  },
  {
    item: "等待頁進度只存記憶體",
    status:
      "未變動：app/ads/routes.py 的 _progress_state 仍是模組級 dict，" +
      "重啟即失。待決：要不要把進度落地到 DB。",
  },
  {
    item: "四處寫死絕對路徑",
    status:
      "部分緩解：DB 路徑（BRAND_OS_DB）、備份目錄（BRAND_OS_BACKUP_DIR）、" +
      "上傳目錄（BRAND_OS_UPLOADS）都已有環境變數可覆蓋，" +
      "但硬編碼的預設值本身還在 app/core/db.py／app/core/backup.py／app/main.py，" +
      "沒有環境變數時仍會落回 C:/Users/User/Desktop/marketing/...。" +
      "待決：要不要拔掉硬編碼預設值、改成沒設環境變數就報錯。",
  },
];

export const PROTOTYPE_PHASE_DETAIL: PrototypePhaseDetail = {
  ended: true,
  exemptions: PROTOTYPE_PHASE_EXEMPTIONS,
};

// ---------------------------------------------------------------------------
// 設定（S15）
// ---------------------------------------------------------------------------

/** 逐字對照真實 `app/shared/web.py` MODEL_CHOICES ＋ `app/llm/pricing.py` PRICING。 */
const MODEL_CHOICES: ModelChoice[] = [
  {
    id: "claude-opus-5",
    name: "Claude Opus 5（預設，品質最好）",
    price_text: "每百萬 token：輸入 US$5、輸出 US$25",
  },
  {
    id: "claude-sonnet-5",
    name: "Claude Sonnet 5（速度與品質平衡）",
    price_text: "每百萬 token：輸入 US$3、輸出 US$15",
  },
  {
    id: "claude-haiku-4-5",
    name: "Claude Haiku 4.5（最便宜、最快）",
    price_text: "每百萬 token：輸入 US$1、輸出 US$5",
  },
  {
    id: "claude-fable-5",
    name: "Claude Fable 5（最強、最貴，價格約 Opus 5 的兩倍，適合最難的規劃與長任務）",
    price_text: "每百萬 token：輸入 US$10、輸出 US$50",
  },
];

/** 逐字對照真實 `app/llm/providers.py` TASK_TYPE_LABELS ＋ TASK_DEFAULTS。 */
const TASK_MODEL_THINKING_TABLE: TaskModelThinkingRow[] = [
  { task_label: "檔期規劃（出方案）", model_label: "沿用上面設定的模型", thinking_label: "高" },
  { task_label: "素材生成（整批）", model_label: "沿用上面設定的模型", thinking_label: "中" },
  { task_label: "素材生成（補打缺型別）", model_label: "沿用上面設定的模型", thinking_label: "中" },
  { task_label: "素材生成（單則改寫）", model_label: "沿用上面設定的模型", thinking_label: "中" },
  { task_label: "素材生成（主題，票 04）", model_label: "沿用上面設定的模型", thinking_label: "中" },
  { task_label: "建檔精靈：讀取網址", model_label: "沿用上面設定的模型", thinking_label: "低" },
  { task_label: "建檔精靈：追問", model_label: "沿用上面設定的模型", thinking_label: "低" },
  { task_label: "建檔精靈：貼上格式修復", model_label: "沿用上面設定的模型", thinking_label: "低" },
  { task_label: "產品建檔：讀取網址", model_label: "沿用上面設定的模型", thinking_label: "低" },
  { task_label: "產品交接：格式修復", model_label: "沿用上面設定的模型", thinking_label: "低" },
  { task_label: "品牌智庫報告", model_label: "沿用上面設定的模型", thinking_label: "中" },
  { task_label: "顧客原話萃取", model_label: "沿用上面設定的模型", thinking_label: "中" },
  { task_label: "成效判讀", model_label: "沿用上面設定的模型", thinking_label: "中" },
  { task_label: "補件重判差異說明", model_label: "沿用上面設定的模型", thinking_label: "低" },
];

/** AI 金鑰來源三版文案（S15.13）：與整頁 loading／error／empty 開關分開，另立一顆
 * DevToggle 選單控制（見 `mocks/state.ts`），因為三版是同一個「正常態」底下要輪看的
 * 文案分支，不是四態的一種。 */
export function buildSettingsData(apiKeySource: "env" | "db" | null): SettingsData {
  return {
    masked_key: apiKeySource === null ? null : apiKeySource === "env" ? "sk-…9f2a" : "sk-…3c71",
    api_key_source: apiKeySource,
    db_key_present: apiKeySource === "db",
    model_choices: MODEL_CHOICES,
    current_model: "claude-opus-5",
    task_model_thinking_table: TASK_MODEL_THINKING_TABLE,
    masked_meta_token: null, // 契約要求：masked_* 至少一個為 null（沒設定過）
    meta_account_id: "act_1234567890",
    masked_ga4_key: "…9f2a",
    ga4_property_id: "123456789",
    creative_root: "D:\\某某雲端同步資料夾\\行銷素材\\2026\\第三季\\所有品牌共用",
    prompt_header: "圖上文字一律平面實填，不要浮雕、液態字、金屬字、粗糙紋理、磨砂感",
    intake_budget: 0, // 契約要求：下限邊界
  };
}

interface RuleCardFieldDef {
  key: string;
  label: string;
  unit: string;
  help: string;
  default: number;
}

interface RuleCardDef {
  key: string;
  title: string;
  description: string;
  fields: RuleCardFieldDef[];
}

/** 逐字對照真實 `app/core/rule_cards.py` CARDS（6 張，唯一權威，含各欄位系統預設值）。 */
const RULE_CARD_DEFS: RuleCardDef[] = [
  {
    key: "budget_structure",
    title: "帳戶結構與預算配置門檻",
    description: "這張卡決定「日預算多少算小／中／大」，以及每個級距怎麼分帳戶結構與組別預算。",
    fields: [
      {
        key: "min_daily_per_group",
        label: "每組日預算下限",
        unit: "NT$",
        help: "Meta 的實務下限：一組的日預算低於這個數字，一天拿不到足夠曝光。",
        default: 300,
      },
      {
        key: "medium_tier_floor",
        label: "中預算門檻（日預算達到此金額才分兩組）",
        unit: "NT$",
        help: "日預算低於這個數字算「小預算」，全額投入單一測試組，不硬拆。",
        default: 600,
      },
      {
        key: "large_tier_floor",
        label: "大預算門檻（日預算達到此金額才開雙活動）",
        unit: "NT$",
        help: "日預算達到這個數字，才有本錢同時養「已驗證贏家放大」與「新概念測試」。",
        default: 1200,
      },
      {
        key: "medium_validation_ratio",
        label: "中預算級距 — 已驗證方向佔比",
        unit: "比例（0–1）",
        help: "中預算用一個 CBO、兩個廣告組：這個比例留給比較有把握的方向。",
        default: 0.7,
      },
      {
        key: "large_scaling_ratio",
        label: "大預算級距 — 放大活動佔比",
        unit: "比例（0–1）",
        help: "大預算開兩個獨立 CBO 活動：放大活動拿這個比例。",
        default: 0.8,
      },
    ],
  },
  {
    key: "sample_size",
    title: "樣本數門檻（統計等級 vs 方向性判讀）",
    description: "這張卡決定「這期的樣本數夠不夠格說是統計上站得住腳的結論」。",
    fields: [
      {
        key: "baseline_1pct",
        label: "基準轉換率 1% 所需樣本數",
        unit: "次／變體",
        help: "轉換率大約在 1% 上下時的樣本數門檻。",
        default: 97000,
      },
      {
        key: "baseline_3pct",
        label: "基準轉換率 3% 所需樣本數",
        unit: "次／變體",
        help: "轉換率大約在 3% 上下時的樣本數門檻。",
        default: 31000,
      },
      {
        key: "baseline_5pct",
        label: "基準轉換率 5% 所需樣本數",
        unit: "次／變體",
        help: "轉換率大約在 5% 上下時的樣本數門檻。",
        default: 18000,
      },
      {
        key: "baseline_10pct",
        label: "基準轉換率 10% 所需樣本數",
        unit: "次／變體",
        help: "轉換率大約在 10% 上下時的樣本數門檻。",
        default: 8700,
      },
      {
        key: "baseline_20pct",
        label: "基準轉換率 20% 所需樣本數",
        unit: "次／變體",
        help: "轉換率大約在 20% 上下時的樣本數門檻。",
        default: 4000,
      },
    ],
  },
  {
    key: "ad_creative_fatigue",
    title: "素材疲勞頻率門檻",
    description: "「頻率」是同一個人平均看過這支素材幾次，這張卡決定頻率到多少算警示、危險。",
    fields: [
      {
        key: "cold_warning",
        label: "冷受眾開發 — 警示門檻",
        unit: "頻率",
        help: "冷受眾開發：安全 1.0–2.5，超過這個數字進入警示區。",
        default: 2.5,
      },
      {
        key: "cold_danger",
        label: "冷受眾開發 — 危險門檻",
        unit: "頻率",
        help: "超過這個數字視為危險。",
        default: 3.5,
      },
      {
        key: "retargeting_warning",
        label: "再行銷 — 警示門檻",
        unit: "頻率",
        help: "再行銷受眾容忍度較高：安全 2.0–4.0。",
        default: 4.0,
      },
      {
        key: "retargeting_danger",
        label: "再行銷 — 危險門檻",
        unit: "頻率",
        help: "超過這個數字視為危險。",
        default: 6.0,
      },
      {
        key: "niche_warning",
        label: "小眾／精準受眾 — 警示門檻",
        unit: "頻率",
        help: "小眾受眾池子小，天然頻率就會偏高：安全 2.0–5.0。",
        default: 5.0,
      },
      {
        key: "niche_danger",
        label: "小眾／精準受眾 — 危險門檻",
        unit: "頻率",
        help: "超過這個數字視為危險。",
        default: 8.0,
      },
    ],
  },
  {
    key: "rule_prompt_cap",
    title: "品牌智庫規則上限",
    description: "生成 prompt 會把這個品牌全部生效中的 hard 規則整包塞進去。",
    fields: [
      {
        key: "max_active_rules",
        label: "進生成提示詞的規則上限",
        unit: "條",
        help: "hard 規則不受這個數字限制；soft 規則超過上限後排比較後面的這次不會進 prompt。",
        default: 20,
      },
    ],
  },
  {
    key: "rule_expiry",
    title: "規則有效期",
    description: "品牌智庫的規則被接受後，超過這裡設定的期數沒有人重新確認會自動退回待確認。",
    fields: [
      {
        key: "reconfirm_cycles",
        label: "重新確認門檻",
        unit: "期",
        help: "規則被接受（或上次重新確認）之後，經過這麼多期都沒有人重新確認就會退回待確認。",
        default: 6,
      },
    ],
  },
  {
    key: "pacing",
    title: "檔期預算步調門檻",
    description: "這張卡決定「檔期預算花得比時間進度快多少或慢多少」才算異常。",
    fields: [
      {
        key: "deviation_threshold_ratio",
        label: "步調偏差門檻",
        unit: "比例（0–1）",
        help: "花費進度與時間進度的差距超過這個比例（不分正負）就送出警示。",
        default: 0.15,
      },
    ],
  },
];

/** 品牌覆寫值：模組級記憶體（重新整理頁面就重置，跟真後端的 DB 持久化不同——原型階段
 * 只需要在同一次瀏覽期間看得到「儲存／重設」有反應）。budget_structure 全部欄位、
 * ad_creative_fatigue／rule_expiry 各一欄刻意先偏離預設值，示範「已自訂」；sample_size
 * 整張維持預設值，示範「非自訂」（契約要求「至少一張全部已自訂、至少一張全部是預設值」）。
 * key 格式：`${cardKey}.${fieldKey}`，跨品牌共用同一份（原型階段不分品牌存放，圖簡單）。 */
const ruleCardOverrides = new Map<string, number>([
  ["budget_structure.min_daily_per_group", 350],
  ["budget_structure.medium_tier_floor", 650],
  ["budget_structure.large_tier_floor", 1300],
  ["budget_structure.medium_validation_ratio", 0.65],
  ["budget_structure.large_scaling_ratio", 0.75],
  ["ad_creative_fatigue.cold_warning", 3.0],
  ["ad_creative_fatigue.retargeting_danger", 6.5],
  ["rule_expiry.reconfirm_cycles", 8],
]);

function buildCard(def: RuleCardDef): RuleCard {
  return {
    key: def.key,
    title: def.title,
    description: def.description,
    fields: def.fields.map((f) => {
      const overrideKey = `${def.key}.${f.key}`;
      const value = ruleCardOverrides.has(overrideKey) ? ruleCardOverrides.get(overrideKey)! : f.default;
      return {
        key: f.key,
        label: f.label,
        unit: f.unit,
        help: f.help,
        value,
        customized: value !== f.default,
      };
    }),
  };
}

function buildRuleCards(): RuleCard[] {
  return RULE_CARD_DEFS.map(buildCard);
}

export function buildRuleCardsData(brandId: string): RuleCardsData {
  return { brand_id: brandId, cards: buildRuleCards() };
}

/** 「儲存這張卡」（S15.31）：把送出的欄位值寫進覆寫表，回傳重算後的卡片（含新的
 * `customized` 標記）。 */
export function saveRuleCardValues(cardKey: string, fields: Record<string, number>): RuleCard {
  const def = RULE_CARD_DEFS.find((d) => d.key === cardKey);
  if (!def) throw new Error(`沒有這張規則卡：${cardKey}`);
  for (const [fieldKey, value] of Object.entries(fields)) {
    ruleCardOverrides.set(`${cardKey}.${fieldKey}`, value);
  }
  return buildCard(def);
}

/** 「重設為系統預設值」（S15.32）：清掉這張卡全部欄位的覆寫值。 */
export function resetRuleCardValues(cardKey: string): RuleCard {
  const def = RULE_CARD_DEFS.find((d) => d.key === cardKey);
  if (!def) throw new Error(`沒有這張規則卡：${cardKey}`);
  for (const f of def.fields) ruleCardOverrides.delete(`${cardKey}.${f.key}`);
  return buildCard(def);
}

/** 品牌選擇器（S15.29）清單，至少 15 筆、一筆長字串。同一份也拿來假造
 * `GET /api/dashboard/overview`（見 `mocks/handlers.ts` 註解：只在畫面契約第 1 段、
 * 零後端期間攔截，跟真正的跨品牌總覽頁互不相干）。 */
export const BRAND_OPTIONS: BrandOption[] = [
  { brand_id: "brand-1", brand_name: "測試用超長品牌名稱有限公司　旗艦生活風格系列" },
  { brand_id: "brand-2", brand_name: "小島野餐" },
  { brand_id: "brand-3", brand_name: "北風羊毛" },
  { brand_id: "brand-4", brand_name: "深夜廚房" },
  { brand_id: "brand-5", brand_name: "貓山咖啡" },
  { brand_id: "brand-6", brand_name: "海邊柑仔店" },
  { brand_id: "brand-7", brand_name: "老宅木作" },
  { brand_id: "brand-8", brand_name: "青苔工作室" },
  { brand_id: "brand-9", brand_name: "曬穀場甜點" },
  { brand_id: "brand-10", brand_name: "巷口修理鋪" },
  { brand_id: "brand-11", brand_name: "野草花藝" },
  { brand_id: "brand-12", brand_name: "山邊釀造所" },
  { brand_id: "brand-13", brand_name: "月光洗衣店" },
  { brand_id: "brand-14", brand_name: "石頭湯食堂" },
  { brand_id: "brand-15", brand_name: "布丁研究所" },
  { brand_id: "brand-16", brand_name: "廢墟植物園" },
];

export const BRAND_OPTIONS_EMPTY: BrandOption[] = [];

export function buildDashboardOverview(brands: BrandOption[]): DashboardBrandCard[] {
  const healths: DashboardBrandCard["health"][] = ["green", "yellow", "red"];
  return brands.map((b, i) => ({
    brand_id: b.brand_id,
    brand_name: b.brand_name,
    health: healths[i % healths.length],
    revenue_this_month: i % 4 === 0 ? null : 120000 + i * 3500,
    revenue_mom_pct: i % 4 === 0 ? null : i % 3 === 0 ? -8.5 : 4.2,
    active_cycle: null,
    next_step: null,
  }));
}
