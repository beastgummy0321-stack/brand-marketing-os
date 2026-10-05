import { Button } from "@/components/layout/ui/button";
/** 側板送出按鈕（票 B2-products）：跟 `components/library/shared/PanelSaveButton.tsx`
 * 樣式相同，獨立一份（模組化規則，見 `shared/Badge.tsx` 註解）。 */
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
    <Button variant="outline" size="sm"
      type="submit"
      busy={saving}
      className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
    >
      {saving ? pendingLabel : label}
    </Button>
  );
}
