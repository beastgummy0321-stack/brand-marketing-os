import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** shadcn/ui 慣用的 class 合併 helper：後續票加 shadcn 元件時直接複用。 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** 高頻點擊（矩陣格點擊、複製鈕等）只值輕量按壓回饋：`:active { scale(0.97) }`，150ms
 * ease-out（redesign-preserve 動效鐵則）。`:not(:focus-visible)` 把鍵盤觸發排除在外
 * （鍵盤動作零動畫）；`motion-reduce:duration-0` 讓偏好減少動態的使用者退化成瞬間顯示。
 * 原本只在 MatrixCell.tsx 內定義（票 16），票 17 側板共用元件（複製鈕、退件圖示、主題卡
 * 點擊）也要用同一套回饋，抽出來共用，不重寫一份。 */
export const PRESS_FEEDBACK =
  "transition-transform duration-150 ease-out motion-reduce:duration-0" +
  " [&:active:not(:focus-visible)]:scale-[0.97]";
