import { useEffect, useSyncExternalStore } from "react";
import { useParams } from "react-router-dom";
import type { AdsRules } from "@/lib/adsTriageApi";
import type { Grade } from "./Chip";

/** F48 Contract R-API (decision 11): the ONE frontend reader of the served ruler — every threshold, grade／verdict
 * word and glossary sentence an ads screen prints comes from `GET …/brands/{b}/rules`, never from a copy here.
 *
 * One request per brand per page load (module cache keyed by brand; a `brandId` change in the route loads the other
 * brand). While the rules are not loaded `useAdsRules()` is `null`: pieces print their words without the numbers and
 * never fall back to a literal. A failed read stays `null` and is retried by the next mount. Tests seed the served
 * values once for every test file (`rulesFixture.ts`, a `setupFiles` entry in `frontend/vitest.config.ts`); a seed
 * wins over any request, so a test never fetches the rules.
 *
 * The request module (`lib/adsTriageApi`) is imported when the first request is made, not at load: the test setup
 * loads this file before a test file registers its `vi.mock`s, and an eager import would pin the real transport
 * (`lib/http`) under every later mock of it. */

export type { AdsRules };

const loaded = new Map<string, AdsRules>();
const pending = new Map<string, Promise<AdsRules | null>>();
const listeners = new Set<() => void>();
let seeded: AdsRules | null = null;
let latest: AdsRules | null = null;

function notify() {
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

/** Load the brand's rules once (later calls share the request or the cached result). Resolves `null` on failure. */
export function loadAdsRules(brandId: string): Promise<AdsRules | null> {
  if (seeded) return Promise.resolve(seeded);
  const have = loaded.get(brandId);
  if (have) return Promise.resolve(have);
  let request = pending.get(brandId);
  if (!request) {
    request = import("@/lib/adsTriageApi").then(({ getAdsRules }) => getAdsRules(brandId)).then(
      (rules) => {
        loaded.set(brandId, rules);
        latest = rules;
        notify();
        return rules;
      },
      () => null,
    ).finally(() => pending.delete(brandId));
    pending.set(brandId, request);
  }
  return request;
}

/** The served rules of the route's brand (`/brands/:brandId/…`), `null` until loaded. Outside a brand route it is the
 * last rules loaded on this page. */
export function useAdsRules(): AdsRules | null {
  const { brandId } = useParams();
  useEffect(() => {
    if (brandId) void loadAdsRules(brandId);
  }, [brandId]);
  return useSyncExternalStore(subscribe, () => seeded ?? (brandId ? loaded.get(brandId) ?? null : latest));
}

/** The rules without subscribing (plain functions such as `define`); `null` until some brand's rules are loaded. */
export function peekAdsRules(): AdsRules | null {
  return seeded ?? latest;
}

/** Tests only: serve `rules` to every reader without a request (`null` = nothing seeded, back to requests). */
export function seedAdsRules(rules: AdsRules | null) {
  seeded = rules;
  notify();
}

/** A ruler number as words print it (`2`, `1.3`) — never `2.0000000000000004`. */
export function figure(value: number): string {
  return String(Number(value.toFixed(6)));
}

/** 偏貴's width in 成 (tenths over the cap), e.g. `2` for a 1.2 × cap band. */
export function watchTenths(rules: AdsRules): string {
  return figure((rules.grade.watch_band - 1) * 10);
}

/** The cost line between 偏貴 and 太貴 for cap `cap`. */
export function watchLine(rules: AdsRules, cap: number): number {
  return cap * rules.grade.watch_band;
}

/** The spend line of 沒賣出 for cap `cap` (a known zero below it is 剛開始). */
export function unsoldLine(rules: AdsRules, cap: number): number {
  return cap * rules.grade.unsold_spend_multiple;
}

/** The served word of a grade. `insufficient` splits by the item's `reason_code`: `too_new` (or no code) is 剛開始、數字
 * 還不夠, any other code 資料不足. `null` while the rules are not loaded. */
export function gradeWord(rules: AdsRules | null, grade: Grade, reasonCode?: string | null): string | null {
  if (!rules) return null;
  if (grade === "insufficient") return rules.labels.grade[reasonCode && reasonCode !== "too_new" ? "no_data" : "too_new"];
  return rules.labels.grade[grade];
}

/** The sample chip's word of an item's `sample`: the served 「樣本少」 (`labels.flags.few`) when `few`, else none (and
 * none while the rules are not loaded). The only sample chip: `too_new` is not shown — beside a grade it contradicts it
 * (沒賣出＋還太新), and on a 7-day campaign it would sit on every row. */
export function sampleWords(rules: AdsRules | null, sample: { few?: boolean } | null | undefined): string[] {
  return rules && sample?.few ? [rules.labels.flags.few] : [];
}
