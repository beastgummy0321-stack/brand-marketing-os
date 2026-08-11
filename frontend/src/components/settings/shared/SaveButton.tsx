/** 送出按鈕（票 B1-settings）：送出中鎖住＋文字換成人話進度（五鐵則④）。可逆動作（儲存）
 * 用「儲存中…」，不可逆動作（清除金鑰、重設規則卡）呼叫端傳 `pendingLabel="處理中…"`。 */
export function SaveButton({
  saving,
  label,
  pendingLabel = "儲存中…",
  variant = "primary",
}: {
  saving: boolean;
  label: string;
  pendingLabel?: string;
  variant?: "primary" | "secondary";
}) {
  return (
    <button
      type="submit"
      disabled={saving}
      className={
        variant === "primary"
          ? "rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          : "rounded-md border border-border px-4 py-2 text-sm font-medium text-foreground hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
      }
    >
      {saving ? pendingLabel : label}
    </button>
  );
}
