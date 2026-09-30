/** frontend/src/lib/adsCampaignTypes.ts — F40-I12: the campaign create／context shapes shared by
 * `adsApi.ts` (the campaign payloads), `adsWizardApi.ts` (the structured create) and the two wizard
 * pages. Type-only; split out of `adsApi.ts` for its 800-line cap. Mirrors `app/ads/brief.py`
 * (`_check_extras`, `_copy_from_previous`, `set_landing_url`) and `app/ads/routes.py`
 * (`CreateCampaignRequest`). */

/** F04-I11：`context_json.field_sources` 的六格——`"user"`＝你說的，`"system"`＝行銷駕駛艙
 * 沒聽到就幫你補的（ARCHITECTURE.md §6.1 第 11 條）。F40-I04：`"copied"`＝建立時沒填、從上一期
 * （最新一個非草稿活動）複製來的。 */
export type FieldSource = "user" | "system" | "copied";

export interface CampaignFieldSources {
  product: FieldSource;
  objective: FieldSource;
  platform: FieldSource;
  budget: FieldSource;
  dates: FieldSource;
  audience: FieldSource;
  /** F40-I04：上限（`target_cost`）與活動層落地頁；舊活動沒有這兩格。 */
  cap?: FieldSource;
  landing_url?: FieldSource;
}

/** F40-I04：建立活動時可先說的四個值（`POST /campaigns` 兩條路徑都收）；沒帶的由後端從上一期複製
 * （`app/ads/brief.py::_copy_from_previous`），所以畫面清空的格子不用送 `null`，省略即可。 */
export interface CampaignCreateExtras {
  /** 通路 key（`channels.py`），例如 `meta`。 */
  platform?: string;
  audience_hint?: string;
  /** 每賣一筆上限，> 0；存成 `target_cost`（`target_basis='own'`）。 */
  cap?: number;
  /** 完整 http／https 網址，存在 `context_json.landing_url`。 */
  landing_url?: string;
}

/** `CampaignDetail.context_json` 裡畫面會讀的鍵（其餘仍是 `unknown`）。F40-I04：`copied_from` 是建立時
 * 從上一期複製的來源與欄位（沒有上一期就沒有這個鍵）；`landing_url` 是活動層的落地頁。 */
export interface CampaignContextJson extends Record<string, unknown> {
  product_ids?: string[];
  audience_hint?: string | null;
  landing_url?: string | null;
  copied_from?: CampaignCopiedFrom;
  field_sources?: Partial<CampaignFieldSources>;
}

/** F40-I04：`context_json.copied_from`——上一期活動與從它複製來的欄位名（`_COPIED_KEYS` 的子集）。 */
export interface CampaignCopiedFrom {
  campaign_id: string;
  name: string;
  fields: string[];
}
