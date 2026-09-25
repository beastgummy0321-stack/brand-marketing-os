import { formatAmount } from "./Chip";

/** The ONE definition source for every coined ads word (Feature F29 Contract K; prototype v10 `GLOSS`).
 * `Term` shows these sentences on hover, focus and tap; no screen writes its own explanation line.
 * Wording is the prototype's, except `thin`, which states the ruled sample gate (§6.17: spend ≥ 3 × cap,
 * or ≥ 10 results over ≥ 7 days) instead of the prototype's "3 筆". */
export type GlossaryKey = "cap" | "break_even" | "on_target" | "watch" | "over" | "wasted" | "thin" | "money" | "notebook";

const FIXED: Record<Exclude<GlossaryKey, "break_even">, string> = {
  cap: "你願意為一筆訂單付的廣告費，每個活動自己設",
  on_target: "每筆廣告費沒超過這個活動的上限",
  watch: "每筆廣告費超過上限，但超過不到 2 成",
  over: "每筆廣告費超過上限 2 成以上，賣越多虧越多",
  wasted: "花到上限 3 倍的錢，還一筆都沒賣出",
  money: "拿每筆廣告費跟打平線比：比它低是有賺，比它高是在虧，差不到 2% 算剛好打平",
  thin: "花的錢還沒到上限 3 倍，也還沒跑滿 7 天、賣出 10 筆，現在打分數不準",
  notebook: "系統記住哪些主打有效；下次開新活動，AI 會先讀這些，避開沒效的主打",
};

/** The sentence for `key`. Break-even carries its own value (「這裡是 520」); an unknown value drops that part
 * rather than printing a guess. */
export function define(key: GlossaryKey, value?: number | null): string {
  if (key !== "break_even") return FIXED[key];
  const known = formatAmount(value);
  return `賣一筆扣掉商品成本和運費後剩下的錢${known === null ? "" : `（這裡是 ${known}）`}；每筆廣告費超過它，就是在虧`;
}

export const GLOSSARY_KEYS: readonly GlossaryKey[] = ["cap", "break_even", "on_target", "watch", "over", "wasted", "thin", "money", "notebook"];
