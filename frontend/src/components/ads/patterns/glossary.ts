import type { AdsRules } from "@/lib/adsTriageApi";
import { formatAmount } from "./Chip";
import { peekAdsRules } from "./rules";

/** The coined ads words (Feature F29 Contract K; prototype v10 `GLOSS`). `Term` shows their sentences on hover, focus
 * and tap; no screen writes its own explanation line. F48 Contract R-API: every sentence is the served
 * `rules.glossary[key]` (built by the backend from the ruler's own constants) — this file keeps no wording. */
export type GlossaryKey = "cap" | "break_even" | "on_target" | "watch" | "over" | "wasted" | "thin" | "money" | "notebook";

/** The served sentence for `key` (`rules` defaults to the loaded rules; `""` while none are loaded). Break-even's
 * sentence gains its own value 「（這裡是 520）」 after the first clause; an unknown value adds nothing rather than a
 * guess. */
export function define(key: GlossaryKey, value?: number | null, rules: AdsRules | null = peekAdsRules()): string {
  const sentence = rules?.glossary[key] ?? "";
  if (key !== "break_even") return sentence;
  const known = formatAmount(value);
  if (known === null || !sentence) return sentence;
  const cut = sentence.indexOf("；");
  const here = `（這裡是 ${known}）`;
  return cut === -1 ? `${sentence}${here}` : `${sentence.slice(0, cut)}${here}${sentence.slice(cut)}`;
}

export const GLOSSARY_KEYS: readonly GlossaryKey[] = ["cap", "break_even", "on_target", "watch", "over", "wasted", "thin", "money", "notebook"];
