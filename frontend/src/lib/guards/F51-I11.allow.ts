/** F51 guard ratchet entries that F51-I11 removes (the performance, detail, overview, assets and handoff screens: a greyed-out control says why, and every
 * figure prints through `layout/Figure` by its basis). Read by `lib/feedbackGuards.test.ts` and `lib/figureGuards.test.ts`
 * through `import.meta.glob("./guards/*.allow.ts")`; an entry whose file no longer hits fails as stale. F51-I11
 * deletes its entries as it cleans each file, and this module when it is empty. */
export default [
  // F51-I04 (Contract D／F scanners: disabled, zero, currency, money-ratio, roas-format).
  { rule: "disabled", file: "components/ads/AssetHandoffPanel.tsx" },
  { rule: "disabled", file: "components/ads/AssetsTab.tsx" },
  { rule: "disabled", file: "components/ads/AuthAssetMedia.tsx" },
  { rule: "disabled", file: "components/ads/detail/AbBlock.tsx" },
  { rule: "disabled", file: "components/ads/detail/PeriodStatusRow.tsx" },
  { rule: "disabled", file: "components/ads/ExistingCampaignDialog.tsx" },
  { rule: "disabled", file: "components/ads/ExternalCampaignPanel.tsx" },
  { rule: "disabled", file: "components/ads/ManualSettings.tsx" },
  { rule: "disabled", file: "components/ads/MaterialTaskEditor.tsx" },
  { rule: "disabled", file: "components/ads/MaterialTasksPanel.tsx" },
  { rule: "disabled", file: "components/ads/OverviewTab.tsx" },
  { rule: "disabled", file: "components/ads/PerformanceTab.tsx" },
  { rule: "disabled", file: "components/ads/PlannedMaterialAssignments.tsx" },
  { rule: "disabled", file: "components/ads/UserAssetPlacements.tsx" },
  { rule: "disabled", file: "components/ads/UserAssetsLibrary.tsx" },
  { rule: "disabled", file: "components/ads/workspace/AssetsBody.tsx" },
  { rule: "disabled", file: "components/ads/workspace/SlotTiles.tsx" },
  { rule: "zero", file: "components/ads/detail/GradeGroups.tsx" },
  { rule: "zero", file: "components/ads/ExistingCampaignDialog.tsx" },
  { rule: "zero", file: "components/ads/ExternalCampaignPanel.tsx" },
  { rule: "zero", file: "components/ads/ManualSettings.tsx" },
  { rule: "zero", file: "components/ads/OverviewTab.tsx" },
  { rule: "zero", file: "components/ads/PerformanceTab.tsx" },
  { rule: "zero", file: "components/ads/workspace/AssetsBody.tsx" },
  { rule: "currency", file: "components/ads/PerformanceTab.tsx" },
  { rule: "roas-format", file: "components/ads/detail/PeriodStatusRow.tsx" },
  { rule: "roas-format", file: "components/ads/PerformanceTab.tsx" },
];
