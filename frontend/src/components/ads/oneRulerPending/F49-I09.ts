/** oneRuler.test.ts pending entries that F49-I09 removes (F49 lead split). Empty or delete when done. */
export const lifecycle = [
  { rule: "native", file: "components/ads/detail/GradeGroups.tsx", issue: "F49-I09" },
  { rule: "native", file: "components/ads/OverviewTab.tsx", issue: "F49-I09" },
  { rule: "lifecycle", file: "components/ads/nextStep.tsx", issue: "F49-I09" },
  { rule: "lifecycle", file: "components/ads/PerformanceTab.tsx", issue: "F49-I09" },
  { rule: "lifecycle", file: "components/ads/detail/CampaignDetailPage.tsx", issue: "F49-I09" },
  { rule: "lifecycle", file: "components/ads/detail/PeriodStatusRow.tsx", issue: "F49-I09" },
  { rule: "lifecycle", file: "components/ads/workspace/OverviewBody.tsx", issue: "F49-I09" },
  { rule: "lifecycle", file: "components/ads/workspace/WorkspaceHead.tsx", issue: "F49-I09" },
  { rule: "lifecycle", file: "components/ads/CloseCampaignDialog.tsx", issue: "F49-I09" },
];
export const sync = [
  { file: "components/ads/CampaignWorkspace.tsx", issue: "F49-I09" },
];
export const queue = [
  { rule: "kinds", file: "components/ads/workspace/OverviewBody.tsx", issue: "F49-I09" },
];
