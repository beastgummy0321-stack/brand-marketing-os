import { useState } from "react";

/** 表單送出的共用狀態機（原票 B1-settings 抽出，票 B2-library 起搬到 `lib/` 給多個
 * feature 共用——本專案模組化規則「跨 feature 只准 import components/layout/ 與 lib/」，
 * 這顆是純邏輯 hook 沒有畫面，天生就該放 lib/ 不是某個 feature 底下）。「送出中鎖按鈕、
 * 失敗人話錯誤、保留輸入內容」（五鐵則④）是全站表單共用的行為，不用每個 feature 各刻
 * 一份。輸入內容本來就是受控欄位、失敗不清空，不用額外處理。 */
export function useFormSubmit<Args extends unknown[]>(
  action: (...args: Args) => Promise<void>,
) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(...args: Args) {
    setSaving(true);
    setError(null);
    try {
      await action(...args);
    } catch (err) {
      setError(err instanceof Error ? err.message : "儲存失敗，請稍後再試。");
    } finally {
      setSaving(false);
    }
  }

  return { saving, error, submit };
}
