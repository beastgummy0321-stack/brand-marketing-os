/** oneRuler.test.ts pending entries that F51-I09 removes (moved out of `NOT_A_RULER` by F51-I04): the home month chart
 * reads the served `pace.budget_to_date`, and the money meter's axis headroom stops reading an unknown cost per
 * purchase as 0. Empty this file (or delete it) when done. */
export const notARuler = [
  { file: "components/ads/home/MonthMoney.tsx", text: "(cpp ?? 0) * 1.3", why: "axis headroom of the home money meter, not NEAR_BEST" },
  { file: "components/ads/patterns/PaceChart.tsx", text: "const pace = Math.round((budget * dayOfMonth) / daysInMonth);", why: "debt: feature C/D (W11/W16) — today's pace on the home month chart is priced in the browser" },
];
