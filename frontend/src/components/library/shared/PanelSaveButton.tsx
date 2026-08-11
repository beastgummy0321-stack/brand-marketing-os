/** 側板送出按鈕（票 B2-library）：送出中鎖住＋文字換成人話進度（五鐵則④），跟
 * `components/settings/shared/SaveButton.tsx` 樣式相同但那顆是 settings feature 內部件
 * （本專案模組化規則「跨 feature 只准 import components/layout/ 與 lib/」，不能跨 feature
 * import），品牌智庫的側板在自己的 shared/ 底下留一份同樣式的。 */
export function PanelSaveButton({
  saving,
  label,
  pendingLabel = "儲存中…",
}: {
  saving: boolean;
  label: string;
  pendingLabel?: string;
}) {
  return (
    <button
      type="submit"
      disabled={saving}
      className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
    >
      {saving ? pendingLabel : label}
    </button>
  );
}
