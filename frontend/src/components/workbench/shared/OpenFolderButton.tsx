import { useState } from "react";
import { FolderOpen } from "lucide-react";
import { cn, PRESS_FEEDBACK } from "@/lib/utils";

/** 開資料夾按鈕四態（idle／opening／opened／failed）：伺服器端 `os.startfile` 開資料夾，
 * 成功不等於「複製成功」，所以不套 CopyIconButton 那套語意，是另一顆小狀態機。
 *
 * 原本就近寫在 ThemePanel.tsx 裡（票 17 當時只有「開主題資料夾」一個呼叫端）；票 W3 矩陣頁
 * 頂部「開這期檔期的資料夾」成為第二個真實呼叫端，才抽到這裡共用。兩個呼叫端唯一的差別是
 * 按下去打哪支端點，由 `onOpen` 傳進來——按鈕本身不認得 brandId／cycleId／themeId。 */
export function OpenFolderButton({ onOpen }: { onOpen: () => Promise<unknown> }) {
  const [state, setState] = useState<"idle" | "opening" | "opened" | "failed">("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleClick() {
    setState("opening");
    setErrorMessage(null);
    try {
      await onOpen();
      setState("opened");
    } catch (err) {
      setState("failed");
      setErrorMessage(err instanceof Error ? err.message : "開資料夾失敗，請稍後再試。");
    }
  }

  return (
    <span className="inline-flex flex-col items-start gap-1">
      <button
        type="button"
        onClick={handleClick}
        disabled={state === "opening"}
        title={state === "failed" ? (errorMessage ?? "開資料夾") : "開資料夾"}
        className={cn(
          "inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md border border-border px-2 py-1 text-xs font-medium transition-colors hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-60",
          state === "failed" ? "text-danger" : "text-muted-foreground",
          PRESS_FEEDBACK,
        )}
      >
        <FolderOpen className="h-3.5 w-3.5" aria-hidden="true" />
        {state === "opened" ? "已開啟" : state === "opening" ? "開啟中…" : "開資料夾"}
      </button>
      {state === "failed" && errorMessage && (
        <span className="text-xs text-danger">{errorMessage}</span>
      )}
    </span>
  );
}
