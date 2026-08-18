import { X } from "lucide-react";
import { SidePanel } from "@/components/layout/SidePanel";
import { WeeklyBattleSection } from "@/components/cockpit/WeeklyBattleSection";

/** 收件匣的提案側板直接重用駕駛艙元件，核可與略過不會長出第二條行為。 */
export function WeeklyProposalsPanel({
  brandId,
  focusProposalId,
  onClose,
}: {
  brandId: string;
  focusProposalId?: string | null;
  onClose: () => void;
}) {
  return (
    <SidePanel ariaLabel="本週提案" onClose={onClose} widthClassName="w-[36rem]">
      <div className="flex items-start justify-between gap-3 border-b border-border pb-4">
        <h2 className="font-display text-lg text-foreground">本週提案</h2>
        <button type="button" onClick={onClose} aria-label="關閉側板" className="rounded-md p-2 text-muted-foreground hover:bg-muted">
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      <WeeklyBattleSection brandId={brandId} focusProposalId={focusProposalId} />
    </SidePanel>
  );
}
