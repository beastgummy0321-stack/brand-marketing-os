import { useState } from "react";
import { FluidCard } from "@/components/layout/FluidCard";
import { StatusLight } from "@/components/layout/StatusLight";
import { confirmTrackingMapping, type TrackingChain, type TrackingChainNodeKey } from "@/lib/warroomApi";

const NODE_CONFIG: { key: TrackingChainNodeKey; label: string; anchor: string }[] = [
  { key: "naming", label: "活動名稱對上", anchor: "naming-utm-block" },
  { key: "mapping", label: "檔期對應", anchor: "handoff-packages" },
  { key: "codes", label: "配碼", anchor: "handoff-codes" },
  { key: "landing_utm", label: "到達頁＋UTM", anchor: "checklist-block" },
];

const STATUS_TEXT = { green: "正常", yellow: "需要確認", red: "需要處理" } as const;

/** R5-1：交接區的主視覺。四節點只保留一句白話與一個可執行動作。 */
export function TrackingChainCard({
  brandId,
  cycleId,
  chain,
  onUpdated,
}: {
  brandId: string;
  cycleId: string;
  chain: TrackingChain;
  onUpdated: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function scrollTo(anchor: string) {
    document.getElementById(anchor)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function confirmMapping() {
    setConfirming(true);
    setError(null);
    try {
      await confirmTrackingMapping(brandId, cycleId);
      onUpdated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "確認對應失敗，請稍後再試。");
    } finally {
      setConfirming(false);
    }
  }

  return (
    <FluidCard
      title="追蹤鏈儀表"
      subtitle="確認 Meta 實際投遞的廣告，能一路追到訂單。"
      hoverable={false}
    >
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {NODE_CONFIG.map(({ key, label, anchor }) => {
          const node = chain[key];
          const isMappingConfirmation = key === "mapping" && node.status === "yellow";
          return (
            <div key={key} className="flex min-h-36 flex-col justify-between gap-3 rounded-xl border border-border bg-muted/20 p-4">
              <StatusLight status={node.status} label={label} statusText={STATUS_TEXT[node.status]} size="sm" />
              <p className="text-sm leading-6 text-foreground">{node.message}</p>
              <button
                type="button"
                disabled={isMappingConfirmation && confirming}
                onClick={() => {
                  if (isMappingConfirmation) void confirmMapping();
                  else scrollTo(anchor);
                }}
                className="self-start rounded-md border border-primary px-3 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isMappingConfirmation ? (confirming ? "確認中…" : "確認對應") : node.action || "查看修復方式"}
              </button>
            </div>
          );
        })}
      </div>
      {error && <p className="mt-3 text-sm text-danger">{error}</p>}
    </FluidCard>
  );
}
