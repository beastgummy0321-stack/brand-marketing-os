/** The new-campaign wizard's unsent picks (F30-I05), kept per workspace scope and brand in this tab's
 * sessionStorage (memory fallback), so leaving step 1 and coming back keeps them. Cleared after a create
 * succeeds. Anything that is not the current shape reads as empty (an old free-text draft included). */
export interface Draft {
  productId: string | null;
  objective: string | null;
  startDate: string;
  endDate: string;
  /** 「這個活動最多花」; null = not filled (never 0). */
  budget: number | null;
  /** Optional extra sentence (進階); the server composes one from the picks when empty. */
  goalText: string;
}
const cache = new Map<string, Draft>();
const empty = (): Draft => ({ productId: null, objective: null, startDate: "", endDate: "", budget: null, goalText: "" });
const strOrNull = (v: unknown) => v === null || typeof v === "string";
function valid(value: unknown): value is Draft {
  if (!value || typeof value !== "object") return false;
  const d = value as Record<string, unknown>;
  return strOrNull(d.productId) && strOrNull(d.objective)
    && [d.startDate, d.endDate, d.goalText].every((x) => typeof x === "string")
    && (d.budget === null || (typeof d.budget === "number" && Number.isFinite(d.budget) && d.budget > 0));
}
export function readDraft(key: string): Draft {
  try {
    const value: unknown = JSON.parse(sessionStorage.getItem(key) || "null");
    if (valid(value)) return value;
  } catch { /* Memory fallback when storage is unavailable. */ }
  return cache.get(key) ?? empty();
}
export function saveDraft(key: string, draft: Draft) {
  cache.set(key, draft);
  try { sessionStorage.setItem(key, JSON.stringify(draft)); } catch { /* Keep in memory. */ }
}
export function clearDraft(key: string) {
  cache.delete(key);
  try { sessionStorage.removeItem(key); } catch { /* Storage unavailable. */ }
}
