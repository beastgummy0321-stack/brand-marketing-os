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
}

export const NAV_TOP: NavItem[] = [
  { label: "跨品牌總覽", href: "/app/", status: "active" },
  { label: "收件匣", href: "/inbox", status: "active" },
];

/** 品牌相關模組要有品牌 context 才可點：已進駕駛艙（網址帶 ?brand=）就亮起並連到
 * 該品牌的舊功能頁（code review 2026-08-06：之前寫死永遠灰掉，選了品牌仍顯示
 * 「請先選品牌」是錯的，票 01 驗收「連到每個既有模組」實質沒達成）。 */
export function navModules(brandId: string | null): NavItem[] {
  return [
    brandId
      ? { label: "品牌智庫", href: `/brands/${brandId}/hub`, status: "active" }
      : { label: "品牌智庫", status: "disabled", reason: "請先在跨品牌總覽選擇品牌" },
    brandId
      ? { label: "投放與成效", href: `/brands/${brandId}/ads`, status: "active" }
      : { label: "投放與成效", status: "disabled", reason: "請先在跨品牌總覽選擇品牌" },
    { label: "內容與曝光", status: "disabled", reason: "即將推出" },
    { label: "顧客與口碑", status: "disabled", reason: "即將推出" },
  ];
}

export const NAV_FOOTER: NavItem[] = [
  { label: "設定", href: "/settings", status: "active" },
];
