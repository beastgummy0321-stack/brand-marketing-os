/** 投放前的品牌層資料：可投放檢查表（F05-I04）＋通路清單（F05-I05）。跟 `adsApi.ts` 分開檔案
 * 只是為了不撐破 800 行慣例，共用 `BASE` 從那邊 import，回應一律交給 `http.readJson`。 */
import { apiFetch, readJson } from "./http";
import { BASE } from "./adsApi";
import type { MonthlyBudget } from "./adsChangeApi";
import type { LaunchSettingsValues, SettingsReadback } from "./adsLaunchSettingsApi";

/** F05-I04：可投放檢查表——`app/ads/readiness.py::launch_readiness()` 的回傳形狀，瀏覽器逐字印
 * 每一列的 `reason`，不重拼句子。三色沒有第四種狀態、`items` 固定三列固定順序。 */
export type ReadinessState = "green" | "yellow" | "red";

export interface ReadinessItem {
  key: string;
  label: string;
  state: ReadinessState;
  reason: string;
  fix_label: string;
  fix_href: string;
}

export interface ReadinessNote {
  key: string;
  text: string;
}

export interface ReadinessAction {
  label: string;
  href: string;
}

export interface LaunchReadiness {
  state: ReadinessState;
  items: ReadinessItem[];
  notes: ReadinessNote[];
  primary: ReadinessAction;
  secondary: ReadinessAction | null;
}

export async function fetchLaunchReadiness(brandId: string): Promise<LaunchReadiness> {
  const res = await apiFetch(`${BASE}/brands/${encodeURIComponent(brandId)}/readiness`);
  const data = await readJson<{ readiness: LaunchReadiness }>(res, "讀取可投放檢查表失敗。");
  return data.readiness;
}

/** F05-I05：通路清單，平台名字只准住在後端 `channels.py`，畫面不准自己寫死。 */
export interface Channel { key: string; label: string; connected: boolean; state_text: string }

export async function fetchChannels(brandId: string): Promise<Channel[]> {
  const res = await apiFetch(`${BASE}/brands/${encodeURIComponent(brandId)}/channels`);
  const data = await readJson<{ channels: Channel[] }>(res, "讀取通路清單失敗。");
  return data.channels;
}


export interface ManualHandoff {
  /** `readable` (F49 decision 5): false when no platform reader can see the value -- approving the launch confirms it. */
  fields: { key: string; label: string; section: string; required: boolean; readable?: boolean }[];
  groups: { id: string; name: string; values: Record<string, string>; missing: string[];
    status: string; saved_at: string | null; saved_by: string | null;
    ads: { id: string; name: string }[] }[];
  pending_count: number;
}

export async function saveManualSettings(
  brandId: string, campaignId: string, groupId: string, values: Record<string, string>,
): Promise<void> {
  const res = await apiFetch(`${BASE}/brands/${brandId}/campaigns/${campaignId}/groups/${groupId}/manual-settings`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ values }),
  });
  await readJson<{ ok: boolean }>(res, "儲存人工上架設定失敗，請稍後再試。");
}

/** F30 Contract G: the one launch view of the publish page (`app/ads/launch_view.py`). The batch
 * holds only ads whose material is ready; the others are `deferred_ads` and go out with a later
 * launch version. Nothing here writes to a platform. */
export type LaunchStep = "list" | "platform" | "verify" | "stale";
export type LaunchItemKind = "campaign" | "group" | "ad";
export type LaunchItemState = "todo" | "built" | "verified" | "mismatch" | "unknown" | "changed";

export interface LaunchSummary {
  campaigns: number;
  groups: number;
  ads: number;
  /** Null when a group has no daily budget. */
  daily_total: number | null;
  start: string | null;
  end: string | null;
  /** The user's own per-result cap; null when none is set. */
  cap: number | null;
  slots_ready: number;
  slots_total: number;
}

export interface LaunchField { key: string; label: string; value: string | number | null }
export interface LaunchMismatch {
  key: string;
  label: string;
  expected: string | number | null;
  /** What the platform showed, stored with the check. */
  observed: string | number | null;
}
/** A required field the platform read cannot see (e.g. the landing URL), confirmed by eye. */
export interface LaunchUnreadable { key: string; label: string; confirmed: boolean }
/** F49 Contract B (decision 5): a field no reader can see, declared so -- approving the launch was its confirmation. */
export interface ApprovalConfirm { key: string; label: string }

export interface LaunchItem {
  /** The handoff item id once approved; the planned id on the `list` step. */
  id: string;
  kind: LaunchItemKind;
  name: string;
  parent_name: string | null;
  fields: LaunchField[];
  state: LaunchItemState;
  /** F49 Contract B: the one word for `state` (`app/ads/launch_view.py::STATE_LABELS`). Optional: absent from test literals. */
  state_label?: string;
  mismatches: LaunchMismatch[];
  unreadable: LaunchUnreadable[];
  /** F49 Contract B: the declared-unreadable fields of this item, confirmed by the approval (never asked again). */
  confirmed_at_approval?: ApprovalConfirm[];
  /** Why a readback left the item `built` (not found, ambiguous name) or `unknown`. */
  reason: string | null;
  /** F49 Contract B: the code of `reason` (`app/ads/handoff_check.py::READBACK_REASONS`); null without one. */
  reason_code?: string | null;
  /** F47-I06: when that reason was read (`app/ads/launch_view.py::_reason_at`); null without a reason. */
  reason_at: string | null;
}

/** F41-I03 (`change_control_launch.py::month_fit`): the list step's month-budget block. The money fields are the
 * `getMonthlyBudget` view of the month as it stands without this launch, plus `extra` (what this launch reserves)
 * and the backend's approval refusal, if any, judged with the launch and mirroring `month_budget.preflight` in its
 * order. `blocker_text` is printed verbatim; the browser never recomputes the rule. */
export interface LaunchMonthBudget extends MonthlyBudget {
  extra: number;
  /** F48 Contract M "month portion": what `extra` is made of — the launch's `days` inside month number `month` and
   * the campaign's whole-period total (`null` when the campaign has none). The card prints it as served. Absent from
   * an older backend (and from test literals): the card keeps its plain 「這期要花」. */
  extra_basis?: { month: number; days: number; period_total: number | null } | null;
  blocker: "unset" | "uncertain" | "short" | null;
  blocker_text: string | null;
}

export interface DeferredAd { ad_id: string; name: string; group_name: string }

export interface LaunchView {
  /** Effective settings and hash from one initialized approval snapshot. */
  content_hash?: string;
  launch_settings?: LaunchSettingsValues;
  step: LaunchStep;
  version: number | null;
  approved_at: string | null;
  summary: LaunchSummary;
  items: LaunchItem[];
  deferred_ads: DeferredAd[];
  read_at: string | null;
  settings_readback: SettingsReadback | null;
  /** Null on approved steps; absent from an older backend (and from test literals). Either way: no card, no blocker. */
  month_budget?: LaunchMonthBudget | null;
  /** F49 Contract B (decision 5): what approving this launch confirms -- printed on the approval screen before 核准. */
  approval_confirms?: ApprovalConfirm[];
}

const launchPath = (brandId: string, campaignId: string) =>
  `${BASE}/brands/${encodeURIComponent(brandId)}/campaigns/${encodeURIComponent(campaignId)}/launch`;

async function launchRequest(url: string, method: string, fallback: string, body?: unknown): Promise<LaunchView> {
  const res = await apiFetch(url, body === undefined ? { method } : {
    method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  return readJson<LaunchView>(res, fallback);
}

export const fetchLaunchView = (brandId: string, campaignId: string) =>
  launchRequest(launchPath(brandId, campaignId), "GET", "讀取上架清單失敗。");

/** Reads back every built item of the batch at once; answers with the refreshed view. */
export const readbackLaunch = (brandId: string, campaignId: string) =>
  launchRequest(`${launchPath(brandId, campaignId)}/readback`, "POST", "讀回核對失敗，請稍後再試。");

export const unreportLaunchItem = (brandId: string, campaignId: string, itemId: string) =>
  launchRequest(`${launchPath(brandId, campaignId)}/items/${encodeURIComponent(itemId)}/unreport`,
    "POST", "取消回報失敗，請稍後再試。");

export const confirmLaunchItemField = (brandId: string, campaignId: string, itemId: string, key: string) =>
  launchRequest(`${launchPath(brandId, campaignId)}/items/${encodeURIComponent(itemId)}/confirm`,
    "POST", "確認失敗，請稍後再試。", { key });

/** Drill-7 #18: the user looked at the platform once and says every setting and item field the readback still
 * reports as unreadable is the same (`POST …/handoff/launch/confirm-all`, one request instead of one per field).
 * Answers with the refreshed launch view; readable, confirmed and differing fields are left alone, and nothing
 * is written to a platform. */
export async function confirmAllLaunchFields(brandId: string, campaignId: string): Promise<LaunchView> {
  const url = `${BASE}/brands/${encodeURIComponent(brandId)}/campaigns/${encodeURIComponent(campaignId)}/handoff/launch/confirm-all`;
  const res = await apiFetch(url, { method: "POST" });
  const data = await readJson<{ confirmed_items: number; confirmed_settings: number; view: LaunchView }>(res, "全部標記失敗，請再按一次。");
  return data.view;
}
