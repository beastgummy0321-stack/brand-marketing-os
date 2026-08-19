import { useCallback, useEffect, useState } from "react";
import { fetchTrackingChain, type Cycle, type TrackingChain } from "@/lib/warroomApi";
import { TrackingChainCard } from "../shared/TrackingChainCard";
import { CheckpointSection } from "./CheckpointSection";
import { ChecklistSection } from "./handoff/ChecklistSection";
import { PackagesSection } from "./handoff/PackagesSection";
import { DeliverySection } from "./DeliverySection";

/** 交接（S8R.13-19 重設計，吸收舊 `S8.25-46` 交接包＋投放前檢查＋`S8.47-50` 期中檢查點三個
 * 舊階段條格位，見 GRILL-B4R-performance.md 分組對照表 199-207 行）：最上方追蹤鏈儀表
 * （R5-1）取代總分環成為主視覺；檢查清單收合成一行，側板保留 9 項逐項勾選。期中檢查點維持在本
 * 區塊內（S8R.19，位置不變），只有真的在投放（LIVE 之後）才有意義。 */
export function HandoffStep({ brandId, cycle }: { brandId: string; cycle: Cycle }) {
  const [trackingChain, setTrackingChain] = useState<TrackingChain | null>(null);

  const loadTrackingChain = useCallback(() => {
    fetchTrackingChain(brandId, cycle.id).then(setTrackingChain);
  }, [brandId, cycle.id]);

  useEffect(() => {
    loadTrackingChain();
  }, [loadTrackingChain]);

  return (
    <div className="flex flex-col gap-4">
      <DeliverySection brandId={brandId} cycleId={cycle.id} />
      {trackingChain && (
        <TrackingChainCard brandId={brandId} cycleId={cycle.id} chain={trackingChain} onUpdated={loadTrackingChain} />
      )}
      <ChecklistSection brandId={brandId} cycleId={cycle.id} />
      <PackagesSection brandId={brandId} cycleId={cycle.id} />
      {(cycle.status === "LIVE" || cycle.status === "EVALUATING") && <CheckpointSection brandId={brandId} cycleId={cycle.id} />}
    </div>
  );
}
