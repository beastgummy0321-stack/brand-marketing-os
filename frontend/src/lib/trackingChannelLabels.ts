/** 五路追蹤通路（`TrackingChannelKey`）的白話標籤——`TrackingHealthPage.tsx`（配圖示）與
 * `proposalFieldFormat.ts`（提案書追蹤健檢區塊的列舉值翻譯）共用同一份，不各自抄一份
 * （見票 F4：兩處原本各寫一套，容易漏改成不一致）。
 *
 * 注意：`ProposalBook.tsx` 的 `CHANNEL_LABELS` 是另一套完全不同的列舉（social／
 * google_search／line_email／kol_media／website_landing，管道分工用），不是這裡的五路
 * 追蹤通路，兩者不能合併。
 */
import type { TrackingChannelKey } from "./trackingApi.ts";

export const TRACKING_CHANNEL_LABELS: Record<TrackingChannelKey, string> = {
  website: "官方網站",
  fb_page: "Facebook 粉專",
  ig_account: "Instagram",
  shopee: "蝦皮",
  pharmacy: "藥局現場",
};
