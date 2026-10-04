/** oneRuler.test.ts pending entries that W14 removes (F49 lead split). Empty or delete when done. */
export const sync = [
  { file: "components/ads/settle/SettleAngles.tsx", issue: "W14", text: "found?.job.status",
    why: "an AI (LLM) job's queue status, not a platform read; background job outcomes are W14 (feature C)" },
];
