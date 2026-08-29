/** 側邊導覽資料（票 01-react-shell，票 02 更新「跨品牌總覽」連結）。
 *
 * 舊介面的側欄骨架已有原型（app/templates/_layouts/console.html，尚未套用到任何路由），
 * 這裡沿用同一份分類：收件匣／品牌智庫／投放與成效／內容與曝光／顧客與口碑／設定。
 *
 * 品牌智庫、投放與成效兩項要選定品牌才有意義，新殼還沒有單品牌駕駛艙（票 03 才做），
 * 所以先灰掉並說明原因，不做成看起來能點但沒反應的假連結（規格使用者故事 23）。
 */

export type NavStatus = "active" | "disabled";

export interface NavItem {
  label: string;
  /** active 才有 href；disabled 項目只顯示原因，不可點。 */
  href?: string;
  status: NavStatus;
  /** disabled 項目要說明原因（規格使用者故事 23：灰掉要附說明，不能沒反應）。 */
  reason?: string;
  /** href 是不是 SPA 內部路徑（票 05-spa-routing）：true 用 react-router 的 `Link`
   * 導航（相對 basename `/app`）；預設 false（一般 `<a>`），離開 SPA 去舊版 Jinja 頁面
   * ——過渡期本來就是獨立頁面，見票 01 驗收條件。 */
  internal?: boolean;
}

export const NAV_TOP: NavItem[] = [
  { label: "跨品牌總覽", href: "/", status: "active", internal: true },
  { label: "收件匣", href: "/inbox", status: "active", internal: true },
];

/** 品牌相關模組要有品牌 context 才可點：已進駕駛艙（網址是 `/brands/:brandId`，
 * 票 05-spa-routing 起改路徑式）就亮起並連到該品牌的舊功能頁（code review
 * 2026-08-06：之前寫死永遠灰掉，選了品牌仍顯示「請先選品牌」是錯的，票 01
 * 驗收「連到每個既有模組」實質沒達成）。 */
export function navModules(brandId: string | null): NavItem[] {
  return [
    brandId
      ? {
          label: "品牌智庫",
          href: `/brands/${brandId}/library`,
          status: "active",
          internal: true,
        }
      : { label: "品牌智庫", status: "disabled", reason: "請先在跨品牌總覽選擇品牌" },
    brandId
      ? {
          label: "產品",
          href: `/brands/${brandId}/products`,
          status: "active",
          internal: true,
        }
      : { label: "產品", status: "disabled", reason: "請先在跨品牌總覽選擇品牌" },
    brandId
      ? {
          label: "顧問分析報告",
          href: `/brands/${brandId}/report`,
          status: "active",
          internal: true,
        }
      : { label: "顧問分析報告", status: "disabled", reason: "請先在跨品牌總覽選擇品牌" },
    brandId
      ? {
          label: "檔期",
          href: `/brands/${brandId}/schedule`,
          status: "active",
          internal: true,
        }
      : { label: "檔期", status: "disabled", reason: "請先在跨品牌總覽選擇品牌" },
    brandId
      ? {
          label: "投放與成效",
          href: `/brands/${brandId}/campaigns`,
          status: "active",
          internal: true,
        }
      : { label: "投放與成效", status: "disabled", reason: "請先在跨品牌總覽選擇品牌" },
    brandId
      ? {
          label: "累積智慧",
          href: `/brands/${brandId}/learnings`,
          status: "active",
          internal: true,
        }
      : { label: "累積智慧", status: "disabled", reason: "請先在跨品牌總覽選擇品牌" },
    brandId
      ? {
          label: "素材工作檯",
          href: `/brands/${brandId}/workbench`,
          status: "active",
          internal: true,
        }
      : { label: "素材工作檯", status: "disabled", reason: "請先在跨品牌總覽選擇品牌" },
    brandId
      ? {
          label: "訂單與顧客",
          href: `/brands/${brandId}/orders`,
          status: "active",
          internal: true,
        }
      : { label: "訂單與顧客", status: "disabled", reason: "請先在跨品牌總覽選擇品牌" },
    brandId
      ? {
          label: "資料上線",
          href: `/brands/${brandId}/data-onboarding`,
          status: "active",
          internal: true,
        }
      : { label: "資料上線", status: "disabled", reason: "請先在跨品牌總覽選擇品牌" },
    { label: "內容與曝光", status: "disabled", reason: "即將推出" },
    { label: "顧客與口碑", status: "disabled", reason: "即將推出" },
  ];
}

export const NAV_FOOTER: NavItem[] = [
  { label: "設定", href: "/settings", status: "active", internal: true },
];
