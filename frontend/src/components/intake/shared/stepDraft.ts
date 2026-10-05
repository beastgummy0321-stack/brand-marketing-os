import { useEffect } from "react";

/** frontend/src/components/intake/shared/stepDraft.ts -- the one keeper of an onboarding step's unsaved edits
 * (F47-I03; drill-10 乙 #1, 甲 建檔 #5, faults F3 / F7): kept in
 * `sessionStorage` under a per-brand / per-product, per-step key while the fields differ from what the step
 * loaded, restored when the step mounts again (「← 上一步」, the step bar, a reload), and dropped once the step's
 * 下一步 saved. Each step keeps only its own shape check and its loaded baseline. */

/** Brand drafts are isolated by user/org scope, brand and step; files never belong here. */
export function brandDraftKey(scope: string | undefined, brandId: string, step: string): string {
  return `intake-draft:${scope ?? ""}:${brandId}:${step}`;
}

/** The draft key of a product onboarding step (product ids are unique across brands; sessionStorage is per tab). */
export function productDraftKey(brandId: string, productId: string, step: string): string {
  return `intake-draft:${brandId}:${productId}:${step}`;
}

/** The kept draft under `key`, or `null` when there is none or it is not of the step's shape. */
export function readStepDraft<T>(key: string, isShape: (value: unknown) => value is T): T | null {
  try {
    const value: unknown = JSON.parse(sessionStorage.getItem(key) || "null");
    return value !== null && isShape(value) ? value : null;
  } catch {
    return null;
  }
}

export function clearStepDraft(key: string): void {
  try {
    sessionStorage.removeItem(key);
  } catch {
    /* Storage unavailable. */
  }
}

/** Keeps `current` under `key` while it differs from `baseline` (what the step loaded); once they match again the
 * draft is dropped. Does nothing until `ready` (the step's data has loaded). */
export function useStepDraft(key: string, ready: boolean, current: unknown, baseline: unknown): void {
  const text = JSON.stringify(current);
  const base = JSON.stringify(baseline);
  useEffect(() => {
    if (!ready) return;
    try {
      if (text === base) sessionStorage.removeItem(key);
      else sessionStorage.setItem(key, text);
    } catch {
      /* Storage unavailable: nothing is kept. */
    }
  }, [key, ready, text, base]);
}
