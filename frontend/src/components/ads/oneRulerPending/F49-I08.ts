/** oneRuler.test.ts pending entries that F49-I08 removes (F49 lead split). Empty or delete when done. */
export const lifecycle = [
  { rule: "lifecycle", file: "components/ads/AllCampaignsPage.tsx", issue: "F49-I08" },
  { rule: "lifecycle", file: "components/ads/patterns/campaignWords.ts", issue: "F49-I08" },
  { rule: "lifecycle", file: "components/ads/home/status.ts", issue: "F49-I08" },
];
export const stateWords = [
  { file: "components/ads/home/status.ts", issue: "F49-I08" },
];
export const queue = [
  { rule: "kinds", file: "components/ads/home/status.ts", issue: "F49-I08" },
  { rule: "kinds", file: "components/ads/home/QueueRow.tsx", issue: "F49-I08" },
  { rule: "kinds", file: "components/ads/settle/SettlePage.tsx", issue: "F49-I08" },
];
