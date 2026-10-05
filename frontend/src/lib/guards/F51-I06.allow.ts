/** F51 feedback-guard ratchet entries that F51-I06 removes (meta, schedule and brand-report clients move onto `readJson`).
 * Read by `lib/feedbackGuards.test.ts` through `import.meta.glob("./guards/*.allow.ts")`; an entry whose
 * file no longer hits fails as stale. F51-I06 deletes its entries as it cleans each file, and this module when it is empty. */
export default [
  { rule: "envelope", file: "lib/metaApi.ts" },
  { rule: "envelope", file: "lib/scheduleApi.ts" },
  { rule: "envelope", file: "lib/brandReportApi.ts" },
];
