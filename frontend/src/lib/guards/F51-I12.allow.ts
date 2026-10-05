/** F51 guard ratchet entries that F51-I12 removes (the change, flow, publish, budget and handoff screens: a greyed-out control says why, and every
 * figure prints through `layout/Figure` by its basis). Read by `lib/feedbackGuards.test.ts` and `lib/figureGuards.test.ts`
 * through `import.meta.glob("./guards/*.allow.ts")`; an entry whose file no longer hits fails as stale. F51-I12
 * deletes its entries as it cleans each file, and this module when it is empty. */
export default [
  // F51-I04 (Contract D／F scanners: disabled, zero, currency, money-ratio, roas-format).
  { rule: "disabled", file: "components/ads/ChangeComposer.tsx" },
  { rule: "disabled", file: "components/ads/ChangeControl.tsx" },
  { rule: "disabled", file: "components/ads/ChangeSetView.tsx" },
  { rule: "disabled", file: "components/ads/CloseCampaignDialog.tsx" },
  { rule: "disabled", file: "components/ads/flow/CleanupRebuild.tsx" },
  { rule: "disabled", file: "components/ads/flow/ConfirmPage.tsx" },
  { rule: "disabled", file: "components/ads/flow/confirmParts.tsx" },
  { rule: "disabled", file: "components/ads/flow/HandoffPage.tsx" },
  { rule: "disabled", file: "components/ads/flow/VerifyPage.tsx" },
  { rule: "disabled", file: "components/ads/LaunchStalePanel.tsx" },
  { rule: "disabled", file: "components/ads/ManualHandoffPanel.tsx" },
  { rule: "disabled", file: "components/ads/MonthlyBudgetPanel.tsx" },
  { rule: "disabled", file: "components/ads/publish/PublishList.tsx" },
  { rule: "disabled", file: "components/ads/publish/PublishPlatform.tsx" },
  { rule: "disabled", file: "components/ads/publish/PublishVerify.tsx" },
  { rule: "disabled", file: "components/ads/publish/SettingsReadback.tsx" },
  { rule: "zero", file: "components/ads/flow/ConfirmPage.tsx" },
  { rule: "zero", file: "components/ads/flow/confirmParts.tsx" },
  { rule: "zero", file: "components/ads/ManualHandoffPanel.tsx" },
  { rule: "zero", file: "components/ads/publish/LaunchSettingsCard.tsx" },
  { rule: "zero", file: "components/ads/publish/PublishVerify.tsx" },
  { rule: "currency", file: "components/ads/flow/confirmParts.tsx" },
];
