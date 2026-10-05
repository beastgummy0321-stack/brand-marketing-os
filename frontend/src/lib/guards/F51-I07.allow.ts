/** F51 guard ratchet entries that F51-I07 removes (the intake clients move onto `readJson`; the wizards branch on codes).
 * Read by `lib/feedbackGuards.test.ts` and `lib/figureGuards.test.ts` through `import.meta.glob("./guards/*.allow.ts")`; an entry whose
 * file no longer hits fails as stale. F51-I07 deletes its entries as it cleans each file, and this module when it is empty. */
export default [
  { rule: "envelope", file: "lib/intakeApi.ts" },
  { rule: "envelope", file: "lib/intakeOnboardingApi.ts" },
  { rule: "envelope", file: "lib/intakeProductApi.ts" },
  { rule: "envelope", file: "lib/intakeT2Api.ts" },
  { rule: "message-branch", file: "components/intake/IntakeWizard.tsx" },
  { rule: "message-branch", file: "components/intake/product/ProductOnboarding.tsx" },
  // F51-I04 (Contract D／F scanners: disabled, zero, currency, money-ratio, roas-format).
  { rule: "disabled", file: "components/intake/HistoryPage.tsx" },
  { rule: "disabled", file: "components/intake/product/BundlePage.tsx" },
  { rule: "disabled", file: "components/intake/product/ProductCard.tsx" },
  { rule: "disabled", file: "components/intake/product/ProductEvidenceStep.tsx" },
  { rule: "disabled", file: "components/intake/product/SellWayEditor.tsx" },
  { rule: "disabled", file: "components/intake/product/SellWaysStep.tsx" },
  { rule: "disabled", file: "components/intake/product/WhatStep.tsx" },
  { rule: "disabled", file: "components/intake/product/WhoStep.tsx" },
  { rule: "disabled", file: "components/intake/shared/CustomEscape.tsx" },
  { rule: "disabled", file: "components/intake/steps/EvidenceStep.tsx" },
  { rule: "disabled", file: "components/intake/steps/IdentityStep.tsx" },
  { rule: "disabled", file: "components/intake/steps/MediaStep.tsx" },
  { rule: "disabled", file: "components/intake/steps/MetaConnectPanel.tsx" },
  { rule: "disabled", file: "components/intake/steps/ScanStep.tsx" },
  { rule: "disabled", file: "components/intake/steps/StartStep.tsx" },
  { rule: "disabled", file: "components/intake/steps/ToolsStep.tsx" },
  { rule: "zero", file: "components/intake/IntakeWizard.tsx" },
  { rule: "zero", file: "components/intake/product/BundlePage.tsx" },
  { rule: "zero", file: "components/intake/product/SellWayTable.tsx" },
  { rule: "currency", file: "components/intake/product/SellWaysStep.tsx" },
  { rule: "currency", file: "components/intake/product/SellWayTable.tsx" },
];
