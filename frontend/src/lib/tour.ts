import { driver } from "driver.js";
import "driver.js/dist/driver.css";

/** 首次進駕駛艙的 30 秒重點導覽（票 09-empty-states-tour，規格使用者故事 20）：
 * KPI 卡、下一步指南卡、異常警示區三站。localStorage 記一次，之後不再自動打擾；
 * 使用者可從 CockpitPage 頁首「重新導覽」手動重看（呼叫 runCockpitTour 不會再檢查
 * hasSeenCockpitTour）。步驟依附在對應區塊的 data-tour 屬性上（見 CockpitPage.tsx、
 * GuideCards.tsx、AlertsPanel.tsx）。 */

const SEEN_KEY = "cockpit_tour_seen";

export function hasSeenCockpitTour(): boolean {
  return localStorage.getItem(SEEN_KEY) === "1";
}

export function runCockpitTour(): void {
  localStorage.setItem(SEEN_KEY, "1");
  driver({
    showProgress: true,
    skipMissingElement: true,
    nextBtnText: "下一步",
    prevBtnText: "上一步",
    doneBtnText: "完成",
    steps: [
      {
        element: '[data-tour="kpis"]',
        popover: {
          title: "四張 KPI 卡",
          description: "本月營收、廣告花費、ROAS、訂單數，各帶迷你趨勢線與環比，十秒判斷這個品牌好不好。",
        },
      },
      {
        element: '[data-tour="guide-cards"]',
        popover: {
          title: "下一步指南卡",
          description: "系統主動列出現在最該做的 1–3 件事，一鍵前往處理；沒事就顯示「一切正常」。",
        },
      },
      {
        element: '[data-tour="alerts"]',
        popover: {
          title: "異常警示區",
          description: "按嚴重度分色的警報，先處理會流失錢的事。",
        },
      },
    ],
  }).drive();
}
