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

export function formatRoas(value: number | null): string {
  if (value === null) return "累積中";
  return `${value.toFixed(2)}x`;
}

export function formatMomPct(value: number | null): string {
  if (value === null) return "";
  const sign = value > 0 ? "+" : "";
  return `（環比 ${sign}${value}%）`;
}
