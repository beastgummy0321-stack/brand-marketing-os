/** oneRuler.test.ts pending entries that F49-I14 removes (F49 lead split). Empty or delete when done. */
export const lifecycle = [
  { rule: "native", file: "components/ads/ExistingCampaignDialog.tsx", issue: "F49-I14" },
  { rule: "native", file: "components/ads/ExternalCampaignPanel.tsx", issue: "F49-I14" },
  { rule: "native", file: "components/ads/ChangeSetView.tsx", issue: "F49-I14" },
  { rule: "native", file: "components/ads/patterns/campaignWords.ts", issue: "F49-I14" },
  { rule: "lifecycle", file: "components/ads/UserAssetPlacements.tsx", issue: "F49-I14" },
];
export const sync = [
  { file: "components/ads/connections/DataConnectionsPage.tsx", issue: "F49-I14" },
  { file: "components/ads/ExistingCampaignDialog.tsx", issue: "F49-I14" },
  { file: "components/ads/ExternalCampaignPanel.tsx", issue: "F49-I14" },
];
export const stateWords = [
  { file: "components/ads/ChangeSetView.tsx", issue: "F49-I14" },
  { file: "components/ads/ManualHandoffPanel.tsx", issue: "F49-I14" },
];
