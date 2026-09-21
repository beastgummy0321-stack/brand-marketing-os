import type { CampaignStatus } from "@/lib/adsApi";

/** F19-I02：從 `AdsHomePage.tsx` 抽出，讓 `home/CampaignCards.tsx` 跟 `AdsHomePage.tsx` 都能讀，
 * 不必互相 import 造成循環依賴。`AdsHomePage.tsx` 原樣 re-export，`AllCampaignsPage.tsx`
 * （do_not_touch 外但這次沒有理由改）沿用同一個 import 路徑不受影響。 */
export const STATUS_LABEL: Record<CampaignStatus, string> = {
  draft: "草稿",
  ready: "待發布",
  live: "投放中",
  ended: "已結束",
  closed: "已結案",
};

export const STATUS_TONE: Record<CampaignStatus, "secondary" | "default" | "outline"> = {
  draft: "secondary",
  ready: "outline",
  live: "default",
  ended: "outline",
  closed: "secondary",
};
