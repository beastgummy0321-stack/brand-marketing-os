import type { Cycle } from "@/lib/warroomApi";
import { ChecklistSection } from "./handoff/ChecklistSection";
import { NamingUtmSection } from "./handoff/NamingUtmSection";
import { PackagesSection } from "./handoff/PackagesSection";
import { QaAutoCheckSection } from "./handoff/QaAutoCheckSection";

/** 交接（S8.25-46，吸收 `ads_checklist.html`＋`ads_handoff.html`）：契約把「交接包」與
 * 「投放前檢查」兩個階段條格位的內容合成同一段落敘述（S8.25 起「交接（第四步…)」標題涵蓋
 * 兩者），本票沿用契約分節方式，中央用同一顆元件呈現，不是漏做——階段條仍各自顯示 7 格
 * （契約「拿不準的點」第 4 點：卡片分組方式留原型驗收時再拍板）。 */
export function HandoffStep({ brandId, cycle }: { brandId: string; cycle: Cycle }) {
  return (
    <div className="flex flex-col gap-4">
      <ChecklistSection brandId={brandId} cycleId={cycle.id} />
      <NamingUtmSection brandId={brandId} cycleId={cycle.id} />
      <QaAutoCheckSection brandId={brandId} cycleId={cycle.id} />
      <PackagesSection brandId={brandId} cycleId={cycle.id} />
    </div>
  );
}
