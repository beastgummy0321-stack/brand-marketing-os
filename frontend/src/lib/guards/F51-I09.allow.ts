/** F51 guard ratchet entries that F51-I09 removes (the ads home, all-campaigns, month, learnings, pattern and connections screens: a greyed-out control says why, and every
 * figure prints through `layout/Figure` by its basis). Read by `lib/feedbackGuards.test.ts` and `lib/figureGuards.test.ts`
 * through `import.meta.glob("./guards/*.allow.ts")`; an entry whose file no longer hits fails as stale. F51-I09
 * deletes its entries as it cleans each file, and this module when it is empty. */
export default [
  // F51-I04 (Contract D／F scanners: disabled, zero, currency, money-ratio, roas-format).
  { rule: "disabled", file: "components/ads/connections/DataConnectionsPage.tsx" },
  { rule: "disabled", file: "components/ads/month/MonthReviewPage.tsx" },
  { rule: "disabled", file: "components/ads/month/RejectedCards.tsx" },
  { rule: "zero", file: "components/ads/AllCampaignsPage.tsx" },
  { rule: "zero", file: "components/ads/connections/DataConnectionsPage.tsx" },
  { rule: "zero", file: "components/ads/home/CampaignRows.tsx" },
  { rule: "zero", file: "components/ads/home/MonthMoney.tsx" },
  { rule: "zero", file: "components/ads/home/QueueRow.tsx" },
  { rule: "zero", file: "components/ads/learnings/GroupSummary.tsx" },
  { rule: "zero", file: "components/ads/learnings/LearningsTable.tsx" },
  { rule: "zero", file: "components/ads/month/MonthReviewPage.tsx" },
  { rule: "zero", file: "components/ads/patterns/GradeBand.tsx" },
  { rule: "zero", file: "components/ads/patterns/PaceChart.tsx" },
  { rule: "zero", file: "components/ads/patterns/ReviewPieces.tsx" },
  { rule: "zero", file: "components/ads/patterns/ScenarioBars.tsx" },
  { rule: "zero", file: "components/ads/patterns/SlotGrid.tsx" },
  { rule: "zero", file: "components/ads/patterns/TargetRuler.tsx" },
  { rule: "money-ratio", file: "components/ads/patterns/ScenarioBars.tsx" },
];
