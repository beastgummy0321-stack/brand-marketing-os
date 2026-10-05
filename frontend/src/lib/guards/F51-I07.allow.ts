/** F51 feedback-guard ratchet entries that F51-I07 removes (the intake clients move onto `readJson`; the wizards branch on codes).
 * Read by `lib/feedbackGuards.test.ts` through `import.meta.glob("./guards/*.allow.ts")`; an entry whose
 * file no longer hits fails as stale. F51-I07 deletes its entries as it cleans each file, and this module when it is empty. */
export default [
  { rule: "envelope", file: "lib/intakeApi.ts" },
  { rule: "envelope", file: "lib/intakeOnboardingApi.ts" },
  { rule: "envelope", file: "lib/intakeProductApi.ts" },
  { rule: "envelope", file: "lib/intakeT2Api.ts" },
  { rule: "message-branch", file: "components/intake/IntakeWizard.tsx" },
  { rule: "message-branch", file: "components/intake/product/ProductOnboarding.tsx" },
];
