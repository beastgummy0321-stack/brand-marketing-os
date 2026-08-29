/** 共用數字格式化（票 02 起沿用，票 03 抽出給駕駛艙 KPI 卡共用）。
 * null 一律代表「沒得算」，不是 0（鐵則 16）——顯示「累積中」而不是 0 或空白。 */

export function formatCurrency(value: number | null): string {
  if (value === null) return "累積中";
  return `NT$ ${Math.round(value).toLocaleString("zh-TW")}`;
}

export function formatCount(value: number | null): string {
  if (value === null) return "累積中";
  return value.toLocaleString("zh-TW");
}

/** AI 花費估計一律美元計價（app/llm/pricing.py cost_ceiling），跟 formatCurrency 的
 * NT$ 是兩種幣別，不能共用同一顆格式化函式——文案沿用既有 Jinja 頁面的既定寫法
 * （app/templates/ads_cycle.html「{{ '%.2f'|format(plan_cost) }} 美元」）。 */
export function formatUsd(value: number): string {
  return `${value.toFixed(2)} 美元`;
}

export function formatRoas(value: number | null): string {
  if (value === null) return "累積中";
  return `${value.toFixed(2)}x`;
}

/** 票 05：Meta 廣告單一活動／總計的 ROAS。這裡的 null 跟 formatRoas() 的「累積中」是
 * 不同的事實——「累積中」暗示數字之後會出現，但 Meta 對這個活動本來就沒有追蹤轉換
 * （或加總時範圍內有活動未追蹤），不會有出現的一天，畫面必須明講「未追蹤」。 */
export function formatMetaRoas(value: number | null): string {
  if (value === null) return "未追蹤";
  return `${value.toFixed(2)}x`;
}

/** 比率 → 百分比字串。後端存的是比值（app/ads/performance.py:467 `clicks / impressions`），
 * 不是百分數，所以顯示前必須乘 100——三個 CTR 呼叫端各自手寫 `${ctr}%` 少了這一步，
 * 1.03% 被印成 0.0103%，看起來像廣告爛掉 100 倍。格式化集中在這裡，呼叫端不再自己拼。 */
export function formatPercent(value: number | null): string {
  if (value === null) return "累積中";
  return `${(value * 100).toFixed(2)}%`;
}

export function formatMomPct(value: number | null): string {
  if (value === null) return "";
  const sign = value > 0 ? "+" : "";
  return `（環比 ${sign}${value}%）`;
}

/** 最後同步時間（票 07-auto-sync）：ISO 時間字串 → `MM/DD HH:mm`（本機時區）。 */
/** 同步時間的人話顯示（R6-2）：避免只給使用者一串 ISO 時間。 */
export function formatRelativeHours(iso: string): string {
  const elapsedHours = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 3_600_000));
  return elapsedHours === 0 ? "不到 1 小時前" : elapsedHours + " 小時前";
}
export function formatSyncTime(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
