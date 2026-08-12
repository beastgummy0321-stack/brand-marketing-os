import { useEffect, useState } from "react";
import { fetchCheckpoint, type CheckpointResult } from "@/lib/warroomApi";
import { Badge } from "../shared/Badge";

const KIND_LABELS = { day3: "第 3 天健康檢查", day7: "第 7 天健康檢查" } as const;

/** 期中檢查點（S8R.19，吸收 `ads_checkpoint.html`）：位置維持在「交接」區塊內（沿用舊分組，
 * GRILL-B4R-performance.md 交接區條文表），由 `HandoffStep` 掛載——只有真的在投放
 * （LIVE 之後）健康檢查才有意義，不判勝負，只看學習期正不正常、錢有沒有在花。 */
export function CheckpointSection({ brandId, cycleId }: { brandId: string; cycleId: string }) {
  const [day3, setDay3] = useState<CheckpointResult | null>(null);
  const [day7, setDay7] = useState<CheckpointResult | null>(null);

  useEffect(() => {
    fetchCheckpoint(brandId, cycleId, "day3").then(setDay3);
    fetchCheckpoint(brandId, cycleId, "day7").then(setDay7);
  }, [brandId, cycleId]);

  return (
    <div className="flex flex-col gap-3">
      {([day3, day7] as const).map((cp, i) => {
        const kind = i === 0 ? "day3" : "day7";
        if (!cp) return null;
        return (
          <div key={kind} className="rounded-lg border border-border bg-card p-4 shadow-[var(--shadow-card)]">
            <p className="font-medium text-foreground">{KIND_LABELS[kind]}</p>
            {!cp.data_sufficient ? (
              <p className="mt-1 text-sm text-muted-foreground">資料還不夠，晚點再看。</p>
            ) : (
              <div className="mt-1 flex flex-wrap items-center gap-2 text-sm">
                <Badge tone={cp.spend_ok ? "success" : "warning"}>{cp.spend_ok ? "錢有在花" : "花費異常"}</Badge>
                <Badge tone={cp.learning_normal ? "success" : "warning"}>{cp.learning_normal ? "學習期正常" : "學習期異常"}</Badge>
                {cp.reach && <span className="text-muted-foreground">觸及 {cp.reach.reach?.toLocaleString("zh-TW")}</span>}
                {cp.fatigue && (
                  <Badge tone={cp.fatigue.status === "warn" ? "warning" : "success"}>
                    頻率 {cp.fatigue.frequency}・{cp.fatigue.status_label}
                  </Badge>
                )}
              </div>
            )}
            <p className="mt-1 text-xs text-muted-foreground">{cp.learning_note}</p>
          </div>
        );
      })}
    </div>
  );
}
