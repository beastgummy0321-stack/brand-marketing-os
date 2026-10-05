import { Button } from "@/components/layout/ui/button";
import { useState } from "react";

/** 原地二次確認刪除鈕（票 B2-products）：跟 `components/library/shared/InlineDeleteButton.tsx`
 * 邏輯相同，獨立一份（模組化規則，見 `shared/Badge.tsx` 註解）。 */
export function InlineDeleteButton({
  confirmText,
  onDelete,
}: {
  confirmText: string;
  onDelete: () => Promise<void>;
}) {
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!confirming) {
    return (
      <button
        type="button"
        onClick={() => setConfirming(true)}
        className="text-xs font-medium text-danger hover:underline"
      >
        刪除
      </button>
    );
  }

  function handleConfirm() {
    setDeleting(true);
    setError(null);
    onDelete().catch((err: unknown) => {
      setDeleting(false);
      setError(err instanceof Error ? err.message : "刪除失敗，請稍後再試。");
    });
  }

  return (
    <span className="inline-flex flex-wrap items-center gap-1.5 text-xs">
      <span className="text-muted-foreground">{confirmText}</span>
      <Button variant="outline" size="sm"
        type="button"
        busy={deleting}
        onClick={handleConfirm}
        className="font-medium text-danger hover:underline disabled:cursor-not-allowed disabled:opacity-50"
      >
        {deleting ? "刪除中…" : "確定刪除"}
      </Button>
      <Button variant="outline" size="sm"
        type="button"
        onClick={() => setConfirming(false)}
        busy={deleting}
        className="text-muted-foreground hover:underline"
      >
        取消
      </Button>
      {error && <span className="text-danger">{error}</span>}
    </span>
  );
}
