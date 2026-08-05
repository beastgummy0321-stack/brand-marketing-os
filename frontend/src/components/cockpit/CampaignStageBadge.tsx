import type { CampaignStage } from "@/lib/api";

/** 進行中檔期目前處於預熱／高潮／衝刺哪個階段（票 06-campaign-calendar）：越接近
 * 檔期當天顏色越急迫（預熱→高潮→衝刺，同異常警示區「越急迫越搶眼」的配色邏輯）。
 * 沒有檔期在提前期窗口內（`stage` 為 null）不渲染任何東西。 */
const STAGE_CLASS: Record<CampaignStage["stage"], string> = {
  預熱: "border-primary/30 bg-primary/10 text-primary",
  高潮: "border-warning/30 bg-warning/10 text-warning",
  衝刺: "border-danger/30 bg-danger/10 text-danger",
};

export function CampaignStageBadge({ stage }: { stage: CampaignStage | null }) {
  if (!stage) return null;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium ${STAGE_CLASS[stage.stage]}`}
    >
      {stage.name}・{stage.tier_label}・{stage.stage}
    </span>
  );
}
