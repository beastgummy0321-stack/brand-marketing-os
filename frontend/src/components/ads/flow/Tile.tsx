import { useEffect, useState, type ReactNode } from "react";
import { Image as ImageIcon } from "lucide-react";

/** 廣告／投放組縮圖：`null`、還沒讀到或載入失敗都落到同一顆中性佔位圖示，不是空白或破圖示
 * （同 `detail/CampaignDetailPage.tsx` 的 `AdThumb` 慣例；那支沒有 export，這裡原本是
 * `ConfirmPage.tsx` 自己的一份小工具，不是重刻 kit 零件）。F27-I15：`new_ad`／`cleanup` 兩批新
 * 卡片（`NewAdEvidence.tsx`／`CleanupEvidence.tsx`）跟既有 `ConfirmPage.tsx` 三種證據卡共用同一顆
 * ——都在 `flow/` 這個功能資料夾內，搬成獨立檔案讓三邊 import 同一份，不三次複製貼上。 */
export function Tile({ url, icon, size = "lg" }: { url?: string | null; icon?: ReactNode; size?: "lg" | "sm" }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [url]);
  const showImage = !!url && !failed;
  const dim = size === "sm" ? "size-8" : "size-16";
  return (
    <div className={`flex ${dim} shrink-0 items-center justify-center overflow-hidden rounded-xl bg-muted`} aria-hidden="true">
      {showImage ? (
        // eslint-disable-next-line @next/next/no-img-element -- 這裡不是 Next.js 專案。
        <img src={url ?? undefined} alt="" className="size-full object-cover" onError={() => setFailed(true)} />
      ) : (
        icon ?? <ImageIcon className={size === "sm" ? "size-4 text-muted-foreground" : "size-6 text-muted-foreground"} />
      )}
    </div>
  );
}
