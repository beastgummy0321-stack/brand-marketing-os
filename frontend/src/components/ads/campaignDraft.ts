/** Scoped wizard picks and recoverable submission receipts. Form memory is a convenience;
 * submission receipts require a verified sessionStorage or Router-history round trip. */
import type {CampaignPicks} from "@/lib/adsWizardApi";

export interface UploadReference {id: string; batch_id: string; filename: string}
export interface Attempt {
  payload: CampaignPicks;
  createdId?: string;
  uploads: UploadReference[];
  attached: string[];
}
export interface Draft {
  productId: string | null;
  objective: string | null;
  startDate: string;
  endDate: string;
  /** 「這個活動最多花」; null = not filled (never 0). */
  budget: number | null;
  /** Optional extra sentence (進階); the server composes one from the picks when empty. */
  goalText: string;
  platform?: string | null;
  groupPick?: string;
  cap?: number | null;
  landing?: string;
  uploads?: UploadReference[];
  mappingProductId?: string | null;
  mappingScope?: string;
  attachment?: {campaignId: string; ids: string[]};
}
const cache = new Map<string, Draft>();
const empty = (): Draft => ({ productId: null, objective: null, startDate: "", endDate: "", budget: null, goalText: "" });
const strOrNull = (v: unknown) => v === null || typeof v === "string";
function valid(value: unknown): value is Draft {
  if (!value || typeof value !== "object") return false;
  const d = value as Record<string, unknown>;
  return strOrNull(d.productId) && strOrNull(d.objective)
    && (d.attachment === undefined || (!!d.attachment && typeof d.attachment === "object"
      && "campaignId" in d.attachment && typeof d.attachment.campaignId === "string"
      && "ids" in d.attachment && Array.isArray(d.attachment.ids) && d.attachment.ids.every(id => typeof id === "string")))
    && (d.uploads === undefined || (Array.isArray(d.uploads) && d.uploads.every(ref => ref &&
      typeof ref.id === "string" && typeof ref.batch_id === "string" && typeof ref.filename === "string")))
    && [d.startDate, d.endDate, d.goalText].every((x) => typeof x === "string")
    && (d.budget === null || (typeof d.budget === "number" && Number.isFinite(d.budget) && d.budget > 0));
}
type Stored = {version: number; value: unknown};
function envelope(value: unknown): Stored {
  return value && typeof value === "object" && "version" in value && "value" in value &&
    typeof value.version === "number" && Number.isFinite(value.version) && value.version >= 0
    ? value as Stored : {version: 0, value};
}
function copies(key: string): Stored[] {
  const values = [envelope(window.history.state?.usr?.campaignWizard?.[key])];
  try {
    values.push(envelope(JSON.parse(sessionStorage.getItem(key) || "null")));
  } catch { /* Memory fallback when storage is unavailable. */ }
  return values;
}
function readStored(key: string): unknown {
  return copies(key).filter(item => item.version > 0 || item.value != null).sort((a,b) => b.version - a.version)[0]?.value ?? null;
}
/** Preserve Router's usr/key/idx. A successful round trip is required before a recoverable POST. */
function store(key: string, value: unknown): boolean {
  const saved: Stored = {version: Math.max(...copies(key).map(item => item.version)) + 1, value};
  const text = JSON.stringify(saved);
  let durable = false;
  try { sessionStorage.setItem(key, text); durable = sessionStorage.getItem(key) === text; } catch { /* Try history. */ }
  try {
    const state = window.history.state ?? {};
    const usr = state.usr ?? {};
    window.history.replaceState({...state, usr: {...usr, campaignWizard: {...usr.campaignWizard, [key]: saved}}}, "");
    durable = JSON.stringify(window.history.state?.usr?.campaignWizard?.[key]) === text || durable;
  } catch { /* Never substitute a volatile Map for a submission receipt. */ }
  return durable;
}
function remove(key: string) {
  // A durable tombstone also beats receipts left in earlier history entries.
  store(key, null);
}
export function readDraft(key: string): Draft {
  const value = readStored(key);
  if (valid(value)) return value;
  return cache.get(key) ?? empty();
}
export function saveDraft(key: string, draft: Draft) {
  cache.set(key, draft);
  return store(key, draft);
}
export function clearDraft(key: string) {
  cache.delete(key);
  remove(key); remove(`${key}:attempt`);
}
export function readAttempt(key: string): Attempt | null {
  const value = readStored(`${key}:attempt`) as Attempt | null;
  return value?.payload?.continuation?.request_id && Array.isArray(value.uploads) && Array.isArray(value.attached) ? value : null;
}
export function saveAttempt(key: string, attempt: Attempt): boolean { return store(`${key}:attempt`, attempt); }
