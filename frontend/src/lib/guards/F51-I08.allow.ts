/** F51 feedback-guard ratchet entries that F51-I08 removes (library, products, settings, orders and coordinates clients move onto `readJson`).
 * Read by `lib/feedbackGuards.test.ts` through `import.meta.glob("./guards/*.allow.ts")`; an entry whose
 * file no longer hits fails as stale. F51-I08 deletes its entries as it cleans each file, and this module when it is empty. */
export default [
  { rule: "envelope", file: "lib/libraryApi.ts" },
  { rule: "envelope", file: "lib/productsApi.ts" },
  { rule: "envelope", file: "lib/settingsApi.ts" },
  { rule: "envelope", file: "lib/ordersApi.ts" },
  { rule: "envelope", file: "lib/coordinatesApi.ts" },
  { rule: "message-branch", file: "components/products/ProductDetailPage.tsx" },
];
