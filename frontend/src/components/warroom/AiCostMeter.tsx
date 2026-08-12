import { useEffect, useState } from "react";
import { fetchAiCostMeter, type AiCostMeter as AiCostMeterData } from "@/lib/warroomApi";

/** 右欄常駐儀表（契約「任務流版型」節）：跟 B3 建檔精靈同一份品牌層 AI 花費數字，不是
 * 「廣告花費」——這期廣告預算／已花費留在中央對應步驟顯示，避免使用者把兩種花費看成
 * 同一個數字（契約原文）。這裡沒有「調整上限」side panel——廣告分支一律用全站設定頁那
 * 一顆全域上限，只提供連結，不重造一份覆寫機制。 */
export function AiCostMeter({ brandId }: { brandId: string }) {
  const [data, setData] = useState<AiCostMeterData | null>(null);

  useEffect(() => {
    fetchAiCostMeter(brandId)
      .then(setData)
      .catch(() => setData(null));
  }, [brandId]);

  if (!data) {
    return <div className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground shadow-[var(--shadow-card)]">花費儀表讀取中…</div>;
  }

  const pct = data.limit > 0 ? Math.min(100, (data.spent / data.limit) * 100) : 0;
  const over = data.spent > data.limit;

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4 shadow-[var(--shadow-card)]">
      <p className="text-sm font-medium text-foreground">這個品牌的 AI 生成花費</p>
      <p className="text-lg font-semibold text-foreground">
        US$ {data.spent.toFixed(2)}
        <span className="ml-1 text-sm font-normal text-muted-foreground">／ US$ {data.limit.toFixed(2)} 上限</span>
      </p>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div className={`h-full rounded-full ${over ? "bg-danger" : "bg-primary"}`} style={{ width: `${pct}%` }} />
      </div>
      {over && <p className="text-xs text-danger">這個品牌本期 AI 生成花費已經超過全站上限，新的生成動作可能會被擋下。</p>}
      <a href={data.settings_url} className="self-start text-xs font-medium text-primary hover:underline">
        去設定頁調整
      </a>
    </div>
  );
}
