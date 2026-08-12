import { useEffect, useState } from "react";
import { fetchReadiness, type Cycle, type ReadinessRing as ReadinessRingData } from "@/lib/warroomApi";
import { ReadinessRingCard } from "../shared/ReadinessRingCard";
import { CheckpointSection } from "./CheckpointSection";
import { ChecklistSection } from "./handoff/ChecklistSection";
import { NamingUtmSection } from "./handoff/NamingUtmSection";
import { PackagesSection } from "./handoff/PackagesSection";
import { QaAutoCheckSection } from "./handoff/QaAutoCheckSection";

/** 交接（S8R.13-19 重設計，吸收舊 `S8.25-46` 交接包＋投放前檢查＋`S8.47-50` 期中檢查點三個
 * 舊階段條格位，見 GRILL-B4R-performance.md 分組對照表 199-207 行）：最上方一顆總分環
 * （S8R.13-15）取代散落各區塊自行判讀過不過，展開明細＋逐項「去處理」錨點捲動；底下沿用
 * 既有四個子區塊逐字不變，只是不再各自顯示完成度徽章當唯一判讀依據。期中檢查點維持在本
 * 區塊內（S8R.19，位置不變），只有真的在投放（LIVE 之後）才有意義。 */
export function HandoffStep({ brandId, cycle }: { brandId: string; cycle: Cycle }) {
  const [ring, setRing] = useState<ReadinessRingData | null>(null);

  useEffect(() => {
    fetchReadiness(brandId, cycle.id).then(setRing);
  }, [brandId, cycle.id]);

  return (
    <div className="flex flex-col gap-4">
      {ring && <ReadinessRingCard ring={ring} />}
      <ChecklistSection brandId={brandId} cycleId={cycle.id} />
      <NamingUtmSection brandId={brandId} cycleId={cycle.id} />
      <QaAutoCheckSection brandId={brandId} cycleId={cycle.id} />
      <PackagesSection brandId={brandId} cycleId={cycle.id} />
      {(cycle.status === "LIVE" || cycle.status === "EVALUATING") && <CheckpointSection brandId={brandId} cycleId={cycle.id} />}
    </div>
  );
}
