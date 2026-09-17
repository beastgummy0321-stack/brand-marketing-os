interface Draft {
  goalText: string;
  startDate: string;
  endDate: string;
  openConstraints: Record<string, boolean>;
  constraintValues: Record<string, string>;
}
const cache = new Map<string, Draft>();
const empty = (): Draft => ({ goalText: "", startDate: "", endDate: "", openConstraints: {}, constraintValues: {} });
export function readDraft(key: string): Draft {
  try {
    const value = JSON.parse(sessionStorage.getItem(key) || "null");
    if (value && [value.goalText, value.startDate, value.endDate].every(x => typeof x === "string") &&
        value.openConstraints && typeof value.openConstraints === "object" &&
        value.constraintValues && typeof value.constraintValues === "object") return value;
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
