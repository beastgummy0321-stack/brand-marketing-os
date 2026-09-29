import type { ProductPart } from "@/lib/workbenchApi";

export const PART_LABEL: Record<ProductPart, string> = {
  copy: "文案",
  image_prompt: "圖片",
  video_script: "腳本",
};

export interface RegenerateLabelInput {
  /** The part whose button is being labelled. */
  part: ProductPart;
  /** `set.generation.status` is queued/running, or this panel's run request is in flight. */
  generating: boolean;
  /** This panel's own `runProduct` request has not returned yet. */
  ownRequestInFlight: boolean;
  /** The part this browser started in the round now running; `null` when unknown. */
  runningPart: ProductPart | null;
  /** `products[part].state` — 未生成／待選定／已選定. */
  productState: string;
  /** What the button says when nothing is running. */
  idleLabel: string;
}

/** F40-I11 (drill-7 #16): the regenerate button says why it is not clickable.
 * `set.generation.status` is one brief-level field shared by every part, so the payload
 * cannot say which part is running; the page passes the part this browser started.
 * - idle → `idleLabel`
 * - own part running → 「生成中…」
 * - another part known → 「正在生成〈part〉，完成後才能再生成」 (also as `title`/aria-label)
 * - starter unknown: an empty product keeps 「生成中…」 (the first round queues every required
 *   part, so its own job is in flight); a product that already has versions is not the one
 *   being filled and says 「另一個部分」. */
export function regenerateLabel(input: RegenerateLabelInput): { label: string; title?: string } {
  const { part, generating, ownRequestInFlight, runningPart, productState, idleLabel } = input;
  if (!generating) return { label: idleLabel };
  if (ownRequestInFlight || runningPart === part) return { label: "生成中…" };
  const other = runningPart ? PART_LABEL[runningPart] : productState === "未生成" ? null : "另一個部分";
  if (!other) return { label: "生成中…" };
  const sentence = `正在生成${other}，完成後才能再生成`;
  return { label: sentence, title: sentence };
}
