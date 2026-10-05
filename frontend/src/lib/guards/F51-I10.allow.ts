/** F51 guard ratchet entries that F51-I10 removes (the campaign workspace head／overview／structure, strategy, delivery, new-campaign and confirm-brief screens: a greyed-out control says why, and every
 * figure prints through `layout/Figure` by its basis). Read by `lib/feedbackGuards.test.ts` and `lib/figureGuards.test.ts`
 * through `import.meta.glob("./guards/*.allow.ts")`; an entry whose file no longer hits fails as stale. F51-I10
 * deletes its entries as it cleans each file, and this module when it is empty. */
export default [
  { rule: "href", file: "components/ads/workspace/WorkspaceHead.tsx" },
  { rule: "href", file: "components/ads/workspace/OverviewBody.tsx" },
  { rule: "href", file: "components/ads/DeliveryTab.tsx" },
  { rule: "href", file: "components/ads/ConfirmBriefPage.tsx" },
  { rule: "href", file: "components/ads/CampaignWorkspace.tsx" },
  // F51-I04 (Contract D／F scanners: disabled, zero, currency, money-ratio, roas-format).
  { rule: "disabled", file: "components/ads/ConfirmBriefPage.tsx" },
  { rule: "disabled", file: "components/ads/DeliveryEditors.tsx" },
  { rule: "disabled", file: "components/ads/DeliveryTab.tsx" },
  { rule: "disabled", file: "components/ads/ExperimentPlan.tsx" },
  { rule: "disabled", file: "components/ads/NewCampaignPage.tsx" },
  { rule: "disabled", file: "components/ads/SimulationRecovery.tsx" },
  { rule: "disabled", file: "components/ads/strategy/BudgetScenarios.tsx" },
  { rule: "disabled", file: "components/ads/strategy/CapBlock.tsx" },
  { rule: "disabled", file: "components/ads/StrategyTab.tsx" },
  { rule: "zero", file: "components/ads/CampaignWorkspace.tsx" },
  { rule: "zero", file: "components/ads/ConfirmBriefPage.tsx" },
  { rule: "zero", file: "components/ads/DeliveryTab.tsx" },
  { rule: "zero", file: "components/ads/strategy/BudgetScenarios.tsx" },
  { rule: "zero", file: "components/ads/StrategyTab.tsx" },
  { rule: "zero", file: "components/ads/workspace/OverviewBody.tsx" },
  { rule: "zero", file: "components/ads/workspace/StructureTab.tsx" },
  { rule: "currency", file: "components/ads/ConfirmBriefPage.tsx" },
  { rule: "currency", file: "components/ads/NewCampaignPage.tsx" },
  { rule: "currency", file: "components/ads/strategy/CapBlock.tsx" },
  { rule: "currency", file: "components/ads/StrategyTab.tsx" },
  { rule: "currency", file: "components/ads/wizard/WizardPieces.tsx" },
  { rule: "currency", file: "components/ads/workspace/OverviewBody.tsx" },
  { rule: "money-ratio", file: "components/ads/ConfirmBriefPage.tsx" },
  { rule: "money-ratio", file: "components/ads/strategy/CapBlock.tsx" },
  { rule: "money-ratio", file: "components/ads/workspace/OverviewBody.tsx" },
];
