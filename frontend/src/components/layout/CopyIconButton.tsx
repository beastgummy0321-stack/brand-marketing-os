import { useState } from "react";
import { Check, Copy, TriangleAlert } from "lucide-react";
import { cn, PRESS_FEEDBACK } from "@/lib/utils";

type CopyState = "idle" | "copying" | "copied" | "failed";

/** 複製按鈕三態（票 17 共用元件之一）：外殼切片（2026-08-28）從
 * `components/workbench/shared/` 搬到 `components/layout/`——素材工作檯整個刪掉了，
 * 但這顆按鈕的最後一個呼叫端（`components/auth/OrgMenu.tsx` 的邀請連結）還在。
 * `getText()` 先把要複製的
 * 內容準備好（逐則複製直接回傳已在記憶體裡的內容；整組複製要先打 API 組內容，見
 * ThemePanel 的用法），拿到內容才呼叫 `navigator.clipboard.writeText()`，await resolve
 * 才顯示 ✓，reject 顯示錯誤態＋「請手動選取複製」提示——不樂觀更新（規範鐵則）。 */
export function CopyIconButton({
  getText,
  label,
  ariaLabel,
  className,
}: {
  getText: () => string | Promise<string>;
  /** 有文字的按鈕（例如「整組複製」）才傳；純圖示按鈕不傳，靠 ariaLabel 讓螢幕閱讀器讀得到。 */
  label?: string;
  ariaLabel: string;
  className?: string;
}) {
  const [state, setState] = useState<CopyState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleClick() {
    setState("copying");
    setErrorMessage(null);
    let text: string;
    try {
      text = await getText();
    } catch (err) {
      setState("failed");
      setErrorMessage(err instanceof Error ? err.message : "取得內容失敗，請稍後再試。");
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      setState("failed");
      setErrorMessage("請手動選取複製");
    }
  }

  const Icon = state === "copied" ? Check : state === "failed" ? TriangleAlert : Copy;
  // 圖示才隨狀態換色（純圖示只需 WCAG 3:1，text-success/danger 都過）；文字標籤永遠用
  // text-muted-foreground，不隨狀態變色——狀態成功／失敗已由圖示表達，label 若也套
  // text-success 在白底卡片上量出來只有 3.30:1，不到一般文字要求的 4.5:1（票 20 findings）。
  const iconColor =
    state === "copied" ? "text-success" : state === "failed" ? "text-danger" : "text-muted-foreground";

  return (
    <span className="inline-flex flex-col items-start gap-1">
      <button
        type="button"
        onClick={handleClick}
        aria-label={ariaLabel}
        title={state === "failed" ? (errorMessage ?? ariaLabel) : ariaLabel}
        className={cn(
          "inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md border border-border px-2 py-1 text-xs font-medium text-muted-foreground transition-colors hover:border-primary hover:text-primary",
          PRESS_FEEDBACK,
          className,
        )}
      >
        <Icon className={cn("h-3.5 w-3.5", iconColor)} aria-hidden="true" />
        {label && <span>{label}</span>}
      </button>
      {state === "failed" && errorMessage && (
        <span className="text-xs text-danger">{errorMessage}</span>
      )}
    </span>
  );
}
