/** F51 feedback-guard ratchet entries that F51-I02 removes (the ads clients and workbench move onto `readJson`, feature Contract H).
 * Read by `lib/feedbackGuards.test.ts` through `import.meta.glob("./guards/*.allow.ts")`; an entry whose
 * file no longer hits fails as stale. F51-I02 deletes its entries as it cleans each file, and this module when it is empty. */
export default [
  { rule: "envelope", file: "lib/adsApi.ts" },
  { rule: "envelope", file: "lib/adsChangeApi.ts" },
  { rule: "envelope", file: "lib/adsConnectionsApi.ts" },
  { rule: "envelope", file: "lib/adsHandoffApi.ts" },
  { rule: "envelope", file: "lib/adsHomeApi.ts" },
  { rule: "envelope", file: "lib/adsMaterialApi.ts" },
  { rule: "envelope", file: "lib/adsMonthApi.ts" },
  { rule: "envelope", file: "lib/adsSettleApi.ts" },
  { rule: "envelope", file: "lib/adsSlotsApi.ts" },
  { rule: "envelope", file: "lib/adsTriageApi.ts" },
  { rule: "envelope", file: "lib/adsUserAssetsApi.ts" },
  { rule: "envelope", file: "lib/adsWorkspaceApi.ts" },
  { rule: "envelope", file: "lib/workbenchApi.ts" },
  { rule: "message-branch", file: "components/ads/UserAssetsLibrary.tsx" },
];
