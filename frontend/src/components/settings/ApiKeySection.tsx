import { useState } from "react";
import type { SettingsData } from "@/lib/settingsApi";
import { clearApiKey, saveAiMonthlyCostLimit, saveApiKey } from "@/lib/settingsApi";
import { SectionCard } from "./shared/SectionCard";
import { SaveButton } from "./shared/SaveButton";
import { TestConnectionButton } from "./shared/TestConnectionButton";
import { useFormSubmit } from "@/lib/useFormSubmit";

const CLEAR_CONFIRM_TEXT =
  "確定要刪除資料庫裡的金鑰？這個動作無法復原。刪除後如果沒有設定環境變數，AI 功能會顯示尚未設定金鑰。";

/** AI 金鑰小節（S15.13–S15.18）。三版文案、清除金鑰二次確認文案沿用既有
 * `app/templates/settings.html:96-157`。 */
export function ApiKeySection({ data, onSaved }: { data: SettingsData; onSaved: () => void }) {
  const [apiKey, setApiKey] = useState("");
  const saveForm = useFormSubmit(async () => {
    await saveApiKey(apiKey);
    setApiKey("");
    onSaved();
  });
  const clearForm = useFormSubmit(async () => {
    await clearApiKey();
    onSaved();
  });

  const [monthlyCap, setMonthlyCap] = useState(String(data.ai_monthly_cost_limit));
  const capForm = useFormSubmit(async () => {
    await saveAiMonthlyCostLimit(Number(monthlyCap));
    onSaved();
  });

  function handleClear() {
    if (window.confirm(CLEAR_CONFIRM_TEXT)) {
      void clearForm.submit();
    }
  }

  const keyForm = (
    <form
      className="flex flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        void saveForm.submit();
      }}
    >
      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-foreground">
          {data.db_key_present ? "新的 AI 金鑰" : "AI 金鑰（存進資料庫）"}
        </span>
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder="貼上以 sk-ant- 開頭的金鑰"
          autoComplete="off"
          className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
        />
        <span className="text-xs text-muted-foreground">
          {data.db_key_present
            ? "貼上後按「儲存金鑰」就會換成新的一把，存進資料庫；舊金鑰不會保留。"
            : "到 Anthropic 網站的帳戶頁面可以產生金鑰，整串複製過來貼上即可。若已設好環境變數，可以不用填這裡。"}
        </span>
      </label>
      {saveForm.error && <p className="text-sm text-danger">{saveForm.error}</p>}
      <div>
        <SaveButton saving={saveForm.saving} label="儲存金鑰" />
      </div>
    </form>
  );

  return (
    <SectionCard
      title="AI 金鑰"
      description="建檔精靈等 AI 功能需要一把 Anthropic 的金鑰才能運作。系統優先採用環境變數裡的金鑰；沒有設環境變數時才會用這頁存進資料庫的金鑰（加密存放在保管庫，不是明文）。"
    >
      {data.api_key_source === "env" && (
        <p className="text-sm text-foreground">
          目前使用中的金鑰來自<strong>環境變數</strong>{" "}
          <code className="rounded bg-muted px-1">ANTHROPIC_API_KEY</code>：
          <span className="font-mono">{data.masked_key}</span>（安全，不會進資料庫或備份）
        </p>
      )}
      {data.api_key_source === "db" && (
        <div className="rounded-md border border-border bg-muted/40 p-3 text-sm">
          <p className="font-medium text-foreground">目前使用中的金鑰來自資料庫（加密保管）</p>
          <p className="mt-1 text-muted-foreground">
            目前用的是這頁存進資料庫的金鑰：<span className="font-mono">{data.masked_key}</span>
            。金鑰本身加密存放在系統的保管庫（Vault），不是明文，備份帶出去的也不是原文。
            也可以改用下面「改用環境變數」的做法。
          </p>
        </div>
      )}
      {data.api_key_source === null && (
        <p className="text-sm text-danger">目前尚未設定任何 AI 金鑰，AI 功能無法使用。</p>
      )}

      <div className="rounded-md border border-border p-3 text-sm">
        <p className="font-medium text-foreground">
          {data.ai_key_source === "own" ? "這個組織用自己的金鑰付費" : "AI 費用目前由平台付費"}
        </p>
        <p className="mt-1 text-muted-foreground">
          這個月整個組織（不分品牌）已花 US$ {data.ai_monthly_spend.toFixed(2)}，上限 US${" "}
          {data.ai_monthly_cost_limit.toFixed(2)}
          {data.ai_cap_applies
            ? "。用到上限會自動擋下新的 AI 呼叫，下個月 1 號自動歸零；跟下面「花費上限」小節的品牌花費上限是不同的兩道關卡，那個只管單一品牌、不會每月重置。"
            : "（僅供參考：這個組織用自己的金鑰付費，不受這道上限限制）。"}
        </p>
        {data.ai_cap_applies && data.is_owner && (
          <form
            className="mt-3 flex flex-col gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              void capForm.submit();
            }}
          >
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-foreground">AI 月費上限（整個組織）</span>
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground">US$</span>
                <input
                  type="number"
                  step={1}
                  min={0}
                  value={monthlyCap}
                  onChange={(e) => setMonthlyCap(e.target.value)}
                  className="w-32 rounded-md border border-border px-3 py-2 text-sm text-foreground"
                />
              </div>
            </label>
            {capForm.error && <p className="text-sm text-danger">{capForm.error}</p>}
            <div>
              <SaveButton saving={capForm.saving} label="儲存月費上限" />
            </div>
          </form>
        )}
        {data.ai_cap_applies && !data.is_owner && (
          <p className="mt-2 text-xs text-muted-foreground">只有組織的擁有者可以調整這個上限。</p>
        )}
      </div>

      <details className="rounded-md border border-border p-3 text-sm">
        <summary className="cursor-pointer font-medium text-foreground">
          改用環境變數（更安全，不進資料庫）
        </summary>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-muted-foreground">
          <li>
            用記事本打開專案資料夾裡的 <code className="rounded bg-muted px-1">啟動行銷系統.bat</code>。
          </li>
          <li>
            找到寫著 <code className="rounded bg-muted px-1">rem set ANTHROPIC_API_KEY=</code>{" "}
            的那一行，刪掉最前面的 <code className="rounded bg-muted px-1">rem </code>
            ，等號後面貼上你的金鑰。
          </li>
          <li>存檔，關掉目前開著的伺服器視窗，再重新用「啟動行銷系統.bat」開啟一次。</li>
          <li>回到這頁重新整理：上面會改成顯示「目前使用中的金鑰來自環境變數」。</li>
        </ol>
      </details>

      {data.db_key_present ? (
        <details className="rounded-md border border-border p-3">
          <summary className="cursor-pointer text-sm font-medium text-foreground">
            更換資料庫裡的金鑰
          </summary>
          <div className="mt-3">{keyForm}</div>
        </details>
      ) : (
        keyForm
      )}

      {data.db_key_present && (
        <div className="flex flex-col gap-2 border-t border-border pt-4">
          <p className="text-sm text-muted-foreground">
            清除資料庫裡存的金鑰（不影響環境變數）。這是不可逆動作，請先確認已照上面步驟設好
            環境變數再按下去。
          </p>
          {clearForm.error && <p className="text-sm text-danger">{clearForm.error}</p>}
          <div>
            <button
              type="button"
              onClick={handleClear}
              disabled={clearForm.saving}
              className="rounded-md border border-danger px-4 py-2 text-sm font-medium text-danger hover:bg-danger/10 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {clearForm.saving ? "處理中…" : "清除資料庫裡的金鑰"}
            </button>
          </div>
        </div>
      )}

      <TestConnectionButton
        description="按下後會用目前的金鑰與模型，向 AI 服務發出一次極小的真實請求，回報金鑰是否可用。會微量扣款（約不到台幣一角）。"
        successMessage="連線成功，金鑰可用。"
        errorMessage="連線失敗，請確認金鑰是否正確。"
      />
    </SectionCard>
  );
}
