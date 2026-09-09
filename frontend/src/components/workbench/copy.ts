/** 素材工作檯固定文案（票 workbench/04，design-system §8：介面文字是固定詞彙，不生成、
 * 不落地）。
 *
 * 三個長度「什麼時候用」一句話與長度標籤不在這裡重寫一份：`workbenchApi.ts`（票 03）已經
 * 匯出 `LENGTH_HINTS`／`LENGTH_LABELS`，那支檔案的開頭註解明講這兩個常數就是留給工作檯
 * （這裡）跟排程（票 05）各自 import 一份、不是各自寫死一份同樣的字——重新宣告一次會製造
 * 兩個要一起改的地方，違背它原本的設計。這裡只 re-export，讓「票面說的 `copy.ts`」跟
 * 「已經存在、要重用的常數」兩件事同時成立。 */
export { LENGTH_HINTS, LENGTH_LABELS } from "@/lib/workbenchApi";

/** 工單種類 → 中文標籤（票面 §3：「文案／圖片提示詞／影片腳本／自由生成／排程節點」）。 */
export const KIND_LABELS: Record<string, string> = {
  copy: "文案",
  image_prompt: "圖片提示詞",
  video_script: "影片腳本",
  free: "自由生成",
  ad_creative: "排程節點",
};

/** 狀態 Badge 文字（design-system §8 固定詞彙）。`idle`：`status='done'` 但沒有任何
 * 產出的 brief——沒有 part 要跑（票 04 amendment 第 2 點；repository.py `submit_brief()`
 * 現在會直接把它建成 done，不是排隊等一個永遠不會出現的 job）。 */
export const STATUS_LABELS = {
  processing: "處理中",
  done: "完成",
  failed: "失敗",
  closed: "已關閉",
  idle: "待產出",
} as const;

/** 按鈕文字（票面 §8 逐字列出的清單）。 */
export const BUTTON_LABELS = {
  newBrief: "新工單",
  createBrief: "建立工單",
  runImagePrompt: "產提示詞",
  runAgain: "再產一輪",
  adopt: "採用這一輪",
  copyAll: "全部複製",
  close: "關閉",
  reopen: "重新開啟",
  delete: "刪除",
  retry: "重新產出",
  toSchedule: "到檔期規劃",
} as const;

/** ADR 0068 §7 使用者原話，逐字。 */
export const IMAGE_PROMPT_ADVISORY = "AI 生圖有不確定性，建議多產幾條備用，建議目標張數的 1.5 倍";
