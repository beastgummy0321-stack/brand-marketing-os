import { useEffect, useState } from "react";
import { SidePanel } from "@/components/layout/SidePanel";
import { cycleLabel, deleteCampaign, fetchDeleteImpact, type CampaignDeleteImpact } from "@/lib/campaignsApi";
import { useFormSubmit } from "@/lib/useFormSubmit";

/** 永久刪除檔期側板（契約 S8.67-71）：跟 `components/campaigns/panels/CampaignDeletePanel.tsx`
 * 是同一套邏輯的獨立一份——本專案模組化規則「跨 feature 只准 import components/layout/ 與
 * lib/」，campaigns／warroom 是兩個獨立頂層 feature 資料夾，JSX 各自留一份（同 Badge.tsx
 * 檔頭已有的既定作法），API 呼叫仍共用 `lib/campaignsApi.ts` 同一份函式，邏輯不重複。
 * 契約 S8.71：舊版整頁改成同畫面內確認對話框——`SidePanel` 本來就是滑出層不是整頁跳轉，
 * 沿用即可，逐字欄位與流程不改。 */
export function CycleDeletePanel({
  brandId,
  cycle,
  onClose,
  onDeleted,
}: {
  brandId: string;
  cycle: { id: string; start_date: string; end_date: string };
  onClose: () => void;
  onDeleted: () => void;
}) {
  const label = cycleLabel(cycle);
  const [impact, setImpact] = useState<CampaignDeleteImpact[] | null>(null);
  const [impactError, setImpactError] = useState<string | null>(null);
  const [confirmName, setConfirmName] = useState("");

  useEffect(() => {
    fetchDeleteImpact(brandId, cycle.id)
      .then(setImpact)
      .catch((err: unknown) => setImpactError(err instanceof Error ? err.message : "讀取失敗，請稍後再試。"));
  }, [brandId, cycle.id]);

  const form = useFormSubmit(async () => {
    await deleteCampaign(brandId, cycle.id, confirmName);
    onDeleted();
  });

  return (
    <SidePanel ariaLabel={`永久刪除檔期「${label}」`} onClose={onClose}>
      <div className="border-b border-border pb-4">
        <h2 className="font-display text-lg text-foreground">永久刪除檔期「{label}」</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          這個動作不能復原。刪掉之後，這期檔期與底下所有資料都會從系統消失，只在稽核紀錄留下一筆「誰在什麼時候刪了什麼」。
        </p>
      </div>

      <div className="rounded-md border border-danger/40 bg-danger/5 p-3 text-sm">
        <p className="font-medium text-foreground">會一起消失的資料：</p>
        {impactError ? (
          <p className="mt-1 text-danger">{impactError}</p>
        ) : impact === null ? (
          <p className="mt-1 text-muted-foreground">讀取中…</p>
        ) : impact.length === 0 ? (
          <p className="mt-1 text-muted-foreground">這期檔期底下目前沒有任何資料。</p>
        ) : (
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-muted-foreground">
            {impact.map((row) => (
              <li key={row.label}>
                {row.label} {row.count} 筆
              </li>
            ))}
          </ul>
        )}
        <p className="mt-2 text-xs text-muted-foreground">
          系統會在刪除前自動把整個資料庫備份一份到 backups 資料夾，萬一刪錯還救得回來。
        </p>
      </div>

      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          void form.submit();
        }}
      >
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">請輸入起訖日期以確認</span>
          <input
            type="text"
            value={confirmName}
            onChange={(e) => setConfirmName(e.target.value)}
            autoComplete="off"
            placeholder={label}
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
          <span className="text-xs text-muted-foreground">要刪除的檔期是「{label}」，請一字不差地打一次。</span>
        </label>

        {form.error && <p className="text-sm text-danger">{form.error}</p>}
        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={form.saving}
            className="rounded-md bg-danger px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {form.saving ? "刪除中…" : "永久刪除這期檔期"}
          </button>
          <button type="button" onClick={onClose} disabled={form.saving} className="text-sm text-muted-foreground hover:underline">
            取消
          </button>
        </div>
      </form>
    </SidePanel>
  );
}
