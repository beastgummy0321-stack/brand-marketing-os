/** oneRuler.test.ts pending entries that W19 removes (F49 lead split). Empty or delete when done. */
export const lifecycle = [
  { rule: "native", file: "components/ads/flow/changeFlow.ts", issue: "W19", text: 'after: { status: "PAUSED" }' },
  { rule: "native", file: "components/ads/ChangeComposer.tsx", issue: "W19", text: '{ status: "PAUSED" }' },
];
