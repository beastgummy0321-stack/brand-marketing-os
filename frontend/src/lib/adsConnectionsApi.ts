/** frontend/src/lib/adsConnectionsApi.ts — F30-I14 (Feature F30 Contract H): the connections
 * page's one read. Mirrors `app/ads/connections.py::get_connections` exactly; the read never
 * requests a sync.
 *
 * Rules the screen can rely on (never re-derive them here):
 * - Sources come in screen order: one `ad_account` row per bound account per platform (never a
 *   min across accounts), then `orders`, then `product_costs`, then one `platform` row per
 *   platform without a reader (`unsupported`, listed last). A platform with a reader but no bound
 *   account is one `platform` row in state `never`.
 * - An account day is `ok` by pull coverage, not by spend rows: a day read with no spend is `ok`.
 *   A day only counts once it was over when the read finished (account timezone), and days an
 *   earlier read proved stay `ok` while a new read runs or after it fails.
 *   An account never read at all is `never` (never `ok`, note 「還沒讀取過」) and every past day
 *   is `missing`.
 * - `auth_expired` / `failed` win over gaps; `missing_days` lists the unread complete days (up to
 *   yesterday) of this month or of the last 28 days, whichever starts earlier.
 * - `note` is server-written text, shown as is. `action` is `null` when there is nothing for the
 *   user to do on another page.
 * - `attention_count` counts every source whose state is not `ok` or `unsupported`.
 * - Calendar dates are the organisation's own; `calendar.today` is today. Orders are `none` before
 *   the earliest order; a day not read yet today, and every later day, is `future`. */
import { apiFetch } from "./http";
import { BASE, parseJsonOrThrow } from "./adsApi";

export type ConnectionSourceKind = "ad_account" | "orders" | "product_costs" | "platform";

export type ConnectionSourceState =
  | "ok"
  | "auth_expired"
  | "failed"
  | "never"
  | "missing_days"
  | "missing_cost"
  | "unsupported";

export interface ConnectionAction { label: string; href: string }

export interface ConnectionSource {
  key: string;
  kind: ConnectionSourceKind;
  /** The channel key for `ad_account` / `platform` rows; null for orders and product costs. */
  platform: string | null;
  name: string;
  state: ConnectionSourceState;
  note: string;
  /** Accounts only: the newest clean read of the account or its campaigns. */
  last_success_at: string | null;
  /** ISO dates, oldest first. */
  missing_days: string[];
  /** Accounts only: open campaigns with unread days or a failing read. */
  affected_campaigns: { id: string; name: string }[];
  action: ConnectionAction | null;
}

export type CalendarDayState = "ok" | "missing" | "none" | "future";

export interface ConnectionCalendarRow {
  source_key: string;
  label: string;
  days: { date: string; state: CalendarDayState }[];
}

export interface ConnectionCalendar {
  /** `YYYY-MM`. */
  month: string;
  /** ISO date. */
  today: string;
  /** One row per bound account, then orders. */
  rows: ConnectionCalendarRow[];
}

export interface AdsConnections {
  attention_count: number;
  sources: ConnectionSource[];
  calendar: ConnectionCalendar;
}

export async function getConnections(brandId: string, signal?: AbortSignal): Promise<AdsConnections> {
  try {
    const response = await apiFetch(
      `${BASE}/brands/${encodeURIComponent(brandId)}/connections`, { signal },
    );
    return await parseJsonOrThrow<AdsConnections>(response, "讀取資料連線失敗。");
  } catch (error) {
    if (error instanceof TypeError) throw new Error("未收到伺服器回應，請重試。");
    throw error;
  }
}
