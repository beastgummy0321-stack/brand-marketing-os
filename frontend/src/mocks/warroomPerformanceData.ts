/** S8 作戰室「期中檢查點／成效／覆盤」假資料（票 B4-warroom）。判讀狀態文案抄
 * `app/ads/reading.py:69-76 STATUS_LABELS`（查證日 2026-08-12）。8 期已結案檔期
 * （`cyc-6`…`cyc-13`）＋ 1 期已封存已結案（`cyc-14`）依序覆蓋契約要求的四種判讀狀態
 * （scale_candidate／pause_candidate／insufficient_data／unclear_economics）。 */
import type { AttributionSummary, CheckpointResult, ClosingReview, HealthLights, HealthLightStatus, PerformanceSummary, ReadingResult } from "@/lib/warroomApi";
import type { CampaignRecord } from "./campaignsData";

const READING_STATUS_LABELS: Record<string, string> = {
  insufficient_data: "資料還不夠",
  learning: "還在學習期",
  maintain: "維持現狀",
  scale_candidate: "可以考慮加碼",
  pause_candidate: "該考慮停下來",
  unclear_economics: "還看不出賺不賺",
};

/** 依 store 裡固定順序手動指定，確保契約要求的四種狀態都出現至少一次。 */
const READING_STATUS_BY_ID: Record<string, keyof typeof READING_STATUS_LABELS> = {
  "cyc-6": "scale_candidate",
  "cyc-7": "pause_candidate",
  "cyc-8": "insufficient_data",
  "cyc-9": "unclear_economics",
  "cyc-10": "scale_candidate",
  "cyc-11": "pause_candidate",
  "cyc-12": "scale_candidate",
  "cyc-13": "maintain",
  "cyc-14": "scale_candidate",
};

export function buildCheckpoint(record: CampaignRecord, kind: "day3" | "day7"): CheckpointResult {
  if (record.id !== "cyc-5") {
    return { kind, data_sufficient: false, spend_ok: null, learning_normal: null, learning_note: "這期還沒有累積到足夠的投放資料。", reach: null, fatigue: null };
  }
  if (kind === "day3") {
    return { kind, data_sufficient: false, spend_ok: true, learning_normal: null, learning_note: "第 3 天資料還不夠判斷學習期正不正常，錢有在花是正常的。", reach: { reach: 18234, note: "觸及持續成長中" }, fatigue: null };
  }
  return {
    kind,
    data_sufficient: true,
    spend_ok: true,
    learning_normal: true,
    learning_note: "學習期已完成，花費節奏正常。",
    reach: { reach: 62410, note: "觸及成長趨緩，屬正常現象" },
    fatigue: { frequency: 3.8, status_label: "略高，留意素材疲勞", status: "warn", note: "頻率超過門檻（3.5），建議準備新素材輪替", audience_type_label: "暖受眾（再行銷）" },
  };
}

export function buildPerformanceSummary(record: CampaignRecord): PerformanceSummary | null {
  if (record.id === "cyc-15") return null; // 已封存＋LIVE，尚無成效資料（S8.51 空狀態）
  if (record.id === "cyc-5") {
    // 醜資料：曝光超大值、點擊負數各一筆，示範 S8.58 異常擱置提醒
    return {
      spend: 15234,
      impressions: 999999999,
      reach: 62410,
      clicks: -12,
      conversions: 48,
      revenue: 38520,
      kpis: { ctr: 2.1, cpc: 9.8, cpa: 317.4, roas: 2.53 },
      discarded_rows: 2,
    };
  }
  if (record.id === "cyc-8") return null; // 完全沒判讀過，算不出來誠實顯示「資料不足」
  if (record.reading === null) return null;
  const revenue = Math.round(record.budget * record.reading.roas);
  return {
    spend: record.budget,
    impressions: Math.round(record.budget * 40),
    reach: Math.round(record.budget * 15),
    clicks: Math.round(record.budget * 0.6),
    conversions: Math.max(0, Math.round(revenue / 800)),
    revenue,
    kpis: { ctr: 1.8, cpc: 8.2, cpa: revenue > 0 ? Math.round(record.budget / Math.max(1, Math.round(revenue / 800))) : null, roas: record.reading.roas },
    discarded_rows: 0,
  };
}

export function buildReadingResult(record: CampaignRecord): ReadingResult | null {
  const status = READING_STATUS_BY_ID[record.id];
  if (!status) return null;
  const directional = record.id === "cyc-9" || record.id === "cyc-13";
  return {
    status,
    status_label: READING_STATUS_LABELS[status],
    statistical_level: directional ? "directional" : "statistical",
    statistical_level_label: directional
      ? "這期的樣本數還沒到統計等級的門檻，這只能算方向性判讀。"
      : "這期收到的樣本數已經到達統計等級門檻，這個結論有統計依據撐著。",
    llm_explanation: status === "insufficient_data" ? "這期完全沒有回填過成效資料，算不出任何結論。" : `依 ROAS 與轉換量判斷，這期屬於「${READING_STATUS_LABELS[status]}」。`,
    reasons: status === "insufficient_data" ? ["沒有任何一筆成效資料"] : ["ROAS 與同品牌歷史平均比較", "轉換量是否達統計門檻"],
  };
}

function verdictToLightStatus(verdict: "ok" | "danger" | "neutral" | null): HealthLightStatus {
  if (verdict === "ok") return "green";
  if (verdict === "neutral") return "yellow";
  if (verdict === "danger") return "red";
  return "insufficient";
}

/** S8R.20-21：檔期健康燈號。真後端四燈公式見 GRILL-B4R-performance.md「檔期健康燈號」小節
 * （`pacing.classify()`／`performance.totals().kpis`／`target_cpa.resolve_target_cpa()`／
 * `reading.breakeven_roas()`／`checkpoint`）。原型沒有逐日花費與逐日頻率兩份底層追蹤資料
 * （cyc-5 除外，沿用既有 `buildCheckpoint()` 頻率數字），CPA／ROAS 兩燈借用既有判讀結論
 * `reading.verdict_kind` 映射三色；燒錢速度／疲勞沒有底層資料時顯示「資料不足」灰燈，
 * 誠實不假裝算得出來（鐵則 16）。cyc-11 刻意四燈全紅，示範「情境：全滅檔期」最壞情境
 * （GRILL-B4R-performance.md 醜資料段）。 */
export function buildHealthLights(record: CampaignRecord): HealthLights {
  if (record.id === "cyc-11") {
    return {
      spend_rate: { status: "red", value: 92, label: "燒錢速度", note: "已經過 60% 天數，花了 92% 預算，燒太快，情境：全滅檔期示範用。" },
      cpa: { status: "red", value: 512, label: "CPA", note: "實際 CPA 512 元，超過目標 CPA 三成以上，情境：全滅檔期示範用。" },
      roas: { status: "red", value: 0.85, label: "ROAS", note: "實際 ROAS 0.85，低於打平投報率八成，情境：全滅檔期示範用。" },
      fatigue: { status: "red", value: 4.6, label: "疲勞", note: "頻率 4.6，同一批人已經看膩，情境：全滅檔期示範用。" },
    };
  }
  if (record.id === "cyc-5") {
    return {
      spend_rate: { status: "red", value: 76, label: "燒錢速度", note: "已經過 55% 天數，花了 76% 預算，燒太快，照這個速度會提早花完。" },
      cpa: { status: "yellow", value: 317, label: "CPA", note: "實際 CPA 略高於目標，還在可接受範圍，先觀察別急著喊停。" },
      roas: { status: "green", value: 2.53, label: "ROAS", note: "實際 ROAS 高於打平投報率，維持現在的做法。" },
      fatigue: { status: "yellow", value: 3.8, label: "疲勞", note: "頻率 3.8，超過門檻，建議準備新素材輪替。" },
    };
  }
  const verdict = record.reading?.verdict_kind ?? null;
  const summary = buildPerformanceSummary(record);
  const status = verdictToLightStatus(verdict);
  const kpiNote = status === "insufficient" ? "還沒有可以算的成效數字。" : "依這期的判讀結論換算。";
  return {
    spend_rate: { status: "insufficient", value: null, label: "燒錢速度", note: "這期沒有逐日花費追蹤資料，量不出燒錢速度。" },
    cpa: { status, value: summary?.kpis.cpa ?? null, label: "CPA", note: kpiNote },
    roas: { status, value: summary?.kpis.roas ?? null, label: "ROAS", note: kpiNote },
    fatigue: { status: "insufficient", value: null, label: "疲勞", note: "這期沒有頻率追蹤資料。" },
  };
}

/** S8R.24：訂單歸因四分類——原型沒有逐筆訂單資料表，依這期成效摘要的轉換數／營收比例
 * 反推一組內部一致的示範分類（毛單＝淨單＋排除；自然單另計），不是真實逐筆歸因結果。
 * 完全沒有成效資料時四類皆為 0（同 S3P.11 空狀態精神）。 */
export function buildAttributionSummary(summary: PerformanceSummary | null): AttributionSummary {
  const net = summary?.conversions ?? 0;
  if (net === 0) {
    const zero = { count: 0, net_revenue: 0 };
    return { gross: zero, net: zero, excluded: zero, natural: zero };
  }
  const perOrder = summary && net > 0 ? summary.revenue / net : 0;
  const excludedCount = Math.max(0, Math.round(net * 0.08));
  const naturalCount = Math.max(0, Math.round(net * 0.2));
  const round = (n: number) => Math.round(n);
  return {
    gross: { count: net + excludedCount, net_revenue: round((net + excludedCount) * perOrder) },
    net: { count: net, net_revenue: round(net * perOrder) },
    excluded: { count: excludedCount, net_revenue: round(excludedCount * perOrder) },
    natural: { count: naturalCount, net_revenue: round(naturalCount * perOrder) },
  };
}

export function buildClosingReview(record: CampaignRecord): ClosingReview | null {
  if (record.status !== "CLOSED") return null;
  const reading = buildReadingResult(record);
  const summary = buildPerformanceSummary(record);
  const isConversion = record.objective === "sales" || record.objective === "leads";
  const targetCpa = 180; // 展示用固定值，同 buildTargetCpaView() 既有示範值
  return {
    cycle_id: record.id,
    goal_comparison: {
      objective_label: record.objective === "sales" ? "銷售" : record.objective === "leads" ? "潛在顧客" : record.objective === "traffic" ? "流量" : record.objective === "engagement" ? "互動" : "知名度",
      target: isConversion ? `目標 CPA 約 ${targetCpa} 元` : `建議花費區間中點約 NT$ ${Math.round(record.budget)}`,
      target_value: isConversion ? targetCpa : record.budget,
      actual_value: isConversion ? (summary?.kpis.cpa ?? null) : (summary?.spend ?? null),
      metric_label: isConversion ? "CPA（元）" : "花費（NT$）",
      lower_is_better: isConversion,
      actual_kpis: summary?.kpis ?? { ctr: null, cpc: null, cpa: null, roas: null },
    },
    gap_attribution: {
      reasons: reading?.reasons ?? ["沒有足夠資料可歸因"],
      channel_note: record.id === "cyc-6" ? "跟 GA4 通路對照無明顯落差" : null,
      ga4_leak_note: record.id === "cyc-7" ? "GA4 事件疑似有漏偵測，實際轉換可能比回填數字更多" : null,
      attribution: buildAttributionSummary(summary),
    },
    learning: {
      hypotheses: [{ statement: "暖受眾對「有感有效」切角的轉換率優於冷受眾", verdict: record.reading?.verdict_kind === "ok" ? "supported" : record.reading?.verdict_kind === "danger" ? "rejected" : "inconclusive" }],
      ledger_entries: record.reading?.verdict_kind === "ok" ? [{ text: "有感有效切角對暖受眾轉換率較佳，已入帳累積智慧", created_at: `${record.end_date}T18:00:00+08:00` }] : [],
    },
    recommendation: {
      budget_advice: record.reading?.verdict_kind === "ok" ? "建議下期加碼 20%，持續放大已驗證方向" : record.reading?.verdict_kind === "danger" ? "建議下期先降預算並更換切角，不建議原封不動延續" : "建議下期維持同等預算，先累積更多樣本再決定",
      proposed_budget: record.reading?.verdict_kind === "ok" ? Math.round(record.budget * 1.2) : record.budget,
      rule_cards_created: record.reading?.verdict_kind === "danger" ? 1 : 0,
      echo_chamber: false,
    },
  };
}

export const AI_COST_METER = { spent: 512.3, limit: 500, settings_url: "/settings" };
