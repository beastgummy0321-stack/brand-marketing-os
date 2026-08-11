import { useState } from "react";

/** 表單送出的共用狀態機（票 B1-settings）：設定頁 10 個表單（Meta／GA4／AI 金鑰／清除
 * 金鑰／模型／素材資料夾／提示詞開頭／花費上限／規則卡儲存／規則卡重設）都是同一套
 * 「送出中鎖按鈕、失敗人話錯誤、保留輸入內容」（五鐵則④），抽成一個 hook 避免十處各刻
 * 一份 saving／error state。輸入內容本來就是受控欄位、失敗不清空，不用額外處理。 */
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
