import { useState } from "react";
import type { SettingsData } from "@/lib/settingsApi";
import { saveMeta } from "@/lib/settingsApi";
import { SectionCard } from "./shared/SectionCard";
import { SaveButton } from "./shared/SaveButton";
import { TestConnectionButton } from "./shared/TestConnectionButton";
import { useFormSubmit } from "@/lib/useFormSubmit";

/** Meta 廣告帳號小節（S15.1–S15.6）。文案沿用既有 `app/templates/settings.html:19-56`。 */
export function MetaSection({ data, onSaved }: { data: SettingsData; onSaved: () => void }) {
  const [accountId, setAccountId] = useState(data.meta_account_id);
  const [token, setToken] = useState("");
  const { saving, error, submit } = useFormSubmit(async () => {
    await saveMeta(accountId, token);
    setToken("");
    onSaved();
  });

  return (
    <SectionCard
      title="Meta 廣告帳號（唯讀）"
      description={
        <>
          連上之後，廣告成效會自動抓回來，不用手動貼 CSV。這裡只需要唯讀金鑰——
          系統讀得到你的廣告數字，但改不了、也開不了任何廣告。
        </>
      }
    >
      {data.masked_meta_token && (
        <p className="text-sm text-foreground">
          目前已設定連線金鑰：<span className="font-mono">{data.masked_meta_token}</span>
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
          <span className="font-medium text-foreground">廣告帳號編號</span>
          <input
            type="text"
            value={accountId}
            onChange={(e) => setAccountId(e.target.value)}
            placeholder="act_1234567890"
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
          <span className="text-xs text-muted-foreground">
            在廣告管理員的網址列看得到，像 act_1234567890。只填數字也可以。
          </span>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">唯讀連線金鑰</span>
          <input
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="貼上系統用戶的存取權杖"
            autoComplete="off"
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
          <span className="text-xs text-muted-foreground">留白代表沿用目前這一把，不會被清掉。</span>
        </label>
        {error && <p className="text-sm text-danger">{error}</p>}
        <div>
          <SaveButton saving={saving} label="儲存 Meta 設定" />
        </div>
      </form>
      <TestConnectionButton
        description="按下後會用目前設定實際向 Meta 要一次廣告帳號的資料，確認連線是否正常。"
        successMessage="連線成功，讀到廣告帳號資料。"
        errorMessage="連線失敗，請確認金鑰與帳號編號是否正確。"
      />
    </SectionCard>
  );
}
