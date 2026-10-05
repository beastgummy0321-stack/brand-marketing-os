/** F51 guard ratchet entries that F51-I06 removes (meta, schedule and brand-report clients move onto `readJson`).
 * Read by `lib/feedbackGuards.test.ts` and `lib/figureGuards.test.ts` through `import.meta.glob("./guards/*.allow.ts")`; an entry whose
 * file no longer hits fails as stale. F51-I06 deletes its entries as it cleans each file, and this module when it is empty. */
export default [
  { rule: "envelope", file: "lib/metaApi.ts" },
  { rule: "envelope", file: "lib/scheduleApi.ts" },
  { rule: "envelope", file: "lib/brandReportApi.ts" },
  // F51-I04 (Contract D／F scanners: disabled, zero, currency, money-ratio, roas-format).
  { rule: "disabled", file: "components/cockpit/CockpitPage.tsx" },
  { rule: "disabled", file: "components/cockpit/DashboardWidgets.tsx" },
  { rule: "disabled", file: "components/cockpit/DiagnosisPanel.tsx" },
  { rule: "disabled", file: "components/cockpit/LayoutEditor.tsx" },
  { rule: "disabled", file: "components/cockpit/ProductsBlock.tsx" },
  { rule: "disabled", file: "components/report/BrandReportPage.tsx" },
  { rule: "zero", file: "components/cockpit/CoordinateQuadrantChart.tsx" },
  { rule: "zero", file: "components/cockpit/DashboardWidgets.tsx" },
  { rule: "zero", file: "components/report/BrandReportPage.tsx" },
  { rule: "currency", file: "components/report/BrandReportPage.tsx" },
];
