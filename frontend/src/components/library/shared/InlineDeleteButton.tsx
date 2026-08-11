import { useState } from "react";

/** 原地二次確認刪除鈕（票 B2-library，契約 S5.10 等）：舊版 Jinja 頁面用瀏覽器
 * `window.confirm`，新殼比照側板失敗態的原地展開慣例，改成點下去原地變成
 * 「這句提示／確定刪除／取消」，不彈瀏覽器對話框。六個分頁的刪除動作（事實、規則、宣稱、
 * 素材、渠道、顧客原話）共用同一顆。 */
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
    onDelete()
      .catch((err: unknown) => {
        setDeleting(false);
        setError(err instanceof Error ? err.message : "刪除失敗，請稍後再試。");
      });
  }

  return (
    <span className="inline-flex flex-wrap items-center gap-1.5 text-xs">
      <span className="text-muted-foreground">{confirmText}</span>
      <button
        type="button"
        disabled={deleting}
        onClick={handleConfirm}
        className="font-medium text-danger hover:underline disabled:cursor-not-allowed disabled:opacity-50"
      >
        {deleting ? "刪除中…" : "確定刪除"}
      </button>
      <button
        type="button"
        onClick={() => setConfirming(false)}
        disabled={deleting}
        className="text-muted-foreground hover:underline"
      >
        取消
      </button>
      {error && <span className="text-danger">{error}</span>}
    </span>
  );
}
