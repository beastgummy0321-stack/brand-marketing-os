import { apiFetch } from "./http";
import { BASE, parseJsonOrThrow } from "./adsApi";
import type { HandoffWorkspace } from "./adsHandoffApi";

/** F29 Contract I: one set of launch settings per campaign, used by every ad set of the launch.
 * Choice fields with program-recommended values; UTM stays text with a format check. Nothing here
 * writes to an ad platform: readback compares the approved values with a platform READ. */
export type OptimizationEvent = "purchase" | "add_to_cart" | "initiate_checkout" | "view_content";
export type BidStrategy = "lowest_cost" | "cost_cap" | "bid_cap";
export type PlacementPosition = "facebook_feed" | "instagram_feed" | "stories" | "reels" | "messenger";
export type AudienceGender = "all" | "female" | "male";

export interface LaunchSettingsValues {
  optimization_event: OptimizationEvent;
  bid_strategy: BidStrategy;
  /** F47-I06 (Contract A bid): the one amount of a `cost_cap`／`bid_cap` strategy, kept as typed (an unset or
   * non-positive amount is an `errors` entry); absent for every other strategy. Not a readback field. */
  bid_amount?: number | null;
  /** `positions` is empty while `mode` is "auto". */
  placement: { mode: "auto" | "manual"; positions: PlacementPosition[] };
  /** Ages 18–65; 65 means 65+. `countries` are ISO codes from `options.countries`. */
  audience: { age_min: number; age_max: number; gender: AudienceGender; countries: string[] };
  pixel_id: string | null;
  utm: string;
}
export type LaunchSettingsKey = keyof LaunchSettingsValues;

/** One choice with its one-line plain note (shown under the field). */
export interface LaunchSettingOption<T extends string = string> { value: T; label: string; note: string }
export interface LaunchSettingsOptions {
  optimization_event: LaunchSettingOption<OptimizationEvent>[];
  bid_strategy: LaunchSettingOption<BidStrategy>[];
  positions: LaunchSettingOption<PlacementPosition>[];
  countries: LaunchSettingOption[];
  /** null when the platform list could not be read (`pixels_error` says why) — never an empty
   * list standing in for a failed read. */
  pixels: { id: string; name: string }[] | null;
  pixels_error: string | null;
  placement_modes: LaunchSettingOption<"auto" | "manual">[];
  genders: LaunchSettingOption<AudienceGender>[];
  ages: number[];
  field_notes: { audience: string; pixel_id: string; utm: string };
}
export type LaunchSettingsErrorCode =
  | "utm_format" | "utm_source_missing" | "age_range" | "countries_empty" | "positions_empty" | "pixel_unknown"
  | "pixel_format" | "bid_amount_missing" | "bid_amount_invalid";
/** Any error blocks the launch approval (409 `launch_settings_invalid`). */
export interface LaunchSettingsError {
  field: "utm" | "audience.age" | "audience.countries" | "placement.positions" | "pixel_id" | "bid_amount";
  code: LaunchSettingsErrorCode;
  message: string;
}
export interface LaunchSettingsView {
  values: LaunchSettingsValues;
  recommended: LaunchSettingsValues;
  options: LaunchSettingsOptions;
  /** Top-level keys whose value differs from `recommended` (tagged 「你改的」). */
  edited: LaunchSettingsKey[];
  errors: LaunchSettingsError[];
}

export type SettingsReadbackKey =
  | "optimization_event" | "bid_strategy" | "placement" | "age" | "gender" | "countries" | "pixel_id" | "utm";
export type SettingsReadbackState = "match" | "differ" | "unreadable" | "self_confirmed";
export interface SettingsReadbackField {
  key: SettingsReadbackKey;
  label: string;
  expected_label: string;
  /** The platform's value (set for `match` and `differ`); null when it could not be read. */
  observed_label: string | null;
  state: SettingsReadbackState;
  /** Why a field is unreadable (e.g. a missing read permission). */
  reason: string | null;
}
/** `GET …/handoff` → `settings_readback`: null before any ad set or ad was read back, or for a
 * launch approved before launch settings existed. */
export interface SettingsReadback { read_at: string | null; fields: SettingsReadbackField[] }

const path = (brand: string, campaign: string) =>
  `${BASE}/brands/${encodeURIComponent(brand)}/campaigns/${encodeURIComponent(campaign)}`;

/** Reads the account's pixel list from the platform (read only) before answering. */
export async function getLaunchSettings(brand: string, campaign: string, signal?: AbortSignal): Promise<LaunchSettingsView> {
  return parseJsonOrThrow(await apiFetch(`${path(brand, campaign)}/launch-settings`, { signal }), "讀取投放設定失敗。");
}
/** Saves shape-checked values (400 `launch_settings_malformed` otherwise); format problems come
 * back in `errors`, saved, not refused. An edit after approval makes the launch stale. */
export async function saveLaunchSettings(brand: string, campaign: string, values: LaunchSettingsValues, signal?: AbortSignal): Promise<LaunchSettingsView> {
  return parseJsonOrThrow(await apiFetch(`${path(brand, campaign)}/launch-settings`, {
    method: "PUT", signal, headers: { "Content-Type": "application/json" }, body: JSON.stringify(values),
  }), "儲存投放設定失敗。");
}
/** The user checked the platform by eye: an `unreadable` field becomes `self_confirmed`. Any other
 * state is refused (409). Answers with the refreshed handoff workspace. */
export async function confirmLaunchSetting(
  brand: string, campaign: string, key: SettingsReadbackKey, signal?: AbortSignal,
): Promise<HandoffWorkspace & { settings_readback: SettingsReadback | null }> {
  return parseJsonOrThrow(await apiFetch(`${path(brand, campaign)}/handoff/launch/settings-confirm`, {
    method: "POST", signal, headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key }),
  }), "確認投放設定失敗。");
}
