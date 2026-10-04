/** oneRuler.test.ts pending entries that F49-I13 removes (F49 lead split). Empty or delete when done. */
export const lifecycle = [
  { rule: "native", file: "components/ads/AssetsTab.tsx", issue: "F49-I13" },
  { rule: "native", file: "components/ads/DeliveryTab.tsx", issue: "F49-I13" },
  { rule: "lifecycle", file: "components/ads/DeliveryTab.tsx", issue: "F49-I13" },
];
export const slot = [
  { rule: "chip", file: "components/ads/workspace/SlotTiles.tsx", issue: "F49-I13" },
  { rule: "chip", file: "components/ads/workspace/AssetsBody.tsx", issue: "F49-I13" },
  { rule: "missing", file: "components/ads/workspace/StructureTab.tsx", issue: "F49-I13" },
];
