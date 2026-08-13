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
