/** S8 作戰室「期中檢查點／成效／覆盤」假資料（票 B4-warroom）。判讀狀態文案抄
 * `app/ads/reading.py:69-76 STATUS_LABELS`（查證日 2026-08-12）。8 期已結案檔期
 * （`cyc-6`…`cyc-13`）＋ 1 期已封存已結案（`cyc-14`）依序覆蓋契約要求的四種判讀狀態
 * （scale_candidate／pause_candidate／insufficient_data／unclear_economics）。 */
import type { CheckpointResult, ClosingReview, PerformanceSummary, ReadingResult } from "@/lib/warroomApi";
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

export function buildClosingReview(record: CampaignRecord): ClosingReview | null {
  if (record.status !== "CLOSED") return null;
  const reading = buildReadingResult(record);
  const summary = buildPerformanceSummary(record);
  return {
    cycle_id: record.id,
    goal_comparison: {
      objective_label: record.objective === "sales" ? "銷售" : record.objective === "leads" ? "潛在顧客" : record.objective === "traffic" ? "流量" : record.objective === "engagement" ? "互動" : "知名度",
      target: "目標 CPA 約 180 元／週轉換 20 筆",
      actual_kpis: summary?.kpis ?? { ctr: null, cpc: null, cpa: null, roas: null },
    },
    gap_attribution: {
      reasons: reading?.reasons ?? ["沒有足夠資料可歸因"],
      channel_note: record.id === "cyc-6" ? "跟 GA4 通路對照無明顯落差" : null,
      ga4_leak_note: record.id === "cyc-7" ? "GA4 事件疑似有漏偵測，實際轉換可能比回填數字更多" : null,
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
