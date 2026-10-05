/** F51 guard ratchet entries that F51-I13 removes (the review, settle and wait screens, and the ads pattern pieces' deprecated `disabled`: a greyed-out control says why, and every
 * figure prints through `layout/Figure` by its basis). Read by `lib/feedbackGuards.test.ts` and `lib/figureGuards.test.ts`
 * through `import.meta.glob("./guards/*.allow.ts")`; an entry whose file no longer hits fails as stale. F51-I13
 * deletes its entries as it cleans each file, and this module when it is empty. */
export default [
  { rule: "href", file: "components/ads/wait/WaitPage.tsx" },
  { rule: "href", file: "components/ads/review/CopyPage.tsx" },
  // F51-I04 (Contract D／F scanners: disabled, zero, currency, money-ratio, roas-format).
  { rule: "disabled", file: "components/ads/patterns/DecisionCard.tsx" },
  { rule: "disabled", file: "components/ads/patterns/LoopPieces.tsx" },
  { rule: "disabled", file: "components/ads/patterns/PickCard.tsx" },
  { rule: "disabled", file: "components/ads/patterns/ReviewPieces.tsx" },
  { rule: "disabled", file: "components/ads/patterns/RowMenu.tsx" },
  { rule: "disabled", file: "components/ads/review/CopyPage.tsx" },
  { rule: "disabled", file: "components/ads/review/MaterialStepPage.tsx" },
  { rule: "disabled", file: "components/ads/review/PreparePage.tsx" },
  { rule: "disabled", file: "components/ads/review/ReviewEvidencePage.tsx" },
  { rule: "disabled", file: "components/ads/ReviewPanel.tsx" },
  { rule: "disabled", file: "components/ads/ReviewTracking.tsx" },
  { rule: "disabled", file: "components/ads/settle/SettleNote.tsx" },
  { rule: "disabled", file: "components/ads/wait/WaitPage.tsx" },
  { rule: "zero", file: "components/ads/review/reviewFlow.ts" },
  { rule: "zero", file: "components/ads/ReviewPanel.tsx" },
  { rule: "zero", file: "components/ads/settle/SettleAngles.tsx" },
];
