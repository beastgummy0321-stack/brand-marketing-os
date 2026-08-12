import type { StatusLightValue } from "./StatusLight";

/** V3 流體卡片元件庫共用假資料（GRILL-B4R-performance.md R4-4「Storybook 元件庫＋整站
 * 原型雙軌共用同一份假資料」）：這裡先給元件庫 story 用；B4R 後端接上後，駕駛艙／作戰室
 * 的 fetch 攔截 mocks 要沿用同一份形狀，不得另造第二份。`HealthLightStatus` 字面沿用
 * 契約 TS 型別（第 429 行），數值單位與白話說明比照 blocks.md 既有假資料語氣。 */

export const HEALTH_LIGHT_FIXTURES: { status: StatusLightValue; label: string; statusText: string }[] = [
  { status: "green", label: "燒錢速度", statusText: "一切正常" },
  { status: "yellow", label: "CPA", statusText: "CPA 112 元，超出目標 1.3 倍" },
  { status: "red", label: "ROAS", statusText: "ROAS 0.6×，低於損益兩平" },
  { status: "insufficient", label: "疲勞度", statusText: "投放天數不足，還沒有足夠樣本" },
];

export const READINESS_RING_FIXTURE = { passed: 7, total: 9 };

export const WEEKLY_BUDGET_TREND = [12000, 14500, 13200, 15800, 15100, 16400, 15900];
export const FLAT_TREND = [10000, 10000, 10000, 10000];

export const CYCLE_ROAS_STAT = { value: "2.4×", label: "本期 ROAS", trend: { direction: "up" as const, text: "較上期 +0.3×" } };
export const CYCLE_SPEND_STAT = { value: "NT$ 48,200", label: "本期花費", trend: { direction: "down" as const, text: "較上期 -6%" } };
