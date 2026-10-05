import { useEffect, useState } from "react";
import { Check, Copy, TriangleAlert } from "lucide-react";
import { cn, PRESS_FEEDBACK } from "@/lib/utils";
import { Button } from "./ui/button";

type CopyState = "idle" | "copying" | "copied" | "failed";

/** How long 「已複製」 stays on the button after a successful copy (F47 Contract B). */
export const COPIED_FEEDBACK_MS = 2000;

/** F51 Contract D: why a copy button with nothing to copy is greyed out. */
export const NOTHING_TO_COPY = "沒有可複製的內容";

/** 複製按鈕（票 17 共用元件之一；F47-I02 起與 `ads/patterns/CopyField` 是全站唯二呼叫
 * `navigator.clipboard` 的地方，`lib/feedbackGuards.test.ts` 擋第三處）。
 * `getText()` 先把要複製的內容準備好（可以是要打 API 才拿得到的內容），拿到內容才呼叫
 * `navigator.clipboard.writeText()`；await resolve 後按鈕上的字換成看得見的「已複製」2 秒，
 * reject 則在按鈕下方留一句「請手動選取複製」——不樂觀更新（規範鐵則），也不在沒有權限時
 * 假裝成功。`onResult(copied)` 讓呼叫端在嘗試後做自己的事（例如把清單那一項打勾）。
 *
 * F51 Contract S (drill-11 c1-10): while `getText()`／`writeText()` is pending the button reads 「複製中…」 and is
 * busy — an icon-only button used to show nothing at all until the clipboard answered, so a slow or stuck clipboard
 * looked like a dead button. F51 Contract D: `disabled` means "nothing to copy" and prints 「沒有可複製的內容」. */
export function CopyIconButton({
  getText,
  label,
  ariaLabel,
  className,
  disabled,
  onResult,
}: {
  getText: () => string | Promise<string>;
  /** 有文字的按鈕（例如「整組複製」）才傳；純圖示按鈕不傳，靠 ariaLabel 讓螢幕閱讀器讀得到。 */
  label?: string;
  ariaLabel: string;
  className?: string;
  /** Nothing to copy yet: the button is greyed out and says 「沒有可複製的內容」. */
  disabled?: boolean;
  /** Called once per attempt that got its text: `true` after the clipboard accepted it. */
  onResult?: (copied: boolean) => void;
}) {
  const [state, setState] = useState<CopyState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (state !== "copied") return;
    const timer = setTimeout(() => setState("idle"), COPIED_FEEDBACK_MS);
    return () => clearTimeout(timer);
  }, [state]);

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
      if (!navigator.clipboard) throw new Error("no clipboard");
      await navigator.clipboard.writeText(text);
      setState("copied");
      onResult?.(true);
    } catch {
      setState("failed");
      setErrorMessage("請手動選取複製");
      onResult?.(false);
    }
  }

  const Icon = state === "copied" ? Check : state === "failed" ? TriangleAlert : Copy;
  // 圖示才隨狀態換色（純圖示只需 WCAG 3:1，text-success/danger 都過）；文字標籤永遠用
  // text-muted-foreground，不隨狀態變色——狀態成功／失敗已由圖示表達，label 若也套
  // text-success 在白底卡片上量出來只有 3.30:1，不到一般文字要求的 4.5:1（票 20 findings）。
  const iconColor =
    state === "copied" ? "text-success" : state === "failed" ? "text-danger" : "text-muted-foreground";
  const text = state === "copied" ? "已複製" : state === "copying" ? "複製中…" : label;

  return (
    <span className="inline-flex flex-col items-start gap-1">
      <Button
        type="button"
        variant="outline"
        size="xs"
        onClick={handleClick}
        busy={state === "copying"}
        disabledReason={disabled ? NOTHING_TO_COPY : null}
        aria-label={ariaLabel}
        title={state === "failed" ? (errorMessage ?? ariaLabel) : ariaLabel}
        className={cn(
          "h-auto gap-1.5 whitespace-nowrap px-2 py-1 text-xs font-medium text-muted-foreground has-[>svg]:px-2 hover:border-primary hover:bg-card hover:text-primary aria-busy:opacity-100",
          PRESS_FEEDBACK,
          className,
        )}
      >
        <Icon className={cn("size-3.5", iconColor)} aria-hidden="true" />
        <span aria-live="polite" className="empty:hidden">{text ?? ""}</span>
      </Button>
      {state === "failed" && errorMessage && (
        <span role="status" className="text-xs text-danger">{errorMessage}</span>
      )}
    </span>
  );
}
