import { useState } from "react";
import { Button } from "@/components/layout/ui/button";
import type { ChangeItem } from "@/lib/adsChangeApi";

/** 「↗ 打開平台」：有 `platform_url` 就在新分頁開啟；沒有（今天還沒有這個能力，或缺識別欄位）
 * 就换成標的名稱＋原生編號＋「複製編號」（feature Decisions「Agent choice — ↗ 打開平台」）。
 * 兩種情況都會回報 `onOpen`——這一步「打開平台」在畫面上算不算做完，退回複製編號版一樣算。
 * F27-I15：原本是 `HandoffPage.tsx` 自己的一顆，`CleanupHandoffSections.tsx` 一則廣告一顆也要用
 * 同一顆按鈕，搬成獨立檔案讓兩邊 import 同一份，不重刻。 */
export function PlatformButton({ platformUrl, target, onOpen }: {
  platformUrl: string | null; target: ChangeItem["target"]; onOpen: () => void;
}) {
  const [copied, setCopied] = useState(false);
  if (platformUrl) {
    return (
      <Button variant="outline" asChild>
        <a href={platformUrl} target="_blank" rel="noreferrer" onClick={onOpen}>↗ 打開平台</a>
      </Button>
    );
  }
  async function copyId() {
    try { await navigator.clipboard.writeText(target.native_id); } catch { /* 沒有剪貼簿權限也不擋操作 */ }
    setCopied(true);
    onOpen();
  }
  return (
    <div className="flex flex-col items-end gap-1 text-right text-xs text-muted-foreground">
      <span className="max-w-[10rem] truncate" title={target.name ?? undefined}>{target.name ?? "（未命名）"}</span>
      <span className="numeric">{target.native_id}</span>
      <Button variant="outline" size="sm" onClick={() => void copyId()}>{copied ? "已複製" : "複製編號"}</Button>
    </div>
  );
}
