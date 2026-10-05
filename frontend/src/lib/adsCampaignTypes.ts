/** frontend/src/lib/adsCampaignTypes.ts — F40-I12: the campaign create／context shapes shared by
 * `adsApi.ts` (the campaign payloads), `adsWizardApi.ts` (the structured create) and the two wizard
 * pages. Type-only; split out of `adsApi.ts` for its 800-line cap. Shapes served by `app/ads/brief.py`
 * (`_check_extras`, `_copy_from_previous`, `set_landing_url`) and `app/ads/routes.py`
 * (`CreateCampaignRequest`). */

/** F04-I11：`context_json.field_sources` 的六格——`"user"`＝你說的，`"system"`＝行銷駕駛艙
 * 沒聽到就幫你補的（ARCHITECTURE.md §6.1 第 11 條）。F40-I04：`"copied"`＝建立時沒填、從上一期
 * （最新一個非草稿活動）複製來的（F43-I04 起新活動不再複製，舊活動仍讀得到）。F43-I04：`"sell_way"`＝
從選的賣法（與它的商品）帶入的（受眾、上限、落地頁）。F46-I08：`"copied"` 回來了——結構化建立時平台、上限、
 * 預算從同一個賣法的上一期帶入（`app/ads/brief.py`）；`"brand"`＝品牌已接上的第一個帳戶（平台）；
 * `"break_even"`＝賣法的打平線，存成這個活動自己的上限。 */
/** F50 Contract I: `parsed` = the model read it from the 一句話 sentence (shown like `system`: 猜的，請確認). */
export type FieldSource = "user" | "system" | "parsed" | "copied" | "sell_way" | "brand" | "break_even";

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

/** F40-I04：建立活動時可先說的四個值（`POST /campaigns` 兩條路徑都收）。F43-I04：結構化路徑沒帶的由後端從
 * 品牌與選的賣法帶入（`app/ads/brief.py::_sell_way_defaults`），所以畫面沒改的格子不用送，省略即可。 */
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
  /** F43-I04：這期投的顧客群（賣法的商品的 `product_customer_group` id）；建立時預設全部群。舊活動沒有這個鍵。 */
  customer_group_ids?: string[];
  copied_from?: CampaignCopiedFrom;
  field_sources?: Partial<CampaignFieldSources>;
}

/** F40-I04：`context_json.copied_from`——上一期活動與從它複製來的欄位名（`_COPIED_KEYS` 的子集）。 */
export interface CampaignCopiedFrom {
  campaign_id: string;
  name: string;
  fields: string[];
}
