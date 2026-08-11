import { useState } from "react";
import type { SettingsData } from "@/lib/settingsApi";
import { saveGa4 } from "@/lib/settingsApi";
import { SectionCard } from "./shared/SectionCard";
import { SaveButton } from "./shared/SaveButton";
import { TestConnectionButton } from "./shared/TestConnectionButton";
import { useFormSubmit } from "./shared/useFormSubmit";

/** GA4 小節（S15.7–S15.12）。文案沿用既有 `app/templates/settings.html:59-93`。 */
export function Ga4Section({ data, onSaved }: { data: SettingsData; onSaved: () => void }) {
  const [propertyId, setPropertyId] = useState(data.ga4_property_id);
  const [json, setJson] = useState("");
  const { saving, error, submit } = useFormSubmit(async () => {
    await saveGa4(propertyId, json);
    setJson("");
    onSaved();
  });

  return (
    <SectionCard
      title="GA4（網站數據，唯讀）"
      description="連上之後，系統會自動抓回來源／媒介的工作階段、轉換與收益，不用手動查看 GA4 後台。"
    >
      {data.masked_ga4_key && (
        <p className="text-sm text-foreground">
          目前已設定服務帳戶金鑰：<span className="font-mono">{data.masked_ga4_key}</span>
        </p>
      )}
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">GA4 資源編號</span>
          <input
            type="text"
            value={propertyId}
            onChange={(e) => setPropertyId(e.target.value)}
            placeholder="例如 123456789"
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
          <span className="text-xs text-muted-foreground">
            在 GA4 後台「資源設定」可以看到，格式是一串數字。
          </span>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">服務帳戶金鑰（JSON 內容）</span>
          <textarea
            value={json}
            onChange={(e) => setJson(e.target.value)}
            rows={4}
            autoComplete="off"
            placeholder="貼上服務帳戶金鑰的完整 JSON 內容"
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
          <span className="text-xs text-muted-foreground">留白代表沿用目前這一把，不會被清掉。</span>
        </label>
        {error && <p className="text-sm text-danger">{error}</p>}
        <div>
          <SaveButton saving={saving} label="儲存 GA4 設定" />
        </div>
      </form>
      <TestConnectionButton
        description="按下後會用目前設定實際向 GA4 要一次網站數據，確認連線是否正常。"
        successMessage="連線成功，讀到 GA4 網站數據。"
        errorMessage="連線失敗，請確認服務帳戶金鑰是否正確。"
      />
    </SectionCard>
  );
}
