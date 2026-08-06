import type { CampaignStage } from "@/lib/api";

/** 進行中檔期目前處於遠期備戰／中期備戰／近期備戰哪個階段（票 06-campaign-calendar）：
 * 越接近檔期當天顏色越急迫（遠期備戰→中期備戰→近期備戰，同異常警示區「越急迫越搶眼」
 * 的配色邏輯）。沒有檔期在提前期窗口內（`stage` 為 null）不渲染任何東西。 */
const STAGE_CLASS: Record<CampaignStage["stage"], string> = {
  遠期備戰: "border-primary/30 bg-primary/10 text-primary",
  中期備戰: "border-warning/30 bg-warning/10 text-warning",
  近期備戰: "border-danger/30 bg-danger/10 text-danger",
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
