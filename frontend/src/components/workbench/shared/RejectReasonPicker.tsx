import { useEffect, useRef, useState } from "react";
import { ThumbsDown } from "lucide-react";
import { cn, PRESS_FEEDBACK } from "@/lib/utils";
import { REJECT_REASONS } from "@/lib/workbenchApi";

/** 退件理由選單（票 17 共用元件之一，跨畫面 3／4／5 側板重用）：點圖示彈出理由清單，選一項
 * 就送出。理由碼固定沿用 `REJECT_REASONS`（照抄後端常數，見 workbenchApi.ts 註解），不接受
 * 自由輸入、不自造清單。點外面或選完就收合，失敗顯示錯誤但不收合（讓使用者能重試）。 */
export function RejectReasonPicker({
  onReject,
}: {
  /** 選好理由後呼叫；成功要 resolve，失敗要 reject 帶錯誤訊息（選單會顯示、留著讓使用者
   * 重選，不是靜默失敗）。 */
  onReject: (reasonCode: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handlePointerDown(event: PointerEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [open]);

  async function handlePick(reasonCode: string) {
    setSubmitting(true);
    setErrorMessage(null);
    try {
      await onReject(reasonCode);
      setOpen(false);
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "退件失敗，請稍後再試。");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="退這則，選理由"
        title="退這則"
        className={cn(
          "inline-flex shrink-0 items-center justify-center rounded-md border border-border p-1.5 text-muted-foreground transition-colors hover:border-danger hover:text-danger",
          PRESS_FEEDBACK,
        )}
      >
        <ThumbsDown className="h-3.5 w-3.5" aria-hidden="true" />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full z-10 mt-1 w-56 rounded-md border border-border bg-card p-1 shadow-[var(--shadow-card)]"
        >
          {REJECT_REASONS.map(([code, label]) => (
            <button
              key={code}
              type="button"
              role="menuitem"
              disabled={submitting}
              onClick={() => handlePick(code)}
              className="block w-full rounded px-2 py-1.5 text-left text-sm text-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
            >
              {label}
            </button>
          ))}
          {errorMessage && <p className="px-2 py-1 text-xs text-danger">{errorMessage}</p>}
        </div>
      )}
    </div>
  );
}
